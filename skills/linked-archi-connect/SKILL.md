---
name: linked-archi-connect
description: Find and attach a Linked.Archi architecture graph - local RDF files or a read-only SPARQL endpoint - and report what actually loaded before anything is asked of it. Use when setting up, refreshing, merging or inspecting a dataset, when a query fails because nothing is loaded, or when results look thinner than expected and the graph may be partial.
license: Apache-2.0
compatibility: Local files need Python 3.11 or newer with pyoxigraph, and work fully offline. An endpoint needs only the standard library. Never both at once.
metadata:
  author: linked-archi
  version: "0.11.0"
  homepage: https://meta.linked.archi
allowed-tools: Read Bash(python3:*)
---

# Attaching a graph

## Invocation and companions

Owner command: `la-connect`. `datasets` and `connect` work alone; executing a query
delegates read-only enforcement to `linked-archi-query`.

Installing a skill does not put its command on `PATH`. Examples are skill-relative
(`python3 scripts/la-connect`); substitute the path the harness gave you, or
`$LINKED_ARCHI_SKILLS_DIR/linked-archi-connect` (authoritative when set), or the install
root (`~/.kiro/skills`, `~/.claude/skills`). Companions resolve the same way: the
environment root, then the sibling directory beside this skill, then `PATH`.

If the path is unknown, one bounded call lists every installed owner:

```bash
python3 -c 'import glob, os; root = os.path.expanduser(os.environ.get("LINKED_ARCHI_SKILLS_DIR") or "~/.kiro/skills"); print("root: " + root, *sorted(glob.glob(root + "/linked-archi-*/scripts/la-*")), sep="\n")'
```

**Never search the filesystem for skills, scripts, templates or profiles, and never search
from `/` or `$HOME`.** If anything is unresolved, run `la-connect doctor`: it prints this
skill's root, its resolved command, its dependencies and every companion it can reach. If a
companion is genuinely missing, report it by name and stop.

Run from the project and write derived artifacts there, never into the skill directory.

Two backends, one interface; which you use is a deployment fact, so templates and method
do not change between them:

```bash
# Local files. Several merge into one store - how a federated graph is assembled.
python3 scripts/la-connect connect --data dist/bpmn.trig --data dist/archimate.trig

# A read-only SPARQL endpoint.
python3 scripts/la-connect connect --endpoint https://graph.example.org/architecture/query
```

Passing both is refused: two datasets would make the recorded dataset identity wrong.

## Report what loaded before answering anything

`connect` prints the quad count, the number of named graphs, and every warning. Read:

- **Named graphs present.** No provenance graph means no evidence for any answer.
- **Which notations contributed.** Follow up with `core/models`. If only one notation
  loaded, no cross-notation question can be answered - say so before being asked.
- **Element counts.** Follow up with `core/inventory`. A count far below expectation is
  usually a partial export rather than a small enterprise.

A confident answer over a quarter of the graph is worse than an admission that it is partial.
If connect warns that sources declared in `sources-index.yaml` are on disk but not loaded,
treat that as a stop signal for any estate-wide claim and confirm with `core/models`.

## Named graphs and profile verification

`connect` reports whether named graphs loaded and warns when a format cannot preserve
graph identity. It does not load profiles; profile semantics belong to `linked-archi-profile`:

```bash
python3 ../linked-archi-profile/scripts/la-profile verify --profile linked-archi-default --data graph.trig
```

It exits `1` when the dataset and profile disagree. Use TriG/N-Quads, or the profile that
describes the actual layout.

**Prefer TriG or N-Quads.** Turtle, N-Triples, RDF/XML and JSON-LD collapse everything into
the default graph, which from inside a query is indistinguishable from an empty dataset.
The extension chooses the parser, so a TriG file named `.ttl` loses its graphs silently.
Full table: [references/formats.md](references/formats.md).

## Loading cost

Local files are parsed by every owner process; read `load_ms` beside `elapsed_ms`, which
times only the query. For several questions, `la-query query batch` removes the repeated
parse. `--store cached` (or `$LINKED_ARCHI_STORE`) loads much faster but queries slower -
a win for many cheap lookups, a loss for aggregation. Measurements and invalidation:
[references/store-modes.md](references/store-modes.md).

## Attach the graph; do not read around it

When a question needs graph evidence, attach a dataset and query it - do not grep the
`.trig`, and do not load it with another RDF library to peek. Those paths skip read-only
enforcement, profile resolution and the dataset identity that make an answer checkable.
Reading files is right only for resolving an explicitly named local graph path. If nothing
can be attached, say so; `la-connect doctor` reports what is missing.

## Finding the dataset

If you know the path, pass it to `--data` (a directory resolves to the one graph it
canonically holds, and refuses if two could be meant), or set `$LINKED_ARCHI_DATA`.
Otherwise ask the tool; do not guess a path:

```bash
python3 scripts/la-connect datasets                  # candidates in the working directory
python3 scripts/la-connect datasets path/to/project  # or somewhere specific
```

It lists loadable RDF with size, date, commit and clean/dirty state, excluding test data,
and it **selects nothing**. Widen a search with its flags (`--search-dir`, `--max-depth`,
`--extension`), never with a filesystem tool. Then:

1. If exactly one plausible candidate exists, name it to the user and proceed.
2. If several do, ask which. Do not pick the largest or the newest silently.
3. If none do, say the graph could not be found. Do not answer from the fixtures, and
   do not describe results you have not seen.

Say so if you answer from a file with uncommitted changes or one that is untracked: no
reviewer can fetch that version. Record the answer so nobody rediscovers it:

```bash
export LINKED_ARCHI_DATA=dist/merged.trig
export LINKED_ARCHI_DATA=dist/bpmn.trig:dist/archimate.trig   # federated, like PATH
```

or in the project's `AGENTS.md`, `CLAUDE.md` or `.kiro/steering/` (snippet in the
package's `USAGE.md`). A path in `$LINKED_ARCHI_DATA` that does not exist is an error, not
a fallback to searching. How discovery searches, directory resolution, the completeness
warning and git states: [references/discovery.md](references/discovery.md).

**This skill never fetches over the network except to query an explicitly named SPARQL
endpoint.** A graph not yet on disk belongs to `linked-archi-source`, which verifies it and
hands back a target this skill accepts unchanged:
[references/source-routing.md](references/source-routing.md).

## Endpoints

```bash
export LINKED_ARCHI_SPARQL_TOKEN=...   # only if authentication is needed
python3 scripts/la-connect connect --endpoint https://graph.example.org/architecture/query
```

HTTPS only; the token comes from the environment, never an argument. Connect **cannot** tell
you an endpoint has no named graphs, and the client-side read-only check is a guard rather
than a boundary - use a read-only credential and a server-side cap.
Detail: [references/endpoints.md](references/endpoints.md).

## When it does not work

Symptom-to-cause table and how a dataset gets rebuilt or fetched:
[references/troubleshooting.md](references/troubleshooting.md). Driving this owner from
another program: [references/machine-contract.md](references/machine-contract.md);
`la-connect _machine` is machine-facing rather than private, and it is how
`linked-archi-query` and `linked-archi-profile` reach transport.
