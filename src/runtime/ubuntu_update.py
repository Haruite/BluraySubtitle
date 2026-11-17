"""Hand the running Ubuntu package to its detached installer."""

from __future__ import annotations

import fcntl
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.app_config import app_config_path
from src.core.i18n import translate_text

if TYPE_CHECKING:
    from .program_update import UpdatePackage


UBUNTU_ARCHITECTURE = "arm64" if platform.machine().lower() in ("aarch64", "arm64") else "x64"
PACKAGE_ARCHIVE = f"BluraySubtitle_ubuntu26.04_{UBUNTU_ARCHITECTURE}.tar.xz"
SERVER_PACKAGE_URL = f"https://sbx.mysmy.top/tools/BluraySubtitle/{PACKAGE_ARCHIVE}"
_INSTALLER = Path("tools/ubuntu_update.py")
_PYTHON = Path("linux/python/bin/python3.14")


def update_executable() -> Path | None:
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return None
    executable = Path(sys.executable).resolve()
    runtime = executable.parent / "_internal"
    if (
        runtime == Path(sys._MEIPASS).resolve()
        and not runtime.is_symlink()
        and executable.is_file()
        and (runtime / _INSTALLER).is_file()
        and os.access(runtime / _PYTHON, os.X_OK)
    ):
        return executable
    return None


def update_in_progress() -> bool:
    executable = update_executable()
    if executable is None:
        return False
    directory_fd = os.open(executable.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(directory_fd)


def start_update(package: UpdatePackage) -> None:
    executable = update_executable()
    if executable is None:
        raise RuntimeError(translate_text("Direct updates require the packaged Ubuntu 26.04 program."))

    install = executable.parent
    runtime = install / "_internal"
    configuration = app_config_path().parent
    with ExitStack() as files:
        lock_fd = os.open(install, os.O_RDONLY | os.O_DIRECTORY)
        files.callback(os.close, lock_fd)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(translate_text("An update is already running for this installation.")) from error

        workspace = Path(tempfile.mkdtemp(prefix=".bluraysubtitle-update-", dir=install))
        try:
            script = workspace / _INSTALLER.name
            shutil.copyfile(runtime / _INSTALLER, script)
            plan = {
                "executable": executable.name,
                "working_directory": os.getcwd(),
                "internal_configuration": str(configuration.relative_to(runtime))
                if configuration.is_relative_to(runtime) else None,
                "url": package.url,
                "sha256": package.sha256,
                "failure": translate_text("Could not update the program."),
                "invalid_package": translate_text("The Ubuntu update package is incomplete or has an unexpected layout."),
                "invalid_digest": translate_text("The downloaded package failed SHA-256 verification."),
                "restart_failed": translate_text("The updated program could not start."),
                "backup": translate_text("Update files are in {path}.").format(path=workspace),
            }
            (workspace / "update.json").write_text(json.dumps(plan), encoding="utf-8")
            parent_fd = os.pidfd_open(os.getpid())
            files.callback(os.close, parent_fd)
            # Keep the old bundled interpreter reachable while its directory is moved.
            runtime_fd = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY)
            files.callback(os.close, runtime_fd)
            live_runtime = Path(f"/proc/self/fd/{runtime_fd}")
            environment = dict(os.environ)
            for name in ("PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH"):
                environment.pop(name, None)
            environment.update(
                PYTHONHOME=str(live_runtime / "linux/python"),
                LD_LIBRARY_PATH=str(live_runtime),
            )
            subprocess.Popen(
                [live_runtime / _PYTHON, "-B", "-S", script, str(parent_fd)],
                cwd=install, env=environment, pass_fds=(lock_fd, parent_fd, runtime_fd),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except BaseException:
            shutil.rmtree(workspace, ignore_errors=True)
            raise
