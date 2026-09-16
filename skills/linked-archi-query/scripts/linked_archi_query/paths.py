"""Does this query traverse a path the metamodel permits?

Asked by ``lint`` and nowhere else. A wrong path returns nothing rather than failing, and
an empty result reads as absence - so the useful moment to ask is before running it, not
on every execution.

Three rules over the table :mod:`constraints` builds, all of them needing the class
hierarchy to avoid confident nonsense:

``source``   the query types the subject and the predicate is constrained, but nothing
             permits that class as a source.
``target``   the query types the object, and that class is outside every allowed target
             for the predicate - a violation whatever the subject turns out to be.
``pair``     both ends typed, so the exact ``(source, predicate) -> target`` is checked.

**A declared type only yields a verdict when it is the constrained class or below it.**
Converter output types an element as ``arch:Element`` as well as its notation class, so a
query saying ``?s a arch:Element`` cannot be judged against ``am:BusinessRole``
constraints: the instance may well be one. Judging anyway would produce false positives on
this package's own fixtures, which is worse than having no check.

**Unparseable is reported, never passed.** rdflib parses 35 of the 39 catalogued templates;
the three using SPARQL 1.2 triple terms it cannot, and neither can it be assumed present.
Both cases answer "not checked" with the reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .constraints import Constraints, Runner, notation_root

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


@dataclass(frozen=True)
class Violation:
    """One triple pattern the metamodel does not permit."""

    rule: str
    subject: str
    predicate: str
    obj: str
    message: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.message}"


@dataclass(frozen=True)
class Report:
    """What the check concluded, including what it could not conclude.

    ``checked`` counts the patterns that produced a verdict. Zero of it with no violations
    is not a clean bill: it means nothing in the query was checkable, which is the state a
    caller must be able to tell apart from "checked and sound".
    """

    violations: tuple[Violation, ...] = ()
    checked: int = 0
    #: Why a pattern was skipped, once per distinct reason, for a caller to relay.
    unchecked: tuple[str, ...] = ()
    #: What a verdict here rests on that could not be verified. Present whenever anything
    #: was judged, because judging depends on the attached shape documents being whole and
    #: only their namespaces being represented could be checked.
    caveats: tuple[str, ...] = ()
    #: Set when no verdict was possible at all - unparseable, or no parser installed.
    refused: str | None = None

    @property
    def sound(self) -> bool:
        """No violations AND something was actually checked."""
        return self.refused is None and not self.violations and self.checked > 0

    def summary(self) -> str:
        if self.refused:
            return f"not checked: {self.refused}"
        if self.violations:
            return f"{len(self.violations)} impossible path(s) in {self.checked} checked"
        if not self.checked:
            return "not checked: no pattern in this query could be judged"
        return f"{self.checked} pattern(s) checked, all permitted"


def extract_patterns(query: str) -> list[tuple[Any, Any, Any]]:
    """Triple patterns from a query's WHERE, including OPTIONAL, UNION and MINUS.

    Raises ``ImportError`` when no parser is available and ``ValueError`` when the query
    cannot be parsed, so the caller reports "not checked" rather than "nothing found".
    """
    from rdflib.plugins.sparql.algebra import translateQuery
    from rdflib.plugins.sparql.parser import parseQuery

    try:
        algebra = translateQuery(parseQuery(query)).algebra
    except Exception as exc:  # rdflib raises a wide range for a bad parse
        raise ValueError(str(exc).replace("\n", " ")[:200]) from exc

    found: list[tuple[Any, Any, Any]] = []
    _walk(algebra, found)
    return found


def _walk(node: Any, into: list[tuple[Any, Any, Any]]) -> None:
    if node is None:
        return
    if getattr(node, "name", None) in ("BGP", "TriplesBlock"):
        for triple in node.get("triples") or ():
            if isinstance(triple, tuple) and len(triple) == 3:
                into.append(triple)
        return
    if not hasattr(node, "keys"):
        return
    for key in node.keys():
        if key == "_vars":
            continue
        value = node[key]
        if hasattr(value, "name") or hasattr(value, "keys"):
            _walk(value, into)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if hasattr(item, "name") or hasattr(item, "keys"):
                    _walk(item, into)


def read_subclasses(run: Runner) -> dict[str, frozenset[str]]:
    """``class -> itself and every class below it``, from the attached vocabulary.

    Needed to keep the check honest rather than to widen it: without the hierarchy a
    supertype in the query looks like a violation of every subtype's constraint.
    """
    below: dict[str, set[str]] = {}
    for row in run(
        f"SELECT ?sub ?super WHERE {{ ?sub <{RDFS_SUBCLASS}>+ ?super }}"
    ):
        below.setdefault(str(row["super"]), set()).add(str(row["sub"]))
    return {
        parent: frozenset({parent, *children}) for parent, children in below.items()
    }


def _iri(term: Any) -> str | None:
    """The IRI of a term, or ``None`` for a variable, literal or blank node."""
    if type(term).__name__ == "URIRef":
        return str(term)
    return None


def _declared_types(patterns: Sequence[tuple[Any, Any, Any]]) -> dict[str, set[str]]:
    """``?variable -> classes the query itself asserts for it``."""
    types: dict[str, set[str]] = {}
    for subject, predicate, obj in patterns:
        if _iri(predicate) != RDF_TYPE:
            continue
        cls = _iri(obj)
        if cls is not None:
            types.setdefault(str(subject), set()).add(cls)
    return types


def check_query(
    query: str, constraints: Constraints, subclasses: Mapping[str, frozenset[str]]
) -> Report:
    """Judge every checkable triple pattern against ``constraints``."""
    if not constraints:
        return Report(refused="no relationship constraints are attached")
    try:
        patterns = extract_patterns(query)
    except ImportError:
        return Report(refused="rdflib is not installed, so the query cannot be parsed")
    except ValueError as exc:
        return Report(refused=f"the query could not be parsed ({exc})")

    declared = _declared_types(patterns)
    sources = {source for source, _ in constraints.allowed}
    violations: list[Violation] = []
    unchecked: dict[str, None] = {}
    checked = 0

    for subject, predicate, obj in patterns:
        term = _iri(predicate)
        if term is None or term == RDF_TYPE or not constraints.constrains(term):
            continue
        subject_types = declared.get(str(subject), set())
        object_types = declared.get(str(obj), set())
        if not subject_types and not object_types:
            unchecked[
                f"{term.rsplit('#', 1)[-1]}: neither end is typed in the query, so nothing "
                "identifies which constraint applies"
            ] = None
            continue

        # Nothing may be called forbidden where the shape set is partial: a missing shape
        # would read as a prohibition. The manifest is what says whether it is partial.
        if notation_root(term) not in constraints.represented:
            unchecked[
                f"{term.rsplit('#', 1)[-1]}: the shapes attached for this notation are not "
                "known to be complete, so a missing rule cannot be told from a prohibition"
            ] = None
            continue

        judged, note = _judge(
            term, subject_types, object_types, constraints, subclasses, sources
        )
        if note is not None:
            unchecked[note] = None
        if judged is None:
            continue
        checked += 1
        if judged is not True:
            violations.append(
                Violation("path", str(subject), term, str(obj), judged)
            )

    qualified_violations, qualified_checked, qualified_notes = _check_qualified(
        patterns, declared, constraints, subclasses
    )
    violations += qualified_violations
    checked += qualified_checked
    for note in qualified_notes:
        unchecked[note] = None

    return Report(
        violations=tuple(violations),
        checked=checked,
        unchecked=tuple(unchecked),
        caveats=(PROVISIONAL,) if checked else (),
    )


#: Attached once to any report that judged something. The check can verify that every shape
#: namespace a manifest declares has shapes attached; it cannot verify that those documents
#: are whole, because nothing published states how many shapes they hold. So a verdict is
#: as good as the attachment, and saying so is cheaper than being wrong quietly.
PROVISIONAL = (
    "verdicts assume each attached shape document is whole. Only the presence of every "
    "declared shape namespace could be verified - one shape of 28 would pass that test - so "
    "a partial attachment can still produce a wrong verdict"
)


def _check_qualified(
    patterns: Sequence[tuple[Any, Any, Any]],
    declared: Mapping[str, set[str]],
    constraints: Constraints,
    subclasses: Mapping[str, frozenset[str]],
) -> tuple[list[Violation], int, list[str]]:
    """Judge the qualified form: ``?rel a R ; arch:source ?s ; arch:target ?t``.

    This is the shape the catalogued templates use, and it was invisible to the direct-
    predicate rules - the legs are deliberately excluded from that table, and nothing else
    looked at them. So the check ran over the whole catalogue and judged nothing, which
    looked like 39 clean templates and was in fact no coverage at all.
    """
    legs = constraints.legs
    if legs is None or not constraints.qualified:
        return [], 0, []

    ends: dict[str, dict[str, Any]] = {}
    for subject, predicate, obj in patterns:
        term = _iri(predicate)
        if term == legs.source:
            ends.setdefault(str(subject), {})["source"] = obj
        elif term == legs.target:
            ends.setdefault(str(subject), {})["target"] = obj

    violations: list[Violation] = []
    notes: list[str] = []
    checked = 0
    for variable, sides in ends.items():
        relationship_types = [
            cls for cls in declared.get(variable, ()) if cls in constraints.qualified
        ]
        if not relationship_types or "source" not in sides or "target" not in sides:
            continue
        for relationship in relationship_types:
            if notation_root(relationship) not in constraints.represented:
                notes.append(
                    f"{_short(relationship)}: the shapes attached for this notation are "
                    "not known to be complete, so a missing rule cannot be told from a "
                    "prohibition"
                )
                continue
            pairs = constraints.qualified[relationship]
            source_types = declared.get(str(sides["source"]), set())
            target_types = declared.get(str(sides["target"]), set())
            if not source_types or not target_types:
                notes.append(
                    f"{_short(relationship)}: its ends are not both typed in the query, so "
                    "which pair applies cannot be identified"
                )
                continue
            # Each end is judged on its own, exactly as the direct-predicate rules do. A
            # combined "either end looks ambiguous" test excused the whole pattern the
            # moment one end matched exactly, because a class is trivially below itself:
            # `arch:Element` matching the permitted source hid a forbidden target.
            applicable = [
                (permitted_source, permitted_target)
                for permitted_source, permitted_target in pairs
                if any(is_below(source, permitted_source, subclasses)
                       for source in source_types)
            ]
            if not applicable:
                if _above_any(source_types, {s for s, _ in pairs}, subclasses):
                    notes.append(
                        f"{_short(relationship)}: its source is typed above the permitted "
                        "classes, so an instance of a permitted subclass would be judged "
                        "wrongly"
                    )
                    continue
                checked += 1
                violations.append(Violation(
                    "qualified", str(sides["source"]), relationship,
                    str(sides["target"]),
                    f"{_short(relationship)} may not start at {_names(source_types)}; "
                    f"permitted: {_names({s for s, _ in pairs})}",
                ))
                continue

            permitted_targets = {target for _, target in applicable}
            if any(
                is_below(target, permitted, subclasses)
                for target in target_types
                for permitted in permitted_targets
            ):
                checked += 1
                continue
            if _above_any(target_types, permitted_targets, subclasses):
                notes.append(
                    f"{_short(relationship)}: its target is typed above the permitted "
                    "classes, so an instance of a permitted subclass would be judged wrongly"
                )
                continue
            checked += 1
            violations.append(Violation(
                "qualified", str(sides["source"]), relationship, str(sides["target"]),
                f"{_short(relationship)} may not go from {_names(source_types)} to "
                f"{_names(target_types)}; permitted targets: {_names(permitted_targets)}",
            ))
    return violations, checked, notes


def _short(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _names(classes: Iterable[str], limit: int = 6) -> str:
    ordered = sorted(_short(cls) for cls in classes)
    head = ", ".join(ordered[:limit])
    return head + (f" and {len(ordered) - limit} more" if len(ordered) > limit else "")


def is_below(
    declared: str, constrained: str, subclasses: Mapping[str, frozenset[str]]
) -> bool:
    """``declared`` is ``constrained`` or a class beneath it, so it inherits the rule."""
    return declared == constrained or declared in subclasses.get(constrained, frozenset())


def _above_any(
    declared: Iterable[str],
    constrained: Iterable[str],
    subclasses: Mapping[str, frozenset[str]],
) -> bool:
    """Whether a declared class is a STRICT ancestor of something constrained.

    Strict matters: a class is trivially below itself, so a non-strict test excuses an
    exact match as ambiguous and hides the violation on the other end.
    """
    constrained = set(constrained)
    return any(
        candidate != cls and candidate in subclasses.get(cls, frozenset())
        for cls in declared
        for candidate in constrained
    )


def _judge(
    predicate: str,
    subject_types: Iterable[str],
    object_types: Iterable[str],
    constraints: Constraints,
    subclasses: Mapping[str, frozenset[str]],
    sources: set[str],
) -> tuple[bool | str | None, str | None]:
    """``(verdict, note)``: True permitted, a message when forbidden, None unchecked.

    Usability is decided **per predicate**, which an earlier version got wrong: it asked
    whether the declared class appeared anywhere in the table, and `arch:Element` does -
    as the source of `bs:ownedBy` through derivation. So a query typing its subject
    `arch:Element` and traversing `am:flowsTo` was judged against BusinessRole's rule and
    reported as impossible. A false positive on this package's own fixture, and precisely
    the failure the class hierarchy is here to prevent.

    Three relations to a constrained class, and only one of them yields a verdict:

    * **at or below it** - the rule applies, judge against it;
    * **above it** - unchecked, because the instance may be the subclass that is permitted;
    * **unrelated** - forbidden, since no rule for this predicate could ever admit it.
    """
    # Sources the shapes constrain FOR THIS PREDICATE, not for anything.
    constrained_sources = {
        source for (source, term) in constraints.allowed if term == predicate
    }
    subject_types = set(subject_types)
    object_types = set(object_types)

    applicable = {
        source for source in constrained_sources
        for declared in subject_types
        if is_below(declared, source, subclasses)
    }
    broader = {
        declared for declared in subject_types
        for source in constrained_sources
        if is_below(source, declared, subclasses) and declared != source
    }

    permitted: set[str] = set()
    for source in applicable:
        permitted |= constraints.targets(source, predicate) or set()

    if subject_types and not applicable:
        if broader:
            return None, (
                f"{_short(predicate)}: subject typed only as {_names(broader)}, which is "
                f"above {_names(constrained_sources)} - an instance of a permitted subclass "
                "would be judged wrongly, so this is left unjudged"
            )
        return (
            f"{_names(subject_types)} may not be the source of {_short(predicate)}; "
            f"permitted: {_names(constrained_sources)}"
        ), None

    if not object_types:
        # Subject alone is judgeable only in the sense that SOME target is permitted,
        # which every constrained source has. Nothing to conclude without the other end.
        return None, (
            f"{_short(predicate)}: object end is not typed, so only the subject could be "
            "checked and the subject is permitted"
        ) if applicable else (None, None)[1]

    reachable = permitted or {
        target
        for (source, term), targets in constraints.allowed.items()
        if term == predicate
        for target in targets
    }
    for declared in object_types:
        if any(is_below(declared, allowed, subclasses) for allowed in reachable):
            return True, None
        if any(is_below(allowed, declared, subclasses) for allowed in reachable):
            return None, (
                f"{_short(predicate)}: object typed only as {_names(object_types)}, which "
                "is above the permitted targets, so this is left unjudged"
            )
    return (
        f"{_short(predicate)} may not point at {_names(object_types)}"
        + (f"; permitted: {_names(reachable)}" if reachable else "")
    ), None
