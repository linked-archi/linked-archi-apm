# Brief: linked-archi-query after meta's D33 (direct triples, derivations)

Bring linked-archi-apm's query skill in line with meta's question sets as they are now. Since APM's last
alignment (`c9b4dc4`, version 0.10.0), meta changed how its questions read relationships (meta's DD-33): they
follow the direct triple `{source} {predicate} {target}`, so a valid derivation is one hop and a potential one,
which asserts no triple, is never read as a relationship. A question about the relationship itself reads its
qualified resource. Converters 1.3.0 also write BPMN's direct predicates. Until APM re-bundles, its question
tests run meta's expected answers against the old bundled sets and fail.

Target: linked-archi-apm 0.11.0.

## Hard constraints

- Never commit, stage, stash or push; the user commits. See
  `/Users/kalin.maldzhanski/data/linked.archi/.kiro/steering/no-autonomous-commits.md`.
- Run `git status` before editing anything, in every repo you touch, and never revert a change you did not make.
- `.linked-archi-cache/` in this repo holds real company data from an audit. Exclude it from every search
  (`grep --exclude-dir=.linked-archi-cache`, `rg -g '!.linked-archi-cache'`), never open it, and never repeat
  anything from it.
- Two decisions below are the user's: whether a template keeps its name, and anything changed outside this repo
  (meta's docs). Analyse them, state the options with their consequences, and ask before acting.
- Never modify `tools/modellers/excalidraw-linked-archi-yjs-demo`.
- In linked-archi-meta, if the user agrees to a change there: British English; never run its
  `generate-docs.sh` on the real repo; never write into `.agents/tasks/notation-order-followup/`; published docs
  give no `.scripts/` or `.reference/` paths; check with `./validate.sh --syntax`.
- Back every claim in your report with a file path and line number, and say what you could not verify.

## Background (verified 2026-11-04)

- meta: `/Users/kalin.maldzhanski/data/linked.archi/linked-archi-meta`, at `fa3e69e` (pushed), which holds
  everything below. Run every step against it: `make questions META=/Users/kalin.maldzhanski/data/linked.archi/linked-archi-meta`
  (the Makefile's default, `../../../linked-archi-meta`, resolves to the same directory).
- The published site (`https://meta.linked.archi/…`) is older: its ArchiMate 4.0 set has 20 questions, meta's
  file 24. Read meta's files, not the site.
- meta's decision record: `linked-archi-meta/doc/guide/design-decisions.md`, DD-27/DD-28 (derivations, where they
  live), DD-33 (how questions read relationships). The ArchiMate guides
  (`doc/guide/archimate/archimate-4.0-modeling-guide.md`, `…-3.2-…`) describe the questions.
- What a derivation looks like: the last section of `linked-archi-meta/examples/archimate4-questions-example.ttl`
  (two potential derivations, as the rules write them). A valid derivation also asserts the direct triple and the
  qualified predicate leading to it; a potential one asserts neither until a modeller confirms it. Its rule is
  `prov:wasGeneratedBy/prov:qualifiedAssociation/prov:hadPlan`, its premises `prov:wasDerivedFrom`, its
  certainty `am4deriv:derivationCertainty` (`amderiv:` for 3.2).
- la-gram already reads meta's sets this way; its spec of that work is
  `tools/modellers/la-gram/.kiro/specs/la-queries/` (design § linked-archi-query, tasks 7). Read it for D16–D19
  (the one-graph reading, direct triples by default, the metamodel checked when a question runs, one name with
  two implementations), which this repo already implements.

## Tasks

### 1. Re-bundle the question sets

`make questions` refreshes `skills/linked-archi-query/assets/questions/` (`core-questions.ttl`,
`archimate4-questions.ttl`, `archimate3.2-questions.ttl`, `index.json`) and the fixtures' copy. What arrives:

- `core/neighbours-qualified` is now `core/neighbours`, and `core/dependents-qualified` is `core/dependents`
  (IRIs `archq:neighbours`, `archq:reaches-in-two-hops` unchanged). Both follow direct triples, reading the
  relationship predicates from the metamodel (`arch:unqualifiedForm` on a subclass of
  `arch:QualifiedRelationship`, the most general), so both now need `arch:ModelAndMetamodelDataset`.
  `neighbours` has no `?relationship` column.
- `core/reifies-audit` (`archq:relationship-integrity`) no longer reports a proposition: a resource whose
  `rdf:reifies` triple is not asserted and to which nothing leads.
- Per ArchiMate version, twelve questions on direct triples:
  - seven along the chains the valid derivation rules follow, anchored on the relationship asked about:
    `responsibility-assignments`, `capability-realisation`, `unassigned-behaviour`, `unrealised-services`,
    `unrealised-requirements`, `principles-without-requirements`, `work-package-deliverables`;
  - four by their fixed steps, because a walk was too slow on a 350 000-triple model:
    `application-dependencies`, `applications-without-technology`, `requirement-traceability`,
    `unrealised-capabilities`;
  - the domain and layer crossings, which now count pairs of elements.
  `responsibility-assignments` now asks only about active structure and has no `?assignment` column.
- Two new questions per version: `notation/archimate4/potential-derivations` and
  `notation/archimate4/potential-derivation-premises` (`notation/archimate/…` for 3.2). They declare `prov` and
  `am4deriv` (`amderiv`) in `sh:declare`. On meta's NordFreight example with its derivations
  (`linked-archi-meta/examples/nordfreight/nordfreight-model.ttl`), the first answers 88 rows.

Check that the index and `catalog show`/`dump` list the new and renamed entries.

### 2. Requirement checks (D17, D18)

What the re-bundled questions need:
- `neighbours` and `dependents`: the metamodel's `arch:unqualifiedForm`;
- the questions on direct triples: `direct_rel_triples`;
- the two derivation questions: nothing a profile claims. They answer nothing until derivations are loaded; say
  so in the answer rather than refuse.

Check that none is refused on `linked-archi-default`, and that `linked-archi-qualified` refuses what needs direct
triples and names the remedy.

### 3. `tests/test_questions.py`

meta's two expected files (`linked-archi-meta/examples/archimate4-questions-example.expected.tsv`,
`…archimate3.2-…`) changed:
- `capability-realisation` gains `ex:clerk ex:customer` (both versions);
- 3.2's `work-package-deliverables` gains `ex:crmFunction ex:customerService`;
- `requirement-traceability` is as before;
- four cases for the derivation questions, with a new `@prefix` line for `am4deriv`/`amderiv`.

Each question example now has two potential derivations beside the model, with `rdf:reifies` triple terms and
`prov:` provenance. The flattened and converter-graph variants of the test have to carry them: a derivation is
model data, and in a store it would be in the model's `…/graph/derived`. Check that the store and parser used
here accept triple terms (RDF 1.2).

### 4. One name, two implementations (D19) — the user decides

`core/neighbours-qualified` and `core/dependents-qualified` are templates in
`skills/linked-archi-query/assets/templates/catalog.json` whose meta questions are now named `core/neighbours`
and `core/dependents`. For each, set out the two options and ask:
- keep it as the qualified reading under its own name. It then answers differently from meta's question: it
  returns resource IRIs, counts two relationships of one type between one pair twice, and lists a potential
  derivation;
- retire it in favour of the question.

`core/dependents-direct` (transitive, `PREDICATE_PATH`) is not meta's `core/dependents` (two hops, every
relationship predicate); keep the names apart.

