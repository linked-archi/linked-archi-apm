# When a fetch does not go as expected

What to do when a fetch is refused, negotiation returns the wrong serialisation, an offline
request misses the cache, or you need to say what a manifest records. It adds to the rules in
`SKILL.md` and does not repeat them.

## HTTPS refusals

Besides the checks `SKILL.md` lists, a fetch is refused after more than five redirects, and
for a compressed response. A refusal is final for those inputs: change what was asked (host
decision, limits, digest), never retry the same request hoping for another answer.

## Content negotiation

A URL with an RDF extension (`.trig`, `.ttl`, ...) is requested once, with the full weighted
`Accept`. Never re-request a quad dataset as Turtle: it would come back flattened, losing its
named graphs.

A failed negotiation does not mean the URL is wrong: some publishers answer 404, not 406, for a
serialisation they do not hold. Retry with `--format` naming one they publish. A `200` carrying
HTML, plain text or JSON is documentation, not RDF; the refusal names the `Accept` that
produced it. When neither the suffix nor the `Content-Type` decides the format, pass `--format`.

## Git refusals

`file`, `ext`, `git` and local protocols are refused. One revision is fetched into a temporary
bare repository, with hooks, submodule recursion and LFS smudge disabled. A `--path` naming a
directory, symlink, submodule entry or LFS pointer is refused: ask for the exported RDF file.

## Offline cache misses

```bash
python3 scripts/la-source url https://models.example.org/architecture.trig \
  --sha256 68b8... --offline
python3 scripts/la-source git https://git.example.org/models.git \
  --ref FULL_COMMIT --path dist/architecture.trig --offline
```

A miss means that exact artifact was never fetched with these inputs: fetch it once online.
Cache files are named by SHA-256 and re-hashed before reuse; partial downloads and failed
validations never become targets.

## The source manifest

Every ready result points to a JSON manifest containing:

- requested and resolved source identities, with URL credentials/query removed;
- the full resolved Git commit where applicable;
- selected repository paths and MCP server identity where applicable;
- each artifact's format, byte size, SHA-256, parsed quad count and immutable path;
- acquisition time and warnings about mutable or unpinned inputs.
