"""Shared runtime and build records for the Windows Qt tools."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from tools.windows_build_cache import files_under
from tools.windows_tool_paths import MKV_SETTINGS


MKV_RECIPE = "mingw-ucrt-static-qtcore-1"
MKV_DYNAMIC_RECIPE = "mingw-ucrt-qtcore-no-icu-1"
VSEDIT_RECIPE = "msvc-pyqt6-1"
INSTALLATION_SCHEMA = 1
VSEDIT_PROGRAMS = (
    "vsedit.exe", "vsedit-previewer.exe", "vsedit-encode.exe",
    "vsedit-job-server.exe", "vsedit-job-server-watcher.exe",
)
VSEDIT_PLUGINS = (
    "platforms/qwindows.dll", "imageformats/qwebp.dll", "multimedia/windowsmediaplugin.dll",
)
VSEDIT_QT_LIBRARIES = tuple(f"Qt6{name}.dll" for name in ("Core", "Gui", "Network", "Widgets", "Multimedia", "WebSockets"))
SYSTEM_ROOT = Path(os.environ.get("SystemRoot", r"C:\Windows"))


class MsvcRequired(Exception):
    """Resume the build after preparing the x64 MSVC toolchain."""


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, algorithm).hexdigest()


def fingerprint(*inputs) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode("utf-8")).hexdigest()


def fetch_verified(url: str, destination: Path, digest: str, algorithm: str = "sha256") -> Path:
    if destination.is_file() and file_hash(destination, algorithm) == digest:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".part", delete=False) as stream:
            partial = Path(stream.name)
        try:
            with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output)
            if file_hash(partial, algorithm) != digest:
                raise ValueError(f"{algorithm.upper()} mismatch: {url}")
            partial.replace(destination)
            return destination
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
        finally:
            partial.unlink(missing_ok=True)


def pyqt_runtime() -> tuple[str, Path]:
    from PyQt6.QtCore import QLibraryInfo, qVersion

    return qVersion(), Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PrefixPath)).resolve()


def editor_qt_files(record: dict, qt: Path) -> dict[str, Path]:
    return {
        name: qt / ("plugins" if "/" in name else "bin") / name
        for name in record["files"]
        if name in VSEDIT_PLUGINS or (name.lower().startswith("qt6") and name.lower().endswith(".dll"))
    }


def editor_runtime_matches(record: dict, version: str, qt: Path) -> bool:
    if record.get("qt_version") != version:
        return False
    return all(path.is_file() and file_hash(path) == record["files"][name]
               for name, path in editor_qt_files(record, qt).items())


def msvc_environment() -> dict[str, str]:
    environment = os.environ.copy()
    installer = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    vswhere = installer / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        raise MsvcRequired("Windows setup must prepare the x64 MSVC build tools")
    install = subprocess.check_output([
        vswhere, "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "-property", "installationPath", "-utf8",
    ], encoding="utf-8").strip()
    vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
    if not vcvars.is_file():
        raise MsvcRequired("Windows setup must prepare the x64 MSVC build tools")
    environment["BLURAYSUBTITLE_VCVARS"] = str(vcvars)
    cmd = SYSTEM_ROOT / "System32/cmd.exe"
    output = subprocess.check_output(
        f'"{cmd}" /d /u /s /c "call "%BLURAYSUBTITLE_VCVARS%" >nul && set"',
        env=environment, encoding="utf-16-le",
    )
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line and not line.startswith("="))


def clean_tool_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PATH"] = str(SYSTEM_ROOT / "System32")
    for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH"):
        environment.pop(name, None)
    return environment


def tool_version(executable: Path) -> str:
    result = subprocess.run(
        [executable.resolve(), "--version"], cwd=executable.parent, capture_output=True, check=True, timeout=30,
        encoding="utf-8", errors="replace", env=clean_tool_environment(),
    )
    return (result.stdout + result.stderr).strip()


def pe_imports(path: Path) -> dict[str, set]:
    import pefile

    directories = ("IMAGE_DIRECTORY_ENTRY_IMPORT", "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT")
    with pefile.PE(str(path), fast_load=True) as image:
        if image.FILE_HEADER.Machine != 0x8664:
            raise ValueError(f"Expected an x64 Windows binary: {path}")
        image.parse_data_directories([pefile.DIRECTORY_ENTRY[name] for name in directories])
        imports = {}
        for directory in directories:
            for entry in getattr(image, "DIRECTORY_ENTRY_" + directory.removeprefix("IMAGE_DIRECTORY_ENTRY_"), ()):
                imports.setdefault(entry.dll.decode("ascii").lower(), set()).update(
                    symbol.name if symbol.name is not None else symbol.ordinal for symbol in entry.imports
                )
    return imports


def imported_symbols(programs) -> dict[str, set]:
    imports = {}
    for program in programs:
        for name, symbols in pe_imports(program).items():
            imports.setdefault(name, set()).update(symbols)
    return imports


def exports_imported_symbols(path: Path, symbols: set) -> bool:
    import pefile

    with pefile.PE(str(path), fast_load=True, max_symbol_exports=65536) as image:
        if image.FILE_HEADER.Machine != 0x8664:
            return False
        image.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])
        directory = getattr(image, "DIRECTORY_ENTRY_EXPORT", None)
        if directory is None:
            return False
        exports = {name for symbol in directory.symbols
                   for name in (symbol.name, symbol.ordinal)}
    return symbols <= exports


def runtime_dependencies(programs, search_dirs: list[Path]) -> dict[str, Path]:
    """Resolve private PE imports before considering the Windows system directory."""
    private = {}
    pending = list(programs)
    system = SYSTEM_ROOT / "System32"
    while pending:
        program = pending.pop()
        for name in pe_imports(program):
            if name in private or name.startswith(("api-ms-win-", "ext-ms-win-")):
                continue
            dependency = next((directory / name for directory in search_dirs if (directory / name).is_file()), None)
            if dependency is not None:
                private[name] = dependency
                pending.append(dependency)
            elif not (system / name).is_file():
                raise FileNotFoundError(f"Missing {name} imported by {program}")
    return private


def verify_mkv_runtime(programs, dependencies: dict[str, Path]) -> None:
    if (any(name.startswith(("qt6", "icu")) for name in dependencies)
            or any("libmtxcommon.dll" not in pe_imports(program) for program in programs)):
        raise RuntimeError("Expected MKVToolNix to use the ICU-free QtCore linked into libmtxcommon.dll")


def build_record(directory: Path, tool: str, *, installed: bool = False, allow_legacy: bool = False) -> dict | None:
    """Check the build recipe, executable mapping and the recorded file hashes."""
    try:
        record = json.loads((directory / f"{tool}-build.json").read_text(encoding="utf-8"))
        recipe, programs = (MKV_RECIPE, MKV_SETTINGS) if tool == "mkvtoolnix" else (VSEDIT_RECIPE, VSEDIT_PROGRAMS)
        if installed and record.get("installation_schema") != INSTALLATION_SCHEMA:
            return None
        legacy = tool == "mkvtoolnix" and record["recipe"] == MKV_DYNAMIC_RECIPE
        if record["recipe"] != recipe and not (allow_legacy and legacy):
            return None
        if not all(isinstance(record[key], str) and record[key] for key in ("version", "fingerprint")):
            return None
        entries = record["entrypoints"]
        files = record["files"]
        if set(entries) != set(programs) or len({name.casefold() for name in entries.values()}) != len(entries):
            return None
        if any(Path(name).name != name or Path(name).suffix.lower() != ".exe" for name in entries.values()):
            return None
        required = set(entries.values())
        if tool == "mkvtoolnix":
            required.add("libmtxcommon.dll")
            if legacy:
                required.add("Qt6Core.dll")
            elif any(Path(name).name.casefold() == "qt6core.dll" for name in files):
                return None
        else:
            required.update(("Qt6Core.dll", *VSEDIT_PLUGINS))
        if not required <= files.keys():
            return None
        for name, digest in files.items():
            relative = Path(name)
            path = (directory / relative).resolve()
            if (relative.as_posix() != name or relative.anchor or ".." in relative.parts
                    or not path.is_relative_to(directory.resolve()) or file_hash(path) != digest):
                return None
    except (KeyError, OSError, AttributeError, TypeError, ValueError):
        return None
    return record


def record_build(directory: Path, tool: str, recipe: str, version: str, key: str, programs, **metadata) -> None:
    record = {
        "recipe": recipe, "version": version, "fingerprint": key,
        "entrypoints": {name: name for name in programs},
        "files": {name: file_hash(path) for name, path in sorted(files_under(directory).items())},
        **metadata,
    }
    (directory / f"{tool}-build.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\r\n")


def install_build(directory: Path, destination: Path, tool: str, record: dict, entrypoints: dict[str, str]) -> None:
    """Copy a verified build, recording the configured names after deployment."""
    import msvcrt

    if set(record["entrypoints"]) != entrypoints.keys():
        raise ValueError(f"Incomplete executable mapping for {tool}")
    mapping = {record["entrypoints"][name]: target for name, target in entrypoints.items()}
    names = {name: mapping.get(name, name) for name in record["files"]}
    if (len({name.casefold() for name in names.values()}) != len(names)
            or any(Path(name).name != name or Path(name).suffix.lower() != ".exe" for name in mapping.values())):
        raise ValueError(f"Invalid configured executable names for {tool}")
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / f"{tool}-build.json"
    with (destination / ".build.lock").open("a+b") as lock, ExitStack() as cleanup:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        previous = build_record(destination, tool, allow_legacy=True)
        install_root = destination.resolve()

        def stage_file(target: Path):
            if not target.resolve().is_relative_to(install_root):
                raise ValueError(f"Installation file is outside its tool directory: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            # Create each file beside its target so it inherits the installation directory's ACL.
            stream = tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{tool}-", suffix=".part", delete=False)
            cleanup.callback(Path(stream.name).unlink, missing_ok=True)
            return stream

        staged_files = []
        for name, relative in names.items():
            target = destination / relative
            with stage_file(target) as staged, (directory / name).open("rb") as source:
                shutil.copyfileobj(source, staged)
                staged_files.append((Path(staged.name), target))
        updated = dict(record, installation_schema=INSTALLATION_SCHEMA, entrypoints=entrypoints, files={
            names[name]: digest for name, digest in record["files"].items()
        })
        with stage_file(marker) as staged:
            staged.write((json.dumps(updated, indent=2).replace("\n", "\r\n") + "\r\n").encode("utf-8"))
            staged_record = Path(staged.name)
        for staged, target in staged_files:
            staged.replace(target)
        if previous:
            retained = {name.casefold() for name in names.values()}
            for relative in previous["files"]:
                if relative.casefold() not in retained:
                    (destination / relative).unlink(missing_ok=True)
        staged_record.replace(marker)
