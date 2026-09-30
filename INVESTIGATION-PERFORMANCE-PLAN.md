# Agent-visible investigation performance plan

Status: in progress. This plan measures and improves APM investigations, not the upload platform.
`graph/` below means the ArchiSurance graph checkout at
`../../../linked.archi usecase/use-case-repo-group/archisurance/graph/` relative to this repo.

## Objective

Reduce elapsed time and model tokens for a **complete, evidence-backed architecture answer**,
without weakening profile checks, refusal rules, review barriers, provenance or answer quality.
`linked-archi-analyse` continues to frame the question, orchestrate and interpret;
`linked-archi-query` alone executes read-only queries. The benchmark must not become a new
automatic investigation command or a second query executor (PROPOSAL D23).

## Existing baseline

- The ArchiSurance graph's `out/e2e/demo-final` snapshot completed native-source checks, five
  conversions, validation, merge, enrichment, six answer contracts and profile verification in
  that order. `scripts/e2e.py verify` rechecked its receipt on 2026-09-30 without conversion.
- `graph/out/e2e/apm-benchmark-2026-09-30.json` records five measured runs and one warmup of
  the current APM checkout against that snapshot. Correctness and evidence-equivalence checks pass.
- Median orientation time was 985 ms in two calls versus 484 ms batched. A selected catalogue
  printed 1,490 rather than 45,862 bytes, but took 149 rather than 143 ms. Lookup preview
  printed 2,124 rather than 9,216 bytes, but took 471 rather than 478 ms. These are CLI
  timings and stdout bytes, **not model tokens or complete investigation latency**.
- The benchmark's `analyse_plan` case prints the full plan as JSON (14,309 bytes); the skill's
  recommended `-o plan.json` route does not. Neither figure measures what an agent actually read.
- `graph/scripts/run_skills.py` verifies a plan, resolver candidates and one source-grounded
  21-row answer. It does not execute and judge every dependency in the six-step plan.

The snapshot and benchmark reports are ignored local artifacts. A future run must record their
hashes and a fresh report path; it must not silently substitute APM's small bundled fixtures or
reconvert native sources for each skills trial. If source inputs or converter identity change,
build a **new** ordered E2E snapshot before benchmarking it.

## First observed agent baseline

The first complete current-APM cross-notation trial is retained locally at
`graph/out/e2e/apm-agent-trial/`. Its `trace.json` anchors the raw Codex JSONL, frozen prompt,
snapshot, profile, APM skills-tree digest, final answer and 10 executed query envelopes. The
agent used `linked-archi-analyse` for planning and bundling and `linked-archi-query` for graph
execution. No conversion was repeated. An independent projection of the process answer matched
all 21 source-grounded rows as an exact multiset; the answer cites its saved envelopes and
qualifies partial coverage and the truncated identity audit.

| One successful run, not a paired result | Observed value |
|---|---:|
| Question-to-final-answer wall time | 218,867 ms |
| Completed shell tool calls | 17 |
| Aggregated command output reported in Codex JSONL | 130,078 bytes |
| Saved run artifacts, excluding harness files and final answer | 552,906 bytes |
| Codex `turn.completed` input tokens, including cached input | 713,189 |
| Cached input tokens, a subset of input | 663,552 |
| Output tokens | 5,684 |

These are **measured client telemetry for this one run**, not account balance or a token saving.
The agent grouped most owner invocations with file reads or scripts in one shell call, so the
JSONL exposes combined output but not per-invocation stdout/stderr or timings. The collector
therefore marks those commands `unclassified`, leaves per-call and first-evidence times null,
and does not pretend to allocate their bytes or model tokens to a stage. The raw JSONL and
saved envelopes remain available for manual audit, but should be disclosure-reviewed before
sharing. `graph/scripts/collect_investigation_trace.py` only summarizes an already-run agent;
it neither launches one nor executes a query.

The first visible detour was routing: the question named ArchiMate, Backstage, LeanIX and BPMN
but matched no phrase trigger. The agent read the pattern index and reran planning with
`--mode cross-notation`; one attempted orientation batch also failed before recovery. A separate
narrow-lookup pilot selected `core/resolve-model` for element records and did not answer that
scenario; it is diagnostic, not a successful benchmark sample. None of these observations
establishes a measured per-stage or stable cross-version token reduction.

After the routing change, `graph/out/e2e/apm-benchmark-routing-2026-09-30.json` passes the
existing evidence-equivalence checks against the same snapshot. It is a CLI benchmark, **not**
a post-change agent trial. The collector expects Codex `--json` events, the answer path, the
frozen prompt, and run metadata containing `started_at`, `finished_at`, `elapsed_ms`,
`exit_code`, `client`, `model`, `reasoning_effort` and a non-secret `settings` object. It records
missing usage as `unmeasured`; combined shell output is never falsely split by owner.

## Measurement contract

