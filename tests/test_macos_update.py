"""Check that unusable macOS release archives are rejected before installation."""

import hashlib
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools.macos_update import extract_package


class MacUpdateTests(unittest.TestCase):
    def test_invalid_digest_preserves_installed_application(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "BluraySubtitle.app"
            current.mkdir()
            archive = root / "package.zip"
            archive.write_bytes(b"incomplete download")
            with self.assertRaisesRegex(ValueError, "digest"):
                extract_package({"sha256": "0" * 64, "invalid_digest": "digest"}, archive, root / "incoming")
            self.assertTrue(current.is_dir())
            self.assertFalse((root / "incoming").exists())

    def test_archive_layout_is_validated_before_running_system_tools(self):
        for entries in (["Other.app/Contents/Info.plist"],
                        ["BluraySubtitle.app/Contents/Info.plist", "BluraySubtitle.app/Contents/info.plist"]):
            with self.subTest(entries=entries), TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / "package.zip"
                with zipfile.ZipFile(archive, "w") as package:
                    for name in entries:
                        package.writestr(name, b"metadata")
                plan = {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "invalid_package": "layout"}
                with patch("tools.macos_update.subprocess.run") as run, self.assertRaisesRegex(ValueError, "layout"):
                    extract_package(plan, archive, root / "incoming")
                run.assert_not_called()
                self.assertFalse((root / "incoming").exists())
