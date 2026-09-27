# Contributing

Issues and merge requests are welcome at
<https://github.com/linked-archi/linked-archi-apm>.

## Before you start

```bash
pip install PyYAML pyoxigraph
make check          # skill validation, then the full test suite
```

`make check` is what CI runs. It must pass before and after your change.

## Benchmarking query workflows

Run from the repository root with the same dependencies as the tests:

```bash
make benchmark
python3 tests/benchmark_queries.py --runs 5 --warmups 1 --output out/benchmark-current.json
```

The default is **the bundled test-only `fixtures/base.trig`**, not a discovered user dataset.
`make benchmark` writes `out/query-benchmark.json`; override `BENCH_ARGS` for other settings.
Reports never overwrite existing files: choose a fresh path for each comparison. Without
`--output`, the script prints JSON. It makes no network requests and changes no installed skills.

For a real local dataset, choose the file, profile and an element name explicitly:

```bash
python3 tests/benchmark_queries.py --data /path/to/model.trig \
  --profile /path/to/profile.yaml --term 'Known Service' \
  --runs 5 --warmups 1 --output out/benchmark-model.json
```

`--data` is repeatable and requires `--term`; the harness never guesses a name from private
data. A term must have at least two characters, no quote marks and no surrounding whitespace,
matching the current analyse name parser's limits. Unicode names are preserved. `--limit`
caps the lookup query (default 20), while `--preview-rows` caps display (default 5).
`--timeout-seconds` bounds each owner invocation (default 120). A local profile file or
bundled profile name works; resolve and verify the appropriate profile separately before
interpreting real architecture evidence.

The eight cases measure:

| Cases | Comparison |
|---|---|
| `catalogue_full`, `catalogue_selected` | Full metadata versus one selected template, with identical gates and caveats |
| `render_only` | Profile-resolved query generation without dataset access |
| `lookup_json`, `lookup_preview` | The same bounded lookup as JSON stdout versus a saved full envelope with bounded preview |
| `analyse_plan` | Question routing, dependencies and batch-manifest creation; no query execution |
| `orientation_individual`, `orientation_batch` | The plan's two ready orientation queries in separate invocations versus one batch |

This is a **mechanical benchmark, not an automatic investigation**: no dependent steps,
refused candidates or placeholders are executed, and no answer is inferred. All queries
still go through query, transport through connect, and planning through analyse. It pins
the checkout's owner scripts and companions, uses fresh temporary verification state and
explicit in-memory stores, and preserves inherited local memory/deadline bounds. It does
not modify or verify the user's normal profile state. Unverified-profile caveats remain.

Every measured case includes individual samples and medians for CLI wall time, UTF-8
stdout/stderr bytes and **top-level owner CLI calls**, not total nested subprocesses. Query
cases also report load/query timings from the envelopes; batch load time is counted once.
One setup plan and two profile-resolution checks are counted separately, outside samples.
The report records source revision/dirty status, source digest, Python/dependency versions,
dataset hashes and resolved profile identity/fingerprint. Warmups are excluded, case order
alternates, and fresh processes do not imply cold OS caches. File hashing also warms caches.

Evidence checks retain exact query/hash, dataset/profile identity, complete rows including
duplicates, warnings and truncation. They ignore only execution timestamps and timings,
row order, and the order within `core/models`' set-valued `generated` timestamp cell.
Each batch preview must retain its own warnings/citation. Temporary outputs are removed
before each writing command so a missing write cannot reuse another run's envelope.
Empty lookups/orientation, changed inputs/profile or unequal evidence fail the run rather
than producing a misleading speed result. Nondeterministic subsets at a query limit can
therefore fail comparison; use a suitably selective term or a higher permitted limit.

Output bytes are **not model tokens** or account usage. The harness compares same-checkout
execution modes, not historical revisions, LLM reasoning time or an end-to-end agent answer.
Preview includes writing the full envelope, while the JSON lookup prints it to stdout.
Do not assert speed thresholds on tiny fixtures or extrapolate them to a production estate.
Use separately named reports on the same stable real input before choosing another optimisation.
Reports contain local paths, search terms, hashes and counts but no raw rows or full queries;
keep them in ignored `out/` and review them before sharing. Temporary evidence is deleted on exit.

## The rules the suite enforces

These are not style preferences — the tests fail on them, and each exists because the
failure mode it prevents is silent rather than loud.

**No template names a vocabulary term.** Templates name *roles*; the profile binds roles to
IRIs. A `PREFIX` line in a template is how a whole library ends up querying a namespace that
does not exist while every query still parses. Pinned by
`test_no_template_carries_its_own_prefixes`.

**Every catalogued template has a fixture case.** Add a template and you add a case to
`tests/test_templates.py`, or the build fails. A template nobody runs is a template nobody
knows is broken.

**A gated template declares `requires:` and names an alternative.** If a template needs a
capability the dataset may not have, it must say so and point somewhere useful. A refusal an
agent can act on beats an empty result it cannot distinguish from a fact.

**No capability claim before the runtime provides it.** See decision D18 in
[PROPOSAL.md](PROPOSAL.md). A claim written ahead of its implementation is indistinguishable
from one whose implementation regressed.

**Strict per-skill ownership.** Runtime code and assets live only in the skill that owns
them. No shared library, no generated copies, no cross-skill imports — companions talk over
versioned JSON subprocess contracts. Fifteen packaging tests enforce this.

**Fixtures are extracted, not authored.** `fixtures/` comes from real converter output via
`make fixtures`. An authored fixture is written to satisfy the queries under test, so it
cannot detect a wrong vocabulary. If you need new fixture coverage, extract it.

## Scope of a change

One concern per merge request, with the reasoning in the commit message rather than only in
the diff. If your change alters what the package promises — a `SKILL.md` contract, a machine
contract under a skill's `references/`, a bundled profile, or the template catalogue — say so,
and record *why* in the commit message and in [PROPOSAL.md](PROPOSAL.md).

## Documentation

Prose is part of the package. `PROPOSAL.md` is the design record and decision log; amend it
rather than silently contradicting it. Every documented command is checked for executability
by the packaging tests, so an example that cannot run fails CI.

## Licence

Contributions are accepted under [Apache-2.0](LICENSE), the licence this package ships under.
