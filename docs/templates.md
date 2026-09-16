# Template catalogue

Thirty-nine tested templates. Each one declares what it answers, what it does **not** prove, what it
needs from the profile, and which templates to use instead when it is refused.

`la-query catalog show <name>` is the authoritative parameter list — read it rather than the `.rq`
file, because it carries the typing and the caveats the file does not.

```bash
python3 scripts/la-query catalog list --profile linked-archi-default --why
python3 scripts/la-query catalog show core/traceability --profile linked-archi-default
```

## By stage

| Stage | Templates | Purpose |
|---|---|---|
| [orientation](#orientation) | 4 | Run these first, every session. They establish what is actually loaded, so an empty later result can be told from a partial export. |
| [resolution](#resolution) | 5 | Turn a name a user typed into an IRI. Never construct an IRI from a label. |
| [discovery](#discovery) | 3 | Find out what predicates and relationship types this dataset actually uses, before assuming one. |
| [analysis](#analysis) | 10 | The questions people actually ask: what depends on what, what realises what, what crosses a layer. |
| [views](#views) | 6 | Diagrams: what is drawn, where, and what differs between two of them. |
| [enrichment](#enrichment) | 3 | Attributes only some notations carry, such as lifecycle and ownership. |
| [quality](#quality) | 8 | Whether the model can be trusted to answer at all: gaps, orphans, provenance, identity, conformance. |

Thirty-three are cross-notation. Six are notation-specific: one each for ArchiMate, C4, Backstage and LeanIX, and two for BPMN. A notation template is gated on the vocabulary IRI it is written against, never on a notation label.

## orientation

Run these first, every session. They establish what is actually loaded, so an empty later result can be told from a partial export.

### `core/elements-by-category`

Elements of a model grouped by the taxonomy category of their type.

**Answers.** How a notation's own taxonomy groups what is in this model.

!!! warning "Does not prove"
    That an element whose type no category names is unimportant - it produces no row at all.

!!! note "Caveat carried with every result"
    Grouping comes from the attached vocabulary, so it is only as current as the ontology version paired with this dataset.

| Parameter | Type | Default |
|---|---|---|
| `MODEL_IRI` | iri | required |
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** graphs `vocabulary`, `semantic`; membership

**Instead, when refused.** `notation/bpmn/process-components`, `core/elements-by-type`

### `core/inventory`

Named graphs, types and counts. Run first, every session.

**Answers.** What is loaded, from which graphs, and how much of each type.

!!! warning "Does not prove"
    That the dataset is complete. A low count is usually a partial export.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `300` |

**Requires.** —

### `core/inventory-summary`

Notations present, with model, graph and concept counts. Use on a large dataset.

**Answers.** How much of each notation is loaded, in one screen.

!!! warning "Does not prove"
    Completeness. A missing notation may never have been converted, or a merge may have dropped it.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..500) | `50` |

**Requires.** graphs `model`, `semantic`; membership

**Instead, when refused.** `core/inventory`, `core/models`

### `core/models`

Models present, the metamodel each conforms to, and its source.

**Answers.** Which notations contributed, and when each model was converted.

!!! warning "Does not prove"
    That a model is current. A conversion timestamp is not an as-at date.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..1000) | `100` |

**Requires.** graphs `model`, `provenance`

## resolution

Turn a name a user typed into an IRI. Never construct an IRI from a label.

### `core/define-term`

Explain each resource a term matches: definition, type, owning model, immediate relationships.

**Answers.** What this dataset says a term means, and how ambiguous the term is.

!!! warning "Does not prove"
    That a definition is true, current or agreed. It is text somebody typed in a modelling tool.

| Parameter | Type | Default |
|---|---|---|
| `TERM` | string | required |
| `LIMIT` | integer (range 1..1000) | `100` |

**Requires.** graphs `semantic`, `provenance`; membership

**Instead, when refused.** `core/resolve-element`, `core/element-detail`, `core/neighbours-qualified`

### `core/element-detail`

Every predicate and object on one resource, with its graph.

**Answers.** What the dataset actually says about an element, in exact spelling.

!!! warning "Does not prove"
    Completeness. Absent here means absent from the models.

| Parameter | Type | Default |
|---|---|---|
| `FOCUS_IRI` | iri | required |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** —

### `core/elements-by-type`

List elements carrying one rdf:type.

**Answers.** The population of a class, with labels and native ids.

!!! warning "Does not prove"
    That the type is the element's only type. Elements are multi-typed.

| Parameter | Type | Default |
|---|---|---|
| `TYPE_IRI` | iri | required |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`; membership

**Instead, when refused.** `core/inventory`

### `core/resolve-element`

Resolve a name a user typed to candidate IRIs, best candidate first.

**Answers.** Which resources match a term by name, alias or native id, ranked by how much of the value matched (?rank) and by which of the three matched (?matched).

!!! warning "Does not prove"
    That the top match is the one meant. Ask when the choice changes the answer.

| Parameter | Type | Default |
|---|---|---|
| `TERM` | string | required |
| `LIMIT` | integer (range 1..200) | `25` |

**Requires.** graphs `semantic`

**Instead, when refused.** `core/resolve-model`, `core/define-term`

### `core/resolve-model`

Resolve a phrase to a model, as against a concept inside one.

**Answers.** Which models match by title, name, native id, description, source file, status or notation, ranked exact then prefix then substring.

!!! warning "Does not prove"
    That the top-ranked model is the one meant, or that it is current. Rank is string similarity only.

| Parameter | Type | Default |
|---|---|---|
| `TERM` | string | required |
| `LIMIT` | integer (range 1..200) | `25` |

**Requires.** graphs `model`, `provenance`

**Instead, when refused.** `core/models`, `core/resolve-element`

## discovery

Find out what predicates and relationship types this dataset actually uses, before assuming one.

### `core/discover-predicates`

Predicates in use, with frequency and object kind.

**Answers.** Exact predicate spellings, including house fields with no core role.

!!! warning "Does not prove"
    That a predicate means what its local name suggests.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `250` |

**Requires.** graphs `semantic`

### `core/discover-relationship-types`

Relationship types present, with counts and the endpoint types they join.

**Answers.** Which relationship kinds this dataset actually uses.

!!! warning "Does not prove"
    What the metamodel permits. This is what was modelled.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `250` |

**Requires.** graphs `semantic`

### `core/reified-predicates`

Unqualified predicates exposed by the RDF 1.2 reification bridge, per qualified class.

**Answers.** The predicate a relationship stands for, which the qualified class alone does not carry.

!!! warning "Does not prove"
    That the predicate is asserted. A triple term is not a triple, and property paths do not traverse it.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `250` |

**Requires.** graphs `semantic`; `rdf_reifies: true`

**Instead, when refused.** `core/discover-relationship-types`

## analysis

The questions people actually ask: what depends on what, what realises what, what crosses a layer.

### `core/classified-by`

Elements classified under a taxonomy concept or any concept beneath it.

**Answers.** The membership of a taxonomy branch, whichever scheme it belongs to.

!!! warning "Does not prove"
    That unclassified elements fall outside the branch.

| Parameter | Type | Default |
|---|---|---|
| `CONCEPT_IRI` | iri | required |
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** graphs `semantic`

### `core/dependents-direct`

Transitive dependents through named direct predicates.

**Answers.** Everything reaching an element at any depth along a chosen predicate set.

!!! warning "Does not prove"
    Impact, or completeness beyond the predicates named.

| Parameter | Type | Default |
|---|---|---|
| `FOCUS_IRI` | iri | required |
| `PREDICATE_PATH` | iri_path | required |
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** graphs `semantic`; `direct_rel_triples: true`

**Instead, when refused.** `core/dependents-qualified`, `core/neighbours-qualified`

### `core/dependents-qualified`

What reaches an element within two hops, via the qualified form.

**Answers.** Bounded incoming dependency paths, with the relationship types on each.

!!! warning "Does not prove"
    Impact. Reachability in a model is not blast radius.

| Parameter | Type | Default |
|---|---|---|
| `FOCUS_IRI` | iri | required |
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** graphs `semantic`

**Instead, when refused.** `core/neighbours-qualified`

### `core/neighbours-qualified`

Direct relationships touching an element, via the qualified form.

**Answers.** What an element relates to, in both directions, with the relationship kind.

!!! warning "Does not prove"
    Runtime dependency, criticality or failure propagation.

| Parameter | Type | Default |
|---|---|---|
| `FOCUS_IRI` | iri | required |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`

### `core/neighbours-reified`

Relationships touching an element, naming the unqualified predicate as well as the class.

**Answers.** What an element relates to, in both directions, with the predicate the bridge names.

!!! warning "Does not prove"
    Runtime dependency. And one hop only: paths cannot traverse triple terms.

| Parameter | Type | Default |
|---|---|---|
| `FOCUS_IRI` | iri | required |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`; `rdf_reifies: true`

**Instead, when refused.** `core/neighbours-qualified`, `core/dependents-qualified`

### `core/traceability`

Paths of one or two hops between two kinds of element.

**Answers.** Which elements of one type connect to which of another, and how.

!!! warning "Does not prove"
    That an unlisted pair is unconnected. Deeper paths are out of scope.

| Parameter | Type | Default |
|---|---|---|
| `SOURCE_TYPE` | iri | required |
| `TARGET_TYPE` | iri | required |
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** graphs `semantic`

**Instead, when refused.** `core/coverage-gaps`

### `notation/archimate/layer-crossing`

*archimate only.*

Relationships that cross ArchiMate layers, grouped by layer pair.

**Answers.** Where realisation and serving cross layers, and how often.

!!! warning "Does not prove"
    That a crossing is correct, or that a missing one is a gap. Layer is inferred from class names.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`

### `notation/bpmn/process-components`

*bpmn only.*

What takes part in a BPMN model, grouped by kind of participant.

**Answers.** Where work arrives, what is automated, what a person does, the participants, the data touched, and where it ends.

!!! warning "Does not prove"
    That any of it runs. A ServiceTask is a modelled intent, not a deployed service.

| Parameter | Type | Default |
|---|---|---|
| `MODEL_IRI` | iri | required |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`; membership

**Instead, when refused.** `notation/bpmn/process-flow`, `core/elements-by-type`

### `notation/bpmn/process-flow`

*bpmn only.*

Sequence flows of one BPMN process, as edges.

**Answers.** Which steps follow which, with the flow element types.

!!! warning "Does not prove"
    Runtime order. Gateways branch; these are edges, not a path.

| Parameter | Type | Default |
|---|---|---|
| `PROCESS_IRI` | iri | required |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`

### `notation/c4/containers`

*c4 only.*

C4 elements with type, technology and containing parent.

**Answers.** The container and component structure of a C4 model.

!!! warning "Does not prove"
    Deployment. A container is a modelled unit, not a running instance.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`

## views

Diagrams: what is drawn, where, and what differs between two of them.

### `core/view-contents`

Which elements a diagram places.

**Answers.** What one view depicts, with each element's label, native id and types.

!!! warning "Does not prove"
    That the diagram is current, or that an element absent from it is absent from the architecture.

| Parameter | Type | Default |
|---|---|---|
| `VIEW_IRI` | iri | required |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`, `views`; `views_graph: true`

**Instead, when refused.** `core/view-contents-semantic`, `core/views`, `core/view-usage`

### `core/view-contents-semantic`

Which elements a diagram places, read from the semantic graph.

**Answers.** What one view depicts, from the one-hop arch:inView edge rather than a node in the views graph. The route that survives output published without geometry.

!!! warning "Does not prove"
    That the diagram is current, or that an element absent from it is absent from the architecture. It also says nothing about where on the canvas anything sits - use core/view-contents where the views graph exists.

!!! note "Caveat carried with every result"
    Read from arch:inView, so this reports which view presents an element and not where it is drawn. An element placed twice on one view is reported once.

| Parameter | Type | Default |
|---|---|---|
| `VIEW_IRI` | iri | required |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`

**Instead, when refused.** `core/view-contents`, `core/views`, `core/view-usage-semantic`

### `core/view-diff`

Set difference between two views, by placed element.

**Answers.** Which elements one diagram places and the other does not, in either or both directions.

!!! warning "Does not prove"
    That a difference between diagrams is a difference in the architecture. Views are editorial.

| Parameter | Type | Default |
|---|---|---|
| `VIEW_A_IRI` | iri | required |
| `VIEW_B_IRI` | iri | required |
| `DIRECTION` | string | `symmetric` |
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `views`, `semantic`; `views_graph: true`

**Instead, when refused.** `core/view-contents`, `core/views`

### `core/view-usage`

Which diagrams depict an element.

**Answers.** Where an element has been drawn, and under which viewpoint.

!!! warning "Does not prove"
    That an undrawn element is unimportant.

| Parameter | Type | Default |
|---|---|---|
| `FOCUS_IRI` | iri | required |
| `LIMIT` | integer (range 1..1000) | `100` |

**Requires.** graphs `semantic`, `views`; `views_graph: true`

**Instead, when refused.** `core/view-usage-semantic`, `core/views`

### `core/view-usage-semantic`

Which diagrams depict an element, read from the semantic graph.

**Answers.** Where an element has been drawn and under which viewpoint, from the one-hop arch:inView edge rather than a node in the views graph.

!!! warning "Does not prove"
    That an undrawn element is unimportant. It returns no node, so it cannot distinguish two drawings of one element on one view.

!!! note "Caveat carried with every result"
    Returns no node column, unlike core/view-usage. Each view is reported once however many times the element is drawn on it.

| Parameter | Type | Default |
|---|---|---|
| `FOCUS_IRI` | iri | required |
| `LIMIT` | integer (range 1..1000) | `100` |

**Requires.** graphs `semantic`

**Instead, when refused.** `core/view-usage`, `core/views`, `core/view-contents-semantic`

### `core/views`

Views present, their viewpoint, and how many nodes each places.

**Answers.** What diagrams exist and how substantial they are.

!!! warning "Does not prove"
    Quality or currency of a diagram.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`, `views`; membership

## enrichment

Attributes only some notations carry, such as lifecycle and ownership.

### `core/lifecycle`

Element-level lifecycle status, where any notation records it.

**Answers.** Which elements carry a status, and what it is.

!!! warning "Does not prove"
    Coverage. Lifecycle is sparse and notation-specific.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** graphs `semantic`; `element_lifecycle: true`; membership

**Instead, when refused.** `notation/backstage/ownership`, `notation/leanix/factsheets`

### `notation/backstage/ownership`

*backstage only.*

Backstage entities and the group or user that owns them.

**Answers.** Who is recorded as owning what, with lifecycle state.

!!! warning "Does not prove"
    Accountability. spec.owner is what somebody wrote in a file.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`

**Instead, when refused.** `core/coverage-gaps`

### `notation/leanix/factsheets`

*leanix only.*

LeanIX fact sheets with status, completion and lifecycle phase.

**Answers.** What the inventory holds and how filled-in each record is.

!!! warning "Does not prove"
    That a fact sheet's subject exists, or that its content is right. A fact sheet is a record about a thing.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`

## quality

Whether the model can be trusted to answer at all: gaps, orphans, provenance, identity, conformance.

### `core/coverage-gaps`

Elements of a type with no value for an expected predicate.

**Answers.** Where the models are silent about something you expected.

!!! warning "Does not prove"
    That the real thing lacks the property. Nobody recorded it.

| Parameter | Type | Default |
|---|---|---|
| `RESOURCE_TYPE` | iri | required |
| `EXPECTED_PREDICATE` | iri | required |
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** membership

### `core/graph-provenance`

What produced each named graph, from which source, and when.

**Answers.** Whether every graph in the dataset can be accounted for, or just the graphs whose IRI matches GRAPH_MATCH.

!!! warning "Does not prove"
    That a graph is complete, or that its source is current.

| Parameter | Type | Default |
|---|---|---|
| `GRAPH_MATCH` | string | `` |
| `LIMIT` | integer (range 1..1000) | `100` |

**Requires.** graphs `provenance`; `graph_bundles: true`

**Instead, when refused.** `core/provenance`, `core/models`

### `core/identity-audit`

Cross-source identity assertions, and which kind each is.

**Answers.** Which elements are linked across tools, by correspondence or by identity.

!!! warning "Does not prove"
    That unlisted elements have no counterpart. Identity is authored.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`; `identity_assertions: true`

**Instead, when refused.** `core/resolve-element`, `core/models`

### `core/label-collisions`

Elements sharing a normalised label across different models. Identity CANDIDATES only.

**Answers.** Where the same name appears in more than one model, with each side's type and model.

!!! warning "Does not prove"
    Identity. Same label is not same system: it may be one thing modelled twice, two things, or a thing and a record about it.

!!! note "Caveat carried with every result"
    core/label-collisions returns identity CANDIDATES, not identity assertions. A shared label is not evidence that two resources are the same thing. Cross-tool identity here is authored and human-reviewed: core/identity-audit reads those assertions, and this template makes none.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** graphs `semantic`; membership

**Instead, when refused.** `core/identity-audit`, `core/resolve-element`, `core/define-term`

### `core/orphans`

Elements taking part in no relationship.

**Answers.** Where the model has islands, as a data-quality reading.

!!! warning "Does not prove"
    That an element is unused or safe to remove.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** graphs `semantic`; membership

### `core/provenance`

Source file, converter, and timestamps behind an element's model.

**Answers.** Where a fact came from, so a claim becomes evidence.

!!! warning "Does not prove"
    That the source model is current, correct or approved.

| Parameter | Type | Default |
|---|---|---|
| `FOCUS_IRI` | iri | required |
| `LIMIT` | integer (range 1..500) | `50` |

**Requires.** graphs `semantic`, `provenance`; `provenance_graph: true`; membership

**Instead, when refused.** `core/models`, `core/element-detail`

### `core/reifies-audit`

Qualified relationships whose triple term is missing or disagrees with arch:source/arch:target.

**Answers.** Whether the two halves of each relationship agree with each other.

!!! warning "Does not prove"
    Correctness. A relationship wrong in both halves agrees with itself and passes.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..3000) | `300` |

**Requires.** graphs `semantic`; `rdf_reifies: true`

**Instead, when refused.** `core/discover-relationship-types`, `core/orphans`

### `core/validation-summary`

SHACL verdict with violations by severity and shape, from a report in the dataset.

**Answers.** What a loaded SHACL report says, and how much it covered.

!!! warning "Does not prove"
    Soundness. A verdict without an evaluated count means nothing.

| Parameter | Type | Default |
|---|---|---|
| `LIMIT` | integer (range 1..2000) | `200` |

**Requires.** `validation_in_graph: true`

**Instead, when refused.** `core/coverage-gaps`, `core/orphans`

