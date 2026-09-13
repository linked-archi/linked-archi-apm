"""Execute every catalogued template against the committed fixtures.

**The suite fails when a catalogued template has no case**, so the catalogue cannot drift
untested. That single rule is what keeps the template library honest, and it is the reason
`CASES` below has to be edited whenever a template is added.

Expected row counts are **floors**, not assertions about anyone's data. A template that
returns nothing against the fixtures is a fixture gap rather than a count to lower: the
suite cannot tell an empty-by-design template from a broken one.
"""

from __future__ import annotations

import unittest

import support
from support import AUGMENTED, BASE, FLAT, requires_pyoxigraph

from linked_archi_connect.adapters.base import AdapterError
from linked_archi_query import load_catalog, render
from linked_archi_query.render import UnsupportedTemplate

load_profile = support.load_resolved_profile

BPMN_TASK = support.BPMN_TASK
CORE = support.CORE
SKOS = support.SKOS
BPMN = "https://meta.linked.archi/bpmn/onto#"
LEANIX = "https://meta.linked.archi/leanix/onto#"

#: template -> (parameters, minimum rows against fixtures/augmented.trig)
CASES: dict[str, tuple[dict, int]] = {
    "core/inventory": ({"LIMIT": 50}, 8),
    "core/inventory-summary": ({}, 4),
    "core/models": ({}, 5),
    "core/resolve-element": ({"TERM": "order"}, 2),
    # Same term as resolve-element on purpose: the two populations are different, and
    # "order" hits both a BPMN model and several concepts inside it.
    "core/resolve-model": ({"TERM": "order"}, 2),
    # A genuinely ambiguous term in the fixture: a Backstage System and a C4
    # SoftwareSystem both called "Commerce Platform".
    "core/define-term": ({"TERM": "Commerce Platform"}, 5),
    "core/element-detail": ({"FOCUS_IRI": BPMN_TASK}, 4),
    "core/elements-by-type": (
        {"TYPE_IRI": "https://meta.linked.archi/backstage/onto#Component"}, 1),
    "core/discover-relationship-types": ({}, 3),
    "core/discover-predicates": ({}, 10),
    "core/neighbours-qualified": ({"FOCUS_IRI": BPMN_TASK}, 2),
    "core/dependents-qualified": ({"FOCUS_IRI": BPMN_TASK}, 1),
    "core/reified-predicates": ({}, 10),
    # Deliberately NOT BPMN_TASK. The BPMN ontology declares no
    # arch:unqualifiedForm, so BPMN relationships carry no triple term and this
    # focus would return zero - the fixture is honest about that gap.
    "core/neighbours-reified": ({"FOCUS_IRI": support.BACKSTAGE_COMPONENT}, 2),
    "core/reifies-audit": ({}, 4),
    # Every named graph the conversion described. 13 bundles in the fixture, one per
    # graph it wrote, so a floor of 4 is comfortably under what the data holds while
    # still failing if the bundles stop being extracted.
    "core/graph-provenance": ({}, 4),
    # ArchiMate rather than BPMN, because the fixture's direct triples use the predicate
    # `arch:unqualifiedForm` declares and the ontology declares none for
    # bpmn:SequenceFlow. A real conversion CAN have BPMN direct edges - the BPMN type
    # mapping supplies `bpmn:sequenceFlowTo` - but this fixture is built from the
    # ontology's declarations, so it has none. See fixtures/PROVENANCE.md.
    "core/dependents-direct": (
        {"FOCUS_IRI": support.ARCHIMATE_FLOW_SOURCE,
         "PREDICATE_PATH": support.ARCHIMATE_FLOWS_TO}, 1),
    "core/traceability": (
        {"SOURCE_TYPE": "https://meta.linked.archi/bpmn/onto#UserTask",
         "TARGET_TYPE": "https://meta.linked.archi/bpmn/onto#ServiceTask"}, 1),
    "core/classified-by": ({"CONCEPT_IRI": support.TAX_ROOT}, 3),
    "core/lifecycle": ({}, 1),
    "core/provenance": ({"FOCUS_IRI": BPMN_TASK}, 1),
    "core/coverage-gaps": (
        {"RESOURCE_TYPE": f"{CORE}Element",
         "EXPECTED_PREDICATE": f"{CORE}conceptOwner"}, 1),
    "core/orphans": ({}, 1),
    "core/identity-audit": ({}, 2),
    "core/validation-summary": ({}, 1),
    "core/views": ({}, 2),
    "core/view-contents": ({"VIEW_IRI": support.C4_VIEW}, 3),
    # The semantic route to the same three. arch:inView reaches four subjects on this
    # view - the three elements and one relationship drawn between two of them - so a
    # floor of 3 is also the assertion that the relationship is excluded.
    "core/view-contents-semantic": ({"VIEW_IRI": support.C4_VIEW}, 3),
    # Two C4 views of the same model: Containers places 3 elements, Context places 2,
    # and they share one. So the symmetric difference is 2 + 1.
    "core/view-diff": (
        {"VIEW_A_IRI": support.C4_VIEW, "VIEW_B_IRI": support.C4_CONTEXT_VIEW}, 3),
    # "Commerce Platform" is a Backstage System and a C4 SoftwareSystem: two candidates.
    "core/label-collisions": ({}, 2),
    "core/view-usage": ({"FOCUS_IRI": support.C4_CONTAINER}, 1),
    "core/view-usage-semantic": ({"FOCUS_IRI": support.C4_CONTAINER}, 1),
    "notation/archimate/layer-crossing": ({}, 1),
    "notation/bpmn/process-components": ({"MODEL_IRI": support.BPMN_MODEL}, 5),
    "notation/bpmn/process-flow": ({"PROCESS_IRI": support.BPMN_PROCESS}, 3),
    "notation/c4/containers": ({}, 2),
    "notation/backstage/ownership": ({}, 2),
    "notation/leanix/factsheets": ({}, 2),
}


