# Lifecycle and portfolio comparison

Triggers: duplicate, overlap, rationalise, lifecycle, deprecated, strategic importance.

Use bounded populations and explicit comparison dimensions. `core/lifecycle` where the
capability is available, remembering it is sparse and notation-specific: the elements *not*
listed are overwhelmingly ones nobody recorded a status for, not ones in a healthy state.
`notation/leanix/factsheets` where the register itself is the subject.

**Never infer functional equivalence from labels alone.** Two applications called "Billing"
may be one system in two models, two systems, or one system and a report about it.
`core/define-term` makes the collision visible — its `candidates` column counts the distinct
resources a term matched, and each row carries that resource's own definition, type and
owning model, which is usually enough to see whether they are the same thing.
`core/label-collisions` sweeps for the same thing across a whole dataset, and returns
candidates rather than assertions. `core/identity-audit` settles it where the dataset has a
reconciliation step; where it does not, say the question is not answerable yet.

## Stop when

- equivalence rests on labels alone. Say the question is not answerable yet and name what
  would settle it — an authored identity assertion, reviewed by someone who knows both
  systems;
- lifecycle is absent for most of the population. A list of the few elements that carry a
  status is not a portfolio view, and presenting it as one implies the rest are healthy.
