"""Inspect native Linux dependencies and select the Qt components used by the application."""

import os
from pathlib import Path
import re
import subprocess

QT_MODULES = ("QtCore", "QtDBus", "QtGui", "QtNetwork", "QtSvg", "QtWidgets")
QT_PLUGINS = {
    "platforms": ("libqxcb.so", "libqwayland.so", "libqwayland-egl.so", "libqwayland-generic.so", "libqoffscreen.so"),
    "xcbglintegrations": ("*.so",),
    "wayland-shell-integration": ("libxdg-shell.so",),
    "wayland-graphics-integration-client": ("*wayland-egl*.so",),
    "wayland-decoration-client": ("libadwaita.so", "libbradient.so"),
    "platforminputcontexts": ("libcomposeplatforminputcontextplugin.so", "libibusplatforminputcontextplugin.so", "libfcitx5platforminputcontextplugin.so"),
    "imageformats": ("libqgif.so", "libqico.so", "libqjpeg.so", "libqsvg.so", "libqtiff.so", "libqwebp.so"),
    "iconengines": ("libqsvgicon.so",),
    "tls": ("libqopensslbackend.so", "libqcertonlybackend.so"),
    "networkinformation": ("libqglib.so", "libqnetworkmanager.so"),
}
GLIBC = re.compile(r"(?:ld-linux-[\w-]+|lib(?:c|m|mvec|pthread|rt|dl|resolv|util|anl|nss_(?:dns|files|compat|hesiod)))\.so(?:\.\d+)+")
# Client libraries, including GLVND and libva, form part of the application's ABI.
# The loaders discover GPU-specific drivers on the running system.
HOST_DRIVER = re.compile(r"lib(?:GLX_|EGL_|nvidia-|vulkan_|vdpau_)[\w.-]+\.so(?:\.\d+)*")


def selected_plugins(root: Path) -> list[Path]:
    return sorted({file for directory, patterns in QT_PLUGINS.items()
                   for pattern in patterns for file in (root / directory).glob(pattern)})


def linked_libraries(file: Path, search: tuple[Path, ...] = (), *, resolving: bool = False) -> dict[str, Path | None]:
    environment = dict(os.environ, LC_ALL="C")
    environment.pop("LD_LIBRARY_PATH", None)
    if search:
        environment["LD_LIBRARY_PATH"] = os.pathsep.join(map(str, search))
    result = subprocess.run(["ldd", file], env=environment, text=True, capture_output=True)
    output = result.stdout + result.stderr
    if result.returncode and not any(x in output for x in ("not a dynamic executable", "statically linked")):
        raise RuntimeError(f"ldd failed for {file}: {output.strip()}")
    libraries = {}
    for line in output.splitlines():
        if " => " in line:
            name, target = line.strip().split(" => ", 1)
            libraries[name] = None if target == "not found" else Path(target.rsplit(" (0x", 1)[0])
        elif "not found" in line and not resolving:
            raise RuntimeError(f"Incompatible library for {file}: {line.strip()}")
    return libraries


def kernel_requirement(library: Path, *, note_required: bool = True) -> tuple[int, int, int]:
    notes = subprocess.check_output(["readelf", "-nW", library], env=dict(os.environ, LC_ALL="C"), text=True)
    match = re.search(r"OS: Linux, ABI: (\d+)\.(\d+)\.(\d+)", notes)
    if match:
        return tuple(map(int, match.groups()))
    if note_required:
        raise ValueError(f"Missing Linux ABI note in {library}")
    return (0, 0, 0)
