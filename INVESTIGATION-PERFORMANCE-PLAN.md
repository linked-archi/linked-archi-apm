# Agent-visible investigation performance plan

Status: D27 token objective verified; latency improvement and per-stage attribution remain open.
This plan measures and improves APM investigations, not the upload platform.
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
`--mode cross-notation`. The orientation batch itself succeeded; its compound shell call
exited 2 because a subsequent file search included a nonexistent directory. The shell exit
must not be attributed to the query owner. A separate narrow-lookup pilot selected
`core/resolve-model` for element records and did not answer that
scenario; it is diagnostic, not a successful benchmark sample. None of these observations
establishes a measured per-stage or stable cross-version token reduction.

After the routing change, `graph/out/e2e/apm-benchmark-routing-2026-09-30.json` passes the
existing evidence-equivalence checks against the same snapshot. It is a CLI benchmark, **not**
a post-change agent trial. The collector expects Codex `--json` events, the answer path, the
frozen prompt, and run metadata containing `started_at`, `finished_at`, `elapsed_ms`,
`exit_code`, `client`, `model`, `reasoning_effort` and a non-secret `settings` object. It records
missing usage as `unmeasured`; combined shell output is never falsely split by owner.

## Follow-up lookup diagnostic

`graph/out/e2e/apm-agent-lookup-guidance-2026-09-30/` contains one post-guidance agent run
of the frozen bounded-lookup question. It chose `core/resolve-element` in one executed query,
not `core/resolve-model`; the saved envelope has eight exact typed rows for six distinct
records across Backstage, LeanIX, ArchiMate and UML. The original scenario contract and its
baseline trace hash are unchanged. The separate source-grounded
`graph/tests/bounded-lookup-expected.json` checks the complete six-record answer, while the
original scenario still names the three core notation types needed by the cross-notation task.

Its observational trace records six completed shell calls, 14,066 agent-visible output bytes,
87,938 input tokens (80,128 cached) and 1,021 output tokens. Wall time is unmeasured at
millisecond precision; the recorded start/end are second-resolution filesystem timestamps.
The earlier failed pilot used a different prompt, so these runs are **not paired** and their
token counts are not a saving claim. The refreshed converter-backed skills benchmark passes
the six-record lookup and 21-row process checks at
`graph/out/e2e/apm-benchmark-frozen-contract-2026-09-30.json`. Final local checks: 904 APM
tests, 125 graph tests and a strict documentation build passed. The APM memory-watchdog test
failed under the file sandbox but passed when the full suite was rerun outside it.

## Initial paired investigation trials

The controlled A/B run is retained at `graph/out/e2e/apm-paired-2026-09-30/` with its runner,
per-run raw events, traces, answers, independent structural scoring and `manual-review.md`.
Baseline is the archived `6fdc595` skills tree, whose digest exactly matches the first agent
trace; candidate is the current skills tree with D25 and D26. The frozen prompt hash,
snapshot, dataset, profile, scenario, model and settings hashes match across the six
completed runs. Order alternated: baseline/candidate, candidate/baseline, baseline/candidate.
No source conversion was repeated.

All six completed answers select cross-notation (the three baseline agents need an explicit
mode override), save twelve query envelopes and a bundle, cite existing evidence, and match
the 21 source-grounded process rows as an exact multiset. The manual review flags wording in
one baseline and one candidate answer that could imply a contradiction between ArchiMate
`Target` and LeanIX `Active`; they are different register dimensions. No answer asserts that
an unmatched API path proves implementation absence.

| Completed runs only | Baseline, n=3 | Candidate, n=3 |
|---|---:|---:|
| Median agent wall time | 300,803 ms (266,503–523,136) | 290,836 ms (199,189–379,163) |
| Median measured input tokens | 703,375 (510,511–788,500) | 733,503 (459,226–827,297) |
| Median output tokens | 6,958 (5,457–7,853) | 7,386 (5,013–8,613) |
| Median completed shell calls | 16 | 21 |
| Manual cross-notation override | 3/3 | 0/3 |

Candidate median wall time is 3.3% lower but only two of three pairs are faster; median input
tokens are 4.3% higher and only one pair uses fewer. Query-envelope load and execution times
are well under one second in median per run, so they cannot explain the hundreds of seconds
of agent wall time. Per-stage model tokens and compound-command timings remain unmeasured.
This sample is **inconclusive**, not an APM performance win.

The original attempts at trials 7–10 did not complete because the Codex client returned
"Your workspace is out of credits. Add credits to continue." They remain preserved as
infrastructure failures, excluded from medians and distinct from answer-quality failures.
The five-pair result below supersedes this initial three-pair view.