class TestEveryTemplateIsTested(unittest.TestCase):
    def test_no_catalogued_template_lacks_a_case(self):
        catalogued = set(load_catalog().names)
        untested = catalogued - set(CASES)
        self.assertEqual(
            untested, set(),
            "add a case to CASES for: " + ", ".join(sorted(untested)),
        )

    def test_no_case_names_a_template_that_is_gone(self):
        catalogued = set(load_catalog().names)
        stale = set(CASES) - catalogued
        self.assertEqual(stale, set(), f"CASES references missing templates: {stale}")


class TestAgainstAugmentedFixture(unittest.TestCase):
    """The curated profile supports everything, so every template must run."""

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            raise unittest.SkipTest("pyoxigraph is not installed")
        cls.catalog = load_catalog()
        cls.profile = load_profile("curated-store")
        cls.adapter = support.load_fixture(AUGMENTED)

    def test_every_template_returns_at_least_its_floor(self):
        for name, (params, minimum) in sorted(CASES.items()):
            with self.subTest(name):
                rendered = render(name, self.profile, params, catalog=self.catalog)
                envelope = self.adapter.execute(
                    rendered.query, template=name, profile_id=self.profile.name,
                    profile_version=self.profile.profile_version, limit=200,
                )
                self.assertGreaterEqual(
                    envelope.row_count, minimum,
                    f"{name}: {envelope.row_count} rows, expected at least {minimum}. "
                    "A template returning nothing is one the suite cannot tell from "
                    "broken - fix the fixture rather than the floor.",
                )

    def test_qualified_traversal_finds_the_expected_neighbours(self):
        """A concrete assertion about real converter output, not just a count."""
        rendered = render("core/neighbours-qualified", self.profile,
                          {"FOCUS_IRI": BPMN_TASK}, catalog=self.catalog)
        envelope = self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=200,
        )
        directions = {row["direction"] for row in envelope.rows}
        self.assertEqual(directions, {"incoming", "outgoing"})
        for row in envelope.rows:
            self.assertEqual(
                row["relType"], "https://meta.linked.archi/bpmn/onto#SequenceFlow"
            )

    def _traceability(self, source_type, target_type):
        rendered = render("core/traceability", self.profile,
                          {"SOURCE_TYPE": source_type, "TARGET_TYPE": target_type},
                          catalog=self.catalog)
        return self.adapter.execute(
            rendered.query, template="core/traceability", profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=200,
        )

    def test_traceability_follows_the_second_hop_in_both_directions(self):
        """A pair joined through a shared intermediate is connected, not unconnected.

        The two-hop branch once matched source->mid->target only, while the header
        claimed both directions. In this fixture these two types have no direct
        relationship and no forward-forward path: their ONLY connection is one
        IT component that both requires and supports, so `source<-mid->target`. The
        forward-only formulation returned nothing here and that read as "no path
        exists", which is the one answer this template must never get wrong.
        """
        envelope = self._traceability(f"{LEANIX}ITComponent", f"{LEANIX}BusinessCapability")
        self.assertTrue(
            envelope.rows,
            "no path found: the second hop is not being followed in both directions",
        )
        for row in envelope.rows:
            self.assertEqual(row["hops"], "2")
            self.assertEqual(row["direction"], "mid-to-source, mid-to-target")
            self.assertTrue(
                row["relType2"], "a two-hop row must name the second hop's type"
            )

    def test_traceability_names_the_type_of_each_hop(self):
        """Two hops, two relationship types. One column described half the path."""
        envelope = self._traceability(f"{BPMN}UserTask", f"{BPMN}ServiceTask")
        two_hop = [row for row in envelope.rows if row["hops"] == "2"]
        self.assertTrue(two_hop, "the forward-forward path must still be found")
        for row in two_hop:
            self.assertEqual(row["direction"], "source-to-mid, mid-to-target")
            self.assertEqual(row["relType"], f"{BPMN}SequenceFlow")
            self.assertEqual(row["relType2"], f"{BPMN}SequenceFlow")

    def test_coverage_gaps_sees_a_type_outside_the_semantic_graph(self):
        """The count here tells three implementations apart, which is why it is exact.

        Five models in this fixture are typed in `graph/model`; four carry `dct:source`
        in `graph/provenance` and one carries it nowhere. So a semantic-scoped query
        returns 0 and calls that perfect coverage, a query that widens the type search
        but keeps the absence test graph-local returns 5 and calls four recorded
        sources a gap, and only a dataset-wide reading of both returns the 1 real gap.
        """
        rendered = render("core/coverage-gaps", self.profile,
                          {"RESOURCE_TYPE": f"{CORE}Model",
                           "EXPECTED_PREDICATE": "http://purl.org/dc/terms/source"},
                          catalog=self.catalog)
        envelope = self.adapter.execute(
            rendered.query, template="core/coverage-gaps", profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=200,
        )
        self.assertEqual(
            [row["element"] for row in envelope.rows],
            ["https://example.org/la/model/archisurance"],
            "expected exactly the one model with no dct:source anywhere",
        )

    def test_resolve_element_reports_the_graph_it_matched_in(self):
        """The promised graph column has to be the variable the scope binds.

        This projected a hand-spelled ?g while the scope binds ?g_semantic. SPARQL
        projects an unbound variable without complaint, so the template advertised
        "the graph they came from" and returned that column empty on every row.
        """
        rendered = render("core/resolve-element", self.profile,
                          {"TERM": "order"}, catalog=self.catalog)
        envelope = self.adapter.execute(
            rendered.query, template="core/resolve-element", profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=200,
        )
        self.assertIn("g_semantic", envelope.variables)
        self.assertTrue(envelope.rows)
        for row in envelope.rows:
            self.assertTrue(
                row["g_semantic"], f"no graph reported for {row['element']}"
            )

    def test_provenance_names_the_source_and_the_converter(self):
        rendered = render("core/provenance", self.profile,
                          {"FOCUS_IRI": BPMN_TASK}, catalog=self.catalog)
        envelope = self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=50,
        )
        row = envelope.rows[0]
        self.assertEqual(row["source"], "order-fulfillment.bpmn")
        self.assertEqual(row["agentName"], "bpmn2linkedarchi")

    def test_models_reports_provenance_for_every_model_that_has_it(self):
        """A false negative found while writing core/resolve-model.

        Grouping the provenance fields as OPTIONALs inside one GRAPH block dropped the
        ArchiMate model's conversion timestamp, which is in its provenance graph and was
        never reported. Each field now carries its own triple pattern and its own scope.
        A row count could not have caught this: the count was right and a cell was empty.
        """
        rendered = render("core/models", self.profile, {}, catalog=self.catalog)
        envelope = self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=100,
        )
        generated = {
            row["model"]: row["generated"] for row in envelope.rows if row["generated"]
        }
        self.assertIn("https://example.org/la/model/archisurance", generated)
        models = [row["model"] for row in envelope.rows]
        self.assertEqual(
            len(models), len(set(models)) + 1,
            "exactly one model has two conversion timestamps in this fixture; more "
            "repetition than that is row multiplication, not history",
        )

    def _resolve_model(self, term):
        rendered = render("core/resolve-model", self.profile, {"TERM": term},
                          catalog=self.catalog)
        return self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=100,
        )

    def test_resolve_model_returns_models_not_the_concepts_inside_them(self):
        """The boundary against core/resolve-element, as a fact about the rows.

        "order" matches BPMN tasks by label and the BPMN model by title. Only the
        model may come back here, or the two templates have merged.
        """
        envelope = self._resolve_model("order")
        self.assertTrue(envelope.rows)
        for row in envelope.rows:
            self.assertEqual(row["model"], support.BPMN_MODEL, row)

    def test_resolve_model_ranks_an_exact_match_above_a_substring(self):
        exact = self._resolve_model("archisurance")
        self.assertTrue(exact.rows)
        self.assertTrue(all(row["rank"].startswith("1") for row in exact.rows), exact.rows)

        # "order" appears at the start of a title and inside a filename: prefix, never
        # exact, and the title outranks the filename.
        prefixed = self._resolve_model("order")
        self.assertEqual([row["rank"] for row in prefixed.rows],
                         ["2 prefix"] * len(prefixed.rows))
        self.assertEqual(prefixed.rows[0]["matched"], "1 title")

    def _resolve_element(self, term, limit=200):
        rendered = render("core/resolve-element", self.profile,
                          {"TERM": term, "LIMIT": limit}, catalog=self.catalog)
        return self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=limit,
        )

    def _graph_provenance(self, **params):
        rendered = render("core/graph-provenance", self.profile, params,
                          catalog=self.catalog)
        return self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=200,
        )

    def test_graph_provenance_defaults_to_every_graph(self):
        """The default has to stay the unfiltered question, or attaching provenance to
        an answer changes meaning depending on which version is installed."""
        unfiltered = self._graph_provenance()
        self.assertGreater(unfiltered.row_count, 4)
        notations = {row["graph"].split("/la/")[1].split("/")[0]
                     for row in unfiltered.rows}
        self.assertGreater(len(notations), 1, notations)

    def test_graph_provenance_narrows_to_a_notation(self):
        """"Where did this model come from" should not return every other notation too.

        Unfiltered, one downstream dataset answered it with 100 rows of which 97 were
        per-catalog-file partitions of a notation nobody asked about.
        """
        filtered = self._graph_provenance(GRAPH_MATCH="bpmn")
        self.assertTrue(filtered.rows)
        for row in filtered.rows:
            self.assertIn("bpmn", row["graph"])
        self.assertLess(filtered.row_count, self._graph_provenance().row_count)

    def test_graph_provenance_narrows_to_a_graph_role(self):
        """The same parameter reaches a role, which a notation-only filter could not."""
        filtered = self._graph_provenance(GRAPH_MATCH="graph/semantic")
        self.assertTrue(filtered.rows)
        for row in filtered.rows:
            self.assertTrue(row["graph"].endswith("graph/semantic"), row)

    def test_graph_provenance_reports_no_rows_for_a_notation_that_is_absent(self):
        """A filter matching nothing is an empty finding, not every graph."""
        self.assertEqual(self._graph_provenance(GRAPH_MATCH="no-such-notation").row_count, 0)

    def test_resolve_element_ranks_a_name_above_a_native_id(self):
        """The sibling's idiom, which this template did not have.

        It ORDERED BY the role name alone, and those names sorted alphabetically:
        altLabel, nativeId, prefLabel. Names came LAST, so a small LIMIT threw away the
        candidates a human meant and kept the ids. Measured on fixtures/base.trig before
        the fix: TERM="e" at the default LIMIT 25 returned 23 id hits, 2 alias hits and
        none of the 63 available name matches.
        """
        rows = self._resolve_element("order").rows
        self.assertTrue(rows)
        kinds = [row["matched"] for row in rows]
        self.assertIn("1 name", kinds)
        self.assertIn("3 id", kinds)
        self.assertLess(
            kinds.index("1 name"), kinds.index("3 id"),
            "a name match must outrank an id match: " + str(kinds),
        )

    def test_resolve_element_ranks_an_exact_match_first(self):
        """Exactness dominates the kind of match, as it does in core/resolve-model.

        "Order Service" is a whole label in this fixture and a fragment of several
        native ids, so the exact hit has real competition to outrank.
        """
        rows = self._resolve_element("Order Service").rows
        self.assertTrue(rows)
        self.assertEqual(rows[0]["rank"], "1 exact")
        self.assertEqual(rows[0]["matched"], "1 name")
        ranks = [row["rank"] for row in rows]
        self.assertEqual(ranks, sorted(ranks), "rank must be the primary sort key")

    def test_resolve_element_orders_by_rank_then_kind(self):
        """The full key, checked as a sort rather than by naming expected rows."""
        rows = self._resolve_element("e").rows
        self.assertTrue(rows)
        keys = [(row["rank"], row["matched"]) for row in rows]
        self.assertEqual(keys, sorted(keys))

    def test_resolve_element_no_longer_buries_names_under_a_small_limit(self):
        """The defect, as a property of the first page rather than of the whole result.

        "e" is deliberately a term that matches far more native ids than names in this
        fixture, which is exactly the shape that produced a name-free resolution.
        """
        first_page = self._resolve_element("e", limit=25).rows
        self.assertEqual(len(first_page), 25)
        self.assertIn(
            "1 name", {row["matched"] for row in first_page},
            "the first page of a resolution must contain name matches when any exist",
        )

    def test_resolve_model_surfaces_status_on_every_row(self):
        """A model whose conversion did not complete has to be visible before use."""
        for row in self._resolve_model("order").rows:
            self.assertTrue(row["status"], row)

    def test_resolve_model_does_not_multiply_rows_per_provenance_graph(self):
        """The C4 model has a provenance graph with neither title nor status.

        An all-OPTIONAL group inside GRAPH leaves ?model unbound and duplicates every
        row once per provenance graph. Measured at 3x before each projection OPTIONAL
        was given its own triple pattern, so this asserts the fix rather than a style.
        """
        rows = self._resolve_model("order").rows
        keys = [(row["matched"], row["value"]) for row in rows]
        self.assertEqual(len(keys), len(set(keys)), rows)

    def _view_diff(self, direction):
        rendered = render(
            "core/view-diff", self.profile,
            {"VIEW_A_IRI": support.C4_VIEW, "VIEW_B_IRI": support.C4_CONTEXT_VIEW,
             "DIRECTION": direction},
            catalog=self.catalog,
        )
        return self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=100,
        )

    def test_view_diff_is_a_difference_and_never_the_shared_elements(self):
        """Containers places 3, Context places 2, and "Customer" is on both.

        The shared element is the assertion that matters: a diff that leaks it would read
        as "this was added" for something that was always there.
        """
        symmetric = {row["element"] for row in self._view_diff("symmetric").rows}
        shared = "https://example.org/la/c4/commerce-platform/element/1"  # Customer
        self.assertNotIn(shared, symmetric)
        self.assertEqual(len(symmetric), 3)

    def test_view_diff_directions_partition_the_symmetric_difference(self):
        a_only = {row["element"] for row in self._view_diff("a-only").rows}
        b_only = {row["element"] for row in self._view_diff("b-only").rows}
        symmetric = {row["element"] for row in self._view_diff("symmetric").rows}
        self.assertEqual(a_only | b_only, symmetric)
        self.assertEqual(a_only & b_only, set())
        self.assertEqual(len(a_only), 2)
        self.assertEqual(len(b_only), 1)

    def test_view_diff_labels_each_side(self):
        for row in self._view_diff("a-only").rows:
            self.assertEqual(row["side"], "a-only")
            self.assertTrue(row["label"], row)
            self.assertTrue(row["types"], "GROUP_CONCAT over IRIs needs STR()")

    def test_label_collisions_finds_the_cross_notation_pair(self):
        rendered = render("core/label-collisions", self.profile, {}, catalog=self.catalog)
        envelope = self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=100,
        )
        by_label: dict[str, set[str]] = {}
        for row in envelope.rows:
            by_label.setdefault(row["normalised"], set()).add(row["model"])
        self.assertIn("commerce platform", by_label)
        self.assertEqual(len(by_label["commerce platform"]), 2, "two models, not one")
        for row in envelope.rows:
            self.assertEqual(row["models"], str(len(by_label[row["normalised"]])))
            self.assertTrue(row["type"], "the notation type is what tells the sides apart")

    def test_label_collisions_carries_its_caveat_into_the_result(self):
        """The caveat has to travel with the rows, not sit in the documentation.

        A table of label matches read as identity assertions is the exact mistake every
        other part of this package refuses to make.
        """
        rendered = render("core/label-collisions", self.profile, {}, catalog=self.catalog)
        self.assertTrue(rendered.warnings)
        first = rendered.warnings[0]
        self.assertIn("CANDIDATES", first)
        self.assertIn("not identity assertions", first)

    def test_only_a_template_that_asks_for_a_caveat_gets_one(self):
        """Opt-in: a caveat on all 35 templates would train a reader to skip the line."""
        plain = render("core/models", self.profile, {}, catalog=self.catalog)
        self.assertNotIn("CANDIDATES", " ".join(plain.warnings))

    def _define_term(self, term):
        rendered = render("core/define-term", self.profile, {"TERM": term},
                          catalog=self.catalog)
        return self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=100,
        )

    def test_define_term_counts_the_candidates_so_ambiguity_is_visible(self):
        """Two resources really are called "Commerce Platform" here, in two notations.

        The count has to be on the rows. An agent that cannot see the term was
        ambiguous will describe the first row as the answer.
        """
        ambiguous = self._define_term("Commerce Platform")
        self.assertTrue(ambiguous.rows)
        self.assertEqual({row["candidates"] for row in ambiguous.rows}, {"2"})
        self.assertEqual(len({row["resource"] for row in ambiguous.rows}), 2)

        unambiguous = self._define_term("Ship Order")
        self.assertEqual({row["candidates"] for row in unambiguous.rows}, {"1"})

    def test_define_term_matches_definition_text_not_only_labels(self):
        """"A shopper." is the definition of an element labelled "Customer"."""
        rows = self._define_term("shopper").rows
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["label"], "Customer")
            self.assertEqual(row["definition"], "A shopper.")

    def test_define_term_names_the_owning_model_and_its_source(self):
        """Membership through the profile directive, plus the model's own provenance."""
        for row in self._define_term("Ship Order").rows:
            self.assertEqual(row["model"], support.BPMN_MODEL, row)
            self.assertEqual(row["source"], "order-fulfillment.bpmn", row)

    def test_define_term_reports_the_notation_type_not_the_structural_one(self):
        for row in self._define_term("Ship Order").rows:
            self.assertEqual(row["type"], "https://meta.linked.archi/bpmn/onto#ServiceTask")
            self.assertEqual(row["relType"],
                             "https://meta.linked.archi/bpmn/onto#SequenceFlow")

    def test_define_term_gives_both_directions_one_hop_out(self):
        rows = self._define_term("Ship Order").rows
        self.assertEqual({row["direction"] for row in rows}, {"incoming", "outgoing"})
        self.assertEqual({row["relatedLabel"] for row in rows},
                         {"Process Payment", "Order Complete"})

    def test_identity_audit_resolves_labels_on_both_sides(self):
        """Both elements come from different models, so different semantic graphs."""
        rendered = render("core/identity-audit", self.profile, {}, catalog=self.catalog)
        envelope = self.adapter.execute(
            rendered.query, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=50,
        )
        self.assertTrue(envelope.rows)
        for row in envelope.rows:
            self.assertTrue(row["elementLabel"], row)
            self.assertTrue(row["counterpartLabel"], row)
            self.assertIn("exactMatch", row["kind"])


