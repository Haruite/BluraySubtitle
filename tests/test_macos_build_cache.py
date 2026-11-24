"""The macOS build plan and restored archives must describe the same installed products."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.macos_actions_cache import main as snapshot
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

    def test_failed_build_can_save_completed_current_components(self):
        self.ctx.expected = self.plan()
        self.ctx.built.clear()
        self.ctx.planning = False
        output = self.ctx.cache / "step-outputs"
        plan = self.ctx.cache / "build-plan.json"
        plan.write_text(json.dumps({"components": self.ctx.expected}), encoding="utf-8")

        def fail_after_writing(work, stage):
            (stage / "partial").write_bytes(b"unfinished")
            raise RuntimeError("build failed")

        self.ctx.component("sdk", "1", self.install, packages=("lib",))
        with self.assertRaisesRegex(RuntimeError, "build failed"):
            self.ctx.component("tool", "v1", fail_after_writing, dependencies=("sdk",))
        (self.ctx.components / "obsolete.tar.gz").write_bytes(b"old component")
        (self.ctx.components / "obsolete.tar.sha256").write_bytes(b"old checksum")
        with patch.dict(os.environ, BLURAY_SETUP_CACHE_DIR=str(self.ctx.cache), BLURAY_MACOS_CACHE_PLAN=str(plan),
                        GITHUB_OUTPUT=str(output), PACKAGE_CACHE_PREFIX="macos-build-v1-x64-",
                        GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1"):
            snapshot()
        key = self.ctx.expected["sdk"]
        self.assertRegex(output.read_text(), r"^key=macos-build-v1-x64-[0-9a-f]{64}-123-1\n$")
        self.assertEqual({p.name for p in self.ctx.components.iterdir()},
                         {f"sdk-{key}.tar.gz", f"sdk-{key}.tar.sha256"})

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
