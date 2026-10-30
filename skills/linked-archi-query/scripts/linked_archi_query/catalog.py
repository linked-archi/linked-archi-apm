"""The template catalogue, and the capability gating that makes it honest.

The catalogue is machine-readable and carries three things per template: typed parameter
declarations, a prose header saying what the query answers and - more usefully - what it does
*not* prove, and the rule that a template without a test case fails the build.

The load-bearing field is :attr:`TemplateEntry.requires`. A template declares the roles,
graph roles and capabilities it depends on, and :meth:`TemplateEntry.check`
compares that against a profile *before* the query is rendered. A template whose
dependency is absent is refused with a reason and an alternative, instead of
running and returning an empty result that reads as "no such thing exists".

That is the single behaviour this package exists to fix. Both predecessors could
emit a query that ran, returned nothing, and was wrong - because the term was
spelled differently, or because the relationship form it assumed is not emitted
by default.

An entry may also be a model question from a published question set, the source of truth
for what it asks (see ``questions``). Where a question and a template share a name they are
one question with two implementations: the question runs where the dataset fits it - read
as one graph, with what its query reads present - and the template elsewhere. See
:meth:`TemplateEntry.choose`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .contract import _is_absolute_iri
from .questions import (
    Question,
    QuestionError,
    catalogue_parameters,
    load_index,
    read_set,
)

#: Templates are committed assets owned by this skill.
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "assets" / "templates"
CATALOG_PATH = TEMPLATE_DIR / "catalog.json"

#: Stages, in the order an investigation moves through them. Used for listing and
#: for the routing tables in the skills.
STAGES = (
    "orientation",
    "resolution",
    "discovery",
    "analysis",
    "enrichment",
    "quality",
    "views",
)

#: ``iri_path`` renders an alternation for a SPARQL property path (``<a>|<b>``).
#: It exists so a transitive traversal can be bounded by an explicit predicate
#: set. A property path cannot be parameterised through ``VALUES``, so without it
#: the only way to write transitive traversal is a wildcard path over every
#: predicate in the graph - which is unbounded exploration wearing a disguise.
PARAM_TYPES = frozenset({"iri", "iri_list", "iri_path", "string", "integer"})


def _valid_iri_sequence(value: Any) -> bool:
    if isinstance(value, str):
        items = [item for item in re.split(r"[,\s]+", value) if item]
    elif isinstance(value, list):
        items = value
    else:
        return False
    return bool(items) and all(
        isinstance(item, str)
        and item == item.strip()
        and _is_absolute_iri(item)
        for item in items
    )


class CatalogError(ValueError):
    """The catalogue is malformed, or a template is not in it."""


@dataclass(frozen=True)
class Requirement:
    """What a template needs from a profile in order to mean anything.

    ``roles``        role names that must be bound (not null).
    ``graph_roles``  named-graph roles the template scopes to.
    ``capabilities`` capability name -> required value. ``True`` means the
                     dataset must carry it; ``'partial'`` is accepted with a
                     warning, because a thin result may reflect coverage rather
                     than absence.
    """

    roles: tuple[str, ...] = ()
    graph_roles: tuple[str, ...] = ()
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    #: Set by a template using ``{{MEMBERSHIP:...}}``. Not every profile can express
    #: "belongs to this model": co-location needs named graphs to mean anything, and
    #: without them the pattern degenerates into a join against every model in the
    #: dataset - which answers, wrongly, rather than refusing.
    membership: bool = False

    @classmethod
    def from_json(cls, raw: Mapping[str, Any] | None) -> "Requirement":
        if raw is None:
            raw = {}
        if not isinstance(raw, Mapping):
            raise CatalogError("requires must be a mapping")
        if any(not isinstance(key, str) for key in raw):
            raise CatalogError("requires keys must be strings")
        unknown = set(raw) - {"roles", "graph_roles", "capabilities", "membership"}
        if unknown:
            raise CatalogError(
                f"Unknown keys in requires: {', '.join(sorted(unknown))}"
            )

        lists: dict[str, tuple[str, ...]] = {}
        for field_name in ("roles", "graph_roles"):
            value = raw.get(field_name, [])
            if not isinstance(value, list) or any(
                not isinstance(item, str)
                or not item.strip()
                or item != item.strip()
                for item in value
            ):
                raise CatalogError(
                    f"requires.{field_name} must be a list of stripped, non-empty strings"
                )
            lists[field_name] = tuple(value)

        capabilities = raw.get("capabilities", {})
        if not isinstance(capabilities, Mapping) or any(
            not isinstance(key, str)
            or not key.strip()
            or key != key.strip()
            or not (
                isinstance(value, bool)
                or value == "partial"
                or (
                    key == "label_language"
                    and isinstance(value, str)
                    and bool(value.strip())
                    and value == value.strip()
                )
            )
            for key, value in (
                capabilities.items() if isinstance(capabilities, Mapping) else ()
            )
        ):
            raise CatalogError(
                "requires.capabilities must map non-empty names to booleans, "
                "'partial', or a label_language string"
            )

        membership = raw.get("membership", False)
        if not isinstance(membership, bool):
            raise CatalogError("requires.membership must be true or false")

        return cls(
            roles=lists["roles"],
            graph_roles=lists["graph_roles"],
            capabilities=dict(capabilities),
            membership=membership,
        )


@dataclass(frozen=True)
class Verdict:
    """Whether a template can run against a profile, and what to say if not."""

    ok: bool
    unmet: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class TemplateEntry:
    """One catalogued template."""

    name: str
    file: str
    stage: str
    purpose: str
    answers: str = ""
    does_not_prove: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)
    requires: Requirement = field(default_factory=Requirement)
    alternatives: tuple[str, ...] = ()
    notation: str | None = None
    #: The notation vocabulary this template is written against, as a namespace IRI.
    #:
    #: What turns ``notation`` from a label into a gate. A notation template names that
    #: notation's terms directly - there is no role indirection for `bpmn:SequenceFlow` -
    #: so against a dataset without that notation it does not fail, it returns nothing,
    #: which is indistinguishable from "this notation has none of those".
    #:
    #: An IRI rather than the slug above, because the slug is a directory name and a
    #: profile's own slug for the same notation may differ (ArchiMate's is ``model``).
    #: See ResolvedProfile.notation_for_namespace.
    notation_namespace: str | None = None
    #: A caveat that travels with every RESULT, not just with the catalogue entry.
    #:
    #: Distinct from ``does_not_prove``, which helps choose a template. This is for a
    #: template whose rows are dangerous to quote without it - `core/label-collisions`
    #: returns identity *candidates*, and a table of them read as assertions is exactly
    #: the mistake the package forbids elsewhere. Opt-in, deliberately: attaching one to
    #: all 34 templates would train a reader to skip the line, and the profile caveats
    #: that matter would go with it.
    caveat: str = ""
    template_dir: Path = TEMPLATE_DIR
    #: The model question of this name, when a question set has one. With ``file`` empty
    #: the entry is a question only, and its other fields are read from it.
    question: Question | None = None

    @property
    def has_template(self) -> bool:
        return bool(self.file)

    @property
    def implementations(self) -> tuple[str, ...]:
        return (("question",) if self.question else ()) + (("template",) if self.file else ())

    @property
    def question_parameters(self) -> dict[str, dict[str, Any]]:
        """The question's parameters under their catalogue names, and its LIMIT."""
        if self.question is None:
            return {}
        return catalogue_parameters(self.question)

    @property
    def path(self) -> Path:
        if not self.file:
            raise CatalogError(f"{self.name!r} is a model question; it has no template file")
        root = self.template_dir.resolve()
        path = (self.template_dir / self.file).resolve()
        if not path.is_relative_to(root):
            raise CatalogError(
                f"Template {self.name!r} file escapes its catalogue directory: {self.file}"
            )
        return path

    def text(self) -> str:
        if not self.file and self.question is not None:
            return self.question.text
        if not self.path.is_file():
            raise CatalogError(
                f"Template {self.name!r} is catalogued as {self.file} but that file "
                "does not exist"
            )
        try:
            return self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CatalogError(f"Could not read template {self.name!r}: {exc}") from exc

    def check(self, profile: ResolvedProfile, transport: str | None = None) -> Verdict:
        """Whether ``profile`` supports this entry: the verdict of what would run.

        ``transport`` is ``local``, ``endpoint``, or ``None`` when no dataset is in view (a
        listing). It matters to a model question only, which reads the dataset as one graph.
        """
        return self.choose(profile, transport)[1]

    def choose(
        self,
        profile: ResolvedProfile,
        transport: str | None = None,
        supplied: Sequence[str] = (),
    ) -> tuple[str | None, Verdict]:
        """Which implementation runs - ``question``, ``template`` or ``None`` - and its verdict.

        The question when the dataset fits it, else the template; refused only when neither
        fits, with both sets of reasons. ``supplied`` names the parameters given: one only
        the other implementation takes makes this one unfit, rather than silently dropped.
        """
        verdicts: dict[str, Verdict] = {}
        if (
            transport is None
            and self.question is not None
            and self.file
            and profile.graphs.named_graphs
        ):
            # Nothing will run it here - `query render` - so prefer the SPARQL that runs as
            # rendered on this layout. The question needs the dataset read as one graph,
            # which `query run` arranges and a pasted query does not.
            template = self.check_template(profile, supplied)
            if template.ok:
                return "template", template
        if self.question is not None:
            verdicts["question"] = self.check_question(profile, transport, supplied)
            if verdicts["question"].ok:
                return "question", verdicts["question"]
        if self.file:
            verdicts["template"] = self.check_template(profile, supplied)
            if verdicts["template"].ok:
                return "template", verdicts["template"]
        if len(verdicts) == 1:
            return None, next(iter(verdicts.values()))
        return None, Verdict(
            ok=False,
            unmet=tuple(f"as a model question: {reason}" for reason in verdicts["question"].unmet)
            + tuple(f"as a template: {reason}" for reason in verdicts["template"].unmet),
        )

    def check_question(
        self,
        profile: ResolvedProfile,
        transport: str | None = None,
        supplied: Sequence[str] = (),
    ) -> Verdict:
        """Whether the model question can be asked on this dataset.

        What its query reads is gated as a template's ``requires`` is; the metamodel it needs
        is checked when it runs, against the data. Beyond that a question needs the dataset
        read as ONE graph: local data is read so on request, an endpoint only when the
        profile says its default graph is the union of its graphs.
        """
        question = self.question
        if question is None:
            return Verdict(ok=False, unmet=(f"{self.name!r} has no model question",))
        unmet: list[str] = []
        warnings: list[str] = []
        _gate_capabilities(
            profile, question.capabilities, unmet, warnings, "model question", QUESTION_REMEDIES
        )
        _gate_notation(
            profile, question.notation, question.notation_namespace, unmet, warnings,
            "model question",
        )
        if profile.graphs.named_graphs and transport == "endpoint":
            if profile.capability("union_default_graph") is not True:
                unmet.append(
                    "a model question reads the dataset as one graph - the model and its "
                    "metamodel together - and this endpoint's default graph is not declared "
                    "to be the union of its graphs (capabilities.union_default_graph in "
                    f"profile {profile.name!r}). Run it on local data, or declare the "
                    "capability if the endpoint's default graph is that union."
                )
        taken = set(self.question_parameters)
        foreign = sorted(set(supplied) - taken)
        if foreign:
            unmet.append(
                "the model question takes no "
                + ", ".join(foreign)
                + f" (it takes: {', '.join(sorted(taken))})"
            )
        return Verdict(ok=not unmet, unmet=tuple(unmet), warnings=tuple(warnings))

    def check_template(self, profile: ResolvedProfile, supplied: Sequence[str] = ()) -> Verdict:
        """Whether ``profile`` supports this template.

        Refusals are phrased for a reader who must decide what to do next, so each
        names the missing thing, why it matters, and where to look.
        """
        unmet: list[str] = []
        warnings: list[str] = []
        if not self.file:
            return Verdict(ok=False, unmet=(f"{self.name!r} has no template",))
        foreign = sorted(set(supplied) - set(self.parameters))
        if foreign:
            unmet.append(
                "the template takes no " + ", ".join(foreign)
                + f" (it takes: {', '.join(sorted(self.parameters)) or 'none'})"
            )

        for role in self.requires.roles:
            if not profile.has_role(role):
                declared = role in profile.roles
                unmet.append(
                    f"role {role!r} is "
                    + (
                        "declared absent in this dataset"
                        if declared
                        else f"not declared by profile {profile.name!r}"
                    )
                    + f". Bind it in the profile if the dataset does carry it."
                )

        for role in self.requires.graph_roles:
            if not profile.graphs.named_graphs:
                warnings.append(
                    f"profile has no named graphs, so the {role!r} scope cannot be "
                    "applied. The query will run unscoped, which mixes semantic, "
                    "view and provenance facts in one result."
                )
            elif not profile.graphs.has_role(role):
                available = ", ".join(profile.graphs.role_names()) or "none"
                unmet.append(
                    f"graph role {role!r} is not present in profile "
                    f"{profile.name!r} (has: {available})"
                )

        _gate_capabilities(profile, self.requires.capabilities, unmet, warnings)

        if self.requires.membership:
            gap = profile.membership_gap()
            if gap:
                unmet.append(gap)

        _gate_notation(profile, self.notation, self.notation_namespace, unmet, warnings)

        return Verdict(ok=not unmet, unmet=tuple(unmet), warnings=tuple(warnings))

    def summary_line(self) -> str:
        tag = f"[{self.notation}]" if self.notation else ""
        # Q: a model question only; Q+T: a question with a template for other layouts.
        kind = {("question",): "Q ", ("question", "template"): "Q+T "}.get(self.implementations, "")
        return f"{self.name:38} {self.stage:12} {tag:12} {kind}{self.purpose}"


