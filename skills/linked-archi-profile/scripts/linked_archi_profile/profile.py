"""Graph profiles: the one place a vocabulary decision is recorded.

A profile answers three questions about a dataset that a template cannot answer
for itself:

* **What is this called here?** ``roles`` maps a semantic role such as ``label``
  onto the term this dataset uses (``skos:prefLabel``).
* **Where does it live?** ``graphs`` describes the named-graph layout, so a
  template can be scoped to the semantic graph without knowing model IRIs.
* **Is it actually present?** ``capabilities`` records what the dataset contains
  rather than what the vocabulary permits, so a template needing something
  absent is refused with a reason.

The third is the one that earns the abstraction. Both packages this one replaces
could produce a query that ran happily and returned nothing, because the term it
used was spelled differently or the relationship form it assumed was not emitted.
A capability declared false converts that into a refusal naming an alternative.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - environment problem
    raise ModuleNotFoundError(
        "Profiles are YAML. Install PyYAML:  pip install PyYAML"
    ) from exc

#: Profiles are committed assets owned by this skill.
PROFILE_DIR = Path(__file__).resolve().parents[2] / "assets" / "profiles"
#: The profile assumed when nobody names one, and the vocabulary lens a shape
#: observation is read through. Defined here rather than in the CLI because the
#: observation code needs it and must not import the CLI.
DEFAULT_PROFILE = "linked-archi-default"

#: Graph layouts a profile may declare. See ``graphs.layout`` in the profiles.
LAYOUTS = frozenset({"per-model-triple", "explicit", "single"})

#: Capability values. ``partial`` means "present for some models, absent for
#: others" - true of the views graph, which exists only where a source had
#: diagrams. A template requiring a partial capability is allowed to run but
#: carries a warning, because a thin result may reflect coverage, not absence.
TRISTATE = frozenset({True, False, "partial"})

#: Roles every profile must bind. Deliberately short: these are the terms without
#: which no template in the catalogue can do anything at all.
REQUIRED_ROLES = (
    "label",
    "concept_class",
    "element_class",
    "relationship_class",
    "rel_source",
    "rel_target",
    "rel_type",
)

_CURIE = re.compile(r"^([A-Za-z][\w.-]*):([^\s/][^\s]*)$")
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


class ProfileError(ValueError):
    """A profile is malformed, or asks for something it has not declared."""


def _merge(base: Any, overlay: Any) -> Any:
    """Merge ``overlay`` onto ``base`` for profile inheritance.

    Mappings merge key by key so a child profile can rebind one role without
    restating the rest. Everything else - scalars, and crucially lists - replaces
    outright: a role bound to a fallback chain is one decision, and appending to
    it from a child would silently change which term ``{{ROLE:x}}`` resolves to.
    """
    if isinstance(base, Mapping) and isinstance(overlay, Mapping):
        merged = dict(base)
        for key, value in overlay.items():
            merged[key] = _merge(base[key], value) if key in base else value
        return merged
    return overlay


def _read(path: Path, _seen: tuple[Path, ...] = ()) -> dict:
    """Read a profile document, resolving ``extends`` depth-first."""
    resolved = path.resolve()
    if resolved in _seen:
        chain = " -> ".join(p.name for p in (*_seen, resolved))
        raise ProfileError(f"Circular profile inheritance: {chain}")
    if not resolved.is_file():
        raise ProfileError(f"Profile not found: {path}")

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ProfileError(f"{path.name} must contain a YAML mapping")

    parent_ref = raw.pop("extends", None)
    if parent_ref is None:
        return dict(raw)

    # Sibling first, then the bundled profiles. The second lookup is what lets a
    # derived or project-local profile live anywhere on disk and still inherit from
    # `linked-archi-default.yaml`, which is the common case: a team keeps its
    # profile beside its graph, not inside this package.
    #
    # The bundled lookup takes the reference AS GIVEN before falling back to its
    # basename, so a subdirectory survives: `examples/curated-store.yaml` resolves to
    # the file that is actually there. Basename-only resolution silently failed for
    # every bundled profile not at the top level, which made `verify --emit-fix`
    # against one of them emit a child that could not load.
    candidates: list[Path] = []
    for candidate in (
        (resolved.parent / str(parent_ref)).resolve(),
        (PROFILE_DIR / str(parent_ref)).resolve(),
        (PROFILE_DIR / Path(str(parent_ref)).name).resolve(),
    ):
        if candidate not in candidates:
            candidates.append(candidate)

    for parent_path in candidates:
        if parent_path.is_file():
            return _merge(_read(parent_path, (*_seen, resolved)), dict(raw))

    tried = ", ".join(str(c) for c in candidates)
    message = f"{path.name} extends {parent_ref!r}, which was not found. Tried: {tried}"
    # A bundled profile in a subdirectory is the likely intent behind a bare basename,
    # so name the path that would work rather than leaving the reader to go looking.
    deeper = sorted(
        p.relative_to(PROFILE_DIR.resolve()).as_posix()
        for p in PROFILE_DIR.resolve().rglob(Path(str(parent_ref)).name)
        if p.is_file()
    )
    if deeper:
        message += (
            f". A bundled profile of that name exists at {', '.join(deeper)} - "
            "reference it with its directory."
        )
    raise ProfileError(message)


def load_profile(reference: str | Path) -> "Profile":
    """Load a profile by path, by bare name, or by name relative to ``profiles/``.

    ``load_profile("linked-archi-default")`` and
    ``load_profile("profiles/linked-archi-default.yaml")`` are equivalent, so a
    skill can accept whichever a user types.
    """
    candidate = Path(reference)
    tried: list[Path] = []
    options = [candidate]
    if candidate.suffix not in {".yaml", ".yml"}:
        # APPEND, never `with_suffix`. A profile named for a version has a dot in it,
        # and `with_suffix` would read that dot as a file extension and replace it:
        # `linked-archi-1.3` became `linked-archi-1.yaml`, which does not exist, so a
        # bundled profile was unreachable by its own name while the error message
        # helpfully listed it as available.
        options.append(candidate.with_name(candidate.name + ".yaml"))
    options += [PROFILE_DIR / opt.name for opt in list(options)]
    options += [PROFILE_DIR / "examples" / opt.name for opt in options[:2]]

    for option in options:
        tried.append(option)
        if option.is_file():
            return Profile(_read(option), source=option)

    listing = ", ".join(sorted(p.stem for p in PROFILE_DIR.glob("*.yaml")))
    raise ProfileError(
        f"No profile at any of: {', '.join(str(t) for t in tried)}. "
        f"Bundled profiles: {listing}"
    )


#: Snapshot fields that decide what a query MEANS, and therefore what a verification
#: covers. Anything listed here invalidates a recorded verification when it changes.
#:
#: Deliberately excluded:
#:
#: ``version``      the field this replaces. A hand-maintained integer cannot be trusted
#:                  to change when the profile's meaning does - it is edited by whoever
#:                  remembers to, and adding a required graph role without bumping it is
#:                  exactly the mistake that motivated this.
#: ``source``       an absolute path. Including it would make a marker useless on another
#:                  machine, and moving a checkout would silently invalidate every one.
#: ``description``  prose. Rewording an explanation must not invalidate a verification.
#: ``limits``       row caps and timeouts. They bound a result's size, not its meaning,
#:                  and no verification probe reads them.
FINGERPRINT_FIELDS = (
    "schema_version", "base_iri", "namespaces", "roles", "graphs", "capabilities",
    "notations", "taxonomies", "navigation",
)


def _fingerprint(snapshot: Mapping[str, Any]) -> str:
    """A stable digest of everything about a profile that changes what an answer means.

    This is what the verification marker is keyed on, replacing the declared ``version``.
    The point is that it cannot be forgotten: bind a role differently, require another
    graph, flip a capability, and the fingerprint moves on its own, so a recorded
    verification stops vouching for a profile that no longer says the same thing.

    Carried IN the snapshot rather than recomputed by each consumer. The query owner keys
    its "not verified against this dataset" caveat on the same value the profile owner
    wrote the marker with, and two independent implementations of one digest would be a
    silent way for those to disagree - which would resurrect the caveat that never fires.
    """
    material = {
        field_name: snapshot[field_name]
        for field_name in FINGERPRINT_FIELDS
        if field_name in snapshot
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"),
                           default=str, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class GraphLayout:
    """How named graphs are arranged, and how to scope a query to one role."""

    layout: str
    named_graphs: bool
    roles: Mapping[str, Any] = field(default_factory=dict)
    #: Graph roles whose absence from a dataset is an error rather than a warning.
    #:
    #: The distinction is not decoration. A missing ``semantic`` graph empties every
    #: scoped query in the catalogue, so a run that reports it as a warning and exits
    #: 0 hands back "no rows" as though it were an answer - which is the failure this
    #: package exists to prevent. A missing ``views`` graph is the opposite case: a
    #: Backstage or LeanIX conversion never emits one, so refusing that dataset would
    #: be refusing a correct dataset.
    #:
    #: Defaults to ``("semantic",)`` where a semantic role is declared. Set
    #: ``graphs.required: []`` to opt out, or name more roles to opt them in - a
    #: profile written for a graph layout that keeps model resources in their own
    #: graph should require that role too.
    required: tuple[str, ...] = ()
    #: Graph roles whose suffix also matches graphs BELOW it, so that
    #: ``graph/semantic`` scopes to ``graph/semantic/{repo}/{path}`` as well.
    #:
    #: Opt-in per role, and deliberately not the default. Matching descendants
    #: everywhere would be the smaller change and the wrong one: a profile describing
    #: the older unpartitioned layout would silently start matching a partitioned
    #: dataset's semantic graphs and look like it fitted, while its other roles still
    #: read the wrong graphs - `arch:Model` moved to `graph/model` in the same
    #: generation that introduced the partitions. Half-fitting is exactly how a wrong
    #: profile returns a confident wrong answer, so opting in is a claim the profile
    #: makes about the dataset and `verify` can check.
    #:
    #: Only meaningful under ``per-model-triple``. Under ``explicit`` the roles hold
    #: literal graph IRIs and there is nothing to descend; under ``single`` there are
    #: no graphs at all. Both are rejected at load.
    descendants: tuple[str, ...] = ()

    def has_role(self, role: str) -> bool:
        return self.roles.get(role) is not None

    def role_names(self) -> list[str]:
        return sorted(k for k, v in self.roles.items() if v is not None)

    def is_required(self, role: str) -> bool:
        return role in self.required

    def matches_descendants(self, role: str) -> bool:
        return role in self.descendants

    def suffix_test(self, role: str, variable: str) -> str:
        """The SPARQL filter expression that scopes ``variable`` to this role.

        Lives on the layout so the profile owner's verification probe and the query
        owner's renderer cannot disagree about what a role matches. They are separate
        skills and neither imports the other, so the *expression* is the contract;
        this is its one definition, and ``references/machine-contract.md`` publishes
        the same rule for any other consumer.
        """
        binding = self.roles[role]
        suffixes = binding if isinstance(binding, list) else [binding]
        tests = []
        for suffix in suffixes:
            tests.append(f'STRENDS(STR({variable}), "{suffix}")')
            if self.matches_descendants(role):
                # The trailing slash is what keeps this a path test rather than a
                # prefix test: "graph/semantic/" cannot match "graph/semantic-draft".
                tests.append(f'CONTAINS(STR({variable}), "{suffix}/")')
        return " || ".join(tests)


class Profile:
    """A resolved graph profile.

    Construct through :func:`load_profile` rather than directly; the constructor
    validates but does not resolve inheritance.
    """

    def __init__(self, document: Mapping[str, Any], source: Path | None = None) -> None:
        where = source.name if source else "profile"
        if not isinstance(document, Mapping):
            raise ProfileError(f"{where}: profile document must be a mapping")
        self._doc = copy.deepcopy(dict(document))
        self.source = source

        raw_name = self._doc.get("profile", source.stem if source else "anonymous")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ProfileError(f"{where}: profile must be a non-empty string")
        raw_version = self._doc.get("version", 1)
        if (
            not isinstance(raw_version, int)
            or isinstance(raw_version, bool)
            or raw_version < 1
        ):
            raise ProfileError(f"{where}: version must be a positive integer")
        raw_description = self._doc.get("description", "")
        raw_base_iri = self._doc.get("base_iri", "")
        if not isinstance(raw_description, str):
            raise ProfileError(f"{where}: description must be a string")
        if not isinstance(raw_base_iri, str):
            raise ProfileError(f"{where}: base_iri must be a string")

        mappings: dict[str, dict[str, Any]] = {}
        for field_name in ("namespaces", "roles", "capabilities", "notations", "limits"):
            value = self._doc.get(field_name, {})
            if not isinstance(value, Mapping):
                raise ProfileError(f"{where}: {field_name} must be a mapping")
            mappings[field_name] = dict(value)
        raw_taxonomies = self._doc.get("taxonomies", [])
        if not isinstance(raw_taxonomies, list):
            raise ProfileError(f"{where}: taxonomies must be a list")
        raw_graphs = self._doc.get("graphs", {})
        if not isinstance(raw_graphs, Mapping):
            raise ProfileError(f"{where}: graphs must be a mapping")
        graphs = dict(raw_graphs)
        raw_graph_roles = graphs.get("roles", {})
        if not isinstance(raw_graph_roles, Mapping):
            raise ProfileError(f"{where}: graphs.roles must be a mapping")
        raw_layout = graphs.get("layout", "per-model-triple")
        raw_named_graphs = graphs.get("named_graphs", True)
        if not isinstance(raw_layout, str):
            raise ProfileError(f"{where}: graphs.layout must be a string")
        if not isinstance(raw_named_graphs, bool):
            raise ProfileError(f"{where}: graphs.named_graphs must be a boolean")

        self.name = raw_name.strip()
        self.profile_version = raw_version
        self.description = raw_description.strip()
        self.base_iri = raw_base_iri.strip()
        self.namespaces = mappings["namespaces"]
        self.roles = mappings["roles"]
        self.capabilities = mappings["capabilities"]
        self.notations = mappings["notations"]
        self.taxonomies = list(raw_taxonomies)
        self.limits = mappings["limits"]
        self.navigation = self._read_navigation(document.get("navigation"), where)

        graph_roles = dict(raw_graph_roles)
        # `validation: null` is conventionally written at the `graphs` level in
        # the bundled profiles because it reads better next to the explanation of
        # why there is no validation graph. Fold it in so lookups are uniform.
        #
        # `required` is NOT a role and must stay out of this: folding it in would
        # invent a graph role named "required" whose value is a list of role names,
        # and verification would then probe for a graph whose IRI ends with
        # "semantic" on its behalf.
        for key, value in graphs.items():
            if key not in {"layout", "named_graphs", "roles", "required", "descendants"}:
                graph_roles.setdefault(key, value)
        self.graphs = GraphLayout(
            layout=raw_layout,
            named_graphs=raw_named_graphs,
            roles=graph_roles,
            required=self._read_required_graph_roles(graphs, graph_roles, where),
            descendants=self._read_descendant_graph_roles(
                graphs, graph_roles, raw_layout, where
            ),
        )

        self._validate()

    #: Required by default, where the profile declares it. A dataset with no semantic
    #: graph cannot answer a single scoped question, so the default is the strict one
    #: and opting out is explicit.
    DEFAULT_REQUIRED_GRAPH_ROLES = ("semantic",)

    @staticmethod
    def _read_required_graph_roles(
        graphs: Mapping[str, Any], graph_roles: Mapping[str, Any], where: str
    ) -> tuple[str, ...]:
        """Which graph roles must be present in a dataset for it to be usable.

        Absent key means the default. An empty list means "none", and is honoured -
        it is how a profile describing a dataset with an unusual layout says so,
        rather than being told it must contain a graph it has no reason to have.
        """
        declared = graphs.get("required", None)
        if declared is None and "required" not in graphs:
            return tuple(
                role for role in Profile.DEFAULT_REQUIRED_GRAPH_ROLES
                if graph_roles.get(role) is not None
            )
        if declared is None:
            return ()
        if isinstance(declared, str) or not isinstance(declared, (list, tuple)):
            raise ProfileError(
                f"{where}: graphs.required must be a list of graph role names"
            )
        names = []
        for item in declared:
            if not isinstance(item, str) or not item.strip():
                raise ProfileError(
                    f"{where}: graphs.required must contain non-empty role names"
                )
            names.append(item.strip())
        unknown = [n for n in names if graph_roles.get(n) is None]
        if unknown:
            # A required role that is not bound can never be satisfied, so the
            # profile would refuse every dataset. Nearly always a typo.
            available = ", ".join(sorted(k for k, v in graph_roles.items() if v is not None))
            raise ProfileError(
                f"{where}: graphs.required names {', '.join(sorted(unknown))}, which "
                f"{'is' if len(unknown) == 1 else 'are'} not bound under graphs.roles "
                f"(bound: {available or '<none>'})"
            )
        return tuple(dict.fromkeys(names))

    @staticmethod
    def _read_descendant_graph_roles(
        graphs: Mapping[str, Any], graph_roles: Mapping[str, Any],
        layout: str, where: str
    ) -> tuple[str, ...]:
        """Which graph roles also match graphs below them. Empty unless declared."""
        declared = graphs.get("descendants", None)
        if declared is None:
            return ()
        if isinstance(declared, str) or not isinstance(declared, (list, tuple)):
            raise ProfileError(
                f"{where}: graphs.descendants must be a list of graph role names"
            )
        names = []
        for item in declared:
            if not isinstance(item, str) or not item.strip():
                raise ProfileError(
                    f"{where}: graphs.descendants must contain non-empty role names"
                )
            names.append(item.strip())
        if names and layout != "per-model-triple":
            raise ProfileError(
                f"{where}: graphs.descendants needs layout 'per-model-triple'; "
                f"got {layout!r}. Under 'explicit' the roles hold literal graph IRIs "
                "and there is nothing to descend; under 'single' there are no graphs."
            )
        unknown = [n for n in names if graph_roles.get(n) is None]
        if unknown:
            available = ", ".join(sorted(k for k, v in graph_roles.items() if v is not None))
            raise ProfileError(
                f"{where}: graphs.descendants names {', '.join(sorted(unknown))}, which "
                f"{'is' if len(unknown) == 1 else 'are'} not bound under graphs.roles "
                f"(bound: {available or '<none>'})"
            )
        return tuple(dict.fromkeys(names))

    # -- validation ---------------------------------------------------------

    def _validate(self) -> None:
        where = self.source.name if self.source else "profile"

        if any(
            not isinstance(key, str)
            or not key.strip()
            or key != key.strip()
            or not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            for key, value in self.namespaces.items()
        ):
            raise ProfileError(
                f"{where}: namespaces must map stripped, non-empty names to stripped, non-empty strings"
            )
        if any(
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
            for key, value in self.roles.items()
        ):
            raise ProfileError(
                f"{where}: roles must map names to strings, non-empty string lists, or null"
            )
        if any(
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
            for key, value in self.graphs.roles.items()
        ):
            raise ProfileError(
                f"{where}: graph roles must map names to strings, non-empty string lists, or null"
            )
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, Mapping)
            for key, value in self.notations.items()
        ):
            raise ProfileError(f"{where}: notations must map names to mappings")
        if any(
            not isinstance(item, Mapping)
            or any(not isinstance(key, str) or not key for key in item)
            for item in self.taxonomies
        ):
            raise ProfileError(f"{where}: taxonomies must contain mappings with string keys")
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            for key, value in self.limits.items()
        ):
            raise ProfileError(f"{where}: limits must map names to positive integers")

        if self.graphs.layout not in LAYOUTS:
            raise ProfileError(
                f"{where}: graphs.layout is {self.graphs.layout!r}; "
                f"expected one of {', '.join(sorted(LAYOUTS))}"
            )
        if self.graphs.layout == "single" and self.graphs.named_graphs:
            raise ProfileError(
                f"{where}: graphs.layout 'single' contradicts named_graphs: true. "
                "A flattened dataset has no named graphs to scope to."
            )
        if self.graphs.layout == "explicit":
            for role, value in self.graphs.roles.items():
                if value is None:
                    continue
                for iri in value if isinstance(value, list) else [value]:
                    if not _is_absolute_iri(str(iri)):
                        raise ProfileError(
                            f"{where}: graphs.roles.{role} must hold absolute IRIs "
                            f"under layout 'explicit'; got {iri!r}"
                        )

        missing = [r for r in REQUIRED_ROLES if not self.roles.get(r)]
        if missing:
            raise ProfileError(
                f"{where}: these roles must be bound and are not: {', '.join(missing)}"
            )

        for capability, value in self.capabilities.items():
            if not isinstance(capability, str) or not capability:
                raise ProfileError(f"{where}: capability names must be non-empty strings")
            if capability == "label_language":
                if not isinstance(value, str) or not value.strip():
                    raise ProfileError(
                        f"{where}: capability 'label_language' must be a non-empty string"
                    )
                continue
            if not isinstance(value, bool) and value != "partial":
                raise ProfileError(
                    f"{where}: capability {capability!r} is {value!r}; "
                    "expected true, false or 'partial'"
                )

        # Resolve every binding now so a typo surfaces on load rather than
        # halfway through an investigation.
        for role in self.roles:
            if self.roles[role] is not None:
                self.expand_role(role)

    # -- terms --------------------------------------------------------------

    #: How a dataset expresses "this element belongs to that model".
    #:
    #: Converter output nests elements under a folder tree, so membership is a one-to-three
    #: hop traversal - and the chain is not reliably complete: it is emitted for BPMN but
    #: stops at `folder/Elements` for C4 (PROPOSAL Appendix A7). That is why the *default*
    #: is co-location rather than the folder path: every concept in a model's semantic graph
    #: belongs to that model, which holds for every converter. A dataset whose folder chain
    #: is complete can say so and get the more precise traversal.
    #: How a dataset says "this concept belongs to that model". The first is the
    #: default because it holds for every converter at default flags.
    #:
    #: ``direct-predicate`` is the converter's real 1.3 contract and is better than
    #: both others where it exists - one hop, on every concept, needing neither
    #: named graphs nor a complete folder chain. It is not the default only because
    #: a pre-1.3 dataset does not carry the edge.
    MEMBERSHIP_MODES = (
        "same-graph-colocation", "bounded-folder-tree", "direct-predicate",
    )
    DEFAULT_MEMBERSHIP_DEPTH = 3
    MAX_MEMBERSHIP_DEPTH = 6

    def _read_navigation(self, raw: Any, where: str) -> dict[str, Any]:
        """Validate the optional ``navigation`` section.

        Membership used to be re-invented per template: `core/provenance` finds the model by
        co-location, and a field session hand-wrote a bounded folder path for the same thing.
        Expressing it once as a profile fact means a template asks for membership and the
        dataset decides what that means.
        """
        if raw is None:
            membership: dict[str, Any] = {}
        elif not isinstance(raw, dict):
            raise ProfileError(f"{where}: navigation must be a mapping")
        else:
            unknown = set(raw) - {"model_membership"}
            if unknown:
                raise ProfileError(
                    f"{where}: navigation has unknown key(s) {sorted(unknown)}; "
                    "only model_membership is defined"
                )
            membership = raw.get("model_membership") or {}
            if not isinstance(membership, dict):
                raise ProfileError(f"{where}: navigation.model_membership must be a mapping")

        unknown = set(membership) - {"mode", "max_depth"}
        if unknown:
            raise ProfileError(
                f"{where}: navigation.model_membership has unknown key(s) {sorted(unknown)}"
            )

        mode = membership.get("mode", self.MEMBERSHIP_MODES[0])
        if mode not in self.MEMBERSHIP_MODES:
            raise ProfileError(
                f"{where}: navigation.model_membership.mode is {mode!r}; expected one of "
                f"{', '.join(self.MEMBERSHIP_MODES)}"
            )
        if mode == "direct-predicate" and not self.roles.get("part_of_model"):
            # The mode is nothing but that predicate, so an unbound role would render
            # a pattern with no edge and silently match every model in the dataset.
            raise ProfileError(
                f"{where}: navigation.model_membership.mode is 'direct-predicate' but "
                "roles.part_of_model is not bound. That mode IS the predicate, so "
                "without it membership would match every model and name the wrong one."
            )
        depth = membership.get("max_depth", self.DEFAULT_MEMBERSHIP_DEPTH)
        if (
            not isinstance(depth, int)
            or isinstance(depth, bool)
            or depth < 1
            or depth > self.MAX_MEMBERSHIP_DEPTH
        ):
            raise ProfileError(
                f"{where}: navigation.model_membership.max_depth must be an integer between "
                f"1 and {self.MAX_MEMBERSHIP_DEPTH}; an unbounded traversal is not offered "
                "because it turns one wrong hop into a whole-dataset scan"
            )
        if mode == "bounded-folder-tree" and self.roles.get("part_of") is None:
            raise ProfileError(
                f"{where}: navigation.model_membership.mode 'bounded-folder-tree' needs the "
                "'part_of' role bound, since that is the predicate it walks"
            )
        return {"model_membership": {"mode": mode, "max_depth": depth}}

    def expand_term(self, term: str) -> str:
        """Resolve a CURIE or absolute IRI to an absolute IRI, unbracketed."""
        text = str(term).strip()
        if text.startswith("<") and text.endswith(">"):
            text = text[1:-1]
        if _is_absolute_iri(text):
            return text
        match = _CURIE.match(text)
        if not match:
            raise ProfileError(
                f"{text!r} is neither an absolute IRI nor prefix:local"
            )
        prefix, local = match.groups()
        if prefix not in self.namespaces:
            known = ", ".join(sorted(self.namespaces))
            raise ProfileError(
                f"Unknown prefix {prefix!r} in {text!r}. Declared prefixes: {known}"
            )
        expanded = f"{self.namespaces[prefix]}{local}"
        if not _is_absolute_iri(expanded):
            raise ProfileError(
                f"{text!r} expands to invalid absolute IRI {expanded!r}"
            )
        return expanded

    def role(self, name: str) -> str:
        """The primary IRI bound to ``name``.

        Raises if the role is unbound, because reaching here with an unbound role
        means a template declared it optional when it is not.
        """
        return self.expand_role(name)[0]

    def expand_role(self, name: str) -> list[str]:
        """Every IRI bound to ``name``, in preference order."""
        if name not in self.roles:
            known = ", ".join(sorted(k for k, v in self.roles.items() if v is not None))
            raise ProfileError(
                f"Profile {self.name!r} declares no role {name!r}. Bound roles: {known}"
            )
        value = self.roles[name]
        if value is None:
            raise ProfileError(
                f"Profile {self.name!r} binds role {name!r} to null: this dataset "
                "does not represent it."
            )
        terms = value if isinstance(value, list) else [value]
        if not terms:
            raise ProfileError(f"Profile {self.name!r} binds role {name!r} to an empty list")
        return [self.expand_term(t) for t in terms]

    def has_role(self, name: str) -> bool:
        return self.roles.get(name) is not None

    def capability(self, name: str) -> Any:
        """A capability's value; ``False`` when undeclared.

        Undeclared reads as absent on purpose. A profile that has not thought
        about a capability should not have templates depending on it silently.
        """
        return self.capabilities.get(name, False)

    def prefix_block(self) -> str:
        """The ``PREFIX`` block prepended to every rendered query."""
        return "\n".join(
            f"PREFIX {prefix}: <{iri}>" for prefix, iri in sorted(self.namespaces.items())
        )

    def notation_for_metamodel(self, metamodel_iri: str) -> str | None:
        """The notation slug whose metamodel is ``metamodel_iri``."""
        for slug, spec in self.notations.items():
            if str((spec or {}).get("metamodel", "")) == metamodel_iri:
                return slug
        return None

    def row_limit(self, requested: int | None = None) -> int:
        default = int(self.limits.get("default_row_limit", 200))
        ceiling = int(self.limits.get("max_row_limit", 5000))
        return min(int(requested) if requested else default, ceiling)

    # -- reporting ----------------------------------------------------------

    def summary(self) -> str:
        lines = [
            f"profile        {self.name} (v{self.profile_version})",
            f"source         {self.source if self.source else '<in memory>'}",
            f"base IRI       {self.base_iri or '<unset>'}",
            f"graph layout   {self.graphs.layout}"
            f" (named graphs: {'yes' if self.graphs.named_graphs else 'no'})",
            f"graph roles    {', '.join(self.graphs.role_names()) or '<none>'}",
            f"notations      {', '.join(sorted(self.notations)) or '<none>'}",
            f"taxonomies     {len(self.taxonomies)}",
            "",
            "capabilities",
        ]
        for name in sorted(self.capabilities):
            lines.append(f"  {name:22} {self.capabilities[name]}")

        bound = sorted(k for k, v in self.roles.items() if v is not None)
        unbound = sorted(k for k, v in self.roles.items() if v is None)
        lines += ["", f"roles bound    {len(bound)}"]
        for name in bound:
            value = self.roles[name]
            shown = ", ".join(value) if isinstance(value, list) else str(value)
            lines.append(f"  {name:22} {shown}")
        if unbound:
            lines += ["", "roles declared absent (templates requiring these are refused)"]
            for name in unbound:
                lines.append(f"  {name}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return copy.deepcopy(self._doc)

    def source_reference(self) -> str:
        """How a child profile should name this one in its ``extends``.

        A path RELATIVE TO THE BUNDLED DIRECTORY for a bundled profile - so
        ``examples/curated-store.yaml`` rather than ``curated-store.yaml``. It keeps the
        child portable between machines, and it is what ``_read`` can actually resolve:
        a basename reference misses every bundled profile that lives in a subdirectory,
        so a child generated from one of those could not be loaded at all.

        An absolute path otherwise, which resolution accepts as a sibling reference and
        which is the only thing that can be correct for a profile kept beside a graph.
        """
        if self.source is None:
            return "linked-archi-default.yaml"
        source = self.source.resolve()
        try:
            relative = source.relative_to(PROFILE_DIR.resolve())
        except ValueError:
            return str(source)
        return relative.as_posix()

    def resolved_snapshot(self) -> dict[str, Any]:
        """Return the versioned, normalized contract consumed by companion skills.

        Inheritance and CURIE expansion happen here, in the profile owner. Consumers
        receive absolute role lists (or explicit nulls) and never reimplement profile
        loading or vocabulary resolution.

        The snapshot carries its own ``fingerprint``, so a consumer keying anything on
        "which profile is this, exactly" reads that rather than recomputing a digest.
        See :func:`_fingerprint`.
        """
        snapshot: dict[str, Any] = {
            "schema_version": 1,
            "name": self.name,
            "version": self.profile_version,
            "source": str(self.source.resolve()) if self.source else None,
            "description": self.description,
            "base_iri": self.base_iri,
            "namespaces": dict(self.namespaces),
            "roles": {
                name: (self.expand_role(name) if value is not None else None)
                for name, value in self.roles.items()
            },
            "graphs": {
                "layout": self.graphs.layout,
                "named_graphs": self.graphs.named_graphs,
                "roles": copy.deepcopy(dict(self.graphs.roles)),
                "required": list(self.graphs.required),
                "descendants": list(self.graphs.descendants),
            },
            "capabilities": copy.deepcopy(self.capabilities),
            "notations": copy.deepcopy(self.notations),
            "taxonomies": copy.deepcopy(self.taxonomies),
            "limits": copy.deepcopy(self.limits),
            "navigation": copy.deepcopy(self.navigation),
        }
        snapshot["fingerprint"] = _fingerprint(snapshot)
        return snapshot

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Profile {self.name!r} v{self.profile_version} layout={self.graphs.layout}>"


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One discrepancy between what a profile claims and what a dataset holds."""

    severity: str  # "error" | "warning" | "info"
    subject: str
    message: str
    #: The observed correction, as ``(dotted_key, value)``, when this drift can be
    #: mechanically fixed. Only set where the fix is unambiguous - a capability claim
    #: contradicted by a probe. Deliberately absent for the rest:
    #:
    #: * an **unused role** is usually harmless, and nulling it would refuse every
    #:   template that requires it. That is a bigger change than the finding warrants.
    #: * **named graphs claimed but absent** needs a different `layout`, not a key
    #:   edit, so the report names the `single`-layout profiles instead of guessing.
    #:
    #: Carried as data rather than parsed back out of ``message``, so the report wording
    #: and the generated profile cannot drift apart.
    fix: tuple[str, Any] | None = None

    def __str__(self) -> str:
        mark = {"error": "FAIL", "warning": "warn", "info": "ok  "}[self.severity]
        return f"{mark} {self.subject:34} {self.message}"


