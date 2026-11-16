import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.windows_tool_paths import load_tool_paths


class WindowsToolPathTests(unittest.TestCase):
    def test_normalizes_managed_directories_and_preserves_frozen_and_linux_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            settings = root / "settings.py"
            paths = {"MKVTOOLNIX_PATH": root / "custom", "VSEDIT_PATH": root / "editor/vsedit.exe"}
            settings.write_text(
                "import sys\n"
                "def _bundled_path(relative, local):\n"
                "    return relative if getattr(sys, 'frozen', False) else local\n"
                f"MKVTOOLNIX_PATH = _bundled_path('mkvtoolnix', {str(paths['MKVTOOLNIX_PATH'])!r})\n"
                f"VSEDIT_PATH = _bundled_path('vsedit/vsedit.exe', {str(paths['VSEDIT_PATH'])!r})\n"
                "if sys.platform == 'linux':\n    MKVTOOLNIX_PATH = '/usr/bin'\n",
                encoding="utf-8",
            )
            with patch("sys.platform", "win32"):
                loaded = load_tool_paths(settings, list(paths))
                normalized = settings.read_bytes()
                self.assertEqual(load_tool_paths(settings, list(paths)), loaded)
                self.assertEqual(settings.read_bytes(), normalized)
                mkv_dir = paths["MKVTOOLNIX_PATH"] / "mkvtoolnix"
                editor = paths["VSEDIT_PATH"].parent / "vsedit/vsedit.exe"
                self.assertEqual(Path(loaded["MKVTOOLNIX_PATH"]), mkv_dir)
                self.assertEqual(Path(loaded["VSEDIT_PATH"]), editor)
                self.assertTrue(mkv_dir.is_dir())
                self.assertTrue(editor.parent.is_dir())
                with patch("sys.frozen", True, create=True):
                    self.assertEqual(runpy.run_path(str(settings))["MKVTOOLNIX_PATH"], "mkvtoolnix")
            with patch("sys.platform", "linux"):
                self.assertEqual(runpy.run_path(str(settings))["MKVTOOLNIX_PATH"], "/usr/bin")
