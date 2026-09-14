"""RDF 1.2 reification: what the bridge gives you, and what it does not.

The single most important test here is
``test_a_triple_term_is_not_an_asserted_triple``. Everything else in this file
follows from it. A triple term ``<<( s p o )>>`` *denotes* a triple; it does not
assert one. So a dataset with 30 triple terms naming ``am:`` predicates still matches
nothing for ``?s am:serves ?o``, and no property path will traverse those edges.

That is why the bridge is a capability of its own rather than a fallback for
``direct_rel_triples``: it answers "which predicate does this relationship stand
for", not "what can I reach from here". Anyone who later assumes otherwise will get
an empty result that looks like a finding, which is the failure this whole package
exists to prevent.
"""

from __future__ import annotations

import glob
import re
import unittest

import support
from support import AUGMENTED

from linked_archi_query import load_catalog, render
from linked_archi_query.render import UnsupportedTemplate, render_literal

load_profile = support.load_resolved_profile

REIFIES = "http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies"
AM = "https://meta.linked.archi/archimate3/onto#"
CORE = support.CORE

#: The templates that need the bridge.
REIFIED_TEMPLATES = (
    "core/reified-predicates",
    "core/neighbours-reified",
    "core/reifies-audit",
)


#: A dataset carrying the bridge and NOTHING ELSE that joins the endpoints.
#:
#: Written here rather than taken from ``augmented.trig``, and the reason matters. That
#: fixture stands for a conversion run with ``--emit-direct-rel-triples``, so it asserts
#: ``am:flowsTo`` for real - and once a predicate is asserted, "a triple term is not an
#: asserted triple" cannot be demonstrated with it. The claim is about RDF semantics, not
#: about that fixture, so it is tested against the one configuration that can show it:
#: bridge present, direct edge absent.
#:
#: Deliberately minimal. Anything else in here would be a second explanation for an empty
#: result, and the assertions below read emptiness as evidence.
BRIDGE_ONLY = f"""\
@prefix arch: <{CORE}> .
@prefix am:   <{AM}> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
<https://example.org/la/bridge/m/graph/semantic> {{
  <https://example.org/la/bridge/m> a arch:Model .
  <https://example.org/la/bridge/m/e/a> a arch:Element ; skos:prefLabel "A" .
  <https://example.org/la/bridge/m/e/b> a arch:Element ; skos:prefLabel "B" .
  <https://example.org/la/bridge/m/r/1> a arch:QualifiedRelationship, am:Flow ;
      arch:source <https://example.org/la/bridge/m/e/a> ;
      arch:target <https://example.org/la/bridge/m/e/b> ;
      rdf:reifies <<( <https://example.org/la/bridge/m/e/a> am:flowsTo
                      <https://example.org/la/bridge/m/e/b> )>> .
}}
"""


