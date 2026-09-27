# Analyse machine contract

`la-analyse _machine` is the stable boundary for automation and sibling orchestration. The
leading underscore marks it as **machine-facing, not private**: it is documented and
versioned, like every other owner's. Human-facing output belongs to `plan`, `bundle`,
`render` and `doctor`.

One JSON object on stdin, one JSON object on stdout, diagnostics on stderr. The contract is
`schema_version: 1`, checked exactly.

**This owner executes nothing.** No dataset is opened, no SPARQL is issued, no transport is
used. `plan` emits commands, decisions and batch manifests; `bundle` reads what query wrote.

## Commands

| Command | Purpose |
|---|---|
| `la-analyse _machine plan` | Route a question to a pattern and return the ordered steps |
| `la-analyse _machine bundle` | Assemble already-written envelopes into one artifact |

## plan

```json
{
  "schema_version": 1,
  "question": "what depends on \"Order Service\" if we retire it?",
  "mode": "impact-and-dependency",
  "profile": "linked-archi-default",
  "data": ["dist/merged.trig"],
  "endpoint": null,
  "budget": 12,
  "steps_dir": "steps",
  "definitions": false,
  "batch_dir": "batches"
}
```

Only `question` is required. `mode` names a pattern instead of routing to one and is
validated against `assets/patterns.json`. `data` and `endpoint` are **recorded into the
emitted commands, not used** — nothing here reads them.

`definitions` is an optional boolean, default `false`. Definitions are planned when this is
true or the question explicitly asks for meaning: `define`, `definition`, `meaning`,
`what does/do … mean`, or `what is/are "a quoted name"`. Words inside quoted names do not
trigger the heuristic. A pattern listing `core/define-term` does not force it into every
plan: request definitions when the investigation needs that semantic evidence. Name
resolution still preserves its ambiguity stop condition.

`batch_dir`, when supplied, must be a non-empty string. It sets the intended manifest paths.
**The machine command writes no manifests.** The human `plan --batch-dir DIR` command writes
them; otherwise consumers can save the embedded manifests themselves. Neither runs queries.

The response is the plan document. These representative fields abbreviate the `steps`
array; `decisions` and `batches` are described separately below:

```json
{
  "schema_version": 1,
  "question": "...",
  "pattern": "impact-and-dependency",
  "pattern_title": "Impact and dependency",
  "pattern_file": "references/patterns/impact-and-dependency.md",
  "ranked": [{"pattern": "impact-and-dependency", "score": 2, "matched": ["retire", "depends on"]}],
  "budget": 12,
  "planned_steps": 7,
  "annotated": true,
  "profile": "linked-archi-default",
  "data": ["dist/merged.trig"],
  "endpoint": null,
  "steps_dir": "steps",
  "notes": [],
  "pattern_stop_when": ["..."],
  "steps": [
    {
      "number": 1,
      "stage": "orient",
      "purpose": "Which notations loaded, and how much of each.",
      "template": "core/inventory-summary",
      "parameters": {},
      "establishes": "...",
      "stop_when": "...",
      "availability": "available",
      "caveats": [],
      "alternatives": [],
      "over_budget": false,
      "note": "",
      "depends_on": [],
      "review_decisions": [],
      "unresolved_parameters": [],
      "status": "ready",
      "command": "la-query query run core/inventory-summary --profile linked-archi-default --data dist/merged.trig --json -o steps/01-inventory-summary.json --preview --limit 20"
    }
  ]
}
```

What a caller may rely on:

- **`command` remains a string describing the planned invocation.** It includes
  `--json -o` to save the full envelope and, when the installed companion supports it,
  `--preview --limit 20` for bounded presentation.
  A command with unresolved placeholders or unknown availability is not runnable yet;
  supplying a target and reviewing dependencies and decisions are the caller's work.
- **`availability`** on query steps is `available`, `caveat`, or `unknown`. Known refusals
  are recorded in `decisions` with `availability: "refused"` and no command. Alternatives
  require an explicit semantic assessment, never an automatic substitution.
