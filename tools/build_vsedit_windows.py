"""Build VSEdit with the official MSVC SDK matching the installed PyQt6 Qt."""

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


def prepare_qt_sdk(version: str, downloads: Path, sdk: Path, seven_zip: str) -> None:
    if not re.fullmatch(r"6\.\d+\.\d+", version):
        raise ValueError(f"Unexpected PyQt6 Qt version: {version}")
    kit = "msvc2022_64"
    tag = "".join(version.split("."))
    repo = f"https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_{tag}/qt6_{tag}_{kit}"
    downloads.mkdir(parents=True, exist_ok=True)
    index = downloads / "Updates.xml"
    if not index.is_file():
        with urllib.request.urlopen(f"{repo}/Updates.xml", timeout=90) as response:
            xml = response.read()
    else:
        xml = index.read_bytes()
    packages = {package.findtext("Name"): package for package in ET.fromstring(xml).findall("PackageUpdate")}
    for module in ("qtbase", "qtmultimedia", "qtwebsockets"):
        group = "" if module == "qtbase" else f".addons.{module}"
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
    (sdk / "bin/qt.conf").write_text("[Paths]\nPrefix=..\n", encoding="ascii", newline="\r\n")


def patch_project(project: Path, index: int) -> None:
    source = project.read_text(encoding="utf-8")
    source = re.sub(r"^[ \t]*QMAKE_POST_LINK[ \t]*\+=.*DEPLOY_COMMAND.*\n", "", source, flags=re.M)
    if "OBJECTS_DIR = $$OUT_PWD/build-objects" not in source:
        source += (
            "\nOBJECTS_DIR = $$OUT_PWD/build-objects\n"
            f"MOC_DIR = $${{PROJECT_DIRECTORY}}/g/m{index}\n"
            f"UI_DIR = $${{PROJECT_DIRECTORY}}/g/u{index}\n"
            f"RCC_DIR = $${{PROJECT_DIRECTORY}}/g/r{index}\n"
        )
    project.write_text(source, encoding="utf-8", newline="\r\n")


def build_programs(source: Path, sdk: Path, jom: Path, include: Path, env: dict, jobs: int,
                   qt_version: str) -> list[Path]:
    qmake = sdk / "bin/qmake.exe"
    env = {name.upper(): value for name, value in env.items()}
    env["PATH"] = str(qmake.parent) + os.pathsep + env["PATH"]
    env["VS_INCLUDE_PATH"] = include.as_posix()
    version = subprocess.check_output([qmake, "-query", "QT_VERSION"], env=env, text=True).strip()
    if version != qt_version:
        raise ValueError(f"Expected the Qt {qt_version} MSVC SDK, found Qt {version}")
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
        patch_project(project, index)
        subprocess.run([qmake, project.name, "CONFIG+=release", "CONFIG-=debug_and_release"], cwd=project.parent,
                       env=env, check=True)
        # Several upstream objects can otherwise race their generated UI headers.
        subprocess.run([jom, f"-j{jobs}", "/NOLOGO", "compiler_uic_make_all"], cwd=project.parent, env=env, check=True)
        subprocess.run([jom, f"-j{jobs}", "/NOLOGO"], cwd=project.parent, env=env, check=True)
        programs.append(source / "build/release-64bit-msvc" / executable)
    return programs


def stage_editor(source: Path, programs: list[Path], payload: Path, qt: Path, env: dict) -> None:
    redist = next((Path(value) for key, value in env.items() if key.upper() == "VCTOOLSREDISTDIR"), None)
    directories = [qt / "bin"]
    if redist:
        directories.extend(sorted((redist / "x64").glob("Microsoft.VC*.CRT")))
    plugins = [qt / "plugins" / path for path in VSEDIT_PLUGINS]
    dependencies = runtime_dependencies(programs + plugins, directories)
    qt_names = {path.name.lower(): path.name for path in (qt / "bin").glob("*.dll")}
    imports = imported_symbols(programs + plugins + list(dependencies.values()))
    if any(name.startswith(("msvcp140", "vcruntime140", "concrt140")) and name not in dependencies for name in imports):
        raise RuntimeError("VSEdit requires the app-local x64 MSVC runtime")
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
        target = payload / path.relative_to(qt / "plugins")
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