Use the same snapshot checksum, profile fingerprint, question, model/version,
reasoning setting, tool permissions, query bounds and resource limits for each paired comparison.
Record the different APM revision and skills-tree digest for each variant.
Use fresh agent sessions and separate output directories; alternate baseline and candidate order.
Start with at least five successful runs per variant and report every sample, median and spread.
Do not pool a changed dataset, profile, prompt or runtime into the same comparison.

Record separately:

1. **Answer quality:** source-grounded expected bindings, graph facts versus inference and
   unknowns, cited executed envelopes, refusal/ambiguity handling, no unsupported absence claim.
2. **Agent-visible context:** bytes of tool responses and file excerpts actually delivered to
   the model, full artifact bytes written but not read, number of tool calls, and selected
   pattern/reference files. Do not count saved envelopes as prompt content unless read.
3. **Actual token usage:** input, output and cached-input tokens from client/provider telemetry,
   when available. If telemetry is unavailable, report `unmeasured`; never estimate account
   usage from bytes or present an estimate as a measured token saving.
4. **Time:** question-to-final-answer wall time, time to first useful evidence, agent/tool
   time, and each owner CLI's wall, store-load and query time. Keep error, retry and refusal
   counts visible rather than dropping slow or unsuccessful trials.

The trace collector may observe an agent's commands and replies, but may not choose the next
query, fill unbound parameters or bypass analyse/query ownership. Review checkpoints remain
real: orientation before a population or absence claim; name-resolution evidence before an
IRI is bound; dependent steps only after earlier results are inspected.
The trace JSON stores command text, paths, digests and byte counts, not tool output bodies or
private reasoning. Commands may still reveal query text or source identifiers, so the trace,
full envelopes and answers stay in ignored per-run artifacts and need disclosure review before
sharing.

## Scenarios

1. **Cross-notation investigation:** use the existing ArchiSurance question in
   `graph/scripts/run_skills.py`. Require the selected pattern, reviewed orientation and
   resolution candidates, dependent evidence, provenance, a bundle and a final answer that
   distinguishes known links from unsupported identity or ownership claims. Compare the
   process portion to the source-grounded answer contract, not to a freshly generated answer.
2. **Narrow bounded lookup:** resolve a supplied name and answer one supported question with
   `linked-archi-query`. This catches unnecessary escalation to a full investigation.
3. **Refusal or ambiguity:** use a fixed unsupported or multiply resolved request whose
   correct outcome is a qualified refusal or clarification, not an empty factual answer.
   Establish its expected behavior from the published profile and source evidence before runs.

Each scenario has a frozen prompt, allowed dataset/profile, query budget, expected evidence
checks and allowed unknowns. Do not score natural-language answers by exact prose matching.
An independent reviewer must audit whether the answer's claims are supported by its saved
envelopes and source-grounded contracts.

## Work sequence

- [x] Preserve a completed converter-backed ArchiSurance snapshot and rerun the current CLI
  benchmark with correctness checks; leave converters and the platform out of repeated trials.
- [x] Write the three scenario contracts in `graph/tests/investigation-scenarios.json` and
  the observational trace schema in `schemas/investigation-trace-v1.schema.json`. Reuse the
  graph project's source-grounded answer checker; keep APM's owner CLIs as the only
  execution path. Trace collection and agent trials are separate from these contracts.
- [x] Capture a **current-APM agent baseline** with actual tool-visible context and provider
  token telemetry where available. Include final answers and executed evidence, not just plans.
- [ ] Attribute cost to orientation, plan/catalogue loading, name resolution, dependent queries,
  bundle/render and model reasoning. Separate process/startup overhead from store load and query
  execution. Record the first bottleneck before editing a skill.
- [x] Make one targeted APM change: when no phrase trigger matches, two distinct named
  notations now route to `cross-notation`. Other phrase triggers and explicit `--mode` retain
  priority. This removes the observed routing miss in deterministic tests; it is **not yet**
  an observed agent-time or token improvement. Later candidates include compact plan inspection,
  unnecessary repeated metadata reads, safe batching and expensive query structure.
- [ ] Repeat paired trials on the **same snapshot** and verify evidence/answer equivalence.
  Run `make check` and the existing CLI benchmark; add focused regression tests for any changed
  contract. Record rationale in `PROPOSAL.md` and user-facing changes in `CHANGELOG.md`.

## Completion criteria

An optimization is complete only when the full investigation scenario produces a defensible
answer in every accepted trial, all required queries remain attributable to the same verified
dataset/profile, no refusal or review barrier is weakened, and repeated measurements show a
stable improvement in the targeted time or **measured** token metric. Publish absolute values,
relative changes, sample variability and any regressions in other scenarios. If token telemetry
is absent or answer quality cannot be judged, label that goal unverified rather than declaring
the APM optimization finished.

Remote GitLab CI, platform deployment, converter changes and autonomous execution of an entire
analyse plan are out of scope for this performance work.
