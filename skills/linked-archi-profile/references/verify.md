# Recommending and verifying a profile

The detail behind the `recommend`, `verify` and `--emit-fix` instructions in `SKILL.md`:
what a profile claims, what each finding means, and why a finding is an error, a warning or
advice. Load it when a verification reports something you need to interpret.

## What a profile claims

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

## What `recommend` and `verify` report

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

## The layout every bundled profile describes

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
