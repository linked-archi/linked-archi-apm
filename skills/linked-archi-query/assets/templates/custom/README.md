# Your own templates

A new vocabulary usually needs a custom profile, not new SPARQL: the bundled queries
resolve roles through the profile. Write a template when the *question* is new.

## Downstream APM: keep queries in your project

Do not edit an installed `linked-archi-query` skill. Put `catalog.json` and its `.rq`
files together in your own project or APM package, and opt in to that catalogue on
**each** command that uses it:

```bash
python3 path/to/la-query catalog show acme/my-question \
  --catalog queries/catalog.json --profile profiles/acme.yaml
python3 path/to/la-query query render acme/my-question \
  --catalog queries/catalog.json --profile profiles/acme.yaml --set FOCUS_IRI=https://example.org/focus
python3 path/to/la-query query run acme/my-question \
  --catalog queries/catalog.json --profile profiles/acme.yaml --data graph.trig \
  --set FOCUS_IRI=https://example.org/focus
```

The flag also works with `catalog list`, `catalog dump` and `query batch`; repeat it to
add more than one project catalogue. It **adds to** the bundled catalogue, without
overriding a bundled name. Names need a project namespace such as `acme/my-question`;
`core/`, `notation/` and `custom/` are reserved. `file` is relative to the project
catalogue's directory, cannot escape it (including through symlinks), and must exist.
An external catalogue is never discovered automatically. Pass the same `--catalog`
value during selection, rendering and execution. `linked-archi-analyse` does not add
project templates to its built-in planning patterns automatically; choose and run
them explicitly as analyst-led steps. Use full names such as `acme/my-question`;
basename shortcuts can become ambiguous across catalogues.

The loader checks the catalogue shape, a positive bounded `LIMIT {{LIMIT}}` at the end
of each template, declared role/graph/membership dependencies, and valid alternative
names. Rendering still applies profile gates, typed parameters and read-only validation.
Test your own query's semantics against representative data; these checks cannot prove
that joins, scope or the answer are correct. Treat external SPARQL as **trusted project
code**. Read-only validation is not an isolation or authorization boundary; use
read-only endpoint credentials for remote stores.

For a complete downstream package with a fixed graph, custom profile, selected skills
and project catalogue, see `examples/fixed-graph-downstream/` in the package repository.

## Upstream contribution: change the package repository

To add a bundled template for all users, work in the package checkout. A scratch
template under `assets/templates/custom/` is exempt from the bundled completeness check
and is not reachable by routing. To publish it, add an entry to
`assets/templates/catalog.json` and a case in `tests/test_templates.py`, then run
`make check`. Do not make this change in an installed skill directory.

Follow [the template contract](../../../references/template-contract.md): include a
header describing what the query answers and does not prove, use `{{PREFIXES}}`,
role and graph directives rather than remembered vocabulary, declare `requires`,
and bound the result with `LIMIT`. Core profile roles normally cover vocabulary
variation; a new template should add a new question rather than duplicate a bundled
one for a different ontology spelling.
