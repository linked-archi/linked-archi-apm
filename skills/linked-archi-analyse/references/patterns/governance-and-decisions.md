# Governance and decisions

Triggers: decision, principle, standard, policy, exception, constraint, who approved.

Resolve the governed scope. Discover which predicates carry decisions or policies in this
dataset with `core/discover-predicates` — **there is no guarantee any do**. Retrieve status
and provenance, then linked documents. Separate normative statements from your own inference.

Templates: `core/discover-predicates`, `core/element-detail`, `core/classified-by`,
`core/provenance`.

`core/classified-by` is a candidate only when the governance question actually
names a taxonomy branch. Resolve that name with `core/resolve-concept` and review
the scheme before binding `CONCEPT_IRI`; this pattern's ordinary resolve step is
for the governed architecture element, not for a taxonomy concept.

Note that `adms:status` in the provenance graph describes the **conversion**, not the
architecture. "Completed" means the converter finished.

## Stop when

- no predicate in this dataset carries decisions or policies. Governance is frequently
  outside the model entirely, and that is the answer;
- the only status found describes the conversion. Reporting a converter's "Completed" as an
  approval is a fabricated governance claim.
