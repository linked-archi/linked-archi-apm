"""Which relationship may connect which element types, read from published SHACL.

A conversion emits instances. Nothing in it says that a Serving from a Business Actor to a
Value is not a thing the metamodel allows, so a query can traverse a path the metamodel
forbids, return nothing, and read as evidence of absence. Two published artifacts answer
that, and they answer it for different relationship forms:

``rdfs:domain`` / ``rdfs:range``
    Covers the core predicates - ``arch:source``, ``arch:target``, ``arch:inModel`` - which
    is what an Ontology-Based Query Check walks (Allemang & Sequeda, arXiv:2405.11706).
    Necessary and not sufficient: it says ``arch:source`` starts at a
    ``QualifiedRelationship`` and ends at a ``ModelConcept``, which is true of every
    relationship in the estate and rules out nothing anyone would ask.

SHACL node shapes
    The **unqualified** (direct triple) forms have no domain and no range anywhere in the
    ontologies. ``am:flowsTo``, ``bs:ownedBy`` and the other 73 predicates carrying an
    ``arch:unqualifiedForm`` mapping are constrained only as shapes. Reading them is what
    the paper does not do, and it is the form most estates query most.

Both reduce to the same table, which is what this module produces:

    ``(source class, predicate) -> {target classes}``

Two shapes of the same fact, so two ways in. ArchiMate publishes the unqualified form
directly, one ``sh:property`` per direct predicate under a source class. Every other
notation constrains only ``arch:source`` and ``arch:target`` on the relationship class, so
its direct form has to be DERIVED - follow ``arch:unqualifiedForm`` from the relationship
class to its predicate and reuse the qualified shape's classes. ``bs:Ownership`` allowing
``Element -> Group | User`` becomes the rule for ``bs:ownedBy``.

**A class with no shape means NO CONSTRAINT, never "the query is fine".** Coverage is
carried beside the table for exactly that reason: `linked-archi-profile`'s verify probe
reports which declared assets are missing, and a caller that ignores :attr:`Constraints.
notations` will report "no violations" over an estate whose shapes were never attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

#: Runs one SPARQL SELECT and returns its rows as ``{variable: lexical value}`` mappings.
#: A callable rather than an adapter, so the reader can be tested against a store directly
#: and used against an endpoint through the transport the query owner already has.
Runner = Callable[[str], Iterable[Mapping[str, Any]]]

SH = "http://www.w3.org/ns/shacl#"
#: The core namespace, for the two terms read straight from published metadata rather than
#: through a profile role: `arch:Metamodel` and `arch:formalRules`. Both are fixed by the
#: publishing convention - a manifest that called them something else would not be a
#: manifest - so binding them would add a knob with one correct setting.
CORE = "https://meta.linked.archi/core#"
RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"
RDF_REST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"

#: An `sh:or` list, walked to each alternative. Written out rather than using a property
#: path with `rdf:rest*` alone, because the alternatives are what carry `sh:class`.
_LIST = f"<{RDF_REST}>*/<{RDF_FIRST}>"


@dataclass(frozen=True)
class Legs:
    """The predicates a qualified relationship hangs its ends off.

    Taken from the profile - ``roles.rel_source`` and ``roles.rel_target`` - rather than
    matched by name. An earlier draft filtered with ``STRENDS(STR(?path), "source")``,
    which is the string-guessing this package exists to avoid: it binds the check to one
    vocabulary's spelling and quietly matches anything else ending in the same word.
    """

    source: str
    target: str


@dataclass(frozen=True)
class Constraints:
    """What the attached shapes permit, and how far they reach.

    ``allowed`` is empty when nothing is attached, which is indistinguishable from "the
    metamodel forbids everything" unless ``notations`` is read too. Hence both.
    """

    #: ``(source class IRI, predicate IRI) -> allowed target class IRIs``.
    allowed: Mapping[tuple[str, str], frozenset[str]] = field(default_factory=dict)
    #: ``relationship class IRI -> allowed (source, target) pairs``, the qualified form.
    qualified: Mapping[str, frozenset[tuple[str, str]]] = field(default_factory=dict)
    #: The predicates a qualified relationship hangs its ends off, as this table was read.
    #: Carried so a checker can find those patterns without being told twice.
    legs: Legs | None = None
    #: Namespaces some carried shape constrains. A predicate outside these is unchecked
    #: because nothing was published or nothing was attached - not because it is valid.
    covered: frozenset[str] = frozenset()
    #: Notation roots - ``https://meta.linked.archi/backstage/`` - whose attached manifest
    #: declares shape assets and every one of them is present. Only here may a checker
    #: conclude that something is forbidden.
    #:
    #: Everywhere else, a missing shape is indistinguishable from a prohibition. Found by
    #: accusation: against four ArchiMate shapes out of 73, a Business Actor traversing
    #: ``am:flowsTo`` was reported impossible because the one unqualified shape carried was
    #: BusinessRole's. That is "empty means none" reasoning inside the checker.
    complete: frozenset[str] = frozenset()
    #: Predicates whose constraint was derived through ``arch:unqualifiedForm`` rather
    #: than published directly. Worth reporting: the derivation assumes the direct form
    #: means the same as the qualified one, which is the ontology's claim, not a
    #: measurement of the data.
    derived: frozenset[str] = frozenset()

    def targets(self, source: str, predicate: str) -> frozenset[str] | None:
        """Allowed targets, or ``None`` when nothing constrains this pair.

        ``None`` and ``frozenset()`` are different answers and must not be conflated:
        the first means "unchecked", the second "nothing may sit here".
        """
        return self.allowed.get((source, predicate))

    def constrains(self, predicate: str) -> bool:
        return any(pair[1] == predicate for pair in self.allowed)

    def __bool__(self) -> bool:
        return bool(self.allowed or self.qualified)


class ConstraintError(RuntimeError):
    """The constraints cannot be read, so no verdict is available.

    Raised rather than returning an empty table, because the two are opposite answers and
    an empty table is indistinguishable from "this query breaks nothing".
    """


#: Roles this needs that a profile is not obliged to bind, and what each absence costs.
#:
#: ``rel_source`` and ``rel_target`` are deliberately absent from this list: the resolved
#: profile contract already requires them, so a ``ResolvedProfile`` cannot exist without
#: them and re-checking here would be a guard for a state that cannot occur.
OPTIONAL_ROLES: tuple[tuple[str, str], ...] = (
    (
        "unqualified_form",
        "how a relationship class maps to its direct predicate. Without it every notation "
        "except ArchiMate has no constraint on its direct triples at all, because only "
        "ArchiMate publishes that form - so the table would be silently empty where it "
        "matters most",
    ),
)


def constraints_from_profile(run: Runner, profile: Any) -> Constraints:
    """Read the constraints, refusing when the profile does not say how.

    The first draft did the opposite and was worse: an unbound ``unqualified_form`` skipped
    the derivation without comment, so a dataset whose shapes cover only the qualified form
    produced a table with nothing in it for direct triples - and a caller reading that table
    would have found no violations and reported none. A missing binding is a reason to
    refuse, not a reason to go quiet.
    """
    missing = [
        f"{role} - {why}" for role, why in OPTIONAL_ROLES if not profile.has_role(role)
    ]
    if missing:
        raise ConstraintError(
            f"cannot read relationship constraints: profile "
            f"{getattr(profile, 'name', '?')!r} does not bind "
            + "; ".join(missing)
            + ". Bind it, or do not ask for a path check: an unread constraint set finds "
            "no violations, which reads exactly like a query that has none."
        )

    bindings: dict[str, str] = {}
    for role in ("rel_source", "rel_target", *(name for name, _ in OPTIONAL_ROLES)):
        expanded = profile.expand_role(role)
        if len(expanded) != 1:
            raise ConstraintError(
                f"role {role!r} expands to {len(expanded)} IRIs; the path check reads one "
                "and would silently ignore the rest"
            )
        bindings[role] = expanded[0]

    return read_constraints(
        run,
        Legs(bindings["rel_source"], bindings["rel_target"]),
        bindings["unqualified_form"],
    )


def _namespace(iri: str) -> str:
    for separator in ("#", "/"):
        if separator in iri:
            return iri.rsplit(separator, 1)[0] + separator
    return iri


def read_unqualified(run: Runner, legs: Legs) -> dict[tuple[str, str], set[str]]:
    """Direct-triple constraints as published: one ``sh:property`` per predicate.

    Only ArchiMate publishes this form.

    ``legs`` is excluded rather than filtered out afterwards. A qualified shape also hangs
    its constraints off ``sh:property`` - one leg for ``arch:source``, one for
    ``arch:target`` - so without this the table gains entries like
    ``(bs:Ownership, arch:source) -> {arch:Element}``. True, and not a direct-triple rule:
    it would tell a checker that `arch:source` is a relationship between element types.
    """
    table: dict[tuple[str, str], set[str]] = {}
    rows = run(f"""
        SELECT ?src ?pred ?tgt WHERE {{
          ?shape <{SH}targetClass> ?src ; <{SH}property> ?property .
          ?property <{SH}path> ?pred .
          {{ ?property <{SH}or> ?alternatives .
             ?alternatives {_LIST} ?alternative .
             ?alternative <{SH}class> ?tgt }}
          UNION
          {{ ?property <{SH}class> ?tgt }}
          FILTER(?pred NOT IN (<{legs.source}>, <{legs.target}>))
        }}
    """)
    for row in rows:
        key = (str(row["src"]), str(row["pred"]))
        table.setdefault(key, set()).add(str(row["tgt"]))
    return table


def read_qualified(run: Runner, legs: Legs) -> dict[str, set[tuple[str, str]]]:
    """Qualified constraints: per relationship class, the source and target pairs.

    Two published spellings, both carried. ArchiMate nests ``sh:or`` over ``sh:and``, one
    conjunction per valid source, with the targets as an inner ``sh:or`` - 361 pairs for
    Aggregation alone, which matches the count its own source comment states. Other
    notations put ``arch:source`` and ``arch:target`` directly on the shape.
    """
    table: dict[str, set[tuple[str, str]]] = {}
    rows = run(f"""
        SELECT ?rel ?src ?tgt WHERE {{
          ?shape <{SH}targetClass> ?rel .
          {{
            ?shape <{SH}or> ?alternatives .
            ?alternatives {_LIST} ?alternative .
            ?alternative <{SH}and> ?conjunction .
            ?conjunction {_LIST} ?sourceLeg .
            ?sourceLeg <{SH}property> ?sourceProperty .
            ?sourceProperty <{SH}path> ?sourcePath ; <{SH}class> ?src .
            ?conjunction {_LIST} ?targetLeg .
            ?targetLeg <{SH}property> ?targetProperty .
            ?targetProperty <{SH}path> ?targetPath .
            {{ ?targetProperty <{SH}or> ?targets .
               ?targets {_LIST} ?targetAlternative .
               ?targetAlternative <{SH}class> ?tgt }}
            UNION
            {{ ?targetProperty <{SH}class> ?tgt }}
          }}
          UNION
          {{
            ?shape <{SH}property> ?sourceProperty , ?targetProperty .
            ?sourceProperty <{SH}path> ?sourcePath ; <{SH}class> ?src .
            ?targetProperty <{SH}path> ?targetPath .
            {{ ?targetProperty <{SH}or> ?targets .
               ?targets {_LIST} ?targetAlternative .
               ?targetAlternative <{SH}class> ?tgt }}
            UNION
            {{ ?targetProperty <{SH}class> ?tgt }}
          }}
          FILTER(?sourcePath = <{legs.source}>)
          FILTER(?targetPath = <{legs.target}>)
        }}
    """)
    for row in rows:
        table.setdefault(str(row["rel"]), set()).add((str(row["src"]), str(row["tgt"])))
    return table


def notation_root(iri: str) -> str:
    """``.../backstage/onto#Component`` -> ``.../backstage/``.

    The level a metamodel, its ontology, its taxonomy and its shapes all sit under, which
    is what lets a predicate be matched to the manifest that declares its shapes.
    """
    namespace = _namespace(iri)
    trimmed = namespace.rstrip("#")
    return trimmed.rsplit("/", 1)[0] + "/" if "/" in trimmed else namespace


def read_complete_notations(run: Runner) -> frozenset[str]:
    """Notation roots whose declared shape assets are all attached.

    The manifest is the only statement of what a complete shape set is: ``arch:formalRules``
    names each published namespace, so a namespace with no shape present means the set is
    partial and nothing may be called forbidden.

    A notation with no attached manifest is not complete - not because it is wrong, but
    because nothing says what it should contain.
    """
    declared: dict[str, set[str]] = {}
    for row in run(
        f"SELECT ?m ?asset WHERE {{ ?m a <{CORE}Metamodel> ; <{CORE}formalRules> ?asset }}"
    ):
        declared.setdefault(notation_root(str(row["m"])), set()).add(str(row["asset"]))
    if not declared:
        return frozenset()

    present = {
        str(row["shape"]) for row in run(
            f"SELECT ?shape WHERE {{ ?shape a <{SH}NodeShape> }}"
        )
    }
    complete = set()
    for root, assets in declared.items():
        if all(any(shape.startswith(asset) for shape in present) for asset in assets):
            complete.add(root)
    return frozenset(complete)


def read_unqualified_forms(run: Runner, predicate: str) -> dict[str, str]:
    """``relationship class -> direct predicate``, from the attached ontology.

    Read from the store rather than from a bundled table, because the mapping belongs to
    the metamodel and moves with it. The profile binds the predicate as
    ``roles.unqualified_form``.
    """
    rows = run(f"SELECT ?cls ?pred WHERE {{ ?cls <{predicate}> ?pred }}")
    forms: dict[str, str] = {}
    for row in rows:
        cls, direct = str(row["cls"]), str(row["pred"])
        # Only class -> predicate. The ontologies also state the pair on the qualified
        # PROPERTY, which is the same mapping from the other side and collides here.
        local = cls.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if local[:1].isupper():
            forms[cls] = direct
    return forms


def read_constraints(
    run: Runner, legs: Legs, unqualified_form: str | None = None
) -> Constraints:
    """The whole table, published and derived, with its coverage.

    Derivation runs second and never overwrites a published constraint: where ArchiMate
    states the direct form itself, that is the answer, and the qualified shape is a
    cross-check rather than a source. Everywhere else the derivation is the only way the
    direct form is constrained at all.
    """
    allowed = {key: set(value) for key, value in read_unqualified(run, legs).items()}
    published = set(allowed)
    qualified = read_qualified(run, legs)

    derived: set[str] = set()
    forms = read_unqualified_forms(run, unqualified_form) if unqualified_form else {}
    for relationship, pairs in qualified.items():
        direct = forms.get(relationship)
        if direct is None:
            continue
        for source, target in pairs:
            key = (source, direct)
            if key in published:
                continue
            allowed.setdefault(key, set()).add(target)
            derived.add(direct)

    covered = {_namespace(predicate) for _, predicate in allowed}
    covered |= {_namespace(relationship) for relationship in qualified}
    return Constraints(
        allowed={key: frozenset(value) for key, value in allowed.items()},
        qualified={key: frozenset(value) for key, value in qualified.items()},
        legs=legs,
        covered=frozenset(covered),
        complete=read_complete_notations(run),
        derived=frozenset(derived),
    )
