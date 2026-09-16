"""Query owner CLI; companion skills are invoked only through JSON subprocesses."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from . import verification
from .catalog import CatalogError, load_catalog
from .contract import ContractError, ResolvedProfile
from .envelope import Envelope
from .render import RenderError, UnsupportedTemplate, render, render_literal
from .validate import QueryError, validate_readonly

OK, REFUSED, ERROR = 0, 1, 2

#: `_machine` is machine-facing, NOT private. The underscore says "not for a human to
#: type", and nothing more: the contract is documented, versioned, and depended on across
#: process boundaries by sibling skills. Hiding it from `--help` while three skills call it
#: was the worst of both worlds - visible in the usage line as `==SUPPRESS==` and explained
#: nowhere.
_MACHINE_HELP = "versioned JSON contract for automation (see references/machine-contract.md)"
_MACHINE_DESCRIPTION = (
    "Read one JSON object on stdin, write one JSON object on stdout. Diagnostics go to "
    "stderr. schema_version is checked exactly. This is a stable, documented boundary for "
    "sibling skills and automation, not a private entry point: skills/linked-archi-query/references/machine-contract.md"
)

DEFAULT_PROFILE = "linked-archi-default"

#: Store modes, restated rather than imported. This owner reaches linked-archi-connect
#: over the machine contract as a subprocess and imports nothing from it, so importing a
#: constant here would create the coupling that boundary exists to prevent. The cost of
#: restating is that this list can fall behind; the protection is that connect validates
#: the field itself and refuses an unknown mode by name, so the failure is a clear
#: message rather than a silently ignored setting. `store` is null-by-default on the
#: wire, meaning "defer to $LINKED_ARCHI_STORE in the connect process".
_STORE_MODES = ("memory", "cached", "readonly", "refresh")


class CompanionError(RuntimeError):
    pass


_RAW_RESULT_KEYS = {
    "schema_version", "form", "variables", "rows", "boolean", "triples",
    "elapsed_ms", "dataset_id", "named_graphs_present", "description",
}


def _validate_raw_result(raw: object) -> dict[str, Any]:
    """Fail closed on malformed schema_version=1 transport evidence."""
    if not isinstance(raw, dict):
        raise CompanionError("linked-archi-connect returned a malformed raw result: expected an object")
    missing = sorted(_RAW_RESULT_KEYS.difference(raw))
    if missing:
        raise CompanionError(
            "linked-archi-connect returned a malformed raw result: missing "
            + ", ".join(missing)
        )
    if (
        not isinstance(raw["schema_version"], int)
        or isinstance(raw["schema_version"], bool)
        or raw["schema_version"] != 1
    ):
        raise CompanionError("linked-archi-connect returned an unsupported raw-result schema_version")

    form = raw["form"]
    variables = raw["variables"]
    rows = raw["rows"]
    boolean = raw["boolean"]
    triples = raw["triples"]
    if form not in {"SELECT", "ASK", "CONSTRUCT"}:
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid form")
    if (
        not isinstance(variables, list)
        or any(not isinstance(item, str) or not item for item in variables)
        or len(set(variables)) != len(variables)
    ):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid variables")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid rows")
    variable_names = set(variables)
    if any(
        set(row) != variable_names
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in row.items()
        )
        for row in rows
    ):
        raise CompanionError(
            "linked-archi-connect returned a malformed raw result: invalid SELECT bindings"
        )
    if boolean is not None and not isinstance(boolean, bool):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid boolean")
    if triples is not None and not isinstance(triples, str):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid triples")
    if (
        not isinstance(raw["elapsed_ms"], int)
        or isinstance(raw["elapsed_ms"], bool)
        or raw["elapsed_ms"] < 0
    ):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid elapsed_ms")
    # Optional, so absence is fine and only a present-but-wrong value is refused.
    # Kept out of _RAW_RESULT_KEYS on purpose: requiring it would reject every result
    # from a linked-archi-connect older than the store cache, which is a compatibility
    # break bought for a timing field.
    if "load_ms" in raw and (
        not isinstance(raw["load_ms"], int)
        or isinstance(raw["load_ms"], bool)
        or raw["load_ms"] < 0
    ):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid load_ms")
    if not isinstance(raw["dataset_id"], str) or not raw["dataset_id"].strip():
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid dataset_id")
    if raw["named_graphs_present"] is not None and not isinstance(raw["named_graphs_present"], bool):
        raise CompanionError(
            "linked-archi-connect returned a malformed raw result: invalid named_graphs_present"
        )
    if not isinstance(raw["description"], str):
        raise CompanionError("linked-archi-connect returned a malformed raw result: invalid description")

    if form == "SELECT" and (boolean is not None or triples is not None):
        raise CompanionError("linked-archi-connect returned an inconsistent SELECT result")
    if form == "ASK" and (variables or rows or not isinstance(boolean, bool) or triples is not None):
        raise CompanionError("linked-archi-connect returned an inconsistent ASK result")
    if form == "CONSTRUCT" and (variables or rows or boolean is not None or not isinstance(triples, str)):
        raise CompanionError("linked-archi-connect returned an inconsistent CONSTRUCT result")
    return raw


#: This skill's own name, used only to phrase the adjacency hint in an error.
OWN_SKILL = "linked-archi-query"


def _companion(skill: str, executable: str) -> Path:
    """Locate a sibling owner. One order, used identically by every owner here.

    1. ``$LINKED_ARCHI_SKILLS_DIR`` when set - **authoritative, and never falls back**.
       Someone who names an install root means that root; silently using a different
       generation of the skill found elsewhere is how two skill sets get mixed.
    2. the sibling directory beside this skill, which is how installed skill sets sit.
    3. the command on ``PATH``, for a packaged or symlinked install.

    Deliberately not a filesystem search. A missing companion is reported by name so the
    caller installs it, rather than going looking for it.
    """
    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    if configured:
        candidate = Path(configured).expanduser() / skill / "scripts" / executable
        if candidate.is_file():
            return candidate
        raise CompanionError(
            f"Missing required skill: {skill} under explicit "
            f"LINKED_ARCHI_SKILLS_DIR={configured}."
        )
    candidate = Path(__file__).resolve().parents[2].parent / skill / "scripts" / executable
    if candidate.is_file():
        return candidate
    on_path = shutil.which(executable)
    if on_path:
        return Path(on_path)
    raise CompanionError(
        f"Missing required skill: {skill}. Install it beside {OWN_SKILL}, put "
        f"{executable} on PATH, or set LINKED_ARCHI_SKILLS_DIR."
    )


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Where this owner is, and what it can reach.

    The first question is never about the graph, it is "where is the command and are its
    companions here". Unanswered, that becomes a filesystem search - one field session ran
    `find / -maxdepth 6` and timed out.
    """
    root = Path(__file__).resolve().parents[1]
    print(OWN_SKILL)
    print(f"  owner root:   {root.parent}")
    print(f"  command:      {root / 'la-query'}")
    print(f"  templates:    {len(load_catalog().names)} in {root.parent / 'assets' / 'templates'}")
    configured = os.environ.get("LINKED_ARCHI_SKILLS_DIR")
    print(f"  skills dir:   {configured or '(unset; resolving beside this skill)'}")
    data = os.environ.get("LINKED_ARCHI_DATA")
    print(f"  dataset env:  {data or '(unset)'}")

    ok = True
    for skill, executable, why in (
        ("linked-archi-profile", "la-profile", "resolves the profile for render and run"),
        ("linked-archi-connect", "la-connect", "executes against a dataset or endpoint"),
    ):
        try:
            print(f"  {executable:<12}  {_companion(skill, executable)}  ({why})")
        except CompanionError as exc:
            ok = False
            print(f"  {executable:<12}  MISSING - {exc}")
    print(
        "\nCatalogue browsing and lint work alone. Rendering needs the profile owner;\n"
        "execution additionally needs the connect owner. Resolution order is\n"
        "$LINKED_ARCHI_SKILLS_DIR (authoritative), then the sibling directory beside this\n"
        "skill, then PATH - never a filesystem search."
    )
    return OK if ok else REFUSED


