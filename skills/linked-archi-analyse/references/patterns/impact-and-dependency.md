# Impact and dependency

Triggers: retire, replace, change, migrate, fail, affected by, depends on, blast radius.

1. Resolve the focus resource with `core/resolve-element`.
2. Discover which relationship types this dataset actually uses
   (`core/discover-relationship-types`).
3. `core/neighbours-qualified` before `core/dependents-qualified`. Direct evidence first.
4. Classify each path by element type **and relationship semantics**.
5. Retrieve lifecycle, ownership, governance and provenance only where relevant.

Templates: `core/neighbours-qualified`, `core/dependents-qualified`, `core/provenance`.
With `direct_rel_triples`, `core/dependents-direct` gives unbounded-depth traversal along a
chosen predicate set.

**The mistake this pattern exists to prevent:** labelling everything reachable "impacted".
A two-hop path may compose relationship types whose combination means nothing — "A is
assigned to B" and "B is associated with C" does not make C depend on A. Read the
relationship types on the path and say which steps you consider load-bearing.

A modelled dependency is a design-time statement by whoever drew the model. It is not
traffic, not criticality, and not failure propagation.

## Stop when

- the relationship semantics on a path stop supporting the claim;
- reachability is established but criticality is not — they are different questions, and
  only one of them is in the graph;
- the next hop needs data the models do not carry, such as traffic or failure history. Say
  so rather than substituting reachability for it.
