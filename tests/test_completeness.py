"""Does what loaded account for everything the project declares?

Written from a real failure. A merged artifact was loaded and queried confidently; it
contained no LeanIX model, while the LeanIX graph file sat in the next directory. The
dataset looked complete because a merge is supposed to be complete, and nothing said
otherwise. These tests pin the warning that would have caught it - and, just as
importantly, the cases where it must stay quiet, because a warning that cries wolf gets
ignored exactly when it matters.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

import support  # noqa: F401  - puts the owner scripts on sys.path

from linked_archi_connect import completeness, discover

MANIFEST = textwrap.dedent(
    """
    sources:
      - id: enterprise-archimate
        target: graph/archimate/enterprise-model.trig
        tier: 1
      - id: bpmn-processes
        target: graph/bpmn/order-processes.trig
        tier: 1
      - id: enterprise-leanix
        target: graph/leanix/enterprise-inventory.trig
        tier: 2
    """
)

#: ArchiMate graph IRIs use `/model/`, not `/archimate/` - the converter's --path-model
#: defaults to `model`. If the alias were missing, every ArchiMate source would be
#: reported absent, so this shape is load-bearing rather than incidental.
MERGED_GRAPHS = [
    "https://example.org/la/model/enterprise/graph/semantic",
    "https://example.org/la/bpmn/orders/graph/semantic",
]
LEANIX_GRAPH = "https://example.org/la/leanix/inventory/graph/semantic"


class _Project(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, manifest: str = MANIFEST, targets: bool = True) -> Path:
        (self.root / "sources-index.yaml").write_text(manifest, encoding="utf-8")
        merged = self.root / "merged-graph.trig"
        merged.write_text("# merged\n", encoding="utf-8")
        if targets:
            for relative in (
                "graph/archimate/enterprise-model.trig",
                "graph/bpmn/order-processes.trig",
                "graph/leanix/enterprise-inventory.trig",
            ):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# source\n", encoding="utf-8")
        return merged


class TestDroppedSources(_Project):
    def test_a_merge_missing_one_source_names_it(self):
        merged = self.build()
        result = completeness.assess([merged], MERGED_GRAPHS)
        self.assertEqual([source.id for source in result.dropped], ["enterprise-leanix"])
        note = " ".join(result.notes())
        self.assertIn("enterprise-leanix", note)
        self.assertIn("looks like the merged whole", note)
        self.assertIn("core/models", note, "the fact belongs to the query owner")

    def test_a_complete_merge_says_nothing(self):
        merged = self.build()
        result = completeness.assess([merged], [*MERGED_GRAPHS, LEANIX_GRAPH])
        self.assertEqual(result.dropped, [])
        self.assertEqual(result.notes(), [])

    def test_archimate_is_matched_through_its_model_slug(self):
        """Without the alias this would report a false absence."""
        merged = self.build()
        result = completeness.assess([merged], MERGED_GRAPHS)
        archimate = next(s for s in result.sources if s.id == "enterprise-archimate")
        self.assertTrue(archimate.represented)

    def test_a_single_notation_dataset_is_reported_differently(self):
        merged = self.build()
        result = completeness.assess([merged], ["https://example.org/la/bpmn/o/graph/semantic"])
        note = " ".join(result.notes())
        self.assertIn("single-notation dataset", note)
        self.assertNotIn("looks like the merged whole", note)

    def test_a_source_never_pulled_is_a_different_finding(self):
        merged = self.build(targets=False)
        result = completeness.assess([merged], MERGED_GRAPHS)
        self.assertEqual(result.dropped, [], "a file that does not exist was not dropped")
        self.assertEqual(len(result.never_pulled), 3)
        self.assertIn("never fully pulled", " ".join(result.notes()))

    def test_loading_a_source_directly_counts_as_represented(self):
        self.build()
        source = self.root / "graph" / "leanix" / "enterprise-inventory.trig"
        result = completeness.assess([source], [])
        leanix = next(s for s in result.sources if s.id == "enterprise-leanix")
        self.assertTrue(leanix.loaded)
        self.assertTrue(leanix.represented)

    def test_a_flattened_dataset_cannot_be_assessed_by_graph_name(self):
        # No graph names means the question cannot be asked. Unknown, not absent.
        merged = self.build()
        result = completeness.assess([merged], [])
        self.assertTrue(all(s.represented in (True, None) for s in result.sources))
        self.assertEqual(result.dropped, [])


class TestManifestHandling(_Project):
    def test_a_manifest_above_the_data_file_is_found(self):
        merged = self.build()
        nested = self.root / "graph" / "archimate" / "enterprise-model.trig"
        result = completeness.assess([nested], MERGED_GRAPHS)
        self.assertEqual(
            result.manifest.resolve(), (self.root / "sources-index.yaml").resolve()
        )
        self.assertTrue(merged.exists())

    def test_a_malformed_manifest_does_not_break_connecting(self):
        merged = self.build(manifest="sources: [this is not a mapping]\n")
        result = completeness.assess([merged], MERGED_GRAPHS)
        self.assertEqual(result.sources, [])
        self.assertEqual(result.notes(), [])

    def test_unparseable_yaml_is_ignored_rather_than_raised(self):
        merged = self.build(manifest="sources: [unclosed\n")
        result = completeness.assess([merged], MERGED_GRAPHS)
        self.assertEqual(result.sources, [])

    def test_entries_without_an_id_or_target_are_skipped(self):
        merged = self.build(manifest="sources:\n  - repo: only/a-repo\n")
        result = completeness.assess([merged], MERGED_GRAPHS)
        self.assertEqual(result.sources, [])

    def test_no_manifest_reports_unloaded_siblings(self):
        graph = self.root / "one.trig"
        graph.write_text("# g\n", encoding="utf-8")
        (self.root / "two.trig").write_text("# g\n", encoding="utf-8")
        result = completeness.assess(
            [graph], MERGED_GRAPHS, known_extensions=tuple(discover.DEFAULT_EXTENSIONS)
        )
        self.assertIsNone(result.manifest)
        self.assertEqual([p.name for p in result.unloaded_files], ["two.trig"])
        self.assertIn("were not loaded", " ".join(result.notes()))

    def test_the_same_graph_in_another_serialisation_is_not_a_missing_source(self):
        """merged-graph.ttl beside merged-graph.trig is one graph, not two sources."""
        graph = self.root / "merged-graph.trig"
        graph.write_text("# g\n", encoding="utf-8")
        (self.root / "merged-graph.ttl").write_text("# g\n", encoding="utf-8")
        result = completeness.assess(
            [graph], MERGED_GRAPHS, known_extensions=tuple(discover.DEFAULT_EXTENSIONS)
        )
        self.assertEqual(result.unloaded_files, [])
        self.assertEqual(result.notes(), [])


if __name__ == "__main__":
    unittest.main()