#: What lifts a model question's capability refusal. A question has no template to name as
#: an alternative where it is the only implementation, so the refusal says how the data
#: comes to carry what it reads.
QUESTION_REMEDIES: Mapping[str, str] = {
    "direct_rel_triples": (
        "The converters write the direct triples unless run with "
        "--no-emit-direct-rel-triples; data that has them is described by a profile "
        "claiming the capability, such as linked-archi-default."
    ),
    "rdf_reifies": (
        "The converters write rdf:reifies with the direct triples; a profile claiming the "
        "capability, such as linked-archi-default, describes data that has it."
    ),
    "part_of_model_edge": (
        "Output of a converter from before arch:inModel lacks it; reconvert the model."
    ),
}


def _gate_capabilities(
    profile: "ResolvedProfile",
    required_capabilities: Mapping[str, Any],
    unmet: list[str],
    warnings: list[str],
    kind: str = "template",
    remedies: Mapping[str, str] | None = None,
) -> None:
    """The profile's capabilities against what a query needs."""
    for capability, required in required_capabilities.items():
        actual = profile.capability(capability)
        if actual == required:
            continue
        if actual == "partial" and required is True:
            warnings.append(
                f"capability {capability!r} is partial: present for some models "
                "and absent for others. A short result may be coverage rather "
                "than absence - check with the orientation templates."
            )
            continue
        remedy = (remedies or {}).get(capability)
        unmet.append(
            f"capability {capability!r} is {actual!r} in profile "
            f"{profile.name!r} but this {kind} needs {required!r}"
            + (f". {remedy}" if remedy else "")
        )


