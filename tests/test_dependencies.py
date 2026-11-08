"""Release checks fail before the suite when its Python dependencies are absent."""

import shlex
import shutil
import subprocess
import sys
import unittest

from support import ROOT


class TestDependencyPreflight(unittest.TestCase):
    def test_the_preflight_accepts_the_complete_test_environment(self):
        done = subprocess.run(
            [sys.executable, str(ROOT / "tests/check_dependencies.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(sys.executable, done.stdout)

    @unittest.skipUnless(shutil.which("make"), "make is needed to check the test target")
    def test_missing_packages_stop_make_before_test_discovery(self):
        # -S removes site-packages in the child without changing the real environment.
        done = subprocess.run(
            [shutil.which("make"), "test", f"PY={shlex.quote(sys.executable)} -S"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        output = done.stdout + done.stderr
        self.assertNotEqual(done.returncode, 0, output)
        self.assertIn("Test dependencies are unavailable", output)
        for package in ("PyYAML", "pyoxigraph", "rdflib", "pyshacl", "jsonschema"):
            self.assertIn(package, output)
        command = shlex.join([
            sys.executable, "-m", "pip", "install", "-r", str(ROOT / "tests/requirements.txt"),
        ])
        self.assertIn(command, output)
        self.assertNotIn("unittest discover", output)


if __name__ == "__main__":
    unittest.main()
