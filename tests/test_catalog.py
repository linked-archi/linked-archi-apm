"""The catalogue, and the contract every template has to satisfy to be in it.

Most of these are consistency checks rather than behaviour tests. They exist because
the catalogue is what routing reads: a template with a missing file cannot run, and a
file with no entry is invisible and untested. Both kinds of drift are silent.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import support

from linked_archi_profile import load_profile as load_owner_profile

from linked_archi_query import ResolvedProfile, load_catalog, render
from linked_archi_query.catalog import (
    PARAM_TYPES,
    STAGES,
    Catalog,
    CatalogError,
    Requirement,
)

# The renderer's own placeholder grammar and role normalisation, imported rather than
# restated: a second copy would drift, and a check that disagrees with the renderer
# about what a template uses is worse than no check.
from linked_archi_query.render import _PLACEHOLDER as PLACEHOLDER
from linked_archi_query.render import _base_role as base_role
from linked_archi_query.validate import split_comments
load_profile = support.load_resolved_profile


class TestCatalogParsing(unittest.TestCase):
    def _document(self, **overrides):
        spec = {
            "file": "core/example.rq",
            "stage": "analysis",
            "purpose": "Example query.",
            "parameters": {
                "LIMIT": {
                    "type": "integer",
                    "default": 10,
                    "min": 1,
                    "max": 100,
                    "description": "maximum rows",
                },
            },
            "requires": {"roles": ["label"]},
            "alternatives": [],
        }
        spec.update(overrides)
        return {"version": 1, "templates": {"core/example": spec}}

    def test_malformed_catalog_shapes_raise_catalog_error(self):
        malformed = [
            [],
            {"version": True, "templates": {}},
            {"version": "1", "templates": {}},
            {"version": 1, "templates": []},
            {"version": 1, "templates": {" ": {}}},
            {"version": 1, "templates": {"core/example": []}},
            self._document(purpose=True),
            self._document(parameters=[]),
            self._document(parameters={"LIMIT": []}),
            self._document(parameters={"LIMIT": {"type": "integer", "max": True}}),
            self._document(parameters={
                "PATH": {"type": "iri_path", "default": [True]},
            }),
            self._document(parameters={
                "PATH": {
                    "type": "iri_path",
                    "default": ["https://example.org/p", "not-an-iri"],
                },
            }),
            # choices: only for strings, two or more distinct values, and a default
            # that is one of them. An enum whose default is not a choice would refuse
            # every call that omitted the parameter.
            self._document(parameters={
                "N": {"type": "integer", "choices": ["1", "2"]},
            }),
            self._document(parameters={
                "D": {"type": "string", "choices": ["only-one"]},
            }),
            self._document(parameters={
                "D": {"type": "string", "choices": ["a", "a"]},
            }),
            self._document(parameters={
                "D": {"type": "string", "choices": ["a", "b"], "default": "c"},
            }),
            self._document(parameters={
                "D": {"type": "string", "choices": ["a", ""]},
            }),
            self._document(caveat=True),
            self._document(caveat="  padded  "),
            self._document(requires=[]),
            self._document(requires={"roles": "label"}),
            self._document(requires={"capabilities": {"direct_rel_triples": "yes"}}),
            self._document(requires={"membership": "yes"}),
            self._document(alternatives="core/inventory"),
            self._document(notation=True),
        ]
        for document in malformed:
            with self.subTest(document=document):
                with self.assertRaises(CatalogError):
                    Catalog(document)

    def test_minimal_catalog_shape_is_accepted(self):
        catalog = Catalog(self._document())
        self.assertIn("core/example", catalog)


class TestCatalogueIntegrity(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def test_catalogue_and_disk_agree_both_ways(self):
        self.assertEqual(self.catalog.validate_files(), [])

    def test_every_template_declares_a_known_stage(self):
        for entry in self.catalog:
            with self.subTest(entry.name):
                self.assertIn(entry.stage, STAGES)

    def test_every_template_says_what_it_does_not_prove(self):
        """The line where a reader learns not to over-read the result."""
        for entry in self.catalog:
            with self.subTest(entry.name):
                self.assertTrue(entry.purpose.strip())
                self.assertTrue(
                    entry.does_not_prove.strip(),
                    f"{entry.name} must declare does_not_prove",
                )

    def test_every_parameter_is_typed_and_described(self):
        for entry in self.catalog:
            for name, spec in entry.parameters.items():
                with self.subTest(f"{entry.name}:{name}"):
                    self.assertIn(spec["type"], PARAM_TYPES)
                    self.assertTrue(spec.get("description", "").strip())

    def test_every_limit_is_bounded(self):
        for entry in self.catalog:
            if "LIMIT" not in entry.parameters:
                continue
            with self.subTest(entry.name):
                spec = entry.parameters["LIMIT"]
                self.assertIn("max", spec, f"{entry.name} LIMIT needs a ceiling")

    def test_every_template_takes_a_limit(self):
        for entry in self.catalog:
            with self.subTest(entry.name):
                self.assertIn("LIMIT", entry.parameters,
                              f"{entry.name} must be bounded")

    def test_alternatives_name_real_templates(self):
        for entry in self.catalog:
            for alternative in entry.alternatives:
                with self.subTest(f"{entry.name} -> {alternative}"):
                    self.assertIn(alternative, self.catalog)

    def test_gated_templates_offer_an_alternative(self):
        """A refusal that offers nowhere to go is only half an answer."""
        for entry in self.catalog:
            if not entry.requires.capabilities:
                continue
            with self.subTest(entry.name):
                self.assertTrue(
                    entry.alternatives,
                    f"{entry.name} is capability-gated and must name an alternative",
                )

    def test_declared_roles_exist_in_the_default_profile(self):
        """A requires block naming a role no profile knows is a typo, not a gate."""
        profile = load_profile("linked-archi-default")
        for entry in self.catalog:
            for role in entry.requires.roles:
                with self.subTest(f"{entry.name}:{role}"):
                    self.assertIn(role, profile.roles)

    def test_declared_graph_roles_exist(self):
        """Some bundled profile must bind every graph role a template asks for.

        Checked across the bundled set rather than against one profile: a role can be
        legitimately absent from converter output and still be real - `vocabulary` is
        attached beside the data, `reconciliation` and `validation` are authored by a
        publishing pipeline - so requiring one profile to bind them all would either
        force a false claim into that profile or block the template from existing. What
        must not happen is a `requires` block naming a role nothing knows, which is a typo.
        """
        profiles = [
            load_profile(name) for name in
            ("linked-archi-default", "curated-store", "with-vocabulary")
        ]
        for entry in self.catalog:
            for role in entry.requires.graph_roles:
                with self.subTest(f"{entry.name}:{role}"):
                    self.assertTrue(
                        any(profile.graphs.has_role(role) for profile in profiles),
                        f"no bundled profile binds the graph role {role!r}",
                    )

    def test_every_role_a_template_renders_is_declared(self):
        """The mirror of the test above, and the direction that actually bites.

        That one catches a `requires` block naming a role nobody binds - a typo. This
        catches the opposite and more expensive drift: a template *using* a role it
        never declared. `expand_role` raises on a role bound to null, so an undeclared
        role is not a soft omission - it is a hard render failure the moment a profile
        legitimately says "this dataset does not represent that". Declaring it turns a
        crash into the refusal-with-an-alternative the gate exists to give, and it is
        why `OPTIONAL { ?x {{ROLE:definition}} ?d }` still has to declare `definition`.

        Read from the rendered body with comments stripped, because a template header
        names its own placeholders as documentation.
        """
        for entry in self.catalog:
            code = "".join(
                "" if is_comment else chunk
                for is_comment, chunk in split_comments(entry.path.read_text())
            )
            declared = set(entry.requires.roles)
            used = {
                match.group(2)
                for match in PLACEHOLDER.finditer(code)
                if match.group(1) in {"ROLE", "ROLES", "PATH"}
            }
            with self.subTest(entry.name):
                self.assertEqual(
                    sorted(used - declared), [],
                    f"{entry.name} renders these roles without declaring them under "
                    "requires.roles",
                )

    def test_every_graph_role_a_template_scopes_to_is_declared(self):
        """Same drift, one level up: an undeclared scope is an unrefusable query.

        A scope naming a graph role the profile has no binding for raises at render
        time; declared, it is refused with the roles the dataset does have. The `any`
        role is exempt because it deliberately constrains nothing - the orientation
        templates use it to report which graphs exist - and a trailing digit is an
        independent scope on the same role, so `semantic2` declares `semantic`.
        """
        for entry in self.catalog:
            code = "".join(
                "" if is_comment else chunk
                for is_comment, chunk in split_comments(entry.path.read_text())
            )
            declared = set(entry.requires.graph_roles)
            used = {
                base_role(match.group(2))
                for match in PLACEHOLDER.finditer(code)
                if match.group(1) in {"GRAPH_OPEN", "GRAPH_VAR"}
            } - {"any"}
            with self.subTest(entry.name):
                self.assertEqual(
                    sorted(used - declared), [],
                    f"{entry.name} scopes to these graph roles without declaring them "
                    "under requires.graph_roles",
                )

    def test_membership_is_declared_by_every_template_that_walks_it(self):
        """`requires.membership` is what refuses a profile that cannot express it.

        Undeclared, the directive still renders - and under co-location without named
        graphs it degenerates into a join against every model in the dataset, which
        answers wrongly instead of refusing.
        """
        for entry in self.catalog:
            code = "".join(
                "" if is_comment else chunk
                for is_comment, chunk in split_comments(entry.path.read_text())
            )
            walks = any(
                match.group(1) == "MEMBERSHIP" for match in PLACEHOLDER.finditer(code)
            )
            with self.subTest(entry.name):
                self.assertEqual(
                    walks, entry.requires.membership,
                    f"{entry.name} uses {{{{MEMBERSHIP}}}}={walks} but declares "
                    f"requires.membership={entry.requires.membership}",
                )

    def test_notation_templates_live_under_their_notation(self):
        for entry in self.catalog:
            if entry.notation:
                with self.subTest(entry.name):
                    self.assertTrue(entry.file.startswith(f"notation/{entry.notation}/"))

    def test_every_notation_template_names_the_vocabulary_it_uses(self):
        """Without this the `notation` label is decoration, which is what it was.

        A notation template names that notation's terms directly - there is no role
        indirection for `bpmn:SequenceFlow` - so against a dataset without the notation it
        returns nothing rather than being refused. The namespace IRI is what makes that
        gateable, so a new notation template must not be able to skip it.
        """
        for entry in self.catalog:
            if entry.notation:
                with self.subTest(entry.name):
                    self.assertTrue(
                        entry.notation_namespace,
                        f"{entry.name} declares notation {entry.notation!r} but no "
                        "notation_namespace, so nothing can gate it",
                    )
                    self.assertTrue(entry.notation_namespace.startswith("https://"))


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def test_full_name(self):
        self.assertEqual(self.catalog.get("core/inventory").name, "core/inventory")

    def test_suffix_and_bare_name_tolerated(self):
        self.assertEqual(self.catalog.get("core/inventory.rq").name, "core/inventory")
        self.assertEqual(self.catalog.get("inventory").name, "core/inventory")

    def test_unknown_name_suggests_the_listing(self):
        with self.assertRaises(CatalogError) as caught:
            self.catalog.get("nonsense")
        self.assertIn("catalog list", str(caught.exception))

    def test_by_stage_is_sorted(self):
        names = [e.name for e in self.catalog.by_stage("orientation")]
        self.assertEqual(names, sorted(names))
        self.assertIn("core/inventory", names)


class TestGating(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()

    def test_default_profile_refuses_exactly_the_unsupported_templates(self):
        """Pinned deliberately. Adding a template here is a decision, not a detail.

        Every name below is refused because converter output verifiably lacks what it
        needs - not out of caution. A template appearing or disappearing from this set
        changes what the package claims real datasets can answer.
        """
        profile = load_profile("linked-archi-default")
        refused = {entry.name for entry, _ in self.catalog.refused(profile)}
        self.assertEqual(
            refused,
            {
                # --emit-direct-rel-triples is off by default: zero direct triples.
                "core/dependents-direct",
                # Identity is authored; owl:sameAs and skos:exactMatch are both zero.
                "core/identity-audit",
                # No converter writes a SHACL report into the dataset.
                "core/validation-summary",
                # The RDF 1.2 bridge is specified in the core ontology and emitted by
                # nothing. Also requires a SPARQL 1.2 engine.
                "core/neighbours-reified",
                "core/reified-predicates",
                "core/reifies-audit",
                # A conversion emits instances, not the ontologies and taxonomies they
                # conform to, so there is no class hierarchy and no class-to-category
                # link to read. Attaching published vocabulary beside the data is what
                # lifts this - examples/with-vocabulary - and until then the answer comes
                # from notation/bpmn/process-components and its hand-maintained list.
                "core/elements-by-category",
            },
        )

    def test_curated_profile_supports_everything(self):
        profile = load_profile("curated-store")
        self.assertEqual(self.catalog.refused(profile), [])
        self.assertEqual(len(self.catalog.available(profile)), len(self.catalog))

    def test_missing_graph_role_is_a_warning_when_there_are_no_graphs(self):
        """Flattened data may still hold the facts; it just cannot separate them."""
        flat = load_profile("flattened-turtle")
        entry = self.catalog.get("core/neighbours-qualified")
        verdict = entry.check(flat)
        self.assertTrue(verdict.ok)
        self.assertTrue(verdict.warnings)

    def test_partial_capability_is_a_warning_not_a_refusal(self):
        profile = load_profile("linked-archi-default")
        verdict = self.catalog.get("core/view-usage").check(profile)
        self.assertTrue(verdict.ok)
        self.assertTrue(any("partial" in w for w in verdict.warnings))

    def test_unmet_requirement_explains_itself(self):
        profile = load_profile("linked-archi-default")
        verdict = self.catalog.get("core/dependents-direct").check(profile)
        self.assertFalse(verdict.ok)
        self.assertTrue(any("direct_rel_triples" in reason for reason in verdict.unmet))

    def test_requirement_rejects_unknown_keys(self):
        with self.assertRaises(CatalogError):
            Requirement.from_json({"rolez": ["label"]})

    def test_a_notation_the_profile_does_not_declare_is_refused(self):
        """A C4-only store must not be offered the BPMN templates.

        They would run and return nothing, and nothing distinguishes that from "this
        model has no sequence flows". The profile is narrowed by dropping notations from
        a resolved snapshot rather than by authoring a profile file, because notation maps
        merge key by key on inheritance and cannot be narrowed by an override.
        """
        snapshot = load_owner_profile("linked-archi-default").resolved_snapshot()
        snapshot["notations"] = {
            slug: spec for slug, spec in snapshot["notations"].items() if slug == "c4"
        }
        c4_only = ResolvedProfile(snapshot)

        refused = {entry.name for entry, _ in self.catalog.refused(c4_only)}
        self.assertIn("notation/bpmn/process-flow", refused)
        self.assertIn("notation/leanix/factsheets", refused)
        self.assertNotIn("notation/c4/containers", refused)

        verdict = self.catalog.get("notation/bpmn/process-flow").check(c4_only)
        self.assertTrue(
            any("bpmn/onto#" in reason for reason in verdict.unmet),
            f"the refusal must name the vocabulary: {verdict.unmet}",
        )

    def _with_presence(self, slug: str, present):
        """The default profile with one notation's dataset presence recorded.

        Edited through a resolved snapshot for the same reason the test above does it:
        notation maps merge key by key on inheritance, so a child profile cannot narrow
        what its parent declares.
        """
        snapshot = load_owner_profile("linked-archi-default").resolved_snapshot()
        snapshot["notations"] = {
            name: (dict(spec) | {"present": present} if name == slug else spec)
            for name, spec in snapshot["notations"].items()
        }
        return ResolvedProfile(snapshot)

    def test_a_notation_recorded_absent_from_the_dataset_is_refused(self):
        """Declaring a notation and holding a model in it are different facts.

        The profile still speaks BPMN - the vocabulary is bound, the templates render -
        but this dataset has none of it, so every BPMN template joins nothing. Answering
        that with an empty table says "this model has no gateways". Refusing says "ask a
        dataset that has a process in it", which is the only true statement available.
        """
        profile = self._with_presence("bpmn", False)
        refused = {entry.name for entry, _ in self.catalog.refused(profile)}
        self.assertIn("notation/bpmn/process-flow", refused)
        self.assertNotIn("notation/c4/containers", refused)

        verdict = self.catalog.get("notation/bpmn/process-flow").check(profile)
        reasons = " ".join(verdict.unmet)
        self.assertIn("absent", reasons)
        self.assertIn(
            "core/inventory-summary", reasons,
            "the refusal has to name how to check, not just that it refused",
        )
        self.assertIn(
            "notations.bpmn.present", reasons,
            "and it has to name the edit that lifts the refusal",
        )

    def test_a_notation_present_for_some_models_runs_with_a_caveat(self):
        """`partial` is not a refusal. Rows exist; they just do not cover the notation."""
        profile = self._with_presence("bpmn", "partial")
        verdict = self.catalog.get("notation/bpmn/process-flow").check(profile)
        self.assertTrue(verdict.ok, verdict.unmet)
        self.assertTrue(
            any("some models" in warning for warning in verdict.warnings),
            f"a partial notation must warn: {verdict.warnings}",
        )

    def test_recording_a_notation_present_changes_nothing(self):
        """The claim only ever removes an answer, never adds one.

        Worth pinning because the opposite would be a way to talk a template into running
        against a dataset that cannot support it.
        """
        stated = self._with_presence("bpmn", True)
        unstated = ResolvedProfile(
            load_owner_profile("linked-archi-default").resolved_snapshot()
        )
        self.assertEqual(
            {entry.name for entry, _ in self.catalog.refused(stated)},
            {entry.name for entry, _ in self.catalog.refused(unstated)},
        )

    def test_an_unstated_presence_refuses_nothing(self):
        """Unknown is not absent.

        Every profile that predates this key leaves presence unstated, and none of them
        may start refusing templates because of it. This is the whole reason the gate is
        opt-in rather than measured at render time.
        """
        profile = ResolvedProfile(
            load_owner_profile("linked-archi-default").resolved_snapshot()
        )
        for slug in profile.notations:
            self.assertIsNone(profile.notation_present(slug))
        refused = {entry.name for entry, _ in self.catalog.refused(profile)}
        self.assertNotIn("notation/bpmn/process-flow", refused)

    def test_a_presence_value_that_is_not_a_tristate_is_rejected(self):
        """A typo must not read as absent and refuse a notation silently."""
        from linked_archi_query.contract import ContractError

        snapshot = load_owner_profile("linked-archi-default").resolved_snapshot()
        snapshot["notations"]["bpmn"] = dict(snapshot["notations"]["bpmn"]) | {
            "present": "yes"
        }
        with self.assertRaises(ContractError) as caught:
            ResolvedProfile(snapshot)
        self.assertIn("present", str(caught.exception))

    def test_the_bundled_profiles_refuse_no_notation_template(self):
        """The trap this gate had to avoid: a slug is not a notation's identity.

        ArchiMate's profile slug is `model`, because the converter's --path-model defaults
        to that, while the catalogue directory is `archimate`. Gating on the label would
        have refused a supported template against every bundled profile. Matching is on
        the namespace IRI for that reason, and this is what keeps it honest.
        """
        for name in ("linked-archi-default", "curated-store", "flattened-turtle"):
            profile = load_profile(name)
            for entry in self.catalog:
                if not entry.notation_namespace:
                    continue
                with self.subTest(f"{name}:{entry.name}"):
                    self.assertIsNotNone(
                        profile.notation_for_namespace(entry.notation_namespace),
                        f"{name} does not match {entry.notation_namespace}",
                    )

    def test_a_role_the_dataset_lacks_refuses_instead_of_crashing(self):
        """What declaring a rendered role actually buys, as behaviour.

        `expand_role` raises on a role bound to null, so while `core/views` used
        `conforms_to_viewpoint` without declaring it, a legitimate profile statement -
        "the views in this dataset declare no viewpoint conformance" - produced
        `RenderError: binds role 'conforms_to_viewpoint' to null` from inside
        rendering. Nothing about that tells a caller which template to reach for
        instead. Declared, the same profile gets a refusal that names the role.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "no-viewpoints.yaml"
            path.write_text(
                "extends: linked-archi-default.yaml\n"
                "profile: no-viewpoints\n"
                "version: 1\n"
                "description: A dataset whose views declare no viewpoint conformance.\n"
                "roles:\n"
                "  conforms_to_viewpoint: null\n"
            )
            profile = load_profile(str(path))
            verdict = self.catalog.get("core/views").check(profile)

        self.assertFalse(verdict.ok)
        self.assertTrue(
            any("conforms_to_viewpoint" in reason for reason in verdict.unmet),
            f"the refusal must name the missing role, got: {verdict.unmet}",
        )

    def test_listing_marks_refusals(self):
        profile = load_profile("linked-archi-default")
        listing = self.catalog.format_list(profile)
        self.assertIn("x core/dependents-direct", listing)
        self.assertIn("32 available", listing)