- **`annotated: false`** means `linked-archi-query` was not reachable, so no parameters or
  availability could be read. The plan is still ordered and still names templates; `notes`
  says what is missing. It degrades rather than failing. `annotated: true` means catalogue
  metadata was obtained; without a profile its availability is still `unknown`.
- **A parameter value wrapped in `<…>` is a placeholder**, never a value. It names where the
  value comes from — "resolved in the resolve step, from core/resolve-element". Nothing is
  invented, which is the whole reason the resolve step exists. `unresolved_parameters`
  contains the names of these parameters.
- **`depends_on`** lists preceding step numbers whose evidence must be reviewed first.
  Resolution depends on orientation; pattern steps retain their ordered review boundaries.
  It does not assert that those steps have run or returned sufficient evidence.
- **`review_decisions`** lists earlier refusal decision IDs to resolve before proceeding.
  Reporting a limitation or stopping may be the right resolution; choosing an alternative
  is not assumed to answer the original question.
- **`pattern: null`** means no trigger matched. The orientation steps are still correct; the
  caller should name a `mode` or report that this package has no method for the question.
- **`over_budget`** marks steps beyond `budget`. They are marked rather than dropped, so what
  is being given up stays visible, but never enter a batch. `planned_steps` and the budget
  count query steps; refusal decisions are separate.
- **`pattern_stop_when`** belongs to the investigation, not to any one step. Distributing
  those conditions across steps would read as per-step rules and mislead.

`status` is a planning summary, not execution authorization:

| Status | Meaning |
|---|---|
| `unknown` | Profile availability is not known. Metadata may still provide parameter names. |
| `review-required` | An earlier refusal appears in `review_decisions`. |
| `awaiting-parameters` | One or more parameter values remain placeholders. |
| `awaiting-evidence` | Parameters are concrete but `depends_on` evidence needs review. |
| `ready` | Known profile availability, bound parameters, no outstanding planning dependencies. |

When several conditions apply, the first applicable status in that table wins; the other
fields remain available. `ready` on a step does not imply that a target was supplied, that
the configured profile was verified against this dataset, or that stop conditions hold.
Query still performs rendering, gating and read-only validation at execution time.

Fresh orientation is always retained. This planner accepts no cached orientation evidence
and does not use the existing verification marker to skip queries: basename-only dataset
identity cannot establish a current dataset revision.

### Refusal decisions

`decisions` is an array, empty when no template is refused. A record contains:

```json
{
  "id": "decision-1",
  "stage": "pattern",
  "template": "core/dependents-direct",
  "purpose": "Impact and dependency: evidence from core/dependents-direct.",
  "availability": "refused",
  "reason": "capability 'direct_rel_triples' is False but this template needs True",
  "alternatives": ["core/dependents-qualified", "core/neighbours-qualified"],
  "answers": "Everything reaching an element at any depth along a chosen predicate set.",
  "does_not_prove": "Impact, or completeness beyond the predicates named.",
  "caveats": []
}
```

The reason, alternatives and semantic limits come from the query catalogue. The record has
no `command`, is absent from `steps`, and is never batched. For example, a two-hop qualified
path is not equivalent to unbounded direct reachability; the planner makes no such claim.

### Batch manifests

`batches` is an array of groups with at least two independent concrete steps, sharing a
stage and the same dependencies. It is empty unless an explicit `data` or `endpoint` target
is supplied. Unknown profile availability, unresolved parameters, refusal review and
over-budget status exclude a step. A ready orientation group looks like:

```json
{
  "stage": "orient",
  "steps": [1, 2],
  "depends_on": [],
  "status": "ready",
  "manifest_path": "batches/01-orient.json",
  "manifest": {
    "schema_version": 1,
    "queries": [
      {"id": "step-01", "template": "core/inventory-summary", "set": {}, "out": "steps/01-inventory-summary.json"},
      {"id": "step-02", "template": "core/models", "set": {}, "out": "steps/02-models.json"}
    ]
  },
  "command": "la-query query batch batches/01-orient.json --profile linked-archi-default --data dist/merged.trig --preview --limit 20"
}
```

