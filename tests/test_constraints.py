"""Reading which relationship may connect which types, out of published SHACL.

The table this produces is what lets a check say "that path is not possible" instead of
returning nothing and leaving an empty result to be read as absence. Two published forms
feed it, and the ones that matter most are the ones RDFS cannot express: the direct
predicates - `am:flowsTo`, `bs:ownedBy` - carry no domain and no range anywhere in the
ontologies, so shapes are the only statement of their validity.
"""

from __future__ import annotations

import unittest

import support
from support import requires_pyoxigraph

from linked_archi_query.constraints import (
    Legs,
    read_constraints,
    read_unqualified_forms,
)

CORE = "https://meta.linked.archi/core#"
AM = "https://meta.linked.archi/archimate3/onto#"
BS = "https://meta.linked.archi/backstage/onto#"

LEGS = Legs(f"{CORE}source", f"{CORE}target")


def _runner(*paths):
    """Run SPARQL against the fixtures, returning rows of lexical values.

    Deliberately not the adapter: the reader takes a callable so it can be exercised
    without transport, and this is that callable at its smallest.
    """
    from pyoxigraph import RdfFormat, Store

    store = Store()
    for path in paths:
        # TriG for the converter fixtures, Turtle for the published ones. The published
        # schema is Turtle precisely because that is what the publisher serves.
        fmt = RdfFormat.TRIG if str(path).endswith(".trig") else RdfFormat.TURTLE
        store.load(path=str(path), format=fmt)

    def run(query: str):
        result = store.query(query)
        names = [str(variable.value) for variable in result.variables]
        return [
            {name: solution[name].value for name in names if solution[name] is not None}
            for solution in result
        ]

    return run


class TestPublishedConstraints(unittest.TestCase):
    """What ArchiMate states directly, one `sh:property` per direct predicate."""

    @classmethod
    def setUpClass(cls):
        requires_pyoxigraph(cls)
        cls.sparql = staticmethod(_runner(support.SHAPES, support.VOCABULARY))
        cls.constraints = read_constraints(cls.sparql, LEGS, f"{CORE}unqualifiedForm")

    def test_the_direct_predicates_of_a_source_class_are_read(self):
        predicates = {
            predicate for source, predicate in self.constraints.allowed
            if source == f"{AM}BusinessRole"
        }
        self.assertEqual(len(predicates), 11, sorted(predicates))
        self.assertIn(f"{AM}flowsTo", predicates)

    def test_a_published_target_list_is_read_in_full(self):
        targets = self.constraints.targets(f"{AM}BusinessRole", f"{AM}flowsTo")
        self.assertIn(f"{AM}BusinessActor", targets)
        self.assertEqual(len(targets), 35)

    def test_the_qualified_form_is_read_including_single_target_conjunctions(self):
        """365, not 361.

        The four extra are the junction rules - Junction_And and Junction_Or to
        `arch:ModelConcept` and back - which have exactly one permitted target each and are
        therefore written as a bare `sh:class` rather than a one-element `sh:or`. A reader
        that walks only `sh:or` misses them, which is what the shape's own header comment
        did until it was fixed upstream, and what an earlier version of this package
        repeated as a confirmed figure.
        """
        pairs = self.constraints.qualified[f"{AM}Aggregation"]
        self.assertEqual(len(pairs), 365)
        junction = (f"{AM}Junction_And", f"{CORE}ModelConcept")
        self.assertIn(junction, pairs, "the bare sh:class conjunctions must be read")

    def test_the_qualified_legs_are_not_mistaken_for_direct_predicates(self):
        """A qualified shape hangs its ends off `sh:property` too.

        Without excluding them the table gains `(bs:Ownership, arch:source) -> Element`,
        which would tell a checker that `arch:source` is a relationship between element
        types and that a query traversing it should be judged against element classes.
        """
        legs = {
            (source, predicate) for source, predicate in self.constraints.allowed
            if predicate in (LEGS.source, LEGS.target)
        }
        self.assertEqual(legs, set())

    def test_the_leg_predicates_come_from_the_profile_not_from_a_name(self):
        """Proven by asking with the wrong ones and getting nothing.

        An earlier draft filtered on `STRENDS(STR(?path), "source")`, which reads the same
        for any vocabulary that happens to end in that word and silently misses one that
        does not. If this test ever passes with a non-empty result, the reader has gone
        back to guessing.
        """
        elsewhere = read_constraints(
            self.sparql, Legs("urn:example:from", "urn:example:to"), f"{CORE}unqualifiedForm"
        )
        self.assertEqual(elsewhere.qualified, {})