class TestAgainstBaseFixture(unittest.TestCase):
    """Default converter output: the gated templates must be refused, not empty."""

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            raise unittest.SkipTest("pyoxigraph is not installed")
        cls.catalog = load_catalog()
        cls.profile = load_profile("linked-archi-default")
        cls.adapter = support.load_fixture(BASE)

    GATED = {
        "core/dependents-direct", "core/identity-audit", "core/validation-summary",
        # The RDF 1.2 bridge. Refused here for two reasons at once: no converter
        # emits it, and the `<<( s p o )>>` syntax is a parse error on SPARQL 1.1.
        "core/reified-predicates", "core/neighbours-reified", "core/reifies-audit",
    }

    def test_gated_templates_are_refused(self):
        for name in sorted(self.GATED):
            with self.subTest(name):
                with self.assertRaises(UnsupportedTemplate):
                    render(name, self.profile, CASES[name][0], catalog=self.catalog)

    def test_everything_else_runs(self):
        for name, (params, _) in sorted(CASES.items()):
            if name in self.GATED:
                continue
            with self.subTest(name):
                rendered = render(name, self.profile, params, catalog=self.catalog)
                self.adapter.execute(
                    rendered.query, template=name, profile_id=self.profile.name,
                    profile_version=self.profile.profile_version, limit=200,
                )

    def test_the_graph_scoping_defect_is_measurable(self):
        """The defect this package exists to remove, as a number.

        Identical patterns: unscoped matches the default graph, which converter TriG
        leaves empty. Scoped through the profile, it finds the data.
        """
        from linked_archi_query.render import render_literal

        unscoped = render_literal(
            "{{PREFIXES}}\nSELECT ?r WHERE { ?r a {{ROLE:relationship_class}} }",
            self.profile,
        )
        scoped = render_literal(
            "{{PREFIXES}}\nSELECT ?r WHERE { {{GRAPH_OPEN:semantic}} "
            "?r a {{ROLE:relationship_class}} . {{GRAPH_CLOSE}} }",
            self.profile,
        )
        empty = self.adapter.execute(unscoped.query, profile_id=self.profile.name)
        found = self.adapter.execute(scoped.query, profile_id=self.profile.name)
        self.assertEqual(empty.row_count, 0)
        self.assertGreater(found.row_count, 0)

    def test_direct_triples_are_absent_from_default_output(self):
        """The behavioural fact the qualified-first default rests on."""
        from linked_archi_query.render import render_literal

        probe = render_literal(
            "{{PREFIXES}}\nASK { {{GRAPH_OPEN:semantic}} "
            "?r a {{ROLE:relationship_class}} ; {{ROLE:rel_source}} ?s ; "
            "{{ROLE:rel_target}} ?t . ?s ?direct ?t . "
            "FILTER(?direct != {{ROLE:rel_source}} && ?direct != {{ROLE:rel_target}}) "
            "{{GRAPH_CLOSE}} }",
            self.profile,
        )
        self.assertFalse(self.adapter.ask(probe.query))


