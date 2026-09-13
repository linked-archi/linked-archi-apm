"""Test package bootstrap.

Puts ``lib/`` and this directory on ``sys.path`` so the suite runs the same way
however it is invoked:

    make test
    python3 -m unittest discover -s tests -t .
    python3 -m unittest tests.test_profiles
    cd tests && python3 test_profiles.py

Without this, ``import support`` resolves only when the tests directory happens to be
the top-level directory, so the suite would pass under one runner and fail under
another - which is the kind of difference that gets a failing test ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_ROOT = _TESTS.parent

for path in (str(_ROOT / "lib"), str(_TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)
