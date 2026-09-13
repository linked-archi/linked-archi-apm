"""Turn a question into an ordered sequence of `la-query` commands.

Nothing here opens a dataset or issues SPARQL. The output is a plan: what to run, in what
order, with which parameters, what each step establishes, and when to stop. Execution stays
with the query owner, which is where read-only enforcement and result provenance live.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .patterns import AnalyseError, Match, Pattern, terms_in

#: The default query budget for a focused question. Stated in the plan rather than enforced,
#: because a portfolio comparison legitimately needs more and should say so.
DEFAULT_BUDGET = 12

#: Where a parameter's value comes from, when the question cannot supply it. This is method
#: knowledge and belongs here: it is the difference between a runnable plan and a plan with
#: invented IRIs in it. Anything not listed becomes a generic placeholder naming the
#: catalogue as the authority, which is honest rather than convenient.
PARAMETER_SOURCES: Mapping[str, str] = {
    "FOCUS_IRI": "resolved in the resolve step, from core/resolve-element",
    "MODEL_IRI": "resolved in the resolve step, from core/resolve-model",
    "PROCESS_IRI": "an element IRI from core/resolve-element or notation/bpmn/process-components",
    "VIEW_IRI": "a view IRI from core/views",
    "VIEW_A_IRI": "a view IRI from core/views",
    "VIEW_B_IRI": "the other view IRI from core/views",
    "TYPE_IRI": "a class IRI from core/inventory, never hand-written",
    "RESOURCE_TYPE": "a class IRI from core/inventory",
    "SOURCE_TYPE": "a class IRI from core/inventory",
    "TARGET_TYPE": "a class IRI from core/inventory",
    "EXPECTED_PREDICATE": "a predicate from core/discover-predicates, spelling confirmed with core/element-detail",
    "PREDICATE_PATH": "a predicate from core/discover-relationship-types",
    "CONCEPT_IRI": "a taxonomy concept IRI, from the profile's taxonomies entry",
    "TERM": "a name from the question",
}

#: Steps every investigation starts with, in doctrine order. Orientation is first because
#: skipping it is how a partial export becomes a confident answer.
_ORIENTATION = (
    ("core/inventory-summary", "Which notations loaded, and how much of each."),
    ("core/models", "Which models contributed, and when each was converted."),
)


@dataclass
class Step:
    """One planned command."""

    number: int
    stage: str
    purpose: str
    template: str
    parameters: dict[str, str] = field(default_factory=dict)
    establishes: str = ""
    stop_when: str = ""
    availability: str = "unknown"
    caveats: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    over_budget: bool = False
    note: str = ""

    def command(self, *, profile: str | None, data: Sequence[str], endpoint: str | None,
                steps_dir: str) -> str:
        """The exact command to run, with the output path already chosen.

        Every step writes an envelope from the first step onward, because the envelope IS the
        evidence and a terminal scroll cannot be turned back into one.
        """
        parts = ["la-query", "query", "run", self.template]
        if profile:
            parts += ["--profile", shlex.quote(profile)]
        for path in data:
            parts += ["--data", shlex.quote(path)]
        if endpoint:
            parts += ["--endpoint", shlex.quote(endpoint)]
        for name, value in self.parameters.items():
            parts += ["--set", f"{name}={_render_value(value)}"]
        slug = self.template.split("/")[-1]
        parts += ["--json", "-o", f"{steps_dir}/{self.number:02d}-{slug}.json"]
        return " ".join(parts)

    def as_dict(self, **command_context: Any) -> dict[str, Any]:
        return {
            "number": self.number,
            "stage": self.stage,
            "purpose": self.purpose,
            "template": self.template,
            "parameters": dict(self.parameters),
            "establishes": self.establishes,
            "stop_when": self.stop_when,
            "availability": self.availability,
            "caveats": list(self.caveats),
            "alternatives": list(self.alternatives),
            "over_budget": self.over_budget,
            "note": self.note,
            "command": self.command(**command_context),
        }


def _render_value(value: str) -> str:
    """A supplied value is quoted; a placeholder is left visibly unresolved."""
    if value.startswith("<") and value.endswith(">"):
        return value
    return shlex.quote(value)


@dataclass
class Plan:
    """An ordered investigation, and everything it could not decide for itself."""

    question: str
    pattern: str | None
    pattern_title: str
    pattern_file: str
    ranked: list[dict[str, Any]]
    steps: list[Step]
    budget: int
    profile: str | None
    data: list[str]
    endpoint: str | None
    steps_dir: str
    annotated: bool
    notes: list[str]
    #: The pattern's own stop conditions, carried whole. NOT distributed across steps: they
    #: are conditions on the investigation, and pairing "reachability is not criticality"
    #: with whichever step happened to be third reads as a per-step rule and is nonsense.
    pattern_stop_when: list[str] = field(default_factory=list)

    def _context(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "data": self.data,
            "endpoint": self.endpoint,
            "steps_dir": self.steps_dir,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "question": self.question,
            "pattern": self.pattern,
            "pattern_title": self.pattern_title,
            "pattern_file": self.pattern_file,
            "ranked": list(self.ranked),
            "budget": self.budget,
            "planned_steps": len(self.steps),
            "annotated": self.annotated,
            "profile": self.profile,
            "data": list(self.data),
            "endpoint": self.endpoint,
            "steps_dir": self.steps_dir,
            "notes": list(self.notes),
            "pattern_stop_when": list(self.pattern_stop_when),
            "steps": [step.as_dict(**self._context()) for step in self.steps],
        }

    def to_text(self) -> str:
        lines: list[str] = [f"question   {self.question}"]
        if self.pattern:
            lines.append(f"pattern    {self.pattern} — {self.pattern_title}")
            lines.append(f"read       {self.pattern_file}")
        else:
            lines.append("pattern    none matched")
        if self.ranked:
            ranked = ", ".join(
                f"{entry['pattern']}({entry['score']})" for entry in self.ranked[:4]
            )
            lines.append(f"ranked     {ranked}")
        lines.append(
            f"budget     {self.budget} quer{'y' if self.budget == 1 else 'ies'}; "
            f"{len(self.steps)} step(s) planned"
        )
        lines.append(
            "annotated  yes, against the profile"
            if self.annotated
            else "annotated  no - template availability unknown"
        )
        for note in self.notes:
            lines.append(f"note       {note}")
        lines.append("")
        for step in self.steps:
            flag = "  [OVER BUDGET]" if step.over_budget else ""
            mark = {"available": "", "refused": "  [REFUSED by this profile]",
                    "caveat": "  [runs with a caveat]"}.get(step.availability, "")
            lines.append(f"{step.number:02d} {step.stage:12} {step.purpose}{mark}{flag}")
            lines.append(f"   $ {step.command(**self._context())}")
            if step.establishes:
                lines.append(f"   establishes: {step.establishes}")
            for name, value in step.parameters.items():
                if value.startswith("<"):
                    lines.append(f"   {name}: {value}")
            for caveat in step.caveats:
                lines.append(f"   caveat: {caveat}")
            if step.alternatives and step.availability == "refused":
                lines.append(f"   instead: {', '.join(step.alternatives)}")
            if step.note:
                lines.append(f"   note: {step.note}")
            if step.stop_when:
                lines.append(f"   stop if: {step.stop_when}")
            lines.append("")
        if self.pattern_stop_when:
            lines.append("stop the investigation when:")
            for condition in self.pattern_stop_when:
                lines.append(f"  - {condition}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _parameters_for(
    template: str, metadata: Mapping[str, Any] | None, term: str | None = None
) -> dict[str, str]:
    """Bind what the question supplies; leave everything else a visible placeholder.

    ``term`` is the name this particular step is about, passed in rather than taken from a
    shared cursor. An earlier version advanced a cursor per template, so a question quoting
    one name resolved it in step 3 and then asked `core/define-term` about a placeholder -
    two steps about the same thing, one of them unrunnable.
    """
    if metadata is None:
        return {}
    parameters: dict[str, str] = {}
    for name, spec in (metadata.get("parameters") or {}).items():
        if name == "LIMIT":
            continue  # the catalogue default is right until a result truncates
        if "default" in spec:
            continue  # a documented default beats a guess
        if name == "TERM":
            parameters[name] = term if term else f"<{name}: {PARAMETER_SOURCES['TERM']}>"
            continue
        source = PARAMETER_SOURCES.get(name)
        parameters[name] = f"<{name}: {source}>" if source else (
            f"<{name}: see `la-query catalog show {template}`>"
        )
    return parameters


def build_plan(
    question: str,
    *,
    pattern: Pattern | None,
    ranked: Sequence[Match],
    catalogue: Mapping[str, Any] | None,
    profile: str | None = None,
    data: Sequence[str] = (),
    endpoint: str | None = None,
    budget: int = DEFAULT_BUDGET,
    steps_dir: str = "steps",
) -> Plan:
    """Assemble the plan. Reads no dataset; runs nothing.

    ``catalogue`` is the query owner's `catalog dump` output when that skill is installed, and
    ``None`` when it is not. With it, each step carries real parameter names and this
    profile's availability, so **a refused template is replaced by its documented alternative
    at planning time** rather than being discovered mid-investigation. Without it the plan is
    still ordered and still names templates, and says it is unannotated.
    """
    if not question.strip():
        raise AnalyseError("a plan needs a question")
    if budget < 1:
        raise AnalyseError("--budget must be at least 1")

    templates = (catalogue or {}).get("templates") or {}
    annotated = bool(templates)
    notes: list[str] = []
    if not annotated:
        notes.append(
            "linked-archi-query was not reachable, so no template parameters or "
            "availability could be read. Run `la-query catalog dump --profile P` and re-plan, "
            "or take parameters from `la-query catalog show <template>` as you go."
        )
    if pattern is None:
        notes.append(
            "No pattern matched this question. The orientation steps below are still the "
            "right start; then either name a pattern with --mode (see "
            "references/analysis-patterns.md) or report that this package has no method for "
            "the question."
        )

    terms = terms_in(question)
    if not terms:
        notes.append(
            "No quoted name in the question, so resolve steps carry a placeholder. Quote the "
            "names you mean - inventing a TERM value is what the resolve step exists to stop."
        )

    steps: list[Step] = []
    number = 0
    planned: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    def add(
        template: str,
        stage: str,
        purpose: str,
        establishes: str,
        stop_when: str = "",
        term: str | None = None,
    ) -> None:
        nonlocal number
        metadata = templates.get(template) if annotated else None
        if annotated and metadata is None:
            # A pattern naming a template this installation does not have. The suite forbids
            # it, so this is defence against a mismatched pair of installed skills.
            notes.append(
                f"{template} is named by the routing table but absent from the installed "
                "catalogue; skipped. The two skills are probably different generations."
            )
            return
        parameters = _parameters_for(template, metadata, term)
        # The same template with the same parameters twice is the same query twice. Patterns
        # legitimately name templates the doctrine already plans - `core/provenance` is in
        # both - and running it once and citing it twice is what a reader wants.
        signature = (template, tuple(sorted(parameters.items())))
        if signature in planned:
            return
        planned.add(signature)
        number += 1
        step = Step(
            number=number,
            stage=stage,
            purpose=purpose,
            template=template,
            parameters=parameters,
            establishes=establishes,
            stop_when=stop_when,
            over_budget=number > budget,
        )
        if metadata is not None:
            available = metadata.get("available")
            profile_caveats = list(metadata.get("profile_caveats") or [])
            caveat = metadata.get("caveat")
            if available is False:
                step.availability = "refused"
                step.note = "; ".join(metadata.get("unmet") or [])
            elif profile_caveats:
                step.availability = "caveat"
            else:
                step.availability = "available"
            step.caveats = ([caveat] if caveat else []) + profile_caveats
            step.alternatives = list(metadata.get("alternatives") or [])
        steps.append(step)

    for template, purpose in _ORIENTATION:
        add(
            template, "orient", purpose,
            "what is actually loaded, so an empty later result can be told from a partial export",
            "only one notation loaded and the question needs two",
        )

    resolve_template = "core/resolve-element"
    # One resolve step per quoted name: a question naming two things needs both resolved, and
    # a plan that resolves the first and assumes the second is how the second gets invented.
    for term in (terms or (None,)):
        subject = f'"{term}"' if term else "each name in the question"
        add(
            resolve_template, "resolve",
            f"Turn {subject} into an IRI.",
            "the focus IRIs later steps take as parameters",
            "several candidates match and the choice changes the answer - ask instead of picking",
            term=term,
        )
        add(
            "core/define-term", "resolve",
            f"Explain what {subject} means here, and how ambiguous it is.",
            "whether the name means one thing in this dataset",
            "the candidates column is greater than one - name them and ask",
            term=term,
        )

    if pattern is not None:
        for template in pattern.templates:
            add(
                template, "pattern",
                f"{pattern.title}: evidence from {template}.",
                "the pattern's own evidence",
                term=terms[0] if terms else None,
            )

    add(
        "core/provenance", "quality",
        "Name the source model, converter and timestamp for what the answer rests on.",
        "that every load-bearing element can be traced to a source",
        "an element the conclusion depends on has no provenance - say so in the answer",
    )

    if number > budget:
        notes.append(
            f"The plan is {number} steps against a budget of {budget}. Steps marked OVER "
            "BUDGET are the ones to drop first, or raise the budget and say you did."
        )

    return Plan(
        question=question.strip(),
        pattern=pattern.name if pattern else None,
        pattern_title=pattern.title if pattern else "",
        pattern_file=pattern.file if pattern else "",
        ranked=[
            {"pattern": match.pattern.name, "score": match.score,
             "matched": list(match.matched)}
            for match in ranked
        ],
        steps=steps,
        budget=budget,
        profile=profile,
        data=list(data),
        endpoint=endpoint,
        steps_dir=steps_dir,
        annotated=annotated,
        notes=notes,
        pattern_stop_when=list(pattern.stop_when) if pattern else [],
    )
