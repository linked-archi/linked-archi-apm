"""Does what loaded account for everything the project says contributes to the graph?

This exists because of a specific, expensive failure. A merged artifact was loaded and
queried confidently; it contained no LeanIX model at all, while the LeanIX graph file - the
largest in the repository - sat in the directory next to it. Nothing said so. The dataset
looked complete because it *was* a merge, and a merge is supposed to be complete.

A publishing repository usually declares its inputs in a manifest, so the answer is
available for the cost of reading one YAML file. That is cheaper than a query and far
cheaper than a wrong portfolio answer.

What this module does **not** do is decide. It reports which declared sources appear absent
and says how to confirm, because absence inferred from graph naming is a suspicion and
`core/models` is the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

#: Manifest filenames a publishing repository conventionally uses to declare its inputs.
MANIFEST_NAMES = ("sources-index.yaml", "sources-index.yml", "sources.yaml")

#: How far above the data file to look for a manifest. Bounded, because an unbounded walk
#: towards / would start reading unrelated projects' files.
_MAX_PARENTS = 4

#: The notation slug in a graph IRI is not always the directory name in the manifest.
#: ArchiMate is the case that matters: the converter's `--path-model` defaults to `model`,
#: so `graph/archimate/x.trig` produces IRIs under `/model/`. Verified in the converter
#: output this package's fixtures were extracted from - see PROPOSAL Appendix A3. Without
#: this alias every ArchiMate source would be reported absent, and a false alarm here
#: costs more trust than silence.
NOTATION_ALIASES: dict[str, tuple[str, ...]] = {
    "archimate": ("archimate", "model"),
    "structurizr": ("structurizr", "c4"),
    "c4": ("c4", "structurizr"),
    "plantuml": ("plantuml", "uml"),
}


@dataclass(frozen=True)
class IndexedSource:
    """One entry from the project's manifest, and what became of it."""

    id: str
    target: str
    notation: str | None
    tier: Any = None
    exists: bool = False
    loaded: bool = False
    #: True when a loaded named graph looks like it came from this source, False when
    #: none does, and None when the question cannot be asked - a flattened dataset has
    #: no graph names to compare against.
    represented: bool | None = None


@dataclass
class Completeness:
    manifest: Path | None = None
    sources: list[IndexedSource] = field(default_factory=list)
    unloaded_files: list[Path] = field(default_factory=list)
    notations_present: list[str] = field(default_factory=list)

    @property
    def dropped(self) -> list[IndexedSource]:
        """Declared, present on disk, and not in what loaded.

        The dangerous case, and the one this module was written for: the artifact exists,
        so nothing looks broken, and the merge simply does not contain it.
        """
        return [
            source
            for source in self.sources
            if source.represented is False and source.exists
        ]

    @property
    def never_pulled(self) -> list[IndexedSource]:
        """Declared but absent from disk - an intended graph, not a broken merge."""
        return [source for source in self.sources if not source.exists]

    def notes(self) -> list[str]:
        """Warnings worth interrupting an answer for, most serious first."""
        notes: list[str] = []
        if self.manifest is None:
            if self.unloaded_files:
                shown = ", ".join(str(path) for path in self.unloaded_files[:5])
                more = (
                    f" and {len(self.unloaded_files) - 5} more"
                    if len(self.unloaded_files) > 5
                    else ""
                )
                notes.append(
                    f"{len(self.unloaded_files)} other RDF file(s) sit beside this dataset "
                    f"and were not loaded: {shown}{more}. If this dataset is meant to "
                    "include them, confirm that it does."
                )
            return notes

        dropped = self.dropped
        if dropped and len(self.notations_present) > 1:
            named = ", ".join(f"{source.id} ({source.notation})" for source in dropped)
            notes.append(
                f"this dataset spans {len(self.notations_present)} notation(s), so it looks "
                f"like the merged whole, but {len(dropped)} source(s) declared in "
                f"{self.manifest.name} are on disk and not in it: {named}. A merge that "
                "silently dropped a source still looks complete. Confirm with the query "
                "owner's core/models before answering anything portfolio-wide."
            )
        elif dropped:
            named = ", ".join(source.id for source in dropped)
            notes.append(
                f"single-notation dataset: {len(dropped)} source(s) in "
                f"{self.manifest.name} are on disk and not in it ({named}). Expected when "
                "working on one model; not a basis for an estate-wide answer."
            )

        gone = self.never_pulled
        if gone:
            named = ", ".join(source.id for source in gone)
            notes.append(
                f"{len(gone)} source(s) in {self.manifest.name} have no file on disk "
                f"({named}). The index describes an intended graph that was never fully "
                "pulled, which is a different problem from a dropped merge."
            )
        return notes

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest": str(self.manifest) if self.manifest else None,
            "notations_present": list(self.notations_present),
            "sources": [
                {
                    "id": source.id,
                    "target": source.target,
                    "notation": source.notation,
                    "tier": source.tier,
                    "exists": source.exists,
                    "loaded": source.loaded,
                    "represented": source.represented,
                }
                for source in self.sources
            ],
            "unloaded_files": [str(path) for path in self.unloaded_files],
        }


