---
name: linked-archi-connect
description: Attach an architecture knowledge graph and report honestly what loaded before anything is asked of it. Use when setting up, refreshing, merging or inspecting a Linked.Archi dataset, when a query fails because nothing is loaded, when choosing between local RDF files and a read-only SPARQL endpoint, or when results look thinner than expected and you need to know whether the graph is partial. Reports named-graph presence so the profile skill can verify graph-layout claims before querying.
license: Apache-2.0
compatibility: Local files need Python 3.11 or newer with pyoxigraph, and work fully offline. An endpoint needs only the standard library. Never both at once.
metadata:
  author: linked-archi
  version: "0.1.0"
  homepage: https://meta.linked.archi
allowed-tools: Read Bash(python3:*)
---

# Attaching a graph

## Invocation and companions

Owner command: `la-connect`. `datasets` and `connect` work alone; executing a query delegates read-only enforcement to `linked-archi-query`.

Resolve it once, with **one** call. `python3` is the only command these instructions need, which is also all this skill's `allowed-tools` grants:

```bash
python3 - <<'PY'
import os, pathlib, shutil
print("on PATH:", shutil.which("la-connect") or "no")
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
from `/` or `$HOME`.** If anything is unresolved, run `la-connect doctor`: it prints this
skill's root, its resolved command, its dependencies and every companion it can reach. If a
companion is genuinely missing, report it by name and stop.


**Examples below are skill-relative, but nothing requires you to `cd` here.** Resolve the
command once as above and keep it in a variable; then every example works from wherever the
project is, which is where the dataset and the output belong:

```bash
SKILL="${LINKED_ARCHI_SKILLS_DIR:-$HOME/.kiro/skills}/linked-archi-connect"   # resolved above
PROJECT="$PWD"                                  # wherever you actually are
```

Write derived artifacts relative to `$PROJECT`, never into the skill directory: a profile or
a result that lands beside an installed skill is lost on the next upgrade, and invisible to
the repository that needed it.

`python3 <script>` is deliberate: installing a skill does not put its owner CLI on `PATH`.
Companion paths assume the required skills are installed as siblings.

Two backends, one interface. Which you use is a deployment fact, not an architectural
one, so the templates and the method do not change between them.

```bash
# Local files. Several merge into one store, which is how a federated graph is
# assembled from per-model converter output.
python3 scripts/la-connect connect --data dist/bpmn.trig --data dist/archimate.trig

