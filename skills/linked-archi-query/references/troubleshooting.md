# When a query does not do what you expect

Ordered by how often each turns out to be the cause. Note that the first four
symptoms all produce a query that runs cleanly and returns rows — or no rows — without
any error, which is why the diagnosis has to be deliberate.

## Every query returns nothing

| Check | Command |
|---|---|
| Is anything loaded | `python3 scripts/la-query query run core/inventory --profile ... --data ...` |
| Does the dataset have named graphs | `python3 ../linked-archi-connect/scripts/la-connect connect --data ...` |
| Does the profile match the dataset | `python3 ../linked-archi-profile/scripts/la-profile verify --profile ... --data ...` |

Almost always the dataset is Turtle. `.ttl` has no graph boundaries, so everything
landed in the default graph while the profile scopes to named graphs, and every scoped
pattern matches nothing. Convert to TriG, or use a `single`-layout profile.

`python3 ../linked-archi-connect/scripts/la-connect connect` reports the loaded graph shape. `python3 ../linked-archi-profile/scripts/la-profile verify` compares
that evidence with the profile and refuses a mismatch with exit code 1 before a
query can turn it into a misleading empty result.

## One query returns nothing, others work

1. **A guessed IRI.** Resolve it: `core/resolve-element`. Never build an IRI from a
   label.
2. **A guessed class or predicate IRI.** The notation ontologies carry their version in
   the namespace, so `am:` and `am4:` spell the same concept differently. Take class
   IRIs from `core/inventory` and predicates from `core/discover-predicates`.
3. **The wrong relationship form.** If you hand-wrote a `?source ?predicate ?target`
   pattern, it is probably not there — direct triples are opt-in. Use
   `core/neighbours-qualified`.
4. **Two graph scopes sharing one variable.** If you hand-wrote a query scoping to two
   roles, a single `?g` requires one graph IRI to end in two suffixes at once. Use
   `{{GRAPH_OPEN:semantic}}` and `{{GRAPH_OPEN:provenance}}`, which bind separate
   variables, and add a trailing digit for two independent scopes on the same role.

## Counts look doubled

The direct and qualified relationship forms were unioned in one query. The same
relationship appears in both when direct triples are emitted. Query one or the other,
never both.

## A count sits exactly on a round number

That is the row limit, not a total. It is a floor: report "at least". `to_table` says
so when it detects it.

## A cross-notation join is empty

Missing identity assertion, not a broken query. Cross-tool equivalence cannot be
derived and no converter emits it. Run `core/identity-audit`; if it is refused, the
dataset has no reconciliation step and the join is not answerable yet.

## Provenance is empty for some elements

Either that model was converted without a provenance graph — worth reporting as
missing evidence — or the dataset is flattened, in which case there are no graph
boundaries and provenance cannot be attributed to a particular model at all.

## A template is refused

Read the reason and use the named alternative. Refusals are answers: they mean the
dataset cannot support the question.

Do **not** set the capability true to make it go away, and do not hand-write the query
the template would have produced. Both give you an empty result that looks like a
finding, which is the failure the refusal prevented.

If you believe the capability really is present,
`python3 ../linked-archi-profile/scripts/la-profile verify` will say so —
it reports "claimed false but present" as a warning precisely so an over-cautious
profile can be corrected on evidence rather than on assumption.

## A label column is empty

The label lookup is scoped to a graph that does not hold labels. Labels live in the
semantic graph with their elements; assertions about elements may live elsewhere. If
the two sides of a query come from different models, they are in different semantic
graphs, so they need independent scopes.

## Results include something that looks like an id but is not

`_:id` is a blank node. Its identifier is generated per parse and means nothing outside
the document. Folder list items and view styles are blank nodes.

## An element appears twice with different labels

Language tags. `skos:prefLabel` is language-tagged and one element may carry several.
Filter on the profile's `label_language`, or report both.

## A FILTER on a label matches nothing, and reports no error

The worst failure mode in this toolkit, because there is no error at all — just an empty
result that reads as absence.

Labels from real models contain **real newlines**. A BPMN lane called `Order\nSourcing` is
one literal with a line break in it, so this silently matches nothing:

```sparql
FILTER(?laneLabel != "Order\nSourcing")     # never matches; no error
```

Escapes in a SPARQL literal are not the same characters as the bytes in the data, and
leading or trailing whitespace differs too. Two ways out, in order of preference:

1. **Restrict on IRIs, never on multi-line labels.** Resolve the label to an IRI once with
   `core/resolve-element`, then use `VALUES ?focus { <iri> }`. IRIs have no whitespace
   surprises.
2. If you must match text, compare normalised: `CONTAINS(LCASE(?label), "sourcing")` rather
   than equality against a literal you retyped.

The same applies to `=`, `!=` and `IN` on any label. If a label-based filter returns
nothing, assume the filter before you assume the data.

## A count is exactly the row limit

It is a floor, not a total. Say "at least". The runtime prints this before and after the
table and sets `truncated` in the envelope, but the number itself looks like an answer, so
it is worth naming: 25 rows from `core/resolve-element` means "25 or more".

Check `truncated`, not the number against 100. The limit that produced it is the query's —
each template declares its own default, and they run from 25 to 300 — so there is no single
figure to recognise. `--limit` is not it: that caps the printed table only.

## Absence read from a truncated result

Related and more dangerous. Do not conclude "X is not here" by scanning a table that was cut
off at the row limit, and do not grep truncated output for a term. Raise the query's cap with
`--set LIMIT=N`, use `--json` to see every row that was fetched, or ask a question whose
answer is a count rather than a list. A field session grepped a truncated view listing,
found no match, and nearly reported that a whole set of diagrams did not exist.

Raising `--limit` instead is the trap: it prints more of what came back and does not fetch
more, so a result cut off by the query's own `LIMIT` looks the same at any display width.

## The query is rejected before running

| Message | Meaning |
|---|---|
| unresolved placeholders | Rendered text still contains `{{...}}`. Render through the CLI, not by hand. |
| `Prefix not found` on an ad-hoc query | The query has no `{{PREFIXES}}`. Nothing is injected for you. Put it first — and do not trust the character offset in the message, which counts into the rendered text after the other directives expanded, not into what you typed. |
| SPARQL Update is not allowed | The query contains an update keyword. This package is read-only. |
| federated SERVICE calls are not allowed | The query would send this graph's data to an endpoint outside the profile's scope. |
| parameter is not an absolute IRI | Resolve the label to an IRI first. |
| `LIMIT: N exceeds the maximum M` | The **template's** ceiling. `catalog show <template>` prints it. Ask for less, or raise `max` for that parameter in `catalog.json`. Raising `max_row_limit` will not move it. |
| `LIMIT: N exceeds max_row_limit M in profile ...` | The **profile's** ceiling. Ask for less, or raise `limits.max_row_limit` deliberately. |

Two ceilings, two files, and the lower one refuses first — which is why the message names
which it was. It used to say only "exceeds the maximum" and point at `max_row_limit`,
which sent readers to edit a file that had nothing to do with the refusal.

## Verifying a suspicion quickly

`core/element-detail` on one element you know well is the fastest way to see the exact
predicates, spellings and graphs in play. Most vocabulary suspicions are settled in one
command.
