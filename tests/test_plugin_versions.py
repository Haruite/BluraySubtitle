import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.vapoursynth_plugin_releases import SOURCES, latest_tag, znedi3_release
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
            ("29.0", "v29_2", False),
            ("v29_2", "v29", True),
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

    def test_keeps_source_tag_when_plugin_reports_an_older_version(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "mvtools.so"
            plugin.write_bytes(b"plugin")
            record_version(plugin, "v29_2", "29.0")
            self.assertEqual(fallback_version(plugin, normalize=False), "v29_2")

    def test_prefers_latest_stable_tag_within_the_runtime_limit(self):
        refs = "\n".join(f"sha\trefs/tags/{tag}" for tag in ("v9", "v26", "v29", "v29_2", "v30-rc1"))
        with patch("tools.vapoursynth_plugin_releases.subprocess.check_output", return_value=refs):
            self.assertEqual(latest_tag(SOURCES["mvtools"], "git", classic=False), "v29_2")
            self.assertEqual(latest_tag(SOURCES["mvtools"], "git", classic=True), "v26")

    def test_znedi3_uses_the_latest_stable_non_yanked_source(self):
        source = {
            "packagetype": "sdist", "filename": "source.tar.gz", "digests": {"sha256": "checksum"},
            "url": "https://files.pythonhosted.org/source.tar.gz", "yanked": False,
        }
        metadata = {"releases": {
            "3.3": [source],
            "4.0": [dict(source, yanked=True)],
            "4.1": [dict(source, packagetype="bdist_wheel")],
            "4.2rc1": [source],
        }}
        with patch("tools.vapoursynth_plugin_releases.urllib.request.urlopen"), \
             patch("tools.vapoursynth_plugin_releases.json.load", return_value=metadata):
            release = znedi3_release()
        self.assertEqual((release.ref, release.source_url, release.sha256), ("3.3", source["url"], "checksum"))


if __name__ == "__main__":
    unittest.main()
