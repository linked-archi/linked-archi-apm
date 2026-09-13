# Evidence model

Five classes. Every claim in an answer belongs to exactly one, and the class should be
apparent to a reader without being spelled out pedantically.

| Class | Meaning | Example |
|---|---|---|
| **Graph fact** | An explicit triple or result binding | A qualified serving relationship exists from Application A to Service B |
| **Derived graph fact** | Produced by traversal or aggregation, with a path | Capability C is reachable from A in two hops via B |
| **Document statement** | A claim in a retrieved source | An ADR states the canonical API must be used |
| **Analyst inference** | Your conclusion from the above | Retiring A will require migrating B first |
| **Unknown** | Absent or ambiguous evidence | Runtime call volume is not represented in these models |

## The line that matters

Between **derived graph fact** and **analyst inference**. Reachability is a graph
property; impact is a judgement. "Twelve elements are reachable from A" is derived.
"Twelve systems are affected" is inference, and needs the relationship semantics on each
path to hold it up.

State the inference as an inference. It is often the most useful sentence in the answer —
it just should not be dressed as a measurement.

## What to retain per material conclusion

- The resource IRIs.
- The relationship path and its **direction**.
- The named graph or source each fact came from.
- The query identity — template name and query hash.
- The dataset identity, and the **profile and version**. A result produced under one
  profile and read under another looks reproducible and is not.
- The qualifications that apply.

The result envelope carries all of this. `citation()` renders it as one line.

## Absence

**Graph absence is not real-world absence.** Everything here came from models somebody
drew, so absence in the graph means absence in the models. The only case where the
stronger reading is available is when declared graph coverage supports it — and that is
a claim about the pipeline, not about the graph.

Three phrasings, in decreasing strength, all defensible when true:

- "No relationship of these types is modelled between X and Y."
- "Nothing in the loaded models connects X to Y."
- "X and Y may be connected in a model that is not loaded here."

Never: "X does not depend on Y."

## Empty results

An empty result is a finding, and which finding depends on evidence you must have
already gathered:

| Reading | Requires |
|---|---|
| Nothing of this kind is modelled | `core/inventory` showing the type has members |
| The data is not loaded | `core/inventory` showing it does not |
| The question is not answerable here | A refusal naming the missing capability |
| The query is wrong | A term check with `core/element-detail` |

Reporting the first when the truth is the second or fourth is how an empty result becomes
a wrong answer.

## Truncation

A count sitting exactly on the row limit is a floor. Report "at least twelve", never
"twelve". The envelope flags this.

## Contradiction

When two sources disagree, report both with their provenance rather than picking one.
Which model is right is usually a question for a model owner, and the disagreement is
frequently the most valuable thing the graph surfaced.

Common shape: a LeanIX fact sheet and an ArchiMate model describing the same system with
different lifecycle states. Note that a fact sheet is a **record about** a thing, not the
thing, so the two are not straightforwardly comparable.

## Staleness

Provenance records when the RDF was produced, not when the architecture was true. Two
timestamps worth separating:

- **The author-declared export or model date.** What the source claims about itself.
- **The conversion run.** When the file was read.

A gap between them is a staleness signal. LeanIX output carries both, which is why
`core/provenance` may legitimately return two rows for one element.

## Inference steps that need naming

If a conclusion depends on any of these, say so — each is a step a reader may not grant:

- Treating a design-time relationship as a runtime dependency.
- Treating reachability as impact.
- Treating a label match as identity.
- Treating a fact sheet as its subject.
- Treating an absent property as a property known to be absent.
- Treating one model's view as the enterprise's.
