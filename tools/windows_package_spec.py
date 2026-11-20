"""Build the Windows distribution shared by the architecture-specific spec files."""

from fnmatch import fnmatchcase
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
import json
import os
import runpy
import sys
import sysconfig
import zipfile

from PyInstaller import __version__ as PYINSTALLER_VERSION
from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
import soundfile
import vapoursynth


package_name = f"BluraySubtitle_windows_{PACKAGE_ARCHITECTURE}"
arm64 = PACKAGE_ARCHITECTURE == "arm64"
python_platform = "win-arm64" if arm64 else "win-amd64"
if sysconfig.get_platform() != python_platform:
    raise RuntimeError(f"{package_name} requires Python for {python_platform}")
if not (PROJECT_ROOT / ".git").exists():
    raise SystemExit(
        "Windows packaging requires a Git checkout to record the source commit.\n"
        "Clone the project with the following command and build from the cloned directory.\n"
        "git clone https://github.com/Haruite/BluraySubtitle.git"
    )

sys.path.insert(0, str(PROJECT_ROOT))
from tools.windows_native_tools import ARM64_NLM_CPU, file_hash, has_pe_machine, pyqt_runtime, runtime_dependencies
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
exe_icon = WORK_PATH / "bluraysubtitle.ico"
build_executable_icon(app_icon, exe_icon)
third_party_notices_paths = {
    required_path(PROJECT_ROOT / "legal/windows" / name, "third-party notices template"):
        WORK_PATH / "legal" / name
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
    PACKAGE_ARCHITECTURE,
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
    raise RuntimeError("Run Windows setup with the Python running PyInstaller")
r79 = build_state.get("version") == "79"
if arm64 and r79:
    nlm = upstream_components["components"].get("nlm_ispc", {})
    if (nlm.get("ispc_cpu") != ARM64_NLM_CPU or nlm["method"] != "source"
            or nlm["files"].get(nlm["plugin"]) != file_hash(vapoursynth_dir / nlm["plugin"])):
        raise RuntimeError(f"Run Windows setup to install the {ARM64_NLM_CPU} build of NLM")
if r79 and Path(vapoursynth.__file__).resolve().parent != Path(build_state["package"]).resolve():
    raise RuntimeError("The packaging Python did not import the configured VapourSynth R79 wheel")
vs_bundle = Path("Lib/site-packages/vapoursynth") if r79 else Path(".")


def keep_runtime_file(destination, source, root_binary_names):
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

    # Share native CRT DLLs with the main executable. Some ARM64 Qt wheels
    # also include an unused x64 vcruntime140_1.dll.
    if parts[:3] == ("pyqt6", "qt6", "bin") and name in {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"}:
        return name not in root_binary_names and (not arm64 or has_pe_machine(Path(source)))

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
]
vs_license_dir = required_path(vapoursynth_dir / "licenses", "VapourSynth source dependency licenses")
datas.extend((str(path), "legal/vapoursynth") for path in sorted(vs_license_dir.iterdir()) if path.is_file())
# Collect plugin licenses from the current install manifest so obsolete files are skipped.
for component in upstream_components["components"].values():
    for name in sorted(component["files"]):
        relative = Path(name)
        if relative.is_relative_to("licenses/components"):
            source = required_path(vapoursynth_dir / relative, "VapourSynth component license")
            destination = Path("legal/vapoursynth") / relative.relative_to("licenses").parent
            datas.append((str(source), destination.as_posix()))
ffmpeg_licenses = Path(SETTINGS["FFMPEG_PATH"]).with_name("ffmpeg-licenses.txt")
if ffmpeg_licenses.is_file():
    datas.append((str(ffmpeg_licenses), "legal/ffmpeg"))

datas += copy_metadata("numpy")
version_module = runpy.run_path(str(PROJECT_ROOT / "src" / "core" / "version.py"))
commit_file = WORK_PATH / version_module["BUILD_COMMIT_FILENAME"]
commit_file.write_text(
    version_module["git_commit_record"](PROJECT_ROOT),
    encoding="utf-8",
    newline="\r\n",
)
datas.append((str(commit_file), "."))

# Keep the upstream package layout so R79 VSScript can discover the bundled CPython.
if r79:
    vs_package = Path(vapoursynth.__file__).resolve().parent
    runtime_files = [
        "vsscript.dll", "libvapoursynth.dll", "libvapoursynthfilters.dll", "vspipe.exe", "vapoursynth.pyd",
    ]
    if not arm64:
        runtime_files.extend(("libvapoursynthfilters_avx2.dll", "libvapoursynthfilters_zn4.dll"))
        binaries.append((str(required_path(vs_package / "plugins/avscompat.dll", "AviSynth compatibility plugin")),
                         (vs_bundle / "plugins").as_posix()))
    runtime_binaries = [required_path(vs_package / name, name) for name in runtime_files]
    # Standalone VSPipe loads VSScript before the embedded Python is available.
    search_dirs = [vs_package, Path(sys.base_prefix)]
    if not arm64:
        search_dirs.append(pyqt_runtime()[1] / "bin")
    standalone_dependencies = runtime_dependencies(runtime_binaries, search_dirs)
    runtime_binaries.extend(
        path for name, path in standalone_dependencies.items()
        if name not in runtime_files and path.parent != Path(sys.base_prefix)
    )
    binaries.extend((str(path), vs_bundle.as_posix()) for path in runtime_binaries)

    # Resolve the shared plugin DLLs in the bundle support directory. VSPipe's
    # isolated CPython does not process the setup's site-packages hooks.
    shared_init = WORK_PATH / "vapoursynth" / "__init__.py"
    shared_init.parent.mkdir(parents=True, exist_ok=True)
    shared_init.write_text(
        (vs_package / "__init__.py").read_text(encoding="utf-8")
        + "\nimport os as _os\nfrom pathlib import Path as _Path\n"
          "_shared_dlls = _os.add_dll_directory(str(_Path(__file__).resolve().parents[3]))\n",
        encoding="utf-8", newline="\r\n",
    )
    datas.append((str(shared_init), vs_bundle.as_posix()))
    datas.extend((str(path), vs_bundle.as_posix()) for path in vs_package.glob("*.py") if path.name != shared_init.name)
    for name in ("python.exe", "python3.dll"):
        add_binary(binaries, Path(sys.base_prefix) / name, name)
    shared_path = WORK_PATH / f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    shared_path.write_text(
        f"python{sys.version_info.major}{sys.version_info.minor}.zip\n.\nDLLs\nLib/site-packages\n",
        encoding="ascii", newline="\r\n",
    )
    datas.append((str(shared_path), "."))
else:
    for name in ("VapourSynth.dll", "VSScript.dll"):
        add_binary(binaries, vapoursynth_dir / name, name)
    binaries.append((str(vspipe_path), "."))
    for plugin in (vapoursynth_dir / "vapoursynth64/coreplugins").glob("*.dll"):
        binaries.append((str(plugin), "vapoursynth64/coreplugins"))
    datas.append((str(required_path(vapoursynth_dir / "portable.vs", "portable plugin marker")), "."))

libass = Path(SETTINGS["LIBASS_PATH"])
managed_plugins = set(upstream_components["dependencies"])
managed_plugins.update(component["plugin"] for component in upstream_components["components"].values() if "plugin" in component)
plugin_data = {name for component in upstream_components["components"].values() for name in component.get("data", ())}
plugins_dir = Path(SETTINGS["PLUGIN_PATH"] or vapoursynth_dir / "vapoursynth64/plugins").resolve()
for relative in sorted(managed_plugins | plugin_data):
    source = required_path(vapoursynth_dir / relative, "managed VapourSynth component file")
    if r79 and relative in upstream_components["dependencies"]:
        if source.name.casefold() == libass.name.casefold():
            if file_hash(source) != file_hash(libass):
                raise RuntimeError("ASSRender and the application are configured with different libass DLLs")
            continue
        if any(path.name.casefold() == source.name.casefold() and file_hash(path) == file_hash(source)
               for path in runtime_binaries):
            continue
        destination = Path(".")
    elif r79:
        destination = vs_bundle / "plugins" / (source.relative_to(plugins_dir).parent
                                               if source.is_relative_to(plugins_dir) else Path("."))
    else:
        destination = (
            Path("vapoursynth64/plugins") / source.relative_to(plugins_dir).parent
            if source.is_relative_to(plugins_dir) else source.relative_to(vapoursynth_dir).parent
        )
    (datas if relative in plugin_data else binaries).append((str(source), destination.as_posix()))
datas.append((str(upstream_manifest), "legal"))
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
shared_python = WORK_PATH / "shared-python"
shared_python.mkdir(parents=True, exist_ok=True)
if not r79:
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
    hiddenimports=["muvsfunc", "mvsfunc", "vapoursynth"],
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
    ("vspipe.exe", source, kind) if not r79 and Path(source).resolve() == vspipe_path else (destination, source, kind)
    for destination, source, kind in a.binaries
]
root_binary_names = {
    Path(destination).name.lower()
    for destination, _source, _kind in a.binaries
    if len(Path(destination).parts) == 1
}
if r79:
    # The frozen app and standalone VSScript import the same files.
    a.pure = [entry for entry in a.pure if entry[0] != "vapoursynth" and not entry[0].startswith("vapoursynth.")]
    a.binaries = [entry for entry in a.binaries if Path(entry[0]).parts[0].casefold() != "vapoursynth"]
