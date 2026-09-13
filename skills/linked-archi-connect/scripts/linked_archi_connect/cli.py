"""Public connect commands and the private schema_version=1 transport contract."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Sequence

from . import completeness, discover
from .adapters import (
    STORE_MODES,
    AdapterError,
    open_adapter,
    validate_endpoint_url,
    validate_queries_readonly,
)
from .adapters.store_cache import DEFAULT_MODE as DEFAULT_STORE_MODE

OK, REFUSED, ERROR = 0, 1, 2

#: `_machine` is machine-facing, NOT private. The underscore says "not for a human to
#: type", and nothing more: the contract is documented, versioned, and depended on across
#: process boundaries by sibling skills. Hiding it from `--help` while three skills call it
#: was the worst of both worlds - visible in the usage line as `==SUPPRESS==` and explained
#: nowhere.
_MACHINE_HELP = "versioned JSON contract for automation (see references/machine-contract.md)"
_MACHINE_DESCRIPTION = (
    "Read one JSON object on stdin, write one JSON object on stdout. Diagnostics go to "
    "stderr. schema_version is checked exactly. This is a stable, documented boundary for "
    "sibling skills and automation, not a private entry point: skills/linked-archi-connect/references/machine-contract.md"
)



def _add_target_args(parser: argparse.ArgumentParser) -> None:
    """The target. Exactly one kind of it, and the same four flags everywhere."""
    parser.add_argument(
        "--data",
        action="append",
        default=[],
        metavar="FILE",
        help=(
            "local RDF file, or a directory holding one canonical merged graph "
            "(repeatable; files merge into one dataset). Loadable suffixes: "
            + ", ".join(sorted(discover.DEFAULT_EXTENSIONS))
            + ". Omit when $LINKED_ARCHI_DATA is set (env: LINKED_ARCHI_DATA)"
        ),
    )
    parser.add_argument(
        "--endpoint",
        metavar="URL",
        help=(
            "HTTPS SPARQL query endpoint instead of local files. Mutually exclusive "
            "with --data: two targets would make the dataset a result cites ambiguous"
        ),
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        metavar="MS",
        help=(
            "endpoint request deadline (default: 30000). Ignored for local files, which "
            "are bounded by the file rather than a clock"
        ),
    )
    parser.add_argument(
        "--lenient",
        action="store_true",
        help=(
            "relax RDF parsing so a malformed file loads what it can. Never relaxes "
            "query safety, and the result says so"
        ),
    )
    parser.add_argument(
        "--store",
        choices=STORE_MODES,
        default=None,
        help=(
            "where the store comes from, for local files (env: LINKED_ARCHI_STORE, "
            f"default: {DEFAULT_STORE_MODE}). 'cached' reuses an on-disk store: much "
            "faster to load and slower to query, so it wins for many cheap lookups and "
            "loses for aggregation. See references/store-modes.md"
        ),
    )


_EPILOG = """\
Examples:
  la-connect datasets                       # candidates here and in the git root
  la-connect datasets dist --extension .json
  la-connect connect --data dist/archimate.trig --data dist/bpmn.trig
  la-connect connect --endpoint https://graph.example.org/architecture/query
  la-connect doctor

