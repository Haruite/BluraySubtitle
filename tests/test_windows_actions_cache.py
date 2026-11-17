from dataclasses import replace
from inspect import getsource
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from tools import install_vapoursynth_windows_components as plugins
from tools.windows_actions_cache import outdated_cache_ids, snapshot_keys, tool_fingerprint
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
            keys = snapshot_keys(pip.parent, archive.parent, "X64")

            with ZipFile(archive) as cached:
                entries = [(name, cached.read(name)) for name in cached.namelist()]
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as cached:
                for name, content in reversed(entries):
                    cached.writestr(name, content)
            metadata.write_bytes(b"refreshed headers")
            self.assertEqual(snapshot_keys(pip.parent, archive.parent, "X64"), keys)
            self.assertNotEqual(snapshot_keys(pip.parent, archive.parent, "ARM64"), keys)

            body.write_bytes(b"new wheel")
            updated = snapshot_keys(pip.parent, archive.parent, "X64")
            self.assertNotEqual(updated["pip"], keys["pip"])
            self.assertEqual(updated["tools"], keys["tools"])

            with ZipFile(archive, "w") as cached:
                for name, content in entries:
                    cached.writestr(name, b"corrupt binary" if name == artifact.name else content)
            with self.assertRaisesRegex(ValueError, "Invalid cached file"):
                tool_fingerprint(archive.parent)

    def test_pruning_requires_a_verified_snapshot_in_its_family(self):
        def entry(cache_id, prefix, ref="refs/heads/main"):
            return {"id": cache_id, "key": prefix + f"{cache_id:064x}", "ref": ref,
                    "created_at": "2026-11-17T00:00:00Z", "size_in_bytes": 1}

        entries = [
            entry(1, "windows-tools-v3-ARM64-"),
            entry(2, "windows-tools-v4-ARM64-"),
            entry(3, "windows-tools-v4-ARM64-"),
            entry(4, "windows-tools-v4-ARM64-"),
            entry(5, "windows-tools-v4-X64-"),
            entry(6, "windows-pip-v1-ARM64-"),
            entry(7, "windows-tools-v4-ARM64-", "refs/heads/other"),
        ]
        self.assertEqual(outdated_cache_ids(entries, "ARM64", {"tools": entries[0]["key"]}), [])
        self.assertEqual(outdated_cache_ids(entries, "ARM64", {"tools": entries[2]["key"]}), [2, 1])
        self.assertEqual(outdated_cache_ids(entries, "ARM64", {"tools": entries[3]["key"]}), [2, 1])

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
