"""Loading RDF for validation, with the named-graph trap handled explicitly.

Converter output puts every triple in a named graph and leaves the default graph empty.
A validator that only looks at the default graph therefore checks nothing and reports a
clean pass - the exact vacuous result this skill exists to catch. So data is loaded into a
dataset, which is what lets us report how many named graphs arrived, and validation runs
against the *union* of those graphs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .errors import ValidateError

#: Extension to rdflib parser name. Only `.trig`, `.nq` and `.nquads` carry graph
#: identity; the rest flatten into one graph, which is fine for validation and matters
#: for what we report about the input.
FORMATS: dict[str, str] = {
    ".trig": "trig",
    ".ttl": "turtle",
    ".turtle": "turtle",
    ".nt": "nt",
    ".nq": "nquads",
    ".nquads": "nquads",
    ".rdf": "xml",
    ".xml": "xml",
    ".jsonld": "json-ld",
    ".json": "json-ld",
    ".n3": "n3",
}
QUAD_FORMATS = frozenset({"trig", "nquads"})


def require_rdflib() -> Any:
    try:
        import rdflib
    except ModuleNotFoundError as exc:  # pragma: no cover - environment problem
        raise ValidateError(
            "RDF loading needs rdflib: pip install pyshacl (which installs rdflib)"
        ) from exc
    return rdflib


def rdf_format(path: Path, explicit: str | None = None) -> str:
    if explicit is not None:
        candidate = explicit.strip().lower()
        aliases = {
            "ttl": "turtle",
            "nq": "nquads",
            "ntriples": "nt",
            "n-triples": "nt",
            "n-quads": "nquads",
            "rdfxml": "xml",
            "rdf-xml": "xml",
            "jsonld": "json-ld",
            "trig": "trig",
        }
        candidate = aliases.get(candidate, candidate)
        if candidate not in set(FORMATS.values()):
            raise ValidateError(
                f"unsupported RDF format {explicit!r}; choose one of: "
                + ", ".join(sorted(set(FORMATS.values())))
            )
        return candidate
    suffix = path.suffix.lower()
    if suffix not in FORMATS:
        raise ValidateError(
            f"cannot infer the RDF format of {path.name} from its extension. "
            "Pass --data-format, and check the extension matches the content: a TriG "
            "file named .ttl loses its graphs silently."
        )
    return FORMATS[suffix]


def _existing_file(raw: str, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.exists():
        raise ValidateError(f"{label} does not exist: {path}")
    if path.is_dir():
        raise ValidateError(
            f"{label} is a directory, not a file: {path}. Name the RDF file explicitly."
        )
    if not path.is_file():
        raise ValidateError(f"{label} is not a regular file: {path}")
    return path


@dataclass
class LoadedGraphs:
    """A union graph for validation, plus honest facts about what arrived."""

    graph: Any
    paths: list[Path]
    triples: int
    named_graphs: int
    flattened_inputs: list[str]

    @property
    def carries_graphs(self) -> bool:
        return self.named_graphs > 0


def load(
    raw_paths: Sequence[str],
    label: str,
    explicit_format: str | None = None,
) -> LoadedGraphs:
    """Parse one or more files into a single union graph.

    Several files merge, which is how a federated graph is assembled from per-model
    converter output, and how a shape set is assembled from several published documents.
    """
    rdflib = require_rdflib()
    if not raw_paths:
        raise ValidateError(f"at least one {label} is required")

    dataset = rdflib.Dataset(default_union=True)
    paths: list[Path] = []
    flattened: set[str] = set()
    for raw in raw_paths:
        path = _existing_file(raw, label)
        parser = rdf_format(path, explicit_format)
        try:
            dataset.parse(source=str(path), format=parser)
        except Exception as exc:  # rdflib raises a wide range of parse errors
            raise ValidateError(f"could not parse {path.name} as {parser}: {exc}") from exc
        paths.append(path)
        if parser not in QUAD_FORMATS:
            flattened.add(parser)

    named_count = _named_graph_count(dataset)

    # Validation runs against the union. Handing a dataset straight to a validator
    # risks it seeing only the empty default graph, which would pass while checking
    # nothing - a vacuous result dressed as success.
    union = rdflib.Graph()
    for triple in dataset.triples((None, None, None)):
        union.add(triple)

    return LoadedGraphs(
        graph=union,
        paths=paths,
        triples=len(union),
        named_graphs=named_count,
        flattened_inputs=sorted(flattened),
    )


def _named_graph_count(dataset: Any) -> int:
    """Count non-empty named graphs across rdflib generations.

    rdflib 7.5 renamed ``contexts()``/``default_context`` to ``graphs()``/``default_graph``
    and deprecated the old spelling. Prefer the new names where present so this does not
    emit warnings now, or break when the old ones are removed.
    """
    lister = getattr(dataset, "graphs", None) or dataset.contexts
    default = getattr(dataset, "default_graph", None)
    if default is None:  # pragma: no cover - older rdflib
        default = dataset.default_context
    default_id = str(getattr(default, "identifier", ""))
    return sum(
        1
        for graph in lister()
        if str(getattr(graph, "identifier", "")) != default_id and len(graph)
    )
