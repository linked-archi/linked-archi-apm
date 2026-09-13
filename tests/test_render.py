"""Rendering: role resolution, graph scoping, parameter typing, refusals.

The renderer is where a profile becomes SPARQL, so it is where a vocabulary mistake
either gets caught or gets baked into a query that runs and misleads. Several tests
below pin behaviour that was wrong at some point during development and is easy to
regress.
"""

from __future__ import annotations

import unittest

import support

from linked_archi_profile import Profile
from linked_archi_query import ResolvedProfile, load_catalog, render
from linked_archi_query.catalog import Requirement
from linked_archi_query.render import (
    RenderError,
    UnsupportedTemplate,
    coerce,
    graph_open,
    graph_var,
    membership_pattern,
    render_literal,
    trailing_row_limit,
)
load_profile = support.load_resolved_profile


class TestGraphScoping(unittest.TestCase):
    def setUp(self):
        self.default = load_profile("linked-archi-default")
        self.flat = load_profile("flattened-turtle")

    def test_per_model_layout_filters_on_the_suffix(self):
        opened = graph_open(self.default, "semantic")
        self.assertIn("GRAPH ?g_semantic {", opened)
        self.assertIn('STRENDS(STR(?g_semantic), "graph/semantic")', opened)

    def test_each_role_binds_its_own_variable(self):
        """A shared variable would require one graph to end in two suffixes at once."""
        self.assertEqual(graph_var("semantic"), "?g_semantic")
        self.assertEqual(graph_var("provenance"), "?g_provenance")
        self.assertNotEqual(graph_var("semantic"), graph_var("provenance"))

    def test_numbered_alias_opens_an_independent_scope_on_one_role(self):
        first = graph_open(self.default, "semantic")
        second = graph_open(self.default, "semantic2")
        self.assertIn("?g_semantic2", second)
        self.assertIn('STRENDS(STR(?g_semantic2), "graph/semantic")', second)
        self.assertNotEqual(first, second)

    def test_any_scope_binds_without_constraining(self):
        opened = graph_open(self.default, "any")
        self.assertEqual(opened, "GRAPH ?g_any {")
        self.assertNotIn("FILTER", opened)

    def test_single_layout_collapses_to_a_plain_group(self):
        self.assertEqual(graph_open(self.flat, "semantic"), "{")

    def test_explicit_layout_uses_a_values_restriction(self):
        profile = ResolvedProfile(Profile({
            "profile": "explicit",
            "namespaces": {"ex": "http://e/"},
            "graphs": {
                "layout": "explicit",
                "roles": {"semantic": ["https://e/g/one", "https://e/g/two"]},
            },
            "roles": {
                "concept_class": "ex:C", "element_class": "ex:E",
                "relationship_class": "ex:R", "rel_source": "ex:s",
                "rel_target": "ex:t", "rel_type": "ex:ty", "label": "ex:l",
            },
        }).resolved_snapshot())
        opened = graph_open(profile, "semantic")
        self.assertIn("VALUES ?g_semantic {", opened)
        self.assertIn("<https://e/g/one>", opened)

    def test_unknown_graph_role_names_what_exists(self):
        with self.assertRaises(RenderError) as caught:
            graph_open(self.default, "nonsense")
        self.assertIn("semantic", str(caught.exception))


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.profile = load_profile("linked-archi-default")

    def _render(self, name, **params):
        return render(name, self.profile, params, catalog=self.catalog)

    def test_roles_become_absolute_iris(self):
        query = self._render(
            "core/neighbours-qualified", FOCUS_IRI=support.BPMN_TASK
        ).query
        self.assertIn("<https://meta.linked.archi/core#QualifiedRelationship>", query)
        self.assertIn("<https://meta.linked.archi/core#source>", query)

    def test_no_template_carries_its_own_prefixes(self):
        """A template with its own PREFIX lines is how one query goes stale alone."""
        for entry in self.catalog:
            with self.subTest(entry.name):
                body = "\n".join(
                    line for line in entry.text().splitlines()
                    if not line.lstrip().startswith("#")
                )
                self.assertNotIn("PREFIX ", body)
                self.assertIn("{{PREFIXES}}", entry.text())

    def test_prefixes_directive_expands(self):
        query = self._render("core/inventory").query
        self.assertIn("PREFIX arch: <https://meta.linked.archi/core#>", query)

    def test_comment_header_is_left_alone(self):
        """A header naming its placeholders documents the mechanism; do not rewrite it."""
        query = self._render("core/inventory").query
        header = [l for l in query.splitlines() if "Deliberately unscoped" in l]
        self.assertTrue(header)
        self.assertIn("{{GRAPH_OPEN:any}}", header[0])
        self.assertIn("GRAPH ?g_any {", query)

    def test_rendered_query_is_read_only(self):
        for entry in self.catalog:
            if not entry.check(self.profile).ok:
                continue
            with self.subTest(entry.name):
                params = _sample_params(entry)
                render(entry.name, self.profile, params, catalog=self.catalog)

    def test_limit_defaults_to_the_profile_ceiling_logic(self):
        query = self._render("core/inventory").query
        self.assertRegex(query, r"LIMIT \d+")

    def test_literal_query_gets_the_same_treatment(self):
        rendered = render_literal(
            "{{PREFIXES}}\nSELECT ?s WHERE { {{GRAPH_OPEN:semantic}} "
            "?s a {{ROLE:element_class}} . {{GRAPH_CLOSE}} }",
            self.profile,
        )
        self.assertIn("GRAPH ?g_semantic {", rendered.query)
        self.assertIn("<https://meta.linked.archi/core#Element>", rendered.query)

    def test_literal_query_rejects_a_parameter(self):
        with self.assertRaises(RenderError):
            render_literal("SELECT ?s WHERE { ?s a {{FOCUS_IRI}} }", self.profile)


