"""The result envelope: what makes an answer auditable rather than merely produced."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

import support

from linked_archi_query.envelope import Envelope, query_id


def _envelope(**overrides) -> Envelope:
    defaults = dict(
        query="SELECT ?s WHERE { ?s ?p ?o }",
        dataset_id="fixtures/base.trig",
        profile_id="linked-archi-default",
        profile_version=1,
        elapsed_ms=7,
        row_count=2,
        template="core/inventory",
        form="SELECT",
        variables=["s"],
        rows=[{"s": "urn:a"}, {"s": "urn:b"}],
    )
    defaults.update(overrides)
    return Envelope.build(**defaults)


class TestQueryIdentity(unittest.TestCase):
    def test_reindenting_does_not_change_the_identity(self):
        """Re-formatting a template must not invalidate every recorded result."""
        self.assertEqual(
            query_id("SELECT ?s WHERE { ?s ?p ?o }"),
            query_id("SELECT   ?s\nWHERE {\n  ?s ?p ?o\n}"),
        )

    def test_a_changed_term_changes_the_identity(self):
        self.assertNotEqual(
            query_id("SELECT ?s WHERE { ?s <urn:a> ?o }"),
            query_id("SELECT ?s WHERE { ?s <urn:b> ?o }"),
        )

    def test_a_changed_limit_changes_the_identity(self):
        self.assertNotEqual(
            query_id("SELECT ?s WHERE { ?s ?p ?o } LIMIT 10"),
            query_id("SELECT ?s WHERE { ?s ?p ?o } LIMIT 20"),
        )


class TestCitation(unittest.TestCase):
    def test_citation_carries_the_profile_and_its_version(self):
        """A result read under a different vocabulary is not the same result."""
        citation = _envelope().citation()
        self.assertIn("linked-archi-default", citation)
        self.assertIn("v1", citation)
        self.assertIn("fixtures/base.trig", citation)
        self.assertIn("core/inventory", citation)

    def test_ad_hoc_queries_are_labelled(self):
        self.assertIn("ad-hoc query", _envelope(template=None).citation())


class TestPresentation(unittest.TestCase):
    def test_table_renders_columns_in_declared_order(self):
        table = _envelope(
            variables=["b", "a"], rows=[{"a": "1", "b": "2"}]
        ).to_table()
        header = table.splitlines()[0]
        self.assertLess(header.index("b"), header.index("a"))

    def test_empty_result_is_reported_as_a_finding(self):
        rendered = _envelope(rows=[], row_count=0).to_table()
        self.assertIn("(no rows)", rendered)
        self.assertIn("finding, not a failure", rendered)
        self.assertIn("orientation templates", rendered)

    def test_truncation_is_reported_as_a_floor(self):
        rendered = _envelope(truncated=True).to_table()
        self.assertIn("floor", rendered)
        self.assertIn("at least", rendered)

    def test_caveats_are_surfaced(self):
        rendered = _envelope(warnings=["views graph is partial"]).to_table()
        self.assertIn("caveat: views graph is partial", rendered)

    def test_boolean_result(self):
        self.assertIn("True", _envelope(form="ASK", boolean=True, rows=[]).to_table())

    def test_construct_result_shows_triples(self):
        rendered = _envelope(
            form="CONSTRUCT", triples="<urn:a> <urn:p> <urn:b> .", rows=[]
        ).to_table()
        self.assertIn("<urn:a>", rendered)


class TestSerialisation(unittest.TestCase):
    def test_json_round_trip_keeps_the_audit_fields(self):
        document = json.loads(_envelope().to_json())
        for field in (
            "query", "query_id", "dataset_id", "profile_id", "profile_version",
            "executed_at", "elapsed_ms", "row_count", "truncated",
        ):
            self.assertIn(field, document)

    def test_write_creates_parent_directories(self):
        target = support.ROOT / "tests" / "_scratch" / "envelope.json"
        try:
            written = _envelope().write(target)
            self.assertTrue(written.is_file())
            self.assertEqual(
                json.loads(written.read_text())["profile_id"], "linked-archi-default"
            )
        finally:
            if target.is_file():
                target.unlink()
            if target.parent.is_dir():
                target.parent.rmdir()


class TestTruncationDetection(unittest.TestCase):
    """Detected by query when it turns a raw transport result into an envelope.

    These used to pass the row cap to ``_envelope`` by hand, which is why a defect in
    how the CALLERS chose that number survived them: the arithmetic was tested and the
    input never was. The cap now travels on the rendered query, so these read it from
    the same place the commands do, and ``TestTheRowCapComesFromTheQuery`` covers the
    seam itself.
    """

    def setUp(self):
        support.requires_pyoxigraph(self)

    def test_result_filling_the_limit_is_flagged(self):
        from linked_archi_query import load_catalog, render
        from linked_archi_query.cli import _envelope as build_envelope

        catalog = load_catalog()
        profile = support.load_resolved_profile("linked-archi-default")
        rendered = render("core/inventory", profile, {"LIMIT": 3}, catalog=catalog)
        self.assertEqual(rendered.row_limit, 3)
        raw = support.load_fixture(support.BASE).execute(rendered.query)
        envelope = build_envelope(raw.as_contract(), rendered, profile)
        self.assertEqual(envelope.row_count, 3)
        self.assertTrue(envelope.truncated)

    def test_result_below_the_limit_is_not_flagged(self):
        from linked_archi_query import load_catalog, render
        from linked_archi_query.cli import _envelope as build_envelope

        catalog = load_catalog()
        profile = support.load_resolved_profile("linked-archi-default")
        rendered = render(
            "core/provenance", profile,
            {"FOCUS_IRI": support.BPMN_TASK, "LIMIT": 50}, catalog=catalog,
        )
        raw = support.load_fixture(support.BASE).execute(rendered.query)
        envelope = build_envelope(raw.as_contract(), rendered, profile)
        self.assertFalse(envelope.truncated)


class TestTruncationIsHardToMiss(unittest.TestCase):
    """Truncation must be visible before the data, not only under it.

    It was footer-only once. A field session read a 200-row table, grepped the visible part
    for a term, found none, and nearly reported that those diagrams did not exist. A caveat
    200 lines below the data is a caveat nobody reads.
    """

    def _envelope(self, rows: int, limit: int, truncated: bool) -> Envelope:
        return Envelope.build(
            query="SELECT ?s WHERE { ?s ?p ?o }",
            dataset_id="base.trig",
            profile_id="linked-archi-default",
            profile_version=1,
            elapsed_ms=1,
            row_count=rows,
            template="core/inventory",
            form="SELECT",
            variables=["s"],
            rows=[{"s": f"urn:{index}"} for index in range(rows)],
            truncated=truncated,
        )

    def test_the_note_precedes_the_table(self):
        table = self._envelope(50, 5, truncated=False).to_table(limit=5)
        note = table.index("NOTE: showing 5 of 50")
        first_row = table.index("| s")
        self.assertLess(note, first_row, "the truncation note must come before the table")

    def test_a_limit_hit_says_the_count_is_a_floor(self):
        """"this result", not "this table": one wording now serves tsv and md both."""
        for shape in ("to_table", "to_tsv"):
            with self.subTest(shape=shape):
                rendered = getattr(self._envelope(100, 100, truncated=True), shape)(limit=100)
                self.assertIn("floor", rendered)
                self.assertIn("never read absence from this result", rendered)

    def test_a_complete_result_gets_no_note(self):
        table = self._envelope(3, 100, truncated=False).to_table(limit=100)
        self.assertNotIn("NOTE:", table)


class TestEmptyResultGuidance(unittest.TestCase):
    """An empty result from an invented query is usually a broken query."""

    def _empty(self, template: str | None) -> str:
        return Envelope.build(
            query="SELECT ?s WHERE { ?s <urn:nope> ?o }",
            dataset_id="base.trig",
            profile_id="linked-archi-default",
            profile_version=1,
            elapsed_ms=1,
            row_count=0,
            template=template,
            form="SELECT",
            variables=["s"],
            rows=[],
        ).to_table()

    def test_a_hand_written_query_is_told_to_lint_against_the_data(self):
        """`--data` is the part that matters, not the word lint.

        Without it the lint only confirms the query is read-only, which a query that already
        ran obviously is. With it, the published shapes answer whether the path was possible
        at all - the actual question behind an empty result, and the one this hint used to
        hand back to the reader as "check the direction of every relationship".
        """
        output = self._empty(None)
        self.assertIn("lint", output)
        self.assertIn("--data", output)
        self.assertIn("metamodel permits", output)

    def test_a_catalogued_template_is_not_told_to_lint_itself(self):
        # Templates are executed against the fixtures on every change; suggesting a lint
        # here would point the reader at the wrong suspect.
        output = self._empty("core/orphans")
        self.assertNotIn("hand-written", output)

    def test_both_still_frame_emptiness_as_a_finding(self):
        for template in (None, "core/orphans"):
            with self.subTest(template=template):
                self.assertIn("a finding, not a failure", self._empty(template))


class TestCaveatsSurviveEveryOutputShape(unittest.TestCase):
    """A caveat must reach the reader whatever shape the result took.

    Caveats were once rendered in the populated-table branch only, so an empty result,
    an ASK and a CONSTRUCT all dropped them. The worst case is the empty one: the
    caveat that says "this profile has not been verified against this dataset" explains
    precisely why a scoped query came back with nothing, and it was withheld from the
    one result that needed it. Observed against a real converter graph read with a
    profile that did not fit its graph layout - `(no rows)` plus generic advice, while
    the caveat naming the cause appeared in `--json` only.
    """

    CAVEAT = "profile 'linked-archi-default' has not been verified against this dataset"

    def _envelope(self, **overrides):
        defaults = dict(
            query="SELECT ?s WHERE { ?s ?p ?o }",
            dataset_id="converter-1.3.trig",
            profile_id="linked-archi-default",
            profile_version=1,
            elapsed_ms=1,
            row_count=0,
            template="core/models",
            form="SELECT",
            variables=["s"],
            rows=[],
            warnings=[self.CAVEAT],
        )
        defaults.update(overrides)
        return Envelope.build(**defaults)

    def test_an_empty_result_carries_it(self):
        output = self._envelope().to_table()
        self.assertIn(f"caveat: {self.CAVEAT}", output)
        # And still frames emptiness as a finding rather than replacing that guidance.
        self.assertIn("a finding, not a failure", output)

    def test_a_populated_table_carries_it(self):
        output = self._envelope(
            row_count=2, rows=[{"s": "urn:a"}, {"s": "urn:b"}]
        ).to_table()
        self.assertIn(f"caveat: {self.CAVEAT}", output)

    def test_a_boolean_result_carries_it(self):
        output = self._envelope(form="ASK", boolean=True, rows=[], variables=[]).to_table()
        self.assertIn(f"caveat: {self.CAVEAT}", output)

    def test_a_triples_result_carries_it(self):
        output = self._envelope(
            form="CONSTRUCT", triples="<urn:a> <urn:b> <urn:c> .", rows=[], variables=[]
        ).to_table()
        self.assertIn(f"caveat: {self.CAVEAT}", output)

    def test_the_citation_still_comes_last(self):
        """The caveat is inserted before the citation, not appended after it.

        The citation is what an answer quotes, so it has to stay the final line of
        every shape.
        """
        for label, overrides in (
            ("empty", {}),
            ("table", {"row_count": 1, "rows": [{"s": "urn:a"}]}),
            ("boolean", {"form": "ASK", "boolean": False, "variables": []}),
            ("triples", {"form": "CONSTRUCT", "triples": "<urn:a> <urn:b> <urn:c> ."}),
        ):
            with self.subTest(shape=label):
                envelope = self._envelope(**overrides)
                self.assertTrue(
                    envelope.to_table().rstrip().endswith(envelope.citation()),
                    f"{label} result does not end with its citation",
                )

    def test_no_caveats_means_no_caveat_line(self):
        """Silence when there is nothing to say, on every shape."""
        for label, overrides in (
            ("empty", {}),
            ("table", {"row_count": 1, "rows": [{"s": "urn:a"}]}),
            ("boolean", {"form": "ASK", "boolean": True, "variables": []}),
            ("triples", {"form": "CONSTRUCT", "triples": "<urn:a> <urn:b> <urn:c> ."}),
        ):
            with self.subTest(shape=label):
                self.assertNotIn(
                    "caveat:", self._envelope(warnings=[], **overrides).to_table()
                )


class TestTheRowCapComesFromTheQuery(unittest.TestCase):
    """`truncated`, exercised through the COMMANDS rather than through `_envelope`.

    This is the seam the defect lived in, and the reason it survived a suite that tested
    truncation: `TestTruncationDetection` passed the cap in by hand, so it verified the
    arithmetic and never the callers' choice of input. `run` measured against its own
    `--set LIMIT` - absent for most calls - and `literal` against the profile's
    `default_row_limit`, which describes what a template would be given rather than what
    the query carried.

    Both directions were wrong, and the false negative is the worse one: a result capped
    at 25 reported as complete is a count that reads as a total when it is a floor.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover - environment dependent
            raise unittest.SkipTest("pyoxigraph is not installed")

    def _query(self, *args: str) -> dict:
        """Run `la-query` as the command it is, and return the parsed envelope."""
        env = {
            key: value for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "LINKED_ARCHI_DATA", "LINKED_ARCHI_SKILLS_DIR"}
        }
        script = support.ROOT / "skills/linked-archi-query/scripts/la-query"
        done = subprocess.run(
            [sys.executable, str(script), *args, "--data", str(support.BASE), "--json"],
            capture_output=True, text=True, timeout=180, cwd=support.ROOT, env=env,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def _literal(self, query: str) -> dict:
        return self._query("query", "literal", "--query", query)

    #: Every triple in every named graph: 1282 rows in the base fixture, which is well
    #: above the 200 the old reference number happened to be.
    ALL_TRIPLES = (
        "{{PREFIXES}} SELECT ?s ?p ?o WHERE { GRAPH ?g { ?s ?p ?o } }"
    )

    def test_a_template_capped_at_its_own_default_is_flagged(self):
        """core/resolve-element defaults to LIMIT 25, and a full page of hits IS capped.

        This reported `false` before, so a resolution that had discarded most of its
        candidates looked exhaustive - on the one template the workflow always starts
        with.
        """
        envelope = self._query("query", "run", "core/resolve-element", "--set", "TERM=e")
        self.assertEqual(envelope["row_count"], 25)
        self.assertTrue(envelope["truncated"])

    def test_the_answer_does_not_depend_on_restating_the_default(self):
        """Same query, same rows. It used to differ: `false` without `--set LIMIT`,
        `true` with `--set LIMIT=25`."""
        implied = self._query("query", "run", "core/resolve-element", "--set", "TERM=e")
        restated = self._query(
            "query", "run", "core/resolve-element", "--set", "TERM=e", "--set", "LIMIT=25"
        )
        self.assertEqual(implied["row_count"], restated["row_count"])
        self.assertEqual(implied["truncated"], restated["truncated"])
        self.assertEqual(implied["query_id"], restated["query_id"])

    def test_a_template_with_room_to_spare_is_not_flagged(self):
        envelope = self._query(
            "query", "run", "core/resolve-element", "--set", "TERM=e",
            "--set", "LIMIT=200",
        )
        self.assertLess(envelope["row_count"], 200)
        self.assertFalse(envelope["truncated"])

    def test_a_literal_query_capped_below_two_hundred_is_flagged(self):
        """The false negative: 200 was the reference, so anything under it read complete."""
        for cap in (5, 50, 199):
            with self.subTest(limit=cap):
                envelope = self._literal(f"{self.ALL_TRIPLES} LIMIT {cap}")
                self.assertEqual(envelope["row_count"], cap)
                self.assertTrue(envelope["truncated"])

    def test_two_hundred_is_no_longer_special(self):
        """199 and 200 are both caps, and both were hit."""
        for cap in (199, 200, 201):
            with self.subTest(limit=cap):
                self.assertTrue(self._literal(f"{self.ALL_TRIPLES} LIMIT {cap}")["truncated"])

    def test_a_complete_literal_result_is_not_flagged_however_large(self):
        """The false positive: >= 200 rows was enough to be called truncated."""
        envelope = self._literal(f"{self.ALL_TRIPLES} LIMIT 5000")
        self.assertGreater(envelope["row_count"], 200)
        self.assertFalse(envelope["truncated"])

    def test_a_literal_query_with_no_limit_is_not_flagged(self):
        """Nothing capped it, so nothing can have been cut off."""
        envelope = self._literal(self.ALL_TRIPLES)
        self.assertGreater(envelope["row_count"], 200)
        self.assertFalse(envelope["truncated"])

    def test_display_limit_does_not_move_the_verdict(self):
        """`--limit` is a display cap. It bounds the table, not the query."""
        script = support.ROOT / "skills/linked-archi-query/scripts/la-query"
        env = {
            key: value for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "LINKED_ARCHI_DATA", "LINKED_ARCHI_SKILLS_DIR"}
        }
        verdicts = set()
        for display in ("5", "5000"):
            done = subprocess.run(
                [sys.executable, str(script), "query", "literal",
                 "--query", f"{self.ALL_TRIPLES} LIMIT 50",
                 "--data", str(support.BASE), "--json", "--limit", display],
                capture_output=True, text=True, timeout=180, cwd=support.ROOT, env=env,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            payload = json.loads(done.stdout)
            self.assertEqual(payload["row_count"], 50)
            verdicts.add(payload["truncated"])
        self.assertEqual(verdicts, {True})


class TestTsvIsTheDefaultShape(unittest.TestCase):
    """Tab-separated rows with the provenance commented, so a pipe stays a pipe.

    The reason it is the default is cost: on one 108-row result the same answer measured
    11.1 kB as tsv, 14.9 kB as the aligned markdown table - which showed only 100 of the
    rows - and 21.8 kB as the envelope, most of that last figure being the column name
    repeated on every row. Agents handed the envelope were shelling out to `jq` to get a
    column back.

    What must not be lost in exchange is the citation, so it is a comment rather than a
    line on stderr: capturing stdout alone cannot drop it.
    """

    @staticmethod
    def _rows(rendered: str) -> list[str]:
        """What a caller gets from `grep -v '^#'` - and nothing else."""
        return [line for line in rendered.split("\n") if not line.startswith("#")]

    def test_the_header_and_the_rows_are_all_that_is_not_commented(self):
        body = self._rows(_envelope().to_tsv())
        self.assertEqual(body, ["s", "urn:a", "urn:b"])

    def test_no_blank_line_survives_the_filter(self):
        """A blank line reads as a row to `cut`, which is why the separator is a comment."""
        for label, envelope in (
            ("plain", _envelope()),
            ("truncated", _envelope(truncated=True)),
            ("caveats", _envelope(warnings=["views graph is partial"])),
        ):
            with self.subTest(label):
                self.assertNotIn("", self._rows(envelope.to_tsv()))

    def test_every_row_has_the_same_field_count(self):
        """An unbound variable is an empty field, not a missing column."""
        envelope = _envelope(
            variables=["a", "b"], rows=[{"a": "1", "b": "2"}, {"a": "3"}], row_count=2
        )
        body = self._rows(envelope.to_tsv())
        self.assertEqual(body, ["a\tb", "1\t2", "3\t"])

    def test_a_value_containing_a_tab_cannot_invent_a_column(self):
        envelope = _envelope(rows=[{"s": "one\ttwo"}], row_count=1)
        body = self._rows(envelope.to_tsv())
        self.assertEqual(body, ["s", "one\\ttwo"])
        self.assertEqual(body[1].count("\t"), 0)

    def test_a_value_containing_a_newline_cannot_invent_a_row(self):
        envelope = _envelope(rows=[{"s": "one\ntwo"}], row_count=1)
        body = self._rows(envelope.to_tsv())
        self.assertEqual(body, ["s", "one\\ntwo"])

    def test_a_backslash_is_escaped_first_so_the_escaping_is_reversible(self):
        envelope = _envelope(rows=[{"s": "a\\tb"}], row_count=1)
        self.assertEqual(self._rows(envelope.to_tsv())[1], "a\\\\tb")

    def test_the_citation_still_comes_last(self):
        envelope = _envelope()
        self.assertTrue(envelope.to_tsv().rstrip().endswith(envelope.citation()))

    def test_the_truncation_note_precedes_the_rows_and_is_commented(self):
        rendered = _envelope(
            rows=[{"s": f"urn:{index}"} for index in range(50)], row_count=50
        ).to_tsv(limit=5)
        note = rendered.index("NOTE: showing 5 of 50")
        self.assertLess(note, rendered.index("urn:0"))
        self.assertTrue(rendered.startswith("# NOTE:"))

    def test_caveats_are_carried_and_commented(self):
        rendered = _envelope(warnings=["views graph is partial"]).to_tsv()
        self.assertIn("# caveat: views graph is partial", rendered)

    def test_shapes_with_nothing_tabular_render_as_the_prose_they_are(self):
        """ASK, CONSTRUCT and an empty result are guidance, and it is written once."""
        for label, overrides in (
            ("empty", {"rows": [], "row_count": 0}),
            ("boolean", {"form": "ASK", "boolean": True, "rows": [], "variables": []}),
            ("triples", {"form": "CONSTRUCT", "triples": "<urn:a> <urn:b> <urn:c> .",
                         "rows": [], "variables": []}),
        ):
            with self.subTest(label):
                envelope = _envelope(**overrides)
                self.assertEqual(envelope.to_tsv(), envelope.to_table())


class TestTheDefaultFormatIsTsv(unittest.TestCase):
    """Through the command, because the default is a property of the CLI, not the envelope."""

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover - environment dependent
            raise unittest.SkipTest("pyoxigraph is not installed")

    def _run(self, *extra: str) -> str:
        env = {
            key: value for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "LINKED_ARCHI_DATA", "LINKED_ARCHI_SKILLS_DIR"}
        }
        script = support.ROOT / "skills/linked-archi-query/scripts/la-query"
        done = subprocess.run(
            [sys.executable, str(script), "query", "run", "core/models",
             "--data", str(support.BASE), *extra],
            capture_output=True, text=True, timeout=180, cwd=support.ROOT, env=env,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_no_format_flag_gives_tab_separated_rows(self):
        output = self._run()
        rows = [line for line in output.strip().split("\n") if not line.startswith("#")]
        self.assertNotIn("|", rows[0], "the default should no longer be a markdown table")
        self.assertIn("\t", rows[0])

    def test_md_still_gives_the_aligned_table(self):
        self.assertIn("|", self._run("--format", "md").split("\n")[0])

    def test_json_and_the_older_flag_agree(self):
        by_format = json.loads(self._run("--format", "json"))
        by_alias = json.loads(self._run("--json"))
        self.assertEqual(by_format["rows"], by_alias["rows"])
        self.assertEqual(by_format["query_id"], by_alias["query_id"])

    def test_the_citation_survives_every_format(self):
        for shape in ([], ["--format", "md"]):
            with self.subTest(shape=shape or "default"):
                self.assertIn("profile linked-archi-default", self._run(*shape))
