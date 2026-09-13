# Profile machine contract

`la-profile _machine` is the stable boundary for automation and sibling orchestration.
The leading underscore marks it as **machine-facing, not private**: it is documented,
versioned, and `linked-archi-query` depends on it for every single query it renders.
Human-facing output belongs to `list`, `show`, `resolve`, `derive` and `verify`.

One JSON object on stdin, one JSON object on stdout, diagnostics on stderr. The contract
is `schema_version: 1`, checked exactly.

## Commands

| Command | Purpose |
|---|---|
| `la-profile _machine resolve` | Resolve a profile reference to its full snapshot |

One operation, because resolution is the only thing another skill needs from this owner.
`verify` is deliberately absent: it needs a dataset and a transport, so a caller that can
verify can also call `verify` directly and read its exit code.

## Request

```bash
printf '%s' '{"schema_version": 1, "profile": "examples/curated-store"}' \
  | python3 scripts/la-profile _machine resolve
```

| Field | Rule |
|---|---|
| `schema_version` | Required, exactly `1`. |
| `profile` | Optional non-empty string. Omitted means `linked-archi-default`. |

The reference resolves the same way as `--profile` on the human commands: a path if it
looks like one, then a bare bundled name, then `examples/<name>`. There is no separate
machine lookup order, because two lookup orders is how a caller and a human end up
reading different files while naming the same profile.

## Response

The resolved snapshot — the same object `la-profile resolve` prints, on one line. Exactly
these keys:

```json
{
  "schema_version": 1,
  "name": "linked-archi-default",
  "version": 1,
  "description": "Converter output with default flags: ...",
  "base_iri": "https://example.org/la/",
  "source": "/abs/path/skills/linked-archi-profile/assets/profiles/linked-archi-default.yaml",
  "namespaces": {"arch": "https://meta.linked.archi/core#"},
  "graphs": {
    "layout": "per-model-triple",
    "named_graphs": true,
    "roles": {"semantic": "graph/semantic", "views": "graph/views",
              "provenance": "graph/provenance", "validation": null},
    "required": ["semantic"],
    "descendants": []
  },
  "fingerprint": "3f9a1c72b48e05d6",
  "roles": {
    "label": ["http://www.w3.org/2004/02/skos/core#prefLabel"],
    "native_id": ["http://www.w3.org/2004/02/skos/core#notation",
                  "https://meta.linked.archi/bpmn/onto#id"],
    "owner": null
  },
  "capabilities": {"direct_rel_triples": false, "views_graph": "partial",
                   "label_language": "en"},
  "notations": {"bpmn": {"label": "BPMN 2.0", "namespace": "bpmn",
                         "metamodel": "https://meta.linked.archi/bpmn/metamodel#BPMN2",
                         "native_id": "bpmn:id"}},
  "taxonomies": [{"scheme": "https://meta.linked.archi/core-tax",
                  "prefix": "arch-tax", "label": "Linked.Archi common taxonomy"}],
  "navigation": {"model_membership": {"mode": "same-graph-colocation", "max_depth": 3}},
  "limits": {"default_row_limit": 200, "max_row_limit": 5000, "timeout_ms": 30000}
}
```

Note the names: the profile's identity is `name` and `version` here. A consumer that
records them in a result envelope may of course call them something else — the query owner
records them as `profile_id` and `profile_version` — but on this wire they are `name` and
`version`.

What a caller may rely on:

- **`extends` is already applied.** The snapshot is the merged result, so a consumer never
  reads a second file or re-implements the merge rules. This is the reason the contract
  exists rather than callers parsing YAML: PyYAML would otherwise become a dependency of
  every skill, and the merge semantics would have as many implementations as consumers.
- **Roles are resolved to absolute IRIs, always as a list.** A single-term binding is a
  one-element list; a fallback chain keeps its order, and the first entry is what
  `{{ROLE:x}}` means. A role this dataset does not represent is `null` — a claim that it is
  absent, not a gap in the response. In `linked-archi-default` those are `owner`,
  `same_as` and `exact_match`.
- **Graph roles may be `null` too**, and mean the same thing: `validation` is null in the
  default profile because the converters write a SHACL report as a document, never as a
  graph in the dataset.
- **`graphs.required` lists the roles whose absence is an error**, and
  **`graphs.descendants` the roles whose suffix also matches graphs below it.** A role in
  `descendants` is scoped as
  `STRENDS(?g, "SUFFIX") || CONTAINS(?g, "SUFFIX/")` — the trailing slash keeps it a path
  test. That expression is the contract: the profile owner probes with it and a consumer
  must render with it, or `verify` will pass while every scoped query returns nothing.
  Both keys may be absent in a snapshot from an older owner; treat that as `[]`.
- **`fingerprint` identifies what the profile currently SAYS.** A digest over
  `schema_version`, `base_iri`, `namespaces`, `roles`, `graphs`, `capabilities`,
  `notations`, `taxonomies` and `navigation` — everything that changes what an answer
  means. Deliberately excludes `version` (hand-maintained, so it cannot be trusted to
  change when the meaning does), `source` (an absolute path, useless across machines),
  `description` (prose) and `limits` (they bound a result's size, not its meaning).

  Use it, not `version`, to key anything that must stop being valid when the profile
  changes. The verification marker does: keying it on `version` meant that editing what a
  profile claimed without bumping the integer left an old marker vouching for the new
  claims. Recompute nothing — read the published value, so producer and consumer cannot
  disagree.
- **`capabilities` values are `true`, `false`, `"partial"`,** or a language tag for
  `label_language`. `"partial"` is a third state, not a soft `true`: it means present for
  some models and absent for others, so a short result may be coverage rather than absence.
- **`navigation.model_membership`** always carries `mode` and `max_depth`, defaulted and
  validated, so a consumer never has to decide what an absent navigation block means.
- **`source` is the one machine-specific field.** It is the absolute path the profile was
  loaded from, useful in a diagnostic and meaningless on another host. Compare `name` and
  `version` to decide whether two snapshots are the same profile; never diff the whole
  object.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | A snapshot was written to stdout. |
| `2` | Malformed request, unknown or invalid profile, unresolvable companion. Message on stderr, no traceback. |

Exit `1` is not used by `_machine resolve`. It *is* used by `verify`, where it means
**drift was found** — a claim in the profile is false about the dataset. That difference is
deliberate: resolution either produces a profile or fails, while verification produces a
report whose findings are the point.

## Versioning

`schema_version` is checked exactly, on both sides, and describes **this wire format**.
`version` is a different number with a different job: it identifies the *content* of one
profile, travels into query envelopes, and is bumped by whoever edits a binding. One can
change without the other, which is the point of keeping them separate.

Fields may be added within `schema_version: 1` only while every documented field keeps its
meaning. Anything that changes an existing field's meaning gets a new version, and a
caller receiving an unexpected version must stop rather than guess.
