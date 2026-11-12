# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for the Windows x64 release.

Build from the root of a Git checkout with:

    python BluraySubtitle_windows_x64.spec

Archive the complete ``dist/BluraySubtitle_windows_x64`` directory for
distribution; the executable depends on its adjacent ``_internal`` directory.

The external tool locations are loaded from ``src/core/settings.py`` so the
spec and the application configuration cannot silently drift apart.
"""

from fnmatch import fnmatchcase
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
import json
import os
import runpy
import sys
import sysconfig
import zipfile

if "SPECPATH" not in globals():
    from PyInstaller.__main__ import run

    raise SystemExit(run([str(Path(__file__).resolve()), *sys.argv[1:]]))

from PyInstaller import __version__ as PYINSTALLER_VERSION
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
import soundfile


PROJECT_ROOT = Path(SPECPATH).resolve()
if not (PROJECT_ROOT / ".git").exists():
    raise SystemExit(
        "Windows packaging requires a Git checkout to record the source commit.\n"
        "Clone the project with the following command and build from the cloned directory.\n"
        "git clone https://github.com/Haruite/BluraySubtitle.git"
    )

sys.path.insert(0, str(PROJECT_ROOT))
from tools.windows_package_tools import build_executable_icon, installed_tools, package_tools

SETTINGS_PATH = PROJECT_ROOT / "src" / "core" / "settings.py"
SETTINGS = runpy.run_path(str(SETTINGS_PATH))
native_tools = installed_tools(SETTINGS)


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
default_config = required_path(
    PROJECT_ROOT / "config.default.json",
    "default application configuration",
)
app_icon = required_path(PROJECT_ROOT / "resource" / "bluraysubtitle.svg", "application icon")
log_icon = required_path(PROJECT_ROOT / "resource" / "log-window.svg", "log window icon")
update_script = required_path(PROJECT_ROOT / "tools" / "windows_update.ps1", "Windows update script")
exe_icon = Path(workpath) / "bluraysubtitle.ico"
build_executable_icon(app_icon, exe_icon)
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
    soundfile.__libsndfile_version__,
)

# Native tools, CPython, and NumPy share the bundle support directory.
vapoursynth_dir = required_path(
    Path(SETTINGS["VSPIPE_PATH"]).parent,
    "VapourSynth runtime directory",
)
if not vapoursynth_dir.is_dir():
    raise NotADirectoryError(f"VapourSynth path is not a directory: {vapoursynth_dir}")

vspipe_path = required_path(SETTINGS["VSPIPE_PATH"], "VSPipe executable")
upstream_manifest = required_path(vapoursynth_dir / "vapoursynth-components.json", "upstream component manifest")
upstream_components = json.loads(upstream_manifest.read_text(encoding="utf-8"))
editor_state = upstream_components["components"]["vsedit"]
_, _, editor_dir, editor_build = native_tools
if ((vapoursynth_dir / editor_state["entrypoint"]).resolve() != editor_dir / editor_build["entrypoints"]["vsedit.exe"]
        or editor_state.get("recipe") != editor_build["recipe"] or editor_state["ref"] != editor_build["version"]):
    raise RuntimeError("Run Windows setup to update the VSEdit installation record")
build_state = json.loads(required_path(
    vapoursynth_dir / "vapoursynth-build.json", "VapourSynth source-build manifest"
).read_text(encoding="utf-8"))
if build_state["python_tag"] != sys.implementation.cache_tag:
    raise RuntimeError("VapourSynth must be built for the Python running PyInstaller")


def keep_runtime_file(destination, root_binary_names):
    """Keep shared runtime files and resources used by the application."""
    path = Path(destination)
    relative = path.as_posix().lower()
    name = path.name.lower()
    parts = tuple(part.lower() for part in path.parts)

    if "__pycache__" in parts:
        return False
    if fnmatchcase(name, "tcl*.dll") or fnmatchcase(name, "tk*.dll"):
        return False

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
    )):
        return False

    # Qt can share the root C++ runtime; its additional MSVCP140_1/2 DLLs stay.
    if parts[:3] == ("pyqt6", "qt6", "bin"):
        if name in {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"}:
            return name not in root_binary_names

    if parts[0] == "numpy":
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
    (str(app_icon), "resource"),
    (str(log_icon), "resource"),
    (str(update_script), "tools"),
    (str(SETTINGS_PATH), "src/core"),
    *((str(path), "legal") for path in third_party_notices_paths.values()),
    # Keep CPython's DLLs directory available as its platform-library landmark.
    (str(required_path(Path(sys.base_prefix) / "LICENSE.txt", "CPython license")), "DLLs"),
    (str(required_path(vapoursynth_dir / "licenses", "VapourSynth source dependency licenses")), "legal/vapoursynth"),
]
ffmpeg_licenses = Path(SETTINGS["FFMPEG_PATH"]).with_name("ffmpeg-licenses.txt")
if ffmpeg_licenses.is_file():
    datas.append((str(ffmpeg_licenses), "legal/ffmpeg"))

datas += copy_metadata("numpy")
version_module = runpy.run_path(str(PROJECT_ROOT / "src" / "core" / "version.py"))
commit_file = Path(workpath) / version_module["BUILD_COMMIT_FILENAME"]
commit_file.write_text(
    version_module["git_commit_record"](PROJECT_ROOT),
    encoding="utf-8",
    newline="\r\n",
)
datas.append((str(commit_file), "."))

# Use the selected system Python for both frozen workers and VSScript.
for name in ("VapourSynth.dll", "VSScript.dll"):
    add_binary(binaries, vapoursynth_dir / name, name)
binaries.append((str(vspipe_path), "."))
for plugin in (vapoursynth_dir / "vapoursynth64/coreplugins").glob("*.dll"):
    binaries.append((str(plugin), "vapoursynth64/coreplugins"))
managed_plugins = set(upstream_components["dependencies"])
managed_plugins.update(component["plugin"] for component in upstream_components["components"].values() if "plugin" in component)
plugins_dir = Path(SETTINGS["PLUGIN_PATH"] or vapoursynth_dir / "vapoursynth64/plugins").resolve()
for relative in sorted(managed_plugins):
    source = required_path(vapoursynth_dir / relative, "managed VapourSynth plugin")
    destination = (
        Path("vapoursynth64/plugins") / source.relative_to(plugins_dir).parent
        if source.is_relative_to(plugins_dir) else source.relative_to(vapoursynth_dir).parent
    )
    binaries.append((str(source), str(destination)))
datas.append((str(upstream_manifest), "legal"))
datas.append((str(required_path(vapoursynth_dir / "portable.vs", "portable plugin marker")), "."))
script_root = required_path(
    PROJECT_ROOT / "third_party" / "vapoursynth_scripts",
    "repository-managed VapourSynth scripts",
)
datas.extend((str(script), ".") for script in sorted(script_root.glob("*.py")))
for name in ("COPYRIGHT.md", "COPYRIGHT.zh-Hans.md"):
    datas.append((str(required_path(script_root / name, "VapourSynth script notices")), "legal/vapoursynth_scripts"))
datas.append((str(required_path(script_root / "licenses", "VapourSynth script licenses")), "legal/vapoursynth_scripts/licenses"))

# VSScript has a regular CPython importer, so give it a standard-library archive.
# VSScript reads the same NumPy and filter source files as frozen workers.
shared_python = Path(workpath) / "shared-python"
shared_python.mkdir(parents=True, exist_ok=True)
python_ini = shared_python / "python-runtime.ini"
python_ini.write_text("[Python]\nHome=.\nIsolated=1\n", encoding="utf-8", newline="\r\n")
datas.append((str(python_ini), "."))
standard_library = Path(sysconfig.get_path("stdlib"))
standard_archive = shared_python / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
with zipfile.ZipFile(standard_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for directory, folders, files in os.walk(standard_library):
        folders[:] = [name for name in folders if name not in {
            "site-packages", "__pycache__", "test", "tests", "idlelib",
            "tkinter", "turtledemo", "ensurepip",
        }]
        for name in files:
            if name.endswith(".py"):
                file = Path(directory) / name
                archive.write(file, file.relative_to(standard_library).as_posix())
datas.append((str(standard_archive), "."))
for library in (Path(sys.base_prefix) / "DLLs").iterdir():
    if library.suffix.lower() == ".pyd":
        module_name = next((
            library.name[:-len(suffix)] for suffix in EXTENSION_SUFFIXES
            if library.name.endswith(suffix) and "." not in library.name[:-len(suffix)]
        ), "")
        if (
            not module_name or module_name.endswith("_d")
            or module_name.startswith("_test")
            or module_name in {"_ctypes_test", "_tkinter"}
        ):
            continue
        add_binary(binaries, library, library.name)
    elif (
        library.suffix.lower() == ".dll" and not library.stem.endswith("_d")
        and not library.name.lower().startswith(("tcl", "tk"))
    ):
        add_binary(binaries, library, library.name)

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
    pathex=[str(script_root), str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["muvsfunc", "mvsfunc"],
    hookspath=[str(PROJECT_ROOT / "tools" / "pyinstaller_hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # muvsfunc's optional plotting helper is not used by the application.
        "matplotlib",
        "tkinter",
        "_tkinter",
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
a.binaries = [
    ("vspipe.exe", source, kind) if Path(source).resolve() == vspipe_path else (destination, source, kind)
    for destination, source, kind in a.binaries
]
root_binary_names = {
    Path(destination).name.lower()
    for destination, _source, _kind in a.binaries
    if len(Path(destination).parts) == 1
}
a.binaries = [entry for entry in a.binaries if keep_runtime_file(entry[0], root_binary_names)]
a.datas = [entry for entry in a.datas if keep_runtime_file(entry[0], root_binary_names)]

pycountry_databases = Path(workpath) / "pycountry-databases"
pycountry_databases.mkdir(exist_ok=True)
for index, (destination, source, kind) in enumerate(a.datas):
    relative = Path(destination)
    if relative.parent.as_posix() == "pycountry/databases" and relative.suffix == ".json":
        compact = pycountry_databases / relative.name
        data = json.loads(Path(source).read_text(encoding="utf-8"))
        compact.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        a.datas[index] = (destination, str(compact), kind)

sndfile_dir = PROJECT_ROOT / "build/windows-runtime" / f"libsndfile-{soundfile.__libsndfile_version__}"
sndfile = sndfile_dir / "libsndfile_x64.dll"
if sndfile.is_file():
    destination = "_soundfile_data/libsndfile_x64.dll"
    license_destination = "_soundfile_data/COPYING"
    a.binaries = [entry for entry in a.binaries if Path(entry[0]).as_posix() != destination]
    a.datas = [entry for entry in a.datas if Path(entry[0]).as_posix() not in (destination, license_destination)]
    a.binaries.append((destination, str(sndfile), "BINARY"))
    a.datas.append((license_destination, str(required_path(sndfile_dir / "COPYING", "libsndfile license")), "DATA"))

# Keep the separate MinGW QtCore and the shared MSVC Qt layout after Analysis.
a.datas += package_tools(native_tools, Path(workpath) / "native-tools", a.binaries, a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BluraySubtitle_windows_x64",
    icon=str(exe_icon),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
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
