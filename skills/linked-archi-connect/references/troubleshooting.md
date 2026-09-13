# When attaching goes wrong

| Symptom | Usual cause |
|---|---|
| Nothing parses | Extension does not match content. A `.ttl` holding `GRAPH` blocks is TriG misnamed. |
| Loads, every query returns nothing | Turtle, so everything is in the default graph. Convert to TriG, or use a `single`-layout profile. |
| Far fewer quads than expected | Partial export. Confirm with `core/models` which models are actually present. |
| Two elements that should be one | Not a load problem. Cross-tool identity is asserted, never derived — see `core/identity-audit`. |
| Endpoint returns HTTP 400 | Often a server that rejects `POST` form encoding, or a query-only endpoint given an update. The refusal text is passed through. |
| `datasets` finds nothing | The layout is unconventional. Widen with `--search-dir` / `--max-depth` / `--extension`; the negative result names all three. Do not fall back to a filesystem search. |
| A companion cannot be resolved | `la-connect doctor` names it. Report the missing skill; do not work around it. |

## When there is nothing to attach

Stop. Produce candidate queries with
`python3 ../linked-archi-query/scripts/la-query query render`, label them clearly as
**unexecuted**, and say what would be needed to run them. Do not describe results you have
not seen, and do not substitute a filesystem search for a dataset.

## Refreshing from source models

A rebuild is the converters' job, not this skill's. The pipeline reads the source models and
emits the dataset; point the user at it rather than assembling RDF here:

```bash
cd tools/converters/example-architecture-project
BASE_IRI=https://example.org/la/ ./convert-all.sh
```

If the graph is remote rather than absent, that is `linked-archi-source`: it materialises a
verified copy and hands back a target this skill accepts unchanged.

## What this skill will not do

- **Not read around the graph.** No grepping a `.trig`, no loading it with another RDF
  library to peek. Those paths skip read-only enforcement, profile resolution and the dataset
  identity that make an answer checkable.
- **Not choose between candidate datasets.** `datasets` lists and selects nothing; ordering
  is a weak signal and newest is not most correct.
- **Not decide profile semantics.** Whether a profile fits is `la-profile verify`, and which
  one to start from is `la-profile recommend`.
