"""Finding a dataset, and refusing to choose one.

The rule under test: **discovery reports, it does not select.** An agent that silently
picks the newest `.trig` it can find will sooner or later answer from last month's
conversion, and the answer will carry a citation line that makes it look sound. The
only thing allowed to resolve a dataset without being asked is `$LINKED_ARCHI_DATA`,
because a human or a project set that deliberately.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

import support  # noqa: F401  - puts lib/ on sys.path

from linked_archi_connect import discover
from linked_archi_connect.adapters import local


class _Sandbox(unittest.TestCase):
    """A throwaway tree, with $LINKED_ARCHI_DATA cleared so it cannot leak in."""

    def setUp(self):
        self._saved = os.environ.pop(discover.ENV_DATA, None)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        if self._saved is not None:
            os.environ[discover.ENV_DATA] = self._saved
        else:
            os.environ.pop(discover.ENV_DATA, None)

    def write(self, relative: str, text: str = "# rdf\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class TestSearch(_Sandbox):
    def test_finds_files_in_the_conventional_directories(self):
        self.write("dist/merged.trig")
        self.write("out/bpmn.trig")
        self.write("graph/archimate.nq")
        names = {c.path.name for c in discover.find(self.root)}
        self.assertEqual(names, {"merged.trig", "bpmn.trig", "archimate.nq"})

    def test_ignores_unrelated_files_and_hidden_directories(self):
        self.write("dist/notes.md")
        self.write(".git/objects/whatever.trig")
        self.write("node_modules/pkg/data.trig")
        self.assertEqual(discover.find(self.root), [])

    def test_flags_turtle_as_carrying_no_graph_identity(self):
        """The single most common cause of every scoped query returning nothing."""
        self.write("dist/merged.ttl")
        candidate = discover.find(self.root)[0]
        self.assertFalse(candidate.carries_graphs)
        self.assertTrue(
            any("graph identity" in c for c in candidate.caveats()),
            candidate.caveats(),
        )

    def test_trig_and_nquads_carry_graph_identity(self):
        self.write("dist/a.trig")
        self.write("dist/b.nq")
        for candidate in discover.find(self.root):
            self.assertTrue(candidate.carries_graphs, candidate.path)
            self.assertEqual(candidate.caveats(), [])

    def test_newest_first(self):
        old = self.write("dist/old.trig")
        time.sleep(0.01)
        new = self.write("dist/new.trig")
        os.utime(old, (1_600_000_000, 1_600_000_000))
        found = discover.find(self.root)
        self.assertEqual(found[0].path, new.resolve())

    def test_empty_tree_yields_nothing_rather_than_a_default(self):
        """No fallback to the bundled fixtures. Nothing is better than wrong."""
        self.assertEqual(discover.find(self.root), [])


class TestFixturesAreNotOfferedByDefault(_Sandbox):
    def test_test_data_is_excluded(self):
        self.write("fixtures/base.trig")
        self.write("tests/data/sample.trig")
        self.assertEqual(discover.find(self.root), [])

    def test_and_is_listed_with_a_caveat_when_asked_for(self):
        self.write("fixtures/base.trig")
        found = discover.find(self.root, include_fixtures=True)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].is_fixture)
        self.assertTrue(
            any("test data" in c for c in found[0].caveats()), found[0].caveats()
        )

    def test_a_real_dataset_beside_fixtures_is_still_found(self):
        self.write("fixtures/base.trig")
        real = self.write("dist/merged.trig")
        found = discover.find(self.root)
        self.assertEqual([c.path for c in found], [real.resolve()])


class TestEnvironmentOverride(_Sandbox):
    def test_a_named_dataset_is_marked_as_deliberate(self):
        path = self.write("anywhere/odd-name.trig")
        os.environ[discover.ENV_DATA] = str(path)
        found = discover.find(self.root)
        self.assertEqual(found[0].path, path.resolve())
        self.assertEqual(found[0].origin, "env")

    def test_several_datasets_separated_like_PATH(self):
        first = self.write("a.trig")
        second = self.write("b.trig")
        os.environ[discover.ENV_DATA] = os.pathsep.join([str(first), str(second)])
        self.assertEqual(discover.from_env(), [first, second])

    def test_a_missing_path_is_reported_not_ignored(self):
        """A typo in a project's configuration must surface, not fall back to searching."""
        os.environ[discover.ENV_DATA] = str(self.root / "does-not-exist.trig")
        self.assertEqual(len(discover.missing_from_env()), 1)

    def test_it_survives_being_pointed_at_a_fixture(self):
        """Explicit beats tidy: if someone names the fixture, it is still listed."""
        path = self.write("fixtures/base.trig")
        os.environ[discover.ENV_DATA] = str(path)
        found = discover.find(self.root)
        self.assertEqual([c.path for c in found], [path.resolve()])

    def test_unset_means_no_opinion(self):
        self.assertEqual(discover.from_env(), [])
        self.assertEqual(discover.missing_from_env(), [])


