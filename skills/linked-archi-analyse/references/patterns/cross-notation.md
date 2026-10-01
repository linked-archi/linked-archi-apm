# Cross-notation questions

Triggers: anything joining two tools — a BPMN process to an ArchiMate application, a
Backstage component to a C4 container, "is this the same system", "reconcile".
If no phrase trigger matches, naming at least two notations also routes here; an explicit
impact or coverage trigger takes precedence over this fallback.

These are the questions the graph exists to answer and the ones most likely to come back
empty. For an identity-dependent join, a **missing identity assertion** is a common cause;
it does not explain an empty result for every other clause. Cross-tool equivalence cannot
be derived; it is authored and human-reviewed.

Confirm both notations actually loaded (`core/inventory-summary`) before concluding anything
about the join: one absent notation explains an empty result completely.

For a multi-part question, identify the requested claims before spending the query budget.
This pattern's templates address authored correspondence; a separate serving, traceability
or ownership clause needs its own evidence path. After orientation and name resolution,
prioritise one load-bearing path per claim before broad or repeated audits. Use
`core/identity-audit` for the identity-dependent claim; if its result is truncated, seek
focused evidence for the resolved records instead of raising the limit while another clause
remains unanswered. Execute any focused or adapted query only through `linked-archi-query`.

If `core/identity-audit` is refused, the dataset has no supported reconciliation for that
join — report that boundary, and note what would provide it. Do not treat it as a refusal
of independent parts of the user's question.

`core/label-collisions` is the one thing to reach for after that refusal, and it changes
nothing about the finding. It lists elements sharing a normalised label across models —
**candidates, not assertions** — so the set somebody would otherwise eyeball is at least
complete and on the record. Every result carries a caveat saying exactly that; keep it in the
answer. Presenting these as a join is the failure this pattern exists to prevent.

## Stop when

- `core/identity-audit` is refused: stop the identity-dependent join, not independent parts
  of a multi-part question;
- only label candidates remain: report identity as unresolved, with the caveat. The next
  identity decision belongs to a human; continue independent claims with their own evidence.