def find_manifest(paths: Sequence[Path]) -> Path | None:
    """The nearest inputs manifest at or above the loaded files."""
    seen: set[Path] = set()
    for path in paths:
        directory = path.parent.resolve()
        for index, candidate_dir in enumerate([directory, *directory.parents]):
            if index > _MAX_PARENTS or candidate_dir in seen:
                continue
            seen.add(candidate_dir)
            for name in MANIFEST_NAMES:
                candidate = candidate_dir / name
                if candidate.is_file():
                    return candidate
    return None


def _notation_of(target: str) -> str | None:
    """The notation a manifest target implies, from its directory layout.

    `graph/leanix/enterprise-inventory.trig` means leanix. A bare filename means nothing
    can be inferred, which is reported as unknown rather than guessed.
    """
    parts = [part for part in Path(target).parts if part not in (".", "/")]
    if len(parts) >= 3 and parts[0] in {"graph", "graphs", "data"}:
        return parts[1].lower()
    if len(parts) >= 2:
        return parts[0].lower()
    return None


def read_manifest(path: Path) -> list[dict[str, Any]]:
    """Parse the manifest defensively; a malformed one must not break connecting."""
    try:
        import yaml
    except ModuleNotFoundError:  # pragma: no cover - PyYAML is a package dependency
        return []
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(document, dict):
        return []
    sources = document.get("sources")
    if not isinstance(sources, list):
        return []
    return [entry for entry in sources if isinstance(entry, dict)]


def assess(
    loaded_paths: Sequence[Path],
    graph_names: Sequence[str],
    known_extensions: Sequence[str] = (),
) -> Completeness:
    """Compare what loaded against what the project declares, and against its siblings."""
    resolved = {path.resolve() for path in loaded_paths}
    manifest = find_manifest(list(loaded_paths))
    lowered = [name.lower() for name in graph_names]

    if manifest is None:
        return Completeness(
            manifest=None,
            unloaded_files=_sibling_rdf_files(resolved, known_extensions),
        )

    root = manifest.parent
    sources: list[IndexedSource] = []
    notations: set[str] = set()
    for entry in read_manifest(manifest):
        identifier = str(entry.get("id") or "").strip()
        target = str(entry.get("target") or "").strip()
        if not identifier or not target:
            continue
        notation = _notation_of(target)
        candidate = (root / target).resolve()
        tokens = NOTATION_ALIASES.get(notation, (notation,)) if notation else ()

        # Loaded directly is the strongest evidence there is, and it holds even for a
        # flattened dataset with no graph names to inspect - so test it first.
        if candidate in resolved:
            represented: bool | None = True
        elif not lowered:
            represented = None
        elif tokens:
            represented = any(
                f"/{token}/" in name for name in lowered for token in tokens if token
            )
        else:
            represented = None

        # Count the notation the manifest declares, not the aliases used to find it.
        # Counting alias tokens would report three notations where two are present.
        if represented and notation:
            notations.add(notation)
        sources.append(
            IndexedSource(
                id=identifier,
                target=target,
                notation=notation,
                tier=entry.get("tier"),
                exists=candidate.is_file(),
                loaded=candidate in resolved,
                represented=represented,
            )
        )

    return Completeness(
        manifest=manifest,
        sources=sources,
        notations_present=sorted(notations),
        unloaded_files=[],
    )


def _sibling_rdf_files(
    loaded: set[Path], known_extensions: Sequence[str]
) -> list[Path]:
    """Other RDF files in the same directories, which nothing declared as related."""
    if not known_extensions:
        return []
    suffixes = {suffix.lower() for suffix in known_extensions}
    # `merged-graph.ttl` beside `merged-graph.trig` is the same graph in another
    # serialisation, not a source anybody forgot. Flagging it would be a false alarm, and
    # a warning that cries wolf is worse than no warning at all.
    loaded_stems = {path.stem.lower() for path in loaded}
    siblings: list[Path] = []
    for directory in sorted({path.parent for path in loaded}):
        try:
            entries = sorted(directory.iterdir())
        except OSError:  # pragma: no cover - environment dependent
            continue
        for entry in entries:
            if (
                entry.is_file()
                and entry.suffix.lower() in suffixes
                and entry.resolve() not in loaded
                and entry.stem.lower() not in loaded_stems
            ):
                siblings.append(entry)
    return siblings
