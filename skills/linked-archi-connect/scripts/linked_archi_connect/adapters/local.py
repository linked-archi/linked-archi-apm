"""Execute against local RDF files, in process, with no server.

A versioned, diffable, offline dataset is a feature rather than a missing triplestore, so
this is a first-class adapter and not a fallback. Several files merge into one store, which is how a federated graph is
assembled from per-model converter output.

One deliberate non-default: ``use_default_graph_as_union`` stays ``False``. Turning
it on would make an unscoped query match quads in named graphs, which would paper
over exactly the defect this package corrects - a template with no ``GRAPH``
clause returning nothing against TriG. With it off, the profile's ``named_graphs``
setting means something and a missing scope fails loudly.

Where the store comes from is a separate decision, and a selectable one: see
``store_cache``. In process terms nothing here changed - the adapter still holds a
pyoxigraph store and still owns validation - but that store may have been parsed on
this call or on an earlier one. ``store_mode``, ``store_origin`` and ``load_ms`` say
which, and :meth:`describe` prints it, because a cache that silently is not working
is worse than no cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from .base import Adapter, AdapterError, RawResult, term_to_string
from . import store_cache
from .store_cache import Source, StoreCacheError

#: Extension to pyoxigraph format name. ``.trig`` and ``.nq`` keep named graphs;
#: the rest flatten everything into the default graph, which is why loading a
#: ``.ttl`` and then scoping to a graph role returns nothing.
FORMATS: dict[str, str] = {
    ".trig": "TRIG",
    ".ttl": "TURTLE",
    ".turtle": "TURTLE",
    ".nt": "N_TRIPLES",
    ".nq": "N_QUADS",
    ".nquads": "N_QUADS",
    ".rdf": "RDF_XML",
    ".xml": "RDF_XML",
    ".jsonld": "JSON_LD",
    ".json": "JSON_LD",
    ".n3": "N3",
}

#: Serialisations that carry graph identity.
QUAD_FORMATS = frozenset({"TRIG", "N_QUADS"})


class LocalAdapter(Adapter):
    """An in-process store loaded from files on disk."""

    #: pyoxigraph parses RDF 1.2 triple terms and matches them in SPARQL. Asserted against
    #: 0.5.9, the version this package pins; the import below fails the run on anything that
    #: cannot be imported at all, so there is no older-pyoxigraph path to guard.
    sparql_12: bool = True

    def __init__(
        self,
        paths: Sequence[str | Path],
        lenient: bool = False,
        store: str | None = None,
    ) -> None:
        try:
            from pyoxigraph import RdfFormat, Store  # noqa: F401  - presence check
        except ModuleNotFoundError as exc:  # pragma: no cover - environment problem
            raise AdapterError(
                "Local execution needs pyoxigraph:  pip install pyoxigraph\n"
                "Alternatively point the connect skill at a SPARQL endpoint."
            ) from exc

        if not paths:
            raise AdapterError("No dataset given. Pass at least one RDF file.")

        # Validation runs before any cache decision, deliberately. The cache key is
        # built from each file's size and mtime, so every path has to be a real,
        # readable file with a known format before there is a key to look up - and a
        # bad path should produce the same error whether or not a cache exists.
        sources = self._validate(paths)

        try:
            loaded = store_cache.load(sources, lenient=lenient, mode=store)
        except StoreCacheError as exc:
            # A mode's own contract could not be met. That is the caller's decision
            # failing, not a dataset problem, so it is reported rather than absorbed.
            raise AdapterError(str(exc)) from exc
        except (OSError, ValueError, SyntaxError) as exc:
            raise AdapterError(f"Could not load {self._names(sources)}: {exc}") from exc

        self._store = loaded.store
        self.paths: list[Path] = [source.path for source in sources]
        self.quads_loaded = loaded.quads_loaded

        #: How the store was obtained, for reporting. ``store_origin`` is the useful
        #: one: ``memory``, ``cache-hit-rw``, ``cache-hit-ro`` or ``cache-built``.
        self.store_mode = loaded.mode
        self.store_origin = loaded.origin
        self.store_path = loaded.store_path
        self.cache_note = loaded.note

        #: Milliseconds spent obtaining the store. Surfaced through RawResult so it
        #: sits beside elapsed_ms in the envelope: the load used to be invisible, and
        #: on a large dataset it was two orders of magnitude larger than the query.
        self.load_ms = loaded.load_ms

        self.dataset_id = ", ".join(p.name for p in self.paths)
        #: The graph IRIs themselves, not only how many. Knowing *which* graphs arrived is
        #: what lets a caller notice that a merged artifact is missing a whole source.
        self.graph_names = loaded.graph_names
        self._graph_count = len(self.graph_names)
        self.named_graphs_present = self._graph_count > 0
        self.flattened_inputs = loaded.flattened_inputs

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _names(sources: Sequence[Source]) -> str:
        return ", ".join(source.path.name for source in sources)

    @staticmethod
    def _validate(paths: Sequence[str | Path]) -> list[Source]:
        """Turn caller-supplied paths into validated sources with their stat data.

        One ``stat`` per file, reused for both the existence check and the cache key,
        so keying costs nothing beyond what validation already had to do.
        """
        sources: list[Source] = []
        for raw_path in paths:
            path = Path(raw_path)
            if not path.exists():
                raise AdapterError(f"Dataset not found: {path}")
            if path.is_dir():
                raise AdapterError(
                    f"{path} is a directory. Name the files, or pass a glob your "
                    "shell expands."
                )
            fmt = FORMATS.get(path.suffix.lower())
            if fmt is None:
                known = ", ".join(sorted(FORMATS))
                raise AdapterError(
                    f"Unsupported extension {path.suffix!r} on {path.name}. "
                    f"Known: {known}. Note that an extension is how the format is "
                    "chosen, so a TriG file named .ttl loads as Turtle and loses "
                    "its graphs."
                )
            try:
                stat = path.resolve().stat()
            except OSError as exc:
                raise AdapterError(f"Could not read {path}: {exc}") from exc
            sources.append(
                Source(
                    path=path.resolve(),
                    fmt=fmt,
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            )
        return sources

    def _execute_raw(self, query: str, timeout_ms: int | None = None) -> RawResult:
        # pyoxigraph has no query timeout, so `timeout_ms` cannot be honoured here and is
        # accepted only to keep one adapter signature. The query is a blocking call into
        # Rust: nothing inside this process can interrupt it.
        #
        # That does NOT mean local execution is unbounded. The bound lives at the only
        # place that can enforce one - the process boundary - where the query owner kills
        # this subprocess after LINKED_ARCHI_LOCAL_DEADLINE_S (default 300s) and explains
        # why. Anyone tempted to add a bound here should know that was tried: reaching for
        # a thread or a signal cannot stop a Rust call mid-flight.
        #
        # Row limits are still not a work bound: ORDER BY materialises every solution
        # before LIMIT applies, so a query can cost far more than its result size.
        try:
            result = self._store.query(query)
        except (SyntaxError, ValueError) as exc:
            raise AdapterError(f"SPARQL error: {exc}") from exc

        if hasattr(result, "variables"):
            variables = [str(v.value) for v in result.variables]
            rows = [
                {name: term_to_string(solution[name]) for name in variables}
                for solution in result
            ]
            return RawResult(form="SELECT", variables=variables, rows=rows)

        if isinstance(result, bool) or type(result).__name__ == "QueryBoolean":
            return RawResult(form="ASK", boolean=bool(result))

        triples = "\n".join(str(triple) for triple in result)
        return RawResult(form="CONSTRUCT", triples=triples)

    # -- reporting ----------------------------------------------------------

    def describe(self) -> str:
        parts = [
            f"local store: {len(self.paths)} file(s), {self.quads_loaded} quad(s), "
            f"{self._graph_count} named graph(s)"
        ]
        for path in self.paths:
            parts.append(f"  {path}")
        parts.append(self._store_line())
        if self.cache_note:
            parts.append(f"  {self.cache_note}")
        if self.flattened_inputs:
            parts.append(
                "  warning: "
                + ", ".join(self.flattened_inputs)
                + " input carries no graph identity, so everything from it landed in "
                  "the default graph. Any query scoped to a graph role will return "
                  "nothing. Use TriG or N-Quads, or a profile with layout 'single'."
            )
        if self._graph_count == 0:
            parts.append(
                "  warning: no named graphs in this dataset. Use a profile with "
                "layout 'single' from sibling linked-archi-profile/assets/profiles/ "
                "or every scoped query returns nothing."
            )
        return "\n".join(parts)

    def _store_line(self) -> str:
        """One line saying where the store came from and what that cost.

        Printed on every describe() rather than behind a verbose flag, because the
        failure mode of a cache is being silently inactive while everyone assumes it
        is working. A number here makes that visible without anyone having to ask.
        """
        origin = {
            "memory": "parsed into memory",
            "cache-built": "built and cached",
            "cache-hit-rw": "reused cached store (read-write)",
            "cache-hit-ro": "reused cached store (read-only)",
        }.get(self.store_origin, self.store_origin)
        line = f"  store: {origin} in {self.load_ms} ms (mode {self.store_mode})"
        if self.store_path is not None:
            line += f"\n  cache: {self.store_path}"
        return line

    def __len__(self) -> int:
        return len(self._store)


def load(
    paths: Iterable[str | Path], lenient: bool = False, store: str | None = None
) -> LocalAdapter:
    return LocalAdapter(list(paths), lenient=lenient, store=store)
