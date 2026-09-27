# CLI reference

Six executables, one per skill. Each is invoked as `python3 <skill>/scripts/<name>`; the paths below
are relative to the installed skill directory.

Every skill has a `doctor` that reports where it is, which companions it resolved and what is
missing. Companion resolution is `$LINKED_ARCHI_SKILLS_DIR` (authoritative), then the sibling
directory, then `PATH` — never a filesystem search.

## la-source

```
la-source url <uri> [policy]
la-source git <repository> --ref REV --path PATH [--path PATH ...] [--sha256 [PATH=]DIGEST ...] [policy]
la-source gitlab-mcp --project ID --ref REV --path PATH --sha256 DIGEST [--server-id ID] [policy]
la-source complete <request_id> --reported-commit SHA [--cache-dir DIR] [--json]
la-source doctor [--cache-dir DIR]
la-source _machine {resolve,complete}
```

Policy flags, shared by `url`, `git` and `gitlab-mcp`: `--cache-dir DIR`, `--timeout-ms MS` (30000),
`--max-bytes N` (104857600), `--allowed-host HOST` (repeatable), `--allow-private-network`,
`--allow-ssh`, `--offline`, `--lenient`, `--json`.

`url` also takes `--format FMT`, `--sha256 DIGEST`, `--token-env VAR`. Formats: `json-ld`, `n-quads`,
`n-triples`, `n3`, `rdf-xml`, `trig`, `turtle`.

## la-connect

```
la-connect datasets [directory] [--include-fixtures] [--no-git] [--search-dir DIR ...]
                    [--max-depth N] [--extension EXT ...]
la-connect connect <target>
la-connect doctor
la-connect _machine {execute,execute-many}
```

## la-profile

```
la-profile list
la-profile show    [--profile NAME_OR_PATH] [--json]
la-profile resolve [--profile NAME_OR_PATH]
la-profile verify  [--profile NAME_OR_PATH] <target> [--all] [--emit-fix]
la-profile recommend <target>
la-profile derive <name> [--type-mapping FILE] [--metamodel FILE] [--base-iri IRI]
                         [--notation SLUG] [--extends PROFILE] [-o FILE]
la-profile doctor
la-profile _machine resolve
```

## la-query

```
la-query catalog list [--profile P] [--why] [-o FILE]
la-query catalog show <template> [--profile P] [--source] [-o FILE]
la-query catalog dump [--profile P] [--template NAME ...] [--stage STAGE ...]
                       [--notation NAME ...] [-o FILE]
la-query query render <template> [--profile P] [--set NAME=VALUE ...] [--force] [-o FILE]
la-query query run <template> [--profile P] <target> [--set NAME=VALUE ...]
                              [--format {tsv,md,json}] [--json] [--limit N] [-o FILE] [--preview]
la-query query literal (--query SPARQL | --file FILE) [--profile P] <target>
                              [--format ...] [--json] [--limit N] [-o FILE] [--preview]
la-query query batch <manifest> [--profile P] <target> [-o FILE] [--preview] [--limit N]
la-query lint [file] [--query SPARQL] [--profile P] <target> [-o FILE]
la-query doctor [-o FILE]
la-query _machine lint
```

`catalog dump` filters are repeatable: values within one filter kind form a union, and different
kinds intersect. Select only relevant templates to reduce output while retaining their complete
metadata, profile refusals and caveats. The unfiltered dump and `schema_version: 1` payload remain
unchanged. Unknown template, stage or notation values fail explicitly.

For `query run` and `literal`, `--preview` requires `-o FILE` and a positive `--limit`; invalid
combinations fail before execution. The file remains the complete JSON envelope; stdout also gets
a bounded preview, including warnings, truncation and citation. Preview presentation uses TSV
regardless of `--format` or `--json`. `--limit` defaults to 100 displayed rows (CONSTRUCT previews:
physical output lines). It does not reduce query cost, change the query's own `LIMIT`, or truncate
the saved envelope.