class TestEnumParameters(unittest.TestCase):
    """A misspelled enum is refused, not interpolated.

    `core/view-diff` compares its DIRECTION against a bound `?side`. Without validation,
    `--set DIRECTION=aonly` would match nothing and return zero rows, which reads as "the
    two views are identical" - a wrong answer dressed as a finding.
    """

    def setUp(self):
        self.catalog = load_catalog()
        self.profile = load_profile("linked-archi-default")

    def _diff(self, **params):
        return render(
            "core/view-diff", self.profile,
            {"VIEW_A_IRI": support.C4_VIEW, "VIEW_B_IRI": support.C4_CONTEXT_VIEW,
             **params},
            catalog=self.catalog,
        )

    def test_every_declared_choice_renders(self):
        for direction in ("a-only", "b-only", "symmetric"):
            with self.subTest(direction):
                self.assertIn(f'"{direction}"', self._diff(DIRECTION=direction).query)

    def test_an_unlisted_value_is_refused_and_the_options_are_named(self):
        with self.assertRaises(RenderError) as caught:
            self._diff(DIRECTION="aonly")
        message = str(caught.exception)
        self.assertIn("DIRECTION", message)
        for direction in ("a-only", "b-only", "symmetric"):
            self.assertIn(direction, message)

    def test_the_default_is_used_when_the_parameter_is_omitted(self):
        self.assertIn('"symmetric"', self._diff().query)

    def test_a_string_without_choices_is_still_free_text(self):
        rendered = render("core/resolve-element", self.profile, {"TERM": "anything at all"},
                          catalog=self.catalog)
        self.assertIn('"anything at all"', rendered.query)


