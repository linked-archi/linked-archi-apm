# Build a downstream APM

The [fixed-graph downstream example](https://github.com/linked-archi/linked-archi-apm/tree/main/examples/fixed-graph-downstream)
is an installable APM package, not a fork of the six skills. It combines a synthetic,
already-published TriG graph and a project-owned profile inside its own Agent Skill,
an APM dependency selecting four upstream skills, and project-owned query files. Its
`SKILL.md` tells an installed agent which graph and profile to use; each owner command
still receives those choices explicitly.

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

The example's `apm.yml` pins the published `v0.7.0` four-skill baseline. That release does
**not** have `--catalog`; the project query requires this unreleased checkout or a later release
containing explicit catalogue overlays. Do not expect the pinned install to run it until the
example's ref is updated at release time.

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
