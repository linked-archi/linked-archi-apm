"""Find candidate datasets, and report enough about each to choose between them.

An agent asked "which processes depend on the payment service?" has to answer a
prior question first: *which file holds the graph.* Left to prose instructions it
guesses, and a wrong guess here is expensive in a specific way - picking up a stale
``out/*.trig`` from last month's conversion produces a confident, well-cited answer
about the wrong architecture.

So this module reports rather than decides. It lists what it found with the facts
needed to choose - format, size, quad count, named graphs, modification time - and
leaves the choice to whoever can judge currency. The one exception is
``$LINKED_ARCHI_DATA``, which is an explicit statement by a human or a project.

**Nothing here selects a dataset implicitly.** `open_adapter` still requires `--data`
or `--endpoint`, because the dataset named in a result's citation line should always be
one somebody chose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .adapters.local import FORMATS, QUAD_FORMATS

#: An explicit dataset, set by a human or a project. Colon-separated, like PATH,
#: because a federated graph is several files.
ENV_DATA = "LINKED_ARCHI_DATA"

#: Directories a converter or build conventionally writes to, plus the ones a
#: repository conventionally *commits* a graph into. Both matter: converter output
#: lands in `out/`, but the file a team shares is usually committed somewhere named
#: after the content rather than the build.
SEARCH_DIRS = (
    ".",
    "dist", "build", "out", "target",          # build output
    "graph", "graphs", "data",                 # data
    "architecture", "models", "model",         # committed architecture
)

#: Extension -> whether it carries graph identity, derived from the local adapter's own
#: format table so the two cannot disagree. They did once, in both directions: discovery
#: ignored `.nt`, `.rdf`, `.xml`, `.jsonld` and `.json`, which the adapter loads happily,
#: so a supported graph was invisible and manual globbing became the only way to find it;
#: and discovery offered `.nquads`, which the adapter then refused, so a proposed
#: candidate could not be loaded. One table, one truth.
#:
#: The boolean is what matters most in the result: a `.ttl` file carries no graph
#: identity, and that is the single most common reason every scoped query returns nothing.
EXTENSIONS: dict[str, bool] = {
    extension: rdf_format in QUAD_FORMATS
    for extension, rdf_format in FORMATS.items()
}

#: Loadable, but the suffix does not mean RDF. `.json` is JSON-LD *and* every
#: `package.json`, `tsconfig.json` and lockfile in the tree; `.xml` is RDF/XML *and*
#: every `pom.xml` and sitemap. Scanning them by default buries the real candidates it is
#: this command's whole job to surface, so they stay loadable and become discoverable only
#: when asked for by name. An explicit path or $LINKED_ARCHI_DATA always works.
AMBIGUOUS_EXTENSIONS = frozenset({".json", ".xml"})

#: What a bare search looks at: every unambiguous RDF suffix the adapter can load.
DEFAULT_EXTENSIONS = frozenset(EXTENSIONS) - AMBIGUOUS_EXTENSIONS

#: Never returned as a candidate for real work. Committed test data lives here, and an
#: answer sourced from it is a demonstration, not a finding.
FIXTURE_MARKERS = ("fixtures", "test", "tests", "example", "examples", "sample")

#: How far below each search directory a bare scan looks. Bounded rather than unlimited:
#: an unbounded walk from a repository root reads every dependency tree and vendored
#: checkout on the machine, which is slow enough to look broken.
DEFAULT_MAX_DEPTH = 3

#: A ceiling on `--max-depth`. Above this the walk stops being a search and becomes a
#: filesystem crawl, which is precisely the behaviour this command exists to replace.
MAX_MAX_DEPTH = 12

#: Retained name, still used internally.
_MAX_DEPTH = DEFAULT_MAX_DEPTH


def _git(args: list[str], cwd: Path) -> str | None:
    """Run a read-only git command, or return None if it is not usable here.

    Never touches the network. Everything asked for is answerable from the local
    object store, so this works offline and adds no latency beyond a process spawn.
    """
    import subprocess

    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # git absent, or unusable
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip() or None


def repo_root(start: Path) -> Path | None:
    """The git working tree containing ``start``, if any."""
    top = _git(["rev-parse", "--show-toplevel"], start if start.is_dir() else start.parent)
    return Path(top) if top else None


@dataclass(frozen=True)
class GitInfo:
    """What git knows about one file. All of it local; none of it fetched."""

    commit: str | None
    ref: str | None
    #: ISO date of the last commit touching this file. The real currency signal.
    committed: str | None
    #: The file has uncommitted modifications.
    dirty: bool
    #: The file is not tracked, so nobody else has it.
    untracked: bool


def git_info(path: Path) -> GitInfo | None:
    """Provenance for one candidate, or None when it is not in a working tree."""
    cwd = path.parent
    if repo_root(cwd) is None:
        return None

    status = _git(["status", "--porcelain", "--", str(path)], cwd)
    return GitInfo(
        commit=_git(["rev-parse", "--short", "HEAD"], cwd),
        ref=_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd),
        committed=_git(["log", "-1", "--format=%cs", "--", str(path)], cwd),
        dirty=bool(status) and not status.startswith("??"),
        untracked=bool(status) and status.startswith("??"),
    )


@dataclass(frozen=True)
class Candidate:
    """One file that might be the graph."""

    path: Path
    #: ``env`` (explicitly set), ``search`` (found by convention), ``fixture``.
    origin: str
    carries_graphs: bool
    size_bytes: int
    modified: float
    #: Populated lazily by :func:`describe`, because it costs a subprocess.
    git: GitInfo | None = None

    @property
    def is_fixture(self) -> bool:
        parts = {p.lower() for p in self.path.parts}
        return bool(parts & set(FIXTURE_MARKERS))

    def caveats(self) -> list[str]:
        notes: list[str] = []
        if not self.carries_graphs:
            notes.append(
                f"{self.path.suffix} carries no graph identity, so every "
                "graph-scoped query returns nothing unless the profile layout is "
                "'single'"
            )
        if self.is_fixture:
            notes.append(
                "looks like test data - say so plainly if you answer from it"
            )
        if self.git is not None:
            if self.git.untracked:
                notes.append(
                    "not committed, so it exists only on this machine - nobody "
                    "reviewing your answer can reproduce it"
                )
            elif self.git.dirty:
                notes.append(
                    "modified since its last commit, so it does not match any "
                    f"reviewable version ({self.git.commit})"
                )
        return notes


def from_env() -> list[Path]:
    """Datasets named in ``$LINKED_ARCHI_DATA``. Missing files are reported, not hidden."""
    raw = os.environ.get(ENV_DATA)
    if not raw:
        return []
    return [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]


def _walk(root: Path, depth: int, extensions: frozenset[str]) -> list[Path]:
    if depth < 0 or not root.is_dir():
        return []
    found: list[Path] = []
    try:
        entries = sorted(root.iterdir())
    except PermissionError:  # pragma: no cover - environment dependent
        return []
    for entry in entries:
        if entry.name.startswith(".") or entry.name in {"node_modules", "__pycache__"}:
            continue
        if entry.is_file() and entry.suffix.lower() in extensions:
            found.append(entry)
        elif entry.is_dir():
            found.extend(_walk(entry, depth - 1, extensions))
    return found


def _requested_extensions(extensions: Sequence[str] | None) -> frozenset[str]:
    """Normalise caller-supplied suffixes, refusing ones nothing can load.

    Refusing beats silently returning nothing: a typo like ``--extension trigg`` would
    otherwise look exactly like a repository with no graph in it.
    """
    if extensions is None:
        return DEFAULT_EXTENSIONS
    wanted: set[str] = set()
    for raw in extensions:
        candidate = raw.strip().lower()
        if not candidate:
            continue
        if not candidate.startswith("."):
            candidate = f".{candidate}"
        if candidate not in EXTENSIONS:
            raise ValueError(
                f"{raw!r} is not a loadable RDF extension. Choose from: "
                + ", ".join(sorted(EXTENSIONS))
            )
        wanted.add(candidate)
    return frozenset(wanted) or DEFAULT_EXTENSIONS


def search_roots(start: Path) -> list[Path]:
    """Where to look: the given directory, and the git working tree containing it.

    Anchoring at the repository root matters because an agent's working directory is
    rarely the root. Asked a question from `docs/`, a cwd-only search misses
    `dist/merged.trig` two levels up and reports "no graph found" about a repository
    that plainly has one.
    """
    roots = [start]
    top = repo_root(start)
    if top is not None and top.resolve() != start.resolve():
        roots.append(top.resolve())
    return roots


def _requested_directories(directories: Sequence[str] | None) -> tuple[str, ...]:
    """Which subdirectories to scan under each root.

    Replaces the conventional list rather than adding to it, because a caller naming a
    layout knows something the convention does not - and a search that also walks nine
    conventional directories they did not ask about is slower and noisier for no gain.
    ``.`` is always included, so a graph sitting directly in the named directory is found.
    """
    if directories is None:
        return SEARCH_DIRS
    wanted: list[str] = ["."]
    for raw in directories:
        candidate = raw.strip()
        if not candidate:
            continue
        if Path(candidate).is_absolute():
            raise ValueError(
                f"{raw!r} is an absolute path. --search-dir is relative to each search "
                "root; pass an absolute location with --data instead, which needs no search."
            )
        if candidate not in wanted:
            wanted.append(candidate)
    return tuple(wanted)


def _requested_depth(depth: int | None) -> int:
    if depth is None:
        return DEFAULT_MAX_DEPTH
    if depth < 0:
        raise ValueError("--max-depth cannot be negative")
    if depth > MAX_MAX_DEPTH:
        raise ValueError(
            f"--max-depth {depth} exceeds the ceiling of {MAX_MAX_DEPTH}. Beyond that a "
            "search becomes a filesystem crawl; name the directory with --search-dir, or "
            "pass the file with --data."
        )
    return depth


def find(
    start: Path | None = None,
    include_fixtures: bool = False,
    with_git: bool = False,
    extensions: Sequence[str] | None = None,
    directories: Sequence[str] | None = None,
    max_depth: int | None = None,
) -> list[Candidate]:
    """Candidates, best first: explicit, then conventional locations.

    Ordering within a group is newest first. Modification time is a weak signal and in
    one common case a actively misleading one: after a fresh clone every file was
    written at checkout, so mtime says they are all equally new. Pass ``with_git`` to
    attach the last commit date, which is the signal that survives a clone.

    ``extensions`` narrows or widens the suffixes scanned. The default omits the
    ambiguous ones - see :data:`AMBIGUOUS_EXTENSIONS` - so pass ``[".jsonld", ".json"]``
    to go looking for JSON-LD specifically. Anything named in ``$LINKED_ARCHI_DATA`` is
    returned whatever its suffix, because that is an explicit statement rather than a guess.
    """
    scanned = _requested_extensions(extensions)
    directories_scanned = _requested_directories(directories)
    depth = _requested_depth(max_depth)
    base = Path(start or Path.cwd()).resolve()
    candidates: list[Candidate] = []
    seen: set[Path] = set()

    def add(path: Path, origin: str) -> None:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            return
        seen.add(resolved)
        stat = resolved.stat()
        candidates.append(Candidate(
            path=resolved,
            origin=origin,
            carries_graphs=EXTENSIONS.get(resolved.suffix.lower(), False),
            size_bytes=stat.st_size,
            modified=stat.st_mtime,
        ))

    for path in from_env():
        add(path, "env")

    found: list[Path] = []
    for root in search_roots(base):
        for name in directories_scanned:
            # `.` stays shallow by default so a root scan does not duplicate the deep walk
            # of every named directory below it. An explicit --max-depth means what it says,
            # including for `.`: that is the flag someone reaches for when the graph is
            # somewhere the convention does not name.
            here = depth if (name != "." or max_depth is not None) else 1
            found.extend(_walk(root / name, here, scanned))
    for path in sorted(found, key=lambda p: p.stat().st_mtime, reverse=True):
        add(path, "search")

    if not include_fixtures:
        candidates = [c for c in candidates if c.origin == "env" or not c.is_fixture]

    if with_git:
        import dataclasses

        candidates = [
            dataclasses.replace(c, git=git_info(c.path)) for c in candidates
        ]
        # Prefer the last commit date over mtime where git knows it, so a fresh clone
        # orders by when the graph actually changed rather than when it was checked out.
        candidates.sort(
            key=lambda c: (
                c.origin != "env",
                -(c.modified if c.git is None or not c.git.committed
                  else _as_epoch(c.git.committed, c.modified)),
            )
        )
    return candidates


def _as_epoch(iso_date: str, fallback: float) -> float:
    import datetime

    try:
        return datetime.datetime.strptime(iso_date, "%Y-%m-%d").timestamp()
    except ValueError:  # pragma: no cover - git's %cs is always this shape
        return fallback


def missing_from_env() -> list[Path]:
    """Paths named in the environment that do not exist.

    Reported so a typo in a project's configuration surfaces as a problem rather than
    as an empty candidate list.
    """
    return [p for p in from_env() if not p.is_file()]


@dataclass(frozen=True)
class Resolution:
    """Which file a directory resolved to, and the reason it was chosen."""

    path: Path
    reason: str
    git: GitInfo | None = None
    caveat: str | None = None


class AmbiguousDirectory(Exception):
    """Several graphs could have been meant, so none is chosen.

    Deliberately an error rather than a best guess. Silently picking one is how an answer
    ends up citing last month's conversion, and the citation makes it look reproducible.
    """

    def __init__(self, directory: Path, candidates: Sequence[Path]) -> None:
        self.directory = directory
        self.candidates = list(candidates)
        listed = "\n".join(f"    {path}" for path in self.candidates)
        super().__init__(
            f"{directory} holds {len(self.candidates)} candidate graphs, so none was "
            f"chosen:\n{listed}\n  Name one with --data, or set $LINKED_ARCHI_DATA."
        )


def resolve_directory(directory: Path, with_git: bool = True) -> Resolution:
    """Pick the canonical graph inside a directory, or refuse and say why.

    Users name a repository - "the graph is in models/archi-graph" - while the queryable
    input is one file inside it. Resolving that here is what stops the alternative, which
    is an agent running its own filesystem search and picking whatever it finds first.

    Graph-carrying serialisations win outright. A directory holding both `merged-graph.trig`
    and `merged-graph.ttl` is the common case, and the TriG is the one that keeps the named
    graphs every scoped query depends on.
    """
    resolved = directory.expanduser().resolve()
    if not resolved.is_dir():
        raise AmbiguousDirectory(resolved, [])

    top_level = sorted(
        entry
        for entry in resolved.iterdir()
        if entry.is_file() and entry.suffix.lower() in DEFAULT_EXTENSIONS
    )
    carrying = [entry for entry in top_level if EXTENSIONS.get(entry.suffix.lower())]
    flattening = [entry for entry in top_level if not EXTENSIONS.get(entry.suffix.lower())]

    if len(carrying) == 1:
        chosen, reason, caveat = carrying[0], "the only graph-carrying file here", None
    elif carrying:
        raise AmbiguousDirectory(resolved, carrying)
    elif len(flattening) == 1:
        chosen = flattening[0]
        reason = "the only RDF file here"
        caveat = (
            f"{chosen.suffix} carries no named graphs, so every graph-scoped query will "
            "return nothing. Prefer a TriG or N-Quads export if one exists."
        )
    elif flattening:
        raise AmbiguousDirectory(resolved, flattening)
    else:
        deeper = [candidate.path for candidate in find(resolved)]
        raise AmbiguousDirectory(resolved, deeper)

    return Resolution(
        path=chosen,
        reason=reason,
        git=git_info(chosen) if with_git else None,
        caveat=caveat,
    )
