# Viewpoint selection

Triggers: which viewpoint, what viewpoint, choose a viewpoint, suitable viewpoint,
viewpoint catalog, viewpoint library, capability map viewpoint.

Start with `core/viewpoint-catalog`, which lists **prescribed** viewpoints from
attached vocabulary and their scheme, category and definition. Review which
catalog belongs to the model's notation and version;
do not select by a matching label alone. Use a reviewed `VIEWPOINT_IRI` with
`core/viewpoint-detail` to inspect its allowed element classes, stakeholders,
purposes and view types. Compare those declarations with the question's audience
and concern. `core/views` separately reports **actual model views** and their
`viewConformsToViewpoint` assertions; it does not choose a viewpoint.

The catalog must be attached under `vocabulary`. A manifest reference or a
profile entry does not fetch it. If no catalog is attached, stop or acquire the
published document explicitly. A declared palette is guidance, not proof that an
actual view meets it; use `linked-archi-validate` with the matching viewpoint
SHACL shapes for conformance.

Templates: `core/viewpoint-catalog`, `core/viewpoint-detail`, `core/views`.

## Stop when

- the matching viewpoint catalog is not attached — a missing option is not a negative finding;
- stakeholder, purpose or allowed classes do not fit the stated question — do not recommend by label alone;
- viewpoint guidance or a `viewConformsToViewpoint` assertion is not SHACL conformance.
