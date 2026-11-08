"""The analyse owner: plans an investigation, bundles its evidence, executes nothing.

The last clause is the one worth testing hardest. Everything else here is convenience; if
analyse ever opened a dataset or issued SPARQL, read-only enforcement would have two homes
and the reproducibility envelope two authors.
"""

from __future__ import annotations

import json
import io
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

import support
from support import AUGMENTED, ROOT

from linked_archi_analyse import build_bundle, build_plan, load_patterns, render_markdown
from linked_archi_analyse.patterns import AnalyseError, resolve_mode, terms_in
from linked_archi_analyse.plan import DEFAULT_BUDGET, required_templates
from linked_archi_analyse import cli as analyse_cli

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
          catalogue: dict | None = -1, budget: int = DEFAULT_BUDGET,
          definitions: bool = False, preview: bool = True):
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
        definitions=definitions,
        preview=preview,
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
            ('How is "General CRM System" represented across ArchiMate, Backstage and LeanIX, '
             'and which teams own APIs serving the BPMN processes?',
             "cross-notation"),
        ):
            with self.subTest(question):
                self.assertEqual(_plan(question, catalogue=None).pattern, expected)

    def test_notation_names_require_two_distinct_mentions(self):
        patterns = load_patterns()
        selected, ranked = resolve_mode(None, "What is in the ArchiMate model?", patterns)
        self.assertNotEqual(selected.name if selected else None, "cross-notation")
        selected, ranked = resolve_mode(None, "Compare BPMN with Backstage", patterns)
        self.assertEqual(selected.name, "cross-notation")
        self.assertIn("named notations: backstage, bpmn", ranked[0].matched)
        selected, ranked = resolve_mode(None, "What depends on Backstage and LeanIX?", patterns)
        self.assertEqual(selected.name, "impact-and-dependency")

    def test_a_single_word_trigger_matches_whole_words_only(self):
        """"data" must not fire on "database", and "fail" must not fire on "failover"."""
        patterns = load_patterns()
        _, ranked = resolve_mode(None, "which database stores the failover config?", patterns)
        self.assertEqual([match.pattern.name for match in ranked], [])

    def test_taxonomy_intent_selects_concept_resolution_not_a_domain_label(self):
        plan = _plan('Which elements are classified under "Arch component"?', catalogue=None)
        self.assertEqual(plan.pattern, "taxonomy-classification")
        self.assertEqual([step.template for step in plan.steps[:4]], [
            "core/inventory-summary", "core/models", "core/resolve-concept",
            "core/classified-by",
        ])
        self.assertEqual(plan.steps[2].parameters, {})
        self.assertIn("several concepts or schemes", plan.steps[2].stop_when)
        self.assertIsNone(_plan('Tell me about "Arch component"', catalogue=None).pattern)
        self.assertEqual(
            _plan('Which policy elements are classified under "Arch component"?',
                  catalogue=None).pattern,
            "taxonomy-classification",
        )

    def test_taxonomy_plan_keeps_concept_iri_unresolved_until_evidence_is_reviewed(self):
        plan = _plan('Which elements are classified under "Arch component"?')
        resolution = next(step for step in plan.steps if step.template == "core/resolve-concept")
        classified = next(step for step in plan.steps if step.template == "core/classified-by")
        self.assertEqual(resolution.parameters["TERM"], "Arch component")
        self.assertIn("core/resolve-concept", classified.parameters["CONCEPT_IRI"])
        self.assertIn("CONCEPT_IRI", classified.unresolved_parameters)
        self.assertIn(resolution.number, classified.depends_on)
        self.assertNotIn("core/resolve-element", [step.template for step in plan.steps])

    def test_taxonomy_resolution_requires_a_quoted_term(self):
        plan = _plan("Which elements are classified under the category?")
        resolution = next(step for step in plan.steps if step.template == "core/resolve-concept")
        self.assertTrue(any("No quoted name" in note for note in plan.notes))
        self.assertIn("TERM", resolution.unresolved_parameters)

    def test_notation_taxonomy_uses_attached_vocabulary_not_instance_classification(self):
        plan = _plan('Which types are grouped by domain under "Strategy Domain"?',
                     profile="curated-store")
        self.assertEqual(plan.pattern, "notation-taxonomy")
        names = [step.template for step in plan.steps]
        self.assertIn("core/resolve-vocabulary-concept", names)
        self.assertIn("core/elements-by-category", names)
        self.assertNotIn("core/classified-by", names)
        self.assertEqual(next(step for step in plan.steps if
                              step.template == "core/resolve-vocabulary-concept")
                         .parameters["TERM"], "Strategy Domain")

    def test_notation_taxonomy_without_a_category_skips_unused_resolution(self):
        plan = _plan("How are elements grouped by domain?", profile="curated-store")
        self.assertEqual(plan.pattern, "notation-taxonomy")
        self.assertNotIn("core/resolve-vocabulary-concept",
                         [step.template for step in plan.steps])
        self.assertIn("core/elements-by-category", [step.template for step in plan.steps])
        self.assertFalse(any("No quoted name" in note for note in plan.notes))
        self.assertNotIn("core/resolve-vocabulary-concept", required_templates(
            "How are elements grouped by domain?", load_patterns()["notation-taxonomy"]
        ))

    def test_viewpoint_selection_starts_with_catalog_not_a_model_view(self):
        plan = _plan("Which viewpoint suits a capability map?", profile="curated-store")
        self.assertEqual(plan.pattern, "viewpoint-selection")
        self.assertEqual(plan.steps[2].template, "core/viewpoint-catalog")
        detail = next(step for step in plan.steps if step.template == "core/viewpoint-detail")
        self.assertIn("core/viewpoint-catalog", detail.parameters["VIEWPOINT_IRI"])
        self.assertIn(plan.steps[2].number, detail.depends_on)
        self.assertNotIn("core/resolve-element", [step.template for step in plan.steps])
        self.assertFalse(any("No quoted name" in note for note in plan.notes))

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

    def test_stop_conditions_belong_to_pattern_claims_not_arbitrary_steps(self):
        """Distributing them across steps would make them per-step rules."""
        self.assertTrue(self.plan.pattern_stop_when)
        pattern_steps = [s for s in self.plan.steps if s.stage == "pattern"]
        self.assertTrue(pattern_steps)
        for step in pattern_steps:
            self.assertEqual(step.stop_when, "")

    def test_cross_notation_plan_flags_independent_parts_without_extra_queries(self):
        question = ('How is "General CRM System" represented across ArchiMate and LeanIX, '
                    'and which teams own APIs serving BPMN processes?')
        plan = _plan(question, catalogue=None)
        self.assertEqual(plan.pattern, "cross-notation")
        self.assertTrue(any("each requested answer" in note and "budget" in note
                            for note in plan.notes))
        self.assertTrue(all("independent" in condition for condition in plan.pattern_stop_when))
        self.assertIn("stop the pattern-dependent claim when:", plan.to_text())
        self.assertEqual([step.template for step in plan.steps], [
            "core/inventory-summary", "core/models", "core/resolve-element",
            "core/identity-audit", "core/label-collisions", "core/provenance",
        ])
        self.assertEqual(plan.budget, DEFAULT_BUDGET)

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
    def test_a_refused_template_is_a_decision_without_an_executable_command(self):
        plan = _plan('what depends on "Order Service" if we retire it?',
                     profile="linked-archi-qualified")
        refused = plan.decisions
        self.assertTrue(refused, "output without direct triples refuses core/dependents-direct")
        for decision in refused:
            self.assertTrue(decision["alternatives"])
            self.assertTrue(decision["reason"])
            self.assertTrue(decision["answers"])
            self.assertTrue(decision["does_not_prove"])
            self.assertNotIn("command", decision)
            self.assertNotIn(decision["template"], [step.template for step in plan.steps])
        self.assertNotIn("query run core/dependents-direct", plan.to_text())
        self.assertIn("not assumed to answer the same question", plan.to_text())
        self.assertEqual(plan.as_dict()["planned_steps"], 5)
        self.assertTrue({"core/neighbours", "core/dependents"}.issubset(
            {decision["template"] for decision in refused}))

    def test_the_same_plan_under_a_richer_profile_refuses_nothing(self):
        plan = _plan('what depends on "Order Service" if we retire it?',
                     profile="examples/curated-store")
        self.assertEqual([s for s in plan.steps if s.availability == "refused"], [])
        self.assertEqual(plan.decisions, [])

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


