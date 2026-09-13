"""Running SHACL in-process, with no converter and no JVM.

The shapes themselves are never bundled here: the Linked.Archi ontologies and shape
documents are published separately under their own licence. Pass local shape files, or
acquire the published ones once with `linked-archi-source` - which verifies a digest,
caches by content, and then works offline - and pass the cached paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import coverage as coverage_module
from .errors import ValidateError
from .rdf import LoadedGraphs


@dataclass
class ValidationOutcome:
    conforms: bool
    report_graph: Any
    coverage: coverage_module.Coverage
    rdfs_reasoning: bool


def require_pyshacl() -> Any:
    try:
        import pyshacl
    except ModuleNotFoundError as exc:  # pragma: no cover - environment problem
        raise ValidateError(
            "SHACL validation needs pyshacl: pip install pyshacl. No converter, Java "
            "runtime or network access is required once the shapes are available locally."
        ) from exc
    return pyshacl


def run(
    data: LoadedGraphs,
    shapes: LoadedGraphs,
    ontology: LoadedGraphs | None = None,
    rdfs_reasoning: bool = True,
) -> ValidationOutcome:
    """Validate the data graph against the shape graph.

    Coverage is measured before validation, because it is the number that decides whether
    the verdict means anything, and it must be reported even when validation itself
    finds nothing to complain about.
    """
    pyshacl = require_pyshacl()

    if shapes.triples == 0:
        raise ValidateError(
            "the shape graph is empty, so nothing would be checked. Name a SHACL shapes "
            "file rather than an empty or non-RDF document."
        )
    if data.triples == 0:
        raise ValidateError(
            "the data graph is empty. If the file is TriG holding named graphs, check it "
            "parsed - an empty union here means nothing was read."
        )

    measured = coverage_module.measure(data.graph, shapes.graph)

    try:
        conforms, report_graph, _text = pyshacl.validate(
            data_graph=data.graph,
            shacl_graph=shapes.graph,
            ont_graph=ontology.graph if ontology is not None else None,
            inference="rdfs" if rdfs_reasoning else "none",
            advanced=True,
            inplace=False,
            do_owl_imports=False,
        )
    except ValidateError:
        raise
    except Exception as exc:  # pyshacl surfaces a wide range of failures
        raise ValidateError(f"SHACL validation could not run: {exc}") from exc

    return ValidationOutcome(
        conforms=bool(conforms),
        report_graph=report_graph,
        coverage=measured,
        rdfs_reasoning=rdfs_reasoning,
    )
