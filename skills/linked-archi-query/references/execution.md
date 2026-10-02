# Execution modes and bounded evidence

Read only for batching, output controls or ad-hoc queries. Investigation decisions belong
to analyse; execution and the evidence envelope belong to query.

## Output without duplicate context

Default output is TSV, with escaped tabs/newlines and `#` lines for counts, caveats and
citation. Markdown (`--format md`) is for human presentation. JSON (`--json` or
`--format json`) is the full envelope; RDF terms in every format are lexical values,
not a W3C SPARQL results document. `--format` wins over `--json`.

`-o FILE` always saves the full JSON envelope. Add `--preview --limit 20` to print bounded
TSV in the same call without rereading that file. On `run` and `literal`, preview requires
`-o`. For CONSTRUCT, preview bounds physical output lines, not saved triples. Neither
preview nor the display limit changes the executed query, saved rows or query hash.
Keep warnings, citation and the distinction between display omission and query truncation.

`--set LIMIT=N` is the template's result cap. The lower of the parameter maximum and
`profile.limits.max_row_limit` wins; explicit excess is refused, an excessive default
is clamped with a caveat. A result cap does not guarantee bounded computation. `--limit`
only caps display and does not shorten JSON or the saved envelope.

## Batch only independent, bound queries

```json
{"schema_version": 1, "queries": [
  {"id": "inventory", "template": "core/inventory-summary", "out": "steps/01-inventory.json"},
  {"id": "models", "template": "core/models", "out": "steps/02-models.json"}
]}
```

```bash
python3 scripts/la-query query batch orientation.json --profile linked-archi-default \
  --data graph.trig --preview --limit 20
```

Each entry takes exactly one of `template`, `file` or `query`, plus optional `id`, `set`
and `out`. Use `out` for **every** investigation step. Batch-level `-o` saves the summary,
not the evidence envelopes. `--preview` prints a bounded result for each entry, including
its warnings, truncation and citation; the default batch summary stays compact.

All entries are rendered and validated read-only before any executes. One local load
serves the batch; only its first result carries `load_ms`. A batch has no result-to-input
substitution: resolve names and review evidence before batching their dependent queries.
Do not combine stages merely because their parameters happen to be filled in.
For project-owned template entries, pass the same explicit `--catalog queries/catalog.json`
to `query batch` that you used when inspecting them. One selected catalogue set applies
to every entry; a batch entry cannot silently select a different template source.

Do not switch to cached stores just to avoid parsing. Analytical performance differs;
consult the connect owner's `references/store-modes.md` before changing modes (D19).

## Ad-hoc queries

Prefer adapting a tested template. If none covers the request, read `graph-shape.md` and
`template-contract.md` in this reference directory before writing a query. Directive-based
input begins with `{{PREFIXES}}`: nothing injects prefixes automatically. Role directives bind full IRIs,
but adding a prefixed term without the prefix directive still fails.

```bash
python3 scripts/la-query query render core/neighbours-qualified --profile linked-archi-default \
  --set FOCUS_IRI=https://example.org/la/element/known-id -o question.rq
```

Adapt that rendered text if needed, then lint the expanded query before execution:

```bash
python3 scripts/la-query lint question.rq --profile linked-archi-default \
  --data graph.trig --data shapes.ttl --data vocabulary.ttl
python3 scripts/la-query query literal --profile linked-archi-default --data graph.trig \
  --file question.rq -o steps/custom.json --preview --limit 20
```

Standalone `lint` requires expanded SPARQL: it rejects unresolved `{{...}}` directives,
and `--profile` does not render them. `query literal` expands directive-based input and
enforces read-only before transport, but does not perform the optional SHACL path check.
For a pre-execution path check, start from rendered template text as above.
Never infer absence from an unreviewed empty custom query:
check syntax, graph scope, relationship direction and whether the path is possible.
Negative tests inside a graph see that graph, not the whole dataset. Give `NOT EXISTS`,
`MINUS` and `EXISTS` their own intended graph scope, for example
`FILTER NOT EXISTS { GRAPH ?any { ... } }` when absence across named graphs is intended.
An `OPTIONAL` with an explicit match flag may be cheaper on large candidate sets; inspect
semantics before changing it. Do not conflate a document/fact-sheet record with its subject.

`lint --data` / `--endpoint` also reports SHACL path feasibility; ordinary query execution
does not pay for this check. “Impossible path” requires complete declared namespace
coverage and a class hierarchy. “Not checked” means no verdict, not a valid path.
Even a judged path is provisional: namespace presence does not prove whole documents
were attached. Retain that caveat; profile verification reports missing assets.
Disclose ad-hoc/adapted execution and show its final SPARQL with source provenance.
