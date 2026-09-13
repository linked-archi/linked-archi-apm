# Connect machine contract

`la-connect _machine` is the stable boundary for automation and sibling orchestration.
The leading underscore marks it as **machine-facing, not private**: it is documented,
versioned, and depended on across process boundaries by `linked-archi-query` and
`linked-archi-profile`. Human-facing output belongs to `datasets` and `connect`.

One JSON object on stdin, one JSON object on stdout, diagnostics on stderr. Every
contract is `schema_version: 1`. Unknown fields, booleans in integer fields, blank
strings and missing required fields fail closed.

## Commands

| Command | Purpose |
|---|---|
| `la-connect _machine execute` | Execute one read-only query against one target |
| `la-connect _machine execute-many` | Execute several queries against one opened target |

`execute-many` opens the target once. For a local file that means parsing it once, which
is the whole reason it exists: `la-profile verify` issues a dozen probes and paying the
load cost per probe would make verification the slowest step in the package.

## Request

```bash
printf '%s' "$REQUEST" | python3 scripts/la-connect _machine execute
```

```json
{
  "schema_version": 1,
  "query": "SELECT ?s WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 10",
  "target": {
    "data": ["/absolute/or/relative/graph.trig"],
    "endpoint": null,
    "timeout_ms": 30000,
    "lenient": false,
    "store": null
  }
}
```

`execute-many` replaces `query` with `queries`, a non-empty array of strings.

`target` is **exactly** connect target version 1 — `data`, `endpoint`, `timeout_ms`,
`lenient`, `store`, and nothing else. Any other key is rejected rather than ignored, which
is what lets `la-source` hand its `target` through unchanged: a caller that merges manifest
fields into it gets an error instead of a silently different execution.

`store` is the one optional key. Omitting it is not the same as sending `"memory"`: absent
and `null` both mean "defer to `$LINKED_ARCHI_STORE` in the connect process", so a caller
written before this field existed keeps working and keeps deferring. Sending a mode by name
overrides the environment.

| Field | Rule |
|---|---|
| `data` | Array of non-empty strings. Files merge into one dataset. |
| `endpoint` | `null`, or an HTTPS URL that passes the same endpoint validation as `--endpoint`. |
| `timeout_ms` | Positive integer. Default 30000. Endpoint requests only; a local load is bounded by the file, not a clock. |
| `lenient` | Boolean. Default `false`. Relaxes RDF parsing, never query safety. |
| `store` | `null`, or one of `memory`, `cached`, `readonly`, `refresh`. Absent or `null` defers to `$LINKED_ARCHI_STORE`. Where a local store comes from; ignored for an endpoint, but still validated there, because a silently ignored option reads as a setting that had no effect. An unknown mode is refused by name. See [store-modes.md](store-modes.md). |

**Exactly one of `data` or `endpoint`.** Both, or neither, is an error. Two targets in one
request would make `dataset_id` ambiguous, and a result whose dataset cannot be named is
not evidence.

## Response

`execute` returns one raw transport result:

```json
{
  "schema_version": 1,
  "form": "SELECT",
  "variables": ["s"],
  "rows": [{"s": "https://example.org/la/bpmn/order-fulfillment"}],
  "boolean": null,
  "triples": null,
  "elapsed_ms": 4,
  "load_ms": 1840,
  "dataset_id": "graph.trig",
  "named_graphs_present": true,
  "description": "local store: 1 file(s), 1425 quad(s), 19 named graph(s)\n  graph.trig\n  store: parsed into memory in 1840 ms (mode memory)"
}
```

`execute-many` returns `{"schema_version": 1, "results": [ ... ]}`, one entry per query,
in request order. **Only the first entry carries a non-zero `load_ms`.** The target is
opened once, so there was no load to attribute to the rest; stamping each of them would
make one parse read as several and report more loading than the wall clock contained.
Summing `load_ms` across the results therefore gives one load.

| Field | Meaning |
|---|---|
| `form` | `SELECT`, `ASK`, `CONSTRUCT` or `DESCRIBE`, as the query was parsed. |
| `variables` | Projected variable names for `SELECT`; empty otherwise. |
| `rows` | Bindings as strings, one key per projected variable. An **unbound** variable is present with an empty string, so every row has the same keys and a caller can index by variable name without checking. Distinguishing "unbound" from "the empty literal" is not possible through this contract; a query that needs that distinction should project a `BOUND()` flag. |
| `boolean` | The answer for `ASK`; `null` otherwise. |
| `triples` | Serialized graph for `CONSTRUCT`/`DESCRIBE`; `null` otherwise. |
| `elapsed_ms` | Execution only, excluding process start and target load. Read it beside `load_ms`; alone it is not the cost of the command. |
| `load_ms` | Milliseconds spent obtaining the store before the query ran, as distinct from running it. `0` for an endpoint, where the question does not apply, and near-zero on a cached local store. Reported because the two are not comparable work: on a large local dataset the load can exceed the query by orders of magnitude while `elapsed_ms` shows single digits. |
| `dataset_id` | What was queried, stable enough to cite in an answer. |
| `named_graphs_present` | Whether the loaded data has named graphs, or `null` for an endpoint. Callers use it to warn that a graph-scoped query will behave differently. |
| `description` | Multi-line human-readable summary of the target — store kind, counts, one line per file, then where the store came from and what that cost, and the cache directory when one was used. Diagnostics only; do not parse it. Read `load_ms` for the number and `store` for the setting. |

There is no `row_count` on the wire. Count `rows`, or read `boolean`. A count field would
be a second answer to a question the rows already settle.

## Read-only enforcement

Connect **never decides** whether a query is read-only. Before any backend sees query
text, it delegates every query to `la-query _machine lint` and refuses on rejection. One
enforcement point, in the owner of query policy, reached over this same contract.

That delegation has a fixed 30-second deadline and is a hard dependency: if
`linked-archi-query` cannot be resolved, `_machine execute` fails rather than executing
unchecked. `la-connect doctor` reports whether it can be reached.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | A structured result was written to stdout. |
| `2` | Malformed request, rejected target, unresolvable companion, refused query, timeout, parse failure, or backend error. Message on stderr, no traceback. |

Exit `1` is unused here. A query that runs and matches nothing exits `0` with zero rows:
an empty result is a finding, and turning it into a failure code would invite callers to
treat "nothing matched" as "something broke".

## Versioning

`schema_version` is checked exactly, on both sides. A caller receiving an unexpected
version must stop rather than guess. Fields may be added within version 1 only when every
documented field keeps its meaning; anything that changes an existing field's meaning gets
a new version.

`store` and `load_ms` were added under that rule. Nothing already documented changed
meaning: `elapsed_ms` timed only execution before and still does, and a request that omits
`store` behaves exactly as it did.

The rule cuts differently for each side, which is worth stating because it looks like a
contradiction otherwise. **This version always emits `load_ms`**, so it is not optional
output. But a *consumer* should treat it as optional on input, because a `linked-archi-query`
newer than the `linked-archi-connect` it finds on disk will meet a producer that predates
the field — skills are installed and updated independently here, so version skew between
siblings is normal. Refusing an otherwise valid result over a missing timing field would
trade a working answer for a tidy schema. The same asymmetry applies to any field added
within a version: required of this producer, tolerated as absent by a careful consumer.