## Offline follow-up checks

The converter-backed snapshot benchmark now checks the frozen C4 refusal scenario as well as
the bounded lookup and process answer. It calls `la-query query render notation/c4/containers`
with the verified profile but **without** a dataset or force option, and requires the profile
refusal rather than successful rendering or an empty result. The report at
`graph/out/e2e/apm-benchmark-refusal-2026-09-30.json` passes: six exact lookup records, the
21 source-grounded process rows and refusal before execution. This is a deterministic owner
check, not evidence that an agent would refuse correctly in a new trial. All 128 graph tests
pass; no sources were reconverted.

An offline review of the six completed JSONL traces found median agent-visible shell output
of 127,654 bytes for baseline and 148,266 for candidate. Large individual outputs often
combine file reads, owner calls or ad-hoc query-building, so their bytes cannot be attributed
to a single owner or stage. The identity-audit preview and reading both skill entrypoints are
also substantial context sources. These observations suggest a next optimization target, not
a measured token cause or a performance improvement; the candidate's measured median input
tokens are currently higher.

For a **new** comparison, the observational collector can accept a
line-hashed monotonic event-timing sidecar. The trial harness has an optional
`--capture-timing` switch that saves one without altering raw JSONL. It can measure completed
shell-call durations, but not model reasoning time or per-owner costs inside compound shell
commands. It was not mixed into the resumed A/B run, which retained the original settings.
The sidecar capture has unit tests and syntax checks; it was subsequently exercised in the
separate D27 comparison below. Its event-arrival offsets do not identify model versus service
latency or split compound shell commands into owner timings.

## Completed five-pair comparison

Credits and service access returned. A first trial-7 retry failed during local sandbox
initialization, before contacting the service; it remains an infrastructure failure. Four
`retry2` trials then completed with the frozen prompt, snapshot, model, settings and skill
digests unchanged. The ignored graph artifacts retain all ten completed trials, failed
attempts, raw events, envelopes, `summary.json`, `manual-audit.json` and `manual-review.md`.

| All completed attempts, n=5 each | Baseline | Candidate |
|---|---:|---:|
| Independent answer-quality passes | 5/5 | 4/5 |
| Median agent wall time | 266,503 ms (192,528–523,136) | 290,836 ms (199,189–379,163) |
| Median measured input tokens | 655,140 (453,972–788,500) | 733,503 (459,226–837,234) |
| Median agent-visible shell output | 133,519 bytes | 148,266 bytes |
| Manual cross-notation override | 5/5 | 0/5 |

The candidate is faster in three of five pairs but has 9.1% **higher** median wall time;
it uses fewer input tokens in two of five pairs but has 12.0% **higher** median input tokens.
These values include the failed-quality candidate run rather than selecting it out. The
candidate routing change removes all observed manual mode overrides, but no time or token
improvement is established.

The fifth candidate trial used all twelve queries without executing the available
process-to-API join. It correctly qualified that mapping as unresolved in its **executed
evidence**, but its answer omitted the requested ownership result even though the frozen
dataset contains the source-grounded 21-row answer. The independent exact-multiset checker
and manual review both mark this as incomplete. Earlier wording caveats in one trial per
variant remain separate from this failure. At that stage the quality regression blocked a
performance release or version bump. It also shows why a clean deterministic CLI benchmark
cannot substitute for agent trials; the D27 follow-up and separate forward test are below.

The bounded follow-up changes `linked-archi-analyse` guidance and its cross-notation plan:
claim-to-evidence coverage precedes optional/wider audits, and identity stop conditions do
not end independent question clauses. A focused deterministic test checks the compound
question, budget and unchanged query shortlist. The changed checkout passes 905 APM tests,
a strict documentation build and the converter-backed skills benchmark at
`graph/out/e2e/apm-benchmark-claim-coverage-final-2026-09-30.json` without reconversion.
At this point the checkpoint had not been tested with agents. Keep `linked-archi-query` as
the read-only executor; the separate changed-skills comparison below must not be pooled with
these ten runs. Per-stage model-token attribution remains unmeasured.

## D27 paired forward test

