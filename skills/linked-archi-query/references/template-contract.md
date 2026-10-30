# Writing a template

First, check whether you need one. Core templates resolve **roles**, not terms, so a
custom ontology usually needs a profile entry and no new SPARQL. Write a template when
the *question* is new, not when the vocabulary is.

## Placeholders

| Placeholder | Expands to |
|---|---|
| `{{PREFIXES}}` | The profile's `PREFIX` block |
| `{{ROLE:x}}` | The primary IRI bound to role `x`, bracketed |
| `{{ROLES:x}}` | Every IRI in the chain, space-separated, for a `VALUES` block |
| `{{PATH:x}}` | The chain joined with `|`, for use as a predicate |
| `{{GRAPH_OPEN:role}}` | The opening of a group scoped to a named-graph role |
| `{{GRAPH_CLOSE}}` | Its closing brace |
| `{{GRAPH_VAR:role}}` | The variable that scope binds, for `SELECT` and `GROUP BY` |
| `{{MEMBERSHIP:var}}` | A pattern binding `?model` for `?var`, however this dataset expresses membership |
| `{{PARAM}}` | A typed parameter declared in the catalogue |

Placeholders inside `#` comments are left alone, so a header can name the mechanism it
uses without being rewritten into an example of its output.

### `{{MEMBERSHIP:var}}`

"Which model does this belong to" has two right answers, and which one applies is a fact
about the dataset rather than a choice a template gets to make. The profile's
`navigation.model_membership` decides; both expansions bind `?model`, so the template does
not branch:

- **`same-graph-colocation`** — expands to `?model a <model_class> .` and relies on the
  enclosing `GRAPH` scope, so it only ever appears inside one. This is the default because
  it holds for every converter.
- **`bounded-folder-tree`** — expands to a capped alternation over `part_of`
  (`?var (p|p/p|p/p/p) ?model .`) plus the model typing. Capped rather than `+` because
  SPARQL 1.1 has no `{1,n}` range and an unbounded path turns one wrong hop into a scan.

Pin the model with `VALUES ?model { {{MODEL_IRI}} }` before it to ask about one model.

**A template using this must declare `"membership": true` under `requires`.** Co-location
is a statement about named graphs, and without them it reduces to "`?model` is a model" —
true of every model in the dataset, so the query joins all of them and names the wrong
one. Measured against the flattened fixture, where a LeanIX element came back attributed
to the Backstage catalogue. Declaring the requirement turns that into a refusal naming
`bounded-folder-tree` as the way out. An ad-hoc `query literal` is cautioned rather than
refused, on the grounds that its author may know something the profile does not.

Do not hand-write a folder path instead. `core/provenance` finds the model by co-location
and a field session hand-wrote a bounded path for the same question; having both in
templates is how the two drift apart.

## Rules

**No `PREFIX` lines.** Use `{{PREFIXES}}`. A template carrying its own prefixes is how
one query ends up on a stale namespace while its neighbour is current — the drift that
made this package necessary.

**No vocabulary terms.** Use roles. A hardcoded IRI works until someone runs it against
a graph built from a different ontology version, and then returns nothing rather than
failing.

**Wrap patterns in a graph scope.** The profile decides whether that becomes a `GRAPH`
clause, a `VALUES` restriction or a plain group, so one template serves TriG and
flattened Turtle. Use `:any` when the point is to report which graphs exist.

**One scope per thing you look up.** Two roles bind two variables, so scoping to
`semantic` and `provenance` in one query is safe. Two lookups on the *same* role that
may live in different graphs need a numbered alias: `semantic2` scopes like `semantic`
and binds `?g_semantic2`.

**Give every scoped group a required triple.** A group containing only a `FILTER` and a
chain of `OPTIONAL`s has nothing to anchor the join to, and returns every column
unbound. This was observed, not theorised: one `OPTIONAL` worked and seven did not.
Prefer several small `OPTIONAL { scope { required triple } }` blocks to one scope
holding many optionals.

**Bound the result.** Every template takes a `LIMIT`.

**Avoid unbounded traversal.** A wildcard property path over every predicate is
unbounded exploration in disguise. Use the `iri_path` parameter type, which builds a
capped alternation from IRIs you validate.

**Return what an answer needs to cite itself**: labels, types, relationship kinds, and
the graph a row came from.

