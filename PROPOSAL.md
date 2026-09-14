# linked-archi-apm: proposal, design record, and progress tracker

**Status:** released, Apache-2.0, installable directly by APM (v0.1.0)
**Last updated:** 2026-09-08

One document, three jobs. It records **why** this package exists, **how** it is
designed and what evidence each decision rests on, and **where the work stands**.
Update the status table and the changelog as things change; treat the design
sections as the record of what was decided and why, and amend them rather than
silently contradicting them.

---

## 1. What this is

The first APM package for the linked.archi approach: an agent-usable way to ask
architecture questions of an RDF graph produced by the linked.archi converters.

The converters turn ArchiMate, BPMN, C4/Structurizr, Backstage and LeanIX models into RDF
against published ontologies. That output is queryable, but not *usefully* queryable by an
agent on its own, for three reasons this package exists to remove.

**An agent cannot know the vocabulary from the data.** The graph uses
`https://meta.linked.archi/core#` with `arch:source`, `arch:target`,
`arch:QualifiedRelationship`, `arch:modelConformsToMetamodel` and a per-notation namespace
alongside. Guessing any of it produces queries that return nothing, or worse, return rows
that mean something else. §2 records the terms that actually exist and how each was checked.

**The same question needs a different query per deployment.** Converter TriG has named
graphs; a curated triplestore has its own graph IRIs; flattened Turtle has none. A query
hardcoded for one returns zero rows against the others, silently.

**Nothing tells an agent which questions the dataset can answer.** Direct relationship
triples, the RDF 1.2 bridge, view geometry and validation reports are each present or absent
depending on converter flags and pipeline. Without a way to know, an agent runs a query that
cannot work and reads the empty result as a finding.

The answer to all three is the **graph profile** in §3: one artifact that names the
vocabulary, describes the graph layout, and declares what the dataset supports — verifiable
against the data rather than asserted. Templates are written against roles, so they are
portable; capabilities are gated, so an unanswerable question is refused with a reason
instead of answered with nothing.

