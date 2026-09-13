"""The analyse owner: plans an investigation, bundles its evidence, executes nothing.

The last clause is the one worth testing hardest. Everything else here is convenience; if
analyse ever opened a dataset or issued SPARQL, read-only enforcement would have two homes
and the reproducibility envelope two authors.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import support
from support import AUGMENTED, ROOT

from linked_archi_analyse import build_bundle, build_plan, load_patterns, render_markdown
from linked_archi_analyse.patterns import AnalyseError, resolve_mode, terms_in
from linked_archi_analyse.plan import DEFAULT_BUDGET

QUERY = ROOT / "skills" / "linked-archi-query" / "scripts" / "la-query"


def _catalogue(profile: str = "linked-archi-default") -> dict:
    """The real catalogue, read the way the CLI reads it: one `catalog dump`."""
    import subprocess
    import sys

    done = subprocess.run(
        [sys.executable, str(QUERY), "catalog", "dump", "--profile", profile],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _plan(question: str, *, mode: str | None = None, profile: str = "linked-archi-default",
          catalogue: dict | None = -1, budget: int = DEFAULT_BUDGET):
    patterns = load_patterns()
    pattern, ranked = resolve_mode(mode, question, patterns)
    return build_plan(
        question,
        pattern=pattern,
        ranked=ranked,
        catalogue=_catalogue(profile) if catalogue == -1 else catalogue,
        profile=profile,
        data=["graph.trig"],
        budget=budget,
    )


class TestRouting(unittest.TestCase):
    def test_a_question_reaches_the_pattern_its_words_belong_to(self):
        for question, expected in (
            ('what depends on "A" if we retire it?', "impact-and-dependency"),
            ("which capability does this application realise?", "traceability"),
            ("which applications have no owner recorded?", "coverage-and-gaps"),
            ("which diagram shows this container?", "views-and-documentation"),
            ("can we trust these models?", "model-quality"),
            ("what is in this process?", "model-contents"),
        ):
            with self.subTest(question):
                self.assertEqual(_plan(question, catalogue=None).pattern, expected)

    def test_a_single_word_trigger_matches_whole_words_only(self):
        """"data" must not fire on "database", and "fail" must not fire on "failover"."""
        patterns = load_patterns()
        _, ranked = resolve_mode(None, "which database stores the failover config?", patterns)
        self.assertEqual([match.pattern.name for match in ranked], [])

    def test_no_match_is_reported_rather_than_guessed(self):
        """The alphabetically first pattern is not an answer to an unrecognised question."""
        plan = _plan("what colour is the logo?", catalogue=None)
        self.assertIsNone(plan.pattern)
        self.assertTrue(any("No pattern matched" in note for note in plan.notes))
        # Orientation is still right, so the plan is not empty.
        self.assertTrue(plan.steps)

    def test_an_explicit_mode_wins_and_is_validated(self):
        plan = _plan("what colour is the logo?", mode="model-quality", catalogue=None)
        self.assertEqual(plan.pattern, "model-quality")
        with self.assertRaises(AnalyseError) as caught:
            _plan("anything", mode="not-a-pattern", catalogue=None)
        self.assertIn("not-a-pattern", str(caught.exception))

    def test_only_quoted_names_are_taken_from_the_question(self):
        self.assertEqual(terms_in('what depends on "Order Service"?'), ("Order Service",))
        self.assertEqual(terms_in("what depends on the order service?"), ())


class TestPlanShape(unittest.TestCase):
    def setUp(self):
        self.plan = _plan('what depends on "Order Service" if we retire it?')

    def test_steps_follow_the_doctrine_order(self):
        stages = [step.stage for step in self.plan.steps]
        self.assertEqual(stages[0], "orient")
        self.assertIn("resolve", stages)
        # Orientation never comes after the pattern's own evidence.
        self.assertEqual(
            stages, sorted(stages, key=lambda s: ["orient", "resolve", "pattern", "quality"].index(s))
        )

    def test_every_step_is_a_runnable_command_that_writes_an_envelope(self):
        for step in self.plan.steps:
            command = step.command(
                profile=self.plan.profile, data=self.plan.data,
                endpoint=None, steps_dir="steps",
            )
            with self.subTest(step.number):
                self.assertTrue(command.startswith("la-query query run "))
                self.assertIn("--json", command)
                self.assertIn(f"-o steps/{step.number:02d}-", command)

    def test_a_quoted_name_becomes_the_term_of_every_resolve_step(self):
        """One earlier version resolved the name in step 3 and then asked about a placeholder."""
        resolve = [step for step in self.plan.steps if step.stage == "resolve"]
        self.assertTrue(resolve)
        for step in resolve:
            self.assertEqual(step.parameters.get("TERM"), "Order Service")

    def test_an_unknown_parameter_is_a_placeholder_naming_where_it_comes_from(self):
        focus = [s for s in self.plan.steps if "FOCUS_IRI" in s.parameters]
        self.assertTrue(focus)
        for step in focus:
            value = step.parameters["FOCUS_IRI"]
            self.assertTrue(value.startswith("<") and value.endswith(">"), value)
            self.assertIn("core/resolve-element", value)

    def test_no_step_is_planned_twice(self):
        """`core/provenance` is both the quality step and part of this pattern."""
        signatures = [
            (step.template, tuple(sorted(step.parameters.items()))) for step in self.plan.steps
        ]
        self.assertEqual(len(signatures), len(set(signatures)))

    def test_stop_conditions_belong_to_the_investigation_not_to_a_step(self):
        """Distributing them across steps read as per-step rules and was nonsense."""
        self.assertTrue(self.plan.pattern_stop_when)
        pattern_steps = [s for s in self.plan.steps if s.stage == "pattern"]
        self.assertTrue(pattern_steps)
        for step in pattern_steps:
            self.assertEqual(step.stop_when, "")

    def test_the_plan_states_its_budget_and_marks_what_exceeds_it(self):
        tight = _plan('what depends on "Order Service"?', budget=3)
        self.assertEqual(tight.budget, 3)
        over = [step for step in tight.steps if step.over_budget]
        self.assertTrue(over)
        self.assertTrue(any("OVER BUDGET" in note for note in tight.notes))
        # Marked, not dropped: what is being given up stays visible.
        self.assertGreater(len(tight.steps), 3)

    def test_it_refuses_a_plan_with_no_question(self):
        for bad in ("", "   "):
            with self.assertRaises(AnalyseError):
                _plan(bad, catalogue=None)


class TestProfileAwareness(unittest.TestCase):
    def test_a_refused_template_is_replaced_at_planning_time(self):
        """The point of annotating: not discovering it halfway through."""
        plan = _plan('what depends on "Order Service" if we retire it?',
                     profile="linked-archi-default")
        refused = [step for step in plan.steps if step.availability == "refused"]
        self.assertTrue(refused, "the default profile refuses core/dependents-direct")
        for step in refused:
            self.assertTrue(step.alternatives, "a refusal with nowhere to go is half an answer")
            self.assertTrue(step.note, "and it must say why")

    def test_the_same_plan_under_a_richer_profile_refuses_nothing(self):
        plan = _plan('what depends on "Order Service" if we retire it?',
                     profile="examples/curated-store")
        self.assertEqual([s for s in plan.steps if s.availability == "refused"], [])

    def test_a_template_caveat_is_carried_into_the_plan(self):
        plan = _plan("is this the same system? reconcile the two", profile="examples/curated-store")
        caveats = [c for step in plan.steps for c in step.caveats]
        self.assertTrue(any("CANDIDATES" in c for c in caveats), caveats)

    def test_without_query_the_plan_degrades_and_says_so(self):
        plan = _plan('what depends on "Order Service"?', catalogue=None)
        self.assertFalse(plan.annotated)
        self.assertTrue(any("not reachable" in note for note in plan.notes))
        self.assertTrue(plan.steps, "still an ordered plan")
        for step in plan.steps:
            self.assertEqual(step.availability, "unknown")


class TestBundle(unittest.TestCase):
    """Envelopes in, one artifact out. Nothing re-executed."""

    @classmethod
    def setUpClass(cls):
        support.requires_pyoxigraph(cls)
        import subprocess
        import sys
        import tempfile

        cls._tmp = tempfile.TemporaryDirectory()
        cls.steps_dir = Path(cls._tmp.name)
        cls.steps = []
        for number, template in enumerate(
            ("core/inventory-summary", "core/models", "core/label-collisions"), start=1
        ):
            target = cls.steps_dir / f"{number:02d}-{template.split('/')[-1]}.json"
            done = subprocess.run(
                [sys.executable, str(QUERY), "query", "run", template,
                 "--profile", "examples/curated-store", "--data", str(AUGMENTED),
                 "--json", "-o", str(target)],
                capture_output=True, text=True, timeout=180, cwd=ROOT,
            )
            assert done.returncode == 0, done.stderr
            cls.steps.append(target)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _findings(self, **overrides):
        document = {
            "answer": "Five notations loaded.",
            "graph_facts": [{"claim": "Five notations are present.", "steps": [1]}],
            "derived_facts": [],
            "document_statements": [],
            "inferences": [],
            "unknowns": [{"claim": "Runtime call volume is not represented."}],
        }
        document.update(overrides)
        path = self.steps_dir / "findings.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_it_identifies_the_dataset_and_the_profile_version(self):
        bundle = build_bundle(self.steps, question="what loaded?").as_dict()
        self.assertEqual(bundle["schema_version"], 1)
        self.assertEqual(bundle["dataset"]["id"], "augmented.trig")
        self.assertEqual(bundle["profile"]["id"], "curated-store")
        self.assertEqual(bundle["profile"]["version"], 1)
        self.assertEqual(len(bundle["steps"]), 3)

    def test_every_step_carries_its_query_and_identity(self):
        for step in build_bundle(self.steps).as_dict()["steps"]:
            with self.subTest(step["number"]):
                self.assertTrue(step["query"].strip())
                self.assertEqual(len(step["query_id"]), 64)
                self.assertTrue(step["executed_at"])
                self.assertIn("row_count", step)
                self.assertIn("truncated", step)

    def test_a_row_snapshot_is_bounded_and_says_how_much_it_omitted(self):
        for step in build_bundle(self.steps).as_dict()["steps"]:
            with self.subTest(step["number"]):
                self.assertEqual(step["rows_shown"], len(step["rows"]))
                self.assertEqual(
                    step["rows_shown"] + step["rows_omitted"],
                    min(step["row_count"], step["rows_shown"] + step["rows_omitted"]),
                )

    def test_a_template_caveat_travels_into_the_bundle(self):
        bundle = build_bundle(self.steps).as_dict()
        self.assertTrue(any("CANDIDATES" in caveat for caveat in bundle["caveats"]))

    def test_it_reports_whether_the_profile_was_ever_verified(self):
        """Read from the shared marker convention, not from a claim in the bundle."""
        self.assertIn("verified", build_bundle(self.steps).as_dict()["profile"])

    def test_it_refuses_envelopes_from_two_datasets(self):
        import subprocess
        import sys

        other = self.steps_dir / "other.json"
        subprocess.run(
            [sys.executable, str(QUERY), "query", "run", "core/models",
             "--profile", "linked-archi-default", "--data", str(support.BASE),
             "--json", "-o", str(other)],
            capture_output=True, text=True, timeout=180, cwd=ROOT, check=True,
        )
        with self.assertRaises(AnalyseError) as caught:
            build_bundle([self.steps[0], other])
        message = str(caught.exception)
        self.assertIn("different datasets", message)
        self.assertIn("reads as reproducible and is not", message)

    def test_it_refuses_a_file_that_is_not_a_versioned_envelope(self):
        stray = self.steps_dir / "stray.json"
        stray.write_text(json.dumps({"rows": []}), encoding="utf-8")
        with self.assertRaises(AnalyseError) as caught:
            build_bundle([stray])
        self.assertIn("schema_version", str(caught.exception))

    def test_it_needs_at_least_one_step(self):
        with self.assertRaises(AnalyseError):
            build_bundle([])

    def test_findings_must_declare_every_claim_class(self):
        path = self._findings()
        document = json.loads(path.read_text())
        del document["inferences"]
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(AnalyseError) as caught:
            build_bundle(self.steps, findings_file=path)
        self.assertIn("inferences", str(caught.exception))

    def test_a_claim_must_cite_a_step(self):
        path = self._findings(graph_facts=[{"claim": "no citation"}])
        with self.assertRaises(AnalyseError) as caught:
            build_bundle(self.steps, findings_file=path)
        self.assertIn("cites no step", str(caught.exception))

    def test_an_unknown_may_cite_nothing(self):
        """It rests on the absence of evidence, which is not a step."""
        bundle = build_bundle(self.steps, findings_file=self._findings())
        self.assertEqual(bundle.as_dict()["findings"]["unknowns"][0]["steps"], [])

    def test_a_citation_must_name_a_step_in_the_bundle(self):
        path = self._findings(graph_facts=[{"claim": "x", "steps": [99]}])
        with self.assertRaises(AnalyseError) as caught:
            build_bundle(self.steps, findings_file=path)
        self.assertIn("99", str(caught.exception))

    def test_a_caller_supplied_revision_is_recorded_as_supplied(self):
        bundle = build_bundle(self.steps, dataset_revision="9f0a12d4").as_dict()
        self.assertEqual(bundle["dataset"]["revision"], "9f0a12d4")
        self.assertIsNone(build_bundle(self.steps).as_dict()["dataset"]["revision"])


class TestMarkdownRendering(unittest.TestCase):
    """The answer is generated from the bundle, so it cannot cite a query it lacks."""

    @classmethod
    def setUpClass(cls):
        support.requires_pyoxigraph(cls)

    def _bundle(self):
        return {
            "schema_version": 1,
            "created_at": "2026-09-02T00:00:00+00:00",
            "question": "what loaded?",
            "dataset": {"id": "augmented.trig", "revision": "9f0a12d4"},
            "profile": {"id": "curated-store", "version": 1, "verified": False},
            "truncated": True,
            "caveats": ["a caveat from a query"],
            "steps": [{
                "number": 1, "source_file": "01.json", "template": "core/models",
                "query": "SELECT ?model WHERE { ?model a ?x }",
                "query_id": "abc123def456789", "executed_at": "2026-09-02T00:00:00+00:00",
                "elapsed_ms": 1, "form": "SELECT", "variables": ["model"],
                "row_count": 6, "truncated": False, "warnings": [], "boolean": None,
                "rows_shown": 1, "rows": [{"model": "urn:a"}], "rows_omitted": 5,
            }],
            "findings": {
                "answer": "Six models.",
                "graph_facts": [{"claim": "Six model rows.", "steps": [1]}],
                "derived_facts": [], "document_statements": [], "inferences": [],
                "unknowns": [{"claim": "Nothing about runtime.", "steps": []}],
            },
        }

    def test_it_names_the_dataset_the_profile_and_that_it_is_unverified(self):
        rendered = render_markdown(self._bundle())
        self.assertIn("augmented.trig", rendered)
        self.assertIn("9f0a12d4", rendered)
        self.assertIn("**not verified**", rendered)

    def test_truncation_is_stated_as_a_floor(self):
        self.assertIn("floors, not totals", render_markdown(self._bundle()))

    def test_every_claim_class_appears_even_when_empty(self):
        rendered = render_markdown(self._bundle())
        for heading in ("Graph facts", "Derived from the graph", "Document statements",
                        "Analyst inference", "Unknown, and why"):
            self.assertIn(heading, rendered)
        self.assertIn("_None._", rendered)

    def test_the_queries_are_quoted_in_full(self):
        rendered = render_markdown(self._bundle())
        self.assertIn("```sparql", rendered)
        self.assertIn("SELECT ?model WHERE { ?model a ?x }", rendered)


if __name__ == "__main__":
    unittest.main()
