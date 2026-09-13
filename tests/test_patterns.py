"""The analyse routing table, checked against the templates that actually exist.

`assets/patterns.json` is authoritative for routing and `references/analysis-patterns.md` is
the index a reader browses. Neither is generated, because this skill ships no runtime and so
cannot run a generator - which leaves the suite as the thing that keeps them honest.

The failure being prevented is specific: a pattern that names a template nobody ships sends
an agent to run a command that does not exist, and "load only the pattern you need" is worse
than one long file if the pattern file is missing or its templates were renamed.
"""

from __future__ import annotations

import json
import unittest

import support
from support import ROOT

from linked_archi_query import load_catalog

ANALYSE = ROOT / "skills" / "linked-archi-analyse"
PATTERNS_JSON = ANALYSE / "assets" / "patterns.json"
INDEX = ANALYSE / "references" / "analysis-patterns.md"


def _patterns() -> dict:
    document = json.loads(PATTERNS_JSON.read_text(encoding="utf-8"))
    return document["patterns"]


class TestRoutingTableShape(unittest.TestCase):
    def test_the_document_is_versioned(self):
        document = json.loads(PATTERNS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], 1)
        self.assertTrue(document["patterns"])

    def test_every_pattern_declares_the_five_routing_fields(self):
        """Trigger, file, templates, capabilities, stop conditions. All five, always.

        A pattern without triggers cannot be routed to; without stop conditions it has no
        end, which is how an investigation turns into a fishing expedition.
        """
        for name, pattern in _patterns().items():
            with self.subTest(name):
                self.assertEqual(
                    set(pattern),
                    {"title", "file", "triggers", "templates", "capabilities", "stop_when"},
                )
                self.assertTrue(pattern["title"].strip())
                self.assertTrue(pattern["triggers"], "a pattern nothing routes to")
                self.assertTrue(pattern["templates"], "a pattern that runs nothing")
                self.assertTrue(pattern["stop_when"], "a pattern that never finishes")
                self.assertIsInstance(pattern["capabilities"], dict)

    def test_pattern_names_are_usable_as_identifiers(self):
        for name in _patterns():
            with self.subTest(name):
                self.assertRegex(name, r"^[a-z][a-z0-9-]*$")


class TestPatternsPointAtRealThings(unittest.TestCase):
    def test_every_pattern_file_exists(self):
        for name, pattern in _patterns().items():
            with self.subTest(name):
                self.assertTrue(
                    (ANALYSE / pattern["file"]).is_file(),
                    f"{name} points at {pattern['file']}, which is not there",
                )

    def test_every_template_named_is_one_the_catalogue_ships(self):
        catalogued = set(load_catalog().names)
        unknown = {}
        for name, pattern in _patterns().items():
            missing = [t for t in pattern["templates"] if t not in catalogued]
            if missing:
                unknown[name] = missing
        self.assertEqual(unknown, {}, f"patterns naming templates that do not exist: {unknown}")

    def test_every_capability_gate_names_a_real_capability(self):
        """So a planner can trust the gate, and a renamed capability cannot rot silently."""
        profile = support.load_resolved_profile("linked-archi-default")
        for name, pattern in _patterns().items():
            for capability in pattern["capabilities"]:
                with self.subTest(f"{name}:{capability}"):
                    self.assertIn(capability, profile.capabilities)

    def test_a_capability_gate_matches_what_the_catalogue_requires(self):
        """The routing table's gates are advisory, but they must not be inventions.

        Every capability a pattern claims gates it has to be a capability at least one of
        its own templates actually requires. Otherwise a planner refuses a pattern the data
        could have answered.
        """
        catalog = load_catalog()
        for name, pattern in _patterns().items():
            required = set()
            for template in pattern["templates"]:
                required |= set(catalog.get(template).requires.capabilities)
            for capability in pattern["capabilities"]:
                with self.subTest(f"{name}:{capability}"):
                    self.assertIn(
                        capability, required,
                        f"{name} claims {capability} gates it, but none of its templates "
                        "requires it",
                    )


class TestIndexAgreesWithTheData(unittest.TestCase):
    """The prose index is what a reader routes with, so it cannot drift from the data."""

    @classmethod
    def setUpClass(cls):
        cls.index = INDEX.read_text(encoding="utf-8")

    def test_every_pattern_appears_in_the_index_with_its_file(self):
        for name, pattern in _patterns().items():
            with self.subTest(name):
                self.assertIn(pattern["title"], self.index)
                relative = pattern["file"].split("references/", 1)[-1]
                self.assertIn(relative, self.index)

    def test_the_index_lists_no_pattern_that_is_gone(self):
        listed = {
            line.split("patterns/")[1].split(".md")[0]
            for line in self.index.splitlines()
            if "patterns/" in line and line.strip().startswith("|")
        }
        known = {pattern["file"].split("/")[-1][: -len(".md")] for pattern in _patterns().values()}
        self.assertEqual(listed - known, set(), "the index points at patterns that do not exist")

    def test_the_index_points_at_the_machine_readable_table(self):
        self.assertIn("assets/patterns.json", self.index)

    def test_the_skill_sends_a_reader_to_the_index(self):
        skill = (ANALYSE / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/analysis-patterns.md", skill)


class TestPatternFilesCarryTheirOwnRouting(unittest.TestCase):
    """Each file has to stand alone: it is loaded without the others, by design."""

    def test_each_file_states_its_triggers_and_its_stop_conditions(self):
        for name, pattern in _patterns().items():
            with self.subTest(name):
                text = (ANALYSE / pattern["file"]).read_text(encoding="utf-8")
                self.assertIn("Triggers:", text)
                self.assertIn("## Stop when", text)

    def test_each_file_names_the_templates_the_routing_table_claims(self):
        """Prose and data disagreeing about which template to run is the whole hazard."""
        for name, pattern in _patterns().items():
            text = (ANALYSE / pattern["file"]).read_text(encoding="utf-8")
            for template in pattern["templates"]:
                with self.subTest(f"{name}:{template}"):
                    self.assertIn(template, text)


if __name__ == "__main__":
    unittest.main()
