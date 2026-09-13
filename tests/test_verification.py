"""The profile-verification reminder: a caveat, never a gate.

Four skills with an implied order and no checkpoint means the order is advisory, and
advisory steps get dropped. A field session went connect then query, skipped
`profile verify`, and got lucky that the default profile fitted. When it does not fit the
failure is silent - scoped queries return nothing, or rows meaning something else.

What is deliberately *not* here is enforcement. A gate would need cross-invocation session
state, would be trivially bypassed, and would break the machine contracts and CI. So these
tests pin that the reminder appears, disappears once earned, and never refuses anything.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  - puts the owner scripts on sys.path
from support import ROOT

from linked_archi_query import verification

QUERY = ROOT / "skills" / "linked-archi-query" / "scripts" / "la-query"
PROFILE = ROOT / "skills" / "linked-archi-profile" / "scripts" / "la-profile"


class TestMarkerKeying(unittest.TestCase):
    def test_the_key_covers_dataset_profile_and_version(self):
        base = verification.marker_name("base.trig", "linked-archi-default", 1)
        for other in (
            verification.marker_name("augmented.trig", "linked-archi-default", 1),
            verification.marker_name("base.trig", "curated-store", 1),
            verification.marker_name("base.trig", "linked-archi-default", 2),
        ):
            self.assertNotEqual(base, other, "each part of the triple must change the key")

    def test_the_same_triple_is_stable(self):
        self.assertEqual(
            verification.marker_name("base.trig", "linked-archi-default", 1),
            verification.marker_name("base.trig", "linked-archi-default", 1),
        )

    def test_an_unidentifiable_dataset_is_never_nagged_about(self):
        # An endpoint or a missing identity is not something to lecture the reader about.
        self.assertTrue(verification.is_verified("", "linked-archi-default", 1))
        self.assertTrue(verification.is_verified("<unset>", "linked-archi-default", 1))

    def test_recording_is_best_effort_and_returns_nothing_for_no_dataset(self):
        self.assertIsNone(verification.record("", "linked-archi-default", 1))

    def test_the_caveat_names_the_command_that_settles_it(self):
        text = verification.caveat("acme")
        self.assertIn("la-profile verify", text)
        self.assertIn("acme", text)
        self.assertIn("silently", text)


class TestEndToEnd(unittest.TestCase):
    """Across two owners, which share only a documented path convention."""

    def setUp(self):
        support.requires_pyoxigraph(self)
        self._state = tempfile.TemporaryDirectory()
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "LINKED_ARCHI_SKILLS_DIR"}
        }
        self.env["LINKED_ARCHI_STATE_DIR"] = self._state.name

    def tearDown(self):
        self._state.cleanup()

    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, cwd=ROOT, env=self.env, timeout=180,
        )

    def _query(self, profile: str, data: Path) -> subprocess.CompletedProcess:
        return self._run(
            QUERY, "query", "run", "core/models", "--profile", profile, "--data", str(data)
        )

    def test_an_unverified_pair_is_flagged_but_still_answers(self):
        done = self._query("linked-archi-default", support.BASE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("has not been verified", done.stdout + done.stderr)
        self.assertIn("row(s)", done.stdout, "the caveat must not suppress the answer")

    def test_a_clean_verification_silences_it(self):
        verify = self._run(
            PROFILE, "verify", "--profile", "linked-archi-default", "--data", str(support.BASE)
        )
        self.assertEqual(verify.returncode, 0, verify.stderr)
        self.assertEqual(len(list(Path(self._state.name).glob("*.verified"))), 1)

        done = self._query("linked-archi-default", support.BASE)
        self.assertNotIn("has not been verified", done.stdout + done.stderr)

    def test_verifying_one_pair_does_not_vouch_for_another(self):
        self._run(
            PROFILE, "verify", "--profile", "linked-archi-default", "--data", str(support.BASE)
        )
        for profile, data in (
            ("curated-store", support.BASE),
            ("linked-archi-default", support.AUGMENTED),
        ):
            with self.subTest(profile=profile, data=data.name):
                done = self._query(profile, data)
                self.assertIn("has not been verified", done.stdout + done.stderr)

    def test_an_unwritable_state_directory_does_not_fail_verification(self):
        self.env["LINKED_ARCHI_STATE_DIR"] = "/proc/nonexistent/cannot-create"
        done = self._run(
            PROFILE, "verify", "--profile", "linked-archi-default", "--data", str(support.BASE)
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