The separate five-pair comparison and independent review are retained at
`graph/out/e2e/apm-paired-d27-2026-10-01/` (`summary.json`, `manual-review.md` and individual
raw events, answers and envelopes). Baseline is the archived pre-D27 skills tree
(`ef7c3e3d73a5357c732302b1f0d15799944ef6fceb18bd5d08a440893e0dc2c1`); candidate
is D27 (`82079b89e629669cf0563970bfdc021c41b7238573d4bf7c5964622d859a1691`).
All completed trials used the same frozen prompt, converter-backed snapshot, verified
profile, model, low reasoning setting, 12-query budget and isolated settings. Order
alternated, with no source reconversion. An initial trial-7 candidate attempt exhausted
Codex credits before an answer; its completed retry is counted, while the failure remains
visible in the artifacts and is excluded from medians.

| Five completed attempts per variant | Pre-D27 baseline | D27 candidate |
|---|---:|---:|
| Independent 21-row exact process passes | 3/5 | 5/5 |
| Manual answer-quality passes | 4/5 | 5/5 |
| Median measured input tokens | 696,187 (653,397–754,764) | 542,727 (436,121–611,767) |
| Median output tokens | 6,926 | 6,239 |
| Median agent wall time | 255,268 ms (224,741–285,987) | 253,593 ms (210,381–792,602) |
| Median agent-visible shell output | 142,939 bytes | 136,039 bytes |
| Median completed shell calls / executed query envelopes | 15 / 11 | 12 / 10 |

Candidate input tokens are 22.0% lower by median and lower in every pair. Its exact process
evidence and manual answer-quality checks pass in all five trials. The baseline's first
answer genuinely misses the notification API/team path. Another baseline answer contains
all 21 substantive relations but projects owner as a group IRI rather than the expected
native entity reference; the exact checker fails it, while manual review counts a qualified
pass. Both results are reported without changing the checker after the fact. Several
baseline answers also need wording care: ArchiMate `Target` and LeanIX `Active` belong to
different register dimensions, not a demonstrated contradiction.

Median wall time is only 0.7% lower, with the candidate faster in three of five pairs and
one 792,602 ms candidate outlier. **No stable latency improvement or causal attribution to
the guidance alone is established.** JSONL event timing cannot distinguish model reasoning
from service delay; query-envelope load and execution medians are below one second per trial.
The measured-token completion gate is met on this frozen cross-notation scenario, with no
observed answer-quality or review-barrier regression. Per-stage cost attribution remains
unverified; the additional one-off agent smoke trials below are not performance samples.

## Release smoke trials

One D27 agent trial per remaining scenario is retained at
`graph/out/e2e/apm-release-smoke-2026-10-01/`, including raw events, traces, answers,
evidence and `review.md`. The bounded lookup executes `core/resolve-element` once; the
independent source-grounded checker matches all eight exact-name `(IRI, type)` bindings
for six distinct records, and the answer does not equate them by label. The C4 trial uses
query's catalogue/profile gate, saves the `REFUSED` result for
`notation/c4/containers`, executes zero RDF queries and does not mistake dataset absence
for enterprise-wide absence. Both answers cite existing archived evidence. An earlier
lookup attempt failed during sandboxed Codex initialization before answering; the
successful retry and failed attempt are both retained. The lookup envelope correctly
states that its fresh isolated skill state has no profile-verification marker, despite
the separately verified E2E snapshot. These two single trials check for obvious route
and refusal regressions; they do not establish statistical reliability or latency gains.

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
- [x] Clarify element-versus-model name resolution in query and analyse entrypoints and the
  catalogue. One bounded agent diagnostic now selects the element resolver and produces the
  complete source-grounded record set. This does not establish a stable performance gain.
- [x] Add a deterministic, profile-gated C4 refusal check to the converter-backed snapshot
  benchmark. It guards against treating an absent notation as an empty factual answer, but
  does not replace an agent refusal trial.
- [x] Complete five alternating pairs on the **same snapshot** and independently score their
  evidence. The candidate fails one ownership answer and has no stable wall-time or token win;
  the result is a failed gate, not an optimization success.
- [x] Add claim-to-evidence budget guidance in analyse and scope cross-notation stop conditions
  to the identity-dependent claim, without moving execution into query. Record the rationale
  in `PROPOSAL.md`, user-facing change in `CHANGELOG.md` and a focused regression test.
- [x] Run `make check`, strict docs and the CLI benchmark on the frozen snapshot. All 905 APM
  tests pass with process RSS inspection available; source-grounded checks pass without
  reconversion.
- [x] Forward-test the changed skill on the frozen snapshot in five new alternating pairs,
  independently review their answers and report the measured token gain separately from
  the unverified latency objective.
- [x] Run one bounded-lookup and one profile-refusal agent smoke trial against the same
  frozen snapshot and independently check their saved evidence before release preparation.

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
