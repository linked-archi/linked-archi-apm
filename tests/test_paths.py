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
    read_represented_notations,
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


class TestTheQualifiedForm(unittest.TestCase):
    """`?rel a R ; arch:source ?s ; arch:target ?t` - the form the templates use.

    Invisible to the direct-predicate rules, because the legs are deliberately excluded
    from that table and nothing else looked at them. The check ran over all 39 catalogued
    templates and judged nothing, which reads as 39 clean templates and was no coverage.
    """

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

    RELATION = "?r a bs:Ownership ; arch:source ?s ; arch:target ?t . "

    def test_a_permitted_pair_is_sound(self):
        report = self._check(f"{self.RELATION}?s a arch:Element . ?t a bs:Group")
        self.assertTrue(report.sound, report.summary())

    def test_a_forbidden_target_is_reported(self):
        report = self._check(f"{self.RELATION}?s a arch:Element . ?t a bs:Component")
        self.assertEqual(len(report.violations), 1, report.summary())
        self.assertIn("permitted targets", report.violations[0].message)

    def test_a_subclass_of_a_permitted_source_still_applies(self):
        """`bs:Group` is an `arch:Element`, so Ownership from a Group is permitted.

        The rule is inherited down the hierarchy; only a class ABOVE a permitted one is
        ambiguous.
        """
        report = self._check(f"{self.RELATION}?s a bs:Group . ?t a bs:User")
        self.assertTrue(report.sound, report.summary())

    def test_an_exact_source_match_does_not_excuse_a_bad_target(self):
        """The bug this rule was rewritten for.

        Judging both ends in one test excused the whole pattern as soon as either end
        looked ambiguous - and a class is trivially below itself, so an exact source match
        hid a forbidden target. The ends are judged independently now.
        """
        report = self._check(f"{self.RELATION}?s a arch:Element . ?t a bs:Component")
        self.assertTrue(report.violations, "an exact source match must not excuse this")

    def test_untyped_ends_are_reported_as_unjudged(self):
        report = self._check(self.RELATION.rstrip(". "))
        self.assertEqual(report.violations, ())
        self.assertFalse(report.sound)
        self.assertTrue(any("not both typed" in note for note in report.unchecked))

    def test_the_catalogue_offers_nothing_to_judge(self):
        """Recorded because it looks like a gap and is not.

        Every catalogued template leaves its ends untyped - `notation/backstage/ownership`
        asks WHICH entities are owned, so typing `?entity` would defeat the question. So
        this check cannot validate the catalogue, and a sweep reporting "no violations
        across 39 templates" would be measuring nothing. It is for hand-written and
        generated queries, where the classes are concrete.
        """
        from linked_archi_query.render import render

        report = check_query(
            render("notation/backstage/ownership", self.constraints_profile(), {}).query,
            self.constraints,
            self.subclasses,
        )
        self.assertEqual(report.checked, 0)
        self.assertEqual(report.violations, ())

    def constraints_profile(self):
        from linked_archi_profile.profile import load_profile
        from linked_archi_query import ResolvedProfile

        return ResolvedProfile(load_profile("curated-store").resolved_snapshot())


class TestWhatTheManifestCanAndCannotEstablish(unittest.TestCase):
    """`arch:formalRules` proves a set is PARTIAL; it cannot prove one is whole.

    A namespace with nothing attached is decisive - the shapes are missing. The converse
    does not follow, and this class pins both halves so the weaker guarantee is not mistaken
    for the stronger one later.
    """

    @classmethod
    def setUpClass(cls):
        requires_pyoxigraph(cls)
        cls.sparql = staticmethod(_sparql(support.SHAPES, support.VOCABULARY))

    def test_a_notation_with_every_namespace_attached_is_represented(self):
        represented = read_represented_notations(self.sparql)
        self.assertIn("https://meta.linked.archi/backstage/", represented)

    def test_a_notation_missing_a_declared_namespace_is_not(self):
        represented = read_represented_notations(self.sparql)
        self.assertNotIn("https://meta.linked.archi/archimate3/", represented)

    def test_no_manifest_means_nothing_is_represented(self):
        self.assertEqual(read_represented_notations(_sparql(support.BASE)), frozenset())

    def test_one_shape_of_many_still_counts_as_represented(self):
        """The known limitation, asserted rather than left as a comment.

        Nothing published states how many shapes a document declares, so presence of one
        shape per declared namespace is all that can be verified. This test exists so the
        gap is visible, and so that publishing a count upstream turns it into a failure that
        has to be dealt with rather than a silent improvement nobody notices.
        """
        import tempfile
        from pathlib import Path

        manifest = (
            "@prefix arch: <https://meta.linked.archi/core#> .\n"
            "<https://meta.linked.archi/example/metamodel#X> a arch:Metamodel ;\n"
            "    arch:formalRules <https://meta.linked.archi/example/shapes#> .\n"
        )
        one_shape = (
            "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
            "<https://meta.linked.archi/example/shapes#Only> a sh:NodeShape .\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, text in (("m.ttl", manifest), ("s.ttl", one_shape)):
                path = Path(directory) / name
                path.write_text(text, encoding="utf-8")
                paths.append(path)
            represented = read_represented_notations(_sparql(*paths))
        self.assertIn(
            "https://meta.linked.archi/example/",
            represented,
            "if this now fails, wholeness became verifiable - tighten the gate and drop "
            "the provisional caveat from Report",
        )

    def test_any_verdict_carries_the_provisional_caveat(self):
        from linked_archi_profile.profile import load_profile
        from linked_archi_query import ResolvedProfile
        from linked_archi_query.constraints import constraints_from_profile

        sparql = _sparql(support.SHAPES, support.VOCABULARY)
        profile = ResolvedProfile(load_profile("curated-store").resolved_snapshot())
        report = check_query(
            f"{PREFIXES}SELECT * WHERE {{ ?s a bs:Component ; bs:ownedBy ?o . ?o a bs:Group }}",
            constraints_from_profile(sparql, profile),
            read_subclasses(sparql),
        )
        self.assertTrue(report.checked)
        self.assertTrue(any("whole" in caveat for caveat in report.caveats))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
