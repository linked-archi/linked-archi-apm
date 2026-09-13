"""Public source commands and strict schema_version=1 acquisition contracts."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from .core import (
    DEFAULT_MAX_BYTES,
    DEFAULT_TIMEOUT_MS,
    FORMATS,
    Policy,
    reject_unknown,
    require_object,
)
from .errors import SourceError
from .git import acquire_git
from .http import acquire_url
from .mcp import complete_gitlab, request_gitlab

OK, ERROR = 0, 2

#: `_machine` is machine-facing, NOT private. The underscore says "not for a human to
#: type", and nothing more: the contract is documented, versioned, and depended on across
#: process boundaries by sibling skills. Hiding it from `--help` while three skills call it
#: was the worst of both worlds - visible in the usage line as `==SUPPRESS==` and explained
#: nowhere.
_MACHINE_HELP = "versioned JSON contract for automation (see source-contract.md)"
_MACHINE_DESCRIPTION = (
    "Read one JSON object on stdin, write one JSON object on stdout. Diagnostics go to "
    "stderr. schema_version is checked exactly. This is a stable, documented boundary for "
    "sibling skills and automation, not a private entry point: skills/linked-archi-source/references/source-contract.md"
)



_FORMAT_HELP = (
    "RDF syntax, one of: " + ", ".join(sorted(FORMATS)) + ". Default: inferred from the "
    "suffix or an exact Content-Type, and refused when neither is decisive"
)

_SHA256_HELP = (
    "expected content digest, 64 lowercase hex characters. Optional here, but it is what "
    "turns a fetch into a reproducible one: without it you get whatever the host served"
)

_EPILOG = """\
Examples:
  la-source url https://models.example.org/architecture.trig --sha256 68b8...
  la-source url https://private.example.org/model.ttl --token-env LINKED_ARCHI_SOURCE_TOKEN
  la-source git https://git.example.org/models.git --ref 9f0a12d4... \\
      --path dist/archimate.trig --path dist/bpmn.trig
  la-source gitlab-mcp --project group/models --ref main --path dist/model.trig --sha256 68b8...
  la-source complete REQUEST_ID --reported-commit 9f0a12d4...
  la-source doctor

Exit codes: 0 a structured result was produced (ready, or action_required for MCP),
2 fail-closed. Exit 2 covers malformed input, a disallowed source, host, network or
path, an unavailable credential, a timeout, a size limit, a digest mismatch, invalid
RDF, a missing or tampered cache entry, a Git failure, or an expired request.
There is no exit 1: acquisition either produces verified bytes or refuses.

