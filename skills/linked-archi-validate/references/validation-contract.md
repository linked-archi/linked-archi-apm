# Validation contract

What `la-validate` produces, what it deliberately does not, and the exact JSON shape.
`la-validate _machine` is the stable boundary for automation, and it is machine-facing
rather than private: the underscore means "not for a human to type", nothing more. Same
policy as every other owner here.

SHACL runs in-process through `pyshacl`. There is no converter, no Java runtime and no
network access in this path. The only requirement beyond Python is `pip install pyshacl`,
which brings `rdflib` with it — the same shape of dependency as `pyoxigraph` for local
querying.

Shape documents are **never bundled**. The Linked.Archi ontologies and shapes are published
separately under their own licence, so callers pass local files, or acquire the published
documents once through `linked-archi-source` and pass the cached paths.

## Commands

| Command | Purpose |
|---|---|
| `la-validate run --data F --shapes S` | Validate here and now. Reports coverage. |
| `la-validate report FILE` | Summarise a report produced elsewhere. Cannot report coverage. |
| `la-validate doctor` | Owner root, resolved command, dependency versions, optional companions. |
| `la-validate _machine validate` | Versioned JSON contract for a run. |
| `la-validate _machine report` | Versioned JSON contract for reading a report. |

## `run` options

| Option | Effect |
|---|---|
| `--data FILE` | RDF to validate. Repeatable; files merge into one graph. Required. |
| `--shapes FILE` | SHACL shapes. Repeatable; files merge into one shape set, so passing more is **additive**. Required. |
| `--ontology FILE` | Axioms loaded for reasoning. Repeatable. Adds to the data; never replaces shapes. |
| `--no-rdfs-reasoning` | Disable `rdfs:subClassOf` inference. Changes which shapes match. |
| `--data-format FMT` | Override the parser for `--data` files. |
| `-r`, `--report FILE` | Also write the report graph as Turtle. |
| `--json` | Emit the versioned JSON result. |
| `--limit N` | Findings shown (default 25). Counts are always complete. |

Additive shape sets are a deliberate difference from the converters' `validate`, where
`--shapes` *replaces* the defaults. There are no defaults here — nothing is bundled — so
every shape set is one you named, and adding another can only widen what is checked.

## How the data graph is loaded

TriG and N-Quads are parsed into a dataset, then validated as the **union** of their
graphs. This matters more than it sounds: converter output puts every triple in a named
graph and leaves the default graph empty, so a validator that looked only at the default
graph would check nothing and report a clean pass.

The number of named graphs that arrived is reported alongside the triple count, so a
flattened input is visible rather than silent.

Extensions map to parsers as `.trig`, `.ttl`/`.turtle`, `.nt`, `.nq`/`.nquads`,
`.rdf`/`.xml`, `.jsonld`/`.json`, `.n3`. The extension chooses the parser, so a TriG file
named `.ttl` loads as Turtle and loses its graphs without complaint.

## Coverage, and what it means

Coverage is measured over **target classes**, before validation runs, because it is the
number that decides whether the verdict means anything.

Counted as declared targets:

- every object of `sh:targetClass`;
- SHACL **implicit class targets** — a node that is both a shape and an `rdfs:Class` or
  `owl:Class` targets its own instances. Missing these would understate coverage and make
  a sound shape set look vacuous.

A target counts as matched when the data has an instance of it, or of any subclass reached
through `rdfs:subClassOf`. Subclass awareness matters because the notation ontologies are
class hierarchies: a shape targeting a superclass genuinely applies to specialisations.

Other target kinds — `sh:targetNode`, `sh:targetSubjectsOf`, `sh:targetObjectsOf`,
`sh:target` — are counted separately, so "no class targets" is never reported as "no
targets at all".

| Case | Meaning | Exit |
|---|---|---|
| `matched == declared` | Every declared class target applied | `0` or `1` |
| `0 < matched < declared` | Partial. Normal when validating one notation in a merged graph | `0` or `1` |
| `matched == 0`, `declared > 0` | **Vacuous.** Nothing was checked | `2` |
| `declared == 0`, no other targets | Nothing selected a focus node | `2` |
| `declared == 0`, other targets present | Class coverage unknown, not zero | `0` or `1` |

## Exit codes

| Code | Means |
|---|---|
| `0` | Conforms, and something was actually checked |
| `1` | Results reported |
| `2` | Could not run, or checked nothing |

