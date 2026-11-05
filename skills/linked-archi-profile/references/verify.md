# Acting on `verify` findings

What to do about each finding `la-profile verify` reports. `SKILL.md` has the commands and the
error / warning / ok rule; load this when a finding needs action or explaining.

| Finding | Do |
|---|---|
| `capabilities.<name>` (error) | The data contradicts the claim. `--emit-fix` writes the correction (below). A capability found **true** means the converter ran with a flag the parent profile does not assume; one found **false** may mean a model failed to load - check `core/models` before accepting it. |
| `graphs.named_graphs` (error) | Named graphs claimed, none found: the file lost them (Turtle, N-Triples, or TriG named `.ttl`) or never had any. Re-export as TriG or N-Quads, or use `examples/flattened-turtle`. |
| `graphs.roles.<name>`, **absent** (error if required) | No graph has that role. A model did not load, the dataset predates the current layout (override the three keys in `SKILL.md`), or another profile's layout fits. |
| `graphs.roles.<name>`, **present but partitioned** | The role is split across descendant graphs (`graph/semantic/{repo}/{path}`) that a suffix selector cannot match. Opt the role into [`graphs.descendants`](profile-reference.md#descendants). |
| `roles.<name>` (warning) | Bound to a term this dataset never uses. If a template depending on it comes back empty, confirm the spelling with `core/element-detail` before rebinding. Do not null the role to silence the warning: that refuses every template requiring it. |
| `metamodel.manifest` (warning) | The data declares a metamodel whose manifest is not attached. Its IRI dereferences: `la-source url <iri>`, then attach it with `la-connect`. Where the version is part of the IRI (ArchiMate, BPMN), a manifest for another release reads as absent; C4 and Backstage are not versioned that way. |
| `metamodel.assets` (warning) | The manifest is attached and the ontology, taxonomy, shapes or viewpoint catalogue it names are not. Attach them the same way. |
| `notations.present` (warning) | A declared notation has no model in this dataset. Record it (below). |

Until a notation's shapes and vocabulary are attached, a schema-level check finds nothing for
it: "no constraint published" is not "no problem".

## Recording notation presence

```yaml
notations:
  bpmn:
    present: false      # this dataset holds no BPMN
```

`false` refuses every template written against that notation, with a refusal naming it instead
of an empty table implying absence. `partial` - present for some models, absent for others -
runs with a caveat. `true` changes nothing. Leaving it out means unknown, and nothing is
refused on an unknown.

## `--emit-fix`

The report goes to stderr and the child profile to stdout, so `> child.yaml` gives a usable
file. The child `extends` the parent and overrides only capability drift: an unused role is
left alone, and a missing named graph needs a different `layout` rather than a key edit. Read
it before using it.
