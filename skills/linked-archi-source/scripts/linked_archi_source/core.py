"""Strict values, RDF validation, immutable cache, and source manifests."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence

from .errors import SourceError

DEFAULT_CACHE = Path("~/.cache/linked-archi/sources")
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_TIMEOUT_MS = 30_000
PENDING_TTL_SECONDS = 24 * 60 * 60
MAX_PENDING_REAP = 32
MAX_MANIFEST_BYTES = 1024 * 1024

# Public format name -> (canonical extension, pyoxigraph RdfFormat member).
FORMATS: dict[str, tuple[str, str]] = {
    "trig": (".trig", "TRIG"),
    "turtle": (".ttl", "TURTLE"),
    "n-triples": (".nt", "N_TRIPLES"),
    "n-quads": (".nq", "N_QUADS"),
    "rdf-xml": (".rdf", "RDF_XML"),
    "json-ld": (".jsonld", "JSON_LD"),
    "n3": (".n3", "N3"),
}
EXTENSIONS: dict[str, str] = {
    ".trig": "trig",
    ".ttl": "turtle",
    ".turtle": "turtle",
    ".nt": "n-triples",
    ".nq": "n-quads",
    ".rdf": "rdf-xml",
    ".xml": "rdf-xml",
    ".jsonld": "json-ld",
    ".json": "json-ld",
    ".n3": "n3",
}
MEDIA_TYPES: dict[str, str] = {
    "application/trig": "trig",
    "text/turtle": "turtle",
    "application/n-triples": "n-triples",
    "application/n-quads": "n-quads",
    "application/rdf+xml": "rdf-xml",
    "application/ld+json": "json-ld",
    "text/n3": "n3",
}
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
_GIT_COMMIT = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_PENDING_FIELDS = {
    "schema_version",
    "request_id",
    "created_epoch",
    "staging_name",
    "kind",
    "project_id",
    "revision",
    "path",
    "format",
    "expected_sha256",
    "server_id",
    "request_key",
    "policy",
    "signature",
}


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceError(f"{label} must be an object")
    return value


def reject_unknown(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise SourceError(f"{label} contains unknown fields: {', '.join(sorted(unknown))}")


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceError(f"{label} must be a non-empty string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SourceError(f"{label} contains control characters")
    return value.strip()


def optional_digest(value: Any, label: str = "expected_sha256") -> str | None:
    if value is None:
        return None
    digest = require_text(value, label).lower()
    if not _DIGEST.fullmatch(digest):
        raise SourceError(f"{label} must be exactly 64 hexadecimal characters")
    return digest


def require_digest(value: Any, label: str = "expected_sha256") -> str:
    digest = optional_digest(value, label)
    if digest is None:
        raise SourceError(f"{label} is required")
    return digest


def require_commit(value: Any, label: str = "commit") -> str:
    commit = require_text(value, label).lower()
    if not _GIT_COMMIT.fullmatch(commit):
        raise SourceError(f"{label} must be a full 40- or 64-character Git commit ID")
    return commit


def is_full_commit(value: str) -> bool:
    return bool(_GIT_COMMIT.fullmatch(value))


def positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise SourceError(f"{label} must be a positive integer")
    return value


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_format(explicit: Any, name: str, content_type: str | None = None) -> str:
    if explicit is not None:
        candidate = require_text(explicit, "format").lower()
        aliases = {
            "ttl": "turtle",
            "nt": "n-triples",
            "ntriples": "n-triples",
            "nq": "n-quads",
            "nquads": "n-quads",
            "rdfxml": "rdf-xml",
            "xml": "rdf-xml",
            "jsonld": "json-ld",
        }
        candidate = aliases.get(candidate, candidate)
        if candidate not in FORMATS:
            raise SourceError(
                f"unsupported RDF format {explicit!r}; choose " + ", ".join(FORMATS)
            )
        return candidate

    suffix = Path(name).suffix.lower()
    if suffix in EXTENSIONS:
        return EXTENSIONS[suffix]
    if content_type:
        media_type = content_type.partition(";")[0].strip().lower()
        if media_type in MEDIA_TYPES:
            return MEDIA_TYPES[media_type]
    raise SourceError(f"cannot determine RDF format for {name!r}; pass --format explicitly")


def validate_repository_path(value: Any) -> str:
    text = require_text(value, "repository path")
    if "\\" in text:
        raise SourceError(f"repository path must use forward slashes: {text}")
    path = Path(text)
    if (
        path.is_absolute()
        or text.startswith("/")
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        raise SourceError(f"repository path must be a normalized relative path: {text}")
    return text


def _open_regular(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SourceError(f"file is not a safe regular file: {path}: {exc}") from exc
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode):
        os.close(descriptor)
        raise SourceError(f"file is not a regular file: {path}")
    return descriptor


def _sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        block = os.read(descriptor, 1024 * 1024)
        if not block:
            break
        digest.update(block)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    descriptor = _open_regular(path)
    try:
        return _sha256_fd(descriptor)
    finally:
        os.close(descriptor)


def _validate_rdf_stream(handle: BinaryIO, rdf_format: str, *, lenient: bool) -> int:
    try:
        from pyoxigraph import RdfFormat, Store
    except ModuleNotFoundError as exc:  # pragma: no cover - environment failure
        raise SourceError("RDF verification needs pyoxigraph: pip install pyoxigraph") from exc

    store = Store()
    try:
        store.bulk_load(handle, getattr(RdfFormat, FORMATS[rdf_format][1]), lenient=lenient)
    except (OSError, SyntaxError, ValueError) as exc:
        raise SourceError(f"downloaded content is not valid {rdf_format}: {exc}") from exc
    return len(store)


def _validate_rdf_fd(descriptor: int, rdf_format: str, *, lenient: bool) -> int:
    os.lseek(descriptor, 0, os.SEEK_SET)
    try:
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            return _validate_rdf_stream(handle, rdf_format, lenient=lenient)
    finally:
        os.lseek(descriptor, 0, os.SEEK_SET)


def _validate_rdf(path: Path, rdf_format: str, *, lenient: bool) -> int:
    descriptor = _open_regular(path)
    try:
        return _validate_rdf_fd(descriptor, rdf_format, lenient=lenient)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class Policy:
    """Acquisition policy after strict wire validation."""

    cache_dir: Path
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_bytes: int = DEFAULT_MAX_BYTES
    allowed_hosts: tuple[str, ...] = ()
    allow_private_network: bool = False
    allow_ssh: bool = False
    offline: bool = False
    lenient: bool = False

    @classmethod
    def from_mapping(cls, raw: Any) -> "Policy":
        value = {} if raw is None else require_object(raw, "policy")
        reject_unknown(
            value,
            {
                "cache_dir",
                "timeout_ms",
                "max_bytes",
                "allowed_hosts",
                "allow_private_network",
                "allow_ssh",
                "offline",
                "lenient",
            },
            "policy",
        )
        if "cache_dir" in value:
            configured_cache = value["cache_dir"]
            if not isinstance(configured_cache, str) or not configured_cache.strip():
                raise SourceError("policy cache_dir must be a non-empty string")
        else:
            configured_cache = os.environ.get("LINKED_ARCHI_SOURCE_CACHE", str(DEFAULT_CACHE))
        hosts = value.get("allowed_hosts", [])
        if not isinstance(hosts, list) or any(
            not isinstance(host, str) or not host.strip() for host in hosts
        ):
            raise SourceError("policy allowed_hosts must be a string array")
        normalized_hosts = tuple(sorted({host.strip().lower().rstrip(".") for host in hosts}))
        for key in ("allow_private_network", "allow_ssh", "offline", "lenient"):
            if key in value and not isinstance(value[key], bool):
                raise SourceError(f"policy {key} must be a boolean")
        return cls(
            cache_dir=Path(configured_cache).expanduser().resolve(strict=False),
            timeout_ms=positive_integer(
                value.get("timeout_ms", DEFAULT_TIMEOUT_MS), "policy timeout_ms"
            ),
            max_bytes=positive_integer(
                value.get("max_bytes", DEFAULT_MAX_BYTES), "policy max_bytes"
            ),
            allowed_hosts=normalized_hosts,
            allow_private_network=value.get("allow_private_network", False),
            allow_ssh=value.get("allow_ssh", False),
            offline=value.get("offline", False),
            lenient=value.get("lenient", False),
        )

    def public_contract(self) -> dict[str, Any]:
        return {
            "cache_dir": str(self.cache_dir),
            "timeout_ms": self.timeout_ms,
            "max_bytes": self.max_bytes,
            "allowed_hosts": list(self.allowed_hosts),
            "allow_private_network": self.allow_private_network,
            "allow_ssh": self.allow_ssh,
            "offline": self.offline,
            "lenient": self.lenient,
        }


class SourceCache:
    """Content-addressed artifacts plus source-owned manifests and pending requests."""

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.root = policy.cache_dir
        self.artifacts = self.root / "sha256"
        self.manifests = self.root / "manifests"
        self.pending = self.root / "pending"
        self.staging = self.root / "staging"
        self.temporary_dir = self.root / "tmp"
        self.request_secret = self.root / ".pending-hmac-key"
        for directory in (
            self.root,
            self.artifacts,
            self.manifests,
            self.pending,
            self.staging,
            self.temporary_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            details = directory.lstat()
            if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
                raise SourceError(f"source cache directory is not safe: {directory}")
            if hasattr(os, "getuid") and details.st_uid != os.getuid():
                raise SourceError(f"source cache directory has an unexpected owner: {directory}")
            if details.st_mode & 0o022:
                raise SourceError(f"source cache directory is group/world writable: {directory}")
            os.chmod(directory, 0o700, follow_symlinks=False)

    def temporary_path(self, suffix: str = "") -> Path:
        handle = tempfile.NamedTemporaryFile(
            prefix="acquire-", suffix=suffix, dir=self.temporary_dir, delete=False
        )
        handle.close()
        path = Path(handle.name)
        path.chmod(0o600)
        return path

    def discard(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def materialize(
        self,
        source_path: Path,
        rdf_format: str,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        if rdf_format not in FORMATS:
            raise SourceError(f"unsupported RDF format: {rdf_format}")
        descriptor = _open_regular(source_path)
        try:
            details = os.fstat(descriptor)
            size = details.st_size
            if size > self.policy.max_bytes:
                raise SourceError(
                    f"artifact is {size} bytes, above max_bytes={self.policy.max_bytes}"
                )
            digest = _sha256_fd(descriptor)
            if expected_sha256 is not None and digest != expected_sha256:
                raise SourceError(
                    f"SHA-256 mismatch: expected {expected_sha256}, received {digest}"
                )
            quads = _validate_rdf_fd(descriptor, rdf_format, lenient=self.policy.lenient)

            extension = FORMATS[rdf_format][0]
            directory = self.artifacts / digest
            directory.mkdir(mode=0o700, exist_ok=True)
            directory_details = directory.lstat()
            if not stat.S_ISDIR(directory_details.st_mode) or stat.S_ISLNK(directory_details.st_mode):
                raise SourceError(f"artifact cache directory is not safe: {directory}")
            destination = directory / f"{digest}{extension}"
            if destination.exists() or destination.is_symlink():
                cached = _open_regular(destination)
                try:
                    if _sha256_fd(cached) != digest:
                        raise SourceError(
                            f"cached artifact failed its content-address check: {destination}"
                        )
                finally:
                    os.close(cached)
            else:
                temporary = directory / f".{digest}.{secrets.token_hex(8)}.tmp"
                output_flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                output = os.open(temporary, output_flags, 0o600)
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    while True:
                        block = os.read(descriptor, 1024 * 1024)
                        if not block:
                            break
                        os.write(output, block)
                    os.fsync(output)
                finally:
                    os.close(output)
                os.replace(temporary, destination)
            return {
                "path": str(destination),
                "format": rdf_format,
                "size_bytes": size,
                "sha256": digest,
                "quads_loaded": quads,
            }
        finally:
            os.close(descriptor)

    def write_manifest(
        self,
        source: Mapping[str, Any],
        artifacts: Sequence[Mapping[str, Any]],
        warnings: Sequence[str] = (),
    ) -> dict[str, Any]:
        stable_artifacts = [self._stable_artifact(artifact) for artifact in artifacts]
        manifest_digest = canonical_digest(
            {
                "manifest_version": 1,
                "source": source,
                "artifacts": stable_artifacts,
            }
        )
        manifest_id = f"sha256:{manifest_digest}"
        manifest_path = self.manifests / f"{manifest_digest}.json"
        manifest = {
            "manifest_version": 1,
            "id": manifest_id,
            "source": dict(source),
            "artifacts": [dict(artifact) for artifact in artifacts],
            "acquired_at": utc_now(),
            "warnings": list(warnings),
        }
        self._atomic_json(manifest_path, manifest)
        return self._ready(manifest, manifest_path, [])

    def find(self, request_key: str) -> dict[str, Any] | None:
        if not _DIGEST.fullmatch(request_key):
            raise SourceError("cache request key is malformed")
        candidates: list[tuple[float, Path]] = []
        try:
            with os.scandir(self.manifests) as entries:
                for entry in entries:
                    if not entry.name.endswith(".json") or entry.is_symlink():
                        continue
                    try:
                        details = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISREG(details.st_mode):
                        candidates.append((details.st_mtime, Path(entry.path)))
        except OSError as exc:
            raise SourceError(f"could not inspect source manifests: {exc}") from exc

        for _modified, path in sorted(candidates, reverse=True):
            try:
                manifest = self._read_json(path)
                validated = self._validate_manifest(path, manifest, request_key)
            except (SourceError, OSError):
                continue
            if validated is not None:
                return self._ready(
                    validated,
                    path,
                    ["offline/cache hit: no remote source was contacted"],
                )
        return None

    def create_pending(self, payload: Mapping[str, Any], suffix: str) -> dict[str, Any]:
        self.reap_pending()
        request_id = secrets.token_urlsafe(24)
        request_dir = self.staging / request_id
        request_dir.mkdir(mode=0o700)
        staging_name = f"artifact{suffix}"
        pending = {
            "schema_version": 1,
            "request_id": request_id,
            "created_epoch": int(time.time()),
            "staging_name": staging_name,
            **dict(payload),
        }
        if set(pending) != _PENDING_FIELDS - {"signature"}:
            raise SourceError("pending source request payload has an invalid schema")
        pending["signature"] = self._pending_signature(pending, create_key=True)
        self._atomic_json(self.pending / f"{request_id}.json", pending)
        return {**pending, "staging_path": str(request_dir / staging_name)}

    def load_pending(self, request_id: Any) -> dict[str, Any]:
        value = require_text(request_id, "request_id")
        if not _REQUEST_ID.fullmatch(value):
            raise SourceError("request_id is malformed")
        path = self.pending / f"{value}.json"
        try:
            pending = self._read_json(path)
        except FileNotFoundError as exc:
            raise SourceError(f"pending source request not found: {value}") from exc
        if set(pending) != _PENDING_FIELDS:
            raise SourceError(f"pending source request has an invalid schema: {value}")
        signature = pending.get("signature")
        if not isinstance(signature, str) or not _DIGEST.fullmatch(signature):
            raise SourceError(f"pending source request has an invalid signature: {value}")
        expected_signature = self._pending_signature(pending, create_key=False)
        if not hmac.compare_digest(signature, expected_signature):
            raise SourceError(f"pending source request authentication failed: {value}")
        if pending.get("schema_version") != 1 or pending.get("request_id") != value:
            raise SourceError(f"pending source request identity is malformed: {value}")
        created = pending.get("created_epoch")
        now = int(time.time())
        if type(created) is not int or created > now + 300:
            raise SourceError(f"pending source request timestamp is malformed: {value}")
        if now - created > PENDING_TTL_SECONDS:
            self.finish_pending(pending)
            raise SourceError(f"pending source request has expired and was removed: {value}")
        if pending.get("kind") != "gitlab-mcp":
            raise SourceError(f"pending source request kind is invalid: {value}")
        project_id = require_text(pending.get("project_id"), "pending project_id")
        if "://" in project_id:
            raise SourceError("pending GitLab project_id must not be a URL")
        require_text(pending.get("revision"), "pending revision")
        selected = validate_repository_path(pending.get("path"))
        rdf_format = normalize_format(pending.get("format"), selected)
        require_digest(pending.get("expected_sha256"), "pending expected_sha256")
        require_text(pending.get("server_id"), "pending server_id")
        request_key = require_text(pending.get("request_key"), "pending request_key")
        if not _DIGEST.fullmatch(request_key):
            raise SourceError("pending request_key is malformed")
        Policy.from_mapping(pending.get("policy"))
        if pending.get("staging_name") != f"artifact{FORMATS[rdf_format][0]}":
            raise SourceError("pending staging filename does not match its RDF format")
        return pending

    def consume_staged(self, pending: Mapping[str, Any]) -> Path:
        request_id = require_text(pending.get("request_id"), "pending request_id")
        staging_name = require_text(pending.get("staging_name"), "pending staging_name")
        if not _REQUEST_ID.fullmatch(request_id) or Path(staging_name).name != staging_name:
            raise SourceError("pending staging locator is malformed")
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        root_fd = request_fd = artifact_fd = None
        trusted = self.temporary_path(FORMATS[str(pending["format"])][0])
        try:
            root_fd = os.open(self.staging, directory_flags)
            request_fd = os.open(request_id, directory_flags, dir_fd=root_fd)
            request_details = os.fstat(request_fd)
            if not stat.S_ISDIR(request_details.st_mode):
                raise SourceError("GitLab MCP staging request is not a directory")
            artifact_fd = os.open(
                staging_name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=request_fd,
            )
            details = os.fstat(artifact_fd)
            if not stat.S_ISREG(details.st_mode):
                raise SourceError("GitLab MCP staged result is not a regular file")
            if details.st_size > self.policy.max_bytes:
                raise SourceError(
                    f"GitLab MCP staged result exceeds max_bytes={self.policy.max_bytes}"
                )
            received = 0
            with trusted.open("wb") as output:
                while True:
                    block = os.read(artifact_fd, min(1024 * 1024, self.policy.max_bytes + 1 - received))
                    if not block:
                        break
                    received += len(block)
                    if received > self.policy.max_bytes:
                        raise SourceError(
                            f"GitLab MCP staged result exceeds max_bytes={self.policy.max_bytes}"
                        )
                    output.write(block)
            return trusted
        except (FileNotFoundError, NotADirectoryError, OSError) as exc:
            self.discard(trusted)
            if isinstance(exc, SourceError):
                raise
            raise SourceError("GitLab MCP result is not safely staged at the requested path") from exc
        except BaseException:
            self.discard(trusted)
            raise
        finally:
            for descriptor in (artifact_fd, request_fd, root_fd):
                if descriptor is not None:
                    os.close(descriptor)

    def finish_pending(self, pending: Mapping[str, Any]) -> None:
        request_id = str(pending["request_id"])
        self._cleanup_request(request_id)

    def reap_pending(self) -> None:
        now = time.time()
        checked = 0
        try:
            entries = list(os.scandir(self.pending))
        except OSError:
            return
        for entry in entries:
            if checked >= MAX_PENDING_REAP:
                break
            checked += 1
            if not entry.name.endswith(".json"):
                continue
            request_id = entry.name[:-5]
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if now - details.st_mtime > PENDING_TTL_SECONDS:
                self._cleanup_request(request_id)

        checked = 0
        try:
            entries = list(os.scandir(self.staging))
        except OSError:
            return
        for entry in entries:
            if checked >= MAX_PENDING_REAP:
                break
            checked += 1
            if not _REQUEST_ID.fullmatch(entry.name):
                continue
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            pending_path = self.pending / f"{entry.name}.json"
            if now - details.st_mtime > PENDING_TTL_SECONDS and not pending_path.exists():
                self._remove_tree(self.staging, entry.name)

    def _validate_manifest(
        self,
        path: Path,
        value: Any,
        request_key: str,
    ) -> dict[str, Any] | None:
        manifest = require_object(value, "source manifest")
        if set(manifest) != {
            "manifest_version",
            "id",
            "source",
            "artifacts",
            "acquired_at",
            "warnings",
        }:
            raise SourceError("source manifest has an invalid schema")
        if manifest.get("manifest_version") != 1:
            raise SourceError("source manifest version is unsupported")
        require_text(manifest.get("acquired_at"), "manifest acquired_at")
        warnings = manifest.get("warnings")
        if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
            raise SourceError("source manifest warnings must be a string array")
        source = self._validate_manifest_source(manifest.get("source"))
        keys = source.get("request_keys", [source["request_key"]])
        if request_key not in keys:
            return None
        raw_artifacts = manifest.get("artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise SourceError("source manifest artifacts must be a non-empty array")
        artifacts = [self._validate_cached_artifact(item) for item in raw_artifacts]
        if source["kind"] in {"url", "gitlab-mcp"} and len(artifacts) != 1:
            raise SourceError("source manifest has an invalid artifact count")
        if source["kind"] == "git" and len(artifacts) != len(source["paths"]):
            raise SourceError("Git manifest path and artifact counts do not match")
        stable = [self._stable_artifact(artifact) for artifact in artifacts]
        digest = canonical_digest(
            {"manifest_version": 1, "source": source, "artifacts": stable}
        )
        if path.name != f"{digest}.json" or manifest.get("id") != f"sha256:{digest}":
            raise SourceError("source manifest identity does not match its stable content")
        return {
            **manifest,
            "source": source,
            "artifacts": artifacts,
        }

    def _validate_manifest_source(self, value: Any) -> dict[str, Any]:
        source = require_object(value, "manifest source")
        kind = source.get("kind")
        schemas = {
            "url": {
                "kind", "request_key", "requested_identity", "resolved_identity",
                "redirect_chain", "expected_sha256", "credential_env", "content_type",
            },
            "git": {
                "kind", "request_key", "request_keys", "requested_identity",
                "resolved_identity", "requested_revision", "resolved_commit", "paths",
            },
            "gitlab-mcp": {
                "kind", "request_key", "request_keys", "requested_identity",
                "mcp_reported_identity", "project_id", "server_id", "requested_revision",
                "mcp_reported_commit", "path", "expected_sha256",
            },
        }
        expected_fields = schemas.get(kind)
        if expected_fields is None or set(source) != expected_fields:
            raise SourceError("manifest source has an invalid provider schema")
        request_key = require_text(source.get("request_key"), "manifest request_key")
        if not _DIGEST.fullmatch(request_key):
            raise SourceError("manifest request_key is malformed")
        require_text(source.get("requested_identity"), "manifest requested_identity")
        if kind == "url":
            require_text(source.get("resolved_identity"), "manifest resolved_identity")
            redirects = source.get("redirect_chain")
            if not isinstance(redirects, list) or any(not isinstance(item, str) for item in redirects):
                raise SourceError("manifest redirect_chain must be a string array")
            optional_digest(source.get("expected_sha256"))
            for key in ("credential_env", "content_type"):
                if source.get(key) is not None:
                    require_text(source.get(key), f"manifest {key}")
        else:
            keys = source.get("request_keys")
            if (
                not isinstance(keys, list)
                or not keys
                or any(not isinstance(key, str) or not _DIGEST.fullmatch(key) for key in keys)
            ):
                raise SourceError("manifest request_keys must contain SHA-256 values")
            if request_key not in keys or keys != sorted(set(keys)):
                raise SourceError("manifest request_keys are not canonical")
            require_text(source.get("requested_revision"), "manifest requested_revision")
            if kind == "git":
                require_text(source.get("resolved_identity"), "manifest resolved_identity")
                require_commit(source.get("resolved_commit"), "manifest resolved_commit")
                paths = source.get("paths")
                if not isinstance(paths, list) or not paths:
                    raise SourceError("manifest paths must be a non-empty array")
                normalized = [validate_repository_path(item) for item in paths]
                if len(set(normalized)) != len(normalized):
                    raise SourceError("manifest paths contain duplicates")
            else:
                require_text(source.get("mcp_reported_identity"), "manifest mcp_reported_identity")
                require_commit(source.get("mcp_reported_commit"), "manifest mcp_reported_commit")
                require_text(source.get("project_id"), "manifest project_id")
                require_text(source.get("server_id"), "manifest server_id")
                validate_repository_path(source.get("path"))
                require_digest(source.get("expected_sha256"), "manifest expected_sha256")
        return dict(source)

    def _validate_cached_artifact(self, value: Any) -> dict[str, Any]:
        artifact = require_object(value, "cached artifact")
        if set(artifact) != {"path", "format", "size_bytes", "sha256", "quads_loaded"}:
            raise SourceError("cached artifact has an invalid schema")
        rdf_format = artifact.get("format")
        if not isinstance(rdf_format, str) or rdf_format not in FORMATS:
            raise SourceError("cached artifact format is invalid")
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise SourceError("cached artifact digest is invalid")
        size = artifact.get("size_bytes")
        quads = artifact.get("quads_loaded")
        if type(size) is not int or size < 0 or size > self.policy.max_bytes:
            raise SourceError("cached artifact size is invalid")
        if type(quads) is not int or quads < 0:
            raise SourceError("cached artifact quad count is invalid")
        expected_path = self.artifacts / digest / f"{digest}{FORMATS[rdf_format][0]}"
        if artifact.get("path") != str(expected_path):
            raise SourceError("cached artifact path is not content-address derived")
        directory_details = expected_path.parent.lstat()
        if not stat.S_ISDIR(directory_details.st_mode) or stat.S_ISLNK(directory_details.st_mode):
            raise SourceError("cached artifact directory is not safe")
        descriptor = _open_regular(expected_path)
        try:
            details = os.fstat(descriptor)
            if details.st_size != size or _sha256_fd(descriptor) != digest:
                raise SourceError("cached artifact content does not match its manifest")
            actual_quads = _validate_rdf_fd(
                descriptor, rdf_format, lenient=self.policy.lenient
            )
            if actual_quads != quads:
                raise SourceError("cached artifact quad count does not match its manifest")
        finally:
            os.close(descriptor)
        return {
            "path": str(expected_path),
            "format": rdf_format,
            "size_bytes": size,
            "sha256": digest,
            "quads_loaded": quads,
        }

    @staticmethod
    def _stable_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "format": artifact["format"],
            "size_bytes": artifact["size_bytes"],
            "sha256": artifact["sha256"],
            "quads_loaded": artifact["quads_loaded"],
        }

    def _pending_signature(self, pending: Mapping[str, Any], *, create_key: bool) -> str:
        payload = {key: value for key, value in pending.items() if key != "signature"}
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hmac.new(self._pending_key(create=create_key), encoded, hashlib.sha256).hexdigest()

    def _pending_key(self, *, create: bool) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.request_secret, flags)
        except FileNotFoundError:
            if not create:
                raise SourceError("pending request authentication key is missing")
            create_flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            secret = secrets.token_bytes(32)
            try:
                output = os.open(self.request_secret, create_flags, 0o600)
            except FileExistsError:
                return self._pending_key(create=False)
            try:
                os.write(output, secret)
                os.fsync(output)
            finally:
                os.close(output)
            return secret
        details = os.fstat(descriptor)
        try:
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or details.st_mode & 0o077
                or (hasattr(os, "getuid") and details.st_uid != os.getuid())
            ):
                raise SourceError("pending request authentication key is not private")
            secret = os.read(descriptor, 33)
            if len(secret) != 32:
                raise SourceError("pending request authentication key is malformed")
            return secret
        finally:
            os.close(descriptor)

    def _cleanup_request(self, request_id: str) -> None:
        if not _REQUEST_ID.fullmatch(request_id):
            return
        try:
            os.unlink(self.pending / f"{request_id}.json")
        except FileNotFoundError:
            pass
        except OSError:
            pass
        self._remove_tree(self.staging, request_id)

    @classmethod
    def _remove_tree(cls, parent: Path, name: str) -> None:
        if Path(name).name != name:
            return
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            parent_fd = os.open(parent, directory_flags)
        except OSError:
            return
        try:
            cls._remove_at(parent_fd, name)
        finally:
            os.close(parent_fd)

    @classmethod
    def _remove_at(cls, parent_fd: int, name: str) -> None:
        try:
            details = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError:
            return
        if stat.S_ISDIR(details.st_mode):
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                child_fd = os.open(name, flags, dir_fd=parent_fd)
            except OSError:
                return
            try:
                for child in os.listdir(child_fd):
                    cls._remove_at(child_fd, child)
            finally:
                os.close(child_fd)
            try:
                os.rmdir(name, dir_fd=parent_fd)
            except OSError:
                pass
        else:
            try:
                os.unlink(name, dir_fd=parent_fd)
            except OSError:
                pass

    def _read_json(self, path: Path) -> dict[str, Any]:
        descriptor = _open_regular(path)
        try:
            chunks: list[bytes] = []
            total = 0
            while True:
                block = os.read(descriptor, min(64 * 1024, MAX_MANIFEST_BYTES + 1 - total))
                if not block:
                    break
                total += len(block)
                if total > MAX_MANIFEST_BYTES:
                    raise SourceError(f"JSON state is too large: {path}")
                chunks.append(block)
            try:
                value = json.loads(b"".join(chunks).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SourceError(f"JSON state is corrupt: {path}") from exc
            return require_object(value, f"JSON state {path}")
        finally:
            os.close(descriptor)

    def _ready(
        self,
        manifest: Mapping[str, Any],
        manifest_path: Path,
        warnings: Sequence[str],
    ) -> dict[str, Any]:
        artifacts = manifest["artifacts"]
        combined_warnings = list(manifest.get("warnings", []))
        for warning in warnings:
            if warning not in combined_warnings:
                combined_warnings.append(warning)
        return {
            "schema_version": 1,
            "status": "ready",
            "target": {
                "data": [artifact["path"] for artifact in artifacts],
                "endpoint": None,
                "timeout_ms": self.policy.timeout_ms,
                "lenient": self.policy.lenient,
            },
            "manifest": {**dict(manifest), "path": str(manifest_path)},
            "warnings": combined_warnings,
        }

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        encoded = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
