"""Read-only enforcement.

Two halves that matter equally. The refusals stop a mutation reaching a graph. The
acceptances stop the checker being so blunt that it refuses legitimate work - and
five of the cases below are queries the predecessor's checker wrongly rejected,
because `?` and `:` are non-word characters and its word-boundary patterns matched
inside variable names and prefixed names.
"""

from __future__ import annotations

import unittest

import support  # noqa: F401 - puts lib/ on the path

from linked_archi_query.validate import (
    QueryError,
    code_only,
    is_readonly,
    query_form,
    split_comments,
    validate_readonly,
)


class TestAccepted(unittest.TestCase):
    """Read-only queries that must run."""

    CASES = {
        "plain select": "SELECT ?s WHERE { ?s ?p ?o }",
        "with prefixes": "PREFIX ex: <http://e/>\nSELECT ?s WHERE { GRAPH ?g { ?s a ex:T } }",
        "ask": "ASK { ?s ?p ?o }",
        "construct": "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "describe": "DESCRIBE <http://e/x>",
        "base declaration": "BASE <http://e/>\nSELECT ?s WHERE { ?s ?p ?o }",
        "values block": "SELECT ?s WHERE { VALUES ?s { 1 2 } }",
        "filter exists": "SELECT ?s WHERE { ?s ?p ?o FILTER EXISTS { ?s a ?t } }",
        "property path": "SELECT ?s WHERE { ?s <http://e/a>|<http://e/b> ?o }",
        "subquery": "SELECT ?s WHERE { { SELECT ?s WHERE { ?s ?p ?o } LIMIT 1 } }",
    }

    #: Rejected by the predecessor's checker. Each is legitimate SPARQL whose text
    #: happens to contain an update keyword somewhere a keyword cannot appear.
    FALSE_POSITIVES = {
        "variable named add": "SELECT ?add WHERE { ?add ?p ?o }",
        "variable named delete": "SELECT ?delete WHERE { ?delete ?p ?o }",
        "prefixed name copy": "PREFIX ex: <http://e/>\nSELECT ?s WHERE { ?s ex:copy ?o }",
        "prefixed name load": "PREFIX ex: <http://e/>\nSELECT ?s WHERE { ?s a ex:load }",
        "literal holding INSERT": 'SELECT ?s WHERE { ?s ?p "INSERT DATA { }" }',
        "comment holding DROP": "# DROP GRAPH <g>\nSELECT ?s WHERE { ?s ?p ?o }",
        "iri holding delete": "SELECT ?s WHERE { ?s <http://e/delete> ?o }",
        "triple-quoted literal": 'SELECT ?s WHERE { ?s ?p """a\nLOAD b""" }',
    }

    def test_accepted(self):
        for name, query in self.CASES.items():
            with self.subTest(name):
                validate_readonly(query)
                self.assertTrue(is_readonly(query))

    def test_no_false_positives(self):
        for name, query in self.FALSE_POSITIVES.items():
            with self.subTest(name):
                validate_readonly(query)


class TestRefused(unittest.TestCase):
    """Anything that is not a read-only query."""

    CASES = {
        "insert data": "INSERT DATA { <a> <b> <c> }",
        "delete where": "DELETE WHERE { ?s ?p ?o }",
        "delete insert": "DELETE { ?s ?p ?o } INSERT { ?s ?p 1 } WHERE { ?s ?p ?o }",
        "load": "LOAD <http://e/d>",
        "clear": "CLEAR GRAPH <http://e/g>",
        "drop": "DROP GRAPH <http://e/g>",
        "create": "CREATE GRAPH <http://e/g>",
        "copy": "COPY <http://e/a> TO <http://e/b>",
        "move": "MOVE <http://e/a> TO <http://e/b>",
        "add": "ADD <http://e/a> TO <http://e/b>",
        "with prologue": "WITH <http://e/g> DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "service": "SELECT ?s WHERE { SERVICE <http://r/sparql> { ?s ?p ?o } }",
        "unresolved placeholder": "SELECT ?s WHERE { ?s a {{ROLE:element_class}} }",
        "update smuggled after select": (
            "SELECT ?s WHERE { ?s ?p ?o } ; INSERT DATA { <a> <b> <c> }"
        ),
        "empty": "   ",
        "prologue only": "PREFIX ex: <http://e/>",
    }

    def test_refused(self):
        for name, query in self.CASES.items():
            with self.subTest(name):
                with self.assertRaises(QueryError):
                    validate_readonly(query)
                self.assertFalse(is_readonly(query))

    def test_refusal_names_the_construct(self):
        """A refusal an agent can explain, not a generic failure."""
        with self.assertRaises(QueryError) as caught:
            validate_readonly("DROP GRAPH <http://e/g>")
        self.assertIn("DROP", str(caught.exception))

        with self.assertRaises(QueryError) as caught:
            validate_readonly("SELECT ?s WHERE { SERVICE <http://r/s> { ?s ?p ?o } }")
        self.assertIn("SERVICE", str(caught.exception))

        with self.assertRaises(QueryError) as caught:
            validate_readonly("SELECT ?s WHERE { ?s a {{ROLE:x}} }")
        self.assertIn("{{ROLE:x}}", str(caught.exception))


class TestQueryForm(unittest.TestCase):
    def test_form_detected(self):
        for query, expected in [
            ("SELECT * WHERE { ?s ?p ?o }", "SELECT"),
            ("PREFIX ex: <http://e/>\nASK { ?s ?p ?o }", "ASK"),
            ("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "CONSTRUCT"),
            ("DESCRIBE <http://e/x>", "DESCRIBE"),
        ]:
            with self.subTest(expected):
                self.assertEqual(query_form(query), expected)

    def test_form_validates_first(self):
        with self.assertRaises(QueryError):
            query_form("DROP GRAPH <http://e/g>")


class TestCommentSplitting(unittest.TestCase):
    """Shared with the renderer, so a template header is not mistaken for code."""

    def test_full_line_comment_detected(self):
        segments = split_comments("# a comment\nSELECT ?s WHERE { ?s ?p ?o }")
        self.assertTrue(any(is_comment for is_comment, _ in segments))

    def test_hash_inside_iri_is_not_a_comment(self):
        segments = split_comments("SELECT * WHERE { ?s <http://x/y#z> ?o }")
        self.assertFalse(any(is_comment for is_comment, _ in segments))

    def test_hash_inside_literal_is_not_a_comment(self):
        segments = split_comments('SELECT * WHERE { ?s ?p "a#b" }')
        self.assertFalse(any(is_comment for is_comment, _ in segments))

    def test_code_only_preserves_line_count(self):
        text = "# one\nSELECT ?s\n# two\nWHERE { ?s ?p ?o }"
        self.assertEqual(len(code_only(text).splitlines()), len(text.splitlines()))

    def test_placeholder_in_comment_is_not_unresolved(self):
        """A header naming its own placeholders is documentation, not a bug."""
        validate_readonly(
            "# uses {{GRAPH_OPEN:any}} deliberately\nSELECT ?s WHERE { ?s ?p ?o }"
        )


if __name__ == "__main__":
    unittest.main()
