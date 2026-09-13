#!/usr/bin/env python3
"""Validate every SKILL.md against the Agent Skills specification.

These checks belong in CI: the rules below are the ones that make a strict client refuse to
load a skill, and a skill that does not load fails silently rather than loudly.

Checks:

* frontmatter starts at byte 0 and is closed;
* frontmatter parses as a YAML mapping - every client reads it with a YAML parser,
  and so does GitHub when it renders the file;
* only spec-defined keys - a non-spec key fails validation in strict clients;
* ``name`` matches the parent directory exactly, and is 1-64 lowercase
  alphanumeric characters with single internal hyphens;
* ``description`` is present and within 1024 characters;
* ``compatibility`` is within 500 characters;
* no angle brackets anywhere in frontmatter, since they can carry injected markup;
* every relative link in the body resolves;
* body length is reported, and flagged past the spec's recommended 500 lines.

Run directly, or through ``make skills``. Exits non-zero on any problem.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPEC_KEYS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
RECOMMENDED_BODY_LINES = 500

#: Below this, a description is unlikely to say both what the skill does and when to
#: use it, which is what a client matches on.
MIN_USEFUL_DESCRIPTION = 40

_LINK = re.compile(r"\[[^\]]*\]\(([^)#][^)]*)\)")

#: A colon followed by whitespace or end of line. Inside an unquoted value this opens a
#: nested mapping rather than continuing the sentence, which is the one YAML rule long
#: prose in `description` and `compatibility` walks into.
_PLAIN_COLON = re.compile(r":(?:\s|$)")


def parse_frontmatter(text: str) -> tuple[dict[str, str] | None, str, str | None]:
    """Return ``(keys, body, error)``.

    Deliberately not a YAML parse. The point is to check what a strict client sees
    when it reads the frontmatter, including keys a lenient parser would tolerate.
    """
    if not text.startswith("---"):
        return None, "", "frontmatter must start at byte 0 with ---"
    end = text.find("\n---", 3)
    if end == -1:
        return None, "", "frontmatter is not closed with ---"

    raw, body = text[3:end], text[end + 4:]
    keys: dict[str, str] = {}
    current: str | None = None
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^\S", line):
            key, _, value = line.partition(":")
            current = key.strip()
            keys[current] = value.strip()
        elif current:
            # A folded continuation line, or a nested mapping under `metadata`.
            keys[current] += " " + line.strip()
    return keys, body, None


def frontmatter_body(text: str) -> str:
    """The text between the fences, starting at the first key line.

    Line 1 of the result is line 1 of the frontmatter as GitHub numbers it in a render
    error, which is the report a maintainer is most likely to be holding.
    """
    raw = text[3:text.find("\n---", 3)]
    return raw[1:] if raw.startswith("\n") else raw


def yaml_problems(folder: str, frontmatter: str) -> list[str]:
    """Frontmatter that does not parse is frontmatter no client reads.

    The checks above deliberately avoid a YAML parse, so that a key a lenient parser
    would tolerate is still reported. That leaves the opposite gap, and this closes it:
    frontmatter this validator reads happily and a real parser rejects. One skill
    shipped exactly that - a ``: `` inside an unquoted ``compatibility`` sentence, which
    YAML reads as a nested mapping. Every check here passed, GitHub refused to render
    the file, and a strict client would have refused to load the skill.

    The scan runs first and alone when it finds something, because it names the key and
    the fix where a parser reports only the position at which the grammar broke.
    """
    problems: list[str] = []
    for number, line in enumerate(frontmatter.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator or not value.strip():
            continue
        # Quoted and block scalars carry a colon safely. That is the documented escape.
        if value.strip()[0] in "\"'|>":
            continue
        found = _PLAIN_COLON.search(value)
        if found:
            problems.append(
                f"{folder}: frontmatter line {number} column "
                f"{len(key) + found.start() + 2}: the unquoted {key.strip()!r} value "
                "contains ': ', which YAML reads as a nested mapping. Use ';' instead, "
                "or quote the whole value"
            )
    if problems:
        return problems

    try:
        import yaml
    except ImportError:
        # PyYAML is not a dependency of this validator, and the scan above covers the
        # failure that has occurred. CI installs it, so the parse does run there.
        return problems

    try:
        parsed = yaml.safe_load(frontmatter)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f" at line {mark.line + 1} column {mark.column + 1}" if mark else ""
        problems.append(
            f"{folder}: frontmatter is not valid YAML{where}: "
            f"{getattr(error, 'problem', error)}"
        )
    else:
        if not isinstance(parsed, dict):
            problems.append(
                f"{folder}: frontmatter must be a YAML mapping, not "
                f"{type(parsed).__name__}"
            )
    return problems


def check_skill(skill_md: Path) -> tuple[list[str], list[str], dict[str, int]]:
    folder = skill_md.parent.name
    text = skill_md.read_text(encoding="utf-8")
    problems: list[str] = []
    warnings: list[str] = []

    keys, body, error = parse_frontmatter(text)
    if error or keys is None:
        return [f"{folder}: {error}"], [], {}

    problems += yaml_problems(folder, frontmatter_body(text))

    unexpected = set(keys) - SPEC_KEYS
    if unexpected:
        problems.append(
            f"{folder}: non-spec frontmatter keys {sorted(unexpected)}; strict "
            "clients refuse to load these"
        )

    name = keys.get("name", "")
    if not name:
        problems.append(f"{folder}: missing name")
    else:
        if not NAME_PATTERN.match(name):
            problems.append(
                f"{folder}: name {name!r} must be lowercase alphanumeric with single "
                "internal hyphens"
            )
        if len(name) > MAX_NAME:
            problems.append(f"{folder}: name is {len(name)} chars, max {MAX_NAME}")
        if name != folder:
            problems.append(
                f"{folder}: name {name!r} must equal the folder name, or the skill "
                "will not load"
            )

    description = keys.get("description", "")
    if not description:
        problems.append(f"{folder}: missing description")
    elif len(description) > MAX_DESCRIPTION:
        problems.append(
            f"{folder}: description is {len(description)} chars, max {MAX_DESCRIPTION}"
        )
    elif len(description) < MIN_USEFUL_DESCRIPTION:
        warnings.append(
            f"{folder}: description is short; state what it does AND when to use it"
        )

    compatibility = keys.get("compatibility", "")
    if len(compatibility) > MAX_COMPATIBILITY:
        problems.append(
            f"{folder}: compatibility is {len(compatibility)} chars, "
            f"max {MAX_COMPATIBILITY}"
        )

    frontmatter_text = text[: text.find("\n---", 3)]
    if "<" in frontmatter_text or ">" in frontmatter_text:
        problems.append(f"{folder}: angle brackets in frontmatter")

    body_lines = len(body.splitlines())
    if body_lines > RECOMMENDED_BODY_LINES:
        warnings.append(
            f"{folder}: body is {body_lines} lines; the spec recommends under "
            f"{RECOMMENDED_BODY_LINES}"
        )

    # Activation hands an agent this text and no filesystem location, so a skill that does
    # not say how to resolve its own command invites the exact behaviour we are removing:
    # one field session ran `find / -maxdepth 6` looking for these scripts and timed out.
    if "## Invocation and companions" not in body:
        problems.append(
            f"{folder}: no '## Invocation and companions' section. Every skill must state "
            "its owner command and the resolution order, because activation does not "
            "expose where the skill is installed"
        )
    elif "never search" not in body.lower():
        problems.append(
            f"{folder}: the invocation section must forbid searching the filesystem for "
            "skills, scripts or assets"
        )
    if "doctor" not in body:
        warnings.append(
            f"{folder}: does not mention a doctor command, which is the one-call answer "
            "to an unresolved command or companion"
        )

    links = _LINK.findall(body)
    for link in links:
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        target = (skill_md.parent / link).resolve()
        if not target.exists():
            problems.append(f"{folder}: broken link {link}")

    return problems, warnings, {
        "description": len(description),
        "compatibility": len(compatibility),
        "body": body_lines,
        "links": len(links),
    }


def main() -> int:
    skills = sorted(ROOT.glob("skills/*/SKILL.md"))
    if not skills:
        print(f"No SKILL.md found under {ROOT / 'skills'}", file=sys.stderr)
        return 2

    all_problems: list[str] = []
    all_warnings: list[str] = []

    for skill_md in skills:
        problems, warnings, sizes = check_skill(skill_md)
        all_problems += problems
        all_warnings += warnings
        status = "FAIL" if problems else "ok  "
        folder = skill_md.parent.name
        if sizes:
            print(
                f"{status} {folder:24} desc={sizes['description']:4} "
                f"compat={sizes['compatibility']:3} body={sizes['body']:3}L "
                f"links={sizes['links']}"
            )
        else:
            print(f"{status} {folder}")

    print()
    for warning in all_warnings:
        print(f"warn: {warning}")
    for problem in all_problems:
        print(f"FAIL: {problem}")

    if all_problems:
        print(f"\n{len(all_problems)} problem(s) across {len(skills)} skill(s)")
        return 1
    print(f"{len(skills)} skill(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
