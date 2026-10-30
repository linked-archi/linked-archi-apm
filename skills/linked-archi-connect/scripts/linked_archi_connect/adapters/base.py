"""Backend-neutral RDF transport owned by linked-archi-connect.

The public execution boundary delegates read-only decisions to the query owner over
its versioned machine contract before backend-specific code sees any query text.
This module imports no sibling runtime and knows no SPARQL policy details.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Sequence


@dataclass
class RawResult:
    """A transport result suitable for JSON serialization across skill boundaries."""

    form: str
    variables: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    boolean: bool | None = None
    triples: str | None = None
    elapsed_ms: int = 0
    #: Milliseconds spent obtaining the store, as distinct from executing the query.
    #:
    #: Added because ``elapsed_ms`` alone was actively misleading on a large local
    #: dataset: it timed only ``_execute_raw``, so a query reported in single-digit
    #: milliseconds had cost seconds of parsing that nothing recorded - three orders of
    #: magnitude, invisible. Zero for backends where the question does not apply, which
    #: is every remote endpoint.
    load_ms: int = 0
    dataset_id: str = "<unset>"
    named_graphs_present: bool | None = None
    description: str = ""
    #: How the query's default graph was read: ``None`` as stored, ``"union"`` as the RDF
    #: merge of every graph in the dataset. Echoed rather than assumed, so a caller that
    #: asked for the union can tell it got it - an older backend that ignored the request
    #: would otherwise answer from an empty default graph, which reads as "none found".
    default_graph: str | None = None

    @property
    def row_count(self) -> int:
        """Convenience count over the raw shape; not part of the wire contract."""
        if self.form == "SELECT":
            return len(self.rows)
        return 1 if self.boolean is not None else 0

    def as_contract(self) -> dict[str, Any]:
        return {"schema_version": 1, **asdict(self)}


class AdapterError(RuntimeError):
    """A backend or required companion could not safely execute a query."""


#: The ways a query's default graph can be read. ``None`` is the default graph as stored,
#: deliberately not the union (see adapters/local.py); ``"union"`` is asked for per query,
#: by a query written for one graph - a model question, which reads the model and its
#: metamodel as la-gram holds them.
DEFAULT_GRAPH_MODES = (None, "union")


def _check_default_graphs(default_graphs: Sequence[Any] | None, count: int) -> list[str | None]:
    if default_graphs is None:
        return [None] * count
    if isinstance(default_graphs, (str, bytes)) or not isinstance(default_graphs, Sequence):
        raise AdapterError("default_graphs must be a list, one entry per query")
    modes = list(default_graphs)
    if len(modes) != count:
        raise AdapterError(
            f"default_graphs has {len(modes)} entries for {count} queries; give one per query"
        )
    for mode in modes:
        if mode not in DEFAULT_GRAPH_MODES:
            raise AdapterError(
                f"default graph {mode!r} is not one of: null (as stored), \"union\""
            )
    return modes


REQUIRED_QUERY_SKILL = "linked-archi-query"


#: This skill's own name, used only to phrase the adjacency hint in an error.
OWN_SKILL = "linked-archi-connect"


def _companion(skill: str, executable: str) -> Path:
    """Locate a sibling owner. One order, used identically by every owner here.

    1. ``$LINKED_ARCHI_SKILLS_DIR`` when set - **authoritative, and never falls back**.
       Someone who names an install root means that root; silently using a different
       generation of the skill found elsewhere is how two skill sets get mixed.
    2. the sibling directory beside this skill, which is how installed skill sets sit.
    3. the command on ``PATH``, for a packaged or symlinked install.

    Deliberately not a filesystem search. A missing companion is reported by name so the
    caller installs it, rather than going looking for it.
    """
    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    if configured:
        candidate = Path(configured).expanduser() / skill / "scripts" / executable
        if candidate.is_file():
            return candidate
        raise AdapterError(
            f"Missing required skill: {skill} under explicit "
            f"LINKED_ARCHI_SKILLS_DIR={configured}."
        )
    skill_root = next(
        (parent for parent in Path(__file__).resolve().parents if parent.name == OWN_SKILL),
        None,
    )
    if skill_root is not None:
        candidate = skill_root.parent / skill / "scripts" / executable
        if candidate.is_file():
            return candidate
    on_path = shutil.which(executable)
    if on_path:
        return Path(on_path)
    raise AdapterError(
        f"Missing required skill: {skill}. Install it beside {OWN_SKILL}, put "
        f"{executable} on PATH, or set LINKED_ARCHI_SKILLS_DIR."
    )


def _query_executable() -> Path:
    """Locate the safety-policy owner without importing sibling Python code."""
    return _companion(REQUIRED_QUERY_SKILL, "la-query")


def validate_queries_readonly(queries: Sequence[str]) -> None:
    """Require one affirmative, versioned query-owner decision per query."""
    request = {"schema_version": 1, "queries": list(queries)}
    try:
        done = subprocess.run(
            [sys.executable, str(_query_executable()), "_machine", "lint"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("Query safety check exceeded its 30s companion deadline") from exc
    if done.returncode != 0:
        detail = done.stderr.strip() or done.stdout.strip() or "query lint failed"
        raise AdapterError(f"Query safety check failed: {detail}")
    try:
        response = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise AdapterError("Query safety check returned invalid JSON") from exc
    if (
        not isinstance(response, dict)
        or type(response.get("schema_version")) is not int
        or response["schema_version"] != 1
    ):
        raise AdapterError("Query safety check returned unsupported schema_version")
    decisions = response.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != len(queries):
        raise AdapterError("Query safety check returned the wrong number of decisions")
    for decision in decisions:
        if not isinstance(decision, dict) or not isinstance(decision.get("accepted"), bool):
            raise AdapterError("Query safety check returned a malformed decision")
        if not decision["accepted"]:
            reason = decision.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise AdapterError("Query safety check refused execution without a reason")
            raise AdapterError(f"Query safety check refused execution: {reason}")


class Adapter(ABC):
    """Raw transport whose public methods always enforce query-owner policy."""

    dataset_id: str = "<unset>"
    named_graphs_present: bool | None = None

    #: Whether this backend can PARSE SPARQL 1.2 syntax — specifically the triple-term
    #: pattern ``<<( s p o )>>`` used to look inside an ``rdf:reifies`` bridge.
    #:
    #: False by default because it has to be. On a 1.1 engine that pattern is a parse error
    #: rather than an empty result, and :meth:`execute_many` fails the whole batch on one bad
    #: query — so a probe reaching for it optimistically would take an entire ``verify`` down
    #: against an endpoint that merely happens to be older. A caller who wants the stricter
    #: check against a remote endpoint says so through the profile's
    #: ``capabilities.rdf_reifies`` claim, the same gate query templates are refused by.
    sparql_12: bool = False

    @abstractmethod
    def _execute_raw(
        self, query: str, timeout_ms: int | None = None, default_graph: str | None = None
    ) -> RawResult:
        """Backend hook. Callers must use :meth:`execute` or :meth:`execute_many`.

        ``default_graph="union"`` reads the query's default graph as the RDF merge of every
        graph in the dataset; a backend that cannot must refuse rather than ignore it.
        """

    def _decorate(self, raw: RawResult, started: float) -> RawResult:
        return replace(
            raw,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            # An adapter that has no load step simply does not set this, so the
            # default stands rather than every backend having to declare a zero.
            load_ms=int(getattr(self, "load_ms", 0)),
            dataset_id=self.dataset_id,
            named_graphs_present=self.named_graphs_present,
            description=self.describe(),
        )

    def execute_many(
        self,
        queries: Sequence[str],
        timeout_ms: int | None = None,
        default_graphs: Sequence[str | None] | None = None,
    ) -> list[RawResult]:
        """Validate the complete batch, then execute it without partial unsafe work.

        ``default_graphs`` gives each query's reading of the default graph, one entry per
        query; absent, every query reads it as stored.
        """
        query_list = list(queries)
        if not query_list or any(not isinstance(query, str) or not query.strip() for query in query_list):
            raise AdapterError("execute_many requires a non-empty sequence of queries")
        if timeout_ms is not None and (
            not isinstance(timeout_ms, int)
            or isinstance(timeout_ms, bool)
            or timeout_ms <= 0
        ):
            raise AdapterError("timeout_ms must be a positive integer or null")
        modes = _check_default_graphs(default_graphs, len(query_list))
        validate_queries_readonly(query_list)
        results: list[RawResult] = []
        for index, (query, mode) in enumerate(zip(query_list, modes)):
            started = time.perf_counter()
            raw = (
                self._execute_raw(query, timeout_ms=timeout_ms, default_graph=mode)
                if mode
                else self._execute_raw(query, timeout_ms=timeout_ms)
            )
            decorated = replace(self._decorate(raw, started), default_graph=mode)
            # The load was paid ONCE, before the first query, so only the first result
            # carries it. Stamping every result would make one parse read as N of them
            # and turn the whole point of a batch into a mystery: the reported load
            # would exceed the wall clock that contained a single parse. Zero on the
            # rest is the honest figure - there was no load to attribute to them.
            results.append(decorated if index == 0 else replace(decorated, load_ms=0))
        return results

    def execute(
        self,
        query: str,
        timeout_ms: int | None = None,
        default_graph: str | None = None,
        **_legacy_context: Any,
    ) -> RawResult:
        """Execute one query through the mandatory query-owner safety contract."""
        if default_graph is None:
            return self.execute_many([query], timeout_ms=timeout_ms)[0]
        return self.execute_many(
            [query], timeout_ms=timeout_ms, default_graphs=[default_graph]
        )[0]

    def ask(self, query: str) -> bool:
        """Execute a validated ASK probe."""
        return bool(self.execute(query).boolean)

    def count(self, query: str) -> int:
        """Return the first numeric binding of a validated count probe."""
        raw = self.execute(query)
        if not raw.rows:
            return 0
        for key in raw.variables or list(raw.rows[0]):
            try:
                return int(str(raw.rows[0].get(key)))
            except (TypeError, ValueError):
                continue
        return 0

    def describe(self) -> str:
        return f"{type(self).__name__} -> {self.dataset_id}"

    def close(self) -> None:
        """Release resources. Safe to call more than once."""

    def __enter__(self) -> "Adapter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def term_to_string(term: Any) -> str:
    """Render an RDF term while keeping blank nodes distinguishable."""
    if term is None:
        return ""
    kind = type(term).__name__
    value = getattr(term, "value", None)
    if value is None:
        return str(term)
    if kind == "BlankNode":
        return f"_:{value}"
    return str(value)
