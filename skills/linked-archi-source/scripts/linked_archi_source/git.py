"""Pinned Git acquisition without checkout, hooks, submodules, or filters."""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import (
    Policy,
    SourceCache,
    canonical_digest,
    is_full_commit,
    normalize_format,
    optional_digest,
    require_commit,
    require_text,
    validate_repository_path,
)
from .errors import SourceError
from .http import parse_https_url, public_url, validated_https_transport

_SCP_REMOTE = re.compile(r"^(?P<user>[^@/:]+)@(?P<host>[^:/]+):(?P<path>.+)$")
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1\n"
_GIT_PREFIX = (
    "-c", "protocol.allow=never",
    "-c", "protocol.file.allow=never",
    "-c", "protocol.https.allow=always",
    "-c", "core.hooksPath=/dev/null",
    "-c", "filter.lfs.smudge=",
    "-c", "filter.lfs.required=false",
    "-c", "submodule.recurse=false",
)
_PROXY_ENV = {
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
}


def _https_probe(host: str, port: int) -> str:
    rendered = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"https://{rendered}:{port}/"


def _parse_remote(remote: str, policy: Policy) -> tuple[str, str, str, int]:
    """Validate remote identity without performing DNS resolution."""
    if remote.startswith("https://"):
        split = parse_https_url(remote, policy)
        if split.query:
            raise SourceError("Git HTTPS remote must not contain a query string")
        return public_url(remote), "https", (split.hostname or "").lower().rstrip("."), split.port or 443

    scp = _SCP_REMOTE.fullmatch(remote)
    if scp:
        if not policy.allow_ssh:
            raise SourceError("SSH Git remotes require --allow-ssh")
        host = scp.group("host").lower().rstrip(".")
        split = parse_https_url(_https_probe(host, 22), policy)
        path = scp.group("path")
        if not path or any(ord(char) < 32 or ord(char) == 127 for char in path):
            raise SourceError("Git SSH remote has an invalid path")
        return f"ssh://{split.hostname}/{path.lstrip('/')}", "ssh", split.hostname or "", 22

    split = urllib.parse.urlsplit(remote)
    if split.scheme.lower() == "ssh":
        if not policy.allow_ssh:
            raise SourceError("SSH Git remotes require --allow-ssh")
        if split.password is not None:
            raise SourceError("Git SSH remote must not contain a password")
        if split.query or split.fragment:
            raise SourceError("Git SSH remote must not contain a query or fragment")
        host = (split.hostname or "").lower().rstrip(".")
        if not host:
            raise SourceError("Git SSH remote requires a host")
        try:
            port = split.port or 22
        except ValueError as exc:
            raise SourceError(f"Git SSH remote has an invalid port: {exc}") from exc
        validated = parse_https_url(_https_probe(host, port), policy)
        if not split.path or any(ord(char) < 32 or ord(char) == 127 for char in split.path):
            raise SourceError("Git SSH remote has an invalid path")
        normalized_host = validated.hostname or ""
        rendered = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
        return (
            f"ssh://{rendered}{':' + str(port) if split.port else ''}{split.path}",
            "ssh",
            normalized_host,
            port,
        )

    raise SourceError(
        "Git remote must use HTTPS, or SSH with --allow-ssh; local/file/git/ext remotes are refused"
    )


def _git_env(ssh_command: str | None = None) -> dict[str, str]:
    # Do not let user/system Git config rewrite a validated URL through
    # url.*.insteadOf or install filters/helpers. Askpass and SSH-agent
    # credentials still work; repository content never controls configuration.
    refused_prefixes = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
    refused_exact = {
        "GIT_CONFIG",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "GIT_SSL_NO_VERIFY",
        "GIT_SSL_CAINFO",
        "GIT_SSL_CAPATH",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        *_PROXY_ENV,
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in refused_exact and not key.startswith(refused_prefixes)
    }
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_SSH_COMMAND": ssh_command
            or (
                "ssh -F /dev/null -oBatchMode=yes -oClearAllForwardings=yes "
                "-oPermitLocalCommand=no -oProxyCommand=none"
            ),
        }
    )
    return env