Exit codes: 0 attached, 2 error (nothing parsed, rejected endpoint, unresolvable
companion, refused query). `datasets` finding no candidates is exit 0 with an empty
list: no dataset here is a finding, not a failure.
"""


def _resolve_directories(data: Sequence[str]) -> list[str]:
    """Turn any directory in --data into the one file it canonically means.

    Reported, never silent: the chosen file, why it was chosen, and its git revision, so
    the dataset a citation names is one somebody can check.
    """
    resolved: list[str] = []
    for raw in data:
        candidate = Path(raw).expanduser()
        if not candidate.is_dir():
            resolved.append(raw)
            continue
        try:
            choice = discover.resolve_directory(candidate)
        except discover.AmbiguousDirectory as exc:
            raise AdapterError(str(exc)) from exc
        print(f"{candidate} -> {choice.path}")
        print(f"  chosen: {choice.reason}")
        if choice.git is not None:
            bits = [part for part in (choice.git.ref, choice.git.commit) if part]
            if bits:
                state = "uncommitted changes" if choice.git.dirty else (
                    "untracked" if choice.git.untracked else "clean"
                )
                print(f"  git:    {' @ '.join(bits)}, {state}")
        if choice.caveat:
            print(f"  caveat: {choice.caveat}", file=sys.stderr)
        resolved.append(str(choice.path))
    return resolved


def _target(args: argparse.Namespace) -> dict[str, Any]:
    data = _resolve_directories(args.data)
    if not data and not args.endpoint:
        missing = discover.missing_from_env()
        if missing:
            raise AdapterError(
                f"${discover.ENV_DATA} names files that do not exist: "
                + ", ".join(str(path) for path in missing)
            )
        data = [str(path) for path in discover.from_env()]
    return {
        "data": data,
        "endpoint": args.endpoint,
        "timeout_ms": args.timeout_ms,
        "lenient": args.lenient,
        # None rather than a default, so an unset flag defers to $LINKED_ARCHI_STORE
        # instead of overriding it with the flag's default.
        "store": getattr(args, "store", None),
    }


def _open(target: dict[str, Any]):
    timeout_ms = target.get("timeout_ms", 30000)
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
        raise AdapterError("machine target timeout_ms must be a positive integer")
    return open_adapter(
        data=target.get("data") or None,
        endpoint=target.get("endpoint"),
        timeout_ms=timeout_ms,
        lenient=target.get("lenient", False),
        store=target.get("store"),
    )


def cmd_connect(args: argparse.Namespace) -> int:
    with _open(_target(args)) as adapter:
        print(adapter.describe())
        _report_completeness(adapter)
        _suggest_profile_step(args)
    return OK


def _suggest_profile_step(args: argparse.Namespace) -> None:
    """Name the command that picks a profile, rather than picking one here.

    Which profile fits is the profile owner's judgement, and duplicating the shape-to-name
    mapping in this skill would give two answers that could disagree. So this points, with
    the target already filled in: the next step after attaching a dataset is always the same
    one, and a session that skips it gets lucky rather than right.
    """
    target = " ".join(f"--data {shlex.quote(str(data))}" for data in (args.data or []))
    if not target and args.endpoint:
        target = f"--endpoint {shlex.quote(str(args.endpoint))}"
    print()
    print("Which profile fits this dataset? Ask the profile owner, do not guess:")
    print(f"  la-profile recommend {target}".rstrip())


def _report_completeness(adapter: Any) -> None:
    """Say whether what loaded accounts for everything the project declares.

    Reported at connect time on purpose. Learning that a merge dropped a whole source
    after building an answer on it is the expensive way to find out.
    """
    paths = getattr(adapter, "paths", None)
    if not paths:  # an endpoint has no manifest to check against
        return
    assessment = completeness.assess(
        paths,
        getattr(adapter, "graph_names", ()),
        known_extensions=tuple(discover.DEFAULT_EXTENSIONS),
    )
    notes = assessment.notes()
    if not notes:
        return
    print()
    for note in notes:
        print(f"  warning: {note}", file=sys.stderr)


def cmd_datasets(args: argparse.Namespace) -> int:
    start = Path(args.directory).expanduser() if args.directory else Path.cwd()
    if not start.is_dir():
        print(f"Error: not a directory: {start}", file=sys.stderr)
        return ERROR

    missing = discover.missing_from_env()
    if missing:
        print(
            f"warning: ${discover.ENV_DATA} names files that do not exist: "
            + ", ".join(str(path) for path in missing),
            file=sys.stderr,
        )
    roots = discover.search_roots(start)
    try:
        found = discover.find(
            start,
            include_fixtures=args.include_fixtures,
            with_git=not args.no_git,
            extensions=args.extension,
            directories=args.search_dir,
            max_depth=args.max_depth,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return REFUSED
    if not found:
        # Say exactly what was looked for, so a negative result is explainable rather
        # than mysterious. An unexplained "nothing found" is what sends an agent off to
        # run its own filesystem search - and every one of these lines corresponds to a
        # flag that can widen the search, so the next move is in the output.
        scanned = ", ".join(sorted(
            discover._requested_extensions(args.extension)
        ))
        directories = discover._requested_directories(args.search_dir)
        depth = discover._requested_depth(args.max_depth)
        print(f"No RDF graph found under {start}")
        print(f"\nSearched {', '.join(str(root) for root in roots)}")
        print("  in:         " + ", ".join(directories) + "   (--search-dir DIR)")
        print(f"  depth:      {depth} below each   (--max-depth N)")
        print(f"  extensions: {scanned}   (--extension EXT)")
        print(
            "  not scanned: "
            + ", ".join(sorted(discover.AMBIGUOUS_EXTENSIONS))
            + " (loadable, but usually not RDF; pass --extension json to include them)"
        )
        print("\nNothing is selected. Set $LINKED_ARCHI_DATA or pass --data explicitly.")
        return REFUSED

    print(f"{len(found)} candidate(s) under {', '.join(str(root) for root in roots)}\n")
    for candidate in found:
        shown = _shortest_relative(candidate.path, roots)
        if candidate.git is not None and candidate.git.committed:
            when = f"{candidate.git.committed} (commit)"
        else:
            when = f"{datetime.datetime.fromtimestamp(candidate.modified):%Y-%m-%d}"
        marker = "*" if candidate.origin == "env" else " "
        print(
            f"{marker} {str(shown):<46} {candidate.size_bytes // 1024:>6} KiB  "
            f"{when:<19}  graphs: {'yes' if candidate.carries_graphs else 'no'}"
        )
        if candidate.git is not None:
            bits = [part for part in (candidate.git.ref, candidate.git.commit) if part]
            if bits:
                state = "uncommitted changes" if candidate.git.dirty else (
                    "untracked" if candidate.git.untracked else "clean"
                )
                print(f"    git: {' @ '.join(bits)}, {state}")
        for caveat in candidate.caveats():
            print(f"    caveat: {caveat}")
    # Deliberately a placeholder, not found[0]. Printing the first candidate directly
    # after saying nothing was selected is an invitation to treat "newest" as "correct",
    # and the ordering signal here is weak: mtime is meaningless after a fresh clone, and
    # even the commit date says when a graph changed, not whether it is the right one.
    print("\nNothing is selected for you. Confirm which candidate is current, then:")
    owner_cli = Path(__file__).resolve().parents[1] / "la-connect"
    print(f'  "{sys.executable}" "{owner_cli}" connect --data "<PATH from the list above>"')
    if len(found) > 1:
        print("\nRepeat --data to merge several files into one store.")
    return OK


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Where this owner is, what it can load, and what execution needs."""
    from .adapters.base import _companion

    root = Path(__file__).resolve().parents[1]
    print("linked-archi-connect")
    print(f"  owner root:   {root.parent}")
    print(f"  command:      {root / 'la-connect'}")
    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    print(f"  skills dir:   {configured or '(unset; resolving beside this skill)'}")
    print(f"  dataset env:  {os.environ.get(discover.ENV_DATA) or '(unset)'}")
    missing = discover.missing_from_env()
    if missing:
        print("    warning:    " + ", ".join(str(path) for path in missing) + " do not exist")
    print(f"  scans:        {', '.join(sorted(discover.DEFAULT_EXTENSIONS))}")
    print(
        f"  on request:   {', '.join(sorted(discover.AMBIGUOUS_EXTENSIONS))} "
        "(loadable, ambiguous, so --extension is needed)"
    )

    ok = True
    try:
        import pyoxigraph  # noqa: F401
        print("  pyoxigraph    present (local RDF files)")
    except ModuleNotFoundError:
        ok = False
        print("  pyoxigraph    MISSING - pip install pyoxigraph (endpoints still work)")

    try:
        print(f"  la-query      {_companion('linked-archi-query', 'la-query')}")
        print("                enforces read-only policy before any execution")
    except AdapterError as exc:
        ok = False
        print(f"  la-query      MISSING - {exc}")
    print(
        "\ndatasets and connect work alone; executing a query delegates read-only\n"
        "enforcement to the query owner. Resolution order is $LINKED_ARCHI_SKILLS_DIR\n"
        "(authoritative), then the sibling directory beside this skill, then PATH -\n"
        "never a filesystem search."
    )
    return OK if ok else REFUSED


