# Related work

This package is a text-to-SPARQL system that mostly does not generate SPARQL. That is unusual
enough to be worth placing against the published approaches it borrows from, and honest about
which of their ideas are actually implemented here.

Three lines of work are relevant: ontology-based checking of a generated query, retrieval of
schema metadata to ground generation, and agentic exploration of an unfamiliar graph.

## At a glance

| | Generation strategy | Correctness mechanism | Assumes |
|---|---|---|---|
| **OBQC** ([2405.11706](https://arxiv.org/abs/2405.11706)) | LLM writes SPARQL | check against ontology axioms, then LLM repair | ontology with usable domain/range |
| **SPARQL-LLM** ([2410.06062](https://arxiv.org/abs/2410.06062), [2512.14277](https://arxiv.org/abs/2512.14277)) | LLM writes SPARQL, RAG over examples + schema | validate against endpoint schema, correct | endpoints publish rich metadata |
| **SPINACH** ([2407.11417](https://arxiv.org/abs/2407.11417)) | agent explores and executes iteratively | the agent's own observation of results | little; discovers the schema |
| **ARUQULA** ([2510.02200](https://arxiv.org/abs/2510.02200)) | as SPINACH, generalised with ReAct + exploration tools | same, plus tool feedback | little; portable across graphs |
| **Linked.Archi APM** | routes to a tested template; renders roles via a profile | the profile gates before running; refusal instead of empty rows | graph came from known converters against a published ontology |

The bottom row is a narrower assumption than any of the others, and the whole design exploits it.
When the graph is converter-generated against an ontology you control, the failure modes are
enumerable in advance — so they can be encoded once in a template library and a profile, rather
than rediscovered per question.

## OBQC: implemented without the repair loop

[Allemang & Sequeda](https://arxiv.org/abs/2405.11706) observed that inaccurate LLM-generated
SPARQL tended to follow paths the ontology does not permit, and proposed two components: an
Ontology-based Query Check that reads the ontology to decide whether a generated query is
semantically possible, and an LLM Repair step that feeds the check's explanation back to the model.
Reported accuracy on their benchmark rose to 72%, of which 8% were explicit "I don't know" answers,
leaving a 20% error rate. *(Figures from the paper's abstract; content paraphrased for licensing
compliance.)*

The check is implemented here, in
`skills/linked-archi-query/scripts/linked_archi_query/constraints.py` and `paths.py`, and reached
through `la-query lint`. It applies three rules over a constraint table — `source`, `target` and
`pair` — walking the class hierarchy so a superclass declaration is not judged against a subclass
rule.

A query the metamodel forbids, caught before it runs:

```console
$ python3 scripts/la-query lint bad.rq --profile curated-store \
    --data fixtures/augmented.trig --data fixtures/shapes.ttl --data fixtures/vocabulary.ttl
OK: read-only (bad.rq)
paths: 1 impossible path(s) in 1 checked
  ! ownedBy may not point at Component; permitted: Group, User
  caveat: verdicts assume each attached shape document is whole. Only the presence of every declared shape namespace could be verified - one shape of 28 would pass that test - so a partial attachment can still produce a wrong verdict
```

And the sound version of the same query:

```console
$ python3 scripts/la-query lint good.rq --profile curated-store \
    --data fixtures/augmented.trig --data fixtures/shapes.ttl --data fixtures/vocabulary.ttl
OK: read-only (good.rq)
paths: 1 pattern(s) checked, all permitted
  caveat: verdicts assume each attached shape document is whole. Only the presence of every declared shape namespace could be verified - one shape of 28 would pass that test - so a partial attachment can still produce a wrong verdict
```

The caveat rides on the clean verdict too, deliberately. It qualifies the basis of the judgement,
not its outcome.

Two deliberate departures from the paper.

**There is no repair loop.** Where OBQC feeds the error explanation to an LLM to rewrite the query,
this routes to a template that was already tested. Repair improves a query nobody has validated;
routing avoids needing one. The tradeoff is real — a question no template covers gets a refusal
here, where OBQC would attempt a repair — and it is the same tradeoff that makes every answer
citable by query hash.

**Verdicts are three-valued, not pass/fail.** The check reports "not checked" with a reason
whenever a verdict would be guesswork:

```console
$ python3 scripts/la-query lint bad.rq --profile linked-archi-default --data fixtures/base.trig
OK: read-only (bad.rq)
paths: not checked: no relationship constraints are attached
```

```
paths: not checked: no pattern in this query could be judged
  ~ accesses: the shapes attached for this notation are not known to be complete, so a missing rule cannot be told from a prohibition
```

That distinction matters more here than in the paper's setting. A missing rule and a prohibition are
opposite claims, and a checker that conflates them reports violations it cannot support. `paths.py`
also declines to judge `?s a arch:Element` against notation-class constraints, because converter
output dual-types every element — judging anyway produced false positives on this package's own
fixtures, which is worse than having no check. The paper's 8% "I don't know" bucket is the same
instinct applied to answers rather than to checks.

One thing this implementation needs that the paper does not: relationships here are reified, so
domain and range say nothing until the qualified class is bridged to its direct predicate. That is
`arch:unqualifiedForm`, and `constraints.py` refuses outright when the profile does not bind it,
rather than producing an empty constraint table that would find no violations and read as a clean
bill of health.

## SPARQL-LLM: the same premise, a different generation strategy

The SIB group's [SPARQL-LLM](https://github.com/sib-swiss/sparql-llm) grounds generation in
metadata the endpoints already publish — query examples and schema descriptions — retrieved per
question, with a validation step that corrects the generated query before it runs. It runs as a
public chat service over federated bioinformatics graphs, and the
[2025 paper](https://arxiv.org/abs/2512.14277) reports a 24% F1 gain on a shared challenge along
with substantially lower latency and cost per question than comparable systems.

The shared premise is the important part: schema metadata beats unaided generation, and validation
belongs before execution rather than after a confusing result. This package agrees on both and
differs on what gets generated. Instead of retrieving examples to condition a model, it ships
thirty-nine templates whose parameters are typed and whose vocabulary is bound by
[profile](concepts/profile.md) roles at render time. Validation is the fallback path for a
hand-written query, not the main one.

Where SPARQL-LLM is the better fit: a federation whose endpoints publish good metadata, questions
too varied for a template library, and a need to answer anything a user might ask. Where this
package is: a bounded domain where the same twenty questions recur, and the cost of a plausible
wrong answer is high enough that "no template covers this" is a better outcome than a guess.

## SPINACH and ARUQULA: exploration, bounded

[SPINACH](https://arxiv.org/abs/2407.11417) treats query writing as iterative exploration and
execution rather than one shot, imitating how an expert works through an unfamiliar graph, and
reports state-of-the-art results across several QALD benchmarks.
[ARUQULA](https://arxiv.org/abs/2510.02200) generalises it with a ReAct loop and a set of graph
exploration utilities, making the approach portable across knowledge graphs.

The premise — do not assume a schema you have not looked at — is one this package shares and
enforces harder than most, since [orientation](templates.md#orientation) is mandatory and absence
cannot be reported without it. The difference is how much freedom the looking gets. Exploration
here runs through three tested [discovery](templates.md#discovery) templates rather than an open
agent loop, which caps both the cost and the variance: the flow in
[Answering a question](answering-a-question.md) is four queries, and it is four queries every time.

That cap is the tradeoff, and it cuts both ways. Agentic designs handle questions no template
anticipated, at a cost in latency that other work measures directly: the
[GRISP paper](https://arxiv.org/abs/2604.21133) reports its own generate-then-retrieve method
averaging 2.3 to 14 seconds per question and being *much faster than current agentic methods*,
while also finding those agentic methods ahead on the hardest low-training-data benchmarks. A fixed
library cannot answer the unanticipated question at all — it refuses and says which template comes
closest.

Where SPINACH and ARUQULA fit best: open graphs such as Wikidata, where the schema genuinely must
be discovered per question and no one controls how the data was produced. That is the opposite of
the situation here, where the converters, the ontology and the shapes are all known in advance.

## What this package adds

Little of the machinery is novel. The check is OBQC's, the schema-grounding instinct is
SPARQL-LLM's, the do-not-assume-the-schema discipline is SPINACH's. Three things are specific:

**Refusal as a first-class result.** Exit 1 with named alternatives, rather than an empty table.
The published systems mostly optimise for answering; this one treats "this dataset cannot support
that question" as an answer worth returning. See [Evidence and refusal](concepts/evidence.md).

**A profile as a separate, verifiable artifact.** The vocabulary binding is not in the prompt or
the template — it is a file that can be checked against the data with `la-profile verify`, and
whose staleness is reported in every result footer until it is re-checked.

**Provenance attached to the answer, not the session.** Every result carries the template, the
query hash, the dataset and the profile version, so a claim made from it stays traceable after the
conversation ends.

The assumption that buys all three is the narrow one in the table above. Point this at a
hand-authored graph outside the Linked.Archi converters and it degrades toward the others: the
profile has to be derived rather than trusted, most templates become unavailable, and `la-query
lint` turns from a fallback into the primary path — which is the case the three-valued verdicts
were built for.
