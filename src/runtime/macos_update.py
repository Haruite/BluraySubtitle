"""Hand a native Finder application to its detached macOS installer."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from src.core.app_config import macos_application_bundle
from src.core.i18n import translate_text

if TYPE_CHECKING:
    from .program_update import UpdatePackage


MACOS_ARCHITECTURE = "arm64" if platform.machine() == "arm64" else "x64"
PACKAGE_ARCHIVE = f"BluraySubtitle_macos_{MACOS_ARCHITECTURE}.zip"
SERVER_PACKAGE_URL = f"https://sbx.mysmy.top/tools/BluraySubtitle/{PACKAGE_ARCHIVE}"


def update_executable() -> Path | None:
    app = macos_application_bundle()
    if app is None:
        return None
    executable = app / "Contents/MacOS/BluraySubtitle"
    return executable if os.access(executable, os.X_OK) else None


def _lock_file(app: Path) -> Path:
    directory = Path.home() / "Library/Caches/BluraySubtitle/updates"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha256(os.fsencode(app.resolve())).hexdigest()
    return directory / (key + ".lock")


def update_in_progress() -> bool:
    app = macos_application_bundle()
    if app is None:
        return False
    with _lock_file(app).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def start_update(package: UpdatePackage) -> None:
    app = macos_application_bundle()
    if app is None or update_executable() is None:
        raise RuntimeError(translate_text("Direct updates require the packaged macOS application."))
    runtime = app / "Contents/Resources/Runtime"
    scripts = runtime / "app/tools"
    with _lock_file(app).open("a") as lock, ExitStack() as on_failure:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(translate_text("An update is already running for this installation.")) from error
        try:
            work = Path(tempfile.mkdtemp(prefix=".bluraysubtitle-update-", dir=app.parent))
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
                raise
            raise RuntimeError(translate_text("Move the application to your user's Applications folder to update it.")) from error
        on_failure.callback(shutil.rmtree, work)
        for source in (scripts / "macos_update.py", scripts / "macos_finish_update.sh", Path(__file__).with_name("macos_files.js")):
            shutil.copyfile(source, work / source.name)
        plan = {
            "app": str(app), "url": package.url, "sha256": package.sha256, "arch": platform.machine(),
            "server_origin": urlsplit(SERVER_PACKAGE_URL).netloc,
            "failure": translate_text("Could not update the program."),
            "invalid_package": translate_text("The macOS update package is incomplete or incompatible."),
            "invalid_digest": translate_text("The downloaded package failed SHA-256 verification."),
            "restart_failed": translate_text("The updated program could not start."),
        }
        (work / "update.json").write_text(json.dumps(plan), encoding="utf-8")
        read_fd, write_fd = os.pipe()
        writer = on_failure.enter_context(os.fdopen(write_fd, "wb", buffering=0))
        # GUI exit closes the only writer, even if a fork-based worker outlives it.
        os.register_at_fork(after_in_child=writer.close)
        with os.fdopen(read_fd, "rb", buffering=0) as parent, (work / "installer.log").open("w") as log:
            subprocess.Popen([runtime / "python/bin/python3", "-I", "-B", work / "macos_update.py", str(lock.fileno())],
                             cwd=work, stdin=parent, stdout=log, stderr=subprocess.STDOUT,
                             pass_fds=(lock.fileno(),), start_new_session=True)
        on_failure.pop_all()
