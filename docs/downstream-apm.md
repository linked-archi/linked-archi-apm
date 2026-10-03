# Build a downstream APM

Choose the [fixed-graph example](https://github.com/linked-archi/linked-archi-apm/tree/main/examples/fixed-graph-downstream)
when you publish RDF with the package. Choose the
[SPARQL-endpoint example](https://github.com/linked-archi/linked-archi-apm/tree/main/examples/sparql-endpoint-downstream)
when the graph is already served remotely. Both select the same four upstream
skills; only the fixed-graph example packages RDF and an optional custom query.

The [fixed-graph downstream example](https://github.com/linked-archi/linked-archi-apm/tree/main/examples/fixed-graph-downstream)
is an installable APM package, not a fork of the six skills. It combines a synthetic,
already-published TriG graph and a project-owned profile inside its own Agent Skill,
an APM dependency selecting four upstream skills, and project-owned query files. Its
`SKILL.md` tells an installed agent which graph and profile to use; each owner command
still receives those choices explicitly.

The graph, profile and query are under the skill because APM deploys the declared
`skills/fixed-graph-demo/` subtree. Root-level sibling asset folders would not travel
with this package into the consuming project.

| In the downstream package | Purpose |
|---|---|
| `apm.yml` | Includes `fixed-graph-demo` and selects `linked-archi-analyse`, `linked-archi-connect`, `linked-archi-profile` and `linked-archi-query` as dependencies. |
| `skills/fixed-graph-demo/SKILL.md` | Instructions that travel with the downstream package. |
| `skills/fixed-graph-demo/assets/data/architecture.trig` | The fixed graph; this example does not acquire or convert sources. |
| `skills/fixed-graph-demo/assets/profiles/demo.yaml` | A child of `linked-archi-default` that binds the graph's label and owner predicates. |
| `skills/fixed-graph-demo/assets/queries/` | An explicitly selected project query, separate from the upstream query skill. |

No `linked-archi-source` is needed when the graph has already been published. No
`linked-archi-validate` is needed unless the task includes SHACL validation. Query execution
does require connect and profile; analyse investigates and orchestrates but does not become
another executor. Verify the custom profile against the fixed graph before treating an empty
query result as absence. The small synthetic graph intentionally produces warnings for claims it
cannot cover, but its profile verification has no errors.

## The catalogue boundary

`--catalog` is **not** needed to compose a downstream APM, select skills, use a fixed graph,
or load a custom profile with bundled templates. It is needed only to register and run
the project's own named query through `linked-archi-query`.

The example's `apm.yml` pins the published `v0.7.0` four-skill baseline. That release does
**not** have `--catalog`; the project query requires this unreleased checkout or a later release
containing explicit catalogue overlays. Do not expect the pinned install to run it until a
supporting ref is published and the example's pin is updated.

With the current repository checkout, from `examples/fixed-graph-downstream/`, the new query
owner can inspect and run the project entry without editing its bundled `catalog.json`:

```bash
python3 ../../skills/linked-archi-query/scripts/la-query catalog show demo/accountability \
  --catalog skills/fixed-graph-demo/assets/queries/catalog.json \
  --profile skills/fixed-graph-demo/assets/profiles/demo.yaml
python3 ../../skills/linked-archi-query/scripts/la-query query run demo/accountability \
  --catalog skills/fixed-graph-demo/assets/queries/catalog.json \
  --profile skills/fixed-graph-demo/assets/profiles/demo.yaml \
  --data skills/fixed-graph-demo/assets/data/architecture.trig \
  --set FOCUS_IRI=https://example.org/fixed-graph/catalog/element/payments-service
```

The explicit catalogue path is a trust decision. It is never found automatically, cannot
replace bundled template names, and is resolved only within its own directory. External
templates still pass the query owner's profile gates and read-only checks and produce the same
evidence envelope. The consumer must test its own queries against its own graph; the bundled
fixture suite cannot prove their meaning. Keep endpoint credentials read-only as well.

A catalogue entry makes a query discoverable and executable by `linked-archi-query`; it does
**not** add an analysis pattern or make `linked-archi-analyse plan` choose that query. The
analyst can select it explicitly while investigating a question. See the
[query skill](skills/query.md#project-owned-catalogue-extensions) and
[profile adaptation guide](concepts/profile.md) for the two separate extension contracts.

## Endpoint variant

The endpoint example ships its own skill instructions and profile, but no TriG file,
catalogue or credentials. Its consumer supplies `--endpoint URL` instead of `--data`
on each connect, profile and query command. The URL is an explicit target, not an
environment fallback in the CLI. `LINKED_ARCHI_SPARQL_TOKEN` supplies an optional
Bearer token; credentials must have server-side read-only permissions.

`connect --endpoint` checks configuration and describes the adapter, but does **not**
contact the service. Run `la-profile verify --endpoint` against the actual graph
before treating an empty query result as absence. Use HTTPS, configure a server-side
timeout and result cap, and record an external dataset revision if reproducibility
matters: the service may change without the APM package changing. The endpoint
example uses bundled query templates and therefore needs no `--catalog` or later
release than its `v0.7.0` pin.
