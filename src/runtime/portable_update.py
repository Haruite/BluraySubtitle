"""Hand a Linux or FreeBSD archive installation to its detached updater."""

from __future__ import annotations

import errno
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
from src.core.version import FREEBSD_PACKAGE_ARCHIVE

if TYPE_CHECKING:
    from .program_update import UpdatePackage


_FREEBSD = sys.platform.startswith("freebsd")
LINUX_ARCHITECTURE = "arm64" if platform.machine().lower() in ("aarch64", "arm64") else "x64"
PACKAGE_ARCHIVE = FREEBSD_PACKAGE_ARCHIVE if _FREEBSD else f"BluraySubtitle_linux_{LINUX_ARCHITECTURE}.tar.xz"
SERVER_PACKAGE_URL = f"https://sbx.mysmy.top/tools/BluraySubtitle/{PACKAGE_ARCHIVE}"
DIRECT_UPDATE_REQUIREMENT = (
    "Direct updates require the packaged FreeBSD program." if _FREEBSD else "Direct updates require the packaged Linux program."
)
_INSTALLER = Path("tools/linux_update.py")
_PYTHON = Path("python/bin/python3" if _FREEBSD else "linux/python/libexec/python3")


def update_executable() -> Path | None:
    if _FREEBSD:
        bundled = getattr(sys, "_bluray_freebsd_runtime", None)
        if not bundled or os.environ.get("BLURAY_FREEBSD_SOURCE"):
            return None
        bundled_runtime = Path(bundled).resolve()
        executable = bundled_runtime.parent / "BluraySubtitle"
    else:
        if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
            return None
        bundled_runtime = Path(sys._MEIPASS).resolve()
        executable = Path(sys.executable).resolve()
    runtime = executable.parent / "_internal"
    if (
        runtime == bundled_runtime
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


def _link_or_copy(source: str, destination: str) -> str:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def start_update(package: UpdatePackage) -> None:
    executable = update_executable()
    if executable is None:
        raise RuntimeError(translate_text(DIRECT_UPDATE_REQUIREMENT))

    install = executable.parent
    runtime = install / "_internal"
    configuration = app_config_path().parent
    with ExitStack() as files, ExitStack() as spawn_failure:
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
                "invalid_package": translate_text(
                    "The FreeBSD update package is incomplete or has an unexpected layout." if _FREEBSD
                    else "The Linux update package is incomplete or has an unexpected layout."
                ),
                "invalid_digest": translate_text("The downloaded package failed SHA-256 verification."),
                "restart_failed": translate_text("The updated program could not start."),
                "backup": translate_text("Update files are in {path}.").format(path=workspace),
            }
            (workspace / "update.json").write_text(json.dumps(plan), encoding="utf-8")
            parent_fd = None
            if hasattr(os, "pidfd_open"):
                try:
                    parent_fd = os.pidfd_open(os.getpid())
                except OSError as error:
                    if error.errno not in (errno.ENOSYS, errno.EPERM, errno.EACCES):
                        raise
            if parent_fd is None:
                # Only the GUI keeps a writer. EOF also works on kernels predating pidfd_open.
                parent_fd, writer_fd = os.pipe()
                writer = spawn_failure.enter_context(os.fdopen(writer_fd, "wb", buffering=0))
                os.register_at_fork(after_in_child=writer.close)
            files.callback(os.close, parent_fd)
            environment = dict(os.environ)
            for name in ("PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH"):
                environment.pop(name, None)
            environment.pop("LD_LIBRARY_PATH", None)
            descriptors = (lock_fd, parent_fd)
            # The installer needs the old interpreter after swapping the runtime directories.
            if _FREEBSD:
                # FreeBSD installations do not require procfs or fdescfs.
                shutil.copytree(runtime / "python", workspace / "python", symlinks=True, copy_function=_link_or_copy,
                                ignore=shutil.ignore_patterns("site-packages"))
                shutil.copytree(runtime / "lib", workspace / "lib", symlinks=True, copy_function=_link_or_copy)
                environment["LD_LIBRARY_PATH"] = str(workspace / "lib")
                command = [workspace / _PYTHON, "-I", "-B", "-S"]
            else:
                runtime_fd = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY)
                files.callback(os.close, runtime_fd)
                descriptors += (runtime_fd,)
                live_runtime = Path(f"/proc/self/fd/{runtime_fd}")
                environment["PYTHONHOME"] = str(live_runtime / "linux/python")
                libc = live_runtime / "linux/glibc"
                command = [libc / "ld.so", "--library-path", f"{libc}:{live_runtime}", live_runtime / _PYTHON, "-B", "-S"]
            subprocess.Popen(
                [*command, script, str(parent_fd)],
                cwd=install, env=environment, pass_fds=descriptors,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            spawn_failure.pop_all()
        except BaseException:
            shutil.rmtree(workspace, ignore_errors=True)
            raise
