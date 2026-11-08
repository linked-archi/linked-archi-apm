---
name: linked-archi-profile
description: Choose, verify and derive the graph profile that tells the other Linked.Archi skills what a dataset calls things. Use before querying an unfamiliar architecture graph, when adapting to a custom ontology or taxonomy, when a query returns nothing and the vocabulary may be wrong rather than the question, or when onboarding converter output whose flags you did not choose.
license: Apache-2.0
compatibility: Needs Python 3.11 or newer and PyYAML. Verifying a dataset delegates transport to linked-archi-connect and read-only enforcement to linked-archi-query; local files additionally need pyoxigraph. Install those companion skills for verification. Works offline with local files.
metadata:
  author: linked-archi
  version: "0.11.0"
  homepage: https://meta.linked.archi
allowed-tools: Read Bash(python3:*)
---

# The graph profile

## Invocation and companions

Owner command: `la-profile`. `list`, `show`, `resolve`, `recommend` and `derive` work
alone; `verify` needs `linked-archi-connect` and `linked-archi-query`.

Installing a skill does not put its command on `PATH`. Examples are skill-relative
(`python3 scripts/la-profile`); substitute the path the harness gave you, or
`$LINKED_ARCHI_SKILLS_DIR/linked-archi-profile` (authoritative when set), or the install
root (`~/.kiro/skills`, `~/.claude/skills`). Companions resolve the same way: the
environment root, then the sibling directory beside this skill, then `PATH`.

If the path is unknown, one bounded call lists every installed owner:

```bash
python3 -c 'import glob, os; root = os.path.expanduser(os.environ.get("LINKED_ARCHI_SKILLS_DIR") or "~/.kiro/skills"); print("root: " + root, *sorted(glob.glob(root + "/linked-archi-*/scripts/la-*")), sep="\n")'
```

**Never search the filesystem for skills, scripts, templates or profiles, and never search
from `/` or `$HOME`.** If anything is unresolved, run `la-profile doctor`: it prints this
skill's root, its resolved command, its dependencies and every companion it can reach. If a
companion is genuinely missing, report it by name and stop.

Write derived profiles in the project, never into the skill directory: one beside an
installed skill is lost on the next upgrade.

A profile records what one dataset calls things, so no template guesses: `roles` (what a
term is called here), `graphs` (the named-graph layout), `capabilities` (what the dataset
*contains*, not what the vocabulary permits) and `navigation` (how "belongs to that model"
is expressed). A template that needs something absent is **refused with a reason** instead
of returning an empty result that reads as "none exist". Every field:
[references/profile-reference.md](references/profile-reference.md).

## Do this first

```bash
python3 scripts/la-profile list
python3 scripts/la-profile recommend --data path/to/graph.trig     # which one fits?
python3 scripts/la-profile show --profile linked-archi-default
python3 scripts/la-profile verify --profile linked-archi-default --data path/to/graph.trig
```

`recommend` measures the dataset and names a starting profile with its evidence; use it
instead of trying profiles and keeping whichever warns least. It reads through the published
Linked.Archi vocabulary, so a custom ontology looks emptier than it is - `derive` is the
answer for that. It recommends and never applies.

**`verify` is the step that matters.** Read its output before trusting any answer built on
the profile; it exits `1` on any error, so it can gate a pipeline.

- **error** - a claim is false: a capability the data contradicts, named graphs claimed
  against a dataset with none, or a required graph role matching no graph. Templates
  depending on it run and return nothing while looking correct. Fix the profile or the
  dataset; do not proceed.
- **warning** - bound but not seen: a role this dataset never uses, an optional graph role
  absent, a declared metamodel whose manifest or assets are not attached
  (`metamodel.manifest`, `metamodel.assets`), or a declared notation the data holds no
  model in (`notations.present`). Usually harmless; sometimes the first sign that a model
  did not load.
- **ok** - confirmed against the data.

A missing graph role is reported as **absent** or **present but partitioned**; they need
opposite fixes. Record `present: false` for a declared notation the dataset does not hold,
so its templates are refused with a reason instead of returning empty tables. What to do
about each finding: [references/verify.md](references/verify.md).