The `2` for "checked nothing" is a deliberate departure from treating conformance as the
only question. A namespace mismatch produces `sh:conforms true` over zero checked
constraints; returning `0` there would let every CI step and every reader record a pass.
The verdict and the coverage are reported either way — only the exit code refuses to call
it success.

## What the report contains

Standard SHACL. Per result: `sh:resultSeverity`, `sh:focusNode`, `sh:resultPath`,
`sh:sourceShape`, `sh:sourceConstraintComponent`, `sh:resultMessage`, `sh:value`.

Per the SHACL specification, `sh:conforms` is false when there is **any** result,
regardless of severity. If a report claims `sh:conforms true` while carrying results, this
tool trusts the results and reports non-conformance — the other reading is the dangerous
one.

## What it does not contain

Reported as explicit `null` in JSON rather than omitted, so absence cannot be read as zero:

- `constraints_evaluated`
- `constraints_skipped`

Nothing in the pipeline produces either number. Also absent from a SHACL report, by design
of the standard:

- **the source model** of a violating element — `sh:focusNode` is an element IRI; reaching
  the file and its author needs `core/provenance` from the query owner;
- **an owner** — ownership is notation-specific and often absent entirely.

## JSON contract

`schema_version` is `1`. Unknown input fields, a non-`1` version, and query or SPARQL
fields are refused. This owner never accepts query text.

Run request:

```json
{
  "schema_version": 1,
  "data": ["dist/merged.trig"],
  "shapes": ["core-shapes.ttl"],
  "ontology": [],
  "rdfs_reasoning": true
}
```

Run response:

```json
{
  "schema_version": 1,
  "mode": "run",
  "conforms": false,
  "result_count": 27,
  "by_severity": {"Violation": 27},
  "by_source_shape": {"...": 27},
  "findings": [
    {
      "severity": "Violation",
      "focus_node": "https://example.org/la/...",
      "path": "http://www.w3.org/2004/02/skos/core#prefLabel",
      "source_shape": "...",
      "constraint": "http://www.w3.org/ns/shacl#MinCountConstraintComponent",
      "message": "Every ModelConcept instance must have at least one skos:prefLabel.",
      "value": null
    }
  ],
  "findings_truncated": false,
  "coverage": {
    "declared_target_classes": 2,
    "matched_target_classes": 2,
    "unmatched_target_classes": [],
    "other_target_kinds": {"target": 0, "targetNode": 0, "targetObjectsOf": 0, "targetSubjectsOf": 0},
    "shape_count": 3,
    "vacuous": false,
    "no_class_targets": false,
    "constraints_evaluated": null,
    "constraints_skipped": null
  },
  "checked_nothing": false,
  "inputs": {
    "data": ["/abs/dist/merged.trig"],
    "shapes": ["/abs/core-shapes.ttl"],
    "data_triples": 1282,
    "data_named_graphs": 12,
    "shape_triples": 43,
    "rdfs_reasoning": true
  },
  "warnings": []
}
```

Report request and response:

```json
{"schema_version": 1, "report": "ttl/graph-shacl-report.ttl"}
```

The response has the same verdict and findings fields, `"mode": "report"`, and
`"coverage": null` — explicitly null, because a report does not record what was checked.
Its `warnings` always carry the two caveats: the shape selection is unknown, and the report
is a point-in-time document.

## Reading a report that is in the dataset

A report loaded into the graph as a named graph is a *graph* question. It belongs to the
query owner, under a profile that declares both the capability and the graph role:

```yaml
capabilities:
  validation_in_graph: true
graphs:
  roles:
    validation: the graph IRI or suffix the report is loaded into
```

```bash
la-query query run core/validation-summary --profile curated-store --data "$GRAPH"
```

Without that capability the template is refused, correctly. Setting it true to get past the
message produces an empty summary that reads as a clean verdict.

## Merged, multi-notation graphs

There is no single shape set for "all of it". Validate once per notation present, and
report the runs separately:

```bash
la-query query run core/models --data dist/merged.trig     # which notations exist

la-validate run --data dist/merged.trig --shapes core-shapes.ttl --shapes archimate-shapes.ttl \
  -r reports/archimate.ttl
la-validate run --data dist/merged.trig --shapes core-shapes.ttl --shapes bpmn-shapes.ttl \
  -r reports/bpmn.ttl
```

Each run matches only its own notation's classes, so each reports partial coverage against
the merged whole. That is expected, which is why coverage must be reported per run rather
than summed. A notation you did not validate is not a notation that passed.