Whatever is decided, update:
- `catalog.json`, `catalog show`/`dump`;
- the analyse patterns that pick these by name: `skills/linked-archi-analyse/assets/patterns.json`,
  `references/patterns/impact-and-dependency.md`, `references/machine-contract.md`;
- the query skill: `SKILL.md`, `references/execution.md`, `references/troubleshooting.md`,
  `scripts/linked_archi_query/cli.py`;
- the docs: `docs/templates.md`, `docs/concepts/profile.md`, `docs/skills/query.md`.

meta's docs name these templates too: task 5.

### 5. meta's docs that quote the refusal — after task 4, with the user's agreement

meta's docs show the refusal `la-query` gives `core/dependents-direct` on `linked-archi-qualified`, and its
"Try instead" list. That list is the template's `alternatives` in `catalog.json`: `core/dependents-qualified`,
`core/neighbours-qualified`. Where:

| File (in `linked-archi-meta`) | Lines | What |
|---|---|---|
| `doc/tools/apm.md` | 178–183 | the refusal, in a code block under "A refusal is an answer" |
| `doc/guide/ontology-guided-conversational-analysis.md` | 208–213, and 216–218 | the refusal, then "The qualified variant runs, …", which tells what that alternative answered |
| `doc/assets/diagrams/guide/ontology-guided-conversational-analysis/zero-rows-four-meanings.svg` | 121 | `Try instead: core/dependents-qualified`, drawn in the diagram |

The quote is stale already, whatever task 4 decides. Today `la-query query render core/dependents-direct
--profile linked-archi-qualified --set FOCUS_IRI=… --set PREDICATE_PATH=…` prints the capability line as
"capability 'direct_rel_triples' is False in profile 'linked-archi-qualified' but this template needs True",
ends the "Try instead" line with "(same question, different evidence).", and has no blank line before "This is a
refusal". Replace both code blocks with the output of that command as it is once this task list is done; do not
write it by hand.

