"""Compact inspection must not shrink saved evidence or hide its limitations."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import support

from linked_archi_query import cli
from linked_archi_query.envelope import Envelope


class TestSavedPreview(unittest.TestCase):
    def envelope(self, **overrides):
        values = dict(
            query="SELECT ?subject WHERE { ?subject ?predicate ?object } LIMIT 3",
            dataset_id="base.trig",
            profile_id="linked-archi-default",
            profile_version=1,
            elapsed_ms=2,
            row_count=3,
            template="core/inventory",
            form="SELECT",
            variables=["subject"],
            rows=[{"subject": f"urn:subject:{index}"} for index in range(3)],
            truncated=True,
            warnings=["views graph is partial", "profile has not been verified"],
        )
        values.update(overrides)
        return Envelope.build(**values)

    def test_preview_and_default_write_identical_complete_envelopes(self):
        envelope = self.envelope()
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.json"
            previewed = Path(directory) / "previewed.json"
            outputs = []
            for target, preview in ((original, False), (previewed, True)):
                output = io.StringIO()
                args = argparse.Namespace(
                    output=str(target), preview=preview, limit=1, format="json", json=True,
                )
                with contextlib.redirect_stdout(output):
                    self.assertEqual(cli._emit(envelope, args), cli.OK)
                outputs.append(output.getvalue())
            self.assertEqual(original.read_bytes(), previewed.read_bytes())
            self.assertEqual(json.loads(previewed.read_text()), envelope.to_dict())
            self.assertEqual(outputs[0], f"Wrote {original} (3 row(s))\n")

        output = outputs[1]
        self.assertIn("showing 1 of 3", output)
        self.assertIn("floor", output)
        self.assertIn("urn:subject:0", output)
        self.assertNotIn("urn:subject:1", output)
        for warning in envelope.warnings:
            self.assertIn(warning, output)
        self.assertTrue(output.rstrip().endswith(envelope.citation()))

    def test_ask_and_empty_previews_keep_existing_guidance_and_caveats(self):
        for fields in (
            {"rows": [], "row_count": 0, "truncated": False},
            {"rows": [], "form": "ASK", "boolean": False, "truncated": False},
        ):
            with self.subTest(fields=fields):
                envelope = self.envelope(**fields)
                self.assertEqual(envelope.to_preview(limit=1), envelope.to_tsv(limit=1))
                for warning in envelope.warnings:
                    self.assertIn(warning, envelope.to_preview(limit=1))

    def test_construct_preview_bounds_display_lines_without_changing_saved_triples(self):
        triples = "\n".join(f"<urn:{index}> <urn:predicate> <urn:value> ." for index in range(3))
        envelope = self.envelope(
            form="CONSTRUCT", rows=[], variables=[], row_count=0,
            triples=triples, truncated=False,
        )
        before = envelope.to_json()
        output = envelope.to_preview(limit=1)
        self.assertIn("showing 1 of 3 CONSTRUCT output lines", output)
        self.assertIn("not a complete RDF document", output)
        self.assertIn("<urn:0>", output)
        self.assertNotIn("<urn:1>", output)
        self.assertIn("profile has not been verified", output)
        self.assertTrue(output.rstrip().endswith(envelope.citation()))
        self.assertEqual(envelope.to_json(), before)

    def test_invalid_preview_settings_refuse_before_profile_or_backend_access(self):
        for arguments in (
            ["query", "run", "core/models", "--preview"],
            ["query", "literal", "--query", "ASK {}", "--preview"],
            ["query", "run", "core/models", "--preview", "-o", "unused.json", "--limit", "0"],
            ["query", "batch", "missing.json", "--preview", "--limit", "-1"],
        ):
            with self.subTest(arguments=arguments), patch.object(cli, "_profile") as profile:
                with contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(cli.main(arguments), cli.REFUSED)
                self.assertIn("--preview requires", error.getvalue())
                profile.assert_not_called()


class TestPreviewCommands(unittest.TestCase):
    def setUp(self):
        support.requires_pyoxigraph(self)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.environment = {
            key: value for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "LINKED_ARCHI_DATA", "LINKED_ARCHI_SKILLS_DIR",
                           "LINKED_ARCHI_STORE", "LINKED_ARCHI_STATE_DIR"}
        }
        self.environment["LINKED_ARCHI_STATE_DIR"] = str(self.directory / "state")

    def command(self, *arguments):
        done = subprocess.run(
            [sys.executable, str(support.ROOT / "skills/linked-archi-query/scripts/la-query"),
             "query", *arguments, "--data", str(support.BASE)],
            capture_output=True, text=True, timeout=180, cwd=support.ROOT,
            env=self.environment,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_run_and_literal_preview_preserve_query_limits_and_unverified_warning(self):
        for operation in (
            ("run", "core/inventory", "--set", "LIMIT=3"),
            ("literal", "--query", "SELECT DISTINCT ?subject WHERE { "
             "GRAPH ?graph { ?subject ?predicate ?object } } LIMIT 3"),
        ):
            with self.subTest(operation=operation):
                target = self.directory / f"{operation[0]}.json"
                output = self.command(*operation, "-o", str(target), "--preview", "--limit", "1")
                saved = json.loads(target.read_text())
                self.assertEqual(saved["row_count"], 3)
                self.assertEqual(len(saved["rows"]), 3)
                self.assertTrue(saved["truncated"])
                self.assertIn("showing 1 of 3", output)
                self.assertIn("floor", output)
                self.assertIn("has not been verified against this dataset", output)
                self.assertIn(saved["query_id"][:12], output)
                displayed = [line for line in output.splitlines()
                             if not line.startswith(("#", "Wrote "))]
                self.assertEqual(len(displayed), 2)

    def test_batch_previews_every_result_and_keeps_summary_and_envelopes_separate(self):
        manifest = self.directory / "batch.json"
        entries = [
            {"id": "models", "template": "core/models", "out": str(self.directory / "models.json")},
            {"id": "inventory", "template": "core/inventory", "set": {"LIMIT": 3},
             "out": str(self.directory / "inventory.json")},
        ]
        manifest.write_text(json.dumps({"schema_version": 1, "queries": entries}))
        summary = self.directory / "summary.txt"
        output = self.command("batch", str(manifest), "--preview", "--limit", "1", "-o", str(summary))
        self.assertIn("2 queries in one invocation", summary.read_text())
        self.assertNotIn("# NOTE", summary.read_text())
        for entry in entries:
            saved = json.loads(Path(entry["out"]).read_text())
            self.assertGreater(len(saved["rows"]), 1)
            self.assertIn(f"# {entry['id']}\n", output)
            self.assertIn(saved["query_id"][:12], output)
            for warning in saved["warnings"]:
                self.assertIn(warning, output)
        self.assertIn("floor", output)
        self.assertEqual(output.count("has not been verified against this dataset"), 2)