class TestTripleTermSemantics(unittest.TestCase):
    """The facts the design rests on, asserted against a bridge-only dataset."""

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            raise unittest.SkipTest("pyoxigraph is not installed")
        import tempfile
        from pathlib import Path

        from linked_archi_connect.adapters import open_adapter

        cls._tmp = tempfile.TemporaryDirectory()
        graph = Path(cls._tmp.name) / "bridge-only.trig"
        graph.write_text(BRIDGE_ONLY, encoding="utf-8")
        cls.adapter = open_adapter(data=[graph])

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_fixture_really_has_triple_terms(self):
        """Otherwise everything below passes vacuously."""
        envelope = self.adapter.execute(
            f"SELECT ?r WHERE {{ GRAPH ?g {{ ?r <{REIFIES}> ?tt }} }}", limit=500
        )
        self.assertGreaterEqual(envelope.row_count, 1)

    def test_a_triple_term_is_not_an_asserted_triple(self):
        """The load-bearing fact. `<<( s p o )>>` denotes; it does not assert.

        The dataset reifies one relationship as ``<<( a am:flowsTo b )>>`` and asserts
        no ``am:flowsTo`` triple. If terms were assertions, this pattern would match.
        It does not.
        """
        asserted = self.adapter.execute(
            f"SELECT ?s ?o WHERE {{ GRAPH ?g {{ ?s <{AM}flowsTo> ?o }} }}", limit=100
        )
        reified = self.adapter.execute(
            f"SELECT ?s ?o WHERE {{ GRAPH ?g {{ "
            f"?r <{REIFIES}> <<( ?s <{AM}flowsTo> ?o )>> }} }}",
            limit=100,
        )
        self.assertGreater(
            reified.row_count, 0, "the fixture should reify am:flowsTo relationships"
        )
        self.assertEqual(
            asserted.row_count, 0,
            "a triple term must not be visible as an asserted triple. If this ever "
            "passes, the reified templates' contract changes and "
            "capabilities.rdf_reifies stops meaning what the profile says it means.",
        )

    def test_property_paths_do_not_traverse_triple_terms(self):
        """Why the bridge cannot stand in for direct_rel_triples.

        core/dependents-direct walks a capped property path. Paths see asserted
        triples only, so a reified-only dataset yields nothing however deep you go.
        """
        for path in (f"<{AM}flowsTo>", f"<{AM}flowsTo>+", f"<{AM}flowsTo>*"):
            with self.subTest(path):
                envelope = self.adapter.execute(
                    f"SELECT ?s ?o WHERE {{ GRAPH ?g {{ ?s {path} ?o }} }}", limit=50
                )
                if path.endswith("*"):
                    # A zero-length path matches every term, so it is not evidence
                    # either way; assert only that it found no am:flowsTo edge.
                    continue
                self.assertEqual(envelope.row_count, 0)

    def test_the_bridge_recovers_what_the_qualified_form_cannot(self):
        """The reason to have it at all.

        The qualified resource carries the relationship's CLASS (am:Flow). The
        unqualified PREDICATE (am:flowsTo) exists only inside the triple term.
        """
        envelope = self.adapter.execute(
            f"SELECT DISTINCT ?p WHERE {{ GRAPH ?g {{ "
            f"?r <{REIFIES}> <<( ?s ?p ?o )>> }} }}",
            limit=200,
        )
        predicates = {row["p"] for row in envelope.rows}
        self.assertIn(f"{AM}flowsTo", predicates)
        # And the class is not among them: classes and predicates are disjoint here.
        self.assertNotIn(f"{AM}Flow", predicates)


