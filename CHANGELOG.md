# Changelog

Notable changes to linked-archi-apm. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A section here is not optional at release time: `make release-notes` reads it, and
`make release-check` refuses to declare a version ready without one. The release
workflow publishes exactly this text, so what is written here is what a consumer reads.

## [Unreleased]

### Added
- **`lint --data` checks whether a query's paths are possible.** A path the metamodel forbids
  returns nothing rather than failing, so this answers "is this absence real?" before the
  query runs. Judged against the published SHACL, reporting what is permitted instead of what
  was asked. On `lint` only: the check costs a parse and a store read, and the moment worth
  paying for them is before running a query rather than on every execution of one that works.
- **A violation is only asserted where the evidence supports one.** Two conditions, both
  learned by getting them wrong: every shape namespace the notation's manifest declares must
  have shapes attached — `arch:formalRules` names them, so a namespace with nothing attached
  proves the set is partial — and the class hierarchy must be present, so that
  "unrelated to any constrained class" is a fact rather than a gap. The first draft accused a
  Business Actor of an impossible `am:flowsTo` because the fixture carried one ArchiMate shape
  of 73, and accused `arch:Element` of not being a permitted source when it sits *above* the
  permitted classes. Both are absence-means-prohibition, which is the reasoning this package
  exists to refuse — pointed inward. Anything unjudged is reported with its reason, and a
  report where nothing was judged is not a clean bill.
- **A verdict is provisional, and every report that judges anything says so.** The condition
  above is necessary and not sufficient: nothing published states how many shapes a document
  declares, so presence of each declared namespace is all that can be verified — one shape of
  28 passes it, and `versionIRI` does not help since extracting a single shape with the ontology
  header carries a matching version. A partial attachment can therefore still produce a wrong
  verdict. A test pins that limitation so publishing a count upstream turns it into a failure
  someone must address rather than a silent improvement.
- **The qualified form is checked too: `?rel a R ; arch:source ?s ; arch:target ?t`.** It was
  invisible at first, because the relationship legs are deliberately excluded from the
  direct-predicate table and nothing else looked at them — so the check ran over all 39
  catalogued templates and judged nothing, which reads as 39 clean templates and was no
  coverage at all. Each end is judged separately: judging them together excused the whole
  pattern as soon as either looked ambiguous, and since a class is trivially below itself, an
  exact source match hid a forbidden target.
- **Three notations are carried whole in the fixtures:** Backstage, C4 and LeanIX, with their
  manifests and class hierarchies. A slice proves the constraints can be read; it cannot
  support a check that accuses, since a missing shape would read as a prohibition. C4 declares
  two `arch:formalRules` namespaces, which is why completeness is per document set rather than
  per file. Hierarchies are extracted without the ontologies around them — LeanIX's is 65 kB
  of which the subclass edges are a few hundred bytes. ArchiMate is deliberately left out: its
  relationship shapes are 1.15 MB, so completeness cannot be reached by carrying the document,
  and a derived table would be a different kind of fixture.
- **What this check cannot do, recorded so it is not mistaken for a gap.** It cannot validate
  the catalogue. Every catalogued template leaves its ends untyped — `notation/backstage/
  ownership` asks *which* entities are owned, so typing them would defeat the question — and
  without a concrete class there is nothing to judge. A sweep reporting "no violations across
  39 templates" would be measuring nothing. The check is for hand-written and generated
  queries, where the classes are concrete.
- **The published constraints are readable as a table: which relationship may connect which
  element types.** Groundwork for checking a query's path instead of running it and reading
  an empty result as absence. `constraints.py` reduces both published forms to
  `(source class, predicate) -> allowed target classes`. The direct predicates are the ones
  that need it: `am:flowsTo`, `bs:ownedBy` and the other 73 in the `arch:unqualifiedForm`
  mapping carry no `rdfs:domain` and no `rdfs:range` anywhere, so shapes are the only
  statement of their validity — which is the part an Ontology-Based Query Check as published
  does not cover.
- **Constraints for notations that publish only the qualified form are derived.** Only
  ArchiMate states the direct form outright. Elsewhere the rule follows
  `arch:unqualifiedForm` from the relationship class to its predicate and reuses the
  qualified shape's classes, so `bs:Ownership` permitting `Element -> Group | User` becomes
  the rule for `bs:ownedBy`. A published constraint is never overwritten by a derived one.
  `fixtures/vocabulary.ttl` gains all 75 mapping pairs, without which that path had nothing
  to walk and no test.
