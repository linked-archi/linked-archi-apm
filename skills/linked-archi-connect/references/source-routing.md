# When the graph is not on disk yet

**This skill never fetches over the network** except when querying an explicitly named SPARQL
endpoint. Acquisition is a different problem with a different failure mode — unverified bytes
from an unpinned revision — so it has a different owner.

`linked-archi-source` verifies HTTPS documents, pinned Git revisions, or agent-mediated
GitLab MCP content, and returns immutable local paths:

```bash
python3 ../linked-archi-source/scripts/la-source git \
  https://git.example.org/architecture.git \
  --ref FULL_COMMIT --path dist/merged.trig

python3 scripts/la-connect connect \
  --data ~/.cache/linked-archi/sources/sha256/abc.../abc....trig
```

The `target` object source returns is **exactly** connect target version 1, so it can be
passed through unchanged. Merging manifest fields into it is rejected rather than ignored —
see the two machine contracts.

## Manual cloning is still valid

When a working tree is what you actually need:

```bash
git clone <url> /tmp/arch && python3 scripts/la-connect datasets /tmp/arch
```

That is a legitimate choice, not a workaround. What it does not give you is acquisition
provenance: no manifest, no digest, no pinned commit recorded against the bytes you queried.
For a reproducible answer, prefer `la-source`.

## Who decides what

| Decision | Owner |
|---|---|
| Whether these bytes are safe and reproducible to materialise | `linked-archi-source` |
| What those local bytes actually load, and whether graphs survived | `linked-archi-connect` |
| Whether the vocabulary in them matches a profile | `linked-archi-profile` |
| Whether a query may run against them | `linked-archi-query` |

Two kinds of provenance come out of this, and they answer different questions. The source
manifest records **acquisition** — requested and resolved identity, commit, size, SHA-256,
format, parsed quad count, when. `core/provenance` reads **conversion** provenance from
inside the RDF: which model, which converter, which run. Keep both; neither substitutes for
the other.
