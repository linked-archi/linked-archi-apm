"""The graph layout the converters emit, and the one they used to.

Three things distinguish the current layout, and each one silently empties a query written
for the older shape:

1. ``arch:Model``, its metamodel conformance and its folder tree live in ``graph/model``,
   not in the semantic graph.
2. The semantic graph is partitioned per input as ``graph/semantic/{repo}/{path}`` wherever
   a model has more than one source. A suffix test matches NONE of those graphs.
3. Membership is a direct one-hop ``arch:inModel`` edge.

The bundled profiles describe that layout. The failure this file exists to prevent is the
one observed in the field on a real estate: `verify` reported 0 errors, `core/inventory`
worked, and `core/models` and `core/provenance` returned nothing — because the profile read
model-level facts from the wrong graph. An answer of "no models" that is really "wrong
profile" is worse than an error, because nothing about it looks wrong.

So the assertions come in pairs. The profile fits the current layout, AND a dataset in the
older layout is refused rather than silently answered — and is still *describable* by
overriding three keys, which is the property that keeps this a profile system rather than a
hard-coded assumption.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import support
from support import BASE, CONVERTER_13, requires_pyoxigraph

from linked_archi_profile import load_profile, verify_against_dataset
from linked_archi_profile.profile import (
    ProfileError,
    format_findings,
    observe_dataset,
    recommend_profile,
    worst_severity,
)
from linked_archi_query import load_catalog, render

CORE = support.CORE
#: An element that really carries ``arch:inModel`` in the partitioned fixture.
FOCUS_13 = (
    "https://example.org/la/backstage/usl-api-registry/element/component/default/"
    "order-service"
)

#: A dataset in the OLDER layout: the model declared inside the semantic graph, no
#: ``graph/model``, no direct membership edge. Written here rather than committed as a
#: fixture, because the package no longer ships one and the point is the *contract*, not a
#: sample of anyone's data.
OLDER_LAYOUT = """\
@prefix arch: <https://meta.linked.archi/core#> .
@prefix am:   <https://meta.linked.archi/archimate3/onto#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<https://example.org/la/model/legacy/graph/semantic> {
  <https://example.org/la/model/legacy> a arch:Model ;
      arch:modelConformsToMetamodel <https://meta.linked.archi/archimate3/metamodel#ArchiMate3.2> .
  <https://example.org/la/model/legacy/element/a> a arch:Element, am:ApplicationComponent ;
      skos:prefLabel "Ordering" .
  <https://example.org/la/model/legacy/element/b> a arch:Element, am:ApplicationComponent ;
      skos:prefLabel "Billing" .
}
"""

#: What it takes to describe that dataset: three keys.
OLDER_PROFILE = """\
extends: linked-archi-default.yaml
profile: older-layout
version: 1
description: A dataset from a converter that predates graph/model.
graphs:
  layout: per-model-triple
  named_graphs: true
  roles:
    model: graph/semantic
  descendants: []
navigation:
  model_membership:
    mode: same-graph-colocation
