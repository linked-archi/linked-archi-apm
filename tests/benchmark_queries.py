"""Maintainer benchmark of owner CLIs, not an agent or a second query executor."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
LOOKUP = "core/resolve-element"
ORIENTATION = ("core/inventory-summary", "core/models")
CASES = (
    "catalogue_full", "catalogue_selected", "render_only", "lookup_json",
    "lookup_preview", "analyse_plan", "orientation_individual", "orientation_batch",
)


class BenchmarkError(ValueError):
    pass


def normalise_envelope(document: dict) -> dict:
    if document.get("schema_version") != 1 or document.get("form") != "SELECT":
        raise BenchmarkError("Expected a version-1 SELECT envelope")
    if document.get("row_count") != len(document.get("rows", [])):
        raise BenchmarkError("Envelope row_count does not match its complete rows")
    result = {key: value for key, value in document.items()
              if key not in {"executed_at", "elapsed_ms", "load_ms"}}
    rows = [dict(row) for row in document["rows"]]
    if document.get("template") == "core/models":
        for row in rows:
            if isinstance(row.get("generated"), str):
                row["generated"] = ", ".join(sorted(row["generated"].split(", ")))
    result["rows"] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
    return result


def require_equal(left, right, label: str) -> None:
    if left != right:
        raise BenchmarkError(f"Evidence differs: {label}; no performance verdict is safe")


def fingerprints(paths: list[Path]) -> list[dict]:
    result = []
    for path in paths:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        result.append({"path": str(path), "bytes": path.stat().st_size, "sha256": digest})
    return result


def checkout_identity() -> dict:
    digest = hashlib.sha256()
    sources = [Path(__file__).resolve(), ROOT / "apm.yml"]
    sources.extend(path for path in (ROOT / "skills").glob("*/scripts/la-*") if path.is_file())
    sources.extend(path for path in (ROOT / "skills").rglob("*")
                   if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".rq", ".md"})
    for path in sorted(sources):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    result = {"source_sha256": digest.hexdigest(), "revision": None, "dirty": None}
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                  text=True, timeout=10)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                                text=True, timeout=10)
        if revision.returncode == 0:
            result["revision"] = revision.stdout.strip()
        if status.returncode == 0:
            result["dirty"] = bool(status.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result


class Runner:
    def __init__(self, directory: Path, timeout: int):
        self.timeout = timeout
        bounds = {"LINKED_ARCHI_LOCAL_DEADLINE_S", "LINKED_ARCHI_LOCAL_MAX_RSS_MB"}
        self.environment = {
            key: value for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
            and (not key.startswith("LINKED_ARCHI_") or key in bounds)
        }
        self.environment.update({
            "LINKED_ARCHI_SKILLS_DIR": str(ROOT / "skills"),
            "LINKED_ARCHI_STATE_DIR": str(directory / "state"),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.calls: list[dict] = []

    def run(self, owner: str, arguments: list[str]) -> str:
        script = ROOT / "skills" / f"linked-archi-{owner}" / "scripts" / f"la-{owner}"
        started = time.perf_counter()
        with subprocess.Popen(
            [sys.executable, str(script), *arguments], cwd=ROOT, env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=os.name == "posix",
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.communicate()
                raise BenchmarkError(f"la-{owner} exceeded {self.timeout}s") from None
        self.calls.append({
            "wall_ms": (time.perf_counter() - started) * 1000,
            "stdout_bytes": len(stdout), "stderr_bytes": len(stderr), "owner_cli_calls": 1,
        })
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace").strip()[-1200:]
            raise BenchmarkError(f"la-{owner} exited {process.returncode}: {detail}")
        return stdout.decode("utf-8")


def preview_checks(output: str, envelopes: list[dict], limit: int) -> None:
    for envelope in envelopes:
        expected = [*envelope["warnings"], envelope["query_id"][:12], envelope["dataset_id"]]
        if envelope["truncated"]:
            expected.append("floor")
        if envelope["row_count"] > limit:
            expected.append(f"showing {limit}")
        if any(text not in output for text in expected):
            raise BenchmarkError("Preview lost a warning, citation or truncation/display notice")


def batch_preview_checks(output: str, entries: list[dict], envelopes: list[dict], limit: int) -> None:
    markers = [f"# {entry['id']}\n" for entry in entries]
    if any(output.count(marker) != 1 for marker in markers):
        raise BenchmarkError("Batch preview must identify every entry exactly once")
    positions = [output.index(marker) for marker in markers] + [len(output)]
    if positions != sorted(positions):
        raise BenchmarkError("Batch preview entry order changed")
    for index, envelope in enumerate(envelopes):
        preview_checks(output[positions[index]:positions[index + 1]], [envelope], limit)


def orientation_manifest(plan: dict) -> dict:
    if plan.get("schema_version") != 1:
        raise BenchmarkError("Expected a version-1 analyse plan")
    candidates = [batch for batch in plan.get("batches", [])
                  if batch.get("stage") == "orient" and batch.get("status") == "ready"
                  and not batch.get("depends_on")]
    if len(candidates) != 1:
        raise BenchmarkError("No single ready orientation batch; check profile availability")
    manifest = candidates[0]["manifest"]
    entries = manifest.get("queries", [])
    if manifest.get("schema_version") != 1 or tuple(entry.get("template") for entry in entries) != ORIENTATION:
        raise BenchmarkError("Unexpected orientation manifest; refusing to execute other plan steps")
    if any(entry.get("set") or not entry.get("out") or "query" in entry or "file" in entry
           for entry in entries):
        raise BenchmarkError("Orientation must contain only the two parameter-free saved templates")
    return manifest


def benchmark(args: argparse.Namespace) -> dict:
    custom_data = bool(args.data)
    if custom_data and not args.term:
        raise BenchmarkError("--data requires --term naming a known element; no fixture label is assumed")
    term = args.term or "Order Service"
    if len(term.strip()) < 2 or term != term.strip() or any(mark in term for mark in "\"'\u201c\u201d\u2018\u2019"):
        raise BenchmarkError("Choose a term of at least two characters without quote marks or surrounding whitespace; "
                             "the current analyse name parser cannot preserve those inputs")
    data = [Path(path).expanduser().resolve() for path in (args.data or [ROOT / "fixtures/base.trig"])]
    if any(not path.is_file() for path in data):
        raise BenchmarkError("Every --data path must name an existing local file")
    profile_path = Path(args.profile).expanduser()
    profile = str(profile_path.resolve()) if profile_path.is_file() else args.profile
    if args.output and Path(args.output).expanduser().resolve() in [*data, profile_path.resolve()]:
        raise BenchmarkError("The report must not overwrite an input dataset or profile")
    if args.output and Path(args.output).expanduser().exists():
        raise BenchmarkError("Report output already exists; choose a new report path")
    if args.runs < 1 or args.warmups < 0 or min(args.limit, args.preview_rows, args.timeout_seconds) < 1:
        raise BenchmarkError("Runs, limits and timeout must be positive; warmups must be non-negative")
    before = fingerprints(data)
    source_identity = checkout_identity()
    target = [argument for path in data for argument in ("--data", str(path))] + ["--store", "memory"]
    profiled = ["--profile", profile]
    lookup = ["query", "run", LOOKUP, *profiled, *target,
              "--set", f"TERM={term}", "--set", f"LIMIT={args.limit}"]
    samples: dict[str, list[dict]] = {name: [] for name in CASES}
    observations: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="linked-archi-benchmark-") as temporary:
        directory = Path(temporary)
        runner = Runner(directory, args.timeout_seconds)
        resolved_profile = json.loads(runner.run("profile", ["resolve", *profiled]))
        if resolved_profile.get("schema_version") != 1:
            raise BenchmarkError("Expected a version-1 resolved profile")
        plan_arguments = [
            "plan", "--question", f'what depends on "{term}"?', *profiled,
            *target[:-2], "--steps-dir", str(directory / "steps"),
            "--batch-dir", str(directory / "batches"), "--json",
        ]
        setup_plan = json.loads(runner.run("analyse", plan_arguments))
        manifest = orientation_manifest(setup_plan)
        manifest_path = directory / "orientation.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        def case(name: str):
            envelopes = []
            if name.startswith("catalogue_"):
                arguments = ["catalog", "dump", *profiled]
                if name == "catalogue_selected":
                    arguments += ["--template", LOOKUP]
                payload = json.loads(runner.run("query", arguments))
            elif name == "render_only":
                payload = runner.run("query", ["query", "render", LOOKUP, *profiled,
                                               "--set", f"TERM={term}", "--set", f"LIMIT={args.limit}"])
            elif name == "lookup_json":
                payload = json.loads(runner.run("query", [*lookup, "--json"]))
                envelopes = [payload]
            elif name == "lookup_preview":
                saved = directory / "lookup.json"
                saved.unlink(missing_ok=True)
                output = runner.run("query", [*lookup, "-o", str(saved), "--preview",
                                              "--limit", str(args.preview_rows)])
                payload = json.loads(saved.read_text(encoding="utf-8"))
                envelopes = [payload]
                preview_checks(output, envelopes, args.preview_rows)
            elif name == "analyse_plan":
                payload = json.loads(runner.run("analyse", plan_arguments))
                require_equal(orientation_manifest(payload), manifest, "planned orientation manifest")
            elif name == "orientation_individual":
                for entry in manifest["queries"]:
                    Path(entry["out"]).unlink(missing_ok=True)
                    output = runner.run("query", ["query", "run", entry["template"], *profiled, *target,
                                                  "-o", entry["out"], "--preview",
                                                  "--limit", str(args.preview_rows)])
                    envelope = json.loads(Path(entry["out"]).read_text(encoding="utf-8"))
                    preview_checks(output, [envelope], args.preview_rows)
                    envelopes.append(envelope)
                payload = envelopes
            else:
                for entry in manifest["queries"]:
                    Path(entry["out"]).unlink(missing_ok=True)
                output = runner.run("query", ["query", "batch", str(manifest_path), *profiled, *target,
                                              "--preview", "--limit", str(args.preview_rows)])
                envelopes = [json.loads(Path(entry["out"]).read_text(encoding="utf-8"))
                             for entry in manifest["queries"]]
                batch_preview_checks(output, manifest["queries"], envelopes, args.preview_rows)
                payload = envelopes
            if envelopes and any(envelope["row_count"] == 0 for envelope in envelopes):
                raise BenchmarkError(f"{name} returned no rows; choose a known term and suitable profile")
            return payload, envelopes

        for iteration in range(args.warmups + args.runs):
            observed = {}
            order = CASES if iteration % 2 == 0 else tuple(reversed(CASES))
            for name in order:
                offset = len(runner.calls)
                payload, envelopes = case(name)
                observed[name] = payload
                if iteration >= args.warmups:
                    calls = runner.calls[offset:]
                    sample = {key: round(sum(call[key] for call in calls), 3) for key in calls[0]}
                    if envelopes:
                        sample["load_ms"] = sum(envelope["load_ms"] for envelope in envelopes)
                        sample["query_ms"] = sum(envelope["elapsed_ms"] for envelope in envelopes)
                    samples[name].append(sample)
            selected = observed["catalogue_selected"]
            full = observed["catalogue_full"]
            expected = {**full, "templates": {LOOKUP: full["templates"][LOOKUP]}}
            require_equal(selected, expected, "selected catalogue metadata")
            require_equal(observed["render_only"].strip(), observed["lookup_json"]["query"].strip(),
                          "render-only versus executed query")
            require_equal(normalise_envelope(observed["lookup_json"]),
                          normalise_envelope(observed["lookup_preview"]), "lookup presentation")
            require_equal([normalise_envelope(envelope) for envelope in observed["orientation_individual"]],
                          [normalise_envelope(envelope) for envelope in observed["orientation_batch"]],
                          "individual versus batched orientation")
            observations = observed
        require_equal(fingerprints(data), before, "dataset changed during benchmark")
        require_equal(json.loads(runner.run("profile", ["resolve", *profiled])), resolved_profile,
                      "resolved profile changed during benchmark")
        report = {
            "schema_version": 1,
            "configuration": {
                "fixture_only": not custom_data, "data": before, "profile": profile,
                "term": term, "runs": args.runs, "warmups": args.warmups,
                "query_limit": args.limit, "preview_rows": args.preview_rows,
                "timeout_seconds": args.timeout_seconds, "store": "memory",
                "resolved_profile": {key: resolved_profile[key]
                                     for key in ("name", "version", "source", "fingerprint", "limits")},
            },
            "environment": {
                "checkout": str(ROOT), **source_identity, "python": platform.python_version(),
                "platform": platform.platform(),
                "dependencies": {name: importlib.metadata.version(name) for name in ("PyYAML", "pyoxigraph")},
                "local_bounds": {key: value for key, value in runner.environment.items()
                                 if key.startswith("LINKED_ARCHI_LOCAL_")},
            },
            "entrypoint_bytes": {owner: (ROOT / "skills" / f"linked-archi-{owner}" / "SKILL.md").stat().st_size
                                 for owner in ("query", "analyse")},
            "setup_owner_cli_calls": 1,
            "validation_owner_cli_calls": 2,
            "total_owner_cli_calls_including_warmups": len(runner.calls),
            "cases": {name: {"samples": values, "median": {
                key: statistics.median(sample[key] for sample in values) for key in values[0]
            }} for name, values in samples.items()},
            "checks": {
                "catalogue_metadata_equal": True, "render_matches_execution": True,
                "lookup_evidence_equal": True, "orientation_evidence_equal": True,
                "preview_preserves_caveats": True, "data_unchanged": True, "profile_unchanged": True,
            },
            "evidence_summary": {
                "lookup_rows": observations["lookup_json"]["row_count"],
                "lookup_truncated": observations["lookup_json"]["truncated"],
                "lookup_query_id": observations["lookup_json"]["query_id"],
                "orientation": [{"template": envelope["template"], "rows": envelope["row_count"],
                                 "truncated": envelope["truncated"], "warnings": len(envelope["warnings"])}
                                for envelope in observations["orientation_batch"]],
                "planned_queries": observations["analyse_plan"]["planned_steps"],
                "refusal_decisions": len(observations["analyse_plan"]["decisions"]),
            },
            "limitations": [
                "UTF-8 output bytes are not model tokens or billing measurements.",
                "Owner CLI calls exclude nested companion subprocesses; their time is included.",
                "Only planning and independent orientation are benchmarked, not investigation judgement.",
                "Same-checkout variants are compared, not historical code or a complete agent session.",
                "Fresh memory stores do not imply cold OS caches; warmups are excluded and order alternates.",
                "JSON lookup uses stdout; preview includes saving a complete envelope to disk.",
                "Evidence equality does not prove profile correctness, complete coverage or an answer.",
                "Reports contain input paths, search terms, hashes and counts; review before sharing.",
            ],
        }
        report["comparisons"] = {}
        for baseline, optimized in (
            ("catalogue_full", "catalogue_selected"),
            ("lookup_json", "lookup_preview"),
            ("orientation_individual", "orientation_batch"),
        ):
            original = report["cases"][baseline]["median"]
            improved = report["cases"][optimized]["median"]
            report["comparisons"][optimized] = {
                "baseline": baseline,
                "wall_speedup_ratio": original["wall_ms"] / improved["wall_ms"],
                "stdout_reduction_percent": 100 * (1 - improved["stdout_bytes"] / original["stdout_bytes"]),
                "owner_cli_calls_saved": original["owner_cli_calls"] - improved["owner_cli_calls"],
            }
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", action="append", help="local dataset; repeatable (default: test-only base fixture)")
    parser.add_argument("--term", help="known element name; required with --data")
    parser.add_argument("--profile", default="linked-archi-default")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--limit", type=int, default=20, help="lookup query row limit")
    parser.add_argument("--preview-rows", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=120, help="deadline per owner invocation")
    parser.add_argument("-o", "--output", help="save JSON report and print a short summary; otherwise JSON on stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = benchmark(args)
        text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            target = Path(args.output).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as stream:
                stream.write(text)
            print(f"Report: {target} (bytes are not model tokens)")
            for name, result in report["cases"].items():
                median = result["median"]
                print(f"{name:24} {median['wall_ms']:9.1f} ms  "
                      f"{median['stdout_bytes']:8.0f} stdout bytes  "
                      f"{median['owner_cli_calls']:.0f} owner CLI call(s)")
        else:
            print(text, end="")
        return 0
    except (BenchmarkError, OSError, ValueError, KeyError, importlib.metadata.PackageNotFoundError) as error:
        print(f"Benchmark failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