class _ProbePlanner:
    def __init__(self, sparql_12: bool = False) -> None:
        self.queries: list[str] = []
        #: Mirrors the real adapter's flag, so a pass that varies its QUERIES on engine
        #: support plans the same set it will later replay. Varying on a probe RESULT stays
        #: forbidden — `ask` always answers False here.
        self.sparql_12 = sparql_12

    def ask(self, query: str) -> bool:
        self.queries.append(query)
        return False

    def count(self, query: str) -> int:
        self.queries.append(query)
        # A positive planning value includes graph-role probes. Replay applies the
        # real count and skips those findings naturally for graphless datasets.
        return 1


class _ReplayProbe:
    def __init__(
        self, queries: list[str], results: Sequence[object], sparql_12: bool = False
    ) -> None:
        self._results: dict[str, list[object]] = {}
        self._positions: dict[str, int] = {}
        #: Same value the planner saw. See :class:`_ProbePlanner`.
        self.sparql_12 = sparql_12
        for query, result in zip(queries, results):
            self._results.setdefault(query, []).append(result)

    @staticmethod
    def _value(result: object, name: str, default=None):
        return result.get(name, default) if isinstance(result, dict) else getattr(result, name, default)

    def _take(self, query: str) -> object:
        position = self._positions.get(query, 0)
        matches = self._results.get(query, [])
        if position >= len(matches):
            raise ProfileError("profile verification requested an unplanned probe")
        self._positions[query] = position + 1
        return matches[position]

    def ask(self, query: str) -> bool:
        return bool(self._value(self._take(query), "boolean"))

    def count(self, query: str) -> int:
        result = self._take(query)
        rows = self._value(result, "rows", []) or []
        if not rows:
            return 0
        variables = self._value(result, "variables", []) or list(rows[0])
        for key in variables:
            try:
                return int(str(rows[0].get(key)))
            except (TypeError, ValueError):
                continue
        return 0


