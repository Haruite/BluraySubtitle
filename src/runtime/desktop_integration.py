"""Create per-user launch shortcuts for the current installation."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

from PyQt6.QtCore import QIODevice, QSaveFile, QStandardPaths
from PyQt6.QtGui import QGuiApplication, QIcon

from src.core.app_config import application_directory, application_location_id, application_support_directory
from src.core.i18n import translate_text
from src.runtime.windows_shell import launch_system_powershell


_WINDOWS_SHORTCUT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    $shell = New-Object -ComObject WScript.Shell
    $folder = $shell.SpecialFolders.Item($env:BLURAYSUBTITLE_SHORTCUT_FOLDER)
    if ([string]::IsNullOrEmpty($folder)) { throw $env:BLURAYSUBTITLE_SHORTCUT_MISSING_FOLDER }
    [void][IO.Directory]::CreateDirectory($folder)
    $path = Join-Path $folder 'BluraySubtitle.lnk'
    $link = $shell.CreateShortcut($path)
    $target = $env:BLURAYSUBTITLE_SHORTCUT_TARGET
    $arguments = [string]$env:BLURAYSUBTITLE_SHORTCUT_ARGUMENTS
    if ((Test-Path -LiteralPath $path) -and ($link.TargetPath -ne $target -or $link.Arguments -ne $arguments)) {
        $path = Join-Path $folder "BluraySubtitle ($env:BLURAYSUBTITLE_SHORTCUT_LOCATION).lnk"
        $link = $shell.CreateShortcut($path)
    }
    $link.TargetPath = $target
    $link.Arguments = $arguments
    $link.WorkingDirectory = $env:BLURAYSUBTITLE_SHORTCUT_DIRECTORY
    $link.IconLocation = "$env:BLURAYSUBTITLE_SHORTCUT_ICON,0"
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


def _launch_command() -> list[str]:
    executable = str(Path(sys.executable).absolute())
    if getattr(sys, "frozen", False):
        return [executable]
    return [executable, str(application_directory() / "src/main.py")]


def supports_desktop_entries() -> bool:
    if sys.platform.startswith("linux"):
        return True
    app = QGuiApplication.instance()
    platform = app.platformName() if isinstance(app, QGuiApplication) else ""
    return os.name == "posix" and (platform == "xcb" or platform.startswith("wayland"))


def create_launch_shortcut(*, menu: bool) -> Path:
    directory = application_directory()
    command = _launch_command()
    if sys.platform == "win32":
        executable = Path(command[0])
        frozen = bool(getattr(sys, "frozen", False))
        icon = executable if frozen else _windows_source_icon()
        if not frozen and executable.with_name("pythonw.exe").is_file():
            command[0] = str(executable.with_name("pythonw.exe"))
        return _create_windows_shortcut(command, directory, icon, menu=menu)
    if supports_desktop_entries():
        return _create_desktop_entry_shortcut(command, directory, menu=menu)
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
    missing_folder = translate_text("This desktop does not provide a shortcut directory.")
    script = base64.b64encode(_WINDOWS_SHORTCUT.encode("utf-16-le")).decode("ascii")
    process = launch_system_powershell(
        ["-EncodedCommand", script],
        # PowerShell 2 has no JSON cmdlets. Pass Unicode fields directly to the shortcut process.
        environment={
            "BLURAYSUBTITLE_SHORTCUT_TARGET": command[0],
            "BLURAYSUBTITLE_SHORTCUT_ARGUMENTS": subprocess.list2cmdline(command[1:]),
            "BLURAYSUBTITLE_SHORTCUT_DIRECTORY": str(directory),
            "BLURAYSUBTITLE_SHORTCUT_ICON": str(icon),
            "BLURAYSUBTITLE_SHORTCUT_LOCATION": application_location_id()[:8],
            "BLURAYSUBTITLE_SHORTCUT_FOLDER": "Programs" if menu else "Desktop",
            "BLURAYSUBTITLE_SHORTCUT_MISSING_FOLDER": missing_folder,
        },
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
        raise OSError(errors.decode("utf-8", errors="replace").strip() or missing_folder)
    return Path(path)


def _desktop_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _desktop_argument(value: str) -> str:
    # Exec quoting happens after the desktop entry's string escapes are decoded.
    escaped = "".join(f"\\{char}" if char in '\\"$`' else char for char in value)
    return f'"{escaped.replace("%", "%%")}"'


def _create_desktop_entry_shortcut(command: list[str], directory: Path, *, menu: bool) -> Path:
    location = QStandardPaths.StandardLocation.ApplicationsLocation if menu else QStandardPaths.StandardLocation.DesktopLocation
    folder = QStandardPaths.writableLocation(location)
    if not folder:
        raise OSError(translate_text("This desktop does not provide a shortcut directory."))
    path = Path(folder) / f"{desktop_entry_id()}.desktop"
    _write_desktop_entry(path, command, directory, "BluraySubtitle", application_icon_path(), desktop_entry_id())
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


def log_taskbar_entry(title: str, icon: Path, window_class: str) -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
    if not location:
        raise OSError(translate_text("This desktop does not provide a shortcut directory."))
    path = Path(location) / "bluraysubtitle" / f"{window_class}.desktop"
    _write_desktop_entry(path, _launch_command(), application_directory(), title, icon, window_class, hidden=True)
    return path


def _write_desktop_entry(
    path: Path, command: list[str], directory: Path, title: str, icon: Path, window_class: str, *, hidden: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # GLib checks the executable before expanding percent escapes in Exec.
    env_command = shutil.which("env") if "%" in command[0] else None
    entry_command = [env_command, *command] if env_command else command
    arguments = " ".join(_desktop_argument(argument) for argument in entry_command)
    data = (
        f"[Desktop Entry]\nType=Application\nName={_desktop_value(title)}\n"
        f"Exec={_desktop_value(arguments)}\n"
        f"Path={_desktop_value(str(directory))}\n"
        f"Icon={_desktop_value(str(icon))}\nStartupWMClass={window_class}\n"
        "Terminal=false\nCategories=AudioVideo;Video;\n"
        + ("NoDisplay=true\n" if hidden else "")
    ).encode("utf-8")
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly) or output.write(data) != len(data) or not output.commit():
        raise OSError(output.errorString())
