# Finding, resolving and checking a dataset

The detail behind the dataset rules `SKILL.md` summarises: how `datasets` searches, how a
directory resolves to one graph, how connect notices a merge that dropped a source, and why
each rule is there. Load it when discovery finds nothing, finds several candidates, or warns
about the dataset's completeness or git state.

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
[source-routing.md](source-routing.md).

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