def _batched(run, adapter):
    """Run an ask/count probe pass in one round trip when the adapter supports it.

    Plan against a recording stub, execute the whole batch, then run the same pass again
    against the recorded answers. Shared by verification and shape observation because both
    are a sequence of small probes, and paying one process and one graph load per probe
    made verification the slowest step in the package.

    The pass must therefore be deterministic in the QUERIES it asks: it may skip probes on
    replay, never invent new ones.
    """
    execute_many = getattr(adapter, "execute_many", None)
    if not callable(execute_many):
        return run(adapter)
    sparql_12 = bool(getattr(adapter, "sparql_12", False))
    planner = _ProbePlanner(sparql_12)
    run(planner)
    results = execute_many(planner.queries)
    if not isinstance(results, Sequence) or len(results) != len(planner.queries):
        raise ProfileError("profile probe batch returned the wrong number of results")
    return run(_ReplayProbe(planner.queries, results, sparql_12))


def verify_against_dataset(profile: Profile, adapter) -> list[Finding]:
    """Batch profile probes when supported, then interpret them in stable order."""
    return _batched(lambda probe: _verify_against_dataset(profile, probe), adapter)


def _verify_against_dataset(profile: Profile, adapter) -> list[Finding]:
    """Interpret one owner-neutral ask/count probe contract.

    This is what stops a profile becoming the same kind of stale prose that the
    ``conventions.md`` it replaces became: a claim that can be checked, and is.

    ``adapter`` provides ``ask(query)`` and ``count(query)``. The public verifier
    plans a batch first when the adapter also provides ``execute_many(queries)``.
    """
    findings: list[Finding] = []
    p = profile.prefix_block()

    def ask(pattern: str) -> bool:
        return adapter.ask(f"{p}\nASK {{ {pattern} }}")

    # --- named graphs ------------------------------------------------------
    if profile.graphs.named_graphs:
        graph_count = adapter.count(
            f"{p}\nSELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ GRAPH ?g {{ ?s ?pp ?o }} }}"
        )
        if graph_count == 0:
            findings.append(
                Finding(
                    "error",
                    "graphs.named_graphs",
                    "profile says named graphs, dataset has none. If this is Turtle, "
                    "use a profile with layout 'single'; every scoped query returns "
                    "nothing otherwise.",
                )
            )
        else:
            findings.append(Finding("info", "graphs.named_graphs", f"{graph_count} named graph(s)"))
            for role in profile.graphs.role_names():
                suffix = profile.graphs.roles[role]
                descendants = False
                if profile.graphs.layout == "per-model-triple":
                    present = ask(
                        f"GRAPH ?g {{ ?s ?pp ?o }} "
                        f"FILTER({profile.graphs.suffix_test(role, '?g')})"
                    )
                    if not present:
                        # Distinguish "absent" from "present but partitioned". A
                        # suffix selector cannot match `graph/semantic/{repo}/{path}`,
                        # so a dataset that splits a role across descendant graphs
                        # looks identical to one that lacks the role entirely - and
                        # the two need opposite fixes. Only asked when the role is
                        # already missing, which the batching contract allows.
                        descendants = ask(
                            f'GRAPH ?g {{ ?s ?pp ?o }} '
                            f'FILTER(CONTAINS(STR(?g), "{suffix}/"))'
                        )
                else:
                    iris = suffix if isinstance(suffix, list) else [suffix]
                    values = " ".join(f"<{i}>" for i in iris)
                    present = ask(f"VALUES ?g {{ {values} }} GRAPH ?g {{ ?s ?pp ?o }}")
                if present:
                    findings.append(Finding("info", f"graphs.roles.{role}", "present"))
                    continue
                # A required role that matches nothing is an error, and the exit code
                # says so. Reporting it as a warning and exiting 0 is how a run comes
                # back with no rows and no complaint: every query scoped to this role
                # is asking about a graph that is not there, so "no results" means
                # "wrong profile", not "nothing to find".
                required = profile.graphs.is_required(role)
                if descendants:
                    message = (
                        f"no graph matching {suffix!r}, but the dataset has graphs "
                        f"BELOW it - {suffix}/... - so this role is partitioned, not "
                        f"missing. A suffix selector cannot match a descendant graph. "
                        f"Use a profile whose {role} selector matches the partitioned "
                        f"layout; the content is there and is being skipped."
                    )
                else:
                    message = f"no graph matching {suffix!r}"
                    if required:
                        message += (
                            ". Every query scoped to this role returns nothing, so "
                            "results would be silently empty rather than wrong-looking."
                        )
                findings.append(
                    Finding(
                        "error" if required else "warning",
                        f"graphs.roles.{role}",
                        message,
                    )
                )

    # --- roles -------------------------------------------------------------
    for name in sorted(k for k, v in profile.roles.items() if v is not None):
        iris = profile.expand_role(name)
        alternatives = " UNION ".join(
            f"{{ ?s <{iri}> ?o }} UNION {{ ?s ?pp <{iri}> }} UNION {{ ?s a <{iri}> }}"
            for iri in iris
        )
        used = ask(f"GRAPH ?g {{ {alternatives} }}") if profile.graphs.named_graphs \
            else ask(alternatives)
        findings.append(
            Finding(
                "info" if used else "warning",
                f"roles.{name}",
                "in use" if used else f"bound to {', '.join(iris)} but unused in this dataset",
            )
        )

    # --- capabilities ------------------------------------------------------
    findings += _verify_capabilities(profile, adapter)
    return findings