class TestGating(unittest.TestCase):
    """Refused wherever the bridge is absent, available where it is present."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_refused_under_the_default_flag_profiles(self):
        """The bridge needs --emit-direct-rel-triples, so default-flag profiles refuse these.

        Every converter emits `rdf:reifies`, but only inside the branch that writes the
        direct triple. A profile describing a default conversion therefore has neither, and
        the templates that read triple terms must be refused rather than returning nothing.
        `linked-archi-direct` is the counterpart and is checked below.
        """
        for profile_name in ("linked-archi-default", "linked-archi-merged"):
            profile = load_profile(profile_name)
            self.assertIsNot(
                profile.capability("rdf_reifies"), True,
                f"{profile_name} describes default flags, so it must not claim rdf_reifies",
            )
            for name in REIFIED_TEMPLATES:
                with self.subTest(f"{profile_name}/{name}"):
                    with self.assertRaises(UnsupportedTemplate):
                        render(name, profile, self._params(name), catalog=self.catalog)

    def test_allowed_where_the_flag_that_emits_the_bridge_was_passed(self):
        """`linked-archi-direct` describes --emit-direct-rel-triples, which emits both."""
        profile = load_profile("linked-archi-direct")
        self.assertIs(
            profile.capability("rdf_reifies"), True,
            "the profile for --emit-direct-rel-triples must claim the bridge that flag emits",
        )
        for name in REIFIED_TEMPLATES:
            with self.subTest(name):
                rendered = render(
                    name, profile, self._params(name), catalog=self.catalog
                )
                self.assertIn("reifies", str(rendered).lower())

    def test_the_refusal_names_the_capability_and_an_alternative(self):
        """A refusal an agent can act on, not a dead end."""
        profile = load_profile("linked-archi-default")
        with self.assertRaises(UnsupportedTemplate) as caught:
            render("core/neighbours-reified", profile,
                   {"FOCUS_IRI": support.BACKSTAGE_COMPONENT}, catalog=self.catalog)
        message = str(caught.exception)
        self.assertIn("rdf_reifies", message)
        self.assertIn("core/neighbours-qualified", message)

    def test_available_under_the_curated_profile(self):
        """Available, and honest about coverage.

        This profile claims `partial` rather than `true`, which is what its own comments
        always described: the bridge covers only the relationship classes whose ontology
        declares an `arch:unqualifiedForm`. `partial` is what keeps these templates
        runnable - a partial capability warns rather than refuses - so what matters here
        is that they still render AND that the caveat travels with them, because a short
        result under a partial bridge may be coverage rather than absence.
        """
        profile = load_profile("curated-store")
        self.assertEqual(profile.capability("rdf_reifies"), "partial")
        for name in REIFIED_TEMPLATES:
            with self.subTest(name):
                rendered = render(name, profile, self._params(name),
                                  catalog=self.catalog)
                self.assertIn("reifies", rendered.query)
                self.assertTrue(
                    any("partial" in warning for warning in rendered.warnings),
                    f"{name} must carry the coverage caveat: {rendered.warnings}",
                )

    @staticmethod
    def _params(name: str) -> dict:
        if name == "core/neighbours-reified":
            return {"FOCUS_IRI": support.BACKSTAGE_COMPONENT}
        return {}


class TestAuditFindsDisagreement(unittest.TestCase):
    """The two branches the shared fixture deliberately cannot cover.

    A bridge whose triple term disagrees with arch:source/arch:target is a
    corruption. Planting one in `augmented.trig` would make every other template's
    results suspect, so it is built here instead, in a store used by nothing else.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            raise unittest.SkipTest("pyoxigraph is not installed")

    def _store(self):
        from pyoxigraph import NamedNode, Quad, Store, Triple

        graph = NamedNode("https://example.org/la/test/m/graph/semantic")
        rdf_type = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
        store = Store()

        def relationship(local, term_source, term_target):
            rel = NamedNode(f"https://example.org/la/test/m/relationship/{local}")
            store.add(Quad(rel, rdf_type,
                           NamedNode(f"{CORE}QualifiedRelationship"), graph))
            store.add(Quad(rel, rdf_type, NamedNode(f"{AM}Flow"), graph))
            store.add(Quad(rel, NamedNode(f"{CORE}source"),
                           NamedNode("https://example.org/la/test/m/element/A"), graph))
            store.add(Quad(rel, NamedNode(f"{CORE}target"),
                           NamedNode("https://example.org/la/test/m/element/B"), graph))
            if term_source is not None:
                store.add(Quad(
                    rel, NamedNode(REIFIES),
                    Triple(NamedNode(term_source), NamedNode(f"{AM}flowsTo"),
                           NamedNode(term_target)),
                    graph,
                ))
            return rel

        base = "https://example.org/la/test/m/element/"
        relationship("sound", f"{base}A", f"{base}B")
        relationship("wrong-subject", f"{base}WRONG", f"{base}B")
        relationship("wrong-object", f"{base}A", f"{base}WRONG")
        relationship("no-term", None, None)
        return store

    def _findings(self):
        profile = load_profile("curated-store")
        rendered = render("core/reifies-audit", profile, {}, catalog=load_catalog())
        rows = list(self._store().query(rendered.query))
        findings: dict[str, set[str]] = {}
        for row in rows:
            finding = str(row["finding"]).strip('"')
            rel = str(row["rel"])[1:-1].rsplit("/", 1)[-1]
            findings.setdefault(finding, set()).add(rel)
        return findings

    def test_each_branch_reports_exactly_the_relationship_it_should(self):
        findings = self._findings()
        self.assertEqual(findings.get("missing-term"), {"no-term"})
        self.assertEqual(findings.get("subject-disagrees"), {"wrong-subject"})
        self.assertEqual(findings.get("object-disagrees"), {"wrong-object"})

    def test_a_sound_bridge_is_not_reported(self):
        """The point of an audit is that clean data produces no rows."""
        for reported in self._findings().values():
            self.assertNotIn("sound", reported)


