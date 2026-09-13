"""The APM manifest: what a consumer's package manager actually reads.

`apm.yml` had no test at all until this file. Nothing in the suite parsed it, and the only
other consumer is a Makefile regex that lifts `version:` out for the tarball name - so a
manifest that stopped parsing, or that pointed `includes:` at a directory somebody renamed,
would have shipped with every check green. That failure is silent in the worst way:
`apm install` reads the manifest, not this repository's prose, so the package would install
nothing at all while the six skills sat correct and committed beside it.

Two kinds of check here, and the distinction matters when one fails.

Schema constraints are transcribed from the normative v0.1 schema the manifest pins, and
each transcription says so where it sits. Nothing here fetches that schema: a test that
needs the network is a test that fails on a plane. Nothing here vendors it either, so
these checks are the constraints this package can actually break, not a full validation -
transcription drift is the known limit, and the pinned identity is asserted so a manifest
that moved to a different schema version is caught even though its rules are not.

Decision checks pin choices this package documents in prose and would otherwise only
state once. `targets:` is the clearest case: README tells a reader the package declares
none and lets APM auto-detect, so adding one would make the documentation wrong in a way
no reader could see from the manifest.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from support import ROOT

MANIFEST = ROOT / "apm.yml"
CHANGELOG = ROOT / "CHANGELOG.md"

#: Normative OpenAPM v0.1, pinned deliberately rather than tracking the working draft.
#: An unknown schema identity fails closed in a consumer, which is the safe direction.
SCHEMA_ID = "https://microsoft.github.io/apm/specs/schemas/manifest-v0.1.schema.json"

#: Transcribed from the pinned schema's `version` pattern, which is semver 2.0.0.
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

#: The pinned schema's `type` enum. The manifest sets no `type` and explains why; this is
#: here so a later edit cannot introduce a value a consumer would reject.
TYPES = frozenset({"instructions", "skill", "hybrid", "prompts"})

#: Transcribed from Makefile line 110, which is what names the dist tarball. Kept as a
#: separate reader on purpose: the point is that a *regex* over the raw text agrees with a
#: YAML parse, so a version rewritten as a folded scalar cannot silently rename the
#: release artifact.
MAKEFILE_VERSION = re.compile(r"^version:\s*(\S+)", re.M)


class ManifestTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = MANIFEST.read_text(encoding="utf-8")
        cls.manifest = yaml.safe_load(cls.text)


class TestItParses(ManifestTestCase):
    def test_the_manifest_is_a_yaml_mapping(self):
        """The one check whose absence let everything else here go unverified."""
        self.assertIsInstance(self.manifest, dict)

    def test_it_pins_the_normative_schema(self):
        """Not the working draft. A published package must not change meaning later."""
        self.assertEqual(self.manifest.get("$schema"), SCHEMA_ID)

    def test_no_key_is_declared_twice(self):
        """A duplicate key parses: PyYAML keeps the last and discards the first silently.

        Which makes it the one malformation a successful parse cannot reveal. This
        manifest is heavily commented and edited by hand, so a second `dependencies:`
        block below the first is a realistic mistake with no visible symptom.
        """
        top_level = [
            line.partition(":")[0]
            for line in self.text.splitlines()
            if re.match(r"^[A-Za-z$][\w$-]*:", line)
        ]
        duplicates = sorted({key for key in top_level if top_level.count(key) > 1})
        self.assertEqual(duplicates, [], f"declared more than once: {duplicates}")


class TestRequiredFields(ManifestTestCase):
    def test_name_and_version_are_present(self):
        """The schema's only two required properties."""
        self.assertTrue(self.manifest.get("name"))
        self.assertTrue(self.manifest.get("version"))

    def test_the_version_is_a_string_and_not_a_number(self):
        """`version: 0.1` parses as a float and stops matching the schema pattern.

        Which is why the manifest quotes it, and why quoting is worth pinning rather
        than trusting: the failure surfaces in a consumer, not here.
        """
        self.assertIsInstance(self.manifest["version"], str)
        self.assertRegex(self.manifest["version"], SEMVER)

    def test_the_makefile_reads_the_same_version(self):
        """`make dist` names the tarball from a regex, not from a YAML parse.

        Two readers of one value, so they have to be shown to agree. A version rewritten
        in any form the regex cannot see would produce a tarball named after the wrong
        release, which is the sort of thing noticed after publishing.
        """
        found = MAKEFILE_VERSION.search(self.text)
        self.assertIsNotNone(found, "the Makefile's version regex matches nothing")
        self.assertEqual(found.group(1).strip("\"'"), self.manifest["version"])

    def test_a_type_if_ever_added_is_one_the_schema_admits(self):
        declared = self.manifest.get("type")
        if declared is not None:
            self.assertIn(declared, TYPES)


class TestTargets(ManifestTestCase):
    def test_it_declares_no_targets(self):
        """So resolution falls through to APM's auto-detect, which is the documented plan.

        A package-authored `targets:` RESTRICTS installation to the names listed. Nothing
        in this package is target-specific - no hooks, no target-scoped frontmatter, no
        `bin/` for one client - so a list could only exclude a runtime that would
        otherwise work, and would silently install nothing for anyone outside it. README
        states the absence as a fact about the package, so it is an invariant and not an
        oversight. Narrowing belongs to the consumer, via `--target` or a per-dependency
        `targets:`.

        The schema forbids `target` and `targets` together; declaring neither satisfies
        that and keeps the choice where it belongs.
        """
        self.assertNotIn("targets", self.manifest)
        self.assertNotIn("target", self.manifest)


