"""Model questions: the published question sets, read as catalogue entries.

A question set (``arch:QuestionSet``) is the source of truth for every question it holds:
what is asked, why, what a row means and does not prove, the concerns it informs, and the
query. The query is written for ONE graph - the model and its metamodel together, as
la-gram holds them and meta's question check runs them - so a question is asked on the
dataset read as one graph, never scoped by graph role the way a template is.

Two sources, one reader:

- the sets this skill bundles (``assets/questions/``), read from ``index.json``, which
  :func:`refresh` writes from the Turtle beside it. Listing the catalogue therefore needs no
  RDF library, and a test fails when the index and the Turtle disagree;
- a project's own set, passed with ``--catalog set.ttl`` and read when it is passed, which
  needs pyoxigraph.

What a question needs from a dataset is read from what its query reads, by the same rule for
both sources: a direct relationship triple (any published ``arch:unqualifiedForm``) needs
``direct_rel_triples``, ``rdf:reifies`` needs ``rdf_reifies``, ``arch:inModel`` needs
``part_of_model_edge``. A question that declares ``arch:ModelAndMetamodelDataset`` also needs
the metamodel loaded beside the data, which is checked when it runs (:func:`metamodel_probes`).
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

QUESTION_DIR = Path(__file__).resolve().parents[2] / "assets" / "questions"
INDEX_PATH = QUESTION_DIR / "index.json"

#: The bundled sets, by file name, and where each is in a linked-archi-meta checkout.
BUNDLED_SETS: Mapping[str, str] = {
    "core-questions.ttl": "core/core-questions.ttl",
    "archimate4-questions.ttl": "modelingLanguages/archimate/4.0/archimate4-questions.ttl",
    "archimate3.2-questions.ttl": "modelingLanguages/archimate/3.2/archimate3.2-questions.ttl",
}

ARCH = "https://meta.linked.archi/core#"
SH = "http://www.w3.org/ns/shacl#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
DCTERMS = "http://purl.org/dc/terms/"
OWL = "http://www.w3.org/2002/07/owl#"
XSD = "http://www.w3.org/2001/XMLSchema#"

#: A question's parameter, by the core property it is declared on, and the catalogue name it
#: takes. The names templates already use, so one ``--set`` serves either implementation.
PARAMETER_NAMES: Mapping[str, str] = {
    "focus": "FOCUS_IRI",
    "model": "MODEL_IRI",
    "view": "VIEW_IRI",
    "viewpoint": "VIEWPOINT_IRI",
    "conceptType": "TYPE_IRI",
    "from": "FROM_IRI",
    "to": "TO_IRI",
}

#: Investigation stages, as the catalogue spells them, by the core concept.
_STAGES = {
    f"{ARCH}OrientationStage": "orientation",
    f"{ARCH}ResolutionStage": "resolution",
    f"{ARCH}DiscoveryStage": "discovery",
    f"{ARCH}AnalysisStage": "analysis",
    f"{ARCH}EnrichmentStage": "enrichment",
    f"{ARCH}QualityStage": "quality",
    f"{ARCH}ViewsStage": "views",
}
_DATASETS = {
    f"{ARCH}ModelDataset": "model",
    f"{ARCH}ModelAndMetamodelDataset": "model-and-metamodel",
}
_SEVERITIES = {f"{SH}Info": "info", f"{SH}Warning": "warning", f"{SH}Violation": "violation"}


class QuestionError(ValueError):
    """A question set could not be read, or a question could not be built."""


@dataclass(frozen=True)
class Parameter:
    """One ``sh:parameter`` of a question."""

    variable: str
    path: str
    name: str = ""
    optional: bool = False
    order: float = 0
    description: str = ""

    @property
    def catalogue_name(self) -> str:
        return parameter_name(self.variable)


@dataclass(frozen=True)
class Question:
    """One ``arch:ModelQuestion``, as the catalogue reads it."""

    iri: str
    set: str
    identifier: str
    label: str
    text: str
    description: str = ""
    answers: str = ""
    does_not_prove: str = ""
    stage: str = "analysis"
    finding: bool = False
    finding_focus: str = ""
    severity: str = ""
    dataset: str = "model"
    metamodels: tuple[str, ...] = ()
    concerns: tuple[str, ...] = ()
    stakeholders: tuple[str, ...] = ()
    viewpoints: tuple[str, ...] = ()
    result_key: str = ""
    default_limit: int = 200
    prefixes: Mapping[str, str] = field(default_factory=dict)
    parameters: tuple[Parameter, ...] = ()
    #: What the query reads that a dataset may lack - see the module docstring.
    reads: Mapping[str, bool] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Question":
        try:
            return cls(
                **{
                    **raw,
                    "metamodels": tuple(raw.get("metamodels", ())),
                    "concerns": tuple(raw.get("concerns", ())),
                    "stakeholders": tuple(raw.get("stakeholders", ())),
                    "viewpoints": tuple(raw.get("viewpoints", ())),
                    "prefixes": dict(raw.get("prefixes", {})),
                    "parameters": tuple(Parameter(**p) for p in raw.get("parameters", ())),
                    "reads": dict(raw.get("reads", {})),
                }
            )
        except TypeError as exc:
            raise QuestionError(f"malformed question {raw.get('iri', '?')!r}: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def notation(self) -> str | None:
        """``archimate4`` for ``notation/archimate4/...``; ``None`` for a core question."""
        parts = self.identifier.split("/")
        return parts[1] if len(parts) > 2 and parts[0] == "notation" else None

    @property
    def notation_namespace(self) -> str | None:
        """The vocabulary a notation question is written against: its one required metamodel."""
        return self.metamodels[0] if self.notation and len(self.metamodels) == 1 else None

    @property
    def capabilities(self) -> dict[str, bool]:
        """The profile capabilities this question's query needs."""
        return {
            capability: True
            for capability, key in (
                ("direct_rel_triples", "direct_rel_triples"),
                ("rdf_reifies", "rdf_reifies"),
                ("part_of_model_edge", "part_of_model_edge"),
            )
            if self.reads.get(key)
        }