Hand the `target` object straight to linked-archi-connect. It is exactly connect
target version 1; merging manifest fields into it is rejected, deliberately.
"""


def _add_policy(parser: argparse.ArgumentParser, *, completion: bool = False) -> None:
    """Acquisition policy. Every default is the closed one; each flag opens something."""
    parser.add_argument(
        "--cache-dir",
        metavar="DIR",
        help=(
            "source cache (default: $LINKED_ARCHI_SOURCE_CACHE or "
            "~/.cache/linked-archi/sources) (env: LINKED_ARCHI_SOURCE_CACHE)"
        ),
    )
    if not completion:
        parser.add_argument(
            "--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS, metavar="MS",
            help=(
                f"one deadline for the whole acquisition (default: {DEFAULT_TIMEOUT_MS}), "
                "not per request"
            ),
        )
        parser.add_argument(
            "--max-bytes", type=int, default=DEFAULT_MAX_BYTES, metavar="N",
            help=(
                f"refuse anything larger (default: {DEFAULT_MAX_BYTES}, 100 MiB). "
                "Enforced while streaming, not after"
            ),
        )
        parser.add_argument(
            "--allowed-host", action="append", default=[], metavar="HOST",
            help=(
                "restrict acquisition to this host (repeatable). Default: any public "
                "host the URI names"
            ),
        )
        parser.add_argument(
            "--allow-private-network", action="store_true",
            help=(
                "permit a host that resolves to loopback, link-local or other private "
                "space. Off by default, so a self-hosted store is a decision you make"
            ),
        )
        parser.add_argument(
            "--allow-ssh", action="store_true",
            help="permit an ssh:// or scp-style Git remote. HTTPS only by default",
        )
        parser.add_argument(
            "--offline", action="store_true",
            help=(
                "reuse the cache with no network at all. Requires an immutable identity: "
                "a full 40- or 64-character commit for Git. Re-verifies digest, size, "
                "RDF parsing and quad count rather than trusting the cache"
            ),
        )
        parser.add_argument(
            "--lenient", action="store_true",
            help=(
                "relax RDF parsing of the acquired document. Never relaxes digest, size "
                "or network policy"
            ),
        )
    parser.add_argument("--json", action="store_true", help="emit the versioned JSON result")


def _policy_from_args(args: argparse.Namespace, *, completion: bool = False) -> Policy:
    raw: dict[str, Any] = {}
    if args.cache_dir:
        raw["cache_dir"] = args.cache_dir
    if not completion:
        raw.update(
            {
                "timeout_ms": args.timeout_ms,
                "max_bytes": args.max_bytes,
                "allowed_hosts": args.allowed_host,
                "allow_private_network": args.allow_private_network,
                "allow_ssh": args.allow_ssh,
                "offline": args.offline,
                "lenient": args.lenient,
            }
        )
    return Policy.from_mapping(raw)


def _emit(result: dict[str, Any], *, json_output: bool, machine: bool = False) -> int:
    if machine or json_output or result.get("status") == "action_required":
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=not machine,
                indent=None if machine else 2,
            )
        )
        return OK

    target = result["target"]
    paths = target["data"]
    print(f"Ready: {len(paths)} verified RDF artifact(s)")
    for path in paths:
        print(f"  data: {path}")
    manifest = result["manifest"]
    print(f"  manifest: {manifest['path']}")
    source = manifest["source"]
    identity = source.get("resolved_identity") or source.get("mcp_reported_identity")
    print(f"  source: {identity}")
    for warning in result.get("warnings", []):
        print(f"  warning: {warning}", file=sys.stderr)
    _print_next_step(paths)
    return OK


#: This skill's own name, used only to phrase the adjacency hint in a message.
OWN_SKILL = "linked-archi-source"


def _companion(skill: str, executable: str) -> Path:
    """Locate a sibling owner. One order, used identically by every owner here.

    1. ``$LINKED_ARCHI_SKILLS_DIR`` when set - **authoritative, and never falls back**.
       Someone who names an install root means that root; silently using a different
       generation of the skill found elsewhere is how two skill sets get mixed.
    2. the sibling directory beside this skill, which is how installed skill sets sit.
    3. the command on ``PATH``, for a packaged or symlinked install.

    Deliberately not a filesystem search. A missing companion is reported by name so the
    caller installs it, rather than going looking for it.
    """
    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    if configured:
        candidate = Path(configured).expanduser() / skill / "scripts" / executable
        if candidate.is_file():
            return candidate
        raise SourceError(
            f"Missing required skill: {skill} under explicit "
            f"LINKED_ARCHI_SKILLS_DIR={configured}."
        )
    candidate = Path(__file__).resolve().parents[3] / skill / "scripts" / executable
    if candidate.is_file():
        return candidate
    on_path = shutil.which(executable)
    if on_path:
        return Path(on_path)
    raise SourceError(
        f"Missing required skill: {skill}. Install it beside {OWN_SKILL}, put "
        f"{executable} on PATH, or set LINKED_ARCHI_SKILLS_DIR."
    )


def _print_next_step(paths: Sequence[str]) -> None:
    print("\nNext:")
    try:
        resolved = _companion("linked-archi-connect", "la-connect")
    except SourceError as exc:
        # Never print a command that cannot run. Acquisition succeeded, so the verified
        # paths above stay the usable output; only the convenience step is unavailable.
        print(f"  {exc}")
        print("  Then attach the verified path(s) above with: la-connect connect --data ...")
        return
    command = [str(resolved), "connect"]
    if not shutil.which(resolved.name):
        command.insert(0, sys.executable)
    for path in paths:
        command.extend(("--data", path))
    print("  " + " ".join(shlex.quote(part) for part in command))


def cmd_doctor(args: argparse.Namespace) -> int:
    """Where this owner is, what it can verify, and where acquisitions land."""
    root = Path(__file__).resolve().parents[1]
    print(OWN_SKILL)
    print(f"  owner root:   {root.parent}")
    print(f"  command:      {root / 'la-source'}")
    policy = Policy.from_mapping({"cache_dir": args.cache_dir} if args.cache_dir else {})
    print(f"  cache:        {policy.cache_dir}")
    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    print(f"  skills dir:   {configured or '(unset; resolving beside this skill)'}")

    ok = True
    try:
        import pyoxigraph  # noqa: F401
        print("  pyoxigraph    present (verifies acquired RDF parses)")
    except ModuleNotFoundError:
        ok = False
        print("  pyoxigraph    MISSING - pip install pyoxigraph")
    git = shutil.which("git")
    print(f"  git           {git or 'not found - only needed for Git acquisition'}")

    try:
        print(f"  la-connect    {_companion('linked-archi-connect', 'la-connect')}")
        print("                attaches what this skill materializes (optional)")
    except SourceError as exc:
        print(f"  la-connect    not found (optional) - {exc}")
    print(
        "\nHTTPS and Git acquisition need no companion. GitLab MCP is agent-mediated: no\n"
        "MCP server is installed or invoked here. Resolution order is\n"
        "$LINKED_ARCHI_SKILLS_DIR (authoritative), then the sibling directory beside this\n"
        "skill, then PATH - never a filesystem search."
    )
    return OK if ok else ERROR


def cmd_url(args: argparse.Namespace) -> int:
    source = {
        "kind": "url",
        "uri": args.uri,
        "format": args.format,
        "expected_sha256": args.sha256,
        "token_env": args.token_env,
    }
    result = acquire_url(source, _policy_from_args(args))
    return _emit(result, json_output=args.json)


def _git_digests(values: Sequence[str], paths: Sequence[str]) -> dict[str, str] | None:
    if not values:
        return None
    result: dict[str, str] = {}
    for raw in values:
        selected, separator, digest = raw.partition("=")
        if not separator:
            if len(paths) != 1:
                raise SourceError(
                    "with multiple --path values, each --sha256 must be PATH=DIGEST"
                )
            selected, digest = paths[0], selected
        if selected not in paths:
            raise SourceError(f"--sha256 names an unselected path: {selected}")
        if selected in result:
            raise SourceError(f"duplicate --sha256 for path: {selected}")
        result[selected] = digest
    return result


def cmd_git(args: argparse.Namespace) -> int:
    source = {
        "kind": "git",
        "repository": args.repository,
        "revision": args.revision,
        "paths": args.paths,
        "expected_sha256": _git_digests(args.sha256, args.paths),
    }
    result = acquire_git(source, _policy_from_args(args))
    return _emit(result, json_output=args.json)


def cmd_gitlab_mcp(args: argparse.Namespace) -> int:
    source = {
        "kind": "gitlab-mcp",
        "project_id": args.project_id,
        "revision": args.revision,
        "path": args.path,
        "format": args.format,
        "expected_sha256": args.sha256,
        "server_id": args.server_id,
    }
    result = request_gitlab(source, _policy_from_args(args))
    return _emit(result, json_output=True)


def cmd_complete(args: argparse.Namespace) -> int:
    result = complete_gitlab(
        args.request_id,
        args.reported_commit,
        _policy_from_args(args, completion=True),
    )
    return _emit(result, json_output=args.json)


def _machine_input(allowed: set[str], label: str) -> dict[str, Any]:
    try:
        raw = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise SourceError(f"machine input is not valid JSON: {exc}") from exc
    request = require_object(raw, "machine input")
    reject_unknown(request, {"schema_version", *allowed}, "machine input")
    if type(request.get("schema_version")) is not int or request["schema_version"] != 1:
        raise SourceError("machine input requires schema_version=1")
    return request


def cmd_machine_resolve(_args: argparse.Namespace) -> int:
    request = _machine_input({"source", "policy"}, "resolve")
    source = require_object(request.get("source"), "source")
    kind = source.get("kind")
    policy = Policy.from_mapping(request.get("policy"))
    if kind == "url":
        result = acquire_url(source, policy)
    elif kind == "git":
        result = acquire_git(source, policy)
    elif kind == "gitlab-mcp":
        result = request_gitlab(source, policy)
    else:
        raise SourceError("source kind must be one of: url, git, gitlab-mcp")
    return _emit(result, json_output=True, machine=True)


def cmd_machine_complete(_args: argparse.Namespace) -> int:
    request = _machine_input({"request_id", "reported_commit", "policy"}, "complete")
    result = complete_gitlab(
        request.get("request_id"),
        request.get("reported_commit"),
        Policy.from_mapping(request.get("policy")),
    )
    return _emit(result, json_output=True, machine=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="la-source",
        description="Materialize verified remote RDF as immutable local inputs.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    url = commands.add_parser(
        "url",
        help="fetch one HTTPS RDF document",
        description=(
            "Fetch, verify and cache one document. The format comes from the suffix or an "
            "exact Content-Type unless --format says otherwise."
        ),
    )
    url.add_argument("uri", help="HTTPS URI of the RDF document")
    url.add_argument("--format", metavar="FMT", help=_FORMAT_HELP)
    url.add_argument("--sha256", metavar="DIGEST", help=_SHA256_HELP)
    url.add_argument(
        "--token-env",
        metavar="VAR",
        help=(
            "name of an environment variable holding a bearer token, never the token "
            "itself. Its value is sent as Authorization and is never serialized into a "
            "manifest or a result. A token on the command line would land in the process "
            "list and the shell history"
        ),
    )
    _add_policy(url)
    url.set_defaults(func=cmd_url)

    git = commands.add_parser(
        "git",
        help="extract RDF files from a remote Git revision",
        description=(
            "Extract named files from one revision without cloning a working tree. "
            "System and user Git configuration, proxies, URL rewrites, hooks and filters "
            "are all ignored: acquisition must not run repository-controlled code."
        ),
    )
    git.add_argument("repository", help="repository URL, HTTPS unless --allow-ssh")
    git.add_argument(
        "--ref", dest="revision", required=True, metavar="REV",
        help=(
            "branch, tag or commit to read. Required. Immutable reuse and --offline need "
            "a full 40- or 64-character commit ID, because a branch moves"
        ),
    )
    git.add_argument(
        "--path", dest="paths", action="append", required=True, metavar="PATH",
        help="repository-relative RDF file to extract (repeatable). Required",
    )
    git.add_argument(
        "--sha256",
        action="append",
        default=[],
        metavar="[PATH=]DIGEST",
        help=(
            "expected digest (repeatable). Use PATH=DIGEST to pin one file when several "
            "were requested; a bare digest applies to a single path"
        ),
    )
    _add_policy(git)
    git.set_defaults(func=cmd_git)

    mcp = commands.add_parser(
        "gitlab-mcp",
        help="request a read-only GitLab MCP file handoff",
        description=(
            "Phase one of two: prints the read-only MCP steps for the agent to run and a "
            "staging path to write the bytes to. This runtime never calls MCP itself. "
            "Finish with `la-source complete`."
        ),
    )
    mcp.add_argument(
        "--project", dest="project_id", required=True, metavar="ID_OR_PATH",
        help="numeric project ID or full project path such as group/models. Not a URL",
    )
    mcp.add_argument("--ref", dest="revision", required=True, metavar="REV",
                     help="branch, tag or commit to read. Required")
    mcp.add_argument("--path", required=True, metavar="PATH",
                     help="repository-relative RDF file. One file per request. Required")
    mcp.add_argument("--format", metavar="FMT", help=_FORMAT_HELP)
    mcp.add_argument(
        "--sha256", required=True, metavar="DIGEST",
        help=(
            "expected digest. **Mandatory here**, and it must come from a channel "
            "independent of the MCP response - a release manifest, configuration, or "
            "human approval. The MCP-reported commit is not proof that those bytes were "
            "stored at it; only this digest binds the staged content"
        ),
    )
    mcp.add_argument(
        "--server-id", default="gitlab", metavar="ID",
        help="which approved MCP server to name in the steps (default: gitlab)",
    )
    _add_policy(mcp)
    mcp.set_defaults(func=cmd_gitlab_mcp)

    complete = commands.add_parser(
        "complete",
        help="verify and cache a staged GitLab MCP result",
        description=(
            "Phase two: verify the staged bytes against the digest from phase one and "
            "cache them. The pending request's original limits stay authoritative, so "
            "completion cannot widen them. Success or failure both clear the staging."
        ),
    )
    complete.add_argument("request_id", help="request ID printed by gitlab-mcp")
    complete.add_argument(
        "--reported-commit", required=True, metavar="SHA",
        help="full commit SHA the MCP server reported. Recorded as reported, not proven",
    )
    _add_policy(complete, completion=True)
    complete.set_defaults(func=cmd_complete)

    doctor = commands.add_parser(
        "doctor",
        help="report this owner's location, cache and companions",
        description=(
            "Owner root, resolved command, cache directory, git availability, and every "
            "companion this skill can reach. Run it instead of searching the filesystem."
        ),
    )
    doctor.add_argument(
        "--cache-dir", metavar="DIR",
        help="report this cache instead of the default (env: LINKED_ARCHI_SOURCE_CACHE)",
    )
    doctor.set_defaults(func=cmd_doctor)

    machine = commands.add_parser(
        "_machine",
        help=_MACHINE_HELP,
        description=_MACHINE_DESCRIPTION,
    )
    machine_commands = machine.add_subparsers(dest="machine_command", required=True)
    resolve = machine_commands.add_parser(
        "resolve",
        help="acquire and verify a source, or return the MCP steps to run",
        description=(
            'Request {"schema_version": 1, "source": {...}, "policy": {...}}. Responds '
            '"ready" with a connect target and a manifest, or "action_required" with MCP '
            "steps. See references/source-contract.md."
        ),
    )
    resolve.set_defaults(func=cmd_machine_resolve)
    machine_complete = machine_commands.add_parser(
        "complete",
        help="verify and cache a staged MCP result",
        description=(
            'Request {"schema_version": 1, "request_id": "...", "reported_commit": '
            '"...", "policy": {"cache_dir": "..."}}. Only cache_dir is needed; the '
            "pending request's original limits remain authoritative."
        ),
    )
    machine_complete.set_defaults(func=cmd_machine_complete)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (SourceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ERROR
    except BrokenPipeError:
        return OK
    except KeyboardInterrupt:
        return ERROR


if __name__ == "__main__":
    raise SystemExit(main())
