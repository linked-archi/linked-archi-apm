"""Model questions, read from the published question sets as catalogue entries.

A question set is the source of truth for what it asks (D10 of the la-queries design), and
this skill reads it rather than keeping a copy of its own. Four things are tested here:

- the bundled index says what the bundled Turtle says;
- a question and a template of one name are one entry, the same question implemented twice;
- a question is asked of the dataset read as ONE graph, refused where that cannot be done,
  and refused - or answered by its template - where the metamodel it reads is not loaded;
- asked through this skill, every question answers meta's example models exactly as meta's
  own question check expects, on the flattened model and on the model in converter graphs.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import support
from support import FIXTURES, requires_pyoxigraph

from linked_archi_query import load_catalog, render
from linked_archi_query.catalog import CatalogError
from linked_archi_query.questions import (
    BUNDLED_SETS,
    INDEX_PATH,
    QUESTION_DIR,
    extract,
    load_index,
    metamodel_probes,
    parameter_name,
)
from linked_archi_query.render import RenderError, UnsupportedTemplate

QUESTIONS = FIXTURES / "questions"
PROFILES = support.ROOT / "skills" / "linked-archi-profile" / "assets" / "profiles"

#: meta's two question examples, and the documents its question check loads beside each.
EXAMPLES = {
    "archimate4": (
        "archimate4-questions-example",
        ("core-onto.ttl", "archimate4-onto.ttl", "archimate4-viewpoints.ttl"),
    ),
    "archimate3.2": (
        "archimate3.2-questions-example",
        ("core-onto.ttl", "archimate3.2-onto.ttl", "archimate3.2-viewpoints.ttl"),
    ),
}


def _profile(directory: Path, *, named_graphs: bool, direct: bool = True) -> object:
    """A profile every bundled question fits: both ArchiMate notations, the direct triples."""
    base = PROFILES / ("linked-archi-default.yaml" if direct else "linked-archi-qualified.yaml")
    single = """
graphs:
  layout: single
  named_graphs: false
  roles:
    semantic: graph/semantic
    views: graph/views
    provenance: graph/provenance
    model: graph/model
  descendants: []
"""
    path = directory / f"questions-{'trig' if named_graphs else 'flat'}-{int(direct)}.yaml"
    path.write_text(
        f"extends: {base.as_posix()}\n"
        f"profile: questions-{'trig' if named_graphs else 'flat'}\n"
        "version: 1\n"
        "description: >-\n  meta's question examples.\n"
        + ("" if named_graphs else single)
        + """notations:
  archimate4:
    label: ArchiMate 4.0
    metamodel: https://meta.linked.archi/archimate4/metamodel#ArchiMate4
    namespace: am4
""",
        encoding="utf-8",
    )
    return support.load_resolved_profile(str(path))


def _expected(name: str) -> tuple[dict[str, str], list[tuple[str, dict[str, str], str, set[str], int]]]:
    """The defaults and cases of an expected file, as meta's QuestionRunner reads them."""
    prefixes: dict[str, str] = {}
    defaults: dict[str, str] = {}
    cases = []

    def expand(value: str) -> str:
        prefix, _, local = value.partition(":")
        return prefixes[prefix] + local if local and prefix in prefixes else value

    def bindings(cell: str) -> dict[str, str]:
        if cell.strip() == "-":
            return {}
        return {
            pair.split("=", 1)[0]: expand(pair.split("=", 1)[1])
            for pair in cell.split()
        }

    lines = (QUESTIONS / f"{name}.expected.tsv").read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.split("\t")
        if cells[0] == "@prefix":
            prefixes[cells[1]] = cells[2]
            continue
        if cells[0] == "*":
            defaults.update(bindings(cells[1] if len(cells) > 1 else "-"))
            continue
        expected = set() if cells[3].strip() == "-" else {expand(v) for v in cells[3].split()}
        cases.append((expand(cells[0]), bindings(cells[1]), cells[2], expected, number))
    return defaults, cases


def _column(rows: list[dict[str, str]], column: str) -> set[str]:
    """A result column's values, a GROUP_CONCAT's split, as QuestionRunner compares them."""
    values: set[str] = set()
    for row in rows:
        value = row.get(column, "")
        if value:
            values.update(value.split("; "))
    return values


