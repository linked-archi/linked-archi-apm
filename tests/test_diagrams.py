"""Structural checks on every Mermaid diagram in the site.

Mermaid renders in the browser, so `mkdocs build --strict` cannot see a syntax error in a
diagram: the page builds, ships, and shows an error box to the reader instead of a picture.
Rendering here would mean a headless browser, which is a heavy dependency for a docs check.

These tests cover the mistakes that actually break a diagram and are invisible until it is
viewed: an unbalanced bracket or quote, a `subgraph` with no `end`, an edge pointing at
nothing, and a diagram type Mermaid does not know. They do not attempt to be a parser.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from support import ROOT

DOCS = ROOT / "docs"
FENCE = re.compile(r"^```mermaid\s*$(.*?)^```\s*$", re.MULTILINE | re.DOTALL)

#: The diagram types this site uses. A new one is a deliberate addition, not a typo.
KNOWN_TYPES = ("flowchart", "sequenceDiagram", "graph")

#: Arrow forms used here. `-.->` and `<-->` are easy to mistype as `-.>` or `<->`.
ARROW = re.compile(r"(-{2,3}>|-\.->|<-{2,3}>|-{3}|===>|--)")


def diagrams() -> list[tuple[Path, int, str]]:
    """Every Mermaid block in the site, as (page, ordinal, body)."""
    found: list[tuple[Path, int, str]] = []
    for page in sorted(DOCS.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        for ordinal, match in enumerate(FENCE.finditer(text), start=1):
            found.append((page.relative_to(DOCS), ordinal, match.group(1)))
    return found


def code_lines(body: str) -> list[str]:
    """Non-blank, non-comment lines."""
    return [
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith("%%")
    ]


class TestEveryDiagramIsStructurallySound(unittest.TestCase):
    def setUp(self):
        self.diagrams = diagrams()
        self.assertTrue(self.diagrams, "no Mermaid diagrams found; the fence regex is wrong")

    def test_each_declares_a_known_type(self):
        for page, ordinal, body in self.diagrams:
            with self.subTest(page=str(page), diagram=ordinal):
                first = code_lines(body)[0]
                self.assertTrue(
                    first.startswith(KNOWN_TYPES),
                    f"diagram {ordinal} in {page} starts with {first!r}; expected one of "
                    f"{KNOWN_TYPES}",
                )

    def test_delimiters_balance(self):
        for page, ordinal, body in self.diagrams:
            with self.subTest(page=str(page), diagram=ordinal):
                for name, opener, closer in (("square", "[", "]"), ("curly", "{", "}")):
                    self.assertEqual(
                        body.count(opener), body.count(closer),
                        f"diagram {ordinal} in {page} has unbalanced {name} brackets: "
                        f"{body.count(opener)} {opener} vs {body.count(closer)} {closer}",
                    )
                self.assertEqual(
                    body.count('"') % 2, 0,
                    f"diagram {ordinal} in {page} has an odd number of double quotes",
                )

    #: Everything `end` can close. `subgraph` is the flowchart one; the rest are
    #: sequenceDiagram blocks, and counting only subgraphs reports a false imbalance on any
    #: sequence diagram that uses a loop.
    BLOCK_OPENERS = ("subgraph", "loop", "alt", "opt", "par", "critical", "rect", "box")

    def test_blocks_are_closed(self):
        for page, ordinal, body in self.diagrams:
            with self.subTest(page=str(page), diagram=ordinal):
                lines = code_lines(body)
                opened = sum(
                    1 for line in lines
                    if line.split(" ")[0] in self.BLOCK_OPENERS
                )
                closed = sum(1 for line in lines if line == "end")
                self.assertEqual(
                    opened, closed,
                    f"diagram {ordinal} in {page} opens {opened} block(s) and closes {closed}",
                )

    def test_no_edge_points_at_nothing(self):
        """`A -->|"label"|` with the target left off renders as a broken diagram."""
        for page, ordinal, body in self.diagrams:
            for line in code_lines(body):
                if not ARROW.search(line) or line.startswith(("subgraph", "sequenceDiagram")):
                    continue
                tail = ARROW.split(line)[-1].strip()
                # An edge label closes with `|`; what follows it must be the target.
                if tail.startswith("|"):
                    tail = tail.rpartition("|")[2].strip()
                with self.subTest(page=str(page), diagram=ordinal, line=line):
                    self.assertTrue(
                        tail, f"edge with no target in {page} diagram {ordinal}: {line!r}"
                    )

    def test_direction_only_appears_inside_a_subgraph(self):
        """A stray `direction` at top level is ignored silently, which looks like a no-op fix."""
        for page, ordinal, body in self.diagrams:
            depth = 0
            for line in code_lines(body):
                if line.startswith("subgraph"):
                    depth += 1
                elif line == "end":
                    depth -= 1
                elif line.startswith("direction "):
                    with self.subTest(page=str(page), diagram=ordinal):
                        self.assertGreater(
                            depth, 0,
                            f"`{line}` sits outside any subgraph in {page} diagram {ordinal}; "
                            "set the direction on the flowchart header instead",
                        )


if __name__ == "__main__":
    unittest.main()
