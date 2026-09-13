"""`la-analyse`: plan an investigation, bundle its evidence, render the answer.

This owner **never executes a query**. There is no dataset access, no SPARQL and no transport
in this package, and the packaging suite asserts their absence. Template metadata is read by
running the query owner's documented `catalog dump` in a subprocess: a contract, not a
coupling.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from .bundle import CLAIM_CLASSES, DEFAULT_STATE_DIR, STATE_DIR_ENV, build_bundle, render_markdown
from .patterns import AnalyseError, load_patterns, pattern_summary, resolve_mode
from .plan import DEFAULT_BUDGET, build_plan

OK, REFUSED, ERROR = 0, 1, 2

#: This skill's own name, used only to phrase the adjacency hint in an error.
OWN_SKILL = "linked-archi-analyse"

REQUIRED_QUERY_SKILL = "linked-archi-query"

#: `_machine` is machine-facing, NOT private. The underscore says "not for a human to
#: type", and nothing more: the contract is documented, versioned, and depended on across
#: process boundaries by sibling skills. Hiding it from `--help` while three skills call it
#: was the worst of both worlds - visible in the usage line as `==SUPPRESS==` and explained
#: nowhere.
_MACHINE_HELP = "versioned JSON contract for automation (see references/machine-contract.md)"
_MACHINE_DESCRIPTION = (
    "Read one JSON object on stdin, write one JSON object on stdout. Diagnostics go to "
    "stderr. schema_version is checked exactly. This is a stable, documented boundary for "
    "sibling skills and automation, not a private entry point: "
    "skills/linked-archi-analyse/references/machine-contract.md"
)


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
        raise AnalyseError(
            f"Missing required skill: {skill} under explicit "
            f"LINKED_ARCHI_SKILLS_DIR={configured}."
        )
    candidate = Path(__file__).resolve().parents[2].parent / skill / "scripts" / executable
    if candidate.is_file():
        return candidate
    on_path = shutil.which(executable)
    if on_path:
        return Path(on_path)
    raise AnalyseError(
        f"Missing required skill: {skill}. Install it beside {OWN_SKILL}, put "
        f"{executable} on PATH, or set LINKED_ARCHI_SKILLS_DIR."
    )


def _catalogue(profile: str | None) -> dict[str, Any] | None:
    """The query owner's catalogue, or ``None`` when that skill is not reachable.

    One `catalog dump` call rather than one `catalog show` per template, and the documented
    human command rather than a machine contract, because the JSON it emits is already
    versioned and this needs no new surface on the query owner.

    Degrades rather than fails: a plan without availability annotations is still an ordered
    plan, and the caller is told what is missing.
    """
    try:
        executable = _companion(REQUIRED_QUERY_SKILL, "la-query")
    except AnalyseError:
        return None
    command = [sys.executable, str(executable), "catalog", "dump"]
    if profile:
        command += ["--profile", profile]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    try:
        document = json.loads(done.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        return None
    return document


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def cmd_plan(args: argparse.Namespace) -> int:
    patterns = load_patterns()
    if args.list_patterns:
        for entry in pattern_summary(patterns):
            print(f"{entry['pattern']:24} {entry['title']}")
            print(f"{'':24} triggers: {', '.join(entry['triggers'][:6])}")
        return OK
    if not args.question:
        raise AnalyseError("plan needs --question, or --list-patterns")

    pattern, ranked = resolve_mode(args.mode, args.question, patterns)
    plan = build_plan(
        args.question,
        pattern=pattern,
        ranked=ranked,
        catalogue=_catalogue(args.profile),
        profile=args.profile,
        data=args.data,
        endpoint=args.endpoint,
        budget=args.budget,
        steps_dir=args.steps_dir,
    )
    output = plan.as_dict() if args.json else plan.to_text()
    text = json.dumps(output, indent=2, ensure_ascii=False) if args.json else output
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        print(f"Wrote {target} ({len(plan.steps)} step(s))", file=sys.stderr)
    else:
        print(text, end="" if text.endswith("\n") else "\n")
    return OK


# ---------------------------------------------------------------------------
# bundle and render
# ---------------------------------------------------------------------------


def cmd_bundle(args: argparse.Namespace) -> int:
    bundle = build_bundle(
        args.step,
        question=args.question or "",
        findings_file=args.findings,
        dataset_revision=args.dataset_revision,
    )
    document = bundle.as_dict()
    text = render_markdown(document) if args.markdown else bundle.to_json()
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(
            f"Wrote {target} ({len(document['steps'])} step(s), "
            f"dataset {document['dataset']['id']}, profile {document['profile']['id']} "
            f"v{document['profile']['version']})",
            file=sys.stderr,
        )
    else:
        print(text)
    if not document["profile"]["verified"]:
        print(
            "caveat: this profile was never verified against this dataset. Settle it with "
            "`la-profile verify` - an unfitting profile fails silently.",
            file=sys.stderr,
        )
    if document["truncated"]:
        print(
            "caveat: a step was truncated, so any count in this bundle is a floor.",
            file=sys.stderr,
        )
    return OK


def cmd_render(args: argparse.Namespace) -> int:
    path = Path(args.bundle)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnalyseError(f"bundle not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AnalyseError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise AnalyseError(f"{path.name} is not a version 1 bundle")
    text = render_markdown(document)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"Wrote {target}", file=sys.stderr)
    else:
        print(text, end="")
    return OK


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(_args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[2]
    print(OWN_SKILL)
    print(f"  owner root:    {root}")
    print(f"  command:       {root / 'scripts' / 'la-analyse'}")
    try:
        patterns = load_patterns()
        print(f"  patterns:      {len(patterns)} ({', '.join(sorted(patterns))})")
    except AnalyseError as exc:
        print(f"  patterns:      MISSING - {exc}")
        return REFUSED

    state = os.environ.get(STATE_DIR_ENV)
    print(f"  state dir:     {state or f'(unset; {DEFAULT_STATE_DIR})'}")
    print("  executes:      nothing. This owner plans and bundles; la-query runs queries.")

    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    print(f"  skills dir:    {configured or '(unset; resolving beside this skill)'}")
    ok = True
    try:
        print(f"  la-query       {_companion(REQUIRED_QUERY_SKILL, 'la-query')} "
              "(executes every step; also annotates a plan with availability)")
    except AnalyseError:
        ok = False
        print("  la-query       MISSING - required to execute a plan, and to annotate one")
    for skill, executable, why in (
        ("linked-archi-profile", "la-profile", "resolve and verify the profile"),
        ("linked-archi-connect", "la-connect", "find and attach the dataset"),
        ("linked-archi-validate", "la-validate", "SHACL conformance, when that is the question"),
        ("linked-archi-source", "la-source", "acquire a graph that is not on disk yet"),
    ):
        try:
            print(f"  {executable:<14} {_companion(skill, executable)} ({why})")
        except AnalyseError:
            print(f"  {executable:<14} not found (optional here) - {why}")

    print(
        "\nResolution order is $LINKED_ARCHI_SKILLS_DIR (authoritative), then the sibling\n"
        "directory beside this skill, then PATH - never a filesystem search."
    )
    return OK if ok else REFUSED


# ---------------------------------------------------------------------------
# machine contract
# ---------------------------------------------------------------------------


def _machine_input(allowed: set[str], label: str) -> dict[str, Any]:
    try:
        raw = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise AnalyseError(f"machine input is not valid JSON: {exc}") from exc
    if (
        not isinstance(raw, dict)
        or type(raw.get("schema_version")) is not int
        or raw["schema_version"] != 1
    ):
        raise AnalyseError("machine input requires schema_version=1")
    unknown = set(raw) - allowed - {"schema_version"}
    if unknown:
        raise AnalyseError(
            f"machine {label} has unknown field(s): " + ", ".join(sorted(unknown))
        )
    return raw


def cmd_machine_plan(_args: argparse.Namespace) -> int:
    request = _machine_input(
        {"question", "mode", "profile", "data", "endpoint", "budget", "steps_dir"}, "plan"
    )
    question = request.get("question")
    if not isinstance(question, str) or not question.strip():
        raise AnalyseError("machine plan requires a non-empty question")
    data = request.get("data") or []
    if not isinstance(data, list) or any(not isinstance(item, str) for item in data):
        raise AnalyseError("machine plan data must be a string array")
    budget = request.get("budget", DEFAULT_BUDGET)
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise AnalyseError("machine plan budget must be a positive integer")
    patterns = load_patterns()
    pattern, ranked = resolve_mode(request.get("mode"), question, patterns)
    plan = build_plan(
        question,
        pattern=pattern,
        ranked=ranked,
        catalogue=_catalogue(request.get("profile")),
        profile=request.get("profile"),
        data=data,
        endpoint=request.get("endpoint"),
        budget=budget,
        steps_dir=request.get("steps_dir") or "steps",
    )
    print(json.dumps(plan.as_dict(), ensure_ascii=False))
    return OK


def cmd_machine_bundle(_args: argparse.Namespace) -> int:
    request = _machine_input(
        {"steps", "question", "findings", "dataset_revision"}, "bundle"
    )
    steps = request.get("steps")
    if (
        not isinstance(steps, list)
        or not steps
        or any(not isinstance(item, str) or not item.strip() for item in steps)
    ):
        raise AnalyseError("machine bundle requires a non-empty steps string array")
    bundle = build_bundle(
        steps,
        question=request.get("question") or "",
        findings_file=request.get("findings"),
        dataset_revision=request.get("dataset_revision"),
    )
    print(json.dumps(bundle.as_dict(), ensure_ascii=False))
    return OK


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


_EPILOG = """\
Examples:
  la-analyse plan --list-patterns
  la-analyse plan --question 'what depends on "Order Service"?' \\
      --profile linked-archi-default --data graph.trig
  la-analyse plan --question '...' --mode impact-and-dependency --budget 8 --json -o plan.json
  la-analyse bundle --step steps/01-inventory-summary.json --step steps/02-models.json \\
      --findings findings.json -o investigations/errata.json
  la-analyse render --bundle investigations/errata.json -o investigations/errata.md
  la-analyse doctor

