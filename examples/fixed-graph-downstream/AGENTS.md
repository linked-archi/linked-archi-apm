# Architecture evidence in this package checkout

- The installable skill is `skills/fixed-graph-demo/`; its `SKILL.md` carries graph and profile instructions into consumer projects. This checkout's `AGENTS.md` does not travel with an APM install.
- The fixed dataset is `skills/fixed-graph-demo/assets/data/architecture.trig`. Use `skills/fixed-graph-demo/assets/profiles/demo.yaml` and verify it against that dataset before graph-backed claims.
- Use `linked-archi-analyse` for multi-step investigation and `linked-archi-query` for read-only execution. Always pass the fixed profile and dataset, or set `LINKED_ARCHI_DATA` to that dataset and still pass the profile.
- `linked-archi-source` and `linked-archi-validate` are not selected. Do not invent source-acquisition or SHACL-validation results.
- `skills/fixed-graph-demo/assets/queries/catalog.json` is optional. The pinned `v0.7.0` query skill cannot load it; use `--catalog` only with a later supporting ref or the current development checkout.
