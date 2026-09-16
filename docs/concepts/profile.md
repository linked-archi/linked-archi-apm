# The graph profile

A profile is the answer to one question: **what does this dataset call things?**

Two graphs converted from the same ArchiMate model can differ in namespace, graph layout,
relationship form and membership predicate, all legitimately, depending on converter flags. A
template written against one of them returns nothing against the other — silently. The profile is
what makes a template portable, and what lets the catalogue refuse a template the dataset cannot
support instead of running it into an empty result.

## What a profile document contains

Every section is optional, and `extends` is resolved depth-first before validation.

| Section | Type | Purpose |
|---|---|---|
| `profile` | string | The name. Defaults to the file stem, then `anonymous`. |
| `version` | positive int | Declared version, default `1`. Deliberately **not** part of the fingerprint. |
| `description` | string | What this profile describes. |
| `base_iri` | string | The minted-IRI base. |
| `extends` | path | Parent profile, resolved before construction. |
| `namespaces` | map | Prefix to IRI. Names and values are stripped and must be non-empty. |
| `roles` | map | Role name to one IRI, a non-empty list of IRIs in preference order, or `null`. |
| `graphs` | map | `layout`, `named_graphs`, `roles`, `required`, `descendants`. |
| `capabilities` | map | `true`, `false` or `"partial"`. `label_language` is a string instead. |
| `notations` | map | Slug to a spec: `label`, `metamodel`, `namespace`, `native_id`, `present`. |
| `taxonomies` | list | SKOS concept schemes available for classification queries. |
| `navigation` | map | Only `model_membership`, and inside it only `mode` and `max_depth`. |
| `limits` | map | `default_row_limit`, `max_row_limit`, `timeout_ms`. |

The bundled `linked-archi-default` binds **59 roles**, 4 graph roles and 14 capabilities.

!!! note "Any other key under `graphs` becomes a graph role"
    The guard list is exactly `layout`, `named_graphs`, `roles`, `required`, `descendants`.
    Anything else under `graphs` is folded in as a graph role, which is how `validation:` and
    `vocabulary:` are declared unbound in the default profile.

## Roles, not literal IRIs

A template names a role; the profile binds it. `core/resolve-element` asks for `label`, and the
default profile answers `skos:prefLabel`. A role may bind a **list** in preference order —
`native_id` is `[skos:notation, bpmn:id]`, because BPMN carries its own identifier predicate —
and a role bound to `null` is declared-but-unbound, which is how a template gets refused rather
than rendered against nothing.

```yaml
roles:
  label: skos:prefLabel
  native_id: [skos:notation, bpmn:id]
  rel_source: arch:source
  rel_target: arch:target
  owner: null            # nothing in converter output carries ownership
```

## Graph layout

```mermaid
flowchart TB
  subgraph pmt["layout: per-model-triple (default)"]
    direction LR
    GM["graph/model<br/><small>arch:Model resources</small>"]
    GS["graph/semantic/*<br/><small>one per input</small>"]
    GV["graph/views"]
    GP["graph/provenance"]
  end
  subgraph single["layout: single"]
    DG["default graph<br/><small>everything, no graph identity</small>"]
  end
```

Turtle carries no graph identity, so a Turtle export lands entirely in the default graph. That is
why `examples/flattened-turtle` exists with `layout: single`: under it a scoped question is
answered unscoped, with a caveat, rather than returning nothing. `la-connect` says so at load
time, verbatim:

```
warning: no named graphs in this dataset. Use a profile with layout 'single' from sibling
linked-archi-profile/assets/profiles/ or every scoped query returns nothing.
```

## Capabilities

A capability is a claim about the dataset, taking `true`, `false` or `"partial"`. `partial` means
present for some models and absent for others — a template requiring a partial capability runs and
carries a warning.

| Capability | Default profile | What it claims |
|---|---|---|
| `model_graph` | `true` | Model resources live in their own graph. |
| `part_of_model_edge` | `true` | A direct membership edge exists. |
| `graph_bundles` | `true` | Named graphs are described as `prov:Bundle`. |
| `partitioned_semantic_graphs` | `true` | One semantic graph per input. |
| `direct_rel_triples` | `false` | The direct source-predicate-target triple exists beside the qualified form. |
| `rdf_reifies` | `false` | The RDF 1.2 reification bridge is present. |
| `views_graph` | `partial` | Diagrams are present, for some notations. |
| `provenance_graph` | `true` | A provenance graph is present. |
| `view_geometry` | `partial` | Node bounds are recorded. |
| `identity_assertions` | `false` | Cross-source identity has been asserted. |
| `element_lifecycle` | `partial` | Element-level lifecycle status is recorded. |
| `concept_owner` | `false` | Ownership is recorded on concepts. |
| `validation_in_graph` | `false` | A SHACL report is loaded as a named graph. |
| `label_language` | `en` | Language tag to prefer for labels. |

There is no whitelist of capability names: any name is legal, and an undeclared capability reads as
absent on purpose.

## Notations, and whether the data holds any

A notation spec says the profile can speak that notation. It is matched on the **namespace IRI**,
never the slug: ArchiMate's slug in the default profile is `model`, because the converter's
`--path-model` defaults to that and is configurable.

