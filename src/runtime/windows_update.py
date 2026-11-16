"""Select verified Windows packages and hand installation to a detached updater."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import sysconfig
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.app_config import app_config_path
from src.core.i18n import translate_text
from src.core.tool_paths import require_tool_path
from src.runtime.windows_shell import launch_system_powershell

if TYPE_CHECKING:
    from .program_update import UpdatePackage


WINDOWS_ARCHITECTURE = "arm64" if sysconfig.get_platform() == "win-arm64" else "x64"
WINDOWS_PACKAGE_NAME = f"BluraySubtitle_windows_{WINDOWS_ARCHITECTURE}"
PACKAGE_ARCHIVE = f"{WINDOWS_PACKAGE_NAME}.7z"
SERVER_PACKAGE_URL = f"https://sbx.mysmy.top/tools/BluraySubtitle/{PACKAGE_ARCHIVE}"
_UPDATER_SCRIPT = Path("tools") / "windows_update.ps1"


def update_executable() -> Path | None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return None
    executable = Path(sys.executable).resolve()
    runtime = executable.parent / "_internal"
    if (
        runtime == Path(sys._MEIPASS).resolve()
        and executable.is_file()
        and (runtime / _UPDATER_SCRIPT).is_file()
    ):
        return executable
    return None


def start_update(package: UpdatePackage) -> None:
    executable = update_executable()
    if executable is None:
        raise RuntimeError(translate_text("Direct updates require the packaged Windows program."))
    seven_zip = require_tool_path("SEVEN_ZIP_PATH")
    install = executable.parent
    runtime = install / "_internal"
    config_directory = app_config_path().parent
    relative_config = str(config_directory.relative_to(runtime)) if config_directory.is_relative_to(runtime) else None
    plan = {
        "pid": os.getpid(),
        "executable": executable.name,
        "packageName": WINDOWS_PACKAGE_NAME,
        "workingDirectory": os.getcwd(),
        "configDirectory": relative_config,
        "sevenZip": seven_zip,
        "url": package.url,
        "sha256": package.sha256,
        "mutex": "Local\\BluraySubtitleUpdate-" + hashlib.sha256(os.path.normcase(str(install)).encode()).hexdigest(),
        "title": translate_text("Update BluraySubtitle"),
        "failure": translate_text("Could not update the program."),
        "busy": translate_text("An update is already running for this installation."),
        "invalidPackage": translate_text("The Windows update package is incomplete or has an unexpected layout."),
        "invalidDigest": translate_text("The downloaded package failed SHA-256 verification."),
        "extractFailed": translate_text("7-Zip could not extract the update package using {path}.").format(path=seven_zip),
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
