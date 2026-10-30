# Answering a question

One question, start to finish, driven by hand with `la-query`. Four queries, then a fifth that
turns the answer into evidence.

This is the path to read first. [Conversational analysis](walkthrough.md) covers the same ground
with `la-analyse` planning the steps for you; the difference is who chooses the templates, not what
the templates do. Doing it by hand once makes the planned version legible.

Everything below was run against `fixtures/base.trig`, which ships with the package. Output is
copied from those runs.

**The question.** *What does Order Service relate to, and can I trust the answer?*

## Step 0 — verify the profile against this dataset

A [profile](concepts/profile.md) is a set of claims about the data. Until something checks those
claims against the file in front of you, nobody has.

```console
$ python3 scripts/la-profile verify --profile linked-archi-default --data fixtures/base.trig
local store: 1 file(s), 3471 quad(s), 17 named graph(s)
  store: parsed into memory in 8 ms (mode memory)
warn roles.subclass_of                  bound to http://www.w3.org/2000/01/rdf-schema#subClassOf but unused in this dataset
warn roles.unqualified_form             bound to https://meta.linked.archi/core#unqualifiedForm but unused in this dataset
warn notations.present                  declared by the profile with no model conforming to them in this dataset: plantuml. Questions about them can only ever come back empty. Recording notations.<name>.present false turns that empty answer into a refusal that says which dataset to ask instead.
76 check(s): 0 error(s), 17 warning(s), 59 confirmed (--all to show)
```

Zero errors, so the profile fits. Two of the confirmed claims (`--all` shows them) matter further
down: `direct_rel_triples`, and `rdf_reifies` as `partial`. This dataset has the direct triples the
converters write by default, each with its RDF 1.2 bridge, on every relationship whose class
publishes an unqualified predicate - BPMN's sequence flows have neither.

The `roles.unqualified_form`, `roles.subclass_of` and `roles.narrower` warnings say
something duller: those are schema-level predicates, and no ontology or taxonomy is attached to this
dataset. `examples/with-vocabulary` is the profile for when they are.

!!! warning "Skipping this step is not neutral"
    Without it every later result carries `profile 'linked-archi-default' has not been verified
    against this dataset`. That caveat is load-bearing: a profile that no longer fits fails
    silently, returning nothing from a scoped query, or rows that mean something else. Verifying
    is what removes it from the footers below.

## Step 1 — orient

```console
$ python3 scripts/la-query query run core/inventory-summary \
    --profile linked-archi-default --data fixtures/base.trig
metamodel	models	graphs	concepts
https://meta.linked.archi/archimate3/metamodel#ArchiMate3.2	1	1	41
https://meta.linked.archi/leanix/metamodel#LeanIXv4	1	1	15
https://meta.linked.archi/backstage/metamodel#BackstageCatalog	1	1	13
https://meta.linked.archi/bpmn/metamodel#BPMN2	1	1	10
https://meta.linked.archi/c4/metamodel#C4Model	1	1	5
#
# 5 row(s)
# core/inventory-summary | query 07119971d2fa | dataset base.trig | profile linked-archi-default v3 | 2026-10-30T08:47:21.128577+00:00 | 5 row(s)
```

Five notations, 84 concepts. This establishes the loaded population, not that every export
is complete. Before an absence claim, also check scope, predicates, relationship direction
and query truncation.

Reuse inspected orientation only when the dataset and profile are known unchanged. Refresh
it when either changes and before absence claims; filenames or verification markers alone
do not establish freshness. The two orientation queries can share one batch.

## Step 2 — resolve the name

The question said *Order Service*. That is a label, and labels are not identifiers.

```console
$ python3 scripts/la-query query run core/resolve-element \
    --profile linked-archi-default --data fixtures/base.trig \
    --set TERM="Order Service"
rank	matched	value	element	type	g_semantic
1 exact	1 name	Order Service	https://example.org/la/backstage/commerce-catalog/element/component/default/order-service	https://meta.linked.archi/backstage/onto#Component	…/commerce-catalog/graph/semantic
#
# 1 row(s)
# core/resolve-element | query a04276f83284 | dataset base.trig | profile linked-archi-default v3 | 2026-10-30T08:47:21.564147+00:00 | 1 row(s)
```

One exact match, on the name, in the **Backstage** graph — a `bs:Component`. That last part is the
reason this step exists. The same fixture also holds an ArchiMate model with an `Order Management`
element in it, and a hand-built IRI would have queried whichever namespace the author guessed.

`?rank` and `?matched` are how much of the value matched and which of name, alias or native id
matched it. When several candidates come back and the choice changes the answer, ask rather than
taking the top row.

!!! danger "Never construct an IRI from a label"
    The minted form depends on notation, model id and element id. Guessing it produces a query that
    runs, returns nothing, and reads as absence.

## Step 3 — traverse

