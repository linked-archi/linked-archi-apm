"""Profile owner CLI and normalized profile subprocess contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from .derive import DeriveError, derive_profile
from .profile import (
    DEFAULT_PROFILE,
    PROFILE_DIR,
    ProfileError,
    emit_fix_profile,
    format_findings,
    load_profile,
    observe_dataset,
    recommend_profile,
    verify_against_dataset,
    worst_severity,
)

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
    "sibling skills and automation, not a private entry point: skills/linked-archi-profile/references/machine-contract.md"
)

REQUIRED_CONNECT_SKILL = "linked-archi-connect"


class CompanionError(RuntimeError):
    pass


_RAW_RESULT_KEYS = {
    "schema_version", "form", "variables", "rows", "boolean", "triples",
    "elapsed_ms", "dataset_id", "named_graphs_present", "description",
}


def _validate_raw_result(raw: object) -> dict[str, Any]:
    """Fail closed before a transport result can become a profile finding."""
    if not isinstance(raw, dict):
        raise CompanionError("linked-archi-connect returned a malformed raw result: expected an object")
    missing = sorted(_RAW_RESULT_KEYS.difference(raw))
    if missing:
        raise CompanionError(
            "linked-archi-connect returned a malformed raw result: missing "
            + ", ".join(missing)
        )
    if (
        not isinstance(raw["schema_version"], int)
        or isinstance(raw["schema_version"], bool)
        or raw["schema_version"] != 1
    ):
        raise CompanionError("linked-archi-connect returned an unsupported raw-result schema_version")

    form = raw["form"]
    variables = raw["variables"]
    rows = raw["rows"]
    boolean = raw["boolean"]
    triples = raw["triples"]
    if form not in {"SELECT", "ASK", "CONSTRUCT"}:
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid form")
    if (
        not isinstance(variables, list)
        or any(not isinstance(item, str) or not item for item in variables)
        or len(set(variables)) != len(variables)
    ):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid variables")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid rows")
    variable_names = set(variables)
    if any(
        set(row) != variable_names
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in row.items()
        )
        for row in rows
    ):
        raise CompanionError(
            "linked-archi-connect returned a malformed raw result: invalid SELECT bindings"
        )
    if boolean is not None and not isinstance(boolean, bool):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid boolean")
    if triples is not None and not isinstance(triples, str):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid triples")
    if (
        not isinstance(raw["elapsed_ms"], int)
        or isinstance(raw["elapsed_ms"], bool)
        or raw["elapsed_ms"] < 0
    ):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid elapsed_ms")
    if not isinstance(raw["dataset_id"], str) or not raw["dataset_id"].strip():
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid dataset_id")
    if raw["named_graphs_present"] is not None and not isinstance(raw["named_graphs_present"], bool):
        raise CompanionError(
            "linked-archi-connect returned a malformed raw result: invalid named_graphs_present"
        )
    if not isinstance(raw["description"], str):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid description")

    if form == "SELECT" and (boolean is not None or triples is not None):
        raise CompanionError("linked-archi-connect returned an inconsistent SELECT result")
    if form == "ASK" and (variables or rows or not isinstance(boolean, bool) or triples is not None):
        raise CompanionError("linked-archi-connect returned an inconsistent ASK result")
    if form == "CONSTRUCT" and (variables or rows or boolean is not None or not isinstance(triples, str)):
        raise CompanionError("linked-archi-connect returned an inconsistent CONSTRUCT result")
    return raw


#: This skill's own name, used only to phrase the adjacency hint in an error.
OWN_SKILL = "linked-archi-profile"


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
        raise CompanionError(
            f"Missing required skill: {skill} under explicit "
            f"LINKED_ARCHI_SKILLS_DIR={configured}."
        )
    candidate = Path(__file__).resolve().parents[2].parent / skill / "scripts" / executable
    if candidate.is_file():
        return candidate
    on_path = shutil.which(executable)
    if on_path:
        return Path(on_path)
    raise CompanionError(
        f"Missing required skill: {skill}. Install it beside {OWN_SKILL}, put "
        f"{executable} on PATH, or set LINKED_ARCHI_SKILLS_DIR."
    )


def _connect_executable() -> Path:
    return _companion(REQUIRED_CONNECT_SKILL, "la-connect")


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Where this owner is, what it bundles, and what verification needs."""
    root = Path(__file__).resolve().parents[1]
    profiles = root.parent / "assets" / "profiles"
    print(OWN_SKILL)
    print(f"  owner root:   {root.parent}")
    print(f"  command:      {root / 'la-profile'}")
    bundled = sorted(path.name for path in profiles.glob("*.yaml"))
    examples = sorted(path.name for path in (profiles / "examples").glob("*.yaml"))
    print(f"  profiles:     {len(bundled) + len(examples)} in {profiles}")
    print(f"    bundled:    {', '.join(bundled) or 'none'}")
    print(f"    examples:   {', '.join(examples) or 'none'}")
    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    print(f"  skills dir:   {configured or '(unset; resolving beside this skill)'}")

    ok = True
    try:
        import yaml  # noqa: F401
        print("  PyYAML        present (profiles are YAML)")
    except ModuleNotFoundError:
        ok = False
        print("  PyYAML        MISSING - pip install PyYAML")

    for skill, executable, why in (
        (REQUIRED_CONNECT_SKILL, "la-connect", "probes the dataset during verify"),
        ("linked-archi-query", "la-query", "lints every probe before it runs"),
    ):
        try:
            print(f"  {executable:<12}  {_companion(skill, executable)}  ({why})")
        except CompanionError as exc:
            ok = False
            print(f"  {executable:<12}  MISSING - {exc}")
    print(
        "\nlist, show, resolve and derive work alone. verify needs the connect and query\n"
        "owners. Resolution order is $LINKED_ARCHI_SKILLS_DIR (authoritative), then the\n"
        "sibling directory beside this skill, then PATH - never a filesystem search."
    )
    return OK if ok else REFUSED


