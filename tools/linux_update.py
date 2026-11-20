"""Install a verified Linux archive after the running program exits."""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


PACKAGE_DIRECTORY = "BluraySubtitle"
PROGRAM = "BluraySubtitle"
RUNTIME = "_internal"


def download_package(plan: dict, archive: Path) -> None:
    url = urlsplit(plan["url"])
    if url.scheme != "https" or url.hostname not in {"github.com", "sbx.mysmy.top"}:
        raise ValueError(plan["invalid_package"])
    request = Request(plan["url"], headers={"Cache-Control": "no-cache", "User-Agent": "BluraySubtitle-Updater"})
    with urlopen(request, timeout=30) as response, archive.open("wb") as stream:
        shutil.copyfileobj(response, stream, length=1024 * 1024)


def extract_package(plan: dict, archive: Path, destination: Path) -> Path:
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != plan["sha256"]:
        raise ValueError(plan["invalid_digest"])

    def package_files(member: tarfile.TarInfo, root: str) -> tarfile.TarInfo:
        name = PurePosixPath(member.name)
        if (
            name.is_absolute() or ".." in name.parts
            or name.parts[:1] != (PACKAGE_DIRECTORY,)
            or (len(name.parts) > 1 and name.parts[1] not in {PROGRAM, RUNTIME})
        ):
            raise ValueError(plan["invalid_package"])
        return tarfile.data_filter(member, root)

    with tarfile.open(archive, "r:xz") as package:
        package.extractall(destination, filter=package_files)
    root = destination / PACKAGE_DIRECTORY
    executable = root / PROGRAM
    runtime = root / RUNTIME
    if (
        root.is_symlink() or runtime.is_symlink() or executable.is_symlink()
        or not executable.is_file() or not os.access(executable, os.X_OK)
        or not (runtime / "build-commit.txt").is_file()
        or not (runtime / "config.default.json").is_file()
        or not (runtime / "tools/linux_update.py").is_file()
    ):
        raise ValueError(plan["invalid_package"])
    return root


def preserve_configuration(plan: dict, runtime: Path, next_runtime: Path) -> None:
    mpv_config = runtime / "mpv"
    if mpv_config.is_dir():
        shutil.copytree(mpv_config, next_runtime / "mpv", symlinks=True, dirs_exist_ok=True)

    relative = plan["internal_configuration"]
    if relative is None:
        return
    old_config = (runtime / relative).resolve()
    new_config = (next_runtime / relative).resolve()
    if not old_config.is_relative_to(runtime) or not new_config.is_relative_to(next_runtime):
        raise ValueError(plan["invalid_package"])
    for name in ("config.json", "logs", "vpy", "src/core/settings.py"):
        old = old_config / name
        if not old.exists():
            continue
        new = new_config / name
        if not new.resolve().is_relative_to(next_runtime):
            raise ValueError(plan["invalid_package"])
        new.parent.mkdir(parents=True, exist_ok=True)
        if old.is_dir():
            shutil.copytree(old, new, symlinks=True)
        else:
            shutil.copy2(old, new)


def restart(executable: Path, plan: dict, *, ready: Path | None = None, failure: str = "") -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONHOME", None)
    original_library_path = environment.pop("LD_LIBRARY_PATH_ORIG", None)
    environment.pop("LD_LIBRARY_PATH", None)
    if original_library_path is not None:
        environment["LD_LIBRARY_PATH"] = original_library_path
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if ready is not None:
        environment["BLURAY_SUBTITLE_UPDATE_READY"] = str(ready)
    if failure:
        environment["BLURAY_SUBTITLE_UPDATE_ERROR"] = failure

    directory = Path(plan["working_directory"])
    process = subprocess.Popen(
        [executable, "--detached-gui"],
        cwd=directory if directory.is_dir() else executable.parent,
        env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    if ready is None:
        return
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise OSError(plan["restart_failed"])
        if ready.is_file():
            return
        time.sleep(0.1)
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    raise OSError(plan["restart_failed"])


def install_update(workspace: Path, plan: dict) -> int:
    installation = workspace.parent
    executable = installation / plan["executable"]
    runtime = installation / RUNTIME
    backup = workspace / "previous"
    moves: list[tuple[Path, Path]] = []
    keep_workspace = False

    def move(source: Path, target: Path) -> None:
        source.rename(target)
        moves.append((target, source))

    try:
        if not re.fullmatch(r"[0-9a-f]{64}", plan["sha256"]):
            raise ValueError(plan["invalid_digest"])
        archive = workspace / "package.tar.xz"
        download_package(plan, archive)
        incoming = extract_package(plan, archive, workspace / "unpacked")
        preserve_configuration(plan, runtime, incoming / RUNTIME)
        backup.mkdir()
        move(executable, backup / executable.name)
        move(runtime, backup / RUNTIME)
        move(incoming / RUNTIME, runtime)
        move(incoming / PROGRAM, executable)
        restart(executable, plan, ready=workspace / "ready")
    except Exception as error:
        failure = f'{plan["failure"]}\n{error}'
        try:
            for source, target in reversed(moves):
                source.rename(target)
            restart(executable, plan, failure=failure)
        except OSError as recovery_error:
            keep_workspace = True
            (workspace / "error.txt").write_text(
                f'{failure}\n{recovery_error}\n{plan["backup"]}\n', encoding="utf-8",
            )
        return 1
    finally:
        if not keep_workspace:
            shutil.rmtree(workspace)
    return 0


if __name__ == "__main__":
    workspace = Path(__file__).resolve().parent
    plan = json.loads((workspace / "update.json").read_text(encoding="utf-8"))
    parent = select.poll()
    parent_fd = int(sys.argv[1])
    parent.register(parent_fd, select.POLLIN | select.POLLHUP)
    try:
        parent.poll()
    finally:
        os.close(parent_fd)
    raise SystemExit(install_update(workspace, plan))