class TestIncludes(ManifestTestCase):
    def skill_dirs(self) -> list[str]:
        return sorted(
            f"skills/{path.name}/" for path in (ROOT / "skills").iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )

    def test_it_lists_exactly_the_committed_skill_directories(self):
        """Both directions, because each omission fails differently and both fail quietly.

        An entry with no directory installs nothing under that name. A directory with no
        entry is a skill that exists in the repository, passes `make check`, and is absent
        from the installed package - the harder of the two to notice, since everything
        local keeps working.
        """
        self.assertEqual(sorted(self.manifest["includes"]), self.skill_dirs())
        self.assertEqual(len(self.manifest["includes"]), 6)

    def test_every_included_path_exists_and_is_a_skill(self):
        for entry in self.manifest["includes"]:
            with self.subTest(entry):
                directory = ROOT / entry
                self.assertTrue(directory.is_dir(), f"{entry} is not a directory")
                self.assertTrue(
                    (directory / "SKILL.md").is_file(), f"{entry} has no SKILL.md"
                )

    def test_the_repository_dispatcher_is_not_shipped(self):
        """`bin/la-kg` is a convenience for working in this checkout and nothing more.

        Installing it would put a repository-relative dispatcher on a consumer's PATH,
        where the paths it resolves do not exist.
        """
        self.assertTrue((ROOT / "bin" / "la-kg").is_file(), "the dispatcher moved")
        for entry in self.manifest["includes"]:
            self.assertFalse(entry.startswith("bin"))


class TestDependencies(ManifestTestCase):
    def test_no_mandatory_mcp_server(self):
        """URL and Git acquisition work without one; GitLab MCP is agent-mediated.

        A mandatory server here would hand every installation a repository credential
        decision that belongs to the deployment. USAGE.md documents the absence, so it
        is pinned rather than left to be quietly reversed.
        """
        self.assertEqual(self.manifest["dependencies"]["mcp"], [])

    def test_no_apm_dependencies(self):
        """The six skills depend on each other, and on nothing outside this package."""
        self.assertEqual(self.manifest["dependencies"]["apm"], [])


class TestChangelog(ManifestTestCase):
    """The release body is read from CHANGELOG.md, so the two files have to agree.

    `make release-notes` extracts the section for the manifest version and the release
    workflow publishes exactly that. A version bumped in `apm.yml` with no section written
    for it fails the release - and that failure is worth having here instead, where it
    costs a test run rather than a tag that has already been pushed and fetched.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.changelog = CHANGELOG.read_text(encoding="utf-8")

    def test_the_manifest_version_has_a_section(self):
        heading = f"## [{self.manifest['version']}]"
        self.assertIn(
            heading,
            self.changelog,
            f"CHANGELOG.md has no {heading} section for the declared version",
        )

    def test_that_section_says_something(self):
        """An empty section passes a substring check and publishes a blank release."""
        version = self.manifest["version"]
        after = self.changelog.split(f"## [{version}]", 1)[1]
        # Same three stops the Makefile extractor uses: the next release heading, a link
        # reference definition, or end of file.
        body = re.split(r"^(?:## \[|\[[^\]]+\]: )", after, maxsplit=1, flags=re.M)[0]
        # Drop the rest of the heading line, which carries only the date.
        body = body.split("\n", 1)[1] if "\n" in body else ""
        self.assertTrue(body.strip(), f"the {version} section is empty")

    def test_the_version_is_linked(self):
        """Keep a Changelog's link definitions, so a reader can reach the release."""
        self.assertIn(f"[{self.manifest['version']}]: https://", self.changelog)

    def test_every_root_document_ships_including_this_one(self):
        """`make dist` copies a hand-written list, so a new document is opt-in.

        A changelog a consumer cannot read after installing is a changelog for us only,
        and the same is true of every other root document. Asserting the whole set rather
        than just CHANGELOG.md means the next document added at the root is caught too -
        the mistake is forgetting the list exists, not forgetting one file.
        """
        recipe = re.search(r"@for item in (.*?); do",
                           (ROOT / "Makefile").read_text(encoding="utf-8"), re.S)
        self.assertIsNotNone(recipe, "the dist copy list moved; this test cannot see it")
        # Line continuations and indentation are noise between the item names.
        shipped = set(recipe.group(1).replace("\\", " ").split())
        at_root = {path.name for path in ROOT.glob("*.md")}
        self.assertEqual(
            at_root - shipped, set(), "root documents missing from the dist copy list"
        )
        self.assertIn("CHANGELOG.md", shipped)


class TestScripts(ManifestTestCase):
    def test_there_is_no_scripts_block(self):
        """`apm run` executes in the consumer's project, where only skills exist.

        This block once held entries pointing at `profiles/`, `fixtures/` and `tests/` -
        paths that exist in this repository and nowhere else - so every one of them would
        have failed for a consumer. A broken script is worse than no script, because
        `apm list` advertises it. The equivalents are Makefile targets.
        """
        self.assertNotIn("scripts", self.manifest)


if __name__ == "__main__":
    unittest.main()
