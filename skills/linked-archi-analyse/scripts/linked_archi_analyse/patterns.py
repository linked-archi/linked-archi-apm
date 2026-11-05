"""Read the routing table and match a question to a pattern.

`assets/patterns.json` is the authoritative routing table; the prose under
`references/patterns/` is the depth behind each entry, and the suite keeps the two in
agreement. This module is the only thing that parses it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
    notation_mentions: tuple[str, ...]
    resolution: str = "element"
    #: Method order that no parameter expresses: ``{template: (earlier templates...)}`` means
    #: "review those results before running this one", because a judgement on them decides
    #: whether or how it runs. Inputs taken from earlier evidence are derived by the planner
    #: and need no entry here.
    after: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def _after(name: str, spec: Mapping[str, Any], templates: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Validate a pattern's declared review order against its own template list.

    A key must be one of the pattern's templates. A value is either a template listed before
    that key or one the planner always places before pattern evidence (orientation and
    resolution), so a review barrier can never point at a later step.
    """
    raw = spec.get("after", {})
    if not isinstance(raw, Mapping):
        raise AnalyseError(f"pattern {name!r}: after must be an object")
    after: dict[str, tuple[str, ...]] = {}
    for template, earlier in raw.items():
        if template not in templates:
            raise AnalyseError(
                f"pattern {name!r}: after names {template!r}, which the pattern does not run"
            )
        if not isinstance(earlier, list) or not earlier:
            raise AnalyseError(f"pattern {name!r}: after[{template!r}] must be a non-empty list")
        later = templates[templates.index(template):]
        for prerequisite in earlier:
            if prerequisite in later:
                raise AnalyseError(
                    f"pattern {name!r}: {template!r} cannot wait for {prerequisite!r}, which is "
                    "not listed before it"
                )
        after[template] = tuple(str(prerequisite) for prerequisite in earlier)
    return after


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
        resolution = spec.get("resolution", "element")
        if resolution not in ("element", "concept", "vocabulary", "viewpoint"):
            raise AnalyseError(f"pattern {name!r} has unknown resolution {resolution!r}")
        templates = tuple(str(t) for t in spec["templates"])
        patterns[name] = Pattern(
            name=name,
            title=str(spec["title"]),
            file=str(spec["file"]),
            triggers=tuple(str(t) for t in spec["triggers"]),
            templates=templates,
            capabilities=dict(spec["capabilities"]),
            stop_when=tuple(str(s) for s in spec["stop_when"]),
            notation_mentions=tuple(str(n).lower() for n in spec.get("notation_mentions", [])),
            resolution=resolution,
            after=_after(name, spec, templates),
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
    if not matches:
        for pattern in patterns.values():
            named_notations = sorted(words.intersection(pattern.notation_mentions))
            if len(named_notations) >= 2:
                matches.append(Match(pattern=pattern, score=1,
                                     matched=("named notations: " + ", ".join(named_notations),)))
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
            "notation_mentions": list(pattern.notation_mentions),
            "resolution": pattern.resolution,
            "templates": list(pattern.templates),
        }
        for pattern in sorted(patterns.values(), key=lambda p: p.name)
    ]
