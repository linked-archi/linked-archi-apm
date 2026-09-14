"""One version in `apm.yml`, many derived copies: find every one, or rewrite them all.

`apm.yml` said 0.3.0 while six `SKILL.md` files, one `__init__.py` and four passages of
prose said 0.1.0 - two releases behind, in the files a consumer actually reads. Nothing
read any of them, so nothing failed. The stalest copy was the one that matters most:
`apm.yml` is not deployed into a harness, so `metadata.version` in the frontmatter is the
only version an installed skill directory carries, and an operator inspecting
`.kiro/skills/linked-archi-query/` had no other way to tell what they had.

The fix is not "remember to update ten files". It is to name them once, here, so that

* ``python3 tests/version_sync.py`` reports every copy that disagrees, and
* ``python3 tests/version_sync.py --set X.Y.Z`` (``make bump TO=X.Y.Z``) writes all of
  them from one command.

A test in `test_packaging.py` calls :func:`disagreements`, which is what turns the report
into a build failure.

A pattern that matches *nothing* is also a failure. Prose gets reworded, and a site whose
pattern silently stops matching is enforcement that has quietly lapsed - the exact failure
mode this package exists to argue against.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MANIFEST = "apm.yml"

#: The authority. Quoted in YAML per the authoring spec, so the quotes are part of the match.
MANIFEST_VERSION = re.compile(r'^version: "([^"]+)"$', re.M)

#: `metadata.version` in a skill's frontmatter, two spaces in under `metadata:`.
_FRONTMATTER = re.compile(r'^  version: "([^"]+)"$', re.M)

#: A runtime package's `__version__`. Only linked-archi-source declares one today.
_DUNDER = re.compile(r'^__version__ = "([^"]+)"$', re.M)

#: The install pin readers copy: `apm install linked-archi/linked-archi-apm#vX.Y.Z`.
_INSTALL_PIN = re.compile(r"linked-archi-apm#v(\d+\.\d+\.\d+)")

#: USAGE's explanation of what pinning means, which names the same version in prose.
_PROSE_PIN = re.compile(r"means v(\d+\.\d+\.\d+) until")

#: PROPOSAL's status line.
_STATUS_PIN = re.compile(r"by APM \(v(\d+\.\d+\.\d+)\)")

#: Every file that repeats the version, with the patterns whose first group is the literal.
#: Adding a site here extends both the check and the rewrite; there is no second list.
SITES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("skills/linked-archi-source/SKILL.md", (_FRONTMATTER,)),
    ("skills/linked-archi-profile/SKILL.md", (_FRONTMATTER,)),
    ("skills/linked-archi-connect/SKILL.md", (_FRONTMATTER,)),
    ("skills/linked-archi-query/SKILL.md", (_FRONTMATTER,)),
    ("skills/linked-archi-analyse/SKILL.md", (_FRONTMATTER,)),
    ("skills/linked-archi-validate/SKILL.md", (_FRONTMATTER,)),
    ("skills/linked-archi-source/scripts/linked_archi_source/__init__.py", (_DUNDER,)),
    ("README.md", (_INSTALL_PIN,)),
    ("USAGE.md", (_INSTALL_PIN, _PROSE_PIN)),
    ("PROPOSAL.md", (_STATUS_PIN,)),
)


def manifest_version(root: Path = ROOT) -> str:
    """The one authoritative version, read from `apm.yml`."""
    text = (root / MANIFEST).read_text(encoding="utf-8")
    found = MANIFEST_VERSION.search(text)
    if found is None:
        raise SystemExit(f"REFUSED: {MANIFEST} declares no quoted version:")
    return found.group(1)


def disagreements(root: Path = ROOT, version: str | None = None) -> list[str]:
    """Every derived copy that differs from the manifest, and every pattern gone dead.

    Returned as human-readable lines so the test and the CLI report identically.
    """
    expected = version or manifest_version(root)
    problems: list[str] = []
    for relative, patterns in SITES:
        path = root / relative
        if not path.exists():
            problems.append(f"{relative}: listed as a version site but does not exist")
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            matches = list(pattern.finditer(text))
            if not matches:
                problems.append(
                    f"{relative}: nothing matches {pattern.pattern!r} - the version is no "
                    "longer stated here, or the wording moved and this check has lapsed"
                )
                continue
            for match in matches:
                if match.group(1) != expected:
                    line = text.count("\n", 0, match.start()) + 1
                    problems.append(
                        f"{relative}:{line}: says {match.group(1)}, manifest says {expected}"
                    )
    return problems


def rewrite(version: str, root: Path = ROOT) -> list[str]:
    """Write `version` into the manifest and every derived copy. Returns files changed."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"REFUSED: {version!r} is not X.Y.Z")

    changed: list[str] = []
    manifest = root / MANIFEST
    text = manifest.read_text(encoding="utf-8")
    updated = MANIFEST_VERSION.sub(f'version: "{version}"', text, count=1)
    if updated != text:
        manifest.write_text(updated, encoding="utf-8")
        changed.append(MANIFEST)

    for relative, patterns in SITES:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        updated = text
        for pattern in patterns:
            def _swap(match: re.Match[str]) -> str:
                whole = match.group(0)
                start, end = match.span(1)
                return whole[: start - match.start()] + version + whole[end - match.start() :]

            updated = pattern.sub(_swap, updated)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(relative)
    return changed


def main(argv: list[str]) -> int:
    if argv[:1] == ["--set"]:
        if len(argv) != 2:
            print("usage: version_sync.py [--set X.Y.Z]", file=sys.stderr)
            return 2
        changed = rewrite(argv[1])
        remaining = disagreements()
        for relative in changed:
            print(f"  {relative}")
        if remaining:
            print("\nstill disagreeing:", file=sys.stderr)
            for problem in remaining:
                print(f"  {problem}", file=sys.stderr)
            return 1
        print(f"\n  version is {argv[1]} in {len(changed)} file(s)")
        return 0

    if argv:
        print("usage: version_sync.py [--set X.Y.Z]", file=sys.stderr)
        return 2

    problems = disagreements()
    if problems:
        print(f"REFUSED: the version is stated in {len(problems)} place(s) that disagree "
              f"with {MANIFEST}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("\nRewrite them all with: make bump TO=" + manifest_version(), file=sys.stderr)
        return 1
    print(f"  version {manifest_version()} agrees across {len(SITES)} derived site(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
