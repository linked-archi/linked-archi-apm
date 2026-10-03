---
name: sparql-endpoint-demo
description: Use a consumer-supplied SPARQL query endpoint with a verified Linked.Archi profile and selected companion skills. Use for a downstream APM that queries an already-published architecture graph without packaging RDF or acquiring sources.
license: Apache-2.0
compatibility: Needs Python 3.11+, PyYAML, and sibling linked-archi-connect, linked-archi-profile, and linked-archi-query skills. Endpoint transport uses the standard library; pyoxigraph is not needed.
metadata:
  author: linked-archi
  version: "0.1.0"
allowed-tools: Read Bash(python3:*)
---

# Consumer-supplied SPARQL endpoint

## Invocation and companions

This downstream skill has no executable owner command. Use the installed
`la-connect`, `la-profile`, and `la-query` companion scripts for their respective
operations; `linked-archi-analyse` owns investigation and orchestration. Resolve
this skill's directory from the harness-provided path first, then an explicitly
configured `LINKED_ARCHI_SKILLS_DIR`, then the consumer project's `.agents/skills`
when it used the documented `agent-skills` target. Never search the filesystem
for a skill, script, profile, or endpoint. If a companion is unresolved, run its
`doctor` command from the known installed skills root and stop if it remains missing.

This skill packages no graph, endpoint URL, or credentials. The consumer chooses a
query-only HTTPS SPARQL endpoint and supplies it as
`ARCHITECTURE_SPARQL_ENDPOINT`. Pass that URL explicitly as `--endpoint` to each
graph-backed owner command. Never substitute `--data`, a fixture, or a guessed
endpoint. Ask for the endpoint if it has not been supplied.

The starter profile is `assets/profiles/endpoint.yaml` relative to this skill.
It inherits the Linked.Archi converter-default graph layout and vocabulary,
**not** facts observed on a live store. An endpoint may use a different layout
or vocabulary. Verify the profile against the actual endpoint; if it does not
fit, adapt the child profile and re-verify before interpreting query results.

The companion owner scripts are sibling skills in the same installed root.
With `SKILL` set to this skill's absolute installed path and the endpoint URL
already supplied by the consumer:

```bash
python3 "$SKILL/../linked-archi-connect/scripts/la-connect" connect \
  --endpoint "$ARCHITECTURE_SPARQL_ENDPOINT"
python3 "$SKILL/../linked-archi-profile/scripts/la-profile" verify \
  --profile "$SKILL/assets/profiles/endpoint.yaml" \
  --endpoint "$ARCHITECTURE_SPARQL_ENDPOINT"
```

Only after verification has zero errors, use `linked-archi-query` for bounded,
read-only execution, always passing the same endpoint and profile:

```bash
python3 "$SKILL/../linked-archi-query/scripts/la-query" query run \
  core/inventory-summary --profile "$SKILL/assets/profiles/endpoint.yaml" \
  --endpoint "$ARCHITECTURE_SPARQL_ENDPOINT"
```

Review verification warnings as limits on interpretation. For multi-step
questions, `linked-archi-analyse` investigates and orchestrates; it does not
execute SPARQL instead of `linked-archi-query`.

If authentication is needed, the existing transport reads a bearer token from
`LINKED_ARCHI_SPARQL_TOKEN`. Supply it through the consumer's secret manager,
not this package, command arguments, or URL userinfo. The credential and the
server endpoint must be read-only, with server-side timeout and result limits;
client-side query lint is not a security boundary. Never claim connection,
profile conformance, completeness, or absence without results from the selected
endpoint. Endpoint citations omit URL query parameters, so do not distinguish
tenants or snapshots by query parameters alone; record the dataset revision
separately. `linked-archi-source` and `linked-archi-validate` are not selected.
