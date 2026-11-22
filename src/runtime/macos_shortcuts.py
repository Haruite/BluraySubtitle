"""Finder desktop links and per-user Applications entries."""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.core.app_config import application_directory, application_location_id, macos_application_bundle
from src.core.i18n import translate_text
from src.core.tool_paths import bundle_directory


def _file_operation(*args: str | Path) -> None:
    result = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", Path(__file__).with_name("macos_files.js"), *args],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise OSError(result.stderr.strip())


def refresh_source_launchers(runtime: Path) -> None:
    """Retarget generated shortcuts for this checkout after its entry point moves."""
    project = application_directory()
    identity = application_location_id()
    old_entry = project / "tools" / "macos" / "entry.py"
    new_entry = project / "tools/macos_entry.py"
    python = str(runtime / "python/bin/python3")
    old_command = "exec " + shlex.join([python, "-I", "-B", str(old_entry), "--detached-gui"]) + ' "$@"\n'
    new_command = "exec " + shlex.join([python, "-I", "-B", str(new_entry), "--detached-gui"]) + ' "$@"\n'
    launchers = runtime.parent / "Launchers" / identity
    for directory in (Path.home() / "Applications", launchers):
        app = directory / "BluraySubtitle (Source).app"
        launcher = app / "Contents/MacOS/BluraySubtitle"
        if app.is_symlink() or launcher.is_symlink() or not launcher.is_file():
            continue
        script = launcher.read_bytes()
        if not script.endswith(old_command.encode()):
            continue
        with (app / "Contents/Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        if info.get("CFBundleIdentifier") != "io.github.haruite.BluraySubtitle.source." + identity:
            continue
        with tempfile.TemporaryDirectory(dir=launcher.parent) as temp:
            replacement = Path(temp) / launcher.name
            replacement.write_bytes(script.removesuffix(old_command.encode()) + new_command.encode())
            shutil.copymode(launcher, replacement)
            replacement.replace(launcher)


def _source_app(command: list[str], directory: Path) -> Path:
    identity = application_location_id()
    target = directory / "BluraySubtitle (Source).app"
    identifier = "io.github.haruite.BluraySubtitle.source." + identity
    runtime = bundle_directory()
    if runtime is not None:
        command = [str(runtime / "python/bin/python3"), "-I", "-B", str(application_directory() / "tools/macos_entry.py")]
    directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.get("BLURAY_SUBTITLE_CONFIG_DIR")
    script = "#!/bin/sh\n"
    if environment:
        script += "export BLURAY_SUBTITLE_CONFIG_DIR=" + shlex.quote(environment) + "\n"
    script += "exec " + shlex.join([*command, "--detached-gui"]) + ' "$@"\n'
    if target.exists() or target.is_symlink():
        launcher = target / "Contents/MacOS/BluraySubtitle"
        if launcher.is_file() and launcher.read_text() == script:
            return target
        raise FileExistsError(target)
    with tempfile.TemporaryDirectory(dir=directory) as temp:
        app = Path(temp) / target.name
        contents = app / "Contents"
        launcher = contents / "MacOS/BluraySubtitle"
        launcher.parent.mkdir(parents=True)
        launcher.write_text(script, encoding="utf-8")
        launcher.chmod(0o755)
        info = {"CFBundleIdentifier": identifier, "CFBundleName": "BluraySubtitle (Source)",
                "CFBundlePackageType": "APPL", "CFBundleExecutable": launcher.name,
                "CFBundleVersion": "1", "LSMinimumSystemVersion": "11.0"}
        icon = runtime / "share/BluraySubtitle.icns" if runtime else None
        if icon and icon.is_file():
            (contents / "Resources").mkdir()
            shutil.copy2(icon, contents / "Resources" / icon.name)
            info["CFBundleIconFile"] = icon.name
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        _file_operation("place", app, target)
    return target


def create_macos_shortcut(command: list[str], *, menu: bool) -> Path:
    applications = Path.home() / "Applications"
    app = macos_application_bundle()
    if app is None:
        launchers = Path.home() / "Library/Application Support/BluraySubtitle/Launchers" / application_location_id()
        app = _source_app(command, applications if menu else launchers)
    if menu:
        if not any(app.is_relative_to(folder) for folder in (Path("/Applications"), applications)):
            applications.mkdir(parents=True, exist_ok=True)
            target = applications / app.name
            if target.exists() or target.is_symlink():
                seal = Path("Contents/_CodeSignature/CodeResources")
                if target.is_symlink() or not (target / seal).is_file() or (target / seal).read_bytes() != (app / seal).read_bytes():
                    raise FileExistsError(target)
                subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", target], check=True)
            else:
                with tempfile.TemporaryDirectory(dir=applications) as temp:
                    incoming = Path(temp) / app.name
                    subprocess.run(["/usr/bin/ditto", app, incoming], check=True)
                    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", incoming], check=True)
                    _file_operation("place", incoming, target)
            app = target
        _file_operation("register", app)
        return app
    from PyQt6.QtCore import QStandardPaths

    directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    if not directory:
        raise OSError(translate_text("This desktop does not provide a shortcut directory."))
    link = Path(directory) / app.name
    # A path-based Finder link continues to open the replacement after an atomic update.
    try:
        link.symlink_to(app, target_is_directory=True)
    except FileExistsError:
        if not link.is_symlink() or link.resolve() != app.resolve():
            raise
    return link
