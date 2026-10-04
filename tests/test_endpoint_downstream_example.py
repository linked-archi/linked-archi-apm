"""The endpoint downstream package works without a packaged graph or live server."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import yaml

import support
from tests.validate_skills import check_skill

from linked_archi_profile import profile as profile_owner
from linked_archi_query import ResolvedProfile, render
from linked_archi_query import cli as query_cli


EXAMPLE = support.ROOT / "examples" / "sparql-endpoint-downstream"
DEMO_SKILL = EXAMPLE / "skills" / "sparql-endpoint-demo"
PROFILE = DEMO_SKILL / "assets" / "profiles" / "endpoint.yaml"
ENDPOINT = "https://architecture.invalid/sparql"


class TestEndpointDownstreamExample(unittest.TestCase):
    def test_packaged_skill_passes_the_same_frontmatter_checks_as_upstream(self):
        problems, warnings, _ = check_skill(DEMO_SKILL / "SKILL.md")
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])

    def test_manifest_pins_only_the_needed_companions(self):
        manifest = yaml.safe_load((EXAMPLE / "apm.yml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["includes"], ["skills/sparql-endpoint-demo/"])
        dependencies = manifest["dependencies"]["apm"]
        self.assertEqual(len(dependencies), 1)
        self.assertEqual(dependencies[0]["git"], "linked-archi/linked-archi-apm")
        self.assertEqual(dependencies[0]["ref"], "v0.8.0")
        self.assertEqual(set(dependencies[0]["skills"]), {
            "linked-archi-analyse",
            "linked-archi-query",
            "linked-archi-profile",
            "linked-archi-connect",
        })
        self.assertTrue((DEMO_SKILL / "SKILL.md").is_file())
        self.assertTrue((EXAMPLE / "AGENTS.md").is_file())
        self.assertFalse((DEMO_SKILL / "assets" / "data").exists())
        self.assertFalse((DEMO_SKILL / "assets" / "queries").exists())
        self.assertEqual(list(EXAMPLE.rglob("*.trig")), [])
        self.assertEqual(list(EXAMPLE.rglob("catalog.json")), [])

    def test_profile_loads_from_an_installed_skill_and_renders_a_bundled_query(self):
        with tempfile.TemporaryDirectory() as temporary:
            skills = Path(temporary) / ".agents" / "skills"
            installed_demo = skills / "sparql-endpoint-demo"
            installed_base_profiles = skills / "linked-archi-profile" / "assets" / "profiles"
            shutil.copytree(DEMO_SKILL, installed_demo)
            shutil.copytree(
                support.ROOT / "skills" / "linked-archi-profile" / "assets" / "profiles",
                installed_base_profiles,
            )
            installed_profile = installed_demo / "assets" / "profiles" / "endpoint.yaml"
            with mock.patch.object(profile_owner, "PROFILE_DIR", installed_base_profiles):
                profile = profile_owner.load_profile(installed_profile)

        self.assertEqual(profile.name, "sparql-endpoint-demo")
        resolved = ResolvedProfile(profile.resolved_snapshot())
        rendered = render("core/inventory-summary", resolved)
        self.assertIn("SELECT", rendered.query)
        query_body = "\n".join(
            line for line in rendered.query.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn("{{", query_body)

    def test_installed_skill_names_sibling_owner_commands_and_explicit_endpoint(self):
        instructions = (DEMO_SKILL / "SKILL.md").read_text(encoding="utf-8")
        for owner, command in (
            ("linked-archi-connect", "la-connect"),
            ("linked-archi-profile", "la-profile"),
            ("linked-archi-query", "la-query"),
        ):
            self.assertIn(f"$SKILL/../{owner}/scripts/{command}", instructions)
            self.assertTrue((support.ROOT / "skills" / owner / "scripts" / command).is_file())
        self.assertIn("$SKILL/assets/profiles/endpoint.yaml", instructions)
        self.assertIn('--endpoint "$ARCHITECTURE_SPARQL_ENDPOINT"', instructions)
        self.assertNotIn("--data", instructions.split("```bash", 1)[1].split("```", 1)[0])

    def test_query_cli_routes_the_explicit_endpoint_without_network_access(self):
        resolved = ResolvedProfile(profile_owner.load_profile(PROFILE).resolved_snapshot())
        raw = {"form": "SELECT", "rows": [], "dataset_id": ENDPOINT, "elapsed_ms": 0}
        with (
            mock.patch.object(query_cli, "_profile", return_value=resolved),
            mock.patch.object(query_cli, "_execute", return_value=raw) as execute,
            mock.patch.object(query_cli.verification, "is_verified", return_value=True),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = query_cli.main([
                "query", "run", "core/inventory-summary",
                "--profile", str(PROFILE), "--endpoint", ENDPOINT,
            ])
        self.assertEqual(status, query_cli.OK)
        query, target = execute.call_args.args
        self.assertIn("SELECT", query)
        self.assertEqual(target["endpoint"], ENDPOINT)
        self.assertEqual(target["data"], [])


if __name__ == "__main__":
    unittest.main()