def _verify_capabilities(profile: Profile, adapter) -> list[Finding]:
    """Check the capability claims that can be probed cheaply."""
    findings: list[Finding] = []
    p = profile.prefix_block()
    scope = "GRAPH ?g {{ {} }}" if profile.graphs.named_graphs else "{}"

    def ask(pattern: str) -> bool:
        return adapter.ask(f"{p}\nASK {{ {scope.format(pattern)} }}")

    rel_class = profile.role("relationship_class")
    src, tgt = profile.role("rel_source"), profile.role("rel_target")

    #: ``None`` means the dataset cannot answer the question, which is different from
    #: answering "no". A claim is never contradicted on the strength of an unknown.
    probes: list[tuple[str, bool | None]] = []

    # Direct triples. The question is NOT "are these two endpoints joined by some other
    # predicate" - that is what this used to ask, and it produced a false positive on any
    # unrelated edge between the same pair. One `dct:relation` between two elements that a
    # qualified relationship also connects was enough to report the capability present,
    # which then un-refused the templates that read direct edges, and those returned rows
    # meaning something else entirely. Verified, not theorised.
    #
    # The real question is whether the endpoints are joined by the predicate this
    # relationship's class DECLARES as its unqualified form. That declaration lives in the
    # ontologies (`arch:unqualifiedForm`), and a converted dataset does not include them -
    # so it is only answerable when the ontology has been loaded alongside the data.
    #
    # Hence three-valued. Where no declaration is present the honest answer is "unknown",
    # not "no": absence of the mapping is absence of evidence. Confirming a genuine `true`
    # needs the ontology corpus, which is the ontology-acquisition work this package has
    # not done yet.
    # Any predicate at all joining the endpoints. Not sufficient to claim the capability,
    # but decisive the other way: with no candidate edge there can be no declared one, so
    # this still confirms a `false` without needing any ontology.
    any_candidate = ask(
        f"?r a <{rel_class}> ; <{src}> ?s ; <{tgt}> ?t . ?s ?direct ?t . "
        f"FILTER(?direct != <{src}> && ?direct != <{tgt}>)"
    )
    # The declaration comes from the RDF 1.2 bridge on the relationship itself. Its triple
    # term names the unqualified predicate AND both endpoints, so one pattern answers the
    # question the permissive form could only guess at, from the data, with no ontology.
    #
    # The trailing `?s ?direct ?t` is not redundant. A triple term is NOT an asserted
    # triple: it denotes a proposition, a plain pattern does not match inside it, and
    # property paths do not traverse it. The bridge alone says which predicate the
    # relationship stands for and nothing about whether that edge was written, so asking for
    # the asserted triple as well is what makes this a check rather than an assumption about
    # what the converter does.
    #
    # Gated rather than tried and caught, because `<<( s p o )>>` is a PARSE error on a
    # SPARQL 1.1 engine and `execute_many` fails a whole batch on one bad query - so probing
    # optimistically would take `verify` down against every 1.1 endpoint. Two ways to open
    # the gate: the backend says it parses 1.2 (`adapter.sparql_12`, true for pyoxigraph), or
    # the profile claims `rdf_reifies`, which is how an operator asserts it of a remote
    # endpoint and the same gate templates needing the syntax are refused by. Neither leaves
    # the answer to `any_candidate` below, which is three-valued and needs no 1.2 support.
    #
    # Both inputs are static, which keeps the batch deterministic: `_batched` plans the query
    # set against a stub whose `ask` always returns False, so branching on a probe RESULT
    # here would ask on replay what planning never recorded.
    #
    # Supersedes `arch:relPredicate`, which the converters used to emit for this. Core never
    # published it - the historyNote on QualifiedRelationship records the rdf:Statement
    # design behind that name being dropped - and no converter emits it any more.
    forms_declared = declared_direct = False
    # `partial` opens this gate as well as `true`. The gate is about SYNTAX - can the
    # engine parse `<<( s p o )>>` - and a bridge covering some relationships still has to
    # be parseable to be read at all. Accepting only `true` would leave the honest claim
    # for a partially bridged remote endpoint unable to probe its own bridge.
    can_destructure = (
        getattr(adapter, "sparql_12", False)
        or profile.capability("rdf_reifies") in (True, "partial")
    )
    if profile.has_role("reifies") and can_destructure:
        bridge = profile.role("reifies")
        forms_declared = ask(f"?anyRel <{bridge}> ?anyTerm")
        declared_direct = ask(
            f"?r a <{rel_class}> ; <{src}> ?s ; <{tgt}> ?t ; "
            f"<{bridge}> <<( ?s ?direct ?t )>> . ?s ?direct ?t ."
        )
    if forms_declared:
        observed_direct: bool | None = declared_direct
    elif not any_candidate:
        observed_direct = False
    else:
        observed_direct = None
    probes.append(("direct_rel_triples", observed_direct))
    # Two ASKs rather than one, because presence and coverage are different questions and
    # only the second can distinguish "this dataset has the bridge" from "this dataset has
    # the bridge everywhere". A single existence probe reports the first and recommends
    # `true`, which overstates any dataset where the bridge is notation-specific - the
    # normal case, since each converter emits it only under its own flag, and the usual
    # shape of an aggregate store. Both probes are static, so the batch stays deterministic:
    # nothing here branches on a probe result.
    reifies = "http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies"
    bridge_present = ask(f"?r <{reifies}> ?x")
    bridge_absent = ask(
        f"?r a <{rel_class}> ; <{src}> ?s ; <{tgt}> ?t . "
        f"FILTER NOT EXISTS {{ ?r <{reifies}> ?anyTerm }}"
    )
    probes.append((
        "rdf_reifies",
        "partial" if bridge_present and bridge_absent else bridge_present,
    ))
    if profile.has_role("owner"):
        probes.append(("concept_owner", ask(f"?s <{profile.role('owner')}> ?o")))
    if profile.has_role("same_as") or profile.has_role("exact_match"):
        identity = [
            profile.role(r) for r in ("same_as", "exact_match") if profile.has_role(r)
        ]
        probes.append((
            "identity_assertions",
            ask(" UNION ".join(f"{{ ?s <{i}> ?o }}" for i in identity)),
        ))
    if profile.has_role("element_lifecycle"):
        probes.append((
            "element_lifecycle",
            ask(" UNION ".join(
                f"{{ ?s <{i}> ?o }}" for i in profile.expand_role("element_lifecycle")
            )),
        ))
    if profile.has_role("view_node_class"):
        probes.append((
            "views_graph",
            ask(" UNION ".join(
                f"{{ ?n a <{i}> }}" for i in profile.expand_role("view_node_class")
            )),
        ))
    if profile.has_role("bounds_x"):
        probes.append(("view_geometry", ask(f"?n <{profile.role('bounds_x')}> ?x")))
    probes.append((
        "validation_in_graph",
        ask("?r a <http://www.w3.org/ns/shacl#ValidationReport>"),
    ))

    for name, observed in probes:
        claimed = profile.capability(name)
        if observed is None:
            # Unknown. Report what is missing and move on: contradicting a claim here
            # would be asserting something the dataset does not say, and "fixing" the
            # profile to match an unknown is how a correct claim gets deleted.
            findings.append(Finding(
                "info", f"capabilities.{name}",
                f"claimed {claimed!r}; some predicate joins the endpoints of a qualified "
                "relationship, but no rdf:reifies bridge says which predicate that "
                "relationship stands for, so a genuine unqualified form cannot be told "
                "from an unrelated edge between the same two resources. Left as claimed - "
                "re-convert with --emit-direct-rel-triples, or claim "
                "capabilities.rdf_reifies if the endpoint speaks SPARQL 1.2, to settle it.",
            ))
            continue
        if observed == "partial":
            # Measured coverage, so it outranks a claim in either direction. `true` would
            # promise a completeness the data does not have, and `false` refuses templates
            # the data can answer for part of the estate; `partial` runs them and carries
            # the caveat that a short result may be coverage rather than absence.
            if claimed == "partial":
                findings.append(Finding(
                    "info", f"capabilities.{name}", "partial, confirmed by coverage",
                ))
            else:
                findings.append(Finding(
                    "warning", f"capabilities.{name}",
                    f"claimed {str(claimed).lower()}, but present for some qualified "
                    "relationships and absent for others - so neither true nor false "
                    "describes this dataset. Set it 'partial': templates needing it then "
                    "run with a coverage caveat instead of promising completeness or "
                    "being refused outright.",
                    fix=(f"capabilities.{name}", "partial"),
                ))
            continue
        if claimed is True and not observed:
            findings.append(Finding(
                "error", f"capabilities.{name}",
                "claimed true, not found in dataset. Templates requiring it will run "
                "and return nothing - set it false or fix the dataset.",
                fix=(f"capabilities.{name}", False),
            ))
        elif claimed is False and observed:
            findings.append(Finding(
                "warning", f"capabilities.{name}",
                "claimed false but present. Templates needing it are being refused "
                "unnecessarily - set it true.",
                fix=(f"capabilities.{name}", True),
            ))
        elif claimed == "partial":
            findings.append(Finding(
                "info", f"capabilities.{name}",
                f"partial, {'observed' if observed else 'not observed here'}",
            ))
        else:
            findings.append(Finding("info", f"capabilities.{name}", f"{claimed}, confirmed"))
    return findings


