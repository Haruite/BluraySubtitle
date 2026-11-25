"""Exercise IINA discovery and the libmpv options the macOS previews use."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.core.tool_paths import resolve_tool_paths
from src.runtime.gui_runtime_split import playback_and_paths as playback


@unittest.skipUnless(sys.platform == "darwin", "IINA playback tests run on macOS")
class MacPlaybackTests(unittest.TestCase):
    def test_configured_application_precedes_player_discovery(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            cli = base / "My IINA.app/Contents/MacOS/iina-cli"
            cli.parent.mkdir(parents=True)
            cli.touch(mode=0o755)
            with patch("shutil.which", return_value=None):
                paths = resolve_tool_paths({"MPV_PATH": "My IINA.app"}, base)
            self.assertEqual(paths["MPV_PATH"], str(cli))

    def test_iina_receives_playlist_root_and_single_subtitle_property(self):
        window = SimpleNamespace(_app_config=SimpleNamespace(tools={}))
        cli = "/Applications/IINA.app/Contents/MacOS/iina-cli"
        args = ["--sub-file=/Movies/01: 字幕.srt", "--bluray-device=/Movies/Disc A", "bd://mpls/00003"]
        with patch.object(playback, "QProcess") as process:
            playback.PlaybackPathsMixin._start_mpv_playback(window, cli, args, "00003.mpls")
        process.return_value.start.assert_called_once_with(
            cli, ["--no-stdin", "--", r"--sub-files=/Movies/01\: 字幕.srt",
                  "--bluray-device=/Movies/Disc A", "bd://mpls/00003"],
        )