@dataclass(frozen=True)
class Probe:
    """An ASK the dataset must answer true for a question to mean what it says."""

    query: str
    needs: str
    #: Where the missing document is published, when there is one to name.
    load: str = ""


@dataclass(frozen=True)
class QuestionIndex:
    """The bundled question sets, as ``index.json`` holds them."""

    questions: tuple[Question, ...]
    sets: tuple[Mapping[str, Any], ...] = ()
    unqualified_forms: frozenset[str] = frozenset()
    labels: Mapping[str, str] = field(default_factory=dict)


def parameter_name(variable: str) -> str:
    """The catalogue name for a question's parameter variable."""
    if variable in PARAMETER_NAMES:
        return PARAMETER_NAMES[variable]
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", variable).upper()
    return f"{snake}_IRI"


def catalogue_parameters(question: Question) -> dict[str, dict[str, Any]]:
    """A question's parameters under their catalogue names, and the LIMIT it takes.

    Every parameter is an IRI. One the question declares ``sh:optional`` is ``optional``
    here: left unset, the question answers for every value rather than for one.
    """
    specs: dict[str, dict[str, Any]] = {}
    for parameter in question.parameters:
        spec: dict[str, Any] = {
            "type": "iri",
            "description": parameter.description or parameter.name,
        }
        if parameter.optional:
            spec["optional"] = True
        specs[parameter.catalogue_name] = spec
    specs["LIMIT"] = {
        "type": "integer",
        "description": "maximum rows",
        "default": question.default_limit,
        "min": 1,
        "max": max(2000, question.default_limit),
    }
    return specs


def published_turtle(namespace: str) -> str:
    """Where meta.linked.archi serves a document's Turtle: its namespace path + ``/ontology.ttl``."""
    return namespace.rstrip("#/") + "/ontology.ttl"


def metamodel_probes(question: Question) -> tuple[Probe, ...]:
    """What must be loaded beside the data for ``question`` to mean what it says.

    Only for a question that declares ``arch:ModelAndMetamodelDataset``: one that reads model
    data alone needs nothing more. Without the metamodel such a question does not fail - it
    answers from type sets of one type and a viewpoint catalogue of none, which reads as an
    answer - so it is checked, not assumed.
    """
    if question.dataset != "model-and-metamodel":
        return ()
    probes = [
        Probe(
            query=f"ASK {{ <{ontology}> a <{OWL}Ontology> }}",
            needs=f"the ontology {ontology}",
            load=published_turtle(ontology),
        )
        for ontology in question.metamodels
    ]
    if question.reads.get("viewpoints"):
        probes.append(Probe(
            query=f"ASK {{ ?viewpoint <{ARCH}includesConcept> ?concept }}",
            needs="the viewpoint catalogue of the model's language (viewpoints and the concepts each includes)",
            load=_viewpoint_catalogue(question),
        ))
    if question.reads.get("unqualified_forms"):
        probes.append(Probe(
            query=f"ASK {{ ?relationshipClass <{ARCH}unqualifiedForm> ?predicate }}",
            needs="the ontology of the model's language (each relationship's arch:unqualifiedForm)",
        ))
    return tuple(probes)


