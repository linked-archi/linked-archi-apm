---
name: linked-archi-query
description: Answer questions about enterprise architecture by querying an RDF knowledge graph built from ArchiMate, BPMN, C4 or Structurizr, Backstage and LeanIX models with the Linked.Archi converters. Generates SPARQL from a tested, profile-resolved template library rather than from scratch, and returns the query and its provenance with every answer. Use when asked which applications support a process, what depends on a system, which capabilities are unrealised, who owns what, where a diagram shows an element, or any question that crosses two modelling tools. Refuses templates the dataset cannot support instead of returning misleading empty results.
license: Apache-2.0
compatibility: Needs Python 3.11 or newer and PyYAML. Rendering delegates profile resolution to linked-archi-profile; execution also delegates transport to linked-archi-connect and needs pyoxigraph for local RDF. Endpoint transport uses the standard library. Read-only throughout.
metadata:
  author: linked-archi
  version: "0.3.0"
  homepage: https://meta.linked.archi
allowed-tools: Read Bash(python3:*)
---

# Querying an architecture knowledge graph

## Invocation and companions

Owner command: `la-query`. Catalogue browsing and `lint` work alone; rendering needs `linked-archi-profile`, and execution additionally needs `linked-archi-connect`.

Resolve it once, with **one** call. `python3` is the only command these instructions need, which is also all this skill's `allowed-tools` grants:

```bash
python3 - <<'PY'
import os, pathlib, shutil
print("on PATH:", shutil.which("la-query") or "no")
root = pathlib.Path(os.environ.get("LINKED_ARCHI_SKILLS_DIR") or "~/.kiro/skills").expanduser()
print("install root:", root, "(exists)" if root.is_dir() else "(not there)")
for owner in sorted(root.glob("linked-archi-*/scripts/la-*")):
    print(" ", owner)
PY
```

Installed skills usually sit together under `~/.kiro/skills` or `~/.claude/skills`, often
as symlinks into a checkout. Every owner here resolves its siblings the same way:
`$LINKED_ARCHI_SKILLS_DIR` when set — authoritative, never falling back — then the sibling
directory beside the running skill, then `PATH`.

**Never search the filesystem for skills, scripts, templates or profiles, and never search
from `/` or `$HOME`.** If anything is unresolved, run `la-query doctor`: it prints this
skill's root, its resolved command, its dependencies and every companion it can reach. If a
companion is genuinely missing, report it by name and stop.


**Examples below are skill-relative, but nothing requires you to `cd` here.** Resolve the
command once as above and keep it in a variable; then every example works from wherever the
project is, which is where the dataset and the output belong:

```bash
SKILL="${LINKED_ARCHI_SKILLS_DIR:-$HOME/.kiro/skills}/linked-archi-query"   # resolved above
PROJECT="$PWD"                                  # wherever you actually are
```

Write derived artifacts relative to `$PROJECT`, never into the skill directory: a profile or
a result that lands beside an installed skill is lost on the next upgrade, and invisible to
the repository that needed it.

`python3 <script>` is deliberate: installing a skill does not put its owner CLI on `PATH`.
Companion paths assume the required skills are installed as siblings.

This graph is built by converting several modelling notations into RDF against a
shared ontology. It does not look like a graph designed as a graph. Writing SPARQL
against it from memory produces queries that run, return rows, and are wrong — worse
than failing.

So do not write it from memory. Templates in this package name semantic **roles**;
the profile binds each role to a term for the dataset in front of you. Nothing here
hardcodes a vocabulary.

## Always do this first

**Know which dataset you are querying, and never guess one.** Answering from a file
nobody chose is the one failure this skill cannot detect afterwards — the result looks
sound and cites the wrong architecture.

If the user gave a path, use it. If `$LINKED_ARCHI_DATA` is set, `--data` can be
omitted from every command below. If neither, `python3 ../linked-archi-connect/scripts/la-connect datasets` lists candidates and
selects none of them; choosing between them is `linked-archi-connect`'s job, so hand
over to that skill if it is installed. Either way, do not answer until the dataset is
settled, and do not fall back to this package's fixtures.

```bash
python3 scripts/la-query query run core/inventory-summary --data graph.trig
python3 scripts/la-query query run core/models    --data graph.trig
```

`core/inventory-summary` tells you which notations are loaded and how much of each, in
one screen. `core/inventory` breaks that down by graph and type once you know where to
look - it returns graphs x types rows, which on a large estate truncates and buries the
signal.
Do not answer a counting or coverage question without it: an empty graph and a graph
with no matching elements look identical from every later query.