`manifest` uses the existing query batch contract unchanged. Each `out` saves a complete
envelope for `bundle`; preview limits only presentation. Without `batch_dir`, paths default
to `steps_dir/batches/NN-STAGE.json`. Save the manifest before invoking its command.

A later independent resolution batch has `status: "awaiting-evidence"` and its orientation
step numbers in `depends_on`. Review those results and stop conditions first. Execute a
batch **instead of** its constituent commands, not in addition to them. Pattern evidence
remains sequential, preserving checks such as direct neighbours before deeper paths.

### Metadata retrieval

The CLI requests only candidate templates with repeated `catalog dump --template NAME`.
A failed filtered request retries the unfiltered catalogue for older companion versions or
missing template names. Template filtering and preview were introduced in the same query
release, so successful filtered retrieval enables preview flags in generated commands.
Fallback retrieval conservatively disables `--preview` and `--limit` in both individual and
batch commands; envelope saving remains unchanged. This compatibility information stays
local to planning and does not alter the query catalogue payload or schema. Direct Python
`build_plan` calls also default to commands without preview unless explicitly enabled.
Missing metadata still degrades to an unannotated plan; a template
absent from an otherwise available catalogue is skipped with a generation-mismatch note.
Metadata requests do not open the dataset or execute a query.

## bundle

```json
{
  "schema_version": 1,
  "steps": ["steps/01-inventory-summary.json", "steps/02-models.json"],
  "question": "...",
  "findings": "findings.json",
  "dataset_revision": "9f0a12d4..."
}
```

`steps` is required and ordered. Each file must be a `schema_version: 1` envelope written by
`la-query --json -o`; anything else is refused rather than guessed at.

**Refused, deliberately:**

- envelopes from **two different datasets**, or from two different profile identities. A
  bundle spanning two vocabularies looks reproducible and is not, and nothing about the
  artifact would reveal it.
- `findings` missing any claim class. An empty class is a statement; a missing one is an
  omission.
- a claim in any class except `unknowns` that cites no step, or cites a step number the
  bundle does not contain.

`dataset_revision` is **caller-supplied** and recorded as such. This owner does not run git
and will not guess a revision; `la-connect datasets` reports the commit.

The response is the bundle document: `dataset` (id, revision), `profile` (id, version,
**verified**), `truncated`, `caveats`, `steps` (query, `query_id`, timestamp, row count,
truncation flag and a bounded row snapshot with `rows_omitted`), and `findings` when supplied.

`profile.verified` is read from the shared verification marker — the same
`$LINKED_ARCHI_STATE_DIR` path convention `la-profile verify` writes and the query owner
reads. A path convention shared by three owners and imported by none of them.
That marker records prior verification, not dataset revision freshness; the planner does
not use it to authorize orientation reuse.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | A plan or bundle was written to stdout. |
| `1` | Refused: unknown pattern, incoherent bundle, missing claim class, uncited claim. |
| `2` | Error: unreadable file, malformed request. |

Exit `1` is a judgement about the request, not a crash. Exit `2` means the request could not
be read at all.

## Versioning

`schema_version` is checked exactly on both sides. Fields may be added within version 1 only
while every documented field keeps its meaning; anything that changes an existing field's
meaning gets a new version, and a caller receiving an unexpected version must stop rather
than guess.

Readiness, dependency, decision and batch fields are additive within version 1. Existing
query-step commands remain strings and result envelopes keep their existing contract.
Refused candidates now appear as separate decisions instead of commands that could only
fail gating. Consumers must still resolve planning placeholders and inspect evidence and
refusals; the plan has never represented an unattended executable workflow.