def _remaining(deadline: float, policy: Policy) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceError(f"Git acquisition exceeded timeout_ms={policy.timeout_ms}")
    return remaining


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    policy: Policy,
    deadline: float,
    operation: str,
    text: bool = True,
    transport_config: Sequence[str] = (),
    ssh_command: str | None = None,
) -> subprocess.CompletedProcess:
    try:
        ssh_policy = "always" if policy.allow_ssh else "never"
        completed = subprocess.run(
            [
                "git",
                *_GIT_PREFIX,
                "-c", f"protocol.ssh.allow={ssh_policy}",
                *transport_config,
                *args,
            ],
            cwd=cwd,
            env=_git_env(ssh_command),
            capture_output=True,
            text=text,
            timeout=_remaining(deadline, policy),
            check=False,
        )
    except FileNotFoundError as exc:
        raise SourceError("Git acquisition needs the git executable on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceError(f"Git acquisition exceeded timeout_ms={policy.timeout_ms}") from exc
    if completed.returncode != 0:
        raw = completed.stderr if completed.stderr else completed.stdout
        if isinstance(raw, bytes):
            detail = raw.decode("utf-8", "replace")
        else:
            detail = raw or "no diagnostic"
        detail = " ".join(detail.strip().split())[-1000:]
        raise SourceError(f"Git {operation} failed: {detail}")
    return completed


def _expected_map(raw: Any, paths: Sequence[str]) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SourceError("git source expected_sha256 must be an object keyed by repository path")
    unknown = set(raw).difference(paths)
    if unknown:
        raise SourceError(
            "git source expected_sha256 names unselected paths: " + ", ".join(sorted(unknown))
        )
    result: dict[str, str] = {}
    for path, digest in raw.items():
        result[path] = optional_digest(digest, f"expected_sha256[{path}]") or ""
    return result


def _request_key(
    remote: str,
    revision: str,
    paths: Sequence[str],
    expected: Mapping[str, str],
    lenient: bool,
) -> str:
    return canonical_digest(
        {
            "kind": "git",
            "repository": remote,
            "revision": revision,
            "paths": list(paths),
            "expected_sha256": dict(sorted(expected.items())),
            "lenient": lenient,
        }
    )


def _transport_policy(
    remote: str,
    scheme: str,
    host: str,
    port: int,
    policy: Policy,
    deadline: float,
) -> tuple[list[str], str | None]:
    probe = remote if scheme == "https" else _https_probe(host, port)
    _split, addresses = validated_https_transport(probe, policy, deadline)
    unique_addresses = list(dict.fromkeys(address[4][0] for address in addresses))
    if scheme == "https":
        config = [
            "-c", "http.followRedirects=false",
            "-c", "http.proxy=",
            "-c", "http.sslVerify=true",
        ]
        for address in unique_addresses:
            rendered = f"[{address}]" if ipaddress.ip_address(address).version == 6 else address
            config.extend(("-c", f"http.curloptResolve={host}:{port}:{rendered}"))
        return config, None

    pinned_address = unique_addresses[0]
    ssh_command = " ".join(
        (
            "ssh",
            "-F", "/dev/null",
            "-oBatchMode=yes",
            "-oClearAllForwardings=yes",
            "-oPermitLocalCommand=no",
            "-oProxyCommand=none",
            f"-oHostname={shlex.quote(pinned_address)}",
            f"-oHostKeyAlias={shlex.quote(host)}",
        )
    )
    return [], ssh_command


def acquire_git(source: dict[str, Any], policy: Policy) -> dict[str, Any]:
    allowed = {"kind", "repository", "revision", "paths", "expected_sha256"}
    unknown = set(source).difference(allowed)
    if unknown:
        raise SourceError("git source contains unknown fields: " + ", ".join(sorted(unknown)))
    remote = require_text(source.get("repository"), "git repository")
    public_remote, scheme, host, port = _parse_remote(remote, policy)
    revision = require_text(source.get("revision"), "git revision")
    if revision.startswith("-"):
        raise SourceError("git revision must not begin with '-'")
    raw_paths = source.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise SourceError("git source paths must be a non-empty string array")
    paths = [validate_repository_path(path) for path in raw_paths]
    if len(set(paths)) != len(paths):
        raise SourceError("git source paths must not contain duplicates")
    expected = _expected_map(source.get("expected_sha256"), paths)
    request_key = _request_key(public_remote, revision, paths, expected, policy.lenient)
    cache = SourceCache(policy)

    if policy.offline:
        if not is_full_commit(revision):
            raise SourceError("offline Git acquisition requires a full immutable commit ID")
        cached = cache.find(request_key)
        if cached is None:
            raise SourceError("offline mode has no exact cached result for this Git request")
        return cached

    deadline = time.monotonic() + policy.timeout_ms / 1000
    transport_config, ssh_command = _transport_policy(
        remote, scheme, host, port, policy, deadline
    )
    temporary_artifacts: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="git-", dir=cache.temporary_dir) as raw_tmp:
        root = Path(raw_tmp)
        repository = root / "repository.git"
        run = {
            "cwd": root,
            "policy": policy,
            "deadline": deadline,
            "transport_config": transport_config,
            "ssh_command": ssh_command,
        }
        _run_git(["init", "--bare", str(repository)], operation="init", **run)
        _run_git(
            [
                "-C", str(repository),
                "fetch", "--depth=1", "--no-tags", "--no-recurse-submodules",
                "--end-of-options", remote, revision,
            ],
            operation="fetch",
            **run,
        )
        resolved = _run_git(
            ["-C", str(repository), "rev-parse", "--verify", "FETCH_HEAD^{commit}"],
            operation="resolve",
            **run,
        ).stdout.strip().lower()
        commit = require_commit(resolved, "resolved Git commit")

        artifacts: list[dict[str, Any]] = []
        total_size = 0
        try:
            for selected in paths:
                listing = _run_git(
                    ["-C", str(repository), "ls-tree", "-z", commit, "--", selected],
                    operation=f"inspect {selected}",
                    text=False,
                    **run,
                ).stdout
                records = [record for record in listing.split(b"\0") if record]
                if len(records) != 1 or b"\t" not in records[0]:
                    raise SourceError(f"Git path is missing or ambiguous at {commit}: {selected}")
                metadata, raw_name = records[0].split(b"\t", 1)
                try:
                    mode, object_type, object_id = metadata.decode("ascii").split()
                    returned_name = raw_name.decode("utf-8")
                except (UnicodeDecodeError, ValueError) as exc:
                    raise SourceError(f"Git returned malformed tree metadata for {selected}") from exc
                if returned_name != selected:
                    raise SourceError(f"Git returned an unexpected path for {selected}: {returned_name}")
                if object_type != "blob" or not mode.startswith("100") or mode == "120000":
                    raise SourceError(
                        f"Git path must be a regular file, not mode {mode} type {object_type}: {selected}"
                    )
                size_text = _run_git(
                    ["-C", str(repository), "cat-file", "-s", object_id],
                    operation=f"size {selected}",
                    **run,
                ).stdout.strip()
                try:
                    size = int(size_text)
                except ValueError as exc:
                    raise SourceError(f"Git returned an invalid size for {selected}") from exc
                total_size += size
                if size < 0 or total_size > policy.max_bytes:
                    raise SourceError(f"selected Git artifacts exceed max_bytes={policy.max_bytes}")
                content = _run_git(
                    ["-C", str(repository), "cat-file", "blob", object_id],
                    operation=f"read {selected}",
                    text=False,
                    **run,
                ).stdout
                if content.startswith(_LFS_POINTER):
                    raise SourceError(
                        f"Git LFS pointer refused for {selected}; materialize and publish the RDF artifact explicitly"
                    )
                if len(content) != size:
                    raise SourceError(
                        f"Git blob size changed while reading {selected}: expected {size}, received {len(content)}"
                    )
                rdf_format = normalize_format(None, selected)
                staged = cache.temporary_path()
                temporary_artifacts.append(staged)
                staged.write_bytes(content)
                artifacts.append(cache.materialize(staged, rdf_format, expected.get(selected)))
        finally:
            for staged in temporary_artifacts:
                cache.discard(staged)

    immutable_key = _request_key(public_remote, commit, paths, expected, policy.lenient)
    warnings: list[str] = []
    if not is_full_commit(revision):
        warnings.append(
            f"mutable Git revision {revision!r} resolved to {commit}; pin the full commit for reproducible reuse"
        )
    for selected in paths:
        if selected not in expected:
            warnings.append(
                f"{selected} was not pinned by SHA-256; its observed digest is recorded in the manifest"
            )
    source_manifest = {
        "kind": "git",
        "request_key": request_key,
        "request_keys": sorted({request_key, immutable_key}),
        "requested_identity": f"{public_remote}@{revision}",
        "resolved_identity": f"{public_remote}@{commit}",
        "requested_revision": revision,
        "resolved_commit": commit,
        "paths": paths,
    }
    return cache.write_manifest(source_manifest, artifacts, warnings)