`core/models` tells you which notations contributed, via
`arch:modelConformsToMetamodel`. If only one loaded, no cross-notation question can
be answered.

Then resolve every name the user typed:

```bash
python3 scripts/la-query query run core/resolve-element --data graph.trig --set TERM="order service"
```

Never construct an IRI from a label. The minted form is
`{base}{notation}/{modelId}/element/{localId}` and the local id is the source tool's,
so guessing it guesses twice. When more than one candidate comes back and the choice
changes the answer, ask.

**A phrase that resolves to nothing may be a model rather than a concept.**
`core/resolve-element` searches concepts only, so a model name returns zero and reads
as absence. Try `core/resolve-model`, which searches title, name, native id,
description, source filename, status and notation, and ranks exact before prefix before
substring:

```bash
python3 scripts/la-query query run core/resolve-model --data graph.trig --set TERM="errata ingestion"
python3 scripts/la-query query run core/define-term   --data graph.trig --set TERM="Billing"
```

`core/define-term` is the "what is X" lookup: definition, native type, owning model,
model source, and the relationships one hop out. Its `candidates` column counts the
distinct resources the term matched — greater than one means name the candidates and
ask, rather than describing the first row as the answer.

## Choosing a template

```bash
python3 scripts/la-query catalog list --profile linked-archi-default --why
python3 scripts/la-query catalog show core/dependents-qualified --profile linked-archi-default
```

`catalog list` marks each template as available, refused, or usable with a caveat.
`--why` explains every refusal and names an alternative. Routing table:

| Question | Start with |
|---|---|
| What is loaded | `core/inventory-summary`, `core/models`; then `core/inventory` for detail |
| Which IRI is this name | `core/resolve-element` for a concept, `core/resolve-model` for a model |
| What is X, what does this term mean | `core/define-term` |
| What does the data say about X | `core/element-detail` |
| Which relationship kinds exist here | `core/discover-relationship-types` |
| What does X relate to | `core/neighbours-qualified` |
| What depends on X | `core/dependents-qualified` |
| What connects these two kinds of thing | `core/traceability` |
| What is under this taxonomy branch | `core/classified-by` |
| Where is X missing a property | `core/coverage-gaps` |
| Where did this come from | `core/provenance` |
| Which diagrams show X | `core/view-usage`, or `core/view-usage-semantic` where there is no views graph |
| What is on diagram X | `core/view-contents`, or `core/view-contents-semantic` where there is no views graph |
| What is on one diagram and not the other | `core/view-diff` |
| Are these two things the same system | `core/identity-audit` for assertions; `core/label-collisions` for un-asserted candidates |
| What takes part in a BPMN model | `notation/bpmn/process-components` (participants) vs `notation/bpmn/process-flow` (the edges between them) |
| Notation-specific questions | `notation/archimate/`, `notation/bpmn/`, `notation/c4/`, `notation/backstage/`, `notation/leanix/` |

## Running one

**Read the parameters before the first call, not after the first refusal.** They are not
guessable and they are not uniform: `core/neighbours-qualified` and `core/element-detail`
take `FOCUS_IRI`, `core/resolve-element` takes `TERM`, and an invented name like `ELEMENT`
is refused rather than ignored. One call settles it:

```bash
python3 scripts/la-query catalog show core/neighbours-qualified --profile linked-archi-default

# Or every template's full metadata, availability and caveats in one call:
python3 scripts/la-query catalog dump --profile linked-archi-default
```

`catalog show` is the authoritative parameter list — it carries the typing, the defaults,
what the template does not prove, and whether this profile supports it. Use `dump` when
you are choosing among several templates or binding several sets of parameters; it is one
call instead of one per template.

**Do not grep the template files.** `catalog list --why` and `catalog show` carry all of
that. Reading the `.rq` files is skill development, not use.

Then run it:

```bash
python3 scripts/la-query query run core/neighbours-qualified --data graph.trig \
  --set FOCUS_IRI=https://example.org/la/bpmn/order-fulfillment/element/Task_Validate

python3 scripts/la-query query render core/coverage-gaps --profile acme \
  --set RESOURCE_TYPE=... --set EXPECTED_PREDICATE=...   # inspect without executing
```

Parameters are typed and escaped. An IRI is accepted with or without angle brackets,
and a relative IRI is refused.

**Do not pipe a result through `jq` to get a column.** The default output is already
tab-separated rows, so `cut -f2` works and the parse step is not needed:

| | |
|---|---|
| `--format tsv` | Default. A header line, then one line per row. The row count, caveats and citation follow as `#` comment lines, so `grep -v '^#'` leaves the header and the rows and nothing else. Tabs and newlines inside a value are escaped, so a literal cannot invent a column. |
| `--format md` | An aligned markdown table. Costs about a third more for the same rows, which buys readability for a person. |
| `--format json` | The full envelope. Use it when the *metadata* is what you need — `query_id`, `truncated`, `warnings` — or when writing an evidence step. `--json` is the same thing. |

All three carry identical values: the adapters flatten every RDF term to its lexical
form, so none of them is a W3C SPARQL results document and `json` is not richer, only
more verbose. `-o FILE` always writes the envelope whatever `--format` says, because an
artifact is a record that `query batch` and the analyse bundler read back.

**Two different things are called a limit, and only one of them bounds the query.**

| | |
|---|---|
| `--set LIMIT=N` | The query's own cap. It is what `LIMIT` in the SPARQL becomes, what decides whether a result is `truncated`, and the only one that bounds the work. |
| `--limit N` | How many rows to **print**. A display cap: `-o` and `--format json` still write every row, and the query still computed them all. |

`--set LIMIT=N` is refused above two separate ceilings, and the lower one wins: the
template's own `max` from `catalog show`, and the profile's `limits.max_row_limit`. The
refusal names which one it was, because they live in different files. A template whose
own default sits above the profile's ceiling runs clamped to the ceiling and says so in
a caveat — the caller did not choose that default, so refusing them would be the wrong
answer.

Prefer adapting a catalogued template to inventing a query. Every template is
executed against the committed fixtures on every change; a query you invent is not.
When you do adapt one, say so and show the final SPARQL.

### Several questions at once: `query batch`

A local dataset is parsed **per process**, and on a large aggregate that parse is the
dominant cost — seconds of loading against single-digit milliseconds of query time. So
asking five questions with five commands pays for the dataset five times. `query batch`
pays once:

```bash
python3 scripts/la-query query batch runs.json --data graph.trig
```

```json
{"schema_version": 1, "queries": [
  {"id": "inventory", "template": "core/inventory-summary", "out": "/tmp/inv.json"},
  {"template": "core/resolve-element", "set": {"TERM": "sourcing"}, "out": "/tmp/r.json"},
  {"file": "queries/capability-tree.rq", "out": "/tmp/tree.json"}
]}
```

Each entry takes exactly one of `template`, `file` or `query`, plus optional `id`, `set`
and `out`. Measured on a large aggregate, a handful of queries took roughly **2.8x** the
wall clock as separate commands, with identical rows, `query_id` and `truncated` either
way.

Two properties worth relying on. Every entry is rendered before any query executes, so a
typo in the last entry costs nothing — no load, no partial run. And the whole batch is
validated read-only before any of it runs, so a batch cannot do partial unsafe work.

**Only the first result carries `load_ms`.** The load happened once, so the rest report
zero; summing them gives one load rather than N.

Batching is the only thing that removes this cost. Reusing a parsed store across
processes was implemented and measured, and it makes analytical queries slower — see
`linked-archi-connect/references/store-modes.md` before reaching for `--store cached`.

### An ad-hoc query, and how to not fool yourself with it

For a question the library does not cover, `query literal` still expands profile
directives and still enforces read-only, so a hand-written query gets the same namespace
and graph-scoping treatment:

```bash
python3 scripts/la-query query literal --data graph.trig \
  --query '{{PREFIXES}} SELECT ?s WHERE { {{GRAPH_OPEN:semantic}} ?s a {{ROLE:element_class}} . {{GRAPH_CLOSE}} }' \
  --limit 50

python3 scripts/la-query query literal --data graph.trig --file question.rq
```

**Start every ad-hoc query with `{{PREFIXES}}`.** Nothing is injected for you: prefixes
appear only if you ask for them, so `bs:Component` or `skos:prefLabel` in a query without
it fails with `Prefix not found` and a character offset into the *rendered* text, which
does not line up with what you wrote once the other directives have expanded. Write it
even when the query seems not to need one — `{{ROLE:...}}` expands to a full `<IRI>`, so a
query built only from directives works without it right up until you add one prefixed
name.

Write a negative test — `NOT EXISTS`, `MINUS`, `EXISTS` — with its own `GRAPH ?any` scope,
never bare inside `{{GRAPH_OPEN:...}}`. See the fourth item above; this is the mistake in
an ad-hoc query that produces confident findings that do not exist.

