from pathlib import Path
import json
import os

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks.qt import pyqt6_library_info

from src.core.version import BUILD_COMMIT_FILENAME, git_commit_record


# Filter before binary analysis so unused desktop plugins cannot pull in their dependencies.
qt_plugins = {
    "platforms": {"libqxcb.so", "libqwayland.so", "libqoffscreen.so"},
    "xcbglintegrations": {"libqxcb-glx-integration.so", "libqxcb-egl-integration.so"},
    "wayland-shell-integration": {"libxdg-shell.so"},
    "wayland-graphics-integration-client": {"libqt-plugin-wayland-egl.so"},
    "wayland-decoration-client": {"libadwaita.so", "libbradient.so"},
    "platforminputcontexts": {
        "libcomposeplatforminputcontextplugin.so",
        "libibusplatforminputcontextplugin.so",
        "libfcitx5platforminputcontextplugin.so",
    },
    "imageformats": {"libqgif.so", "libqico.so", "libqjpeg.so", "libqsvg.so", "libqtiff.so", "libqwebp.so"},
    "iconengines": {"libqsvgicon.so"},
    "tls": {"libqopensslbackend.so", "libqcertonlybackend.so"},
    "networkinformation": {"libqglib.so", "libqnetworkmanager.so"},
}
collect_plugins = pyqt6_library_info.collect_plugins


def collect_selected_qt_plugins(plugin_type):
    names = qt_plugins.get(plugin_type, ())
    if not names:
        return []
    return [entry for entry in collect_plugins(plugin_type) if Path(entry[0]).name in names]


pyqt6_library_info.collect_plugins = collect_selected_qt_plugins


root = Path(SPECPATH)
build_commit = Path(CONF["workpath"]) / BUILD_COMMIT_FILENAME
build_commit.write_text(git_commit_record(root), encoding="utf-8")
vs_scripts = root / "third_party/vapoursynth_scripts"
pycountry_data = []
for source, destination in collect_data_files("pycountry", excludes=["locales/**"]):
    path = Path(source)
    if path.suffix == ".json" and path.parent.name == "databases":
        output = Path(CONF["workpath"]) / path.name
        output.write_text(
            json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        source = str(output)
    pycountry_data.append((source, destination))

analysis = Analysis(
    [str(root / "src/main.py")],
    pathex=[str(root), str(vs_scripts)],
    datas=[
        (str(root / "config.default.json"), "."),
        (str(build_commit), "."),
        (str(root / "tools/ubuntu_update.py"), "tools"),
        (str(root / "resource"), "resource"),
        (str(root / "LICENSE"), "legal"),
        (str(root / "src/core/settings.py"), "src/core"),
        *pycountry_data,
    ],
    hiddenimports=["muvsfunc", "mvsfunc", "vapoursynth"],
    hookspath=[str(root / "tools/pyinstaller_hooks")],
    excludes=[
        "matplotlib",
        "tkinter",
        "_tkinter",
        "numpy._core._multiarray_tests",
        "PIL.AvifImagePlugin",
        "PIL._avif",
        "PIL.ImageTk",
        "PIL._imagingtk",
    ],
)


def keep_runtime_entry(entry):
    path = Path(entry[0])
    if path.parts[0] == "pycountry" and "locales" in path.parts:
        return False
    if path.parts[0] == "PyQt6" and path.suffix == ".qm":
        return path.name in {"qt_en.qm", "qtbase_en.qm", "qt_zh_CN.qm", "qtbase_zh_CN.qm"}
    if path.parts[0] == "numpy":
        return not (
            set(path.parts).intersection({"test", "tests", "_pyinstaller", "doc"})
            or path.suffix in {".pyi", ".h", ".c", ".cpp", ".pxd", ".pyx", ".rst"}
            or "_tests." in path.name
        )
    return True


analysis.binaries = [entry for entry in analysis.binaries if keep_runtime_entry(entry)]
analysis.datas = [entry for entry in analysis.datas if keep_runtime_entry(entry)]
if apt_paths := os.environ.get("BLURAY_APT_CACHE_PATHS"):
    sources = {Path(entry[1]).resolve() for entry in (*analysis.binaries, *analysis.datas, *analysis.pure) if entry[1]}
    Path(apt_paths).write_text("".join(f"{path}\n" for path in sorted(sources)), encoding="utf-8")
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="BluraySubtitle", upx=False, console=True)
bundle = COLLECT(executable, analysis.binaries, analysis.datas, name="BluraySubtitle", upx=False)