When a capability claim is contradicted, the report ends with the command that fixes it:

```bash
python3 scripts/la-profile verify --profile linked-archi-default --data graph.trig \
    --emit-fix > my-graph.yaml
```

It writes a child profile that `extends` the parent and overrides only observed capability
drift. Read it before using it: a capability that turned out **false** may mean a model
failed to load rather than that the dataset lacks it.

A verification without errors is recorded (under `$LINKED_ARCHI_STATE_DIR` or
`~/.cache/linked-archi/verified`); the query owner adds a caveat to every result for a pair
never checked. It is advice, never a gate, and it does not prove a dataset unchanged.

## Choosing a bundled profile

| Profile | For |
|---|---|
| `linked-archi-default` | Converter output at default flags, direct triples included. Start here. |
| `linked-archi-qualified` | Output without the direct triples: an older converter, or `--no-emit-direct-rel-triples`. |
| `linked-archi-direct` | Deprecated: the same as `linked-archi-default`. |
| `linked-archi-merged` | A store with an authored reconciliation graph. |
| `examples/curated-store` | Enriched store: identity, direct triples, a loaded SHACL report. |
| `examples/flattened-turtle` | A dataset with no named graphs, as Turtle output collapses to. |
| `examples/cloudplatform` | Worked example of a custom metamodel. |

Output from a converter that predates the current layout (model resources in
`graph/model`, membership as `arch:inModel`) needs `graphs.roles.model: graph/semantic`,
`graphs.descendants: []` and `navigation.model_membership.mode: same-graph-colocation`;
`verify` refuses it otherwise. If none fits, derive one. **Do not edit a bundled profile in
place** - it describes other people's datasets too.

## Adapting to a custom ontology or taxonomy

Usually **no new templates**: core templates resolve roles rather than terms, so binding
your vocabulary in a profile is enough. Derive rather than author, from the converter's type
mapping or a published `arch:Metamodel` manifest:

```bash
SKILL="${LINKED_ARCHI_SKILLS_DIR:-$HOME/.kiro/skills}/linked-archi-profile"   # as resolved
PROJECT="$PWD"                                                               # where output belongs
python3 "$SKILL/scripts/la-profile" derive acme \
    --type-mapping "$PROJECT/config/type-mapping-acme.yml" \
    --base-iri https://acme.example/la/ -o "$PROJECT/profiles/acme.yaml"
```

The result is a **draft** of what those artifacts declare, not what a dataset contains, so
it always ends with `verify`. Both sources, what is left to you, and taxonomies:
[references/deriving.md](references/deriving.md).

To edit by hand, copy the closest bundled profile and use `extends`, so your file states
only the differences:

```yaml
extends: linked-archi-default.yaml
profile: acme
version: 1
roles:
  owner: acme:responsibleTeam
capabilities:
  concept_owner: true
```

`extends` resolves beside your file first, then in the bundled `profiles/`. Mappings merge
key by key; scalars and **lists replace outright**. Every role and capability:
[references/profile-reference.md](references/profile-reference.md).

## When a query returns nothing

Suspect the profile before rewriting the query. In order:

1. `python3 ../linked-archi-connect/scripts/la-connect connect` - what graph shape and inputs actually loaded?
2. `python3 scripts/la-profile verify` - does that evidence match the profile's claims?
3. `python3 ../linked-archi-query/scripts/la-query query run core/element-detail --set FOCUS_IRI=...` - is the predicate
   spelled the way the profile thinks?

An empty result and an empty graph look identical from inside a query; only the
orientation templates tell them apart.

## What not to do

- Do not bind a role to a term you have not seen in the data. A wrong binding produces
  confident empty results.
- Do not set a capability true to make a refusal go away. The refusal is the finding.
- Do not describe a dataset you have not verified against. If you cannot reach it, say the
  profile is unverified and stop.

Driving this owner from another program:
[references/machine-contract.md](references/machine-contract.md). `la-profile _machine
resolve` returns the merged snapshot, which is how the query owner reads a profile without
parsing YAML itself.