def _gate_notation(
    profile: "ResolvedProfile",
    notation: str | None,
    notation_namespace: str | None,
    unmet: list[str],
    warnings: list[str],
    kind: str = "template",
) -> None:
    """A notation query against the notations the profile declares, and their presence."""
    # A notation template names that notation's own terms, because there is no role
    # indirection for `bpmn:SequenceFlow` or `c4:hasContainer`. Against a dataset
    # without the notation it therefore runs and returns nothing, which reads as "this
    # notation has none of those" rather than "this dataset has no such notation" -
    # and an empty result is the one answer this package refuses to leave ambiguous.
    #
    # The catalogue has carried a `notation` label since the beginning without ever
    # consulting it. Matching is on the vocabulary's namespace IRI rather than that
    # label, because a profile's slug for a notation is its own choice.
    if notation_namespace:
        slug = profile.notation_for_namespace(notation_namespace)
        if slug is None:
            declared = ", ".join(sorted(profile.notations)) or "none"
            unmet.append(
                f"profile {profile.name!r} declares no notation using the vocabulary "
                f"{notation_namespace} that this {notation} {kind} is "
                f"written against (it declares: {declared}). The query would run and "
                "return nothing, which is not the same as an empty answer. Add the "
                "notation to the profile if the dataset does carry it."
            )
        else:
            # Declaring a notation says the profile speaks it. Presence says the data
            # holds a model in it, and only the second decides whether this template
            # can answer. Both are gated here rather than in a `requires` key, because
            # every notation template already names its vocabulary and none of them
            # should have to opt in to being refused against a dataset that lacks it.
            present = profile.notation_present(slug)
            if present is False:
                unmet.append(
                    f"profile {profile.name!r} declares notation {slug!r} but records it "
                    f"as absent from this dataset, so no model this {notation} "
                    f"{kind} asks about is here. Refused rather than answered with no "
                    "rows, which would read as 'none exist'. Confirm with "
                    "core/inventory-summary, and if the notation is in fact loaded, set "
                    f"notations.{slug}.present true - `la-profile verify` reports which "
                    "notations have models here."
                )
            elif present == "partial":
                warnings.append(
                    f"notation {slug!r} is present for some models in this dataset and "
                    "absent for others, so rows here cover part of it. "
                    "core/inventory-summary reports which models carry it."
                )


