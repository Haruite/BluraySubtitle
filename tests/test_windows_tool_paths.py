import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.windows_tool_paths import MKV_SETTINGS, load_tool_paths


class WindowsToolPathTests(unittest.TestCase):
    def test_normalizes_managed_directories_and_preserves_frozen_and_linux_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            settings = root / "settings.py"
            entries = {**MKV_SETTINGS, "vsedit.exe": "VSEDIT_PATH"}
            paths = {name: root / ("editor" if name == "VSEDIT_PATH" else "custom") / exe
                     for exe, name in entries.items()}
            settings.write_text(
                "import sys\n"
                "def _bundled_path(relative, local):\n"
                "    return relative if getattr(sys, 'frozen', False) else local\n"
                + "".join(f"{name} = _bundled_path({exe!r}, {str(paths[name])!r})\n"
                          for exe, name in entries.items())
                + "if sys.platform == 'linux':\n    MKV_MERGE_PATH = '/usr/bin/mkvmerge'\n",
                encoding="utf-8",
            )
            with patch("sys.platform", "win32"):
                loaded = load_tool_paths(settings, list(entries.values()))
                normalized = settings.read_bytes()
                self.assertEqual(load_tool_paths(settings, list(entries.values())), loaded)
                self.assertEqual(settings.read_bytes(), normalized)
                for name, original in paths.items():
                    folder = "vsedit" if name == "VSEDIT_PATH" else "mkvtoolnix"
                    self.assertEqual(Path(loaded[name]), original.parent / folder / original.name)
                    self.assertTrue(Path(loaded[name]).parent.is_dir())
                with patch("sys.frozen", True, create=True):
                    self.assertEqual(runpy.run_path(str(settings))["MKV_MERGE_PATH"], "mkvmerge.exe")
            with patch("sys.platform", "linux"):
                self.assertEqual(runpy.run_path(str(settings))["MKV_MERGE_PATH"], "/usr/bin/mkvmerge")
