# Profile field reference

Every field, what it is for, and where the bundled values came from. All of them
were verified against real converter output rather than read from documentation. The evidence
is in `PROPOSAL.md` Appendix A - **repository material**, so it may not be in an installed
copy; nothing here depends on reading it.

| Looking for | Section |
|---|---|
| profile name, version, `extends`, `base_iri` | [Top level](#top-level) |
| prefixes, and why never to key on one | [namespaces](#namespaces) |
| named-graph layout, per-model suffixes, `single` | [graphs](#graphs) |
| what a term is called here, fallback chains, `null` | [roles](#roles) |
| what the dataset *contains*, and `partial` | [capabilities](#capabilities) |
| notation slugs and metamodel IRIs | [notations](#notations) |
| SKOS schemes for classification | [taxonomies](#taxonomies) |
| row limits and timeouts | [limits](#limits) |
| "belongs to that model" | [membership.md](membership.md) |
| building a profile for a custom vocabulary | [deriving.md](deriving.md) |
| driving this owner from a program | [machine-contract.md](machine-contract.md) |

`roles` and `capabilities` stay on one page on purpose: authoring a profile means deciding
what a term is called *and* whether it is present, and separating them would mean loading two
files for one task.

## Top level

| Field | Meaning |
|---|---|
| `extends` | Parent profile. Resolved beside your file first, then in bundled `profiles/`. |
| `profile` | Identifier recorded in every result envelope. |
| `version` | Integer. Recorded alongside the name, so a saved result says which vocabulary produced it. |
| `description` | One or two sentences. Shown by `profile list`. |
| `base_iri` | Informational. Nothing parses IRIs to extract meaning; it lets `verify` report when a dataset does not look like the one the profile describes. |

## namespaces

Prefix to namespace IRI. Emitted as the `PREFIX` block of every rendered query
through `{{PREFIXES}}`.

Prefix choice is cosmetic: roles resolve to absolute IRIs, so no template depends on
a prefix being spelled a particular way. This matters more than it sounds — the
converters emit both `archvis:` and `arch-vis:` for the same namespace depending on
which emitter ran. Never key on a prefix.

## graphs

```yaml
graphs:
  layout: per-model-triple    # per-model-triple | explicit | single
  named_graphs: true
  roles:
    semantic: graph/semantic
    views: graph/views
    provenance: graph/provenance
  validation: null
  required:                   # absence is an error, not a warning
    - semantic
```

| Layout | Meaning | `{{GRAPH_OPEN:role}}` becomes |
|---|---|---|
| `per-model-triple` | Each model contributes graphs whose IRIs end in these suffixes. What the converters emit as TriG. | `GRAPH ?g_role { FILTER(STRENDS(...)) ` |
| `explicit` | `roles` holds literal graph IRIs, for a curated store. | `GRAPH ?g_role { VALUES ?g_role { ... } ` |
| `single` | No named graphs. What Turtle output collapses to. | `{` |

Under `single` the templates still work: the wrapper becomes a plain group, and any
template that scoped to a role runs with a caveat saying the separation was lost. That
is why `layout: single` and `named_graphs: true` together are rejected at load — the
combination cannot mean anything.

A graph role bound to `null` is declared absent. `validation` is null in the default
profile because **there is no validation graph**: the converters' `validate`
subcommand writes a SHACL report to stdout or to `-r file`, as a separate document.
Declaring it null is what makes `core/validation-summary` refuse with that reason
rather than return nothing.

### descendants

Graph roles whose suffix also matches graphs *below* it, so `graph/semantic` scopes to
`graph/semantic/{repo}/{path}` as well.

```yaml
graphs:
  layout: per-model-triple
  roles:
    semantic: graph/semantic
  descendants:
    - semantic
```

The selector becomes `STRENDS(?g, "graph/semantic") || CONTAINS(?g, "graph/semantic/")`.
The trailing slash keeps it a path test: `graph/semantic/` cannot match
`graph/semantic-draft`.

Needed because the converters partition the semantic graph per input where a model has
more than one source. A plain suffix test matches **none** of those graphs, which is how
a profile can report "no graph matching `graph/semantic`" against a dataset whose
semantic content is plainly present and queryable by other means.

**Opt-in per role, and deliberately not the default.** Matching descendants everywhere
would be the smaller change and the wrong one: a profile describing the older
unpartitioned layout would silently start matching a partitioned dataset's semantic
graphs and look like it fitted, while its other roles still read the wrong graphs —
`arch:Model` moved to `graph/model` in the same generation that introduced the
partitions. Half-fitting is precisely how a wrong profile returns a confident wrong
answer, so opting in is a claim the profile makes and `verify` can check.

Only meaningful under `layout: per-model-triple`. Under `explicit` the roles hold literal
graph IRIs and there is nothing to descend; under `single` there are no graphs. Both are
rejected at load, as is a name that is not a bound graph role.

Every bundled graph-scoped profile uses it for `semantic`. `examples/flattened-turtle` sets `descendants: []`, because a layout with no named graphs has nothing to descend and inheriting the claim is rejected.

**What this changes for a query that asks what is NOT there.** A scoped block still binds
one graph per solution, so a negative test written inside it asks "is this missing from
this partition" rather than "from the dataset" — and descendant matching multiplies the
partitions, so it multiplies the wrong findings too. One downstream dataset with 208
semantic partitions reported 66 dangling relationships where 27 existed. This is a
property of graph scoping rather than of this key, and the rule for writing such a test
correctly belongs with the query owner:
[graph-shape.md](../../linked-archi-query/references/graph-shape.md#negative-tests-across-named-graphs).

### required

Which graph roles a dataset must actually have. A required role that matches no graph
is an **error** and `profile verify` exits non-zero; an optional one is a warning.

The distinction decides whether a mismatch is loud or silent. Every query scoped to a
role that matches nothing returns no rows, so a warning plus exit 0 hands back an
empty result that reads like a finding about the architecture. That is the failure
mode this package exists to remove, and it was observed in the field: a 1.3 converter
graph verified with 0 errors and 24 warnings while `core/models` returned nothing.

Defaults to `[semantic]` where a `semantic` role is declared, because a dataset with
no semantic graph cannot answer a single scoped question. `views` and `provenance` are
deliberately **not** required: a Backstage or LeanIX conversion emits no views graph
at all, so requiring one would refuse correct data.

- `required: []` opts out entirely, for a profile describing an unusual dataset.
- Naming more roles opts them in. A profile written for a layout that keeps model
  resources in their own graph should require that role, so pointing it at a dataset
  without one refuses instead of returning nothing.
- A name that is not bound under `roles`, or is bound to `null`, is rejected at load.
  It could never be satisfied, so it would refuse every dataset.

Under `layout: single` the check never runs: the profile expects no named graphs, so
requiring a semantic *graph* would be incoherent. A flat dataset read with a
graph-scoping profile is already an error, reported as `graphs.named_graphs`.

The bundled profiles require `model` as well as `semantic`: every model-level question
reads `graph/model`, and its absence means the dataset predates that layout rather than
merely lacking a graph. `recommend` says which three keys to override in that case.

When a role is missing, verification also distinguishes **absent** from **present but
partitioned**. A suffix selector cannot match `graph/semantic/{repo}/{path}`, so a
dataset that splits a role across descendant graphs looks identical to one that lacks
the role. The two need opposite fixes, so the finding says which it is.

Scoping to two roles in one query works because each role binds its own variable,
`?g_semantic` and `?g_provenance`. A single shared variable would require one graph
IRI to end in two different suffixes at once — unsatisfiable, and silent. Add a
trailing digit for an independent scope on the *same* role: `semantic2` scopes like
`semantic` but binds `?g_semantic2`, which is what lets a cross-source query read
labels from two different models' graphs.

## roles

A role is what a query needs; the binding is what this dataset calls it.

- **single value** — bound to exactly that term.
- **list** — a fallback chain. `{{ROLE:x}}` takes the first, `{{ROLES:x}}` emits all
  for a `VALUES` block, `{{PATH:x}}` joins them with `|`.
- **`null`** — not represented here. Any template declaring the role under `requires`
  is refused, with that reason shown.

These must be bound in every profile, because no template can do anything without
them: `label`, `concept_class`, `element_class`, `relationship_class`, `rel_source`,
`rel_target`, `rel_type`.

### Bindings worth explaining

| Role | Default | Why |
|---|---|---|
| `label` | `skos:prefLabel` | Not `rdfs:label`. A query on the wrong one returns zero rows and looks like an empty result rather than a mistake. |
| `native_id` | `[skos:notation, bpmn:id]` | A chain because BPMN uses `bpmn:id` while every other notation uses `skos:notation`. `{{ROLES:native_id}}` covers a mixed dataset. |
| `rel_source` / `rel_target` | `arch:source` / `arch:target` | `arch:relSource` and `arch:relTarget` are the withdrawn `rdf:Statement` design and are deliberately absent. |
| `rel_type` | `rdf:type` | There is no `arch:relType` predicate. A relationship's kind is an `rdf:type` on the qualified node alongside `arch:QualifiedRelationship` — `am:Access`, `bpmn:SequenceFlow`, `bs:Ownership`. |
| `element_lifecycle` | `[bs:lifecycleState, lmm:factSheetStatus]` | No core lifecycle predicate exists. Each notation spells it differently, and ArchiMate output carries none. |
| `owner` | `null` | `arch:conceptOwner` appears in no converter output. Ownership arrives as a relationship, or not at all. |
| `same_as` / `exact_match` | `null` | Cross-source identity cannot be derived and is never emitted by a converter. It is authored and human-reviewed. |
| `view_node_class` | `[archvis:ArchNode, archvis:Node]` | A node is typed `ArchNode` only when backed by an element; layout-only nodes are plain `Node`, and older output types every node that way. |
| `in_view` | `arch:inView` | The one-hop semantic route to "this concept is on that view", emitted since core 0.4.0 beside the two-hop `view_ref`/`node_element` visual route. It is the route that survives output published without a views graph, and the one the ArchiMate viewpoint conformance shapes read. The bundled view templates use the visual route; this is bound so a profile describes the data honestly. |
| `part_of_model` | `arch:inModel` | Renamed upstream in core 0.4.0 from `arch:partOfModel`, which is now deprecated. The role key is unchanged — it is this tool's name, not a vocabulary term. A dataset from an earlier converter carries only the old predicate; override the binding or re-convert, and expect `verify` to report the drift. |
| `reifies` | `rdf:reifies` | Bound even though converter output carries none, because `rdf:reifies` is fixed RDF vocabulary rather than a Linked.Archi choice. Whether the dataset *has* the bridge is `capabilities.rdf_reifies`, not this. |
| `unqualified_form` | `arch:unqualifiedForm` | Links a qualified class to its unqualified predicate — `am:Serving` → `am:serves`. Declared in the metamodel, so usually absent from instance data. |

## capabilities

What the dataset contains, as against what the vocabulary permits. Values are
`true`, `false` or `partial`.

`partial` means present for some models and absent for others — true of the views
graph, which exists only where a source had diagrams. A template requiring a partial
capability runs with a warning, because a thin result may reflect coverage rather
than absence.

An undeclared capability reads as `false`, on purpose: a profile that has not thought
about one should not have templates depending on it silently.

| Capability | Default | Why |
|---|---|---|
| `direct_rel_triples` | `false` | `--emit-direct-rel-triples` is off by default, so the qualified form is usually the only form. Verified zero in every default-flag output. Its probe is **three-valued** — see below. |
| `rdf_reifies` | `false` | Two claims in one flag: the dataset carries the RDF 1.2 bridge, **and** the engine parses `<<( s p o )>>`. No converter emits the bridge, and on a SPARQL 1.1 endpoint the syntax is a parse error rather than an empty result — so the three reified templates are refused at render time. Do not set it true to "try": a triple term is not an asserted triple, so it cannot stand in for `direct_rel_triples`. |
| `views_graph` | `partial` | Absent entirely for Backstage and LeanIX output. |
| `view_geometry` | `partial` | ArchiMate carries bounds; Structurizr and PlantUML emit topology without them. |
| `identity_assertions` | `false` | Authored, so absent from raw output. |
| `element_lifecycle` | `partial` | Notation-specific and sparse. |
| `concept_owner` | `false` | Not emitted by any converter. |
| `validation_in_graph` | `false` | The report is a document, not a graph. |

`verify` probes each of these. Claimed true but absent is an **error**; claimed false
but present is a **warning**, because you are refusing templates unnecessarily.

## notations

Keyed by the notation slug that appears in minted IRIs. Note ArchiMate's slug is
`model`, not `archimate`: its IRI scheme is configurable and `--path-model` defaults
to `model`.

`metamodel` is the object of `arch:modelConformsToMetamodel` and is the reliable way
to detect which notations a dataset holds — more reliable than inspecting element
types, and far more so than parsing IRIs.

## taxonomies

SKOS concept schemes available for classification. Adding a custom taxonomy is an
entry here and needs no new template: `core/classified-by` walks `skos:broader` from
whatever concept you name.

## navigation

How this dataset expresses "this concept belongs to that model", which several templates ask
for through `{{MEMBERSHIP:var}}`. Two modes, `same-graph-colocation` (the default) and
`bounded-folder-tree`.

It has its own page, because the choice needs a measurement rather than a preference and the
wrong claim fails silently: [membership.md](membership.md).

## limits

`default_row_limit`, `max_row_limit`, `timeout_ms`.

**`max_row_limit` is one of two ceilings on a row limit, and the lower one wins.** The
other is the `max` a template declares for its own `LIMIT` parameter, which is a property
of that query's shape rather than of this dataset. Every bundled template declares one,
and all of them are below the bundled `max_row_limit` of 5000 — so in practice the
template's ceiling refuses first, and this one is what protects a dataset or endpoint that
cannot stand what a template considers reasonable. A request above either is refused, and
the refusal names which ceiling it was so the reader edits the right file.

**`default_row_limit` is a fallback, not the normal path.** Every bundled template
declares its own `LIMIT` default, so this applies only to a template that does not — and
to a template whose own default exceeds `max_row_limit`, which runs clamped to the ceiling
with a caveat on the result rather than being refused. Do not read it as the number a
result is measured against for completeness: that is the cap the query actually carried.

### Why direct_rel_triples is probed three ways

"Are the endpoints joined by some other predicate" is not the question, and asking it
produced a false positive: one unrelated `dct:relation` between two elements that a
qualified relationship also connects was enough to report the capability present, which
un-refused the templates reading direct edges so they returned rows meaning something
else.

The question is whether the endpoints are joined by the predicate that relationship
**declares** as its unqualified form. That declaration is the RDF 1.2 bridge, reached
through the `reifies` role (`rdf:reifies`), whose triple term names the predicate *and* both
endpoints. Every converter emits it inside the branch that writes the direct triple, so a
dataset with genuine direct edges always names them and no ontology needs loading.

The probe asks for the asserted triple as well as the bridge, because a triple term is not
an asserted triple: it denotes a proposition, a plain pattern does not match inside it, and
property paths do not traverse it. The bridge alone says which predicate the relationship
stands for and nothing about whether that edge was written.

| Dataset | Verdict |
|---|---|
| A bridge exists and the predicate it names joins the endpoints | **true** |
| A bridge exists and it does not | **false** |
| No candidate edge joins the endpoints at all | **false** — absence of any candidate proves absence of a declared one |
| A candidate edge exists but nothing declares the form | **unknown** — reported, and the claim is left as written |

An unknown never contradicts the claim and is never offered as a `--emit-fix` correction.
"Fixing" a profile to match an unknown is how a correct claim gets deleted.

!!! note "The bridge is only read where the engine can parse it"
    `<<( s p o )>>` is a **parse error** on a SPARQL 1.1 engine rather than an empty result,
    and a probe batch fails whole on one bad query. So the destructuring pattern is used only
    when the backend reports SPARQL 1.2 — true for local pyoxigraph — or when the profile
    claims `capabilities.rdf_reifies`, which is how an operator asserts it of a remote
    endpoint and the same gate query templates are refused by. Otherwise the verdict falls to
    the last two rows above, which need no 1.2 support.

This role replaced `rel_predicate` (`arch:relPredicate`). Core never published that term —
the `skos:historyNote` on `QualifiedRelationship` records the `rdf:Statement` design behind
it being dropped — and no converter emits it any more. A custom profile still declaring
`rel_predicate` is ignored rather than rejected; bind `reifies` instead.
