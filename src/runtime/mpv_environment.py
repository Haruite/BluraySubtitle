"""Select the Linux Desktop mpv executable and its VapourSynth runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


MPV_COMMAND = Path("/usr/local/bin/mpv")
MPV_NATIVE = MPV_COMMAND.with_name("mpv-bluraysubtitle-native")
MPV_RUNTIME = Path("/usr/local/libexec/bluraysubtitle/mpv_runtime.py")
MPV_LAUNCHER = f'#!/bin/sh\nexec /usr/bin/python3 -I {MPV_RUNTIME} "$@"\n'.encode("ascii")


def desktop_runtime_file() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not config_home.is_absolute():
        config_home = Path.home() / ".config"
    return config_home / "bluraysubtitle/mpv-runtime.json"


def read_desktop_runtime() -> dict[str, str]:
    try:
        with desktop_runtime_file().open(encoding="utf-8") as stream:
            # A privileged mpv must not load a runtime chosen by another user.
            if os.geteuid() == 0 and os.fstat(stream.fileno()).st_uid != 0:
                return {}
            return json.load(stream)
    except FileNotFoundError:
        return {}


def is_desktop_launcher(executable: Path) -> bool:
    if not executable.is_file():
        return False
    with executable.open("rb") as stream:
        return stream.read(len(MPV_LAUNCHER) + 1) == MPV_LAUNCHER


def native_mpv_executable(executable: Path) -> Path:
    if not is_desktop_launcher(executable):
        return executable
    if MPV_NATIVE.is_file() and os.access(MPV_NATIVE, os.X_OK):
        return MPV_NATIVE
    # An installation may already use a distro or third-party player elsewhere on PATH.
    for directory in os.get_exec_path():
        candidate = Path(directory) / "mpv"
        if candidate.is_file() and os.access(candidate, os.X_OK) and not is_desktop_launcher(candidate):
            return candidate
    return Path("/usr/bin/mpv")


if __name__ == "__main__":
    runtime = read_desktop_runtime()
    if runtime:
        os.environ["VSSCRIPT_PATH"] = runtime["VSSCRIPT_PATH"]
        plugins = os.environ.setdefault("BLURAYSUB_PLUGIN_PATH", runtime["PLUGIN_PATH"])
        os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = plugins
    player = native_mpv_executable(Path(runtime.get("MPV_PATH") or MPV_COMMAND))
    os.execv(player, [str(player), *sys.argv[1:]])
