# Security

## Reporting

Report suspected vulnerabilities **privately**, through GitHub's security advisories:
[open a draft advisory](https://github.com/linked-archi/linked-archi-apm/security/advisories/new).
That keeps the report private until a fix is published, and gives us a place to coordinate with
you. Please do not open a public issue for anything exploitable.

If advisories are unavailable to you for any reason, email the maintainer rather than filing
publicly.

Include what you ran, what happened, and what you expected. A reproducing dataset or query is
worth more than a description.

## What this package does with your data

Worth stating plainly, because it decides what a vulnerability here could mean.

**Queries are read-only, enforced before execution.** Every query passes a checker that
refuses SPARQL update forms, and that check lives in the query owner rather than being
duplicated. Only `linked-archi-query` executes anything; `linked-archi-analyse` plans and
bundles and contains no execution path, which is asserted by a test that greps its runtime for
transport and SPARQL keywords.

**Parameters are typed and escaped, never substituted.** User input is validated against a
declared type and quoted. Raw string substitution into a query is the injection route and is
not used anywhere.

**Nothing is transmitted.** Local execution runs in-process against files you name. Endpoint
execution talks only to the endpoint you configure. No telemetry, no analytics, no outbound
call the operator did not ask for.

**Remote acquisition is fail-closed and bounded.** `linked-archi-source` fetches over verified
HTTPS or from a pinned Git revision, with host allow-lists, size and time limits, SHA-256
content addressing and a written manifest. It refuses rather than guessing. An optional GitLab
MCP handoff is read-only and agent-mediated; no MCP server is required, and the package never
asks for repository credentials of its own.

**Executable code you install.** The skills ship Python that your agent runs locally. Read it
before installing if that matters to you — that is the point of shipping a committed tree
rather than a build artifact. There is no install-time code generation, no post-install hook,
and no `bin/` deployed onto an agent's PATH.

## Supported versions

The latest released version receives fixes. Given the current version, expect a patch release
rather than a backport.

| Version | Supported |
|---|---|
| 0.1.x | yes |
