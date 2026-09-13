# Your own templates

Templates here follow the same contract as the bundled ones and are the right
place for questions the core set does not cover. Note first that **a custom
ontology usually needs no new template at all**: the core templates resolve roles
rather than terms, so binding your vocabulary in a profile is normally enough. Use
the `linked-archi-profile` skill and its `references/profile-reference.md` guide for
that work. Write a template when the *question* is new, not when the vocabulary is.

`assets/templates/custom/` is exempt from the catalogue completeness check, so a template
dropped here will not fail the build. It also will not be reachable by routing or
covered by a test. Add a catalogue entry as soon as it is more than a scratch
query.

## The contract

**A prose header.** Three things, in this order: what it answers, what it does
*not* prove, and its parameters. The middle one earns its place - it is where a
reader learns that a modelled relationship is not a runtime dependency, or that an
absent value means nobody recorded it. Routing reads these too.

**No `PREFIX` lines.** Use `{{PREFIXES}}`. A template carrying its own prefixes is
how one query ends up on a stale namespace while its neighbour is current.

**No vocabulary terms.** Use `{{ROLE:label}}` for the primary binding,
`{{ROLES:x}}` for a `VALUES` list, `{{PATH:x}}` for an alternation. A hardcoded
IRI works until someone runs it against a graph built from a different ontology
version, and then returns nothing rather than failing.

**Wrap patterns in `{{GRAPH_OPEN:role}}` / `{{GRAPH_CLOSE}}`.** The profile decides
whether that becomes a `GRAPH` clause, a `VALUES` restriction, or a plain group, so
one template serves TriG and flattened Turtle. Use `:any` when the point is to
report which graphs exist.

**Bound the result.** Every template takes a `LIMIT`.

**Declare `requires`.** Roles, graph roles and capabilities. This is what turns a
missing dependency into a refusal with a reason instead of an empty result that
reads as "nothing exists". Add `alternatives` naming a template that answers the
same question from evidence the dataset does have.

**Add a test case.** `tests/test_templates.py` fails when a catalogued template has
none, so the catalogue cannot drift untested. That file is in the package **repository**, not
in an installed skill: a template added to an installed copy is an untested template.

## Getting started

```bash
cp ../core/neighbours-qualified.rq my-question.rq
```

Then add the catalogue entry, run it, and check the refusal path works:

```bash
python3 scripts/la-query catalog show custom/my-question --profile <your-profile>
python3 scripts/la-query query render custom/my-question --profile <your-profile> --set FOCUS_IRI=...
python3 scripts/la-query query run    custom/my-question --profile <your-profile> --data <your>.trig
```

Naming: `assets/templates/custom/<verb-or-noun>.rq`, catalogued as `custom/<same>`.
Group notation-specific work under `assets/templates/notation/<notation>/` instead,
and say so with a `notation` key.
