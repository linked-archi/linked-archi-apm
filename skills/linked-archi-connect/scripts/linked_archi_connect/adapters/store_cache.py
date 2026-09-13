"""Where the store comes from: parse the files, or reuse a store parsed earlier.

Every measurement quoted below was taken on one large multi-notation TriG aggregate,
and every figure is given as a ratio or an order of magnitude rather than an absolute,
because the absolutes are properties of that dataset and not of this code. Expect the
same SHAPE at a different scale: the crossover moves, the direction does not.

── THE PROBLEM ──────────────────────────────────────────────────────────────────
An in-memory store dies with the process, and every owner CLI here is a separate
process, so a session that asks ten questions of one dataset parses it ten times. On a
large aggregate that parse takes seconds, and two smaller costs rode along with it:
rediscovering graph names by SPARQL, and counting quads. Together they sat under a
query whose own execution was single-digit milliseconds - three orders of magnitude
smaller - and nothing reported it, because ``elapsed_ms`` times only the query.
``load_ms`` exists because of that, and it is the reason any of this is visible.

── WHAT MEASUREMENT ACTUALLY SHOWED, INCLUDING WHERE IT SAID NO ────────────────
The obvious fix is pyoxigraph's RocksDB-backed ``Store(path)``: parse once, reopen
forever. It works, and for a cheap query it is dramatic - a selective lookup went from
seconds to tens of milliseconds, close to two orders of magnitude. It is implemented
here as the ``cached`` mode.

It is NOT the default, because on the same dataset it makes an analytical query
substantially slower. Queries against a RocksDB store do not run at in-memory speed:

    an aggregating template               load          query        total wall
      parse into memory              full parse     baseline         baseline
      reuse a cached store           ~1/100th       roughly 3x       ~1.6x worse

The load saving is real and the query penalty is larger. Whether caching wins depends
entirely on how much work the query does, which nothing can know before running it -
so this is a mode a caller selects knowingly, not a default applied on their behalf.

Three routes to "get an in-memory store without re-parsing" were measured, and all
three are slower than simply parsing the TriG again:

    parse TriG -> memory                           1.0x   <- the fastest route
    open cached store read-only, copy -> memory    ~2.5x
    dump to N-Quads, parse -> memory               ~1.25x

pyoxigraph's TriG reader moves hundreds of thousands of quads per second, which is
quick enough that no serialisation here beats it. So there is no way to keep in-memory
query speed and skip the parse within one process.

The consequence is worth stating plainly, because it redirects the whole problem: the
per-process parse is irreducible, so the way to stop paying it repeatedly is to stop
starting a process per query. That is ``la-query query batch``, which runs several
queries against one load, or a resident process holding the store. Neither belongs in
this module, and neither is replaced by what is here.

── THE MODES ────────────────────────────────────────────────────────────────────
``memory``    Parse into memory. The default, and the right answer for analytical work
              and for anything one-shot. No disk, no cache, nothing to invalidate.
``cached``    Persist an on-disk store and reuse it. Load drops by around two orders of
              magnitude; queries get slower in proportion to how much work they do.
              Worth it for many cheap lookups over one large dataset, and a poor trade
              for aggregation. Refuses rather than silently falling back, so a
              benchmark cannot measure the slow path and report it as the fast one.
``readonly``  Reuse a cached store, never build one. For parallel readers against a
              warmed cache, and where querying must be unable to mutate a shared store.
``refresh``   Discard this dataset's cached store and rebuild it.

── WHY THE KEY IS WHAT IT IS ────────────────────────────────────────────────────
Cache invalidation is the only part of this that can produce a WRONG answer rather
than a slow one, so the key is deliberately conservative: the ordered file list with
each file's size and mtime, the ``lenient`` flag, the pyoxigraph version, and a
revision of our own load semantics.

Stat data rather than content hashes, because hashing the whole dataset to decide
whether to skip parsing it would give back most of what the cache saves. Every real
update moves size or mtime, so the key moves and the next call rebuilds unprompted.

The cost of that choice is visible and accepted: two spellings of one dataset get two
stores. Observed on one deployment, a fetched copy and a repository checkout of the
same files produced two stores of near-identical size for one logical dataset. Hence
the byte budget in :func:`evict` rather than a content-addressed key.

The profile is deliberately NOT in the key. A profile binds vocabulary when a query is
rendered and never changes which quads exist, so keying on it would multiply disk cost
by the number of profiles for no correctness gain.

── WHY A BUILD IS ATOMIC ────────────────────────────────────────────────────────
A store is built into a temporary directory and moved into place with ``os.replace``,
so a reader sees either no store or a complete one, and two processes racing to build
the same key both end up with a valid store. Building in place behind a lock file would
leave a partial store behind whenever a build was killed, and a partial store looks
exactly like a valid cache hit.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

#: Bump when what gets loaded, or how, changes in a way that makes an existing store
#: wrong rather than merely old. Part of the cache key, so a bump invalidates every
#: store without anyone having to clear a directory.
FORMAT_REVISION = 1

#: Sidecar schema, versioned for the same fail-closed reason every other boundary here
#: is: an unreadable sidecar is a cache miss, never "assume the defaults".
META_SCHEMA_VERSION = 1

META_FILENAME = "meta.json"

#: ``memory`` is first because it is the default. See the module docstring for why the
#: fast-loading mode is not the default one.
MODES = ("memory", "cached", "readonly", "refresh")

DEFAULT_MODE = "memory"

ENV_MODE = "LINKED_ARCHI_STORE"
ENV_CACHE = "LINKED_ARCHI_STORE_CACHE"
ENV_KEEP = "LINKED_ARCHI_STORE_KEEP"
ENV_MAX_BYTES = "LINKED_ARCHI_STORE_MAX_BYTES"

#: How many store directories to keep per cache root. Three covers alternating between
#: dataset variants - the per-notation set and the merged file, say - plus one previous
#: generation.
DEFAULT_KEEP = 3

#: And a bound in bytes, because a count is not a budget. Store size tracks dataset
#: size over orders of magnitude, so "keep 3" is a few megabytes for one estate and
#: gigabytes for another, and only the second is a problem. A budget answers the
#: question a count cannot: how much disk will this cost me.
DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024


class StoreCacheError(RuntimeError):
    """A mode's own contract could not be met.

    Every caching mode here promises something specific - ``cached`` that a store will
    be used, ``readonly`` that one already exists - and a promise that quietly degrades
    is worse than one that fails, because the caller goes on believing it held.
    """


@dataclass(frozen=True)
class Source:
    """One input file, already validated, with the stat data the key needs."""

    path: Path
    fmt: str
    size: int
    mtime_ns: int


@dataclass
class Loaded:
    """A store plus how it came to be, so the caller can report rather than guess."""

    store: Any
    mode: str
    origin: str
    quads_loaded: int
    graph_names: list[str] = field(default_factory=list)
    flattened_inputs: list[str] = field(default_factory=list)
    load_ms: int = 0
    store_path: Path | None = None
    note: str = ""


# -- configuration ---------------------------------------------------------------


def resolve_mode(explicit: str | None = None) -> str:
    """Pick the mode, preferring an explicit argument over the environment.

    An unrecognised value is refused rather than defaulted. A typo would otherwise
    select the default silently and look like a mode that had no effect, which is the
    hardest kind of configuration bug to see.
    """
    raw = explicit if explicit is not None else os.environ.get(ENV_MODE)
    if raw is None or not str(raw).strip():
        return DEFAULT_MODE
    mode = str(raw).strip().lower()
    if mode not in MODES:
        raise StoreCacheError(
            f"unknown store mode {mode!r}. Expected one of: " + ", ".join(MODES)
        )
    return mode


def cache_root() -> Path:
    """Where store directories live. Honours $LINKED_ARCHI_STORE_CACHE, then XDG."""
    configured = os.environ.get(ENV_CACHE)
    if configured and configured.strip():
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg and xdg.strip() else Path.home() / ".cache"
    return base / "linked-archi" / "stores"


def _non_negative_int_env(name: str, default: int) -> int:
    """Read a non-negative integer setting, ignoring anything unreadable.

    A malformed value falls back to the default rather than failing. These are disk
    housekeeping knobs, and refusing to run because someone wrote ``KEEP=lots`` would
    trade a working path for no path at all.
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def keep_count() -> int:
    return _non_negative_int_env(ENV_KEEP, DEFAULT_KEEP)