- **"Unchecked" and "forbidden" are different answers and stay that way.** No constraint
  published, or none attached, returns `None`; an empty set would mean the metamodel permits
  nothing there. Conflating them turns "we do not know" into "your query is wrong" — the
  same mistake as reading an empty result as absence, pointed the other way. Coverage is
  reported beside the table so a caller cannot silently treat an unattached notation as
  clean.

### Changed
- **An empty result now points at the check that can explain it.** The guidance already said
  to lint a hand-written query; it now says to lint it `--data`, which is the part that
  matters — without it the lint only confirms the query is read-only, which a query that just
  ran obviously is. With it, the published shapes answer whether the path was possible at all.
  That was previously handed back to the reader as "check the direction of every relationship",
  which is work a machine can do.

### Fixed
- **The pair count in `fixtures/PROVENANCE.md` was wrong, and agreed with an upstream
  comment that was wrong the same way.** The qualified shape permits 365 pairs, not 361.
  Four in every ArchiMate relationship shape are the junction rules, which have exactly one
  permitted target each and are therefore written as a bare `sh:class` rather than a
  one-element `sh:or`; a reader walking only `sh:or` misses them. Both the shape's own header
  comment and the query this package verified with made that omission, so their agreement
  read as confirmation. Fixed at source in `linked-archi-meta` (`7431007`), where 21 comments
  across ArchiMate 3.2 and 4.0 understated their own shapes.

## [0.5.0] - 2026-09-16
Published schema became usable. Every ontology, taxonomy and SHACL shape set on
`meta.linked.archi` can now be fetched, lands where a Turtle file actually goes, carries the
constraints a query check needs, says which release it came from, and `verify` reports when
what a dataset declares conformance to has not been attached.

None of that was true a release ago, and one measurement explains why it went unnoticed:
asking the publisher for RDF with a full weighted `Accept` list returns 404 for ten of
twelve assets, while asking the same IRIs for `text/turtle` alone returns all twelve —
1.15 MB of ArchiMate relationship shapes among them. A publisher that answers 404 rather
than 406 for a serialisation it does not hold makes a broader request the less useful one.

**Two changes can surprise an upgrade.** `query run` and `query literal` print
tab-separated rows rather than a markdown table, so anything parsing stdout needs
`--format md`. And `graphs.roles.vocabulary` in the shipped profiles is `default` rather
than a graph suffix: a profile of your own binding a suffix keeps working unchanged, but a
Turtle vocabulary paired against a suffix binding returns nothing, silently — which is the
defect being fixed here, and worth recognising if you have hit it.

Three of the fixes below are for silent failures in this package's own work, two of them
introduced earlier in the same development cycle. They are written up in full rather than
summarised away, because a package whose argument is "an empty result is not evidence of
absence" has no business hiding its own.

### Added
- **The extracted schema fixtures name the release they were sliced from.**
  `vocabulary.ttl` and `shapes.ttl` are the only fixtures whose upstream moves
  independently of this package, and they said nothing about which version they came from:
  the extraction dropped each document's `owl:Ontology` header. ArchiMate shipping 3.3, or
  core moving off 0.4.0, would have left them testing yesterday's constraints while looking
  current — the defect `fixtures/PROVENANCE.md` opens by describing, where `base.trig` was
  faithfully extracted from output that predated the build beside it. A stamp does not
  prevent staleness; it makes a stale fixture say so, and a refresh against newer upstream
  show up as a diff. Only documents that actually contributed a shape are stamped, so the
  claim cannot over-reach: carrying every source consulted would have named LeanIX and C4
  shapes that are not in the file.
- **`verify` reports the published assets a dataset declares conformance to but has not
  been given.** Every model states its metamodel through `arch:modelConformsToMetamodel`,
  and each of the eleven published `arch:Metamodel` manifests names its own ontology,
  taxonomy and SHACL shapes — so the dataset can be asked whether what it points at is
  actually attached, and nobody has to remember which files to pair. Two findings, because
  the fixes differ: `metamodel.manifest` when the manifest itself is absent, naming the
  dereferenceable IRI and the `la-source url` command for it, and `metamodel.assets` when
  the manifest is attached but what it names is not. This is what stops a schema-level
  check from reporting "no violations" on an estate where the shapes were never loaded —
  the shipped fixtures declare five metamodels and carry shapes for two. Verified end to
  end against the publisher: fetching `archimate3/metamodel` moved ArchiMate from the first
  finding to the second, and fetching the ontology, taxonomy and shapes it names silenced
  both. Per notation and per asset kind rather than per document, because a probe adapter
  has only `ASK` and `COUNT`.