def _converter_graphs(source: Path, target: Path) -> None:
    """The flattened example as the converters lay a model out: its data in named graphs."""
    from pyoxigraph import NamedNode, Quad, RdfFormat, Store

    flat = Store()
    flat.load(path=str(source), format=RdfFormat.TURTLE)
    base = "https://example.org/la/model/questions-example/graph/"
    graphed = Store()
    for quad in flat:
        graph = "model" if quad.subject.value.endswith("/model") else "semantic"
        graphed.add(Quad(quad.subject, quad.predicate, quad.object, NamedNode(base + graph)))
    graphed.dump(str(target), format=RdfFormat.TRIG)


class TestTheIndexIsTheTurtle(unittest.TestCase):
    """The bundled index is generated; this is what makes it safe to read without RDF."""

    def setUp(self):
        requires_pyoxigraph(self)

    def test_the_index_holds_what_the_bundled_sets_say(self):
        index = load_index()
        read = extract([QUESTION_DIR / name for name in BUNDLED_SETS], index.unqualified_forms)
        self.assertEqual(
            [q.to_dict() for q in read], [q.to_dict() for q in index.questions],
            "assets/questions/index.json disagrees with the Turtle beside it: run `make questions`",
        )

    def test_every_bundled_set_is_indexed_with_where_it_is_published(self):
        index = load_index()
        self.assertEqual([s["file"] for s in index.sets], list(BUNDLED_SETS))
        for entry in index.sets:
            self.assertTrue(entry["iri"].startswith("https://meta.linked.archi/"), entry)
            self.assertTrue(entry["published"].endswith("/ontology.ttl"), entry)

    def test_fifty_five_questions_core_archimate_4_and_3_2(self):
        identifiers = [q.identifier for q in load_index().questions]
        self.assertEqual(len(identifiers), 55)
        self.assertEqual(sum(i.startswith("core/") for i in identifiers), 16)
        self.assertEqual(sum(i.startswith("notation/archimate4/") for i in identifiers), 20)
        self.assertEqual(sum(i.startswith("notation/archimate/") for i in identifiers), 19)


class TestWhatAQuestionReads(unittest.TestCase):
    """Requirements come from the query, by one rule for bundled and project sets."""

    def setUp(self):
        self.by_id = {q.identifier: q for q in load_index().questions}

    def test_a_direct_relationship_triple_needs_the_capability(self):
        question = self.by_id["notation/archimate/unrealised-capabilities"]
        self.assertTrue(question.reads["direct_rel_triples"])
        self.assertEqual(question.capabilities, {"direct_rel_triples": True, "part_of_model_edge": True})

    def test_a_question_on_qualified_relationships_needs_no_direct_triple(self):
        for name in ("core/neighbours-qualified", "core/dependents-qualified",
                     "notation/archimate/layer-crossing", "notation/archimate/data-access"):
            self.assertFalse(self.by_id[name].reads["direct_rel_triples"], name)

    def test_the_bridge_audit_needs_the_bridge(self):
        self.assertEqual(self.by_id["core/reifies-audit"].capabilities, {"rdf_reifies": True})

    def test_a_metamodel_question_checks_what_it_reads_is_loaded(self):
        probes = metamodel_probes(self.by_id["notation/archimate4/viewpoint-scope"])
        self.assertEqual(
            [p.load for p in probes],
            ["https://meta.linked.archi/archimate4/onto/ontology.ttl",
             "https://meta.linked.archi/archimate4/viewpoints/ontology.ttl"],
        )
        # The unknown-viewpoint question reports what no loaded catalogue defines: without
        # one, every view would be reported.
        self.assertEqual(len(metamodel_probes(self.by_id["core/unknown-viewpoints"])), 1)
        self.assertEqual(metamodel_probes(self.by_id["core/orphans"]), ())

    def test_parameters_take_the_names_templates_use(self):
        self.assertEqual(parameter_name("focus"), "FOCUS_IRI")
        self.assertEqual(parameter_name("conceptType"), "TYPE_IRI")
        self.assertEqual(parameter_name("fromPlateau"), "FROM_PLATEAU_IRI")
        variables = {p.variable for q in self.by_id.values() for p in q.parameters}
        self.assertEqual(variables, {"focus", "model", "view", "viewpoint", "conceptType", "from", "to"})


