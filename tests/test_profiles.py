"""Profiles: loading, inheritance, validation, and drift detection.

The profile is where every vocabulary decision lives, so a mistake here is a mistake
in every query. These tests care most about the failure paths: a profile that loads
when it should not is how a wrong binding reaches a graph.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import support
from support import AUGMENTED, BASE, CONVERTER_13, FLAT, requires_pyoxigraph

from linked_archi_profile.derive import DeriveError, read_type_mapping
from linked_archi_profile.profile import (
    LAYOUTS,
    PROFILE_DIR,
    REQUIRED_ROLES,
    Profile,
    ProfileError,
    format_findings,
    load_profile,
    verify_against_dataset,
    worst_severity,
)

BUNDLED = [
    "linked-archi-default",
    "linked-archi-direct",
    "linked-archi-merged",
    "cloudplatform",
    "curated-store",
    "flattened-turtle",
]


class TestLoading(unittest.TestCase):
    def test_every_bundled_profile_loads(self):
        for name in BUNDLED:
            with self.subTest(name):
                profile = load_profile(name)
                self.assertEqual(profile.name, name)
                self.assertIn(profile.graphs.layout, LAYOUTS)

    def test_reference_forms_are_equivalent(self):
        by_name = load_profile("linked-archi-default")
        by_path = load_profile(PROFILE_DIR / "linked-archi-default.yaml")
        by_relative = load_profile("profiles/linked-archi-default.yaml")
        self.assertEqual(by_name.as_dict(), by_path.as_dict())
        self.assertEqual(by_name.as_dict(), by_relative.as_dict())

    def test_unknown_profile_lists_what_exists(self):
        with self.assertRaises(ProfileError) as caught:
            load_profile("no-such-profile")
        self.assertIn("linked-archi-default", str(caught.exception))

    def test_required_roles_are_all_bound(self):
        for name in BUNDLED:
            profile = load_profile(name)
            for role in REQUIRED_ROLES:
                with self.subTest(profile=name, role=role):
                    self.assertTrue(profile.has_role(role))


class TestInheritance(unittest.TestCase):
    def test_child_inherits_and_overrides(self):
        base = load_profile("linked-archi-default")
        direct = load_profile("linked-archi-direct")
        self.assertFalse(base.capability("direct_rel_triples"))
        self.assertTrue(direct.capability("direct_rel_triples"))
        # Untouched keys carry through.
        self.assertEqual(base.role("label"), direct.role("label"))
        self.assertEqual(base.namespaces, direct.namespaces)

    def test_custom_profile_adds_a_role_without_restating_the_rest(self):
        custom = load_profile("cloudplatform")
        self.assertEqual(
            custom.role("resilience_level"),
            "https://meta.linked.archi/examples/cloudplatform/onto#resilienceLevel",
        )
        self.assertEqual(
            custom.role("label"), "http://www.w3.org/2004/02/skos/core#prefLabel"
        )

    def test_mappings_merge_key_by_key(self):
        merged = load_profile("linked-archi-merged")
        # Added by the child.
        self.assertTrue(merged.graphs.has_role("reconciliation"))
        # Still present from the parent.
        self.assertTrue(merged.graphs.has_role("semantic"))

    def test_lists_replace_rather_than_append(self):
        """A fallback chain is one decision; appending would change what ROLE resolves to."""
        parent = Profile({
            "profile": "p",
            "namespaces": {"ex": "http://e/"},
            "roles": {
                "label": ["ex:one", "ex:two"],
                "concept_class": "ex:C",
                "element_class": "ex:E",
                "relationship_class": "ex:R",
                "rel_source": "ex:s",
                "rel_target": "ex:t",
                "rel_type": "ex:ty",
            },
        })
        self.assertEqual(len(parent.expand_role("label")), 2)

        child_document = dict(parent.as_dict())
        child_document["roles"] = dict(child_document["roles"])
        child_document["roles"]["label"] = ["ex:three"]
        child = Profile(child_document)
        self.assertEqual(child.expand_role("label"), ["http://e/three"])

    def test_missing_parent_names_both_paths_tried(self):
        broken = Path(support.ROOT) / "tests" / "_broken-extends.yaml"
        broken.write_text("extends: nope.yaml\nprofile: x\n", encoding="utf-8")
        try:
            with self.assertRaises(ProfileError) as caught:
                load_profile(broken)
            message = str(caught.exception)
            self.assertIn("nope.yaml", message)
            self.assertIn("profiles", message)
        finally:
            broken.unlink()

    def test_derived_profile_inherits_from_outside_the_repo(self):
        """The common case: a team keeps its profile beside its graph."""
        elsewhere = Path(support.ROOT) / "tests" / "_elsewhere.yaml"
        elsewhere.write_text(
            "extends: linked-archi-default.yaml\nprofile: elsewhere\n", encoding="utf-8"
        )
        try:
            profile = load_profile(elsewhere)
            self.assertEqual(profile.name, "elsewhere")
            self.assertEqual(
                profile.role("label"), "http://www.w3.org/2004/02/skos/core#prefLabel"
            )
        finally:
            elsewhere.unlink()


class TestValidation(unittest.TestCase):
    MINIMAL = {
        "profile": "minimal",
        "namespaces": {"ex": "http://e/"},
        "roles": {
            "concept_class": "ex:C",
            "element_class": "ex:E",
            "relationship_class": "ex:R",
            "rel_source": "ex:s",
            "rel_target": "ex:t",
            "rel_type": "ex:ty",
            "label": "ex:l",
        },
    }

    def _with(self, **overrides):
        document = {k: dict(v) if isinstance(v, dict) else v
                    for k, v in self.MINIMAL.items()}
        document.update(overrides)
        return document

    def test_minimal_profile_is_valid(self):
        Profile(self.MINIMAL)

    def test_notation_presence_must_be_a_tristate(self):
        """A typo must not read as absent.

        `present` is the one key inside a notation spec that changes behaviour, and the
        behaviour it changes is refusal. An unrecognised value reaching the query side would
        be neither true nor "partial", so every template for that notation would be refused
        over a spelling.
        """
        for value in ("yes", "true", 1, 0, "absent", []):
            with self.subTest(value=value):
                with self.assertRaises(ProfileError) as caught:
                    Profile(self._with(
                        notations={"bpmn": {"namespace": "ex", "present": value}}
                    ))
                self.assertIn("present", str(caught.exception))

    def test_notation_presence_accepts_the_tristate(self):
        for value in (True, False, "partial"):
            with self.subTest(value=value):
                Profile(self._with(
                    notations={"bpmn": {"namespace": "ex", "present": value}}
                ))

    def test_a_notation_may_omit_presence(self):
        """Unstated is the default and has to stay valid: it means unknown."""
        Profile(self._with(notations={"bpmn": {"namespace": "ex"}}))

    def test_namespace_bindings_must_be_stripped_and_non_empty(self):
        for namespaces in (
            {"ex": "  "},
            {"ex": " http://e/"},
            {" ex": "http://e/"},
        ):
            with self.subTest(namespaces=namespaces):
                with self.assertRaisesRegex(ProfileError, "namespaces"):
                    Profile(self._with(namespaces=namespaces))

    def test_unknown_layout_refused(self):
        with self.assertRaises(ProfileError):
            Profile(self._with(graphs={"layout": "sideways"}))

    def test_single_layout_contradicting_named_graphs_refused(self):
        with self.assertRaises(ProfileError) as caught:
            Profile(self._with(graphs={"layout": "single", "named_graphs": True}))
        self.assertIn("contradicts", str(caught.exception))

    def test_explicit_layout_requires_absolute_iris(self):
        for iri in ("graph/semantic", "https://example.org/graph with space"):
            with self.subTest(iri=iri):
                with self.assertRaises(ProfileError):
                    Profile(self._with(graphs={
                        "layout": "explicit",
                        "roles": {"semantic": iri},
                    }))
        Profile(self._with(graphs={
            "layout": "explicit",
            "roles": {"semantic": "https://e/g/semantic"},
        }))

    def test_role_iris_reject_illegal_characters(self):
        for iri in (
            "https://example.org/label with space",
            "https://example.org/a#b#c",
            "https://example.org/[",
            "ex:bad#one#two",
        ):
            with self.subTest(iri=iri):
                roles = {**self.MINIMAL["roles"], "label": iri}
                with self.assertRaises(ProfileError):
                    Profile(self._with(roles=roles))

    def test_graph_role_bindings_must_be_non_empty(self):
        with self.assertRaisesRegex(ProfileError, "graph roles"):
            Profile(self._with(graphs={
                "layout": "per-model-triple",
                "roles": {"semantic": "  "},
            }))

    def test_missing_required_role_refused(self):
        document = self._with()
        del document["roles"]["label"]
        with self.assertRaises(ProfileError) as caught:
            Profile(document)
        self.assertIn("label", str(caught.exception))

    def test_capability_must_be_tristate(self):
        with self.assertRaises(ProfileError) as caught:
            Profile(self._with(capabilities={"direct_rel_triples": "yes"}))
        self.assertIn("true, false or 'partial'", str(caught.exception))
        Profile(self._with(capabilities={"views_graph": "partial"}))

    def test_label_language_is_exempt_from_tristate(self):
        Profile(self._with(capabilities={"label_language": "en"}))

    def test_version_must_be_a_positive_integer(self):
        for value in (True, "bad", 0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ProfileError, "positive integer"):
                    Profile(self._with(version=value))

    def test_label_language_is_a_non_empty_string(self):
        Profile(self._with(capabilities={"label_language": "en"}))
        for value in (False, 1, ""):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ProfileError, "non-empty string"):
                    Profile(self._with(capabilities={"label_language": value}))

    def test_bad_prefix_fails_at_load_not_at_query_time(self):
        with self.assertRaises(ProfileError) as caught:
            Profile(self._with(roles={**self.MINIMAL["roles"], "label": "nope:thing"}))
        self.assertIn("nope", str(caught.exception))

    def test_null_role_refuses_with_an_explanation(self):
        profile = load_profile("linked-archi-default")
        self.assertFalse(profile.has_role("owner"))
        with self.assertRaises(ProfileError) as caught:
            profile.role("owner")
        self.assertIn("does not represent it", str(caught.exception))

    def test_undeclared_capability_reads_false(self):
        profile = load_profile("linked-archi-default")
        self.assertFalse(profile.capability("no_such_capability"))


class TestTypeMappingValidation(unittest.TestCase):
    def _read(self, document):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.yaml"
            path.write_text(json.dumps(document), encoding="utf-8")
            return read_type_mapping(path)

    def test_every_supported_section_has_an_exact_container_shape(self):
        mapping_sections = (
            "namespaces", "vocab", "elements", "relationships", "predicates",
            "qualifiedPredicates", "metadata-predicates", "spec-relations",
        )
        list_sections = ("object-properties", "spec-literals")
        for section in mapping_sections:
            for bad in (None, [], "not-a-mapping", {"key": "  "}):
                with self.subTest(section=section, bad=bad):
                    with self.assertRaisesRegex(DeriveError, section):
                        self._read({section: bad})
        for section in list_sections:
            for bad in (None, {}, "not-a-list", ["  "]):
                with self.subTest(section=section, bad=bad):
                    with self.assertRaisesRegex(DeriveError, section):
                        self._read({section: bad})

    def test_complete_type_mapping_shape_is_accepted(self):
        document = {
            "namespaces": {"ex": "https://example.org/"},
            "vocab": {"arch:Element": "https://example.org/Element"},
            "elements": {"Component": "https://example.org/Component"},
            "relationships": {"Uses": "https://example.org/Uses"},
            "predicates": {"Uses": "https://example.org/uses"},
            "qualifiedPredicates": {"Uses": "https://example.org/hasUses"},
            "metadata-predicates": {"owner": "https://example.org/owner"},
            "object-properties": ["https://example.org/uses"],
            "spec-relations": {"parent": "https://example.org/parent"},
            "spec-literals": ["https://example.org/status"],
            "ignored-converter-section": {"anything": True},
        }
        mapping = self._read(document)
        self.assertEqual(mapping.namespaces, document["namespaces"])
        self.assertEqual(mapping.spec_literals, document["spec-literals"])


class TestTermResolution(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile("linked-archi-default")

    def test_role_resolves_to_absolute_iri(self):
        self.assertEqual(
            self.profile.role("label"), "http://www.w3.org/2004/02/skos/core#prefLabel"
        )

    def test_chain_preserves_order(self):
        chain = self.profile.expand_role("native_id")
        self.assertEqual(chain[0], "http://www.w3.org/2004/02/skos/core#notation")
        self.assertIn("https://meta.linked.archi/bpmn/onto#id", chain)

    def test_absolute_iri_passes_through(self):
        self.assertEqual(
            self.profile.expand_term("https://example.org/x"), "https://example.org/x"
        )
        self.assertEqual(
            self.profile.expand_term("<https://example.org/x>"), "https://example.org/x"
        )

    def test_prefix_block_covers_every_namespace(self):
        block = self.profile.prefix_block()
        self.assertEqual(len(block.splitlines()), len(self.profile.namespaces))
        self.assertIn("PREFIX arch: <https://meta.linked.archi/core#>", block)

    def test_notation_lookup_by_metamodel(self):
        self.assertEqual(
            self.profile.notation_for_metamodel(
                "https://meta.linked.archi/bpmn/metamodel#BPMN2"
            ),
            "bpmn",
        )
        self.assertIsNone(self.profile.notation_for_metamodel("https://e/unknown"))

    def test_every_metamodel_the_fixtures_assert_is_recognised(self):
        """Checked against converter output, because a near-miss here is silent.

        `notation_for_metamodel` compares the profile's string to the dataset's, so a
        profile naming `leanix/metamodel#LeanIX` where every converter writes
        `#LeanIXv4` answers None: the notation is simply never detected, with no error
        and no empty result to notice. Verifying one notation by hand is how that
        survived, so this asserts over every metamodel the committed fixtures actually
        declare rather than over a chosen example.
        """
        pattern = re.compile(r"modelConformsToMetamodel\s+<([^>]+)>")
        asserted = set()
        for fixture in (BASE, AUGMENTED, FLAT, CONVERTER_13):
            asserted |= set(pattern.findall(fixture.read_text()))
        self.assertTrue(asserted, "no metamodel assertions found in the fixtures")
        unrecognised = sorted(
            iri for iri in asserted
            if self.profile.notation_for_metamodel(iri) is None
        )
        self.assertEqual(
            unrecognised, [],
            "linked-archi-default declares no notation for: " + ", ".join(unrecognised),
        )

    def test_archimate_notation_slug_is_model(self):
        """Not `archimate`: the converter's --path-model defaults to `model`."""
        self.assertIn("model", self.profile.notations)

    def test_row_limit_is_capped(self):
        ceiling = int(self.profile.limits["max_row_limit"])
        self.assertEqual(self.profile.row_limit(999_999), ceiling)
        self.assertEqual(self.profile.row_limit(10), 10)
        self.assertEqual(
            self.profile.row_limit(), int(self.profile.limits["default_row_limit"])
        )