- **The fixtures now carry what says whether a query's path is possible.** Groundwork for
  checking a hand-written or generated query against the metamodel instead of running it and
  reading an empty result as absence. Two artifacts, because the two relationship forms
  declare validity in different places: `vocabulary.ttl` gains the 75 `rdfs:domain` /
  `rdfs:range` axioms from the core ontology, which is what an Ontology-Based Query Check
  walks ([arXiv:2405.11706](https://arxiv.org/abs/2405.11706)); and a new `shapes.ttl`
  carries published SHACL, because the **unqualified** (direct triple) forms have no domain
  or range anywhere — `am:flowsTo`, `bs:ownedBy` and the other 73 predicates in
  `unqualified-forms.json` are constrained only by node shapes. Reading those is new work
  relative to the paper, which walks RDFS alone. Both are regenerated by
  `build_fixtures.py --refresh-axioms` and `--refresh-shapes`, and
  `fixtures/PROVENANCE.md` records the selection rules.
- **`tests/test_fixtures.py` reads the file table in `fixtures/PROVENANCE.md`.** It was
  wrong for three of the five fixtures it described — `base.trig` documented at 1282 quads
  while holding 3320 — because nothing read it.

### Changed
- **HTTPS acquisition negotiates for Turtle first, and asks one type at a time.** The
  published assets a query check needs turn out to be reachable only this way. Asking
  `meta.linked.archi` with the full weighted RDF `Accept` list returns 404 for ten of
  twelve assets — every SHACL shape set and every taxonomy among them — while asking the
  same IRIs for `text/turtle` alone returns all twelve, including 1.15 MB of ArchiMate
  relationship shapes. The publisher answers 404 rather than 406 for a serialisation it
  does not hold, so a broader request is not a safer one, and weights cannot express the
  preference because they are ignored: Turtle at `q=1.0` beside JSON-LD at `q=0.7` still
  returns JSON-LD. So the first attempt names one type and the fallback lists everything.
  `--format` now sets the header rather than only interpreting the response, which fixes
  `--format turtle` failing with a parse error against a server holding several
  serialisations; a named format is never substituted. A URL with an RDF extension is
  still asked for once and broadly, so a quad dataset cannot be requested as Turtle and
  silently flattened.

### Fixed
- **The suite now refuses to contain a test it cannot run.** Two ways a written test goes
  missing without anyone noticing: an attribute that is no longer callable — how the
  `@requires_pyoxigraph` misuse below removed one — and a name defined twice in one class,
  where the second definition wins and the first never runs. Both are checked across every
  test module, and the guard is itself checked by reproducing the original mistake, so it
  cannot quietly stop being able to fail. Verified against a real injected instance too,
  not only the synthetic one. Nothing else in the suite was affected, which this now
  establishes rather than assumes.
- **A test that checked nothing, for the reason tests usually check nothing.**
  `support.requires_pyoxigraph` is a helper called with `self`, not a decorator. Written as
  `@requires_pyoxigraph` it is invoked at class-definition time and its return value —
  `None` — replaces the method, so `unittest` cannot see the test and the suite reports
  success with one fewer test than it has. That is how the count half of the
  `PROVENANCE.md` table check shipped dead in the same commit that documented it as
  enforced. Both halves run now, verified by breaking a documented count on purpose.

- **Paired vocabulary was unreadable in the shape it is actually published in.** Every
  ontology, taxonomy and shape set on `meta.linked.archi` is served as `text/turtle`, and
  `la-connect` loads a Turtle file into the default graph — but `graphs.roles.vocabulary`
  was bound to a named-graph suffix, so a scoped query asked for a graph the artifact does
  not have. Measured on the shipped fixture: identical triples returned five rows from a
  named graph and **none** from the default graph, with no error in either direction. So
  the documented workflow — fetch the published ontology, pair it with `la-connect` —
  silently answered "this model has none of those". A role can now be bound to `default`,
  meaning its triples are read unscoped, and the shipped profiles bind vocabulary that way.
  Isolation is unaffected, which was the original reason for a separate graph: instance
  templates are graph-scoped, so a class carrying `skos:prefLabel "Task"` still cannot come
  back as a candidate from `core/resolve-element` — verified rather than assumed. Under
  `layout: single` schema and instances share the default graph, which flattening always
  implied and nothing here can recover.
- **`fixtures/vocabulary.trig` and `shapes.trig` are now `.ttl`, in the default graph.**
  They were the reason the bug above went unnoticed: a named-graph fixture is easier than
  the published file, and a fixture that passes where the real artifact fails is the exact
  defect `fixtures/PROVENANCE.md` opens by describing. The builder is simpler for it —
  no graph wrapper, so no text assembly around the serialiser — and `test_profiles.py` now
  pairs the vocabulary the way a fetch delivers it.

- **A `200` carrying `text/html` is refused instead of parsed.** Content negotiation can
  fail without failing: asked for `application/trig`, `meta.linked.archi` answers 200 with
  254 kB of documentation. For a URL ending `.ttl` the extension then chose the format, so
  the page reached a Turtle parser and reported a syntax error at line 1 — which reads as
  "this vocabulary is malformed" rather than "the server sent you a web page". The refusal
  names the `Accept` header that produced it.

## [0.4.0] - 2026-09-14
Results are handed over as tab-separated rows now. The shape that was easiest to read
turned out to be the one that cost the most to produce and the one agents worked around:
the aligned markdown table padded every cell, which came to more bytes than the JSON
envelope's entire metadata block, and it truncated rows at the display cap while spending
them. Agents given the envelope instead were shelling out to `jq` to recover a column.

**If you parse `query run` stdout, pass `--format md` to keep the table.** Everything
else is additive, and `--json` still means what it did.

Both halves of this release are the same defect in different clothes: a fact stated in
more than one place, with nothing checking that the copies agreed. The version was
repeated in ten files and had been stale for two releases, including the install command
a reader copies first. Now one place states it, one command writes the rest, and a test
fails the build when they diverge.

### Changed
- **`query run` and `query literal` print tab-separated rows by default, not a markdown
  table.** Agents were piping results through `jq` to recover a column, which is a parse
  step that should not have been necessary. Measured on one 108-row result, the same answer
  costs 11.1 kB as `tsv`, 14.9 kB as the aligned table — which showed only 100 of the rows,
  because alignment padding accounted for about 2.5 kB — and 21.8 kB as the JSON envelope,
  most of that last figure being the column name repeated on every row. The envelope's
  metadata was 708 bytes of it, so provenance was never the cost. `cut -f2` now works
  without a parse, and `grep -v '^#'` leaves the header and the rows and nothing else.

### Added
- **`--format tsv|md|json` on `run` and `literal`.** `tsv` is the new default; `md` is the
  previous aligned table, kept because padding is what makes a result readable to a person;
  `json` is the full envelope, and `--json` still means exactly that. The row count, caveats
  and citation travel as `#` comment lines rather than on stderr, so capturing stdout alone
  cannot silently drop the attribution. Values inside a row are escaped, because a literal
  containing a tab would otherwise invent a column and nothing downstream could tell. All
  three formats carry identical values: the connect adapters flatten every RDF term to its
  lexical form, so none of them is a W3C SPARQL results document and none claims to be.
  NDJSON was considered and left out — `json` already gives an agent every row, and
  streaming is the only thing NDJSON would add.

### Fixed
- **The documented install pin and every skill's `metadata.version` said 0.1.0 at
  release 0.3.0.** The version was repeated in ten files outside `apm.yml` and read by
  nothing, so two releases of drift accumulated in the copies a consumer sees first: the
  `apm install linked-archi/linked-archi-apm#v0.1.0` line in `README.md` and `USAGE.md`
  named a tag two versions old, and all six `SKILL.md` files still declared 0.1.0. That
  frontmatter is the only version an installed skill carries — `apm.yml` is not deployed
  into a harness — so the stalest copy was the one an operator would read to identify what
  they had. `apm.yml` is now the single authority, `make bump TO=X.Y.Z` writes every derived
  copy from it, and a packaging test fails the build when any of them disagrees. The check
  also fails when a pattern matches nothing, so rewording prose cannot silently retire it.

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

[Unreleased]: https://github.com/linked-archi/linked-archi-apm/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/linked-archi/linked-archi-apm/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/linked-archi/linked-archi-apm/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/linked-archi/linked-archi-apm/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/linked-archi/linked-archi-apm/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/linked-archi/linked-archi-apm/releases/tag/v0.1.0
