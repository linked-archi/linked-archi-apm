"""Judging a query's paths, and refusing to judge when the evidence does not support it.

The rule that shaped this module: a violation may only be asserted where the shape set is
known complete and the class hierarchy is attached. Everything else is reported as unjudged
with the reason. Both halves were learned by getting them wrong - the first draft accused a
Business Actor of an impossible `am:flowsTo` because the fixture carried one ArchiMate shape
out of 73, which is absence-means-prohibition inside the checker.
"""

from __future__ import annotations

import unittest

import support
from support import requires_pyoxigraph

from linked_archi_query.constraints import (
    constraints_from_profile,
    read_complete_notations,
)
from linked_archi_query.paths import check_query, read_subclasses

AM = "https://meta.linked.archi/archimate3/onto#"
BS = "https://meta.linked.archi/backstage/onto#"
PREFIXES = (
    f"PREFIX am: <{AM}>\n"
    f"PREFIX bs: <{BS}>\n"
    "PREFIX arch: <https://meta.linked.archi/core#>\n"
)


def _sparql(*paths):
    from pyoxigraph import RdfFormat, Store

    store = Store()
    for path in paths:
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


class TestPathChecking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        requires_pyoxigraph(cls)
        from linked_archi_profile.profile import load_profile
        from linked_archi_query import ResolvedProfile

        cls.sparql = staticmethod(_sparql(support.SHAPES, support.VOCABULARY))
        profile = ResolvedProfile(load_profile("curated-store").resolved_snapshot())
        cls.constraints = constraints_from_profile(cls.sparql, profile)
        cls.subclasses = read_subclasses(cls.sparql)

    def _check(self, where: str):
        return check_query(f"{PREFIXES}SELECT * WHERE {{ {where} }}",
                           self.constraints, self.subclasses)

    def test_a_permitted_path_is_sound(self):
        report = self._check("?s a bs:Component ; bs:ownedBy ?o . ?o a bs:Group")
        self.assertTrue(report.sound, report.summary())
        self.assertEqual(report.violations, ())

    def test_a_forbidden_target_is_reported_with_what_is_permitted(self):
        report = self._check("?s a bs:Component ; bs:ownedBy ?o . ?o a bs:Component")
        self.assertEqual(len(report.violations), 1, report.summary())
        message = report.violations[0].message
        self.assertIn("may not point at", message)
        self.assertIn("Group", message, "the repair hint has to name the alternatives")

    def test_a_partial_shape_set_is_never_accused(self):
        """The defect this design exists for.

        ArchiMate carries 4 shapes of 73 here, so the absence of a Business Actor shape
        says nothing about whether a Business Actor may flow to anything. Reading it as a
        prohibition is the same error as reading an empty result as absence.
        """
        report = self._check("?s a am:BusinessActor ; am:flowsTo ?o . ?o a am:Value")
        self.assertEqual(report.violations, ())
        self.assertFalse(report.sound, "nothing was judged, so it is not a clean bill")
        self.assertTrue(any("complete" in note for note in report.unchecked))

    def test_nothing_judged_is_not_the_same_as_nothing_wrong(self):
        report = self._check("?s bs:ownedBy ?o")
        self.assertEqual(report.violations, ())
        self.assertEqual(report.checked, 0)
        self.assertFalse(report.sound)
        self.assertIn("not checked", report.summary())

    def test_an_unconstrained_predicate_is_simply_skipped(self):
        report = self._check("?s a bs:Component ; <https://example.org/x#rel> ?o")
        self.assertEqual(report.violations, ())
        self.assertEqual(report.checked, 0)

    def test_a_query_that_cannot_be_parsed_is_refused_not_passed(self):
        """SPARQL 1.2 triple terms are beyond the available parser.

        Three catalogued templates use them. Reporting "no violations" for a query nobody
        could read would be the worst available answer.
        """
        report = check_query(
            "SELECT * WHERE { <<( ?s ?p ?o )>> ?a ?b }",
            self.constraints,
            self.subclasses,
        )
        self.assertIsNotNone(report.refused)
        self.assertFalse(report.sound)

    def test_no_constraints_attached_refuses(self):
        from linked_archi_query.constraints import Constraints

        report = check_query(f"{PREFIXES}SELECT * WHERE {{ ?s bs:ownedBy ?o }}",
                             Constraints(), {})
        self.assertIn("no relationship constraints", report.refused or "")


class TestCompletenessComesFromTheManifest(unittest.TestCase):
    """Only a manifest can say what a complete shape set is.

    `arch:formalRules` names every published shape namespace for a metamodel, so a
    namespace with no shape present means the set is partial. A notation with no manifest
    attached is not complete either - nothing says what it should hold.
    """

    @classmethod
    def setUpClass(cls):
        requires_pyoxigraph(cls)
        cls.sparql = staticmethod(_sparql(support.SHAPES, support.VOCABULARY))

    def test_the_notation_carried_whole_is_complete(self):
        complete = read_complete_notations(self.sparql)
        self.assertIn("https://meta.linked.archi/backstage/", complete)

    def test_the_notation_carried_as_a_slice_is_not(self):
        complete = read_complete_notations(self.sparql)
        self.assertNotIn("https://meta.linked.archi/archimate3/", complete)

    def test_no_manifest_means_nothing_is_complete(self):
        self.assertEqual(read_complete_notations(_sparql(support.BASE)), frozenset())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
