---
name: fixed-graph-demo
description: Use the packaged, synthetic fixed architecture graph with its project-owned profile and optional accountability query. Use for demonstrating a downstream APM that selects Linked.Archi companion skills without acquiring or converting sources.
license: Apache-2.0
compatibility: Needs Python 3.11+, PyYAML, pyoxigraph, and sibling linked-archi-profile, linked-archi-connect, and linked-archi-query skills for local queries.
metadata:
  author: linked-archi
  version: "0.1.0"
allowed-tools: Read Bash(python3:*)
---

# Fixed graph, owned by this downstream package

The dataset is `assets/data/architecture.trig` relative to this skill directory.
Use `assets/profiles/demo.yaml` with it. The profile extends the installed
`linked-archi-profile` base and binds project-specific labels and ownership.
These assets travel with this skill when another APM project installs it.

Resolve this skill's installed directory from the harness-provided skill path.
The companion owner scripts are siblings under the same installed skills root:
`../linked-archi-profile/scripts/la-profile` and
`../linked-archi-query/scripts/la-query`. Do not search the machine for another
graph, profile, or executor. Verify the profile before interpreting results:

```bash
SKILL=/absolute/path/to/installed/fixed-graph-demo
python3 "$SKILL/../linked-archi-profile/scripts/la-profile" verify \
  --profile "$SKILL/assets/profiles/demo.yaml" \
  --data "$SKILL/assets/data/architecture.trig"
python3 "$SKILL/../linked-archi-query/scripts/la-query" query run core/resolve-element \
  --profile "$SKILL/assets/profiles/demo.yaml" \
  --data "$SKILL/assets/data/architecture.trig" --set 'TERM=Payments Service'
```

The graph is synthetic and intentionally small. It has one Backstage model and
an authored ownership statement; it does not establish live accountability,
complete coverage, real source lineage, or schema-level conclusions. Profile
verification should have zero errors, but warnings about unused inherited
roles and an unattached metamodel are expected.

For a multi-step question, invoke `linked-archi-analyse` to frame and
orchestrate it, and use `linked-archi-query` for read-only execution. This skill
does not execute SPARQL itself. `linked-archi-source` and
`linked-archi-validate` are deliberately absent.

`assets/queries/catalog.json` registers `demo/accountability`. The pinned
Linked.Archi `v0.8.0` dependency supports external catalogues; pass this
skill's absolute catalogue path with `--catalog` on each catalogue or query call.