@dataclass(frozen=True)
class Observation:
    """One measured fact about a dataset's shape, and what it implies for a profile."""

    subject: str
    value: str
    implication: str

    def __str__(self) -> str:
        return f"     {self.subject:22} {self.value:30} {self.implication}"


@dataclass(frozen=True)
class Recommendation:
    """A named starting profile, the evidence for it, and what is still unknown."""

    profile: str
    observations: tuple[Observation, ...]
    reasons: tuple[str, ...]
    caveats: tuple[str, ...]


def observe_dataset(adapter) -> tuple[Observation, ...]:
    """Measure shape, batching through one round trip where the adapter allows it."""
    return _batched(_observe_dataset, adapter)


def _observe_dataset(adapter) -> tuple[Observation, ...]:
    """Measure the shape facts that decide which bundled profile fits.

    Read through the **published Linked.Archi vocabulary**, because that is the only
    vocabulary a recommendation can assume: a dataset built on a custom ontology cannot be
    recognised by probing for terms nobody has named yet, and `derive` is the answer for it.
    Stated as a caveat on every recommendation rather than left for the reader to discover.

    Same ask/count contract as verification, so it batches through one `execute_many` when
    the adapter supports it.
    """
    lens = load_profile(DEFAULT_PROFILE)
    p = lens.prefix_block()

    def ask(pattern: str) -> bool:
        return adapter.ask(f"{p}\nASK {{ {pattern} }}")

    def graphs_ending(suffix: str) -> int:
        return adapter.count(
            f"{p}\nSELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ GRAPH ?g {{ ?s ?pp ?o }} "
            f'FILTER(STRENDS(STR(?g), "{suffix}")) }}'
        )

    def graphs_below(suffix: str) -> int:
        """Graphs BELOW a suffix, which a suffix test cannot see.

        The trailing slash makes this a path test rather than a prefix test, matching
        ``GraphLayout.suffix_test``. This is the measurement that tells a partitioned
        semantic graph apart from a missing one - the two are indistinguishable to
        ``graphs_ending`` and need opposite fixes.
        """
        return adapter.count(
            f"{p}\nSELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ GRAPH ?g {{ ?s ?pp ?o }} "
            f'FILTER(CONTAINS(STR(?g), "{suffix}/")) }}'
        )

    total_graphs = adapter.count(
        f"{p}\nSELECT (COUNT(DISTINCT ?g) AS ?n) WHERE {{ GRAPH ?g {{ ?s ?pp ?o }} }}"
    )

    def scoped(pattern: str) -> bool:
        """Ask inside and outside named graphs at once.

        Not a convenience: the query text must not depend on an earlier probe's ANSWER.
        Probes are planned in one pass and replayed against a batch keyed by query text, so
        branching the scope on ``total_graphs`` would ask a question in replay that was
        never planned - and that is an error rather than a wrong answer, which is how this
        was found.
        """
        return ask(f"{{ GRAPH ?g {{ {pattern} }} }} UNION {{ {pattern} }}")

    rel = lens.role("relationship_class")
    src, tgt = lens.role("rel_source"), lens.role("rel_target")
    part_of = lens.role("part_of")
    model = lens.role("model_class")

    observations = [
        Observation(
            "named graphs", str(total_graphs),
            "a graph-scoped layout" if total_graphs
            else "no scoping is possible: layout must be 'single'",
        ),
    ]
    if total_graphs:
        for role in ("semantic", "views", "provenance"):
            suffix = lens.graphs.roles.get(role)
            count = graphs_ending(str(suffix)) if suffix else 0
            observations.append(Observation(
                f"graph/{role}", str(count),
                "present" if count else "absent: templates needing it are refused",
            ))
        for role, suffix in (("reconciliation", "graphs/reconciliation"),
                             ("validation", "graphs/validation")):
            count = graphs_ending(suffix)
            observations.append(Observation(
                f"{role} graph", "present" if count else "absent",
                "an authored store" if count else "raw converter output",
            ))

        # The two observations that tell the converter GENERATIONS apart. Worth
        # measuring even though the reader cannot act on them directly, because the
        # pre-1.3 profile against a 1.3 dataset is the one mismatch that empties every
        # scoped query while looking like an answer about the architecture.
        model_graphs = graphs_ending("graph/model")
        observations.append(Observation(
            "graph/model", str(model_graphs),
            "1.3 layout: arch:Model lives here, not in the semantic graph"
            if model_graphs else "pre-1.3 layout: the model is in the semantic graph",
        ))
        partitioned = graphs_below("graph/semantic")
        observations.append(Observation(
            "semantic partitions", str(partitioned),
            "graph/semantic/{repo}/{path}: a suffix selector matches NONE of these"
            if partitioned else "one semantic graph per model",
        ))

    # Three-valued, matching `_verify_capabilities`. These two commands must not disagree
    # about the same dataset, and they did: this used to ask only whether SOME predicate
    # joins the endpoints, so a real estate carrying no declaration was reported here as
    # "converted with --emit-direct-rel-triples" while `verify` correctly called it
    # unverifiable. An unrelated edge between the same two resources is enough to fool the
    # permissive form.
    candidate = scoped(
        f"?r a <{rel}> ; <{src}> ?s ; <{tgt}> ?t . ?s ?direct ?t . "
        f"FILTER(?direct != <{src}> && ?direct != <{tgt}>)"
    )
    # Same declaration source, same gate, same reasoning as `_verify_capabilities` - see the
    # comment there. These two commands must not disagree about one dataset, so the pair of
    # queries is kept identical rather than merely equivalent.
    # The lens is a vocabulary, not a description of this dataset, so its `rdf_reifies` claim
    # says nothing here — `observe_dataset` is measuring a graph nobody has profiled yet.
    # Engine support is the only gate that applies.
    bridge = (
        lens.role("reifies")
        if lens.has_role("reifies") and getattr(adapter, "sparql_12", False)
        else None
    )
    declared_any = scoped(f"?anyRel <{bridge}> ?anyTerm") if bridge else False
    declared_direct = scoped(
        f"?r a <{rel}> ; <{src}> ?s ; <{tgt}> ?t ; "
        f"<{bridge}> <<( ?s ?direct ?t )>> . ?s ?direct ?t ."
    ) if bridge else False
    if declared_any:
        observations.append(Observation(
            "direct rel triples", "present" if declared_direct else "absent",
            "converted with --emit-direct-rel-triples" if declared_direct
            else "qualified form only, the converter default",
        ))
    elif not candidate:
        observations.append(Observation(
            "direct rel triples", "absent",
            "qualified form only, the converter default",
        ))
    else:
        observations.append(Observation(
            "direct rel triples", "unverifiable",
            "edges exist between endpoints but no rdf:reifies bridge says which one is the "
            "unqualified form; claim capabilities.rdf_reifies if the engine speaks SPARQL 1.2",
        ))
    reifies = scoped("?r <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> ?x")
    observations.append(Observation(
        "rdf:reifies", "present" if reifies else "absent",
        "needs a SPARQL 1.2 engine" if reifies else "no triple terms",
    ))
    identity = scoped(
        "{ ?s <http://www.w3.org/2004/02/skos/core#exactMatch> ?o } UNION "
        "{ ?s <http://www.w3.org/2002/07/owl#sameAs> ?o }"
    )
    observations.append(Observation(
        "identity assertions", "present" if identity else "absent",
        "cross-notation joins are possible" if identity
        else "cross-notation joins cannot be made",
    ))
    validation = scoped("?r a <http://www.w3.org/ns/shacl#ValidationReport>")
    observations.append(Observation(
        "SHACL report", "in the dataset" if validation else "absent",
        "core/validation-summary can run" if validation
        else "a report is a document here, not a graph",
    ))
    # Membership: is the folder chain actually walkable, or is co-location the only
    # portable answer? The measurement PR1's default rests on.
    folder_walk = scoped(
        f"?c ((<{part_of}>)|(<{part_of}>/<{part_of}>)|"
        f"(<{part_of}>/<{part_of}>/<{part_of}>)) ?m . ?m a <{model}> ."
    )
    # A direct membership edge outranks both other answers where it exists: one hop, on
    # every concept, needing neither named graphs nor a complete folder chain. Probed by
    # published IRI rather than through a role, because the default lens does not bind it
    # - it did not exist when that profile was written.
    # `arch:` comes from the lens's own prefix block, so this stays a statement about
    # the published vocabulary rather than a literal IRI pasted into the probe.
    #
    # Both spellings, because this runs against a dataset of unknown vintage. core 0.4.0
    # renamed the predicate to arch:inModel and deprecated arch:partOfModel; probing only
    # the current one would report "co-location only" for every graph an earlier converter
    # produced, and only the old one would do the same for every graph produced since.
    # Which was found is reported, so the recommendation names the vocabulary the dataset
    # actually uses rather than the one this tool prefers. See core DD-30.
    membership_edge = next(
        (
            spelling for spelling in ("arch:inModel", "arch:partOfModel")
            if scoped(f"?c {spelling} ?m")
        ),
        None,
    )
    if membership_edge is not None:
        observations.append(Observation(
            "membership", membership_edge,
            "'direct-predicate' - one hop, better than both other modes",
        ))
    else:
        observations.append(Observation(
            "membership", "folder chain walks" if folder_walk else "co-location only",
            "'bounded-folder-tree' possible, if it holds for EVERY notation"
            if folder_walk else "keep 'same-graph-colocation'",
        ))
    return tuple(observations)