class TestAgainstFlatFixture(unittest.TestCase):
    """Flattened Turtle: the same templates, no GRAPH clause, with caveats."""

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            raise unittest.SkipTest("pyoxigraph is not installed")
        cls.catalog = load_catalog()
        cls.profile = load_profile("flattened-turtle")
        cls.adapter = support.load_fixture(FLAT)

    def test_scoped_templates_run_unscoped_with_a_caveat(self):
        rendered = render("core/neighbours-qualified", self.profile,
                          {"FOCUS_IRI": BPMN_TASK}, catalog=self.catalog)
        self.assertNotIn("GRAPH ?g", rendered.query)
        self.assertTrue(rendered.warnings)
        raw = self.adapter.execute(rendered.query)
        self.assertGreaterEqual(raw.row_count, 2)
        self.assertTrue(rendered.warnings)

    def test_no_named_graphs_present(self):
        self.assertFalse(self.adapter.named_graphs_present)


if __name__ == "__main__":
    unittest.main()


class TestViewContents(unittest.TestCase):
    """The inverse of core/view-usage, and the aggregate that silently failed once.

    A row-count floor cannot catch a column that arrives empty, and that is exactly what
    happened here: GROUP_CONCAT over IRIs is a type error, an erroring aggregate yields
    unbound rather than failing, so every row looked right with no types in it. These
    tests assert on the content, not the count.
    """

    @classmethod
    def setUpClass(cls):
        support.requires_pyoxigraph(cls)
        cls.profile = support.load_resolved_profile("curated-store")
        cls.catalog = load_catalog()
        cls.adapter = support.load_fixture(AUGMENTED)

    def _rows(self, name: str, params: dict) -> list[dict]:
        rendered = render(name, self.profile, params, catalog=self.catalog)
        return list(self.adapter.execute(rendered.query).rows or [])

    def test_it_names_the_elements_the_view_places(self):
        rows = self._rows("core/view-contents", {"VIEW_IRI": support.C4_VIEW})
        labels = {row["label"] for row in rows}
        self.assertEqual(labels, {"Customer", "Inventory Service", "Orders DB"})

    def test_every_element_reports_its_types(self):
        rows = self._rows("core/view-contents", {"VIEW_IRI": support.C4_VIEW})
        for row in rows:
            with self.subTest(row["element"]):
                self.assertTrue(
                    row["types"],
                    "types came back empty - GROUP_CONCAT needs STR() over IRIs",
                )
                self.assertIn("meta.linked.archi", row["types"])

    def test_the_notation_and_core_classes_both_appear(self):
        # Multi-typing is a fact about converter output, and collapsing it to one row
        # per element is the reason this template concatenates rather than joins.
        rows = self._rows("core/view-contents", {"VIEW_IRI": support.C4_VIEW})
        service = next(row for row in rows if row["label"] == "Inventory Service")
        self.assertIn("c4/onto#Container", service["types"])
        self.assertIn("core#Element", service["types"])

    def test_one_row_per_element_despite_several_types(self):
        rows = self._rows("core/view-contents", {"VIEW_IRI": support.C4_VIEW})
        self.assertEqual(len(rows), len({row["element"] for row in rows}))

    def test_it_is_the_exact_inverse_of_view_usage(self):
        """Each element on the view must report the view, and vice versa."""
        contents = self._rows("core/view-contents", {"VIEW_IRI": support.C4_VIEW})
        for row in contents:
            with self.subTest(row["element"]):
                usage = self._rows("core/view-usage", {"FOCUS_IRI": row["element"]})
                self.assertIn(support.C4_VIEW, {seen["view"] for seen in usage})

    def test_an_unknown_view_returns_nothing_rather_than_everything(self):
        rows = self._rows(
            "core/view-contents",
            {"VIEW_IRI": "https://example.org/la/c4/commerce-platform/view/DoesNotExist"},
        )
        self.assertEqual(rows, [])


