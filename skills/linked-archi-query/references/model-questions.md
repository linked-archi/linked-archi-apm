# Running a model question

How a model question (`Q`, `Q+T`) runs, and why one is refused. `catalog show NAME` says
what it asks and what its rows do not prove.

- A question reads the dataset as **one graph**. `query run` arranges that on local data; an
  endpoint takes it only when the profile declares `capabilities.union_default_graph`.
  `query render` gives the template where one fits a profile with named graphs.
- `Q+T`: `query run` asks the question where the dataset fits it and runs the template of the
  same name elsewhere.
- What its query reads is gated like a template's `requires` (direct triples, `rdf:reifies`,
  `arch:inModel`). One reading the metamodel is checked when it runs, and refused - naming the
  published Turtle to pass with another `--data` - when that is not loaded, unless its
  template can answer instead.
- A project's own question set joins with `--catalog questions.ttl` (needs pyoxigraph), under
  a project namespace.

## Asserted relationships and derivations

The catalogue bundles 59 model questions. `core/neighbours` and `core/dependents` follow
asserted direct triples using the metamodel's `arch:unqualifiedForm` mappings. They need
`direct_rel_triples` and the relevant ontology, including when the query follows a variable
predicate. `core/dependents` is bounded to two hops; `core/dependents-direct` follows a
chosen predicate path at any depth. The `-qualified` queries keep their names and resource-level
meaning: endpoints can describe an unconfirmed proposal, so those rows alone are not assertions.

A local question reads the union of the loaded graphs, including a model's derived graph.
A valid derivation asserts a triple and is traversed; an unconfirmed potential derivation
does not. To distinguish stated facts from valid derivations, inspect provenance or use an
explicitly scoped query over the source model/semantic graphs, excluding the derived graph.
Never silently describe the union as authored facts only.

Use `notation/archimate/potential-derivations` and `potential-derivation-premises` (or the
`notation/archimate4/` equivalents) to inspect proposals and the premises behind them.
They return nothing when no derivations are loaded; that does not establish that no
relationship could be derived. The integrity audit excludes unasserted, unlinked propositions.

For presentation names use `core/context-names`; aliases resolve through plain SKOS while
this query preserves the audience and language. Label expressions are presentation rules,
not additional canonical names or asserted relationships, and are not evaluated by APM.
