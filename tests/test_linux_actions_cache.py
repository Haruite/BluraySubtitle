import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.actions_cache import superseded_snapshot_ids
from tools.linux_actions_cache import apt_fingerprint, snapshot_checksums


class LinuxActionsCacheTests(unittest.TestCase):
    def test_snapshot_checksum_follows_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, home = root / "cache", root / "home"
            data = cache / "ccache" / "a" / "compiled"
            data.parent.mkdir(parents=True)
            data.write_bytes(b"object")
            checksums = snapshot_checksums(cache, home)

            (data.parent / "stats").write_text("new hit", encoding="utf-8")
            data.touch()
            self.assertEqual(snapshot_checksums(cache, home), checksums)

            data.write_bytes(b"changed object")
            self.assertNotEqual(snapshot_checksums(cache, home)["setup"], checksums["setup"])

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

    def test_pruning_keeps_one_confirmed_snapshot_within_scope(self):
        def entry(cache_id, key, ref="refs/heads/main", size=1):
            return {"id": cache_id, "key": key, "ref": ref, "created_at": "2026-11-16T00:00:00Z", "size_in_bytes": size}

        prefix = "ubuntu2604-build-v1-x64-"
        legacy = ("ubuntu2604-tools-v3-X64-",)
        entries = [
            entry(1, prefix + "old"),
            entry(2, prefix + "retained"),
            entry(3, prefix + "new"),
            entry(4, legacy[0] + "old"),
            entry(5, "ubuntu2604-build-v1-arm64-other"),
            entry(6, prefix + "other-branch", "refs/heads/other"),
            entry(7, prefix + "pending", size=0),
        ]
        self.assertEqual(superseded_snapshot_ids(entries, prefix, prefix + "absent", legacy), [])
        self.assertEqual(superseded_snapshot_ids(entries, prefix, prefix + "pending", legacy), [])
        self.assertEqual(superseded_snapshot_ids(entries, prefix, prefix + "retained", legacy), [1, 4])
        self.assertEqual(superseded_snapshot_ids(entries, prefix, prefix + "new", legacy), [1, 2, 4])


if __name__ == "__main__":
    unittest.main()
