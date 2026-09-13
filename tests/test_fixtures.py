"""What each fixture must contain, asserted rather than trusted.

Extraction from converter output is how the fixtures are built, and it is not enough
on its own. Extraction guarantees a fixture was true of *some* build; it says nothing
about which one. The fixtures in this package proved that: ``base.trig`` was extracted
faithfully from converter output stamped ``1.3.0-SNAPSHOT`` that carried none of the
graph layout 1.3 emits, because the output predated the build sitting beside it. The
extraction was honest and the fixture was stale, and nothing failed.

So the shape is pinned here. Two layouts are represented on purpose - ``base.trig``
is pre-1.3 and ``converter-1.3.trig`` is the final 1.3 shape - and each is asserted
to have the markers of its own layout *and to lack the other's*. Regenerating either
one from a converter whose output has moved on breaks a test, which is the point: it
forces a decision instead of quietly redefining what the whole suite is testing
against.

``test_the_version_stamp_cannot_tell_the_layouts_apart`` is the one to read first.
It asserts that the two fixtures share one version string while having different
graph layouts, which is the fact that made every other assertion here necessary.
"""

from __future__ import annotations

import unittest

from support import (
    AUGMENTED,
    BASE,
    CONVERTER_13,
    CORE,
    FLAT,
    requires_pyoxigraph,
)

#: Where a converter records which build produced a graph.
SOFTWARE_VERSION = "https://schema.org/softwareVersion"


def _load(path):
    from pyoxigraph import RdfFormat, Store

    store = Store()
    with path.open("rb") as handle:
        store.bulk_load(handle, RdfFormat.TRIG if path.suffix == ".trig" else RdfFormat.TURTLE)
    return store


def _graph_iris(store) -> list[str]:
    """The named graphs, with the default graph excluded rather than stringified.

    ``flat.ttl`` puts everything in the default graph, which is a ``DefaultGraph``
    and has no IRI at all - so it is skipped by type, not by truthiness.
    """
    from pyoxigraph import NamedNode

    return sorted(
        {
            str(q.graph_name.value)
            for q in store
            if isinstance(q.graph_name, NamedNode)
        }
    )


def _count(store, predicate: str) -> int:
    from pyoxigraph import NamedNode

    return sum(1 for _ in store.quads_for_pattern(None, NamedNode(predicate), None, None))


def _versions(store) -> set[str]:
    from pyoxigraph import NamedNode

    return {
        str(q.object.value)
        for q in store.quads_for_pattern(None, NamedNode(SOFTWARE_VERSION), None, None)
    }


class TestTheExtractedFixtures(unittest.TestCase):
    """``base.trig`` and its derivatives, in the layout the converters emit."""

    def setUp(self):
        requires_pyoxigraph(self)

    def test_base_has_a_model_graph(self):
        """Where arch:Model, its metamodel conformance and its folders live.

        The first 1.3 extraction silently omitted this: the extractor kept the semantic,
        provenance and views graphs and had no clause for the new one, so `core/models` had
        nothing to read against a fixture that otherwise looked current.
        """
        graphs = _graph_iris(_load(BASE))
        self.assertTrue(
            [g for g in graphs if g.endswith("/graph/model")],
            f"no graph/model among {graphs}",
        )

    def test_base_expresses_membership_as_a_direct_edge(self):
        self.assertGreater(_count(_load(BASE), f"{CORE}inModel"), 0)

    def test_base_has_a_semantic_graph(self):
        graphs = _graph_iris(_load(BASE))
        self.assertTrue([g for g in graphs if g.endswith("/graph/semantic")])

    def test_base_is_not_partitioned(self):
        """Every conversion it extracts from has a single input.

        Which is exactly why ``converter-1.3.trig`` has to exist separately: the
        partitioned shape cannot be produced from these sources at all.
        """
        graphs = _graph_iris(_load(BASE))
        self.assertEqual([g for g in graphs if "/graph/semantic/" in g], [])

    def test_augmented_keeps_the_layout_it_was_derived_from(self):
        """The additions are vocabulary, not a change of graph layout."""
        store = _load(AUGMENTED)
        self.assertGreater(_count(store, f"{CORE}inModel"), 0)
        graphs = _graph_iris(store)
        self.assertTrue([g for g in graphs if g.endswith("/graph/model")])
        self.assertTrue([g for g in graphs if g.endswith("/graph/semantic")])

    def test_flat_has_no_named_graphs_at_all(self):
        """The whole point of ``flat.ttl``: graph identity discarded."""
        self.assertEqual(_graph_iris(_load(FLAT)), [])


