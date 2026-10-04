# Installable SPARQL-endpoint downstream APM

This is a second, installable APM example. Unlike the
[fixed-graph example](../fixed-graph-downstream/README.md), it does **not** ship
an RDF file. A consumer supplies the URL of an existing SPARQL query endpoint
at runtime. The package selects only `linked-archi-analyse`,
`linked-archi-query`, `linked-archi-profile`, and `linked-archi-connect` from
the `v0.8.0` Linked.Archi APM, plus its own `sparql-endpoint-demo`
skill. There is no source acquisition, conversion, SHACL validation, or
project-owned query catalogue.

The child profile under `skills/sparql-endpoint-demo/assets/profiles/` is inside
the installed skill so that it travels with it. It **inherits** the default
Linked.Archi converter vocabulary and named-graph layout; it is a starter,
not proof that any particular endpoint has those characteristics. Edit and
verify it for a real store. No endpoint URL or credential is committed here.

## Install from a separate project

With APM, Python 3.11+, and PyYAML installed, start **outside this package
checkout**. Set `EXAMPLE` to the absolute path of this directory. The upstream
`v0.8.0` tag must be published before resolving this dependency:

```bash
mkdir my-endpoint-project && cd my-endpoint-project
EXAMPLE=/absolute/path/to/linked-archi-apm/examples/sparql-endpoint-downstream
apm install "$EXAMPLE" --target agent-skills

SKILLS=.agents/skills
DEMO="$SKILLS/sparql-endpoint-demo"
PROFILE="$DEMO/assets/profiles/endpoint.yaml"
```

In the consumer project, set the endpoint explicitly. The address below is
**only a placeholder**; replace it with a real HTTPS SPARQL query URL you
control. Do not embed tokens in the URL or commit a real private URL to the
example. If the endpoint needs authentication, arrange for the consumer's
secret manager to populate `LINKED_ARCHI_SPARQL_TOKEN` with a **read-only**
bearer token in the process environment. It is not an APM setting.

```bash
export ARCHITECTURE_SPARQL_ENDPOINT='https://your-host.example/sparql'

python3 "$SKILLS/linked-archi-connect/scripts/la-connect" connect \
  --endpoint "$ARCHITECTURE_SPARQL_ENDPOINT"
python3 "$SKILLS/linked-archi-profile/scripts/la-profile" verify \
  --profile "$PROFILE" --endpoint "$ARCHITECTURE_SPARQL_ENDPOINT"
```

Do not proceed if either command fails. `connect` validates and describes the
endpoint configuration; it does **not** contact the service or prove it is
reachable. `verify` sends read-only probes and checks the profile's claims
against the actual endpoint. Review warnings as well as errors;
the endpoint cannot provide a local manifest/completeness check, and named
graph presence is not inferred by `connect` alone. If the inherited default
graph layout, roles, or capabilities do not match, edit the child profile for
the actual store and re-run verification. Do not treat zero result rows as
absence until dataset scope and profile have been checked.

After verification reports zero errors, ask one bounded question through the
query owner. This template is bundled in `v0.8.0`; `--catalog` is **not** needed:

```bash
python3 "$SKILLS/linked-archi-query/scripts/la-query" catalog show \
  core/inventory-summary --profile "$PROFILE"
python3 "$SKILLS/linked-archi-query/scripts/la-query" query run \
  core/inventory-summary --profile "$PROFILE" \
  --endpoint "$ARCHITECTURE_SPARQL_ENDPOINT"
```

Rows, counts, and warnings depend on the real endpoint. This example makes no
claim that the placeholder URL is live or that a real endpoint serves
Linked.Archi RDF. For a multi-step question, use `linked-archi-analyse` for
question investigation and orchestration; its execution steps go through
`linked-archi-query`. The installed `sparql-endpoint-demo/SKILL.md` carries
those choices to the agent. The root `AGENTS.md` applies only while editing
this checkout and is not installed as a skill.

## Adapt it

- Point `ARCHITECTURE_SPARQL_ENDPOINT` at a query-only HTTPS endpoint with
  SPARQL JSON responses and form-encoded `POST` support. Give it a read-only
  credential and server-side timeout/result limits: client-side read-only
  checks are safeguards, not access control.
- Adapt `skills/sparql-endpoint-demo/assets/profiles/endpoint.yaml` to the
  actual store's vocabulary, named-graph layout, capabilities, and notation
  population. Verify again after an endpoint or dataset refresh.
- Keep the endpoint URL and token out of the package. Pass `--endpoint` on
  every graph-backed call; the commands do not automatically read
  `ARCHITECTURE_SPARQL_ENDPOINT`.
- Use distinct endpoint paths for distinct tenants or snapshots: result citations
  omit URL query parameters. Record a separate dataset revision when you need
  reproducible answers, because the remote graph can change independently.
- Publish this downstream package at a reviewed Git ref and install it from
  a separate project. Commit that consumer project's APM lockfile. The
  `v0.8.0` pin supports this example as written once that tag is published.

See the parent package's [profile adaptation guide](../../ADAPTING.md),
[usage guide](../../USAGE.md), and
[endpoint reference](../../skills/linked-archi-connect/references/endpoints.md)
for profile and endpoint semantics.
