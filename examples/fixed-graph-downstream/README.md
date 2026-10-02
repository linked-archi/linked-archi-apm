# Installable fixed-graph downstream APM

This directory is an **APM package** that another project can install. Its
`apm.yml` includes the project-owned `fixed-graph-demo` skill and pins only four
Linked.Archi companion skills from `v0.7.0`: analyse, query, profile, and connect.
The package ships a tiny synthetic TriG graph, its matching custom profile, and
an optional project query inside the demo skill's `assets/` directory. No source
acquisition, conversion, or SHACL validation is part of this fixed-graph example.

The profile extends Linked.Archi's bundled default, but binds `label` to
`demo:displayName`, `owner` to `demo:accountableTeam`, and a project role to
`bs:Ownership`. These are claims about the included graph, not blanket overrides
for other datasets.

## Install from a separate project

With APM, Python 3.11+, PyYAML, and pyoxigraph installed, start **outside this
package checkout**. Set `EXAMPLE` to the absolute path of this directory:

```bash
mkdir my-architecture-project && cd my-architecture-project
EXAMPLE=/absolute/path/to/linked-archi-apm/examples/fixed-graph-downstream
apm install "$EXAMPLE" --target agent-skills

SKILLS=.agents/skills
DEMO="$SKILLS/fixed-graph-demo"
PROFILE="$DEMO/assets/profiles/demo.yaml"
DATA="$DEMO/assets/data/architecture.trig"

python3 "$SKILLS/linked-archi-profile/scripts/la-profile" verify \
  --profile "$PROFILE" --data "$DATA"
python3 "$SKILLS/linked-archi-query/scripts/la-query" query run core/inventory-summary \
  --profile "$PROFILE" --data "$DATA"
python3 "$SKILLS/linked-archi-query/scripts/la-query" query run core/resolve-element \
  --profile "$PROFILE" --data "$DATA" --set 'TERM=Payments Service'
```

The installation deploys **five** skills: the one from this package plus the
four selected upstream companions. The generated consumer `apm.yml` records the
local package dependency; its lockfile records the resolved upstream pin. In a real
downstream repository, publish or pin this package at a reviewed Git ref rather
than keeping an absolute path to this checkout.

Verification should report zero errors before results are interpreted. The
inventory should find one Backstage model and the name lookup should resolve
`Payments Service` to its element IRI. The tiny graph leaves many inherited
roles unused, so warnings are expected; its published metamodel is not attached,
so schema-level claims need more data. Neither APM nor the custom skill silently
sets a global graph or profile. Pass both explicitly, as above. The installed
`fixed-graph-demo/SKILL.md` carries these choices for the agent; the root
`AGENTS.md` applies only while editing this example checkout.

For a multi-step question such as “What owns Payments Service, and what evidence
supports that?”, use `linked-archi-analyse` to frame and orchestrate steps, and
`linked-archi-query` to execute them. The graph contains an authored qualified
`bs:Ownership` relationship and a `demo:accountableTeam` assertion, but no live
ownership directory or real source lineage. A result about this synthetic graph
is not a conclusion about an enterprise.

## Optional catalogued query

The packaged `assets/queries/catalog.json` registers `demo/accountability` with
typed parameters, profile requirements, a row limit, and a result caveat. Its
`accountability.rq` reports a team only when the project-specific accountability
edge and the qualified ownership relationship agree. If the direct owner
capability is unavailable, `core/neighbours-qualified` can inspect the
qualified relationship alone, but cannot establish that agreement.

**The pinned `v0.7.0` query skill does not support external catalogues.** This
project query is ready for a later Linked.Archi ref with explicit `--catalog`
support. To exercise it **now, inside this source checkout**, use the current
development query owner and the packaged asset paths:

```bash
DEMO=skills/fixed-graph-demo
QUERY=../../skills/linked-archi-query/scripts/la-query
python3 "$QUERY" catalog show demo/accountability \
  --catalog "$DEMO/assets/queries/catalog.json" \
  --profile "$DEMO/assets/profiles/demo.yaml"
python3 "$QUERY" query run demo/accountability \
  --catalog "$DEMO/assets/queries/catalog.json" \
  --profile "$DEMO/assets/profiles/demo.yaml" \
  --data "$DEMO/assets/data/architecture.trig" \
  --set FOCUS_IRI=https://example.org/fixed-graph/catalog/element/payments-service
```

After changing the `apm.yml` ref to a release with that support and reinstalling
the downstream package, set `DEMO=.agents/skills/fixed-graph-demo` and
`QUERY=.agents/skills/linked-archi-query/scripts/la-query` in the **consumer
project** and run the same two commands. The catalogue is never auto-discovered;
the user/agent must pass its installed path on each call. The query file is
resolved relative to the catalogue, and bundled template names remain intact.

## Adapt it

- Replace `skills/fixed-graph-demo/assets/data/architecture.trig` with a published
  graph or a fixed read-only endpoint. For an endpoint, pass `--endpoint URL`
  instead of `--data`, and verify the profile against that endpoint. Do not put
  credentials or a large private dataset in an APM package.
- Edit `skills/fixed-graph-demo/assets/profiles/demo.yaml` to match the actual
  vocabulary, graph layout, capabilities, and notation population. Re-verify
  after every graph or profile change.
- Edit `skills/fixed-graph-demo/SKILL.md` to name the installed graph/profile
  and state limitations. Keep connect and profile selected: query execution
  needs both. Add source only for acquisition, and validate only for SHACL work.
- Pin and publish the downstream package, then install it from a separate
  consumer project and commit that project's APM lockfile for reproducible CI.

See the parent package's `ADAPTING.md` and `USAGE.md` for profile semantics and
owner-command details. A profile changes graph interpretation; the separate,
explicit catalogue adds a named query.
