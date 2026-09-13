"""Turn a catalogued template plus a profile into executable SPARQL.

Three placeholder families, each solving a problem that one of the predecessor
packages got wrong:

``{{PREFIXES}}``
    The profile's namespace map. Templates carry no ``PREFIX`` lines of their own, so a
    namespace can never be stale in one template and current in another. Per-template
    prefixes are how a whole library ends up querying a namespace that does not exist
    while every query still parses.

``{{ROLE:x}}`` ``{{ROLES:x}}`` ``{{PATH:x}}``
    A semantic role resolved through the profile. ``ROLE`` yields the primary IRI,
    ``ROLES`` a space-separated list for a ``VALUES`` block, ``PATH`` an
    alternative path. Templates never name a vocabulary term directly.

``{{GRAPH_OPEN:role}}`` ``{{GRAPH_CLOSE}}``
    A named-graph wrapper the profile decides the shape of. A template with no ``GRAPH``
    clause returns nothing against converter TriG, and one with a hardcoded clause returns
    nothing against flattened Turtle - both verified, not assumed. Because the profile
    decides, one template serves both, plus a curated store with literal graph IRIs.

Plus ``{{PARAM}}`` for typed user input. Parameters are type-checked and escaped rather than
substituted: a raw ``str.replace`` on user input is an injection hole, and it also forces the
caller to supply their own angle brackets, which is the kind of detail that silently produces
a query matching nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .catalog import Catalog, TemplateEntry, Verdict, load_catalog
from .contract import ResolvedProfile
from .validate import QueryError, split_comments, validate_readonly

def graph_var(role: str) -> str:
    """The variable a graph scope binds, derived from the role.

    One variable per role, not one per template. A template that scopes to two
    roles - an element's facts in the semantic graph, its provenance in the
    provenance graph - would otherwise bind both with ``?g`` and require a single
    graph IRI to end in two different suffixes at once. That is unsatisfiable, so
    the query runs and returns nothing: precisely the failure mode this package
    exists to remove, reintroduced by the mechanism meant to prevent it.

    Templates refer to the variable through ``{{GRAPH_VAR:role}}`` rather than
    spelling it, so the naming stays an implementation detail.
    """
    return f"?g_{role}"


#: The scope most templates use, and the variable it binds.
GRAPH_VAR = graph_var("semantic")


def _base_role(role: str) -> str:
    """``semantic2`` -> ``semantic``. See :func:`graph_open` for why."""
    return re.sub(r"\d+$", "", role) or role

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Z_]+)(?:\s*:\s*([A-Za-z_][\w-]*))?\s*\}\}")
_DIRECTIVE = frozenset({
    "PREFIXES", "ROLE", "ROLES", "PATH", "GRAPH_OPEN", "GRAPH_CLOSE", "GRAPH_VAR",
    "MEMBERSHIP",
})
_BAD_IRI_CHARS = '<>"{}|\\^` '


def _substitute_outside_comments(text: str, replacer) -> str:
    """Expand placeholders in code, leaving the template's prose header intact.

    A template header names the placeholders it uses. Substituting there would
    rewrite the documentation into whatever the current profile binds, turning an
    explanation of the mechanism into an example of its output.
    """
    return "".join(
        chunk if is_comment else _PLACEHOLDER.sub(replacer, chunk)
        for is_comment, chunk in split_comments(text)
    )


class RenderError(ValueError):
    """A template could not be rendered as written."""


class UnsupportedTemplate(RenderError):
    """The profile does not support this template.

    Distinct from :class:`RenderError` so a caller can tell "you asked for
    something this dataset cannot answer" from "the template or its parameters are
    wrong". The first is a routing decision; the second is a bug.
    """

    def __init__(self, entry: TemplateEntry, verdict: Verdict, profile: ResolvedProfile) -> None:
        self.entry = entry
        self.verdict = verdict
        self.profile = profile
        reasons = "\n".join(f"  - {r}" for r in verdict.unmet)
        hint = ""
        if entry.alternatives:
            hint = (
                "\nTry instead: "
                + ", ".join(entry.alternatives)
                + " (same question, different evidence)."
            )
        super().__init__(
            f"Template {entry.name!r} cannot run against profile "
            f"{profile.name!r}:\n{reasons}{hint}\n"
            "This is a refusal, not an empty result: running it anyway would "
            "return no rows and read as 'nothing exists'."
        )


# ---------------------------------------------------------------------------
# Parameter coercion
# ---------------------------------------------------------------------------


def _iri(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise RenderError(f"Parameter {name}: IRI must be a string, got {type(value).__name__}")
    text = value.strip()
    # Accept a bracketed IRI so a user who pastes `<http://...>` is not punished
    # for it. The predecessor required the brackets; requiring their absence would
    # be the same trap inverted.
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https", "urn"}:
        raise RenderError(
            f"Parameter {name}: {value!r} is not an absolute http, https or urn IRI. "
            "Resolve a label to an IRI first (see the resolution templates)."
        )
    if any(char in text for char in _BAD_IRI_CHARS):
        raise RenderError(
            f"Parameter {name}: {value!r} contains a character not allowed in an IRI"
        )
    return f"<{text}>"


def _string(value: object, name: str, spec: Mapping[str, Any] | None = None) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RenderError(f"Parameter {name}: expected a string literal")
    choices = (spec or {}).get("choices")
    if choices and str(value) not in choices:
        # Refused rather than interpolated. An enum compared inside the query would
        # match nothing for a misspelling, and zero rows reads as "no differences" -
        # the exact failure this package exists to remove.
        raise RenderError(
            f"Parameter {name}: {value!r} is not one of "
            + ", ".join(repr(choice) for choice in choices)
        )
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _integer(value: object, name: str, spec: Mapping[str, Any]) -> str:
    if isinstance(value, bool):
        raise RenderError(f"Parameter {name}: a boolean is not an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RenderError(f"Parameter {name}: {value!r} is not an integer") from exc
    low, high = spec.get("min"), spec.get("max")
    if low is not None and number < int(low):
        raise RenderError(f"Parameter {name}: {number} is below the minimum {low}")
    if high is not None and number > int(high):
        raise RenderError(
            f"Parameter {name}: {number} exceeds the maximum {high}. An unbounded "
            "result is how an exploratory query becomes an outage."
        )
    return str(number)


def _iri_list(value: object, name: str) -> str:
    if isinstance(value, str):
        # A comma- or whitespace-separated string, because that is what a CLI
        # user types and what an agent tends to emit.
        items: Sequence[Any] = [v for v in re.split(r"[,\s]+", value) if v]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise RenderError(f"Parameter {name}: expected a list of IRIs")
    if not items:
        raise RenderError(f"Parameter {name}: needs at least one IRI")
    return " ".join(_iri(item, name) for item in items)


def _iri_path(value: object, name: str, spec: Mapping[str, Any]) -> str:
    """An alternation of IRIs for a SPARQL property path: ``<a>|<b>``.

    Each element is validated as an IRI, so nothing but IRIs and ``|`` can reach
    the path position. Arbitrary path syntax is deliberately not accepted: a
    caller who could inject ``!<x>*`` could turn a bounded traversal into a walk
    of the whole graph.

    ``max_terms`` caps the alternation, because a path over a hundred predicates
    is the wildcard path it was meant to replace.
    """
    rendered = _iri_list(value, name)
    terms = rendered.split()
    ceiling = int(spec.get("max_terms", 12))
    if len(terms) > ceiling:
        raise RenderError(
            f"Parameter {name}: {len(terms)} predicates exceeds the maximum "
            f"{ceiling} for a property path. Narrow the predicate set - a path over "
            "everything is the unbounded traversal this parameter type exists to "
            "prevent."
        )
    return "|".join(terms)


def _within_profile_ceiling(
    requested: int,
    profile: ResolvedProfile,
    entry: TemplateEntry,
    asked_for: bool,
    caveats: list[str],
) -> int:
    """Apply ``limits.max_row_limit`` to a row limit, refusing or clamping.

    Two ceilings bound a row limit and they are set by different people: the template's
    ``max`` is a property of the query's shape, and the profile's ``max_row_limit`` is
    what this dataset or endpoint will stand. The lower one has to win, and until this
    existed the profile's was never consulted at all - a profile declaring
    ``max_row_limit: 20`` rendered ``LIMIT 1500`` without complaint, while five
    documents said it would be refused.

    The two origins are treated differently on purpose:

    ``asked_for``
        Refused. Someone naming a number that the profile forbids has made a decision
        this package should not quietly overrule, and the message names the profile so
        the fix is obvious - raise the ceiling deliberately, or ask for less.

    a template default
        Clamped, with a caveat. The caller did nothing wrong, and refusing would make
        the template unusable against a profile with a tight ceiling for reasons the
        caller cannot see. Clamping silently is the other trap, so the caveat rides
        along on the result.
    """
    # `row_limit(requested)` is `min(requested, ceiling)`, so when it comes back lower
    # than what was asked for it IS the ceiling. Going through the profile rather than
    # reading `limits` here keeps one implementation of the cap; that method existed and
    # had no live caller, which is why the ceiling went unenforced for so long.
    ceiling = profile.row_limit(requested)
    if ceiling >= requested:
        return requested
    if asked_for:
        raise RenderError(
            f"Parameter LIMIT: {requested} exceeds max_row_limit {ceiling} in profile "
            f"{profile.name!r}. Ask for at most {ceiling}, or raise "
            "'limits.max_row_limit' in the profile deliberately - it is there because "
            "an unbounded result against a shared endpoint is how an exploratory query "
            "becomes an outage."
        )
    caveats.append(
        f"{entry.name} defaults to LIMIT {requested}, above max_row_limit {ceiling} in "
        f"profile {profile.name!r}, so it ran with LIMIT {ceiling}. Rows are capped "
        "lower than the template intends; a full result may need a profile with a "
        "higher ceiling."
    )
    return ceiling


def coerce(name: str, value: Any, spec: Mapping[str, Any]) -> str:
    kind = spec["type"]
    if kind == "iri":
        return _iri(value, name)
    if kind == "iri_list":
        return _iri_list(value, name)
    if kind == "iri_path":
        return _iri_path(value, name, spec)
    if kind == "string":
        return _string(value, name, spec)
    if kind == "integer":
        return _integer(value, name, spec)
    raise RenderError(f"Parameter {name}: unsupported type {kind!r}")


# ---------------------------------------------------------------------------
# Graph scoping
# ---------------------------------------------------------------------------


def membership_pattern(profile: ResolvedProfile, subject: str) -> str:
    """Bind ``?model`` for ``?<subject>``, however this dataset expresses membership.

    Written once here because templates kept re-inventing it. `core/provenance` finds the
    model by co-location; a field session hand-wrote a bounded folder path for the same
    question. Both are correct for *some* datasets, and neither belongs in a template: which
    one applies is a fact about the data, so it is a profile fact.

    Two modes, both binding the same variables so a template does not care which it got:

    ``same-graph-colocation``
        A concept in a model's semantic graph belongs to that model. Holds for every
        converter, so it is the default. Relies on the enclosing ``GRAPH`` scope, which is
        why this only ever appears inside one.

    ``bounded-folder-tree``
        Walk ``part_of`` up through folders to the model. Expressed as capped alternation
        rather than a ``+`` path: SPARQL 1.1 has no ``{1,n}`` range, and an unbounded ``+``
        turns one wrong hop into a whole-dataset scan.

    ``direct-predicate``
        One hop along ``part_of_model``. The converters' real 1.3 contract, and better
        than both others where it exists: it needs neither named graphs nor a complete
        folder chain.

        Note what this mode deliberately does NOT emit: ``?model a <model_class>``. In
        the layout that carries this edge the model resource lives in ``graph/model``,
        not in the semantic graph, so a class test would be evaluated in the wrong
        graph and match nothing. This pattern is injected inside whatever ``GRAPH``
        scope the template opened, so it cannot reach across graphs - and it does not
        need to, because the edge already identifies the model. The other two modes
        keep the class test because for them it is the only thing that identifies it.
    """
    mode, depth = profile.model_membership()
    model_class = profile.role("model_class")
    if mode == "direct-predicate":
        return f"?{subject} <{profile.role('part_of_model')}> ?model ."
    if mode == "bounded-folder-tree":
        step = f"<{profile.role('part_of')}>"
        alternatives = "|".join("/".join([step] * hops) for hops in range(1, depth + 1))
        return (
            f"?{subject} ({alternatives}) ?model .\n"
            f"    ?model a <{model_class}> ."
        )
    return f"?model a <{model_class}> ."


def graph_open(profile: ResolvedProfile, role: str) -> str:
    """The opening of a group scoped to the named-graph ``role``.

    Under ``per-model-triple`` the model IRIs are not knowable in advance, so the
    scope is a suffix test on the graph IRI. Under ``explicit`` the profile holds
    literal IRIs and a ``VALUES`` block is both clearer and faster. Under
    ``single`` there are no graphs and the wrapper becomes a plain group, which is
    what lets one template serve TriG and flattened Turtle alike.

    The role ``any`` binds its variable without constraining it, for the orientation
    templates whose whole job is to report which graphs exist. Scoping those would
    hide the thing they are meant to reveal.

    A trailing digit opens an INDEPENDENT scope on the same role: ``semantic2`` is
    scoped like ``semantic`` but binds ``?g_semantic2``. Needed when one query looks
    up two things that share a role but live in different graphs - two elements from
    two models, each with its own semantic graph. Sharing one variable would require
    both to sit in the same graph, and quietly return nothing for the second.
    """
    if not profile.graphs.named_graphs:
        return "{"

    variable = graph_var(role)
    role = _base_role(role)

    if role == "any":
        return f"GRAPH {variable} {{"

    if not profile.graphs.has_role(role):
        available = ", ".join(profile.graphs.role_names()) or "none"
        raise RenderError(
            f"ResolvedProfile {profile.name!r} has no graph role {role!r} (has: {available})"
        )

    binding = profile.graphs.roles[role]

    if profile.graphs.layout == "explicit":
        iris = binding if isinstance(binding, list) else [binding]
        values = " ".join(f"<{iri}>" for iri in iris)
        return f"GRAPH {variable} {{\n    VALUES {variable} {{ {values} }}"

    return (
        f"GRAPH {variable} {{\n    "
        f"FILTER({profile.graphs.suffix_test(role, variable)})"
    )


def graph_close(profile: ResolvedProfile) -> str:
    return "}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


#: The trailing row cap of a query, if it has one. Applied to text with comments
#: already stripped, and anchored so that only the OUTERMOST modifier can match:
#: ``LIMIT`` inside a subquery is followed by a closing brace, and a cap that does not
#: bound the result set must not be mistaken for one that does. ``OFFSET`` may follow
#: ``LIMIT`` in either order, so both orders are accepted.
_TRAILING_LIMIT = re.compile(
    r"\bLIMIT\s+(\d+)\b(?:\s+OFFSET\s+\d+\b)?\s*$", re.IGNORECASE
)


def trailing_row_limit(query: str) -> int | None:
    """The row cap this query actually applies to its result, or ``None`` for none.

    Only for hand-written queries. A catalogued template's cap is the resolved value
    of its ``LIMIT`` parameter, which is known exactly and needs no parsing.

    ``None`` means "no cap was applied", which is a statement, not an absence of one:
    a query with no ``LIMIT`` returned everything it matched, so its result cannot be
    truncated at a limit. Reporting that as unknown would make the completeness field
    unusable for exactly the queries where it is easiest to be certain.
    """
    text = "".join(
        "" if is_comment else chunk for is_comment, chunk in split_comments(query)
    ).rstrip().rstrip(";").rstrip()
    match = _TRAILING_LIMIT.search(text)
    return int(match.group(1)) if match else None


@dataclass
class Rendered:
    """A rendered query and what it took to produce it."""

    query: str
    template: str
    profile: str
    profile_version: int
    warnings: tuple[str, ...] = ()
    #: The row cap this query applies, or ``None`` when it applies none.
    #:
    #: Carried HERE, rather than recomputed by whoever builds the result envelope,
    #: because rendering is the only step that knows it. A caller that re-derives it
    #: gets a different answer - measured: `truncated` was computed against the
    #: profile's `default_row_limit` while the query carried the template's own
    #: default, so a complete 200-row result was flagged incomplete and a result
    #: genuinely capped at 25 was flagged complete. One producer, one value.
    row_limit: int | None = None

    def __str__(self) -> str:
        return self.query


def render(
    template: str,
    profile: ResolvedProfile,
    params: Mapping[str, Any] | None = None,
    catalog: Catalog | None = None,
    strict: bool = True,
) -> Rendered:
    """Render ``template`` against ``profile``.

    ``strict=False`` renders a template the profile does not support, for
    inspection only. It still validates read-only, and the caller is expected not
    to execute it - the point of looking is usually to explain the refusal.
    """
    catalog = catalog or load_catalog()
    entry = catalog.get(template)

    verdict = entry.check(profile)
    if not verdict.ok and strict:
        raise UnsupportedTemplate(entry, verdict, profile)

    supplied = dict(params or {})
    unknown = set(supplied) - set(entry.parameters)
    if unknown:
        expected = ", ".join(sorted(entry.parameters)) or "none"
        raise RenderError(
            f"Template {entry.name!r} got unknown parameter(s): "
            f"{', '.join(sorted(unknown))}. Expected: {expected}"
        )

    values: dict[str, str] = {}
    row_limit: int | None = None
    ceiling_caveats: list[str] = []
    for name, spec in entry.parameters.items():
        if name in supplied and supplied[name] is not None:
            raw = supplied[name]
            asked_for = True
        elif "default" in spec:
            raw = spec["default"]
            asked_for = False
        elif name == "LIMIT":
            raw = profile.row_limit()
            asked_for = False
        else:
            raise RenderError(
                f"Template {entry.name!r} requires parameter {name!r} "
                f"({spec.get('description', spec['type'])})"
            )
        values[name] = coerce(name, raw, spec)
        if name == "LIMIT":
            # The template's own `max` is applied by `coerce`, ABOVE this, and that order
            # is deliberate: when a request exceeds both ceilings the lower one is the
            # binding one, and the template's is lower for every bundled profile. Naming
            # the profile there would send the reader to edit the wrong file.
            row_limit = _within_profile_ceiling(
                int(values[name]), profile, entry, asked_for, ceiling_caveats
            )
            values[name] = str(row_limit)

    text = entry.text()
    errors: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        directive, argument = match.group(1), match.group(2)
        try:
            if directive == "PREFIXES":
                return profile.prefix_block()
            if directive == "GRAPH_CLOSE":
                return graph_close(profile)
            if directive == "GRAPH_OPEN":
                if not argument:
                    raise RenderError("{{GRAPH_OPEN}} needs a graph role, e.g. :semantic")
                return graph_open(profile, argument)
            if directive == "GRAPH_VAR":
                if not argument:
                    raise RenderError("{{GRAPH_VAR}} needs a graph role, e.g. :semantic")
                return graph_var(argument)
            if directive == "MEMBERSHIP":
                if not argument:
                    raise RenderError(
                        "{{MEMBERSHIP}} needs the subject variable name, e.g. :element"
                    )
                return membership_pattern(profile, argument)
            if directive in {"ROLE", "ROLES", "PATH"}:
                if not argument:
                    raise RenderError(f"{{{{{directive}}}}} needs a role name")
                iris = profile.expand_role(argument)
                if directive == "ROLE":
                    return f"<{iris[0]}>"
                if directive == "ROLES":
                    return " ".join(f"<{iri}>" for iri in iris)
                return "|".join(f"<{iri}>" for iri in iris)
            if directive in values:
                return values[directive]
            if directive in entry.parameters:
                raise RenderError(f"Parameter {directive!r} was not resolved")
            raise RenderError(
                f"Unknown placeholder {{{{{directive}}}}} in {entry.file}. "
                f"Directives: {', '.join(sorted(_DIRECTIVE))}; "
                f"parameters: {', '.join(sorted(entry.parameters)) or 'none'}"
            )
        except Exception as exc:  # noqa: BLE001 - every reason is collected and reported
            errors.append(str(exc))
            return match.group(0)

    query = _substitute_outside_comments(text, substitute)

    if errors:
        joined = "\n".join(f"  - {e}" for e in dict.fromkeys(errors))
        raise RenderError(f"Could not render {entry.name!r}:\n{joined}")

    try:
        validate_readonly(query)
    except QueryError as exc:
        raise RenderError(
            f"Rendered {entry.name!r} did not pass read-only validation: {exc}"
        ) from exc

    # A template-declared caveat comes FIRST, before the profile's. It is a statement
    # about what the rows mean, which a reader needs before deciding whether coverage
    # caveats even matter. A clamped row limit comes last: it is a statement about how
    # many rows there are, which only matters once the rows mean something.
    warnings = (
        ((entry.caveat,) if entry.caveat else ())
        + tuple(verdict.warnings)
        + tuple(ceiling_caveats)
    )

    return Rendered(
        query=query,
        template=entry.name,
        profile=profile.name,
        profile_version=profile.profile_version,
        warnings=warnings,
        row_limit=row_limit,
    )


def render_literal(query: str, profile: ResolvedProfile) -> Rendered:
    """Render an ad-hoc query, expanding directives but taking no parameters.

    For the case the templates do not cover. Directives still resolve through the
    profile, so a hand-written query gets the same namespace and graph-scoping
    treatment - and the same read-only check.
    """
    errors: list[str] = []
    warnings: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        directive, argument = match.group(1), match.group(2)
        try:
            if directive == "PREFIXES":
                return profile.prefix_block()
            if directive == "GRAPH_CLOSE":
                return graph_close(profile)
            if directive == "GRAPH_OPEN":
                return graph_open(profile, argument or "semantic")
            if directive == "GRAPH_VAR":
                return graph_var(argument or "semantic")
            if directive == "MEMBERSHIP":
                # A catalogued template declaring requires.membership is refused for
                # this. An ad-hoc query is not refused - the author may know something
                # the profile does not - but it must not be answered silently either.
                gap = profile.membership_gap()
                if gap:
                    warnings.append(gap)
                return membership_pattern(profile, argument or "element")
            if directive in {"ROLE", "ROLES", "PATH"}:
                iris = profile.expand_role(argument or "")
                if directive == "ROLE":
                    return f"<{iris[0]}>"
                if directive == "ROLES":
                    return " ".join(f"<{i}>" for i in iris)
                return "|".join(f"<{i}>" for i in iris)
            raise RenderError(
                f"Unknown placeholder {{{{{directive}}}}}. An ad-hoc query takes "
                "directives but no parameters; substitute values yourself."
            )
        except Exception as exc:  # noqa: BLE001 - every reason is collected and reported
            errors.append(str(exc))
            return match.group(0)

    rendered = _substitute_outside_comments(query, substitute)
    if errors:
        joined = "\n".join(f"  - {e}" for e in dict.fromkeys(errors))
        raise RenderError(f"Could not render the supplied query:\n{joined}")

    try:
        validate_readonly(rendered)
    except QueryError as exc:
        raise RenderError(str(exc)) from exc

    return Rendered(
        query=rendered,
        template="<literal>",
        profile=profile.name,
        profile_version=profile.profile_version,
        warnings=tuple(dict.fromkeys(warnings)),
        # Read from the query the author wrote, because there is no parameter to read it
        # from. The profile's `default_row_limit` is NOT a substitute: it describes what
        # a template would be given, not what this query does, and using it here
        # reported a complete 1282-row result as truncated and a result capped at 5 as
        # complete.
        row_limit=trailing_row_limit(rendered),
    )