**Lint it before you believe it.** A hand-written query that returns nothing is far more
often broken than evidence of absence:

```bash
python3 scripts/la-query lint --query 'SELECT ?s WHERE { ?s ?p ?o }'
python3 scripts/la-query lint question.rq
```

`lint` reports the query form and refuses anything that is not read-only. An empty result
from an invented query means: lint it, check the graph scope, and check the direction of
every relationship — before reporting "none".

## Never substitute something else for a query

The point of this skill is that an answer is attributable: a named template, a rendered
query, a dataset identity, a profile version. Anything that bypasses that loses all of it.

- **Do not grep the RDF.** `grep` on a `.trig` file is not `core/resolve-element`: it
  cannot resolve a label to an IRI, cannot scope to a graph, and produces no provenance.
- **Do not load the graph with another RDF library** to answer a question. That skips the
  read-only enforcement, the profile resolution and the reproducibility envelope this
  package exists to provide.
- **Do not search the repository for facts** the graph is supposed to supply.

If the tooling cannot be resolved, say so and stop — `la-query doctor` names what is
missing. If no dataset is attached, report that instead of looking for one. If a read-only
local fallback is genuinely needed, state that you are leaving the supported path and ask
first.

## The four things that break naive SPARQL here

**Relationships are usually only in the qualified form.** Every relationship is a
resource typed `arch:QualifiedRelationship` carrying `arch:source` and `arch:target`.
The direct `source predicate target` triple is **opt-in at conversion time** and off
by default, so on an ordinary dataset it is not there. Traverse through the qualified
form. If both forms are present, never union them: the same relationship matches
twice and every count doubles, with no error.

**Everything is in named graphs, and the scope matters.** A query with no `GRAPH`
clause matches only the default graph, which is empty in TriG output. Templates handle
this through the profile, which is also why the same template works against flattened
Turtle. Verified, not assumed: the same pattern returns 0 rows unscoped and 13 scoped.

**Some IRIs denote records about a thing, not the thing.** A LeanIX fact sheet is a
document about an application. Treating it as the application merges a register entry
with its subject and inflates every count downstream.

**A negative test must name its own graph scope.** `FILTER NOT EXISTS`, `MINUS` and
`EXISTS` written inside a `GRAPH` block are evaluated in that one graph, so "missing from
this graph" is reported as "missing from the dataset" — and each model contributes its own
graph, so that is always more than one. Write `FILTER NOT EXISTS { GRAPH ?any { … } }`, or
better `OPTIONAL { GRAPH ?any { … } BIND(1 AS ?f) } FILTER(!BOUND(?f))`, which is also the
cheaper form on a large candidate set. Measured: 3 findings reported where 1 existed, on a
fixture with two partitions.

Full detail, including why each term is what it is:
[references/graph-shape.md](references/graph-shape.md).

## Answering

**Show the query.** Every answer includes the SPARQL that produced it. This is the
point of the whole approach: a wrong answer should be visibly a wrong query rather
than a plausible paragraph.

**Attach provenance.** Run `core/provenance` on the main elements and name the source
model, converter and timestamp. An architecture answer without a source is a claim;
with one it is evidence, and the reader can go and look.

**Report empty results as findings, not failures.** "No capability is unrealised" and
"no capability is modelled" are different statements. Check with `core/inventory-summary`
before asserting either.

**Distinguish the graph from the enterprise.** Everything here comes from models
somebody drew. Absence in the graph means absence in the models. Say "nothing in the
models connects X to Y", never "X does not connect to Y".

**Never invent** an IRI, label, count or relationship that did not appear in a result
set. If a query returns nothing, say so and show the query.

A count sitting exactly on the row limit is a floor, not a total. Report "at least".

## When a template is refused

A refusal is an answer. It means the dataset cannot support that question, and it
names why and what to try instead:

```
Template 'core/dependents-direct' cannot run against profile 'linked-archi-default':
  - capability 'direct_rel_triples' is False but this template needs True
Try instead: core/dependents-qualified, core/neighbours-qualified
```

Do not work around it by setting the capability true or by hand-writing the query the
template would have produced. Either would return nothing while looking correct —
which is exactly what the refusal prevented. Use the alternative, or report that the
question needs a differently-converted dataset.

Diagnosing something else: [references/troubleshooting.md](references/troubleshooting.md).
Writing a new template: [references/template-contract.md](references/template-contract.md).
Endpoint permissions and query cost: [references/safety.md](references/safety.md).
Driving this owner from another program: [references/machine-contract.md](references/machine-contract.md).
