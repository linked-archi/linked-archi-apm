# Model quality

Triggers: can we trust this, is the model complete, what is wrong with our models, quality.

`core/inventory-summary` first, then `core/orphans`, `core/coverage-gaps` and
`core/provenance`. `core/identity-audit` where cross-source duplication is the worry. Where a
SHACL report has been loaded into the dataset, `core/validation-summary` — and report
target-class coverage beside the verdict, always. There is no count of constraints evaluated;
nothing in the pipeline produces one, so do not report a number for it.

This pattern is query work and needs no validator. Conformance against shapes is a different
question with a different owner: hand it to `linked-archi-validate`, which runs SHACL
in-process and can also summarise a report file somebody already produced. Do that only when
conformance was actually asked about.

Group findings by source model and owner rather than by rule. The person who can fix a
finding cares which of their files is wrong, not which constraint fired.

## Stop when

- the question turns out to be about conformance against shapes. Hand it to
  `linked-archi-validate` rather than approximating it with queries;
- a verdict is available but its target-class coverage is not. "Conforms" over shapes that
  targeted nothing is not evidence of quality, and reporting the verdict alone implies it is.
