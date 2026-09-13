# Coverage and gaps

Triggers: uncovered, missing owner, no application, incomplete, compliance coverage.

1. Define the population and the expected property.
2. Confirm the population is not empty — a type with zero members produces zero gaps and
   looks like perfect coverage. `core/inventory` or `core/elements-by-type`.
3. Confirm the predicate spelling with `core/element-detail` on one element you know carries
   it. Two spellings of a property key are two different predicates, and a join on the wrong
   casing returns fewer rows with no error.
4. Query absence with `core/coverage-gaps`.
5. Check which models are in scope. A gap concentrated in one model is usually a partial
   export, not an ownership problem.

Templates: `core/coverage-gaps`, `core/orphans`, `core/inventory`.

**Distinguish "not represented" from "does not exist"** in every sentence of the answer.
Reporting the second when you measured the first is the most damaging mistake available here.

## Stop when

- the population is empty. Zero gaps out of zero elements is not coverage, and reporting it
  as such is worse than reporting nothing;
- the gap concentrates in one model. That is a question about the export, and it should be
  answered before the ownership question is asked.
