"""Local query execution is bounded, in time and in memory.

pyoxigraph has no query timeout and the query is a blocking call into Rust, so nothing
inside the executing process can stop an expensive one. For a while nothing outside it did
either: the parent deliberately passed no deadline for local execution, reasoning that a
timeout would kill valid long queries.

That reasoning traded a bounded failure for an unbounded one, and it was falsified in the
field. One `core/dependents-qualified` against a 21 MB estate graph ran for 49 minutes and
reached 20 GB resident, with no message and no ceiling, until it was killed by hand.

Two ceilings, because time alone was measured to be insufficient - the same query reached
22 GB inside 60 seconds, so a purely time-based bound would take a machine into swap long
before the clock expired. Memory is the one that actually fires: with both in place that
query now refuses in under 7 seconds at about 2.2 GB.

`LIMIT` is not a work bound and never was. `ORDER BY` materialises every solution before
`LIMIT` applies, which is why `--limit 100` did not help.
"""

from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from unittest import mock

import support  # noqa: F401  - path setup

from linked_archi_query import cli
from linked_archi_query.cli import (
    DEFAULT_LOCAL_DEADLINE_S,
    DEFAULT_LOCAL_MAX_RSS_MB,
    ENV_LOCAL_DEADLINE,
    ENV_LOCAL_MEMORY_MB,
    CompanionError,
    _companion_deadline,
    _Exceeded,
    _local_deadline,
    _local_max_rss_mb,
    _run_bounded,
)

LOCAL = {"target": {"data": ["graph.trig"], "endpoint": None, "timeout_ms": 30000}}
ENDPOINT = {"target": {"data": [], "endpoint": "https://example.org/sparql",
                       "timeout_ms": 30000}}


@contextmanager
def env(name: str, value: str | None):
    previous = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


class TestLocalExecutionIsBounded(unittest.TestCase):
    """The regression that matters: local execution must not be unbounded."""

    def test_a_local_target_gets_a_finite_deadline(self):
        deadline = _companion_deadline(LOCAL)
        self.assertIsNotNone(
            deadline,
            "local execution is unbounded again. That is the 49-minute, 20 GB failure "
            "this ceiling exists to prevent.",
        )
        self.assertEqual(deadline, DEFAULT_LOCAL_DEADLINE_S)

    def test_a_local_target_gets_a_memory_ceiling(self):
        self.assertGreaterEqual(
            _local_max_rss_mb(LOCAL["target"]), DEFAULT_LOCAL_MAX_RSS_MB
        )

    def test_the_ceiling_scales_with_the_dataset(self):
        """A fixed ceiling is wrong in both directions, so it is proportional.

        Holding the dataset is unavoidable cost - a 112 MB / 1.4M-quad merged estate needs
        about 1 GB just to load - so a flat 2 GB would refuse real work over it while
        allowing a 2 GB runaway against a 300 KB fixture. The query is judged on what it
        adds to the data, not on the data.
        """
        small = _local_max_rss_mb({"data": [str(support.BASE)]})
        large = _local_max_rss_mb({"data": [str(support.BASE), str(support.AUGMENTED)]})
        self.assertGreaterEqual(small, DEFAULT_LOCAL_MAX_RSS_MB)
        self.assertGreaterEqual(large, small)

    def test_an_unreadable_input_does_not_break_the_ceiling(self):
        """It will fail with a proper message when the adapter reads it, not here."""
        self.assertEqual(
            _local_max_rss_mb({"data": ["/nonexistent/graph.trig"]}),
            DEFAULT_LOCAL_MAX_RSS_MB,
        )

    def test_an_explicit_override_is_absolute(self):
        """A number someone chose means that number, not that number plus the data."""
        with env(ENV_LOCAL_MEMORY_MB, "512"):
            self.assertEqual(_local_max_rss_mb({"data": [str(support.BASE)]}), 512)

    def test_the_memory_ceiling_is_the_one_that_can_fire_in_time(self):
        """Measured, not assumed: growth was ~360 MB/s on a real graph.

        If the default ceiling were ever raised above what the deadline can contain, the
        memory bound would stop being the effective one and the old failure would return in
        a slower form.
        """
        worst_case_mb = DEFAULT_LOCAL_DEADLINE_S * 360
        self.assertLess(
            DEFAULT_LOCAL_MAX_RSS_MB, worst_case_mb,
            "the memory ceiling must bind before the deadline could allow swap death",
        )

    def test_an_endpoint_target_keeps_its_own_deadline(self):
        """Unchanged. Server-side work does not grow this process."""
        self.assertEqual(_companion_deadline(ENDPOINT), 60.0 + 30000 / 1000.0)