class TestTheCatalogue(unittest.TestCase):
    """One name, one question: a template of the same name is the other implementation."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_questions_join_the_catalogue(self):
        entries = list(self.catalog)
        self.assertEqual(sum(1 for e in entries if e.question), 55)
        self.assertEqual(sum(1 for e in entries if e.file), 43)
        both = sorted(e.name for e in entries if e.file and e.question)
        self.assertEqual(both, [
            "core/dependents-qualified", "core/element-detail", "core/elements-by-type",
            "core/neighbours-qualified", "core/orphans", "core/reifies-audit",
            "core/view-contents-semantic", "core/view-usage-semantic",
            "notation/archimate/layer-crossing",
        ])

    def test_a_question_and_a_template_asking_different_things_have_different_names(self):
        # The template and the question each keep their own entry: these four once shared
        # a name while asking different things.
        for template, question in (
            ("core/inventory", "core/model-inventory"),
            ("core/coverage-gaps", "core/missing-definitions"),
            ("core/label-collisions", "core/duplicate-labels"),
            ("core/lifecycle", "core/architecture-state"),
        ):
            self.assertIsNone(self.catalog.get(template).question, template)
            entry = self.catalog.get(question)
            self.assertFalse(entry.file, question)
            self.assertEqual(entry.question.identifier, question)

    def test_a_question_entry_is_listed_with_what_it_asks(self):
        entry = self.catalog.get("notation/archimate4/unrealised-services")
        self.assertEqual(entry.purpose, "Which services does nothing realise?")
        self.assertEqual(entry.notation, "archimate4")
        self.assertEqual(entry.notation_namespace, "https://meta.linked.archi/archimate4/onto#")
        self.assertIn("Q ", entry.summary_line())
        self.assertIn("Q+T ", self.catalog.get("core/orphans").summary_line())

    def test_concerns_select_questions(self):
        concerns = self.catalog.concerns()
        self.assertIn("core/orphans", concerns["https://meta.linked.archi/core-viewpoints#QualityConcern"])
        self.assertIn(
            "notation/archimate/unrealised-capabilities",
            concerns["https://meta.linked.archi/archimate3/viewpoints#Completeness"],
        )
        self.assertEqual(
            load_index().labels["https://meta.linked.archi/archimate3/viewpoints#Completeness"],
            "Completeness",
        )

    def test_every_question_renders_read_only_with_all_and_with_required_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = _profile(Path(tmp), named_graphs=False)
        iri = "https://example.org/la/x"
        for entry in self.catalog:
            if entry.question is None:
                continue
            every = {p.catalogue_name: iri for p in entry.question.parameters}
            required = {p.catalogue_name: iri for p in entry.question.parameters if not p.optional}
            for values in (every, required):
                rendered = render(
                    entry.name, profile, values, catalog=self.catalog,
                    transport="local", implementation="question",
                )
                self.assertEqual(rendered.implementation, "question")
                self.assertTrue(rendered.query.rstrip().endswith(f"LIMIT {rendered.row_limit}"))
                for name in values:
                    if name != "LIMIT":
                        self.assertIn(f"<{iri}>", rendered.query, entry.name)

    def test_a_required_parameter_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = _profile(Path(tmp), named_graphs=False)
        with self.assertRaisesRegex(RenderError, "FOCUS_IRI"):
            render("notation/archimate/impact-of-change", profile, {}, catalog=self.catalog,
                   transport="local")


class TestWhichImplementationRuns(unittest.TestCase):
    """The question where the dataset fits it, the template elsewhere, a refusal otherwise."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.default = support.load_resolved_profile("linked-archi-default")

    def test_local_data_asks_the_question_as_one_graph(self):
        rendered = render("core/orphans", self.default, {}, catalog=self.catalog, transport="local")
        self.assertEqual(rendered.implementation, "question")
        self.assertEqual(rendered.default_graph, "union")
        self.assertEqual(rendered.question, "https://meta.linked.archi/core-questions#orphans")
        self.assertEqual(rendered.finding, {"focus": "element", "severity": "info"})

    def test_an_endpoint_whose_default_graph_is_not_the_union_gets_the_template(self):
        rendered = render("core/orphans", self.default, {}, catalog=self.catalog, transport="endpoint")
        self.assertEqual(rendered.implementation, "template")
        self.assertIsNone(rendered.default_graph)

    def test_render_only_on_named_graphs_gives_the_sparql_that_runs_as_rendered(self):
        rendered = render("core/orphans", self.default, {}, catalog=self.catalog)
        self.assertEqual(rendered.implementation, "template")

    def test_a_parameter_only_the_question_takes_chooses_the_question(self):
        rendered = render(
            "core/orphans", self.default, {"MODEL_IRI": "https://example.org/la/m"},
            catalog=self.catalog, transport="local",
        )
        self.assertEqual(rendered.implementation, "question")
        with self.assertRaises(UnsupportedTemplate) as refused:
            render("core/orphans", self.default, {"MODEL_IRI": "https://example.org/la/m"},
                   catalog=self.catalog, transport="endpoint")
        self.assertIn("as a template: the template takes no MODEL_IRI", str(refused.exception))

    def test_a_question_reading_direct_triples_is_refused_without_them(self):
        with self.assertRaises(UnsupportedTemplate) as refused:
            render("notation/archimate/unrealised-services",
                   support.load_resolved_profile("linked-archi-qualified"), {},
                   catalog=self.catalog, transport="local")
        self.assertIn("'direct_rel_triples' is False", str(refused.exception))

    def test_an_archimate_4_question_needs_a_profile_speaking_archimate_4(self):
        direct = support.load_resolved_profile("linked-archi-default")
        with self.assertRaises(UnsupportedTemplate) as refused:
            render("notation/archimate4/unrealised-services", direct, {},
                   catalog=self.catalog, transport="local")
        self.assertIn("https://meta.linked.archi/archimate4/onto#", str(refused.exception))
        render("notation/archimate/unrealised-services", direct, {},
               catalog=self.catalog, transport="local")

    def test_an_endpoint_declared_to_read_its_graphs_as_one_takes_the_question_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "union.yaml"
            path.write_text(
                f"extends: {(PROFILES / 'linked-archi-default.yaml').as_posix()}\n"
                "profile: union-endpoint\nversion: 1\ndescription: >-\n  A union default graph.\n"
                "capabilities:\n  union_default_graph: true\n",
                encoding="utf-8",
            )
            profile = support.load_resolved_profile(str(path))
        rendered = render("core/orphans", profile, {}, catalog=self.catalog, transport="endpoint")
        self.assertEqual(rendered.implementation, "question")
        self.assertIsNone(rendered.default_graph)


