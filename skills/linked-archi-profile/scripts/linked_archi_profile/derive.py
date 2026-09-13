"""Derive a draft profile from artifacts that already exist.

Adapting this package to a custom ontology should not mean editing templates. It
means producing a profile, and a profile can largely be derived from two things
the deployment already has:

**The converter's ``--type-mapping`` YAML.** The file that told the converter to
emit ``cp:Microservice`` instead of ``am:ApplicationComponent`` is the same
information a query needs to find it again. Deriving from it closes the loop: one
file configures both ends, so the graph and the queries cannot disagree.

**The ``arch:Metamodel`` manifest.** The published extension mechanism. A manifest
names its ontology, shapes, viewpoints and taxonomy through
``arch:modelConcepts``, ``arch:formalRules``, ``arch:architectureViewpoints`` and
``arch:conceptClassification``, which is exactly the set a profile needs.

What comes out is a **draft**. Two things cannot be derived and are reported as
notes rather than guessed:

* whether a term is actually *present* in a dataset - only ``profile verify``
  against real data can say, which is why the derive step ends by telling you to
  run it;
* whether an optional role such as ownership or lifecycle is populated, since a
  mapping declares what *may* be emitted, not what was.

Guessing either is how the packages this one replaces ended up describing datasets
that did not exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - environment problem
    raise ModuleNotFoundError("Deriving profiles needs PyYAML:  pip install PyYAML") from exc

CORE_NS = "https://meta.linked.archi/core#"

#: ``--type-mapping`` ``vocab:`` keys that rebind a core term, mapped to the profile
#: role they correspond to. A deployment that remaps ``arch:Element`` has changed
#: what "element" means in its graph, and the profile has to follow.
VOCAB_TO_ROLE: dict[str, str] = {
    "arch:ModelConcept": "concept_class",
    "arch:Element": "element_class",
    "arch:QualifiedRelationship": "relationship_class",
    "arch:Model": "model_class",
    "arch:View": "view_class",
    "arch:Diagram": "diagram_class",
    "arch:Folder": "folder_class",
    "arch:source": "rel_source",
    "arch:target": "rel_target",
    "arch:hasQualifiedRelationship": "has_qualified_rel",
}

#: Manifest properties worth recording, and what they contribute to a profile.
MANIFEST_PROPERTIES: dict[str, str] = {
    "modelConcepts": "ontology",
    "formalRules": "shapes",
    "architectureViewpoints": "viewpoints",
    "conceptClassification": "taxonomy",
    "referenceData": "reference data",
    "derivationRules": "derivation rules",
    "crossLanguageMappings": "cross mappings",
    "notationSet": "notation set",
}

_PREFIX_LINE = re.compile(
    r"^\s*@prefix\s+([A-Za-z][\w.-]*)?:\s*<([^>]+)>\s*\.", re.MULTILINE
)


class DeriveError(ValueError):
    """A source artifact could not be read, or contains nothing usable."""


@dataclass
class Derivation:
    """A draft profile plus everything the deriver could not decide for you."""

    name: str
    extends: str = "linked-archi-default.yaml"
    description: str = ""
    base_iri: str = ""
    namespaces: dict[str, str] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    notations: dict[str, dict] = field(default_factory=dict)
    taxonomies: list[dict] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_yaml(self) -> str:
        body: dict[str, Any] = {"extends": self.extends, "profile": self.name, "version": 1}
        if self.description:
            body["description"] = self.description
        if self.base_iri:
            body["base_iri"] = self.base_iri
        for key in ("namespaces", "roles", "capabilities", "notations", "taxonomies"):
            value = getattr(self, key)
            if value:
                body[key] = value

        dumped = yaml.safe_dump(body, sort_keys=False, default_flow_style=False, width=100)

        header = [
            f"# Draft profile {self.name!r}, derived - not authored.",
            "#",
            "# Derived from:",
        ]
        header += [f"#   {source}" for source in self.sources]
        header += [
            "#",
            "# A derivation states what the source artifacts declare. It cannot state what",
            "# a dataset actually contains, so nothing here is trustworthy until verified.",
            "# From the linked-archi-profile skill directory, run:",
            "#",
            "#   python3 scripts/la-profile verify --profile <this file> --data <your>.trig",
            "#",
        ]
        if self.notes:
            header += ["# Check these before relying on it:", "#"]
            header += [f"#   - {note}" for note in self.notes]
            header += ["#"]
        return "\n".join(header) + "\n" + dumped

    def write(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_yaml(), encoding="utf-8")
        return target


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------


@dataclass
class TypeMappingInfo:
    namespaces: dict[str, str] = field(default_factory=dict)
    vocab: dict[str, str] = field(default_factory=dict)
    element_classes: dict[str, str] = field(default_factory=dict)
    relationship_classes: dict[str, str] = field(default_factory=dict)
    direct_predicates: dict[str, str] = field(default_factory=dict)
    qualified_predicates: dict[str, str] = field(default_factory=dict)
    metadata_predicates: dict[str, str] = field(default_factory=dict)
    object_properties: list[str] = field(default_factory=list)
    spec_relations: dict[str, str] = field(default_factory=dict)
    spec_literals: list[str] = field(default_factory=list)


_MAPPING_SECTIONS = {
    "namespaces": "namespaces",
    "vocab": "vocab",
    "elements": "element_classes",
    "relationships": "relationship_classes",
    "predicates": "direct_predicates",
    "qualifiedPredicates": "qualified_predicates",
    "metadata-predicates": "metadata_predicates",
    "spec-relations": "spec_relations",
}
_LIST_SECTIONS = {
    "object-properties": "object_properties",
    "spec-literals": "spec_literals",
}


def _mapping_section(
    document: Mapping[str, Any], section: str, source: Path
) -> dict[str, str]:
    if section not in document:
        return {}
    value = document[section]
    if not isinstance(value, Mapping):
        raise DeriveError(f"{source.name}: {section} must be a mapping")
    if any(
        not isinstance(key, str)
        or not key.strip()
        or key != key.strip()
        or not isinstance(item, str)
        or not item.strip()
        or item != item.strip()
        for key, item in value.items()
    ):
        raise DeriveError(
            f"{source.name}: {section} must map stripped, non-empty strings to stripped, non-empty strings"
        )
    return dict(value)


def _list_section(
    document: Mapping[str, Any], section: str, source: Path
) -> list[str]:
    if section not in document:
        return []
    value = document[section]
    if not isinstance(value, list) or any(
        not isinstance(item, str)
        or not item.strip()
        or item != item.strip()
        for item in value
    ):
        raise DeriveError(
            f"{source.name}: {section} must be a list of stripped, non-empty strings"
        )
    return list(value)


def read_type_mapping(path: Path | str) -> TypeMappingInfo:
    """Read a converter ``--type-mapping`` YAML.

    Accepts the full superset of sections the converters define, and ignores any it
    does not use, so a mapping written for one notation can be read here without
    editing.
    """
    source = Path(path)
    if not source.is_file():
        raise DeriveError(f"Type mapping not found: {source}")
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DeriveError(f"{source.name} is not valid YAML: {exc}") from exc
    if document is None:
        document = {}
    if not isinstance(document, Mapping):
        raise DeriveError(f"{source.name} must contain a YAML mapping")

    values: dict[str, Any] = {}
    for section, field_name in _MAPPING_SECTIONS.items():
        values[field_name] = _mapping_section(document, section, source)
    for section, field_name in _LIST_SECTIONS.items():
        values[field_name] = _list_section(document, section, source)
    return TypeMappingInfo(**values)


# ---------------------------------------------------------------------------
# Metamodel manifest
# ---------------------------------------------------------------------------


@dataclass
class MetamodelInfo:
    iri: str = ""
    label: str = ""
    prefix: str = ""
    namespaces: dict[str, str] = field(default_factory=dict)
    assets: dict[str, list[str]] = field(default_factory=dict)


def read_metamodel(path: Path | str) -> MetamodelInfo:
    """Read an ``arch:Metamodel`` manifest in Turtle.

    Two passes for two reasons. The graph is parsed properly, because the manifest's
    structure is what matters. Prefixes are read with a regex over the ``@prefix``
    lines, because a parser discards them - and the prefixes are worth keeping, since
    they are what the metamodel's author chose to call things.
    """
    source = Path(path)
    if not source.is_file():
        raise DeriveError(f"Metamodel manifest not found: {source}")
    text = source.read_text(encoding="utf-8")

    namespaces = {
        prefix: iri for prefix, iri in _PREFIX_LINE.findall(text) if prefix
    }

    try:
        from pyoxigraph import RdfFormat, Store
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise DeriveError(
            "Reading a metamodel manifest needs pyoxigraph:  pip install pyoxigraph"
        ) from exc

    store = Store()
    try:
        store.bulk_load(text.encode("utf-8"), RdfFormat.TURTLE)
    except (ValueError, SyntaxError) as exc:
        raise DeriveError(f"Could not parse {source.name} as Turtle: {exc}") from exc

    rows = list(
        store.query(
            f"""
            SELECT ?m ?label ?p ?asset WHERE {{
              ?m a <{CORE_NS}Metamodel> .
              OPTIONAL {{ ?m <http://www.w3.org/2004/02/skos/core#prefLabel> ?label }}
              OPTIONAL {{ ?m ?p ?asset . FILTER(STRSTARTS(STR(?p), "{CORE_NS}")) }}
            }}
            """
        )
    )
    if not rows:
        raise DeriveError(
            f"{source.name} declares no arch:Metamodel. A manifest is an instance "
            f"typed <{CORE_NS}Metamodel>; see linked-archi-meta/examples/custom-metamodel/."
        )

    info = MetamodelInfo(namespaces=namespaces)
    for row in rows:
        if not info.iri and row["m"] is not None:
            info.iri = row["m"].value
        if not info.label and row["label"] is not None:
            info.label = row["label"].value
        predicate, asset = row["p"], row["asset"]
        if predicate is None or asset is None:
            continue
        local = predicate.value[len(CORE_NS):]
        if local in MANIFEST_PROPERTIES:
            info.assets.setdefault(local, [])
            if asset.value not in info.assets[local]:
                info.assets[local].append(asset.value)

    for prefix, iri in namespaces.items():
        if iri == info.iri or iri.rstrip("#") == info.iri.rstrip("#"):
            info.prefix = prefix
            break
    return info


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def _prefix_for(iri: str, namespaces: Mapping[str, str]) -> str | None:
    """The declared prefix whose namespace ``iri`` sits in, if any."""
    for prefix, namespace in namespaces.items():
        if iri.startswith(namespace) and iri != namespace:
            return prefix
    return None


def _prefix_for_graph(iri: str, namespaces: Mapping[str, str]) -> str | None:
    """The prefix naming a graph IRI, tolerating a missing trailing separator.

    A SKOS scheme is conventionally written ``.../tax`` while the prefix that
    covers its concepts is declared ``.../tax#``. Comparing them as strings finds
    nothing, so the terminating ``#`` or ``/`` is ignored on both sides.
    """
    target = iri.rstrip("#/")
    for prefix, namespace in namespaces.items():
        if namespace.rstrip("#/") == target:
            return prefix
    return _prefix_for(iri, namespaces)


def _curie(iri: str, namespaces: Mapping[str, str]) -> str:
    prefix = _prefix_for(iri, namespaces)
    if not prefix:
        return iri
    namespace = namespaces[prefix]
    return f"{prefix}:{iri[len(namespace):]}"


def derive_profile(
    name: str,
    *,
    base_iri: str = "",
    type_mapping: Path | str | None = None,
    metamodel: Path | str | None = None,
    notation: str | None = None,
    extends: str = "linked-archi-default.yaml",
) -> Derivation:
    """Build a draft profile from a type mapping and/or a metamodel manifest."""
    if not type_mapping and not metamodel:
        raise DeriveError(
            "Nothing to derive from. Pass --type-mapping, --metamodel, or both.\n"
            "With neither, copy the profile skill's "
            "assets/profiles/linked-archi-default.yaml and edit it - see ADAPTING.md."
        )

    result = Derivation(name=name, extends=extends, base_iri=base_iri)
    combined: dict[str, str] = {}

    if metamodel:
        info = read_metamodel(metamodel)
        result.sources.append(f"metamodel manifest: {Path(metamodel).name}")
        result.description = (
            f"Derived from the {info.label or info.iri} metamodel manifest."
        )

        # Only namespaces the manifest actually points at, so a boilerplate prefix
        # block does not become 20 unused declarations in the profile.
        referenced = {iri for iris in info.assets.values() for iri in iris}
        referenced.add(info.iri)
        for prefix, namespace in info.namespaces.items():
            if namespace.startswith(("http://www.w3.org/", "http://purl.org/")):
                continue
            if any(iri.startswith(namespace) or iri == namespace for iri in referenced):
                combined[prefix] = namespace
                continue
            if info.prefix and prefix.startswith(info.prefix[:2]):
                combined[prefix] = namespace

        for scheme in info.assets.get("conceptClassification", []):
            trimmed = scheme.rstrip("#")
            result.taxonomies.append({
                "scheme": trimmed,
                "prefix": _prefix_for_graph(scheme, info.namespaces) or "tax",
                "label": f"{info.label or name} classification",
            })

        slug = notation or (info.prefix or name).replace("mm", "") or name
        entry: dict[str, Any] = {
            "label": info.label or name,
            "metamodel": info.iri,
            "native_id": "skos:notation",
        }
        ontologies = info.assets.get("modelConcepts", [])
        if ontologies:
            onto_prefix = _prefix_for_graph(ontologies[0], info.namespaces)
            if onto_prefix:
                entry["namespace"] = onto_prefix
        result.notations[slug] = entry

        for local, description in MANIFEST_PROPERTIES.items():
            if local in info.assets and local != "conceptClassification":
                result.notes.append(
                    f"manifest declares {description}: "
                    + ", ".join(info.assets[local])
                )
        if "formalRules" in info.assets:
            result.notes.append(
                "pass the shapes graph above to the validate skill; it is not "
                "fetched automatically"
            )

    if type_mapping:
        mapping = read_type_mapping(type_mapping)
        result.sources.append(f"converter type mapping: {Path(type_mapping).name}")
        combined.update(mapping.namespaces)
        if not result.description:
            result.description = (
                f"Derived from the converter type mapping {Path(type_mapping).name}."
            )

        # A remapped core term changes what a role means, so it must be rebound.
        for key, iri in mapping.vocab.items():
            role = VOCAB_TO_ROLE.get(key)
            if role:
                result.roles[role] = _curie(iri, combined) if combined else iri
            else:
                result.notes.append(
                    f"vocab remaps {key} to {iri}, which no role corresponds to. "
                    "Add a custom role if a template needs it."
                )

        # Custom classes and predicates get namespaces recorded but no roles: a
        # class is reachable through rdf:type without a role, and inventing a role
        # per class would put the ontology in the profile twice.
        for iri in list(mapping.element_classes.values()) + list(
            mapping.relationship_classes.values()
        ):
            namespace = re.sub(r"[^#/]+$", "", iri)
            if namespace and namespace not in combined.values():
                suggested = _suggest_prefix(namespace, combined)
                combined[suggested] = namespace
                result.notes.append(
                    f"mapping uses namespace {namespace} with no prefix declared; "
                    f"named it {suggested!r} - rename it if you prefer"
                )

        if mapping.direct_predicates:
            result.notes.append(
                f"mapping declares {len(mapping.direct_predicates)} direct "
                "predicate(s). These are emitted only with "
                "--emit-direct-rel-triples, so capabilities.direct_rel_triples is "
                "NOT set true here. Verify against the dataset, then set it."
            )
        if mapping.object_properties:
            result.notes.append(
                "mapping declares object-properties "
                f"({', '.join(mapping.object_properties[:5])}): those values reach "
                "the graph as IRIs, not literals, so compare them to terms and not "
                "to strings."
            )
        if mapping.spec_relations or mapping.spec_literals:
            result.notes.append(
                "mapping declares custom Backstage spec fields; the relations become "
                "edges and the literals become properties"
            )

    result.namespaces = dict(sorted(combined.items()))
    result.notes.append(
        "optional roles (owner, element_lifecycle, same_as, exact_match) are "
        "inherited from the base profile. A mapping says what may be emitted, not "
        "what was - confirm with profile verify before binding them."
    )
    return result


def _suggest_prefix(namespace: str, taken: Mapping[str, str]) -> str:
    """A short, unused prefix for a namespace nobody named."""
    words = re.findall(r"[a-z]+", namespace.lower())
    skip = {"http", "https", "www", "com", "org", "net", "onto", "ontology", "core"}
    candidates = [w for w in words if w not in skip and len(w) > 2]
    stem = (candidates[-1] if candidates else "ns")[:6]
    if stem not in taken:
        return stem
    for index in range(2, 50):
        if f"{stem}{index}" not in taken:
            return f"{stem}{index}"
    return "ns"