def max_bytes() -> int:
    return _non_negative_int_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES)


# -- the key ---------------------------------------------------------------------


def compute_key(sources: Sequence[Source], lenient: bool, pyoxigraph_version: str) -> str:
    """A stable digest of everything that changes what the store should contain.

    Order is preserved. Loading A then B and B then A produce the same quads, but
    keeping the order makes the key trivially explainable and costs nothing. Paths are
    resolved so two spellings of one file share a store.
    """
    parts = [
        f"format_revision={FORMAT_REVISION}",
        f"pyoxigraph={pyoxigraph_version}",
        f"lenient={int(bool(lenient))}",
    ]
    for source in sources:
        parts.append(
            f"file={source.path}\tfmt={source.fmt}\tsize={source.size}"
            f"\tmtime_ns={source.mtime_ns}"
        )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _store_dir(key: str) -> Path:
    """Directory for a key. Shortened for readability; the full key is in the sidecar."""
    return cache_root() / key[:16]


# -- the sidecar -----------------------------------------------------------------


def _write_meta(target: Path, key: str, sources: Sequence[Source], lenient: bool,
                pyoxigraph_version: str, quads: int, graphs: Sequence[str],
                flattened: Sequence[str]) -> None:
    """Record what a cache hit needs, so a hit does not re-derive it.

    ``graph_names`` and ``quads_loaded`` are here because recomputing them was a
    measurable slice of the original load. Everything else is here to make a hit
    verifiable rather than assumed.
    """
    payload = {
        "schema_version": META_SCHEMA_VERSION,
        "key": key,
        "format_revision": FORMAT_REVISION,
        "pyoxigraph": pyoxigraph_version,
        "lenient": bool(lenient),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "quads_loaded": int(quads),
        "graph_names": list(graphs),
        "flattened_inputs": list(flattened),
        "sources": [
            {
                "path": str(source.path),
                "fmt": source.fmt,
                "size": source.size,
                "mtime_ns": source.mtime_ns,
            }
            for source in sources
        ],
    }
    (target / META_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _read_meta(store_path: Path, key: str) -> dict[str, Any] | None:
    """Load a sidecar, or return None for anything that is not certainly ours.

    The directory name encodes a prefix of the key, so a mismatch here means either a
    prefix collision or a hand-edited cache. Both are misses. An unreadable or
    wrong-version sidecar is a miss too: rebuilding costs seconds, while trusting a
    sidecar that does not describe the store on disk would report the wrong quad count
    and the wrong graph list alongside a real answer.
    """
    path = store_path / META_FILENAME
    if not path.is_file():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    if meta.get("schema_version") != META_SCHEMA_VERSION:
        return None
    if meta.get("key") != key:
        return None
    if not isinstance(meta.get("quads_loaded"), int):
        return None
    if not isinstance(meta.get("graph_names"), list):
        return None
    return meta


# -- loading ---------------------------------------------------------------------


def _scan(store: Any) -> tuple[int, list[str]]:
    """Quad count and graph names, taken from the store rather than from SPARQL.

    ``named_graphs()`` is effectively free where ``SELECT DISTINCT ?g`` took a
    measurable fraction of a second on a large aggregate, and it returned an identical
    set on every dataset checked - that aggregate and all three committed fixtures.

    The two are not identical by definition: a graph a TriG file declares but leaves
    empty appears in ``named_graphs()`` and not in the SPARQL form. Where they differ,
    ``named_graphs()`` is the better answer to the question actually being asked, which
    is whether this dataset carries graph identity at all. A flattened Turtle input
    declares none either way, so the warning that depends on this still fires exactly
    when it should.
    """
    names = sorted(str(getattr(name, "value", name)) for name in store.named_graphs())
    return len(store), names


def _bulk_load(store: Any, sources: Sequence[Source], lenient: bool) -> None:
    from pyoxigraph import RdfFormat

    for source in sources:
        with source.path.open("rb") as handle:
            store.bulk_load(handle, getattr(RdfFormat, source.fmt), lenient=lenient)


def _flattened(sources: Sequence[Source]) -> list[str]:
    """Formats among the inputs that carry no graph identity.

    Here rather than in the adapter so a cache hit and a fresh parse derive it the same
    way; the sidecar records it so a hit need not derive it at all.
    """
    quad_formats = {"TRIG", "N_QUADS"}
    return sorted({source.fmt for source in sources} - quad_formats)


def load_memory(sources: Sequence[Source], lenient: bool) -> Loaded:
    """Parse into RAM. The default, and the fastest route to an in-memory store."""
    from pyoxigraph import Store

    started = time.perf_counter()
    store = Store()
    _bulk_load(store, sources, lenient)
    quads, graphs = _scan(store)
    return Loaded(
        store=store,
        mode="memory",
        origin="memory",
        quads_loaded=quads,
        graph_names=graphs,
        flattened_inputs=_flattened(sources),
        load_ms=round((time.perf_counter() - started) * 1000),
    )


def _open_existing(store_path: Path, prefer_read_only: bool) -> tuple[Any, str]:
    """Open a built store, preferring speed but never failing over a held lock.

    RocksDB takes an exclusive lock on a read-write open, so two concurrent readers
    cannot both have one - the second gets ``Resource temporarily unavailable``. A
    read-write open measured an order of magnitude faster than read-only, so it is
    worth trying first and worth falling back rather than serialising callers behind a
    lock. Both are far below the cost of a parse, so either is a good outcome.

    ``prefer_read_only`` inverts that for ``readonly`` mode, where the point is the
    guarantee that querying cannot touch the store, not the 0.3 s.
    """
    from pyoxigraph import Store

    attempts = (
        [("cache-hit-ro", Store.read_only)]
        if prefer_read_only
        else [("cache-hit-rw", Store), ("cache-hit-ro", Store.read_only)]
    )
    last: Exception | None = None
    for origin, opener in attempts:
        try:
            return opener(str(store_path)), origin
        except (OSError, ValueError) as exc:
            last = exc
    raise StoreCacheError(f"could not open the cached store at {store_path}: {last}")


def _build(store_path: Path, sources: Sequence[Source], lenient: bool, key: str,
           pyoxigraph_version: str) -> tuple[Any, int, list[str], list[str]]:
    """Build into a temporary directory, then move it into place.

    The store is dropped before the move and reopened after it. That reopen is cheap
    next to the build it follows, and it buys the certainty that no RocksDB handle
    points at a path renamed underneath it.

    A concurrent builder that wins the race is not an error: its store is as valid as
    ours, so ours is discarded and theirs used. Discarding means deleting the temporary
    directory, hundreds of megabytes for a large dataset - hence the ``finally``.
    """
    from pyoxigraph import Store

    root = store_path.parent
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".building-{store_path.name}-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)

    try:
        store = Store(str(staging))
        _bulk_load(store, sources, lenient)
        store.flush()
        # Compaction earns its one-off cost: this store is written once and read many
        # times, which is what optimize() is for.
        store.optimize()
        quads, graphs = _scan(store)
        flattened = _flattened(sources)
        _write_meta(staging, key, sources, lenient, pyoxigraph_version, quads, graphs,
                    flattened)
        del store

        try:
            os.replace(staging, store_path)
        except OSError:
            # Another builder got there first, or the target is non-empty for some
            # other reason. Either way a usable store is already in place.
            if not (store_path / META_FILENAME).is_file():
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    opened, _origin = _open_existing(store_path, prefer_read_only=False)
    return opened, quads, graphs, flattened


def _dir_size(path: Path) -> int:
    """Bytes under a directory, ignoring anything that vanishes while walking.

    A concurrent build or eviction can remove a file between listing and stat, and an
    approximate size is entirely adequate for deciding what to evict.
    """
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def evict(keep: int, protect: Path | None = None, budget: int | None = None) -> None:
    """Hold the cache to two bounds at once: a count and a byte budget.

    Both exist because neither alone is honest. A count is what a human reasons about
    ("keep the last few datasets") but says nothing about disk, and store size tracks
    dataset size over orders of magnitude. A budget answers "how much will this cost
    me" and is the bound that protects the filesystem.

    Newest first, so the oldest go. ``protect`` is never evicted - normally the store
    just built, since deleting it to satisfy a budget would mean rebuilding it on the
    next call, forever. If that one store alone exceeds the budget it is kept and the
    budget is simply not achievable, which is worth leaving visible rather than
    thrashing over.

    ``keep=0`` disables the count bound rather than deleting everything: "keep nothing"
    is what ``memory`` mode is for, and a cleanup path that could empty the cache would
    make a misconfigured value catastrophic instead of merely wasteful.

    A directory that cannot be removed is left alone. It is most likely open in another
    process, and failing a query in order to tidy a cache would be the wrong trade.
    """
    root = cache_root()
    if not root.is_dir():
        return
    entries = [
        entry for entry in root.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    ]
    if not entries:
        return
    entries.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)

    limit = budget if budget is not None else max_bytes()
    if keep <= 0 and limit <= 0:
        return
    used = 0
    for index, entry in enumerate(entries):
        # Only measured when a budget is in force. Walking a large store directory is
        # cheap but not free, and with no budget the answer would not be used.
        size = _dir_size(entry) if limit > 0 else 0
        if protect is not None and entry == protect:
            used += size
            continue
        over_count = keep > 0 and index >= keep
        over_budget = limit > 0 and used + size > limit
        if over_count or over_budget:
            shutil.rmtree(entry, ignore_errors=True)
            continue
        used += size