class TestTheTwoViewRoutesAgree(unittest.TestCase):
    """Converter output states view membership twice, and the two must not disagree.

    ``archvis:archElement`` on a node in the views graph is the precise route: it carries
    geometry and tells two drawings of one element apart. ``arch:inView`` on the concept in
    the semantic graph is the coarse one, and the only one that survives a publication made
    with ``--views-profile no-views``. Both are emitted since core 0.4.0.

    Agreement is what makes them interchangeable for the question a reader actually asks,
    so it is asserted rather than assumed. Two ways they could silently drift:

    ``arch:inView`` has domain ``arch:ModelConcept``, so a qualified relationship drawn on a
    view carries it too - this fixture has three elements and one relationship pointing at
    ``C4_VIEW``. The archvis route never sees that relationship, because it reaches elements
    through ``archvis:archElement`` while a relationship is reached through
    ``archvis:archRelationship``. Without the ``element_class`` narrowing in the semantic
    template it would return four rows against the other's three, and the extra row would
    look like an element.

    And a converter could stop emitting one route without any existing test noticing, since
    every other view test exercises exactly one of them.
    """

    @classmethod
    def setUpClass(cls):
        support.requires_pyoxigraph(cls)
        cls.profile = support.load_resolved_profile("curated-store")
        cls.catalog = load_catalog()
        cls.adapter = support.load_fixture(AUGMENTED)

    def _rows(self, name: str, params: dict) -> list[dict]:
        rendered = render(name, self.profile, params, catalog=self.catalog)
        return list(self.adapter.execute(rendered.query).rows or [])

    def _elements(self, name: str, view: str) -> set:
        return {row["element"] for row in self._rows(name, {"VIEW_IRI": view})}

    def test_both_routes_name_the_same_elements(self):
        for view in (support.C4_VIEW, support.C4_CONTEXT_VIEW):
            with self.subTest(view):
                self.assertEqual(
                    self._elements("core/view-contents", view),
                    self._elements("core/view-contents-semantic", view),
                    "the visual and semantic routes disagree about what this view places",
                )

    def test_the_semantic_route_excludes_relationships_drawn_on_the_view(self):
        """The narrowing that keeps the two routes comparable.

        Asserted on its own because the equality above would also pass if both routes
        broke in the same direction.
        """
        elements = self._elements("core/view-contents-semantic", support.C4_VIEW)
        self.assertTrue(elements, "fixture no longer places anything on this view")
        for iri in elements:
            with self.subTest(iri):
                self.assertNotIn(
                    "/relationship/", iri,
                    "a qualified relationship carries arch:inView too and must not be "
                    "reported as an element - see element_class in the template",
                )

    def test_both_routes_agree_on_which_views_show_an_element(self):
        def views(name):
            return {row["view"] for row in self._rows(
                name, {"FOCUS_IRI": support.C4_CONTAINER})}

        self.assertEqual(views("core/view-usage"), views("core/view-usage-semantic"))

    def test_the_semantic_pair_are_inverses_of_each_other(self):
        for row in self._rows("core/view-contents-semantic", {"VIEW_IRI": support.C4_VIEW}):
            with self.subTest(row["element"]):
                seen = {r["view"] for r in self._rows(
                    "core/view-usage-semantic", {"FOCUS_IRI": row["element"]})}
                self.assertIn(support.C4_VIEW, seen)

    def test_the_semantic_route_needs_no_views_graph(self):
        """The whole reason it exists: it must not depend on what a profile may drop.

        `core/view-contents` declares graph role `views` and capability `views_graph`.
        Its sibling declares neither, which is what lets it answer for a dataset published
        without geometry.
        """
        visual = self.catalog.get("core/view-contents").requires
        semantic = self.catalog.get("core/view-contents-semantic").requires
        self.assertIn("views", visual.graph_roles)
        self.assertNotIn("views", semantic.graph_roles)
        self.assertIn("views_graph", visual.capabilities)
        self.assertEqual(dict(semantic.capabilities), {})

    def test_each_route_points_at_the_other(self):
        """A reader refused one must be told where else to look."""
        pairs = [
            ("core/view-contents", "core/view-contents-semantic"),
            ("core/view-usage", "core/view-usage-semantic"),
        ]
        for visual, semantic in pairs:
            with self.subTest(f"{visual} <-> {semantic}"):
                self.assertIn(semantic, self.catalog.get(visual).alternatives)
                self.assertIn(visual, self.catalog.get(semantic).alternatives)


