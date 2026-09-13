# Analysis patterns — routing index

Choose the smallest pattern that answers the question and **load only that file**. Combine
only when an evidence gap forces it, and say why.

| Question sounds like | Pattern | Load |
|---|---|---|
| retire, replace, migrate, decommission, affected by, depends on, blast radius | Impact and dependency | [patterns/impact-and-dependency.md](patterns/impact-and-dependency.md) |
| which capability, supports, realises, implements, serves, end to end | Traceability | [patterns/traceability.md](patterns/traceability.md) |
| uncovered, coverage, incomplete, gap, missing, no owner | Coverage and gaps | [patterns/coverage-and-gaps.md](patterns/coverage-and-gaps.md) |
| decision, principle, standard, policy, exception, who approved | Governance and decisions | [patterns/governance-and-decisions.md](patterns/governance-and-decisions.md) |
| duplicate, overlap, rationalise, lifecycle, deprecated, portfolio | Lifecycle and portfolio comparison | [patterns/lifecycle-and-portfolio.md](patterns/lifecycle-and-portfolio.md) |
| reconcile, same system, both tools, identity | Cross-notation questions | [patterns/cross-notation.md](patterns/cross-notation.md) |
| diagram, drawn, documented, view, what is new in | Views and documentation | [patterns/views-and-documentation.md](patterns/views-and-documentation.md) |
| what is in, take part, participate, who is involved, components | What a model contains | [patterns/model-contents.md](patterns/model-contents.md) |
| can we trust, quality, complete, wrong with, orphans, conformance | Model quality | [patterns/model-quality.md](patterns/model-quality.md) |

**`la-analyse plan` does this routing for you**, and shows the score it gave each candidate:

```bash
la-analyse plan --question '...' --profile "$PROFILE" --data "$GRAPH"
la-analyse plan --list-patterns          # the table above, from the data
la-analyse plan --question '...' --mode model-quality     # when the routing is wrong
```

Triggers are matched as whole words for single words and as substrings for phrases, which is
why they are short: "can we trust this" would miss "can we trust **these** models".

Each file carries the steps, the templates, the mistake the pattern exists to prevent, and
its **stop conditions** — because knowing when an investigation is finished is as much of the
method as knowing what to run.

## Running any of them

Every template named in every pattern runs in the one command shape from `SKILL.md` — same
`--profile`, same `--data`/`--endpoint`, `--json -o "$STEPS/NN-name.json"` — with the step
numbering continuing across patterns. Take parameters from
`la-query catalog show <template> --profile "$PROFILE"`, never from the `.rq` file.

A template this dataset cannot support is **refused with a reason and an alternative**, so a
pattern naming six templates does not require all six to be available. Check with
`la-query catalog list --profile "$PROFILE" --why` before deciding a pattern is unavailable.

## The same table, as data

[`assets/patterns.json`](../assets/patterns.json) holds this routing table machine-readably —
triggers, file, templates, gating capabilities and stop conditions per pattern. It is the
authoritative version for routing, and the suite checks this index against it: every pattern
has a file that exists and appears above, and every template named is one the query catalogue
actually ships. A routing table pointing at a template nobody installed is worse than no
routing table.