#: Overrides the wall-clock ceiling on LOCAL query execution, in seconds. Set it to
#: `none` (or `0`) to opt out and allow an unbounded run, which is occasionally the right
#: call for a deliberate one-off against a very large graph - but it is then a choice
#: rather than the default.
ENV_LOCAL_DEADLINE = "LINKED_ARCHI_LOCAL_DEADLINE_S"

#: Five minutes. Deliberately far above `limits.timeout_ms`, because local execution is
#: legitimately slower than an endpoint's: no server-side optimiser, a cold parse of the
#: whole file, and `ORDER BY` forcing full materialisation before `LIMIT` applies. The
#: point is not to be tight, it is to be FINITE.
#:
#: On its own it is NOT enough, which is why the memory ceiling below exists. Measured on
#: a real 21 MB estate graph, a pathological two-hop query reached 22 GB resident in 60
#: seconds - roughly 360 MB/s - so a purely time-based ceiling would let it take the whole
#: machine into swap long before the clock ran out.
DEFAULT_LOCAL_DEADLINE_S = 300.0

#: Overrides the resident-memory ceiling for a LOCAL query, in MB. `none` opts out.
ENV_LOCAL_MEMORY_MB = "LINKED_ARCHI_LOCAL_MAX_RSS_MB"

#: Working room ABOVE the cost of holding the dataset, in MB. The ceiling is not a fixed
#: number because the floor is not fixed: an in-memory store costs what it costs, and a
#: fixed ceiling is therefore simultaneously too tight for a large graph and too loose for a
#: small one. Measured: a 112 MB / 1.4M-quad merged estate needs 1058 MB just to load, and
#: legitimate queries over it peak at about 1.0 GB - so a flat 2 GB would refuse real work
#: on it while allowing a 2 GB runaway against a 300 KB fixture.
WORKING_ROOM_MB = 2048

#: Resident megabytes to allow per megabyte of input. Measured at ~9.4 (112 MB of TriG ->
#: 1058 MB resident); rounded up for headroom across serialisations and notations.
LOAD_FACTOR_MB_PER_MB = 12

#: Kept as the floor a dataset-free or unmeasurable target gets, and what the tests pin.
DEFAULT_LOCAL_MAX_RSS_MB = WORKING_ROOM_MB

#: Why the parent enforces this rather than the OS: `RLIMIT_AS`, `RLIMIT_DATA` and
#: `RLIMIT_RSS` are all unsettable on macOS - `getrlimit` reports an unlimited soft limit
#: that `setrlimit` then refuses as "current limit exceeds maximum limit" - and `ulimit -v`
#: is unsupported. Verified, not assumed. Polling the child's RSS is the portable mechanism
#: and needs no second code path on Linux.
_RLIMIT_UNAVAILABLE = "macOS does not permit RLIMIT_AS/DATA/RSS to be set"

#: How often the watchdog samples the child. Coarse on purpose: this bounds runaway growth,
#: and sampling faster would cost more than it saves.
#:
#: It also sets the granularity of both ceilings, which is worth being explicit about: a
#: run that finishes inside one interval is never sampled and never stopped, whatever the
#: configured limits say. That is deliberate - work that has already completed should not be
#: thrown away - but it means these are bounds on runaways, not precise deadlines.
#:
#: And the memory ceiling OVERSHOOTS, unavoidably. A sampled bound cannot be a hard cap:
#: the child allocates between samples, and measured on a real graph it reached 5 GB against
#: a 2 GB ceiling at a 0.5s interval - roughly 3 GB inside one gap. Sampling five times a
#: second cuts that to well under a gigabyte for the same cost in `ps` calls, which is
#: negligible next to a query that was heading for 20 GB. A true cap would need
#: `RLIMIT_AS`, which macOS does not allow to be set at all.
#:
#: The refusal always reports the size actually observed, so the overshoot is visible rather
#: than implied.
_WATCHDOG_INTERVAL_S = 0.2


def _local_deadline() -> float | None:
    """The ceiling on a local query, or ``None`` when explicitly opted out."""
    raw = os.environ.get(ENV_LOCAL_DEADLINE)
    if raw is None or not raw.strip():
        return DEFAULT_LOCAL_DEADLINE_S
    text = raw.strip().lower()
    if text in {"none", "0", "off"}:
        return None
    try:
        seconds = float(text)
    except ValueError:
        raise CompanionError(
            f"{ENV_LOCAL_DEADLINE} must be a number of seconds, or 'none' to opt out; "
            f"got {raw!r}"
        ) from None
    if seconds <= 0:
        raise CompanionError(f"{ENV_LOCAL_DEADLINE} must be positive; got {raw!r}")
    return seconds


def _local_max_rss_mb(target: dict[str, Any] | None = None) -> int | None:
    """The resident-memory ceiling for a local query, or ``None`` when opted out.

    Proportional to the input, because holding the dataset is unavoidable cost and a query
    should be judged on what it adds to that. An explicit override is absolute: someone
    naming a number means that number, not that number plus the data.
    """
    raw = os.environ.get(ENV_LOCAL_MEMORY_MB)
    if raw is None or not raw.strip():
        return WORKING_ROOM_MB + LOAD_FACTOR_MB_PER_MB * _input_megabytes(target)
    text = raw.strip().lower()
    if text in {"none", "0", "off"}:
        return None
    try:
        megabytes = int(text)
    except ValueError:
        raise CompanionError(
            f"{ENV_LOCAL_MEMORY_MB} must be a whole number of MB, or 'none' to opt out; "
            f"got {raw!r}"
        ) from None
    if megabytes <= 0:
        raise CompanionError(f"{ENV_LOCAL_MEMORY_MB} must be positive; got {raw!r}")
    return megabytes