## The prose header

Three things, in this order:

```
# core/thing - The question, as a question?
#
# Answers: what a row means.
#
# Does NOT prove: the inference a reader will reach for and should not.
#
# ...design notes, if any decision here is non-obvious...
#
# Parameters: FOCUS_IRI, LIMIT
```

The middle line earns its place. It is where a reader learns that a modelled
relationship is not a runtime dependency, that an absent value means nobody recorded
it, or that a fact sheet is a record about a thing rather than the thing. Routing reads
these headers too.

If a shape in the query is surprising, say why in the header. A future reader will
otherwise simplify it back to the version that silently returned nothing.

## The catalogue entry

```json
"core/thing": {
  "file": "core/thing.rq",
  "stage": "analysis",
  "purpose": "One line, shown in listings.",
  "answers": "What a row means.",
  "does_not_prove": "The inference to avoid.",
  "parameters": {
    "FOCUS_IRI": {"type": "iri", "description": "the element to examine"},
    "LIMIT": {"type": "integer", "default": 200, "min": 1, "max": 2000}
  },
  "requires": {
    "roles": ["relationship_class", "label"],
    "graph_roles": ["semantic"],
    "capabilities": {"direct_rel_triples": true},
    "membership": false
  },
  "alternatives": ["core/other-thing"]
}
```

Stages, in the order an investigation moves through them: `orientation`, `resolution`,
`discovery`, `analysis`, `enrichment`, `quality`, `views`.

Parameter types: `iri`, `iri_list`, `iri_path`, `string`, `integer`.

**A `string` parameter with a fixed set of values takes `choices`,** and then a value
outside the list is refused at render time instead of being interpolated:

```json
"DIRECTION": {
  "type": "string",
  "default": "symmetric",
  "choices": ["a-only", "b-only", "symmetric"],
  "description": "which side to report"
}
```

Without it, an enum compared inside the query (`FILTER(?side = {{DIRECTION}})`) matches
nothing for a misspelling, and zero rows reads as "no differences" — a wrong answer wearing
the clothes of a finding. Two or more distinct values, and the default must be one of them.
`catalog show` prints the list.

**`caveat` attaches a warning to every result,** not just to the catalogue entry:

```json
"caveat": "This template returns CANDIDATES, not assertions. ..."
```

It rides in the envelope beside the profile's caveats, so it travels into whatever the
answer becomes rather than scrolling past on stderr. It is deliberately **opt-in**, and
distinct from `does_not_prove`: that one helps a reader *choose* a template and appears in
`catalog show`, while a `caveat` is for reading the rows. Adding one to every template
would train a reader to skip the line, and the profile caveats that matter would go with
it. Reserve it for a template whose rows are dangerous quoted bare —
`core/label-collisions` is the case it was built for.

**`requires` is the important part.** It turns a missing dependency into a refusal with
a reason, instead of an empty result that reads as "nothing exists". Declare every role
the template names, every capability its shape assumes, and `membership: true` if it uses
`{{MEMBERSHIP:var}}`.

**`alternatives` should name a template that answers the same question from evidence a
plainer dataset does have.** A refusal that offers nowhere to go is only half an answer.

Add `notation` for a notation-specific template, and put the file under
`assets/templates/notation/<notation>/`.

## Downstream project catalogue

Keep extensions beside your own APM/project, not in an installed skill. A JSON
catalogue uses the same `version: 1` / `templates` shape as the bundled
`assets/templates/catalog.json`. Each entry's `file` is a `.rq` path relative to
that JSON file's directory. Give every entry a project namespace such as
`acme/capability-map`; `core/`, `notation/` and `custom/` are reserved. A project
catalogue cannot replace a bundled or another project template. A file path cannot
escape the catalogue directory, including by symlink.

```bash
python3 path/to/la-query catalog show acme/capability-map \
  --catalog queries/catalog.json --profile profiles/acme.yaml
python3 path/to/la-query query run acme/capability-map \
  --catalog queries/catalog.json --profile profiles/acme.yaml --data graph.trig
```