a.binaries = [entry for entry in a.binaries if keep_runtime_file(*entry[:2], root_binary_names)]
a.datas = [entry for entry in a.datas if keep_runtime_file(*entry[:2], root_binary_names)]

pycountry_databases = WORK_PATH / "pycountry-databases"
pycountry_databases.mkdir(exist_ok=True)
for index, (destination, source, kind) in enumerate(a.datas):
    relative = Path(destination)
    if relative.parent.as_posix() == "pycountry/databases" and relative.suffix == ".json":
        compact = pycountry_databases / relative.name
        data = json.loads(Path(source).read_text(encoding="utf-8"))
        compact.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        a.datas[index] = (destination, str(compact), kind)

sndfile_dir = PROJECT_ROOT / "build/windows-runtime" / f"libsndfile-{soundfile.__libsndfile_version__}"
sndfile = sndfile_dir / f"libsndfile_{PACKAGE_ARCHITECTURE}.dll"
if sndfile.is_file():
    destination = f"_soundfile_data/{sndfile.name}"
    license_destination = "_soundfile_data/COPYING"
    a.binaries = [entry for entry in a.binaries if Path(entry[0]).as_posix() != destination]
    a.datas = [entry for entry in a.datas if Path(entry[0]).as_posix() not in (destination, license_destination)]
    a.binaries.append((destination, str(sndfile), "BINARY"))
    a.datas.append((license_destination, str(required_path(sndfile_dir / "COPYING", "libsndfile license")), "DATA"))

# Keep the separate MinGW QtCore and the shared MSVC Qt layout after Analysis.
a.datas += package_tools(native_tools, WORK_PATH / "native-tools", a.binaries, a.datas, vs_bundle=vs_bundle)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=package_name,
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
    name=package_name,
)
