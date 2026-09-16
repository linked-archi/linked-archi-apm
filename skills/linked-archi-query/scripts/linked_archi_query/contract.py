"""Local view of the resolved-profile subprocess contract.

Profile inheritance, YAML loading, and CURIE expansion belong exclusively to
linked-archi-profile. This module only validates and presents its normalized
schema_version=1 snapshot to query code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping
from urllib.parse import urlsplit


_REQUIRED_ROLES = (
    "label",
    "concept_class",
    "element_class",
    "relationship_class",
    "rel_source",
    "rel_target",
    "rel_type",
)
_URN = re.compile(r"^urn:[A-Za-z0-9][A-Za-z0-9-]{0,31}:.+$", re.IGNORECASE)
_BAD_IRI_CHARACTERS = frozenset('<>"{}|^`\\')
_BAD_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _is_absolute_iri(value: str) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(
            character.isspace()
            or ord(character) < 32
            or ord(character) == 127
            or character in _BAD_IRI_CHARACTERS
            for character in value
        )
        or _BAD_PERCENT_ESCAPE.search(value)
        or value.count("#") > 1
    ):
        return False
    if _URN.fullmatch(value):
        return "[" not in value and "]" not in value
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(hostname)
        and not any(
            bracket in component
            for component in (parsed.path, parsed.query, parsed.fragment)
            for bracket in "[]"
        )
    )


class ContractError(ValueError):
    """A companion emitted an unsupported or malformed contract."""


#: Reserved role binding meaning "the default graph". Must match the profile owner's
#: constant of the same name; it travels in the profile snapshot as a plain string, so
#: the two skills agree by using the same reserved word rather than by sharing code.
DEFAULT_GRAPH = "default"


@dataclass(frozen=True)
class GraphLayout:
    layout: str
    named_graphs: bool
    roles: Mapping[str, Any] = field(default_factory=dict)
    #: Roles whose suffix also matches graphs below it, from the profile snapshot's
    #: ``graphs.descendants``. Absent in a snapshot from an older profile owner, and
    #: an empty tuple is the pre-existing behaviour, so tolerating its absence is safe.
    descendants: tuple[str, ...] = ()

    def has_role(self, role: str) -> bool:
        return self.roles.get(role) is not None

    def role_names(self) -> list[str]:
        return sorted(name for name, value in self.roles.items() if value is not None)

    def matches_descendants(self, role: str) -> bool:
        return role in self.descendants

    def is_default_graph(self, role: str) -> bool:
        """Whether this role is read unscoped, because its triples have no graph.

        Mirrors the profile owner's method of the same name, and must agree with it for
        the same reason :meth:`suffix_test` must: the two skills share no code, so the
        behaviour is the contract. Published schema - an ontology, a taxonomy, a shape
        set - is a Turtle document, and a Turtle document loads into the default graph.
        """
        return self.roles.get(role) == DEFAULT_GRAPH

    def suffix_test(self, role: str, variable: str) -> str:
        """The filter that scopes ``variable`` to this role under ``per-model-triple``.

        Must agree with the profile owner's probe of the same name. The two skills do
        not share code, so this expression is the contract between them and it is
        published in the profile owner's ``references/machine-contract.md``. If they
        disagree, ``verify`` passes and every scoped query still returns nothing -
        which is the failure this package exists to prevent.
        """
        if self.is_default_graph(role):
            raise ContractError(
                f"graph role {role!r} is bound to the default graph, which has no IRI to "
                "test. Check is_default_graph() before asking for a suffix test"
            )
        binding = self.roles[role]
        suffixes = binding if isinstance(binding, list) else [binding]
        tests = []
        for suffix in suffixes:
            tests.append(f'STRENDS(STR({variable}), "{suffix}")')
            if self.matches_descendants(role):
                # Trailing slash keeps this a path test: "graph/semantic/" must not
                # match "graph/semantic-draft".
                tests.append(f'CONTAINS(STR({variable}), "{suffix}/")')
        return " || ".join(tests)


class ResolvedProfile:
    """Normalized profile snapshot received from ``la-profile`` over JSON."""

    REQUIRED_FIELDS = {
        "schema_version", "name", "version", "source", "description", "base_iri",
        "namespaces", "roles", "graphs", "capabilities", "notations",
        "taxonomies", "limits",
    }

    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        if not isinstance(snapshot, Mapping):
            raise ContractError("linked-archi-profile returned a malformed snapshot: expected an object")
        missing = sorted(self.REQUIRED_FIELDS.difference(snapshot))
        if missing:
            raise ContractError(
                "linked-archi-profile returned a malformed snapshot: missing "
                + ", ".join(missing)
            )
        if (
            not isinstance(snapshot["schema_version"], int)
            or isinstance(snapshot["schema_version"], bool)
            or snapshot["schema_version"] != 1
        ):
            raise ContractError(
                "linked-archi-profile returned unsupported schema_version "
                f"{snapshot['schema_version']!r}; expected 1"
            )
        if not isinstance(snapshot["name"], str) or not snapshot["name"].strip():
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid name")
        if (
            not isinstance(snapshot["version"], int)
            or isinstance(snapshot["version"], bool)
            or snapshot["version"] < 1
        ):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid version")
        if snapshot["source"] is not None and (
            not isinstance(snapshot["source"], str) or not snapshot["source"].strip()
        ):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid source")
        for field_name in ("description", "base_iri"):
            if not isinstance(snapshot[field_name], str):
                raise ContractError(
                    f"linked-archi-profile returned a malformed snapshot: invalid {field_name}"
                )

        mappings: dict[str, Mapping[str, Any]] = {}
        for field_name in ("namespaces", "roles", "graphs", "capabilities", "notations", "limits"):
            value = snapshot[field_name]
            if not isinstance(value, Mapping):
                raise ContractError(
                    f"linked-archi-profile returned a malformed snapshot: invalid {field_name}"
                )
            mappings[field_name] = value
        if not mappings["roles"]:
            raise ContractError("linked-archi-profile returned an incomplete snapshot: roles are empty")

        namespaces = mappings["namespaces"]
        if any(
            not isinstance(key, str)
            or not key.strip()
            or key != key.strip()
            or not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            for key, value in namespaces.items()
        ):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid namespaces")

        roles = mappings["roles"]
        if any(
            not isinstance(key, str)
            or not key
            or (
                value is not None
                and (
                    not isinstance(value, list)
                    or not value
                    or any(
                        not isinstance(item, str) or not item.strip()
                        for item in value
                    )
                )
            )
            for key, value in roles.items()
        ):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid roles")
        missing_roles = [role for role in _REQUIRED_ROLES if not roles.get(role)]
        if missing_roles:
            raise ContractError(
                "linked-archi-profile returned an incomplete snapshot: missing roles "
                + ", ".join(missing_roles)
            )
        if any(
            not _is_absolute_iri(iri)
            for value in roles.values()
            if value is not None
            for iri in value
        ):
            raise ContractError(
                "linked-archi-profile returned a malformed snapshot: roles must contain absolute IRIs"
            )

        graphs = mappings["graphs"]
        missing_graph_fields = {"layout", "named_graphs", "roles"}.difference(graphs)
        if missing_graph_fields:
            raise ContractError(
                "linked-archi-profile returned a malformed snapshot: graphs missing "
                + ", ".join(sorted(missing_graph_fields))
            )
        if graphs["layout"] not in {"per-model-triple", "explicit", "single"}:
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid graph layout")
        if not isinstance(graphs["named_graphs"], bool):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid named_graphs")
        graph_roles = graphs["roles"]
        if not isinstance(graph_roles, Mapping) or any(
            not isinstance(key, str)
            or not key
            or (
                value is not None
                and not (
                    isinstance(value, str)
                    and bool(value.strip())
                    or (
                        isinstance(value, list)
                        and value
                        and all(
                            isinstance(item, str) and bool(item.strip())
                            for item in value
                        )
                    )
                )
            )
            for key, value in (graph_roles.items() if isinstance(graph_roles, Mapping) else ())
        ):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid graph roles")
        if graphs["layout"] == "single" and graphs["named_graphs"]:
            raise ContractError(
                "linked-archi-profile returned a contradictory snapshot: single layout has named graphs"
            )
        if graphs["layout"] == "explicit" and any(
            not _is_absolute_iri(iri)
            for value in graph_roles.values()
            if value is not None
            for iri in (value if isinstance(value, list) else [value])
        ):
            raise ContractError(
                "linked-archi-profile returned a malformed snapshot: explicit graph roles must be absolute IRIs"
            )

        capabilities = mappings["capabilities"]
        if any(not isinstance(key, str) or not key for key in capabilities):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid capabilities")
        for key, value in capabilities.items():
            valid = (
                isinstance(value, bool)
                or value == "partial"
                or (
                    key == "label_language"
                    and isinstance(value, str)
                    and bool(value.strip())
                )
            )
            if not valid:
                raise ContractError(
                    "linked-archi-profile returned a malformed snapshot: "
                    f"invalid capability {key!r}"
                )

        notations = mappings["notations"]
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, Mapping)
            for key, value in notations.items()
        ):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid notations")
        # `present` is the only key inside a notation spec this side interprets, so it is
        # the only one worth validating. A typo in a value here would otherwise read as
        # `False` and refuse every template for that notation.
        for slug, spec in notations.items():
            declared = (spec or {}).get("present")
            if declared is not None and not isinstance(declared, bool) and declared != "partial":
                raise ContractError(
                    "linked-archi-profile returned a malformed snapshot: notation "
                    f"{slug!r} declares present={declared!r}; expected true, false or 'partial'"
                )

        taxonomies = snapshot["taxonomies"]
        if not isinstance(taxonomies, list) or any(
            not isinstance(item, Mapping) for item in taxonomies
        ):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid taxonomies")

        limits = mappings["limits"]
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for key, value in limits.items()
        ):
            raise ContractError("linked-archi-profile returned a malformed snapshot: invalid limits")

        self.name = snapshot["name"]
        self.profile_version = snapshot["version"]
        self.source = snapshot["source"]
        self.description = snapshot["description"]
        self.base_iri = snapshot["base_iri"]
        self.namespaces = dict(namespaces)
        self.roles = dict(roles)
        self.capabilities = dict(capabilities)
        self.notations = dict(notations)
        self.taxonomies = list(taxonomies)
        self.limits = dict(limits)
        # Optional and tolerant: a profile resolved by an older owner has no navigation
        # section, and the default it would have declared is the safe one anyway.
        navigation = snapshot.get("navigation") or {}
        if not isinstance(navigation, dict):
            raise ContractError("linked-archi-profile returned a malformed snapshot: navigation")
        self.navigation = dict(navigation)
        # What "which profile is this, exactly" is keyed on. The profile owner computes it
        # over the fields that change what an answer MEANS and publishes it here, so the
        # verification marker this skill reads is keyed on the same value the profile
        # owner wrote it with. Recomputing it here would be a second implementation of
        # one digest, and the two disagreeing would silence the caveat permanently.
        #
        # Falls back to the declared version for a snapshot from an older profile owner.
        # That is the weaker key this replaced, so the fallback degrades to the old
        # behaviour rather than to no behaviour.
        fingerprint = snapshot.get("fingerprint")
        if fingerprint is not None and (
            not isinstance(fingerprint, str) or not fingerprint.strip()
        ):
            raise ContractError(
                "linked-archi-profile returned a malformed snapshot: fingerprint"
            )
        self.fingerprint = fingerprint or f"v{self.profile_version}"

        # Optional and tolerant, like `navigation` above: a snapshot from an older
        # profile owner has no `descendants`, and the default it would have declared
        # is the pre-existing suffix-only behaviour.
        descendants = graphs.get("descendants") or []
        if not isinstance(descendants, (list, tuple)) or any(
            not isinstance(name, str) or not name.strip() for name in descendants
        ):
            raise ContractError(
                "linked-archi-profile returned a malformed snapshot: graphs.descendants"
            )
        unbound = sorted(n for n in descendants if graph_roles.get(n) is None)
        if unbound:
            # It could never match anything, so a query scoped to it would return
            # nothing while the profile claimed the opposite.
            raise ContractError(
                "linked-archi-profile returned a contradictory snapshot: "
                f"graphs.descendants names unbound role(s) {', '.join(unbound)}"
            )
        self.graphs = GraphLayout(
            layout=graphs["layout"],
            named_graphs=graphs["named_graphs"],
            roles=dict(graph_roles),
            descendants=tuple(descendants),
        )

    def has_role(self, name: str) -> bool:
        return self.roles.get(name) is not None

    def expand_role(self, name: str) -> list[str]:
        if name not in self.roles:
            raise ContractError(f"Resolved profile {self.name!r} declares no role {name!r}")
        value = self.roles[name]
        if value is None:
            raise ContractError(
                f"Resolved profile {self.name!r} binds role {name!r} to null"
            )
        if not isinstance(value, list) or not value:
            raise ContractError(f"Resolved role {name!r} is not a non-empty IRI list")
        return [str(item) for item in value]

    def role(self, name: str) -> str:
        return self.expand_role(name)[0]

    def capability(self, name: str) -> Any:
        return self.capabilities.get(name, False)

    def prefix_block(self) -> str:
        return "\n".join(
            f"PREFIX {prefix}: <{iri}>" for prefix, iri in sorted(self.namespaces.items())
        )

    def notation_for_metamodel(self, metamodel_iri: str) -> str | None:
        for slug, spec in self.notations.items():
            if str((spec or {}).get("metamodel", "")) == metamodel_iri:
                return slug
        return None

    def notation_for_namespace(self, namespace_iri: str) -> str | None:
        """The notation slug whose vocabulary is ``namespace_iri``, or ``None``.

        Keyed on the namespace IRI rather than on the notation slug, for two reasons that
        both bite. A slug is not stable: ArchiMate's is ``model`` because the converter's
        ``--path-model`` defaults to that and is configurable, so the catalogue's
        ``archimate`` and a profile's ``model`` name the same notation. And a prefix is
        not stable either - the converters emit both ``archvis:`` and ``arch-vis:`` for one
        namespace - so the IRI is the only identity here that cannot drift.

        Versioned by construction, which is a feature: a profile describing an ArchiMate 4
        dataset binds ``am4``, so a template written against ``am`` (3.x) does not match
        and is refused rather than quietly returning nothing.
        """
        for slug, spec in self.notations.items():
            prefix = str((spec or {}).get("namespace", ""))
            if prefix and self.namespaces.get(prefix) == namespace_iri:
                return slug
        return None

    def notation_present(self, slug: str) -> bool | str | None:
        """Whether the dataset holds a model in ``slug``: ``True``, ``False``, ``partial``
        or ``None`` for unstated.

        A claim about the DATA, like a capability, not a claim about the vocabulary. The
        notation block otherwise says only "this profile can speak BPMN"; a dataset with no
        BPMN model in it answers every BPMN template with no rows, which reads as "there
        are no gateways" rather than "you asked the wrong dataset".

        Unstated is not absent. Nothing may be refused on the strength of an unknown - the
        same rule ``_verify_capabilities`` follows when a probe cannot answer - so a profile
        that never mentions presence behaves exactly as it did before this existed, and
        ``la-profile verify`` is what turns the unknown into a claim.
        """
        spec = self.notations.get(slug) or {}
        declared = spec.get("present")
        if declared is None or isinstance(declared, bool):
            return declared
        return str(declared)

    def row_limit(self, requested: int | None = None) -> int:
        default = int(self.limits.get("default_row_limit", 200))
        ceiling = int(self.limits.get("max_row_limit", 5000))
        return min(int(requested) if requested else default, ceiling)

    def model_membership(self) -> tuple[str, int]:
        """How this dataset expresses "belongs to that model": (mode, max_depth).

        Defaults to co-location, which holds for every converter, rather than the folder
        path, which is emitted for some notations and truncated for others.
        """
        membership = self.navigation.get("model_membership") or {}
        mode = str(membership.get("mode") or "same-graph-colocation")
        depth = membership.get("max_depth", 3)
        try:
            depth = int(depth)
        except (TypeError, ValueError):
            depth = 3
        return mode, max(1, min(depth, 6))

    def membership_gap(self) -> str | None:
        """Why "belongs to this model" cannot be expressed here, or ``None``.

        One implementation, two consumers: the catalogue turns it into a refusal for a
        template declaring ``requires.membership``, and an ad-hoc query turns it into a
        caveat. Duplicating the judgement would let the two disagree.

        Co-location is a statement about named graphs. Without them the pattern reduces
        to "?model is a model", which is true of every model in the dataset, so a
        membership query silently joins all of them and names the wrong one - measured
        against the flattened fixture, not theorised. A folder walk needs no graphs and
        is unaffected.
        """
        mode, _ = self.model_membership()
        if mode == "direct-predicate" and not self.has_role("part_of_model"):
            # The profile owner refuses this combination at load, so reaching here means
            # a snapshot was assembled by something else. Refuse rather than render a
            # pattern with no edge, which would match every model in the dataset.
            return (
                f"profile {self.name!r} places membership on a direct predicate "
                "('navigation.model_membership.mode: direct-predicate') but does not "
                "bind 'part_of_model', so 'belongs to this model' cannot be expressed: "
                "the pattern would match every model and report the wrong one. Bind "
                "roles.part_of_model, or choose another membership mode."
            )
        if mode == "same-graph-colocation" and not self.graphs.named_graphs:
            return (
                f"profile {self.name!r} places membership by graph co-location "
                "('navigation.model_membership.mode') but has no named graphs, so "
                "'belongs to this model' cannot be expressed: the pattern would match "
                "every model in the dataset and report the wrong one. Set "
                "'mode: bounded-folder-tree' if the folder chain is complete here, or "
                "query a dataset that kept its named graphs."
            )
        return None
