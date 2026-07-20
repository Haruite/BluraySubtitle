"""Run the repository's standard-library test suite."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


def main() -> int:
    """Discover and run all tests with headless Qt settings."""
    repository_root = Path(__file__).resolve().parent
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.dont_write_bytecode = True
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))

    suite = unittest.defaultTestLoader.discover(str(repository_root / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
