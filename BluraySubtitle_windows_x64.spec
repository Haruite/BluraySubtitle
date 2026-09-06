# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for the Windows x64 release.

Build from the repository root with:

    pyinstaller --clean --noconfirm BluraySubtitle_windows_x64.spec

Archive the complete ``dist/BluraySubtitle_windows_x64`` directory for
distribution; the executable depends on its adjacent ``_internal`` directory.

The external tool locations are loaded from ``src/core/settings.py`` so the
spec and the application configuration cannot silently drift apart.
"""

from pathlib import Path
import runpy

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
# Copying the directory (rather than selecting individual files) also keeps
# its portable Python, plugins, scripts, SDK, and VS Editor installation.
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
    # A directory source copies all of its contents beneath this destination.
    (str(vapoursynth_dir), "vs_pkg"),
]

# pycountry needs its packaged databases.
datas += collect_data_files("pycountry")


a = Analysis(
    [str(entry_script)],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

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