class TestParameterTyping(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.profile = load_profile("linked-archi-default")

    def _neighbours(self, **params):
        return render("core/neighbours-qualified", self.profile, params,
                      catalog=self.catalog)

    def test_bracketed_and_bare_iris_both_accepted(self):
        for value in (support.BPMN_TASK, f"<{support.BPMN_TASK}>"):
            with self.subTest(value):
                self.assertIn(f"<{support.BPMN_TASK}>", self._neighbours(FOCUS_IRI=value).query)

    def test_relative_iri_refused(self):
        with self.assertRaises(RenderError) as caught:
            self._neighbours(FOCUS_IRI="not-an-iri")
        self.assertIn("absolute", str(caught.exception))

    def test_iri_with_illegal_character_refused(self):
        with self.assertRaises(RenderError):
            self._neighbours(FOCUS_IRI="https://e.org/a b")

    def test_limit_above_maximum_refused(self):
        with self.assertRaises(RenderError) as caught:
            self._neighbours(FOCUS_IRI=support.BPMN_TASK, LIMIT=10**9)
        self.assertIn("maximum", str(caught.exception))

    def test_unknown_parameter_refused(self):
        with self.assertRaises(RenderError) as caught:
            self._neighbours(FOCUS_IRI=support.BPMN_TASK, NOPE=1)
        self.assertIn("NOPE", str(caught.exception))

    def test_missing_required_parameter_refused(self):
        with self.assertRaises(RenderError) as caught:
            self._neighbours()
        self.assertIn("FOCUS_IRI", str(caught.exception))

    def test_string_injection_becomes_a_literal(self):
        rendered = coerce("TERM", 'x" } ; DROP GRAPH <g> #', {"type": "string"})
        self.assertTrue(rendered.startswith('"') and rendered.endswith('"'))
        self.assertIn('\\"', rendered)

    def test_string_parameter_cannot_escape_the_query(self):
        """The injected quote must be escaped, so the literal is never terminated.

        Asserting the payload text is absent would be the wrong check: it is
        legitimately present, inside a string literal. What matters is that the quote
        which would have closed that literal is escaped, leaving the payload as data.
        """
        payload = 'a" } ; DROP GRAPH <urn:g> #'
        query = render(
            "core/resolve-element", self.profile, {"TERM": payload},
            catalog=self.catalog,
        ).query
        self.assertIn('\\"', query)
        # The literal survives as one token: no bare quote followed by the payload's
        # closing brace, which is what an escape would have to fail to produce.
        self.assertNotIn('"a" }', query)

    def test_iri_list_accepts_a_cli_string(self):
        self.assertEqual(
            coerce("P", "https://e.org/a, https://e.org/b", {"type": "iri_list"}),
            "<https://e.org/a> <https://e.org/b>",
        )

    def test_iri_path_builds_an_alternation(self):
        self.assertEqual(
            coerce("P", ["https://e.org/a", "https://e.org/b"], {"type": "iri_path"}),
            "<https://e.org/a>|<https://e.org/b>",
        )

    def test_iri_path_is_capped(self):
        """An alternation over everything is the wildcard path it replaced."""
        many = [f"https://e.org/p{i}" for i in range(20)]
        with self.assertRaises(RenderError) as caught:
            coerce("P", many, {"type": "iri_path", "max_terms": 12})
        self.assertIn("exceeds the maximum", str(caught.exception))

    def test_boolean_is_not_an_integer(self):
        with self.assertRaises(RenderError):
            coerce("LIMIT", True, {"type": "integer", "min": 1, "max": 10})


class TestRefusals(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.profile = load_profile("linked-archi-default")

    def test_capability_gate_refuses_with_reason_and_alternative(self):
        with self.assertRaises(UnsupportedTemplate) as caught:
            render("core/dependents-direct", self.profile,
                   {"FOCUS_IRI": support.BPMN_TASK,
                    "PREDICATE_PATH": support.ARCHIMATE_FLOWS_TO},
                   catalog=self.catalog)
        message = str(caught.exception)
        self.assertIn("direct_rel_triples", message)
        self.assertIn("core/dependents-qualified", message)
        self.assertIn("refusal, not an empty result", message)

    def test_unbound_role_refuses(self):
        with self.assertRaises(UnsupportedTemplate) as caught:
            render("core/identity-audit", self.profile, {}, catalog=self.catalog)
        self.assertIn("same_as", str(caught.exception))

    def test_refusal_carries_the_verdict_for_inspection(self):
        with self.assertRaises(UnsupportedTemplate) as caught:
            render("core/validation-summary", self.profile, {}, catalog=self.catalog)
        self.assertFalse(caught.exception.verdict.ok)
        self.assertTrue(caught.exception.verdict.unmet)
        self.assertEqual(caught.exception.entry.name, "core/validation-summary")

    def test_force_renders_an_unsupported_template_for_inspection(self):
        rendered = render("core/validation-summary", self.profile, {},
                          catalog=self.catalog, strict=False)
        self.assertIn("sh:ValidationReport", rendered.query)

    def test_enabling_profile_lifts_the_refusal(self):
        curated = load_profile("curated-store")
        rendered = render("core/dependents-direct", curated,
                          {"FOCUS_IRI": support.BPMN_LAST_TASK,
                           "PREDICATE_PATH": support.ARCHIMATE_FLOWS_TO},
                          catalog=self.catalog)
        self.assertIn("+ ", rendered.query)

    def test_partial_capability_runs_with_a_caveat(self):
        rendered = render("core/view-usage", self.profile,
                          {"FOCUS_IRI": support.C4_CONTAINER}, catalog=self.catalog)
        self.assertTrue(rendered.warnings)
        self.assertIn("partial", " ".join(rendered.warnings))

    def test_flat_profile_warns_rather_than_refusing_a_scoped_template(self):
        flat = load_profile("flattened-turtle")
        rendered = render("core/neighbours-qualified", flat,
                          {"FOCUS_IRI": support.BPMN_TASK}, catalog=self.catalog)
        self.assertTrue(rendered.warnings)
        self.assertIn("no named graphs", " ".join(rendered.warnings))

    def test_rendered_records_the_profile_it_used(self):
        rendered = render("core/inventory", self.profile, {}, catalog=self.catalog)
        self.assertEqual(rendered.profile, "linked-archi-default")
        self.assertEqual(rendered.profile_version, self.profile.profile_version)


def _sample_params(entry) -> dict:
    """Plausible values for whatever an entry declares. Shared with test_templates."""
    values = {
        "FOCUS_IRI": support.BPMN_TASK,
        "TERM": "order",
        "TYPE_IRI": f"{support.CORE}Element",
        "RESOURCE_TYPE": f"{support.CORE}Element",
        "EXPECTED_PREDICATE": f"{support.SKOS}prefLabel",
        "SOURCE_TYPE": "https://meta.linked.archi/bpmn/onto#UserTask",
        "TARGET_TYPE": "https://meta.linked.archi/bpmn/onto#ServiceTask",
        "CONCEPT_IRI": support.TAX_ROOT,
        "PROCESS_IRI": support.BPMN_PROCESS,
        "MODEL_IRI": support.BPMN_MODEL,
        "VIEW_IRI": support.C4_VIEW,
        "VIEW_A_IRI": support.C4_VIEW,
        "VIEW_B_IRI": support.C4_CONTEXT_VIEW,
        "PREDICATE_PATH": support.ARCHIMATE_FLOWS_TO,
        "LIMIT": 5,
    }
    return {k: v for k, v in values.items() if k in entry.parameters}


if __name__ == "__main__":
    unittest.main()


class TestMembership(unittest.TestCase):
    """Membership is a profile fact, expanded once, not re-invented per template.

    `core/provenance` finds the model by co-location; a field session hand-wrote a bounded
    folder path for the same question. Both are right for *some* dataset, which is exactly
    why neither belongs in a template.
    """

    #: A profile declaring co-location, because no bundled profile does any more. The
    #: converters emit `arch:inModel`, so the default is the direct edge and
    #: co-location is what a dataset predating it needs.
    COLOCATION = """\
extends: linked-archi-default.yaml
profile: colocation-test
version: 1
description: A dataset whose model is declared in its own semantic graph.
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

    #: Co-location on a dataset with no named graphs - the combination that cannot express
    #: membership at all. `flattened-turtle` no longer exhibits it: it inherits the direct
    #: edge, which needs no graphs, so the same question became answerable there.
    COLOCATION_FLAT = """\
extends: examples/flattened-turtle.yaml
profile: colocation-flat-test
version: 1
description: Flattened Turtle read with co-location membership.
navigation:
  model_membership:
    mode: same-graph-colocation
"""

    @classmethod
    def setUpClass(cls):
        cls._written = []
        for name, body in (("_colocation-test", cls.COLOCATION),
                           ("_colocation-flat-test", cls.COLOCATION_FLAT)):
            path = support.ROOT / f"skills/linked-archi-profile/assets/profiles/{name}.yaml"
            path.write_text(body, encoding="utf-8")
            cls._written.append(path)

    @classmethod
    def tearDownClass(cls):
        for path in cls._written:
            path.unlink(missing_ok=True)

    def setUp(self):
        self.direct = support.load_resolved_profile("linked-archi-default")
        self.colocation = support.load_resolved_profile("_colocation-test")
        self.folders = support.load_resolved_profile("examples/cloudplatform")

    def test_the_converter_default_is_the_direct_predicate(self):
        """It supersedes both others where it exists: one hop, on every concept.

        This used to assert co-location, measured from fixtures that turned out to predate
        the emitter. `arch:inModel` needs neither graph co-location nor a complete
        folder chain, so it is the default now and co-location is the fallback.
        """
        self.assertEqual(self.direct.model_membership()[0], "direct-predicate")

    def test_the_direct_predicate_binds_the_model_in_one_hop(self):
        pattern = membership_pattern(self.direct, "element")
        self.assertIn("inModel", pattern)
        self.assertIn("?element", pattern, "the edge starts at the subject")
        self.assertNotIn(
            "a <https://meta.linked.archi/core#Model>", pattern,
            "the model lives in another graph, so a class test here matches nothing",
        )

    def test_colocation_binds_the_model_without_a_traversal(self):
        pattern = membership_pattern(self.colocation, "element")
        self.assertIn("?model a <", pattern)
        self.assertNotIn("isPartOf", pattern)
        self.assertNotIn("?element", pattern, "co-location needs no path from the subject")

    def test_the_folder_mode_walks_part_of_from_the_named_subject(self):
        pattern = membership_pattern(self.folders, "concept")
        self.assertIn("?concept (", pattern)
        self.assertIn("isPartOf", pattern)
        self.assertIn("?model a <", pattern)

    def test_the_walk_is_capped_alternation_not_an_unbounded_path(self):
        """SPARQL 1.1 has no {1,n} range, and `+` turns a wrong hop into a full scan."""
        pattern = membership_pattern(self.folders, "element")
        mode, depth = self.folders.model_membership()
        self.assertEqual(mode, "bounded-folder-tree")
        self.assertEqual(pattern.count("|"), depth - 1, "one alternative per hop count")
        self.assertNotIn(">+", pattern)
        self.assertNotIn(">*", pattern)

    def test_both_modes_bind_the_same_variable_so_templates_do_not_branch(self):
        for profile in (self.direct, self.colocation, self.folders):
            with self.subTest(profile.name):
                self.assertIn("?model", membership_pattern(profile, "element"))

    def test_a_template_using_it_renders_under_either_mode(self):
        catalog = load_catalog()
        for profile in (self.direct, self.colocation, self.folders):
            with self.subTest(profile.name):
                rendered = render(
                    "notation/bpmn/process-components",
                    profile,
                    {"MODEL_IRI": support.BPMN_MODEL},
                    catalog=catalog,
                )
                self.assertIn("?model", rendered.query)
                # The prose header keeps `{{MEMBERSHIP:element}}` as documentation, so
                # only the code below the PREFIX block must be fully expanded.
                code = rendered.query.split("PREFIX", 1)[1]
                self.assertNotIn("{{", code)

    def test_the_directive_needs_a_subject_variable(self):
        with self.assertRaises(RenderError):
            render_literal("{{MEMBERSHIP:}}", self.colocation)

    def test_colocation_without_named_graphs_is_refused_not_answered(self):
        """The failure mode found by running it: a cross product that names a model.

        With no graphs, co-location reduces to "?model is a model", which is true of
        every model in the dataset. Against the flattened fixture that returned a LeanIX
        element attributed to the Backstage catalogue - a wrong answer, which is worse
        than a refusal.
        """
        flat = support.load_resolved_profile("_colocation-flat-test")
        catalog = load_catalog()
        for name, params in (
            ("core/define-term", {"TERM": "order"}),
            ("notation/bpmn/process-components", {"MODEL_IRI": support.BPMN_MODEL}),
        ):
            with self.subTest(name):
                verdict = catalog.get(name).check(flat)
                self.assertFalse(verdict.ok)
                reason = " ".join(verdict.unmet)
                self.assertIn("model_membership", reason)
                self.assertIn("bounded-folder-tree", reason, "name the way out")
                with self.assertRaises(UnsupportedTemplate):
                    render(name, flat, params, catalog=catalog)

    def test_the_refusal_is_about_colocation_not_membership_as_such(self):
        """Two ways out of it, and both are real.

        A folder walk needs no graphs, and neither does the direct edge - which is why
        `flattened-turtle` itself now expresses membership fine, having inherited it.
        """
        self.assertIsNotNone(
            support.load_resolved_profile("_colocation-flat-test").membership_gap()
        )
        for name in ("examples/cloudplatform", "flattened-turtle"):
            with self.subTest(profile=name):
                self.assertIsNone(support.load_resolved_profile(name).membership_gap())

    def test_an_ad_hoc_query_is_cautioned_rather_than_refused(self):
        """A hand-written query may know something the profile does not; it still says so."""
        flat = support.load_resolved_profile("_colocation-flat-test")
        rendered = render_literal(
            "{{PREFIXES}}\nSELECT ?model WHERE { {{MEMBERSHIP:element}} }", flat
        )
        self.assertTrue(rendered.warnings)
        self.assertIn("co-location", " ".join(rendered.warnings))

    def test_a_profile_that_can_express_membership_raises_no_caveat(self):
        rendered = render_literal(
            "{{PREFIXES}}\nSELECT ?model WHERE { {{GRAPH_OPEN:semantic}} "
            "{{MEMBERSHIP:element}} {{GRAPH_CLOSE}} }",
            self.colocation,
        )
        self.assertEqual(rendered.warnings, ())


class TestTrailingRowLimit(unittest.TestCase):
    """The cap a hand-written query applies, read off the query itself.

    There is no parameter to read it from for an ad-hoc query, and the profile's
    `default_row_limit` is not a stand-in: using it reported a complete 1282-row result
    as truncated and a result genuinely capped at 5 as complete.
    """

    def test_a_trailing_limit_is_found(self):
        self.assertEqual(
            trailing_row_limit("SELECT ?s WHERE { ?s ?p ?o } LIMIT 25"), 25
        )

    def test_no_limit_means_no_cap_rather_than_an_unknown_one(self):
        """`None` is a statement: nothing was capped, so nothing can have been cut."""
        self.assertIsNone(trailing_row_limit("SELECT ?s WHERE { ?s ?p ?o }"))

    def test_an_offset_after_the_limit_does_not_hide_it(self):
        self.assertEqual(
            trailing_row_limit("SELECT ?s WHERE { ?s ?p ?o } LIMIT 50 OFFSET 100"), 50
        )

    def test_offset_before_limit_is_read_too(self):
        self.assertEqual(
            trailing_row_limit("SELECT ?s WHERE { ?s ?p ?o } OFFSET 100 LIMIT 50"), 50
        )

    def test_a_subquery_limit_is_not_the_result_cap(self):
        """It bounds an inner solution set, not the rows that come back.

        Reading it as the cap would report a complete result as truncated whenever the
        inner limit happened to match the row count.
        """
        query = (
            "SELECT ?s WHERE { { SELECT ?s WHERE { ?s ?p ?o } LIMIT 10 } ?s a ?t }"
        )
        self.assertIsNone(trailing_row_limit(query))

    def test_a_limit_in_a_comment_is_not_a_cap(self):
        query = "SELECT ?s WHERE { ?s ?p ?o }\n# ORDER BY ?s LIMIT 10\n"
        self.assertIsNone(trailing_row_limit(query))

    def test_a_trailing_semicolon_and_whitespace_do_not_hide_it(self):
        self.assertEqual(
            trailing_row_limit("SELECT ?s WHERE { ?s ?p ?o } LIMIT 7 ;\n\n"), 7
        )

    def test_case_does_not_matter(self):
        self.assertEqual(
            trailing_row_limit("select ?s where { ?s ?p ?o } limit 12"), 12
        )


class TestRenderedCarriesTheRowCap(unittest.TestCase):
    """One producer of the effective cap, because two producers disagreed.

    `truncated` was computed by the caller: `run` from its own `--set LIMIT` and
    `literal` from the profile's `default_row_limit`. 20 of 36 templates declare a
    default that is not 200, so most of the catalogue was measured against the wrong
    number - including `core/resolve-element`, whose default of 25 made a capped
    resolution look complete.
    """

    def setUp(self):
        self.profile = load_profile("linked-archi-default")
        self.catalog = load_catalog()

    def _rendered(self, template, params):
        return render(template, self.profile, params, catalog=self.catalog)

    def test_an_explicit_limit_is_carried(self):
        self.assertEqual(self._rendered("core/inventory", {"LIMIT": 42}).row_limit, 42)

    def test_a_template_default_is_carried_not_the_profile_default(self):
        """The number in the QUERY, which is the only one that bounds the result."""
        rendered = self._rendered("core/resolve-element", {"TERM": "order"})
        self.assertEqual(rendered.row_limit, 25)
        self.assertIn("LIMIT 25", rendered.query)

    def test_it_matches_the_rendered_query_for_every_template(self):
        """No template may carry a cap that differs from the one it executes.

        Under the curated profile, which binds every role, so this covers the whole
        catalogue rather than the subset the default profile supports.
        """
        curated = load_profile("curated-store")
        checked = 0
        for entry in self.catalog:
            if not entry.check(curated).ok:
                continue
            params = {"LIMIT": entry.parameters["LIMIT"]["default"]}
            for name, other in entry.parameters.items():
                if name == "LIMIT" or "default" in other:
                    continue
                params[name] = _placeholder_for(other["type"])
            with self.subTest(entry.name):
                rendered = render(entry.name, curated, params, catalog=self.catalog)
                self.assertEqual(
                    rendered.row_limit, trailing_row_limit(rendered.query),
                    f"{entry.name} carries a cap its query does not apply",
                )
            checked += 1
        self.assertEqual(
            checked, len(self.catalog),
            "the curated profile is meant to support every template",
        )

    def test_a_literal_query_carries_what_it_wrote(self):
        rendered = render_literal(
            "SELECT ?s WHERE { {{GRAPH_OPEN:semantic}} ?s ?p ?o {{GRAPH_CLOSE}} } LIMIT 9",
            self.profile,
        )
        self.assertEqual(rendered.row_limit, 9)

    def test_a_literal_query_with_no_limit_carries_none(self):
        rendered = render_literal(
            "SELECT ?s WHERE { {{GRAPH_OPEN:semantic}} ?s ?p ?o {{GRAPH_CLOSE}} }",
            self.profile,
        )
        self.assertIsNone(rendered.row_limit)


def _placeholder_for(kind: str):
    """A value of the right type for a required parameter this test does not care about."""
    if kind in {"iri", "iri_list", "iri_path"}:
        return "https://example.org/la/placeholder"
    if kind == "integer":
        return 1
    return "placeholder"


class TestProfileRowCeiling(unittest.TestCase):
    """`limits.max_row_limit` bounds a row limit, which it did not used to.

    Two ceilings exist and are set by different people: a template's `max` describes the
    query's shape, and a profile's `max_row_limit` describes what the dataset or endpoint
    will stand. Only the template's was ever consulted, so a profile declaring
    `max_row_limit: 20` rendered `LIMIT 1500` without complaint - while five documents
    said it would be refused.
    """

    #: `max_row_limit` far below what the templates permit, so the profile's ceiling is
    #: unambiguously the binding one. `core/inventory` allows up to 2000.
    TIGHT = """\
extends: linked-archi-default.yaml
profile: tight-ceiling-test
version: 1
description: A profile whose row ceiling is below what templates permit.
limits:
  default_row_limit: 10
  max_row_limit: 20
  timeout_ms: 30000
"""

    @classmethod
    def setUpClass(cls):
        cls._path = (
            support.ROOT
            / "skills/linked-archi-profile/assets/profiles/_tight-ceiling-test.yaml"
        )
        cls._path.write_text(cls.TIGHT, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._path.unlink(missing_ok=True)

    def setUp(self):
        self.tight = support.load_resolved_profile("_tight-ceiling-test")
        self.catalog = load_catalog()

    def test_an_explicit_request_above_the_ceiling_is_refused(self):
        with self.assertRaises(RenderError) as caught:
            render("core/inventory", self.tight, {"LIMIT": 1500}, catalog=self.catalog)
        message = str(caught.exception)
        self.assertIn("max_row_limit 20", message)
        self.assertIn("tight-ceiling-test", message)

    def test_the_refusal_names_the_profile_rather_than_the_template(self):
        """Because the fix is in the profile. Telling the reader to edit the template's
        `max` would be the wrong instruction and the wrong file."""
        with self.assertRaises(RenderError) as caught:
            render("core/inventory", self.tight, {"LIMIT": 1500}, catalog=self.catalog)
        self.assertIn("limits.max_row_limit", str(caught.exception))

    def test_a_request_at_the_ceiling_is_allowed(self):
        rendered = render(
            "core/inventory", self.tight, {"LIMIT": 20}, catalog=self.catalog
        )
        self.assertEqual(rendered.row_limit, 20)

    def test_a_template_default_above_the_ceiling_is_clamped_not_refused(self):
        """The caller did nothing wrong, so refusing would make the template unusable
        for a reason they cannot see."""
        rendered = render("core/inventory", self.tight, catalog=self.catalog)
        self.assertEqual(rendered.row_limit, 20)
        self.assertIn("LIMIT 20", rendered.query)

    def test_a_clamped_default_says_so(self):
        """Clamping silently is the other trap: the rows would be a floor and nothing
        would say it."""
        rendered = render("core/inventory", self.tight, catalog=self.catalog)
        clamped = [w for w in rendered.warnings if "max_row_limit" in w]
        self.assertTrue(clamped, f"no caveat about the clamp in {rendered.warnings}")
        self.assertIn("LIMIT 300", clamped[0])
        self.assertIn("LIMIT 20", clamped[0])

    def test_the_template_ceiling_still_applies_under_a_loose_profile(self):
        """The lower of the two wins, whichever one that is."""
        default = load_profile("linked-archi-default")
        with self.assertRaises(RenderError) as caught:
            render("core/inventory", default, {"LIMIT": 2500}, catalog=self.catalog)
        self.assertIn("maximum 2000", str(caught.exception))

    def test_the_lower_ceiling_is_the_one_reported(self):
        """Whichever it is. No bundled template's `max` reaches the bundled 5000, so the
        template's is normally the binding one - and a reader sent to raise
        `max_row_limit` when the template's `max` is what refused them would edit the
        wrong file and see no change. That is what `troubleshooting.md` used to say."""
        default = load_profile("linked-archi-default")
        with self.assertRaises(RenderError) as caught:
            render("core/inventory", default, {"LIMIT": 6000}, catalog=self.catalog)
        message = str(caught.exception)
        self.assertIn("maximum 2000", message)
        self.assertNotIn("max_row_limit", message)