```console
$ python3 scripts/la-query query run core/neighbours-qualified \
    --profile linked-archi-default --data fixtures/base.trig \
    --set FOCUS_IRI="<https://example.org/la/backstage/commerce-catalog/element/component/default/order-service>"
direction	relationship	relationshipType	other	otherLabel
outgoing	…/relationship/providesAPI--component-default-order-service--api-default-orders-api	bs:APIProvision	…/element/api/default/orders-api	Orders REST API
outgoing	…/relationship/ownedBy--component-default-order-service--group-default-team-commerce	bs:Ownership	…/element/group/default/team-commerce	Commerce Team
outgoing	…/relationship/partOfSystem--component-default-order-service--system-default-commerce-platform	bs:SystemMembership	…/element/system/default/commerce-platform	Commerce Platform
#
# 3 row(s)
# core/neighbours-qualified (model question) | query 8de8cdefc60e | dataset base.trig | profile linked-archi-default v3 | 2026-10-30T08:47:22.008123+00:00 | 3 row(s)
```

Three relationships, all outgoing: it provides the Orders REST API, it is owned by Commerce Team,
and it belongs to the Commerce Platform system.

`core/neighbours-qualified` is the default traversal because it reads the qualified relationship
resource, which is the form every converter emits without being asked. `?direction` covers both
ways round in one query, so nothing is missed by only asking outgoing. On local data it is asked as
the core model question of the same name, reading the dataset as one graph; the footer says so.

## Step 4 — cite it

An answer without a source is an assertion. This is what makes it evidence.

```console
$ python3 scripts/la-query query run core/provenance \
    --profile linked-archi-default --data fixtures/base.trig \
    --set FOCUS_IRI="<https://example.org/la/backstage/commerce-catalog/element/component/default/order-service>"
model	source	generated	startedAt	agentName	agentVersion	title	creator
https://example.org/la/backstage/commerce-catalog	catalog-info.yaml	2026-10-30T09:32:11.388196+01:00	2026-10-30T09:32:11.320955+01:00	backstage2linkedarchi	1.3.0-SNAPSHOT	Commerce Platform Catalog	Commerce Team
#
# 1 row(s)
# core/provenance | query 3eb6f38cd3b2 | dataset base.trig | profile linked-archi-default v3 | 2026-10-30T08:47:22.436250+00:00 | 1 row(s)
```

The three relationships come from `catalog-info.yaml`, converted by `backstage2linkedarchi`
1.3.0-SNAPSHOT on 2026-10-30. A reader who disputes the answer now knows which file to open.

Note what provenance does **not** establish: that `catalog-info.yaml` is current, correct or
approved. A conversion timestamp is not an as-at date.

## What a refusal looks like mid-flow

Suppose the same model had been converted without the direct triples - by a converter older than
that default, or with `--no-emit-direct-rel-triples` - and Step 0 had fitted it to
`linked-archi-qualified`. Then Step 3 reaches for transitive dependents:

```console
$ python3 scripts/la-query query run core/dependents-direct \
    --profile linked-archi-qualified --data older.trig \
    --set FOCUS_IRI="<…/element/component/default/order-service>" \
    --set PREDICATE_PATH="<https://meta.linked.archi/backstage/onto#ownedBy>"
Template 'core/dependents-direct' cannot run against profile 'linked-archi-qualified':
  - capability 'direct_rel_triples' is False in profile 'linked-archi-qualified' but this template needs True
Try instead: core/dependents-qualified, core/neighbours-qualified (same question, different evidence).
This is a refusal, not an empty result: running it anyway would return no rows and read as 'nothing exists'.
```

Exit 1, and nothing ran. The gate is the `direct_rel_triples` capability, false in that profile
because the dataset has no direct `{source} {predicate} {target}` triple. Step 0 is what makes that
trustworthy: `verify` checked the claim against the data instead of taking it on trust. The template
needs a form the data does not have, so it is refused and its alternatives are named.

The investigation loses nothing — Step 3 answered the question through the qualified form. What it
gains is that nobody reported "nothing depends on Order Service" on the strength of an empty table.
On `fixtures/base.trig`, under the default profile, the same template runs.

## The answer

> Order Service (`bs:Component`, Backstage, Commerce Platform Catalog) has three modelled
> relationships, all outgoing: it provides the Orders REST API (`bs:APIProvision`), it is owned by
> Commerce Team (`bs:Ownership`), and it is part of the Commerce Platform system
> (`bs:SystemMembership`).
>
> Evidence: `core/neighbours-qualified`, query `8de8cdefc60e`, dataset `base.trig`, profile
> `linked-archi-default` v3, 3 rows. Source `catalog-info.yaml`, converted by
> `backstage2linkedarchi` 1.3.0-SNAPSHOT (`core/provenance`, query `3eb6f38cd3b2`).
>
> Not established: runtime dependency, criticality or failure propagation. These are design-time
> statements from a catalogue file. Incoming dependencies at depth were not retrieved.

Four queries, and every clause above traceable to a query hash. The closing
paragraph is not hedging; it is the part that keeps the answer honest when someone acts on it.

## Where to go next

- [Template catalogue](templates.md) — all forty-three, with what each does not prove.
- [Evidence and refusal](concepts/evidence.md) — why exit 1 is an answer.
- [Conversational analysis](walkthrough.md) — the same shape, planned by `la-analyse` from a
  question in natural language.
- [Related work](related-work.md) — how this compares to generating SPARQL and checking it after.