class TestGitWorkingTrees(_Sandbox):
    """A graph pulled from a repository, which is how teams actually share one.

    Nothing here fetches. Git is asked only what it can answer from the local object
    store, so this works offline and a remote repository must be cloned first.
    """

    def setUp(self):
        super().setUp()
        if not self._git_available():
            self.skipTest("git is not installed")
        self._run(["git", "init", "-q", "."])
        self._run(["git", "config", "user.email", "test@example.org"])
        self._run(["git", "config", "user.name", "Test"])

    @staticmethod
    def _git_available() -> bool:
        import shutil

        return shutil.which("git") is not None

    def _run(self, args: list[str]) -> None:
        import subprocess

        subprocess.run(args, cwd=self.root, check=True, capture_output=True)

    def _commit(self, message: str = "add graph") -> None:
        self._run(["git", "add", "-A"])
        self._run(["git", "commit", "-qm", message])

    def test_the_search_is_anchored_at_the_repository_root(self):
        """An agent's working directory is rarely the root.

        Asked a question from `docs/`, a cwd-only search misses `dist/merged.trig` two
        levels up and reports "no graph found" about a repository that has one.
        """
        graph = self.write("dist/merged.trig")
        docs = self.root / "docs"
        docs.mkdir()

        found = discover.find(docs)
        self.assertIn(graph.resolve(), [c.path for c in found])

    def test_a_graph_committed_outside_a_build_directory_is_found(self):
        """Teams commit graphs to `architecture/`, not only to `out/`."""
        graph = self.write("architecture/graphs/model.trig")
        self.assertIn(graph.resolve(), [c.path for c in discover.find(self.root)])

    def test_a_clean_file_reports_its_commit_and_ref(self):
        self.write("dist/merged.trig")
        self._commit()

        candidate = discover.find(self.root, with_git=True)[0]
        self.assertIsNotNone(candidate.git)
        self.assertTrue(candidate.git.commit)
        self.assertTrue(candidate.git.ref)
        self.assertTrue(candidate.git.committed, "expected a commit date")
        self.assertFalse(candidate.git.dirty)
        self.assertFalse(candidate.git.untracked)
        self.assertEqual(candidate.caveats(), [])

    def test_an_uncommitted_edit_is_a_caveat(self):
        """It matches no reviewable version, so nobody can reproduce the answer."""
        graph = self.write("dist/merged.trig")
        self._commit()
        graph.write_text("# rdf\n# edited\n", encoding="utf-8")

        candidate = discover.find(self.root, with_git=True)[0]
        self.assertTrue(candidate.git.dirty)
        self.assertTrue(
            any("last commit" in c for c in candidate.caveats()), candidate.caveats()
        )

    def test_an_untracked_file_is_a_caveat(self):
        self.write("dist/scratch.trig")

        candidate = discover.find(self.root, with_git=True)[0]
        self.assertTrue(candidate.git.untracked)
        self.assertTrue(
            any("only on this machine" in c for c in candidate.caveats()),
            candidate.caveats(),
        )

    def test_commit_date_orders_ahead_of_mtime(self):
        """The defect this fixes: after a clone, every file's mtime is the checkout.

        Two files touched at the same instant are indistinguishable by mtime. The
        commit dates differ, so the ordering has to come from git.
        """
        old = self.write("dist/old.trig")
        new = self.write("dist/new.trig")
        self._run(["git", "add", "-A"])
        self._run([
            "git", "commit", "-qm", "old", "--date", "2020-01-01T00:00:00", "--",
            "dist/old.trig",
        ])
        self._run(["git", "commit", "-qm", "new", "--", "dist/new.trig"])
        # Simulate a fresh clone: identical mtimes for both files.
        stamp = 1_700_000_000
        for path in (old, new):
            os.utime(path, (stamp, stamp))

        found = discover.find(self.root, with_git=True)
        self.assertEqual(
            found[0].path, new.resolve(),
            "the more recently committed graph should come first",
        )

    def test_outside_a_working_tree_git_info_is_absent_not_an_error(self):
        graph = self.write("dist/merged.trig")
        import shutil

        shutil.rmtree(self.root / ".git")
        candidate = discover.find(self.root, with_git=True)[0]
        self.assertIsNone(candidate.git)
        self.assertEqual(candidate.path, graph.resolve())

    def test_repo_root_is_none_outside_a_working_tree(self):
        import shutil

        shutil.rmtree(self.root / ".git")
        self.assertIsNone(discover.repo_root(self.root))


