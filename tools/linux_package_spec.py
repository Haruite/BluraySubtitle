"""Build the native Linux PyInstaller application directory."""

from pathlib import Path
import json
import os
import sys
import sysconfig

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_data_files

python_platform = {"x64": "linux-x86_64", "arm64": "linux-aarch64"}[PACKAGE_ARCHITECTURE]
if sysconfig.get_platform() != python_platform:
    raise RuntimeError(f"Linux packaging for {PACKAGE_ARCHITECTURE} requires Python for {python_platform}")

sys.path.insert(0, str(PROJECT_ROOT))
from src.core.version import BUILD_COMMIT_FILENAME, git_commit_record
from tools.build_ass_extension import MODULE as ASS_MODULE, build_ass_extension


root = PROJECT_ROOT
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

ass_extension = build_ass_extension(Path(CONF["workpath"]) / "ass-extension")
analysis = Analysis(
    [str(root / "src/main.py")],
    pathex=[str(root), str(vs_scripts)],
    binaries=[(str(ass_extension), ".")],
    datas=[
        (str(root / "config.default.json"), "."),
        (str(build_commit), "."),
        (str(root / "tools/linux_update.py"), "tools"),
        (str(root / "resource"), "resource"),
        (str(root / "src/runtime/gtk_appearance_probe.py"), "src/runtime"),
        (str(root / "LICENSE"), "legal"),
        (str(root / "src/core/settings.py"), "src/core"),
        *pycountry_data,
    ],
    hiddenimports=["muvsfunc", "mvsfunc", "vapoursynth"],
    runtime_hooks=[str(root / "tools/pyinstaller_hooks/linux_portable_runtime.py")],
    hookspath=[str(root / "tools/pyinstaller_hooks")],
    excludes=[
        ASS_MODULE,  # The explicit binary above takes precedence over source-run builds.
        "PyQt6",  # The launcher selects a filesystem package before the first Qt import.
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
    if path.parts[0] == "numpy":
        return not (
            set(path.parts).intersection({"test", "tests", "_pyinstaller", "doc"})
            or path.suffix in {".pyi", ".h", ".c", ".cpp", ".pxd", ".pyx", ".rst"}
            or "_tests." in path.name
        )
    return True


analysis.binaries = [entry for entry in analysis.binaries if keep_runtime_entry(entry)]
if not any(Path(source).resolve() == ass_extension for _, source, _ in analysis.binaries):
    raise RuntimeError("PyInstaller did not collect the ASS extension for this build")
analysis.datas = [entry for entry in analysis.datas if keep_runtime_entry(entry)]
if apt_paths := os.environ.get("BLURAY_APT_CACHE_PATHS"):
    sources = {Path(entry[1]).resolve() for entry in (*analysis.binaries, *analysis.datas, *analysis.pure) if entry[1]}
    Path(apt_paths).write_text("".join(f"{path}\n" for path in sorted(sources)), encoding="utf-8")
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="BluraySubtitle", contents_directory=".", upx=False, console=True)
bundle = COLLECT(executable, analysis.binaries, analysis.datas, name="BluraySubtitle", upx=False)
