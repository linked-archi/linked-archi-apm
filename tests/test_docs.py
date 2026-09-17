"""The published site, checked against what the package actually ships.

The docs make specific, countable claims: 39 templates, nine analysis patterns, six skills. Those
are exactly the claims that rot, because adding a template is a one-line catalogue change and
nothing else would notice. A site that documents 38 of 39 templates is worse than one that documents
none, since a reader has no way to tell which page is stale.

These tests do not check prose. They check that every name the package ships appears in the page
that claims to list them all, and that the counts stated in the text match the counts on disk.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from support import ROOT

DOCS = ROOT / "docs"
CATALOG = ROOT / "skills/linked-archi-query/assets/templates/catalog.json"
PATTERNS = ROOT / "skills/linked-archi-analyse/assets/patterns.json"


class TestTemplateCatalogueIsDocumentedWhole(unittest.TestCase):
    def setUp(self):
        self.templates = json.loads(CATALOG.read_text(encoding="utf-8"))["templates"]
        self.page = (DOCS / "templates.md").read_text(encoding="utf-8")

    def test_every_shipped_template_has_a_section(self):
        missing = [name for name in self.templates if f"### `{name}`" not in self.page]
        self.assertEqual(
            missing, [],
            "docs/templates.md is generated from catalog.json; regenerate it after adding a "
            f"template. Missing: {missing}",
        )

    def test_the_page_documents_no_template_that_does_not_exist(self):
        documented = set(re.findall(r"^### `([^`]+)`$", self.page, re.MULTILINE))
        self.assertEqual(
            documented - set(self.templates), set(),
            "the page documents a template the catalogue does not ship",
        )

    def test_the_stated_count_matches(self):
        """The prose says a number. Numbers in prose are the first thing to go stale."""
        self.assertIn(
            "Thirty-nine tested templates", self.page,
            f"the catalogue ships {len(self.templates)} templates; the page's opening sentence "
            "states a different number",
        )
        self.assertEqual(len(self.templates), 39)

    def test_the_stage_table_counts_match_the_catalogue(self):
        counts: dict[str, int] = {}
        for spec in self.templates.values():
            counts[spec["stage"]] = counts.get(spec["stage"], 0) + 1
        for stage, count in counts.items():
            self.assertRegex(
                self.page, rf"\| \[{stage}\]\(#{stage}\) \| {count} \|",
                f"stage {stage} has {count} templates in the catalogue; the table disagrees",
            )


class TestTheRoleTableMatchesTheDefaultProfile(unittest.TestCase):
    """The profile page lists every role by group, and claims a count in its heading.

    A role added to the default profile and not to the page leaves a reader with a list that
    looks complete and is not, which is worse than no list: the roles table is the only place
    the whole vocabulary surface is written down in one view.
    """

    def setUp(self):
        import yaml

        document = yaml.safe_load(
            (
                ROOT / "skills/linked-archi-profile/assets/profiles/linked-archi-default.yaml"
            ).read_text(encoding="utf-8")
        )
        self.roles = set(document["roles"])
        page = (DOCS / "concepts/profile.md").read_text(encoding="utf-8")
        self.heading, _, rest = page.partition("### The ")[2].partition("\n")
        self.table, _, _ = rest.partition("`la-profile show`")

    def test_every_bound_role_appears_in_the_table(self):
        named = set(re.findall(r"`([a-z_]+)`", self.table))
        self.assertEqual(
            self.roles - named, set(),
            "roles bound by linked-archi-default but absent from the table in "
            "docs/concepts/profile.md",
        )

    def test_the_table_invents_no_role(self):
        named = set(re.findall(r"`([a-z_]+)`", self.table))
        self.assertEqual(
            named - self.roles, set(),
            "the table names a role the default profile does not bind",
        )

    def test_the_heading_states_the_real_count(self):
        self.assertTrue(
            self.heading.startswith(f"{len(self.roles)} roles"),
            f"the default profile binds {len(self.roles)} roles; the heading says {self.heading!r}",
        )


class TestAnalysisPatternsAreDocumentedWhole(unittest.TestCase):
    def setUp(self):
        self.patterns = json.loads(PATTERNS.read_text(encoding="utf-8"))["patterns"]
        self.page = (DOCS / "patterns.md").read_text(encoding="utf-8")

    def test_every_pattern_has_a_section(self):
        missing = [name for name in self.patterns if f"### `{name}`" not in self.page]
        self.assertEqual(missing, [], f"docs/patterns.md is missing: {missing}")

    def test_every_pattern_lists_all_of_its_templates(self):
        for name, entry in self.patterns.items():
            with self.subTest(pattern=name):
                for template in entry["templates"]:
                    self.assertIn(f"`{template}`", self.page)

    def test_the_stated_count_matches(self):
        self.assertIn("Nine patterns", self.page)
        self.assertEqual(len(self.patterns), 9)


class TestEveryPageIsReachable(unittest.TestCase):
    """A page absent from the nav is invisible; a nav entry with no page fails the build.

    `mkdocs build --strict` catches the second. It does not catch the first, because an orphan
    file is legal - so a page someone wrote and never linked would simply never be read.
    """

    def setUp(self):
        self.config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    def test_every_markdown_file_appears_in_the_nav(self):
        pages = sorted(
            str(path.relative_to(DOCS)) for path in DOCS.rglob("*.md")
        )
        missing = [page for page in pages if page not in self.config]
        self.assertEqual(missing, [], f"not reachable from the mkdocs nav: {missing}")

    def test_every_nav_target_exists(self):
        targets = re.findall(r":\s+([A-Za-z0-9_/-]+\.md)\s*$", self.config, re.MULTILINE)
        self.assertTrue(targets, "no nav entries found; the nav parser needs updating")
        missing = [target for target in targets if not (DOCS / target).is_file()]
        self.assertEqual(missing, [], f"nav names a page that does not exist: {missing}")


class TestSkillPagesExistForEverySkill(unittest.TestCase):
    def test_one_page_per_shipped_skill(self):
        skills = sorted(p.name for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").is_file())
        self.assertEqual(len(skills), 6, skills)
        for skill in skills:
            slug = skill.removeprefix("linked-archi-")
            with self.subTest(skill=skill):
                self.assertTrue(
                    (DOCS / "skills" / f"{slug}.md").is_file(),
                    f"no docs/skills/{slug}.md for shipped skill {skill}",
                )


if __name__ == "__main__":
    unittest.main()
