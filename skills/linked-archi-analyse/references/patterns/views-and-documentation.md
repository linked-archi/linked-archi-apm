# Views and documentation

Triggers: which diagram shows, where is this drawn, is this documented, what is new in this
view.

`core/views` to find the diagrams, `core/view-contents` for what one diagram places, and
`core/view-usage` for the inverse — which diagrams show a given element. "What is new here"
is `core/view-diff`, with `DIRECTION` set to `a-only`, `b-only` or `symmetric`; running
`core/view-usage` over a handful of suspected elements answers the same question but can only
find what you already suspected.

The views graph is absent whenever a source carried no diagrams, which is always for
Backstage and LeanIX, so an empty result may mean "this notation has no diagrams" rather than
"this element is undrawn".

It is also absent when a dataset was published with `--views-profile no-views` or `no-diagrams`,
and that case has a remedy: `core/view-contents-semantic` and `core/view-usage-semantic` read
`arch:inView` in the semantic graph, which survives both profiles. Before concluding an element is
undrawn, check whether the views graph exists at all — `core/inventory` lists the named graphs. If
`arch:View` resources are present but no views graph is, the diagrams exist and only their contents
were dropped, so use the semantic pair rather than reporting nothing.

Diagram membership is an editorial choice. Appearing on many diagrams does not make an
element central, and appearing on none does not make it unimportant.

## Stop when

- the notation carries no diagrams at all. Report that, rather than reporting an empty
  result as an absence of documentation;
- a difference between two diagrams has been found. That is not yet a difference in the
  architecture: an element missing from one may have been removed, may never have been
  drawn, or may sit on a third diagram nobody named.