class TestOrientationAgainstThe13Fixture(unittest.TestCase):
    """The orientation templates must not return zero rows on a PARTITIONED dataset.

    Every case in ``CASES`` runs against ``augmented.trig``, whose semantic graph is not
    partitioned - every conversion it is extracted from has a single input. So
    ``converter-1.3.trig`` was committed and verified as a PROFILE fixture and no template
    was ever executed against it, which is how ``core/inventory-summary`` came to return
    zero rows on a partitioned dataset without any test noticing. It declared the model
    inside the semantic graph and counted concepts by co-location; the model now lives in
    ``graph/model`` and the semantic graph is split per input, so nothing matched.

    Zero rows is the specific failure worth pinning here rather than a rich assertion:
    an empty result from an orientation template reads as "the dataset is empty", and
    these are the templates whose whole job is to tell that apart from "nothing matched".
    """

    #: Orientation only. A template that is genuinely empty-by-design on this fixture
    #: does not belong here - the point is templates that MUST see something.
    MUST_NOT_BE_EMPTY = {
        "core/inventory-summary": {},
        "core/inventory": {"LIMIT": 50},
        "core/models": {},
        "core/discover-predicates": {},
    }

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            raise unittest.SkipTest("pyoxigraph is not installed")
        cls.catalog = load_catalog()
        cls.profile = load_profile("linked-archi-default")
        cls.adapter = support.load_fixture(support.CONVERTER_13)

    def _rows(self, name, params):
        rendered = render(name, self.profile, params, catalog=self.catalog)
        return self.adapter.execute(
            rendered.query, template=name, profile_id=self.profile.name,
            profile_version=self.profile.profile_version, limit=200,
        ).rows

    def test_orientation_templates_see_the_dataset(self):
        for name, params in sorted(self.MUST_NOT_BE_EMPTY.items()):
            with self.subTest(name):
                self.assertTrue(
                    self._rows(name, params),
                    f"{name} returned no rows against the 1.3 fixture. On this layout "
                    "that reads as an empty dataset, which is the failure the "
                    "orientation templates exist to prevent.",
                )

    def test_inventory_summary_counts_concepts_through_part_of_model(self):
        """Not just non-empty: the concepts have to actually be joined to the model.

        A query that binds the model but drops the concept join still returns a row,
        with 0 concepts - indistinguishable from a notation that arrived with none.
        """
        rows = self._rows("core/inventory-summary", {})
        self.assertTrue(
            any(int(row["concepts"]) > 0 for row in rows),
            f"every notation reported 0 concepts: {rows}",
        )

    def test_inventory_summary_sees_the_partitioned_semantic_graphs(self):
        """The 1.3 shape a suffix selector cannot reach.

        This fixture partitions one model's semantic graph across two inputs, so a
        template that only matched ``graph/semantic`` exactly would report one graph.
        """
        rows = self._rows("core/inventory-summary", {})
        self.assertTrue(
            any(int(row["graphs"]) > 1 for row in rows),
            f"no notation reported more than one semantic graph: {rows}",
        )
