"""The fixed-graph downstream package installs its own evidence-bearing skill."""

from __future__ import annotations

import unittest

import yaml

import support

from linked_archi_profile.profile import load_profile, verify_against_dataset
from linked_archi_query import load_catalog, render


EXAMPLE = support.ROOT / "examples" / "fixed-graph-downstream"
DEMO_SKILL = EXAMPLE / "skills" / "fixed-graph-demo"
GRAPH = DEMO_SKILL / "assets" / "data" / "architecture.trig"
PROFILE = DEMO_SKILL / "assets" / "profiles" / "demo.yaml"
CATALOG = DEMO_SKILL / "assets" / "queries" / "catalog.json"
SERVICE = "https://example.org/fixed-graph/catalog/element/payments-service"
TEAM = "https://example.org/fixed-graph/catalog/element/payments-team"


class TestDownstreamExample(unittest.TestCase):
    def test_manifest_selects_only_the_required_companion_skills(self):
        manifest = yaml.safe_load((EXAMPLE / "apm.yml").read_text(encoding="utf-8"))
        dependencies = manifest["dependencies"]["apm"]
        self.assertEqual(len(dependencies), 1)
        self.assertEqual(dependencies[0]["git"], "linked-archi/linked-archi-apm")
        self.assertTrue(dependencies[0]["ref"])
        self.assertEqual(set(dependencies[0]["skills"]), {
            "linked-archi-analyse",
            "linked-archi-query",
            "linked-archi-profile",
            "linked-archi-connect",
        })
        self.assertEqual(manifest["includes"], ["skills/fixed-graph-demo/"])
        self.assertTrue((DEMO_SKILL / "SKILL.md").is_file())
        self.assertTrue((EXAMPLE / "AGENTS.md").is_file())

    def test_custom_profile_matches_the_fixed_graph_and_core_lookup(self):
        support.requires_pyoxigraph(self)
        profile = load_profile(PROFILE)
        adapter = support.load_fixture(GRAPH)
        findings = verify_against_dataset(profile, adapter)
        self.assertEqual(
            [finding for finding in findings if finding.severity == "error"], []
        )
        resolved = support.load_resolved_profile(str(PROFILE))
        rendered = render("core/resolve-element", resolved, {"TERM": "Payments Service"})
        envelope = adapter.execute(rendered.query, limit=100)
        self.assertEqual(envelope.row_count, 1)
        self.assertEqual(envelope.rows[0]["element"], SERVICE)

    def test_project_catalogue_runs_without_changing_the_builtin_catalogue(self):
        support.requires_pyoxigraph(self)
        catalog = load_catalog(extensions=[CATALOG])
        self.assertEqual(catalog.validate_files(), [])
        self.assertIn("demo/accountability", catalog)
        self.assertIn("core/resolve-element", catalog)
        profile = support.load_resolved_profile(str(PROFILE))
        rendered = render(
            "demo/accountability", profile, {"FOCUS_IRI": SERVICE}, catalog=catalog,
        )
        envelope = support.load_fixture(GRAPH).execute(rendered.query, limit=100)
        self.assertEqual(envelope.row_count, 1)
        self.assertEqual(envelope.rows[0]["component"], SERVICE)
        self.assertEqual(envelope.rows[0]["team"], TEAM)
        self.assertFalse(
            catalog.get("demo/accountability").check(
                support.load_resolved_profile("linked-archi-default")
            ).ok
        )


if __name__ == "__main__":
    unittest.main()
