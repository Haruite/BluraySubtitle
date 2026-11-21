"""Build the Windows x64 package for Windows 7 SP1 and newer."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from xml.etree import ElementTree
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_vsedit_windows as vsedit
from tools.build_mkvtoolnix_windows import MSYS2_REQUIRED
from tools.windows_build_cache import files_under, publish, restore
from tools.windows_native_tools import (
    VSEDIT_PLUGINS, VSEDIT_PROGRAMS, VSEDIT_QT_LIBRARIES, VSEDIT_WIN7_RECIPE, build_record, fetch_verified,
    file_hash, fingerprint, msvc_environment, record_build,
)


PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = "BluraySubtitle_windows_x64_compat"
GITHUB_TOKEN = os.environ.get("BLURAYSUBTITLE_GITHUB_TOKEN", "")
QT_VERSION = "6.8.5"
QT_SDK_VERSION = "6.8.3"
QT_ASSET = "qt6_x64_to_run_on_windows7.7z"
R79_SHA256 = "ba67823944227e3f52cd0faff9d2dd88ea7f23587bffcd9a331cf3140dea90c3"
ZSMOOTH_VERSION = "0.20.0"
ZSMOOTH_SHA256 = "1e9752398082c51c7d73f6d89a155fc5e60294691e12771bb09cffd0b3d7ec6c"
QTBASE_SHA256 = "cea5c8f2c20d9cbd684f8a402721e63b87a2886e906f6ec7e0f7e1ff69c83206"
QT_BACKPORT_SHA256 = "a81615e8a65ecf39f5905dc926a7fddbda44c210de3c359b2c3e2606234a1a3f"
R79_DEPENDENCIES = {
    "libp2p": "869fa993041f9f3af7d9ac8b10158920c6ddce66",
    "zimg": "e2e43d09afa50d1fbad391a7a61e789b1f036854",
    "graphengine": "91c6af4c795c5396d8b974f24b4d2e2ecca04e2d",
}
OMITTED_PLUGINS = {
    "placebo": "The upstream build imports WaitOnAddress and ProcessPrng, which Windows 7 lacks.",
}


class Msys2Required(Exception):
    """Resume the compatibility build after setup prepares the standard toolchain."""


@contextmanager
def component_payload(work: Path, component: str, *inputs):
    key = fingerprint(*inputs)
    archive = work / "cache" / f"{component}.zip"
    with tempfile.TemporaryDirectory(dir=work, prefix=f"{component}-") as temporary:
        payload = Path(temporary) / "payload"
        cached = bool(restore(archive, key, payload))
        if cached:
            print(f"Restored the Windows compatibility build cache for {component}.", flush=True)
        yield payload, cached, key
        if not cached:
            publish(archive, key, files_under(payload))


def github_release(repository: str, tag: str = "") -> dict:
    endpoint = f"tags/{tag}" if tag else "latest"
    request = urllib.request.Request(f"https://api.github.com/repos/{repository}/releases/{endpoint}")
    if GITHUB_TOKEN:
        request.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def github_asset(release: dict, name: str, downloads: Path) -> Path:
    (asset,) = [item for item in release["assets"] if item["name"] == name]
    algorithm, _, digest = asset["digest"].partition(":")
    if algorithm != "sha256" or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError(f"Expected a SHA-256 checksum for {name}")
    return fetch_verified(asset["browser_download_url"], downloads / name, digest)


def prepare_python(work: Path) -> Path:
    release = github_release("adang1345/PythonVista")
    version = release["tag_name"].removeprefix("v")
    if not re.fullmatch(r"3\.\d+\.\d+", version):
        raise ValueError(f"Unexpected PythonVista release: {version}")
    archive = github_asset(release, f"python.{version}.nupkg", work / "downloads")
    installation = work / f"pythonvista-{version}"
    python = installation / "tools/python.exe"
    if not python.is_file():
        with zipfile.ZipFile(archive) as package:
            package.extractall(installation)
    if not (python.parent / "Lib/site-packages/pip").is_dir():
        subprocess.run([python, "-I", "-m", "ensurepip", "--upgrade"], check=True)
    pip(python, "install", "--only-binary=:all:", "pefile")
    return python


def pip(python: Path, *arguments: str | Path) -> None:
    subprocess.run([python, "-I", "-m", "pip", "--disable-pip-version-check", *arguments], check=True)


def source_zip(repository: str, ref: str, work: Path, digest: str) -> Path:
    name = f"{repository.rsplit('/', 1)[-1]}-{ref.removeprefix('v')}"
    source = work / "deps" / name
    if not source.is_dir():
        archive = fetch_verified(f"https://codeload.github.com/{repository}/zip/refs/tags/{ref}",
                                 work / "downloads" / (source.name + ".zip"), digest)
        with zipfile.ZipFile(archive) as package:
            package.extractall(source.parent)
    return source


def checkout_release(repository: str, destination: Path, ref: str) -> Path:
    if not re.fullmatch(r"[\w.-]+", ref, re.ASCII) or ref.startswith("-"):
        raise ValueError(f"Unexpected release tag for {repository}: {ref}")
    if destination.is_dir():
        current = subprocess.check_output(["git", "-C", destination, "describe", "--tags", "--exact-match"], text=True).strip()
        if current == ref:
            return destination
    source = destination.with_name(f"{destination.name}-{ref}")
    if not source.is_dir():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", "--branch", ref, "https://github.com/" + repository, source], check=True)
    return source


def extract_revision(repository: str, revision: str, destination: Path, downloads: Path) -> None:
    url = f"https://codeload.github.com/{repository}/tar.gz/{revision}"
    name = f"{repository.rsplit('/', 1)[-1]}-{revision}"
    directory = destination.parent / name
    source = downloads / (name + ".tar.gz")
    if not source.is_file():
        download_source(url, source)
    with tarfile.open(source) as archive:
        archive.extractall(destination.parent, filter="data")
    shutil.copytree(directory, destination, dirs_exist_ok=True)


def download_source(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".part", delete=False) as output:
        partial = Path(output.name)
    try:
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def prepare_qt(work: Path, python: Path, seven_zip: Path) -> None:
    # This PyQt6 series uses the Qt 6.8 ABI. Install its bindings without the stock Qt wheel.
    pip(python, "install", "--only-binary=:all:", "PyQt6-sip", "PyInstaller", "Pillow",
        "numpy", "SoundFile", "pycountry")
    pip(python, "install", "--only-binary=:all:", "--no-deps", "PyQt6==6.8.1")
    release = github_release("crystalidea/qt6windows7", f"v{QT_VERSION}")
    archive = github_asset(release, QT_ASSET, work / "downloads" / f"qt-{QT_VERSION}")
    extracted = work / f"qt-{QT_VERSION}"
    subprocess.run([seven_zip, "x", archive, "-o" + str(extracted), "-y", "-bso0", "-bsp0"], check=True)
    (core,) = extracted.rglob("Qt6Core.dll")
    runtime = python.parent / "Lib/site-packages/PyQt6/Qt6"
    runtime.mkdir(parents=True, exist_ok=True)
    binaries = runtime / "bin"
    binaries.mkdir(exist_ok=True)
    for path in core.parent.glob("*.dll"):
        shutil.copy2(path, binaries / path.name)
    for path in core.parent.iterdir():
        if path.is_dir():
            shutil.copytree(path, runtime / "plugins" / path.name, dirs_exist_ok=True)
    # Qt's release archive omits translations, which are compatible across Qt 6.8 patch releases.
    sdk = work / f"qt-sdk-msvc-{QT_SDK_VERSION}"
    vsedit.prepare_qt_sdk(QT_SDK_VERSION, work / "downloads" / sdk.name, sdk, str(seven_zip),
                         modules=("qttranslations",))
    translations = runtime / "translations"
    translations.mkdir(exist_ok=True)
    for file in (sdk / "translations").glob("*.qm"):
        if file.name in {"qt_en.qm", "qtbase_en.qm", "qt_zh_CN.qm", "qtbase_zh_CN.qm"}:
            shutil.copy2(file, translations)
    subprocess.run([python, "-I", "-c", "from PyQt6.QtCore import qVersion; print(qVersion())"], check=True)


def compile_vapoursynth(work: Path, python: Path, msys2: Path, jobs: int, payload: Path, python_tag: str) -> None:
    source = source_zip("vapoursynth/vapoursynth", "R79", work, R79_SHA256)
    subprojects = source / "subprojects"
    downloads = work / "downloads"
    for name in ("libp2p", "zimg"):
        destination = subprojects / name
        if not (destination / "meson.build").is_file():
            extract_revision(f"sekrit-twc/{name}", R79_DEPENDENCIES[name], destination, downloads)
            shutil.copytree(subprojects / "packagefiles" / name, destination, dirs_exist_ok=True)
    graphengine = subprojects / "zimg/graphengine"
    if not (graphengine / "COPYING").is_file():
        extract_revision("sekrit-twc/graphengine", R79_DEPENDENCIES["graphengine"], graphengine, downloads)
    # Fused filters can share output rows with another node, but still need their own context and cursor.
    graph = graphengine / "graphengine/graph.cpp"
    text = graph.read_text(encoding="utf-8")
    old = "if (!live_rows)\n\t\t\t\tcontinue;\n\n\t\t\tfor (unsigned p = 0; p < node->num_planes(); ++p)"
    new = "for (unsigned p = 0; live_rows && p < node->num_planes(); ++p)"
    if old in text:
        graph.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    elif new not in text:
        raise RuntimeError("Missing zimg graphengine row-cache sizing loop")
    adapter = "src/common/windows_compat_createfile.c"
    shutil.copy2(PROJECT / "tools/windows_compat_createfile.c", source / adapter)
    meson = source / "meson.build"
    text = meson.read_text(encoding="utf-8")
    if adapter not in text:
        for existing in ("src/core/cpufeatures.cpp", "src/vsscript/vsscript.cpp"):
            marker = f"'{existing}'"
            if marker not in text:
                raise RuntimeError(f"R79 build input is missing: {existing}")
            text = text.replace(marker, f"'{adapter}', {marker}", 1)
        meson.write_text(text, encoding="utf-8", newline="\n")
    pip(python, "install", "--only-binary=:all:", "Cython>=3.1", "meson", "meson-python")
    environment = {key.upper(): value for key, value in msvc_environment().items()}
    environment["PATH"] = os.pathsep.join((str(python.parent), str(python.parent / "Scripts"), str(msys2 / "ucrt64/bin"),
                                           environment["PATH"]))
    environment["CC"] = environment["CXX"] = "cl.exe"
    environment["CFLAGS"] = environment["CXXFLAGS"] = "/DWINVER=0x0601 /D_WIN32_WINNT=0x0601"
    # The MSYS2 pkg-config describes its own MinGW Python, which cannot link into MSVC modules.
    environment["PKG_CONFIG_LIBDIR"] = str(work / "empty-pkgconfig")
    subprocess.run([python, "-I", "-m", "pip", "wheel", "--no-build-isolation", "--no-deps",
                    "-Csetup-args=-Db_lto=false", "-Csetup-args=--force-fallback-for=zimg,libp2p",
                    "-Csetup-args=--wrap-mode=nodownload",
                    f"-Cbuild-dir={work / 'vapoursynth-build' / python_tag}",
                    f"-Ccompile-args=-j{jobs}", "-w", payload, source], env=environment, check=True)
    licenses = payload / "licenses"
    licenses.mkdir()
    for label, license_path in (("VapourSynth", "COPYING.LESSER"), ("libp2p", "subprojects/libp2p/COPYING"),
                                ("zimg", "subprojects/zimg/COPYING"), ("graphengine", "subprojects/zimg/graphengine/COPYING")):
        shutil.copy2(source / license_path, licenses / f"{label}-COPYING")


def build_vapoursynth(work: Path, python: Path, msys2: Path, jobs: int, *, defer_msys2: bool) -> None:
    python_tag = subprocess.check_output([python, "-I", "-c", "import sys; print(sys.implementation.cache_tag)"], text=True).strip()
    with component_payload(work, "vapoursynth-r79", "win7-r79-2", python_tag, R79_SHA256, R79_DEPENDENCIES,
                           file_hash(PROJECT / "tools/windows_compat_createfile.c")) as (payload, cached, _):
        if not cached:
            if defer_msys2:
                raise Msys2Required
            compile_vapoursynth(work, python, msys2, jobs, payload, python_tag)
        (wheel,) = payload.glob("vapoursynth-79-*-win_amd64.whl")
        pip(python, "install", "--no-deps", "--force-reinstall", wheel)
        shutil.copytree(payload / "licenses", work / "vapoursynth/licenses", dirs_exist_ok=True)


def compile_zsmooth(work: Path, jobs: int, payload: Path) -> None:
    source = source_zip("adworacz/zsmooth", ZSMOOTH_VERSION, work, ZSMOOTH_SHA256)
    manifest = source / "build.zig.zon"
    version = re.search(r'\.minimum_zig_version\s*=\s*"([\d.]+)"', manifest.read_text(encoding="utf-8"))[1]
    with urllib.request.urlopen("https://ziglang.org/download/index.json", timeout=60) as response:
        release = json.load(response)[version]["x86_64-windows"]
    archive = fetch_verified(release["tarball"], work / "downloads" / f"zig-{version}.zip", release["shasum"])
    zig_directory = work / "zig"
    zig = zig_directory / f"zig-x86_64-windows-{version}/zig.exe"
    if not zig.is_file():
        with zipfile.ZipFile(archive) as package:
            package.extractall(zig_directory)
    dependencies = re.compile(
        r'\.url = "git\+https://github\.com/([^/]+/[^/]+?)\.git(?:\?[^"#]*)?#([0-9a-f]{40})",\s*\.hash = "[^"]+",'
    )

    def vendor(match: re.Match) -> str:
        repository, commit = match.groups()
        name = repository.rsplit("/", 1)[-1]
        relative = Path("dependencies") / f"{name}-{commit}"
        if not (source / relative).is_dir():
            extract_revision(repository, commit, source / relative, work / "downloads")
        return f'.path = "{relative.as_posix()}",'

    manifest.write_text(dependencies.sub(vendor, manifest.read_text(encoding="utf-8")), encoding="utf-8", newline="\r\n")
    (fftw,) = (source / "dependencies").glob("fftw-*/build.zig.zon")
    fftw_source = fftw.read_text(encoding="utf-8")
    archive_fields = re.search(r'\.url = "(https://www\.fftw\.org/[^"\s]+)"\s*,\s*\.hash = "([^"]+)"', fftw_source)
    if archive_fields:
        url, digest = archive_fields.groups()
        fftw_archive = work / "downloads" / url.rsplit("/", 1)[-1]
        if not fftw_archive.is_file():
            download_source(url, fftw_archive)
        if subprocess.check_output([zig, "fetch", fftw_archive], text=True).strip() != digest:
            raise ValueError(f"Zig dependency checksum mismatch: {fftw_archive.name}")
        with tarfile.open(fftw_archive) as archive:
            archive.extractall(fftw.parent, filter="data")
        fftw.write_text(fftw_source.replace(archive_fields[0], f'.path = "{fftw_archive.name.removesuffix(".tar.gz")}"'),
                        encoding="utf-8", newline="\r\n")
    subprocess.run([zig, "build", f"-j{jobs}", "-Doptimize=ReleaseFast", "-Dtarget=x86_64-windows.win7-gnu",
                    "-Dcpu=baseline", "--prefix", payload], cwd=source, check=True)
    licenses = payload / "licenses"
    licenses.mkdir()
    (fftw_license,) = source.glob("dependencies/fftw-*/fftw-*/COPYING")
    (binding_license,) = source.glob("dependencies/vapoursynth-zig-*/LICENSE")
    for name, source_license in (("LICENSE", source / "LICENSE"), ("FFTW-COPYING", fftw_license),
                                 ("VapourSynth-Zig-LICENSE", binding_license)):
        shutil.copy2(source_license, licenses / name)


def build_zsmooth(work: Path, jobs: int) -> None:
    with component_payload(work, "zsmooth", "win7-baseline-1", ZSMOOTH_SHA256) as (payload, cached, _):
        if not cached:
            compile_zsmooth(work, jobs, payload)
        shutil.copytree(payload, work / "zsmooth", dirs_exist_ok=True)


def build_mkvtoolnix(work: Path, msys2: Path, seven_zip: Path, jobs: int, *, defer_msys2: bool) -> None:
    sdk = work / f"qt-sdk-mingw-{QT_SDK_VERSION}"
    source = work / "deps" / f"qtbase-{QT_SDK_VERSION}"
    upstream = "https://mkvtoolnix.download"
    with urllib.request.urlopen(f"{upstream}/latest-release.xml", timeout=60) as response:
        version = ElementTree.parse(response).findtext("latest-source/version")
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version or ""):
        raise ValueError(f"Unexpected MKVToolNix release: {version}")
    name = f"mkvtoolnix-{version}.tar.xz"
    url = f"{upstream}/sources/{name}"
    with urllib.request.urlopen(url + ".sha256", timeout=60) as response:
        digest, filename = response.read().decode("ascii").split()
    if filename != name:
        raise ValueError(f"Unexpected MKVToolNix source checksum: {filename}")
    # Icon generation uses Pillow and QtSvg from the host Python prepared by setup.
    command = [sys.executable, PROJECT / "tools/build_mkvtoolnix_windows.py", "install", work / "mkvtoolnix",
               "--version", version, "--source", url, "--sha256", digest.lower(), "--cache", work / "cache",
               "--work", work / "mkv-build", "--msys2-root", msys2, "--jobs", str(jobs),
               "--qt-win7-source", source, "--qt-win7-sdk", sdk]
    result = subprocess.run([*command, "--defer-msys2"])
    if result.returncode != MSYS2_REQUIRED:
        result.check_returncode()
        return
    if defer_msys2:
        raise Msys2Required

    if not (sdk / "bin/qmake.exe").is_file():
        vsedit.prepare_qt_sdk(QT_SDK_VERSION, work / "downloads" / sdk.name, sdk, str(seven_zip),
                             mingw=True, modules=("qtbase",))
    ref = f"v{QT_SDK_VERSION}"
    if not (source / "CMakeLists.txt").is_file():
        archive = fetch_verified(f"https://codeload.github.com/qt/qtbase/tar.gz/refs/tags/{ref}",
                                 work / "downloads" / (source.name + ".tar.gz"), QTBASE_SHA256)
        with tarfile.open(archive) as package:
            package.extractall(source.parent, members=(member for member in package if member.isfile() or member.isdir()),
                               filter="data")
    overlay = source_zip("crystalidea/qt6windows7", ref, work, QT_BACKPORT_SHA256)
    shutil.copytree(overlay / "qtbase", source, dirs_exist_ok=True)
    # FILE_ID_INFO is hidden by MinGW headers when targeting Windows 7. The handle query
    # already falls back to BY_HANDLE_FILE_INFORMATION when FileIdInfo is unsupported.
    filesystem = source / "src/corelib/io/qfilesystemengine_win.cpp"
    text = filesystem.read_text(encoding="utf-8")
    text = text.replace("    FILE_ID_INFO infoEx;", "    struct { quint64 VolumeSerialNumber; quint8 FileId[16]; } infoEx;")
    filesystem.write_text(text.replace("&infoEx, sizeof(FILE_ID_INFO)", "&infoEx, sizeof(infoEx)"),
                          encoding="utf-8", newline="\n")
    subprocess.run(command, check=True)


def build_vsedit(work: Path, python: Path, seven_zip: Path, jobs: int) -> None:
    sdk = work / f"qt-sdk-msvc-{QT_SDK_VERSION}"
    qt = python.parent / "Lib/site-packages/PyQt6/Qt6"
    repository = "YomikoR/VapourSynth-Editor"
    ref = github_release(repository)["tag_name"]
    websocket = "Qt6WebSockets.dll"
    runtime = [qt / "bin" / name for name in VSEDIT_QT_LIBRARIES if name != websocket]
    runtime.extend(qt / "plugins" / name for name in VSEDIT_PLUGINS)
    qt_hashes = {path.name: file_hash(path) for path in runtime}
    with component_payload(work, "vsedit", VSEDIT_WIN7_RECIPE, ref, QT_SDK_VERSION, QT_VERSION,
                           qt_hashes, R79_SHA256, vsedit.JOM_SHA256) as (payload, cached, key):
        if not cached:
            if not (sdk / "bin" / websocket).is_file():
                vsedit.prepare_qt_sdk(QT_SDK_VERSION, work / "downloads" / sdk.name, sdk, str(seven_zip))
            # WebSockets uses the stable Qt 6.8 ABI of the patched QtBase and Multimedia libraries.
            shutil.copy2(sdk / "bin" / websocket, qt / "bin")
            source = checkout_release(repository, work / "deps/vsedit", ref)
            include = source_zip("vapoursynth/vapoursynth", "R79", work, R79_SHA256) / "include"
            jom_archive = fetch_verified(vsedit.JOM_URL, work / "downloads/jom.zip", vsedit.JOM_SHA256)
            jom = work / "jom/jom.exe"
            if not jom.is_file():
                vsedit.unpack(jom_archive, jom.parent, str(seven_zip))
            environment = msvc_environment()
            programs = vsedit.build_programs(source, sdk, jom, include, environment, jobs, QT_SDK_VERSION, win7=True)
            vsedit.stage_editor(source, programs, payload, qt, environment)
            for name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt"):
                url = f"https://raw.githubusercontent.com/qt/qtbase/v{QT_SDK_VERSION}/LICENSES/{name}"
                license_file = work / "downloads" / f"qt-{QT_SDK_VERSION}-licenses" / name
                if not license_file.is_file():
                    download_source(url, license_file)
                shutil.copy2(license_file, payload / "licenses/Qt" / name)
            record_build(payload, "vsedit", VSEDIT_WIN7_RECIPE, ref, key, VSEDIT_PROGRAMS, qt_version=QT_VERSION)
        vsedit.verify_editor(payload, "vsedit.exe", ref)
        shutil.copy2(payload / websocket, qt / "bin")
        shutil.copytree(payload, work / "vsedit", dirs_exist_ok=True)


def rust_has_source(rustup: Path, environment: dict[str, str]) -> bool:
    result = subprocess.run([rustup, "run", "nightly", "rustc", "--print", "sysroot"],
                            env=environment, capture_output=True, text=True)
    return result.returncode == 0 and (Path(result.stdout.strip()) / "lib/rustlib/src/rust/library/std/Cargo.toml").is_file()


def prepare_rust(work: Path) -> tuple[Path, dict[str, str]]:
    environment = {key.upper(): value for key, value in msvc_environment().items()}
    cargo_home = work / "rust-cargo"
    installed = shutil.which("rustup.exe", path=environment["PATH"])
    environment.update(CARGO_HOME=str(cargo_home), CARGO_TARGET_DIR=str(work / "rust-build"))
    if installed and rust_has_source(Path(installed), environment):
        return Path(installed), environment

    environment["RUSTUP_HOME"] = str(work / "rust-toolchains")
    rustup = cargo_home / "bin/rustup.exe"
    if not rustup.is_file() and installed:
        rustup = Path(installed)
    if not rustup.is_file():
        url = "https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe"
        with urllib.request.urlopen(url + ".sha256", timeout=60) as response:
            digest = response.read().decode("ascii").split()[0]
        installer = fetch_verified(url, work / "downloads/rustup-init.exe", digest)
        subprocess.run([installer, "-y", "--no-modify-path", "--default-toolchain", "none"], env=environment, check=True)
    if not rust_has_source(rustup, environment):
        subprocess.run([rustup, "toolchain", "install", "nightly", "--profile", "minimal", "--component", "rust-src"],
                       env=environment, check=True)
    return rustup, environment


def build_rust_tools(work: Path, jobs: int) -> None:
    # This target selects the Win7 standard library and the legacy getrandom backend.
    target = "x86_64-win7-windows-msvc"
    output = work / "rust-tools"
    output.mkdir(exist_ok=True)
    toolchain = None
    for tool in ("dovi_tool", "hdr10plus_tool"):
        repository = f"quietvoid/{tool}"
        ref = github_release(repository)["tag_name"]
        binary = tool + ".exe"
        with component_payload(work, tool, "rust-build-std-1", target, ref) as (payload, cached, _):
            if not cached:
                if toolchain is None:
                    toolchain = prepare_rust(work)
                rustup, environment = toolchain
                source = checkout_release(repository, work / "deps" / tool, ref)
                subprocess.run([rustup, "run", "nightly", "cargo", "build", "--locked", "--release", "--target", target,
                                "-Zbuild-std", "--bin", tool, "-j", str(jobs)], cwd=source, env=environment, check=True)
                payload.mkdir()
                shutil.copy2(work / "rust-build" / target / "release" / binary, payload)
            shutil.copy2(payload / binary, output)


def stage_vapoursynth(work: Path, python: Path) -> None:
    settings = runpy.run_path(str(PROJECT / "src/core/settings.py"))
    installed = Path(settings["VSPIPE_PATH"]).parent
    state = json.loads((installed / "vapoursynth-components.json").read_text(encoding="utf-8"))
    plugins = {key: component for key, component in state["components"].items()
               if key not in (*OMITTED_PLUGINS, "zsmooth", "vsedit")}
    runtime = work / "vapoursynth"
    runtime.mkdir(exist_ok=True)
    package = python.parent / "Lib/site-packages/vapoursynth"
    shutil.copy2(package / "vspipe.exe", runtime)
    cache_tag = subprocess.check_output([python, "-I", "-c", "import sys; print(sys.implementation.cache_tag)"], text=True).strip()
    build = {"version": "79", "python_tag": cache_tag, "package": str(package)}
    (runtime / "vapoursynth-build.json").write_text(json.dumps(build), encoding="utf-8", newline="\r\n")

    dependencies = {name: state["dependencies"][name] for component in plugins.values() for name in component["dependencies"]}
    for name in dependencies.keys() | {name for component in plugins.values() for name in component["files"]}:
        destination = runtime / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(installed / name, destination)

    plugin = "vapoursynth64/plugins/zsmooth.dll"
    license_dir = Path("licenses/components/zsmooth")
    (binary,) = (path for path in (work / "zsmooth").rglob("*.dll") if path.name in ("zsmooth.dll", "libzsmooth.dll"))
    shutil.copy2(binary, runtime / plugin)
    shutil.copytree(work / "zsmooth/licenses", runtime / license_dir, dirs_exist_ok=True)
    plugins["zsmooth"] = {
        "name": "zsmooth", "ref": ZSMOOTH_VERSION, "method": "source",
        "source_url": f"https://github.com/adworacz/zsmooth/tree/{ZSMOOTH_VERSION}",
        "plugin": plugin, "dependencies": [], "cpu": "x86_64 baseline",
        "files": {path.relative_to(runtime).as_posix(): file_hash(path)
                  for path in (runtime / plugin, *(runtime / license_dir).iterdir())},
    }
    editor = build_record(work / "vsedit", "vsedit", compatibility=True)
    if not editor:
        raise RuntimeError("A source-built compatible VSEdit is required")
    plugins["vsedit"] = {
        "ref": editor["version"], "entrypoint": "../vsedit/vsedit.exe", "recipe": editor["recipe"],
        "qt_version": QT_VERSION, "qt_source_url": "https://github.com/crystalidea/qt6windows7", "files": {},
    }
    (runtime / "vapoursynth-components.json").write_text(
        json.dumps({"schema": 1, "components": plugins, "dependencies": dependencies}, indent=2),
        encoding="utf-8", newline="\r\n",
    )


def package(work: Path, python: Path, seven_zip: Path, dist: Path) -> Path:
    stage_vapoursynth(work, python)
    (work / "compatibility-components.json").write_text(
        json.dumps({"minimum_windows": "6.1.7601", "omitted_components": OMITTED_PLUGINS | {
            "mkvtoolnix-dvd-chapters": "libdvdread depends on libdvdcss, which imports CreateFile2.",
        }}, indent=2),
        encoding="utf-8", newline="\r\n",
    )
    environment = dict(os.environ, BLURAYSUBTITLE_WINDOWS_COMPAT_ROOT=str(work),
                       PYINSTALLER_CONFIG_DIR=str(work / "pyinstaller-cache"), PYTHONUTF8="1")
    dist.mkdir(parents=True, exist_ok=True)
    destination = dist / f"{PACKAGE}.7z"
    with tempfile.TemporaryDirectory(dir=dist, prefix="compat-") as temporary:
        output = Path(temporary)
        subprocess.run([python, "-I", "-m", "PyInstaller", "--clean", "--noconfirm", "--distpath", output,
                        "--workpath", work / "pyinstaller", PROJECT / f"{PACKAGE}.spec"],
                       cwd=PROJECT, env=environment, check=True)
        archive = output / destination.name
        subprocess.run([seven_zip, "a", "-t7z", "-mx=9", "-md=64m", "-mmt=4", archive, PACKAGE], cwd=output, check=True)
        subprocess.run([seven_zip, "t", archive], check=True)
        subprocess.run([python, PROJECT / "tools/verify_windows_package.py", archive, "--seven-zip", seven_zip], check=True)
        archive.replace(destination)
    return destination


def main() -> int:
    os.environ.pop("BLURAYSUBTITLE_GITHUB_TOKEN", None)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=PROJECT / "build/windows-compat")
    parser.add_argument("--seven-zip", type=Path, default=Path(os.environ["ProgramFiles"]) / "7-Zip/7z.exe")
    parser.add_argument("--msys2-root", type=Path, default=Path("C:/msys64"))
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 1, 8))
    parser.add_argument("--dist-dir", type=Path, default=PROJECT / "dist")
    parser.add_argument("--component", choices=("python-qt", "vapoursynth", "zsmooth", "mkvtoolnix", "vsedit", "rust-tools", "package"))
    parser.add_argument("--defer-msys2", action="store_true", help="return 75 if an MSYS2 build is required")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    python = prepare_python(work) if args.component not in ("mkvtoolnix", "zsmooth", "rust-tools") else None
    try:
        if args.component in (None, "vapoursynth"):
            build_vapoursynth(work, python, args.msys2_root, args.jobs, defer_msys2=args.defer_msys2)
        if args.component in (None, "mkvtoolnix"):
            build_mkvtoolnix(work, args.msys2_root, args.seven_zip, args.jobs, defer_msys2=args.defer_msys2)
    except Msys2Required:
        return MSYS2_REQUIRED
    if args.component in (None, "python-qt"):
        prepare_qt(work, python, args.seven_zip)
    if args.component in (None, "zsmooth"):
        build_zsmooth(work, args.jobs)
    if args.component in (None, "vsedit"):
        build_vsedit(work, python, args.seven_zip, args.jobs)
    if args.component in (None, "rust-tools"):
        build_rust_tools(work, args.jobs)
    if args.component in (None, "package"):
        print(package(work, python, args.seven_zip, args.dist_dir.resolve()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
