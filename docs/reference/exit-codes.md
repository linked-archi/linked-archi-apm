# Exit codes

Exit codes here carry meaning beyond success and failure. In particular, **1 is usually a finding**,
not a crash — something the caller should read and act on rather than retry.

| Skill | 0 | 1 | 2 |
|---|---|---|---|
| `la-source` | a structured result was produced (`ready`, or `action_required` for MCP) | **never used** | fail-closed |
| `la-connect` | attached | `datasets` found nothing; `doctor` found a missing dependency | error: nothing parsed, rejected endpoint, unresolvable companion, refused query |
| `la-profile` | ok | drift found by `verify`: a claim in the profile is false about the dataset | error |
| `la-query` | answered, including an empty result | refused: unsupported template, or not read-only | error |
| `la-validate` | conforms **and** something was checked | results reported | could not run — including a run that selected no focus node |
| `la-analyse` | done | refused: unknown pattern, incoherent bundle, missing claim class, uncited claim | error: unreadable file, malformed request |

## The ones worth knowing

**`la-source` has no exit 1.** Acquisition either produces verified bytes or refuses. There is no
middle state where you got something questionable.

**`la-query` exit 1 is routing.** A refused template names why and, where one exists, what to run
instead. Reading the reason and running the alternative is the intended response.

**`la-query` exit 0 includes zero rows.** An empty result is a finding. The output says so and points
at the orientation templates.

**`la-validate` exit 2 covers a vacuous pass.** If the run selected no focus node, the report may say
`sh:conforms true` while having validated nothing. That exits 2, so no caller can mistake it for
conformance.

**`la-profile` exit 1 means the profile and the dataset disagree.** Read the report, then fix
whichever is wrong. `--emit-fix` writes a child profile for the mechanically fixable part.

## Signals

Across every skill: `BrokenPipeError` exits 0 — piping into `head` is not a failure — and
`KeyboardInterrupt` exits 2.
