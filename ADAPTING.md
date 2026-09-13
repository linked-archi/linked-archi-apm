# Adapting to your own ontology, taxonomy or graph

The short version: **write a profile, not a fork.**

Templates in this package name semantic *roles* rather than vocabulary terms. A
profile binds each role to whatever your dataset calls it. So a custom ontology is
usually a configuration change, and the 28 bundled templates keep working unchanged.

Write a new template when the **question** is new, not when the vocabulary is.

---

## Which situation are you in?

| Situation | What you need |
|---|---|
| Converter output, current layout | Nothing. Use `linked-archi-default`. |
| Output converted before core 0.4.0, carrying `arch:partOfModel` | Override `roles.part_of_model` to `arch:partOfModel`, or re-convert — see [Membership was renamed](#membership-was-renamed-in-core-040) |
| Output from a converter predating `graph/model` | Override three keys — `la-profile recommend --data <graph>` names them |
| Converter run with `--emit-direct-rel-triples` | `linked-archi-direct` |
| A merged store with authored cross-source identity | `linked-archi-merged` |
| Turtle, or any dataset with no named graphs | `examples/flattened-turtle` |
| A custom metamodel extending ArchiMate or BPMN | [Derive a profile](#the-five-step-path) |
| Your own taxonomy | [A `taxonomies` entry](#taxonomies-need-no-new-template) |
| A house field promoted through `--ns-vocab` | [A custom role](#custom-roles) |
| A genuinely new question | [A new template](skills/linked-archi-query/assets/templates/custom/README.md) |
| A vocabulary that is not Linked.Archi at all | [Rebind the core roles](#a-graph-that-is-not-linkedarchi) |

Start with `la-kg profile list` and `la-kg catalog list --profile <candidate>`. If a
bundled profile makes most templates available, you are close.

---

## Membership was renamed in core 0.4.0

`arch:partOfModel` became `arch:inModel`. `roles.part_of_model` in every bundled profile binds the new
name, so a dataset converted before that release answers **nothing** for the five templates that
resolve model membership — `core/define-term`, `core/inventory-summary`, `core/label-collisions`,
`core/provenance` and `notation/bpmn/process-components`.

That failure is silent by nature: the query is valid, the graph is valid, and the result is an empty
table. `la-profile recommend --data <graph>` is what tells you which spelling your dataset actually
uses — it probes both and names the one it found, warning when it is the deprecated one.

Two ways out. Re-convert, which is preferred because the rename came with `arch:inView` and you get
view membership as well. Or override one key:

```yaml
roles:
  part_of_model: arch:partOfModel   # pre-0.4.0 dataset
```

Not bound as a two-element list, tempting as that looks. `role()` returns the first binding only, so a
list would silently prefer one spelling and mask the other rather than matching either.

Upstream retains `arch:partOfModel` as `owl:deprecated` and declares it `rdfs:subPropertyOf`
`arch:inModel`, so a store that applies RDFS entailment needs neither the override nor a re-convert.
Nothing in this package or in the converters applies entailment, so do not rely on it unless you know
your store does.

### View membership is new, and the view templates do not use it yet

The same release added `arch:inView`, a one-hop statement from a concept to a view that every
converter now emits into the semantic graph beside the `archvis:` node layer. `roles.in_view` binds it.

Two templates read it, and they exist because the visual route cannot answer for every dataset:

| question | views graph present | no views graph |
|---|---|---|
| what does this view place? | `core/view-contents` | `core/view-contents-semantic` |
| which views show this element? | `core/view-usage` | `core/view-usage-semantic` |

Prefer the left column wherever the views graph exists. It is the richer route: it carries geometry,
and it can tell two drawings of one element apart. The right column exists for a graph published with
`--views-profile no-views` or `no-diagrams`, where the views graph is gone, the `arch:View` resources
survive in the semantic graph, and the left column returns zero rows — which reads as "this diagram is
empty" rather than "the evidence was dropped at publication".

Each pair names the other in its `alternatives`, so a refusal points somewhere, and neither is a
drop-in for the other in two respects worth knowing. `core/view-usage-semantic` returns no `node`
column, because on that route there is no node; and it reports a view once however many times an
element is drawn on it, where `core/view-usage` reports each node.

`core/views` needs no sibling — it reads the visual route only inside an `OPTIONAL`, so it still lists
every view on a geometry-free graph and simply reports zero nodes. `core/view-diff` has no sibling
yet; it composes `core/view-contents` and is affected the same way.

---

## The five-step path

Worked end to end against the [custom-metamodel example](https://gitlab.com/linked-archi/linked-archi-meta/-/tree/main/examples/custom-metamodel), which
extends ArchiMate 4.0 with `cp:Microservice`, `cp:API`, `cp:MessageBroker`,
`cp:Container` and `cp:resilienceLevel`. The result is
`skills/linked-archi-profile/assets/profiles/examples/cloudplatform.yaml` — about
40 lines, because everything the
core templates need is inherited.

### 1. Author the metamodel

Follow the file-role convention the published metamodels use, so your assets are
discoverable by the same mechanisms:

| File | Holds | Namespace segment |
|---|---|---|
| `<name>-onto.ttl` | OWL classes and properties | `…/onto#` |
| `<name>-metamodel.ttl` | the `arch:Metamodel` manifest | `…/metamodel#` |
| `<name>-tax.ttl` | a SKOS `ConceptScheme` | `…/tax#` |
| `<name>-shapes.ttl` | SHACL | `…/shapes#` |
| `<name>-viewpoints.ttl` | viewpoints | `…/viewpoints#` |

The **manifest** is what makes derivation possible. It is an instance typed
`arch:Metamodel` whose properties point at the constituent graphs:

```turtle
:CloudPlatformMetamodel
    a                           arch:Metamodel ;
    skos:prefLabel              "Cloud Platform Metamodel"@en ;
    arch:basedOnFramework       :CloudPlatformFramework ;
    arch:modelConcepts          <https://…/cloudplatform/onto#> ;
    arch:formalRules            <https://…/cloudplatform/shapes#> ;
    arch:architectureViewpoints <https://…/cloudplatform/viewpoints#> ;
    arch:conceptClassification  <https://…/cloudplatform/tax#> ;
.
```

See [Build your own metamodel](https://meta.linked.archi/docs/practice/build-your-own-metamodel/)
for the authoring detail. This package only reads the manifest.

### 2. Bind it at conversion time

The converters map source constructs onto your classes through a `--type-mapping`
YAML:

```yaml
namespaces:
  cp: https://meta.linked.archi/examples/cloudplatform/onto#

elements:
  component: https://meta.linked.archi/examples/cloudplatform/onto#Microservice
  interface: https://meta.linked.archi/examples/cloudplatform/onto#API

relationships:
  Serving: https://meta.linked.archi/examples/cloudplatform/onto#Serves
```

```bash
archimate2linkedarchi convert models/*.xml \
  --base-iri https://acme.example/la/ \
  --type-mapping config/type-mapping-cp.yml \
  -o out/cp.trig
```

Two other converter flags matter here. `--ns-vocab` promotes author-written
properties (ArchiMate properties, Backstage annotations) into predicates in your own
namespace. `--ns-global-id` sets where those land. Both produce terms the profile
will need to know about.

### 3. Derive a draft profile

```bash
la-kg profile derive cloudplatform \
  --metamodel cloudplatform-metamodel.ttl \
  --type-mapping config/type-mapping-cp.yml \
  --base-iri https://acme.example/la/ \
  --notation cp \
  -o profiles/cloudplatform.yaml
```

Either source works alone; both together is better. Deriving from the type mapping
closes a loop worth closing — the file that told the converter to emit
`cp:Microservice` is the same information a query needs to find it again, so the
graph and the queries cannot disagree.

What comes out carries a header naming its sources and every judgement left to you:

```yaml
# Draft profile 'cloudplatform', derived - not authored.
#
# Check these before relying on it:
#   - manifest declares shapes: https://…/cloudplatform/shapes#
#   - mapping declares 4 direct predicate(s). These are emitted only with
#     --emit-direct-rel-triples, so capabilities.direct_rel_triples is NOT set
#     true here. Verify against the dataset, then set it.
#   - optional roles (owner, element_lifecycle, same_as, exact_match) are
#     inherited from the base profile...
extends: linked-archi-default.yaml
profile: cloudplatform
```

Two things are deliberately **never** guessed:

- **Optional roles** — ownership, lifecycle, identity. A mapping says what *may* be
  emitted, not what was.
- **`direct_rel_triples`** — declaring direct predicates is not the same as having
  run the converter with the flag that emits them.

Guessing either is how a confident empty result gets built.

### 4. Verify against the real dataset

```bash
la-kg profile verify --profile profiles/cloudplatform.yaml --data out/cp.trig
```

This is the step that matters. A profile is a set of claims; `verify` checks them.

| Finding | Meaning | Do |
|---|---|---|
| **error** | Claimed present, absent. A template will run and return nothing while looking correct. | Fix the profile or the dataset. Exit code is 1. |
| **warning** | Claimed absent but present — you are refusing templates unnecessarily. Or a bound role is unused. | Bind it, or leave it and know why. |
| **ok** | Confirmed against the data. | Nothing. |

Iterate until there are no errors. Then:

```bash
la-kg connect --data out/cp.trig
la-kg profile verify --profile profiles/cloudplatform.yaml --data out/cp.trig
la-kg catalog list --profile profiles/cloudplatform.yaml --why
```

`connect` reports the loaded graph shape. Profile verification compares that evidence
with the profile and catches a named-graph mismatch, the single most common cause of
queries that run and return nothing.

### 5. Query, without editing a template

```bash
la-kg query run core/inventory --profile profiles/cloudplatform.yaml --data out/cp.trig
la-kg query run core/elements-by-type --profile profiles/cloudplatform.yaml --data out/cp.trig \
  --set TYPE_IRI=https://meta.linked.archi/examples/cloudplatform/onto#Microservice
```

Custom classes need no role and no template change: they are reachable through
`rdf:type`, and `core/elements-by-type`, `core/neighbours-qualified`,
`core/traceability` and the rest work on them because they resolve *roles* —
label, endpoints, membership — which your metamodel did not change.

---

## Taxonomies need no new template

Classification is plain SKOS, so one template covers every scheme. Add an entry:

```yaml
taxonomies:
  - scheme: https://meta.linked.archi/examples/cloudplatform/tax
    prefix: cptax
    label: Cloud platform service classification
  - scheme: https://meta.linked.archi/core-tax
    prefix: arch-tax
    label: Linked.Archi common taxonomy
```

Then walk any branch:

```bash
la-kg query run core/classified-by --profile profiles/cloudplatform.yaml --data out/cp.trig \
  --set CONCEPT_IRI=https://meta.linked.archi/examples/cloudplatform/tax#PlatformService
```

`core/classified-by` follows `skos:broader` upward from whatever concept you name, so
naming a leaf returns its members and naming a top concept returns the whole branch.
It works identically against the common taxonomy, a notation's own scheme, or yours.

The one requirement is that something in the graph **asserts** the classification.
Converters do not classify elements against a scheme, so this comes from your
pipeline or from an authored enrichment step. If `core/classified-by` returns
nothing, check that first — with `core/discover-predicates` — before suspecting the
query.

---

## Custom roles

Bind a role when a **template needs to name** a custom property. A property that only
appears in output does not need one.

```yaml
roles:
  resilience_level: cp:resilienceLevel
```

Now a template can write `{{ROLE:resilience_level}}` and stay portable across
datasets that spell it differently. Custom roles sit alongside the inherited ones; a
template that needs one declares it under `requires.roles`, so a dataset without it
gets a refusal rather than an empty column.

---

## Editing a profile by hand

Copy the closest bundled profile and use `extends`, so your file states only the
differences and inherits corrections to the base:

```yaml
extends: linked-archi-default.yaml
profile: acme
version: 1

namespaces:
  acme: https://acme.example/vocab#

roles:
  owner: acme:responsibleTeam

capabilities:
  concept_owner: true
```

Two merge rules:

- **Mappings merge key by key**, so rebinding one role leaves the rest alone.
- **Scalars and lists replace outright.** A role bound to a fallback chain is one
  decision, and appending to it from a child would silently change which term
  `{{ROLE:x}}` resolves to.

`extends` resolves beside your file first, then in the profile skill's bundled
`assets/profiles/` directory — so a profile kept next to your graph still inherits
from the base.

Full field reference:
[skills/linked-archi-profile/references/profile-reference.md](skills/linked-archi-profile/references/profile-reference.md).

---

## A graph that is not Linked.Archi

The role layer is not specific to these ontologies. Rebind the seven required roles
and the graph roles, and the core templates work against any RDF graph with elements
and relationships:

```yaml
profile: other-graph
version: 1

namespaces:
  ex: https://other.example/vocab#
  skos: http://www.w3.org/2004/02/skos/core#

graphs:
  layout: single
  named_graphs: false

roles:
  label: skos:prefLabel
  concept_class: ex:Concept
  element_class: ex:Node
  relationship_class: ex:Edge
  rel_source: ex:from
  rel_target: ex:to
  rel_type: rdf:type
```

Expect templates to be refused as you go: without `part_of`, `core/provenance` is
unavailable; without a views graph, `core/view-usage` is. That is the mechanism
working. `la-kg catalog list --profile … --why` tells you exactly what each refusal
needs.

Where a graph reifies relationships differently — a single predicate rather than a
resource with endpoints — the qualified-form templates will not fit, and a small
`skills/linked-archi-query/assets/templates/custom/` set is the honest answer.

---

## Checklist

```bash
python3 bin/la-kg profile derive <name> --metamodel … --type-mapping … -o profiles/<name>.yaml
python3 bin/la-kg connect --data <your>.trig                                # inspect loaded shape
python3 bin/la-kg profile verify --profile profiles/<name>.yaml --data <your>.trig  # until 0 errors
python3 bin/la-kg catalog list --profile profiles/<name>.yaml --why           # what is available
python3 bin/la-kg query run core/inventory --profile profiles/<name>.yaml --data <your>.trig
```

Then commit the profile beside your graph, and tell your agent where both are — a
line in the project's `AGENTS.md` is enough:

```
The architecture graph is at out/cp.trig, converted at https://acme.example/la/.
Use profiles/cloudplatform.yaml.
```

---

## When adaptation is not the answer

- **The dataset lacks something the question needs.** A cross-notation join with no
  identity assertions is not answerable by any profile: cross-tool equivalence
  cannot be derived, so it has to be authored. Report that, and point at the
  reconciliation step.
- **The question needs a differently-converted dataset.** Transitive traversal along
  direct predicates needs `--emit-direct-rel-triples`. Setting the capability true
  without re-converting produces exactly the empty result the refusal prevented.
- **The vocabulary is genuinely incompatible.** If more than a handful of core
  templates get refused, the role layer is fighting the graph. Write a small custom
  set and say so, rather than bending the profile until it lies.
