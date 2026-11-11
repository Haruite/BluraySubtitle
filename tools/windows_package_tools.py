"""Collect the Windows Qt tools without duplicating their packaged runtimes."""

from pathlib import Path
import shutil
import subprocess

from tools.windows_native_tools import (
    MsvcRequired, build_record, editor_qt_files, editor_runtime_matches, exports_imported_symbols,
    file_hash, imported_symbols, msvc_environment, pe_imports, pyqt_runtime,
)
from tools.windows_tool_paths import MKV_SETTINGS


def build_launchers(work: Path) -> dict[bool, Path]:
    try:
        env = msvc_environment()
    except MsvcRequired as error:
        raise RuntimeError("Run Windows setup to prepare MSVC for the bundled launchers") from error
    compiler = shutil.which("cl.exe", path=env["PATH"])
    if compiler is None:
        raise FileNotFoundError("MSVC cl.exe was not found in the x64 build environment")
    source = Path(__file__).with_name("windows_tool_launcher.c")
    work.mkdir(parents=True, exist_ok=True)
    launchers = {}
    for gui, subsystem in ((False, "CONSOLE"), (True, "WINDOWS")):
        filename = "launcher-" + subsystem.lower()
        output = work / (filename + ".exe")
        subprocess.run([
            compiler, "/nologo", "/std:c17", "/O1", "/Zl", "/W4",
            *(["/DGUI_ENTRY"] if gui else []),
            str(source), "/Fo" + str(work / (filename + ".obj")), "/Fe" + str(output),
            "/link", "/NODEFAULTLIB", "/ENTRY:launch_entry", "/SUBSYSTEM:" + subsystem,
            "/INCREMENTAL:NO", "/OPT:REF", "/OPT:ICF", "libvcruntime.lib", "kernel32.lib",
            *(["user32.lib"] if gui else []),
        ], cwd=work, env=env, check=True)
        launchers[gui] = output
    return launchers


def installed_tools(settings) -> tuple[Path, dict, Path, dict]:
    mkv_paths = {name: Path(settings[key]).resolve() for name, key in MKV_SETTINGS.items()}
    mkv = mkv_paths["mkvmerge.exe"].parent
    editor_path = Path(settings["VSEDIT_PATH"]).resolve()
    editor = editor_path.parent
    mkv_record = build_record(mkv, "mkvtoolnix")
    editor_record = build_record(editor, "vsedit")
    if (mkv.name.casefold() != "mkvtoolnix" or not mkv_record
            or any(path.parent != mkv for path in mkv_paths.values())
            or mkv_record["entrypoints"] != {name: path.name for name, path in mkv_paths.items()}):
        raise RuntimeError("Run Windows setup to install the managed MKVToolNix build")
    if editor.name.casefold() != "vsedit" or not editor_record or editor_record["entrypoints"]["vsedit.exe"] != editor_path.name:
        raise RuntimeError("Run Windows setup to install the managed VSEdit build")
    return mkv, mkv_record, editor, editor_record


def package_tools(tools, work: Path, binaries, datas) -> list[tuple[str, str, str]]:
    import pefile

    mkv, mkv_record, editor, editor_record = tools
    qt_version, qt = pyqt_runtime()
    if not editor_runtime_matches(editor_record, qt_version, qt):
        raise RuntimeError("Run Windows setup to rebuild VSEdit for the installed PyQt6 Qt runtime")

    occupied = {Path(name).as_posix().lower(): Path(source) for name, source, _kind in (*datas, *binaries)}
    files = []

    def include(source: Path, relative: str) -> None:
        existing = occupied.get(relative.lower())
        if existing is not None:
            if existing.resolve() != source.resolve() and file_hash(existing) != file_hash(source):
                raise RuntimeError(f"Different files would be bundled at {relative}: {existing} and {source}")
            return
        occupied[relative.lower()] = source
        files.append((relative, str(source), "DATA"))

    launchers = build_launchers(work)
    for tool, directory, record in (("mkvtoolnix", mkv, mkv_record), ("vsedit", editor, editor_record)):
        for name, installed_name in record["entrypoints"].items():
            source = directory / installed_name
            with pefile.PE(str(source), fast_load=True) as image:
                gui = image.OPTIONAL_HEADER.Subsystem == 2
            include(source, f"{tool}/{Path(name).stem}-native.exe")
            include(launchers[gui], f"{tool}/{name}")
            if tool == "mkvtoolnix":
                include(launchers[gui], name)

    mkv_imports = imported_symbols(mkv / name for name in mkv_record["files"] if Path(name).suffix.lower() in (".dll", ".exe"))
    for name, digest in mkv_record["files"].items():
        if name in mkv_record["entrypoints"].values():
            continue
        if name.startswith("locale/") and not name.startswith(("locale/en/", "locale/zh_CN/")):
            continue
        if name.startswith("licenses/"):
            include(mkv / name, f"legal/mkvtoolnix/{name.removeprefix('licenses/')}")
            continue
        dll = name.lower()
        root = occupied.get(dll)
        if root:
            if file_hash(root) == digest:
                continue
            symbols = mkv_imports.get(dll)
            if (symbols and dll in {"libflac.dll", "libwinpthread-1.dll"}
                    and exports_imported_symbols(root, symbols)
                    and (dll != "libwinpthread-1.dll" or pe_imports(root).keys() == pe_imports(mkv / name).keys())):
                continue
        include(mkv / name, f"mkvtoolnix/{name}")

    qt_files = editor_qt_files(editor_record, qt)
    for name, source in qt_files.items():
        include(source, f"PyQt6/Qt6/{source.relative_to(qt).as_posix()}")
    editor_imports = imported_symbols(
        editor / name for name in editor_record["files"] if Path(name).suffix.lower() in (".dll", ".exe")
    )
    for name, digest in editor_record["files"].items():
        if name in editor_record["entrypoints"].values() or name in qt_files or name == "qt.conf":
            continue
        source = editor / name
        if name.startswith("licenses/"):
            include(source, f"legal/vsedit/{name.removeprefix('licenses/')}")
        elif name.lower().endswith(".dll"):
            dll = name.lower()
            root = occupied.get(dll)
            symbols = editor_imports.get(dll)
            if root and (file_hash(root) == digest or (
                dll.startswith(("msvcp140", "vcruntime140")) and symbols and exports_imported_symbols(root, symbols)
            )):
                continue
            include(source, f"PyQt6/Qt6/bin/{name}")
        else:
            include(source, f"vsedit/{name}")

    config = work / "vsedit.config"
    config.write_text(
        "[common]\nprefer_vs_libs_from_list=false\nvapoursynth_library_paths=../\n"
        "vapoursynth_plugins_paths=../vapoursynth64/coreplugins, ../vapoursynth64/plugins\n",
        encoding="utf-8", newline="\r\n",
    )
    qt_config = work / "qt.conf"
    qt_config.write_text("[Paths]\nPrefix=../PyQt6/Qt6\nPlugins=plugins\n", encoding="ascii", newline="\r\n")
    include(config, "vsedit/vsedit.config")
    include(qt_config, "vsedit/qt.conf")
    return files
