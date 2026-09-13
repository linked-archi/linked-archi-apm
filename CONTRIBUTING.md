# Contributing

Issues and merge requests are welcome at
<https://github.com/linked-archi/linked-archi-apm>.

## Before you start

```bash
pip install PyYAML pyoxigraph
make check          # skill validation, then the full test suite
```

`make check` is what CI runs. It must pass before and after your change.

## The rules the suite enforces

These are not style preferences — the tests fail on them, and each exists because the
failure mode it prevents is silent rather than loud.

**No template names a vocabulary term.** Templates name *roles*; the profile binds roles to
IRIs. A `PREFIX` line in a template is how a whole library ends up querying a namespace that
does not exist while every query still parses. Pinned by
`test_no_template_carries_its_own_prefixes`.

**Every catalogued template has a fixture case.** Add a template and you add a case to
`tests/test_templates.py`, or the build fails. A template nobody runs is a template nobody
knows is broken.

**A gated template declares `requires:` and names an alternative.** If a template needs a
capability the dataset may not have, it must say so and point somewhere useful. A refusal an
agent can act on beats an empty result it cannot distinguish from a fact.

**No capability claim before the runtime provides it.** See decision D18 in
[PROPOSAL.md](PROPOSAL.md). A claim written ahead of its implementation is indistinguishable
from one whose implementation regressed.

**Strict per-skill ownership.** Runtime code and assets live only in the skill that owns
them. No shared library, no generated copies, no cross-skill imports — companions talk over
versioned JSON subprocess contracts. Fifteen packaging tests enforce this.

**Fixtures are extracted, not authored.** `fixtures/` comes from real converter output via
`make fixtures`. An authored fixture is written to satisfy the queries under test, so it
cannot detect a wrong vocabulary. If you need new fixture coverage, extract it.

## Scope of a change

One concern per merge request, with the reasoning in the commit message rather than only in
the diff. If your change alters what the package promises — a `SKILL.md` contract, a machine
contract under a skill's `references/`, a bundled profile, or the template catalogue — say so,
and record *why* in the commit message and in [PROPOSAL.md](PROPOSAL.md).

## Documentation

Prose is part of the package. `PROPOSAL.md` is the design record and decision log; amend it
rather than silently contradicting it. Every documented command is checked for executability
by the packaging tests, so an example that cannot run fails CI.

## Licence

Contributions are accepted under [Apache-2.0](LICENSE), the licence this package ships under.