class TestTheCeilingsAreConfigurable(unittest.TestCase):
    """Raising them has to be possible, and has to be a deliberate act."""

    def test_the_deadline_can_be_raised(self):
        with env(ENV_LOCAL_DEADLINE, "900"):
            self.assertEqual(_local_deadline(), 900.0)

    def test_the_deadline_can_be_removed_explicitly(self):
        for value in ("none", "0", "off"):
            with self.subTest(value=value), env(ENV_LOCAL_DEADLINE, value):
                self.assertIsNone(_local_deadline())

    def test_the_memory_ceiling_can_be_raised(self):
        with env(ENV_LOCAL_MEMORY_MB, "8192"):
            self.assertEqual(_local_max_rss_mb(), 8192)

    def test_the_memory_ceiling_can_be_removed_explicitly(self):
        for value in ("none", "0", "off"):
            with self.subTest(value=value), env(ENV_LOCAL_MEMORY_MB, value):
                self.assertIsNone(_local_max_rss_mb())

    def test_nonsense_is_refused_rather_than_ignored(self):
        """Silently falling back to a default would hide a typo in a CI variable."""
        for name, getter in ((ENV_LOCAL_DEADLINE, _local_deadline),
                             (ENV_LOCAL_MEMORY_MB, _local_max_rss_mb)):
            for value in ("soon", "-5"):
                with self.subTest(var=name, value=value), env(name, value):
                    with self.assertRaises(CompanionError):
                        getter()

    def test_an_empty_value_means_the_default(self):
        """An unset-but-exported variable is common in shell wrappers."""
        with env(ENV_LOCAL_DEADLINE, ""):
            self.assertEqual(_local_deadline(), DEFAULT_LOCAL_DEADLINE_S)
        with env(ENV_LOCAL_MEMORY_MB, "   "):
            self.assertEqual(_local_max_rss_mb(), DEFAULT_LOCAL_MAX_RSS_MB)


class TestTheWatchdogStopsAChild(unittest.TestCase):
    """The mechanism, exercised on a child that really does misbehave.

    Driven directly rather than through a query, because a bound needs a run that outlives
    the sampling interval to be observable, and no fixture query is reliably that slow.
    Asserting against a stub keeps the test deterministic instead of racing a real query.
    """

    def test_a_slow_child_is_stopped_by_the_deadline(self):
        with self.assertRaises(_Exceeded) as caught:
            _run_bounded(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                "", deadline=1.0, max_rss_mb=4096,
            )
        self.assertIn("companion deadline", caught.exception.reason)

    def test_a_greedy_child_is_stopped_by_the_memory_ceiling(self):
        with self.assertRaises(_Exceeded) as caught:
            _run_bounded(
                [sys.executable, "-c",
                 "b=bytearray(400*1024*1024); import time; time.sleep(30)"],
                "", deadline=120.0, max_rss_mb=100,
            )
        self.assertIn("memory ceiling", caught.exception.reason)
        self.assertIn("reached", caught.exception.reason,
                      "name the observed size, not only the limit")

    def test_a_well_behaved_child_completes_untouched(self):
        done = _run_bounded(
            [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
            "hello", deadline=60.0, max_rss_mb=4096,
        )
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "hello")

    def test_a_child_that_finishes_inside_one_interval_is_never_sampled(self):
        """Documents the granularity: completed work is not thrown away.

        A run shorter than the sampling interval is not stopped even by an impossible
        limit. These are bounds on runaways, not precise deadlines, and a test that assumed
        otherwise would be flaky rather than wrong.
        """
        done = _run_bounded(
            [sys.executable, "-c", "pass"], "", deadline=0.001, max_rss_mb=1,
        )
        self.assertEqual(done.returncode, 0)


class TestTheRefusalIsActionable(unittest.TestCase):
    """A ceiling that fires without explaining itself reads as a broken tool."""

    def test_the_local_message_names_the_cause_and_the_way_out(self):
        with mock.patch.object(
            cli, "_run_bounded",
            side_effect=_Exceeded("2048 MB memory ceiling (reached 2164 MB)"),
        ):
            with self.assertRaises(CompanionError) as caught:
                cli._machine("linked-archi-connect", "la-connect", "execute", LOCAL)
        message = str(caught.exception)
        self.assertIn("memory ceiling", message)
        self.assertIn("guardrail", message)
        self.assertIn("ORDER BY", message, "the reader needs the actual cause")
        self.assertIn(ENV_LOCAL_MEMORY_MB, message, "and the way to raise it")
        self.assertIn(ENV_LOCAL_DEADLINE, message)

    def test_an_endpoint_failure_keeps_the_terse_message(self):
        """The local advice would be wrong for an endpoint: the work is not in this process."""
        with mock.patch.object(
            cli, "_run_bounded", side_effect=_Exceeded("90s companion deadline")
        ):
            with self.assertRaises(CompanionError) as caught:
                cli._machine("linked-archi-connect", "la-connect", "execute", ENDPOINT)
        message = str(caught.exception)
        self.assertIn("90s companion deadline", message)
        self.assertNotIn("ORDER BY", message)


class TestARealQueryStaysUnaffected(unittest.TestCase):
    """The guardrail must not cost correctness on the ordinary path."""

    def setUp(self):
        support.requires_pyoxigraph(self)

    def test_a_normal_local_query_still_returns_its_rows(self):
        import subprocess

        environment = dict(os.environ)
        environment.pop("LINKED_ARCHI_SKILLS_DIR", None)
        done = subprocess.run(
            [sys.executable,
             str(support.ROOT / "skills/linked-archi-query/scripts/la-query"),
             "query", "run", "core/models",
             "--profile", "linked-archi-default",
             "--data", str(support.BASE)],
            capture_output=True, text=True, timeout=180, env=environment,
            cwd=support.ROOT,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("row(s)", done.stdout)
        self.assertNotIn("guardrail", done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
