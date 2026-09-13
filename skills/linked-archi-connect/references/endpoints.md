# Endpoints

```bash
export LINKED_ARCHI_SPARQL_TOKEN=...   # only if authentication is needed
python3 scripts/la-connect connect --endpoint https://graph.example.org/architecture/query
```

HTTPS only, and the URL is validated before any request is made. `--data` and `--endpoint`
cannot be combined: two datasets would make the recorded dataset identity wrong, and a result
citing the wrong source is worse than an error because it looks reproducible.

## Credentials

The token is read from the **environment**, never from an argument, so it stays out of shell
history and out the process list — which is readable by other processes on the host.

The endpoint recorded in a result envelope is stripped of userinfo and query string, so a
saved result can be shared without leaking a credential embedded in the URL.

## Enforce read-only on the server too

This package refuses updates and federation client-side: every query is linted by the query
owner before any backend sees it, and connect fails closed if that companion is missing. But
**a client-side check is a guard, not a boundary**. Anything that can reach the endpoint
directly bypasses it.

So on the server side:

- use a **read-only credential**, or a query-only endpoint;
- set a **server-side timeout** and a result cap, because `--timeout-ms` is the client's
  patience rather than the server's limit;
- expect the client to send `POST` with form encoding. Some servers reject that and answer
  HTTP 400; the refusal text is passed through rather than being reinterpreted here.

## What differs from a local file

| | Local files | Endpoint |
|---|---|---|
| `--timeout-ms` | ignored: bounded by the file | the request deadline |
| `--lenient` | relaxes RDF parsing | nothing to parse; no effect |
| Named graphs | reported from what loaded | reported as unknown (`null`) |
| Completeness check | compares against a manifest and sibling files | not available: there is no manifest to read |
| Dataset identity | the filename | the endpoint, stripped of credentials |

The named-graph difference matters: with a local file, connect can tell you the load produced
no graphs. Against an endpoint it cannot, so a graph-scoped profile that does not fit the
store fails silently. `la-profile verify --endpoint ...` is the check that catches it.