`--catalog` is explicit on each `catalog list/show/dump` and `query render/run/batch`
invocation and may be repeated for several independent catalogues. It is never
discovered from the environment or the profile. In a batch, the same selected
catalogues resolve all template entries before any execution. The loader checks a
positive integer `LIMIT` bound and an outer trailing `LIMIT {{LIMIT}}`, required
role/graph/membership declarations, and alternative names. Rendering then applies
profile gates, parameter typing and read-only validation. These are mechanical
checks, not proof that a query's joins, scope or answer semantics are right. Test
project templates against representative graph data and use read-only credentials
for endpoints: SPARQL read-only validation is not an authorization boundary.

`linked-archi-analyse` does not register project templates in its bundled planning
patterns. A custom template can be chosen as an explicit analyst-led query step;
automatic planner integration is a separate extension. See the complete example in
`examples/fixed-graph-downstream/` in the package repository.

## Model questions

A question in a published question set (`arch:QuestionSet`) is a catalogue entry too, and
the source of truth for what it asks: its label is the question, `arch:answers` and
`arch:doesNotProve` say what a row means and what it does not, and it names the concerns,
stakeholders and viewpoints it serves. Write a new question there, not as a template, when
the question is about a Linked.Archi model: la-gram and the deliverable generator ask the
same set.

How the catalogue reads one:

- **Name.** `dcterms:identifier`. A question and a template of one name are one entry with
  two implementations: `query run` asks the question where the dataset fits it - read as
  one graph, with what its query reads present - and runs the template elsewhere. A
  question asking something a template does not takes a name of its own.
- **Query.** Written for one graph, the model and its metamodel together; no placeholders,
  no `GRAPH` scoping, prefixes from the set's `sh:declare`. It is asked of the dataset read
  as one graph: local data on request (each triple once, however many graphs hold it), an
  endpoint only with `capabilities.union_default_graph`.
- **Parameters.** One per `sh:parameter`, every one an IRI, named after the core property
  it is declared on: `arch:focus` is `FOCUS_IRI`, `arch:model` `MODEL_IRI`, `arch:view`
  `VIEW_IRI`, `arch:viewpoint` `VIEWPOINT_IRI`, `arch:conceptType` `TYPE_IRI`, `arch:from`
  and `arch:to` `FROM_IRI` and `TO_IRI`. A parameter declared `sh:optional` may be left
  unset, and the question then answers for every value. Each is pre-bound with `VALUES`
  at the start of the outermost `WHERE` group, as la-gram and meta's question check bind
  it. `LIMIT` is `arch:defaultLimit`.
- **Requirements.** Read from the query: a published unqualified predicate needs
  `direct_rel_triples`, `rdf:reifies` needs `rdf_reifies`, `arch:inModel` needs
  `part_of_model_edge`. A refusal names what lifts it. A question declaring
  `arch:ModelAndMetamodelDataset` is also checked when it runs, with an ASK per thing it
  reads: each `arch:requiresMetamodel` ontology, a viewpoint catalogue where it reads
  viewpoints, unqualified forms where it reads them.
- **Notation.** `notation/<slug>/...` makes it a notation entry, gated on the vocabulary of
  its one `arch:requiresMetamodel`, as a notation template is on `notation_namespace`.

The bundled sets are copied from linked-archi-meta, with an index of them that listing reads
without an RDF library; `make questions` refreshes both, and a test fails when they
disagree. A project's own set is passed with `--catalog questions.ttl`, read with
pyoxigraph, and follows the extension rules: project namespace, no taken name, a
`arch:doesNotProve` on every question.

## Testing

The suite fails when a catalogued template has no test case, so the catalogue cannot
drift untested. Add a case to `tests/test_templates.py` with the parameters to use and
a minimum row count.

**Upstream repository development only.** `tests/` and `make check` live in the package
repository, not in an installed skill. Downstream authors keep their own tests with
their own catalogue; adding a template to an installed copy remains unsupported.

Expected counts are **floors**, not assertions about your data. If a template legitimately
returns nothing against the fixtures, that is a fixture gap worth fixing rather than a
count worth lowering — a template that returns nothing is one the suite cannot
distinguish from a broken one. `fixtures/PROVENANCE.md` records how the fixtures are
selected and how to extend them.

Run:

```bash
make check
python3 scripts/la-query catalog list --profile linked-archi-default --why
```

`catalog list` fails if a template is on disk without a catalogue entry, or catalogued
without a file. Templates under `assets/templates/custom/` are exempt — and therefore
untested and invisible to routing.
