"""Prepare a verified replacement while the old bundled Python is still in place."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import posixpath
import re
import stat
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

NAME = "BluraySubtitle.app"


def extract_package(plan: dict, archive: Path, destination: Path) -> Path:
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != plan["sha256"]:
            raise ValueError(plan["invalid_digest"])
    # ditto preserves macOS signatures and symlinks. Check the entry paths and link
    # destinations before extraction, including entries nested below other links.
    with zipfile.ZipFile(archive) as package:
        paths = set()
        filesystem_names = set()
        links = {}
        for entry in package.infolist():
            path = PurePosixPath(entry.filename)
            name = unicodedata.normalize("NFD", str(path)).casefold()
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if (kind not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK)
                    or name in filesystem_names or path.is_absolute() or ".." in path.parts
                    or path.parts[:1] not in ((NAME,), ("__MACOSX",))):
                raise ValueError(plan["invalid_package"])
            filesystem_names.add(name)
            paths.add(path)
            if kind == stat.S_IFLNK:
                if entry.file_size > 4096:
                    raise ValueError(plan["invalid_package"])
                target = os.fsdecode(package.read(entry))
                resolved = PurePosixPath(posixpath.normpath(str(path.parent / target)))
                if not target or resolved.parts[:1] != (NAME,) or path.parts[:1] != (NAME,):
                    raise ValueError(plan["invalid_package"])
                links[path] = resolved
        # A case-insensitive or normalization-insensitive volume aliases path components.
        link_names = {unicodedata.normalize("NFD", str(link)).casefold() for link in links}
        if (any(unicodedata.normalize("NFD", str(parent)).casefold() in link_names
                for path in paths for parent in path.parents)
                or any(target not in paths for target in links.values())):
            raise ValueError(plan["invalid_package"])
    subprocess.run(["/usr/bin/ditto", "-x", "-k", archive, destination], check=True)
    app = destination / NAME
    for link in links:
        if not (destination / link).resolve(strict=True).is_relative_to(app.resolve(strict=True)):
            raise ValueError(plan["invalid_package"])
    runtime = app / "Contents/Resources/Runtime"
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if (app.is_symlink() or info.get("CFBundleIdentifier") != "io.github.haruite.BluraySubtitle"
            or info.get("CFBundleExecutable") != "BluraySubtitle" or info.get("CFBundlePackageType") != "APPL"
            or not os.access(app / "Contents/MacOS/BluraySubtitle", os.X_OK)
            or json.loads((runtime / "runtime.json").read_text())["architecture"] != plan["arch"]
            or not (runtime / "app/build-commit.txt").is_file()):
        raise ValueError(plan["invalid_package"])
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", app], check=True)
    return app


def prepare(work: Path, plan: dict) -> None:
    url = urlsplit(plan["url"])
    if (url.scheme != "https" or url.netloc not in ("github.com", plan["server_origin"])
            or url.username or url.password or not re.fullmatch(r"[0-9a-f]{64}", plan["sha256"])):
        raise ValueError(plan["invalid_package"])
    archive = work / "package.zip"
    subprocess.run(["/usr/bin/curl", "--fail", "--silent", "--show-error", "--location", "--proto", "=https",
                    "--proto-redir", "=https", "--retry", "3", "--connect-timeout", "20", "--max-time", "900",
                    "--header", "Cache-Control: no-cache", "--output", archive, plan["url"]], check=True)
    extract_package(plan, archive, work / "incoming")


if __name__ == "__main__":
    workspace = Path(__file__).resolve().parent
    plan = json.loads((workspace / "update.json").read_text())
    sys.stdin.buffer.read()
    try:
        prepare(workspace, plan)
    except Exception as error:
        (workspace / "failure.txt").write_text(f"{plan['failure']}\n{error}", encoding="utf-8")
    # The installed interpreter and standard library may change ABI during the swap.
    # Finish with native system tools. Keep the per-installation lock through launch.
    os.dup2(int(sys.argv[1]), 9, inheritable=True)
    os.set_inheritable(9, True)
    os.execv("/bin/bash", ["bash", str(workspace / "macos_finish_update.sh"), str(workspace), plan["app"],
                           plan["failure"], plan["restart_failed"]])
