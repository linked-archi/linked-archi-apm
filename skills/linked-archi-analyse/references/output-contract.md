# Output contract

Answer first, evidence under it, limits stated plainly. Length should be proportional to
the question, not to the number of queries it took.

## Conclusion

Answer directly, in the first sentence, and qualify its scope in the same breath.

> Three applications depend on the policy data component, all through modelled serving
> relationships in the Archisurance model. Nothing outside that model was loaded, so this
> is not an enterprise-wide answer.

Not "here is what I found" followed by a list. The reader wants the answer and then the
grounds for it.

## Evidence

A compact table or path list. Include labels, element types, the relationship kind, and
the direction. Direction matters: "A serves B" and "B serves A" are different findings
and the notations disagree about which way to draw some of them.

Show the path, not just the endpoints, whenever a conclusion depends on more than one
hop. A reader has to be able to disagree with a specific step.

## Queries run

Name every template, with its parameters. Include the query hash where results were
saved. If you adapted a template or wrote an ad-hoc query, show the SPARQL — that is the
whole point of the approach: a wrong answer should be visibly a wrong query rather than a
plausible paragraph.

## Sources

Only the sources you actually used. For each: the source model, the converter and
version, and the conversion timestamp. Distinguish document statements from graph facts.

An architecture answer without a source is a claim. With one it is evidence, and the
reader can go and look at the model themselves.

## Qualifications

State, in a sentence each, whichever apply:

- data absent that would change the answer;
- ambiguity you resolved, and how;
- staleness — an export date well before the conversion date;
- truncation — a count that is a floor rather than a total;
- validation findings bearing on the elements involved;
- contradictions between sources;
- **inference steps a reader may not grant**, named individually.

This section is not a disclaimer. A qualification that could change the decision belongs
in the conclusion instead.

## What cannot be concluded

Explicit, and separate from the qualifications. This is what distinguishes an analysis
from an assertion.

> These models say nothing about runtime call volume or failure behaviour, so this does
> not establish operational criticality. Cross-notation identity is not asserted in this
> dataset, so a Backstage component describing the same system would not have been
> joined.

## Reproducibility

Dataset identity, profile name and version, and execution timestamp. The profile is not
optional: a result produced under one vocabulary binding and read under another looks
reproducible and is not.

The result envelope carries all of it, and `citation()` renders it as one line per query.

## Suggested next step

At most one, and only when it would materially reduce an uncertainty you identified.
Name what it would settle.

Skip it entirely when the answer is complete. A next step offered out of habit reads as
an admission that the answer was not.

## Completion criteria

An investigation is finished only when the response states:

- what the evidence supports;
- the explicit paths or records supporting it;
- which queries and documents were used;
- the gaps, contradictions and assumptions;
- what cannot be concluded from the available data.

Missing the last two makes the rest less trustworthy, not more.

## When nothing could be executed

Say so first, before anything else. Produce the candidate queries, label them clearly as
unexecuted, and state what would be needed — a dataset path, an endpoint, a converted
model, a reconciliation step.

Do not describe results you have not seen. Do not soften it into a hypothetical answer.