def recommend_profile(observations: Sequence[Observation]) -> Recommendation:
    """Pick a starting profile from measured shape. Recommend, never apply.

    Ranked by the decision that matters most first: without named graphs nothing else
    changes the answer, and an authored store is a different kind of dataset from converter
    output regardless of which flags the converter ran with.
    """
    seen = {obs.subject: obs.value for obs in observations}

    def present(subject: str) -> bool:
        return seen.get(subject, "absent") not in {"absent", "0"}

    reasons: list[str] = []
    if seen.get("named graphs") in {None, "0"}:
        reasons.append(
            "no named graphs, so every scoped query would return nothing under a "
            "graph-scoped profile"
        )
        profile = "examples/flattened-turtle"
    elif present("validation graph") and present("reconciliation graph"):
        # Both, because `curated-store` claims both - and one claim too many is an ERROR
        # from `verify`, not a warning. Recommending a profile the next command then
        # refuses is worse than recommending a plainer one: over-claiming makes templates
        # run and return nothing, while under-claiming only refuses them with a reason.
        #
        # Observed: a real estate with 4 identity assertions but no reconciliation graph,
        # no loaded report and no arch:conceptOwner was sent to `curated-store`, which
        # then failed verification on two capabilities it claims and the data lacks.
        reasons.append(
            "authored content beyond conversion - a reconciliation graph and a loaded "
            "SHACL report - which no converter emits"
        )
        profile = "examples/curated-store"
    elif present("reconciliation graph"):
        reasons.append(
            "an authored reconciliation graph, which no converter emits, but no loaded "
            "SHACL report - so the merged profile fits and the curated one would claim a "
            "validation graph this dataset does not have"
        )
        profile = "linked-archi-merged"
    elif seen.get("direct rel triples") == "present":
        reasons.append(
            "direct source-predicate-target triples alongside the qualified form, so the "
            "converter ran with --emit-direct-rel-triples"
        )
        profile = "linked-archi-direct"
    else:
        reasons.append(
            "qualified relationships only and three graphs per model: converter output at "
            "default flags"
        )
        profile = "linked-archi-default"

    if seen.get("graph/views") in {"0", None} and seen.get("named graphs") not in {None, "0"}:
        reasons.append(
            "no views graph, so diagram templates will be refused or empty - expected for "
            "Backstage and LeanIX, a partial export otherwise"
        )
    graphless = seen.get("named graphs") in {None, "0"}
    if seen.get("identity assertions") == "present" and not present("reconciliation graph"):
        # Worth saying rather than acting on: the capability is real and usable, but the
        # profiles that claim it also claim things this dataset may not have. Naming the two
        # roles is enough - it is a three-line child profile.
        reasons.append(
            "identity assertions are present without a reconciliation graph, so the "
            "cross-notation templates are being refused. Extend the recommended profile "
            "with roles.same_as and/or roles.exact_match and set "
            "capabilities.identity_assertions true - the bundled merged profiles would "
            "also claim arch:conceptOwner and a validation graph, which is why they are "
            "not recommended here"
        )
    if not graphless and seen.get("graph/model") in {"0", None}:
        # The inverse of the mismatch that motivated all this, and the one still possible:
        # every bundled profile now describes the layout the converters emit today, so a
        # dataset from an older build is the case that needs overriding. Said here because
        # `verify` will report it as an error and this is where a reader finds out why.
        reasons.append(
            "no graph/model, so this dataset predates the layout the bundled profiles "
            "describe - they read model-level facts from graph/model and membership from "
            "arch:inModel. Either re-convert it, or extend the profile with "
            "graphs.roles.model: graph/semantic, graphs.descendants: [] and "
            "navigation.model_membership.mode: same-graph-colocation"
        )
    membership = seen.get("membership")
    if membership in {"arch:inModel", "arch:partOfModel"}:
        # Naming the spelling that was actually found, not the one the bundled profile
        # binds. A dataset carrying the deprecated arch:partOfModel still supports
        # 'direct-predicate', but only if roles.part_of_model is overridden to match it -
        # the bundled profile binds arch:inModel and would otherwise return nothing.
        extra = (
            "" if membership == "arch:inModel" else
            " - note this is the predicate core 0.4.0 deprecated, so bind "
            "roles.part_of_model to arch:partOfModel explicitly or re-convert the dataset"
        )
        reasons.append(
            f"membership is a direct {membership} edge, so set "
            "navigation.model_membership.mode to 'direct-predicate' and bind "
            "roles.part_of_model - it needs neither named graphs nor a complete folder "
            f"chain, which is why it supersedes both other modes where it exists{extra}"
        )
    elif seen.get("membership") == "folder chain walks":
        if graphless:
            # Co-location is a statement about named graphs, so without them it cannot be
            # expressed at all and membership templates are refused. Here the folder walk
            # is not an optimisation, it is the only route.
            reasons.append(
                "the folder chain reaches a model, which matters more than usual here: "
                "with no named graphs, co-location membership cannot be expressed and "
                "membership templates are refused, so set "
                "navigation.model_membership.mode to 'bounded-folder-tree' if the chain "
                "is complete for every notation"
            )
        else:
            reasons.append(
                "the folder chain reaches a model for at least one concept, so "
                "'bounded-folder-tree' membership is worth checking - but only declare it "
                "if it holds for every notation in the dataset"
            )
    elif graphless:
        reasons.append(
            "no folder chain and no named graphs, so membership cannot be expressed at "
            "all: templates needing it will be refused with that reason"
        )

    caveats = (
        "A recommendation, not a decision: run `verify` before trusting any answer built "
        "on it.",
        "Probed through the published Linked.Archi vocabulary. A dataset built on a custom "
        "ontology will look emptier than it is - use `derive` with its type mapping or "
        "metamodel instead.",
    )
    return Recommendation(
        profile=profile,
        observations=tuple(observations),
        reasons=tuple(reasons),
        caveats=caveats,
    )


