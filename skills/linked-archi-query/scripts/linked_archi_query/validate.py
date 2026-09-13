"""Read-only SPARQL enforcement.

Three properties this has to get right, each learned the hard way:

1. **No false positives.** Scanning for update keywords with ``\\bADD\\b``-style patterns
   after stripping IRIs, literals and comments is not enough. Both ``?`` and ``:`` are
   non-word characters, so ``\\b`` matches inside a variable (``?add``) and inside a
   prefixed name (``ex:copy``), rejecting legitimate read-only queries. Variables and
   prefixed names are stripped too.
2. **Keyword position matters.** ``WITH`` is only meaningful as an update prologue,
   so it is rejected at the head of a query rather than anywhere in it - a
   ``VALUES`` block or a variable may legitimately be named after it.
3. **Reasons, not just refusals.** Every rejection names the construct found, so
   an agent can explain the refusal instead of reporting a generic failure.

Client-side checking is a guard, not a security boundary. Point the adapters at a
read-only endpoint or a read-only credential as well; see
``skills/linked-archi-query/references/safety.md``.
"""

from __future__ import annotations

import re

#: Query forms this package will execute. Everything else is refused.
ALLOWED_FORMS = frozenset({"SELECT", "ASK", "CONSTRUCT", "DESCRIBE"})

#: SPARQL Update keywords. Any occurrence in scannable text is a refusal.
_UPDATE_WORDS = re.compile(
    r"\b(?:INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|COPY|MOVE|ADD)\b", re.IGNORECASE
)

#: ``WITH`` opens an update prologue. Legal only there, so only checked there.
_LEADING_WITH = re.compile(r"^\s*WITH\b", re.IGNORECASE)

_FORM = re.compile(
    r"\b(SELECT|ASK|CONSTRUCT|DESCRIBE|INSERT|DELETE|LOAD|CLEAR|CREATE|DROP|COPY|MOVE|ADD)\b",
    re.IGNORECASE,
)
_PROLOGUE = re.compile(
    r"(?im)^\s*(?:PREFIX\s+[\w.-]*:\s*<[^>]*>|BASE\s*<[^>]*>)\s*$"
)
_PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}")
_SERVICE = re.compile(r"\bSERVICE\b", re.IGNORECASE)


class QueryError(ValueError):
    """A query is not safe to execute, or is not a query at all."""


def split_comments(text: str) -> list[tuple[bool, str]]:
    """Split ``text`` into ``(is_comment, chunk)`` segments, in order.

    Shared by the renderer and this module because both need the same distinction
    and for the same reason: a template's prose header names the placeholders it
    uses, so a header is not evidence that a placeholder is unresolved, and
    rewriting one would turn an explanation of the mechanism into an example of
    its output.

    Tracks quotes and angle brackets, so a ``#`` inside a literal or inside an IRI
    fragment is not mistaken for the start of a comment.
    """
    segments: list[tuple[bool, str]] = []
    in_single = in_double = in_iri = False
    index = start = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and (in_single or in_double):
            index += 2
            continue
        if char == '"' and not in_single and not in_iri:
            in_double = not in_double
        elif char == "'" and not in_double and not in_iri:
            in_single = not in_single
        elif char == "<" and not in_single and not in_double:
            in_iri = True
        elif char == ">" and in_iri:
            in_iri = False
        elif char == "\n":
            in_single = in_double = in_iri = False
        elif char == "#" and not (in_single or in_double or in_iri):
            end_of_line = text.find("\n", index)
            end_of_line = len(text) if end_of_line == -1 else end_of_line
            segments.append((False, text[start:index]))
            segments.append((True, text[index:end_of_line]))
            start = index = end_of_line
            continue
        index += 1
    segments.append((False, text[start:]))
    return segments


def code_only(text: str) -> str:
    """``text`` with comment segments blanked out, newlines preserved."""
    return "".join(
        re.sub(r"[^\n]", " ", chunk) if is_comment else chunk
        for is_comment, chunk in split_comments(text)
    )


def _scannable(query: str) -> str:
    """Reduce ``query`` to the text in which a keyword means what it says.

    Order matters. Literals go first so a ``#`` or a keyword inside a string
    cannot be read as syntax; IRIs next for the same reason; then comments;
    then the two token classes whose punctuation defeats ``\\b``.
    """
    text = re.sub(r'"""(?:\\.|[^\\])*?"""', '""', query, flags=re.DOTALL)
    text = re.sub(r"'''(?:\\.|[^\\])*?'''", "''", text, flags=re.DOTALL)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", text)
    text = re.sub(r"<[^>\s]*>", "<>", text)
    text = re.sub(r"#[^\n]*", " ", text)
    # ?var and $var, and prefixed names such as ex:add or :add. Both classes can
    # legally contain an update keyword as their local part.
    text = re.sub(r"[?$][\w]+", " ?v ", text)
    text = re.sub(r"[\w.-]*:[\w.\-%]*", " pn ", text)
    return text


def validate_readonly(query: str) -> None:
    """Raise :class:`QueryError` unless ``query`` is a read-only SPARQL query.

    Passing means: no unresolved placeholders, no update operation, no federation,
    and a supported query form. It does not mean the query is correct, cheap, or
    scoped sensibly.
    """
    if not query or not query.strip():
        raise QueryError("Query is empty")

    # Comments are excluded: a template's header names the placeholders it uses,
    # and that mention is documentation, not an unresolved substitution.
    leftover = _PLACEHOLDER.findall(code_only(query))
    if leftover:
        raise QueryError(
            "Query still contains unresolved placeholders: "
            f"{', '.join(sorted(set(leftover)))}. Render it through "
            "linked_archi_query.render before executing."
        )

    scannable = _scannable(query)

    if _LEADING_WITH.match(scannable):
        raise QueryError(
            "Query opens with WITH, which begins a SPARQL Update prologue. "
            "This package executes read-only queries only."
        )

    found = _UPDATE_WORDS.search(scannable)
    if found:
        raise QueryError(
            f"SPARQL Update operation is not allowed (found {found.group(0).upper()}). "
            "This package executes read-only queries only."
        )

    if _SERVICE.search(scannable):
        raise QueryError(
            "Federated SERVICE calls are not allowed: they send this query, and "
            "possibly data from this graph, to an endpoint outside the profile's "
            "scope. Query the remote endpoint directly if you have authority to."
        )

    body = _PROLOGUE.sub("", scannable)
    match = _FORM.search(body)
    if not match:
        raise QueryError(
            "No query form found. Expected one of: "
            f"{', '.join(sorted(ALLOWED_FORMS))}."
        )
    form = match.group(1).upper()
    if form not in ALLOWED_FORMS:
        raise QueryError(
            f"{form} is not a read-only query form. Expected one of: "
            f"{', '.join(sorted(ALLOWED_FORMS))}."
        )


def query_form(query: str) -> str:
    """The query's form, validating it first.

    Adapters use this to decide how to read a result: ``ASK`` yields a boolean,
    ``CONSTRUCT`` and ``DESCRIBE`` yield triples, ``SELECT`` yields bindings.
    """
    validate_readonly(query)
    body = _PROLOGUE.sub("", _scannable(query))
    match = _FORM.search(body)
    assert match is not None  # validate_readonly guarantees it
    return match.group(1).upper()


def is_readonly(query: str) -> bool:
    """Whether ``query`` passes :func:`validate_readonly`, without raising."""
    try:
        validate_readonly(query)
    except QueryError:
        return False
    return True
