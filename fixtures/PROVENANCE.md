# Where these fixtures come from

Regenerate with `make fixtures`, which runs `build_fixtures.py`.

Everything in `base.trig` is a real quad from a real conversion. Only the selection
is ours. That matters more than it sounds: the package this one replaces tested 15
templates against a hand-written sample using a vocabulary that did not exist, and
every template passed.

Extraction is necessary but it is **not sufficient**, and this file used to claim
otherwise. Extraction guarantees a fixture was true of *some* build; it says nothing
about *which*, and a fixture extracted from stale output is stale no matter how
faithfully it was extracted. What closes that gap is asserting the shape:
`tests/test_fixtures.py` pins what each fixture must contain, so a regenerated
fixture that quietly changes layout fails a test instead of silently redefining what
the suite is testing against.

## The version stamp proves nothing

Every `.trig` file here is stamped:

```
schema:softwareVersion "1.3.0-SNAPSHOT"
```

`-SNAPSHOT` is a moving label: it names a development line, not a build. That one string
has been attached to at least three different output shapes, all verified:

| Build | What it emits |
|---|---|
| The build the first fixtures came from | no `arch:partOfModel`, no `graph/model` |
| A build in the field (converter commit `052dbc9b`) | provenance nodes under `{base}graph/provenance/source/…` |
| The current source tree | provenance nodes under `{base}provenance/source/…` |

So the stamp cannot tell you what a graph contains. `base.trig` and
`converter-1.3.trig` carry the same stamp today and still differ in whether the semantic
graph is partitioned — which decides whether a suffix selector matches anything.

Consequences, all of which the tests encode:

- **Fixtures are identified by shape, never by stamp.** `tests/test_fixtures.py`
  asserts the markers each fixture must and must not have, and asserts that both share one
  stamp — so the hazard is a pinned fact rather than a footnote.
- **`--rebuild-13` verifies before it overwrites.** A conversion that does not carry
  all three markers is refused with the missing ones named.
- **Nothing reads a provenance node's IRI.** Templates address provenance by predicate, so
  the three shapes above are queryably equivalent and the differences above cost nothing.
  Keep it that way: parsing those IRIs would make the stamp matter again.
- **Do not infer a dataset's layout from its version string** in a profile, a
  template, or a bug report. Detect the graphs.

## Files

| File | Quads | Graphs | What it is |
|---|---|---|---|
| `base.trig` | 1282 | 17 | Real converter output, trimmed. The default case. |
| `augmented.trig` | 1425 | 19 | `base` plus what converters never emit. |
| `flat.ttl` | 1282 | 0 | `base` with graph identity discarded. |
| `converter-1.3.trig` | 284 | 4 | Real converter output, **verbatim**. The one PARTITIONED fixture. |
| `unqualified-forms.json` | 75 pairs | — | Extracted `arch:unqualifiedForm` mappings. Not RDF. |

