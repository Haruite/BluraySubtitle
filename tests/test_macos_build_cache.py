"""The macOS build plan and restored archives must describe the same installed products."""

from pathlib import Path
import tempfile
import unittest

from tools.macos_build_support import Build


class MacBuildCacheTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.ctx = object.__new__(Build)
        self.ctx.cache = Path(work.name)
        self.ctx.arch = "x86_64"
        self.ctx.identities = {"native": "test-sdk"}
        self.ctx.conda = {"lib": ("lib-1", ["codec"]), "codec": ("codec-2", ()), "unrelated": ("other-1", ())}
        self.ctx.components = self.ctx.cache / "components"
        self.ctx.components.mkdir()
        self.ctx.prefix = self.ctx.cache / "installation"
        self.ctx.expected = None
        self.ctx.built = {}
        self.ctx.restore = False
        self.ctx.planning = True

    @staticmethod
    def install(work, stage):
        (stage / "tool").write_bytes(b"compiled tool")

    def plan(self, revision="1"):
        self.ctx.component("sdk", revision, self.install, packages=("lib",))
        self.ctx.component("tool", "v1", self.install, dependencies=("sdk",))
        self.ctx.component("other", "v1", self.install)
        return self.ctx.built.copy()

    def test_keys_follow_only_the_selected_component_and_dependency_versions(self):
        initial = self.plan()
        self.ctx.conda["unrelated"] = ("other-2", ())
        self.assertEqual(self.plan(), initial)
        self.ctx.conda["codec"] = ("codec-3", ())
        revised = self.plan()
        self.assertNotEqual(revised["sdk"], initial["sdk"])
        self.assertNotEqual(revised["tool"], initial["tool"])
        self.assertEqual(revised["other"], initial["other"])
        self.ctx.arch = "arm64"
        self.assertNotEqual(self.plan()["other"], initial["other"])
        self.assertFalse(self.ctx.prefix.exists())

    def test_restore_only_and_normal_build_handle_a_damaged_archive(self):
        self.ctx.planning = False
        self.ctx.component("tool", "v1", self.install)
        output = self.ctx.prefix / "tool"
        output.unlink()
        self.ctx.restore = True
        self.ctx.component("tool", "v1", lambda *_: self.fail("Unexpected compiler invocation"))
        self.assertEqual(output.read_bytes(), b"compiled tool")
        archive, = self.ctx.components.glob("*.tar.gz")
        archive.write_bytes(b"interrupted download")
        with self.assertRaises(ValueError):
            self.ctx.component("tool", "v1", self.install)
        self.assertEqual(output.read_bytes(), b"compiled tool")
        self.ctx.restore = False
        self.ctx.component("tool", "v1", self.install)
        self.ctx.restore = True
        self.ctx.component("tool", "v1", lambda *_: self.fail("Repair did not produce a usable archive"))
        self.ctx.expected = {"tool": "obsolete-key"}
        with self.assertRaisesRegex(ValueError, "changed after resolving"):
            self.ctx.component("tool", "v2", self.install)
