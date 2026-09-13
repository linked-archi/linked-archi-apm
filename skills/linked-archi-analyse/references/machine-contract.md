# Analyse machine contract

`la-analyse _machine` is the stable boundary for automation and sibling orchestration. The
leading underscore marks it as **machine-facing, not private**: it is documented and
versioned, like every other owner's. Human-facing output belongs to `plan`, `bundle`,
`render` and `doctor`.

One JSON object on stdin, one JSON object on stdout, diagnostics on stderr. The contract is
`schema_version: 1`, checked exactly.

**This owner executes nothing.** No dataset is opened, no SPARQL is issued, no transport is
used. `plan` emits the commands to run; `bundle` reads what those commands wrote.

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
  "steps_dir": "steps"
}
```

Only `question` is required. `mode` names a pattern instead of routing to one and is
validated against `assets/patterns.json`. `data` and `endpoint` are **recorded into the
emitted commands, not used** — nothing here reads them.

The response is the plan document:

```json
{
  "schema_version": 1,
  "question": "...",
  "pattern": "impact-and-dependency",
  "pattern_title": "Impact and dependency",
  "pattern_file": "references/patterns/impact-and-dependency.md",
  "ranked": [{"pattern": "impact-and-dependency", "score": 2, "matched": ["retire", "depends on"]}],
  "budget": 12,
  "planned_steps": 9,
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
      "command": "la-query query run core/inventory-summary --profile ... --json -o steps/01-inventory-summary.json"
    }
  ]
}
```

What a caller may rely on:

- **`command` is the whole point.** It is complete and runnable, including `--json -o` from
  the first step, because the envelope is the evidence and a terminal scroll cannot be turned
  back into one.
- **`availability`** is `available`, `caveat`, `refused`, or `unknown`. `refused` carries the
  reason in `note` and the documented replacements in `alternatives`, so a template this
  dataset cannot support is swapped **at planning time** rather than mid-investigation.
- **`annotated: false`** means `linked-archi-query` was not reachable, so no parameters or
  availability could be read. The plan is still ordered and still names templates; `notes`
  says what is missing. It degrades rather than failing.
- **A parameter value wrapped in `<…>` is a placeholder**, never a value. It names where the
  value comes from — "resolved in the resolve step, from core/resolve-element". Nothing is
  invented, which is the whole reason the resolve step exists.
- **`pattern: null`** means no trigger matched. The orientation steps are still correct; the
  caller should name a `mode` or report that this package has no method for the question.
- **`over_budget`** marks steps beyond `budget`. They are marked rather than dropped, so what
  is being given up stays visible.
- **`pattern_stop_when`** belongs to the investigation, not to any one step. Distributing
  those conditions across steps would read as per-step rules and mislead.

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