def _viewpoint_catalogue(question: Question) -> str:
    for ontology in question.metamodels:
        if ontology.endswith("/onto#"):
            return published_turtle(ontology[: -len("onto#")] + "viewpoints#")
    return ""


# ---------------------------------------------------------------------------
# Building a question's query
# ---------------------------------------------------------------------------

_MASKED = re.compile(
    r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|#[^\n]*'
)
_IRI = re.compile(r"<[^<>\"{}|^`\\\s]*>")


def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def mask(sparql: str) -> str:
    """The query with strings, IRIs and comments blanked, offsets kept."""
    return _IRI.sub(_blank, _MASKED.sub(_blank, sparql))


def where_group_start(sparql: str) -> int:
    """Offset of the ``{`` opening the outermost WHERE group, or -1."""
    masked = mask(sparql)
    where = re.search(r"\bWHERE\b", masked, re.IGNORECASE)
    return masked.find("{", where.end() if where else 0)


def dedent(text: str) -> str:
    lines = re.sub(r"^\s*\n", "", text).rstrip().split("\n")
    indents = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(line[cut:] for line in lines)


def build_query(question: Question, bindings: Mapping[str, str], limit: int | None) -> str:
    """Prefixes, the question with ``bindings`` pre-bound, and a LIMIT.

    ``bindings`` maps a parameter's variable to a bracketed IRI already checked by the
    caller. Each becomes ``VALUES ?var { <iri> }`` at the start of the outermost WHERE group -
    where la-gram and meta's question check put it, so the three run the same text.
    """
    declared = {p.variable for p in question.parameters}
    clauses = []
    for variable, iri in bindings.items():
        if variable not in declared:
            raise QuestionError(f"{question.identifier} has no parameter ?{variable}")
        if not re.fullmatch(r"\w+", variable) or not _IRI.fullmatch(iri):
            raise QuestionError(f"cannot bind ?{variable} to {iri!r}")
        clauses.append(f"VALUES ?{variable} {{ {iri} }}")
    body = question.text
    if clauses:
        at = where_group_start(body)
        if at < 0:
            raise QuestionError(f"{question.identifier}: no WHERE group to bind parameters in")
        body = body[: at + 1] + "\n  " + "\n  ".join(clauses) + body[at + 1:]
    if limit is not None:
        body += f"\nLIMIT {int(limit)}"
    prologue = "\n".join(
        f"PREFIX {prefix}: <{namespace}>" for prefix, namespace in sorted(question.prefixes.items())
    )
    return f"{prologue}\n\n{body}\n"


# ---------------------------------------------------------------------------
# What a query reads
# ---------------------------------------------------------------------------

_PREFIXED = re.compile(r"(?<![\w?$:/#])([A-Za-z][\w-]*)?:([A-Za-z0-9_][\w-]*)")


def terms_read(text: str, prefixes: Mapping[str, str]) -> set[str]:
    """Every IRI the query names, prefixed names expanded."""
    stripped = _MASKED.sub(_blank, text)
    found = {match.group(0)[1:-1] for match in _IRI.finditer(stripped)}
    for match in _PREFIXED.finditer(_IRI.sub(_blank, stripped)):
        namespace = prefixes.get(match.group(1) or "")
        if namespace is not None:
            found.add(namespace + match.group(2))
    return found


def reads(text: str, prefixes: Mapping[str, str], unqualified_forms: Iterable[str]) -> dict[str, bool]:
    terms = terms_read(text, prefixes)
    return {
        "direct_rel_triples": bool(terms & set(unqualified_forms)),
        "rdf_reifies": f"{RDF}reifies" in terms,
        "part_of_model_edge": f"{ARCH}inModel" in terms,
        "viewpoints": bool(terms & {f"{ARCH}includesConcept", f"{ARCH}viewConformsToViewpoint"}),
        "unqualified_forms": f"{ARCH}unqualifiedForm" in terms,
    }


# ---------------------------------------------------------------------------
# Reading question sets
# ---------------------------------------------------------------------------


