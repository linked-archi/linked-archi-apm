# Formats, and which preserve graph identity

| Extension | Format | Keeps graphs |
|---|---|---|
| `.trig` | TriG | yes |
| `.nq` | N-Quads | yes |
| `.nquads` | N-Quads | yes |
| `.ttl` `.turtle` | Turtle | no |
| `.nt` | N-Triples | no |
| `.rdf` `.xml` | RDF/XML | no |
| `.jsonld` `.json` | JSON-LD | no |

The extension is how the format is chosen, so a TriG file named `.ttl` loads as Turtle and
loses its graphs without complaint. If a file will not parse, check that its extension
matches its content before anything else.

`.json` and `.xml` are loadable but are also every `package.json` and `pom.xml` in a tree, so
discovery skips them unless asked by name (`--extension json`). An explicit `--data` path or
`$LINKED_ARCHI_DATA` always works whatever the suffix.

## Why TriG is worth insisting on

The semantic, views and provenance split is in the data, not a convention. That has three
consequences worth the format choice:

- **Layout facts cannot leak into a semantic query.** Re-rendering every diagram invalidates
  nothing, and no impact analysis can accidentally depend on visual nesting.
- **Provenance is separable.** "Where did this come from" is answerable without the answer
  being polluted by conversion metadata.
- **Scoping is possible at all.** Turtle collapses everything into the default graph, and
  from inside a query an empty graph and a graph with no matching elements look identical.

Flattening throws all three away. It is recoverable — a `single`-layout profile queries
flattened data correctly and says so with a caveat — but the separation cannot be rebuilt
from the flattened file.

## When a load reports fewer quads than expected

Almost always a partial export rather than a small enterprise. Confirm which models are
actually present with the query owner's `core/models`, before anything estate-wide is said.

Parsing can also stop early on a malformed file. `--lenient` relaxes RDF parsing so what can
be read is read, and the result says it was lenient — it never relaxes query safety.
