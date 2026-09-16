---
name: linked-archi-validate
description: Run SHACL validation over an RDF architecture graph in-process, or summarise a SHACL report that already exists, and read the verdict honestly with target-class coverage beside it. Use only when explicitly asked to validate, to check conformance against shapes, to review violations, or when pointed at an existing report file such as graph-shacl-report.ttl. Needs no converter, Java runtime or network access. Do not run it as a background check on other work, and do not use it for general model-quality questions that no SHACL shape covers.
license: Apache-2.0
compatibility: Needs Python 3.11 or newer and pyshacl, which installs rdflib. SHACL runs in-process, so no converter, Java runtime or network access is required. Shape documents are published separately and never bundled here, so pass local shape files or acquire them once with linked-archi-source. Reading a report already loaded into a dataset needs linked-archi-query instead.
metadata:
  author: linked-archi
  version: "0.6.0"
  homepage: https://meta.linked.archi
allowed-tools: Read Bash(python3:*)
---

# Validating an architecture graph

## Invocation and companions

Owner command: `la-validate`. Resolution order, first hit wins:

1. `la-validate` on `PATH`;
2. `$LINKED_ARCHI_SKILLS_DIR/linked-archi-validate/scripts/la-validate`;
3. the sibling skill directory beside this one.

Run `la-validate doctor` when anything is unresolved: it prints the owner root, the
resolved command, `pyshacl`/`rdflib` versions, and which optional companions it can see.

Never search the filesystem for skills, scripts or shape files, and never search from `/`
or `$HOME`. If resolution fails, report the exact missing piece and stop.

Two optional companions, neither required to validate:

- `linked-archi-source` — acquire published shape documents once, verified by digest and
  cached, then reusable offline.
- `linked-archi-query` — model-quality questions no shape covers, and reports that have
  been loaded into a dataset as a named graph.

## Run this only when asked

Validation is an explicit request, not a precondition. Run it when the user asks to
validate, to check conformance, to review violations, or hands you a report file.

Do **not** run it as a silent gate before answering an ordinary architecture question. If
an answer depends on the models being complete, that is a coverage question, and coverage
questions belong to `linked-archi-query` templates — see *Quality without SHACL* below.

## What this skill measures, and what it cannot

Three signals exist, and only three:

- **the verdict** — conforms, or a list of results;
- **target-class coverage** — how many of the shape graph's `sh:targetClass` declarations
  matched something in the data;
- **checked nothing** — no focus node could be selected at all, which makes a clean
  verdict meaningless.

There is no count of constraints evaluated and no inventory of constraints skipped. The
JSON contract returns those fields as explicit `null` rather than omitting them, so a
consumer cannot mistake absence for zero. Do not report numbers the tool does not produce.

Detail: [references/validation-contract.md](references/validation-contract.md).

## Validate a graph

Shapes are never bundled here — the Linked.Archi ontologies and shape documents are
published separately under their own licence — so name them explicitly:

```bash
la-validate run --data dist/merged.trig --shapes core-shapes.ttl --shapes relationships.ttl
```

Several `--data` files merge into one graph, which is how a federated graph is assembled
from per-model converter output. Several `--shapes` files merge into one shape set, so
adding a shape set is additive here rather than replacing anything.

Named graphs are handled explicitly: TriG and N-Quads are loaded as a dataset and
validated as the union of their graphs. A validator that looked only at the default graph
would check nothing against converter output and report a clean pass.

To keep the report:

```bash
la-validate run --data dist/merged.trig --shapes core-shapes.ttl -r reports/shacl.ttl
```

`--ontology` adds axioms for reasoning. `--no-rdfs-reasoning` turns off `rdfs:subClassOf`
inference, which changes which shapes match — say which you used.

### Getting the published shapes without a converter

Acquire once, verified and cached, then work offline:

```bash
la-source url https://meta.linked.archi/core-shapes --format turtle --sha256 68b8...
la-validate run --data dist/merged.trig --shapes ~/.cache/linked-archi/sources/sha256/68b8.../68b8....ttl
```

A local file already on disk works just as well. Nothing here fetches shapes by itself.

## Read a report somebody else produced

When the user points at an existing report — a converter's output, a CI artifact, a
published `graph-shacl-report.ttl` — read it directly. No shapes, no data, no validation
run:

