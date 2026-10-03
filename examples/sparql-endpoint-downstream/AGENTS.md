# Endpoint evidence in this package checkout

- The installable skill is `skills/sparql-endpoint-demo/`; its `SKILL.md` travels into consumer projects. This root `AGENTS.md` does not.
- No graph or endpoint URL is packaged. The consumer supplies `ARCHITECTURE_SPARQL_ENDPOINT` and each owner command receives `--endpoint "$ARCHITECTURE_SPARQL_ENDPOINT"` explicitly.
- The child profile in `skills/sparql-endpoint-demo/assets/profiles/endpoint.yaml` is only a starter for endpoints serving Linked.Archi converter-default RDF. Verify it against the selected endpoint before interpreting results; do not assume any live endpoint conforms to it.
- Use `linked-archi-analyse` for multi-step investigation and `linked-archi-query` for read-only execution. `linked-archi-connect` owns transport and `linked-archi-profile` owns verification.
- No source acquisition, conversion, SHACL validation, graph snapshot, or custom query catalogue is part of this example.