class TestNothingSelectsImplicitly(_Sandbox):
    def test_open_adapter_still_requires_an_explicit_target(self):
        """Discovery must not have quietly become auto-selection.

        `find()` returning candidates changes nothing about execution: a dataset in a
        result's citation line should be one somebody chose.
        """
        from linked_archi_connect.adapters import AdapterError, open_adapter

        self.write("dist/merged.trig")
        with self.assertRaises(AdapterError) as caught:
            open_adapter()
        self.assertIn("--data", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class TestDiscoveryAgreesWithTheLoader(_Sandbox):
    """Discovery and the local adapter must describe the same set of files.

    They disagreed once, in both directions, and each direction produced a distinct
    failure. Discovery ignored `.nt`, `.rdf`, `.xml`, `.jsonld` and `.json`, so a graph
    the adapter loads happily was invisible to `datasets` and the only way to find it was
    the manual filesystem search this command exists to replace. Discovery also offered
    `.nquads`, which the adapter refused, so a candidate it proposed could not be loaded.
    """

    def test_every_discoverable_extension_can_actually_be_loaded(self):
        self.assertEqual(
            set(discover.EXTENSIONS),
            set(local.FORMATS),
            "discovery and the local adapter disagree about supported extensions",
        )

    def test_graph_identity_matches_the_adapters_quad_formats(self):
        for extension, carries in discover.EXTENSIONS.items():
            with self.subTest(extension=extension):
                self.assertEqual(
                    carries,
                    local.FORMATS[extension] in local.QUAD_FORMATS,
                    f"{extension} misreports whether it carries named graphs",
                )

    def test_the_formats_that_lose_graph_identity_are_named(self):
        # The caveat this flag drives is the most common cause of an empty scoped
        # query, so pin the classification rather than only its internal consistency.
        flattening = {ext for ext, carries in discover.EXTENSIONS.items() if not carries}
        self.assertEqual(
            flattening,
            {".ttl", ".turtle", ".nt", ".rdf", ".xml", ".jsonld", ".json", ".n3"},
        )
        self.assertEqual(
            {ext for ext, carries in discover.EXTENSIONS.items() if carries},
            {".trig", ".nq", ".nquads"},
        )

    def test_a_supported_non_quad_graph_is_discovered(self):
        self.write("dist/model.jsonld", "{}\n")
        self.write("graph/model.rdf", "<rdf/>\n")
        found = {c.path.name: c for c in discover.find(self.root)}
        self.assertIn("model.jsonld", found)
        self.assertIn("model.rdf", found)
        self.assertFalse(found["model.jsonld"].carries_graphs)
        self.assertFalse(found["model.rdf"].carries_graphs)


class TestAmbiguousExtensions(_Sandbox):
    """Loadable is not the same as worth scanning.

    `.json` and `.xml` are real RDF serialisations and also the two most common
    non-RDF suffixes in a repository. Scanning them by default turns `package.json`
    and `pom.xml` into dataset candidates, burying the graphs this command exists to
    surface - so they stay loadable and become discoverable on request.
    """

    def test_build_configuration_is_not_offered_as_a_dataset(self):
        self.write("dist/merged.trig")
        self.write("package.json", '{"name": "not-a-graph"}\n')
        self.write("data/tsconfig.json", "{}\n")
        self.write("data/sitemap.xml", "<urlset/>\n")
        names = {c.path.name for c in discover.find(self.root)}
        self.assertEqual(names, {"merged.trig"})

    def test_json_ld_is_found_when_asked_for_by_name(self):
        self.write("data/graph.json", "{}\n")
        self.assertEqual(discover.find(self.root), [])
        asked = {c.path.name for c in discover.find(self.root, extensions=[".json"])}
        self.assertEqual(asked, {"graph.json"})

    def test_an_explicit_dataset_is_returned_whatever_its_suffix(self):
        explicit = self.write("anywhere/graph.json", "{}\n")
        os.environ[discover.ENV_DATA] = str(explicit)
        found = discover.find(self.root)
        self.assertEqual([c.path for c in found], [explicit.resolve()])
        self.assertEqual(found[0].origin, "env")

    def test_an_unloadable_extension_is_refused_rather_than_returning_nothing(self):
        # A typo must not look like a repository with no graph in it.
        with self.assertRaises(ValueError) as caught:
            discover.find(self.root, extensions=["trigg"])
        self.assertIn("not a loadable RDF extension", str(caught.exception))

    def test_extensions_are_normalised_without_a_leading_dot(self):
        self.write("dist/model.jsonld", "{}\n")
        found = discover.find(self.root, extensions=["jsonld"])
        self.assertEqual({c.path.name for c in found}, {"model.jsonld"})

    def test_default_scan_is_every_unambiguous_loadable_suffix(self):
        self.assertEqual(
            discover.DEFAULT_EXTENSIONS,
            frozenset(discover.EXTENSIONS) - discover.AMBIGUOUS_EXTENSIONS,
        )
        self.assertTrue(discover.AMBIGUOUS_EXTENSIONS <= set(local.FORMATS))


class TestDirectoryResolution(_Sandbox):
    """A user says "the graph is in models/archi-graph"; one file inside it is queryable.

    Resolving that here is what stops the alternative, which is an agent running its own
    filesystem search and taking whatever it finds first.
    """

    def test_graph_carrying_wins_over_the_same_graph_flattened(self):
        # The common publishing layout: merged-graph.trig beside merged-graph.ttl.
        self.write("archi-graph/merged-graph.trig")
        self.write("archi-graph/merged-graph.ttl")
        choice = discover.resolve_directory(self.root / "archi-graph", with_git=False)
        self.assertEqual(choice.path.name, "merged-graph.trig")
        self.assertIsNone(choice.caveat)

    def test_two_graph_carrying_files_are_refused_not_guessed(self):
        self.write("archi-graph/merged-graph.trig")
        self.write("archi-graph/last-month.trig")
        with self.assertRaises(discover.AmbiguousDirectory) as caught:
            discover.resolve_directory(self.root / "archi-graph", with_git=False)
        message = str(caught.exception)
        self.assertIn("none was chosen", message)
        self.assertIn("merged-graph.trig", message)
        self.assertIn("last-month.trig", message)

    def test_a_flattening_only_directory_resolves_with_a_caveat(self):
        self.write("archi-graph/model.ttl")
        choice = discover.resolve_directory(self.root / "archi-graph", with_git=False)
        self.assertEqual(choice.path.name, "model.ttl")
        self.assertIn("no named graphs", choice.caveat)

    def test_an_empty_directory_reports_what_it_searched(self):
        (self.root / "empty").mkdir()
        with self.assertRaises(discover.AmbiguousDirectory):
            discover.resolve_directory(self.root / "empty", with_git=False)

    def test_nested_graphs_do_not_resolve_implicitly(self):
        # A graph two levels down may be one of several sources rather than the dataset.
        self.write("archi-graph/graph/leanix/inventory.trig")
        with self.assertRaises(discover.AmbiguousDirectory) as caught:
            discover.resolve_directory(self.root / "archi-graph", with_git=False)
        self.assertIn("inventory.trig", str(caught.exception))

    def test_an_unloadable_suffix_is_not_a_candidate(self):
        self.write("archi-graph/notes.md", "# not rdf\n")
        self.write("archi-graph/merged.trig")
        choice = discover.resolve_directory(self.root / "archi-graph", with_git=False)
        self.assertEqual(choice.path.name, "merged.trig")


class TestReachingAnUnconventionalLayout(_Sandbox):
    """A graph somewhere the convention does not name must be reachable with flags.

    The alternative is what field sessions actually did: "no graph found" from a repository
    that plainly has one, followed by a manual filesystem glob. Every dimension of the
    search is now a flag, and the negative result names all of them.
    """

    DEEP = "deeply/nested/custom/graph.trig"

    def test_the_default_search_does_not_reach_it(self):
        """Establishes that the flags below are doing the work, not the default."""
        self.write(self.DEEP)
        self.assertEqual(discover.find(self.root), [])

    def test_a_deeper_walk_reaches_it(self):
        self.write(self.DEEP)
        found = discover.find(self.root, max_depth=4)
        self.assertEqual([c.path.name for c in found], ["graph.trig"])

    def test_naming_the_directory_reaches_it_without_deepening_anything(self):
        self.write(self.DEEP)
        found = discover.find(self.root, directories=["deeply/nested/custom"])
        self.assertEqual([c.path.name for c in found], ["graph.trig"])

    def test_naming_directories_replaces_the_conventional_list(self):
        """A caller naming a layout knows something the convention does not.

        Adding to the list would keep walking nine directories nobody asked about. The
        observable difference is depth: `dist/` is no longer walked three levels down, while
        anything one level from the root still shows up because `.` is always scanned.
        """
        self.write("dist/nested/deeper/conventional.trig")
        self.write("custom/named.trig")
        found = discover.find(self.root, directories=["custom"])
        self.assertEqual([c.path.name for c in found], ["named.trig"])
        # And a bare search does find it, so the file itself is not the reason.
        bare = {c.path.name for c in discover.find(self.root)}
        self.assertIn("conventional.trig", bare)

    def test_the_current_directory_is_always_scanned(self):
        """So a graph sitting directly in the named root is never missed."""
        self.write("beside.trig")
        found = discover.find(self.root, directories=["nowhere"])
        self.assertEqual([c.path.name for c in found], ["beside.trig"])

    def test_an_explicit_depth_deepens_the_root_scan_too(self):
        """`.` is shallow only by DEFAULT; asking for depth means what it says."""
        self.write("a/b/graph.trig")
        self.assertEqual(discover.find(self.root), [])
        found = discover.find(self.root, max_depth=2)
        self.assertEqual([c.path.name for c in found], ["graph.trig"])

    def test_an_absurd_depth_is_refused_with_the_alternative(self):
        with self.assertRaises(ValueError) as caught:
            discover.find(self.root, max_depth=discover.MAX_MAX_DEPTH + 1)
        message = str(caught.exception)
        self.assertIn("--search-dir", message)
        self.assertIn("--data", message)

    def test_a_negative_depth_is_refused(self):
        with self.assertRaises(ValueError):
            discover.find(self.root, max_depth=-1)

    def test_an_absolute_search_dir_is_refused_and_points_at_data(self):
        with self.assertRaises(ValueError) as caught:
            discover.find(self.root, directories=["/etc"])
        self.assertIn("--data", str(caught.exception))