Six Agent Skills sit on top of it, listed in §5. Everything is verified against fixtures
extracted from real converter output, recorded in
[Appendix A](#appendix-a-verification-evidence).

---

## 2. Four facts the design rests on

Each was measured against real converter output rather than taken from documentation, and
each now has a regression test that fails if it stops being true. They are stated here
because every one of them is a way a plausible-looking query returns nothing, or returns
rows that mean something else. Evidence in
[Appendix A](#appendix-a-verification-evidence).

### F1. The vocabulary is published, and nearby guesses are wrong

The terms that exist, against the ones an author reasonably reaches for first:

| Plausible guess | What the graph actually uses |
|---|---|
| `la:` under an `/ontology/core#` path | `arch: https://meta.linked.archi/core#` |
| one `am:` ArchiMate namespace | `am: .../archimate3/onto#` and `am4: .../archimate4/onto#`, versioned separately |
| `relSource` / `relTarget` | `arch:source` / `arch:target`. The others belong to a withdrawn `rdf:Statement` design the converters dropped |
| a `relType` property | `rdf:type` on the qualified relationship. There is no `arch:relType` |
| a single native-id property | `skos:notation`, except BPMN which uses `bpmn:id` |
| a `sourceNotation` property | `arch:modelConformsToMetamodel`, pointing at an `arch:Metamodel` |
| one lifecycle property | `adms:status` at model level, about the *conversion*, plus notation-specific element lifecycle |
| short graph names like `g:semantic` | `{base}{notation}/{modelId}/graph/{semantic,views,provenance}` — and **no validation graph exists**, see F4 |

**How it is enforced:** no template names a vocabulary term at all. Templates name roles, and
`skills/linked-archi-profile/assets/profiles/linked-archi-default.yaml` binds each role to a
verified term. `tests/test_render.py::test_no_template_carries_its_own_prefixes` asserts it
across all 39 templates, so a term cannot creep back into one.

### F2. Graph scoping has to be a profile decision, not a constant

An unscoped pattern returns nothing against converter TriG. A hardcoded `GRAPH` clause
returns nothing against the converters' own flattened Turtle. Both are real deployments, so
neither can be the built-in choice.

Templates wrap patterns in `{{GRAPH_OPEN:role}}` / `{{GRAPH_CLOSE}}` and the **profile
decides what that becomes** — a `GRAPH` clause with a suffix filter, a `VALUES` restriction,
or a plain group. One template therefore serves TriG, a curated store with literal graph
IRIs, and flattened Turtle.

**Regression test:** `tests/test_templates.py::test_the_graph_scoping_defect_is_measurable`
runs identical patterns scoped and unscoped and asserts 0 versus non-zero.

### F3. The qualified form is the only relationship form by default

Every relationship is an `arch:QualifiedRelationship` resource with `arch:source` and
`arch:target`, reached from its source element by a qualified predicate. The direct
`{src} {pred} {tgt}` shortcut is opt-in: `--emit-direct-rel-triples` is **off** in every
converter, and it also governs the `rdf:reifies` bridge. So on a default dataset, traversal
through the direct predicate returns nothing.

**How it is enforced:** `core/neighbours-qualified` and `core/dependents-qualified` are the
default traversal route. `core/dependents-direct` exists, requires
`capabilities.direct_rel_triples`, and is **refused** under the default profile with an
explanation and a named alternative.

**Regression test:** `test_direct_triples_are_absent_from_default_output` asserts absence
with an `ASK` against the base fixture, so the default cannot be quietly inverted.

### F4. There is no validation graph

The converters' `validate` subcommand writes a SHACL report to stdout or to `-r file`. It is
a document, not a graph, so nothing loads it into the dataset unless a pipeline chooses to.

**How it is enforced:** `graphs.validation: null` in the default profile, so
`core/validation-summary` is refused with that reason rather than returning an empty table.
The template still exists for stores that *do* load their report; the `curated-store` profile
at `skills/linked-archi-profile/assets/profiles/examples/curated-store.yaml` enables it.

---

## 3. The load-bearing idea: the graph profile

Vocabulary knowledge wants to spread itself across prose, template text (`PREFIX` lines),
fixtures and runner code. Four places to change means four places to drift, and drift here is
silent: the queries still run.

A profile collapses them into one declarative artifact that everything resolves
through. It answers three questions a template cannot answer for itself:

- **What is this called here?** `roles` maps a semantic role onto this dataset's term.
- **Where does it live?** `graphs` describes the named-graph layout.
- **Is it actually present?** `capabilities` records what the dataset *contains*, as
  against what the vocabulary permits.

### Capability gating is the behaviour this package exists to add

The third question earns the whole abstraction. Each template declares its
`requires`; a template whose dependency is absent is **refused with a reason and an
alternative** rather than run:

```
Template 'core/dependents-direct' cannot run against profile 'linked-archi-default':
  - capability 'direct_rel_triples' is False but this template needs True
Try instead: core/dependents-qualified, core/neighbours-qualified
This is a refusal, not an empty result: running it anyway would return no rows and
read as 'nothing exists'.
```

Without gating, a query runs, returns nothing, and is wrong — and zero rows read as a
finding. Each of F1 to F4 is a way that happens. Gating converts the failure mode into an
explicit refusal.

Three states, deliberately: `true`, `false`, and `partial`. `partial` means present
for some models and absent for others — true of the views graph, which exists only
where a source had diagrams — and a template requiring it runs **with a caveat**,
because a thin result may reflect coverage rather than absence.

### A profile is verifiable, not just declarative

`la-kg profile verify --profile P --data F` probes the dataset for every claim and
reports drift. This is what stops a profile becoming the stale prose it replaced.

| Finding | Meaning |
|---|---|
| **error** | Claimed true, absent. A template will run and return nothing while looking correct. Exit code 1. |
| **warning** | Claimed false but present — templates are being refused unnecessarily. Or a bound role is unused. |
| **ok** | Confirmed against the data. |

The asymmetry is intentional: over-caution costs you a template, over-confidence
costs you a wrong answer.

### A profile is derivable

Adapting to a custom ontology should not mean editing templates. It means producing
a profile, and a profile can largely be derived from artifacts that already exist:

```bash
la-kg profile derive acme --type-mapping config/type-mapping-acme.yml -o profiles/acme.yaml
la-kg profile derive cp   --metamodel cloudplatform-metamodel.ttl --notation cp -o profiles/cp.yaml
```

Deriving from the converter's `--type-mapping` closes a loop worth closing: the file
that told the converter to emit `cp:Microservice` is the same information a query
needs to find it again, so the graph and the queries cannot disagree.

Output is a **draft**, and two things are never guessed:

- **Optional roles** (ownership, lifecycle, identity) — a mapping says what *may* be
  emitted, not what was.
- **`direct_rel_triples`** — a mapping declaring direct predicates does not mean the
  converter ran with the flag that emits them.

---

## 4. Repository layout

```
apm.yml  README.md  PROPOSAL.md  USAGE.md  ADAPTING.md  Makefile
bin/la-kg                         repository convenience dispatcher only
skills/linked-archi-source/       linked_archi_source, la-source, source contract
skills/linked-archi-profile/      linked_archi_profile, la-profile, assets/profiles
skills/linked-archi-connect/      linked_archi_connect, la-connect, raw adapters
skills/linked-archi-query/        linked_archi_query, la-query, assets/templates
skills/linked-archi-analyse/      orchestration instructions; no Python runtime
skills/linked-archi-validate/     SHACL/query orchestration; no Python runtime
fixtures/                         extracted real converter output
tests/                            behavior and ownership tests
```

Ownership is physical, not conventional. There is no authoritative root library and
no compatibility copy. A skill imports only its own package. Profile resolution and
raw execution cross skill boundaries through `schema_version=1` JSON subprocess
contracts, so installed siblings cooperate without sharing Python code. SPARQL safety
remains query-owned: connect delegates every raw execution to `la-query lint` before a
local store or endpoint sees the text.

---

## 5. The six skills

Method is separated from mechanism on purpose. Bundling both into one skill would make a user
who wants a catalogued query pay for the whole investigation protocol, and would put
execution inside the skill that decides what to investigate.

| Skill | Owns |
|---|---|
| `linked-archi-source` | Remote source resolution, credentials, policy, RDF verification, immutable cache and acquisition manifest. |
| `linked-archi-profile` | Discover, derive, verify, adapt. Custom ontology and taxonomy onboarding. |
| `linked-archi-connect` | Attach a dataset or endpoint; report what actually loaded through profile-agnostic raw transport. |
| `linked-archi-query` | Render, validate, execute, present. The template catalogue and the graph's traps. |
| `linked-archi-analyse` | Investigation method: framing, routing, budgets, evidence classes, output contract. |
| `linked-archi-validate` | SHACL through the converters; coverage-with-verdict; the quality questions SHACL does not answer. |

`linked-archi-analyse` delegates all execution to `linked-archi-query` and says so
in its `compatibility` field: on its own it can plan but not execute.

---

## 6. Standing contracts

The guarantees the package holds itself to, each enforced by tests rather than convention.

| Contract | What it means |
|---|---|
| Read-only enforcement | Every query is checked for update forms before execution, in the query owner and nowhere else. The checker's word-boundary patterns are IRI-aware — see A9 for why that is not obvious. |
| Typed parameters | User input is validated and quoted per declared type. Bare IRIs are accepted; `iri_path` exists for path-shaped values. No raw string substitution anywhere. |
| Reproducibility envelope | Every result carries the query, the dataset identity, the profile identity and version, and the caveats that applied. |
| Evidence model, output contract, analysis patterns, safety | An investigation states what class of evidence each claim rests on, and what the graph cannot tell you. |
| A test case per template, or the build fails | A catalogued template with no fixture case fails the suite, and a gated template must also declare `requires:` and name an alternative. |
| Frontmatter validation | All six skills are checked in CI for a valid Agent Skills manifest. |
| Show the query; attach provenance; empty is a finding; the graph is not the enterprise | The answering rules. An empty result is reported as a measurement with its scope, never as an absence of fact. |

Adding `profile_id` to the envelope is small and load-bearing: a result produced
under one vocabulary binding and read under another looks reproducible and is not.

---

## 7. Fixtures: extracted, not authored

`fixtures/base.trig` contains only real quads from real conversions; only the
*selection* is ours. That matters more than it sounds. A hand-written sample is written to
match the queries, so a template suite passing against one proves the author was
self-consistent and nothing about the graph — which is exactly how a wrong vocabulary
survives a green build.

Four fixtures: `base.trig` (1282 quads, 17 graphs, default converter flags),
`augmented.trig` (1425 quads, 19 graphs, plus what converters never emit),
`flat.ttl` (1282 triples, no graph identity — what Turtle output collapses to, and
the shape in which a scoped query silently returns nothing), and
`converter-1.3.trig` (284 quads, 4 graphs, real output committed verbatim).

The last one is a second graph *layout*, not a newer version of the first: model
resources in their own `graph/model`, membership as a direct `arch:partOfModel` edge,
and a semantic graph partitioned per input as `graph/semantic/{repo}/{path}`. Both
layouts are stamped with the same converter version, which is why fixtures here are
identified by shape and `tests/test_fixtures.py` asserts the shape of each one.
Extraction proves a fixture was true of *some* build; only an assertion pins which.

Every selection rule in `fixtures/build_fixtures.py` exists because a template
returned zero rows without it. All 39 templates return rows against
`augmented.trig`: a template returning nothing is one the suite cannot distinguish
from a broken one. Details in [fixtures/PROVENANCE.md](fixtures/PROVENANCE.md).

One addition bends this rule and is worth naming here rather than only in the
appendix. The RDF 1.2 bridge (`rdf:reifies`) is specified by the core ontology and
emitted by every converter **only under `--emit-direct-rel-triples`**, which is off by
default — so its presence in a default-profile export is authored, not harvested. An
earlier revision of this section claimed no converter emitted it at all; that was
wrong. ArchiMate and LeanIX have emitted it from the start, and BPMN, PlantUML,
Structurizr and Backstage emit it as of the converter change that removed the
unpublished `arch:relPredicate`. The flag, not the converter, is what decides whether
a given `.trig` carries the bridge.

What keeps the addition honest is that the **mapping is extracted**: the
class-to-predicate pairs come from `arch:unqualifiedForm` in the ontologies
themselves, harvested into `fixtures/unqualified-forms.json`. `arch:unqualifiedForm`
is schema-level by declaration — core says to use it on schema definitions only, never
on instance data — so harvesting it from the ontology rather than expecting it in
converter output is correct, not a workaround. That distinction matters because the
mapping is irregular — `am:Serving` → `am:serves`, `am:Flow` → `am:flowsTo` — so the
obvious lowercase-first rule would have invented predicates that do not exist. Classes
whose ontology declares no unqualified form get no bridge, which is why
`core/reifies-audit` reports six genuine `missing-term` rows rather than a planted
defect.

---

## 8. Progress

### Work items

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Harvest ground truth from real converter output | Done | Appendix A |
| 2 | Repo skeleton, licence, APM manifest, Makefile | Done | `make help` |
| 3 | Profile artifact and loader | Done | 33 tests |
| 4 | Query-owned catalog, render, validate, envelope | Done | behavior tests |
| 5 | Connect-owned raw local and endpoint adapters | Done | executed against real output |
| 6 | Distinct CLIs, profile derivation, JSON contracts | Done | subprocess contract tests |
| 7 | Template library and catalogue (28) | Done | 15 tests, all execute |
| 8 | Fixtures in three modes | Done | `fixtures/PROVENANCE.md` |
| 9 | Six SKILL.md files and 9 references | Done | `make skills` |
| 10 | Test suite and skill validator | Done | test suite passes |
| 11 | This document | Done | — |
| 12 | README, USAGE, ADAPTING | Done | 3 files, all links resolve |
| 13 | End-to-end verification | Done | §9 |
| 14 | Strict per-skill ownership and isolated installs | Done | 15 packaging tests |
| 15 | RDF 1.2 `rdf:reifies` as a gated capability | Done | 14 tests, 3 templates |
| 16 | Verified HTTPS, Git and optional GitLab MCP source acquisition | Done | source smoke checks and strict contracts |
| 17 | Load cost made visible (`load_ms`), selectable store modes, and `query batch` | Done | 45 tests, `references/store-modes.md` |

Items 14–16 came from review after item 13 had passed. They are worth recording as
evidence about the process rather than only the product: item 14 was a real defect
that a green build had hidden, item 15 was a stated non-goal that turned out to be
feasible once measured, and item 16 added a new trust boundary rather than teaching
connect to download arbitrary bytes.

Item 17 came from use rather than review, and its shape was decided by measurement that
partly said no — see D19. The reportable part is that the cost it addresses had been
invisible: `elapsed_ms` timed only execution, so a query on a large aggregate was reported
in single-digit milliseconds while the load it depended on took seconds. Nothing was wrong
with the number; it was answering a narrower question than anyone reading it assumed.

### Corrections

Each fact in §2 is pinned by a test that fails if it stops being true.

| Fact | Regression test |
|---|---|
| F1 the vocabulary is published, guesses are wrong | `test_no_template_carries_its_own_prefixes` |
| F2 graph scoping is a profile decision | `test_the_graph_scoping_defect_is_measurable` |
| F3 the qualified form is the only default form | `test_direct_triples_are_absent_from_default_output` |
| F4 there is no validation graph | `test_default_profile_refuses_exactly_the_unsupported_templates` |

### Defects found and fixed during construction

Found by building and testing, not by review. Each is a case where the obvious
implementation silently returned nothing.

| Defect | Where | Fix |
|---|---|---|
| Graph-variable collision: two scopes both bound `?g`, requiring one graph IRI to end in two suffixes at once | `render.py` | Role-derived variables `?g_semantic`, `?g_provenance`; `{{GRAPH_VAR:role}}` directive |
| Same-role collision: two lookups on `semantic` forced both into one graph | `core/identity-audit` | Numbered alias `semantic2` opens an independent scope |
| Seven chained `OPTIONAL`s in a scope with no required triple returned every column unbound | `core/provenance` | One scope per lookup, each with a required triple |
| `dct:isPartOf` traversal to the model works for BPMN, breaks for C4 | `core/provenance` | Find the model by co-location in the same semantic graph |
| `dct:source` on the model (BPMN/C4/Backstage) versus on the `prov:Entity` (ArchiMate) | `core/provenance` | `UNION` over both, `SELECT DISTINCT` |
| Placeholders inside comment headers were being substituted | `render.py` | Comment-aware substitution, shared with the read-only checker |
| `extends` resolved only beside the profile file, so a project-local profile could not inherit | `profile.py` | Sibling first, then the profile skill's bundled `assets/profiles/` |
| Wildcard property path was unbounded traversal in disguise | `core/dependents-direct` | `iri_path` parameter type, capped alternation |
| A capability-gated template offered no alternative | `core/provenance` catalogue entry | Found by `test_gated_templates_offer_an_alternative` |
| **D-11.** Shared root runtime broke when a skill was copied alone | packaging | Move each module and asset to its sole owning skill; test isolated copies |
| **D-12.** Generated common payload duplicated safety/runtime code across every skill | ownership | Distinct packages and executables; JSON subprocess delegation, no cross-skill imports |
| A `FILTER NOT EXISTS` alone in a UNION branch left `?rel` unbound, because a FILTER is scoped to its own group's pattern — 4 rows reported where 6 were correct | `core/reifies-audit` | Anchor the branch with a required triple pattern |
| Hoisting the shared `arch:source`/`arch:target` patterns above a UNION made both disagreement branches match nothing and report a clean bridge | `core/reifies-audit` | Every UNION branch is now self-contained |

The last two are the same root cause as the `core/provenance` defect above: **a group
with no required triple pattern binds nothing, and a FILTER over unbound variables is
simply false.** Three instances now, each found by a test rather than by reading, and
each one had produced a plausible-looking empty or short result. Swept all 28
templates for the pattern afterwards; no others.

D-11 and D-12 established the current packaging rule: tests must execute owner skills
from isolated copies, not only from the repository, and no generated/common Python
payload may exist. `tests/test_packaging.py` hashes Python files across skills, checks
exact asset ownership, verifies root compatibility paths are absent, exercises each
owner's independent commands, checks missing-companion diagnostics, and runs profile
verification plus query execution from copied sibling skills.

### Known limitations

- **`apm install` has not been exercised end to end.** The manifest is validated against the
  normative [OpenAPM v0.1 schema](https://microsoft.github.io/apm/specs/schemas/manifest-v0.1.schema.json)
  and the package uses the documented `skills/<name>/SKILL.md` layout, which APM installs by
  promoting each nested skill. Packaging behaviour is covered by isolated-copy tests and the
  committed tree is itself the artifact — but no run of `apm install` against this package has
  been observed, because APM is not installed in the environment it was built in. **The first
  thing to do on release** is `apm install` it into a throwaway project for each target that
  matters and confirm the skills land.
- **`keywords:` is carried but not interpreted.** The v0.1 schema sets
  `additionalProperties: true`, so the key is legal and preserved verbatim; it is not one of
  the schema's declared properties, so nothing is promised about how a registry renders it.
  The sanctioned route for genuinely custom metadata is an `x-` prefixed key.
- **The package layout is not symmetric between `apm pack` and `apm install`.** Root
  `skills/<name>/` is a supported install source, but the authoring guide recommends
  `.apm/skills/<name>/` for marketplace publishers because that is the only layout both
  commands source from identically. Direct installs and Git-ref installs work as-is; revisit
  the layout before publishing to a marketplace or a REST registry.
- **The local adapter has no query timeout.** pyoxigraph does not offer one; row
  limits are the only bound. Relevant before pointing it at a very large store.
- **Fixtures are not byte-stable.** Blank nodes regenerate per conversion. Assert on
  shape and counts.
- **`notation/archimate/layer-crossing` infers layer from class names.** The
  ArchiMate ontology expresses layer through the class hierarchy, and this query
  deliberately does not require reasoning. A specialisation named outside the
  convention shows an unbound layer rather than being dropped.
- **`linked-archi-mcp` is not integrated.** The server sitting alongside this package is
  built on a vocabulary that no longer matches: `store.ts` declares
  `https://meta.linked.archi/archimate#` and its `get-relationships` tool uses the withdrawn
  `arch:relSource`. It needs the same profile treatment before it could be wired in as an
  optional adapter. See D17 for why that is not planned.
- **`rdf:reifies` needs a SPARQL 1.2 engine, and the converters emit it only under a
  flag.** Every converter emits the bridge, but inside the branch that writes the direct
  triple, so `--emit-direct-rel-triples` produces both or neither. Three templates use it
  and are refused unless the profile sets `capabilities.rdf_reifies`. That flag carries two
  claims at once — the dataset has the bridge, *and* the engine parses `<<( s p o )>>` —
  because on a SPARQL 1.1 endpoint the syntax is a parse error rather than an empty result.
  pyoxigraph 0.5.9 supports it; many endpoints do not. The same gate governs whether
  `verify` may look inside a triple term to settle `direct_rel_triples`.
- **A triple term is not an asserted triple, so the bridge cannot replace direct
  triples.** `?s am:serves ?o` matches nothing in a reified-only dataset, and property
  paths do not traverse triple terms. `core/neighbours-reified` is therefore one hop
  only, and `core/dependents-direct` still requires `direct_rel_triples`. Measured,
  and asserted in `tests/test_reifies.py`.
- **`arch:unqualifiedForm` is read from a committed extract, not live.**
  `fixtures/unqualified-forms.json` holds 75 pairs harvested from the ontologies;
  refresh it with `build_fixtures.py --refresh-forms` when the ontologies change.
  Nothing detects staleness automatically.

### Platform limits

Distinct from the limitations above: these cannot be fixed inside the package at all.
Recorded so effort is not spent trying, and carried here from the agent-usability plan when
that plan was retired.

- **Activation does not expose the skill's absolute install path.** Kiro loads skill content
  by name; the body cannot know where it lives. Everything available is mitigation — the
  `python3` bootstrap snippet in each `SKILL.md`, each owner's `doctor`, steering, or a
  consuming project's own agent with resolved paths.
- **There is no skills registry** mapping name to real path. That is a Kiro feature request,
  not a package change.
- **There is no skill-to-skill invocation API and no dependency resolver.** Cross-skill work
  stays instruction plus a published subprocess contract, which is why each owner has one.
- **A stale skill generation elsewhere on disk can shadow the right one.** Not preventable.
  Each `doctor` echoes its version so it is at least detectable.

### Open work

Two items, carried here from the converter-1.3 revalidation plan when that plan was retired.
Everything else it tracked shipped; these did not, and this is now the only record of them.
Neither is damage control — the "unsafe pass" that made that plan urgent is gone.

**O1. Ontology and metamodel acquisition.** *A feature, and it should be scoped as its own
proposal rather than carried as a bullet here.*

State the position honestly: none of this exists. `derive --metamodel` parses **one local
file's direct declarations**. It does not follow `owl:imports`, does not load a referenced
ontology corpus, and there is no `metamodel/*` template family.

Do the boundary work before the fetching. The source owner already has the hard parts —
HTTPS and Git verification, host allow-lists, size and time limits, digests, pinned manifests,
offline reuse, fail-closed exits. Ontology acquisition should be **a source kind, not a new
mechanism**, and `owl:imports` traversal must be bounded and pinned or it is an unbounded
fetch of whatever a document happens to name.

Only then the `metamodel/*` templates — modules, taxonomy tree, viewpoints, cross-mappings,
asserted-vs-derived, deliverable template — each with a catalogue entry, gating and a fixture
floor like every other template. And a genuinely **non-Linked.Archi fixture**, without which
"adapts to a custom ontology" is an untested claim. This is the largest item here and the one
most likely to be descoped; say so rather than half-building it.

Touches `skills/linked-archi-source/`, `skills/linked-archi-profile/`, and possibly
`assets/templates/metamodel/`.

**O2. Notation presence as a runtime gate.** `notations` is metadata. A question about BPMN
against a dataset holding no BPMN model is answerable only by orientation, and nothing gates
it. Treat notation presence like a capability: probed by `verify`, reported by `recommend`,
and available to a template's `requires`. `core/inventory-summary` already measures it; this
makes the measurement enforceable.

---

## 9. Verification

`make check` runs what CI runs: the skill validator, then the suite.

The counts below assume the optional dependencies CI installs — `pyoxigraph` for local
execution and `pyshacl` for validation. Install them before reading any run of this suite,
because an interpreter without them does not simply run less: it reports **166 skips and 8
hard failures**, and the skipped paths are exactly the ones that touch a real store. Most
tests degrade to a skip on purpose, so a contributor missing one dependency can still trust
the rest, but the `doctor` tests assert a clean exit and the fixture-loading `setUpClass`
hooks cannot skip, so those fail outright. Neither the skips nor those 8 failures indicate
anything about the code under test.

| Check | Result |
|---|---|
| `make skills` | 6 skills valid, 0 problems |
| `make test` | 644 tests, 0 failures, 0 skipped |
| `make verify` (default profile / `base.trig`) | 0 errors |
| `make verify-curated` (curated profile / `augmented.trig`) | 0 errors |
| `query batch` against separate `query run` commands | identical `rows`, `query_id`, `truncated` and `row_count`; load paid once |
| Store modes `memory`, `cached`, `readonly`, `refresh` | same quad and named-graph counts from each; a changed input rebuilds rather than serving a stale store |
| `la-query catalog list --profile linked-archi-default` | 39 templates, 32 available, 7 refused with reasons |
| `la-query catalog list --profile curated-store` | 35 available, 0 refused |
| All 39 templates against `augmented.trig` | every one returns rows |
| Exit-code contracts | 9 of 9 |
| Owner skills copied alone to temp directories | independent commands run with `PYTHONPATH` scrubbed; combined siblings execute |

---

## 10. Decision log

Decisions worth not relitigating without new information.

**D1. Roles, not terms, in templates.** The single change that makes both the
vocabulary correction and custom-ontology support possible. Cost: one level of
indirection when reading a template.

**D2. Capability gating over best-effort execution.** A refusal is more useful than
an empty result. Cost: a `requires` block per template, and the risk of an
over-cautious profile refusing something available — mitigated by `verify`
reporting "claimed false but present" as a warning.

**D3. `partial` as a third capability state.** Reality is not binary: the views
graph exists for some models and not others. Without it, `views_graph` would have to
be `true` (and mislead) or `false` (and refuse working templates).

**D4. `use_default_graph_as_union` left off in the local adapter.** Turning it on
would make unscoped queries work and thereby **mask F2**. The profile's
`named_graphs` setting has to mean something.

**D5. Graph variables derived from the role.** A single `?g` is simpler and
unsatisfiable across two scopes. The numbered alias handles two independent scopes on
one role.

**D6. Fixtures extracted from real output, not authored.** An authored fixture is written to
satisfy the queries under test, so it cannot detect a vocabulary that does not exist. See §7.

**D7. Method separated from mechanism.** `analyse` and `query` install
independently; `query` alone is useful, `analyse` alone is not, and its
`compatibility` says so.

**D8. No mandatory MCP dependency.** The package works
against local files, verified HTTPS/Git artifacts, or an endpoint. GitLab MCP is an
optional agent-mediated source: a consuming deployment supplies its trusted server,
credentials, and an independently trusted SHA-256. The source runtime authenticates
the pending constraints, verifies the staged bytes against that digest, and records
the commit only as MCP-reported because it cannot prove commit-to-blob membership.

**D9. Derivation produces a draft, never a verified profile.** Deriving what can be
derived and *reporting* the rest is what keeps the output honest. Guessing an
optional role is how a confident empty result gets built.

**D10. Runtime and assets have strict per-Agent-Skill ownership.** Source owns remote
identity, acquisition policy, RDF verification, cache and manifests; profile owns
profile loading/derivation and committed profile assets; connect owns local discovery
and raw transport adapters; query owns catalog/render/read-only validation/envelopes
and committed template assets; validate owns in-process SHACL execution, coverage
measurement and report reading; analyse owns pattern routing, planning and bundling, and
owns no execution path at all. See D15 and D16.

There is no root compatibility runtime and no generated common payload. Each owner has
a distinct executable and package name. Operations that cross ownership boundaries use
explicit subprocess delegation with `schema_version=1` JSON on stdin/stdout. Source
returns connect target v1 and accepts no query text. Profile is the only component
that loads inheritance and expands vocabulary terms; query consumes its normalized
`ResolvedProfile` snapshot. Connect submits all query text to query-owned lint before
backend access and returns backend-neutral raw results; query owns the auditable
envelope and presentation.

This matches Agent Skill installation semantics directly: every committed skill folder
is the installable artifact, so `git clone && cp -r skills/*` works without a build
step. Missing companions are explicit and name the required skill rather than borrowing
its runtime.

**D12. `rdf:reifies` is a role, not a new render directive.** A directive was
considered and rejected. `rdf:reifies` is a vocabulary *term*, which is precisely what
the role mechanism exists to bind (D1), and the `<<( s p o )>>` pattern is SPARQL 1.2
*grammar* — no more a vocabulary choice than `OPTIONAL` or `UNION`. A directive whose
only job is to emit fixed syntax would add indirection without adding adaptability.

The one real hazard is that an author reaches for the reifier shorthand
`<< s p o ~ r >>`, which *asserts* the triple and therefore matches nothing against a
reified-only dataset — silently, which is this package's signature failure mode. That
is guarded by `test_no_template_uses_the_asserting_reifier_shorthand` rather than by an
abstraction. A test is the cheaper guard when the risk is one specific mistake.

**D13. Remote acquisition is a source owner, not a connect adapter.** Downloading a
static RDF document or resolving a Git ref owns credentials, redirects, network
policy, mutable identities, cache and checksums. Connect owns local RDF loading and
SPARQL endpoint transport. Source therefore materializes verified local files and
returns the existing connect target instead of teaching connect to fetch arbitrary
bytes. This also leaves query-owned safety as the only execution choke point.

**D15. Validate owns SHACL in-process, and never executes SPARQL.** Validation used to
be instructions that drove a converter's `validate` subcommand. That made the skill
unusable without a JVM and a converter install, and it promised metrics the converter did
not produce — evaluated and skipped constraint counts, which no part of that toolchain
emits. Validate is now a runtime owner: `la-validate` runs SHACL through `pyshacl`, so a
consumer needs one Python dependency and no converter, Java runtime or network access.

Three boundaries hold it in place. It measures **target-class coverage** and vacuity,
which are computable, and reports the constraint counts as explicit `null` rather than
inventing them. It **never executes SPARQL** — query keeps read-only enforcement, so there
is still exactly one place where that policy has to be correct, and a packaging test fails
if validate ever references a SPARQL or store API. And it **never bundles shapes**: the
ontologies and shape documents are published separately under their own licence, so
callers pass local files or acquire them once through the source owner.

Two capabilities follow from owning the runtime rather than shelling out. A **report
produced elsewhere** — a converter's output, a CI artifact, a published
`graph-shacl-report.ttl` — can be summarised directly, with coverage reported as
unavailable because a report records what was found and never what was checked. And a run
that **selected no focus node** exits `2` instead of `0`: a namespace mismatch otherwise
reports `sh:conforms true` over zero checked constraints, which every CI step and every
reader records as a pass.

Rejected: keeping it instructions-only (needs a converter, and cannot report coverage for
an existing report); bundling shapes (licence, and staleness); and letting validate query
the graph (a second read-only enforcement point). Model-quality questions no shape covers
stay with analyse's model-quality pattern, and the two descriptions were separated so they
stop competing for the same request.

**D16. Analyse owns planning and bundling, and never executes.** Analyse used to be
instructions only: it described a method and left every step to be assembled by hand. That
made the good parts optional. Deciding which templates to run, in what order, and against
which profile happened afresh every session, and the reproducibility envelope — "include all
the sources and queries" — depended on the agent remembering to keep one.

`la-analyse` now owns two operations and neither of them touches a dataset. **`plan`** routes
a question to an analysis pattern from `assets/patterns.json`, then emits the numbered
`la-query` commands in doctrine order with their purposes, parameters, stop conditions and —
when query is installed — each template's availability under the chosen profile, so a refused
template is replaced by its documented alternative *at planning time*. **`bundle`** consumes
the envelopes those commands wrote and assembles one artifact, refusing envelopes from two
datasets or two profiles, carrying truncation and caveats forward, and requiring every claim
except an unknown to cite a step.

Three boundaries hold it in place. It **never executes**: no store, no transport, no SPARQL,
and a packaging test greps the runtime for all three plus `validate_readonly`. It **never
imports another owner's package**: template metadata comes from running query's documented
`catalog dump`, and the profile-verification marker is read through the same
`$LINKED_ARCHI_STATE_DIR` path convention profile writes and query reads — a convention
shared by three owners and imported by none. And it **degrades rather than failing**: without
query, a plan is still ordered and still names templates, and says it is unannotated.

Rejected, **option A**: leave analyse as instructions. It keeps the package simpler and was
the status quo, but it leaves the two things worth automating — routing with real availability,
and assembling the evidence — as work nobody does under time pressure. Rejected, **option C**:
let analyse execute its own plan. One command would be nicer, and it would put read-only
enforcement, dataset identity and result provenance in a second place. D7 (method separated
from mechanism) and D10 (strict per-skill ownership) both survive option B and neither
survives option C.

**D17. No MCP wrapper in this package, and an existing SPARQL-passthrough server is the
reason.** Exposing the owners as MCP tools is the strongest available answer to bootstrap: an
agent would never resolve a Python path at all. It is still declined here, and the
`linked-archi-mcp` server sitting alongside is the evidence rather than the counterexample.

That server exposes a `query-graph` tool taking arbitrary SPARQL with a prefix block
auto-injected. Two things follow. It **skips every layer this package is**: no profile
resolves the vocabulary, no capability gating refuses a question the dataset cannot answer, no
read-only lint, no result envelope, no dataset identity. And its prefix table has **decayed
into silence** — measured against `linked-archi-default`, not one of its Linked.Archi
namespaces still matches: `c4:` points at `.../c4#` where the real namespace is
`.../c4/onto#`, `amate:` and `lix:` are similarly stale, and even `schema:` differs by URI
scheme. A query written against it parses, runs, and returns zero rows. Nothing tells the
caller the prefixes were wrong, which is precisely the failure mode this package was built to
remove.

So the tradeoff is not "MCP versus CLI ergonomics". It is that an MCP surface is **another
interface to version against the machine contracts** (G5), and the tempting shape for it — one
tool that takes a query string — is the shape that throws away the guarantees. D8 (no mandatory
MCP dependency) already holds; this extends it to say the package does not ship an optional one
either.

What would have to be true to build one: it wraps the **`_machine` contracts**, one tool per
owner operation, carrying the same `schema_version` and the same refusals; it exposes **no
SPARQL-string tool**; and it is versioned in lockstep with those contracts. That is a real
piece of work with a real maintenance cost, and the CLIs remain the reference interface either
way. A consuming deployment that wants it has the contracts documented to build against.

This also settles the open question in §11: **`linked-archi-mcp` should be retired, not
corrected.** Correcting its prefix table would fix today's silence and leave the design — an
unguarded SPARQL passthrough — intact, and its whole surface is replaced by the machine
contracts plus the query owner's catalogue.

**D18. A capability claim follows the runtime; it never precedes it.** A profile or skill
must not declare a capability before the code that provides it exists. Stated as a decision
because the alternative was tried: a claim written ahead of its runtime is indistinguishable
from a claim whose runtime regressed, and gating then refuses templates that would have
worked, or admits templates that return nothing. Every capability in
`assets/profiles/linked-archi-default.yaml` is probed by `verify` for this reason, and §8's
work items record the one case where the order was reversed.

**D14. Skills are sufficient; no package custom agent.** A custom agent is useful
when a deployment needs its own model, persona, context or tool/MCP permission
boundary. These six units are reusable capabilities and instructions, so a package
agent would duplicate orchestration and reduce cross-client portability. A consuming
project may define a restricted source-broker or architecture-analyst agent that
includes the skills and its approved MCP; that trust decision does not belong here.
APM can carry agent primitives, but this package intentionally includes only skills.

**D19. Store reuse is a mode the caller selects; batching is the fix that works.** Recorded
at length because the obvious optimisation is genuinely appealing, was implemented, and was
then measured into a smaller role than it looked like it deserved. Without the numbers it
will be proposed again as free speed.

Every owner CLI is its own process, so a session asking ten questions of one dataset parses
it ten times. pyoxigraph's RocksDB-backed `Store(path)` removes that: parse once, reopen
after. It works, and for a selective lookup it is close to two orders of magnitude faster.
It is **not** the default, because a disk-backed store does not query at in-memory speed.
Measured on one large multi-notation TriG aggregate:

| An aggregating template | Load | Query | Total wall |
|---|---|---|---|
| parse into memory | full parse | baseline | baseline |
| reuse a cached store | ~1/100th | roughly 3x | **~1.6x worse** |

The load saving is real and the query penalty is larger. Whether caching wins depends on how
much work the query does, which nothing can know before running it — so it is a mode a caller
selects knowingly (`memory`, `cached`, `readonly`, `refresh`), never a default applied on
their behalf. Modes refuse rather than silently falling back, so a benchmark cannot measure
the slow path and report it as the fast one.

Three routes to "in-memory speed without the parse" were also measured, and all three lose to
simply parsing the TriG again: reopening a cached store read-only and copying into memory
~2.5x, dumping to N-Quads and reparsing ~1.25x. The reader moves hundreds of thousands of
quads per second; no serialisation here beats it.

That redirects the problem rather than solving it. **The per-process parse is irreducible, so
the way to stop paying it repeatedly is to stop starting a process per query** — `la-query
query batch`, one invocation, one parse, several queries, measured at roughly 2.8x faster than
the same queries as separate commands. A resident process would go further and is not
implemented.

Two supporting decisions follow from this. `load_ms` is reported beside `elapsed_ms` rather
than folded into it, because they are not comparable work and a fast query on a slow load is
not a fast command. And only the first result of a batch carries `load_ms`: the load happened
once, so stamping every result would make one parse read as several and report more loading
than the wall clock contained.

Cache invalidation is the only part that could produce a *wrong* answer rather than a slow
one, so the key is deliberately conservative — ordered file list with each file's size and
mtime, the `lenient` flag, the pyoxigraph version, and a revision of the load semantics.
Stat data rather than content hashes, because hashing a dataset to decide whether to skip
parsing it gives back most of the saving. The accepted cost is that two spellings of one
dataset get two stores, which is what the byte budget bounds.

**D20. A notation template is gated on its vocabulary's namespace IRI, not on its notation
label.** The catalogue carried a `notation` field from the beginning and never consulted it,
which made it documentation. That is a gap rather than a nicety: a notation template names
that notation's terms directly - there is no role indirection for `bpmn:SequenceFlow` or
`c4:hasContainer` - so against a dataset without the notation it runs and returns nothing,
and nothing distinguishes that from "this model has no sequence flows".

The gate keys on a new `notation_namespace`, the vocabulary IRI, because neither of the
obvious alternatives identifies a notation. The **slug** is not identity: ArchiMate's profile
slug is `model`, since the converter's `--path-model` defaults to that and is configurable,
while the catalogue directory is `archimate` - gating on the label would have refused a
supported template against every bundled profile. The **prefix** is not identity either, and
A12 already records why: the converters emit both `archvis:` and `arch-vis:` for one
namespace. The IRI is versioned by construction, which is a second benefit: a profile
describing an ArchiMate 4 dataset binds `am4`, so a template written against `am` (3.x) is
refused rather than quietly returning nothing - the versioning the audit flagged in
`notation/archimate/layer-crossing`.

Every template declaring `notation` must declare the namespace, enforced by a test, so a new
notation template cannot opt out of its own gate.

**D21. A capability is measured for coverage, not for presence, wherever coverage can differ.**
`TRISTATE` and the "partial warns rather than refuses" gate were already in place; what was
missing was verification that could ever *recommend* `partial`. The probe asked "does this
dataset have the bridge", answered yes, and told the operator to claim `true` - which
overstates every dataset where the bridge is notation-specific. That is the normal case, not
an edge case: each converter emits it only under its own flag, so an aggregate store is
routinely bridged in part.

Implemented for `rdf_reifies` as two static ASKs - one for presence, one for a qualified
relationship lacking a bridge - because the probe batch is planned against a stub and must
not branch on a probe result. Both together mean `partial`, and a measured `partial` outranks
a claim in either direction: `true` promises completeness the data lacks, `false` refuses
templates the data can partly answer. `examples/curated-store` now claims `partial`, which is
what its own comments always described.

The same two-ASK shape extends to `views_graph`, `view_geometry` and `element_lifecycle`,
which are all documented as partial and still probed existentially. Not done here, so their
`partial` claims are accepted rather than confirmed.

### Requests deliberately not adopted as stated

Carried here from the agent-usability plan when that plan was retired, because each of these
will be proposed again otherwise. "Not as stated" matters: most were reframed rather than
refused outright, and the reframing is the useful part.

| Request | Disposition |
|---|---|
| Hard-gate queries on a prior `connect` call in the same session | **Reframed** as the non-blocking unverified-profile caveat. The CLIs are stateless; a session gate needs cross-invocation state, is trivially bypassed, and breaks both the machine contracts and CI. |
| Set `direct_rel_triples: true` in the default profile | **Rejected.** That profile describes default converter output, and a field dataset differs. The route is a derived child profile — `verify --emit-fix` produces one in a command. |
| Make "claimed false but present" a blocking error | **Rejected as stated.** The error/warning asymmetry is deliberate: blocking would refuse templates that would work. `--emit-fix` makes it actionable instead. |
| The default profile wrongly binds `arch:partOfModel` | **Inaccurate**, and doubly so now. It binds `part_of: dct:isPartOf` for containment and `part_of_model: arch:inModel` for the one-hop membership edge; `arch:partOfModel` is the name core deprecated in favour of `arch:inModel`. The real gap was traversal depth, since settled by the `direct-predicate` membership mode. |
| A one-command `la-analyse investigate` orchestrator | **Partly adopted.** Analyse owns `plan` and `bundle`; query keeps execution and read-only enforcement (D16). A full orchestrator stays rejected — it would duplicate orchestration and move safety out of the query owner. |
| Ship a consumer-specific merged profile | **Out of scope.** `derive` and `verify --emit-fix` let a consumer produce and check their own. |
| One shared `linked_archi.where` module as a path resolver | **Rejected as stated.** A shared package would break strict per-skill ownership (D10). Same outcome reached through each owner's `doctor`. |

---

## 11. What adoption should confirm

Released, so this is no longer a decision to make — but two claims in here have only been
checked by their author, and a first external user is worth more than another test.

1. Point one real project at it: `la-kg connect`, then `la-kg profile verify`
   against that project's actual graph. Fix whatever drift appears — in the profile,
   not the templates. That the profile absorbs the difference is the whole design bet.
2. Derive a profile for one custom metamodel end to end and confirm no template
   needed editing. That is the adaptability claim, and it should be checked by
   someone other than its author.
3. Retire `linked-archi-mcp`. Decided in **D17**: its prefix table no longer matches the
   real vocabulary in a single Linked.Archi namespace, so queries through it silently return
   nothing — and correcting that would preserve the design problem, an unguarded SPARQL
   passthrough that skips the profile, the gating, the lint and the envelope. Its surface is
   replaced by the documented machine contracts and the query catalogue.

Do not skip step 1. Everything here is verified against fixtures extracted from the
converters' own examples, which is not the same as verified against an enterprise's
graph.

---

## Appendix A: verification evidence

Every vocabulary and behaviour claim in this package was checked against real
converter output rather than read from documentation. Sources:
`tools/converters/example-architecture-project/out/{bpmn,structurizr,backstage,leanix,plantuml}.trig`
and `tools/converters/linked-archi-converters/playground/out/archisurance.trig`
(9,214 quads, 18 named graphs across the six files). Those `out/` directories are
gitignored in the converter repos, which is why `fixtures/` exists.

**A1. The graph-scoping defect, measured.** Identical triple patterns against the
same dataset:

```
unscoped (no GRAPH clause):  0 rows
scoped via {{GRAPH_OPEN:semantic}}:  13 rows
```

`pyoxigraph` matches only the default graph when `use_default_graph_as_union` is off,
which is the default. Regression test:
`test_templates.py::test_the_graph_scoping_defect_is_measurable`.

**A2. Direct relationship triples are absent by default.** Zero direct
`source predicate target` triples in every default-flag output file.
`arch:QualifiedRelationship` count equals `arch:source` count in all six
(archisurance 178/178, backstage 8/8, bpmn 4/4, leanix 7/7, plantuml 6/6,
structurizr 1/1). Regression test:
`test_direct_triples_are_absent_from_default_output`.

**A3. Named graph layout.** `{base}{notation}/{modelId}/graph/{semantic,views,provenance}`.
ArchiMate's notation slug is `model`, not `archimate` — `--path-model` defaults to
`model`. Backstage and LeanIX output has **no views graph**. No `graph/validation`
exists in any file.

**A4. Relationship shape.** The qualified resource carries the core class *and* the
notation class as separate `rdf:type` values, with `arch:source`/`arch:target`
endpoints — and every converter points into it from the source element with a
**qualified predicate**, which is the only way in, since the endpoints point outward:

```turtle
<.../relationship/Flow_2>
    a arch:QualifiedRelationship, arch:ModelConcept, bpmn:SequenceFlow ;
    arch:source <.../element/Task_Validate> ;
    arch:target <.../element/Task_Payment> .

<.../element/Task_Validate>
    bpmnl:qualifiedSequenceFlow <.../relationship/Flow_2> .
```

The predicate comes from the notation's published qualified form where there is one, and
from `arch:hasQualifiedRelationship` where there is not — core names it as the fallback for
exactly that case.

Zero occurrences of `arch:relPredicate`, `arch:relSource`, `arch:relTarget`; core publishes
none of the three. `rdf:reifies` is also zero **in this harvest**, which was taken with
default flags: every converter emits the bridge, but only inside the branch that writes the
direct triple, under `--emit-direct-rel-triples`. That is why `capabilities.rdf_reifies`
defaults to false here and is true in `linked-archi-direct` — the same flag produces both,
so the two capabilities move together.

**A5. Native identifiers differ by notation.** `skos:notation` in ArchiMate,
Backstage, LeanIX, PlantUML and Structurizr; **`bpmn:id` in BPMN**, where
`skos:notation` count is 0. Hence the fallback chain.

**A6. Ownership, identity and lifecycle are absent or notation-specific.** Across
all six files: `arch:conceptOwner` 0, `owl:sameAs` 0, `skos:exactMatch` 0.
`adms:status` appears once per file, on the **model**, in the provenance graph —
describing the conversion, not the architecture. Element lifecycle exists only as
`bs:lifecycleState` (Backstage) and `lmm:factSheetStatus` (LeanIX).

**A7. Provenance shape differs between converters.** BPMN, Structurizr and Backstage
put `dct:source` on the model; **ArchiMate puts it only on the `prov:Entity`** the
model was derived from. Folder-to-model membership via `dct:isPartOf` is emitted by
BPMN but the chain stops at `folder/Elements` for C4. Both facts forced
`core/provenance` to find the model by co-location and read the source through a
`UNION`. Verified working for all five notations afterwards.

**A8. Two generation times are legitimate.** The LeanIX model carries
`prov:generatedAtTime` twice: `2026-08-15T09:12:00Z` (author-declared export) and
`2026-08-19T09:43:21Z` (conversion run). A staleness signal, not a duplicate.

**A9. Read-only checking cannot use plain word boundaries.** `\b` around an update keyword
matches inside variable names and prefixed names, because `?` and `:` are non-word
characters — so a naive checker rejects legitimate queries. These pass and must:
`?add`, `?delete`, `ex:copy`, `ex:load`, a literal containing `INSERT DATA`, a comment
containing `DROP`, an IRI containing `delete`, a triple-quoted literal containing `LOAD`.
All 16 genuinely unsafe forms are still refused.
`tests/test_validate.py`.

**A10. The chained-`OPTIONAL` failure.** A `GRAPH` group with an empty required
basic pattern plus seven chained `OPTIONAL`s returned **every column unbound** (6
rows, all provenance columns empty). One `OPTIONAL` worked. Hence the rule that every
scoped group gets a required triple.

**A11. View node typing.** `archvis:ArchNode` with `archvis:archElement` in current
Structurizr and PlantUML output; ArchiMate playground output predates it and carries
`arch-vis:Node` with geometry and no `archElement`. Both shapes exist in the wild, so
`view_node_class` is a chain and queries match on `archvis:view` rather than the node
class.

**A12. Prefixes are not stable.** The converters emit both `archvis:` and
`arch-vis:` for `https://meta.linked.archi/core-vis#` depending on which emitter ran.
Nothing keys on a prefix.

---

## Appendix B: profile and template audit

An end-to-end audit of the bundled profiles and all catalogued templates, cross-checked
against three authorities rather than against this package's own documentation: the
published ontologies and SHACL shapes in `linked-archi-meta`, the converter emitters in
`tools/converters/linked-archi-converters`, and a large multi-notation aggregate export
produced by those converters.

**That export was a private third-party dataset and is deliberately not part of this
repository** — no identifiers, hosts, IRIs, model names or digests from it appear here or
in the fixtures. Everything recorded below is either a property of a shipped asset, a
property of the converters, or a measurement reproducible against `fixtures/`. Where a
finding was only observable at scale it says so, because that is a limit on the evidence
rather than a detail to omit.

The audit's own framing: **findings that describe a customer's profile configuration are
that customer's, not this package's**, and were discarded. What follows is only what is
wrong, or unproven, in what this package ships.

### B1–B3: corrected, with regression tests

**B1. A metamodel IRI was a near-miss, and near-misses here are silent.**
`linked-archi-default` bound the LeanIX notation to `leanix/metamodel#LeanIX`. No
ontology declares that term and no converter writes it: the published metamodel declares
`:LeanIXv4`, and `Conformance.kt` emits `metamodel#LeanIXv4`. `notation_for_metamodel`
is an exact string comparison, so every LeanIX model went undetected — no error, no empty
result, nothing to notice. The profile's own comment calls metamodel conformance the
reliable way to detect a notation, which is what made the miss expensive.

The pre-existing test checked one notation by hand, which is how this survived. The
replacement asserts over **every** metamodel the committed fixtures declare, so adding a
notation without binding it now fails:
`test_profiles.py::test_every_metamodel_the_fixtures_assert_is_recognised`.

**B2. A projected variable nothing binds.** `core/resolve-element` selected `?g` while
the scope binds one variable per graph role — `?g_semantic` here. SPARQL projects an
unbound variable without complaint, so the template advertised "the graph they came from"
and returned that column empty on every row of every result. Now projected through
`{{GRAPH_VAR:semantic}}`, like every other graph-reporting template.
`test_templates.py::test_resolve_element_reports_the_graph_it_matched_in`.

**B3. `core/traceability` claimed both directions and followed one.** Its header stated
that direction is a modelling convention and that both are followed; the two-hop branch
matched `source->mid->target` only. Three of the four orientations were missing, and they
are not exotic shapes: `source->mid<-target` is two things written to the same store,
`source<-mid->target` is one component serving both. The result was a confident "no path"
for genuinely connected pairs, which is the one answer this template exists to give.

Measured on `fixtures/base.trig`, restoring the orientations adds 19 reachable FactSheet
pairs the forward-only form denied. Written as two two-branch unions — a hop is
independently forward or reverse — so each hop reports its own orientation and the four
combinations cost a quarter of the duplication. `?relType2` was added because a two-hop
row previously named only the first edge.
`test_templates.py::test_traceability_follows_the_second_hop_in_both_directions` and
`::test_traceability_names_the_type_of_each_hop`.

### B4: investigated and found correct

Recorded so they are not re-litigated. Each looked like a defect and is not.

- **Taxonomy scheme IRIs omit the trailing `#`.** Deliberate: `_prefix_for_graph`
  documents that a SKOS scheme is conventionally written `.../tax` while the prefix
  covering its concepts is `.../tax#`, and comparison strips the separator on both sides.
  No template joins on the scheme value; `core/classified-by` walks `skos:broader` from a
  concept parameter instead.
- **`notations.bpmn.native_id: bpmn:id`.** Accurate for the output it describes — see
  **A5**, where BPMN's `skos:notation` count is 0 — and the role-level chain covers both
  spellings. Newer output carries `skos:notation` instead, because `emitSkosNotation`
  defaults on, so both shapes are real. The per-notation entry is also not consumed by the
  runtime; only `metamodel` is.
- **`notation/c4/containers` and direct relationship triples.** It uses
  `c4:hasContainer` / `c4:hasComponent` / `arch:hasPart`, which the Structurizr emitter
  writes unconditionally, outside the `emitDirectRelTriples` branch. No capability gate is
  owed.

### B5: open findings, in priority order

Not fixed. Each is a package-level defect with a named mechanism, and the first four
change what the package promises, so each needs a decision-log entry when taken.

1. ~~**The `notation` field is declared but never enforced.**~~ **Done**, as **D20**. Gated
   on a new `notation_namespace` rather than the label, because a profile's slug for a
   notation is its own choice - ArchiMate's is `model`, so label matching would have
   refused a supported template against every bundled profile.
2. ~~**Relationship-form capabilities are Booleans describing a per-notation reality.**~~
   **Corrected, then done**, as **D21**. The premise was wrong: capability values were
   already tri-state (`TRISTATE = {True, False, "partial"}`) and the gate already
   downgraded a partial claim to a warning, so nothing needed a new capability model. What
   was missing sat in verification, which measured *presence* and could therefore only ever
   recommend `true` — overstating every dataset where the bridge is notation-specific.
   Now measured for coverage for `rdf_reifies`; `views_graph`, `view_geometry` and
   `element_lifecycle` are still probed existentially.
3. ~~**`requires:` drifts from what a template renders.**~~ **Done.** The suite checked
   that declared roles exist but not the converse, so a template could read roles it
   never declared. The mirror tests found it in **24 of 38 templates**: 22 undeclared
   roles, three undeclared `provenance` scopes, and two undeclared membership walks —
   which is what a class-level check buys over fixing instances. Since `expand_role`
   raises on a null binding, each was a `RenderError` from inside rendering waiting for
   the first profile honest enough to say a role is absent; they are now refusals that
   name the role. No bundled profile changed behaviour, because all the roles involved
   are bound in every one.

   Worth noting what the fix did **not** do: `core/coverage-gaps`, `core/elements-by-type`,
   `core/lifecycle`, `core/orphans` and `core/views` now honestly declare `part_of`,
   which makes item 5 below visible in the catalogue rather than resolved.
4. **Verification proves occurrence, not fit.** Partly closed by **D21** for capability
   coverage, and by B1's fixture-wide metamodel test. The rest stands: roles are probed by
   occurrence anywhere,
   a fallback role passes when any alternative occurs, and a graph role passes when a
   suffix matches a non-empty graph. Nothing probes notation identifiers, scheme
   resolvability, base-IRI fit, or whether the configured membership mode returns
   anything — the four checks that would have caught B1. A warning-only run still leaves a
   marker that reads as semantic verification.
5. ~~**Model membership is bypassed where it is meant.**~~ **Done.** All five templates
   now resolve `?model` through `{{MEMBERSHIP}}` and declare `requires.membership`. The
   hardcoded `dct:isPartOf` hop was the folder edge, which **A7** records as reaching the
   model for BPMN and stopping at `folder/Elements` for C4 — and since the lookup is
   `OPTIONAL`, the mismatch never raised. Measured on `fixtures/augmented.trig`
   beforehand: 0 of 2 C4 containers, 0 of 1 BPMN user task, 0 of 10 lifecycle rows and
   2 of 5 orphans named a model. The regression test asserts the invariant that holds
   under all three membership modes rather than any one mode's pattern: whatever lands in
   the column is an `arch:Model`.

   The scope question this raised is worth recording, because it looked like an
   inconsistency and is not. Membership renders **inside the scope that discovered the
   subject**, even in `core/coverage-gaps` where everything else is dataset-wide: under
   `same-graph-colocation` the pattern is "?model is a model", which only means "this
   subject's model" when evaluated in the subject's own graph. Rendered dataset-wide it
   would match every model in the store — the failure that mode's own documentation
   warns about. `core/coverage-gaps` is also the one template whose subject type is
   caller-chosen and may itself be a model, for which membership is meaningless and an
   unbound column is the correct answer; its test therefore excludes that column.
6. ~~**Negative tests and cross-role scope.**~~ **Done for `core/coverage-gaps`.** It
   scoped both the type search and the absence test to the semantic graph, and each was
   wrong in the opposite direction. `arch:Model` has lived in `graph/model` since the 1.3
   layout, so the type search found nothing and the template answered "no gaps" — the
   shape of answer that reads as perfect coverage. Meanwhile a graph-local absence test
   only establishes that a property is missing from the graph the type happened to be
   asserted in, and model provenance lives in `graph/provenance`.

   Both are now dataset-wide, which is the only reading under which absence is evidence
   that nobody recorded the property. The regression test pins an exact count because
   the count discriminates: on `fixtures/base.trig` the old form returns 0, widening only
   the type search returns 5, and the correct reading returns the 1 real gap.

   **`core/orphans` followed**, and the scope question resolved more cleanly than
   expected. The choice looked like "no relationship in the dataset" versus "none in the
   model", but graph-locality implements neither: under partitioning it means "none in
   the same converter input file", and a model spans several. So the reading is every
   semantic graph — wide enough to be true, narrow enough to stay meaningful, since a
   qualified relationship is a semantic fact and no views or provenance graph holds one.
   Expressed with the renderer's independent scopes (`semantic2`, `semantic3`), so the
   declared graph role is unchanged.

   No fixture and no observed export splits a relationship from its endpoints, so that
   one is correctness under partitioning rather than a measured change, and its test says
   so: an invariant guard that fails the moment a fixture does split them.

   **`core/reifies-audit` is deliberately left alone**, correcting the grouping above.
   Its `rdf:reifies` bridge is part of the relationship resource's own description, so
   "in this graph" and "wherever this relationship is described" are the same place. Its
   purpose — comparing the two halves of one resource against each other — is
   resource-local by nature, and widening the scope would add cost for no semantics. Its
   `?relType` column does still multiply rows; that belongs to item 7.
7. **Row multiplicity from optional projections.** Done for `core/orphans` (1,530 rows for
   1,009 distinct elements on a large export) and for `core/models` (263 rows for 55
   models). The second mattered most: an orientation template whose job is telling a reader
   how much is in front of them must not return more rows than models, and a catalogue
   built from a repository scan carries hundreds of `dct:source` values. Its source paths
   remain available per graph from `core/graph-provenance`.

   Also done for `core/identity-audit`, `core/reifies-audit` and
   `notation/leanix/factsheets`. Each counted once per value of a column rather than once
   per subject, and each result reads as a population — how many broken bridges, how large
   the inventory, how well reconciled the estate — so the inflation changed the finding
   rather than the formatting.

   `core/identity-audit` needed the thought rather than the pattern. Its inflation was the
   `any` scope: one assertion repeated across graphs is still one assertion, and converter
   output does repeat statements between graphs, which is how 4 `owl:sameAs` links became
   215 rows. So `DISTINCT`, which collapses graph repetition — and deliberately does **not**
   collapse direction, because a reciprocal pair and a one-sided assertion are different
   findings and the one-sided case is the one worth chasing.

   The fixtures still cannot catch this class directly: none holds a multi-typed orphan or
   relationship, a multi-phase fact sheet, or a cross-graph duplicate assertion, so these
   tests pin the one-row-per-subject contract without reproducing the inflation and say so.
   Extracting a fixture with those shapes is the remaining work, and per `CONTRIBUTING.md`
   it needs a converter run rather than an edit.
8. ~~**`core/discover-predicates` can describe a tuple that never existed**~~ **Done.** Two
   independent `SAMPLE`s pick independently, so the object kind and the example object
   could come from different solutions - real values describing a pair that never occurred,
   and invisibly so. The kinds are now the complete set rather than a sample, which is also
   the better answer: a predicate carrying both IRIs and literals is worth seeing, and a
   single sample hid exactly that.
9. ~~**Qualified classes are not unqualified predicates.**~~ **Done**, as documentation,
   which is where the defect was. `core/dependents-direct` told callers to source its
   `PREDICATE_PATH` from `core/discover-relationship-types`, which returns qualified
   *classes* (`am:Serving`); following a class as a predicate matches nothing and returns
   it as an empty answer. Both the template header and the parameter description now point
   at `core/reified-predicates`, whose triple terms name the predicate each relationship
   stands for - the same bridge that gates the template.
10. **Cost.** Several templates sort or cross-join globally before `LIMIT`; at scale
    `core/define-term`, `core/dependents-qualified` and `core/traceability` exceeded a
    3-minute wall clock or a 3.6 GB ceiling on an aggregate export. Correctness came first
    here (B3 adds branches); the structural work needs a large synthetic fixture and a
    time budget in CI, neither of which exists yet.
11. **Smaller, verified.** Four of five done.

    - ~~`core/views` documents unbound node counts where `COUNT` returns `0`~~ — done
      alongside item 5, since it was the same file.
    - ~~`core/label-collisions` normalises ASCII only~~ — done, and worse than recorded.
      `[^a-z0-9]` does not merely miss accents: every non-ASCII character became a
      separator, so a label written entirely in a non-Latin script normalised to the empty
      string and matched every other such label. An identity *candidate* list that invents
      candidates is worse than one that misses them. Now `\p{L}\p{N}`, with an
      empty-normalisation guard, verified against the engine's regex support.
    - ~~The README's template count had drifted~~ — done, and the count is now pinned:
      `TestDocumentedCountsMatchReality` knew four phrasings for "the whole catalogue" and
      not the one the README actually used, which is why prose could disagree with the
      catalogue in the sentence most readers see first. That phrasing is now checked too.
    - `core/view-diff` still compares element sets and loses repeated placements of one
      element. Left open deliberately: preserving placement identity is a redesign of what
      the template compares, not a fix to how it compares.
    - ~~The BPMN component whitelist is hand-maintained against an ontology that can
      grow~~ — **addressed, and the premise was wrong twice.** First correction: the
      categories *are* derivable. `bpmn-tax.ttl` declares `skos:narrower` from each
      taxonomy concept to the ontology classes it covers, so "Gateways covers these five
      classes" is a published fact; the template's invented buckets ("2 automated", "3
      human") existed only because nothing had looked. Second correction: the blocker was
      never availability of the ontology — it is published and local — but whether it is
      *in the queried dataset*, which is a different question with a different answer.

      Resolved by attaching vocabulary at query time rather than emitting it: a new
      optional `vocabulary` graph role, and `core/elements-by-category`, which derives both
      membership and category and names no notation term. Measured on the fixture: standard
      `Activities`/`Events` under `FlowObjects`, where the hand table covered 17 of 49
      element classes and omitted every gateway and sub-process.

      The hand-table template stays as the documented alternative, because a dataset with no
      vocabulary attached is the normal case and refusing outright would remove the only
      answer available there. What is *not* done: nothing yet checks that the attached
      vocabulary is the version the data claims conformance to. Pairing the wrong version
      derives from the wrong hierarchy, silently — the highest-value probe left, and the one
      that would also settle the `arch:unqualifiedForm` question **D21** records.

### B6: method and limits

Read-only throughout: during the audit no RDF was mutated, no bundled profile was edited
to make a failing query succeed, and no execution ceiling was raised to obtain a result.
Guardrail failures are recorded as failures rather than retried at a higher limit, which
is why item 10 above is an open cost finding and not a completed fix.

Two limits worth stating. Endpoint-coincident direct predicates without an
`rdf:reifies` bridge are evidence that two elements share an edge, not proof that the
predicate is the relationship's intended unqualified form. And truncated results are
floors, never totals — a capped count says "at least", and no finding here treats one as a
population.
