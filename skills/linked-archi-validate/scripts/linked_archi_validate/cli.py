"""Public validate commands and strict schema_version=1 contracts.

Two entry points, because there are two situations and they have different guarantees:

* ``run`` validates data against shapes here and now, so it can report coverage.
* ``report`` reads a report somebody else already produced, where coverage is simply
  not recoverable - and says so rather than implying a number.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from . import coverage as coverage_module
from . import rdf, report as report_module, shacl
from .errors import ValidateError

OK, VIOLATIONS, ERROR = 0, 1, 2

#: `_machine` is machine-facing, NOT private. The underscore says "not for a human to
#: type", and nothing more: the contract is documented, versioned, and depended on across
#: process boundaries by sibling skills. Hiding it from `--help` while three skills call it
#: was the worst of both worlds - visible in the usage line as `==SUPPRESS==` and explained
#: nowhere.
_MACHINE_HELP = "versioned JSON contract for automation (see validation-contract.md)"
_MACHINE_DESCRIPTION = (
    "Read one JSON object on stdin, write one JSON object on stdout. Diagnostics go to "
    "stderr. schema_version is checked exactly. This is a stable, documented boundary for "
    "sibling skills and automation, not a private entry point: skills/linked-archi-validate/references/validation-contract.md"
)

DEFAULT_LIMIT = 25

#: This skill's own name, used only to phrase the adjacency hint in an error.
OWN_SKILL = "linked-archi-validate"


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
        raise ValidateError(
            f"Missing required skill: {skill} under explicit "
            f"LINKED_ARCHI_SKILLS_DIR={configured}."
        )
    candidate = Path(__file__).resolve().parents[3] / skill / "scripts" / executable
    if candidate.is_file():
        return candidate
    on_path = shutil.which(executable)
    if on_path:
        return Path(on_path)
    raise ValidateError(
        f"Missing required skill: {skill}. Install it beside {OWN_SKILL}, put "
        f"{executable} on PATH, or set LINKED_ARCHI_SKILLS_DIR."
    )


def _target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data",
        action="append",
        default=[],
        metavar="FILE",
        required=True,
        help="RDF file to validate (repeatable; several files merge into one graph)",
    )
    parser.add_argument(
        "--shapes",
        action="append",
        default=[],
        metavar="FILE",
        required=True,
        help=(
            "SHACL shapes file (repeatable). Shapes are never bundled: pass local files, "
            "or acquire the published ones with la-source and pass the cached paths"
        ),
    )
    parser.add_argument(
        "--ontology",
        action="append",
        default=[],
        metavar="FILE",
        help="ontology loaded for reasoning (repeatable). Adds to the data, never replaces shapes",
    )
    parser.add_argument(
        "--no-rdfs-reasoning",
        action="store_true",
        help="disable rdfs:subClassOf reasoning, which changes which shapes match",
    )
    parser.add_argument(
        "--data-format",
        metavar="FMT",
        help="override the parser for --data files, e.g. trig, turtle, nquads",
    )


def _output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit the versioned JSON result")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        metavar="N",
        help=f"findings to show (default: {DEFAULT_LIMIT}); counts are always complete",
    )


def _positive(value: int, label: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value <= 0:
        raise ValidateError(f"{label} must be a positive integer")
    return value


def _describe_inputs(data: rdf.LoadedGraphs, shapes: rdf.LoadedGraphs) -> list[str]:
    notes: list[str] = []
    if not data.carries_graphs and data.flattened_inputs:
        notes.append(
            "the data carries no named graphs, so graph-scoped questions about it cannot "
            "be answered later; validation itself is unaffected"
        )
    return notes


def _emit_run(
    outcome: shacl.ValidationOutcome,
    summary: report_module.Summary,
    data: rdf.LoadedGraphs,
    shapes: rdf.LoadedGraphs,
    args: argparse.Namespace,
    machine: bool = False,
) -> int:
    limit = _positive(args.limit, "--limit") if not machine else None
    warnings = outcome.coverage.notes() + _describe_inputs(data, shapes)

    # A run that selected no focus node is a configuration failure, not a pass. Exit 2
    # so no caller can mistake it for conformance.
    unchecked = outcome.coverage.checked_nothing
    if summary.conforms and not unchecked:
        status = OK
    elif unchecked:
        status = ERROR
    else:
        status = VIOLATIONS

    if machine or args.json:
        payload = {
            "schema_version": 1,
            "mode": "run",
            **summary.as_dict(limit=limit),
            "coverage": outcome.coverage.as_dict(),
            "checked_nothing": unchecked,
            "inputs": {
                "data": [str(path) for path in data.paths],
                "shapes": [str(path) for path in shapes.paths],
                "data_triples": data.triples,
                "data_named_graphs": data.named_graphs,
                "shape_triples": shapes.triples,
                "rdfs_reasoning": outcome.rdfs_reasoning,
            },
            "warnings": warnings,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=not machine, indent=None if machine else 2))
        return status

    _print_verdict(summary, outcome.coverage, warnings)
    if unchecked:
        print(
            "\nNOTHING WAS CHECKED. This is not a pass — treat it as a configuration\n"
            "failure. Confirm the shapes and the data use the same namespaces, that\n"
            "--shapes names a shapes file rather than an ontology, and which notations\n"
            "the dataset actually contains (the query owner's core/models)."
        )
    print(
        f"\n  data:   {data.triples} triple(s), {data.named_graphs} named graph(s) — "
        + ", ".join(path.name for path in data.paths)
    )
    print(
        f"  shapes: {shapes.triples} triple(s), {outcome.coverage.shape_count} shape(s) — "
        + ", ".join(path.name for path in shapes.paths)
    )
    if not outcome.rdfs_reasoning:
        print("  rdfs:subClassOf reasoning disabled")
    _print_findings(summary, limit or DEFAULT_LIMIT)
    return status


def _print_verdict(
    summary: report_module.Summary,
    coverage: coverage_module.Coverage | None,
    warnings: Sequence[str],
) -> None:
    if summary.conforms:
        verdict = "conforms — no results reported"
    else:
        verdict = f"{summary.result_count} result(s) reported"
    print(f"Verdict: {verdict}")

    if coverage is None:
        print(
            "Coverage: not derivable from a report alone — a report records what was "
            "found, never what was checked"
        )
    elif coverage.no_class_targets:
        print("Coverage: unknown — no sh:targetClass declared")
    else:
        print(
            f"Coverage: {coverage.matched} of {coverage.declared} target class(es) matched the data"
        )

    for warning in warnings:
        print(f"  warning: {warning}", file=sys.stderr)


def _print_findings(summary: report_module.Summary, limit: int) -> None:
    if not summary.findings:
        return
    print("\nby severity:")
    for name in report_module.SEVERITIES:
        if summary.by_severity.get(name):
            print(f"  {name:<10} {summary.by_severity[name]}")
    for name, count in sorted(summary.by_severity.items()):
        if name not in report_module.SEVERITIES:
            print(f"  {name:<10} {count}")

    print("\nby shape:")
    for shape, count in list(summary.by_source_shape.items())[:10]:
        print(f"  {count:>5}  {shape}")
    if len(summary.by_source_shape) > 10:
        print(f"  … {len(summary.by_source_shape) - 10} more shape(s)")

    shown = summary.findings[:limit]
    print(f"\nfindings ({len(shown)} of {summary.result_count}):")
    for finding in shown:
        print(f"  [{finding.severity}] {finding.focus_node or '(no focus node)'}")
        if finding.path:
            print(f"      path:    {finding.path}")
        if finding.source_shape:
            print(f"      shape:   {finding.source_shape}")
        if finding.message:
            print(f"      message: {' '.join(str(finding.message).split())}")
    if summary.result_count > len(shown):
        print(f"  … {summary.result_count - len(shown)} more; raise --limit or use --json")

    print(
        "\nA result names a focus node, not a source model or an owner. Get from an "
        "element to the person who can fix it with the query owner's core/provenance."
    )


def cmd_run(args: argparse.Namespace) -> int:
    data = rdf.load(args.data, "--data file", args.data_format)
    shapes = rdf.load(args.shapes, "--shapes file")
    ontology = rdf.load(args.ontology, "--ontology file") if args.ontology else None
    outcome = shacl.run(
        data, shapes, ontology, rdfs_reasoning=not args.no_rdfs_reasoning
    )
    summary = report_module.summarise(outcome.report_graph)
    if args.report:
        destination = Path(args.report).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        outcome.report_graph.serialize(destination=str(destination), format="turtle")
        if not args.json:
            print(f"Report written to {destination}")
    return _emit_run(outcome, summary, data, shapes, args)


def cmd_report(args: argparse.Namespace) -> int:
    loaded = rdf.load([args.file], "report file", args.data_format)
    summary = report_module.summarise(loaded.graph)
    limit = _positive(args.limit, "--limit")

    if args.json:
        payload = {
            "schema_version": 1,
            "mode": "report",
            **summary.as_dict(limit=limit),
            # Explicitly null rather than absent. A consumer that finds no coverage key
            # might assume the report was fully covered; null says the opposite.
            "coverage": None,
            "inputs": {"report": str(loaded.paths[0]), "report_triples": loaded.triples},
            "warnings": _REPORT_CAVEATS,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        return OK if summary.conforms else VIOLATIONS

    print(f"Reading an existing report: {loaded.paths[0]}")
    _print_verdict(summary, None, _REPORT_CAVEATS)
    _print_findings(summary, limit)
    return OK if summary.conforms else VIOLATIONS


_REPORT_CAVEATS = (
    "this report was produced elsewhere: which shapes ran, and whether any target class "
    "matched, are not recorded in it. Re-run validation with the shapes to learn coverage.",
    "a report is a point-in-time document. Confirm it describes the dataset you are "
    "answering about, at a revision you can name.",
)


def cmd_doctor(args: argparse.Namespace) -> int:
    print("linked-archi-validate")
    print(f"  owner root:    {Path(__file__).resolve().parents[2]}")
    print(f"  command:       {Path(__file__).resolve().parents[1] / 'la-validate'}")

    ok = True
    for module, purpose in (("pyshacl", "SHACL validation"), ("rdflib", "RDF parsing")):
        try:
            loaded = __import__(module)
            version = getattr(loaded, "__version__", "unknown")
            print(f"  {module:<13} {version} ({purpose})")
        except ModuleNotFoundError:
            ok = False
            print(f"  {module:<13} MISSING — pip install pyshacl ({purpose})")

    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    print(f"  skills dir:    {configured or '(unset; resolving beside this skill)'}")
    for skill, executable, why in (
        ("linked-archi-source", "la-source", "acquire published shapes, verified and cached"),
        ("linked-archi-query", "la-query", "model-quality templates and reports in a dataset"),
    ):
        try:
            print(f"  {executable:<13} {_companion(skill, executable)} ({why})")
        except ValidateError:
            # Both are optional: validating a local graph against local shapes needs
            # neither, so a missing companion is not a failure here.
            print(f"  {executable:<13} not found (optional) - {why}")

    print(
        "\nNo converter, Java runtime or network access is needed. Shapes are not bundled:\n"
        "pass local files, or acquire the published documents once with la-source.\n"
        "Resolution order is $LINKED_ARCHI_SKILLS_DIR (authoritative), then the sibling\n"
        "directory beside this skill, then PATH - never a filesystem search."
    )
    return OK if ok else VIOLATIONS


def _machine_input(allowed: set[str], label: str) -> dict[str, Any]:
    try:
        raw = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise ValidateError(f"machine input is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValidateError("machine input must be an object")
    unknown = set(raw).difference({"schema_version", *allowed})
    if unknown:
        raise ValidateError(
            f"machine {label} input contains unknown fields: " + ", ".join(sorted(unknown))
        )
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ValidateError("machine input requires schema_version=1")
    return raw


def _string_list(value: Any, label: str, required: bool = True) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValidateError(f"{label} must be a non-empty array of paths")
    return [item.strip() for item in value]


def cmd_machine_validate(_args: argparse.Namespace) -> int:
    request = _machine_input({"data", "shapes", "ontology", "rdfs_reasoning"}, "validate")
    reasoning = request.get("rdfs_reasoning", True)
    if not isinstance(reasoning, bool):
        raise ValidateError("rdfs_reasoning must be a boolean")
    namespace = argparse.Namespace(
        data=_string_list(request.get("data"), "data"),
        shapes=_string_list(request.get("shapes"), "shapes"),
        ontology=_string_list(request.get("ontology"), "ontology", required=False),
        no_rdfs_reasoning=not reasoning,
        data_format=None,
        report=None,
        json=True,
        limit=DEFAULT_LIMIT,
    )
    data = rdf.load(namespace.data, "data file")
    shapes = rdf.load(namespace.shapes, "shapes file")
    ontology = rdf.load(namespace.ontology, "ontology file") if namespace.ontology else None
    outcome = shacl.run(data, shapes, ontology, rdfs_reasoning=reasoning)
    summary = report_module.summarise(outcome.report_graph)
    return _emit_run(outcome, summary, data, shapes, namespace, machine=True)


def cmd_machine_report(_args: argparse.Namespace) -> int:
    request = _machine_input({"report"}, "report")
    path = request.get("report")
    if not isinstance(path, str) or not path.strip():
        raise ValidateError("report must be a non-empty path")
    loaded = rdf.load([path.strip()], "report file")
    summary = report_module.summarise(loaded.graph)
    print(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "report",
                **summary.as_dict(limit=None),
                "coverage": None,
                "inputs": {"report": str(loaded.paths[0]), "report_triples": loaded.triples},
                "warnings": list(_REPORT_CAVEATS),
            },
            ensure_ascii=False,
        )
    )
    return OK if summary.conforms else VIOLATIONS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="la-validate",
        description="Run SHACL over an architecture graph, or read a report already produced.",
        epilog=(
            "Exit codes: 0 conforms, 1 results reported, 2 could not run.\n"
            "Exit 1 is a finding, not a crash: read the report and carry on.\n\n"
            "Examples:\n"
            "  la-validate run --data dist/merged.trig --shapes core-shapes.ttl\n"
            "  la-validate report ttl/graph-shacl-report.ttl\n"
            "  la-validate doctor\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser(
        "run",
        help="validate data against SHACL shapes",
        description=(
            "Validate here and now, in process, and report target-class coverage beside "
            "the verdict. Shape sets are ADDITIVE: nothing is bundled, so every --shapes "
            "file is one you named and adding another can only widen what is checked. "
            "A verdict without coverage is not evidence of quality."
        ),
    )
    _target_args(run)
    run.add_argument("-r", "--report", metavar="FILE", help="also write the report as Turtle")
    _output_args(run)
    run.set_defaults(func=cmd_run)

    existing = commands.add_parser(
        "report",
        help="summarise a SHACL report that already exists",
        description=(
            "Read a report somebody else produced - a converter run, a CI job. Cannot "
            "report coverage: the report says what was violated, never what was checked, "
            "so 'conforms' here means 'nothing in this document failed'."
        ),
    )
    existing.add_argument("file", help="the report document, in any RDF serialisation")
    existing.add_argument(
        "--data-format",
        metavar="FMT",
        help="override the parser for the report file, e.g. turtle",
    )
    _output_args(existing)
    existing.set_defaults(func=cmd_report)

    doctor = commands.add_parser(
        "doctor",
        help="report dependencies and companions",
        description=(
            "Owner root, resolved command, pyshacl and rdflib versions, and any optional "
            "companion. Run it instead of searching the filesystem."
        ),
    )
    doctor.set_defaults(func=cmd_doctor)

    machine = commands.add_parser(
        "_machine",
        help=_MACHINE_HELP,
        description=_MACHINE_DESCRIPTION,
    )
    machine_commands = machine.add_subparsers(dest="machine_command", required=True)
    machine_validate = machine_commands.add_parser(
        "validate",
        help="run SHACL and return the versioned result",
        description=(
            'Request {"schema_version": 1, "data": [...], "shapes": [...], "ontology": '
            '[...], "rdfs_reasoning": true}. Exit 1 means findings were reported, which '
            "is a result and not an error. See references/validation-contract.md."
        ),
    )
    machine_validate.set_defaults(func=cmd_machine_validate)
    machine_report = machine_commands.add_parser(
        "report",
        help="summarise an existing report and return the versioned result",
        description=(
            'Request {"schema_version": 1, "report": "path/to/report.ttl"}. Coverage is '
            "always null here, and the caveats say why."
        ),
    )
    machine_report.set_defaults(func=cmd_machine_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ValidateError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return ERROR
    except BrokenPipeError:
        return OK
    except KeyboardInterrupt:
        return ERROR


if __name__ == "__main__":
    raise SystemExit(main())
