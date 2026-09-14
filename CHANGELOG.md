# Changelog

Notable changes to linked-archi-apm. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A section here is not optional at release time: `make release-notes` reads it, and
`make release-check` refuses to declare a version ready without one. The release
workflow publishes exactly this text, so what is written here is what a consumer reads.

## [Unreleased]

## [0.3.0] - 2026-09-14
A dataset can now be paired with the vocabulary it conforms to, so what one template
enumerated by hand is derived instead. The converters emit instances, never the ontologies
and taxonomies those instances conform to, which left every schema-level question
unanswerable from an export alone — and the template that needed an answer carried a list
covering 17 of the 49 element classes its ontology declares.

Pairing happens at query time rather than in the pipeline: `la-connect` already accepted
several files, so no export changes and no artifact becomes coupled to a vocabulary version
it must then be kept in step with. The cost is that the operator owns the pairing, so
`verify` now checks it.

### Added
- **Published vocabulary can be attached beside a dataset, and queried.** A conversion emits
  instances, never the ontologies and taxonomies they conform to, so anything schema-level —
  which classes are activities, what category a type belongs to — was unanswerable, and a
  template facing that gap could only enumerate types by hand. A new optional
  `graphs.roles.vocabulary` binds the graph the vocabulary lands in; `la-connect` already
  accepts several files, so pairing happens at query time and no export changes. Its own
  graph role, never `semantic`: ontology classes carry `skos:prefLabel` and would otherwise
  come back as candidates from `core/resolve-element`. `examples/with-vocabulary` is the
  worked profile, `fixtures/vocabulary.trig` the extracted fixture, and `roles.narrower` and
  `roles.subclass_of` the two new bindings it needs.
- **`verify` reports partial or mismatched vocabulary pairing.** Attaching vocabulary at
  query time puts the operator in charge of which files are paired, and a wrong or partial
  choice fails in the quietest way available: no error, just a grouping query returning
  fewer categories, with every element of an uncovered notation absent — which reads as
  "this model has none of those". The probe asks, per notation the profile declares,
  whether the data uses its types and whether the attached vocabulary describes any of its
  classes, and names the notations where the first is true and the second is not. Version
  mismatch is the same finding rather than a separate one, because a notation ontology
  carries its version in its namespace: `archimate3/onto#` and `archimate4/onto#` are
  different namespaces. Silent when no `vocabulary` role is bound.
- **`core/elements-by-category`** — what is in a model, grouped the way its own notation
  groups it. The taxonomy already states which classes each category covers
  (`bpmn-tax:Gateways skos:narrower bpmn:ExclusiveGateway, …`), so the grouping is a
  published fact rather than an opinion in a query. It replaces the reason
  `notation/bpmn/process-components` carries a hand-written table of 17 classes — against
  the 49 the BPMN ontology declares, omitting every gateway and sub-process — under category
  names invented because the standard ones were unreachable. Notation-agnostic: any
  vocabulary declaring `skos:narrower` to its classes works, and a test pins that the
  template names no notation term. Refused without the vocabulary role, with the
  hand-table template as the documented alternative.

## [0.2.0] - 2026-09-14
An audit of the bundled profiles and the whole template catalogue against the published
ontologies, the converter emitters and a large multi-notation export. Every fix below is a
case where a query answered confidently and wrongly rather than failing — an empty column,
an inflated count, a silent zero — because that is the failure mode this package exists to
remove, and it had instances of its own. `PROPOSAL.md` Appendix B records the method, what
was corrected, what was investigated and found already correct, and what remains open.

**Result columns changed**, so a consumer reading them by name needs a look: `core/orphans`
`?type`→`?types`, `core/models` `?source`→`?sources` (now a count), `core/reifies-audit`
`?relType`→`?relTypes`, `notation/leanix/factsheets` `?phase`→`?phases`,
`core/discover-predicates` `?objectKind`/`?example`→`?objectKinds`/`?exampleObject`,
`core/resolve-element` `?g`→`?g_semantic`, and `core/traceability` gains `?relType2`.

### Added
- **A test refuses to let a non-public host reach a commit.** Auditing this package against
  a real estate produces IRIs, model names, digests and a private host — all useful, none
  publishable, and a published commit cannot be unpublished. An allowlist rather than a
  denylist, deliberately: a denylist has to name the customer to exclude them, and protects
  only that one engagement. RFC 2606 documentation names and the reserved IP ranges the
  transport tests use are allowed by rule, and the guard's own rule is tested.
- **Notation templates are gated on the vocabulary they name.** The catalogue carried a
  `notation` label from the start and never consulted it, so a BPMN template offered against
  a C4-only dataset ran and returned nothing — indistinguishable from "this model has no
  sequence flows". A new `notation_namespace` key carries the vocabulary IRI and the gate
  refuses when no declared notation uses it. Keyed on the IRI, not the label: ArchiMate's
  profile slug is `model` while its catalogue directory is `archimate`, so label matching
  would have refused a supported template against every bundled profile. Decision **D20**.
