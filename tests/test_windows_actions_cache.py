from dataclasses import replace
from inspect import getsource
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from tools import install_vapoursynth_windows_components as plugins
from tools.windows_actions_cache import legacy_cache_prefixes, snapshot_checksums, split_x64_artifacts, tool_fingerprint
from tools.windows_build_cache import publish, restore


class WindowsActionsCacheTests(unittest.TestCase):
    def test_snapshot_follows_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pip = root / "pip/http-v2"
            pip.mkdir(parents=True)
            metadata = pip / "download"
            body = pip / "download.body"
            metadata.write_bytes(b"headers")
            body.write_bytes(b"wheel")
            artifact = root / "encoder.exe"
            artifact.write_bytes(b"encoder")
            archive = root / "tools/encoder.zip"
            publish(archive, "recipe", {artifact.name: artifact})
            keys = snapshot_checksums(pip.parent, archive.parent, "X64")

            with ZipFile(archive) as cached:
                entries = [(name, cached.read(name)) for name in cached.namelist()]
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as cached:
                for name, content in reversed(entries):
                    cached.writestr(name, content)
            metadata.write_bytes(b"refreshed headers")
            self.assertEqual(snapshot_checksums(pip.parent, archive.parent, "X64"), keys)

            body.write_bytes(b"new wheel")
            updated = snapshot_checksums(pip.parent, archive.parent, "X64")
            self.assertNotEqual(updated["pip"], keys["pip"])
            self.assertEqual(updated["shared"], keys["shared"])

            with ZipFile(archive, "w") as cached:
                for name, content in entries:
                    cached.writestr(name, b"corrupt binary" if name == artifact.name else content)
            with self.assertRaisesRegex(ValueError, "Invalid cached file"):
                tool_fingerprint(archive.parent)

    def test_shared_legacy_cache_remains_until_both_x64_variants_are_migrated(self):
        shared = "windows-shared-v1-X64-"
        standard = {"key": "windows-build-v1-x64-standard-test", "ref": "refs/heads/main", "size_in_bytes": 1}
        compat = {"key": "windows-build-v1-x64-compat-test", "ref": "refs/heads/main", "size_in_bytes": 1}
        self.assertNotIn(shared, legacy_cache_prefixes([standard, {**compat, "size_in_bytes": 0}], "X64", False))
        self.assertIn(shared, legacy_cache_prefixes([standard, compat], "X64", False))
        self.assertIn(shared, legacy_cache_prefixes([standard, compat], "X64", True))
        self.assertNotIn(shared, legacy_cache_prefixes([standard, compat], "ARM64", False))
        self.assertNotIn("windows-compat-v1-X64-", legacy_cache_prefixes([standard, compat], "X64", False))

    def test_compatibility_downloads_and_builds_have_their_own_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / "compat"
            args = (root / "pip", root / "tools", "X64")
            source = work / "downloads/source.tar.gz"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"source")
            first = snapshot_checksums(*args, compatibility=work)
            archive = work / "cache/tool.zip"
            publish(archive, "compatibility recipe", {"tool.dll": source})
            second = snapshot_checksums(*args, compatibility=work)
            self.assertNotEqual(second["compat"], first["compat"])
            self.assertNotIn("compat", snapshot_checksums(*args))

            source.write_bytes(b"new source")
            self.assertNotEqual(snapshot_checksums(*args, compatibility=work)["compat"], second["compat"])

    def test_x64_compatibility_only_reuses_shared_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "artifacts"
            payload = root / "binary"
            payload.write_bytes(b"build")
            shared = {"ffmpeg", "vs-r79-lsmas", "vs-r79-nlm_ispc", "fftw"}
            standard = {"mkvtoolnix", "mkvtoolnix-qtcore", "vsedit", "vs-r79-placebo", "vs-r79-zsmooth",
                        "dovi-tool", "hdr10plus-tool", "vapoursynth-classic"}
            for name in shared | standard:
                publish(tools / (name + ".zip"), name, {name: payload})
            split_x64_artifacts(tools)
            self.assertEqual({file.stem for file in tools.glob("*.zip")}, shared)
            self.assertEqual({file.stem for file in (tools / "standard").glob("*.zip")}, standard)
            args = (root / "pip", tools, "X64")
            regular = snapshot_checksums(*args)
            compat = snapshot_checksums(*args, compatibility=root / "compat")
            self.assertEqual(set(regular), {"shared", "standard"})
            self.assertEqual(compat, {"shared": regular["shared"]})

    def test_component_accepts_compatible_legacy_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "tool.exe"
            artifact.write_bytes(b"old build")
            archive = root / "tool.zip"
            publish(archive, "previous", {artifact.name: artifact})
            destination = root / "restored"
            self.assertIsNone(restore(archive, "current", destination))
            self.assertEqual(restore(archive, "current", destination, legacy_keys=("previous",)), "previous")
            self.assertEqual((destination / artifact.name).read_bytes(), artifact.read_bytes())

    def test_plugin_keys_ignore_logs_and_follow_source_and_build_inputs(self):
        installer = plugins.Installer.__new__(plugins.Installer)
        installer.r79 = True
        installer.arm64 = True
        installer.subsystem = "clangarm64"
        installer.static_runtime = "-static"
        installer.sdk_hashes = {"VapourSynth4.h": "checksum"}
        component = next(item for item in plugins.COMPONENTS if item.key == "addgrain")
        ref = "v1.0"
        original, legacy = installer.component_cache_keys(component, ref, plugins.BUILD_PROFILE)

        def log_added(method):
            source = getsource(method)
            if method.__name__ == "run_msys":
                signature, body = source.split("\n", 1)
                return signature + '\n        self.log("Compiling")\n' + body
            return source

        with patch.object(plugins, "getsource", side_effect=log_added):
            key, changed_legacy = installer.component_cache_keys(component, ref, plugins.BUILD_PROFILE)
        self.assertEqual(key, original)
        self.assertNotEqual(changed_legacy, legacy)
        self.assertNotEqual(installer.component_cache_keys(replace(component, ref="v2.0"), "v2.0", plugins.BUILD_PROFILE)[0], original)
        installer.static_runtime = "-static -s"
        self.assertNotEqual(installer.component_cache_keys(component, ref, plugins.BUILD_PROFILE)[0], original)


if __name__ == "__main__":
    unittest.main()