def _target(args: argparse.Namespace) -> dict[str, Any]:
    data = list(args.data)
    if not data and not args.endpoint:
        raw = os.environ.get("LINKED_ARCHI_DATA", "")
        data = [part for part in raw.split(os.pathsep) if part]
    return {
        "data": data,
        "endpoint": args.endpoint,
        "timeout_ms": args.timeout_ms,
        "lenient": args.lenient,
    }


#: Ceiling on a local probe batch, in seconds. `none` opts out.
#:
#: The same variable the query owner reads, shared by convention rather than by importing
#: code - as with `LINKED_ARCHI_STATE_DIR`. Both owners document it.
ENV_LOCAL_DEADLINE = "LINKED_ARCHI_LOCAL_DEADLINE_S"
DEFAULT_LOCAL_DEADLINE_S = 300.0


def _local_deadline() -> float | None:
    raw = os.environ.get(ENV_LOCAL_DEADLINE)
    if raw is None or not raw.strip():
        return DEFAULT_LOCAL_DEADLINE_S
    text = raw.strip().lower()
    if text in {"none", "0", "off"}:
        return None
    try:
        seconds = float(text)
    except ValueError:
        raise CompanionError(
            f"{ENV_LOCAL_DEADLINE} must be a number of seconds, or 'none' to opt out; "
            f"got {raw!r}"
        ) from None
    if seconds <= 0:
        raise CompanionError(f"{ENV_LOCAL_DEADLINE} must be positive; got {raw!r}")
    return seconds


def _companion_deadline(target: dict[str, Any], query_count: int) -> float | None:
    timeout_ms = target.get("timeout_ms", 30000)
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
        raise CompanionError("target timeout_ms must be a positive integer")
    if target.get("data") and not target.get("endpoint"):
        # A finite ceiling, where this used to impose none at all. pyoxigraph still has no
        # query timeout, so the bound can only be the process boundary - see the query
        # owner's `_companion_deadline` for the field failure that settled this.
        #
        # No memory watchdog here, unlike the query owner, and that is a judgement rather
        # than an omission: these are ASK and COUNT probes with no ORDER BY and no
        # materialised result, so they do not exhibit the runaway growth a template
        # traversal can. If a probe ever does, the bound belongs here too.
        return _local_deadline()
    if not target.get("endpoint"):
        return 120.0
    # One 30s lint contract plus process startup/result serialization margin.
    return 60.0 + max(1, query_count) * timeout_ms / 1000.0