def _input_megabytes(target: dict[str, Any] | None) -> int:
    """Total size of the local inputs, in MB. Best effort: unreadable means 0.

    A missing or unstattable file must not fail the query here - it will fail with a proper
    message when the adapter tries to read it, and guessing a ceiling is not worth
    pre-empting that with a worse error.
    """
    if not isinstance(target, dict):
        return 0
    paths = target.get("data")
    if not isinstance(paths, (list, tuple)):
        return 0
    total = 0
    for path in paths:
        try:
            total += os.path.getsize(os.path.expanduser(str(path)))
        except OSError:
            continue
    return total // (1024 * 1024)


def _child_rss_mb(pid: int) -> int | None:
    """Resident size of ``pid`` in MB, or ``None`` if it cannot be read.

    No psutil: the whole package runs on the standard library plus pyoxigraph, and a
    watchdog is not worth changing that. Two readers instead, tried in order.

    ``/proc/<pid>/statm`` first, because it needs no subprocess and no packages. That is the
    case that matters: a slim container is where this runs, and ``ps`` is absent there —
    Debian ships it in ``procps``, which `python:*-slim` does not include. Reaching for
    ``ps`` first would leave the ceiling unenforced in exactly that environment, and
    undetectably so, because an unreadable RSS looks identical to a well-behaved child.

    ``ps`` second, for macOS and the BSDs, which have no ``/proc``.

    Returning ``None`` is the last resort rather than an error: a diagnostics gap must not
    fail a query. Keep it a last resort — if both readers fail, the bound stops being a bound.
    """
    try:
        fields = Path(f"/proc/{pid}/statm").read_text().split()
        # size resident shared text lib data dt, in pages. Field 1 is resident.
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    try:
        done = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout.strip()
    if not text.isdigit():
        return None
    return int(text) // 1024  # ps reports kilobytes


