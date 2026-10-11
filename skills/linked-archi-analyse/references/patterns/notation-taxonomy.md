# Notation type taxonomy

Triggers: notation taxonomy, type taxonomy, grouped by domain, grouped by aspect,
element by domain, element by aspect, type category.

This pattern asks how a **published notation scheme groups OWL element types**. It
does not ask whether an instance carries an asserted SKOS classification. Orient
on models and notation first. If a category is named, resolve its quoted label with
`core/resolve-vocabulary-concept`; review the exact scheme and ambiguity, then use
`core/elements-by-category` for a reviewed model IRI from `core/models`. Its rows
include the category's scheme. A model may legitimately appear under more than
one axis (for example, ArchiMate 4 domain and aspect), so do not deduplicate
categories as if they were mutually exclusive. Without a named category, skip the
resolver and inspect the categories returned for the reviewed model.

The ontology and taxonomy must be attached under the profile's `vocabulary`
graph role. Converters emit instances, not the published scheme. If that role is
unbound, the query owner refuses the grouping template; do not substitute an
empty result. Use `core/elements-by-type` for an inventory when no taxonomy is
available, and state that it is a weaker answer.

Templates: `core/resolve-vocabulary-concept`, `core/elements-by-category`,
`core/provenance`.

## Stop when

- the notation's matching vocabulary is not attached — do not treat zero categories as zero elements;
- multiple schemes or categories match — review the exact scheme IRI before selecting one;
- the category groups OWL types, not asserted instance classifications.