class TestDerivedConstraints(unittest.TestCase):
    """Every notation except ArchiMate constrains only the qualified form.

    So the rule for a direct predicate has to be derived: follow `arch:unqualifiedForm`
    from the relationship class to its predicate, and reuse the qualified shape's classes.
    """

    @classmethod
    def setUpClass(cls):
        requires_pyoxigraph(cls)
        cls.sparql = staticmethod(_runner(support.SHAPES, support.VOCABULARY))
        cls.constraints = read_constraints(cls.sparql, LEGS, f"{CORE}unqualifiedForm")

    def test_the_mapping_is_present_in_the_fixture(self):
        """It was not, and the derivation had nothing to walk.

        `arch:unqualifiedForm` is ontology content that no conversion emits, so a fixture
        without it leaves the only code path that constrains a non-ArchiMate direct triple
        untested.
        """
        forms = read_unqualified_forms(self.sparql, f"{CORE}unqualifiedForm")
        self.assertEqual(len(forms), 75)
        self.assertEqual(forms[f"{BS}Ownership"], f"{BS}ownedBy")

    def test_a_direct_predicate_with_no_published_shape_is_still_constrained(self):
        targets = self.constraints.targets(f"{CORE}Element", f"{BS}ownedBy")
        self.assertEqual(targets, frozenset({f"{BS}Group", f"{BS}User"}))
        self.assertIn(f"{BS}ownedBy", self.constraints.derived)

    def test_derivation_does_not_overwrite_what_is_published(self):
        """Where ArchiMate states the direct form itself, that is the answer."""
        published = self.constraints.targets(f"{AM}BusinessRole", f"{AM}aggregates")
        self.assertEqual(
            published,
            frozenset({f"{AM}BusinessRole", f"{AM}BusinessInterface", f"{AM}Grouping"}),
        )

    def test_derivation_reaches_source_classes_the_published_slice_omits(self):
        """The fixture carries one unqualified shape and one qualified shape of 73 and 11.

        So a source class outside that one shape is constrained only by derivation, which
        is also what happens in an estate that attaches the qualified shapes alone.
        """
        derived = self.constraints.targets(f"{AM}ApplicationComponent", f"{AM}aggregates")
        self.assertTrue(derived)


class TestUncheckedIsNotTheSameAsForbidden(unittest.TestCase):
    """The distinction the whole feature rests on.

    `None` means no constraint was published or none was attached. An empty set would mean
    the metamodel permits nothing here. Conflating them turns "we do not know" into "your
    query is wrong", which is the same error as reading an empty result as absence - just
    pointed the other way.
    """

    @classmethod
    def setUpClass(cls):
        requires_pyoxigraph(cls)
        cls.constraints = read_constraints(
            _runner(support.SHAPES, support.VOCABULARY), LEGS, f"{CORE}unqualifiedForm"
        )

    def test_an_unconstrained_pair_answers_none(self):
        self.assertIsNone(self.constraints.targets("urn:example:Thing", "urn:example:rel"))

    def test_coverage_names_the_namespaces_that_were_read(self):
        self.assertIn(AM, self.constraints.covered)
        self.assertIn(BS, self.constraints.covered)

    def test_a_predicate_outside_coverage_is_reported_as_unconstrained(self):
        self.assertFalse(self.constraints.constrains("https://example.org/onto#relatesTo"))

    def test_nothing_attached_is_falsy_rather_than_an_empty_verdict(self):
        """A caller must be able to tell "no shapes" from "shapes permitting nothing"."""
        empty = read_constraints(_runner(support.BASE), LEGS)
        self.assertFalse(empty)
        self.assertEqual(empty.covered, frozenset())


class TestAnUnreadableConstraintSetIsRefused(unittest.TestCase):
    """Refusing beats an empty table, because an empty table looks like a clean bill.

    This is the same argument the package makes about empty query results, applied to its
    own machinery: a check that could not read its inputs and says nothing is
    indistinguishable from a check that read them and found no problem.
    """

    @classmethod
    def setUpClass(cls):
        requires_pyoxigraph(cls)
        from linked_archi_profile.profile import load_profile

        cls.snapshot = load_profile("curated-store").resolved_snapshot()
        cls.sparql = staticmethod(_runner(support.SHAPES, support.VOCABULARY))

    def _profile(self, without: str | None = None):
        import copy

        from linked_archi_query import ResolvedProfile

        snapshot = copy.deepcopy(self.snapshot)
        if without:
            snapshot["roles"].pop(without, None)
        return ResolvedProfile(snapshot)

    def test_a_bound_profile_reads_the_table(self):
        from linked_archi_query.constraints import constraints_from_profile

        constraints = constraints_from_profile(self.sparql, self._profile())
        self.assertTrue(constraints.allowed)
        self.assertIn(f"{BS}ownedBy", constraints.derived)

    def test_an_unbound_unqualified_form_refuses_and_says_what_is_lost(self):
        from linked_archi_query.constraints import ConstraintError, constraints_from_profile

        with self.assertRaises(ConstraintError) as caught:
            constraints_from_profile(self.sparql, self._profile(without="unqualified_form"))
        message = str(caught.exception)
        self.assertIn("unqualified_form", message)
        self.assertIn("except ArchiMate", message, "the consequence has to be named")

    def test_the_relationship_legs_are_guaranteed_by_the_contract(self):
        """So `constraints.py` does not guard them, and this pins that assumption.

        If `rel_source` ever stops being contract-required, the reader needs its own check
        and this test is where that shows up.
        """
        from linked_archi_query.contract import ContractError

        for role in ("rel_source", "rel_target"):
            with self.subTest(role):
                with self.assertRaises(ContractError):
                    self._profile(without=role)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
