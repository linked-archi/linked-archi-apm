# Deriving a profile

For a dataset built on a custom ontology, taxonomy or converter configuration. **Derive
rather than author**, because the information already exists in the artifacts that produced
the graph.

Most of the time this needs **no new templates**. Core templates resolve roles rather than
terms, so binding your vocabulary in a profile is enough.

## The two sources

```bash
# $SKILL and $PROJECT as set up in SKILL.md: the profile belongs to the project, not
# beside an installed skill where the next upgrade loses it.

# From the converter type-mapping that produced the graph
python3 "$SKILL/scripts/la-profile" derive acme \
    --type-mapping "$PROJECT/config/type-mapping-acme.yml" \
    --base-iri https://acme.example/la/ -o "$PROJECT/profiles/acme.yaml"

# From a published arch:Metamodel manifest
python3 "$SKILL/scripts/la-profile" derive cloudplatform \
    --metamodel "$PROJECT/cloudplatform-metamodel.ttl" \
    --notation cp -o "$PROJECT/profiles/cloudplatform.yaml"

# Both, when you have both
python3 "$SKILL/scripts/la-profile" derive acme \
    --type-mapping "$PROJECT/acme.yml" --metamodel "$PROJECT/acme-metamodel.ttl" \
    -o "$PROJECT/profiles/acme.yaml"
```

Deriving from the type mapping closes a loop worth closing: the file that told the converter
to emit `cp:Microservice` is the same information a query needs to find it again, so the
graph and the queries cannot disagree.

## What comes out is a draft

It states what the source artifacts **declare**, which is not the same as what a dataset
**contains**. So it always ends with a `verify` step, and two things are deliberately never
guessed:

- **Optional roles** — ownership, lifecycle, identity. A mapping says what *may* be emitted,
  not what was.
- **`direct_rel_triples`** — a mapping declaring direct predicates does not mean the
  converter was run with the flag that emits them.

Read the notes in the generated header; they name every judgement left to you. Then:

```bash
python3 scripts/la-profile verify --profile profiles/acme.yaml --data your-graph.trig
```

If that reports capability drift, `--emit-fix` turns it into a corrected child profile in one
command rather than an editing session.

## Taxonomies need no derivation at all

A taxonomy is one `taxonomies` entry. Classification is plain SKOS, so `core/classified-by`
walks `skos:broader` against whichever scheme you name — the Linked.Archi common taxonomy, a
notation's own, or a house scheme reached through `arch:conceptClassification`.

## Editing by hand instead

Copy the closest bundled profile and use `extends`, so your file states only the differences
and inherits corrections to the base. Mappings merge key by key; scalars and **lists replace
outright**, because a role bound to a fallback chain is one decision and appending to it from
a child would silently change which term `{{ROLE:x}}` resolves to.

Never edit a bundled profile in place. It describes converter output at known flags, and
editing it to match your dataset breaks it for everyone else's.

## Where the fields are documented

- Field-by-field: [profile-reference.md](profile-reference.md)
- Membership traversal: [membership.md](membership.md)

The package also ships a longer prose walkthrough as `ADAPTING.md` at its root. That is
**repository material**, outside this skill, so it may be absent from an installed copy —
reach for the references above first.
