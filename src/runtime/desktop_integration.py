"""Create per-user launch shortcuts for the current installation."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

from PyQt6.QtCore import QIODevice, QSaveFile, QStandardPaths
from PyQt6.QtGui import QIcon

from src.core.app_config import application_directory, application_location_id, application_support_directory
from src.core.i18n import translate_text
from src.core.settings import is_docker
from src.runtime.windows_shell import launch_system_powershell


_WINDOWS_SHORTCUT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    $plan = $env:BLURAYSUBTITLE_SHORTCUT | ConvertFrom-Json
    $shell = New-Object -ComObject WScript.Shell
    $folder = $shell.SpecialFolders.Item($plan.folder)
    if ([string]::IsNullOrWhiteSpace($folder)) { throw $plan.missingFolder }
    [void][IO.Directory]::CreateDirectory($folder)
    $path = Join-Path $folder 'BluraySubtitle.lnk'
    $link = $shell.CreateShortcut($path)
    if ((Test-Path -LiteralPath $path) -and ($link.TargetPath -ne $plan.target -or $link.Arguments -ne $plan.arguments)) {
        $path = Join-Path $folder "BluraySubtitle ($($plan.location)).lnk"
        $link = $shell.CreateShortcut($path)
    }
    $link.TargetPath = $plan.target
    $link.Arguments = $plan.arguments
    $link.WorkingDirectory = $plan.workingDirectory
    $link.IconLocation = "$($plan.icon),0"
    $link.Description = 'BluraySubtitle'
    $link.Save()
    [Console]::WriteLine($path)
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


def application_icon_path() -> Path:
    return application_support_directory() / "resource" / "bluraysubtitle.svg"


def desktop_entry_id() -> str:
    return f"bluraysubtitle-{application_location_id()}"


def create_launch_shortcut(*, menu: bool) -> Path:
    directory = application_directory()
    executable = Path(os.path.abspath(sys.executable))
    frozen = bool(getattr(sys, "frozen", False))
    command = [str(executable)] if frozen else [str(executable), str(directory / "src" / "main.py")]
    if sys.platform == "win32":
        icon = executable if frozen else _windows_source_icon()
        if not frozen and executable.with_name("pythonw.exe").is_file():
            command[0] = str(executable.with_name("pythonw.exe"))
        return _create_windows_shortcut(command, directory, icon, menu=menu)
    if sys.platform.startswith("linux"):
        if is_docker():
            raise RuntimeError(translate_text("Run the application on the host desktop to create shortcuts."))
        return _create_linux_shortcut(command, directory, menu=menu)
    raise RuntimeError(translate_text("Desktop shortcuts are unavailable on this platform."))


def _windows_source_icon() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    if not location:
        raise OSError(translate_text("This desktop does not provide a shortcut directory."))
    path = Path(location) / "BluraySubtitle" / "bluraysubtitle.ico"
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = QIcon(str(application_icon_path())).pixmap(256, 256)
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly) or not pixmap.save(output, "ICO") or not output.commit():
        raise OSError(translate_text("Could not save the shortcut icon at {path}.").format(path=path))
    return path


def _create_windows_shortcut(command: list[str], directory: Path, icon: Path, *, menu: bool) -> Path:
    plan = {
        "target": command[0],
        "arguments": subprocess.list2cmdline(command[1:]),
        "workingDirectory": str(directory),
        "icon": str(icon),
        "location": application_location_id()[:8],
        "folder": "Programs" if menu else "Desktop",
        "missingFolder": translate_text("This desktop does not provide a shortcut directory."),
    }
    script = base64.b64encode(_WINDOWS_SHORTCUT.encode("utf-16-le")).decode("ascii")
    process = launch_system_powershell(
        ["-EncodedCommand", script],
        environment={"BLURAYSUBTITLE_SHORTCUT": json.dumps(plan)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        output, errors = process.communicate(timeout=10)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.communicate()
        raise TimeoutError(translate_text("Creating the shortcut timed out.")) from error
    path = output.decode("utf-8-sig").strip()
    if process.returncode or not path:
        raise OSError(errors.decode("utf-8", errors="replace").strip() or plan["missingFolder"])
    return Path(path)


def _desktop_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _desktop_argument(value: str) -> str:
    # Exec quoting happens after the desktop entry's string escapes are decoded.
    escaped = "".join(f"\\{char}" if char in '\\"$`' else char for char in value)
    return f'"{escaped.replace("%", "%%")}"'


def _create_linux_shortcut(command: list[str], directory: Path, *, menu: bool) -> Path:
    location = QStandardPaths.StandardLocation.ApplicationsLocation if menu else QStandardPaths.StandardLocation.DesktopLocation
    folder = QStandardPaths.writableLocation(location)
    if not folder:
        raise OSError(translate_text("This desktop does not provide a shortcut directory."))
    path = Path(folder) / f"{desktop_entry_id()}.desktop"
    path.parent.mkdir(parents=True, exist_ok=True)
    arguments = " ".join(_desktop_argument(argument) for argument in command)
    data = (
        "[Desktop Entry]\nType=Application\nName=BluraySubtitle\n"
        f"Exec={_desktop_value(arguments)}\n"
        f"Path={_desktop_value(str(directory))}\n"
        f"Icon={_desktop_value(str(application_icon_path()))}\n"
        "Terminal=false\nCategories=AudioVideo;Video;\n"
    ).encode("utf-8")
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(data) != len(data) or not output.commit():
        raise OSError(output.errorString())
    if not menu:
        path.chmod(0o755)
        if gio := shutil.which("gio"):
            # GNOME may require launcher trust metadata in addition to execute permission.
            with suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    [gio, "set", "-t", "string", str(path), "metadata::trusted", "true"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=3, check=True,
                )
    return path