class TestDriftDetection(unittest.TestCase):
    """A profile is a set of claims. These tests check the claims get checked."""

    def setUp(self):
        requires_pyoxigraph(self)

    def test_default_profile_matches_the_base_fixture(self):
        profile = load_profile("linked-archi-default")
        findings = verify_against_dataset(profile, support.load_fixture(BASE))
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual(errors, [], format_findings(findings))
        self.assertNotEqual(worst_severity(findings), "error")

    def test_curated_profile_matches_the_augmented_fixture(self):
        profile = load_profile("curated-store")
        findings = verify_against_dataset(profile, support.load_fixture(AUGMENTED))
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual(errors, [], format_findings(findings))

    def _presence(self, profile_name, fixture, **overrides):
        """Findings from the notation-presence pass, with `present` claims applied.

        Overrides are written onto the loaded profile's notation specs, because presence is
        a fact about a dataset and no bundled profile states one - they cannot know which
        dataset they will meet.
        """
        from linked_archi_profile.profile import _verify_notation_presence, _batched

        profile = load_profile(profile_name)
        for slug, value in overrides.items():
            profile.notations[slug] = dict(profile.notations.get(slug) or {})
            profile.notations[slug]["present"] = value
        return _batched(
            lambda probe: _verify_notation_presence(profile, probe),
            support.load_fixture(fixture),
        )

    def test_a_declared_notation_with_no_model_is_reported(self):
        """The fixtures carry five notations. The default profile declares six.

        PlantUML is the sixth, and nothing in the dataset conforms to the UML metamodel, so
        every UML question here can only come back empty. Reporting it is what lets an
        operator record the claim that turns those empty answers into refusals.
        """
        findings = self._presence("linked-archi-default", BASE)
        warnings = [f for f in findings if f.severity == "warning"]
        self.assertTrue(warnings, format_findings(findings))
        self.assertTrue(
            any("plantuml" in f.message for f in warnings),
            format_findings(findings),
        )
        present = next(f for f in findings if f.severity == "info")
        for slug in ("backstage", "bpmn", "c4", "leanix", "model"):
            self.assertIn(slug, present.message)

    def test_presence_is_measured_in_a_dataset_with_no_named_graphs(self):
        """The regression this pass was written around.

        Turtle carries no graph identity, so a flattened dataset holds its models in the
        default graph. Asked with `GRAPH ?g` alone - which is how the neighbouring metamodel
        pairing probe asked it - every notation on flat.ttl came back absent, and a pass
        that cannot see a single model would have declared five notations missing. The
        UNION form is not a nicety here; it is the difference between measuring and
        guessing.
        """
        findings = self._presence("examples/flattened-turtle", FLAT)
        present = next(f for f in findings if f.severity == "info")
        for slug in ("backstage", "bpmn", "c4", "leanix", "model"):
            self.assertIn(slug, present.message)

    def test_claiming_a_notation_the_dataset_lacks_is_reported(self):
        findings = self._presence("linked-archi-default", BASE, plantuml=True)
        self.assertTrue(
            any(
                f.severity == "warning"
                and "declared present" in f.message
                and "plantuml" in f.message
                for f in findings
            ),
            format_findings(findings),
        )

    def test_recording_a_notation_absent_when_it_is_here_is_reported(self):
        """The direction that costs answers rather than inventing them.

        A stale `present: false` refuses templates the dataset can support, which is a
        quieter failure than the other way round: the operator sees a refusal naming a
        notation and has no reason to doubt it.
        """
        findings = self._presence("linked-archi-default", BASE, bpmn=False)
        self.assertTrue(
            any(
                f.severity == "warning"
                and "recorded absent" in f.message
                and "bpmn" in f.message
                for f in findings
            ),
            format_findings(findings),
        )

    def test_a_partial_notation_is_not_contradicted(self):
        """An ASK answers yes or no and cannot speak to "some models, not others"."""
        findings = self._presence("linked-archi-default", BASE, bpmn="partial")
        self.assertFalse(
            any(f.severity == "warning" and "bpmn" in f.message for f in findings),
            format_findings(findings),
        )

    def test_verify_and_recommend_agree_about_which_notations_are_here(self):
        """Two commands measuring one dataset must not contradict each other.

        The precedent is `direct_rel_triples`, where `recommend` reported a form as
        converted while `verify` called the same capability unverifiable - and a reader
        given two answers has no way to choose. Presence is measured twice for good
        reasons: `verify` reads through the user's profile, `recommend` through the
        published vocabulary as a lens. The measurement has to match where the two
        overlap.
        """
        from linked_archi_profile.profile import observe_dataset

        for fixture in (BASE, FLAT):
            with self.subTest(fixture=fixture.name):
                observed = next(
                    o for o in observe_dataset(support.load_fixture(fixture))
                    if o.subject == "notations"
                )
                from_recommend = set(observed.value.split(", "))
                info = next(
                    f for f in self._presence("linked-archi-default", fixture)
                    if f.severity == "info"
                )
                from_verify = set(info.message.removeprefix("models present for: ").split(", "))
                self.assertEqual(from_recommend, from_verify)

    def test_notation_presence_never_fails_verification(self):
        """Presence is drift to report, not a broken profile.

        The default profile declares six notations and no dataset is obliged to hold all
        six, so an error here would make every bundled profile fail against any real store.
        The metamodel pairing probe made the same call for the same reason.
        """
        for profile_name, fixture in (
            ("linked-archi-default", BASE),
            ("curated-store", AUGMENTED),
            ("examples/flattened-turtle", FLAT),
        ):
            findings = self._presence(profile_name, fixture)
            self.assertEqual(
                [f for f in findings if f.severity == "error"], [],
                f"{profile_name}: {format_findings(findings)}",
            )

    def test_claiming_a_capability_the_dataset_lacks_is_an_error(self):
        """The direct-triples profile against default-flag output. The whole point."""
        profile = load_profile("linked-archi-direct")
        findings = verify_against_dataset(profile, support.load_fixture(BASE))
        errors = [f for f in findings if f.severity == "error"]
        self.assertTrue(errors, "expected drift to be reported")
        self.assertTrue(
            any("direct_rel_triples" in f.subject for f in errors),
            format_findings(errors),
        )
        self.assertEqual(worst_severity(findings), "error")

    def test_a_capability_present_for_some_relationships_is_reported_as_partial(self):
        """Presence and coverage are different questions, and only one is useful here.

        An existence probe answers "does this dataset have the bridge" and then recommends
        `true`, which overstates every dataset where the bridge is notation-specific - the
        normal case, since each converter emits it only under its own flag. The augmented
        fixture is exactly that shape by design: the bridge covers only the relationship
        classes whose ontology declares an `arch:unqualifiedForm`.

        So a profile claiming `false` here must not be told to claim `true`. `partial` is
        the only value that neither promises completeness nor refuses templates the data
        can partly answer.
        """
        profile = load_profile("linked-archi-default")
        findings = verify_against_dataset(profile, support.load_fixture(AUGMENTED))
        relevant = [f for f in findings if f.subject == "capabilities.rdf_reifies"]
        self.assertTrue(relevant, format_findings(findings))
        self.assertEqual(relevant[0].severity, "warning")
        self.assertIn("absent for others", relevant[0].message)
        self.assertEqual(relevant[0].fix, ("capabilities.rdf_reifies", "partial"))

    def test_a_partial_claim_is_confirmed_by_coverage(self):
        """And the curated profile, which says `partial`, is told it is right."""
        profile = load_profile("curated-store")
        findings = verify_against_dataset(profile, support.load_fixture(AUGMENTED))
        relevant = [f for f in findings if f.subject == "capabilities.rdf_reifies"]
        self.assertTrue(relevant, format_findings(findings))
        self.assertEqual(relevant[0].severity, "info")
        self.assertIn("partial", relevant[0].message)

    def test_partial_vocabulary_pairing_is_reported(self):
        """The cost of pairing vocabulary at query time, made visible.

        The operator chooses which files to attach, and a partial or mismatched choice
        fails in the quietest possible way: no error, just a grouping query returning
        fewer categories, with every element of an uncovered notation absent. That reads
        as "this model has none of those".

        The fixture pairs a five-notation dataset with BPMN vocabulary and the class
        hierarchies of the three notations carried whole for the path check, so ArchiMate is
        the one still uncovered and must be named. A notation
        ontology carries its version in its namespace, so this same probe is what pairing
        the wrong version looks like.

        Backstage, C4 and LeanIX were in this list until their hierarchies were added for
        the path check, which needs them to tell "unrelated to any constrained class" from
        "the hierarchy is not attached". Their leaving it is the probe working, not a
        regression.
        """
        findings = verify_against_dataset(
            load_profile("curated-store"),
            support.load_fixture(AUGMENTED, support.VOCABULARY),
        )
        relevant = [f for f in findings
                    if f.subject == "graphs.roles.vocabulary" and f.severity == "warning"]
        self.assertTrue(relevant, format_findings(findings))
        message = relevant[0].message
        self.assertIn("archimate3/onto#", message)
        for attached, why in (
            ("bpmn/onto#", "BPMN vocabulary is attached"),
            ("backstage/onto#", "the Backstage hierarchy is attached for the path check"),
            ("c4/onto#", "the C4 hierarchy is attached for the path check"),
            ("leanix/onto#", "the LeanIX hierarchy is attached for the path check"),
        ):
            self.assertNotIn(
                attached, message, f"{why}, so it must not be reported as uncovered"
            )

    def test_vocabulary_is_readable_where_a_turtle_file_actually_lands(self):
        """Paired vocabulary must work as fetched, not only after hand-editing it.

        This is the test that was missing. `meta.linked.archi` serves every ontology,
        taxonomy and shape set as `text/turtle`, and `la-connect` loads a Turtle file into
        the default graph - so binding the role to a named-graph suffix asked for a graph
        the artifact does not have. Measured on this same fixture before the fix: five rows
        when the vocabulary sat in a named graph, none when the identical triples sat in the
        default graph, and no error in either direction.

        Asserted through the probe rather than a template so it holds for every consumer of
        the role: a covered notation must not be reported as uncovered.
        """
        profile = load_profile("curated-store")
        self.assertTrue(
            profile.graphs.is_default_graph("vocabulary"),
            "published vocabulary is Turtle, so the role belongs in the default graph",
        )
        findings = verify_against_dataset(
            profile, support.load_fixture(AUGMENTED, support.VOCABULARY)
        )
        warnings = [f for f in findings
                    if f.subject == "graphs.roles.vocabulary" and f.severity == "warning"]
        self.assertTrue(warnings, format_findings(findings))
        self.assertNotIn(
            "bpmn/onto#", warnings[0].message,
            "BPMN vocabulary is attached and readable, so it is not uncovered - if this "
            "fails, the role is being scoped to a graph the Turtle file does not have",
        )

    def test_a_default_graph_role_has_no_suffix_to_test(self):
        """Asking for one is a programming error, not a filter on the word 'default'."""
        profile = load_profile("curated-store")
        with self.assertRaises(ProfileError):
            profile.graphs.suffix_test("vocabulary", "?g")

    def test_a_declared_metamodel_with_no_manifest_is_reported(self):
        """"No constraint found" must never be readable as "nothing is wrong".

        Every model declares `arch:modelConformsToMetamodel`, and each published
        `arch:Metamodel` manifest names its own ontology, taxonomy and shapes. A check
        that walks those to decide whether a query's path is possible finds nothing for a
        notation whose shapes were never attached - identical, from the inside, to a query
        with no violations. So the gap is reported before anything relies on it.

        The fixtures make the case concrete: they declare five metamodels and no manifest
        for any of them.
        """
        findings = verify_against_dataset(
            load_profile("curated-store"),
            support.load_fixture(AUGMENTED, support.VOCABULARY),
        )
        warnings = [f for f in findings if f.subject == "metamodel.manifest"
                    and f.severity == "warning"]
        self.assertTrue(warnings, format_findings(findings))
        message = warnings[0].message
        for notation in ("backstage", "bpmn", "c4", "leanix", "model"):
            self.assertIn(notation, message)
        self.assertIn("la-source url", message, "the fix has to name the command")

    def test_the_report_distinguishes_a_missing_manifest_from_missing_assets(self):
        """Two different gaps needing two different actions.

        Verified end to end against the live publisher while this was written: fetching
        `archimate3/metamodel` alone moved ArchiMate out of the manifest warning and into
        the assets one, and fetching the ontology, taxonomy and shapes it names silenced
        both. Here the manifest is synthesised so the test needs no network.
        """
        import tempfile
        from pathlib import Path

        from linked_archi_connect.adapters import open_adapter

        # Paired as a file, like the real thing, rather than by mutating a cached adapter
        # other tests share. Two triples are enough: the manifest exists and names one
        # asset namespace that is not attached.
        manifest = (
            "@prefix arch: <https://meta.linked.archi/core#> .\n"
            "<https://meta.linked.archi/archimate3/metamodel#ArchiMate3.2>\n"
            "    a arch:Metamodel ;\n"
            "    arch:formalRules <https://meta.linked.archi/archimate3/shapes#> .\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archimate3-metamodel.ttl"
            path.write_text(manifest, encoding="utf-8")
            adapter = open_adapter(data=[AUGMENTED, support.VOCABULARY, path])
            findings = verify_against_dataset(load_profile("curated-store"), adapter)
        subjects = {f.subject for f in findings if f.severity == "warning"}
        self.assertIn("metamodel.assets", subjects, format_findings(findings))
        reported = [f for f in findings if f.subject == "metamodel.manifest"
                    and f.severity == "warning"]
        self.assertTrue(reported)
        self.assertNotIn(
            "model (", reported[0].message,
            "ArchiMate's manifest IS attached now, so only its assets are missing",
        )

    def test_no_vocabulary_role_means_no_pairing_findings(self):
        """Silence where there is nothing to pair, or every profile gains noise."""
        findings = verify_against_dataset(
            load_profile("linked-archi-default"), support.load_fixture(BASE)
        )
        self.assertEqual(
            [f for f in findings if f.subject == "graphs.roles.vocabulary"], [],
        )

    def test_claiming_absence_of_something_present_is_only_a_warning(self):
        """Over-caution refuses templates unnecessarily; it does not mislead."""
        profile = load_profile("linked-archi-default")
        findings = verify_against_dataset(profile, support.load_fixture(AUGMENTED))
        relevant = [f for f in findings if "validation_in_graph" in f.subject]
        self.assertTrue(relevant)
        self.assertEqual(relevant[0].severity, "warning")
        self.assertIn("claimed false but present", relevant[0].message)

    def test_graph_scoping_profile_against_flat_data_is_an_error(self):
        profile = load_profile("linked-archi-default")
        findings = verify_against_dataset(profile, support.load_fixture(FLAT))
        errors = [f for f in findings if f.severity == "error"]
        self.assertTrue(any("named_graphs" in f.subject for f in errors),
                        format_findings(findings))

    def test_flattened_profile_matches_flat_data(self):
        profile = load_profile("flattened-turtle")
        findings = verify_against_dataset(profile, support.load_fixture(FLAT))
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual(errors, [], format_findings(findings))


class TestMissingRequiredGraphRole(unittest.TestCase):
    """A required graph role that matches nothing is an error, not a warning.

    This is the difference between a wrong answer and a refusal. The pre-1.3 default
    profile scopes its queries with a suffix selector, and the final 1.3 layout
    partitions the semantic graph into ``graph/semantic/{repo}/{path}``. A suffix
    cannot match a descendant, so every scoped query against a 1.3 dataset returns
    nothing - and reporting that as a warning while exiting 0 is how "no rows" gets
    handed back as though it were a finding about the architecture.

    Observed in the field on a real converter graph: `profile verify` warned that no
    graph matched ``graph/semantic``, exited 0, and `core/models` returned 0 rows
    against a dataset whose models were plainly there.
    """

    #: A profile that does NOT opt into descendant matching, which is what makes the
    #: partitioned fixture unreadable to it. The bundled default opts in, so it reads that
    #: fixture fine - the mismatch has to be constructed to still be testable.
    NO_DESCENDANTS = """\
extends: linked-archi-default.yaml
profile: no-descendants-test
version: 1
description: A profile whose semantic selector cannot match a partitioned graph.
graphs:
  layout: per-model-triple
  named_graphs: true
  descendants: []
"""

    @classmethod
    def setUpClass(cls):
        cls._path = (
            support.ROOT
            / "skills/linked-archi-profile/assets/profiles/_no-descendants-test.yaml"
        )
        cls._path.write_text(cls.NO_DESCENDANTS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._path.unlink(missing_ok=True)

    def setUp(self):
        requires_pyoxigraph(self)
        self.profile = load_profile(str(self._path))
        self.findings = verify_against_dataset(
            self.profile, support.load_fixture(CONVERTER_13)
        )

    def test_semantic_is_required(self):
        self.assertIn("semantic", self.profile.graphs.required)

    def test_the_missing_semantic_graph_is_an_error(self):
        errors = [f for f in self.findings if f.severity == "error"]
        self.assertTrue(
            any(f.subject == "graphs.roles.semantic" for f in errors),
            format_findings(self.findings),
        )

    def test_it_refuses_rather_than_passing(self):
        """The exit code follows, which is what makes this safe to script."""
        self.assertEqual(worst_severity(self.findings), "error")

    def test_the_error_says_the_role_is_partitioned_not_absent(self):
        """Naming the cause, because the two causes need opposite fixes.

        A role that is genuinely absent and a role split across descendant graphs
        look identical to a suffix selector. Reporting only "no graph matching" sends
        a reader looking for missing data that is in fact present and being skipped.
        """
        finding = next(
            f for f in self.findings if f.subject == "graphs.roles.semantic"
        )
        self.assertIn("BELOW it", finding.message)
        self.assertIn("partitioned", finding.message)

    def test_an_optional_missing_role_stays_a_warning(self):
        """``views`` is absent here for a legitimate reason.

        A Backstage conversion emits no views graph at all - the catalog has no
        diagrams - so treating every declared-and-absent graph role as an error would
        refuse a correct dataset and teach the reader to ignore the error.
        """
        finding = next(f for f in self.findings if f.subject == "graphs.roles.views")
        self.assertEqual(finding.severity, "warning", finding.message)
        self.assertNotIn("views", self.profile.graphs.required)

    def test_the_bundled_profile_reads_that_fixture_fine(self):
        """Because it opts into descendant matching. The contrast is the point."""
        findings = verify_against_dataset(
            load_profile("linked-archi-default"), support.load_fixture(CONVERTER_13)
        )
        self.assertEqual([f for f in findings if f.severity == "error"], [],
                         format_findings(findings))

    def test_the_committed_fixtures_are_unaffected(self):
        """The stricter rule must not turn a supported dataset into a refusal."""
        for label, fixture, profile_name in (
            ("base", BASE, "linked-archi-default"),
            ("augmented", AUGMENTED, "curated-store"),
        ):
            with self.subTest(fixture=label):
                findings = verify_against_dataset(
                    load_profile(profile_name), support.load_fixture(fixture)
                )
                self.assertEqual(
                    [f for f in findings if f.severity == "error"], [],
                    format_findings(findings),
                )

    def test_a_flat_dataset_is_not_accused_of_missing_a_semantic_graph(self):
        """The graph-role pass is skipped when the profile expects no graphs.

        ``flattened-turtle`` has ``layout: single``, so requiring a semantic *graph*
        would be incoherent. The finding a flat dataset deserves is the one it already
        gets from a graph-scoping profile: named graphs claimed but absent.
        """
        findings = verify_against_dataset(
            load_profile("flattened-turtle"), support.load_fixture(FLAT)
        )
        self.assertEqual(
            [f for f in findings if f.subject.startswith("graphs.roles.")], [],
            format_findings(findings),
        )


class TestRequiredGraphRoleDeclaration(unittest.TestCase):
    """``graphs.required`` is validated, defaulted, and overridable."""

    MINIMAL_ROLES = {
        role: f"https://example.org/v#{role}" for role in REQUIRED_ROLES
    }

    def _profile(self, graphs: dict) -> Profile:
        return Profile(
            {
                "profile": "t",
                "roles": dict(self.MINIMAL_ROLES),
                "graphs": graphs,
            }
        )

    def test_semantic_is_required_by_default_when_declared(self):
        profile = self._profile(
            {"layout": "per-model-triple", "named_graphs": True,
             "roles": {"semantic": "graph/semantic", "views": "graph/views"}}
        )
        self.assertEqual(profile.graphs.required, ("semantic",))

    def test_nothing_is_required_when_no_semantic_role_is_declared(self):
        """The default cannot demand a role the profile does not bind."""
        profile = self._profile(
            {"layout": "per-model-triple", "named_graphs": True,
             "roles": {"views": "graph/views"}}
        )
        self.assertEqual(profile.graphs.required, ())

    def test_an_empty_list_opts_out(self):
        """Explicit, and honoured. A profile may describe an unusual dataset."""
        profile = self._profile(
            {"layout": "per-model-triple", "named_graphs": True,
             "roles": {"semantic": "graph/semantic"}, "required": []}
        )
        self.assertEqual(profile.graphs.required, ())

    def test_more_roles_can_be_required(self):
        """What a profile for the 1.3 layout needs: require the model graph too."""
        profile = self._profile(
            {"layout": "per-model-triple", "named_graphs": True,
             "roles": {"semantic": "graph/semantic", "model": "graph/model"},
             "required": ["semantic", "model"]}
        )
        self.assertEqual(profile.graphs.required, ("semantic", "model"))

    def test_requiring_an_unbound_role_is_refused(self):
        """It could never be satisfied, so it would refuse every dataset."""
        with self.assertRaises(ProfileError) as caught:
            self._profile(
                {"layout": "per-model-triple", "named_graphs": True,
                 "roles": {"semantic": "graph/semantic"}, "required": ["model"]}
            )
        self.assertIn("model", str(caught.exception))
        self.assertIn("not bound", str(caught.exception))

    def test_requiring_a_null_role_is_refused(self):
        """``validation: null`` says "this dataset has none"; requiring it contradicts that."""
        with self.assertRaises(ProfileError):
            self._profile(
                {"layout": "per-model-triple", "named_graphs": True,
                 "roles": {"semantic": "graph/semantic", "validation": None},
                 "required": ["validation"]}
            )

    def test_a_string_is_not_a_list_of_role_names(self):
        with self.assertRaises(ProfileError):
            self._profile(
                {"layout": "per-model-triple", "named_graphs": True,
                 "roles": {"semantic": "graph/semantic"}, "required": "semantic"}
            )

    def test_required_is_not_mistaken_for_a_graph_role(self):
        """It sits beside ``roles`` in the YAML, where unknown keys fold in as roles.

        Without an explicit exclusion, ``required`` would become a graph role whose
        value is a list of role names, and verification would dutifully probe for a
        graph whose IRI ends with "semantic" on its behalf.
        """
        profile = self._profile(
            {"layout": "per-model-triple", "named_graphs": True,
             "roles": {"semantic": "graph/semantic"}, "required": ["semantic"]}
        )
        self.assertNotIn("required", profile.graphs.roles)
        self.assertNotIn("required", profile.graphs.role_names())

    def test_the_snapshot_carries_it(self):
        """So a consumer of the machine contract sees the same requirement."""
        profile = self._profile(
            {"layout": "per-model-triple", "named_graphs": True,
             "roles": {"semantic": "graph/semantic"}}
        )
        self.assertEqual(
            profile.resolved_snapshot()["graphs"]["required"], ["semantic"]
        )


if __name__ == "__main__":
    unittest.main()


class TestEmitFix(unittest.TestCase):
    """Acting on drift should be one command, not an editing exercise.

    A field session read "claimed false but present" for `direct_rel_triples` and had to
    work out what to do about it in the middle of an investigation - which is exactly when
    nobody wants to be editing YAML.
    """

    def setUp(self):
        requires_pyoxigraph(self)
        from linked_archi_profile.profile import emit_fix_profile, fixable

        self.emit_fix_profile = emit_fix_profile
        self.fixable = fixable
        self.profile = load_profile("linked-archi-default")
        self.findings = verify_against_dataset(
            self.profile, support.load_fixture(AUGMENTED)
        )

    def test_only_capability_drift_is_offered_as_a_fix(self):
        """An unused role is left alone: nulling it would refuse templates that need it."""
        subjects = {finding.subject for finding in self.fixable(self.findings)}
        self.assertTrue(subjects)
        for subject in subjects:
            self.assertTrue(subject.startswith("capabilities."), subject)
        unused_roles = [
            f for f in self.findings
            if f.subject.startswith("roles.") and f.severity == "warning"
        ]
        self.assertTrue(unused_roles, "the fixture does leave roles unused")
        for finding in unused_roles:
            self.assertIsNone(finding.fix, finding.subject)

    def test_the_generated_profile_extends_rather_than_replaces(self):
        generated = self.emit_fix_profile(self.profile, self.findings)
        self.assertIn("extends: linked-archi-default.yaml", generated)
        self.assertIn("profile: linked-archi-default-fitted", generated)
        # Only the corrections, so a later fix to the parent still reaches the child.
        self.assertNotIn("namespaces:", generated)
        self.assertNotIn("roles:", generated)

    def test_the_generated_profile_states_what_was_observed(self):
        generated = self.emit_fix_profile(self.profile, self.findings)
        self.assertIn("direct_rel_triples: true", generated)
        self.assertIn("OBSERVED", generated, "the reader has to know these are measurements")

    def test_the_generated_profile_actually_fits_the_dataset(self):
        """The acceptance criterion, as a measurement rather than a claim.

        Generate, load, re-verify: every capability warning the parent produced is gone,
        and no new error appears.
        """
        import tempfile
        from pathlib import Path

        generated = self.emit_fix_profile(self.profile, self.findings)
        before = {
            f.subject for f in self.findings
            if f.severity in {"error", "warning"} and f.subject.startswith("capabilities.")
        }
        self.assertTrue(before)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fitted.yaml"
            path.write_text(generated, encoding="utf-8")
            fitted = load_profile(path)
            findings = verify_against_dataset(fitted, support.load_fixture(AUGMENTED))
        after = {
            f.subject for f in findings
            if f.severity in {"error", "warning"} and f.subject.startswith("capabilities.")
        }
        self.assertEqual(after, set(), format_findings(findings))
        self.assertEqual(
            [f for f in findings if f.severity == "error"], [], format_findings(findings)
        )

    def test_a_fitting_profile_generates_nothing(self):
        """No fabricated file for a profile that already matches."""
        profile = load_profile("curated-store")
        findings = verify_against_dataset(profile, support.load_fixture(AUGMENTED))
        self.assertIsNone(self.emit_fix_profile(profile, findings))

    def test_a_bundled_parent_is_referenced_relative_to_the_bundled_dir(self):
        """So the generated child is portable AND loadable.

        Previously this asserted a bare basename, on the stated assumption that
        `extends` resolution falls back to the bundled directory by basename. It does
        not fall back into SUBDIRECTORIES, so a child generated from any example
        profile emitted `extends: curated-store.yaml` and could not be loaded at all -
        the one thing --emit-fix exists to hand you. The reference now carries the
        directory, and the round trip below is what actually pins the contract.
        """
        self.assertEqual(
            load_profile("linked-archi-default").source_reference(),
            "linked-archi-default.yaml",
        )
        self.assertEqual(
            load_profile("curated-store").source_reference(),
            "examples/curated-store.yaml",
        )

    def test_a_generated_child_of_a_nested_parent_can_be_loaded(self):
        """The property the reference exists for. A child nobody can load is not a fix."""
        import tempfile
        from pathlib import Path

        parent = load_profile("curated-store")
        with tempfile.TemporaryDirectory() as tmp:
            child = Path(tmp) / "fitted.yaml"
            child.write_text(
                f"extends: {parent.source_reference()}\n"
                "profile: fitted\nversion: 1\n",
                encoding="utf-8",
            )
            loaded = load_profile(child)
        self.assertEqual(loaded.name, "fitted")
        # Inherited from the nested parent, so the chain really was followed.
        self.assertTrue(loaded.capabilities.get("identity_assertions"))

    def test_a_profile_kept_beside_a_graph_is_referenced_absolutely(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "house.yaml"
            path.write_text(
                "extends: linked-archi-default.yaml\nprofile: house\nversion: 1\n",
                encoding="utf-8",
            )
            reference = load_profile(path).source_reference()
        self.assertTrue(reference.startswith("/"), reference)
        self.assertTrue(reference.endswith("house.yaml"), reference)


class TestRecommendation(unittest.TestCase):
    """A named starting profile with evidence, instead of trying candidates.

    The field alternative was running several profiles and reading whichever warned least,
    which rewards the most permissive profile rather than the one that fits.
    """

    def setUp(self):
        requires_pyoxigraph(self)
        from linked_archi_profile.profile import observe_dataset, recommend_profile

        self.observe = observe_dataset
        self.recommend = recommend_profile

    def _for(self, fixture):
        observations = self.observe(support.load_fixture(fixture))
        return observations, self.recommend(observations)

    def test_converter_output_at_default_flags(self):
        _, recommendation = self._for(BASE)
        self.assertEqual(recommendation.profile, "linked-archi-default")

    def test_an_authored_store_is_recognised_by_what_no_converter_emits(self):
        _, recommendation = self._for(AUGMENTED)
        self.assertEqual(recommendation.profile, "examples/curated-store")
        self.assertTrue(
            any("no converter emits" in reason for reason in recommendation.reasons),
            recommendation.reasons,
        )

    def test_a_graphless_dataset_is_recognised_first(self):
        """Without named graphs nothing else changes the answer, so it is checked first."""
        _, recommendation = self._for(FLAT)
        self.assertEqual(recommendation.profile, "examples/flattened-turtle")

    def test_the_evidence_is_reported_not_just_the_verdict(self):
        observations, recommendation = self._for(AUGMENTED)
        subjects = {observation.subject for observation in observations}
        for expected in (
            "named graphs", "graph/semantic", "graph/views", "direct rel triples",
            "identity assertions", "SHACL report", "membership",
        ):
            self.assertIn(expected, subjects)
        self.assertEqual(recommendation.observations, tuple(observations))

    def test_it_recommends_and_never_decides(self):
        _, recommendation = self._for(AUGMENTED)
        joined = " ".join(recommendation.caveats)
        self.assertIn("not a decision", joined)
        self.assertIn("verify", joined)
        self.assertIn("custom", joined, "a custom ontology needs derive, not this")

    def test_a_graphless_dataset_is_told_how_membership_works_there(self):
        """Co-location is a statement about named graphs; the direct edge is not.

        This used to assert that membership could not be expressed at all on flattened
        Turtle. That was true while co-location was the only portable answer. The flat
        fixture now carries `arch:inModel`, so membership IS expressible - and the
        recommendation should say so rather than warn about a limitation that has gone.
        """
        _, recommendation = self._for(FLAT)
        joined = " ".join(recommendation.reasons)
        self.assertIn("membership", joined)
        self.assertIn("arch:inModel", joined)

    def test_observation_survives_the_batched_probe_path(self):
        """The batch is planned once and replayed, so no probe may depend on an answer.

        A branch on an earlier probe's result asks a question in replay that was never
        planned, which raises rather than misreports. This exercises both paths against the
        same fixture and requires the same observations from each.
        """
        from linked_archi_profile.profile import _observe_dataset

        direct = support.load_fixture(FLAT)
        unbatched = _observe_dataset(direct)
        batched = self.observe(support.load_fixture(FLAT))
        self.assertEqual(unbatched, batched)


class TestSnapshotFingerprint(unittest.TestCase):
    """What "which profile is this, exactly" is keyed on.

    A recorded verification is a statement about what a profile *said* when it was
    checked. It used to be keyed on the declared ``version`` - a hand-maintained integer -
    so editing what a profile claims without bumping it left an old marker still vouching
    for the new claims. That was found the hard way: adding a required graph role changed
    which datasets the default profile accepts, and every previously recorded verification
    went on suppressing the caveat.

    The fingerprint cannot be forgotten, because it is derived rather than declared.
    """

    def _snapshot(self, **overrides):
        from linked_archi_profile.profile import REQUIRED_ROLES, Profile

        document = {
            "profile": "t",
            "roles": {r: f"https://example.org/v#{r}" for r in REQUIRED_ROLES},
        }
        document.update(overrides)
        return Profile(document).resolved_snapshot()

    def test_the_snapshot_carries_one(self):
        self.assertTrue(self._snapshot()["fingerprint"])

    def test_it_is_stable_for_the_same_profile(self):
        self.assertEqual(
            self._snapshot()["fingerprint"], self._snapshot()["fingerprint"]
        )

    def test_binding_a_role_differently_changes_it(self):
        from linked_archi_profile.profile import REQUIRED_ROLES

        roles = {r: f"https://example.org/v#{r}" for r in REQUIRED_ROLES}
        moved = dict(roles, label="https://example.org/other#label")
        self.assertNotEqual(
            self._snapshot(roles=roles)["fingerprint"],
            self._snapshot(roles=moved)["fingerprint"],
        )

    def test_requiring_another_graph_role_changes_it(self):
        """The change that exposed the weakness of keying on `version`."""
        graphs = {"layout": "per-model-triple", "named_graphs": True,
                  "roles": {"semantic": "graph/semantic", "model": "graph/model"}}
        self.assertNotEqual(
            self._snapshot(graphs=dict(graphs, required=["semantic"]))["fingerprint"],
            self._snapshot(
                graphs=dict(graphs, required=["semantic", "model"])
            )["fingerprint"],
        )

    def test_flipping_a_capability_changes_it(self):
        self.assertNotEqual(
            self._snapshot(capabilities={"direct_rel_triples": False})["fingerprint"],
            self._snapshot(capabilities={"direct_rel_triples": True})["fingerprint"],
        )

    def test_rewording_the_description_does_not(self):
        """Prose is not meaning. Re-explaining a profile must not invalidate a check."""
        self.assertEqual(
            self._snapshot(description="one way of putting it")["fingerprint"],
            self._snapshot(description="a different way of putting it")["fingerprint"],
        )

    def test_the_declared_version_does_not(self):
        """Deliberate: the fingerprint REPLACES the version rather than including it.

        Folding the version in would let a bump alone invalidate every marker while
        changing nothing about what the profile says, which is the opposite failure.
        """
        self.assertEqual(
            self._snapshot(version=1)["fingerprint"],
            self._snapshot(version=7)["fingerprint"],
        )

    def test_bundled_profiles_have_distinct_fingerprints(self):
        """Two profiles that say different things must not share a marker."""
        seen = {}
        for name in BUNDLED:
            fingerprint = load_profile(name).resolved_snapshot()["fingerprint"]
            self.assertNotIn(
                fingerprint, seen,
                f"{name} and {seen.get(fingerprint)} fingerprint identically",
            )
            seen[fingerprint] = name


class TestDirectRelTriplesProbeIsThreeValued(unittest.TestCase):
    """The probe used to say "present" for any edge between the same two endpoints.

    Reproduced in the field: one unrelated `dct:relation` between two elements that a
    qualified relationship also connects was enough to report `direct_rel_triples` as
    present. That un-refused the templates which read direct edges, and they returned rows
    meaning something else.

    The real question is whether the endpoints are joined by the predicate the
    relationship DECLARES - which it does through the RDF 1.2 bridge, whose triple term
    names the predicate and both endpoints at once. Where nothing declares it, the honest
    answer is "unknown", and a claim is left alone rather than contradicted.

    The declaration used to be ``arch:relPredicate``. Core never published that term and no
    converter emits it any more, so the bridge carries the question instead. It is a better
    witness: the triple term pins the endpoints too, where a bare predicate did not.
    """

    QUALIFIED = """\
@prefix arch: <https://meta.linked.archi/core#> .
@prefix am:   <https://meta.linked.archi/archimate3/onto#> .
@prefix dct:  <http://purl.org/dc/terms/> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<https://example.org/la/p/m/graph/semantic> {
  <https://example.org/la/p/m> a arch:Model .
  <https://example.org/la/p/m/e/a> a arch:Element ; skos:prefLabel "A" .
  <https://example.org/la/p/m/e/b> a arch:Element ; skos:prefLabel "B" .
  <https://example.org/la/p/m/r/1> a arch:QualifiedRelationship, am:Serving ;
      arch:source <https://example.org/la/p/m/e/a> ;
      arch:target <https://example.org/la/p/m/e/b> %s .
%s
}
"""
    #: Declares which predicate the relationship stands for, as the converter does under
    #: --emit-direct-rel-triples. A triple term, so it asserts nothing by itself.
    DECLARES = ("; rdf:reifies <<( <https://example.org/la/p/m/e/a> am:serves "
                "<https://example.org/la/p/m/e/b> )>>")
    #: The genuine unqualified form.
    GENUINE = "  <https://example.org/la/p/m/e/a> am:serves <https://example.org/la/p/m/e/b> ."
    #: An unrelated edge between the same two endpoints. The confounder.
    CONFOUNDER = ("  <https://example.org/la/p/m/e/a> dct:relation "
                  "<https://example.org/la/p/m/e/b> .")

    def setUp(self):
        requires_pyoxigraph(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _observed(self, declares: str, edge: str):
        """The probe's verdict: True, False, or None for unknown."""
        from linked_archi_connect.adapters import open_adapter

        graph = Path(self._tmp.name) / f"case-{abs(hash((declares, edge)))}.trig"
        graph.write_text(self.QUALIFIED % (declares, edge), encoding="utf-8")
        findings = verify_against_dataset(
            load_profile("linked-archi-default"), open_adapter(data=[graph])
        )
        finding = next(
            f for f in findings if f.subject == "capabilities.direct_rel_triples"
        )
        if "Left as claimed" in finding.message:
            return None
        # The default profile claims false, so "present" means the probe said true.
        return "but present" in finding.message

    def test_the_confounder_no_longer_reads_as_present(self):
        """The false positive itself. Unknown, because nothing declares the form."""
        self.assertIsNone(self._observed("", self.CONFOUNDER))

    def test_a_declared_form_that_is_present_reads_as_true(self):
        self.assertIs(self._observed(self.DECLARES, self.GENUINE), True)

    def test_a_declared_form_that_is_absent_reads_as_false(self):
        """The confounder edge is still there; it just is not the declared predicate."""
        self.assertIs(self._observed(self.DECLARES, self.CONFOUNDER), False)

    def test_no_candidate_edge_at_all_reads_as_false_without_any_declaration(self):
        """Absence of any candidate proves absence of a declared one.

        Worth keeping: it is what lets `verify` still catch a profile claiming direct
        triples against a dataset that has none, with no ontology and no declarations.
        """
        self.assertIs(self._observed("", ""), False)

    def test_the_fixtures_land_where_expected(self):
        """The committed fixtures, so the three-way logic is exercised on real data."""
        cases = {
            "base": (BASE, "linked-archi-default", "False, confirmed"),
            "augmented": (AUGMENTED, "curated-store", "True, confirmed"),
        }
        for label, (fixture, profile_name, expected) in cases.items():
            with self.subTest(fixture=label):
                findings = verify_against_dataset(
                    load_profile(profile_name), support.load_fixture(fixture)
                )
                finding = next(
                    f for f in findings
                    if f.subject == "capabilities.direct_rel_triples"
                )
                self.assertIn(expected, finding.message)

    def test_a_claim_of_true_against_a_dataset_with_none_is_still_an_error(self):
        """The signal that must survive the change to a stricter probe."""
        findings = verify_against_dataset(
            load_profile("linked-archi-direct"), support.load_fixture(BASE)
        )
        errors = [f for f in findings
                  if f.severity == "error"
                  and f.subject == "capabilities.direct_rel_triples"]
        self.assertTrue(errors, format_findings(findings))


class TestTheSummaryCountsWhatWasChecked(unittest.TestCase):
    """"4 check(s)" after checking 64 reads as though nothing was verified.

    The default report hides `info` findings, and the summary used to count only the
    visible ones. Observed against a real 1.4M-quad estate: a clean run announced 4 checks
    having actually made 64, which understates the verification to the point of being
    misleading about how much was confirmed.
    """

    def _findings(self):
        from linked_archi_profile.profile import Finding

        return [
            Finding("info", "roles.label", "in use"),
            Finding("info", "roles.definition", "in use"),
            Finding("warning", "roles.owner", "bound but unused"),
        ]

    def test_it_reports_the_total_not_the_shown_count(self):
        findings = self._findings()
        shown = [f for f in findings if f.severity != "info"]
        rendered = format_findings(shown, total=len(findings))
        self.assertIn("3 check(s)", rendered)
        self.assertIn("1 warning(s)", rendered)

    def test_it_says_how_many_were_confirmed_and_hidden(self):
        findings = self._findings()
        shown = [f for f in findings if f.severity != "info"]
        rendered = format_findings(shown, total=len(findings))
        self.assertIn("2 confirmed", rendered)
        self.assertIn("--all", rendered, "the reader needs the way to see them")

    def test_without_a_total_it_still_counts_what_it_was_given(self):
        """Backwards compatible: callers that show everything need no second argument."""
        findings = self._findings()
        rendered = format_findings(findings)
        self.assertIn("3 check(s)", rendered)
        self.assertNotIn("confirmed", rendered)


class TestObserveAndVerifyAgree(unittest.TestCase):
    """`recommend` and `verify` must not describe the same dataset differently.

    They did. The observation asked only whether SOME predicate joins a qualified
    relationship's endpoints, so a real estate carrying no declaration of the unqualified
    form was reported as "converted with --emit-direct-rel-triples" while `verify` correctly
    called the same capability unverifiable. Two commands contradicting each other about one
    graph is worse than either being wrong alone, because it gives a reader no way to decide.
    """

    def setUp(self):
        requires_pyoxigraph(self)

    def _observed_direct(self, fixture):
        from linked_archi_profile.profile import observe_dataset

        for observation in observe_dataset(support.load_fixture(fixture)):
            if observation.subject == "direct rel triples":
                return observation.value
        self.fail("no direct rel triples observation")

    def _verified_direct(self, fixture, profile_name):
        findings = verify_against_dataset(
            load_profile(profile_name), support.load_fixture(fixture)
        )
        finding = next(
            f for f in findings if f.subject == "capabilities.direct_rel_triples"
        )
        if "Left as claimed" in finding.message:
            return "unverifiable"
        return "present" if "but present" in finding.message or "True" in finding.message \
            else "absent"

    def test_they_agree_on_the_augmented_fixture(self):
        """Declarations present, so both should say present."""
        self.assertEqual(self._observed_direct(AUGMENTED), "present")
        self.assertEqual(self._verified_direct(AUGMENTED, "curated-store"), "present")

    def test_they_agree_on_the_base_fixture(self):
        """No candidate edge at all, so both should say absent."""
        self.assertEqual(self._observed_direct(BASE), "absent")
        self.assertEqual(self._verified_direct(BASE, "linked-archi-default"), "absent")

    def test_unverifiable_is_a_value_the_observation_can_report(self):
        """So `recommend` cannot claim a converter flag it has not established."""
        from linked_archi_profile.profile import recommend_profile

        observations = [
            support_observation("named graphs", "4", ""),
            support_observation("direct rel triples", "unverifiable", ""),
        ]
        recommendation = recommend_profile(observations)
        self.assertNotEqual(
            recommendation.profile, "linked-archi-direct",
            "an unverifiable capability must not select the profile that claims it",
        )


def support_observation(subject: str, value: str, implication: str):
    from linked_archi_profile.profile import Observation

    return Observation(subject, value, implication)


class TestRecommendAndVerifyAgree(unittest.TestCase):
    """What `recommend` names, `verify` must accept. The end-to-end invariant.

    This has caught two defects, both of the same kind: a recommendation the very next
    command refuses. First `recommend` named a profile that had been deleted; then it
    chose `examples/curated-store` for a dataset carrying identity assertions but no
    reconciliation graph, no loaded SHACL report and no `arch:conceptOwner` - and that
    profile claims all three, so verification failed on two capabilities.

    The asymmetry is the reason it matters. Over-claiming is an ERROR, because templates
    run and return nothing; under-claiming is only a warning, because they are refused with
    a reason. So a recommendation should err plain, and any capability the dataset has
    beyond the recommended profile belongs in the reasons rather than in the choice.
    """

    def setUp(self):
        requires_pyoxigraph(self)

    def test_every_fixture_verifies_under_its_own_recommendation(self):
        from linked_archi_profile.profile import observe_dataset, recommend_profile

        for fixture in (BASE, AUGMENTED, FLAT, CONVERTER_13):
            with self.subTest(fixture=fixture.name):
                adapter = support.load_fixture(fixture)
                recommended = recommend_profile(observe_dataset(adapter)).profile
                findings = verify_against_dataset(load_profile(recommended), adapter)
                self.assertEqual(
                    [f for f in findings if f.severity == "error"], [],
                    f"recommend named {recommended!r} and verify refuses it:\n"
                    + format_findings(findings),
                )

    def test_identity_without_a_reconciliation_graph_is_advised_not_acted_on(self):
        """The real-estate case, reduced to observations."""
        from linked_archi_profile.profile import Observation, recommend_profile

        recommendation = recommend_profile([
            Observation("named graphs", "384", ""),
            Observation("graph/model", "46", ""),
            Observation("identity assertions", "present", ""),
            Observation("reconciliation graph", "absent", ""),
            Observation("validation graph", "absent", ""),
            Observation("membership", "arch:inModel", ""),
        ])
        self.assertEqual(recommendation.profile, "linked-archi-default")
        joined = " ".join(recommendation.reasons)
        self.assertIn("identity assertions", joined)
        self.assertIn("same_as", joined, "name the role that unlocks it")

    def test_a_reconciliation_graph_alone_gets_the_merged_profile(self):
        """Not the curated one, which would additionally claim a validation graph."""
        from linked_archi_profile.profile import Observation, recommend_profile

        recommendation = recommend_profile([
            Observation("named graphs", "12", ""),
            Observation("graph/model", "5", ""),
            Observation("reconciliation graph", "present", ""),
            Observation("validation graph", "absent", ""),
            Observation("identity assertions", "present", ""),
        ])
        self.assertEqual(recommendation.profile, "linked-archi-merged")