All of them carry the layout the converters emit today: `arch:Model` and its folder tree
in `graph/model`, membership as a direct `arch:inModel` edge. What still differs
between them is whether the semantic graph is **partitioned** — and that cannot be read
off a version stamp either, since every `.trig` here says
`schema:softwareVersion "1.3.0-SNAPSHOT"`. See
[The version stamp proves nothing](#the-version-stamp-proves-nothing).

All 38 catalogued templates return rows against `augmented.trig` under the
`curated-store` profile committed at
`skills/linked-archi-profile/assets/profiles/examples/curated-store.yaml`. That is
the bar the selection rules below
are tuned to: a fixture on which a template returns nothing is a template the test
suite cannot distinguish from a broken one.

## base.trig

Four graph roles per model — `graph/model`, `graph/semantic`, `graph/provenance`, and
`graph/views` where the notation has diagrams — with `arch:inModel` on every concept,
`arch:inView` on every concept a diagram presents,
and an **unpartitioned** semantic graph. That last point is why `converter-1.3.trig` exists
separately: every conversion below has a single input, and the semantic graph is only split
where a model has more than one.

Extracted from output produced by the converters at their default flags:

| Notation | Source file |
|---|---|
| BPMN | `tools/converters/example-architecture-project/out/bpmn.trig` |
| C4 / Structurizr | `tools/converters/example-architecture-project/out/structurizr.trig` |
| Backstage | `tools/converters/example-architecture-project/out/backstage.trig` |
| LeanIX | `tools/converters/example-architecture-project/out/leanix.trig` |
| ArchiMate | `tools/converters/linked-archi-converters/playground/out/archisurance.trig` |

Those `out/` directories are gitignored in the converter repos, so the sources are
not committed anywhere and these extracts are the only durable record.

**Regenerate them from the JARS, not from `convert-all.sh`.** Those scripts run a Docker
image, and a stale image is what produced the drift this file documents: it emitted output
with no `graph/model` and no `arch:partOfModel` while stamping it with the current version
and a fresh timestamp. The source tree and the fat JARs built from it are the reference.

```bash
export PATH=/path/to/jdk-25/bin:$PATH   # the JARs are class file 69; JRE 21 refuses them
L=tools/converters/linked-archi-converters
cd tools/converters/example-architecture-project
java -jar $L/converter-bpmn/build/libs/bpmn2linkedarchi.jar convert models/bpmn/*.bpmn \
    --base-iri https://example.org/la/ --include-di \
    --diagrams-root models/bpmn/ --diagrams-index models/bpmn/diagram-index.yaml \
    -o out/bpmn.trig
```

…and likewise for structurizr, backstage and leanix, mirroring each `convert-*.sh`'s flags.
ArchiMate comes from the playground: `bash run-archisurance.sh`, which `run-all.sh` skips
because its glob is `run-archimate*.sh`.

Selection rules, all in `build_fixtures.py`:

- **Relationships decide which elements survive.** Elements are kept because a
  relationship reaches them, up to `ELEMENT_BUDGET` per model. An element with no
  relationship makes every traversal template vacuous, so a fixture full of them
  would pass tests while proving nothing.
- **The model resource is always kept.** `core/provenance` finds a model by
  co-location in the semantic graph, and `core/models` needs one to have rows.
- **Provenance is kept verbatim.** It is a dozen quads per model and trimming it
  would defeat the point.
- **Relationships joining different element types are preferred.** A fixture whose
  every edge connects two things of the same kind cannot exercise a cross-layer
  question, and `notation/archimate/layer-crossing` returned nothing until this
  ordering was added.
- **Containers are kept.** A BPMN Process owning its flows, a C4 system owning its
  containers. They are reached by a predicate rather than a relationship resource,
  so the relationship pass never sees them, and `notation/bpmn/process-flow` had no
  process to ask about until they were.
- **Two deliberately unconnected elements per model.** Otherwise `core/orphans`
  finds nothing, because selecting only well-connected elements makes the fixture
  tidier than any real model and leaves the model-quality templates untested.
- **The `arch:View` resources are kept from the semantic graph**, not just the nodes
  from the views graph. A view's label, viewpoint and model membership live with the
  model; without them `core/views` returns nothing while the views graph is visibly
  populated.
- **Views are trimmed hard**, to `VIEW_NODE_BUDGET` nodes per graph, preferring
  nodes that reference a kept element. One ArchiMate model otherwise contributes
  over a thousand nodes, each with geometry and a style blank node. A fixture
  nobody can read is a fixture that drifts.

What the mix deliberately preserves:

- Three graph roles, and models that have only two. Backstage and LeanIX output
  carries no views graph, which is why `capabilities.views_graph` is `partial` and
  why `core/view-usage` returning nothing can mean "this notation has no diagrams".
- Both native-id spellings: `skos:notation` for most notations, `bpmn:id` for BPMN.
- Language-tagged labels in more than one language (`@en`, and `@fr` from
  Archisurance).
- The stale ArchiMate views shape - `arch-vis:Node` with geometry and no
  `archvis:archElement` - alongside the current Structurizr shape, `archvis:ArchNode`
  with `archvis:archElement` and no geometry. Both exist in the wild.
- Two `prov:generatedAtTime` values on the LeanIX model: the author-declared export
  date and the conversion run. A staleness signal, kept on purpose.

## augmented.trig

`base.trig` plus four things the converters do not produce. Without them, four
templates could never be exercised, because they are correctly refused against real
output - and a gated template with no test for its enabled path is a template
nobody has run.

| Added | Count | Why it cannot be extracted | Template it enables |
|---|---|---|---|
| Direct relationship triples | 30 | `--emit-direct-rel-triples` is off by default | `core/dependents-direct` |
| `rdf:reifies` triple terms | 30 | Every converter emits the bridge, but only under `--emit-direct-rel-triples`, which is off by default | `core/reified-predicates`, `core/neighbours-reified`, `core/reifies-audit`, and makes `direct_rel_triples` *checkable* |
| Taxonomy classification | 15 assertions + 4 concept quads | Converters classify nothing against a scheme | `core/classified-by` |
| `skos:exactMatch` in a reconciliation graph | 2 | Cross-source identity is authored and human-reviewed, never derived | `core/identity-audit` |
| `arch:conceptOwner` | 4 | Ownership arrives as a `bs:Ownership` relationship; the core predicate is never emitted | `core/coverage-gaps` against ownership |
| `sh:ValidationReport` in its own graph | 11 | `validate` writes a document, not a graph | `core/validation-summary` |

Two of these are **derived** rather than invented, so their shape follows the data
even though their presence does not. `arch:conceptOwner` is promoted from Backstage's
`bs:Ownership` relationships, which is the enrichment a curated pipeline actually
performs — it is what makes "who owns this" answerable without knowing which notation
the answer came from.

### Where a direct triple's predicate comes from

From `arch:unqualifiedForm` in the ontologies, via `unqualified-forms.json` — the same
extracted mapping the RDF 1.2 bridge uses. Not from lower-casing the class name.

That heuristic is what this fixture used to do, and it invented terms: the mapping is
irregular, so `am:Serving` became `am:serving` where the ontology says `am:serves`. A
fixture asserting predicates no ontology declares is the exact failure this file's opening
rule exists to prevent, and it had a second cost — it made the fixture useless as evidence
for `capabilities.direct_rel_triples`, because a probe that checks a direct edge against
its declared form would rightly have rejected almost all of them.

The `rdf:reifies` bridge is added alongside, on the qualified relationship, because that is
what the converter does: every one of the six emits it inside the same branch that writes
the direct triple, so a dataset with one has the other. Its triple term names the predicate
*and* both endpoints, which is what lets `verify` tell a genuine unqualified form from an
unrelated edge between the same two resources.

An earlier revision added an `arch:relPredicate` declaration for that job. Core never
published that term — the `skos:historyNote` on `QualifiedRelationship` records the
`rdf:Statement` design behind it being dropped — and no converter emits it any more, so the
bridge does the work and the declaration is gone from this fixture.

**A real conversion can have direct edges where this fixture has none.** The converter
reads its predicate from the *type mapping*, and a type mapping may define predicates the
ontology does not declare — `type-mapping-bpmn-full.yml` supplies
`sequenceFlow → bpmn:sequenceFlowTo`, which `arch:unqualifiedForm` does not cover. So the
6 relationships here with no declared form get no direct triple, and BPMN sequence flows
are among them. That is a gap in this fixture, not in the converters; a fixture built from
the type mappings instead would cover them, and is worth doing if a template ever needs a
BPMN direct edge.

The identity assertion is `skos:exactMatch` and not `owl:sameAs`, in both
directions, in a graph of its own. That follows design decision DD-11: prefer
correspondence between records over a claim that two resources are one thing.

Use it with the `curated-store` profile at
`skills/linked-archi-profile/assets/profiles/examples/curated-store.yaml`, which is
the profile these additions describe. All 38 templates are available under it, and none
are refused — which is the point of the additions.

### The RDF 1.2 bridge, and where it bends the extraction rule

This is the one addition whose **presence** is authored, and it deserves saying
plainly, because the rule at the top of this file exists for a reason and this is the
exception to it.

No converter emits `rdf:reifies`. The core ontology specifies the pattern — a
qualified resource paired with a triple term naming the *unqualified* predicate —
and the converters have not implemented it. So a fixture exercising it cannot be
extracted from converter output. It has to be constructed.

What keeps that honest is that only the *shape* is constructed; the **mapping is
extracted**:

- The class-to-predicate pairs come from `arch:unqualifiedForm` in the
  linked-archi-meta ontologies, harvested into `unqualified-forms.json` by
  `build_fixtures.py --refresh-forms` (75 pairs from 109 ontology files).
- Guessing them would have been wrong. The mapping is irregular: `am:Serving` →
  `am:serves`, `am:Flow` → `am:flowsTo`, `am:Composition` → `am:composedOf`. A
  lowercase-first-letter rule produces `am:serving` and `am:flow`, neither of which
  exists.
- Endpoints come from the `arch:source` / `arch:target` already in the extract, so
  the bridge agrees with the data it bridges.

**A class with no declared `arch:unqualifiedForm` gets no bridge.** Six
relationships are in that position — four `bpmn:SequenceFlow` and two `am:UsedBy` —
because the BPMN ontology declares no unqualified forms and `am:UsedBy` (the
ArchiMate 2 name for Serving) has none either. That is why `core/reifies-audit`
reports six genuine `missing-term` rows rather than a defect planted to give the
template something to find. The finding is true, and it is about the ontologies.

The `subject-disagrees` and `object-disagrees` branches have no rows here, by
design: a disagreeing bridge is a corruption, and putting one in a shared fixture
would make every other template's results suspect. Those branches are covered by a
purpose-built store in `tests/test_reifies.py` instead.

Two things this fixture therefore does **not** prove, and no test should claim:

1. **That any real dataset carries the bridge.** `capabilities.rdf_reifies` is false
   in every converter profile, and the templates are refused there.
2. **That a triple term behaves like a triple.** It does not — but this fixture can no
   longer be the evidence, and that is worth stating precisely because it used to be.
   `?s am:serves ?o` now matches here, because the fixture also carries *asserted* direct
   triples using the same declared predicates. Once a predicate is asserted, "a triple term
   is not an asserted triple" cannot be demonstrated with it: an empty result would have
   two possible causes.

   The claim is about RDF semantics rather than about this fixture, so it is asserted
   against a purpose-built bridge-only store in `tests/test_reifies.py` — bridge present,
   direct edge absent, which is the one configuration that can show it. Property paths do
   not traverse triple terms there either.

## converter-1.3.trig

Real converter output, **committed verbatim**: no trimming, no selection, no
additions. 284 quads is small enough to read whole, so there was nothing to gain by
cutting it and a provenance claim to lose.

Four named graphs, and the layout is the whole point:

```
.../backstage/usl-api-registry/graph/model
.../backstage/usl-api-registry/graph/provenance
.../backstage/usl-api-registry/graph/semantic/group-order-service/catalog-info-yaml
.../backstage/usl-api-registry/graph/semantic/group-payment-service/catalog-info-yaml
```

Three things distinguish it from `base.trig`, and `build_fixtures.py --rebuild-13`
refuses to install a file missing any of them:

| Marker | Count here | Why it matters |
|---|---|---|
| `arch:inModel` | 13 | Model membership is a direct one-hop edge, not co-location in a graph |
| a `graph/model` graph | 1 | `arch:Model` moved out of the semantic graph |
| a partitioned semantic graph | 2 | `graph/semantic/{repo}/{path}`, one per input |

**No graph in this file ends with `graph/semantic`.** That is not a detail: a
selector written as `STRENDS(STR(?g), "graph/semantic")` matches nothing here, which
is why a profile can report "no graph matching `graph/semantic`" against a dataset
whose semantic content is plainly present.

### Why a multi-input conversion

`IriMinting` partitions the semantic graph *by input, where a model has more than
one*. A single-file conversion emits a plain `graph/semantic` and therefore cannot
demonstrate the partitioned shape, however current the converter is — verified, and
that exact case is one of the two the `--rebuild-13` gate rejects.

So the input is the converter project's own Backstage catalog, distributed across two
synthetic repositories. The descriptors are copied unchanged; only which directory
each one lands in is ours, and `--source-map` supplies the repository, ref, commit
and blob URL that a real pull would have recorded. Regenerate with:

```
python3 fixtures/build_fixtures.py --emit-13-inputs /tmp/r13     # writes the layout
# convert it (see the printed recipe), then:
python3 fixtures/build_fixtures.py --rebuild-13 /tmp/converter-1.3.trig
```

The recipe is executable rather than prose, and it has been round-tripped: emitting
the inputs and re-converting reproduces this fixture's 284 quads and identical graph
set.

`make fixtures` does **not** rebuild it. Producing it needs the converter jars and a
JDK matching the one they were built with (the jars are class file 69, so a Java 21
runtime refuses them), which is more than the default extraction needs. The default
run reports the fixture's state and says it left it alone.

### Provenance terms here are conditional on the invocation

Worth knowing before treating this fixture as the definition of "1.3 provenance". Some
terms appear only because of *how* the converter was called, not because the version
emits them unconditionally:

| Term | Present | Requires |
|---|---|---|
| `arch:inModel`, `prov:qualifiedDerivation`, `prov:wasDerivedFrom`, `schema:name`, `dct:isPartOf` | yes | nothing beyond 1.3 |
| `schema:sha256`, `prov:alternateOf`, `schema:url` | yes | `--source-map` |
| `dct:identifier` on the agent | yes | `--image-ref` |
| `schema:email` | **no** | an owner with an email in the source descriptors |

A profile that binds these as unconditionally-present roles will be wrong about
conversions run without a source map. They are optional in practice.

## flat.ttl

`base.trig` with every quad moved to the default graph, which is what the
converters' `TURTLE` output collapses to and what happens when a TriG file is
renamed `.ttl`.

It exists because this is the shape in which a graph-scoped query returns nothing
while looking correct - the defect this package was built to remove. Use it with a
profile whose `graphs.layout` is `single`; `la-kg connect` reports the shape, and
`la-kg profile verify` refuses a graph-scoping profile when pointed at it.

## Deliberate non-goal: byte stability

Blank nodes for folder list items and view styles are regenerated on every
conversion, so re-running `make fixtures` produces a semantically identical file
that does not diff cleanly. Assert on shape and counts, never on bytes.
