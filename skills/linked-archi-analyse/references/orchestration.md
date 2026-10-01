# Executing a plan and closing the evidence loop

Analyse owns question investigation, ordering and interpretation. Its runtime produces
plans and bundles; every store operation remains with query and its companion owners.

## Work the plan, do not blindly execute it

Read the selected pattern and its stop conditions. `steps` are query candidates, not
commands to execute without review. Replace visible `<...>` parameter placeholders only
with values established by evidence. Unknown availability requires catalogue review;
refused candidates are recorded separately in `decisions`, without a command. Alternatives
are suggestions with different semantics, not automatic replacements.

`depends_on` requires review of earlier results. `review_decisions` requires acknowledging
refusal boundaries. A step being fully bound is not evidence that either review happened.
Budget flags remain advisory: count executed queries and stop at the agreed budget.

For a question with several requested answers, keep a short claim-to-evidence checklist while
reviewing the plan. Allocate queries to the smallest useful path for each claim before optional
audits or wider result limits. A pattern's stop condition can close the claim that depends on
it without abandoning independent claims. Before bundling, check that every requested answer
has executed evidence or an explicit, evidence-based limitation; do not mistake a plan's
candidate steps for complete question coverage.

When the tested template shortlist does not cover a claim, a supplied or project-local query
may be a useful starting point. Inspect only a relevant candidate; check its graph scope,
parameters and bounds, then delegate lint and execution to query. Its presence is not proof
that it answers the question, and it never becomes evidence until executed against the
settled dataset and profile.

Plans include `batches` for independent, fully bound same-stage candidates with known
availability and an explicit dataset/endpoint; `--batch-dir DIR` also writes those manifests.
Over-budget candidates are excluded. Neither plans nor manifest
creation executes queries. Start with the orientation batch, inspect it, then resolve
names. Do not execute later batches until their dependencies and decisions are reviewed.
No placeholder/refused/unknown-availability step should enter a batch. Pattern stages
keep their review barriers even when their parameters are already known.

Use the same explicit profile and target on every query command. Query-level `--set LIMIT`
bounds results, while `--limit` only bounds display. For evidence with a compact preview:

```bash
la-query query run core/resolve-element --profile linked-archi-default --data graph.trig \
  --set TERM='Order Service' -o steps/03-resolve-element.json --preview --limit 20
```

Every batch entry needs its own `out`; batch-level `-o` is only a summary. Preserve exact
queries and complete envelopes on disk from the first step. Read more of an artifact only
when its preview is insufficient. Observe warnings and query truncation even if displayed
rows look convincing. Do not discard failed/refused decisions from the explanation.

Definitions are not mandatory per entity. Resolve first; add `core/define-term` when the
question asks what a term means, a pattern explicitly needs it, or ambiguity remains.
`--definitions` requests definition steps explicitly. A model name may require
`core/resolve-model` rather than concept resolution.

## Bundle only executed evidence

Load `output-contract.md` before composing findings and `evidence-model.md` when classifying
a difficult claim. All five classes must be present, even when empty:

```json
{
  "answer": "A model-scoped answer supported by the cited steps.",
  "graph_facts": [{"claim": "...", "steps": [3]}],
  "derived_facts": [],
  "document_statements": [],
  "inferences": [],
  "unknowns": [{"claim": "Runtime call volume is not represented."}]
}
```

```bash
la-analyse bundle --step steps/01-inventory-summary.json --step steps/02-models.json \
  --step steps/03-resolve-element.json --question '...' --findings findings.json \
  --dataset-revision KNOWN_REVISION -o investigation.json
la-analyse render --bundle investigation.json -o investigation.md
```

List **only actual query envelopes**, in execution order; not plan/manifest/summary files.
Finding step numbers refer to this bundle order, so adjust citations if candidates were
skipped or reordered. Omit `--dataset-revision` if unknown; a project commit is not
automatically the dataset revision. Connect's `datasets` can report the data repository
revision. The bundler records a supplied revision without independently checking it.

Mixed dataset or profile identities are refused. Claims except unknowns must cite existing
steps. The bundler validates structure and coherence, not inference quality or semantic
truth. Its snapshots are bounded; original step files remain the full evidence.
Verification status records an earlier check, not a freshness guarantee.