def _shortest_relative(path: Path, roots: Sequence[Path]) -> Path:
    best = path
    for root in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if best == path or len(relative.parts) < len(best.parts):
            best = relative
    return best


def _machine_request() -> dict[str, Any]:
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"machine input is not valid JSON: {exc}") from exc
    if (
        not isinstance(request, dict)
        or type(request.get("schema_version")) is not int
        or request["schema_version"] != 1
    ):
        raise AdapterError("machine input requires schema_version=1")
    target = request.get("target")
    if not isinstance(target, dict):
        raise AdapterError("machine target must be an object")
    unknown = set(target).difference(
        {"data", "endpoint", "timeout_ms", "lenient", "store"}
    )
    if unknown:
        raise AdapterError(
            "machine target contains unknown fields: " + ", ".join(sorted(unknown))
        )
    data = target.get("data", [])
    endpoint = target.get("endpoint")
    timeout_ms = target.get("timeout_ms", 30000)
    lenient = target.get("lenient", False)
    store = target.get("store")
    if (
        not isinstance(data, list)
        or any(not isinstance(path, str) or not path.strip() for path in data)
    ):
        raise AdapterError("machine target data must be a string array")
    if endpoint is not None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise AdapterError("machine target endpoint must be a non-empty string or null")
        validate_endpoint_url(endpoint)
    if (
        not isinstance(timeout_ms, int)
        or isinstance(timeout_ms, bool)
        or timeout_ms <= 0
    ):
        raise AdapterError("machine target timeout_ms must be a positive integer")
    if not isinstance(lenient, bool):
        raise AdapterError("machine target lenient must be a boolean")
    # Null means "defer to the environment", which is what an absent field has always
    # meant here. A present-but-wrong value is refused by name rather than ignored.
    if store is not None and (not isinstance(store, str) or store not in STORE_MODES):
        raise AdapterError(
            "machine target store must be null or one of: " + ", ".join(STORE_MODES)
        )
    if bool(data) == bool(endpoint):
        raise AdapterError("machine target requires exactly one of data or endpoint")
    request["target"] = {
        "data": data,
        "endpoint": endpoint,
        "timeout_ms": timeout_ms,
        "lenient": lenient,
        "store": store,
    }
    return request