For `query batch`, manifest `out` entries save per-query JSON envelopes; batch `-o FILE` saves the
run summary. `--preview` prints each result's bounded preview to stdout whether the summary is
saved or printed. It does not require batch `-o`. Without `--preview`, existing output is unchanged.

## la-validate

```
la-validate run --data FILE --shapes FILE [--ontology FILE ...] [--no-rdfs-reasoning]
                [--data-format FMT] [-r FILE] [--json] [--limit N]
la-validate report <file> [--data-format FMT] [--json] [--limit N]
la-validate doctor
la-validate _machine {validate,report}
```

`--data` and `--shapes` are both required and both repeatable.

## la-analyse

```
la-analyse plan [--question TEXT] [--mode PATTERN] [--list-patterns] [--profile P]
                [--data FILE ...] [--endpoint URL] [--budget N] [--steps-dir DIR]
                [--definitions] [--batch-dir DIR] [--json] [-o FILE]
la-analyse bundle --step FILE [--step FILE ...] [--question TEXT] [--findings FILE]
                  [--dataset-revision REV] [--markdown] [-o FILE]
la-analyse render --bundle FILE [-o FILE]
la-analyse doctor
la-analyse _machine {plan,bundle}
```

`--step` is required and order-significant.

Analyse owns question investigation and orchestration; `plan` opens no dataset and executes no
queries. Definition questions request term definitions automatically; `--definitions` also includes
them for other questions. `--batch-dir DIR` writes query-owned batch manifests for eligible
independent steps with concrete parameters. Follow each group's prerequisite and evidence-review
boundaries, and run the batch instead of its individual commands. Generated commands save complete
envelopes and print bounded previews; each query still counts toward the investigation budget.

## The target flags

Shared by `la-connect connect`, `la-profile verify|recommend`, `la-query query run|literal|batch`,
`la-query lint`:

| Flag | Default | Notes |
|---|---|---|
| `--data FILE` | `[]` | Repeatable. Files merge into one dataset with one identity. |
| `--endpoint URL` | — | Not combinable with `--data`. |
| `--timeout-ms MS` | `30000` | Ignored for local files. |
| `--lenient` | off | Relaxes RDF parsing only. |
| `--store {memory,cached,readonly,refresh}` | `memory` | Not on `la-analyse`, which opens nothing. |

## Environment variables

| Variable | Read by | Effect |
|---|---|---|
| `LINKED_ARCHI_DATA` | connect, profile, query | The dataset when no `--data`/`--endpoint`. `os.pathsep`-separated. |
| `LINKED_ARCHI_SKILLS_DIR` | all | Authoritative companion root. When set, never falls back. |
| `LINKED_ARCHI_STORE` | connect, query | Store mode when `--store` is unset. |
| `LINKED_ARCHI_STORE_CACHE` | connect | Store cache root. Falls back to `$XDG_CACHE_HOME`. |
| `LINKED_ARCHI_STORE_KEEP` | connect | Stores kept per root. Default 3. |
| `LINKED_ARCHI_STORE_MAX_BYTES` | connect | Byte budget for eviction. |
| `LINKED_ARCHI_SPARQL_TOKEN` | connect | Bearer token for an endpoint. |
| `LINKED_ARCHI_SOURCE_CACHE` | source | Source cache root. |
| `LINKED_ARCHI_STATE_DIR` | profile, analyse | Verification markers. Default `~/.cache/linked-archi/verified`. |
| `LINKED_ARCHI_LOCAL_DEADLINE_S` | profile, query | Seconds ceiling on local execution. Default 300. `none`/`0`/`off` opts out. |
| `LINKED_ARCHI_LOCAL_MAX_RSS_MB` | query | Memory ceiling, scaled by input size. |

## The machine contracts

Every skill exposes `_machine`, which reads one JSON object on stdin and writes one on stdout, with
diagnostics on stderr. `schema_version` is checked exactly — a mismatch is refused rather than
guessed at. These are how the skills call each other, and they are documented rather than private:
`la-profile` reaches `la-connect _machine execute-many` to run a probe batch in one round trip, and
`la-connect` reaches `la-query _machine lint` to enforce read-only at the boundary.