def worst_severity(findings: Iterable[Finding]) -> str:
    severities = {f.severity for f in findings}
    for level in ("error", "warning", "info"):
        if level in severities:
            return level
    return "info"


def fixable(findings: Iterable[Finding]) -> list[Finding]:
    """The findings a generated child profile can correct, in report order."""
    return [finding for finding in findings if finding.fix is not None]


def emit_fix_profile(profile: Profile, findings: Sequence[Finding]) -> str | None:
    """A child profile that keeps the parent and overrides only what the data contradicts.

    Acting on drift used to be an editing exercise performed mid-investigation, which is
    when nobody wants to be editing YAML. `extends` exists precisely so a correction can be
    a three-line file, and this writes that file.

    A **child**, never an edited parent: a bundled profile describes converter output at
    known flags, and editing it in place to match one dataset breaks it for everyone else's.
    Returns ``None`` when there is nothing mechanical to fix.
    """
    fixes = fixable(findings)
    if not fixes:
        return None

    sections: dict[str, dict[str, Any]] = {}
    for finding in fixes:
        section, _, key = finding.fix[0].partition(".")
        sections.setdefault(section, {})[key] = finding.fix[1]

    parent = profile.source_reference()
    lines = [
        "# Generated by `la-profile verify --emit-fix`.",
        "#",
        "# Every value below was OBSERVED in the dataset and contradicts the parent's",
        "# claim. Read them before using this: a capability that turned out true means",
        "# your converter ran with a flag the parent profile does not assume, and a",
        "# capability that turned out false may mean a model failed to load rather than",
        "# that the dataset genuinely lacks it.",
        "#",
        "# Only capability drift is generated. An unused role is left alone, because",
        "# nulling it would refuse every template that requires it, and a missing named",
        "# graph needs a different layout rather than a key edit.",
        "",
        f"extends: {parent}",
        f"profile: {profile.name}-fitted",
        "version: 1",
        "description: >-",
        f"  {profile.name} with the capability claims this dataset actually supports.",
    ]
    for section in sorted(sections):
        lines.append(f"{section}:")
        for key in sorted(sections[section]):
            value = sections[section][key]
            rendered = "true" if value is True else "false" if value is False else str(value)
            lines.append(f"  {key}: {rendered}")
    return "\n".join(lines) + "\n"


def format_findings(findings: Sequence[Finding], total: int | None = None) -> str:
    """Render findings with a summary that counts what was CHECKED, not what was shown.

    ``total`` matters because the default report hides `info` findings. Without it the
    summary counted only the visible ones, so a clean run against a real estate announced
    "4 check(s)" when it had in fact checked 64 - reading as though verification had barely
    looked at the dataset. Observed on a 1.4M-quad graph.
    """
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    checked = len(findings) if total is None else total
    body = "\n".join(str(f) for f in findings)
    summary = f"{checked} check(s): {errors} error(s), {warnings} warning(s)"
    hidden = checked - len(findings)
    if hidden > 0:
        summary += f", {hidden} confirmed (--all to show)"
    return f"{body}\n\n{summary}"
