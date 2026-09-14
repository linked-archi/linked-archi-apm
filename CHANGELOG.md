# Changelog

Notable changes to linked-archi-apm. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A section here is not optional at release time: `make release-notes` reads it, and
`make release-check` refuses to declare a version ready without one. The release
workflow publishes exactly this text, so what is written here is what a consumer reads.

## [Unreleased]
### Added
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

[Unreleased]: https://github.com/linked-archi/linked-archi-apm/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/linked-archi/linked-archi-apm/releases/tag/v0.1.0
