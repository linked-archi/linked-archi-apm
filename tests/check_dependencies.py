"""Check the selected Python environment before running the full test suite."""

from __future__ import annotations

import importlib
from pathlib import Path
import shlex
import sys


def main() -> int:
    failures = []
    for package, module in (
        ("PyYAML", "yaml"),
        ("pyoxigraph", "pyoxigraph"),
        ("rdflib", "rdflib"),
        ("pyshacl", "pyshacl"),
        ("jsonschema", "jsonschema"),
    ):
        try:
            importlib.import_module(module)
        except ImportError as exc:
            failures.append(f"  {package}: {exc}")
    if failures:
        print(f"Test dependencies are unavailable in {sys.executable}:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        requirements = Path(__file__).resolve().with_name("requirements.txt")
        command = shlex.join([sys.executable, "-m", "pip", "install", "-r", str(requirements)])
        print(f"Install them into this Python environment:\n  {command}", file=sys.stderr)
        return 1
    print(f"Test dependencies ready: {sys.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
