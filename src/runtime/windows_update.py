"""Select verified Windows packages and hand installation to a detached updater."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from src.core.app_config import app_config_path
from src.core.i18n import translate_text
from src.runtime.windows_shell import launch_system_powershell


WINDOWS_PACKAGE_NAME = "BluraySubtitle_windows_x64"
WINDOWS_PACKAGE_ARCHIVE = f"{WINDOWS_PACKAGE_NAME}.7z"
GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/Haruite/BluraySubtitle/releases/latest"
SERVER_WINDOWS_PACKAGE_URL = f"https://sbx.mysmy.top/tools/{WINDOWS_PACKAGE_ARCHIVE}"
_UPDATER_SCRIPT = Path("tools") / "windows_update.ps1"


@dataclass(frozen=True)
class WindowsUpdatePackage:
    url: str
    sha256: str


def github_windows_package(payload: dict[str, object]) -> WindowsUpdatePackage | None:
    tag = payload.get("tag_name")
    assets = payload.get("assets")
    if not isinstance(tag, str) or not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != WINDOWS_PACKAGE_ARCHIVE:
            continue
        digest = asset.get("digest")
        if isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            url = f"https://github.com/Haruite/BluraySubtitle/releases/download/{quote(tag, safe='')}/{WINDOWS_PACKAGE_ARCHIVE}"
            return WindowsUpdatePackage(url, digest.removeprefix("sha256:").lower())
    return None


def server_windows_package(record: str) -> WindowsUpdatePackage | None:
    fields = dict(line.split("=", 1) for line in record.splitlines() if "=" in line)
    digest = fields.get("sha256", "").lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest):
        return WindowsUpdatePackage(f"{SERVER_WINDOWS_PACKAGE_URL}?sha256={digest}", digest)
    return None


def windows_update_executable() -> Path | None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return None
    executable = Path(sys.executable).resolve()
    runtime = executable.parent / "_internal"
    if (
        runtime == Path(sys._MEIPASS).resolve()
        and executable.is_file()
        and (runtime / "7z.exe").is_file()
        and (runtime / "7z.dll").is_file()
        and (runtime / _UPDATER_SCRIPT).is_file()
    ):
        return executable
    return None


def start_windows_update(package: WindowsUpdatePackage) -> None:
    executable = windows_update_executable()
    if executable is None:
        raise RuntimeError(translate_text("Direct updates require the packaged Windows program and its bundled 7-Zip."))
    install = executable.parent
    runtime = install / "_internal"
    config_directory = app_config_path().parent
    relative_config = str(config_directory.relative_to(runtime)) if config_directory.is_relative_to(runtime) else None
    plan = {
        "pid": os.getpid(),
        "executable": executable.name,
        "workingDirectory": os.getcwd(),
        "configDirectory": relative_config,
        "url": package.url,
        "sha256": package.sha256,
        "mutex": "Local\\BluraySubtitleUpdate-" + hashlib.sha256(os.path.normcase(str(install)).encode()).hexdigest(),
        "title": translate_text("Update BluraySubtitle"),
        "failure": translate_text("Could not update the program."),
        "busy": translate_text("An update is already running for this installation."),
        "invalidPackage": translate_text("The Windows update package is incomplete or has an unexpected layout."),
        "invalidDigest": translate_text("The downloaded package failed SHA-256 verification."),
        "extractFailed": translate_text("The bundled 7-Zip could not extract the update package."),
        "restartFailed": translate_text("The updated program could not start."),
        "unsafePath": translate_text("The updater found an unexpected program or update path."),
        "cleanupFailed": translate_text("The update finished, but some previous files could not be removed."),
    }
    workspace = Path(tempfile.mkdtemp(prefix=".bluraysubtitle-update-", dir=install))
    script = workspace / _UPDATER_SCRIPT.name
    manifest = workspace / "update.json"
    try:
        plan["backup"] = translate_text("Update files are in {path}.").format(path=workspace)
        shutil.copyfile(runtime / _UPDATER_SCRIPT, script)
        manifest.write_text(json.dumps(plan), encoding="utf-8")
        launch_system_powershell(
            ["-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=install, environment={"PYINSTALLER_RESET_ENVIRONMENT": "1"},
        )
    except Exception:
        for path in (manifest, script):
            with suppress(OSError):
                path.unlink()
        with suppress(OSError):
            workspace.rmdir()
        raise