# A read-only SPARQL endpoint.
python3 scripts/la-connect connect --endpoint https://graph.example.org/architecture/query
```

Passing both is refused. Two datasets would make the recorded dataset identity wrong,
and a result citing the wrong source is worse than an error because it looks
reproducible.

## Report what loaded before answering anything

`connect` prints the quad count, the number of named graphs, and every warning it
found. Read three things from it:

- **Named graphs present.** No provenance graph means no evidence is available for
  any answer you go on to give.
- **Which notations contributed.** Follow up with `core/models`. If only one notation
  loaded, no cross-notation question can be answered, and you should say so before
  being asked.
- **Element counts.** Follow up with `core/inventory`. A count far below expectation
  is usually a partial export rather than a small enterprise.

A confident answer over a quarter of the graph is worse than an admission that the
graph is partial.

## Named graphs and profile verification

`python3 scripts/la-connect connect` reports whether named graphs loaded and warns when an input
format cannot preserve graph identity. It deliberately does not load profiles: profile
semantics belong to `linked-archi-profile`.

Run the owner check when a profile is available:

```bash
python3 ../linked-archi-profile/scripts/la-profile verify --profile linked-archi-default --data graph.trig
```

That command exits `1` when the dataset and profile disagree. A dataset with no named
graphs under a graph-scoping profile makes every scoped query return nothing; a dataset
with named graphs under a single-layout profile mixes semantic, view, and provenance
facts. Use TriG/N-Quads or select the profile that describes the actual layout.

## Formats, in one line

**Prefer TriG or N-Quads.** They keep named graphs; Turtle, N-Triples, RDF/XML and JSON-LD
collapse everything into the default graph, and from inside a query that is
indistinguishable from an empty dataset. The extension chooses the parser, so a TriG file
named `.ttl` loses its graphs silently.

Full table, and why the semantic/views/provenance split is worth the format choice:
[references/formats.md](references/formats.md).

## Loading costs time, and now says so

Local files are parsed on every invocation, and every owner CLI is a separate process. On a
large aggregate that parse takes seconds. `load_ms` reports it beside `elapsed_ms`, which
matters because `elapsed_ms` times only the query: a lookup reported in single-digit
milliseconds had cost seconds that appeared nowhere.

`$LINKED_ARCHI_STORE` and `--store` select where the store comes from — `memory` (default),
`cached`, `readonly`, `refresh`. **`cached` reuses an on-disk store: much faster to load and
slower to query**, so it is a large win for many cheap lookups and a loss for aggregation.
Measured both ways, with the settings and the invalidation rules:
[references/store-modes.md](references/store-modes.md).

If you have several questions, `la-query query batch` removes the repeated parse outright
rather than trading it for slower queries.

`describe()` names the mode and the cost on every attach, so a cache that is not working is
visible rather than assumed.

## Attach the graph; do not read around it

Everything downstream cites the dataset this skill reports. So when a question needs graph
evidence, attach a dataset and query it — do not grep the `.trig`, and do not load it with
another RDF library to peek. Those paths skip the read-only enforcement, the profile
resolution and the dataset identity that make an answer checkable.

Reading files is right for exactly one thing here: resolving an explicitly named local graph
path. If nothing can be attached, say so; `la-connect doctor` reports what is missing.

## Point it at a repository, not a file

When the user says "the graph is in `models/archi-graph`", pass the directory. It resolves
to the one file that directory canonically means, and reports which and why:

```bash
python3 scripts/la-connect connect --data models/archi-graph
```

A graph-carrying serialisation always wins: a directory holding both `merged-graph.trig`
and `merged-graph.ttl` resolves to the TriG, because that is the one that keeps the named
graphs every scoped query depends on. The commit and clean/dirty state of the chosen file
are reported with it.

If two graphs could have been meant, it **refuses** and lists them rather than guessing.
Name one — picking "the newest" is how an answer ends up citing last month's conversion
while looking reproducible.

## Is the dataset complete?

A merge is *supposed* to be complete, which is why a merge missing an entire source is so
dangerous: nothing looks wrong. So when the project declares its inputs in a manifest
(`sources-index.yaml`), connect reads it and says which declared sources are on disk but
not in what loaded:

```
warning: this dataset spans 5 notation(s), so it looks like the merged whole, but
1 source(s) declared in sources-index.yaml are on disk and not in it:
enterprise-leanix (leanix). A merge that silently dropped a source still looks
complete. Confirm with the query owner's core/models before answering anything
portfolio-wide.
```

Treat that as a stop signal for any estate-wide claim. It is a suspicion drawn from graph
naming, not a fact: `core/models` is the fact, and it is one query away. A source declared
but *absent from disk* is reported separately, because a graph that was never pulled is a
different problem from a merge that dropped one.

With no manifest, connect notes other RDF files sitting beside the dataset that were not
loaded. The same graph in another serialisation is not counted — that is one graph, not a
missing source.

## Finding the dataset

Do not guess a path. Ask the tool:

```bash
python3 scripts/la-connect datasets                  # candidates in the working directory
python3 scripts/la-connect datasets path/to/project  # or somewhere specific
```

It reports every RDF file it can actually load — the whole table above except the two
ambiguous suffixes — in the conventional places: build output, data directories, and
committed architecture. Each candidate comes with size, date, and whether the file carries
graph identity at all. Test data is excluded unless you pass `--include-fixtures`.

`.json` and `.xml` are loadable, as JSON-LD and RDF/XML, but they are also every
`package.json` and `pom.xml` in the tree, so a bare search skips them rather than burying
the real candidates. Ask for them by name when that is what you are looking for:

```bash
python3 scripts/la-connect datasets --extension json --extension xml
```

When nothing is found the output names the roots, directories, depth and extensions it
searched, and the flag that widens each one. Read that before concluding a repository has no
graph, and **widen the search with flags rather than a filesystem tool**:

```bash
python3 scripts/la-connect datasets --search-dir architecture/exports   # a named layout
python3 scripts/la-connect datasets --max-depth 5                       # deeper than the default 3
```

`--search-dir` is repeatable, relative to each root, and **replaces** the conventional
directory list — a caller naming a layout knows something the convention does not, and
walking nine other directories as well is slower for no gain. `.` is always included.
`--max-depth` defaults to 3 with a ceiling of 12; beyond that a search stops being a search.

If you already know the path, none of this is needed: pass it to `--data`, or set
`$LINKED_ARCHI_DATA`.

**It selects nothing.** The next command it prints carries a `<PATH>` placeholder, not the
first candidate. Ordering here is a weak signal — newest is not most correct — so the
choice of which graph is current belongs to whoever can judge currency.

Inside a git working tree it also anchors the search at the **repository root**, so
being in a subdirectory does not hide a graph two levels up, and reports each
candidate's commit, ref and whether it is clean. Prefer the **commit date** it shows
over any file date: after a fresh clone every mtime is the checkout time.

Two git states make an answer unreproducible, and both are flagged. **Uncommitted
changes** mean the file matches no version a reviewer can fetch. **Untracked** means it
exists only on this machine. Say so if you answer from either.

**This skill never fetches over the network except when querying an explicitly named SPARQL
endpoint.** A graph that is not on disk yet belongs to `linked-archi-source`, which verifies
it and hands back a target this skill accepts unchanged — see
[references/source-routing.md](references/source-routing.md).

Neither skill silently chooses a candidate. Local discovery therefore follows these rules:

1. If exactly one plausible candidate exists, name it to the user and proceed.
2. If several do, ask which. Do not pick the largest or the newest silently.
3. If none do, say the graph could not be found. Do not answer from the fixtures, and
   do not describe results you have not seen.

Once the answer is known, record it so nobody has to rediscover it. Either set the
environment variable, which every execution command then uses without `--data`:

```bash
export LINKED_ARCHI_DATA=dist/merged.trig
export LINKED_ARCHI_DATA=dist/bpmn.trig:dist/archimate.trig   # federated, like PATH
```

or have the project record it where a later session will read it — `.kiro/steering/`,
`AGENTS.md` or `CLAUDE.md`, depending on the client. The package's `USAGE.md` has a
copy-pasteable snippet (repository material); the short version is:

```
The architecture graph is at dist/merged.trig, converted at
https://example.org/la/. Use profiles/acme.yaml.
```

`$LINKED_ARCHI_DATA` is the only thing that resolves a dataset implicitly, and only
because a human or a project set it deliberately. A path in it that does not exist is
an error, not a silent fallback to searching.

## Endpoints

```bash
export LINKED_ARCHI_SPARQL_TOKEN=...   # only if authentication is needed
python3 scripts/la-connect connect --endpoint https://graph.example.org/architecture/query
```

HTTPS only, and the token comes from the environment rather than an argument so it stays out
of shell history and the process list. Two things differ from a local file and matter:
connect **cannot** tell you an endpoint has no named graphs, and the client-side read-only
check is a guard rather than a boundary — use a read-only credential and a server-side cap.
Detail, including the full local-versus-endpoint table:
[references/endpoints.md](references/endpoints.md).

## When it does not work

Symptom-to-cause table, what to do when nothing can be attached, and how a dataset gets
rebuilt or fetched: [references/troubleshooting.md](references/troubleshooting.md).

Driving this owner from another program:
[references/machine-contract.md](references/machine-contract.md). `la-connect _machine` is
machine-facing rather than private, and it is how `linked-archi-query` and
`linked-archi-profile` reach transport.
