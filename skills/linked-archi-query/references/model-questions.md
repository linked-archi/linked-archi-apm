# Model questions

The published question sets - core, ArchiMate 4.0 and ArchiMate 3.2 - are catalogue
entries alongside the templates. Load this when you select or run a question marked `Q` or
`Q+T`, select by stakeholder concern, or join a project's own question set.

Entries marked `Q` in `catalog list` are model questions from the published question sets
(core, ArchiMate 4.0, ArchiMate 3.2): what is asked, what a row means, what it does not
prove, and the stakeholder concerns it informs. `Q+T` also has a template of that name:
`query run` asks the question where the dataset fits it and runs the template elsewhere,
and the envelope's `implementation` says which answered.

- A question reads the dataset as **one graph**. `query run` arranges that on local data;
  an endpoint takes it only when the profile declares `capabilities.union_default_graph`.
  `query render` gives the template where one fits a profile with named graphs.
- What its query reads is gated like a template's `requires` (direct triples,
  `rdf:reifies`, `arch:inModel`). One reading the metamodel is checked when it runs, and
  refused - naming the published Turtle to pass with another `--data` - when that is
  not loaded, unless its template can answer instead.
- Select by concern: `catalog concerns`, then `catalog list|dump --concern NAME`. A
  project's own question set joins with `--catalog questions.ttl` (needs pyoxigraph),
  under a project namespace like a project template.