def cmd_machine_execute(_args: argparse.Namespace) -> int:
    request = _machine_request()
    query = request.get("query")
    if not isinstance(query, str) or not query.strip():
        raise AdapterError("machine input requires a non-empty query")
    target = request.get("target") or {}
    validate_queries_readonly([query])
    with _open(target) as adapter:
        raw = adapter.execute(query, timeout_ms=target.get("timeout_ms"))
    print(json.dumps(raw.as_contract(), ensure_ascii=False))
    return OK


def cmd_machine_execute_many(_args: argparse.Namespace) -> int:
    request = _machine_request()
    queries = request.get("queries")
    if (
        not isinstance(queries, list)
        or not queries
        or any(not isinstance(query, str) or not query.strip() for query in queries)
    ):
        raise AdapterError("machine input requires a non-empty queries string array")
    target = request.get("target") or {}
    validate_queries_readonly(queries)
    with _open(target) as adapter:
        results = adapter.execute_many(queries, timeout_ms=target.get("timeout_ms"))
    print(json.dumps({
        "schema_version": 1,
        "results": [result.as_contract() for result in results],
    }, ensure_ascii=False))
    return OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="la-connect",
        description="Discover and attach RDF datasets, and report what actually loaded.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    datasets = commands.add_parser(
        "datasets",
        help="report candidate graph files",
        description=(
            "List candidates and select none of them. Choosing is a decision for the "
            "user, because answering from a file nobody chose is the one failure that "
            "cannot be detected afterwards: the result looks sound and cites the wrong "
            "architecture."
        ),
    )
    datasets.add_argument(
        "directory",
        nargs="?",
        help="where to look (default: the working directory, plus its git root)",
    )
    datasets.add_argument(
        "--include-fixtures",
        action="store_true",
        help="also list committed test data, which is a demonstration and not a finding",
    )
    datasets.add_argument("--no-git", action="store_true", help="skip git provenance lookup")
    datasets.add_argument(
        "--search-dir",
        action="append",
        default=None,
        metavar="DIR",
        help=(
            "scan this subdirectory under each root instead of the conventional list "
            "(repeatable, relative, `.` always included). Default: "
            + ", ".join(discover.SEARCH_DIRS)
        ),
    )
    datasets.add_argument(
        "--max-depth",
        type=int,
        default=None,
        metavar="N",
        help=(
            f"how far below each directory to look (default: "
            f"{discover.DEFAULT_MAX_DEPTH}, ceiling {discover.MAX_MAX_DEPTH}). Setting it "
            "also deepens the scan of the root itself"
        ),
    )
    datasets.add_argument(
        "--extension",
        action="append",
        default=None,
        metavar="EXT",
        help=(
            "scan this suffix instead of the defaults (repeatable). Use it for the "
            "loadable-but-ambiguous ones: "
            + ", ".join(sorted(discover.AMBIGUOUS_EXTENSIONS))
        ),
    )
    datasets.set_defaults(func=cmd_datasets)
    doctor = commands.add_parser(
        "doctor",
        help="report this owner's location and companions",
        description=(
            "Owner root, resolved command, scanned versus ambiguous extensions, "
            "pyoxigraph, and every companion this skill can reach. Run it instead of "
            "searching the filesystem."
        ),
    )
    doctor.set_defaults(func=cmd_doctor)
    connect = commands.add_parser(
        "connect",
        help="load and describe a target",
        description=(
            "Attach a dataset and report what actually arrived: quads, named graphs, "
            "which files loaded, and any source the merge appears to be missing. Run it "
            "before querying, because an empty graph and a graph without your elements "
            "look identical from inside a query."
        ),
    )
    _add_target_args(connect)
    connect.set_defaults(func=cmd_connect)
    machine = commands.add_parser(
        "_machine",
        help=_MACHINE_HELP,
        description=_MACHINE_DESCRIPTION,
    )
    machine_sub = machine.add_subparsers(dest="machine_command", required=True)
    execute = machine_sub.add_parser(
        "execute",
        help="execute one read-only query against one target",
        description=(
            'Request {"schema_version": 1, "query": "...", "target": {...}}, where target '
            "is exactly connect target version 1. Every query is sent to the query "
            "owner's read-only lint first; if that companion is missing, this fails "
            "rather than executing unchecked."
        ),
    )
    execute.set_defaults(func=cmd_machine_execute)
    execute_many = machine_sub.add_parser(
        "execute-many",
        help="execute several queries against one opened target",
        description=(
            'As execute, with "queries" instead of "query". The target is opened once, so '
            "a local file is parsed once - which is why profile verification can afford a "
            "dozen probes."
        ),
    )
    execute_many.set_defaults(func=cmd_machine_execute_many)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (AdapterError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ERROR
    except BrokenPipeError:
        return OK
    except KeyboardInterrupt:
        return ERROR


if __name__ == "__main__":
    raise SystemExit(main())
