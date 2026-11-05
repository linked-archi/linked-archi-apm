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
