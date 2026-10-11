# Taxonomy classification

Triggers: classified under, classified as, classified, classification branch, taxonomy branch,
taxonomy category, category members.

This pattern is for membership in an **asserted SKOS classification branch**. The
question's classification wording selects the method; a taxonomy label by itself
does not choose a query. Orient first, then resolve the quoted category name with
`core/resolve-concept`. Review all candidate concept IRIs and schemes. If the term
is missing or ambiguous, ask rather than constructing an IRI from the label.
If candidate results are truncated, raise the bounded limit or stop; the first
page cannot establish that the name is unique.

Bind the reviewed concept IRI to `core/classified-by`, then obtain provenance for
load-bearing returned elements with `core/provenance`. The resolver and classifier
read the semantic graph: a published taxonomy loaded only into the vocabulary
graph is not evidence that the model asserts classification membership. The
resolver accepts direct `skos:inScheme` or one `skos:broader` hop to a parent with
`skos:inScheme`; deeper paths need an explicit profile/query adaptation, not a
silent guess.

Templates: `core/resolve-concept`, `core/classified-by`, `core/provenance`.

## Stop when

- no matching SKOS concept or scheme is present in the semantic graph — do not invent an IRI;
- more than one concept or scheme matches the term — ask which one was intended;
- the branch has no asserted classifications — do not infer that no elements belong to it.