if __name__ == "__main__":
    unittest.main()


class TestCatalogDump(unittest.TestCase):
    """All template metadata in one call.

    `catalog show` per template is one process per template for what is static data, and
    that adds up during template selection. `dump` is the same information at once.
    """

    def _dump(self, *args: str) -> dict:
        import json
        import subprocess
        import sys

        done = subprocess.run(
            [
                sys.executable,
                str(support.ROOT / "skills" / "linked-archi-query" / "scripts" / "la-query"),
                "catalog",
                "dump",
                *args,
            ],
            capture_output=True,
            text=True,
            cwd=support.ROOT,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_it_carries_every_template_with_its_contract(self):
        payload = self._dump()
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(set(payload["templates"]), set(load_catalog().names))
        entry = payload["templates"]["core/traceability"]
        for key in ("stage", "purpose", "answers", "does_not_prove", "parameters", "requires"):
            self.assertIn(key, entry)

    def test_a_profile_adds_availability_and_the_reason_for_a_refusal(self):
        payload = self._dump("--profile", "linked-archi-default")
        self.assertEqual(payload["profile"]["id"], "linked-archi-default")
        refused = payload["templates"]["core/dependents-direct"]
        self.assertFalse(refused["available"])
        self.assertTrue(refused["unmet"], "a refusal must carry its reason")
        available = payload["templates"]["core/neighbours-qualified"]
        self.assertTrue(available["available"])

    def test_without_a_profile_it_makes_no_availability_claim(self):
        payload = self._dump()
        self.assertNotIn("profile", payload)
        self.assertNotIn("available", payload["templates"]["core/traceability"])

    def test_a_partial_capability_is_reported_as_a_caveat_not_a_refusal(self):
        payload = self._dump("--profile", "linked-archi-default")
        views = payload["templates"]["core/view-contents"]
        self.assertTrue(views["available"])
        self.assertTrue(views["profile_caveats"])
