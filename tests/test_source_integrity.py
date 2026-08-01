"""Fast source and public-entry smoke tests."""

from __future__ import annotations

import ast
import importlib
import os
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_legacy_global_configuration_is_removed(self) -> None:
        production_files = [
            path
            for path in (REPOSITORY_ROOT / "src").rglob("*.py")
            if not EXCLUDED_DIRECTORIES.intersection(path.relative_to(REPOSITORY_ROOT).parts)
        ]
        occurrences: list[str] = []
        for path in production_files:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            if any(isinstance(node, ast.Name) and node.id == "CONFIGURATION" for node in ast.walk(tree)):
                occurrences.append(str(path.relative_to(REPOSITORY_ROOT)))

        self.assertEqual(occurrences, [])

    def test_linux_tool_paths_are_loaded_by_setup(self) -> None:
        settings_file = REPOSITORY_ROOT / "src" / "core" / "settings.py"
        setup_script = REPOSITORY_ROOT / "setup_linux_environment.sh"

        with patch.object(sys, "platform", "linux"):
            settings = runpy.run_path(str(settings_file))

        setup_source = setup_script.read_text(encoding="utf-8")
        expected_paths = {
            "VSEDIT_PATH": "/usr/local/bin/vsedit",
            "VSPIPE_PATH": "/usr/local/bin/vspipe",
            "X264_PATH": "/usr/bin/x264",
            "X265_PATH": "/usr/bin/x265",
            "SVT_AV1_PATH": "/usr/bin/SvtAv1EncApp",
            "TS_MUXER_PATH": "/usr/bin/tsMuxeR",
        }
        for name, expected in expected_paths.items():
            with self.subTest(name=name):
                self.assertEqual(settings[name], expected)
                self.assertIn(f'"{name}"', setup_source)
        self.assertNotIn("TSMUXER_PATH", settings)
        self.assertNotIn(
            "TSMUXER_PATH",
            "\n".join(
                path.read_text(encoding="utf-8-sig")
                for path in (REPOSITORY_ROOT / "src").rglob("*.py")
            ),
        )
        self.assertIn('bluray_sudo tee "$VSEDIT_PATH"', setup_source)


if __name__ == "__main__":
    unittest.main()
