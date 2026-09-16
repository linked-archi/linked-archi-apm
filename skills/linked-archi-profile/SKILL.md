---
name: linked-archi-profile
description: Establish, verify and derive the graph profile that tells every other Linked.Archi skill what a dataset calls things. Use before querying an unfamiliar architecture graph, when adapting to a custom ontology or taxonomy, when a query returns nothing and you suspect the vocabulary rather than the question, or when onboarding converter output whose flags you did not choose. Derives a draft profile from a converter type-mapping file or a published arch:Metamodel manifest, then checks its claims against the real dataset and reports drift.
license: Apache-2.0
compatibility: Needs Python 3.11 or newer and PyYAML. Verifying a dataset delegates transport to linked-archi-connect and read-only enforcement to linked-archi-query; local files additionally need pyoxigraph. Install those companion skills for verification. Works offline with local files.
metadata:
  author: linked-archi
  version: "0.5.0"
  homepage: https://meta.linked.archi
allowed-tools: Read Bash(python3:*)
---

# The graph profile

## Invocation and companions

Owner command: `la-profile`. `list`, `show`, `resolve` and `derive` work alone; `verify` needs `linked-archi-connect` and `linked-archi-query`.

Resolve it once, with **one** call. `python3` is the only command these instructions need, which is also all this skill's `allowed-tools` grants:

```bash
python3 - <<'PY'
import os, pathlib, shutil
print("on PATH:", shutil.which("la-profile") or "no")
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
from `/` or `$HOME`.** If anything is unresolved, run `la-profile doctor`: it prints this
skill's root, its resolved command, its dependencies and every companion it can reach. If a
companion is genuinely missing, report it by name and stop.


**Examples below are skill-relative, but nothing requires you to `cd` here.** Resolve the
command once as above and keep it in a variable; then every example works from wherever the
project is, which is where the dataset and the output belong:

```bash
SKILL="${LINKED_ARCHI_SKILLS_DIR:-$HOME/.kiro/skills}/linked-archi-profile"   # resolved above
PROJECT="$PWD"                                  # wherever you actually are
```

Write derived artifacts relative to `$PROJECT`, never into the skill directory: a profile or
a result that lands beside an installed skill is lost on the next upgrade, and invisible to
the repository that needed it.

`python3 <script>` is deliberate: installing a skill does not put its owner CLI on `PATH`.
Companion paths assume the required skills are installed as siblings.

A profile records what one dataset calls things, so no template has to guess. It
answers four questions a query cannot answer for itself:

- **What is this called here?** `roles` binds a semantic role such as `label` to
  the term this dataset uses.
- **Where does it live?** `graphs` describes the named-graph layout, so a query can
  be scoped without knowing model IRIs in advance.
- **Is it actually present?** `capabilities` records what the dataset *contains*
  rather than what the vocabulary permits.
- **How do I get from one thing to another?** `navigation` states how a traversal
  every template needs is expressed here. Currently one entry,
  `navigation.model_membership`, which decides what "this element belongs to that
  model" means: graph co-location, or a bounded walk up an authored folder chain.

The third earns the whole abstraction. A template that needs something absent is
refused with a reason, instead of running and returning nothing — which reads as
"no such thing exists" and is the most expensive failure available here.

The fourth exists because membership was being re-invented per query. Templates now
write `{{MEMBERSHIP:element}}` and the profile decides the pattern, so a dataset whose
folder chain is complete gets the precise traversal without every template
hand-writing a folder path. The default is co-location because the folder chain is
not uniformly emitted — it is present for BPMN and stops short for C4. Details in
[references/profile-reference.md](references/profile-reference.md).

## Do this first

```bash
python3 scripts/la-profile list
python3 scripts/la-profile recommend --data path/to/graph.trig     # which one fits?
python3 scripts/la-profile show --profile linked-archi-default
python3 scripts/la-profile verify --profile linked-archi-default --data path/to/graph.trig
```

`recommend` measures the dataset and names a starting profile with the evidence for it —
named-graph count, which graph roles are present, qualified versus direct relationships, a
reconciliation or validation graph, whether the folder chain reaches a model. Use it
instead of trying profiles and reading whichever warns least, which rewards the most
permissive profile rather than the one that fits. It recommends and never applies: the
output ends with the `verify` command.

It reads the dataset through the **published Linked.Archi vocabulary**, because that is the
only vocabulary a recommendation can assume. A dataset on a custom ontology will look
emptier than it is; `derive` is the answer for that.

`verify` is the step that matters. A profile is a set of claims, and claims decay:
an ontology version moves, a converter flag changes, a model stops being exported.
Read the output before trusting any answer built on top of it.

- **error** — a claim is false. A template depending on it will run and return
  nothing while looking correct. Fix the profile or the dataset; do not proceed.
  Three things produce one: a capability claimed that the data contradicts, named
  graphs claimed against a dataset that has none, and a **required graph role that
  matches no graph** — see `graphs.required` in the profile reference. The last one
  means every scoped query is asking about a graph that is not there.
- **warning** — something bound but not seen. Either a role bound to a term this
  dataset never uses, or an *optional* graph role that is absent. Usually harmless;
  sometimes the first sign that a model did not load.
- **ok** — confirmed against the data.

When a graph role is missing, the finding distinguishes **absent** from **present but
partitioned**. A dataset that splits a role across descendant graphs
(`graph/semantic/{repo}/{path}`) cannot be matched by a suffix selector and looks
identical to one that lacks the role entirely — so the report says which it is, because
the two need opposite fixes.

**`verify` also reports what the data says it conforms to but has not been given.** Every
model declares `arch:modelConformsToMetamodel`, and each published `arch:Metamodel`
manifest names its own ontology, taxonomy and SHACL shapes — so nobody has to remember
which files to attach. Two findings, because they need different actions:

| | |
|---|---|
| `metamodel.manifest` | the data declares a metamodel whose manifest is not attached. The IRI dereferences: `la-source url <iri>`, then pair it with `la-connect`. Where the version is part of the IRI — ArchiMate, BPMN — a manifest for the wrong release reads as an absent one. C4 and Backstage are not versioned that way. |
| `metamodel.assets` | the manifest is attached and the assets it names are not. |

Worth reading before trusting any schema-level answer. A check that walks shapes to decide
whether a query's path is possible finds nothing for a notation whose shapes were never
attached, and "no constraint published" is indistinguishable from "no problem" unless
something says they were never loaded.

**`verify` also says which notations the dataset actually holds a model in**, reported as
`notations.present`. Declaring a notation says the profile speaks it, which is not the same
as the data having any of it — the default profile declares six, and most datasets hold
fewer. Templates for the rest run and return nothing, which reads as "there are none of
those".

Record the answer and that stops happening. A notation spec takes `present`:

```yaml
notations:
  bpmn:
    present: false      # this dataset holds no BPMN
