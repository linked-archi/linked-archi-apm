"""The catalogue, and the contract every template has to satisfy to be in it.

Most of these are consistency checks rather than behaviour tests. They exist because
the catalogue is what routing reads: a template with a missing file cannot run, and a
file with no entry is invisible and untested. Both kinds of drift are silent.
"""

from __future__ import annotations

import unittest

import support

from linked_archi_query import load_catalog, render
from linked_archi_query.catalog import (
    PARAM_TYPES,
    STAGES,
    Catalog,
    CatalogError,
    Requirement,
)
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
        profile = load_profile("curated-store")
        for entry in self.catalog:
            for role in entry.requires.graph_roles:
                with self.subTest(f"{entry.name}:{role}"):
                    self.assertTrue(profile.graphs.has_role(role))

    def test_notation_templates_live_under_their_notation(self):
        for entry in self.catalog:
            if entry.notation:
                with self.subTest(entry.name):
                    self.assertTrue(entry.file.startswith(f"notation/{entry.notation}/"))


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