def load(sources: Sequence[Source], lenient: bool, mode: str | None = None) -> Loaded:
    """Load a dataset under the selected mode. The one entry point the adapter uses."""
    resolved = resolve_mode(mode)

    if resolved == "memory":
        return load_memory(sources, lenient)

    import pyoxigraph

    version = getattr(pyoxigraph, "__version__", "unknown")
    key = compute_key(sources, lenient, version)
    store_path = _store_dir(key)
    started = time.perf_counter()

    if resolved == "refresh" and store_path.exists():
        shutil.rmtree(store_path, ignore_errors=True)

    meta = _read_meta(store_path, key) if resolved != "refresh" else None

    if meta is not None:
        store, origin = _open_existing(
            store_path, prefer_read_only=(resolved == "readonly")
        )
        return Loaded(
            store=store,
            mode=resolved,
            origin=origin,
            quads_loaded=int(meta["quads_loaded"]),
            graph_names=list(meta["graph_names"]),
            flattened_inputs=list(meta.get("flattened_inputs") or []),
            load_ms=round((time.perf_counter() - started) * 1000),
            store_path=store_path,
        )

    if resolved == "readonly":
        raise StoreCacheError(
            f"store mode 'readonly' found no cached store for this dataset at "
            f"{store_path}.\n"
            f"Warm it once with {ENV_MODE}=cached, or use {ENV_MODE}=memory to parse "
            "on every call."
        )

    try:
        store, quads, graphs, flattened = _build(store_path, sources, lenient, key, version)
    except (OSError, ValueError, StoreCacheError) as exc:
        # No silent fallback. Every mode that reaches here asked for a store, and a
        # caller who is told they got one must actually have got one.
        raise StoreCacheError(
            f"store mode {resolved!r} could not build a store at {store_path}: {exc}\n"
            f"Set {ENV_MODE}=memory to parse the files on every call instead."
        ) from exc

    evict(keep_count(), protect=store_path)

    return Loaded(
        store=store,
        mode=resolved,
        origin="cache-built",
        quads_loaded=quads,
        graph_names=graphs,
        flattened_inputs=flattened,
        load_ms=round((time.perf_counter() - started) * 1000),
        store_path=store_path,
    )