def _store(paths: Sequence[Path]):
    try:
        from pyoxigraph import RdfFormat, Store
    except ModuleNotFoundError as exc:
        raise QuestionError(
            "Reading a question set needs pyoxigraph:  pip install pyoxigraph"
        ) from exc
    store = Store()
    for path in paths:
        try:
            store.load(path=str(path), format=RdfFormat.TURTLE)
        except (OSError, SyntaxError, ValueError) as exc:
            raise QuestionError(f"Could not read the question set {path}: {exc}") from exc
    return store


def extract(paths: Sequence[Path], unqualified_forms: Iterable[str]) -> list[Question]:
    """Every model question in ``paths``, ordered by identifier."""
    from pyoxigraph import Literal, NamedNode

    store = _store(paths)
    forms = frozenset(unqualified_forms)

    def objects(subject, predicate: str) -> list:
        return [q.object for q in store.quads_for_pattern(subject, NamedNode(predicate), None)]

    def one(subject, predicate: str) -> Any:
        values = objects(subject, predicate)
        literals = [v for v in values if isinstance(v, Literal)]
        if literals:
            # English first, then untagged, as la-gram picks a label.
            for wanted in ("en", None):
                for value in literals:
                    if (value.language or None) == wanted:
                        return value.value
            return literals[0].value
        return values[0].value if values else None

    def iris(subject, predicate: str) -> tuple[str, ...]:
        return tuple(sorted(v.value for v in objects(subject, predicate) if isinstance(v, NamedNode)))

    questions: list[Question] = []
    for quad in store.quads_for_pattern(None, NamedNode(f"{RDF}type"), NamedNode(f"{ARCH}ModelQuestion")):
        subject = quad.subject
        iri = subject.value
        identifier = one(subject, f"{DCTERMS}identifier")
        text = one(subject, f"{SH}select")
        if not identifier or not text:
            raise QuestionError(
                f"{iri} needs a dcterms:identifier and an sh:select to be a catalogue entry"
            )
        prefixes: dict[str, str] = {}
        set_iri = ""
        for declaring in objects(subject, f"{SH}prefixes"):
            set_iri = set_iri or declaring.value
            for declaration in objects(declaring, f"{SH}declare"):
                prefix = one(declaration, f"{SH}prefix")
                namespace = one(declaration, f"{SH}namespace")
                if prefix is not None and namespace:
                    prefixes[str(prefix)] = str(namespace)
        parameters = []
        for node in objects(subject, f"{SH}parameter"):
            path = one(node, f"{SH}path")
            if not path:
                raise QuestionError(f"{iri} declares a parameter without sh:path")
            if objects(node, f"{SH}datatype"):
                raise QuestionError(
                    f"{iri}: parameter {path} takes a literal; only IRI parameters can be bound"
                )
            variable = re.split(r"[#/]", path)[-1]
            order = one(node, f"{SH}order")
            parameters.append(Parameter(
                variable=variable,
                path=path,
                name=str(one(node, f"{SH}name") or variable),
                optional=str(one(node, f"{SH}optional")).lower() == "true",
                order=float(order) if order is not None else 0,
                description=str(one(node, f"{SH}description") or ""),
            ))
        parameters.sort(key=lambda p: (p.order, p.variable))
        limit = one(subject, f"{ARCH}defaultLimit")
        query = dedent(str(text))
        questions.append(Question(
            iri=iri,
            set=set_iri,
            identifier=str(identifier),
            label=str(one(subject, f"{SKOS}prefLabel") or identifier),
            text=query,
            description=str(one(subject, f"{DCTERMS}description") or ""),
            answers=str(one(subject, f"{ARCH}answers") or ""),
            does_not_prove=str(one(subject, f"{ARCH}doesNotProve") or ""),
            stage=_STAGES.get(str(one(subject, f"{ARCH}questionStage")), "analysis"),
            finding=str(one(subject, f"{ARCH}resultIsFinding")).lower() == "true",
            finding_focus=str(one(subject, f"{ARCH}findingFocus") or ""),
            severity=_SEVERITIES.get(str(one(subject, f"{ARCH}findingSeverity")), ""),
            dataset=_DATASETS.get(str(one(subject, f"{ARCH}requiresDataset")), "model"),
            metamodels=iris(subject, f"{ARCH}requiresMetamodel"),
            concerns=iris(subject, f"{ARCH}questionAddressesConcern"),
            stakeholders=iris(subject, f"{ARCH}questionTargetsStakeholder"),
            viewpoints=iris(subject, f"{ARCH}questionFitsViewpoint"),
            result_key=str(one(subject, f"{ARCH}resultKey") or ""),
            default_limit=int(limit) if limit is not None else 200,
            prefixes=prefixes,
            parameters=tuple(parameters),
            reads=reads(query, prefixes, forms),
        ))
    questions.sort(key=lambda q: q.identifier)
    seen: dict[str, str] = {}
    for question in questions:
        if question.identifier in seen:
            raise QuestionError(
                f"{question.identifier} names two questions: {seen[question.identifier]} "
                f"and {question.iri}"
            )
        seen[question.identifier] = question.iri
    return questions