class _Exceeded(Exception):
    """A bounded run hit its ceiling. Carries what to say about it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _run_bounded(
    command: list[str], payload: str, deadline: float | None, max_rss_mb: int | None
) -> subprocess.CompletedProcess:
    """Run a companion, killing it if it outlives ``deadline`` or outgrows ``max_rss_mb``.

    Falls back to a plain ``subprocess.run`` when there is nothing to watch, so the common
    path keeps its simpler semantics and only the local query path pays for the watchdog.
    """
    if max_rss_mb is None:
        try:
            return subprocess.run(
                command, input=payload, capture_output=True, text=True, timeout=deadline
            )
        except subprocess.TimeoutExpired as exc:
            raise _Exceeded(
                f"{deadline:g}s companion deadline" if deadline is not None
                else "companion process"
            ) from exc

    started = time.monotonic()
    peak = 0
    with subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    ) as proc:
        first, exceeded = True, None
        while True:
            try:
                # The documented way to poll a child while still draining its pipes:
                # retry communicate() after a TimeoutExpired. Draining matters - a child
                # writing a large result would otherwise block on a full pipe and look
                # exactly like a runaway.
                stdout, stderr = proc.communicate(
                    input=payload if first else None, timeout=_WATCHDOG_INTERVAL_S
                )
                break
            except subprocess.TimeoutExpired:
                first = False
                rss = _child_rss_mb(proc.pid)
                if rss is not None:
                    peak = max(peak, rss)
                if rss is not None and rss > max_rss_mb:
                    exceeded = f"{max_rss_mb} MB memory ceiling (reached {rss} MB)"
                elif deadline is not None and time.monotonic() - started > deadline:
                    exceeded = f"{deadline:g}s companion deadline"
                if exceeded is None:
                    continue
                proc.kill()
                try:
                    proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:  # pragma: no cover - kill is reliable
                    pass
                raise _Exceeded(exceeded) from None
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _companion_deadline(request: dict[str, Any]) -> float | None:
    """The wall-clock ceiling for a delegated operation, or ``None`` for unbounded."""
    target = request.get("target")
    if not isinstance(target, dict):
        return 120.0
    timeout_ms = target.get("timeout_ms", 30000)
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
        raise CompanionError("target timeout_ms must be a positive integer")
    if target.get("data") and not target.get("endpoint"):
        # Local execution gets a GENEROUS ceiling, not no ceiling.
        #
        # This used to return None, reasoning that pyoxigraph has no query timeout so a
        # parent deadline would kill valid long queries. The objection was fair and the
        # conclusion was wrong: it traded a bounded failure for an unbounded one. Observed
        # in the field - one `core/dependents-qualified` against a 21 MB estate graph ran
        # for 49 minutes and reached 20 GB resident, with no message and no bound, until it
        # was killed by hand. A refusal after five minutes saying "narrow the scope" is
        # strictly better than swap pressure and silence.
        #
        # It is enforced HERE rather than in the adapter because this is the only place it
        # can be: the query is a blocking call into Rust, so nothing inside that process
        # can interrupt it. Killing the subprocess is the one available mechanism, and this
        # is the process boundary. `limits.timeout_ms` deliberately does not drive it - see
        # DEFAULT_LOCAL_DEADLINE_S - and `--timeout-ms` stays endpoint-only, as documented.
        return _local_deadline()
    if not target.get("endpoint"):
        return 120.0
    queries = request.get("queries")
    query_count = len(queries) if isinstance(queries, list) and queries else 1
    # One 30s lint contract plus process startup/result serialization margin.
    return 60.0 + query_count * timeout_ms / 1000.0


def _machine(skill: str, executable: str, operation: str, request: dict[str, Any]) -> dict[str, Any]:
    command = [sys.executable, str(_companion(skill, executable)), "_machine", operation]
    deadline = _companion_deadline(request)
    target = request.get("target")
    local = bool(
        isinstance(target, dict) and target.get("data") and not target.get("endpoint")
    )
    # Only local execution is watched for memory. An endpoint's work happens on the server,
    # so this process stays small however expensive the query is.
    try:
        done = _run_bounded(
            command,
            json.dumps(request),
            deadline,
            _local_max_rss_mb(target) if local else None,
        )
    except _Exceeded as exc:
        detail = exc.reason
        if local:
            # The advice has to name the two things that actually cause this, because
            # neither is guessable from the query text: LIMIT does not bound the WORK,
            # and a local run has no partial result to show.
            raise CompanionError(
                f"{skill} {operation} exceeded its {detail} and was stopped.\n"
                "This is a guardrail, not a failure of the data. A local query runs "
                "in-memory with no engine-side timeout, so an expensive one consumes "
                "RAM until something stops it.\n"
                "What usually causes it:\n"
                "  - ORDER BY, which materialises EVERY solution before LIMIT applies, so "
                "--limit bounds what you see and not what is computed.\n"
                "  - a join over a variable predicate or variable type, which multiplies "
                "when resources carry several types.\n"
                "What to do: narrow the scope (a tighter FOCUS_IRI, a specific graph "
                "role), drop ORDER BY, or query an endpoint that can plan the join.\n"
                "To allow a bigger run deliberately, raise "
                f"{ENV_LOCAL_MEMORY_MB} (MB, default {DEFAULT_LOCAL_MAX_RSS_MB}) or "
                f"{ENV_LOCAL_DEADLINE} (seconds, default {DEFAULT_LOCAL_DEADLINE_S:g}); "
                "either accepts 'none' to remove the ceiling. Raising them is a choice to "
                "make on purpose - this query reached 22 GB in under a minute on a 21 MB "
                "graph, so 'none' can take the machine into swap."
            ) from exc
        raise CompanionError(
            f"{skill} {operation} exceeded its {detail}"
        ) from exc
    if done.returncode != 0:
        raise CompanionError(done.stderr.strip() or f"{skill} operation failed")
    try:
        response = json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise CompanionError(f"{skill} returned invalid JSON") from exc
    if (
        not isinstance(response, dict)
        or type(response.get("schema_version")) is not int
        or response["schema_version"] != 1
    ):
        raise CompanionError(f"{skill} returned unsupported schema_version")
    return response


def _profile(reference: str) -> ResolvedProfile:
    snapshot = _machine(
        "linked-archi-profile", "la-profile", "resolve",
        {"schema_version": 1, "profile": reference},
    )
    return ResolvedProfile(snapshot)


def _target(args: argparse.Namespace) -> dict[str, Any]:
    data = list(args.data)
    if not data and not args.endpoint:
        raw = os.environ.get("LINKED_ARCHI_DATA", "")
        data = [part for part in raw.split(os.pathsep) if part]
    return {
        "data": data,
        "endpoint": args.endpoint,
        "timeout_ms": args.timeout_ms,
        "lenient": args.lenient,
        # None rather than a default, so an unset flag defers to $LINKED_ARCHI_STORE in
        # the connect process instead of overriding it with this parser's default.
        "store": getattr(args, "store", None),
    }


def _execute(query: str, target: dict[str, Any]) -> dict[str, Any]:
    raw = _machine(
        "linked-archi-connect", "la-connect", "execute",
        {"schema_version": 1, "target": target, "query": query},
    )
    return _validate_raw_result(raw)


def _parse_sets(pairs: Sequence[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise RenderError(f"--set expects NAME=VALUE, got {pair!r}")
        key, _, value = pair.partition("=")
        values[key.strip()] = value
    return values


def cmd_catalog_list(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    problems = catalog.validate_files()
    profile = _profile(args.profile) if args.profile else None
    print(catalog.format_list(profile))
    if profile and args.why:
        refused = catalog.refused(profile)
        if refused:
            print("\nrefused, and why:")
        for entry, verdict in refused:
            print(f"\n  {entry.name}")
            for reason in verdict.unmet:
                print(f"    - {reason}")
            if entry.alternatives:
                print(f"    try instead: {', '.join(entry.alternatives)}")
    if problems:
        for problem in problems:
            print(f"catalogue problem: {problem}", file=sys.stderr)
        return ERROR
    return OK


def cmd_catalog_show(args: argparse.Namespace) -> int:
    entry = load_catalog().get(args.template)
    profile = _profile(args.profile) if args.profile else None
    print(f"name            {entry.name}")
    print(f"file            {entry.file}")
    print(f"stage           {entry.stage}")
    if entry.notation:
        print(f"notation        {entry.notation}")
    print(f"purpose         {entry.purpose}")
    if entry.answers:
        print(f"answers         {entry.answers}")
    if entry.does_not_prove:
        print(f"does not prove  {entry.does_not_prove}")
    if entry.caveat:
        # Shown here as well as attached to every result: a reader choosing between
        # templates should know which one comes with a warning before running it.
        print(f"caveat          {entry.caveat}")
    if entry.parameters:
        print("parameters")
        for name, spec in entry.parameters.items():
            default = f" default={spec['default']}" if "default" in spec else ""
            bounds = ""
            if "min" in spec or "max" in spec:
                bounds = f" range={spec.get('min', '-')}..{spec.get('max', '-')}"
            choices = ""
            if spec.get("choices"):
                # Printed, because an unlisted value is refused rather than ignored.
                choices = " one of=" + "|".join(spec["choices"])
            print(f"  {name:16} {spec['type']}{default}{bounds}{choices}")
            if spec.get("description"):
                print(f"  {'':16} {spec['description']}")
    requirement = entry.requires
    if (
        requirement.roles
        or requirement.graph_roles
        or requirement.capabilities
        or requirement.membership
    ):
        print("requires")
        if requirement.roles:
            print(f"  roles          {', '.join(requirement.roles)}")
        if requirement.graph_roles:
            print(f"  graph roles    {', '.join(requirement.graph_roles)}")
        for capability, value in requirement.capabilities.items():
            print(f"  capability     {capability} = {value}")
        if requirement.membership:
            print("  membership     the profile must be able to express model membership")
    if entry.alternatives:
        print(f"alternatives    {', '.join(entry.alternatives)}")
    if profile is not None:
        verdict = entry.check(profile)
        print(f"\nunder profile {profile.name!r}: {'available' if verdict.ok else 'REFUSED'}")
        for reason in verdict.unmet:
            print(f"  - {reason}")
        for warning in verdict.warnings:
            print(f"  caveat: {warning}")
    if args.source:
        print("\n--- template source ---")
        print(entry.text(), end="")
    return OK


def cmd_catalog_dump(args: argparse.Namespace) -> int:
    """Every entry with full metadata in one call.

    `catalog show` per template costs a call each for what is static metadata. Selecting a
    template and binding its parameters should not be an N-call negotiation.
    """
    catalog = load_catalog()
    profile = _profile(args.profile) if args.profile else None
    payload: dict[str, Any] = {"schema_version": 1, "templates": {}}
    if profile is not None:
        payload["profile"] = {"id": profile.name, "version": profile.profile_version}
    for entry in catalog:
        item: dict[str, Any] = {
            "stage": entry.stage,
            "notation": entry.notation,
            "purpose": entry.purpose,
            "answers": entry.answers,
            "does_not_prove": entry.does_not_prove,
            "caveat": entry.caveat,
            "parameters": entry.parameters,
            "requires": {
                "roles": list(entry.requires.roles),
                "graph_roles": list(entry.requires.graph_roles),
                "capabilities": dict(entry.requires.capabilities),
                "membership": entry.requires.membership,
            },
            "alternatives": list(entry.alternatives),
        }
        if profile is not None:
            verdict = entry.check(profile)
            item["available"] = verdict.ok
            item["unmet"] = list(verdict.unmet)
            # Named for where it comes from. `caveat` above is the template's own
            # statement about its rows; these come from this profile's fit, and a
            # caller that conflates them cannot tell "always true of this template"
            # from "true of this dataset".
            item["profile_caveats"] = list(verdict.warnings)
        payload["templates"][entry.name] = item
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return OK


def cmd_render(args: argparse.Namespace) -> int:
    rendered = render(args.template, _profile(args.profile), _parse_sets(args.set), strict=not args.force)
    for warning in rendered.warnings:
        print(f"caveat: {warning}", file=sys.stderr)
    if args.output:
        target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered.query, encoding="utf-8")
        print(f"Wrote {target}")
    else:
        print(rendered.query, end="")
    return OK


def _envelope(raw: dict[str, Any], rendered, profile: ResolvedProfile) -> Envelope:
    """Turn transport evidence into a result envelope.

    The row cap comes from ``rendered``, and deliberately takes no argument of its own.
    It used to, and each caller computed one: `run` from its `--set LIMIT` and `literal`
    from the profile's `default_row_limit`, neither of which is what the query carried.
    A complete 200-row result was reported truncated, and a result genuinely capped at
    25 was reported complete - the second being the dangerous direction, since it
    removes the very signal that makes a count a floor rather than a total.
    """
    rows = list(raw.get("rows") or [])
    form = str(raw.get("form") or "")
    row_count = len(rows) if form == "SELECT" else (1 if raw.get("boolean") is not None else 0)
    dataset_id = str(raw.get("dataset_id") or "<unset>")
    caveats = list(rendered.warnings)
    # An unverified profile fails silently, so say so once per (dataset, profile) pair
    # rather than trusting that the implied connect -> verify -> query order was followed.
    if not verification.is_verified(dataset_id, profile.name, profile.fingerprint):
        caveats.append(verification.caveat(profile.name))
    return Envelope.build(
        query=rendered.query,
        dataset_id=dataset_id,
        profile_id=profile.name,
        profile_version=profile.profile_version,
        elapsed_ms=int(raw.get("elapsed_ms") or 0),
        # Optional on the wire, not required: an older linked-archi-connect does not
        # send it, and refusing its results over a timing field would be a poor trade.
        load_ms=int(raw.get("load_ms") or 0),
        row_count=row_count,
        template=None if rendered.template == "<literal>" else rendered.template,
        form=form,
        variables=list(raw.get("variables") or []),
        rows=rows,
        boolean=raw.get("boolean"),
        triples=raw.get("triples"),
        # `row_limit is None` means the query applied no cap, so its result cannot have
        # been cut at one. That is a finding, not a gap: it is the case where
        # completeness is easiest to be certain about.
        truncated=(
            form == "SELECT"
            and rendered.row_limit is not None
            and len(rows) >= rendered.row_limit
        ),
        warnings=caveats,
    )


def _emit(envelope: Envelope, args: argparse.Namespace) -> int:
    """Print the result in the requested shape, or write the envelope to a file.

    `-o` still writes JSON whatever `--format` says, because an artifact is a record: the
    analyse bundler and `query batch` read it back, and the envelope is the only shape
    carrying the fields a citation is reconstructed from.
    """
    if args.output:
        written = envelope.write(args.output)
        print(f"Wrote {written} ({envelope.row_count} row(s))")
        return OK

    # --json predates --format and is documented in three places, so it keeps working.
    # An explicit --format wins, which is the only reading that lets a caller override an
    # alias it inherited from a script or a habit.
    chosen = getattr(args, "format", "tsv")
    if chosen == "tsv" and getattr(args, "json", False):
        chosen = "json"

    if chosen == "json":
        print(envelope.to_json())
    elif chosen == "md":
        print(envelope.to_table(limit=args.limit))
    else:
        print(envelope.to_tsv(limit=args.limit))
    return OK


def cmd_run(args: argparse.Namespace) -> int:
    profile = _profile(args.profile)
    rendered = render(args.template, profile, _parse_sets(args.set))
    raw = _execute(rendered.query, _target(args))
    return _emit(_envelope(raw, rendered, profile), args)


def cmd_literal(args: argparse.Namespace) -> int:
    profile = _profile(args.profile)
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.query
    if not text:
        raise RenderError("Give --query or --file")
    rendered = render_literal(text, profile)
    raw = _execute(rendered.query, _target(args))
    return _emit(_envelope(raw, rendered, profile), args)


def _batch_manifest(path: str) -> list[dict[str, Any]]:
    """Read and validate a batch manifest, refusing anything ambiguous.

    Fail-closed on ``schema_version`` for the same reason every other boundary here is:
    a manifest is written once and run repeatedly, often by CI, and a silently
    misread field would change which queries ran without changing the output shape.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise RenderError(f"could not read the batch manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RenderError(f"batch manifest {path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise RenderError(f"batch manifest {path} requires schema_version=1")
    items = document.get("queries")
    if not isinstance(items, list) or not items:
        raise RenderError(f"batch manifest {path} needs a non-empty queries array")

    cleaned: list[dict[str, Any]] = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise RenderError(f"batch entry {position} must be an object")
        unknown = set(item).difference({"id", "template", "file", "query", "set", "out"})
        if unknown:
            raise RenderError(
                f"batch entry {position} has unknown fields: " + ", ".join(sorted(unknown))
            )
        sources = [key for key in ("template", "file", "query") if item.get(key)]
        if len(sources) != 1:
            raise RenderError(
                f"batch entry {position} needs exactly one of template, file or query"
            )
        values = item.get("set") or {}
        if not isinstance(values, dict) or any(
            not isinstance(name, str) for name in values
        ):
            raise RenderError(f"batch entry {position} set must be an object")
        cleaned.append({
            "id": str(item.get("id") or item.get("template") or item.get("file") or f"query-{position}"),
            "template": item.get("template"),
            "file": item.get("file"),
            "query": item.get("query"),
            "set": values,
            "out": item.get("out"),
        })
    return cleaned


def cmd_batch(args: argparse.Namespace) -> int:
    """Run several queries in ONE invocation, so the dataset is parsed once.

    This is the answer to a cost that no cache could remove. A local dataset is parsed
    per process, and on a large aggregate that parse dwarfs the queries it serves.
    Measurement showed that reusing a parsed store across processes makes queries slower
    rather than faster, because a disk-backed store does not query at in-memory speed.
    So the way to stop paying the parse repeatedly is to stop starting a process per
    query, which is this.

    Rendering happens for EVERY entry before ANY query executes. Two reasons, and the
    second is the important one: a typo in the last entry should not cost a full load
    plus every earlier query, and `execute_many` validates the whole batch as read-only
    before running any of it, so a batch cannot do partial unsafe work.
    """
    profile = _profile(args.profile)
    entries = _batch_manifest(args.manifest)

    rendered = []
    for entry in entries:
        if entry["template"]:
            rendered.append(render(entry["template"], profile, entry["set"]))
        else:
            text = (
                Path(entry["file"]).read_text(encoding="utf-8")
                if entry["file"] else entry["query"]
            )
            rendered.append(render_literal(text, profile))

    results = _machine(
        "linked-archi-connect", "la-connect", "execute-many",
        {
            "schema_version": 1,
            "target": _target(args),
            "queries": [item.query for item in rendered],
        },
    ).get("results")
    if not isinstance(results, list) or len(results) != len(rendered):
        raise CompanionError(
            "linked-archi-connect returned a batch of the wrong size: expected "
            f"{len(rendered)} result(s)"
        )

    lines = []
    total_query_ms = 0
    load_ms = 0
    for entry, item, raw in zip(entries, rendered, results):
        envelope = _envelope(_validate_raw_result(raw), item, profile)
        # Only the first result carries the load; see Adapter.execute_many.
        load_ms = load_ms or envelope.load_ms
        total_query_ms += envelope.elapsed_ms
        note = ""
        if entry["out"]:
            envelope.write(entry["out"])
            note = f" -> {entry['out']}"
        flag = " TRUNCATED" if envelope.truncated else ""
        lines.append(
            f"  {entry['id']}: {envelope.row_count} row(s), "
            f"{envelope.elapsed_ms} ms{flag}{note}"
        )

    summary = "\n".join([
        f"{len(entries)} quer{'y' if len(entries) == 1 else 'ies'} in one invocation",
        *lines,
        # Stated together because the comparison is the reason to use this command: the
        # load is what a batch amortises, and the per-query total is what it does not.
        f"  load {load_ms} ms once, {total_query_ms} ms of query time total",
    ])
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(summary + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(summary)
    return OK


def _path_report(text: str, args: argparse.Namespace):
    """Check the query's paths against the attached shapes, or say why not.

    Only here, not on `run`. A wrong path returns nothing rather than failing, so the
    moment worth paying for a parse and a store read is before running the query - not on
    every execution of one that already works.
    """
    from .constraints import ConstraintError, constraints_from_profile
    from .paths import check_query, read_subclasses

    target = _target(args)
    if not target["data"] and not target["endpoint"]:
        return None

    def run(query: str):
        return _execute(query, target).get("rows") or []

    profile = _profile(args.profile)
    try:
        constraints = constraints_from_profile(run, profile)
    except ConstraintError as exc:
        from .paths import Report

        return Report(refused=str(exc))
    return check_query(text, constraints, read_subclasses(run))


def cmd_lint(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.query
    if not text:
        raise QueryError("Give a file or --query")
    validate_readonly(text)
    print(f"OK: read-only ({args.file or 'inline query'})")

    report = _path_report(text, args)
    if report is None:
        print("paths: not checked (no --data or --endpoint given)")
        return OK
    print(f"paths: {report.summary()}")
    for violation in report.violations:
        print(f"  ! {violation.message}")
    for note in report.unchecked:
        print(f"  ~ {note}")
    # Read-only is a refusal; an impossible path is a finding. The query is still legal
    # SPARQL and the caller may have reason to run it, so this reports rather than refuses.
    return OK


def _lint_decision(query: str) -> dict[str, Any]:
    try:
        validate_readonly(query)
    except QueryError as exc:
        return {"accepted": False, "reason": str(exc)}
    return {"accepted": True}


def cmd_machine_lint(_args: argparse.Namespace) -> int:
    """Return versioned read-only decisions without exposing query text in argv."""
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise CompanionError(f"machine input is not valid JSON: {exc}") from exc
    if (
        not isinstance(request, dict)
        or type(request.get("schema_version")) is not int
        or request["schema_version"] != 1
    ):
        raise CompanionError("machine input requires schema_version=1")

    has_query = "query" in request
    has_queries = "queries" in request
    if has_query == has_queries:
        raise CompanionError("machine lint requires exactly one of query or queries")
    if has_query:
        query = request["query"]
        if not isinstance(query, str) or not query.strip():
            raise CompanionError("machine lint query must be a non-empty string")
        print(json.dumps({"schema_version": 1, **_lint_decision(query)}))
        return OK

    queries = request["queries"]
    if (
        not isinstance(queries, list)
        or not queries
        or any(not isinstance(query, str) or not query.strip() for query in queries)
    ):
        raise CompanionError("machine lint queries must be a non-empty string array")
    print(json.dumps({
        "schema_version": 1,
        "decisions": [_lint_decision(query) for query in queries],
    }))
    return OK


@contextlib.contextmanager
def _redirected_stdout(args: argparse.Namespace):
    """Send a command's stdout to ``-o`` when it asked to be redirected that way.

    Two different commands mean two different things by ``-o``, and this handles only the
    second kind:

    - ``render``, ``run`` and ``literal`` write a specific ARTIFACT - the SPARQL, or the
      result envelope as JSON rather than the table you would have seen. They do their own
      writing, and are untouched here.
    - the catalogue commands, ``lint`` and ``doctor`` have no artifact separate from what
      they print, so for them ``-o`` means "that output, in a file".

    Collapsing the two into one mechanism would silently change what `run -o` writes, so
    the second kind opts in with ``set_defaults(redirect_output=True)`` and the difference
    stays visible in the parser.

    Diagnostics are NOT redirected. `catalog list` reports catalogue problems on stderr and
    exits non-zero; sending those into the file being written would hide the reason the
    file is not trustworthy.
    """
    target = getattr(args, "output", None)
    if not target or not getattr(args, "redirect_output", False):
        yield
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        saved, sys.stdout = sys.stdout, handle
        try:
            yield
        finally:
            sys.stdout = saved
    print(f"Wrote {path}")


def _output_arg(parser: argparse.ArgumentParser) -> None:
    """``-o`` for a command whose output IS its stdout. See :func:`_redirected_stdout`."""
    parser.add_argument(
        "-o", "--output", metavar="FILE",
        help="write this command's output to FILE instead of stdout. Diagnostics still "
             "go to stderr",
    )
    parser.set_defaults(redirect_output=True)


def _profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        metavar="NAME_OR_PATH",
        help=(
            "graph profile: a path, a bundled name, or examples/<name> "
            f"(default: {DEFAULT_PROFILE})"
        ),
    )


def _target_args(parser: argparse.ArgumentParser) -> None:
    """The dataset. Exactly one kind, and the same four flags on every command."""
    parser.add_argument(
        "--data",
        action="append",
        default=[],
        metavar="FILE",
        help=(
            "local RDF file (repeatable; files merge into one dataset). "
            "Omit when $LINKED_ARCHI_DATA is set (env: LINKED_ARCHI_DATA)"
        ),
    )
    parser.add_argument(
        "--endpoint",
        metavar="URL",
        help="HTTPS SPARQL query endpoint instead of local files; not combinable with --data",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        metavar="MS",
        help="endpoint request deadline (default: 30000). Ignored for local files",
    )
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="relax RDF parsing of local files. Never relaxes query safety",
    )
    parser.add_argument(
        "--store",
        choices=_STORE_MODES,
        default=None,
        help=(
            "where the store comes from, for local files (env: LINKED_ARCHI_STORE, "
            "default: memory). 'cached' reuses an on-disk store: much faster to load, "
            "slower to query. Read load_ms beside elapsed_ms to see the difference. "
            "linked-archi-connect/references/store-modes.md"
        ),
    )


_SET_HELP = (
    "template parameter, NAME=VALUE (repeatable). Names and types come from "
    "`catalog show <template>`; an IRI works with or without angle brackets"
)
_LIMIT_HELP = (
    "rows to PRINT in the table (default: 100). A display cap only: it does not bound "
    "the query, the work, or what -o and --json write. The query's own cap is "
    "`--set LIMIT=N`"
)
_JSON_HELP = (
    "the same as --format json: emit the full result envelope - query, query_id, "
    "dataset_id, profile_id, profile_version, executed_at, row_count, truncated, "
    "warnings, rows. Kept because it is the documented flag; --format wins if both appear"
)
#: The printable shapes. Deliberately three: NDJSON was considered and left out, because
#: `json` already gives an agent every row and NDJSON's only advantage is streaming, which
#: nothing in this pipeline does. W3C SPARQL results formats were left out too - they need
#: term type, datatype and language, and the adapters have already discarded those.
FORMATS = ("tsv", "md", "json")

#: `tsv` is the default because it is the cheapest shape that still carries the citation:
#: 11.5 kB against 14.9 kB for `md` and 21.8 kB for `json` on one 108-row result, most of
#: the JSON cost being the column name repeated per row. `md` pays for alignment, which is
#: worth it for a person and not for an agent. See Envelope.to_tsv.
_FORMAT_HELP = (
    "how to print the result: tsv (default) tab-separated rows with the row count, "
    "caveats and citation as '#' comment lines, so `grep -v '^#'` leaves pure rows; "
    "md an aligned markdown table; json the full envelope. Values are identical in all "
    "three - the adapters flatten RDF terms to lexical form, so none of them is a W3C "
    "SPARQL results document"
)
#: For the commands that write an ARTIFACT rather than their own stdout: `render` writes
#: the SPARQL, `run` and `literal` write the full envelope as JSON regardless of --json.
#: The catalogue commands, `lint` and `doctor` use `_output_arg` instead, which redirects
#: what they print. Two meanings, kept distinct on purpose - see `_redirected_stdout`.
_OUTPUT_HELP = (
    "write the artifact to this file instead of stdout: the rendered SPARQL for "
    "`render`, the full result envelope as JSON for `run` and `literal`"
)

_EPILOG = """\
Examples:
  la-query catalog list --profile linked-archi-default --why -o routing.txt
  la-query catalog show core/traceability --profile linked-archi-default
  la-query catalog dump --profile linked-archi-default -o catalog.json
  la-query query run core/models --data graph.trig --json -o steps/02-models.json
  la-query query run core/resolve-element --data graph.trig --set TERM="order service"
  la-query query render core/coverage-gaps --set RESOURCE_TYPE=... --set EXPECTED_PREDICATE=...
  la-query query literal --data graph.trig --query 'SELECT ?s WHERE { ?s ?p ?o }' --limit 50
  la-query lint question.rq

Exit codes: 0 answered, 1 refused (unsupported template, or not read-only), 2 error.
Exit 1 is a routing answer, not a crash: read the reason and use the named alternative.
An empty result is exit 0 - a finding, not a failure.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="la-query",
        description="Render and execute read-only SPARQL against an architecture graph.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="group", required=True)

    catalog = commands.add_parser(
        "catalog",
        help="browse the tested template library",
        description="What can be asked, with what parameters, and whether this profile supports it.",
    )
    catalog_sub = catalog.add_subparsers(dest="command", required=True)
    listing = catalog_sub.add_parser(
        "list",
        help="every template, marked available, refused or caveated",
        description=(
            "One line per template. 'x' is refused by this profile, '!' runs with a "
            "caveat, blank is available."
        ),
    )
    listing.add_argument(
        "--profile", metavar="NAME_OR_PATH",
        help="mark availability against this profile (default: no gating shown)",
    )
    listing.add_argument(
        "--why", action="store_true",
        help="explain every refusal and name an alternative template",
    )
    _output_arg(listing)
    listing.set_defaults(func=cmd_catalog_list)
    show = catalog_sub.add_parser(
        "show",
        help="one template's purpose, parameters and requirements",
        description=(
            "The authoritative parameter list. Read this instead of the .rq file: it "
            "carries the typing, what the template does not prove, and its alternatives."
        ),
    )
    show.add_argument("template", help="template name, e.g. core/traceability")
    show.add_argument(
        "--profile", metavar="NAME_OR_PATH",
        help="also report whether this profile supports it, and why not",
    )
    show.add_argument(
        "--source", action="store_true",
        help="print the unrendered SPARQL, directives and all",
    )
    _output_arg(show)
    show.set_defaults(func=cmd_catalog_show)
    dump = catalog_sub.add_parser(
        "dump",
        help="every template's full metadata as JSON, in one call",
        description=(
            "For choosing among several templates, or binding several parameter sets, "
            "without one call per template."
        ),
    )
    dump.add_argument(
        "--profile", metavar="NAME_OR_PATH",
        help="also report availability and caveats per template",
    )
    _output_arg(dump)
    dump.set_defaults(func=cmd_catalog_dump)

    query = commands.add_parser(
        "query",
        help="render or execute a query",
        description=(
            "Render a template, run one, run a hand-written query, or run several in "
            "one invocation with `batch` — which parses the dataset once instead of "
            "once per command."
        ),
    )
    query_sub = query.add_subparsers(dest="command", required=True)
    render_cmd = query_sub.add_parser(
        "render",
        help="expand a template without executing it",
        description=(
            "Produces the exact SPARQL that would run. Needs no dataset, so it is also "
            "how to offer candidate queries when nothing is attached."
        ),
    )
    render_cmd.add_argument("template", help="template name, e.g. core/models")
    _profile_arg(render_cmd)
    render_cmd.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                            help=_SET_HELP)
    render_cmd.add_argument("-o", "--output", metavar="FILE", help=_OUTPUT_HELP)
    render_cmd.add_argument(
        "--force", action="store_true",
        help="render even when the profile refuses it, for inspection only. Do not execute it",
    )
    render_cmd.set_defaults(func=cmd_render)
    run = query_sub.add_parser(
        "run",
        help="render and execute a catalogued template",
        description=(
            "The normal way to ask a question. Prints tab-separated rows with a citation; "
            "--format md for an aligned table, --format json for the full envelope."
        ),
    )
    run.add_argument("template", help="template name, e.g. core/dependents-qualified")
    _profile_arg(run)
    _target_args(run)
    run.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                     help=_SET_HELP)
    run.add_argument("--format", choices=FORMATS, default="tsv", help=_FORMAT_HELP)
    run.add_argument("--json", action="store_true", help=_JSON_HELP)
    run.add_argument("--limit", type=int, default=100, metavar="N", help=_LIMIT_HELP)
    run.add_argument("-o", "--output", metavar="FILE", help=_OUTPUT_HELP)
    run.set_defaults(func=cmd_run)
    literal = query_sub.add_parser(
        "literal",
        help="execute a hand-written query, with profile directives expanded",
        description=(
            "For a question the library does not cover. Directives such as "
            "{{GRAPH_OPEN:semantic}} and {{ROLE:label}} still resolve, and read-only is "
            "still enforced. START THE QUERY WITH {{PREFIXES}}: nothing is injected for "
            "you, so a prefixed name without it fails with 'Prefix not found' at an "
            "offset into the rendered text. Lint it before believing an empty result."
        ),
    )
    _profile_arg(literal)
    _target_args(literal)
    literal.add_argument("--query", metavar="SPARQL",
                         help="the query text; mutually exclusive with --file")
    literal.add_argument("--file", metavar="FILE",
                         help="read the query from this file instead of --query")
    literal.add_argument("--format", choices=FORMATS, default="tsv", help=_FORMAT_HELP)
    literal.add_argument("--json", action="store_true", help=_JSON_HELP)
    literal.add_argument("--limit", type=int, default=100, metavar="N", help=_LIMIT_HELP)
    literal.add_argument("-o", "--output", metavar="FILE", help=_OUTPUT_HELP)
    literal.set_defaults(func=cmd_literal)
    batch = query_sub.add_parser(
        "batch",
        help="run several queries in one invocation, parsing the dataset once",
        description=(
            "A local dataset is parsed per process, and on a large aggregate that parse "
            "dwarfs the queries it serves — so N separate commands pay it N times. This "
            "pays it once. Reusing a parsed store across processes was measured and "
            "REJECTED: a disk-backed store does not query at in-memory speed, so it "
            "makes analytical queries slower. Batching is the fix that works.\n\n"
            "Every entry is rendered before any query runs, and the whole batch is "
            "validated read-only before any of it executes, so a typo in the last entry "
            "costs nothing and a batch cannot do partial unsafe work.\n\n"
            "Manifest (JSON):\n"
            '  {"schema_version": 1, "queries": [\n'
            '     {"id": "inventory", "template": "core/inventory-summary",\n'
            '      "out": "/tmp/inv.json"},\n'
            '     {"template": "core/resolve-element", "set": {"TERM": "sourcing"},\n'
            '      "out": "/tmp/resolve.json"},\n'
            '     {"file": "queries/capability-tree.rq", "out": "/tmp/tree.json"}\n'
            "  ]}\n\n"
            "Each entry takes exactly one of template, file or query, plus optional id, "
            "set and out. Only the first result carries load_ms, because the load "
            "happened once."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    batch.add_argument("manifest", metavar="FILE", help="batch manifest, JSON")
    _profile_arg(batch)
    _target_args(batch)
    batch.add_argument("-o", "--output", metavar="FILE",
                       help="write the run summary here instead of stdout")
    batch.set_defaults(func=cmd_batch)

    lint = commands.add_parser(
        "lint",
        help="report a query's form and refuse anything not read-only",
        description=(
            "The first move on a hand-written query that returned nothing: far more often "
            "broken than evidence of absence."
        ),
    )
    lint.add_argument("file", nargs="?", metavar="FILE",
                      help="file holding the query; omit when using --query")
    lint.add_argument("--query", metavar="SPARQL", help="the query text to check")
    _profile_arg(lint)
    _target_args(lint)
    _output_arg(lint)
    lint.set_defaults(func=cmd_lint)
    doctor = commands.add_parser(
        "doctor",
        help="report this owner's location and companions",
        description=(
            "Owner root, resolved command, template count, dataset environment, and every "
            "companion this skill can reach. Run it instead of searching the filesystem."
        ),
    )
    _output_arg(doctor)
    doctor.set_defaults(func=cmd_doctor)
    machine = commands.add_parser(
        "_machine",
        help=_MACHINE_HELP,
        description=_MACHINE_DESCRIPTION,
    )
    machine_sub = machine.add_subparsers(dest="machine_command", required=True)
    machine_lint = machine_sub.add_parser(
        "lint",
        help="decide whether one query, or a batch, is read-only",
        description=(
            'Request {"schema_version": 1, "query": "..."} or "queries": [...]; response '
            'carries "accepted" and, when refused, "reason". A refusal is exit 0: the '
            "decision is the payload. Query text is read from stdin, never argv."
        ),
    )
    machine_lint.set_defaults(func=cmd_machine_lint)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with _redirected_stdout(args):
            return int(args.func(args))
    except UnsupportedTemplate as exc:
        print(str(exc), file=sys.stderr); return REFUSED
    except (QueryError, RenderError) as exc:
        print(f"Refused: {exc}", file=sys.stderr); return REFUSED
    except (CatalogError, ContractError, CompanionError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr); return ERROR
    except BrokenPipeError:
        return OK
    except KeyboardInterrupt:
        return ERROR


if __name__ == "__main__":
    raise SystemExit(main())
