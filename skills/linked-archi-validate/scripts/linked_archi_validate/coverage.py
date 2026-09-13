"""How much of the shape graph actually applied to the data.

The verdict on its own is close to meaningless. A shape graph whose target classes match
nothing in the data reports `sh:conforms true` while checking nothing, and the usual cause
is mundane: shapes and data in different namespaces, or a file of ontology axioms passed
where a shapes file was meant.

This module measures what can actually be measured - which target classes the data has
instances of - and is deliberately explicit about what it does *not* measure. There is no
count of individual constraints evaluated here, because nothing in the pipeline produces
one, and inventing a number would be worse than admitting the gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rdf import require_rdflib

SH = "http://www.w3.org/ns/shacl#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_CLASS = "http://www.w3.org/2000/01/rdf-schema#Class"
RDFS_SUBCLASS = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
OWL_CLASS = "http://www.w3.org/2002/07/owl#Class"

#: Ways a shape can select focus nodes other than by class. Counted separately so that
#: "no class targets" is never reported as "no targets at all".
OTHER_TARGET_KINDS = {
    "targetNode": f"{SH}targetNode",
    "targetSubjectsOf": f"{SH}targetSubjectsOf",
    "targetObjectsOf": f"{SH}targetObjectsOf",
    "target": f"{SH}target",
}


@dataclass
class Coverage:
    """Target-class coverage, and the honest caveats around it."""

    declared: int
    matched: int
    unmatched_classes: list[str] = field(default_factory=list)
    other_target_kinds: dict[str, int] = field(default_factory=dict)
    shape_count: int = 0

    @property
    def vacuous(self) -> bool:
        """Target classes were declared, and not one of them matched the data."""
        return self.declared > 0 and self.matched == 0

    @property
    def no_class_targets(self) -> bool:
        return self.declared == 0

    @property
    def has_other_targets(self) -> bool:
        return any(self.other_target_kinds.values())

    @property
    def checked_nothing(self) -> bool:
        """No focus node could have been selected, so the verdict is meaningless.

        Kept distinct from conformance on purpose. A run that checked nothing must not
        exit 0, because every CI step and every reader treats 0 as a pass - which is the
        precise way a namespace mismatch becomes a clean bill of health.
        """
        return self.vacuous or (self.no_class_targets and not self.has_other_targets)

    def as_dict(self) -> dict[str, Any]:
        return {
            "declared_target_classes": self.declared,
            "matched_target_classes": self.matched,
            "unmatched_target_classes": self.unmatched_classes,
            "other_target_kinds": dict(self.other_target_kinds),
            "shape_count": self.shape_count,
            "vacuous": self.vacuous,
            "no_class_targets": self.no_class_targets,
            # Stated, not omitted: an absent metric that a reader might assume exists is
            # how "conforms" gets over-read.
            "constraints_evaluated": None,
            "constraints_skipped": None,
        }

    def notes(self) -> list[str]:
        notes: list[str] = []
        if self.vacuous:
            notes.append(
                f"VACUOUS: {self.declared} target class(es) declared and none matched the "
                "data, so no constraint was actually checked. This is not a pass. The "
                "usual cause is shapes and data in different namespaces."
            )
        elif self.no_class_targets and not self.has_other_targets:
            notes.append(
                "the shape graph declares no sh:targetClass and no other target, so "
                "nothing selected a focus node. Check that --shapes names a shapes file "
                "rather than an ontology."
            )
        elif self.no_class_targets and self.has_other_targets:
            kinds = ", ".join(
                f"{name}={count}" for name, count in sorted(self.other_target_kinds.items()) if count
            )
            notes.append(
                "no sh:targetClass is declared, so class coverage cannot be computed. "
                f"Other targets are present ({kinds}); coverage is unknown rather than zero."
            )
        elif self.matched < self.declared:
            notes.append(
                f"{self.declared - self.matched} of {self.declared} target class(es) matched "
                "nothing in this data. Expected when validating one notation inside a "
                "merged graph; report coverage per run rather than summed."
            )
        return notes


def _target_classes(shapes: Any, rdflib: Any) -> set[Any]:
    """Explicit `sh:targetClass`, plus SHACL's implicit class targets.

    A node that is both a shape and a class targets its own instances. Missing that would
    understate coverage and make a sound shape set look vacuous.
    """
    URIRef = rdflib.URIRef
    classes = set(shapes.objects(None, URIRef(f"{SH}targetClass")))
    for shape_type in (f"{SH}NodeShape", f"{SH}PropertyShape"):
        for shape in shapes.subjects(URIRef(RDF_TYPE), URIRef(shape_type)):
            types = set(shapes.objects(shape, URIRef(RDF_TYPE)))
            if URIRef(RDFS_CLASS) in types or URIRef(OWL_CLASS) in types:
                classes.add(shape)
    return {term for term in classes if isinstance(term, rdflib.URIRef)}


def measure(data: Any, shapes: Any) -> Coverage:
    """Compare the shape graph's targets against what the data contains."""
    rdflib = require_rdflib()
    URIRef = rdflib.URIRef

    declared = _target_classes(shapes, rdflib)

    # Subclass-aware, so a shape targeting a superclass still counts as matched when the
    # data only carries specialisations - which is how the notation ontologies are built.
    subclasses: dict[Any, set[Any]] = {}
    for child, parent in data.subject_objects(URIRef(RDFS_SUBCLASS)):
        subclasses.setdefault(parent, set()).add(child)

    def instantiated(target: Any) -> bool:
        seen: set[Any] = set()
        queue = [target]
        while queue:
            current = queue.pop()
            if current in seen:
                continue
            seen.add(current)
            if (None, URIRef(RDF_TYPE), current) in data:
                return True
            queue.extend(subclasses.get(current, frozenset()) - seen)
        return False

    matched = {target for target in declared if instantiated(target)}

    other: dict[str, int] = {}
    for name, predicate in OTHER_TARGET_KINDS.items():
        other[name] = len(set(shapes.subject_objects(URIRef(predicate))))

    shape_count = len(
        set(shapes.subjects(URIRef(RDF_TYPE), URIRef(f"{SH}NodeShape")))
        | set(shapes.subjects(URIRef(RDF_TYPE), URIRef(f"{SH}PropertyShape")))
    )

    return Coverage(
        declared=len(declared),
        matched=len(matched),
        unmatched_classes=sorted(str(term) for term in declared - matched),
        other_target_kinds=other,
        shape_count=shape_count,
    )