```yaml
notations:
  bpmn:
    label: BPMN 2.0
    metamodel: https://meta.linked.archi/bpmn/metamodel#BPMN2
    namespace: bpmn
    native_id: bpmn:id
    present: false        # this dataset holds no BPMN
```

`present` is a claim about the dataset in the same sense a capability is:

- `false` — every template written against that notation is **refused**, naming the notation
  rather than returning an empty table that implies absence.
- `partial` — runs with a caveat.
- `true` — changes nothing. The claim can only ever remove an answer, never manufacture one.
- **absent** — unknown, and nothing is refused on an unknown. A profile that never mentions
  presence behaves exactly as it did before the key existed.

`la-profile verify` measures it and reports which notations have models. It is a warning, never an
error: no dataset is obliged to hold every notation a profile can read.

## How gating decides

```mermaid
flowchart TD
  START["template + profile"] --> ROLE{"every required<br/>role bound?"}
  ROLE -->|no| REF["REFUSED<br/><small>exit 1, names an alternative</small>"]
  ROLE -->|yes| GR{"required graph<br/>role bound?"}
  GR -->|"no, and the dataset<br/>has no named graphs"| WARN["runs with a caveat"]
  GR -->|"no, but named<br/>graphs exist"| REF
  GR -->|yes| CAP{"capability<br/>matches?"}
  CAP -->|"required true,<br/>actual false"| REF
  CAP -->|"required true,<br/>actual partial"| WARN
  CAP -->|yes| MEM{"membership mode<br/>supported?"}
  MEM -->|no| REF
  MEM -->|yes| NOT{"notation<br/>declared?"}
  NOT -->|no| REF
  NOT -->|"yes, present: false"| REF
  NOT -->|"yes, present: partial"| WARN
  NOT -->|"yes, or unstated"| OK["available"]
```

A refusal always names why and, where the catalogue declares one, what to run instead:

```
Template 'notation/bpmn/process-flow' cannot run against profile 'no-bpmn':
  - profile 'no-bpmn' declares notation 'bpmn' but records it as absent from this dataset, so no
    model this bpmn template asks about is here. Refused rather than answered with no rows, which
    would read as 'none exist'. Confirm with core/inventory-summary, and if the notation is in
    fact loaded, set notations.bpmn.present true - `la-profile verify` reports which notations
    have models here.
This is a refusal, not an empty result: running it anyway would return no rows and read as
'nothing exists'.
```

## The bundled profiles

| Profile | Extends | Describes |
|---|---|---|
| `linked-archi-default` | — | Converter output with default flags: qualified relationships only, model resources in their own graph, a semantic graph per input, membership as a direct `arch:inModel` edge. |
| `linked-archi-direct` | default | Output with `--emit-direct-rel-triples`. Traversal templates become available; double-counting becomes possible. |
| `linked-archi-merged` | default | Merged multi-model store with an authored reconciliation graph. |
| `examples/curated-store` | merged | Reconciliation graph, direct triples and a loaded SHACL report. The profile `fixtures/augmented.trig` is built for. |
| `examples/flattened-turtle` | default | `layout: single`. Graph-scoped questions answered unscoped, with a caveat. |
| `examples/with-vocabulary` | default | Converter output plus the published ontologies and taxonomies paired as Turtle beside it, so schema-level questions become answerable. |
| `examples/cloudplatform` | default | A custom metamodel extending ArchiMate 4.0, reached through derivation rather than a fork. |

## Verifying the claims

```mermaid
sequenceDiagram
  participant U as caller
  participant P as la-profile
  participant Q as la-query
  participant C as la-connect
  U->>P: verify --profile P --data graph.trig
  P->>P: plan every probe against a stub
  Note over P: the probe set must not vary<br/>with a probe ANSWER
  P->>Q: _machine lint (every probe)
  P->>C: _machine execute-many (one round trip)
  C-->>P: results, keyed by query text
  P->>P: replay the same pass over the results
  P-->>U: findings: error / warning / info
```

Findings carry a severity, and only `error` moves the exit code:

| Severity | Meaning | Exit |
|---|---|---|
| `error` | A claim in the profile is false about this dataset. | 1 |
| `warning` | A bound role is unused here, or drift worth knowing. | 0 |
| `info` | Confirmed. Hidden unless `--all`. | 0 |

Where a fix is unambiguous, the finding carries it and `--emit-fix` writes a child profile
overriding only the contradicted claims:

```bash
python3 scripts/la-profile verify --profile linked-archi-default --data graph.trig \
    --emit-fix > my-graph.yaml
```

Unused roles and missing graph roles are explicitly not mechanically fixable, and are reported for
a human to decide.

!!! info "The verification marker"
    A clean verification writes a marker keyed on the SHA-256 of
    `dataset_id`, `profile.name` and the profile **fingerprint** — not the declared `version`. The
    fingerprint covers `base_iri`, `namespaces`, `roles`, `graphs`, `capabilities`, `notations`,
    `taxonomies` and `navigation`, so editing any of them invalidates the marker automatically.
    Until a marker exists, every query result carries a caveat saying the profile was never
    verified against this dataset.