class Catalog:
    """The set of catalogued templates."""

    def __init__(self, document: Mapping[str, Any], source: Path | None = None) -> None:
        self.source = source
        self.template_dir = source.parent if source is not None else TEMPLATE_DIR
        if not isinstance(document, Mapping):
            raise CatalogError("catalog must be a mapping")
        if any(not isinstance(key, str) for key in document):
            raise CatalogError("catalog keys must be strings")
        unknown_root = set(document).difference({"version", "templates"})
        if unknown_root:
            raise CatalogError(
                "catalog has unknown keys: " + ", ".join(sorted(unknown_root))
            )
        version = document.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version != 1:
            raise CatalogError("catalog.version must be the integer 1")
        raw = document.get("templates")
        if not isinstance(raw, Mapping):
            raise CatalogError("catalog.templates must be a mapping")

        self.version = version
        self._entries: dict[str, TemplateEntry] = {}
        for name, spec in raw.items():
            if (
                not isinstance(name, str)
                or not name.strip()
                or name != name.strip()
            ):
                raise CatalogError("catalog template names must be stripped, non-empty strings")
            if not isinstance(spec, Mapping):
                raise CatalogError(f"Template {name!r} must be a mapping")
            self._entries[name] = self._entry(name, spec)

    def _entry(self, name: str, spec: Mapping[str, Any]) -> TemplateEntry:
        known = {
            "file", "stage", "purpose", "answers", "does_not_prove",
            "parameters", "requires", "alternatives", "notation",
            "notation_namespace", "caveat",
        }
        if any(not isinstance(key, str) for key in spec):
            raise CatalogError(f"Template {name!r} keys must be strings")
        unknown = set(spec) - known
        if unknown:
            raise CatalogError(
                f"Template {name!r} has unknown catalogue keys: "
                f"{', '.join(sorted(unknown))}"
            )
        for required_key in ("file", "stage", "purpose"):
            value = spec.get(required_key)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
            ):
                raise CatalogError(
                    f"Template {name!r} needs a stripped, non-empty {required_key!r}"
                )
        file = spec["file"]
        if (
            not file.endswith(".rq")
            or "\\" in file
            or any(part in {"", ".", ".."} for part in file.split("/"))
            or Path(file).is_absolute()
        ):
            raise CatalogError(
                f"Template {name!r} file must be a relative .rq path inside its catalogue directory"
            )
        stage = spec["stage"]
        if stage not in STAGES:
            raise CatalogError(
                f"Template {name!r} has stage {stage!r}; expected one of "
                f"{', '.join(STAGES)}"
            )
        for field_name in ("answers", "does_not_prove"):
            if field_name in spec and not isinstance(spec[field_name], str):
                raise CatalogError(f"Template {name!r} {field_name} must be a string")
        notation_namespace = spec.get("notation_namespace")
        if notation_namespace is not None and (
            not isinstance(notation_namespace, str)
            or not notation_namespace.strip()
            or notation_namespace != notation_namespace.strip()
        ):
            raise CatalogError(
                f"Template {name!r} notation_namespace must be a stripped, non-empty "
                "namespace IRI or null"
            )
        if notation_namespace and not spec.get("notation"):
            raise CatalogError(
                f"Template {name!r} declares notation_namespace without notation"
            )
        notation = spec.get("notation")
        if notation is not None and (
            not isinstance(notation, str)
            or not notation.strip()
            or notation != notation.strip()
        ):
            raise CatalogError(
                f"Template {name!r} notation must be a stripped, non-empty string or null"
            )

        raw_parameters = spec.get("parameters", {})
        if not isinstance(raw_parameters, Mapping):
            raise CatalogError(f"Template {name!r} parameters must be a mapping")
        parameters: dict[str, Mapping[str, Any]] = {}
        parameter_keys = {
            "type", "description", "default", "min", "max", "max_terms", "choices",
        }
        for param, pspec in raw_parameters.items():
            if (
                not isinstance(param, str)
                or not param.strip()
                or param != param.strip()
            ):
                raise CatalogError(
                    f"Template {name!r} parameter names must be stripped, non-empty strings"
                )
            if not isinstance(pspec, Mapping):
                raise CatalogError(f"Template {name!r} parameter {param!r} must be a mapping")
            if any(not isinstance(key, str) for key in pspec):
                raise CatalogError(f"Template {name!r} parameter {param!r} keys must be strings")
            unknown_parameter_keys = set(pspec).difference(parameter_keys)
            if unknown_parameter_keys:
                raise CatalogError(
                    f"Template {name!r} parameter {param!r} has unknown keys: "
                    + ", ".join(sorted(unknown_parameter_keys))
                )
            if pspec.get("type") not in PARAM_TYPES:
                raise CatalogError(
                    f"Template {name!r} parameter {param!r} has type "
                    f"{pspec.get('type')!r}; expected one of {', '.join(sorted(PARAM_TYPES))}"
                )
            if "description" in pspec and not isinstance(pspec["description"], str):
                raise CatalogError(
                    f"Template {name!r} parameter {param!r} description must be a string"
                )
            for bound in ("min", "max", "max_terms"):
                if bound in pspec and (
                    not isinstance(pspec[bound], int)
                    or isinstance(pspec[bound], bool)
                ):
                    raise CatalogError(
                        f"Template {name!r} parameter {param!r} {bound} must be an integer"
                    )
            if "choices" in pspec:
                # Only for strings: an enum of IRIs is a VALUES block in the template,
                # and an enum of integers is min/max.
                choices = pspec["choices"]
                if pspec["type"] != "string":
                    raise CatalogError(
                        f"Template {name!r} parameter {param!r} has choices, which is "
                        "only defined for type 'string'"
                    )
                if (
                    not isinstance(choices, list)
                    or len(choices) < 2
                    or any(
                        not isinstance(choice, str) or not choice.strip()
                        for choice in choices
                    )
                    or len(set(choices)) != len(choices)
                ):
                    raise CatalogError(
                        f"Template {name!r} parameter {param!r} choices must be two or "
                        "more distinct non-empty strings"
                    )
                if "default" in pspec and pspec["default"] not in choices:
                    raise CatalogError(
                        f"Template {name!r} parameter {param!r} default is not one of "
                        "its choices"
                    )
            if "default" in pspec:
                default = pspec["default"]
                kind = pspec["type"]
                if kind == "integer":
                    valid_default = (
                        isinstance(default, int) and not isinstance(default, bool)
                    )
                elif kind == "iri":
                    valid_default = _is_absolute_iri(default)
                elif kind == "string":
                    valid_default = isinstance(default, str)
                else:
                    valid_default = _valid_iri_sequence(default)
                if not valid_default:
                    raise CatalogError(
                        f"Template {name!r} parameter {param!r} default does not match {kind}"
                    )
            parameters[param] = dict(pspec)

        alternatives = spec.get("alternatives", [])
        if not isinstance(alternatives, list) or any(
            not isinstance(item, str)
            or not item.strip()
            or item != item.strip()
            for item in alternatives
        ):
            raise CatalogError(
                f"Template {name!r} alternatives must be a list of stripped, non-empty strings"
            )

        caveat = spec.get("caveat", "")
        if not isinstance(caveat, str) or caveat != caveat.strip():
            raise CatalogError(
                f"Template {name!r} caveat must be a stripped string"
            )

        return TemplateEntry(
            name=name,
            file=spec["file"],
            stage=stage,
            purpose=spec["purpose"],
            answers=spec.get("answers", ""),
            does_not_prove=spec.get("does_not_prove", ""),
            parameters=parameters,
            requires=Requirement.from_json(spec.get("requires")),
            alternatives=tuple(alternatives),
            notation=notation,
            notation_namespace=notation_namespace,
            caveat=caveat,
            template_dir=self.template_dir,
        )

    def add_questions(self, questions: Iterable[Question], *, bundled: bool) -> list[TemplateEntry]:
        """Add model questions: beside the template of their name, or as entries of their own.

        A bundled question and a bundled template of one name are one question with two
        implementations. A project's question may not take a name already in the catalogue.
        """
        added: list[TemplateEntry] = []
        for question in questions:
            name = question.identifier
            existing = self._entries.get(name)
            if existing is not None:
                if not bundled or not existing.file or existing.question is not None:
                    raise CatalogError(
                        f"Model question {name!r} ({question.iri}) duplicates an existing "
                        "catalogue entry"
                    )
                entry = replace(existing, question=question)
            else:
                if question.stage not in STAGES:
                    raise CatalogError(f"Model question {name!r} has stage {question.stage!r}")
                entry = TemplateEntry(
                    name=name,
                    file="",
                    stage=question.stage,
                    purpose=question.label,
                    answers=question.answers,
                    does_not_prove=question.does_not_prove,
                    parameters=catalogue_parameters(question),
                    requires=Requirement(capabilities=question.capabilities),
                    notation=question.notation,
                    notation_namespace=question.notation_namespace,
                    template_dir=self.template_dir,
                    question=question,
                )
            self._entries[name] = entry
            added.append(entry)
        return added

    def concerns(self) -> dict[str, list[str]]:
        """Each concern a model question informs, with the entries that inform it."""
        found: dict[str, list[str]] = {}
        for entry in self:
            for concern in entry.question.concerns if entry.question else ():
                found.setdefault(concern, []).append(entry.name)
        return {concern: sorted(names) for concern, names in sorted(found.items())}

    # -- access -------------------------------------------------------------

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries.values())

    @property
    def names(self) -> list[str]:
        return sorted(self._entries)

    def get(self, name: str) -> TemplateEntry:
        """Look up a template, tolerating an omitted directory or ``.rq`` suffix."""
        if name in self._entries:
            return self._entries[name]
        stem = name[:-3] if name.endswith(".rq") else name
        if stem in self._entries:
            return self._entries[stem]
        matches = [n for n in self._entries if n.rsplit("/", 1)[-1] == stem]
        if len(matches) == 1:
            return self._entries[matches[0]]
        if len(matches) > 1:
            raise CatalogError(
                f"{name!r} is ambiguous: {', '.join(sorted(matches))}. "
                "Give the full catalogue name."
            )
        raise CatalogError(
            f"No template {name!r}. Run `catalog list` to see the "
            f"{len(self._entries)} available."
        )

    def by_stage(self, stage: str) -> list[TemplateEntry]:
        return sorted(
            (e for e in self._entries.values() if e.stage == stage),
            key=lambda e: e.name,
        )

    def available(self, profile: ResolvedProfile) -> list[TemplateEntry]:
        """Templates this profile supports."""
        return [e for e in self if e.check(profile).ok]

    def refused(self, profile: ResolvedProfile) -> list[tuple[TemplateEntry, Verdict]]:
        """Templates this profile does not support, with the reasons."""
        out = []
        for entry in self:
            verdict = entry.check(profile)
            if not verdict.ok:
                out.append((entry, verdict))
        return out

    def validate_files(self) -> list[str]:
        """Catalogue-to-disk consistency, both directions.

        Drift in either direction is a real failure: a catalogued template with no
        file cannot run, and a file with no catalogue entry is untested and
        invisible to routing.
        """
        problems: list[str] = []
        for entry in self:
            if entry.file and not entry.path.is_file():
                problems.append(f"{entry.name}: file not found at {entry.file}")
        if self.source is None or self.source.resolve() == CATALOG_PATH.resolve():
            catalogued = {e.file for e in self if e.template_dir == TEMPLATE_DIR}
            for found in sorted(TEMPLATE_DIR.rglob("*.rq")):
                relative = found.relative_to(TEMPLATE_DIR).as_posix()
                if relative.startswith("custom/"):
                    continue
                if relative not in catalogued:
                    problems.append(
                        f"{relative}: on disk but not in catalog.json, so it is "
                        "untested and unreachable by routing"
                    )
        return problems

    def format_list(self, profile: ResolvedProfile | None = None) -> str:
        lines: list[str] = []
        for stage in STAGES:
            entries = self.by_stage(stage)
            if not entries:
                continue
            lines.append(f"\n{stage.upper()}")
            for entry in entries:
                mark = "  "
                if profile is not None:
                    verdict = entry.check(profile)
                    mark = "  " if verdict.ok else "x " if verdict.unmet else "! "
                    if verdict.ok and verdict.warnings:
                        mark = "! "
                lines.append(f"{mark}{entry.summary_line()}")
        # Templates and questions are counted apart, each by its own verdict, so a figure
        # quoted for the templates stays true as question sets grow.
        templates = [entry for entry in self if entry.file]
        questions = [entry for entry in self if entry.question]
        both = sum(1 for entry in questions if entry.file)
        if profile is None:
            lines.append(f"\n{len(templates)} template(s)")
        else:
            usable = sum(1 for entry in templates if entry.check_template(profile).ok)
            lines.append(
                f"\n{len(templates)} template(s): {usable} available under profile "
                f"{profile.name!r}, {len(templates) - usable} refused "
                "(x = refused, ! = runs with a caveat)"
            )
        if questions:
            line = (
                f"{len(questions)} model question(s), {both} of them with a template of the "
                "same name"
            )
            if profile is not None:
                asked = sum(1 for entry in questions if entry.check_question(profile).ok)
                line += f": {asked} can be asked under profile {profile.name!r}"
            lines.append(
                line + " (Q = model question; Q+T = the question where the dataset fits it, "
                "the template elsewhere)"
            )
        return "\n".join(lines).lstrip("\n")


