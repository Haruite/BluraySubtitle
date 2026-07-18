# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-file build for the Windows x64 release.

Build from the repository root with:

    pyinstaller --clean --noconfirm BluraySubtitle_windows_x64.spec

The external tool locations are loaded from ``src/core/settings.py`` so the
spec and the application configuration cannot silently drift apart.
"""

from pathlib import Path
import runpy

from PyInstaller.utils.hooks import collect_all, collect_data_files


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
    """Add a required executable/DLL to the bundle extraction root."""
    resolved = required_path(path, description)
    if not resolved.is_file():
        raise FileNotFoundError(f"Expected a file for {description}: {resolved}")
    items.append((str(resolved), "."))


entry_script = required_path(PROJECT_ROOT / "src" / "main.py", "application entry point")
getnative_vpy = required_path(PROJECT_ROOT / "src" / "vs_tools" / "getnative.vpy", "getnative.vpy")
third_party_notices = required_path(
    PROJECT_ROOT / "legal" / "THIRD_PARTY_NOTICES.md",
    "third-party notices",
)

# The application expects this exact frozen layout:
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

# Executables and DLLs configured in settings.py. They are placed at the
# extraction root to preserve the layout of the previous one-file build.
for setting_name, description in (
    ("FLAC_PATH", "FLAC encoder"),
    ("FFMPEG_PATH", "FFmpeg"),
    ("FFPROBE_PATH", "FFprobe"),
    ("X265_PATH", "x265 encoder"),
    ("X264_PATH", "x264 encoder"),
    ("SVT_AV1_PATH", "SVT-AV1 encoder"),
    ("FDK_AAC_PATH", "FDK-AAC encoder"),
    ("DOVI_TOOL_PATH", "dovi_tool"),
    ("TRUEHDD_PATH", "truehdd"),
    ("LIBASS_PATH", "libass DLL"),
    ("TS_MUXER_PATH", "tsMuxeR"),
    ("MKV_INFO_PATH", "mkvinfo"),
    ("MKV_MERGE_PATH", "mkvmerge"),
    ("MKV_PROP_EDIT_PATH", "mkvpropedit"),
    ("MKV_EXTRACT_PATH", "mkvextract"),
):
    add_binary(binaries, SETTINGS[setting_name], description)

# flac.exe requires its adjacent runtime DLLs. metaflac.exe and fdk-aac.lib
# were also present in the previous release bundle, so retain that layout.
flac_dir = Path(SETTINGS["FLAC_PATH"]).parent
for companion_name in ("metaflac.exe", "libFLAC.dll", "libFLAC++.dll"):
    add_binary(binaries, flac_dir / companion_name, f"FLAC companion {companion_name}")

fdk_aac_import_library = required_path(
    Path(SETTINGS["FDK_AAC_PATH"]).with_name("fdk-aac.lib"),
    "FDK-AAC import library",
)


datas = [
    (str(getnative_vpy), "src/vs_tools"),
    (str(third_party_notices), "legal"),
    (str(fdk_aac_import_library), "."),
    # A directory source copies all of its contents beneath this destination.
    (str(vapoursynth_dir), "vs_pkg"),
]

# librosa exposes modules lazily; collecting all of it avoids late import
# failures in audio analysis features. pycountry needs its packaged databases.
hiddenimports = []
librosa_datas, librosa_binaries, librosa_hiddenimports = collect_all("librosa")
datas += librosa_datas
binaries += librosa_binaries
hiddenimports += librosa_hiddenimports
datas += collect_data_files("pycountry")


a = Analysis(
    [str(entry_script)],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
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
