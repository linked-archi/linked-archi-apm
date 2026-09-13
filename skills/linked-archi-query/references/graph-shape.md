# The shape of this graph

What a query has to know that no ontology dump tells it. Everything below was checked
against real converter output; the evidence is recorded in `PROPOSAL.md` Appendix A, which is
**repository material** and may be absent from an installed copy. Nothing here depends on
reading it.

The profile binds each term, so a template never spells one. The terms are here so you
can recognise them in a result and know what a binding means.

## Relationships: usually one form, not two

Every relationship is a **resource**, not a triple:

```turtle
<.../relationship/Flow_2>
    a arch:QualifiedRelationship, arch:ModelConcept, bpmn:SequenceFlow ;
    arch:source <.../element/Task_Validate> ;
    arch:target <.../element/Task_Payment> .
```

Three consequences.

**The relationship's kind is an `rdf:type`.** There is no `arch:relType` predicate.
The qualified node carries the core class *and* the notation class, so a query reads
the kind by taking the type that is not a core class.

**Endpoints are `arch:source` and `arch:target`.** `arch:relSource` and
`arch:relTarget` exist in the vocabulary but are the withdrawn `rdf:Statement` design,
deprecated in the converters and not covered by the core shapes. A query using them
returns nothing.

**The direct triple is opt-in.** `--emit-direct-rel-triples` is off by default, so
`?source ?predicate ?target` usually does not exist. Traversal goes through the
qualified resource.

Where both forms are present, use the direct form for reachability and property paths,
and the qualified form when the relationship itself is the subject — its label, its
protocol, what it carries. Never union them: the same relationship appears in both, so
every count doubles and nothing raises an error.

### The RDF 1.2 bridge

The core ontology also describes an `rdf:reifies` bridge, pairing the qualified
resource with a triple term that names the **unqualified** predicate:

```turtle
<.../relationship/id-1> a arch:QualifiedRelationship, am:Serving ;
    arch:source <.../element/AppSvc1> ;
    arch:target <.../element/BizProc1> ;
    rdf:reifies <<( <.../element/AppSvc1> am:serves <.../element/BizProc1> )>> .
```

It is the only way to recover the unqualified predicate from the data: the qualified
form carries the *class* (`am:Serving`) and nothing else. Three templates use it —
`core/reified-predicates`, `core/neighbours-reified`, `core/reifies-audit`.

No converter emits it, so `capabilities.rdf_reifies` is false and those three are
refused by default. Two things to know before setting it true:

- **It also claims your engine speaks SPARQL 1.2.** `<<( s p o )>>` is a parse error
  on a 1.1 endpoint, not an empty result.
- **A triple term is not an asserted triple.** `?s am:serves ?o` matches nothing even
  when 30 triple terms name `am:serves`, and property paths do not traverse terms. So
  the bridge cannot substitute for `direct_rel_triples`, and `core/neighbours-reified`
  is one hop only. Chaining hops needs an explicit join per hop.

## Named graphs, and what lives where

Each model contributes up to three graphs:

```
{base}{notation}/{modelId}/graph/semantic
{base}{notation}/{modelId}/graph/views
{base}{notation}/{modelId}/graph/provenance
```

| Graph | Holds |
|---|---|
| `semantic` | Elements, relationships, folders, **and the `arch:View` resources themselves** |
| `views` | Presentation only: nodes, links, points, bounds, styles |
| `provenance` | Source file, conversion activity, agent, editorial metadata |

Two traps in that table. The split is around **geometry, not diagrams** — a view's
label, viewpoint and model membership are semantic facts; only its layout is in the
views graph. And the views graph is **absent** whenever the source carried no
diagrams, which is always for Backstage and LeanIX.

**There is no validation graph.** The converters' `validate` subcommand writes a SHACL
report to stdout or to a file. It is a document to read, not a graph to query.

A query with no `GRAPH` clause matches the default graph only, which is empty in TriG
output. That is a defect measured, not feared: the same pattern returns 0 rows unscoped
and 13 rows scoped. Templates delegate the wrapper to the profile, so one template
serves TriG and flattened Turtle.

### Negative tests across named graphs

**A pattern inside a `GRAPH` block is evaluated in that graph alone.** For a positive
pattern that is the point. For a *negative* one — "which relationships point at nothing",
"which elements have no owner" — it is a trap, because "not in this graph" is being read
as "not in the dataset".

Only the outer scope is bound per solution. `{{GRAPH_OPEN:semantic}}` binds `?g_semantic`
to **one** graph at a time, so a `FILTER NOT EXISTS` written inside it asks whether the
thing is missing from *that* graph. Anything that lives in a sibling graph counts as
absent, and the query reports findings that are not there.

The failure is silent and the output is plausible. Measured on a two-partition fixture
where exactly one relationship really dangles:

| Where the negative test is written | Reported | Correct |
|---|---|---|
| `FILTER NOT EXISTS { ?api a ?t }` inside the block | **3** | no |
| `FILTER NOT EXISTS { GRAPH ?any { ?api a ?t } }` inside the block | 1 | yes |
| the same, after `{{GRAPH_CLOSE}}` | 1 | yes |
| `OPTIONAL { GRAPH ?any { ?api a ?t } BIND(1 AS ?f) } FILTER(!BOUND(?f))` | 1 | yes |

