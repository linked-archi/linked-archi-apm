"""Assemble already-executed envelopes into one reviewable artifact.

Input is envelopes the query owner wrote. Nothing is re-executed, no dataset is opened, and
no SPARQL is issued - the queries are carried forward as text, exactly as recorded.

What makes this worth having: "include all the sources and queries" stops being a manual
assembly step at the end of an investigation, and stops depending on the agent remembering to
keep them.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .patterns import AnalyseError

#: The classes every interpretation must separate. The whole discipline of this skill is that
#: none of them silently becomes another, so the bundler requires the split to be declared -
#: an empty class is a statement, a missing class is an omission.
CLAIM_CLASSES = (
    "graph_facts",
    "derived_facts",
    "document_statements",
    "inferences",
    "unknowns",
)

#: Rows kept per step. A bundle is for review, not a data export: the query and its identity
#: are what make it reproducible, and anyone who wants every row can re-run the query.
SNAPSHOT_ROWS = 10

#: Written by `la-profile verify`, read by the query owner, and read here. A path convention
#: shared by three owners and imported by none of them; each documents these two constants.
STATE_DIR_ENV = "LINKED_ARCHI_STATE_DIR"
DEFAULT_STATE_DIR = Path("~/.cache/linked-archi/verified")


def _verification_marker(dataset_id: str, profile_id: str, profile_version: Any) -> bool:
    """Whether this (dataset, profile, version) was ever verified without errors.

    Best effort and never fatal: the absence of a marker means "not known to be verified",
    which is exactly what gets reported. An unreadable cache is the same answer.
    """
    if not dataset_id or not profile_id:
        return False
    configured = os.environ.get(STATE_DIR_ENV)
    base = Path(configured).expanduser() if configured else DEFAULT_STATE_DIR.expanduser()
    key = f"{dataset_id}\n{profile_id}\n{profile_version}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    try:
        return (base / f"{digest}.verified").is_file()
    except OSError:  # pragma: no cover - environment dependent
        return False


def _read_envelope(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnalyseError(f"step file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AnalyseError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(document, Mapping):
        raise AnalyseError(f"{path.name} is not a result envelope")
    version = document.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise AnalyseError(
            f"{path.name} has schema_version {version!r}; this bundler reads version 1. "
            "Re-run the step with a matching linked-archi-query, rather than bundling a "
            "shape neither side agrees on."
        )
    for required in ("query", "query_id", "dataset_id", "profile_id", "profile_version",
                     "executed_at", "row_count"):
        if required not in document:
            raise AnalyseError(f"{path.name} is missing {required!r}; not a query envelope")
    return dict(document)


def _validate_findings(findings: Mapping[str, Any], step_numbers: set[int]) -> dict[str, Any]:
    """Require the classes, and require every claim to cite a step that exists.

    The bundler does not author the interpretation - it cannot, it has not read the rows - but
    an uncited claim in a reproducibility artifact defeats the artifact, so it refuses one.
    """
    missing = [name for name in CLAIM_CLASSES if name not in findings]
    if missing:
        raise AnalyseError(
            "findings must declare every claim class, even when empty: missing "
            + ", ".join(missing)
            + ". An empty class is a statement; a missing one is an omission."
        )
    unknown = set(findings) - set(CLAIM_CLASSES) - {"answer"}
    if unknown:
        raise AnalyseError(
            "findings has unknown key(s): " + ", ".join(sorted(unknown))
            + f". Expected: answer, {', '.join(CLAIM_CLASSES)}"
        )

    validated: dict[str, Any] = {"answer": str(findings.get("answer", "")).strip()}
    for name in CLAIM_CLASSES:
        claims = findings[name]
        if not isinstance(claims, list):
            raise AnalyseError(f"findings.{name} must be a list")
        checked = []
        for index, claim in enumerate(claims):
            if not isinstance(claim, Mapping) or "claim" not in claim:
                raise AnalyseError(f"findings.{name}[{index}] needs a 'claim'")
            cites = claim.get("steps") or []
            if not isinstance(cites, list) or any(not isinstance(c, int) for c in cites):
                raise AnalyseError(f"findings.{name}[{index}].steps must be a list of integers")
            # An unknown is the one class that legitimately cites nothing: "runtime call
            # volume is not represented" rests on the absence of evidence, not on a step.
            if name != "unknowns" and not cites:
                raise AnalyseError(
                    f"findings.{name}[{index}] cites no step. Every claim except an unknown "
                    "must name at least one step it rests on."
                )
            unknown_steps = [c for c in cites if c not in step_numbers]
            if unknown_steps:
                raise AnalyseError(
                    f"findings.{name}[{index}] cites step(s) {unknown_steps}, which are not "
                    f"in this bundle (have: {sorted(step_numbers)})"
                )
            checked.append({"claim": str(claim["claim"]), "steps": list(cites)})
        validated[name] = checked
    return validated


@dataclass
class Bundle:
    """One investigation, reviewable on a machine that never ran it."""

    created_at: str
    question: str
    dataset_id: str
    dataset_revision: str | None
    profile_id: str
    profile_version: Any
    profile_verified: bool
    truncated: bool
    caveats: list[str]
    steps: list[dict[str, Any]]
    findings: dict[str, Any] | None = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": 1,
            "created_at": self.created_at,
            "question": self.question,
            "dataset": {
                "id": self.dataset_id,
                "revision": self.dataset_revision,
            },
            "profile": {
                "id": self.profile_id,
                "version": self.profile_version,
                "verified": self.profile_verified,
            },
            "truncated": self.truncated,
            "caveats": list(self.caveats),
            "steps": list(self.steps),
        }
        if self.findings is not None:
            document["findings"] = self.findings
        return document

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, ensure_ascii=False)


def build_bundle(
    step_files: Sequence[Path | str],
    *,
    question: str = "",
    findings_file: Path | str | None = None,
    dataset_revision: str | None = None,
) -> Bundle:
    """Read envelopes, refuse an incoherent set, and assemble.

    Refuses **mixed dataset or profile identities**: a bundle spanning two vocabularies or two
    datasets looks reproducible and is not, and that is a worse failure than an error, because
    nothing about the artifact reveals it.
    """
    if not step_files:
        raise AnalyseError("a bundle needs at least one --step envelope")

    envelopes = [(Path(path), _read_envelope(Path(path))) for path in step_files]

    datasets = {envelope["dataset_id"] for _, envelope in envelopes}
    if len(datasets) > 1:
        raise AnalyseError(
            "these steps ran against different datasets: "
            + ", ".join(sorted(datasets))
            + ". One bundle is one dataset; a mixed one reads as reproducible and is not."
        )
    profiles = {
        (envelope["profile_id"], envelope["profile_version"]) for _, envelope in envelopes
    }
    if len(profiles) > 1:
        readable = ", ".join(f"{name} v{version}" for name, version in sorted(map(str, p) for p in profiles))
        raise AnalyseError(
            f"these steps used different profiles: {readable}. The same term can mean "
            "different things under two profiles, so the results are not comparable."
        )

    dataset_id = next(iter(datasets))
    profile_id, profile_version = next(iter(profiles))

    steps: list[dict[str, Any]] = []
    caveats: list[str] = []
    truncated = False
    for number, (path, envelope) in enumerate(envelopes, start=1):
        truncated = truncated or bool(envelope.get("truncated"))
        for warning in envelope.get("warnings") or []:
            if warning not in caveats:
                caveats.append(warning)
        rows = envelope.get("rows") or []
        steps.append({
            "number": number,
            "source_file": path.name,
            "template": envelope.get("template"),
            "query": envelope["query"],
            "query_id": envelope["query_id"],
            "executed_at": envelope["executed_at"],
            "elapsed_ms": envelope.get("elapsed_ms"),
            "form": envelope.get("form"),
            "variables": list(envelope.get("variables") or []),
            "row_count": envelope["row_count"],
            "truncated": bool(envelope.get("truncated")),
            "warnings": list(envelope.get("warnings") or []),
            "boolean": envelope.get("boolean"),
            # A bounded snapshot, and it says so. A truncated snapshot of a truncated result
            # would otherwise be two floors deep with nothing recording either.
            "rows_shown": len(rows[:SNAPSHOT_ROWS]),
            "rows": rows[:SNAPSHOT_ROWS],
            "rows_omitted": max(0, len(rows) - SNAPSHOT_ROWS),
        })

    findings = None
    if findings_file is not None:
        path = Path(findings_file)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AnalyseError(f"findings file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise AnalyseError(f"{path.name} is not valid JSON: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise AnalyseError(f"{path.name} must be a JSON object")
        findings = _validate_findings(raw, {step["number"] for step in steps})

    return Bundle(
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        question=question.strip(),
        dataset_id=dataset_id,
        dataset_revision=dataset_revision,
        profile_id=profile_id,
        profile_version=profile_version,
        profile_verified=_verification_marker(dataset_id, profile_id, profile_version),
        truncated=truncated,
        caveats=caveats,
        steps=steps,
        findings=findings,
    )


def render_markdown(bundle: Mapping[str, Any]) -> str:
    """The same object as the human answer, so the two cannot disagree.

    Generated rather than written by hand: an answer typed separately from the bundle is an
    answer that can cite a query the bundle does not contain.
    """
    dataset = bundle.get("dataset") or {}
    profile = bundle.get("profile") or {}
    lines: list[str] = []
    lines.append(f"# {bundle.get('question') or 'Investigation'}")
    lines.append("")
    lines.append(f"- Dataset: `{dataset.get('id')}`" + (
        f" at revision `{dataset.get('revision')}`" if dataset.get("revision") else ""
    ))
    lines.append(
        f"- Profile: `{profile.get('id')}` v{profile.get('version')}"
        + (" (verified against this dataset)" if profile.get("verified")
           else " (**not verified** against this dataset)")
    )
    lines.append(f"- Steps: {len(bundle.get('steps') or [])}")
    if bundle.get("truncated"):
        lines.append(
            "- **A result was truncated.** Counts below are floors, not totals."
        )
    lines.append("")

    if bundle.get("caveats"):
        lines.append("## Caveats carried from the queries")
        lines.append("")
        for caveat in bundle["caveats"]:
            lines.append(f"- {caveat}")
        lines.append("")

    findings = bundle.get("findings")
    if findings:
        if findings.get("answer"):
            lines.append("## Answer")
            lines.append("")
            lines.append(findings["answer"])
            lines.append("")
        titles = {
            "graph_facts": "Graph facts",
            "derived_facts": "Derived from the graph",
            "document_statements": "Document statements",
            "inferences": "Analyst inference",
            "unknowns": "Unknown, and why",
        }
        for name in CLAIM_CLASSES:
            claims = findings.get(name) or []
            lines.append(f"## {titles[name]}")
            lines.append("")
            if not claims:
                lines.append("_None._")
            for claim in claims:
                cites = ", ".join(f"step {number}" for number in claim.get("steps") or [])
                lines.append(f"- {claim['claim']}" + (f" ({cites})" if cites else ""))
            lines.append("")

    lines.append("## Queries")
    lines.append("")
    for step in bundle.get("steps") or []:
        flag = " — truncated" if step.get("truncated") else ""
        lines.append(
            f"### Step {step['number']}: {step.get('template') or 'ad-hoc query'}"
            f" ({step['row_count']} row(s){flag})"
        )
        lines.append("")
        lines.append(f"`{step['query_id'][:12]}` at {step['executed_at']}")
        lines.append("")
        lines.append("```sparql")
        lines.append(step["query"].rstrip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