- **Capability verification measures coverage, not presence.** Asked whether a dataset had
  the `rdf:reifies` bridge, the probe answered yes and recommended `true` — which overstates
  any dataset where the bridge is notation-specific, the normal case since each converter
  emits it only under its own flag. Two static probes now distinguish "has it" from "has it
  everywhere", and a measured `partial` is recommended over both `true` and `false`.
  `examples/curated-store` claims `partial` accordingly, which is what its own comments
  always described. Decision **D21**.
- **The catalogue now has to declare every role, graph role and membership walk its
  templates actually render.** Four tests enforce it: three static mirrors of the
  existing "declared roles exist" check, plus one behavioural test. The direction
  matters because `expand_role` raises on a role bound to null, so a template using a
  role it never declared turned a legitimate profile statement — "this dataset does not
  represent that" — into a `RenderError` from inside rendering, with nothing to tell a
  caller which template to use instead. Declared, the same profile gets a refusal
  naming the role.

### Changed
- **24 templates now declare what they render.** 22 gained role declarations, three
  gained the `provenance` graph role, and `core/inventory-summary` and `core/provenance`
  now declare the model membership they walk. No bundled profile changes behaviour —
  the roles involved are all bound in every one — so this closes a silent-failure path
  for custom profiles rather than altering current results.

### Fixed
- **Three more templates return one row per subject.** `core/identity-audit` searched every
  graph, and converter output repeats statements between graphs, so 4 `owl:sameAs` links
  arrived as 215 rows and read as a well-reconciled estate; it is now `DISTINCT`, which
  collapses graph repetition but deliberately not direction, since a one-sided assertion is
  a finding rather than half a pair. `core/reifies-audit` reported one broken bridge once
  per relationship type, and `notation/leanix/factsheets` counted a fact sheet once per
  lifecycle phase — an inventory overstating its own size. Both now aggregate that column.
- **`core/models` returns one row per model.** A model converted from many inputs carries
  many `dct:source` values — a catalogue built from a repository scan carries hundreds — and
  a row each turned "which models are loaded" into a number several times larger than the
  number of models: 263 rows for 55 models on a large export. `?sources` is now a count and
  `?generated` the set of timestamps; the source paths remain available per graph from
  `core/graph-provenance`.
- **`core/label-collisions` normalises any script, not just ASCII.** `[^a-z0-9]` did not
  merely miss accents, it manufactured collisions: every non-ASCII character became a
  separator, so "Café Ünïcode 日本" normalised to "caf n code" and a label written entirely
  in a non-Latin script normalised to the empty string, where it matched every other such
  label. An identity *candidate* list that invents candidates is worse than one that misses
  them. Now `\p{L}\p{N}`, with an empty-normalisation guard.
- **`core/discover-predicates` no longer describes an object pair that never occurred.** The
  object kind and the example were independent `SAMPLE`s, so they could come from different
  solutions — both real, the combination invented. Kinds are now the complete set, which
  also reveals a predicate carrying both IRIs and literals.
- **`core/dependents-direct` points at the right source for its predicates.** It told callers
  to take `PREDICATE_PATH` from `core/discover-relationship-types`, which returns qualified
  classes (`am:Serving`) rather than the predicates they stand for (`am:serves`); following a
  class matches nothing and returns it as an empty answer. Now `core/reified-predicates`.
- **The `?model` column now comes from the profile's membership, not a hardcoded folder
  hop.** `core/coverage-gaps`, `core/elements-by-type`, `core/lifecycle`, `core/orphans`
  and `core/views` resolved it with a single `dct:isPartOf` step, which is the folder edge
  rather than model membership: Appendix A7 records that the folder chain reaches the
  model for BPMN and stops at `folder/Elements` for C4. Because the lookup is `OPTIONAL`
  the mismatch never raised — the column just arrived unbound. Measured on
  `fixtures/augmented.trig` before the change: 0 of 2 C4 containers, 0 of 1 BPMN user
  task, 0 of 10 lifecycle rows and 2 of 5 orphans named a model; now all of them do.
  These templates declare `requires.membership`, so a profile that cannot express
  membership is refused with the reason rather than answering with an empty column.
- **`core/views` no longer promises an unbound node count.** `COUNT` over an unmatched
  `OPTIONAL` is 0 by definition, so the documented null was a check a consumer could
  write and never see fire.
- **`core/orphans` tests for relationships across every semantic graph, and reports each
  element once.** The absence test ran inside the element's own graph, so under the
  partitioned 1.3 layout it asked whether a relationship sat in the same converter input
  file — a boundary the converter chose, not the architecture — and a relationship in a
  sibling partition would have left its endpoint listed as an orphan. No committed
  fixture or observed export splits them, so this is correctness under partitioning
  rather than a measured behaviour change, and it costs nothing: the scope widens to all
  semantic graphs, not to the whole dataset. Separately, the `?type` column is now
  `?types`, concatenated per element as in `core/view-contents`: a row per type reads as
  several elements, and on a large export 1,530 rows described 1,009 elements.