```

`false` refuses every template written against that notation, with a refusal naming the
notation instead of an empty table implying absence. `partial` — present for some models,
absent for others — runs with a caveat. `true` changes nothing; the claim only ever removes
an answer.

Leaving it out means unknown, and nothing is refused on an unknown, so an existing profile
behaves exactly as it did. This is a warning rather than an error for the same reason: no
dataset is obliged to carry every notation a profile can read.

Exit code is `1` when any error is found, so this is safe to gate a pipeline on.

**Acting on drift is one command, not an editing exercise.** When a capability claim is
contradicted by the data, the report ends with the command that fixes it:

```bash
python3 scripts/la-profile verify --profile linked-archi-default --data graph.trig \
    --emit-fix > my-graph.yaml
```

That writes a child profile which `extends` the parent and overrides only the observed
corrections — the report goes to stderr so the redirect gives a usable file. Read it before
using it: a capability that turned out **true** means your converter ran with a flag the
parent does not assume, and one that turned out **false** may mean a model failed to load
rather than that the dataset lacks it.

Only capability drift is generated. An unused role is left alone, because nulling it would
refuse every template that requires it, and a missing named graph needs a different
`layout` rather than a key edit.

A verification that finds no errors is **recorded**, keyed by dataset identity, profile and
profile version, under `$LINKED_ARCHI_STATE_DIR` or `~/.cache/linked-archi/verified`. The
query owner reads that marker and adds a caveat to every result for a pair that was never
checked — because an unfitting profile fails silently, and an implied step gets skipped
under time pressure. It is advice, never a refusal: nothing is gated on it, and an
unwritable cache location does not fail verification.

## Choosing a bundled profile

| Profile | For |
|---|---|
| `linked-archi-default` | Converter output at default flags. Start here. |
| `linked-archi-direct` | Converter run with `--emit-direct-rel-triples`. |
| `linked-archi-merged` | A store with an authored reconciliation graph. |
| `examples/curated-store` | Enriched store: identity, direct triples, a loaded SHACL report. |
| `examples/flattened-turtle` | A dataset with no named graphs, as Turtle output collapses to. |
| `examples/cloudplatform` | Worked example of a custom metamodel. |

Every profile here describes the graph layout the converters emit **today**: model
resources in `graph/model`, a semantic graph partitioned per input, and membership as a
direct `arch:inModel` edge.

A dataset from a converter that predates that layout needs three keys overridden —
`graphs.roles.model: graph/semantic`, `graphs.descendants: []` and
`navigation.model_membership.mode: same-graph-colocation`. `verify` refuses it rather than
answering, and `recommend` says exactly that, because the failure otherwise is silent:
`core/models` reads a graph that is not there and returns no rows while everything appears
to work.

If none fits, derive one. Do not edit a bundled profile in place — a profile is a
description of a dataset, and editing the shared one to match yours breaks it for
everyone else's.

## Adapting to a custom ontology or taxonomy

Most of the time this needs **no new templates**: core templates resolve roles rather than
terms, so binding your vocabulary in a profile is enough.

**Derive rather than author.** The information already exists in the artifacts that produced
the graph — the converter's type mapping, or a published `arch:Metamodel` manifest:

```bash
python3 "$SKILL/scripts/la-profile" derive acme \
    --type-mapping "$PROJECT/config/type-mapping-acme.yml" \
    --base-iri https://acme.example/la/ -o "$PROJECT/profiles/acme.yaml"