class TestRegressions(unittest.TestCase):
    """Defects found while building this, kept from coming back."""

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            raise unittest.SkipTest("pyoxigraph is not installed")
        cls.adapter = support.load_fixture(AUGMENTED)

    def test_the_audit_reports_every_unbridged_relationship(self):
        """A FILTER in a group with no triple pattern silently dropped rows.

        `{ FILTER NOT EXISTS { ?rel ... } BIND(...) }` leaves ?rel unbound where the
        FILTER is evaluated, because a FILTER is scoped to its own group's pattern.
        Measured 4 rows where 6 were correct. The fix is the repeated type pattern
        anchoring ?rel inside the branch; this test is why it must stay.
        """
        profile = load_profile("curated-store")
        rendered = render("core/reifies-audit", profile, {}, catalog=load_catalog())
        envelope = self.adapter.execute(rendered.query, limit=500)
        reported = {
            row["rel"] for row in envelope.rows if row["finding"] == "missing-term"
        }

        unbridged = self.adapter.execute(
            f"SELECT ?r WHERE {{ GRAPH ?g {{ "
            f"?r a <{CORE}QualifiedRelationship> ; <{CORE}source> ?s ; "
            f"<{CORE}target> ?t . "
            f"FILTER NOT EXISTS {{ ?r <{REIFIES}> ?tt }} }} }}",
            limit=500,
        )
        expected = {row["r"] for row in unbridged.rows}

        self.assertEqual(
            reported, expected,
            "core/reifies-audit must report every relationship lacking a triple "
            "term. A mismatch here means the FILTER is mis-scoped again.",
        )
        self.assertGreaterEqual(len(expected), 2)

    def test_no_template_uses_the_asserting_reifier_shorthand(self):
        """`<< s p o ~ r >>` asserts the triple. Our data does not.

        The shorthand looks like a tidier spelling of the same thing and is not: it
        requires the triple to be asserted, so it returns nothing against a
        reified-only dataset. Silently. Exactly the class of bug the package exists
        to prevent, so it is banned by test rather than by convention.
        """
        offenders = []
        template_root = support.ROOT / "skills" / "linked-archi-query" / "assets" / "templates"
        for path in sorted(glob.glob(str(template_root / "**" / "*.rq"), recursive=True)):
            from pathlib import Path

            code = "\n".join(
                line for line in Path(path).read_text("utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
            for match in re.finditer(r"<<(?!\()(.*?)>>", code, re.DOTALL):
                if "~" in match.group(1):
                    offenders.append(f"{path}: {match.group(0)[:60]}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_extracted_mapping_is_irregular(self):
        """Guards against anyone "simplifying" the map to a lowercase-first rule.

        It is not derivable. Serving -> serves, Flow -> flowsTo, Composition ->
        composedOf. A lowercase rule yields am:serving and am:flow, which do not
        exist, and the bridge would then name predicates no ontology declares.
        """
        import json

        forms = json.loads(
            (support.FIXTURES / "unqualified-forms.json").read_text("utf-8")
        )["unqualified_forms"]
        self.assertGreaterEqual(len(forms), 50)

        irregular = 0
        for cls, predicate in forms.items():
            local = cls.rsplit("#", 1)[-1]
            naive = local[0].lower() + local[1:]
            if predicate.rsplit("#", 1)[-1] != naive:
                irregular += 1
        self.assertGreater(
            irregular, 10,
            "the mapping should be substantially irregular; if it is not, verify "
            "the extraction actually read the ontologies",
        )

    def test_reifies_is_bound_but_gated_in_the_default_profile(self):
        """Bound because rdf:reifies is fixed RDF vocabulary; gated because absent.

        These are separate statements and both matter. The role says how the bridge
        is spelled; the capability says whether this dataset has one.
        """
        profile = load_profile("linked-archi-default")
        self.assertTrue(profile.has_role("reifies"))
        self.assertEqual(profile.role("reifies"), REIFIES)
        self.assertIs(profile.capability("rdf_reifies"), False)

    def test_the_read_only_checker_accepts_triple_term_syntax(self):
        """`<<(` and `)>>` must not trip the update-keyword or IRI scanners."""
        from linked_archi_query.validate import validate_readonly

        profile = load_profile("curated-store")
        rendered = render_literal(
            "{{PREFIXES}}\nSELECT ?p WHERE { {{GRAPH_OPEN:semantic}} "
            "?r {{ROLE:reifies}} <<( ?s ?p ?o )>> . {{GRAPH_CLOSE}} }",
            profile,
        )
        validate_readonly(rendered.query)  # raises on failure


if __name__ == "__main__":
    unittest.main()
