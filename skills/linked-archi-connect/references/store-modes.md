# Where the store comes from: `memory`, `cached`, `readonly`, `refresh`

Every owner CLI here is a separate process, so a session that asks ten questions of one
dataset parses it ten times. On a large aggregate that parse takes seconds, and until
`load_ms` existed nothing reported it — a query whose `elapsed_ms` read single-digit
milliseconds had cost seconds that appeared nowhere.

`memory` is the default and remains the right answer for most work. The rest of this page
is about when it is not, and the measurements that decide it.

Figures below are ratios rather than absolutes. They were taken on one large
multi-notation TriG aggregate, and the absolutes are properties of that dataset, not of
this code. Expect the same shape at a different scale: the crossover point moves, the
direction does not.

## The modes

| Mode | Loads by | Load cost | Query cost | Disk |
|---|---|---|---|---|
| `memory` | parsing the files | full parse | fastest | none |
| `cached` | reusing an on-disk store, building one if absent | ~1/100th of a parse | slower | several times the RDF |
| `readonly` | reusing an on-disk store, never building | well under a parse | slower | reuses |
| `refresh` | discarding the cached store and rebuilding | parse + write | slower | rewrites |

```bash
la-connect connect --data dist/merged.trig --store cached   # per command
export LINKED_ARCHI_STORE=cached                            # for a session
```

`--store` also exists on `la-query`, the machine contract carries it as a `store` field
on the target, and in process it is `store=` on `open_adapter`. The flag wins over the
environment; an absent flag defers to it rather than overriding it with a default. An
unknown mode is refused rather than defaulted, so a typo fails loudly instead of looking
like a setting that had no effect.

## Why the fast-loading mode is not the default

Because it is not the fast mode. Queries against a RocksDB-backed store do not run at
in-memory speed, and for analytical work the query penalty is larger than the load
saving:

```
an aggregating template          load          query        total wall
  memory                    full parse     baseline         baseline
  cached                    ~1/100th       roughly 3x       ~1.6x worse
```

For a cheap lookup the same cache is transformative — a selective query went from seconds
to tens of milliseconds, close to two orders of magnitude. So the trade turns on how much
work the query does, which nothing can know before running it. That is a choice to hand a
caller, not a default to apply on their behalf.

**Choose `cached` when** you will run many cheap, selective queries against one large
dataset that is not changing: resolving names to IRIs, walking neighbours, fetching one
element's detail.

**Stay on `memory` when** queries aggregate, count, sort or join across the whole graph,
or when you are running one query and leaving.

## What invalidates a cached store

The key covers the ordered file list with each file's size and mtime, the `lenient` flag,
the pyoxigraph version, and a revision of the load semantics. Refreshing a dataset moves
size or mtime, so the key moves and the next call rebuilds without being asked.

Stat data rather than content hashes, deliberately: hashing the whole dataset to decide
whether to skip parsing it would give back most of what the cache saves. The cost of that
choice is that two spellings of one dataset get two stores — a fetched copy and a
repository checkout of the same files produce two stores of near-identical size — which is
what the byte budget below is for.

The profile is not in the key. A profile binds vocabulary when a query is rendered and
never changes which quads exist.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `LINKED_ARCHI_STORE` | `memory` | mode |
| `LINKED_ARCHI_STORE_CACHE` | `$XDG_CACHE_HOME/linked-archi/stores` | where stores live |
| `LINKED_ARCHI_STORE_KEEP` | `3` | how many stores to retain |
| `LINKED_ARCHI_STORE_MAX_BYTES` | `2147483648` | byte budget across all stores |

Both bounds apply, because neither alone is honest: a count is what a human reasons about
but says nothing about disk, and store size tracks dataset size over orders of magnitude.
The store just built is never evicted, so a budget smaller than one store is simply not
achievable rather than a rebuild loop. Setting both to `0` disables eviction; it does not
empty the cache.

## Reading what happened

`describe()` names the origin and the cost on every attach, because a cache that is
silently inactive is worse than no cache:

```
local store: 1 file(s), 1234 quad(s), 4 named graph(s)
  /path/to/dist/merged.trig
  store: reused cached store (read-write) in 8 ms (mode cached)
  cache: /home/me/.cache/linked-archi/stores/1893b7d471e0b45a
```

`load_ms` rides the raw-result contract into the query owner's envelope, beside
`elapsed_ms`. It is optional on the wire: an older `linked-archi-connect` does not send
it, and results are not refused over a timing field.

## What this does not fix

The per-process parse is irreducible. Three routes to skip it while keeping in-memory
query speed were measured, and all three are slower than parsing the TriG again:

```
parse TriG -> memory                             1.0x   <- the fastest route
open cached store read-only, copy into memory    ~2.5x
dump to N-Quads, parse into memory               ~1.25x
```

pyoxigraph's TriG reader moves hundreds of thousands of quads per second, quick enough
that no serialisation beats it. So the way to stop paying the parse repeatedly is to stop
starting a process per query.

That is **`la-query query batch`**, and it is the fix that works — one invocation, one
parse, several queries. Measured on the same dataset with a handful of queries, running
them as separate commands took roughly **2.8x** the wall clock of one batch, and paid the
load once per command instead of once in total. Identical rows, `query_id` and `truncated`
either way.

Only the first result in a batch carries `load_ms`; the rest report zero, because there
was no load to attribute to them and stamping each one would make a single parse read as
several.

A resident process holding the store would go further still, and is not implemented.