So the rule is not "put it outside the block":

> **A negative test must name its own graph scope.** It is wrong when it inherits the
> active graph, and correct when it opens `GRAPH ?any` — inside the block or outside it,
> whichever reads better. The same applies to `MINUS` and to `EXISTS`.

**Partitioning makes this likely rather than causing it.** Any `per-model-triple` layout
binds one graph per solution, so a dataset with one semantic graph per model already has
it. A converter that splits a semantic graph across its input files — one graph per
`catalog-info.yaml`, say — multiplies the partitions and with them the false findings: a
downstream dataset with 208 partitions reported 66 dangling edges where 27 existed. See
[`graphs.descendants`](../../linked-archi-profile/references/profile-reference.md#descendants).

**And it is a cost cliff as well as a correctness trap, which is why the `OPTIONAL` form
is the one to reach for.** A negative test across named graphs is re-evaluated per
candidate binding. That is cheap for tens of candidates and catastrophic for thousands,
and the difference is the number of candidates fed into it rather than anything about the
test itself — the same shape has been measured in the low hundreds of milliseconds and in
the tens of seconds on the same kind of graph. `OPTIONAL { … BIND } FILTER(!BOUND(…))` is
never the slower of the two and satisfies the correctness rule above, so it needs no
judgement call about which regime you are in.

"Never use `NOT EXISTS`" would be the wrong lesson: it is correct when scoped, and
readable. Reach for the `OPTIONAL` form when the candidate set is large or unknown.

## Elements

```turtle
<.../element/id-861>
    a arch:Element, arch:ModelConcept, am:ApplicationComponent ;
    skos:notation "id-861" ;
    skos:prefLabel "Gestion de données de polices"@fr ;
    dct:isPartOf <.../model/archisurance> .
```

- **Labels are `skos:prefLabel`**, language-tagged, with `skos:altLabel` for
  alternatives. A query on `rdfs:label` returns zero rows and looks like an empty
  result rather than a mistake.
- **Elements are multi-typed**: a core class plus a notation class. Filtering the core
  classes out leaves the one that carries meaning.
- **The native id is `skos:notation`** — except BPMN, which uses `bpmn:id`. The profile
  binds both as a chain.
- `skos:definition` carries the description. `schema:keywords` carries a notation's own
  tags, used by PlantUML and LeanIX.

## Identity across sources

Element IRIs are derived from the source, so they are stable across rebuilds and need
no registry: the same input always produces the same IRI. Cross-tool equivalence is the
opposite. It cannot be derived — the same application in ArchiMate and in Backstage
produces two IRIs by construction — so it is **asserted deliberately** and reviewed by
a human. No converter emits it.

Four things that are not interchangeable:

| Predicate | Means |
|---|---|
| `skos:exactMatch` | A corresponding record in another register. Prefer this. |
| `owl:sameAs` | The two IRIs *are* one thing. Merges everything said about both; unforgiving of a mistake. |
| `skos:notation` | The identifier the source tool used. |
| `schema:url` | A link to a page about the element. |

When a cross-notation join comes back empty, the cause is almost always a missing
assertion rather than a wrong query. Check with `core/identity-audit` before rewriting
SPARQL.

## Provenance

Provenance is asserted about the **model**, in its own graph, with hash IRIs on the
graph IRI: `#run` for the activity, `#agent` for the converter, `#source-{slug}` for
the input file.

Two shapes differ between converters, which is why `core/provenance` looks more
complicated than it should:

- **Where the source filename lives.** BPMN, Structurizr and Backstage put
  `dct:source` on the model; ArchiMate puts it only on the `prov:Entity` the model was
  derived from.
- **How to reach the model from an element.** Folder-to-model membership via
  `dct:isPartOf` is emitted by some converters and not others, so walking it works for
  BPMN and fails for C4. `core/provenance` finds the model by co-location in the same
  semantic graph instead.

More than one provenance row for one element is not a fault. A model can carry two
`prov:generatedAtTime` values that mean different things — the export date an author
declared and the moment the converter ran — and LeanIX output does. The gap between
them is a staleness signal worth reporting.

## Lifecycle, ownership and status

None of these has a core predicate, and that absence is the finding rather than a gap
in this package.

- **`adms:status` is model-level**, in the provenance graph, and describes the
  *conversion*. "Completed" means the converter finished. It is not an architecture
  lifecycle.
- **Element lifecycle is notation-specific**: `bs:lifecycleState`,
  `lmm:factSheetStatus`. ArchiMate output carries none.
- **`arch:conceptOwner` appears in no converter output.** Ownership arrives as a
  relationship — `bs:Ownership` in Backstage — or not at all. A curated pipeline may
  promote it; raw output does not.
- `arch:architectureState` distinguishes baseline from target where a model records it.

## Property key hygiene

Two spellings of a property key are two different predicates, and a join on the wrong
casing returns fewer rows with no error. When a result looks suspiciously small, run
`core/element-detail` on one element you know carries the property and read the exact
spelling. `core/discover-predicates` shows the same problem in aggregate: two casings
appear as two rows with split counts.

## Blank nodes

Folder list items and view styles are blank nodes, regenerated on every conversion.
They mean nothing outside the document, so results render them as `_:id` rather than as
a bare string that reads like data. Never treat one as an identifier, and never assert
anything about one across runs.
