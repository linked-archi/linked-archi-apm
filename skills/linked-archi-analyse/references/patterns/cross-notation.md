# Cross-notation questions

Triggers: anything joining two tools — a BPMN process to an ArchiMate application, a
Backstage component to a C4 container, "is this the same system", "reconcile".

These are the questions the graph exists to answer and the ones most likely to come back
empty. The cause is almost always a **missing identity assertion**, not a wrong query.
Cross-tool equivalence cannot be derived; it is authored and human-reviewed.

Confirm both notations actually loaded (`core/inventory-summary`) before concluding anything
about the join: one absent notation explains an empty result completely.

Run `core/identity-audit` first. If it is refused, the dataset has no reconciliation and the
join cannot be made — report that as the finding, and note what would provide it.

`core/label-collisions` is the one thing to reach for after that refusal, and it changes
nothing about the finding. It lists elements sharing a normalised label across models —
**candidates, not assertions** — so the set somebody would otherwise eyeball is at least
complete and on the record. Every result carries a caveat saying exactly that; keep it in the
answer. Presenting these as a join is the failure this pattern exists to prevent.

## Stop when

- `core/identity-audit` is refused. The dataset has no reconciliation, so the join cannot be
  made by any query;
- only label candidates remain. Report them as candidates, with the caveat, and stop. The
  next step belongs to a human who can decide whether two things are one thing.
