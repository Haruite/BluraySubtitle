import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.ubuntu_actions_cache import apt_fingerprint, outdated_cache_ids, snapshot_keys


class UbuntuActionsCacheTests(unittest.TestCase):
    def test_snapshot_keys_follow_payload_and_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, home = root / "cache", root / "home"
            data = cache / "ccache" / "a" / "compiled"
            data.parent.mkdir(parents=True)
            data.write_bytes(b"object")
            keys = snapshot_keys(cache, home, "X64")

            (data.parent / "stats").write_text("new hit", encoding="utf-8")
            data.touch()
            self.assertEqual(snapshot_keys(cache, home, "X64"), keys)
            self.assertNotEqual(snapshot_keys(cache, home, "ARM64")["setup"], keys["setup"])

            data.write_bytes(b"changed object")
            self.assertNotEqual(snapshot_keys(cache, home, "X64")["setup"], keys["setup"])

    def test_apt_key_requires_the_payload_referenced_by_the_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            deb = cache / "apt/libsample_1_arm64.deb"
            manifest = cache / "apt-runtime/packages.json"
            deb.parent.mkdir()
            manifest.parent.mkdir()
            deb.write_bytes(b"package bytes")
            manifest.write_text(json.dumps([
                ["libsample", "arm64", "1", [deb.name, hashlib.sha256(deb.read_bytes()).hexdigest()]],
            ]), encoding="utf-8")

            self.assertTrue(apt_fingerprint(cache))
            deb.write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                apt_fingerprint(cache)
            deb.unlink()
            with self.assertRaises(ValueError):
                apt_fingerprint(cache)

    def test_pruning_keeps_restored_and_newer_snapshots_within_scope(self):
        def entry(cache_id, key, ref="refs/heads/main"):
            return {"id": cache_id, "key": key, "ref": ref, "created_at": "2026-11-16T00:00:00Z", "size_in_bytes": 1}

        entries = [
            entry(1, "ubuntu2604-tools-v2-X64-" + "a" * 64),
            entry(2, "ubuntu2604-tools-v3-X64-" + "b" * 64),
            entry(3, "ubuntu2604-tools-v3-X64-" + "c" * 64),
            entry(4, "ubuntu2604-tools-v3-ARM64-" + "d" * 64),
            entry(5, "ubuntu2604-tools-v3-X64-" + "e" * 64, "refs/heads/other"),
            entry(6, "windows-tools-v3-X64-" + "f" * 64),
        ]
        self.assertEqual(outdated_cache_ids(entries, "X64", {"tools": entries[0]["key"]}), [])
        self.assertEqual(outdated_cache_ids(entries, "X64", {"tools": entries[1]["key"]}), [1])
        self.assertEqual(outdated_cache_ids(entries, "X64", {"tools": entries[2]["key"]}), [1])
        self.assertEqual(outdated_cache_ids(entries, "ARM64", {"tools": entries[2]["key"]}), [])


if __name__ == "__main__":
    unittest.main()