```bash
la-validate report ttl/graph-shacl-report.ttl
```

This gives the verdict, results by severity and by firing shape, and the findings
themselves. It **cannot** give coverage: a report records what was found, never what was
checked. Say that plainly rather than implying the graph was fully checked, and re-run
validation with the shapes when coverage matters.

Two caveats the command prints, and you should carry into the answer: the report was
produced elsewhere so its shape selection is unknown, and it is a point-in-time document
that may not describe the dataset in front of you.

If a report has instead been **loaded into the dataset** as a named graph, it is a graph
question and belongs to the query owner:

```bash
la-query query run core/validation-summary --profile curated-store --data "$GRAPH"
```

Under any profile without `validation_in_graph` that template is refused, and the refusal
is correct — there is no report in the graph. Do not set the capability true to get past
it; that produces an empty summary that reads as a clean verdict.

## Exit codes

| Code | Means |
|---|---|
| `0` | Conforms, and something was actually checked |
| `1` | Results reported |
| `2` | Could not run, **or checked nothing** |

Two things deserve attention.

**A run that selected no focus node exits `2`, not `0`.** A namespace mismatch between
shapes and data, or an ontology passed where a shapes file was meant, would otherwise
report `sh:conforms true` while checking nothing — and every CI step and every reader
treats `0` as a pass. That is the single most dangerous outcome in validation, so it is
reported as a configuration failure.

**Exit `1` is a finding, not a crash.** The tool blocks: a CI job fails on its own, which
is deliberate. The analysis does not: read the report, name the findings, and carry on.
This pipeline merges models it neither authors nor can fix, so a violation is something to
report to a model owner.

## Traps worth naming when you see them

- **A clean verdict with low coverage.** Validating one notation inside a merged graph
  matches only that notation's classes. Report coverage per run; never sum it.
- **An ontology passed as shapes.** No `sh:targetClass`, nothing selected, exit `2`.
- **Reasoning changes the answer.** With `rdfs:subClassOf` inference a shape targeting a
  superclass matches specialisations; without it, it does not.
- **The extension must match the content.** A TriG file named `.ttl` parses as Turtle and
  loses its graphs silently.
- **Blank-node shape identifiers.** Property shapes are often blank nodes, so "by shape"
  grouping can show an opaque identifier. Group findings by source model for humans.

## Severity

`sh:Violation` breaks the metamodel. `sh:Warning` breaks a local expectation. `sh:Info` is
advisory. Per the SHACL specification, *any* result makes `sh:conforms` false, regardless
of severity.

Report severity **as recorded**. Do not promote a warning to a violation because it seems
important; add your own view separately if you have one.

## Ownership of a finding

The shape that fired tells you who can fix it:

| Shapes from | Means | Fixed by |
|---|---|---|
| A notation's published shapes | The model breaks ArchiMate, BPMN or C4 as a language | The author of the source model |
| The core shapes | A shared property is missing or malformed | The model author, usually |
| Project-local shapes | It fails an expectation this pipeline added | Possibly the pipeline — local expectations change |

A result names a focus node, a path and a source shape. It does **not** name a source model
or an owner. Getting from a violating element to the person who can fix it is one more
query:

```bash
la-query query run core/provenance --data "$GRAPH" --set FOCUS_IRI=<violating-element>
```

## Quality without SHACL

Most model-quality questions need no validator and no shapes. They are **query** work, not
validation work, and they belong to the analyse skill's model-quality pattern:
`core/inventory-summary`, `core/models`, `core/coverage-gaps`, `core/orphans`,
`core/provenance`, `core/identity-audit`.

Route there when the question is "can we trust these models" or "is this complete" and
nobody asked for SHACL. Come back here when the question is conformance.

## Reporting

**Group by source model and owner, not by shape.** The person who can fix a finding cares
which of their files is wrong, not which constraint fired.

**State coverage in the same sentence as the verdict.** "Conforms, 14 of 23 target classes
matched" is a report. "Conforms" alone is a reassurance.

**Say what was not checked.** Which shape sets ran, which notations you validated and which
you did not, and whether any run checked nothing.

**Never say "the graph is valid".** Say what conformed, against which shapes, at what
coverage.