def load_index(path: Path = INDEX_PATH) -> QuestionIndex:
    """The bundled sets. Standard library only: no RDF is parsed here."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return QuestionIndex(questions=())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QuestionError(f"Could not read {path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("version") != 1:
        raise QuestionError(f"{path.name} must be version 1")
    return QuestionIndex(
        questions=tuple(Question.from_dict(q) for q in document.get("questions", ())),
        sets=tuple(document.get("sets", ())),
        unqualified_forms=frozenset(document.get("unqualified_forms", ())),
        labels=dict(document.get("labels", {})),
    )


def read_set(path: Path, index: QuestionIndex | None = None) -> list[Question]:
    """A project's question set, read when ``--catalog`` names it."""
    index = index if index is not None else load_index()
    return extract([path], index.unqualified_forms)


# ---------------------------------------------------------------------------
# Refreshing the bundled sets (maintainers, from a linked-archi-meta checkout)
# ---------------------------------------------------------------------------


def refresh(meta_root: Path, target: Path = QUESTION_DIR) -> Path:
    """Copy the published sets from ``meta_root`` and write ``index.json`` from them.

    The unqualified forms and the labels of concerns, stakeholders and viewpoints are read
    from every Turtle file of meta's core and modelling languages, so the index can decide
    what a query reads and name what it informs without the metamodel at hand.
    """
    meta_root = meta_root.resolve()
    target.mkdir(parents=True, exist_ok=True)
    for name, relative in BUNDLED_SETS.items():
        source = meta_root / relative
        if not source.is_file():
            raise QuestionError(f"no question set at {source}")
        shutil.copyfile(source, target / name)

    vocabulary = sorted(
        set(meta_root.glob("core/*.ttl")) | set(meta_root.glob("modelingLanguages/**/*.ttl"))
    )
    from pyoxigraph import NamedNode

    store = _store(vocabulary)
    forms = sorted({
        quad.object.value
        for quad in store.quads_for_pattern(None, NamedNode(f"{ARCH}unqualifiedForm"), None)
        if isinstance(quad.object, NamedNode)
    })
    paths = [target / name for name in BUNDLED_SETS]
    questions = extract(paths, forms)

    labels: dict[str, str] = {}
    concepts = sorted({
        concept
        for question in questions
        for concept in question.concerns + question.stakeholders + question.viewpoints
    })
    for concept in concepts:
        best = None
        for quad in store.quads_for_pattern(NamedNode(concept), NamedNode(f"{SKOS}prefLabel"), None):
            if best is None or (quad.object.language or "") == "en":
                best = quad.object.value
        labels[concept] = best or re.split(r"[#/]", concept)[-1]

    sets = []
    for name in BUNDLED_SETS:
        single = _store([target / name])
        roots = [
            quad.subject.value
            for quad in single.quads_for_pattern(None, NamedNode(f"{RDF}type"), NamedNode(f"{ARCH}QuestionSet"))
        ]
        version = None
        if roots:
            version = next(
                (q.object.value for q in single.quads_for_pattern(
                    NamedNode(roots[0]), NamedNode(f"{OWL}versionInfo"), None)),
                None,
            )
        sets.append({
            "file": name,
            "iri": roots[0] if roots else "",
            "version": version or "",
            "published": published_turtle(roots[0]) if roots else "",
        })

    document = {
        "version": 1,
        "_comment": (
            "Generated from the question sets beside this file by `make questions`; do not "
            "edit. tests/test_questions.py fails when it and the Turtle disagree."
        ),
        "sets": sets,
        "unqualified_forms": forms,
        "labels": labels,
        "questions": [question.to_dict() for question in questions],
    }
    index = target / "index.json"
    index.write_text(json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return index


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python3 -m linked_archi_query.questions",
        description="Refresh the bundled question sets from a linked-archi-meta checkout.",
    )
    parser.add_argument("--refresh", metavar="META_ROOT", required=True)
    args = parser.parse_args(argv)
    written = refresh(Path(args.refresh))
    count = len(load_index(written).questions)
    print(f"Wrote {written} ({count} questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