```

What comes out is a **draft**: it states what those artifacts declare, not what a dataset
contains, so it always ends with `verify`. Optional roles and `direct_rel_triples` are never
guessed.

Both sources, what is deliberately left to you, taxonomies, and hand-editing with `extends`:
[references/deriving.md](references/deriving.md).

## Editing a profile by hand

Copy the closest bundled profile and use `extends`, so your file states only the
differences and inherits corrections to the base:

```yaml
extends: linked-archi-default.yaml
profile: acme
version: 1
roles:
  owner: acme:responsibleTeam
capabilities:
  concept_owner: true
```

`extends` resolves relative to your file first, then to the bundled `profiles/`
directory — so a profile kept beside your graph still inherits from the base.

Mappings merge key by key. Scalars and **lists replace outright**: a role bound to a
fallback chain is one decision, and appending to it from a child would silently
change which term `{{ROLE:x}}` resolves to.

For the field-by-field reference, including every role and capability and why each
is bound the way it is, read
[references/profile-reference.md](references/profile-reference.md).

## When a query returns nothing

Suspect the profile before rewriting the query. In order:

1. `python3 ../linked-archi-connect/scripts/la-connect connect` — what graph shape and inputs actually loaded?
2. `python3 scripts/la-profile verify` — does that evidence match the profile's claims?
3. `python3 ../linked-archi-query/scripts/la-query query run core/element-detail --set FOCUS_IRI=...` — is the predicate
   spelled the way the profile thinks?

An empty result and an empty graph look identical from inside a query. Only the
orientation templates tell them apart.

## What not to do

- Do not bind a role to a term you have not seen in the data. `verify` exists so you
  do not have to guess, and a wrong binding produces confident empty results.
- Do not set a capability true to make a refusal go away. The refusal is the finding.
- Do not describe a dataset you have not verified against. If you cannot reach it,
  say the profile is unverified and stop.

Driving this owner from another program:
[references/machine-contract.md](references/machine-contract.md). `la-profile _machine
resolve` returns the merged snapshot, which is how the query owner reads a profile without
parsing YAML itself.