- **`core/coverage-gaps` is dataset-wide, in both directions.** It scoped the type
  search and the absence test to the semantic graph, which was wrong two opposite ways:
  since the 1.3 layout `arch:Model` lives in `graph/model`, so asking which models lack
  a source found no models at all and reported zero gaps — "perfect coverage" for a type
  it never looked at; and a graph-local absence test only proves the property is missing
  from the graph the type was asserted in, so a model carrying `dct:source` in
  `graph/provenance` counted as a gap. On `fixtures/base.trig` the old form returned 0 of
  1 real gap, and widening only the type search would have returned 5. Now `DISTINCT`,
  with independent scopes for the label and membership columns so neither silently
  arrives empty. `requires.graph_roles` no longer claims `semantic`.
- **`linked-archi-default` now names the LeanIX metamodel the converters actually
  emit** — `leanix/metamodel#LeanIXv4`, not `#LeanIX`, which no ontology declares and
  no converter writes. Notation detection is an exact match on this IRI, so every
  LeanIX model went undetected with no error and no empty result to notice. The
  regression test asserts over every metamodel the committed fixtures declare rather
  than one checked by hand.
- **`core/traceability` follows every hop in both directions.** The header promised
  both directions while the two-hop branch matched `source->mid->target` only, so a
  pair joined through a shared intermediate — one component serving both, or two
  things written to the same store — was reported as unconnected. Restoring the three
  missing orientations adds 19 reachable pairs on `fixtures/base.trig`. Two-hop rows
  now also report the second hop's relationship type as `?relType2`; `?direction`
  names the orientation of each hop.
- **`core/resolve-element` reports the graph it matched in.** It projected a
  hand-spelled `?g` while the scope binds `?g_semantic`, and SPARQL projects an
  unbound variable without complaint, so the promised column was empty on every row.

### Changed
- `PROPOSAL.md` gains **Appendix B**, an audit of the bundled profiles and the whole
  template catalogue against the published ontologies, the converter emitters and a
  large multi-notation export: what was corrected, what was investigated and found
  correct, and the open findings in priority order.

## [0.1.0] - 2026-09-13

First release. Six Agent Skills for ontology-guided, evidence-grounded acquisition,
querying and analysis of architecture knowledge graphs built with the Linked.Archi
converters against the meta.linked.archi ontologies.

### Added

- **linked-archi-source** — verified acquisition of RDF from an HTTPS document or a
  pinned Git revision, plus a two-phase handoff that verifies RDF an agent fetched
  through its own read-only GitLab MCP. Never executes SPARQL or repository code.
- **linked-archi-profile** — graph profiles that bind vocabulary decisions, derived
  from converter type-mapping output or a published `arch:Metamodel` manifest, and
  verified against the real dataset rather than assumed.
- **linked-archi-connect** — local file and SPARQL endpoint transport, named-graph
  reporting so a partial graph is visible as partial, and an optional on-disk store
  cache with explicit modes.
- **linked-archi-query** — a profile-resolved SPARQL template library with capability
  gating, read-only enforcement, and a citation line naming template, dataset,
  profile and row count on every result.
- **linked-archi-analyse** — an investigation planner and evidence bundler with an
  explicit evidence model that separates graph facts from inference from unknowns.
  Plans and bundles only; every query is executed by `linked-archi-query`.
- **linked-archi-validate** — SHACL validation in-process, and summaries of existing
  reports, with target-class coverage reported beside the verdict so a conformant
  result that checked nothing is not mistaken for a clean one.
- Committed fixtures extracted from real converter output, covering ArchiMate, BPMN,
  C4, Backstage and two distinct converter graph layouts.
- `apm.yml` declaring no `targets:`, so APM auto-detects the consuming harness rather
  than the package restricting which runtimes may install it.

### Notes

- Every skill is installable directly from the committed tree. There is no build step
  and no install-time bundling: the committed tree is the artifact.
- Runtime and assets live only in the skill that owns them. Cross-skill operations use
  versioned JSON subprocess contracts between installed siblings; no skill imports
  another skill's Python package.
- Python 3.11 or newer, with `PyYAML`. Add `pyoxigraph` for local RDF files, `pyshacl`
  for SHACL validation, and `git` for Git acquisition. Endpoint and HTTPS transport use
  the standard library. No mandatory MCP server.

[Unreleased]: https://github.com/linked-archi/linked-archi-apm/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/linked-archi/linked-archi-apm/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/linked-archi/linked-archi-apm/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/linked-archi/linked-archi-apm/releases/tag/v0.1.0
