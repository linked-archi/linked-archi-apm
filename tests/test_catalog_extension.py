"""Explicit project catalogues extend, but never replace, the bundled query contract."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import support

from linked_archi_query import load_catalog, render
from linked_archi_query import cli
from linked_archi_query.catalog import CatalogError, TEMPLATE_DIR


TEMPLATE = """{{PREFIXES}}
SELECT ?subject WHERE {
  {{GRAPH_OPEN:semantic}}
    ?subject {{ROLE:label}} ?label .
  {{GRAPH_CLOSE}}
}
LIMIT {{LIMIT}}
"""
UNSAFE_TEMPLATE = """{{PREFIXES}}
SELECT ?subject WHERE {
  SERVICE <https://example.org/sparql> { ?subject ?predicate ?object }
}
LIMIT {{LIMIT}}
"""


class TestProjectCatalogues(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.catalog_path = self.project / "catalog.json"
        self.template_path = self.project / "queries" / "labels.rq"
        self.template_path.parent.mkdir()
        self.template_path.write_text(TEMPLATE, encoding="utf-8")
        self.write_catalog()

    def write_catalog(self, *, name="acme/labels", file="queries/labels.rq", **spec):
        entry = {
            "file": file,
            "stage": "analysis",
            "purpose": "List labelled architecture records.",
            "answers": "Which records have labels in the selected graph.",
            "does_not_prove": "That all records have labels.",
            "parameters": {
                "LIMIT": {
                    "type": "integer", "default": 10, "min": 1, "max": 20,
                    "description": "maximum rows",
                },
            },
            "requires": {"roles": ["label"], "graph_roles": ["semantic"]},
            "alternatives": ["core/inventory"],
        }
        entry.update(spec)
        self.catalog_path.write_text(
            json.dumps({"version": 1, "templates": {name: entry}}), encoding="utf-8"
        )

    def command(self, *arguments):
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = cli.main(list(arguments))
        return result, output.getvalue(), error.getvalue()

    def test_overlay_keeps_bundled_templates_and_uses_project_relative_files(self):
        catalog = load_catalog(extensions=[self.catalog_path])
        self.assertEqual(catalog.get("acme/labels").path, self.template_path.resolve())
        self.assertEqual(catalog.get("core/inventory").path, (TEMPLATE_DIR / "core/inventory.rq").resolve())
        self.assertEqual(catalog.validate_files(), [])
        profile = support.load_resolved_profile("linked-archi-default")
        rendered = render("acme/labels", profile, catalog=catalog)
        self.assertIn("SELECT ?subject", rendered.query)
        self.assertNotIn("{{", rendered.query)

    def test_catalogue_commands_and_render_share_the_explicit_overlay(self):
        path = str(self.catalog_path)
        for arguments, expected in (
            (("catalog", "list", "--catalog", path), "acme/labels"),
            (("catalog", "show", "acme/labels", "--catalog", path, "--source"), TEMPLATE),
            (("catalog", "dump", "--catalog", path, "--template", "acme/labels"),
             '"acme/labels"'),
            (("query", "render", "acme/labels", "--catalog", path), "SELECT ?subject"),
        ):
            with self.subTest(arguments=arguments):
                result, output, error = self.command(*arguments)
                self.assertEqual(result, cli.OK, error)
                self.assertIn(expected, output)
        result, _, error = self.command("catalog", "show", "acme/labels")
        self.assertEqual(result, cli.ERROR)
        self.assertIn("No template", error)

    def test_multiple_overlays_are_explicit_and_duplicate_names_are_refused(self):
        second = self.root / "other"
        second.mkdir()
        (second / "other.rq").write_text(TEMPLATE, encoding="utf-8")
        second_path = second / "catalog.json"
        entry = json.loads(self.catalog_path.read_text(encoding="utf-8"))["templates"]["acme/labels"]
        entry["file"] = "other.rq"
        second_path.write_text(json.dumps({"version": 1, "templates": {
            "other/labels": entry,
        }}), encoding="utf-8")
        catalog = load_catalog(extensions=[self.catalog_path, second_path])
        self.assertIn("acme/labels", catalog)
        self.assertIn("other/labels", catalog)
        second_path.write_text(self.catalog_path.read_text(encoding="utf-8"), encoding="utf-8")
        (second / "queries").mkdir()
        (second / "queries" / "labels.rq").write_text(TEMPLATE, encoding="utf-8")
        with self.assertRaisesRegex(CatalogError, "duplicates an existing template"):
            load_catalog(extensions=[self.catalog_path, second_path])

    def test_project_names_must_not_impersonate_bundled_namespaces(self):
        for name in ("core/inventory", "notation/bpmn/custom", "custom/labels", "labels"):
            with self.subTest(name=name):
                self.write_catalog(name=name)
                with self.assertRaisesRegex(CatalogError, "project namespace"):
                    load_catalog(extensions=[self.catalog_path])

    def test_missing_or_escaping_template_files_are_refused(self):
        outside = self.root / "outside.rq"
        outside.write_text(TEMPLATE, encoding="utf-8")
        for file in ("../outside.rq", "/tmp/outside.rq", "queries/../../outside.rq",
                     "queries\\labels.rq", "queries/missing.rq"):
            with self.subTest(file=file):
                self.write_catalog(file=file)
                with self.assertRaises(CatalogError):
                    load_catalog(extensions=[self.catalog_path])
        link = self.project / "escape.rq"
        link.symlink_to(outside)
        self.write_catalog(file="escape.rq")
        with self.assertRaisesRegex(CatalogError, "escapes its catalogue directory"):
            load_catalog(extensions=[self.catalog_path])

    def test_external_contract_rejects_undeclared_dependencies_and_unbounded_queries(self):
        for spec, source, expected in (
            ({"requires": {"graph_roles": ["semantic"]}}, TEMPLATE, "requires.roles"),
            ({"requires": {"roles": ["label"]}}, TEMPLATE, "requires.graph_roles"),
            ({}, TEMPLATE.replace("LIMIT {{LIMIT}}", ""), "must end with LIMIT"),
            ({}, TEMPLATE.replace("{{ROLE:label}}", "{{ROLE}}"), "missing argument"),
            ({}, TEMPLATE.replace("{{GRAPH_OPEN:semantic}}", "{{GRAPH_OPEN}}"),
             "missing argument"),
            ({}, TEMPLATE.replace("LIMIT {{LIMIT}}", "LIMIT {{LIMIT}} }"),
             "must end with LIMIT"),
            ({"parameters": {}}, TEMPLATE, "bounded integer LIMIT"),
            ({"parameters": {"LIMIT": {"type": "integer", "default": 10,
                                      "min": 0, "max": 20}}}, TEMPLATE,
             "bounded integer LIMIT"),
            ({"parameters": {"LIMIT": {"type": "integer", "default": -1,
                                      "min": 1, "max": 20}}}, TEMPLATE,
             "bounded integer LIMIT"),
            ({"parameters": {"LIMIT": {"type": "integer", "default": 21,
                                      "min": 1, "max": 20}}}, TEMPLATE,
             "bounded integer LIMIT"),
            ({"does_not_prove": ""}, TEMPLATE, "does_not_prove"),
            ({"alternatives": ["acme/missing"]}, TEMPLATE, "unknown alternatives"),
            ({"requires": {"roles": ["label"], "graph_roles": ["semantic"],
                           "capabilities": {"direct_rel_triples": True}},
              "alternatives": []}, TEMPLATE, "alternative for its capability gate"),
            ({}, TEMPLATE.replace("LIMIT {{LIMIT}}", "{{MEMBERSHIP:subject}} LIMIT {{LIMIT}}"),
             "requires.membership"),
        ):
            with self.subTest(expected=expected):
                self.write_catalog(**spec)
                self.template_path.write_text(source, encoding="utf-8")
                with self.assertRaisesRegex(CatalogError, expected):
                    load_catalog(extensions=[self.catalog_path])

    def test_profile_refusal_and_readonly_validation_still_precede_execution(self):
        self.write_catalog(requires={
            "roles": ["label"], "graph_roles": ["semantic"],
            "capabilities": {"direct_rel_triples": True},
        })
        with patch.object(cli, "_execute") as execute:
            result, _, error = self.command(
                "query", "run", "acme/labels", "--catalog", str(self.catalog_path),
                "--data", "unused.trig",
            )
            self.assertEqual(result, cli.REFUSED, error)
            execute.assert_not_called()

        self.write_catalog()
        self.template_path.write_text(UNSAFE_TEMPLATE, encoding="utf-8")
        with patch.object(cli, "_execute") as execute:
            result, _, error = self.command(
                "query", "run", "acme/labels", "--catalog", str(self.catalog_path),
                "--data", "unused.trig",
            )
            self.assertEqual(result, cli.REFUSED, error)
            self.assertIn("read-only", error)
            execute.assert_not_called()

    def test_run_uses_external_template_and_batch_renders_all_before_transport(self):
        raw = {
            "schema_version": 1, "form": "SELECT", "variables": ["subject"],
            "rows": [{"subject": "https://example.org/record"}], "boolean": None,
            "triples": None, "elapsed_ms": 1, "dataset_id": "test-dataset",
            "named_graphs_present": True, "description": "test dataset",
        }
        with patch.object(cli, "_execute", return_value=raw) as execute:
            result, output, error = self.command(
                "query", "run", "acme/labels", "--catalog", str(self.catalog_path),
                "--data", "unused.trig", "--format", "json",
            )
            self.assertEqual(result, cli.OK, error)
            self.assertEqual(json.loads(output)["template"], "acme/labels")
            self.assertIn("SELECT ?subject", execute.call_args.args[0])

        manifest = self.root / "batch.json"
        manifest.write_text(json.dumps({"schema_version": 1, "queries": [
            {"template": "core/inventory"}, {"template": "acme/labels"},
        ]}), encoding="utf-8")
        profile = support.load_resolved_profile("linked-archi-default")
        with patch.object(cli, "_profile", return_value=profile), \
                patch.object(cli, "_machine", return_value={"results": [raw, raw]}) as machine:
            result, output, error = self.command(
                "query", "batch", str(manifest), "--catalog", str(self.catalog_path),
                "--data", "unused.trig",
            )
            self.assertEqual(result, cli.OK, error)
            self.assertIn("2 queries in one invocation", output)
            request = machine.call_args.args[3]
            self.assertEqual(len(request["queries"]), 2)
            self.assertIn("SELECT ?subject", request["queries"][1])

        self.template_path.write_text(UNSAFE_TEMPLATE, encoding="utf-8")
        with patch.object(cli, "_profile", return_value=profile), \
                patch.object(cli, "_machine") as machine:
            result, _, error = self.command(
                "query", "batch", str(manifest), "--catalog", str(self.catalog_path),
                "--data", "unused.trig",
            )
            self.assertEqual(result, cli.REFUSED, error)
            machine.assert_not_called()

    def test_overlay_works_from_an_isolated_installed_query_skill(self):
        source = support.ROOT / "skills" / "linked-archi-query"
        installed = self.root / "installed" / "linked-archi-query"
        shutil.copytree(source, installed, ignore=shutil.ignore_patterns("__pycache__"))
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["LINKED_ARCHI_SKILLS_DIR"] = str(support.ROOT / "skills")
        done = subprocess.run(
            [sys.executable, str(installed / "scripts" / "la-query"), "query", "render",
             "acme/labels", "--catalog", str(self.catalog_path)],
            cwd=self.root, env=environment, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("SELECT ?subject", done.stdout)


if __name__ == "__main__":
    unittest.main()
