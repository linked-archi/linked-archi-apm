"""Current meta/converter semantics, including proposals and audience names."""

import tempfile
import unittest
from pathlib import Path

import support
from linked_archi_connect.adapters import open_adapter
from linked_archi_query import load_catalog, render
from linked_archi_query.questions import load_index, reads
from linked_archi_query.render import UnsupportedTemplate


class TestRelationshipRequirements(unittest.TestCase):
    def test_mapped_walks_are_refused_on_qualified_only_data(self):
        profile = support.load_resolved_profile("linked-archi-qualified")
        for name in ("core/neighbours", "core/dependents"):
            with self.subTest(name=name), self.assertRaises(UnsupportedTemplate) as error:
                render(name, profile, {"FOCUS_IRI": support.BPMN_TASK}, transport="local")
            self.assertIn("direct_rel_triples", str(error.exception))
            self.assertIn("reconvert", str(error.exception).lower())
        # Legacy resource-level readings remain available, with an explicit limitation.
        for name in ("core/neighbours-qualified", "core/dependents-qualified"):
            result = render(name, profile, {"FOCUS_IRI": support.BPMN_TASK}, transport="local")
            self.assertEqual(result.implementation, "template")
            self.assertIn("unconfirmed proposals", load_catalog().get(name).does_not_prove)

    def test_current_bpmn_and_uml_predicates_need_direct_triples(self):
        forms = load_index().unqualified_forms
        for namespace, terms in (
            ("https://meta.linked.archi/bpmn/onto#", (
                "sequenceFlow", "messageFlow", "association", "conversationLink", "dataAssociation")),
            ("https://meta.linked.archi/uml/onto#", (
                "controlFlowsTo", "objectFlowsTo", "informationFlowsTo")),
        ):
            for term in terms:
                for spelling in (f"v:{term}", f"<{namespace}{term}>"):
                    with self.subTest(predicate=spelling):
                        self.assertTrue(reads(f"SELECT * WHERE {{ ?s {spelling} ?o }}",
                                              {"v": namespace}, forms)["direct_rel_triples"])

    def test_mapping_discovery_and_propositions_are_not_traversal(self):
        prefixes = {"c": support.CORE, "otherc": "https://example.org/vocabulary#",
                    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}
        mapping = "?type c:unqualifiedForm ?p ."
        cases = (
            (mapping, False),
            ("?type otherc:unqualifiedForm ?p . ?s ?p ?o .", False),
            (mapping + " ?s ?p ?o .", True),
            (mapping + " FILTER NOT EXISTS { ?s ?p ?o }", False),
            (mapping + " FILTER NOT EXISTS { { ?s ?p ?o } UNION { ?x ?p ?y } }", False),
            (mapping + " ?r rdf:reifies <<( ?s ?p ?o )>> .", False),
            (mapping + ' BIND("?s ?p ?o" AS ?text) # ?s ?p ?o', False),
            (mapping + " FILTER NOT EXISTS { ?x ?p ?y } ?s ?p ?o .", True),
            (f"?type <{support.CORE}unqualifiedForm> $p . $s $p $o .", True),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(reads(text, prefixes, ())["direct_rel_triples"], expected)
        audit = next(q for q in load_index().questions if q.identifier == "core/reifies-audit")
        self.assertEqual(audit.capabilities, {"rdf_reifies": True})


class TestCurrentModelData(unittest.TestCase):
    def setUp(self):
        support.requires_pyoxigraph(self)

    def test_layer_crossing_template_and_question_count_the_same_asserted_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.yaml"
            parent = support.ROOT / "skills/linked-archi-profile/assets/profiles/examples/flattened-turtle.yaml"
            path.write_text(f"extends: {parent}\nprofile: layer-comparison\nversion: 1\n"
                            "description: Layer comparison.\ngraphs:\n  roles:\n    vocabulary: default\n")
            profile = support.load_resolved_profile(str(path))
            adapter = support.load_fixture(*(
                support.FIXTURES / "questions" / file for file in (
                    "archimate3.2-questions-example.ttl", "core-onto.ttl", "archimate3.2-onto.ttl")))
            results = []
            for implementation in ("template", "question"):
                query = render("notation/archimate/layer-crossing", profile, {},
                               implementation=implementation, transport="local")
                rows = adapter.execute(query.query).rows
                self.assertTrue(rows)
                results.append({tuple(sorted(row.items())) for row in rows})
            self.assertEqual(*results)

    def test_notes_and_groups_are_detected_as_views_but_not_model_elements(self):
        from linked_archi_profile.profile import load_profile, verify_against_dataset
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "figures.ttl"
            path.write_text('''
              @prefix x: <https://example.org/la/> .
              @prefix arch: <https://meta.linked.archi/core#> .
              @prefix vis: <https://meta.linked.archi/core-vis#> .
              @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
              x:view a arch:View, arch:Diagram ; skos:prefLabel "A sketch"@en .
              x:group a vis:ContainerNode ; vis:view x:view ; skos:prefLabel "Group"@en .
              x:note a vis:LabelNode ; vis:view x:view ; skos:prefLabel "A note"@en .
            ''')
            adapter = open_adapter(data=[str(path)])
            findings = verify_against_dataset(load_profile("flattened-turtle"), adapter)
            observation = next(f for f in findings if f.subject == "capabilities.views_graph")
            self.assertEqual(observation.message, "partial, observed")
            profile = support.load_resolved_profile("flattened-turtle")
            query = render("core/view-contents", profile, {"VIEW_IRI": "https://example.org/la/view"})
            self.assertEqual(adapter.execute(query.query).rows, [])

    def test_bpmn_fixture_contains_asserted_bridges_and_published_source_links(self):
        adapter = support.load_fixture(support.BASE)
        rows = adapter.execute('''
            PREFIX bpmn: <https://meta.linked.archi/bpmn/onto#>
            PREFIX arch: <https://meta.linked.archi/core#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?r WHERE { GRAPH ?g {
              ?r a bpmn:SequenceFlow ; arch:source ?s ; arch:target ?t ;
                 rdf:reifies <<( ?s bpmn:sequenceFlow ?t )>> .
              ?s bpmn:sequenceFlow ?t ; bpmn:qualifiedSequenceFlow ?r .
            } }
        ''').rows
        self.assertGreaterEqual(len(rows), 3)

    def test_presentation_names_remain_aliases_and_keep_their_audiences(self):
        adapter = open_adapter(data=[str(support.FIXTURES / "questions/labels-per-presentation.ttl")])
        profile = support.load_resolved_profile("flattened-turtle")
        base = "https://meta.linked.archi/examples/labels/"
        query = render("core/resolve-element", profile, {"TERM": "pgw-svc"})
        self.assertEqual({r["element"] for r in adapter.execute(query.query).rows}, {base + "PaymentGateway"})
        query = render("core/context-names", profile, {"FOCUS_IRI": base + "PaymentGateway"})
        rows = adapter.execute(query.query).rows
        self.assertEqual({(r["context"], r["name"], r["language"]) for r in rows}, {
            (base + "DeveloperContext", "pgw-svc", "en"),
            (base + "ExecutiveContext", "Card payments", "en"),
        })
        self.assertEqual({r["canonicalName"] for r in rows}, {"Payment gateway"})
        query = render("core/context-names", profile, {"FOCUS_IRI": base + "Ledger"})
        self.assertEqual(adapter.execute(query.query).rows, [])

    def test_context_name_can_be_in_a_sibling_semantic_partition(self):
        from pyoxigraph import Store, RdfFormat
        store = Store()
        store.load(input='''
          @prefix x: <https://example.org/la/> .
          @prefix arch: <https://meta.linked.archi/core#> .
          @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
          @prefix xl: <http://www.w3.org/2008/05/skos-xl#> .
          <https://example.org/la/m/graph/semantic/a> {
            x:service skos:prefLabel "Service"@en ; xl:altLabel x:name .
          }
          <https://example.org/la/m/graph/semantic/b> {
            x:name xl:literalForm "Service public"@fr ; arch:inPresentationContext x:public .
          }
        ''', format=RdfFormat.TRIG)
        profile = support.load_resolved_profile("linked-archi-default")
        result = render("core/context-names", profile, {"FOCUS_IRI": "https://example.org/la/service"})
        rows = list(store.query(result.query))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["language"].value, "fr")

    def test_unlinked_proposal_is_not_a_template_integrity_violation(self):
        from pyoxigraph import Store, RdfFormat, NamedNode, Quad
        store = Store()
        store.load(input='''
          @prefix x: <https://example.org/la/> .
          @prefix arch: <https://meta.linked.archi/core#> .
          @prefix am: <https://meta.linked.archi/archimate3/onto#> .
          @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
          <https://example.org/la/m/graph/semantic/a> {
            x:proposal a arch:QualifiedRelationship, am:Serving ;
              arch:source x:a ; arch:target x:b ; rdf:reifies <<( x:a am:serves x:b )>> .
          }
        ''', format=RdfFormat.TRIG)
        profile = support.load_resolved_profile("linked-archi-default")
        query = render("core/reifies-audit", profile, {}, implementation="template").query
        self.assertEqual(list(store.query(query)), [])
        n = NamedNode
        graph = n("https://example.org/la/m/graph/semantic/b")
        store.add(Quad(n("https://example.org/la/a"), n("https://meta.linked.archi/archimate3/onto#qualifiedServing"), n("https://example.org/la/proposal"), graph))
        rows = list(store.query(query))
        self.assertEqual([r["finding"].value for r in rows], ["missing-direct-triple"])
        store.add(Quad(n("https://example.org/la/a"), n("https://meta.linked.archi/archimate3/onto#serves"), n("https://example.org/la/b"), graph))
        self.assertEqual(list(store.query(query)), [])


if __name__ == "__main__":
    unittest.main()
