# Traceability

Triggers: which capability, process, application or technology supports, realises,
implements or serves another. Anything asked as "end to end" or "cross-layer".

Resolve the anchor with `core/resolve-element` and name both layers. Discover which
cross-layer relationship types exist before assuming one. Retrieve explicit typed paths with
`core/traceability`, and identify missing links *separately* from negative assertions.

Templates: `core/traceability`, then `core/coverage-gaps` for the complementary question —
which elements of the source type reach nothing at all.

Cross-layer relationship direction is a modelling convention that differs between notations
and sometimes between models, so follow both and report which way the path ran.

## Stop when

- no cross-layer relationship type exists in this dataset. That is a finding about the
  models, and a more creative query will not change it;
- a missing link has been identified. Report it as "nothing in the models connects these",
  never as "these are not connected".
