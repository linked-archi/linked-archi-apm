# APM alignment report — 2026-11-08

APM needed updating. The implementation is prepared as **0.11.0**, with 59 bundled model
questions and 44 templates. Version and release details are in `apm.yml:20` and
`CHANGELOG.md:13`; the catalogue totals are checked by `tests/test_questions.py:222`.

## Decisions and changes

The user authorised proceeding with the proposed alignment. Under that authorisation,
Codex retained the existing qualified template names for compatibility and aligned the
layer-crossing template with the published question. These implementation decisions are
recorded in `PROPOSAL.md:1570` and `CHANGELOG.md:13`.

- `core/neighbours` and `core/dependents` now ask meta's asserted-triple questions. The
  separate `*-qualified` templates retain their resource-level meanings and explain that
  loaded proposals can appear. The transitive `core/dependents-direct` remains separate
  from the two-hop question. See `PROPOSAL.md:1570` and `docs/templates.md:59`.
- The impact pattern selects the asserted questions and requires an explicit review of
  qualified alternatives when the required data is unavailable. See
  `skills/linked-archi-analyse/assets/patterns.json:102` and
  `skills/linked-archi-query/scripts/linked_archi_query/catalog.py:777`.
- Capability detection recognises a traversal through predicates read from
  `arch:unqualifiedForm`, including full IRIs, without mistaking mapping discovery,
  negative existence checks or triple terms for that traversal. The predicate index also
  includes the current BPMN and UML forms. See
  `skills/linked-archi-query/scripts/linked_archi_query/questions.py:357` and
  `tests/test_alignment.py:14`.
- The integrity template excludes unlinked, unasserted propositions and detects an
  asserted relationship missing its direct triple. Assertions can be in sibling semantic
  partitions. See `skills/linked-archi-query/assets/templates/core/reifies-audit.rq:1`
  and `tests/test_alignment.py:159`.
- Layer crossings now count distinct asserted source/target pairs using the ontology's
  hierarchy. A regression compares both implementations' complete result sets. See
  `skills/linked-archi-query/assets/templates/notation/archimate/layer-crossing.rq:1`
  and `tests/test_alignment.py:68`.
- `core/context-names` returns canonical and audience-specific names, contexts and
  languages. Existing plain-SKOS aliases still resolve. The profile also recognises
  diagrams containing only notes/groups without treating those figures as semantic
  elements. See `skills/linked-archi-query/assets/templates/core/context-names.rq:1`,
  `skills/linked-archi-profile/assets/profiles/linked-archi-default.yaml:182`, and
  `tests/test_alignment.py:87`.
- Instructions distinguish asserted relationships, derived assertions and proposals;
  explain the union versus explicit source-only graph selection; and document presentation
  names. See `docs/answering-a-question.md:191`.

## Sources and fixtures

The final snapshots are linked-archi-meta **3cccb1b**, converters **2de154d**, and
la-gram **fb60d0f**. All three bundled question files match meta and la-gram byte for
byte. The two expected-answer files and the presentation example match meta verbatim.
Snapshot provenance is recorded in `fixtures/PROVENANCE.md:20`.

All five converter shadow JARs were built with JDK 25. Conversions used an isolated
`git archive HEAD` of example-architecture-project **6a00bb43419fd7cbe15d1bc77c9b9f51e6932811**
and the committed ArchiSurance XML, preserving the user's unrelated LeanIX edits. The
partitioned Backstage output was regenerated from the existing source-map recipe.
The fixtures contain 3507 base quads, 3564 augmented quads, and 308 partitioned Backstage
quads; vocabulary contains 959 triples and the mapping has 96 pairs. See
`fixtures/PROVENANCE.md:69` and `fixtures/build_fixtures.py:1129`.

The curated fixture intentionally lacks one C4 bridge, preserving a meaningful audit
finding now that current BPMN output supplies bridges. Expected-question tests run all
85 cases (42 ArchiMate 3.2 and 43 ArchiMate 4) both flattened and in converter-style named
graphs, including a derived graph. See `tests/test_questions.py:130` and
`tests/test_questions.py:415`.

The two quoted CLI refusals in meta were updated to actual command output. They are now
included in meta commit **3cccb1b**, made externally while this task was running; this
agent did not commit. Their locations are `linked-archi-meta/doc/tools/apm.md:178` and
`linked-archi-meta/doc/guide/ontology-guided-conversational-analysis.md:208`, relative to
the workspace. No la-gram files were edited by this task.

## Validation

Commands ran from the relevant repository, with JDK 25 selected for Java commands.

| Command/check | Result |
|---|---|
| `./gradlew :converter-bpmn:shadowJar :converter-archimate:shadowJar :converter-backstage:shadowJar :converter-leanix:shadowJar :converter-structurizr:shadowJar` | Passed; all five converters rebuilt |
| `make questions` | Refreshed the three sets, index and upstream examples |
| `LINKED_ARCHI_META=../../../linked-archi-meta python3 fixtures/build_fixtures.py --refresh-forms` (also `--refresh-axioms`, `--refresh-shapes`) | Passed |
| `make check` | Passed: all six skills valid; 1019 tests in 109.433 seconds |
| `make docs` | Passed, strict MkDocs build |
| `LINKED_ARCHI_STORE=memory LINKED_ARCHI_STATE_DIR=/tmp/apm-alignment-final-state make verify verify-curated` | Zero errors; base 79 checks/20 warnings, curated 87 checks/18 warnings |
| `make release-notes` | Passed for 0.11.0 |
| Meta: `bash .scripts/validate.sh` | 266 Turtle files checked, zero syntax errors |
| `git diff --check` | Passed |

A final parser review also added a prefix-token boundary, preventing another vocabulary's
`unqualifiedForm` with a similarly named prefix from triggering a direct-triple requirement
(`tests/test_alignment.py:42`). All 44 alignment and question tests passed after this guard (23.704 seconds;
`/tmp/apm-alignment-final-targeted.log`).

The full-suite release-link check exposed a missing `[0.11.0]` comparison link; it was
fixed, and all 18 manifest tests passed on rerun. Profile warnings concern optional roles,
absent notations and unattached metamodel/vocabulary in the deliberately trimmed fixtures.
Full command outputs are in `/tmp/apm-alignment-check-passed.log`,
`/tmp/apm-alignment-final-docs.log`, `/tmp/apm-alignment-final-verify.log`,
`/tmp/apm-alignment-meta-syntax.log` and `/tmp/apm-converter-build.log`.

The skill-creator supplementary `quick_validate.py` rejects the existing `compatibility`
frontmatter field in all six skills. It gives the identical error on each HEAD version;
this is a validator/schema mismatch, not introduced by this change. The repository's
validator explicitly supports that field (`tests/validate_skills.py:33`) and validates
all six skills as part of `make check`.

## Boundaries and handoff

- Label expressions and pictures remain presentation data: APM does not evaluate or
  render them. See `PROPOSAL.md:1580` and the context-name template's limitations.
- Live endpoint behaviour and large-model performance were not separately benchmarked;
  validation covers the local engine, existing transport tests, published example cases
  and regenerated converter fixtures (`tests/test_questions.py:365`).
- The package is prepared locally; no commit, staging, tag, push, installation or release
  publication was performed. Concurrent source/modeler edits were preserved. Review the
  APM working-tree diff and `CHANGELOG.md:13` before the user's normal release process.
