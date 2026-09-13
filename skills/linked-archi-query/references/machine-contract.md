# Query machine contract

`la-query _machine` is the stable boundary for automation and sibling orchestration. The
leading underscore marks it as **machine-facing, not private**: it is documented,
versioned, and `linked-archi-connect` depends on it before any backend sees query text.
Human-facing output belongs to `catalog`, `query`, `lint` and `doctor`.

One JSON object on stdin, one JSON object on stdout, diagnostics on stderr. The contract
is `schema_version: 1`, checked exactly.

## Commands

| Command | Purpose |
|---|---|
| `la-query _machine lint` | Decide whether one query, or a batch, is read-only |

One operation, and deliberately the smallest one in the package. This owner holds the
read-only policy; connect holds the transport. Publishing the *decision* rather than an
execution entry point is what keeps that single enforcement point single.

Rendering is **not** offered here. A rendered query is inseparable from its catalogue
entry, its parameter typing and its refusal reasons, so a caller that wants a query should
run `query render` or `query run` and read the envelope. Exposing a render contract would
invite a second consumer to bind parameters its own way.

## Request

```bash
printf '%s' "$REQUEST" | python3 scripts/la-query _machine lint
```

One query:

```json
{"schema_version": 1, "query": "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}
```

A batch, decided in one process:

```json
{"schema_version": 1, "queries": ["SELECT ?s WHERE { ?s ?p ?o }", "ASK { ?s ?p ?o }"]}
```

**Exactly one of `query` or `queries`.** Both, or neither, is an error rather than a
guess about which the caller meant. `queries` must be non-empty, and every entry a
non-empty string.

Query text arrives on **stdin, never in argv**: a process list is readable by other
processes on the host, and a query can carry identifiers from a private model.

## Response

For `query`:

```json
{"schema_version": 1, "accepted": true}
```

```json
{
  "schema_version": 1,
  "accepted": false,
  "reason": "SPARQL Update operation is not allowed (found INSERT). This package executes read-only queries only."
}
```

For `queries`, one decision per query in request order:

```json
{
  "schema_version": 1,
  "decisions": [{"accepted": true}, {"accepted": false, "reason": "..."}]
}
```

What a caller may rely on:

- **`accepted` is the whole decision.** `true` means the text parsed as a read-only form
  and contains no write, update, load, federation or unbounded construct this package
  forbids. It is not a statement that the query is *correct*, will return rows, or suits
  the dataset.
- **`reason` is present only when `accepted` is `false`,** and names the construct that
  caused the refusal. It is written to be shown to a person, so a caller can pass it
  through instead of inventing a message.
- **A rejection is exit `0`.** The command ran and answered; the answer was "no". Only a
  malformed request or a broken invocation is a non-zero exit. Conflating the two is how a
  caller ends up treating an unparseable request as a refused query.
- **Batch decisions are positional**, one per request entry, and a batch is rejected as a
  whole only when the *request* is malformed.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | A decision was written to stdout, whether accepted or refused. |
| `2` | Malformed request: not JSON, wrong `schema_version`, both or neither of `query`/`queries`, an empty string. Message on stderr, no traceback. |

Exit `1` is used by the *human* commands, where it means refused — an unsupported template
or a query that failed the read-only check. `_machine lint` does not use it, because here a
refusal is the payload rather than the outcome.

## Callers and deadlines

`linked-archi-connect` calls this before every execution, with a fixed 30-second deadline,
and fails closed: if this skill cannot be resolved, connect refuses to execute rather than
executing unchecked.

In the other direction, this owner calls its companions over their contracts —
`la-profile _machine resolve` for the profile, `la-connect _machine execute` /
`execute-many` for transport. Those subprocess deadlines are derived from the request:
60 seconds of margin plus the target's `timeout_ms` per query, so a large batch is not
killed for being large. See
[connect's machine contract](../../linked-archi-connect/references/machine-contract.md) and
[profile's](../../linked-archi-profile/references/machine-contract.md).

## Versioning

`schema_version` is checked exactly, on both sides. Fields may be added within version 1
only while every documented field keeps its meaning; anything that changes an existing
field's meaning gets a new version. A caller receiving an unexpected version must stop
rather than guess.