"""


class TestTheProfileFitsTheCurrentLayout(unittest.TestCase):
    def setUp(self):
        requires_pyoxigraph(self)

    def test_no_errors_against_the_extracted_fixture(self):
        findings = verify_against_dataset(
            load_profile("linked-archi-default"), support.load_fixture(BASE)
        )
        self.assertEqual(
            [f for f in findings if f.severity == "error"], [], format_findings(findings)
        )

    def test_no_errors_against_the_partitioned_fixture(self):
        """The same profile, a dataset whose semantic graph is split per input."""
        findings = verify_against_dataset(
            load_profile("linked-archi-default"), support.load_fixture(CONVERTER_13)
        )
        self.assertEqual(
            [f for f in findings if f.severity == "error"], [], format_findings(findings)
        )

    def test_the_model_graph_role_is_required(self):
        profile = load_profile("linked-archi-default")
        self.assertIn("model", profile.graphs.required)
        self.assertIn("semantic", profile.graphs.required)
        self.assertEqual(profile.graphs.roles["model"], "graph/model")

    def test_membership_is_the_direct_predicate(self):
        profile = load_profile("linked-archi-default")
        self.assertEqual(
            profile.navigation["model_membership"]["mode"], "direct-predicate"
        )
        self.assertTrue(profile.has_role("part_of_model"))


class TestTheOlderLayoutIsRefusedAndStillDescribable(unittest.TestCase):
    """Both halves. Either alone would be satisfied by a broken package."""

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            raise unittest.SkipTest("pyoxigraph is not installed")
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls.graph = root / "older.trig"
        cls.graph.write_text(OLDER_LAYOUT, encoding="utf-8")
        cls.profile_path = (
            support.ROOT / "skills/linked-archi-profile/assets/profiles/_older-test.yaml"
        )
        cls.profile_path.write_text(OLDER_PROFILE, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.profile_path.unlink(missing_ok=True)
        cls._tmp.cleanup()

    def _adapter(self):
        from linked_archi_connect.adapters import open_adapter

        return open_adapter(data=[self.graph])

    def test_the_default_profile_refuses_it(self):
        """Loudly, because every model-level query would otherwise return nothing."""
        findings = verify_against_dataset(
            load_profile("linked-archi-default"), self._adapter()
        )
        self.assertEqual(worst_severity(findings), "error", format_findings(findings))
        self.assertTrue(
            any(f.subject == "graphs.roles.model" and f.severity == "error"
                for f in findings),
            format_findings(findings),
        )

    def test_three_overridden_keys_make_it_describable_again(self):
        """The property that keeps this a profile system rather than an assumption."""
        findings = verify_against_dataset(
            load_profile(str(self.profile_path)), self._adapter()
        )
        self.assertEqual(
            [f for f in findings if f.severity == "error"], [], format_findings(findings)
        )

    def test_recommend_says_what_to_override(self):
        recommendation = recommend_profile(observe_dataset(self._adapter()))
        joined = " ".join(recommendation.reasons)
        self.assertIn("graph/model", joined)
        self.assertIn("same-graph-colocation", joined)


class TestDescendantGraphMatching(unittest.TestCase):
    """``graph/semantic`` must reach ``graph/semantic/{repo}/{path}``."""

    def setUp(self):
        requires_pyoxigraph(self)
        self.layout = load_profile("linked-archi-default").graphs

    def test_semantic_is_opted_in(self):
        self.assertEqual(self.layout.descendants, ("semantic",))

    def test_the_selector_matches_the_role_graph_and_its_descendants(self):
        test = self.layout.suffix_test("semantic", "?g")
        self.assertIn('STRENDS(STR(?g), "graph/semantic")', test)
        self.assertIn('CONTAINS(STR(?g), "graph/semantic/")', test)

    def test_a_role_without_the_opt_in_gets_a_suffix_test_only(self):
        self.assertNotIn("CONTAINS", self.layout.suffix_test("provenance", "?g"))

    def test_the_trailing_slash_keeps_it_a_path_test(self):
        """``graph/semantic/`` must not match ``graph/semantic-draft``."""
        self.assertIn('"graph/semantic/"', self.layout.suffix_test("semantic", "?g"))

    def test_both_owners_agree_on_the_selector(self):
        """The profile owner probes with it and the query owner renders with it.

        They share no code, so the expression IS the contract between them. If they
        disagree, `verify` passes and every scoped query still returns nothing.
        """
        from linked_archi_query import ResolvedProfile

        for name in ("linked-archi-default", "linked-archi-merged", "curated-store"):
            profile = load_profile(name)
            resolved = ResolvedProfile(profile.resolved_snapshot())
            for role in profile.graphs.role_names():
                with self.subTest(profile=name, role=role):
                    # Where a role lives is part of the same contract as how it is
                    # matched. A role in the default graph has no suffix to compare, and
                    # the owners disagreeing about WHICH roles those are would put a
                    # `GRAPH` clause around triples that have no graph - returning
                    # nothing, silently, which is the failure this test exists for.
                    self.assertEqual(
                        profile.graphs.is_default_graph(role),
                        resolved.graphs.is_default_graph(role),
                    )
                    if profile.graphs.is_default_graph(role):
                        continue
                    self.assertEqual(
                        profile.graphs.suffix_test(role, "?g"),
                        resolved.graphs.suffix_test(role, "?g"),
                    )

    def test_the_partitioned_fixture_has_no_bare_semantic_graph(self):
        """Otherwise the descendant matching above is untested."""
        from pyoxigraph import NamedNode, RdfFormat, Store

        store = Store()
        with CONVERTER_13.open("rb") as handle:
            store.bulk_load(handle, RdfFormat.TRIG)
        graphs = {str(q.graph_name.value) for q in store
                  if isinstance(q.graph_name, NamedNode)}
        self.assertEqual([g for g in graphs if g.endswith("/graph/semantic")], [])
        self.assertGreaterEqual(len([g for g in graphs if "/graph/semantic/" in g]), 2)


class TestDescendantsIsValidated(unittest.TestCase):
    """A claim that cannot be satisfied is refused at load, not at query time."""

    def _profile(self, graphs: dict):
        from linked_archi_profile.profile import REQUIRED_ROLES, Profile

        return Profile({
            "profile": "t",
            "roles": {r: f"https://example.org/v#{r}" for r in REQUIRED_ROLES},
            "graphs": graphs,
        })

    def test_naming_an_unbound_role_is_refused(self):
        with self.assertRaises(ProfileError) as caught:
            self._profile({"layout": "per-model-triple", "named_graphs": True,
                           "roles": {"semantic": "graph/semantic"},
                           "descendants": ["model"]})
        self.assertIn("not bound", str(caught.exception))

    def test_it_needs_the_suffix_matching_layout(self):
        with self.assertRaises(ProfileError) as caught:
            self._profile({"layout": "explicit", "named_graphs": True,
                           "roles": {"semantic": "https://example.org/g/semantic"},
                           "descendants": ["semantic"]})
        self.assertIn("per-model-triple", str(caught.exception))

    def test_a_string_is_not_a_list(self):
        with self.assertRaises(ProfileError):
            self._profile({"layout": "per-model-triple", "named_graphs": True,
                           "roles": {"semantic": "graph/semantic"},
                           "descendants": "semantic"})

    def test_it_is_not_mistaken_for_a_graph_role(self):
        profile = self._profile({"layout": "per-model-triple", "named_graphs": True,
                                 "roles": {"semantic": "graph/semantic"},
                                 "descendants": ["semantic"]})
        self.assertNotIn("descendants", profile.graphs.roles)
        self.assertNotIn("descendants", profile.graphs.role_names())

    def test_a_flat_layout_must_opt_out_explicitly(self):
        """`examples/flattened-turtle` has to carry `descendants: []`.

        Inheriting the parent's claim is not merely useless there, it is incoherent - no
        graphs to descend - so it is rejected rather than ignored. Asserted because the
        flat profile silently stopped loading when the parent gained the key.
        """
        self.assertEqual(load_profile("flattened-turtle").graphs.descendants, ())


class TestMembershipAsADirectPredicate(unittest.TestCase):
    """The contract: one hop, on every concept."""

    def setUp(self):
        requires_pyoxigraph(self)
        self.catalog = load_catalog()

    def _rendered(self, profile_name: str) -> str:
        profile = support.load_resolved_profile(profile_name)
        return render("core/define-term", profile, {"TERM": "order"},
                      catalog=self.catalog).query

    def test_the_default_profile_renders_the_edge(self):
        self.assertIn(
            f"<{CORE}inModel> ?model", self._rendered("linked-archi-default")
        )

    def test_it_does_not_assert_the_model_class(self):
        """Deliberate, and the reason is the graph layout.

        The membership pattern is injected inside whatever ``GRAPH`` scope the template
        opened - the semantic one. Model resources live in ``graph/model``, so a class test
        would be evaluated in the wrong graph and match nothing. The edge already
        identifies the model.
        """
        membership_line = next(
            line for line in self._rendered("linked-archi-default").splitlines()
            if "inModel" in line
        )
        self.assertNotIn(f"a <{CORE}Model>", membership_line)

    def test_the_folder_walk_still_asserts_it(self):
        """For that mode the class test is the only thing identifying the model."""
        self.assertIn(f"?model a <{CORE}Model>", self._rendered("cloudplatform"))

    def test_every_mode_renders_from_the_same_template(self):
        """The test of whether the directive was the right abstraction."""
        for name in ("linked-archi-default", "cloudplatform", "flattened-turtle"):
            with self.subTest(profile=name):
                self.assertIn("?model", self._rendered(name))

    def test_the_mode_is_refused_without_the_predicate(self):
        """It IS the predicate, so an unbound role would match every model."""
        from linked_archi_profile.profile import REQUIRED_ROLES, Profile

        with self.assertRaises(ProfileError) as caught:
            Profile({
                "profile": "t",
                "roles": {r: f"https://example.org/v#{r}" for r in REQUIRED_ROLES},
                "navigation": {"model_membership": {"mode": "direct-predicate"}},
            })
        self.assertIn("part_of_model", str(caught.exception))

    def test_a_flat_dataset_can_now_express_membership(self):
        """An improvement worth pinning, not an accident.

        Co-location is a statement about named graphs, so on flattened Turtle it could not
        be expressed at all and membership templates were refused. A direct edge needs no
        graphs, so the same question is now answerable there.
        """
        profile = support.load_resolved_profile("flattened-turtle")
        self.assertIsNone(profile.membership_gap())


class TestTheTemplatesTheFieldCouldNotUse(unittest.TestCase):
    """``core/models`` and ``core/provenance``, the two that returned 0 rows."""

    def setUp(self):
        requires_pyoxigraph(self)
        self.catalog = load_catalog()

    def _rows(self, name: str, fixture, params: dict) -> int:
        profile = support.load_resolved_profile("linked-archi-default")
        rendered = render(name, profile, params, catalog=self.catalog)
        return support.load_fixture(fixture).execute(
            rendered.query, template=name, profile_id=profile.name,
            profile_version=profile.profile_version, limit=200,
        ).row_count

    def test_core_models_returns_rows(self):
        self.assertGreaterEqual(self._rows("core/models", BASE, {}), 1)

    def test_core_models_reads_the_partitioned_fixture_too(self):
        self.assertGreaterEqual(self._rows("core/models", CONVERTER_13, {}), 1)

    def test_core_provenance_returns_rows(self):
        self.assertGreaterEqual(
            self._rows("core/provenance", CONVERTER_13, {"FOCUS_IRI": f"<{FOCUS_13}>"}), 1
        )

    def test_core_inventory_still_works(self):
        """It always did - it scopes to graph role ``any`` - so it must not regress."""
        self.assertGreaterEqual(self._rows("core/inventory", BASE, {}), 1)

    def test_the_model_is_not_counted_once_per_partition(self):
        """The question a split semantic graph raises immediately.

        The partitioned fixture has two semantic partitions and one model. A query that
        unions the partitions must still report one model, not one per partition.
        """
        self.assertEqual(self._rows("core/models", CONVERTER_13, {}), 1)


class TestRecommendNamesTheRightProfile(unittest.TestCase):
    def setUp(self):
        requires_pyoxigraph(self)

    def test_the_extracted_fixture_gets_the_default(self):
        recommendation = recommend_profile(observe_dataset(support.load_fixture(BASE)))
        self.assertEqual(recommendation.profile, "linked-archi-default")

    def test_it_reports_the_deciding_observations(self):
        seen = {
            o.subject: o.value
            for o in observe_dataset(support.load_fixture(CONVERTER_13))
        }
        self.assertEqual(seen.get("graph/model"), "1")
        self.assertEqual(seen.get("semantic partitions"), "2")
        self.assertEqual(seen.get("membership"), "arch:inModel")


if __name__ == "__main__":
    unittest.main()