def _execute_many(target: dict[str, Any], queries: list[str]) -> list[dict[str, Any]]:
    request = {"schema_version": 1, "target": target, "queries": queries}
    deadline = _companion_deadline(target, len(queries))
    try:
        done = subprocess.run(
            [sys.executable, str(_connect_executable()), "_machine", "execute-many"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=deadline,
        )
    except subprocess.TimeoutExpired as exc:
        detail = f"{deadline:g}s companion deadline" if deadline is not None else "companion process"
        raise CompanionError(
            f"linked-archi-connect execute-many exceeded its {detail}"
        ) from exc
    if done.returncode != 0:
        raise CompanionError(done.stderr.strip() or "linked-archi-connect execution failed")
    try:
        response = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise CompanionError("linked-archi-connect returned invalid JSON") from exc
    if (
        not isinstance(response, dict)
        or type(response.get("schema_version")) is not int
        or response["schema_version"] != 1
    ):
        raise CompanionError("linked-archi-connect returned unsupported schema_version")
    results = response.get("results")
    if not isinstance(results, list) or len(results) != len(queries):
        raise CompanionError("linked-archi-connect returned the wrong number of results")
    return [_validate_raw_result(result) for result in results]


class _ConnectProbe:
    def __init__(self, target: dict[str, Any]) -> None:
        self.target = target
        self.description = ""
        #: The dataset identity connect reported, so a clean verification can be recorded
        #: against the same identity a later query will see.
        self.dataset_id = ""
        #: Whether the backend parses SPARQL 1.2, which decides whether a probe may look
        #: inside an `rdf:reifies` triple term with `<<( s p o )>>`.
        #:
        #: Read off the target rather than from the adapter, because probes go through
        #: `_execute_many` as a subprocess and there is no object to ask. Local data means
        #: pyoxigraph, which parses it; an endpoint is somebody else's engine and is assumed
        #: not to, since the pattern is a parse error rather than an empty result on 1.1 and
        #: one bad query fails the whole batch. An operator who knows better says so by
        #: claiming `capabilities.rdf_reifies` in the profile.
        self.sparql_12 = bool(target.get("data")) and not target.get("endpoint")

    def execute_many(self, queries: list[str]) -> list[dict[str, Any]]:
        results = _execute_many(self.target, queries)
        if results:
            self.description = str(results[0].get("description") or "")
            self.dataset_id = str(results[0].get("dataset_id") or "")
        return results


def cmd_list(_args: argparse.Namespace) -> int:
    found = sorted(PROFILE_DIR.glob("*.yaml")) + sorted((PROFILE_DIR / "examples").glob("*.yaml"))
    if not found:
        print(f"No profiles in {PROFILE_DIR}", file=sys.stderr)
        return ERROR
    for path in found:
        profile = load_profile(path)
        print(f"{profile.name:26} {str(path.relative_to(PROFILE_DIR)):34} {profile.description[:70]}")
    return OK


def cmd_show(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    print(json.dumps(profile.as_dict(), indent=2, ensure_ascii=False) if args.json else profile.summary())
    return OK


def cmd_resolve(args: argparse.Namespace) -> int:
    print(json.dumps(load_profile(args.profile).resolved_snapshot(), indent=2, ensure_ascii=False))
    return OK


def cmd_machine_resolve(_args: argparse.Namespace) -> int:
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"machine input is not valid JSON: {exc}") from exc
    if (
        not isinstance(request, dict)
        or type(request.get("schema_version")) is not int
        or request["schema_version"] != 1
    ):
        raise ProfileError("machine input requires a JSON object with schema_version=1")
    if "profile" in request:
        reference = request["profile"]
        if not isinstance(reference, str) or not reference.strip():
            raise ProfileError("machine profile must be a non-empty string when provided")
    else:
        reference = DEFAULT_PROFILE
    print(json.dumps(load_profile(reference).resolved_snapshot(), ensure_ascii=False))
    return OK


def cmd_derive(args: argparse.Namespace) -> int:
    derivation = derive_profile(
        args.name, base_iri=args.base_iri or "", type_mapping=args.type_mapping,
        metamodel=args.metamodel, notation=args.notation, extends=args.extends,
    )
    if args.output:
        written = derivation.write(args.output)
        print(f"Draft profile written to {written}")
        owner_cli = Path(__file__).resolve().parents[1] / "la-profile"
        print(
            f'Next: "{sys.executable}" "{owner_cli}" verify '
            f'--profile "{written}" --data <your>.trig'
        )
    else:
        print(derivation.to_yaml(), end="")
    return OK


def cmd_recommend(args: argparse.Namespace) -> int:
    """Name a starting profile from the dataset's measured shape.

    The alternative, observed in the field, is trying candidate profiles and interpreting
    each one's warnings - which is slow and rewards whichever profile happens to warn least
    rather than the one that fits.
    """
    probe = _ConnectProbe(_target(args))
    observations = observe_dataset(probe)
    recommendation = recommend_profile(observations)
    if probe.description:
        print(probe.description)
        print()
    print("observed")
    for observation in recommendation.observations:
        print(observation)
    print()
    print(f"recommended profile: {recommendation.profile}")
    for reason in recommendation.reasons:
        print(f"  - {reason}")
    print()
    for caveat in recommendation.caveats:
        print(f"  note: {caveat}")
    target = " ".join(
        f"--data {shlex.quote(str(data))}" for data in (args.data or [])
    ) or (f"--endpoint {shlex.quote(str(args.endpoint))}" if args.endpoint else "")
    print()
    print("next:")
    print(f"  la-profile verify --profile {recommendation.profile} {target}".rstrip())
    return OK


def _fix_command(args: argparse.Namespace, profile: Any) -> str:
    """The exact command that turns this drift into a fitting profile.

    Reconstructed from the invocation rather than described in prose, because the point is
    that acting on drift is one copy-paste instead of an editing exercise performed in the
    middle of an investigation.
    """
    parts = ["la-profile", "verify", "--profile", shlex.quote(str(args.profile))]
    for data in args.data or []:
        parts += ["--data", shlex.quote(str(data))]
    if args.endpoint:
        parts += ["--endpoint", shlex.quote(str(args.endpoint))]
    if args.lenient:
        parts.append("--lenient")
    parts += ["--emit-fix", ">", f"{profile.name}-fitted.yaml"]
    return " ".join(parts)


def cmd_verify(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    probe = _ConnectProbe(_target(args))
    findings = verify_against_dataset(profile, probe)
    # With --emit-fix, stdout carries the generated profile and nothing else, so
    # `> acme.yaml` produces a usable file. The report still goes to the operator.
    report = sys.stderr if args.emit_fix else sys.stdout
    if probe.description:
        print(probe.description, file=report)
        print(file=report)
    failed = worst_severity(findings) == "error"
    if not failed:
        _record_verification(profile, probe.dataset_id)

    shown = findings if args.all else [f for f in findings if f.severity != "info"]
    if not shown:
        print(
            f"{len(findings)} check(s), no drift: the profile matches the dataset.",
            file=report,
        )
    else:
        print(format_findings(shown, total=len(findings)), file=report)

    generated = emit_fix_profile(profile, findings)
    if args.emit_fix:
        if generated is None:
            print(
                "\nNothing to generate: no capability claim is contradicted by this "
                "dataset. Unused roles and missing graph roles are reported above but "
                "are not mechanically fixable - see the notes in the findings.",
                file=report,
            )
        else:
            sys.stdout.write(generated)
    elif generated is not None:
        print(
            "\nA fitting profile can be generated from the drift above:\n"
            f"  {_fix_command(args, profile)}\n"
            "It `extends` this profile and overrides only the observed corrections. "
            "Read it before using it.",
            file=report,
        )
    return REFUSED if failed else OK


#: Written here, read by the query owner, which warns when a pair was never checked.
#: A path convention rather than shared code, so neither skill imports the other. The
#: query owner documents the same two constants.
STATE_DIR_ENV = "LINKED_ARCHI_STATE_DIR"
DEFAULT_STATE_DIR = Path("~/.cache/linked-archi/verified")


def _record_verification(profile: Any, dataset_id: str | None) -> None:
    """Note that this (dataset, profile, version) verified without errors.

    Best effort, and broadly guarded on purpose: recording a marker is a convenience for a
    later query, so no failure here may turn a successful verification into a failed
    command. An earlier version raised on a renamed attribute and took `verify` down with
    it, which is precisely the trade this guard exists to prevent.
    """
    if not dataset_id or not dataset_id.strip():
        return
    # Keyed on the snapshot FINGERPRINT, not the declared version. A verification is a
    # statement about what this profile currently says; the fingerprint changes whenever
    # that changes, whereas the version changes only when someone remembers to bump it.
    key = f"{dataset_id}\n{profile.name}\n{profile.resolved_snapshot()['fingerprint']}"
    configured = os.environ.get(STATE_DIR_ENV)
    base = Path(configured).expanduser() if configured else DEFAULT_STATE_DIR.expanduser()
    try:
        base.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        (base / f"{digest}.verified").write_text(key + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - a convenience marker must never fail the command
        pass


_PROFILE_HELP = (
    "profile to use, looked up in this order: a path if it looks like one, then a "
    "bundled name, then examples/<name> (default: {default})"
)


def _profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        metavar="NAME_OR_PATH",
        help=_PROFILE_HELP.format(default=DEFAULT_PROFILE),
    )


def _target_args(parser: argparse.ArgumentParser) -> None:
    """The dataset to check the profile against. Needs the connect companion."""
    parser.add_argument(
        "--data",
        action="append",
        default=[],
        metavar="FILE",
        help=(
            "local RDF file to probe (repeatable; files merge into one dataset). "
            "Omit when $LINKED_ARCHI_DATA is set (env: LINKED_ARCHI_DATA)"
        ),
    )
    parser.add_argument(
        "--endpoint",
        metavar="URL",
        help="HTTPS SPARQL query endpoint instead of local files; not combinable with --data",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        metavar="MS",
        help="endpoint request deadline (default: 30000). Ignored for local files",
    )
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="relax RDF parsing of local files. Never relaxes query safety",
    )


_EPILOG = """\
Examples:
  la-profile list
  la-profile show --profile linked-archi-default
  la-profile verify --profile linked-archi-default --data graph.trig
  la-profile derive acme --type-mapping config/type-mapping-acme.yml \\
      --base-iri https://acme.example/la/ -o profiles/acme.yaml
  printf '{"schema_version":1,"profile":"linked-archi-default"}' | la-profile _machine resolve

Exit codes: 0 ok, 1 drift found by verify (a claim in the profile is false about the
dataset), 2 error. Exit 1 is a finding: read the report, then fix the profile or the
dataset. Nothing else here uses exit 1.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="la-profile",
        description="Resolve and verify the graph profile that tells queries what a dataset calls things.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser(
        "list",
        help="bundled profiles, with what each describes",
        description="Start here. Works alone: no dataset and no companion skill needed.",
    )
    listing.set_defaults(func=cmd_list)
    show = commands.add_parser(
        "show",
        help="one profile's claims, readably",
        description=(
            "Graph layout, role bindings and capabilities as the profile states them - "
            "claims about a dataset, not yet checked against one."
        ),
    )
    _profile_arg(show)
    show.add_argument(
        "--json", action="store_true",
        help="emit the resolved snapshot as JSON instead of a readable summary",
    )
    show.set_defaults(func=cmd_show)
    resolve = commands.add_parser(
        "resolve",
        help="the fully merged profile as JSON",
        description=(
            "`extends` applied, roles expanded to absolute IRIs. The same object the "
            "machine contract returns, indented. See references/machine-contract.md."
        ),
    )
    _profile_arg(resolve)
    resolve.set_defaults(func=cmd_resolve)
    verify = commands.add_parser(
        "verify",
        help="check a profile's claims against a real dataset",
        description=(
            "The step that matters: a profile is a set of claims, and claims decay. "
            "error = a claim is false, warning = a bound role is unused here, ok = "
            "confirmed. Exits 1 when any error is found, so it is safe to gate on. "
            "Needs linked-archi-connect and linked-archi-query."
        ),
    )
    _profile_arg(verify)
    _target_args(verify)
    verify.add_argument(
        "--all", action="store_true",
        help="report every check, including the ones that passed",
    )
    verify.add_argument(
        "--emit-fix", action="store_true",
        help=(
            "write a child profile that extends this one and overrides only the "
            "capability claims this dataset contradicts. The profile goes to stdout and "
            "the report to stderr, so `> acme.yaml` gives a usable file. Read it before "
            "using it: an observed capability means your converter ran with a flag the "
            "parent does not assume"
        ),
    )
    verify.set_defaults(func=cmd_verify)
    recommend = commands.add_parser(
        "recommend",
        help="name a starting profile from the dataset's shape",
        description=(
            "Measure the dataset and name a bundled profile that fits, with the evidence "
            "for it. Recommends, never applies: the output ends with the verify command "
            "rather than a changed state. Needs linked-archi-connect and "
            "linked-archi-query, and reads the dataset through the published "
            "Linked.Archi vocabulary - for a custom ontology use `derive` instead."
        ),
    )
    _target_args(recommend)
    recommend.set_defaults(func=cmd_recommend)
    derive = commands.add_parser(
        "derive",
        help="draft a profile from a converter mapping or a metamodel",
        description=(
            "Derive rather than author: the information already exists in the artifacts "
            "that produced the graph. The result is a DRAFT - optional roles and "
            "direct_rel_triples are never guessed - so it always ends with verify."
        ),
    )
    derive.add_argument("name", help="profile name to write, e.g. acme")
    derive.add_argument(
        "--type-mapping", metavar="FILE",
        help="converter type-mapping YAML that produced the graph",
    )
    derive.add_argument(
        "--metamodel", metavar="FILE",
        help="published arch:Metamodel manifest (RDF)",
    )
    derive.add_argument(
        "--base-iri", metavar="IRI",
        help="instance IRI base recorded in the draft, e.g. https://acme.example/la/",
    )
    derive.add_argument(
        "--notation", metavar="SLUG",
        help="notation slug appearing in minted IRIs, e.g. cp",
    )
    derive.add_argument(
        "--extends", default="linked-archi-default.yaml", metavar="PROFILE",
        help="profile the draft inherits from (default: linked-archi-default.yaml)",
    )
    derive.add_argument(
        "-o", "--output", metavar="FILE",
        help="write the draft here instead of stdout",
    )
    derive.set_defaults(func=cmd_derive)
    doctor = commands.add_parser(
        "doctor",
        help="report this owner's location and companions",
        description=(
            "Owner root, resolved command, bundled and example profiles, PyYAML, and "
            "every companion this skill can reach. Run it instead of searching the "
            "filesystem."
        ),
    )
    doctor.set_defaults(func=cmd_doctor)
    machine = commands.add_parser(
        "_machine",
        help=_MACHINE_HELP,
        description=_MACHINE_DESCRIPTION,
    )
    machine_sub = machine.add_subparsers(dest="machine_command", required=True)
    machine_resolve = machine_sub.add_parser(
        "resolve",
        help="resolve a profile reference to its full snapshot",
        description=(
            'Request {"schema_version": 1, "profile": "<reference>"}; the profile key is '
            "optional and defaults to linked-archi-default. Response is the merged "
            "snapshot with roles as absolute IRI lists."
        ),
    )
    machine_resolve.set_defaults(func=cmd_machine_resolve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except CompanionError as exc:
        print(f"Error: {exc}", file=sys.stderr); return ERROR
    except (ProfileError, DeriveError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return ERROR
    except BrokenPipeError:
        return OK
    except KeyboardInterrupt:
        return ERROR


if __name__ == "__main__":
    raise SystemExit(main())
