"""What ran, against what, under which profile.

Records ``profile_id`` and ``profile_version`` alongside the query and the dataset.
Without those a saved result records
the query but not the vocabulary that gave it meaning, so a result produced under
one profile and read under another looks reproducible and is not.

The envelope is also what lets an answer cite itself. Every conclusion in an
investigation should be traceable to a query hash, a dataset identity and a
timestamp; see ``skills/linked-archi-analyse/references/output-contract.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_WHITESPACE = re.compile(r"\s+")


def query_id(query: str) -> str:
    """A stable identifier for a query's meaning, not its formatting.

    Whitespace is collapsed before hashing so re-indenting a template does not
    invalidate every recorded result that used it. Anything else - a changed IRI,
    a changed limit - produces a different id, which is the point.
    """
    return hashlib.sha256(
        _WHITESPACE.sub(" ", query.strip()).encode("utf-8")
    ).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Envelope:
    """A result plus the context needed to reproduce or audit it."""

    query: str
    query_id: str
    dataset_id: str
    profile_id: str
    profile_version: int
    executed_at: str
    elapsed_ms: int
    row_count: int
    #: Milliseconds spent loading the dataset before the query ran. Reported separately
    #: because the two are not comparable work: on a large local dataset the load can
    #: dominate by orders of magnitude while ``elapsed_ms`` shows single digits, so a
    #: reader who saw only ``elapsed_ms`` drew the wrong conclusion about cost.
    #: Zero against a remote endpoint, and near-zero on a cached local store.
    load_ms: int = 0
    truncated: bool = False
    template: str | None = None
    form: str | None = None
    variables: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    boolean: bool | None = None
    triples: str | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        *,
        query: str,
        dataset_id: str,
        profile_id: str,
        profile_version: int,
        elapsed_ms: int,
        row_count: int,
        load_ms: int = 0,
        template: str | None = None,
        form: str | None = None,
        variables: list[str] | None = None,
        rows: list[dict[str, Any]] | None = None,
        boolean: bool | None = None,
        triples: str | None = None,
        truncated: bool = False,
        warnings: list[str] | None = None,
    ) -> "Envelope":
        return cls(
            query=query,
            query_id=query_id(query),
            dataset_id=dataset_id,
            profile_id=profile_id,
            profile_version=profile_version,
            executed_at=utc_now(),
            elapsed_ms=elapsed_ms,
            row_count=row_count,
            load_ms=load_ms,
            truncated=truncated,
            template=template,
            form=form,
            variables=list(variables or []),
            rows=list(rows or []),
            boolean=boolean,
            triples=triples,
            warnings=list(warnings or []),
        )

    #: Version of the SERIALISED shape, not of the class. An envelope written to a file is
    #: read back by another owner - `la-analyse bundle` consumes exactly these files - so it
    #: is a wire format and needs the same fail-closed versioning as every other boundary
    #: here. Kept out of the dataclass fields so the in-process API is unchanged.
    SCHEMA_VERSION = 1

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.SCHEMA_VERSION, **asdict(self)}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def write(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json() + "\n", encoding="utf-8")
        return target

    # -- presentation -------------------------------------------------------

    def citation(self) -> str:
        """One line an answer can quote to show where a claim came from.

        The load cost appears only when it is material. A cached store loads in tens
        of milliseconds and saying so on every line would be noise; a cold parse costs
        seconds, and that is exactly when someone should see that the time went to
        loading rather than to the query.
        """
        cost = f"{self.row_count} row(s)"
        if self.load_ms >= 250:
            cost += f" | load {self.load_ms} ms, query {self.elapsed_ms} ms"
        return (
            f"{self.template or 'ad-hoc query'} | query {self.query_id[:12]} | "
            f"dataset {self.dataset_id} | profile {self.profile_id}"
            f" v{self.profile_version} | {self.executed_at} | {cost}"
        )

    def to_table(self, limit: int = 100) -> str:
        """An aligned markdown table, or a finding when there is nothing to show.

        Opt-in as `--format md` since `tsv` became the default. The column padding is why:
        it is what makes the table readable in a console, and it cost 2.5 kB of whitespace
        on the 108-row result measured in :meth:`to_tsv` - worth paying when a person is
        reading, not worth paying on every agent call.

        An empty result is reported as a finding rather than a failure, and says
        so, because "no capability is unrealised" and "no capability is modelled"
        are different statements and only the orientation templates can tell them
        apart.
        """
        if self.boolean is not None:
            return "\n\n".join([str(self.boolean), *self._caveat_lines(), self.citation()])
        if self.triples is not None:
            return "\n\n".join([str(self.triples), *self._caveat_lines(), self.citation()])
        if not self.rows:
            # A hand-written query that returns nothing is usually broken rather than
            # evidence of absence, and the honest framing above reads as permission to
            # report "none". One field session took it that way, then re-ran a template
            # four times instead of linting the query it had just invented.
            hint = (
                "If this query was hand-written or adapted, lint it before concluding "
                "anything: `la-query lint --query '...'`. Check the graph scope and the "
                "direction of every relationship too - the qualified form is the default, "
                "and reversing source and target returns nothing silently."
                if self.template is None
                else ""
            )
            return "\n\n".join(
                [
                    "(no rows)",
                    "An empty result is a finding, not a failure. Before reporting "
                    "'none', confirm with the orientation templates that the data you "
                    "expect is loaded and in scope - an empty graph and a graph with no "
                    "matching elements look identical from here.",
                    *([hint] if hint else []),
                    *self._caveat_lines(),
                    self.citation(),
                ]
            )

        columns = self.variables or sorted({k for row in self.rows for k in row})
        shown = self.rows[:limit]
        note = self._truncation_note(limit)
        banner = f"{note}\n\n" if note else ""
        widths = {
            col: max(len(col), *(len(str(row.get(col, ""))) for row in shown))
            for col in columns
        }
        head = "| " + " | ".join(col.ljust(widths[col]) for col in columns) + " |"
        rule = "|" + "|".join("-" * (widths[col] + 2) for col in columns) + "|"
        body = [
            "| " + " | ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns) + " |"
            for row in shown
        ]
        footer = "\n" + "\n".join(self._footer_lines(limit))
        return banner + "\n".join([head, rule, *body]) + footer + f"\n\n{self.citation()}"

    def to_tsv(self, limit: int = 100) -> str:
        """Tab-separated rows, with the provenance kept as `#` comment lines.

        The default, because it is the cheapest shape that still carries everything: on a
        108-row result it measured 11.5 kB against 14.9 kB for the aligned markdown table
        (which showed only 100 of the rows) and 21.8 kB for the full JSON envelope. Most of
        the JSON cost is the column name repeated on every row; the envelope's metadata is
        708 bytes of it. Agents were reaching for `jq` to recover columns from that.

        The furniture is commented rather than moved to stderr, so that capturing stdout
        alone cannot silently drop the citation - and `grep -v '^#'` still leaves pure
        rows for `cut`. Values are escaped, because a literal containing a tab would
        otherwise invent a column and nothing downstream could tell.

        Not a W3C SPARQL-TSV document, and deliberately not claiming to be one: the
        connect adapters flatten every term to its lexical form before it reaches here,
        so the type, datatype and language a compliant serialisation needs are already
        gone. `--format json` has the same values, not richer ones.
        """
        if self.boolean is not None or self.triples is not None or not self.rows:
            # Nothing tabular to render, and every one of these shapes is prose whose
            # wording matters - an empty result especially. Render it exactly once.
            return self.to_table(limit=limit)

        columns = self.variables or sorted({key for row in self.rows for key in row})
        lines = ["\t".join(columns)]
        lines += [
            "\t".join(self._tsv_cell(row.get(column, "")) for column in columns)
            for row in self.rows[:limit]
        ]
        note = self._truncation_note(limit)
        return "\n".join(
            [
                *(self._commented([note]) if note else []),
                *lines,
                # The separator is a comment too, not a bare blank line: `grep -v '^#'`
                # has to leave the header and the rows and nothing else, or `cut` reads
                # an empty field as a row.
                *self._commented(["", *self._footer_lines(limit), self.citation()]),
            ]
        )

    @staticmethod
    def _tsv_cell(value: object) -> str:
        """Escape a value so it cannot invent a column or a row."""
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace("\t", "\\t")
            .replace("\r", "\\r")
            .replace("\n", "\\n")
        )

    @staticmethod
    def _commented(lines: list[str]) -> list[str]:
        """Prefix every physical line, so a multi-line caveat stays fully commented."""
        return [
            f"# {physical}" if physical else "#"
            for line in lines
            for physical in str(line).split("\n")
        ]

    def _truncation_note(self, limit: int) -> str:
        """The warning that precedes the rows, or "" when the result is complete.

        Announced before the rows as well as after them. It was only in the footer once,
        and a field session read a 200-row result, grepped the visible part for a term,
        found none, and nearly reported that those views did not exist.
        """
        if not (self.truncated or len(self.rows) > limit):
            return ""
        return (
            f"NOTE: showing {min(limit, len(self.rows))} of {self.row_count} row(s)"
            + (
                " and the result hit the query's row limit, so counts here are a "
                "floor - report 'at least', and never read absence from this result."
                if self.truncated
                else " - raise --limit, or --format json to see the rest."
            )
        )

    def _footer_lines(self, limit: int) -> list[str]:
        """What follows the rows, in one wording for every tabular format."""
        count = f"{self.row_count} row(s)"
        if len(self.rows) > limit:
            count += f", showing {limit}"
        lines = [count]
        if self.truncated:
            lines.append(
                "Result was truncated at the row limit, so this is a floor: "
                "report 'at least' rather than a total."
            )
        return lines + self._caveat_lines()

    def _caveat_lines(self) -> list[str]:
        """The caveats, for every output shape rather than only for a populated table.

        They used to be rendered in the table branch alone, which dropped them from
        empty, boolean and CONSTRUCT results. That put the "profile has not been
        verified against this dataset" caveat exactly where it could not be read: an
        unfitting profile's symptom IS the empty result, so the one run that most
        needed the explanation was the one run that never printed it. Verified in the
        field - a 1.3 dataset read with a pre-1.3 profile returned `(no rows)` and
        generic advice, while the caveat naming the cause sat in the JSON output only.
        """
        return [f"caveat: {warning}" for warning in self.warnings]