What else changes depends on task 4:
- the templates keep their names: only the quote;
- they are renamed: the names in all three files;
- they are retired: meta's `core/neighbours` and `core/dependents` need direct triples too, so on
  `linked-archi-qualified` nothing reads dependencies. The refusal names another alternative or none, and the
  guide's scenario (lines 216–218: "The qualified variant runs, and the answer comes back …") no longer holds.
  Propose the rewrite — the remedy is then to reconvert with direct triples — and ask.

Ask the user before changing meta. When changing it:
- follow `linked-archi-meta/.ai/steering/documentation-conventions.md` (front matter, diagrams). Leave the
  front matter's dates as they are;
- edit the SVG's `<text>` in place and keep it inside its box (the diagram is drawn by hand; there is no source
  to regenerate it from);
- British English; no `.scripts/` or `.reference/` paths;
- do not run `generate-docs.sh` in meta's checkout. To see the pages rendered, build into a scratch folder.

### 6. Templates that read the relationship resource

These use `ROLE:rel_source`/`rel_target`: `core/neighbours-qualified`, `core/dependents-qualified`,
`core/reifies-audit`, `core/orphans`, `core/traceability`, `core/define-term`,
`core/discover-relationship-types`, `notation/archimate/layer-crossing`, `notation/bpmn/process-flow`,
`notation/backstage/ownership`.

With a model's derivations loaded (`la-connect` reads the union, the derived graph included), each lists a
potential derivation as a relationship, and `reifies-audit` reports each as a violation (88 on NordFreight).
- Bring `reifies-audit` in line with meta's: skip a resource whose triple is not asserted and to which nothing
  leads.
- Move each listing that needs no resource to direct triples, as meta did.
- For the rest, say in its `Does NOT prove` that a potential derivation is listed when derivations are loaded.
- `notation/archimate/layer-crossing` shares its name with meta's 3.2 question, which now counts pairs on direct
  triples. One name should give one answer: propose which, and ask.

### 7. `core/dependents-direct`

Its header (`skills/linked-archi-query/assets/templates/core/dependents-direct.rq`, line 12) says the converters
write direct triples only with `--emit-direct-rel-triples`, "off by default". It has been on by default since
converters 1.3.0, which the 0.10.0 profile already claims. Reword the comment, and check what still refuses the
template.

### 8. BPMN from converters 1.3.0

The converters (`tools/converters/linked-archi-converters`, `CHANGELOG.md` § 1.3.0) write BPMN's direct triples by
default: `bpmn:sequenceFlow`, `bpmn:messageFlow`, `bpmn:association`, `bpmn:conversationLink`,
`bpmn:dataAssociation`. Each is bridged with `rdf:reifies`, and the qualified property is published
(`bpmn:qualifiedSequenceFlow` …) where `arch:hasQualifiedRelationship` was. UML's control, object and
information flows gained direct predicates too: `uml:controlFlowsTo`, `uml:objectFlowsTo`,
`uml:informationFlowsTo`.
- Re-extract the fixtures: `make fixtures` for `base.trig`, `augmented.trig` and `flat.ttl`, and
  `fixtures/build_fixtures.py --rebuild-13` for `converter-1.3.trig`, which needs the converter jars and a JDK
  (`recipe_13()` in that file has the invocation). Update `fixtures/PROVENANCE.md`.
- Revisit the profile's `partial` `rdf_reifies` for BPMN.
- `notation/bpmn/process-flow` could now follow `bpmn:sequenceFlow`.

The converters' version is still `1.3.0-SNAPSHOT` and untagged; build from the working tree and say so in
`PROVENANCE.md`.

### 9. Derivations in an answer

In `docs/answering-a-question.md` and the analyse skill, say what a store's derived graph changes:
- a question on direct triples gives what holds (the union) or what was stated (`FROM` the model and semantic
  graphs, DD-28);
- the two derivation questions are how to ask what the rules propose.

### 10. Release

`make bump TO=0.11.0`; the `CHANGELOG.md` section for 0.11.0; `make questions`; `make check` (skills and the test
suite); `make docs` (strict, and `tests/test_docs.py` checks the counts the site states).

## Done when

- `make check` and `make docs` pass, with every case of meta's two expected files, flattened and in converter
  graphs.
- The decisions in tasks 4 and 6 are the user's, recorded in `CHANGELOG.md` and in D19's text; meta's docs
  (task 5) changed only with the user's agreement.
- A report beside this brief (`report.md`) lists what changed, what was decided and by whom, the commands run with
  their results, and what is left.
