# How acquisition behaves

The detail behind the commands in `SKILL.md`: what an HTTPS fetch checks, how an
extensionless URL is negotiated, what a Git fetch does and refuses, how the cache is reused
offline, and what a source manifest records. Load it when a fetch is refused, negotiation
returns the wrong serialisation, or you need to explain a manifest.

## HTTPS fetch

The token value is read from the environment and is never written to the manifest.
A credentialled request may redirect only within the same host. The fetch otherwise
requires HTTPS, validates each redirect, rejects non-public addresses by default,
requests an uncompressed response, enforces `--timeout-ms` and `--max-bytes`, parses
the selected RDF format, checks the digest, and atomically promotes it into the
content-addressed cache.

## Content negotiation

The URL suffix selects the format. An extensionless URL is content-negotiated instead,
and you can still pin the serialisation:

```bash
python3 scripts/la-source url https://meta.linked.archi/archimate3/shapes   # negotiated
python3 scripts/la-source url https://models.example.org/export \
  --format trig --sha256 68b8...
```

**Negotiation asks for Turtle first, one type at a time.** A published namespace IRI is
where a single broad `Accept` header goes wrong. Some publishers answer **404, not 406**,
for a serialisation they do not hold, so a broader request fails where a narrower one
succeeds — on `meta.linked.archi`, the full RDF list returns 404 for ten of twelve assets
including every shape set and taxonomy, while `text/turtle` alone returns all twelve. Others
ignore `q` weights entirely and answer with whatever they prefer. So the first attempt names
one type, and only the fallback lists everything.

Two consequences worth knowing:

- **`--format` is a request, not just an interpretation.** It now sets the `Accept` header,
  and no other serialisation is accepted in its place — answering a Turtle request with
  JSON-LD and parsing it as Turtle produces "syntax error at line 1" rather than "this
  publisher does not offer Turtle".
- **A URL with an RDF extension is asked for once, broadly.** `/dataset.trig` already says
  what it is, and must not be requested as Turtle: a quad dataset offered as both would come
  back flattened, losing graph identity.

A `200` carrying `text/html` is refused rather than parsed, and the refusal names the
`Accept` that produced it.

## Git fetch

The implementation creates a temporary bare repository and fetches one revision. It
never checks out a worktree. Local/file/ext/git protocols, hooks, recursive submodules,
LFS smudge filters, symlinks, submodule entries and LFS pointer files are refused.
Only explicitly selected regular blobs are parsed and promoted to the cache.

## Cache and offline reuse

The default cache is `~/.cache/linked-archi/sources`; override it with
`LINKED_ARCHI_SOURCE_CACHE` or `--cache-dir`.

```bash
python3 scripts/la-source url https://models.example.org/architecture.trig \
  --sha256 68b8... --offline

python3 scripts/la-source git https://git.example.org/models.git \
  --ref FULL_COMMIT --path dist/architecture.trig --offline
```

Offline mode performs no HTTP, Git or MCP operation and returns only an exact verified
cache hit. Offline Git and GitLab MCP requests require a full commit. Cache files are
named by SHA-256 and re-hashed before reuse; partial downloads and failed validations
never become targets.

## The source manifest

Every ready result points to a JSON manifest containing:

- requested and resolved source identities, with URL credentials/query removed;
- the full resolved Git commit where applicable;
- selected repository paths and MCP server identity where applicable;
- each artifact's format, byte size, SHA-256, parsed quad count and immutable path;
- acquisition time and warnings about mutable or unpinned inputs.

A manifest records acquisition provenance. The RDF's own provenance graph records
model conversion provenance. Keep both: one cannot substitute for the other.
