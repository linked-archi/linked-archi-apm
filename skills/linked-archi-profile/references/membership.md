# Model membership

How a dataset expresses "this concept belongs to that model" - the one `navigation`
entry, and the reasoning behind its default. Read this when a membership template is
refused, or when deciding whether your store can claim the folder walk.

## The field

Optional. How this dataset expresses a traversal that many templates need, so a
template can ask for the traversal and the dataset decides what it means. One entry
is defined:

```yaml
navigation:
  model_membership:
    mode: direct-predicate        # or same-graph-colocation, or bounded-folder-tree
    max_depth: 3                  # bounded-folder-tree only; 1..6
```

| Mode | Pattern | Use when |
|---|---|---|
| `same-graph-colocation` | A concept in a model's semantic graph belongs to that model. | Output from a converter predating `arch:partOfModel`. Needs named graphs, and needs the model declared in that same graph. |
| `bounded-folder-tree` | Walk the `part_of` role up through folders to the model. | A store that authors the folder chain for every element, and any dataset with no named graphs. Needs `part_of` bound; the profile is rejected otherwise. |
| `direct-predicate` | One hop along `part_of_model`. | Converter output. **Default.** Needs `part_of_model` bound; the profile is rejected otherwise, because the mode *is* that predicate. |

### direct-predicate supersedes both others where it exists

One hop, on every concept, needing neither named graphs nor a complete folder chain. It
is not the default only because a pre-1.3 dataset does not carry the edge — check with
`la-profile recommend`, which names the predicate it found — `arch:inModel` in current output,
or the deprecated `arch:partOfModel` in a dataset converted before core 0.4.0.

Note what this mode deliberately does **not** emit: `?model a <model_class>`. In the
layout that carries the edge, the model resource lives in `graph/model` rather than in
the semantic graph, and the membership pattern is injected inside whatever `GRAPH` scope
the template opened — so a class test would be evaluated in the wrong graph and match
nothing. The edge already identifies the model. The other two modes keep the class test
because for them it is the only thing that does.

This corrects an earlier decision made on stale evidence. Co-location was chosen as the
default partly because the fixtures then available showed no usable chain to a model;
those fixtures turned out to predate the emitters, and the real converter contract is
this direct edge. Co-location remains right for the datasets it was measured against.

Co-location is a statement *about named graphs*, so on a profile with
`named_graphs: false` — flattened Turtle — it cannot be expressed at all: the pattern
reduces to "this is a model", which is true of every model in the dataset. Templates
declaring membership are refused there, naming `bounded-folder-tree` as the way out.
That refusal was added after measuring the alternative: against the flattened fixture
the co-location pattern returned a LeanIX element attributed to the Backstage
catalogue. A wrong answer is worse than a refusal.

Templates consume this as `{{MEMBERSHIP:element}}`, which binds `?model` for
`?element`. Both modes bind the same variables, so a template never branches on the
mode.

The default is co-location because the folder chain is **not uniformly emitted**: it
is present for BPMN elements but stops at `folder/Elements` for C4 (measured; recorded in
the repository's `PROPOSAL.md` Appendix A7). A dataset declaring `bounded-folder-tree` when parts of it lack the
chain returns rows for the part that has it and silently nothing for the rest, which
is the more expensive failure — so this is a claim to make only once `verify` and a
spot check agree.

`max_depth` is a cap, not a hint: the rendered path is a capped alternation
(`p`, `p/p`, `p/p/p`), because SPARQL 1.1 has no `{1,n}` range and an unbounded `+`
turns one wrong hop into a whole-dataset scan. The ceiling is 6.
