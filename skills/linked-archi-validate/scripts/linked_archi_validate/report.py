"""Reading a SHACL validation report, whoever produced it.

A report is a document, not a graph the pipeline maintains. It may come from this skill,
from a converter's own `validate` subcommand, or from a CI job that published
`graph-shacl-report.ttl` months ago. All three are read the same way here.

What a report can and cannot tell you is the point of this module. It records what was
found. It does not record what was *checked*, so coverage is not derivable from a report
alone - only from a run where the shapes and the data were both present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import ValidateError
from .rdf import require_rdflib

SH = "http://www.w3.org/ns/shacl#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

SEVERITIES = ("Violation", "Warning", "Info")

_RESULT_FIELDS = {
    "severity": f"{SH}resultSeverity",
    "focus_node": f"{SH}focusNode",
    "path": f"{SH}resultPath",
    "source_shape": f"{SH}sourceShape",
    "constraint": f"{SH}sourceConstraintComponent",
    "message": f"{SH}resultMessage",
    "value": f"{SH}value",
}


@dataclass
class Finding:
    severity: str
    focus_node: str | None = None
    path: str | None = None
    source_shape: str | None = None
    constraint: str | None = None
    message: str | None = None
    value: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "focus_node": self.focus_node,
            "path": self.path,
            "source_shape": self.source_shape,
            "constraint": self.constraint,
            "message": self.message,
            "value": self.value,
        }


@dataclass
class Summary:
    conforms: bool
    findings: list[Finding] = field(default_factory=list)
    by_severity: dict[str, int] = field(default_factory=dict)
    by_source_shape: dict[str, int] = field(default_factory=dict)

    @property
    def result_count(self) -> int:
        return len(self.findings)

    def as_dict(self, limit: int | None = None) -> dict[str, Any]:
        shown = self.findings if limit is None else self.findings[:limit]
        return {
            "conforms": self.conforms,
            "result_count": self.result_count,
            "by_severity": dict(self.by_severity),
            "by_source_shape": dict(self.by_source_shape),
            "findings": [finding.as_dict() for finding in shown],
            "findings_truncated": limit is not None and self.result_count > len(shown),
        }


def _local(term: Any) -> str:
    text = str(term)
    for separator in ("#", "/"):
        if separator in text:
            candidate = text.rsplit(separator, 1)[-1]
            if candidate:
                return candidate
    return text


def summarise(graph: Any) -> Summary:
    """Extract the verdict and every result from a report graph."""
    rdflib = require_rdflib()
    URIRef = rdflib.URIRef

    conforms_values = list(graph.objects(None, URIRef(f"{SH}conforms")))
    result_nodes = list(graph.objects(None, URIRef(f"{SH}result")))
    if not result_nodes:
        # A bare result graph without a report node is still readable.
        result_nodes = list(graph.subjects(URIRef(RDF_TYPE), URIRef(f"{SH}ValidationResult")))

    if not conforms_values and not result_nodes:
        raise ValidateError(
            "this file carries no sh:conforms and no sh:result, so it is not a SHACL "
            "validation report. Check the path, or run validation to produce one."
        )

    if conforms_values:
        conforms = bool(conforms_values[0].toPython())
    else:
        conforms = not result_nodes

    findings: list[Finding] = []
    for node in result_nodes:
        values: dict[str, str | None] = {}
        for name, predicate in _RESULT_FIELDS.items():
            found = list(graph.objects(node, URIRef(predicate)))
            values[name] = str(found[0]) if found else None
        severity = _local(values.get("severity") or f"{SH}Violation")
        findings.append(
            Finding(
                severity=severity,
                focus_node=values.get("focus_node"),
                path=values.get("path"),
                source_shape=values.get("source_shape"),
                constraint=values.get("constraint"),
                message=values.get("message"),
                value=values.get("value"),
            )
        )

    # Violations first, so a truncated list never hides the severe results.
    order = {name: index for index, name in enumerate(SEVERITIES)}
    findings.sort(key=lambda item: (order.get(item.severity, len(SEVERITIES)), str(item.source_shape or ""), str(item.focus_node or "")))

    by_severity: dict[str, int] = {}
    by_shape: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
        key = finding.source_shape or "(unnamed shape)"
        by_shape[key] = by_shape.get(key, 0) + 1

    if conforms and findings:
        # Trust the results over the flag: a report claiming conformance while carrying
        # results is malformed, and reporting "conforms" would be the dangerous reading.
        conforms = False

    return Summary(
        conforms=conforms,
        findings=findings,
        by_severity=by_severity,
        by_source_shape=dict(sorted(by_shape.items(), key=lambda item: (-item[1], item[0]))),
    )