class TestConverter13Fixture(unittest.TestCase):
    """``converter-1.3.trig`` carries all three markers of the final 1.3 layout."""

    def setUp(self):
        requires_pyoxigraph(self)
        self.store = _load(CONVERTER_13)
        self.graphs = _graph_iris(self.store)

    def test_model_resources_live_in_a_model_graph(self):
        self.assertTrue(
            [g for g in self.graphs if g.endswith("/graph/model")],
            f"no graph/model among {self.graphs}",
        )

    def test_membership_is_a_direct_part_of_model_edge(self):
        self.assertGreater(
            _count(self.store, f"{CORE}inModel"), 0,
            "no arch:inModel, so this is not the 1.3 layout",
        )

    def test_the_semantic_graph_is_partitioned_per_input(self):
        """``graph/semantic/{repo}/{path}``, which needs a multi-input conversion.

        A single-file conversion emits a plain ``graph/semantic`` however current the
        converter is, so a fixture without partitions cannot stand for this shape.
        """
        partitioned = [g for g in self.graphs if "/graph/semantic/" in g]
        self.assertGreaterEqual(
            len(partitioned), 2,
            f"expected at least two semantic partitions, found {partitioned}",
        )

    def test_no_graph_ends_with_the_bare_semantic_suffix(self):
        """The reason a ``STRENDS`` selector reports nothing against a 1.3 dataset.

        Worth asserting on its own, because the symptom in the field was a profile
        warning that no graph matched ``graph/semantic`` while the semantic content
        was plainly present and queryable.
        """
        self.assertEqual(
            [g for g in self.graphs if g.endswith("/graph/semantic")], [],
            "a bare graph/semantic here would make this fixture unable to reproduce "
            "the selector failure it exists to reproduce",
        )

    def test_elements_are_not_double_counted_across_partitions(self):
        """Each element belongs to exactly one partition.

        Splitting the semantic graph per input raises the question immediately: a
        query that unions the partitions must not count an element twice. It cannot
        here, because nothing appears in two of them.
        """
        from pyoxigraph import NamedNode

        rdf_type = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
        element = NamedNode(f"{CORE}Element")
        homes: dict[str, set[str]] = {}
        for graph in (g for g in self.graphs if "/graph/semantic/" in g):
            for quad in self.store.quads_for_pattern(
                None, rdf_type, element, NamedNode(graph)
            ):
                homes.setdefault(str(quad.subject.value), set()).add(graph)

        self.assertTrue(homes, "no arch:Element in any partition")
        shared = {iri: sorted(gs) for iri, gs in homes.items() if len(gs) > 1}
        self.assertEqual(shared, {}, f"element(s) in more than one partition: {shared}")

    def test_it_is_committed_verbatim(self):
        """Every named graph the conversion produced is still here.

        The fixture is deliberately not trimmed, so a reader can take its graph set as
        the converter's actual output rather than a selection of it.
        """
        self.assertEqual(
            len(self.graphs), 4,
            f"expected the conversion's four graphs, found {self.graphs}",
        )
        self.assertEqual(
            len([g for g in self.graphs if g.endswith("/graph/provenance")]), 1,
            "provenance graph missing, so this is not the whole conversion",
        )


class TestVersionStampIsNotAShapeSignal(unittest.TestCase):
    """The finding that made every assertion in this file necessary.

    ``1.3.0-SNAPSHOT`` is a moving label. It was attached to output with no
    no direct membership edge and no ``graph/model``, and to output with both - and it is still
    attached to builds whose provenance IRIs differ. So a stamp cannot tell you what shape
    a graph has, and the fixtures are identified by shape rather than by what they say
    about themselves.

    Both committed fixtures now share a stamp AND a generation, and still differ in a way
    that changes which queries work: one has a partitioned semantic graph and the other
    does not. That is the surviving form of the same hazard.
    """

    def setUp(self):
        requires_pyoxigraph(self)

    def test_both_fixtures_are_stamped(self):
        for path in (BASE, CONVERTER_13):
            with self.subTest(fixture=path.name):
                self.assertTrue(
                    _versions(_load(path)),
                    f"{path.name} records no schema:softwareVersion",
                )

    def test_one_stamp_covers_two_different_shapes(self):
        """So nothing may branch on the version string."""
        shared = _versions(_load(BASE)) & _versions(_load(CONVERTER_13))
        self.assertTrue(
            shared,
            "the fixtures no longer share a stamp; if the converters started emitting a "
            "resolved build identifier that is worth knowing, but do not start trusting "
            "the stamp without checking",
        )

    def test_and_the_shapes_really_do_differ(self):
        """Guards the test above from passing vacuously."""
        base_graphs = set(_graph_iris(_load(BASE)))
        partitioned = set(_graph_iris(_load(CONVERTER_13)))
        self.assertEqual([g for g in base_graphs if "/graph/semantic/" in g], [])
        self.assertTrue([g for g in partitioned if "/graph/semantic/" in g])


class TestRebuildGateRefusesTheWrongShape(unittest.TestCase):
    """``build_fixtures.py --rebuild-13`` checks the shape before overwriting.

    The gate is what keeps the 1.3 fixture from decaying the way ``base.trig`` did.
    It is tested through ``shape_13``, the same function the gate decides with.
    """

    def setUp(self):
        requires_pyoxigraph(self)
        import sys

        from support import ROOT

        sys.path.insert(0, str(ROOT / "fixtures"))

    def test_the_1_3_fixture_passes_the_gate(self):
        from build_fixtures import shape_13

        present, counts = shape_13(CONVERTER_13)
        self.assertTrue(
            all(present.values()),
            f"the committed 1.3 fixture fails its own gate: {present}",
        )
        self.assertGreaterEqual(counts["partitions"], 2)

    def test_an_unpartitioned_conversion_fails_the_gate(self):
        """``base.trig`` is the current layout and still not a substitute.

        It carries two of the three markers - the model graph and the direct membership
        edge - because it is extracted from current converter output. What it cannot have
        is the partitioned semantic graph, since every conversion it comes from has one
        input. So the gate rejects it for exactly one reason, and that reason is the whole
        purpose of the fixture it would be replacing.
        """
        from build_fixtures import MARKERS_13, shape_13

        present, _ = shape_13(BASE)
        self.assertEqual(
            [name for name, ok in present.items() if not ok],
            [MARKERS_13[2]],
            "the gate must reject base.trig on the partitioned semantic graph alone",
        )


if __name__ == "__main__":
    unittest.main()
