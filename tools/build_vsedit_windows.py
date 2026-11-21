"""Build and stage VSEdit with a Qt SDK for the selected Windows architecture."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET

from tools.windows_native_tools import (
    VSEDIT_PLUGINS, VSEDIT_PROGRAMS, exports_imported_symbols, fetch_verified, imported_symbols,
    runtime_dependencies, tool_version,
)


JOM_URL = "https://download.qt.io/official_releases/jom/jom_1_1_7.zip"
JOM_SHA256 = "4c8af345586a9a08fbfd2f613fcac748226d91a75627aa3581b297dd513046fe"


def unpack(archive: Path, destination: Path, seven_zip: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run([seven_zip, "x", archive, "-o" + str(destination), "-y", "-bso0", "-bsp0"], check=True)


def prepare_qt_sdk(version: str, downloads: Path, sdk: Path, seven_zip: str, *, arm64: bool = False,
                   mingw: bool = False, modules: tuple[str, ...] = ("qtbase", "qtmultimedia", "qtwebsockets")) -> None:
    if not re.fullmatch(r"6\.\d+\.\d+", version):
        raise ValueError(f"Unexpected PyQt6 Qt version: {version}")
    kit = "mingw" if mingw else ("msvc2022_arm64" if arm64 else "msvc2022_64")
    tag = "".join(version.split("."))
    host = "windows_arm64" if arm64 else "windows_x86"
    sdk_index = f"qt6_{tag}" if arm64 or version == "6.8.3" else f"qt6_{tag}_{kit}"
    repo = f"https://download.qt.io/online/qtsdkrepository/{host}/desktop/qt6_{tag}/{sdk_index}"
    downloads.mkdir(parents=True, exist_ok=True)
    index = downloads / "Updates.xml"
    if not index.is_file():
        with urllib.request.urlopen(f"{repo}/Updates.xml", timeout=90) as response:
            xml = response.read()
    else:
        xml = index.read_bytes()
    packages = {package.findtext("Name"): package for package in ET.fromstring(xml).findall("PackageUpdate")}
    for module in modules:
        group = "" if module in {"qtbase", "qttranslations"} else f".addons.{module}"
        package = f"qt.qt6.{tag}{group}.win64_{kit}"
        entry = packages[package]
        revision = entry.findtext("Version")
        archives = entry.findtext("DownloadableArchives").split(",")
        archive = next(name.strip() for name in archives if name.strip().startswith(module + "-"))
        if not revision.startswith(version + "-") or Path(archive).name != archive:
            raise ValueError(f"Unexpected {module} archive metadata for Qt {version}")
        filename = revision + archive
        url = f"{repo}/{package}/{filename}"
        checksum = downloads / (filename + ".sha1")
        if checksum.is_file():
            digest = checksum.read_text(encoding="ascii").split()[0].lower()
        else:
            with urllib.request.urlopen(url + ".sha1", timeout=60) as response:
                digest = response.read().decode("ascii").split()[0].lower()
        if not re.fullmatch("[0-9a-f]{40}", digest):
            raise ValueError(f"Invalid Qt SDK checksum: {url}")
        artifact = fetch_verified(url, downloads / filename, digest, "sha1")
        checksum.write_text(digest + "\n", encoding="ascii", newline="\r\n")
        unpack(artifact, sdk, seven_zip)
    index.write_bytes(xml)
    if (sdk / "bin/qmake.exe").is_file():
        (sdk / "bin/qt.conf").write_text("[Paths]\nPrefix=..\n", encoding="ascii", newline="\r\n")


def patch_project(project: Path, index: int, *, arm64: bool = False) -> None:
    source = project.read_text(encoding="utf-8")
    source = re.sub(r"^[ \t]*QMAKE_POST_LINK[ \t]*\+=.*DEPLOY_COMMAND.*\n", "", source, flags=re.M)
    if arm64:
        source = source.replace('"x86_64")', '"(x86_64|arm64|aarch64)")')
        source = source.replace('message("x86_64 build")', 'message("ARM64 build")')
        # The bundled libp2p has a portable path and an x86-only SIMD path.
        source = re.sub(r"^.*common-src/libp2p/simd/.*\n", "", source, flags=re.M)
        source = source.replace(" -DP2P_SIMD ", " ")
        source = re.sub(r"^[ \t]*QMAKE_EXTRA_COMPILERS \+= p2p_sse41\s*$", "", source, flags=re.M)
    if "OBJECTS_DIR = $$OUT_PWD/build-objects" not in source:
        source += (
            "\nOBJECTS_DIR = $$OUT_PWD/build-objects\n"
            f"MOC_DIR = $${{PROJECT_DIRECTORY}}/g/m{index}\n"
            f"UI_DIR = $${{PROJECT_DIRECTORY}}/g/u{index}\n"
            f"RCC_DIR = $${{PROJECT_DIRECTORY}}/g/r{index}\n"
        )
    project.write_text(source, encoding="utf-8", newline="\r\n")


def build_programs(source: Path, sdk: Path, make: Path, include: Path, env: dict, jobs: int,
                   qt_version: str, *, arm64: bool = False, win7: bool = False) -> list[Path]:
    qmake = sdk / "bin/qmake.exe"
    env = {name.upper(): value for name, value in env.items()}
    env["PATH"] = str(qmake.parent) + os.pathsep + env["PATH"]
    env["VS_INCLUDE_PATH"] = include.as_posix()
    version = subprocess.check_output([qmake, "-query", "QT_VERSION"], env=env, text=True).strip()
    if version != qt_version:
        raise ValueError(f"Expected Qt {qt_version}, found Qt {version}")
    # These shared sources are one directory shallower than the upstream include paths assume.
    for relative in ("jobs/job.h", "jobs/job.cpp", "frame_header_writers/frame_header_writer_y4m.cpp"):
        path = source / "common-src" / relative
        if path.is_file():
            original = path.read_text(encoding="utf-8")
            corrected = original.replace('#include "../../../common-src/', '#include "../')
            if corrected != original:
                path.write_text(corrected, encoding="utf-8", newline="\r\n")
    programs = []
    for index, executable in enumerate(VSEDIT_PROGRAMS):
        name = Path(executable).stem
        project = source / "pro" / name / f"{name}.pro"
        patch_project(project, index, arm64=arm64)
        output = source / "build/release-64bit-msvc"
        platform_flags = ["DEFINES+=WINVER=0x0601 _WIN32_WINNT=0x0601"] if win7 else []
        subprocess.run([qmake, project.name, "CONFIG+=release", "CONFIG-=debug_and_release", *platform_flags],
                       cwd=project.parent, env=env, check=True)
        make_arguments = [make, f"-j{jobs}", "/NOLOGO"]
        # Several upstream objects can otherwise race their generated UI headers.
        if re.search(r"(?m)^compiler_uic_make_all:", (project.parent / "Makefile").read_text(errors="replace")):
            subprocess.run([*make_arguments, "compiler_uic_make_all"], cwd=project.parent, env=env, check=True)
        subprocess.run(make_arguments, cwd=project.parent, env=env, check=True)
        programs.append(output / executable)
    return programs


def stage_editor(source: Path, programs: list[Path], payload: Path, qt: Path, env: dict,
                 *, arm64: bool = False) -> None:
    redist = next((Path(value) for key, value in env.items() if key.upper() == "VCTOOLSREDISTDIR"), None)
    plugin_root = qt / "plugins"
    architecture = "arm64" if arm64 else "x64"
    directories = [qt / "bin"]
    if redist:
        directories.extend(sorted((redist / architecture).glob("Microsoft.VC*.CRT")))
    plugins = [plugin_root / path for path in VSEDIT_PLUGINS]
    dependencies = runtime_dependencies(programs + plugins, directories)
    qt_names = {path.name.lower(): path.name for path in (qt / "bin").glob("*.dll")}
    imports = imported_symbols(programs + plugins + list(dependencies.values()))
    if any(name.startswith(("msvcp140", "vcruntime140", "concrt140")) and name not in dependencies for name in imports):
        raise RuntimeError(f"VSEdit requires the app-local {architecture} MSVC runtime")
    for name, dependency in dependencies.items():
        if name.startswith("qt6") and not exports_imported_symbols(dependency, imports[name]):
            raise RuntimeError(f"The installed PyQt6 Qt runtime is missing symbols in {name}")
    payload.mkdir()
    for name, path in dependencies.items():
        shutil.copyfile(path, payload / qt_names.get(name, path.name))
    for path in programs + [source / "README", source / "CHANGELOG", source / "resources/vsedit.ico",
                            source / "resources/vsedit.svg"]:
        shutil.copyfile(path, payload / path.name)
    for path in plugins:
        target = payload / path.relative_to(plugin_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (payload / "qt.conf").write_text("[Paths]\nPrefix=.\nPlugins=.\n", encoding="ascii", newline="\r\n")
    licenses = payload / "licenses"
    (licenses / "Qt").mkdir(parents=True)
    shutil.copyfile(source / "LICENSE", licenses / "LICENSE")


def verify_editor(directory: Path, executable: str, ref: str) -> None:
    version = tool_version(directory / executable)
    if ref not in version:
        raise RuntimeError(f"Unexpected VSEdit version: {version}")