class TestTheExamplesAnswerAsMetaChecks(unittest.TestCase):
    """Requirement 15.4: every case of meta's expected files, through this skill.

    Twice per example - the model flattened, as meta checks it, and the model in converter
    graphs read as one graph - because the second is how converter output is asked.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import pyoxigraph  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover - environment dependent
            raise unittest.SkipTest("pyoxigraph is not installed")
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.flat = _profile(tmp, named_graphs=False)
        cls.trig = _profile(tmp, named_graphs=True)
        cls.catalog = load_catalog()
        cls.by_iri = {q.iri: q for q in load_index().questions}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _ask(self, adapter, profile, question, bindings, union: bool):
        values = {
            parameter_name(name): value for name, value in bindings.items()
            if name in {p.variable for p in question.parameters}
        }
        rendered = render(
            question.identifier, profile, values, catalog=self.catalog,
            transport="local", implementation="question",
        )
        query, probes = rendered.query, rendered.probes
        self.assertEqual(rendered.default_graph, "union" if union else None)
        mode = "union" if union else None
        for probe in probes:
            self.assertTrue(adapter.execute(probe.query, default_graph=mode).boolean,
                            f"{question.identifier}: {probe.needs}")
        return adapter.execute(query, default_graph=mode).rows

    def _check(self, version: str, union: bool):
        from linked_archi_connect.adapters import open_adapter

        example, documents = EXAMPLES[version]
        model = QUESTIONS / f"{example}.ttl"
        if union:
            model = Path(self.tmp.name) / f"{example}.trig"
            _converter_graphs(QUESTIONS / f"{example}.ttl", model)
        adapter = open_adapter(data=[str(model)] + [str(QUESTIONS / d) for d in documents])
        profile = self.trig if union else self.flat
        defaults, cases = _expected(example)
        self.assertGreater(len(cases), 30)
        wrong = []
        for question_iri, case_bindings, column, expected, line in cases:
            question = self.by_iri[question_iri]
            rows = self._ask(adapter, profile, question, {**defaults, **case_bindings}, union)
            got = _column(rows, column)
            if got != expected:
                wrong.append(f"line {line} {question.identifier}: ?{column} is {sorted(got)}, "
                             f"expected {sorted(expected)}")
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_archimate_4_flattened(self):
        self._check("archimate4", union=False)

    def test_archimate_4_in_converter_graphs(self):
        self._check("archimate4", union=True)

    def test_archimate_3_2_flattened(self):
        self._check("archimate3.2", union=False)

    def test_archimate_3_2_in_converter_graphs(self):
        self._check("archimate3.2", union=True)

    def test_every_question_of_an_example_set_is_asked(self):
        for version, (example, _) in EXAMPLES.items():
            _, cases = _expected(example)
            asked = {self.by_iri[iri].identifier for iri, *_ in cases}
            findings = {
                q.identifier for q in self.by_iri.values()
                if q.finding and (q.identifier.startswith("core/") or
                                  q.notation == ("archimate4" if version == "archimate4" else "archimate"))
            }
            self.assertEqual(findings - asked, set(), version)


class TestOneGraph(unittest.TestCase):
    """The one-graph reading belongs to linked-archi-connect, and is asked for per query."""

    def setUp(self):
        requires_pyoxigraph(self)

    def test_a_triple_in_several_graphs_counts_once(self):
        from linked_archi_connect.adapters import open_adapter

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.trig"
            path.write_text(
                "@prefix : <https://example.org/la/> .\n"
                ":a :p :b .\n"
                ":g1 { :a :p :b . :a :q :c . }\n"
                ":g2 { :a :p :b . }\n",
                encoding="utf-8",
            )
            adapter = open_adapter(data=[str(path)])
            stored = adapter.execute("SELECT * WHERE { ?s ?p ?o }")
            merged = adapter.execute("SELECT * WHERE { ?s ?p ?o }", default_graph="union")
        self.assertEqual(len(stored.rows), 1)
        self.assertIsNone(stored.default_graph)
        self.assertEqual(len(merged.rows), 2)
        self.assertEqual(merged.default_graph, "union")

    def test_an_endpoint_refuses_to_be_read_as_one_graph(self):
        from linked_archi_connect.adapters import AdapterError
        from linked_archi_connect.adapters.endpoint import EndpointAdapter

        adapter = EndpointAdapter.__new__(EndpointAdapter)
        with self.assertRaisesRegex(AdapterError, "union_default_graph"):
            adapter._execute_raw("ASK {}", default_graph="union")


class TestAProjectQuestionSet(unittest.TestCase):
    """`--catalog set.ttl`: a project's own questions, under its own names."""

    SET = """@prefix arch: <https://meta.linked.archi/core#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <https://example.org/questions#> .

<https://example.org/questions#> a arch:QuestionSet ;
    sh:declare [ sh:prefix "arch" ; sh:namespace "https://meta.linked.archi/core#"^^xsd:anyURI ] .

:unnamed a arch:ModelQuestion ;
    dcterms:identifier "IDENTIFIER" ;
    skos:prefLabel "Which elements have no name?"@en ;
    arch:answers "One row per element without a name."@en ;
    arch:doesNotProve "That the element is unnamed in its source."@en ;
    arch:questionStage arch:QualityStage ;
    arch:requiresDataset arch:ModelDataset ;
    arch:defaultLimit 50 ;
    sh:parameter [ sh:path arch:model ; sh:optional true ] ;
    sh:prefixes <https://example.org/questions#> ;
    sh:select \"\"\"
        SELECT ?element WHERE { ?element arch:inModel ?model . }
    \"\"\" .
"""

    def setUp(self):
        requires_pyoxigraph(self)

    def _catalog(self, identifier: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "questions.ttl"
            path.write_text(self.SET.replace("IDENTIFIER", identifier), encoding="utf-8")
            return load_catalog(extensions=[path])

    def test_a_project_question_joins_under_its_own_name(self):
        entry = self._catalog("acme/unnamed-elements").get("acme/unnamed-elements")
        self.assertEqual(entry.implementations, ("question",))
        self.assertEqual(entry.requires.capabilities, {"part_of_model_edge": True})
        self.assertEqual(set(entry.question_parameters), {"MODEL_IRI", "LIMIT"})

    def test_a_reserved_or_taken_name_is_refused(self):
        with self.assertRaisesRegex(CatalogError, "project namespace"):
            self._catalog("core/unnamed-elements")
        with self.assertRaisesRegex(CatalogError, "project namespace"):
            self._catalog("unnamed")


class TestTheCommandLine(unittest.TestCase):
    """What a reader of `catalog show` and `catalog dump` is told."""

    def test_dump_carries_the_question_and_where_each_implementation_runs(self):
        import io
        from contextlib import redirect_stdout

        from linked_archi_query.cli import main

        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["catalog", "dump", "--profile", "linked-archi-default",
                         "--template", "core/orphans", "--template", "core/view-usage"])
        self.assertEqual(code, 0)
        templates = json.loads(out.getvalue())["templates"]
        orphans = templates["core/orphans"]
        self.assertEqual(orphans["implementations"], ["question", "template"])
        self.assertEqual(orphans["runs"], {"local": "question", "endpoint": "template"})
        self.assertEqual(orphans["question"]["concerns"][0]["label"], "Quality")
        self.assertEqual(templates["core/view-usage"]["implementations"], ["template"])
        self.assertNotIn("question", templates["core/view-usage"])

    def test_concern_filters_list_and_dump(self):
        import io
        from contextlib import redirect_stdout

        from linked_archi_query.cli import main

        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["catalog", "dump", "--concern", "completeness"])
        self.assertEqual(code, 0)
        names = set(json.loads(out.getvalue())["templates"])
        self.assertIn("notation/archimate/unrealised-capabilities", names)
        self.assertIn("notation/archimate4/unrealised-capabilities", names)
        self.assertNotIn("core/orphans", names)


