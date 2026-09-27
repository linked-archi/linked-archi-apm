"""Benchmark comparisons must preserve evidence and isolate maintainer state."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import benchmark_queries as benchmark
from tests import support


def envelope(**overrides) -> dict:
    document = {
        "schema_version": 1,
        "query": "SELECT ?element ?label WHERE { ?element ?predicate ?label } LIMIT 2",
        "query_id": "query-identity",
        "dataset_id": "base.trig",
        "profile_id": "linked-archi-default",
        "profile_version": 1,
        "executed_at": "2026-01-01T00:00:00Z",
        "elapsed_ms": 5,
        "load_ms": 10,
        "template": "core/resolve-element",
        "form": "SELECT",
        "variables": ["element", "label"],
        "row_count": 2,
        "rows": [{"element": "urn:first", "label": "First"},
                 {"element": "urn:second", "label": "Second"}],
        "truncated": True,
        "warnings": ["Result is a floor", "Profile has not been verified"],
        "boolean": None,
        "triples": None,
    }
    document.update(overrides)
    return document


class TestBenchmarkEvidence(unittest.TestCase):
    def test_only_timing_and_row_order_are_ignored(self):
        original = envelope()
        changed = copy.deepcopy(original)
        changed.update(executed_at="2026-01-02T00:00:00Z", elapsed_ms=90, load_ms=100)
        changed["rows"].reverse()
        before = copy.deepcopy(changed)
        benchmark.require_equal(
            benchmark.normalise_envelope(original), benchmark.normalise_envelope(changed),
            "same evidence",
        )
        self.assertEqual(changed, before)

    def test_audit_fields_and_evidence_differences_refuse_a_verdict(self):
        original = envelope()
        replacements = {
            "query": original["query"] + " OFFSET 1", "query_id": "different-query",
            "dataset_id": "other.trig", "profile_id": "curated-store", "profile_version": 2,
            "template": "core/inventory", "truncated": False,
            "variables": list(reversed(original["variables"])),
            "warnings": list(reversed(original["warnings"])),
            "rows": [{"element": "urn:changed", "label": "First"}, original["rows"][1]],
            "boolean": False, "triples": "different evidence", "new_audit_field": "preserved",
        }
        for field, replacement in replacements.items():
            with self.subTest(field=field):
                changed = {**original, field: replacement}
                with self.assertRaisesRegex(benchmark.BenchmarkError, "Evidence differs: comparison"):
                    benchmark.require_equal(
                        benchmark.normalise_envelope(original),
                        benchmark.normalise_envelope(changed), "comparison",
                    )

    def test_row_multiplicity_is_not_discarded(self):
        first, second = envelope()["rows"]
        original = envelope(rows=[first, first, second], row_count=3)
        changed = envelope(rows=[first, second, second], row_count=3)
        with self.assertRaises(benchmark.BenchmarkError):
            benchmark.require_equal(
                benchmark.normalise_envelope(original), benchmark.normalise_envelope(changed),
                "duplicate rows",
            )

    def test_row_values_with_timing_names_are_evidence(self):
        for field in ("executed_at", "elapsed_ms", "load_ms"):
            with self.subTest(field=field):
                original = envelope(rows=[{field: "first"}], row_count=1)
                changed = envelope(rows=[{field: "second"}], row_count=1)
                self.assertNotEqual(
                    benchmark.normalise_envelope(original), benchmark.normalise_envelope(changed),
                )

    def test_only_core_models_generated_group_concat_is_unordered(self):
        for template, field, equivalent in (
            ("core/models", "generated", True),
            ("core/models", "title", False),
            ("core/resolve-element", "generated", False),
        ):
            with self.subTest(template=template, field=field):
                original = envelope(template=template, rows=[{field: "later, earlier"}], row_count=1)
                changed = envelope(template=template, rows=[{field: "earlier, later"}], row_count=1)
                self.assertEqual(
                    benchmark.normalise_envelope(original) == benchmark.normalise_envelope(changed),
                    equivalent,
                )

    def test_unknown_envelopes_and_incomplete_rows_are_rejected(self):
        for changes in ({"schema_version": 2}, {"form": "ASK"}, {"row_count": 3}):
            with self.subTest(changes=changes), self.assertRaises(benchmark.BenchmarkError):
                benchmark.normalise_envelope(envelope(**changes))


class TestBenchmarkInputs(unittest.TestCase):
    def test_custom_datasets_are_repeatable_and_require_a_known_term(self):
        arguments = benchmark.build_parser().parse_args([
            "--data", str(support.BASE), "--data", str(support.VOCABULARY),
        ])
        self.assertEqual(arguments.data, [str(support.BASE), str(support.VOCABULARY)])
        with patch.object(benchmark.Runner, "run") as run:
            with self.assertRaisesRegex(benchmark.BenchmarkError, "--data requires --term"):
                benchmark.benchmark(arguments)
            run.assert_not_called()

    def test_invalid_run_limits_refuse_before_starting_owners(self):
        for option, value in (("--runs", "0"), ("--warmups", "-1"), ("--limit", "0"),
                              ("--preview-rows", "0"), ("--timeout-seconds", "0")):
            with self.subTest(option=option), patch.object(benchmark.Runner, "run") as run:
                arguments = benchmark.build_parser().parse_args([option, value])
                with self.assertRaises(benchmark.BenchmarkError):
                    benchmark.benchmark(arguments)
                run.assert_not_called()

    def test_report_cannot_overwrite_input_data(self):
        arguments = benchmark.build_parser().parse_args(["--output", str(support.BASE)])
        with patch.object(benchmark.Runner, "run") as run:
            with self.assertRaisesRegex(benchmark.BenchmarkError, "must not overwrite"):
                benchmark.benchmark(arguments)
            run.assert_not_called()

    def test_existing_report_is_preserved_before_any_owner_starts(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report.json"
            target.write_text("existing evidence", encoding="utf-8")
            arguments = benchmark.build_parser().parse_args(["--output", str(target)])
            with patch.object(benchmark.Runner, "run") as run:
                with self.assertRaisesRegex(benchmark.BenchmarkError, "already exists"):
                    benchmark.benchmark(arguments)
                run.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "existing evidence")

    def test_report_created_during_benchmark_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report.json"

            def concurrent_report(arguments):
                Path(arguments.output).write_text("another report", encoding="utf-8")
                return {"cases": {}}

            with patch.object(benchmark, "benchmark", side_effect=concurrent_report):
                with contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(benchmark.main(["--output", str(target)]), 1)
            self.assertIn("Benchmark failed", error.getvalue())
            self.assertEqual(target.read_text(encoding="utf-8"), "another report")

    def test_unicode_term_reaches_the_analyse_question_unchanged(self):
        term = "Échange 服务"
        arguments = benchmark.build_parser().parse_args(["--term", term])
        with patch.object(benchmark, "checkout_identity", return_value={}), \
                patch.object(benchmark.Runner, "run", side_effect=[
                    '{"schema_version": 1}', benchmark.BenchmarkError("stop after plan input"),
                ]) as run:
            with self.assertRaisesRegex(benchmark.BenchmarkError, "stop after plan input"):
                benchmark.benchmark(arguments)
        owner, command = run.call_args.args
        self.assertEqual(owner, "analyse")
        self.assertEqual(command[command.index("--question") + 1], f'what depends on "{term}"?')

    def test_terms_the_analyse_parser_cannot_preserve_are_refused(self):
        for term in (" Order Service", "Order Service ", "x", 'Order "Service"',
                     "Order's Service", "Order “Service”", "Order ‘Service’"):
            with self.subTest(term=term), patch.object(benchmark.Runner, "run") as run:
                arguments = benchmark.build_parser().parse_args(["--term", term])
                with self.assertRaisesRegex(benchmark.BenchmarkError, "analyse name parser"):
                    benchmark.benchmark(arguments)
                run.assert_not_called()

    def test_inherited_local_bounds_survive_environment_isolation(self):
        inherited = {"LINKED_ARCHI_LOCAL_DEADLINE_S": "8", "LINKED_ARCHI_LOCAL_MAX_RSS_MB": "512",
                     "LINKED_ARCHI_STORE": "readonly", "LINKED_ARCHI_ENDPOINT": "https://invalid.test",
                     "PYTHONPATH": "unrelated-scripts", "PYTHONHOME": "unrelated-python"}
        with patch.dict(os.environ, inherited):
            runner = benchmark.Runner(Path("isolated-benchmark"), timeout=120)
        for field in ("LINKED_ARCHI_LOCAL_DEADLINE_S", "LINKED_ARCHI_LOCAL_MAX_RSS_MB"):
            self.assertEqual(runner.environment[field], inherited[field])
        for field in ("LINKED_ARCHI_STORE", "LINKED_ARCHI_ENDPOINT", "PYTHONPATH", "PYTHONHOME"):
            self.assertNotIn(field, runner.environment)
        self.assertEqual(runner.environment["LINKED_ARCHI_SKILLS_DIR"], str(support.ROOT / "skills"))
        self.assertEqual(runner.environment["LINKED_ARCHI_STATE_DIR"], "isolated-benchmark/state")


class TestOrientationSelection(unittest.TestCase):
    def plan(self) -> dict:
        return {"schema_version": 1, "batches": [{
            "stage": "orient", "status": "ready", "depends_on": [],
            "manifest": {"schema_version": 1, "queries": [
                {"id": "inventory", "template": "core/inventory-summary", "out": "inventory.json"},
                {"id": "models", "template": "core/models", "out": "models.json"},
            ]},
        }]}

    def test_only_ready_independent_orientation_can_be_executed(self):
        plan = self.plan()
        self.assertEqual(benchmark.orientation_manifest(plan), plan["batches"][0]["manifest"])
        for field, value in (("stage", "resolve"), ("status", "blocked"), ("depends_on", ["resolve"])):
            with self.subTest(field=field):
                changed = self.plan()
                changed["batches"][0][field] = value
                with self.assertRaises(benchmark.BenchmarkError):
                    benchmark.orientation_manifest(changed)

    def test_other_templates_parameters_and_ad_hoc_queries_are_rejected(self):
        for changes in ({"template": "core/resolve-element"}, {"set": {"LIMIT": 1}},
                        {"query": "SELECT * WHERE {}"}, {"file": "query.rq"}, {"out": ""}):
            with self.subTest(changes=changes):
                plan = self.plan()
                plan["batches"][0]["manifest"]["queries"][0].update(changes)
                with self.assertRaises(benchmark.BenchmarkError):
                    benchmark.orientation_manifest(plan)


class TestBatchPreviewEvidence(unittest.TestCase):
    def previews(self):
        entries = [{"id": "inventory"}, {"id": "models"}]
        documents = [envelope(query_id="inventory-query-identity"),
                     envelope(query_id="models-query-identity")]
        blocks = [
            f"# {entry['id']}\n{document['query_id'][:12]} {document['dataset_id']}\n"
            f"floor; showing 1\n{' '.join(document['warnings'])}\n"
            for entry, document in zip(entries, documents)
        ]
        return entries, documents, blocks

    def test_each_entry_must_preserve_its_own_caveats(self):
        entries, documents, blocks = self.previews()
        benchmark.batch_preview_checks("".join(blocks), entries, documents, 1)
        for missing in ("Profile has not been verified", "floor", "showing 1", "base.trig"):
            with self.subTest(missing=missing):
                output = blocks[0].replace(missing, "") + blocks[1]
                with self.assertRaisesRegex(benchmark.BenchmarkError, "Preview lost"):
                    benchmark.batch_preview_checks(output, entries, documents, 1)

    def test_missing_duplicate_or_reordered_entries_are_rejected(self):
        entries, documents, blocks = self.previews()
        for output in (blocks[0], blocks[0] + "".join(blocks), "".join(reversed(blocks))):
            with self.subTest(output=output), self.assertRaises(benchmark.BenchmarkError):
                benchmark.batch_preview_checks(output, entries, documents, 1)


class TestFreshBenchmarkEvidence(unittest.TestCase):
    def test_an_owner_that_does_not_save_cannot_reuse_previous_evidence(self):
        for case in ("lookup_preview", "orientation_individual", "orientation_batch"):
            with self.subTest(case=case):
                stale_paths = []

                def owner_without_output(runner, owner, arguments):
                    if owner == "profile":
                        return '{"schema_version": 1}'
                    if owner == "analyse":
                        directory = Path(arguments[arguments.index("--steps-dir") + 1]).parent
                        entries = [{"id": str(index), "template": template,
                                    "out": str(directory / f"orientation-{index}.json")}
                                   for index, template in enumerate(benchmark.ORIENTATION)]
                        stale_paths.extend([directory / "lookup.json",
                                            *(Path(entry["out"]) for entry in entries)])
                        for path in stale_paths:
                            path.write_text(json.dumps(envelope()), encoding="utf-8")
                        return json.dumps({"schema_version": 1, "batches": [{
                            "stage": "orient", "status": "ready", "depends_on": [],
                            "manifest": {"schema_version": 1, "queries": entries},
                        }]})
                    outputs = stale_paths[1:] if case == "orientation_batch" else [
                        Path(arguments[arguments.index("-o") + 1]),
                    ]
                    for path in outputs:
                        self.assertFalse(path.exists(), f"stale evidence before {case}: {path}")
                    return ""

                arguments = benchmark.build_parser().parse_args(["--runs", "1", "--warmups", "0"])
                with patch.object(benchmark, "CASES", (case,)), \
                        patch.object(benchmark, "checkout_identity", return_value={}), \
                        patch.object(benchmark.Runner, "run", autospec=True,
                                     side_effect=owner_without_output):
                    with self.assertRaises(FileNotFoundError):
                        benchmark.benchmark(arguments)


class TestFixtureBenchmark(unittest.TestCase):
    def test_real_owner_cases_preserve_evidence_without_using_inherited_state(self):
        support.requires_pyoxigraph(self)
        fingerprint = hashlib.sha256(support.BASE.read_bytes()).hexdigest()
        arguments = benchmark.build_parser().parse_args([
            "--runs", "1", "--warmups", "0", "--limit", "1", "--preview-rows", "1",
        ])
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state_paths = {"LINKED_ARCHI_SKILLS_DIR": str(directory / "installed-skills"),
                           "LINKED_ARCHI_STATE_DIR": str(directory / "existing-state"),
                           "LINKED_ARCHI_STORE_CACHE": str(directory / "existing-cache")}
            inherited = {**state_paths, "LINKED_ARCHI_STORE": "readonly",
                         "LINKED_ARCHI_DATA": str(directory / "missing.trig")}
            with patch.dict(os.environ, inherited):
                report = benchmark.benchmark(arguments)
                for field, value in inherited.items():
                    self.assertEqual(os.environ[field], value)
            for path in state_paths.values():
                self.assertFalse(Path(path).exists(), path)

        self.assertTrue(report["configuration"]["fixture_only"])
        self.assertEqual(report["configuration"]["term"], "Order Service")
        self.assertEqual(report["configuration"]["store"], "memory")
        self.assertEqual(report["configuration"]["data"][0]["sha256"], fingerprint)
        self.assertEqual(hashlib.sha256(support.BASE.read_bytes()).hexdigest(), fingerprint)
        self.assertTrue(report["checks"])
        self.assertTrue(all(report["checks"].values()))
        cases = report["cases"]
        self.assertEqual(set(cases), {"catalogue_full", "catalogue_selected", "render_only",
                                     "lookup_json", "lookup_preview", "analyse_plan",
                                     "orientation_individual", "orientation_batch"})
        for name, result in cases.items():
            with self.subTest(case=name):
                self.assertEqual(len(result["samples"]), 1)
                self.assertEqual(result["median"], result["samples"][0])
                for metric in ("wall_ms", "stdout_bytes", "stderr_bytes", "owner_cli_calls"):
                    self.assertGreaterEqual(result["median"][metric], 0)
        self.assertEqual(cases["orientation_individual"]["median"]["owner_cli_calls"], 2)
        self.assertEqual(cases["orientation_batch"]["median"]["owner_cli_calls"], 1)
        for name in ("lookup_json", "lookup_preview", "orientation_individual", "orientation_batch"):
            for metric in ("load_ms", "query_ms"):
                self.assertGreaterEqual(cases[name]["median"][metric], 0)
        self.assertEqual(report["total_owner_cli_calls_including_warmups"],
                         report["setup_owner_cli_calls"] + report["validation_owner_cli_calls"] +
                         sum(case["median"]["owner_cli_calls"] for case in cases.values()))
        self.assertEqual(report["evidence_summary"]["lookup_rows"], 1)
        self.assertTrue(report["evidence_summary"]["lookup_truncated"])