class TestConditionalPlanning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = _catalogue()

    def test_entity_questions_resolve_names_without_requesting_definitions(self):
        for question in ('what depends on "Order Service"?',
                         'what depends on "Definition Service"?',
                         'what is in "Orders"?',
                         'which applications are deprecated?'):
            with self.subTest(question=question):
                plan = _plan(question, catalogue=self.catalogue)
                self.assertNotIn("core/define-term", [step.template for step in plan.steps])
                resolve = next(step for step in plan.steps if step.stage == "resolve")
                self.assertIn("several candidates", resolve.stop_when)

    def test_definition_questions_and_explicit_requests_keep_definition_evidence(self):
        for question, definitions in (('what does "Order Service" mean?', False),
                                      ('what is "Order Service"?', False),
                                      ('define “Order Service”', False),
                                      ('what depends on "Order Service"?', True)):
            with self.subTest(question=question):
                plan = _plan(question, catalogue=self.catalogue, definitions=definitions)
                definition = next(step for step in plan.steps if step.template == "core/define-term")
                self.assertEqual(definition.parameters["TERM"], "Order Service")
                self.assertIn("ask", definition.stop_when)

    def test_metadata_selection_contains_only_the_planned_candidates(self):
        question = 'what depends on "Order Service"?'
        pattern, _ranked = resolve_mode(None, question, load_patterns())
        selected = required_templates(question, pattern)
        plan = _plan(question, catalogue=self.catalogue)
        self.assertEqual(set(selected), {step.template for step in plan.steps}
                         | {decision["template"] for decision in plan.decisions})
        self.assertEqual(len(selected), len(set(selected)))

    def test_refusals_are_review_barriers_not_silent_substitutions(self):
        plan = _plan('what depends on "Order Service"?', profile="linked-archi-qualified")
        decision = next(item for item in plan.decisions if item["template"] == "core/dependents-direct")
        provenance = next(step for step in plan.steps if step.template == "core/provenance")
        self.assertIn(decision["id"], provenance.review_decisions)
        self.assertEqual(provenance.status, "review-required")

    def test_unprofiled_catalogue_metadata_does_not_assert_availability(self):
        unprofiled = json.loads(json.dumps(self.catalogue))
        for metadata in unprofiled["templates"].values():
            metadata.pop("available", None)
            metadata.pop("profile_caveats", None)
        plan = _plan('what depends on "Order Service"?', catalogue=unprofiled)
        self.assertTrue(all(step.availability == "unknown" for step in plan.steps))
        self.assertEqual(plan.batches(), [])


class TestPlanBatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = _catalogue()

    def test_orientation_is_one_ready_batch_and_keeps_both_envelopes(self):
        plan = _plan('what depends on "Order Service"?', catalogue=self.catalogue)
        batch = plan.batches()[0]
        self.assertEqual(batch["stage"], "orient")
        self.assertEqual(batch["status"], "ready")
        self.assertEqual(batch["depends_on"], [])
        self.assertEqual(batch["steps"], [1, 2])
        self.assertEqual(batch["manifest"]["schema_version"], 1)
        self.assertEqual([entry["template"] for entry in batch["manifest"]["queries"]],
                         ["core/inventory-summary", "core/models"])
        self.assertEqual([entry["out"] for entry in batch["manifest"]["queries"]],
                         ["steps/01-inventory-summary.json", "steps/02-models.json"])

    def test_independent_name_resolution_batches_wait_for_orientation_review(self):
        plan = _plan('what depends on "Orders" and "Payments"?', catalogue=self.catalogue)
        resolution = next(batch for batch in plan.batches() if batch["stage"].startswith("resolve"))
        self.assertEqual(resolution["status"], "awaiting-evidence")
        self.assertEqual(resolution["depends_on"], [1, 2])
        self.assertEqual(resolution["round"], 2)
        self.assertEqual([entry["set"]["TERM"] for entry in resolution["manifest"]["queries"]
                          if "TERM" in entry["set"]],
                         ["Orders", "Payments"])

    def test_unresolved_and_refused_queries_never_enter_a_batch(self):
        plan = _plan("what depends on the order service?", catalogue=self.catalogue)
        for batch in plan.batches():
            for entry in batch["manifest"]["queries"]:
                self.assertNotIn("core/dependents-direct", entry["template"])
                self.assertFalse(any(value.startswith("<") for value in entry["set"].values()))
        self.assertTrue(any(step.unresolved_parameters for step in plan.steps))

    def test_pattern_dependencies_preserve_neighbours_before_deeper_paths(self):
        plan = _plan('what depends on "Order Service"?', catalogue=self.catalogue)
        neighbours = next(step for step in plan.steps if step.template == "core/neighbours")
        dependents = next(step for step in plan.steps if step.template == "core/dependents")
        self.assertEqual(dependents.depends_on, [neighbours.number])
        self.assertEqual(dependents.status, "awaiting-parameters")

    def test_unknown_availability_and_over_budget_steps_do_not_enter_batches(self):
        self.assertEqual(_plan('what depends on "Order Service"?', catalogue=None).batches(), [])
        self.assertEqual(_plan('what depends on "Order Service"?', catalogue=self.catalogue,
                               budget=1).batches(), [])

    def test_commands_quote_output_paths_and_keep_placeholders_as_single_arguments(self):
        plan = _plan('what depends on "Order Service"?', catalogue=self.catalogue)
        step = next(step for step in plan.steps if "FOCUS_IRI" in step.parameters)
        command = shlex.split(step.command(profile=plan.profile, data=plan.data, endpoint=None,
                                           steps_dir="results with spaces", preview=True))
        self.assertEqual(command[command.index("-o") + 1],
                         step.output_path("results with spaces"))
        self.assertIn(f"FOCUS_IRI={step.parameters['FOCUS_IRI']}", command)
        self.assertIn("--preview", command)

    def test_written_manifest_runs_with_query_and_bundles_unchanged_envelopes(self):
        support.requires_pyoxigraph(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            batches = root / "batches"
            steps = root / "steps"
            done = subprocess.run(
                [sys.executable, str(ROOT / "skills/linked-archi-analyse/scripts/la-analyse"),
                 "plan", "--question", 'what depends on "Orders"?',
                 "--profile", "examples/curated-store", "--data", str(AUGMENTED),
                 "--batch-dir", str(batches), "--steps-dir", str(steps), "--json"],
                capture_output=True, text=True, timeout=120, cwd=ROOT,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            plan = json.loads(done.stdout)
            batch = plan["batches"][0]
            manifest = Path(batch["manifest_path"])
            self.assertEqual(json.loads(manifest.read_text()), batch["manifest"])
            self.assertFalse(steps.exists(), "planning cannot execute or write result envelopes")
            command = shlex.split(batch["command"])
            executed = subprocess.run([sys.executable, str(QUERY), *command[1:]],
                                      capture_output=True, text=True, timeout=120, cwd=ROOT)
            self.assertEqual(executed.returncode, 0, executed.stderr)
            evidence = [entry["out"] for entry in batch["manifest"]["queries"]]
            bundle = build_bundle(evidence).as_dict()
            self.assertEqual(len(bundle["steps"]), 2)
            self.assertEqual([step["template"] for step in bundle["steps"]],
                             ["core/inventory-summary", "core/models"])


class TestCompactText(unittest.TestCase):
    """The text plan is what enters a model's context, and so every later turn.

    It has to say what the JSON says about running the plan - every command, placeholder,
    caveat, decision and stop condition - while stating each thing once.
    """

    QUESTION = 'what depends on "Order Service" if we retire it?'

    @classmethod
    def setUpClass(cls):
        cls.catalogue = _catalogue()

    def _plan(self, batch_dir=None):
        patterns = load_patterns()
        pattern, ranked = resolve_mode(None, self.QUESTION, patterns)
        return build_plan(self.QUESTION, pattern=pattern, ranked=ranked, catalogue=self.catalogue,
                          profile="linked-archi-default", data=["graph.trig"],
                          batch_dir=batch_dir, preview=True)

    def test_steps_are_grouped_by_round(self):
        plan = self._plan("plans")
        text = plan.to_text()
        for round_number in range(1, plan.rounds + 1):
            self.assertIn(f"\nround {round_number}", text)
        self.assertIn("round 3  review round 2 first", text)
        self.assertNotIn("review first:", text, "the round heading says it once")

    def test_a_placeholder_source_is_stated_once(self):
        plan = self._plan("plans")
        text = plan.to_text()
        source = "from core/resolve-element or an element IRI in earlier evidence"
        self.assertEqual(text.count(source), 1)
        self.assertIn("'FOCUS_IRI=<FOCUS_IRI>'", text)
        self.assertIn("placeholders - bind each from reviewed evidence", text)
        # The JSON contract keeps the descriptive placeholder in every command.
        focus = [step for step in plan.as_dict()["steps"] if "FOCUS_IRI" in step["parameters"]]
        self.assertTrue(focus)
        for step in focus:
            self.assertIn(f"FOCUS_IRI=<FOCUS_IRI: {source}>", step["command"])

    def test_a_written_batch_replaces_its_steps_commands(self):
        text = self._plan("plans").to_text()
        self.assertIn("la-query query batch plans/01-orient.json", text)
        self.assertIn("la-query query batch plans/03-resolve+pattern.json", text)
        self.assertNotIn("query run core/inventory-summary", text)
        self.assertNotIn("query run core/discover-relationship-types", text)
        self.assertIn("query run core/neighbours", text)

    def test_unwritten_batches_keep_runnable_step_commands(self):
        text = self._plan().to_text()
        self.assertNotIn("query batch", text, "a manifest nobody wrote cannot be run")
        self.assertIn("query run core/inventory-summary", text)
        self.assertIn("re-plan with --batch-dir DIR", text)

    def test_shared_detail_is_printed_once_with_its_steps(self):
        text = self._plan("plans").to_text()
        stop = "only one notation loaded and the question needs two"
        self.assertEqual(text.count(stop), 1)
        self.assertIn(f"stop if (steps 1, 2): {stop}", text)
        self.assertNotIn("the pattern's own evidence", text)

    def test_nothing_that_governs_execution_is_dropped(self):
        plan = self._plan("plans")
        text = plan.to_text()
        for step in plan.steps:
            with self.subTest(step.number):
                self.assertIn(f"{step.number:02d} {step.template}", text)
                for caveat in step.caveats:
                    self.assertIn(caveat, text)
                if step.stop_when:
                    self.assertIn(step.stop_when, text)
        for condition in plan.pattern_stop_when:
            self.assertIn(condition, text)

    def test_the_text_is_smaller_than_the_json_it_summarises(self):
        plan = self._plan("plans")
        self.assertLess(len(plan.to_text()), len(json.dumps(plan.as_dict(), indent=2)) / 2)

    def test_preview_saves_the_plan_and_prints_it_in_one_call(self):
        script = ROOT / "skills/linked-archi-analyse/scripts/la-analyse"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "plan.json"
            done = subprocess.run(
                [sys.executable, str(script), "plan", "--question", self.QUESTION,
                 "--profile", "linked-archi-default", "--data", "graph.trig",
                 "--json", "-o", str(target), "--preview"],
                capture_output=True, text=True, timeout=120, cwd=ROOT,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(target.read_text())["pattern"], "impact-and-dependency")
            self.assertIn("round 1", done.stdout)
            self.assertIn("placeholders - bind each", done.stdout)
            refused = subprocess.run(
                [sys.executable, str(script), "plan", "--question", self.QUESTION, "--preview"],
                capture_output=True, text=True, timeout=120, cwd=ROOT,
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("--preview needs -o", refused.stderr)


class TestReviewRounds(unittest.TestCase):
    """A step waits for the evidence it needs, not for whichever step was listed before it.

    Every round is a review an agent has to perform before continuing, so a plan that queues
    independent evidence behind unrelated steps costs a model turn per step for nothing. What
    must not change is the other direction: a placeholder never runs before the step that
    supplies it, and a declared method order is never skipped.
    """

    QUESTIONS = (
        ('what depends on "Order Service" if we retire it?', None),
        ('which capability does "Order Service" realise?', "traceability"),
        ("which applications have no owner recorded?", "coverage-and-gaps"),
        ('which principle governs "Order Service"?', "governance-and-decisions"),
        ("which applications in the portfolio are duplicates?", "lifecycle-and-portfolio"),
        ('How is "General CRM System" represented across ArchiMate and LeanIX?', "cross-notation"),
        ('which diagram shows "Order Service"?', "views-and-documentation"),
        ('what is in "Claims Process"?', "model-contents"),
        ("can we trust these models?", "model-quality"),
        ('Which types are grouped by domain under "Strategy Domain"?', "notation-taxonomy"),
        ('Which elements are classified under "Arch component"?', "taxonomy-classification"),
        ("Which viewpoint suits a capability map?", "viewpoint-selection"),
    )

    @classmethod
    def setUpClass(cls):
        cls.catalogues = {profile: _catalogue(profile)
                          for profile in ("linked-archi-default", "examples/curated-store")}

    def _plans(self):
        for profile, catalogue in self.catalogues.items():
            for question, mode in self.QUESTIONS:
                yield f"{profile}:{mode or 'impact'}", _plan(
                    question, mode=mode, profile=profile, catalogue=catalogue)

    @staticmethod
    def _by(plan, template):
        return next(step for step in plan.steps if step.template == template)

    def test_rounds_are_consistent_with_dependencies_in_every_pattern(self):
        for label, plan in self._plans():
            numbers = {step.number: step for step in plan.steps}
            with self.subTest(label):
                for step in plan.steps:
                    self.assertTrue(all(number < step.number for number in step.depends_on),
                                    f"step {step.number} waits for a later step")
                    self.assertEqual(step.round, 1 + max(
                        (numbers[number].round for number in step.depends_on), default=0))
                    if step.stage == "orient":
                        self.assertEqual(step.round, 1)
                    else:
                        self.assertGreater(step.round, 1, "orientation is always reviewed first")
                self.assertEqual(plan.rounds, max(step.round for step in plan.steps))
                self.assertEqual(plan.as_dict()["planned_rounds"], plan.rounds)

    def test_a_placeholder_never_runs_before_the_step_that_supplies_it(self):
        from linked_archi_analyse.plan import PARAMETER_PRODUCERS
        for label, plan in self._plans():
            for step in plan.steps:
                earlier = plan.steps[:step.number - 1]
                for name in step.unresolved_parameters:
                    producers = [other for other in earlier
                                 if other.template in PARAMETER_PRODUCERS.get(name, ())]
                    with self.subTest(f"{label}:{step.template}:{name}"):
                        for producer in producers:
                            self.assertLess(producer.round, step.round)

    def test_batches_hold_only_independent_steps_of_one_round(self):
        for label, plan in self._plans():
            numbers = {step.number: step for step in plan.steps}
            for batch in plan.batches():
                members = [numbers[number] for number in batch["steps"]]
                with self.subTest(f"{label}:{batch['steps']}"):
                    self.assertEqual({member.round for member in members}, {batch["round"]})
                    for member in members:
                        self.assertFalse(set(member.depends_on) & set(batch["steps"]))
                        self.assertTrue(all(numbers[number].round < batch["round"]
                                            for number in member.depends_on))

    def test_independent_evidence_shares_the_resolution_round(self):
        plan = _plan('what depends on "Order Service" if we retire it?',
                     catalogue=self.catalogues["linked-archi-default"])
        resolve = self._by(plan, "core/resolve-element")
        discovery = [self._by(plan, "core/discover-relationship-types"),
                     self._by(plan, "core/reified-predicates")]
        self.assertTrue(all(step.round == resolve.round == 2 for step in discovery))
        batch = next(batch for batch in plan.batches() if batch["round"] == 2)
        self.assertEqual(batch["steps"], sorted([resolve.number] + [s.number for s in discovery]))
        self.assertEqual(batch["stage"], "resolve+pattern")
        self.assertEqual(batch["depends_on"], [1, 2])
        self.assertEqual(plan.rounds, 6)

    def test_declared_order_and_supplied_inputs_still_hold(self):
        plan = _plan('what depends on "Order Service" if we retire it?',
                     catalogue=self.catalogues["linked-archi-default"])
        resolve = self._by(plan, "core/resolve-element")
        discovery = self._by(plan, "core/discover-relationship-types")
        neighbours = self._by(plan, "core/neighbours")
        dependents = self._by(plan, "core/dependents")
        predicates = self._by(plan, "core/reified-predicates")
        direct = self._by(plan, "core/dependents-direct")
        self.assertEqual(neighbours.depends_on, [resolve.number, discovery.number])
        self.assertEqual(dependents.depends_on, [neighbours.number])
        self.assertEqual(direct.depends_on, [dependents.number, predicates.number])
        self.assertGreater(direct.round, dependents.round)

    def test_identity_audit_is_reviewed_before_label_candidates(self):
        for mode, question in (
            ("cross-notation", 'How is "General CRM System" represented across ArchiMate and LeanIX?'),
            ("lifecycle-and-portfolio", "which applications in the portfolio are duplicates?"),
        ):
            with self.subTest(mode):
                plan = _plan(question, mode=mode, profile="examples/curated-store",
                             catalogue=self.catalogues["examples/curated-store"])
                audit = self._by(plan, "core/identity-audit")
                collisions = self._by(plan, "core/label-collisions")
                self.assertIn(audit.number, collisions.depends_on)
                self.assertGreater(collisions.round, audit.round)
                self.assertNotIn(collisions.number,
                                 [n for batch in plan.batches() if audit.number in batch["steps"]
                                  for n in batch["steps"]])

    def test_a_refused_audit_still_holds_its_candidates_for_review(self):
        plan = _plan('How is "General CRM System" represented across ArchiMate and LeanIX?',
                     mode="cross-notation", catalogue=self.catalogues["linked-archi-default"])
        self.assertEqual([d["template"] for d in plan.decisions], ["core/identity-audit"])
        collisions = self._by(plan, "core/label-collisions")
        self.assertEqual(collisions.status, "review-required")
        self.assertFalse(any(collisions.number in batch["steps"] for batch in plan.batches()))

    def test_evidence_closing_steps_wait_for_everything_before_them(self):
        for label, plan in self._plans():
            ancestors = {}
            for step in plan.steps:
                ancestors[step.number] = set(step.depends_on).union(
                    *(ancestors[number] for number in step.depends_on))
                if step.template == "core/provenance":
                    with self.subTest(label):
                        self.assertEqual(ancestors[step.number], set(range(1, step.number)))

    def test_a_notation_template_waits_for_the_model_it_describes(self):
        plan = _plan('what is in "Claims Process"?', mode="model-contents",
                     catalogue=self.catalogues["linked-archi-default"])
        model = self._by(plan, "core/resolve-model")
        for template in ("notation/bpmn/process-components", "notation/c4/containers"):
            with self.subTest(template):
                self.assertIn(model.number, self._by(plan, template).depends_on)

    def test_views_wait_for_the_views_they_take(self):
        plan = _plan('which diagram shows "Order Service"?', mode="views-and-documentation",
                     catalogue=self.catalogues["linked-archi-default"])
        views = self._by(plan, "core/views")
        resolve = self._by(plan, "core/resolve-element")
        self.assertEqual(self._by(plan, "core/view-contents").depends_on, [views.number])
        self.assertEqual(self._by(plan, "core/view-diff").depends_on, [views.number])
        self.assertEqual(self._by(plan, "core/view-usage").depends_on, [resolve.number])
        self.assertEqual(plan.rounds, 4)

    def test_an_unannotated_plan_keeps_every_pattern_step_in_sequence(self):
        """Without parameter names nothing can be shown independent, so nothing is."""
        plan = _plan('what depends on "Order Service" if we retire it?', catalogue=None)
        pattern = [step for step in plan.steps if step.stage in ("pattern", "quality")]
        for previous, step in zip(pattern, pattern[1:]):
            self.assertEqual(step.depends_on, [previous.number])
        self.assertEqual(plan.rounds, len(plan.steps) - 1)

    def test_independent_model_questions_share_one_round(self):
        """A concern's published questions take no evidence from one another."""
        from linked_archi_analyse.plan import concern_pattern

        catalogue = self.catalogues["linked-archi-default"]

        def unbound(spec):
            return any(name != "LIMIT" and "default" not in parameter
                       and not parameter.get("optional")
                       for name, parameter in (spec.get("parameters") or {}).items())

        names = sorted(name for name, spec in catalogue["templates"].items()
                       if spec.get("question") and spec.get("available") and not unbound(spec))[:4]
        self.assertEqual(len(names), 4)
        pattern = concern_pattern(["test"], {name: catalogue["templates"][name] for name in names})
        plan = build_plan("concern", pattern=pattern, ranked=[], catalogue=catalogue,
                          profile="linked-archi-default", data=["graph.trig"])
        questions = [step for step in plan.steps if step.template in names]
        self.assertEqual(len(questions), 4)
        self.assertEqual({step.round for step in questions}, {2})
        self.assertEqual(next(batch for batch in plan.batches() if batch["round"] == 2)["steps"],
                         [step.number for step in questions])


class TestSelectiveCatalogue(unittest.TestCase):
    def test_the_normal_path_requests_only_required_metadata(self):
        response = subprocess.CompletedProcess([], 0, json.dumps({"schema_version": 1, "templates": {}}), "")
        with mock.patch.object(analyse_cli, "_companion", return_value=QUERY), \
                mock.patch.object(analyse_cli.subprocess, "run", return_value=response) as run:
            _document, preview = analyse_cli._catalogue("linked-archi-default", ["core/models", "core/resolve-element"])
        self.assertTrue(preview)
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command.count("--template"), 2)
        self.assertIn("core/models", command)
        self.assertIn("core/resolve-element", command)

    def test_a_companion_without_filtered_catalogue_support_keeps_the_existing_contract(self):
        failed = subprocess.CompletedProcess([], 2, "", "unrecognized arguments: --template")
        document = {"schema_version": 1, "templates": {"core/models": {"parameters": {}}}}
        succeeded = subprocess.CompletedProcess([], 0, json.dumps(document), "")
        with mock.patch.object(analyse_cli, "_companion", return_value=QUERY), \
                mock.patch.object(analyse_cli.subprocess, "run", side_effect=[failed, succeeded]) as run:
            result = analyse_cli._catalogue("linked-archi-default", ["core/models"])
        self.assertEqual(result, (document, False))
        self.assertEqual(run.call_count, 2)
        self.assertNotIn("--template", run.call_args.args[0])

    def test_legacy_companion_plans_omit_new_flags_from_steps_and_batches(self):
        catalogue = _catalogue()
        failed = subprocess.CompletedProcess([], 2, "", "unrecognized arguments: --template")
        succeeded = subprocess.CompletedProcess([], 0, json.dumps(catalogue), "")
        for machine in (False, True):
            with self.subTest(machine=machine):
                output = io.StringIO()
                request = {"schema_version": 1, "question": 'what depends on "Orders"?',
                           "profile": "linked-archi-default", "data": ["graph.trig"]}
                with mock.patch.object(analyse_cli, "_companion", return_value=QUERY), \
                        mock.patch.object(analyse_cli.subprocess, "run", side_effect=[failed, succeeded]), \
                        mock.patch.object(sys, "stdin", io.StringIO(json.dumps(request))), \
                        redirect_stdout(output):
                    if machine:
                        analyse_cli.cmd_machine_plan(None)
                    else:
                        args = analyse_cli.build_parser().parse_args([
                            "plan", "--question", request["question"], "--profile", request["profile"],
                            "--data", "graph.trig", "--json",
                        ])
                        analyse_cli.cmd_plan(args)
                plan = json.loads(output.getvalue())
                self.assertTrue(plan["batches"])
                self.assertTrue(plan["annotated"])
                for item in plan["steps"] + plan["batches"]:
                    command = shlex.split(item["command"])
                    self.assertNotIn("--preview", command)
                    self.assertNotIn("--limit", command)
                for step in plan["steps"]:
                    self.assertIn("--json", shlex.split(step["command"]))
                    self.assertIn("-o", shlex.split(step["command"]))

    def test_direct_planner_call_defaults_to_compatible_command_flags(self):
        pattern, ranked = resolve_mode(None, 'what depends on "Orders"?', load_patterns())
        plan = build_plan('what depends on "Orders"?', pattern=pattern, ranked=ranked,
                          catalogue=_catalogue(), profile="linked-archi-default", data=["graph.trig"])
        self.assertTrue(plan.batches())
        for item in plan.as_dict()["steps"] + plan.batches():
            self.assertNotIn("--preview", shlex.split(item["command"]))
            self.assertNotIn("--limit", shlex.split(item["command"]))


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
