import json
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


HELPER = Path(__file__).resolve().parents[1] / "tools/linux_setup_cache.py"


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux component installation paths")
class LinuxComponentCacheTests(unittest.TestCase):
    def test_native_mpv_cache_replays_into_build_and_desktop_layouts(self):
        from src.runtime import mpv_environment
        from tools import linux_setup_cache as cache

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            command, native = root / "mpv", root / "mpv-bluraysubtitle-native"
            native_image = b"\x7fELF" + b"native test image"
            command.write_bytes(mpv_environment.MPV_LAUNCHER)
            native.write_bytes(native_image)
            native.chmod(0o755)
            archive = root / "mpv-ffmpeg.tar.xz"
            scope = cache.InstallPaths(root, [command], system=False)
            with patch.multiple(mpv_environment, MPV_COMMAND=command, MPV_NATIVE=native):
                cache.save_cache(archive, "release", {}, scope, "")
                native.unlink()
                cache.restore_cache(archive, "release", scope)
                self.assertEqual(command.read_bytes(), mpv_environment.MPV_LAUNCHER)
                self.assertEqual(native.read_bytes(), native_image)
                command.unlink()
                native.unlink()
                cache.restore_cache(archive, "release", scope)
                self.assertEqual(command.read_bytes(), native_image)

    def test_already_installed_component_and_unchanged_model_restore_together(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            component = root / "example.tar.xz"
            plugin = root / "plugins/example.so"
            model = plugin.parent / "models/network.bin"
            model.parent.mkdir(parents=True)
            plugin.write_bytes(b"installed plugin")
            model.write_bytes(b"model")

            def cache(operation, recipe="release-1", restored="", check=True):
                return subprocess.run(
                    [sys.executable, "-B", HELPER, operation, component, root / "before.json",
                     recipe, "files", plugin.parent, restored, plugin, model],
                    capture_output=True, text=True, check=check,
                )

            cache("snapshot")
            cache("save")
            with tarfile.open(component) as archive:
                record = json.load(archive.extractfile("build.json"))
            self.assertEqual(set(record["files"]), {str(plugin), str(model)})
            timestamp = component.stat().st_mtime_ns
            plugin.unlink()
            model.unlink()
            self.assertNotEqual(cache("restore", "release-2", check=False).returncode, 0)
            self.assertFalse(plugin.exists())
            self.assertEqual(cache("restore").stdout.strip(), "release-1")
            self.assertEqual(plugin.read_bytes(), b"installed plugin")
            self.assertEqual(model.read_bytes(), b"model")
            cache("save", restored="release-1")
            self.assertEqual(component.stat().st_mtime_ns, timestamp)