Exit codes: 0 done, 1 refused (unknown pattern, incoherent bundle, missing claim class,
uncited claim), 2 error (unreadable file, malformed request).

This owner executes nothing. It emits the la-query commands to run and assembles the
envelopes they produce; execution, read-only enforcement and provenance stay with
linked-archi-query.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="la-analyse",
        description="Plan an architecture investigation and bundle its evidence. Never executes.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser(
        "plan",
        help="turn a question into an ordered list of la-query commands",
        description=(
            "Routes the question to an analysis pattern and emits the numbered steps to run, "
            "in doctrine order: orient, resolve, the pattern's own evidence, then quality. "
            "With --profile and linked-archi-query installed, each step carries this "
            "profile's availability, so a refused template is replaced by its documented "
            "alternative at planning time rather than mid-investigation."
        ),
    )
    plan.add_argument(
        "--question", metavar="TEXT",
        help="the question, with any names you mean in quotes so they are not guessed at",
    )
    plan.add_argument(
        "--mode", metavar="PATTERN",
        help="name the analysis pattern instead of routing to one (see --list-patterns)",
    )
    plan.add_argument(
        "--list-patterns", action="store_true",
        help="print the routing table and exit",
    )
    plan.add_argument(
        "--profile", metavar="NAME_OR_PATH",
        help="profile the plan's commands will use, and the one availability is read against",
    )
    plan.add_argument(
        "--data", action="append", default=[], metavar="FILE",
        help="dataset the plan's commands will use (repeatable). Not opened here",
    )
    plan.add_argument(
        "--endpoint", metavar="URL",
        help="endpoint the plan's commands will use instead of --data. Not contacted here",
    )
    plan.add_argument(
        "--budget", type=int, default=DEFAULT_BUDGET, metavar="N",
        help=(
            f"query budget to plan within (default: {DEFAULT_BUDGET}). Steps beyond it are "
            "marked rather than dropped, so what you are giving up stays visible"
        ),
    )
    plan.add_argument(
        "--steps-dir", default="steps", metavar="DIR",
        help="directory the planned commands write envelopes to (default: steps)",
    )
    plan.add_argument("--json", action="store_true", help="emit the plan as JSON")
    plan.add_argument("-o", "--output", metavar="FILE", help="write to this file instead of stdout")
    plan.set_defaults(func=cmd_plan)

    bundle = commands.add_parser(
        "bundle",
        help="assemble executed envelopes into one reviewable artifact",
        description=(
            "Consumes the envelopes `la-query --json -o FILE` already wrote. Re-executes "
            "nothing. Refuses envelopes from two different datasets or profiles, because a "
            "bundle spanning two vocabularies looks reproducible and is not. Carries "
            "truncation and caveats forward so a floor never reads as a total."
        ),
    )
    bundle.add_argument(
        "--step", action="append", default=[], required=True, metavar="FILE",
        help="a result envelope written by `la-query --json -o` (repeatable, in order)",
    )
    bundle.add_argument(
        "--question", metavar="TEXT", help="the question this investigation answered",
    )
    bundle.add_argument(
        "--findings", metavar="FILE",
        help=(
            "JSON holding the interpretation: an optional answer plus "
            + ", ".join(CLAIM_CLASSES)
            + ". Every claim except an unknown must cite at least one step"
        ),
    )
    bundle.add_argument(
        "--dataset-revision", metavar="REV",
        help=(
            "git revision of the dataset, from `la-connect datasets`. Recorded as "
            "caller-supplied: this owner does not run git and will not guess it"
        ),
    )
    bundle.add_argument(
        "--markdown", action="store_true",
        help="emit the Markdown rendering instead of the JSON artifact",
    )
    bundle.add_argument("-o", "--output", metavar="FILE", help="write to this file instead of stdout")
    bundle.set_defaults(func=cmd_bundle)

    render = commands.add_parser(
        "render",
        help="render an existing bundle as Markdown",
        description=(
            "The human answer, generated from the artifact rather than typed beside it - so "
            "the answer cannot cite a query the bundle does not contain."
        ),
    )
    render.add_argument("--bundle", required=True, metavar="FILE", help="a bundle JSON file")
    render.add_argument("-o", "--output", metavar="FILE", help="write to this file instead of stdout")
    render.set_defaults(func=cmd_render)

    doctor = commands.add_parser(
        "doctor",
        help="report this owner's location and companions",
        description=(
            "Owner root, resolved command, how many patterns loaded, and every companion this "
            "skill can reach. Run it instead of searching the filesystem."
        ),
    )
    doctor.set_defaults(func=cmd_doctor)

    machine = commands.add_parser(
        "_machine",
        help=_MACHINE_HELP,
        description=_MACHINE_DESCRIPTION,
    )
    machine_commands = machine.add_subparsers(dest="machine_command", required=True)
    machine_plan = machine_commands.add_parser(
        "plan",
        help="return a plan as versioned JSON",
        description=(
            'Request {"schema_version": 1, "question": "...", optional "mode", "profile", '
            '"data", "endpoint", "budget", "steps_dir"}. Response is the plan document.'
        ),
    )
    machine_plan.set_defaults(func=cmd_machine_plan)
    machine_bundle = machine_commands.add_parser(
        "bundle",
        help="return a bundle as versioned JSON",
        description=(
            'Request {"schema_version": 1, "steps": ["path", ...], optional "question", '
            '"findings", "dataset_revision"}. Response is the bundle document.'
        ),
    )
    machine_bundle.set_defaults(func=cmd_machine_bundle)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except AnalyseError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return REFUSED
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ERROR
    except BrokenPipeError:
        return OK
    except KeyboardInterrupt:
        return ERROR
