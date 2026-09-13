"""Read the routing table and match a question to a pattern.

`assets/patterns.json` is the authoritative routing table; the prose under
`references/patterns/` is the depth behind each entry, and the suite keeps the two in
agreement. This module is the only thing that parses it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Assets are owned by this skill, so the path is skill-relative and never searched for.
PATTERNS_FILE = Path(__file__).resolve().parents[2] / "assets" / "patterns.json"

_WORD = re.compile(r"[a-z0-9]+")


class AnalyseError(RuntimeError):
    """Something the caller asked for cannot be done, with a reason worth printing."""


@dataclass(frozen=True)
class Pattern:
    """One analysis pattern: what routes to it, what it runs, when it stops."""

    name: str
    title: str
    file: str
    triggers: tuple[str, ...]
    templates: tuple[str, ...]
    capabilities: Mapping[str, str]
    stop_when: tuple[str, ...]


def load_patterns(path: Path | None = None) -> dict[str, Pattern]:
    source = Path(path or PATTERNS_FILE)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnalyseError(f"routing table not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise AnalyseError(f"{source.name} is not valid JSON: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("schema_version") != 1:
        raise AnalyseError(f"{source.name} must be an object with schema_version 1")
    raw = document.get("patterns")
    if not isinstance(raw, Mapping) or not raw:
        raise AnalyseError(f"{source.name} declares no patterns")

    patterns: dict[str, Pattern] = {}
    for name, spec in raw.items():
        if not isinstance(spec, Mapping):
            raise AnalyseError(f"pattern {name!r} must be an object")
        missing = {
            "title", "file", "triggers", "templates", "capabilities", "stop_when"
        } - set(spec)
        if missing:
            raise AnalyseError(
                f"pattern {name!r} is missing {', '.join(sorted(missing))}"
            )
        patterns[name] = Pattern(
            name=name,
            title=str(spec["title"]),
            file=str(spec["file"]),
            triggers=tuple(str(t) for t in spec["triggers"]),
            templates=tuple(str(t) for t in spec["templates"]),
            capabilities=dict(spec["capabilities"]),
            stop_when=tuple(str(s) for s in spec["stop_when"]),
        )
    return patterns


@dataclass(frozen=True)
class Match:
    """A candidate pattern, its score, and which trigger phrases hit."""

    pattern: Pattern
    score: int
    matched: tuple[str, ...]


def route(question: str, patterns: Mapping[str, Pattern]) -> list[Match]:
    """Rank patterns against a question, best first.

    Substring matching on trigger phrases, with whole-word matching for single words so
    "fail" does not fire on "failover-free" and "data" does not fire on "database". Crude on
    purpose: a scored ranking that a reader can check beats a clever one they cannot, and the
    caller can always name the pattern with ``--mode``.

    A zero score for every pattern is a real answer - the question does not look like
    anything this skill has a method for - and the caller is told rather than being given the
    alphabetically first pattern.
    """
    text = question.lower()
    words = set(_WORD.findall(text))
    matches: list[Match] = []
    for pattern in patterns.values():
        hits = []
        for trigger in pattern.triggers:
            lowered = trigger.lower()
            if " " in lowered:
                if lowered in text:
                    hits.append(trigger)
            elif lowered in words:
                hits.append(trigger)
        if hits:
            matches.append(Match(pattern=pattern, score=len(hits), matched=tuple(hits)))
    # Score first, then pattern name, so equal scores are reported in a stable order rather
    # than in whatever order the file happened to list them.
    matches.sort(key=lambda match: (-match.score, match.pattern.name))
    return matches


def resolve_mode(
    mode: str | None, question: str, patterns: Mapping[str, Pattern]
) -> tuple[Pattern | None, list[Match]]:
    """The chosen pattern and the ranking that produced it.

    An explicit ``mode`` wins outright and is validated against the table, because a caller
    naming a pattern that does not exist should be told so rather than quietly routed
    somewhere else.
    """
    ranked = route(question, patterns)
    if mode:
        if mode not in patterns:
            raise AnalyseError(
                f"unknown pattern {mode!r}. Available: " + ", ".join(sorted(patterns))
            )
        return patterns[mode], ranked
    return (ranked[0].pattern if ranked else None), ranked


def terms_in(question: str) -> tuple[str, ...]:
    """Quoted phrases from the question, which are the only names it truly supplies.

    Anything unquoted is guesswork - "the errata service" may be one element, two, or a
    phrase nobody modelled - and inventing a `TERM` value is exactly the failure the resolve
    step exists to prevent. Unquoted questions therefore produce a placeholder instead.
    """
    found: list[str] = []
    for quoted in re.findall(r"[\"'\u201c\u2018]([^\"'\u201d\u2019]{2,})[\"'\u201d\u2019]", question):
        candidate = quoted.strip()
        if candidate and candidate not in found:
            found.append(candidate)
    return tuple(found)


def pattern_summary(patterns: Mapping[str, Pattern]) -> Sequence[dict[str, Any]]:
    """The routing table, for `plan --list` and the machine contract."""
    return [
        {
            "pattern": pattern.name,
            "title": pattern.title,
            "file": pattern.file,
            "triggers": list(pattern.triggers),
            "templates": list(pattern.templates),
        }
        for pattern in sorted(patterns.values(), key=lambda p: p.name)
    ]
