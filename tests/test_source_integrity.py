"""Fast source and public-entry smoke tests."""

from __future__ import annotations

import ast
import importlib
import os
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {".git", ".idea", "__pycache__", "build", "dist"}


class SourceIntegrityTests(unittest.TestCase):
    def test_all_repository_python_files_parse(self) -> None:
        python_files = [
            path
            for path in REPOSITORY_ROOT.rglob("*.py")
            if not EXCLUDED_DIRECTORIES.intersection(path.relative_to(REPOSITORY_ROOT).parts)
        ]
        self.assertTrue(python_files, "No Python source files were found")
        failures: list[str] = []
        for path in python_files:
            try:
                source = path.read_text(encoding="utf-8-sig")
                ast.parse(source, filename=str(path))
            except (OSError, SyntaxError, UnicodeError) as error:
                failures.append(f"{path.relative_to(REPOSITORY_ROOT)}: {error}")
        self.assertFalse(failures, "Python parse failures:\n" + "\n".join(failures))

    def test_main_service_and_gui_entries_import(self) -> None:
        services = importlib.import_module("src.runtime.services.bluray_subtitle_entry")
        gui_runtime = importlib.import_module(
            "src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry"
        )
        bootstrap = importlib.import_module("src.runtime.bootstrap")

        self.assertTrue(hasattr(services, "BluraySubtitle"))
        self.assertTrue(hasattr(gui_runtime, "BluraySubtitleGUI"))
        self.assertTrue(callable(bootstrap.main))


if __name__ == "__main__":
    unittest.main()
