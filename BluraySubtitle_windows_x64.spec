# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for the Windows x64 release.

Build from the repository root with:

    pyinstaller --clean --noconfirm BluraySubtitle_windows_x64.spec

Archive the complete ``dist/BluraySubtitle_windows_x64`` directory for
distribution; the executable depends on its adjacent ``_internal`` directory.

The external tool locations are loaded from ``src/core/settings.py`` so the
spec and the application configuration cannot silently drift apart.
"""

from fnmatch import fnmatchcase
from pathlib import Path
import os
import runpy
import sys
import sysconfig

from PyInstaller import __version__ as PYINSTALLER_VERSION
from PyInstaller.utils.hooks import collect_data_files


PROJECT_ROOT = Path(SPECPATH).resolve()
SETTINGS_PATH = PROJECT_ROOT / "src" / "core" / "settings.py"
SETTINGS = runpy.run_path(str(SETTINGS_PATH))


def required_path(path, description):
    """Return an existing path or stop the build with a useful error."""
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Missing {description}: {resolved}")
    return resolved


def add_binary(items, path, description):
    """Add a required executable/DLL to the bundle support directory."""
    resolved = required_path(path, description)
    if not resolved.is_file():
        raise FileNotFoundError(f"Expected a file for {description}: {resolved}")
    items.append((str(resolved), "."))


entry_script = required_path(PROJECT_ROOT / "src" / "main.py", "application entry point")
getnative_vpy = required_path(PROJECT_ROOT / "src" / "vs_tools" / "getnative.vpy", "getnative.vpy")
default_config = required_path(
    PROJECT_ROOT / "config.default.json",
    "default application configuration",
)
third_party_notices_paths = {
    required_path(PROJECT_ROOT / "legal" / name, "third-party notices template"):
        Path(workpath) / "legal" / name
    for name in (
        "THIRD_PARTY_NOTICES.md",
        "THIRD_PARTY_NOTICES.zh-Hans.md",
    )
}
notices_updater_path = required_path(
    PROJECT_ROOT / "tools" / "update_third_party_notices.py",
    "third-party notices updater",
)
notices_updater = runpy.run_path(str(notices_updater_path))
notices_updater["generate_third_party_notices"](
    third_party_notices_paths,
    SETTINGS,
    PYINSTALLER_VERSION,
)

# The application expects this exact bundled layout:
#     sys._MEIPASS/vs_pkg/vspipe.exe
# Collect the portable Python, plugins, scripts, and VS Editor together.
# Runtime filtering below omits tests and development files before COLLECT.
vapoursynth_dir = required_path(
    Path(SETTINGS["VSEDIT_PATH"]).parent,
    "VapourSynth portable directory",
)
if not vapoursynth_dir.is_dir():
    raise NotADirectoryError(f"VapourSynth path is not a directory: {vapoursynth_dir}")

vspipe_path = required_path(SETTINGS["VSPIPE_PATH"], "VSPipe executable")
if vspipe_path.parent != vapoursynth_dir:
    raise ValueError(
        "VSEDIT_PATH and VSPIPE_PATH must refer to files in the same "
        f"VapourSynth directory: {vapoursynth_dir}"
    )


portable_python_libraries = [
    path for path in vapoursynth_dir.glob("python3*.dll")
    if path.name.lower() != "python3.dll"
]
if len(portable_python_libraries) != 1:
    raise ValueError("VapourSynth must contain exactly one versioned Python DLL")
portable_python_library = portable_python_libraries[0].name.lower()
portable_python_abi = "cp" + portable_python_libraries[0].stem.removeprefix("python")
main_python_library = str(sysconfig.get_config_var("LDLIBRARY")).lower()


def keep_runtime_file(destination, root_binary_names):
    """Keep files required by the GUI and the separate portable VPy runtime."""
    path = Path(destination)
    relative = path.as_posix().lower()
    name = path.name.lower()
    parts = tuple(part.lower() for part in path.parts)

    if relative.startswith("pyqt6/qt6/translations/"):
        return name in {"qt_en.qm", "qtbase_en.qm", "qt_zh_cn.qm", "qtbase_zh_cn.qm"}

    if any(fnmatchcase(relative, pattern) for pattern in (
        "pycountry/locales/*",
        "pyqt6/qt6/bin/opengl32sw.dll",
        "pyqt6/qt6/bin/qt6pdf.dll",
        "pyqt6/qt6/plugins/generic/*",
        "pyqt6/qt6/plugins/imageformats/qpdf.dll",
        "pyqt6/qt6/plugins/imageformats/qicns.dll",
        "pyqt6/qt6/plugins/imageformats/qtga.dll",
        "pyqt6/qt6/plugins/imageformats/qtiff.dll",
        "pyqt6/qt6/plugins/imageformats/qwbmp.dll",
        "pyqt6/qt6/plugins/platforms/qminimal.dll",
        "pyqt6/qt6/plugins/platforms/qoffscreen.dll",
        "pil/_avif.*",
        "pil/_imagingtk.*",
        "vs_pkg/doc/*",
        "vs_pkg/sdk/*",
        "vs_pkg/manifest.in",
        "vs_pkg/setup.py",
    )):
        return False

    # Qt can share the root C++ runtime; its additional MSVCP140_1/2 DLLs stay.
    if parts[:3] == ("pyqt6", "qt6", "bin"):
        if name in {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"}:
            return name not in root_binary_names

    # These dependencies belong beside the portable runtime, not the main EXE.
    if len(parts) == 1 and name != main_python_library:
        if name in {
            portable_python_library, "vapoursynth.dll", "vsscript.dll",
            "sqlite3.dll", "mimalloc-redirect.dll",
        }:
            return False

    if len(parts) == 2 and parts[0] == "vs_pkg" and name.startswith("vapoursynth.cp"):
        return name.startswith(f"vapoursynth.{portable_python_abi}-")

    if parts[0] == "numpy" or parts[:4] == ("vs_pkg", "lib", "site-packages", "numpy"):
        if any(part in {"test", "tests", "_pyinstaller", "doc"} for part in parts):
            return False
        if path.suffix.lower() in {".pyi", ".h", ".hpp", ".c", ".cpp", ".pxd", ".pyx", ".rst", ".lib"}:
            return False
        if "_tests." in name:
            return False

    return True


binaries = []

# Executables and DLLs configured in settings.py are placed in the support
# directory addressed by sys._MEIPASS at runtime.
for setting_name, description in (
    ("SEVEN_ZIP_PATH", "7-Zip"),
    ("FLAC_PATH", "FLAC encoder"),
    ("FFMPEG_PATH", "FFmpeg"),
    ("FFPROBE_PATH", "FFprobe"),
    ("X265_PATH", "x265 encoder"),
    ("X264_PATH", "x264 encoder"),
    ("SVT_AV1_PATH", "SVT-AV1 encoder"),
    ("FDK_AAC_PATH", "FDK-AAC encoder"),
    ("DOVI_TOOL_PATH", "dovi_tool"),
    ("HDR10PLUS_TOOL_PATH", "hdr10plus_tool"),
    ("LIBASS_PATH", "libass DLL"),
    ("TS_MUXER_PATH", "tsMuxeR"),
    ("MKV_INFO_PATH", "mkvinfo"),
    ("MKV_MERGE_PATH", "mkvmerge"),
    ("MKV_PROP_EDIT_PATH", "mkvpropedit"),
    ("MKV_EXTRACT_PATH", "mkvextract"),
):
    add_binary(binaries, SETTINGS[setting_name], description)

# 7z.exe loads archive handlers from its adjacent DLL.
add_binary(binaries, Path(SETTINGS["SEVEN_ZIP_PATH"]).parent / "7z.dll", "7-Zip archive library")

# flac.exe requires its adjacent runtime DLL.
flac_dir = Path(SETTINGS["FLAC_PATH"]).parent
add_binary(binaries, flac_dir / "libFLAC.dll", "FLAC runtime library")


datas = [
    (str(required_path(Path(SETTINGS["SEVEN_ZIP_PATH"]).parent / "License.txt", "7-Zip license")), "legal/7zip"),
    (str(default_config), "."),
    (str(SETTINGS_PATH), "src/core"),
    (str(getnative_vpy), "src/vs_tools"),
    *((str(path), "legal") for path in third_party_notices_paths.values()),
]

# Avoid analyzing obsolete Python ABI modules and NumPy development binaries.
datas += [
    (str(path), str(Path("vs_pkg") / path.relative_to(vapoursynth_dir).parent))
    for path in vapoursynth_dir.rglob("*")
    if path.is_file() and keep_runtime_file(Path("vs_pkg") / path.relative_to(vapoursynth_dir), set())
]

# pycountry needs its ISO databases and notices; the application translates UI text.
datas += collect_data_files("pycountry", excludes=["locales"])

# Resolve DLLs from configured tools and Python, without unrelated PATH additions.
os.environ["PATH"] = os.pathsep.join(dict.fromkeys([
    str(Path(sys.executable).parent),
    str(Path(sys.base_prefix) / "DLLs"),
    str(Path(os.environ["SystemRoot"]) / "System32"),
    os.environ["SystemRoot"],
    *(str(Path(source).parent) for source, _destination in binaries),
    str(vapoursynth_dir),
]))


a = Analysis(
    [str(entry_script)],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PIL.AvifImagePlugin",
        "PIL._avif",
        "PIL.ImageTk",
        "PIL._imagingtk",
        "numpy._core._multiarray_tests",
    ],
    noarchive=False,
    optimize=0,
)

# Hooks can add resources and duplicate DLLs independently of explicit datas.
# Filter both TOCs after dependency analysis so excluded files never enter dist.
root_binary_names = {
    Path(destination).name.lower()
    for destination, _source, _kind in a.binaries
    if len(Path(destination).parts) == 1
}
a.binaries = [entry for entry in a.binaries if keep_runtime_file(entry[0], root_binary_names)]
a.datas = [entry for entry in a.datas if keep_runtime_file(entry[0], root_binary_names)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BluraySubtitle_windows_x64",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BluraySubtitle_windows_x64",
)