class TestPlanningByConcern(unittest.TestCase):
    """Requirement 15.3: linked-archi-analyse selects questions by the concern they inform."""

    def _plan(self, *args: str) -> dict:
        import subprocess
        import sys

        done = subprocess.run(
            [sys.executable, str(support.ROOT / "skills/linked-archi-analyse/scripts/la-analyse"),
             "plan", *args, "--data", "graph.trig", "--json"],
            capture_output=True, text=True, timeout=180, cwd=support.ROOT,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_questions_informing_a_concern_are_the_evidence_in_stage_order(self):
        plan = self._plan("--concern", "Quality", "--profile", "linked-archi-default")
        self.assertEqual(plan["pattern"], "concern")
        evidence = [step["template"] for step in plan["steps"] if step["stage"] == "pattern"]
        self.assertIn("core/orphans", evidence)
        self.assertIn("core/unpresented", evidence)
        self.assertEqual(plan["steps"][0]["template"], "core/inventory-summary")
        self.assertEqual(plan["steps"][-1]["template"], "core/provenance")
        orphans = next(step for step in plan["steps"] if step["template"] == "core/orphans")
        self.assertEqual(orphans["purpose"], "Which elements take part in no relationship?")
        # Optional, so left unset: the question answers for every model.
        self.assertNotIn("MODEL_IRI", orphans["parameters"])

    def test_a_language_the_profile_does_not_declare_is_left_out_and_said(self):
        plan = self._plan("--concern", "Completeness", "--profile", "linked-archi-default")
        planned = {step["template"] for step in plan["steps"]}
        self.assertIn("notation/archimate/unrealised-capabilities", planned)
        self.assertFalse(any(name.startswith("notation/archimate4/") for name in planned))
        self.assertFalse(plan["decisions"])
        self.assertTrue(any("archimate4" in note for note in plan["notes"]))

    def test_a_concern_by_iri_chooses_one_language(self):
        import subprocess
        import sys

        plan = self._plan(
            "--concern", "https://meta.linked.archi/archimate3/viewpoints#Completeness",
            "--profile", "linked-archi-default",
        )
        self.assertFalse(any("left out" in note for note in plan["notes"]))
        self.assertIn(
            "notation/archimate/unrealised-capabilities",
            {step["template"] for step in plan["steps"]},
        )
        # ArchiMate 4.0's concern, on a profile that holds no ArchiMate 4.0: nothing to plan.
        refused = subprocess.run(
            [sys.executable, str(support.ROOT / "skills/linked-archi-analyse/scripts/la-analyse"),
             "plan", "--concern", "https://meta.linked.archi/archimate4/viewpoints#Completeness",
             "--profile", "linked-archi-default"],
            capture_output=True, text=True, timeout=180, cwd=support.ROOT,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("does not declare", refused.stderr)


if __name__ == "__main__":
    unittest.main()
