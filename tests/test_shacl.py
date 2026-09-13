"""In-process SHACL validation, coverage honesty, and report reading.

The behaviour under test is not "does pyshacl work" - it is the reporting discipline
around it. A validator that answers "conforms" while having checked nothing is the failure
this owner exists to prevent, so most of these tests are about that case rather than about
finding violations.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  - puts the owner scripts on sys.path
from support import ROOT

from linked_archi_validate import coverage as coverage_module
from linked_archi_validate import rdf, report as report_module, shacl
from linked_archi_validate.errors import ValidateError

VALIDATE = ROOT / "skills" / "linked-archi-validate" / "scripts" / "la-validate"

SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <https://example.org/onto#> .
ex:ThingShape a sh:NodeShape ;
  sh:targetClass ex:Thing ;
  sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""

CONFORMING = """
@prefix ex: <https://example.org/onto#> .
ex:one a ex:Thing ; ex:name "named" .
"""

VIOLATING = """
@prefix ex: <https://example.org/onto#> .
ex:one a ex:Thing .
"""

#: Everything in a named graph and nothing in the default graph - exactly what converter
#: TriG looks like, and the shape of data a default-graph-only validator silently ignores.
VIOLATING_TRIG = """
@prefix ex: <https://example.org/onto#> .
ex:g { ex:one a ex:Thing . }
"""

WRONG_NAMESPACE_SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix other: <https://elsewhere.example.org/onto#> .
other:ThingShape a sh:NodeShape ;
  sh:targetClass other:Thing ;
  sh:property [ sh:path other:name ; sh:minCount 1 ] .
"""

ONTOLOGY_NOT_SHAPES = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <https://example.org/onto#> .
ex:Thing a owl:Class .
"""

SUBCLASS_DATA = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <https://example.org/onto#> .
ex:Special rdfs:subClassOf ex:Thing .
ex:one a ex:Special .
"""


