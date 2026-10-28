import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.vapoursynth_plugin_versions import fallback_version, record_version, reported_version, usable_version, version_satisfies


class PluginVersionTests(unittest.TestCase):
    def test_stale_upstream_nlm_version_requires_a_fallback_record(self):
        plugin = SimpleNamespace(
            name="Non-local means denoise filter implemented in ISPC",
            functions=lambda: [SimpleNamespace(name="Version", signature="")],
            Version=lambda: {"version": b"3"},
            version=SimpleNamespace(major=-1, minor=0),
        )
        with patch.dict("sys.modules", {"vapoursynth": SimpleNamespace(Error=RuntimeError)}):
            self.assertIsNone(reported_version(plugin, "v4"))
            self.assertEqual(reported_version(plugin, "v3"), "3")

    def test_only_complete_native_versions_identify_pinned_releases(self):
        for value, target, expected in (
            (b"r10", "r10", "10"),
            ({"version": b"v26-0-g1234567"}, "v26", "26"),
            ("12.0", "r12.A", None),
            ("13.0", "r12.A", "13.0"),
            ("2.0", "2.0.4", None),
            ("2.1", "2.0.4", "2.1"),
            ("0.1", "v0.1-fix", None),
            ("r12.A", "r12.A", "12.A"),
            ("r1282-4-gae51313", "commit:ae51313", "commit:ae51313"),
            ("r1282", "commit:ae51313", None),
        ):
            with self.subTest(value=value, target=target):
                self.assertEqual(usable_version(value, target), expected)

    def test_release_ordering_preserves_newer_plugins(self):
        for installed, target, expected in (
            ("r10", "r9", True),
            ("r9", "r10", False),
            ("r7.1", "r7.1", True),
            ("r7", "r7.1", False),
            ("r12.A", "r12", True),
            ("r12", "r12.A", False),
            ("2.0.4~rc1", "2.0.4", False),
            ("0.1-fix", "v0.1", True),
            ("0.1-10", "0.1-9", True),
            ("commit:ae51313", "commit:ae51313", True),
            ("commit:ae51313", "commit:1234567", False),
            ("1282", "commit:ae51313", False),
        ):
            with self.subTest(installed=installed, target=target):
                self.assertEqual(version_satisfies(installed, target), expected)

    def test_fallback_records_require_the_same_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.dll"
            second = Path(directory) / "second.so"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            record_version(first, "r12.A", None)
            record_version(second, "v0.1-fix", None)
            self.assertEqual(fallback_version(first), "12.A")
            self.assertEqual(fallback_version(second), "0.1-fix")
            first.write_bytes(b"replaced")
            self.assertIsNone(fallback_version(first))
            record_version(first, "r13", "13.0")
            self.assertIsNone(fallback_version(first))
            self.assertEqual(fallback_version(second), "0.1-fix")


if __name__ == "__main__":
    unittest.main()
