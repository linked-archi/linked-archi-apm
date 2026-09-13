# Changelog

Notable changes to linked-archi-apm. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A section here is not optional at release time: `make release-notes` reads it, and
`make release-check` refuses to declare a version ready without one. The release
workflow publishes exactly this text, so what is written here is what a consumer reads.

## [Unreleased]

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