class _Files(unittest.TestCase):
    def setUp(self):
        support.requires_pyshacl(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_validation(self, data: str, shapes: str, suffix: str = ".ttl", **kwargs):
        data_path = self.write(f"data{suffix}", data)
        shapes_path = self.write("shapes.ttl", shapes)
        loaded_data = rdf.load([str(data_path)], "data")
        loaded_shapes = rdf.load([str(shapes_path)], "shapes")
        return shacl.run(loaded_data, loaded_shapes, **kwargs)


class TestValidation(_Files):
    def test_conforming_data_conforms(self):
        outcome = self.run_validation(CONFORMING, SHAPES)
        self.assertTrue(outcome.conforms)
        summary = report_module.summarise(outcome.report_graph)
        self.assertTrue(summary.conforms)
        self.assertEqual(summary.result_count, 0)

    def test_violating_data_reports_a_result_with_its_focus_node(self):
        outcome = self.run_validation(VIOLATING, SHAPES)
        self.assertFalse(outcome.conforms)
        summary = report_module.summarise(outcome.report_graph)
        self.assertEqual(summary.result_count, 1)
        finding = summary.findings[0]
        self.assertEqual(finding.severity, "Violation")
        self.assertEqual(finding.focus_node, "https://example.org/onto#one")
        self.assertEqual(finding.path, "https://example.org/onto#name")

    def test_data_in_named_graphs_is_validated_not_ignored(self):
        """The trap: converter output leaves the default graph empty.

        A validator seeing only the default graph would report a clean pass over an
        entire estate.
        """
        outcome = self.run_validation(VIOLATING_TRIG, SHAPES, suffix=".trig")
        self.assertFalse(outcome.conforms, "named-graph data was not validated")
        self.assertEqual(report_module.summarise(outcome.report_graph).result_count, 1)

    def test_named_graphs_are_counted_for_reporting(self):
        path = self.write("data.trig", VIOLATING_TRIG)
        loaded = rdf.load([str(path)], "data")
        self.assertEqual(loaded.named_graphs, 1)
        self.assertTrue(loaded.carries_graphs)

    def test_a_flattened_input_reports_no_named_graphs(self):
        path = self.write("data.ttl", VIOLATING)
        loaded = rdf.load([str(path)], "data")
        self.assertEqual(loaded.named_graphs, 0)
        self.assertFalse(loaded.carries_graphs)

    def test_empty_shapes_are_refused_rather_than_passing(self):
        with self.assertRaises(ValidateError) as caught:
            self.run_validation(CONFORMING, "@prefix ex: <https://example.org/> .\n")
        self.assertIn("nothing would be checked", str(caught.exception))

    def test_a_misnamed_extension_is_reported(self):
        with self.assertRaises(ValidateError) as caught:
            rdf.load([str(self.write("data.bogus", VIOLATING))], "data")
        self.assertIn("cannot infer the RDF format", str(caught.exception))

    def test_a_missing_file_names_itself(self):
        with self.assertRaises(ValidateError) as caught:
            rdf.load([str(self.root / "absent.ttl")], "data file")
        self.assertIn("does not exist", str(caught.exception))


class TestCoverageHonesty(_Files):
    def test_matched_coverage_is_reported(self):
        outcome = self.run_validation(CONFORMING, SHAPES)
        self.assertEqual(outcome.coverage.declared, 1)
        self.assertEqual(outcome.coverage.matched, 1)
        self.assertFalse(outcome.coverage.vacuous)
        self.assertFalse(outcome.coverage.checked_nothing)

    def test_a_namespace_mismatch_is_vacuous_not_a_pass(self):
        outcome = self.run_validation(CONFORMING, WRONG_NAMESPACE_SHAPES)
        self.assertTrue(outcome.conforms, "SHACL itself finds nothing to report")
        self.assertTrue(outcome.coverage.vacuous)
        self.assertTrue(outcome.coverage.checked_nothing)
        self.assertIn("VACUOUS", " ".join(outcome.coverage.notes()))

    def test_an_ontology_passed_as_shapes_selects_nothing(self):
        outcome = self.run_validation(CONFORMING, ONTOLOGY_NOT_SHAPES)
        self.assertTrue(outcome.coverage.no_class_targets)
        self.assertTrue(outcome.coverage.checked_nothing)
        self.assertIn("rather than an ontology", " ".join(outcome.coverage.notes()))

    def test_subclass_instances_count_as_matched(self):
        """The notation ontologies are class hierarchies.

        A shape targeting a superclass genuinely applies to specialisations, so ignoring
        rdfs:subClassOf would report a sound shape set as vacuous.
        """
        outcome = self.run_validation(SUBCLASS_DATA, SHAPES)
        self.assertEqual(outcome.coverage.matched, 1)
        self.assertFalse(outcome.coverage.vacuous)

    def test_implicit_class_targets_are_counted(self):
        shapes = """
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix ex: <https://example.org/onto#> .
        ex:Thing a sh:NodeShape, rdfs:Class ;
          sh:property [ sh:path ex:name ; sh:minCount 1 ] .
        """
        outcome = self.run_validation(VIOLATING, shapes)
        self.assertEqual(outcome.coverage.declared, 1)
        self.assertEqual(outcome.coverage.matched, 1)
        self.assertFalse(outcome.conforms)

    def test_absent_constraint_counts_are_explicitly_null(self):
        # Omitting them would let a reader assume zero. Null says "not measured".
        payload = self.run_validation(CONFORMING, SHAPES).coverage.as_dict()
        self.assertIsNone(payload["constraints_evaluated"])
        self.assertIsNone(payload["constraints_skipped"])

    def test_other_target_kinds_are_distinguished_from_no_targets(self):
        shapes = """
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        @prefix ex: <https://example.org/onto#> .
        ex:Shape a sh:NodeShape ;
          sh:targetSubjectsOf ex:name ;
          sh:property [ sh:path ex:name ; sh:minCount 1 ] .
        """
        outcome = self.run_validation(CONFORMING, shapes)
        self.assertTrue(outcome.coverage.no_class_targets)
        self.assertTrue(outcome.coverage.has_other_targets)
        self.assertFalse(
            outcome.coverage.checked_nothing,
            "a shape with non-class targets did select focus nodes",
        )
        self.assertIn("unknown rather than zero", " ".join(outcome.coverage.notes()))


class TestReadingAnExistingReport(_Files):
    def test_a_report_is_summarised_without_shapes_or_data(self):
        outcome = self.run_validation(VIOLATING, SHAPES)
        path = self.root / "report.ttl"
        outcome.report_graph.serialize(destination=str(path), format="turtle")
        loaded = rdf.load([str(path)], "report")
        summary = report_module.summarise(loaded.graph)
        self.assertFalse(summary.conforms)
        self.assertEqual(summary.result_count, 1)
        self.assertEqual(summary.by_severity["Violation"], 1)

    def test_a_conforming_report_is_read_as_conforming(self):
        path = self.write(
            "clean.ttl",
            "@prefix sh: <http://www.w3.org/ns/shacl#> .\n[] a sh:ValidationReport ; sh:conforms true .\n",
        )
        summary = report_module.summarise(rdf.load([str(path)], "report").graph)
        self.assertTrue(summary.conforms)
        self.assertEqual(summary.result_count, 0)

    def test_a_report_claiming_conformance_while_carrying_results_is_not_trusted(self):
        path = self.write(
            "lying.ttl",
            """
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            @prefix ex: <https://example.org/onto#> .
            [] a sh:ValidationReport ; sh:conforms true ;
               sh:result [ a sh:ValidationResult ; sh:resultSeverity sh:Violation ;
                           sh:focusNode ex:one ] .
            """,
        )
        summary = report_module.summarise(rdf.load([str(path)], "report").graph)
        self.assertFalse(summary.conforms, "results must outweigh a contradictory flag")

    def test_a_non_report_is_refused(self):
        path = self.write("data.ttl", CONFORMING)
        with self.assertRaises(ValidateError) as caught:
            report_module.summarise(rdf.load([str(path)], "report").graph)
        self.assertIn("not a SHACL", str(caught.exception))

    def test_violations_sort_before_warnings(self):
        path = self.write(
            "mixed.ttl",
            """
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            @prefix ex: <https://example.org/onto#> .
            [] a sh:ValidationReport ; sh:conforms false ;
               sh:result [ a sh:ValidationResult ; sh:resultSeverity sh:Warning ; sh:focusNode ex:w ] ,
                         [ a sh:ValidationResult ; sh:resultSeverity sh:Violation ; sh:focusNode ex:v ] .
            """,
        )
        summary = report_module.summarise(rdf.load([str(path)], "report").graph)
        self.assertEqual([f.severity for f in summary.findings], ["Violation", "Warning"])


class TestCommandContract(_Files):
    """Exit codes, because a caller acts on them without reading the prose."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(VALIDATE), *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

    def test_conforming_run_exits_zero(self):
        data = self.write("data.ttl", CONFORMING)
        shapes = self.write("shapes.ttl", SHAPES)
        done = self._run("run", "--data", str(data), "--shapes", str(shapes))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Coverage: 1 of 1", done.stdout)

    def test_violations_exit_one(self):
        data = self.write("data.ttl", VIOLATING)
        shapes = self.write("shapes.ttl", SHAPES)
        done = self._run("run", "--data", str(data), "--shapes", str(shapes))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("1 result(s) reported", done.stdout)

    def test_checking_nothing_exits_two_rather_than_reporting_a_pass(self):
        data = self.write("data.ttl", CONFORMING)
        shapes = self.write("shapes.ttl", WRONG_NAMESPACE_SHAPES)
        done = self._run("run", "--data", str(data), "--shapes", str(shapes))
        self.assertEqual(done.returncode, 2, done.stdout)
        self.assertIn("NOTHING WAS CHECKED", done.stdout)

    def test_machine_validate_emits_a_versioned_contract(self):
        data = self.write("data.ttl", VIOLATING)
        shapes = self.write("shapes.ttl", SHAPES)
        done = subprocess.run(
            [sys.executable, str(VALIDATE), "_machine", "validate"],
            input=json.dumps(
                {"schema_version": 1, "data": [str(data)], "shapes": [str(shapes)]}
            ),
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(done.returncode, 1, done.stderr)
        payload = json.loads(done.stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["mode"], "run")
        self.assertFalse(payload["conforms"])
        self.assertFalse(payload["checked_nothing"])
        self.assertIsNone(payload["coverage"]["constraints_evaluated"])

    def test_machine_report_returns_null_coverage(self):
        path = self.write(
            "clean.ttl",
            "@prefix sh: <http://www.w3.org/ns/shacl#> .\n[] a sh:ValidationReport ; sh:conforms true .\n",
        )
        done = subprocess.run(
            [sys.executable, str(VALIDATE), "_machine", "report"],
            input=json.dumps({"schema_version": 1, "report": str(path)}),
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        payload = json.loads(done.stdout)
        self.assertEqual(payload["mode"], "report")
        self.assertIsNone(payload["coverage"], "a report cannot report coverage")
        self.assertTrue(payload["warnings"])

    def test_machine_input_refuses_query_text(self):
        done = subprocess.run(
            [sys.executable, str(VALIDATE), "_machine", "validate"],
            input=json.dumps(
                {"schema_version": 1, "data": ["a"], "shapes": ["b"], "query": "SELECT * {}"}
            ),
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(done.returncode, 2)
        self.assertIn("unknown fields: query", done.stderr)

    def test_doctor_reports_dependencies(self):
        done = self._run("doctor")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("pyshacl", done.stdout)
        self.assertIn("No converter", done.stdout)


if __name__ == "__main__":
    unittest.main()