def _read_catalog(path: Path | str) -> Catalog:
    target = Path(path).resolve()
    if not target.is_file():
        raise CatalogError(f"Catalogue not found: {target}")
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{target.name} is not valid JSON: {exc}") from exc
    except (OSError, UnicodeError) as exc:
        raise CatalogError(f"Could not read catalogue {target}: {exc}") from exc
    return Catalog(document, source=target)


def _validate_extension_entry(entry: TemplateEntry) -> None:
    from .render import _PLACEHOLDER, _base_role
    from .validate import split_comments

    limit = entry.parameters.get("LIMIT")
    if (
        not limit
        or limit.get("type") != "integer"
        or not isinstance(limit.get("min"), int)
        or isinstance(limit.get("min"), bool)
        or limit["min"] < 1
        or not isinstance(limit.get("max"), int)
        or isinstance(limit.get("max"), bool)
        or limit["max"] < limit["min"]
        or (
            "default" in limit
            and not limit["min"] <= limit["default"] <= limit["max"]
        )
    ):
        raise CatalogError(f"Extension template {entry.name!r} needs a bounded integer LIMIT")
    if not entry.does_not_prove.strip():
        raise CatalogError(f"Extension template {entry.name!r} needs does_not_prove")
    if entry.notation and not entry.notation_namespace:
        raise CatalogError(
            f"Extension template {entry.name!r} needs notation_namespace for its notation gate"
        )
    if entry.requires.capabilities and not entry.alternatives:
        raise CatalogError(
            f"Extension template {entry.name!r} needs an alternative for its capability gate"
        )

    code = "".join(
        "" if is_comment else chunk
        for is_comment, chunk in split_comments(entry.text())
    )
    placeholders = list(_PLACEHOLDER.finditer(code))
    if not re.search(r"\bLIMIT\s*\{\{\s*LIMIT\s*\}\}\s*$", code, re.IGNORECASE):
        raise CatalogError(
            f"Extension template {entry.name!r} must end with LIMIT {{{{LIMIT}}}}"
        )
    for match in placeholders:
        if match.group(1) in {
            "ROLE", "ROLES", "PATH", "GRAPH_OPEN", "GRAPH_VAR", "MEMBERSHIP"
        } and not match.group(2):
            raise CatalogError(
                f"Extension template {entry.name!r} has a missing argument for "
                f"{{{{{match.group(1)}}}}}"
            )

    roles = {
        match.group(2)
        for match in placeholders
        if match.group(1) in {"ROLE", "ROLES", "PATH"}
    }
    graph_roles = {
        _base_role(match.group(2))
        for match in placeholders
        if match.group(1) in {"GRAPH_OPEN", "GRAPH_VAR"}
    } - {"any"}
    undeclared_roles = roles - set(entry.requires.roles)
    undeclared_graph_roles = graph_roles - set(entry.requires.graph_roles)
    if undeclared_roles or undeclared_graph_roles:
        details = []
        if undeclared_roles:
            details.append("requires.roles: " + ", ".join(sorted(undeclared_roles)))
        if undeclared_graph_roles:
            details.append("requires.graph_roles: " + ", ".join(sorted(undeclared_graph_roles)))
        raise CatalogError(
            f"Extension template {entry.name!r} uses undeclared dependencies ("
            + "; ".join(details) + ")"
        )
    uses_membership = any(match.group(1) == "MEMBERSHIP" for match in placeholders)
    if uses_membership != entry.requires.membership:
        raise CatalogError(
            f"Extension template {entry.name!r} uses MEMBERSHIP={uses_membership} "
            f"but requires.membership={entry.requires.membership}"
        )


