# linked-archi-apm

Agent skills for querying an architecture knowledge graph — one built by converting
ArchiMate, BPMN, C4/Structurizr, Backstage and LeanIX models into RDF against the
[meta.linked.archi](https://meta.linked.archi) ontologies with the
[Linked.Archi converters](https://gitlab.com/linked-archi/linked-archi-tools/converters/converters).

There is no application here, and that is deliberate. Given the graph's conventions
as skills and a tested query library, a coding agent in an ordinary IDE becomes a
competent architecture analyst. The artifact is the context and the templates.

What it adds over "point an LLM at the ontology" is one thing: **it refuses
questions the dataset cannot answer, instead of returning an empty result that reads
like a finding.**

```
Template 'core/dependents-direct' cannot run against profile 'linked-archi-default':
  - capability 'direct_rel_triples' is False but this template needs True
Try instead: core/dependents-qualified, core/neighbours-qualified
This is a refusal, not an empty result: running it anyway would return no rows and
read as 'nothing exists'.
```

## Features

**Acquire a remote graph.** `linked-archi-source` fetches a static RDF document over
bounded HTTPS, extracts explicitly selected RDF blobs from a Git revision, or prepares
a read-only two-phase handoff for an agent-provided GitLab MCP. It verifies RDF and
optional URL/Git SHA-256 pins before atomically promoting content into an immutable
local cache; GitLab MCP requires a caller-supplied SHA-256 and records its commit only
as MCP-reported. Source manifests preserve the resolved URL or verified Git commit,
and connect receives only local paths. Exact cache hits work offline.

**Attach a dataset.** Local RDF files — `.trig` and `.nq` keep named graphs, `.ttl`,
`.nt`, `.rdf`, `.jsonld` and `.n3` flatten them — or a read-only SPARQL endpoint.
Repeat `--data` to merge several files into one store, or set `LINKED_ARCHI_DATA`.
`la-connect datasets` reports candidate files near the working directory and
deliberately chooses none of them; `la-connect connect` says how many quads loaded,
whether named graphs survived, and which inputs lost graph identity on the way in.

**Adapt to the vocabulary.** Six profiles ship: three for converter output shapes
(default, `--emit-direct-rel-triples`, merged-with-reconciliation) and three worked
examples including a custom cloud-platform metamodel and a flattened store.
`la-profile derive` drafts one from a converter type-mapping file or a published
`arch:Metamodel` manifest, `--extends` layers it over another, and `la-profile
resolve`/`show` expose what a role binds to. Roles, prefixes, graph layout and
taxonomy terms are all data, so a custom ontology or taxonomy needs no code change.

**Check the profile against reality.** `la-profile verify` probes the dataset,
reports drift between claimed and observed terms, and exits non-zero when a claim is
false. `--all` verifies every profile so you can find which one actually fits.

**Ask a question.** 39 tested templates in four groups — analysis, enrichment,
quality and views — spanning neighbours, transitive dependents, traceability paths,
taxonomy classification, lifecycle, ownership, coverage gaps, orphans, identity
audit, provenance and diagram usage, plus notation-specific templates for ArchiMate,
BPMN, C4, Backstage and LeanIX. `catalog list --why` explains which templates this
dataset can and cannot support. `query render` produces SPARQL without executing it,
`query run` executes it, and results come back as tab-separated rows with the citation
kept as `#` comments — `--format md` for an aligned table, `--format json` for the full
envelope, plus `--limit` and `-o`.

**Get refused instead of misled.** Every template declares the roles and
capabilities it needs. A missing dependency is a refusal naming the reason and
suggesting alternatives; a `partial` one runs with a caveat. Every result carries a
provenance footer: template, query hash, dataset, profile version, timestamp and row
count.

**Investigate, not just query.** Eight analysis patterns cover impact and
dependency, traceability, coverage, governance and decisions, lifecycle and portfolio
comparison, cross-notation questions, views, and model quality. Answers separate
graph facts from inference from unknowns, and state what cannot be concluded.

**Validate honestly, without a JVM.** `la-validate run` executes SHACL in-process
through `pyshacl` — no converter, Java runtime or network access — and reports
target-class coverage and vacuity beside the verdict. A run that matched no target
class exits non-zero rather than reporting the pass that a namespace mismatch would
otherwise produce. `la-validate report` summarises a report somebody else already
generated, and says plainly that coverage is not recoverable from one. Shapes are
never bundled: pass local files, or acquire the published documents once with
`la-kg source url`. Coverage, orphan and provenance queries answer the model-quality
questions no shape covers, and validation runs only when you ask for it.

### Operational properties

- **Read-only, fail-closed.** One policy implementation, owned by
  `linked-archi-query`; update, insert, delete and load are rejected before any
  backend is touched, and connect delegates to that owner's lint before every raw
  execution.
- **Independently installable.** Each skill is a directory that works on its own for
  what it owns; nothing is generated, bundled or copied at install time, and no skill
  imports another's Python package. Cross-skill calls use versioned JSON subprocess
  contracts.
- **Small dependency surface.** Python 3.11+ and `PyYAML`; add `pyoxigraph` for
  local or remotely acquired RDF files, `pyshacl` for SHACL validation, and `git`
  only for Git acquisition. Endpoint and HTTPS transport use the standard library.
  No triplestore, JVM or MCP server is required.
- **Offline capable.** Local querying and exact source-cache reuse work without a
  network, including the committed fixtures. Only a cache miss, endpoint access, a
  remote fetch, or converter-run SHACL needs an external service.

Two limits worth knowing: pyoxigraph exposes no query timeout, so `--timeout-ms`
bounds endpoint queries only and row limits are the sole bound locally; and
`la-profile verify` needs the connect and query skills installed alongside it.

## Why a skill and not a good prompt

Generic text-to-SPARQL fails on this graph for structural reasons no ontology dump
conveys, and it fails *quietly* — producing queries that run, return plausible rows,
and are wrong.

- **Relationships are resources, not triples.** Every relationship is an
  `arch:QualifiedRelationship` with `arch:source`/`arch:target`. The direct
  `subject predicate object` triple is opt-in at conversion time and off by default,
  so on an ordinary dataset it is simply not there.
- **Everything is in named graphs.** A query without a `GRAPH` clause matches the
  default graph, which converter TriG leaves empty. Measured: the same pattern
  returns 0 rows unscoped and 13 scoped.
- **Ownership, lifecycle and cross-source identity are absent or notation-specific.**
  `arch:conceptOwner` appears in no converter output. Identity across tools cannot be
  derived and is never emitted; it is authored.
- **Some IRIs denote records about a thing.** A LeanIX fact sheet is a document about
  an application, not the application.

Each produces a query that succeeds and misleads. That knowledge belongs in a
version-controlled, testable artifact rather than a prompt somebody retypes.

## Install

Every skill is directly installable from the committed tree; there is no build or
install-time bundling step.

**With APM**, which is the intended route. The package declares no `targets:`, so APM
auto-detects your runtime from the project and promotes each of the six skills into it:

```bash
apm install linked-archi/linked-archi-apm#v0.3.0
apm install .                    # from a local clone
```

Name the harnesses yourself when the project has no signal to detect, or when you want
the skills somewhere other than the current project:

```bash
apm install . --target claude,codex,kiro   # or -t all
apm install . --root /tmp/apm-out          # redirect every write under a directory
apm install . -g --target kiro             # user scope (~/.apm/)
```

`apm targets` shows what auto-detection resolves to before you commit to it. Full flag
set in [`apm install`](https://microsoft.github.io/apm/reference/cli/install/), deploy
paths in the [targets
matrix](https://microsoft.github.io/apm/reference/targets-matrix/), and per-harness skill
locations in [USAGE.md](USAGE.md#choosing-targets).

`pyoxigraph` is needed only for local file execution, and `PyYAML` for profiles:

```bash
pip install PyYAML pyoxigraph
```

To upgrade or remove it later — `apm update`, `apm uninstall`, `make uninstall-local`, or by
hand for a copy — see [Upgrading and removing
it](USAGE.md#upgrading-and-removing-it).

**Without APM**, copy the skill directories into whatever your client reads:

```bash
cp -r skills/* ~/.claude/skills/     # Claude Code
cp -r skills/* ~/.kiro/skills/       # Kiro
```

**Working on the package** rather than using it:

```bash
git clone https://github.com/linked-archi/linked-archi-apm && cd linked-archi-apm
pip install PyYAML pyoxigraph
make check                                # validates skills and runs the test suite
make install-local                        # symlink into ~/.kiro/skills
make link-cli BIN_DIR=/opt/homebrew/bin   # optional la-kg dispatcher
```

Ownership is strict. `linked-archi-source` owns remote acquisition, `la-source`,
and source manifests/cache contracts; `linked-archi-profile` owns
`linked_archi_profile`, `la-profile`, and `assets/profiles`;
`linked-archi-connect` owns `linked_archi_connect` and `la-connect`;
`linked-archi-query` owns `linked_archi_query`, `la-query`, and `assets/templates`;
`linked-archi-validate` owns `linked_archi_validate` and `la-validate`;
`linked-archi-analyse` owns `linked_archi_analyse`, `la-analyse`, and
`assets/patterns.json`. All six own runtime, and none of them owns execution twice:
analyse plans and bundles but issues no query at all. Operations spanning skills use JSON
subprocess contracts between installed siblings; no skill imports another skill's
Python package. Source emits the existing connect target shape and never accepts a
query. Connect invokes the query owner's lint command before every raw execution,
preserving one read-only policy implementation rather than copying it. Validate runs
SHACL and never executes SPARQL, so read-only enforcement stays in one place.

Dependencies: Python 3.11+ and `PyYAML`; add `pyoxigraph` for local or acquired RDF
files, `pyshacl` for SHACL validation, and `git` for Git acquisition. Endpoint and HTTPS transport use the standard
library. GitLab MCP is optional and agent-mediated; no mandatory MCP server is
required.

## Five minutes

Everything below runs against the committed fixtures, which are extracts of real
converter output.

```bash
make check                              # 6 skills valid; test suite passes
export PATH="$PWD/bin:$PATH"

la-kg connect --data fixtures/base.trig
la-kg query run core/inventory --data fixtures/base.trig
la-kg query run core/neighbours-qualified --data fixtures/base.trig \
  --set FOCUS_IRI=https://example.org/la/bpmn/order-fulfillment/element/Task_Payment
```

```
| direction | rel            | relType            | other         | otherLabel      |
|-----------|----------------|--------------------|---------------|-----------------|
| incoming  | .../Flow_2     | bpmn:SequenceFlow  | .../Task_...  | Validate Order  |
| outgoing  | .../Flow_3     | bpmn:SequenceFlow  | .../Task_Ship | Ship Order      |

core/neighbours-qualified | query 6384a1b8316a | dataset base.trig |
profile linked-archi-default v1 | 2026-08-29T20:40:52Z | 2 row(s)
```

Then ask where that came from, and see a refusal working:

```bash
la-kg query run core/provenance --data fixtures/base.trig \
  --set FOCUS_IRI=https://example.org/la/bpmn/order-fulfillment/element/Task_Payment

la-kg catalog list --profile linked-archi-default --why
```

## The six skills

| Skill | Use it to |
|---|---|
| `linked-archi-source` | Materialize verified RDF from HTTPS, Git, or an optional read-only GitLab MCP into an immutable local cache. |
| `linked-archi-profile` | Establish, verify and derive the profile that tells the others what this dataset calls things. Adapt to a custom ontology or taxonomy. |
| `linked-archi-connect` | Attach a dataset or endpoint and report honestly what loaded. |
| `linked-archi-query` | Answer a question from a tested, profile-resolved template library. |
| `linked-archi-analyse` | Run a multi-query investigation and answer as a traceable evidence bundle. |
| `linked-archi-validate` | Run SHACL in-process, or read a report already produced, and report coverage beside the verdict. |

`linked-archi-source` is optional when the graph is already local or queryable as a
SPARQL endpoint. Its ready response is the existing connect target and its manifest
keeps acquisition provenance separate from model provenance. `linked-archi-query`
alone provides catalogue browsing and query linting. Rendering also needs
`linked-archi-profile`; execution additionally needs `linked-archi-connect`.
`linked-archi-analyse` plans an investigation and bundles its evidence, and delegates
every execution to that chain: `la-analyse plan` emits the `la-query` commands and
`la-analyse bundle` assembles the envelopes they wrote. All six skills own runtime.
`linked-archi-validate` is independent of the querying chain: it runs SHACL in-process
and reads existing reports, and is invoked only when validation is explicitly requested.

## How it works

Templates name semantic **roles**; a **profile** binds each role to a term for one
dataset. So no template contains a vocabulary IRI, a `PREFIX` line, or an assumption
about graph layout.

```yaml
roles:
  label: skos:prefLabel
  rel_source: arch:source
  owner: null                   # not represented in this dataset

capabilities:
  direct_rel_triples: false     # --emit-direct-rel-triples was not used
  views_graph: partial          # present for some models, absent for others
  rdf_reifies: false            # no RDF 1.2 bridge, and SPARQL 1.2 not assumed
```

Each template declares what it needs. A missing dependency becomes a refusal with a
reason and an alternative; a `partial` one runs with a caveat. And a profile is not
just a claim — `la-kg profile verify` probes the dataset and reports drift, exiting
non-zero when a claim is false.

That is also what makes a custom ontology cheap: derive a profile from your
`arch:Metamodel` manifest or your converter type-mapping, verify it, and the existing
templates work.

```bash
python3 bin/la-kg profile derive acme --metamodel acme-metamodel.ttl -o profiles/acme.yaml
python3 bin/la-kg profile verify --profile profiles/acme.yaml --data out/acme.trig
```

## Adapting to your own graph

Write a profile, not a fork. [ADAPTING.md](ADAPTING.md) walks the five-step path end
to end, with a worked custom metamodel.

## Documentation

| Document | For |
|---|---|
| [USAGE.md](USAGE.md) | Installing, acquiring or connecting a graph, querying, working in an IDE, running a demo |
| [ADAPTING.md](ADAPTING.md) | Custom ontologies, taxonomies, and non-Linked.Archi graphs |
| [PROPOSAL.md](PROPOSAL.md) | Design record, decision log, and the verification evidence |
| [CONTRIBUTING.md](CONTRIBUTING.md) | The rules the test suite enforces, and why each exists |
| [SECURITY.md](SECURITY.md) | Reporting, and what the package does with your data |
| [fixtures/PROVENANCE.md](fixtures/PROVENANCE.md) | Where the fixtures come from and how to regenerate them |
| [skills/linked-archi-query/assets/templates/custom/README.md](skills/linked-archi-query/assets/templates/custom/README.md) | Writing a template |

Each skill also carries its own references — the graph's shape, troubleshooting,
safety, the evidence model, the output contract.

## What this is built on

Four facts about the graph, each measured against real converter output rather than taken
from documentation, and each pinned by a regression test:

- **The vocabulary is published**, and the terms an author reaches for first are mostly
  wrong. Templates therefore name *roles*, never terms; the profile binds them.
- **Graph scoping has to be a profile decision.** An unscoped pattern returns nothing against
  TriG; a hardcoded `GRAPH` clause returns nothing against flattened Turtle. Both ship.
- **The qualified relationship form is the only form by default.** The direct
  `{src} {pred} {tgt}` shortcut needs `--emit-direct-rel-triples`, which is off.
- **There is no validation graph.** The converters' SHACL report is a document, not data.

Each is a way a plausible query returns nothing, or returns rows meaning something else.
[PROPOSAL.md](PROPOSAL.md) has the detail, the evidence and the decision log.

## Testing

```bash
make check        # what CI runs: skill validation and the test suite
make verify       # check the default profile against the committed fixture
make fixtures     # re-extract fixtures from real converter output
```

The packaging tests enforce strict ownership, absence of generated copies, isolated
owner commands, exact companion failure messages, and combined sibling execution.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The ontologies this binds to
are published separately under CC-BY-4.0 and are not vendored here.