def _check_project_name(name: str, kind: str) -> None:
    segments = name.split("/")
    if (
        len(segments) < 2
        or segments[0] in {"core", "notation", "custom"}
        or any(not re.fullmatch(r"[a-z][a-z0-9_-]*", segment) for segment in segments)
    ):
        raise CatalogError(
            f"{kind} {name!r} needs a project namespace, for example acme/my-question"
        )


def load_catalog(
    path: Path | str = CATALOG_PATH,
    *,
    extensions: Sequence[Path | str] = (),
) -> Catalog:
    catalog = _read_catalog(path)
    if Path(path).resolve() == CATALOG_PATH.resolve():
        try:
            catalog.add_questions(load_index().questions, bundled=True)
        except QuestionError as exc:
            raise CatalogError(str(exc)) from exc
    external_entries: list[TemplateEntry] = []
    for extension_path in extensions:
        if str(extension_path).endswith(".ttl"):
            # A project's question set. Its questions take project names, as a project
            # template does, and must say what they do not prove.
            try:
                questions = read_set(Path(extension_path).resolve())
            except QuestionError as exc:
                raise CatalogError(f"Invalid question set {extension_path}: {exc}") from exc
            for question in questions:
                _check_project_name(question.identifier, "Model question")
                if not question.does_not_prove.strip():
                    raise CatalogError(
                        f"Model question {question.identifier!r} needs arch:doesNotProve"
                    )
            catalog.add_questions(questions, bundled=False)
            continue
        extension = _read_catalog(extension_path)
        problems = extension.validate_files()
        if problems:
            raise CatalogError("Invalid extension catalogue: " + "; ".join(problems))
        for entry in extension:
            _validate_extension_entry(entry)
            _check_project_name(entry.name, "Extension template")
            if entry.name in catalog:
                raise CatalogError(
                    f"Extension template {entry.name!r} duplicates an existing template"
                )
            catalog._entries[entry.name] = entry
            external_entries.append(entry)
    for entry in external_entries:
        missing = set(entry.alternatives) - set(catalog.names)
        if missing:
            raise CatalogError(
                f"Extension template {entry.name!r} names unknown alternatives: "
                + ", ".join(sorted(missing))
            )
    return catalog
