"""Collect the shared Python and native tools for the Ubuntu PyInstaller bundle."""

from __future__ import annotations

import argparse
import filecmp
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import sysconfig
import zipfile

import numpy
import soundfile
import vapoursynth
from PyInstaller import __version__ as PYINSTALLER_VERSION
from PyQt6 import QtCore
from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QLibraryInfo

from update_third_party_notices import generate_ubuntu_third_party_notices
from vapoursynth_plugin_versions import fallback_version


ROOT = Path(__file__).resolve().parents[1]
TOOL_SETTINGS = {
    "7zz": "SEVEN_ZIP_PATH",
    "flac": "FLAC_PATH",
    "ffmpeg": "FFMPEG_PATH",
    "ffprobe": "FFPROBE_PATH",
    "x264": "X264_PATH",
    "x265": "X265_PATH",
    "SvtAv1EncApp": "SVT_AV1_PATH",
    "fdkaac": "FDK_AAC_PATH",
    "dovi_tool": "DOVI_TOOL_PATH",
    "hdr10plus_tool": "HDR10PLUS_TOOL_PATH",
    "tsMuxeR": "TS_MUXER_PATH",
}
PLUGIN_PROJECTS = {
    "bm3d.so": ("BM3D", "HomeOfVapourSynthEvolution/VapourSynth-BM3D"),
    "eedi3m.so": ("EEDI3m", "HomeOfVapourSynthEvolution/VapourSynth-EEDI3"),
    "libaddgrain.so": ("AddGrain", "HomeOfVapourSynthEvolution/VapourSynth-AddGrain"),
    "libassrender.so": ("ASSRender", "AmusementClub/assrender"),
    "libbilateral.so": ("Bilateral", "HomeOfVapourSynthEvolution/VapourSynth-Bilateral"),
    "libccd.so": ("CCD", "End-of-Eternity/vs-ccd"),
    "libdescale.so": ("Descale", "AmusementClub/descale"),
    "libdfttest.so": ("DFTTest", "HomeOfVapourSynthEvolution/VapourSynth-DFTTest"),
    "libeedi2.so": ("EEDI2", "HomeOfVapourSynthEvolution/VapourSynth-EEDI2"),
    "libeedi3.so": ("EEDI3", "AmusementClub/vapoursynth-classic"),
    "libfmtconv.so": ("fmtconv", "EleonoreMizo/fmtconv"),
    "libmiscfilters.so": ("MiscFilters", "AmusementClub/vapoursynth-classic"),
    "libremovegrain.so": ("RemoveGrain", "vapoursynth/vs-removegrain"),
    "librife_linux_x86-64.so": ("RIFE", "styler00dollar/VapourSynth-RIFE-ncnn-Vulkan"),
    "libsangnommod.so": ("SangNomMod", "HomeOfVapourSynthEvolution/VapourSynth-SangNomMod"),
    "libvivtc.so": ("VIVTC", "vapoursynth/vivtc"),
    "libvs_placebo.so": ("vs-placebo", "Lypheo/vs-placebo"),
    "libvslsmashsource.so": ("LSMASHSource", "HomeOfAviSynthPlusEvolution/L-SMASH-Works"),
    "libvsnlm_ispc.so": ("vs-nlm-ispc", "AmusementClub/vs-nlm-ispc"),
    "libzsmooth.x86_64-gnu.so": ("zsmooth", "adworacz/zsmooth"),
    "mvtools.so": ("MVTools", "dubhatervapoursynth/vapoursynth-mvtools"),
    "znedi3.so": ("ZNEDI3", "vapoursynth/znedi3-pypi"),
}

SYSTEM_LIBRARY = re.compile(
    r"^(?:ld-linux-.+|lib(?:c|m|mvec|pthread|rt|dl|resolv|util|anl|nss_\w+|"
    r"GL|GLX|GLdispatch|EGL|OpenGL|vulkan|drm(?:_\w+)?|va(?:-\w+)?|vdpau)\.so)(?:\.\d+)*$"
)
DEPENDENCY = re.compile(r"^\s*(\S+) => (.+) \(0x[0-9a-f]+\)$")
QT_PLUGINS = (
    "platforms/libqxcb.so",
    "platforms/libqwayland.so",
    "platforms/libqoffscreen.so",
    "imageformats/libqjpeg.so",
    "imageformats/libqsvg.so",
    "wayland-shell-integration/libxdg-shell.so",
    "wayland-graphics-integration-client/libqt-plugin-wayland-egl.so",
)
STDLIB_EXCLUDES = {
    "site-packages", "dist-packages", "__pycache__", "test", "tests", "idlelib",
    "tkinter", "turtledemo", "ensurepip", "venv",
}
NUMPY_EXCLUDES = (".pyi", ".h", ".hpp", ".c", ".cpp", ".pxd", ".pyx", ".rst")


def dependency_paths(files: list[Path], used_paths: set[Path]) -> dict[str, Path]:
    libraries: dict[str, Path] = {}
    environment = {**os.environ, "LC_ALL": "C"}
    environment.pop("LD_LIBRARY_PATH", None)
    for file in files:
        result = subprocess.run(["ldd", file], env=environment, text=True, capture_output=True)
        output = result.stdout + result.stderr
        if result.returncode and not any(
            phrase in output for phrase in ("not a dynamic executable", "statically linked")
        ):
            raise RuntimeError(f"ldd failed for {file}: {output.strip()}")
        for line in output.splitlines():
            if "=> not found" in line:
                raise RuntimeError(f"Missing dependency for {file}: {line.strip()}")
            match = DEPENDENCY.fullmatch(line)
            if not match:
                continue
            name, target = match.groups()
            used_paths.add(Path(target))
            if SYSTEM_LIBRARY.fullmatch(name):
                continue
            library = Path(target).resolve(strict=True)
            previous = libraries.setdefault(name, library)
            if previous != library:
                raise RuntimeError(f"Conflicting versions of {name}: {previous}, {library}")
    return libraries


def stage_python(support: Path, native: Path, stdlib: Path, extensions: list[Path]) -> None:
    python = native / "python"
    dynload = python / "lib/python3.14/lib-dynload"
    dynload.mkdir(parents=True)
    (python / "bin").mkdir()
    with zipfile.ZipFile(python / "lib/python314.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for directory, folders, files in os.walk(stdlib):
            folders[:] = sorted(set(folders) - STDLIB_EXCLUDES)
            for name in sorted(files):
                if name.endswith(".py"):
                    file = Path(directory) / name
                    archive.write(file, file.relative_to(stdlib))
    for module in extensions:
        frozen = support / "python3.14/lib-dynload" / module.name
        target = dynload / module.name
        if frozen.is_file() and filecmp.cmp(module, frozen, shallow=False):
            target.symlink_to(os.path.relpath(frozen, dynload))
        else:
            shutil.copy2(module, target)
    # Ubuntu's installed python executable also embeds CPython. Link a small launcher
    # against the same libpython used by the frozen application and by VSScript.
    library = support / "libpython3.14.so.1.0"
    if not library.is_file():
        raise FileNotFoundError(library)
    subprocess.run(
        [
            "cc", "-Os", "-s", "-x", "c", "-", "-L", str(support), f"-l:{library.name}",
            "-Wl,-rpath,$ORIGIN/../../..", "-o", str(python / "bin/python3.14"),
        ],
        input="int Py_BytesMain(int, char **);\nint main(int argc, char **argv) { return Py_BytesMain(argc, argv); }\n",
        text=True,
        check=True,
    )

    # The frozen and embedded interpreters import the same NumPy sources and extensions.
    numpy_package = Path(numpy.__file__).resolve().parent
    for directory, folders, files in os.walk(numpy_package):
        folders[:] = sorted(set(folders) - {"__pycache__", "test", "tests", "_pyinstaller", "doc"})
        for name in sorted(files):
            if name.endswith(NUMPY_EXCLUDES + (".pyc",)) or "_tests." in name:
                continue
            source = Path(directory) / name
            target = support / "numpy" / source.relative_to(numpy_package)
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for pattern in ("numpy.libs", "numpy-*.dist-info"):
        for directory in numpy_package.parent.glob(pattern):
            if not (support / directory.name).exists():
                shutil.copytree(directory, support / directory.name)
    scripts = ROOT / "third_party/vapoursynth_scripts"
    for script in scripts.glob("*.py"):
        shutil.copy2(script, support / script.name)
    notices = support / "legal/vapoursynth_scripts"
    shutil.copytree(scripts / "licenses", notices / "licenses")
    for doc in scripts.glob("COPYRIGHT*.md"):
        shutil.copy2(doc, notices / doc.name)


def plugin_notice_rows(directory: Path, files: list[Path]) -> str:
    core = vapoursynth.core
    core.std.LoadAllPlugins(str(directory))
    registered = {Path(plugin.plugin_path).resolve(): plugin for plugin in core.plugins() if plugin.plugin_path}
    rows = []
    for file in files:
        plugin = registered.get(file.resolve())
        name, project = PLUGIN_PROJECTS.get(file.name, (file.stem, ""))
        release = fallback_version(file, normalize=False)
        if release is None and plugin and plugin.version.major >= 0:
            release = f"{plugin.version.major}.{plugin.version.minor}"
        version = f"`{release}`" if release else "—"
        source = f"https://github.com/{project}" if project else "—"
        rows.append(f"| {name} | {version} | `linux/plugins/{file.name}` | {source} |")
    return "\n".join(rows)



def stage(support: Path) -> None:
    settings_file = os.environ.get("BLURAY_SETTINGS_FILE") or str(ROOT / "src/core/settings.py")
    settings = runpy.run_path(settings_file)
    native = support / "linux"
    tools = {tool: Path(settings[key]) for tool, key in TOOL_SETTINGS.items()}
    mkv = Path(settings["MKVTOOLNIX_PATH"])
    tools.update({name: mkv / name for name in ("mkvinfo", "mkvmerge", "mkvpropedit", "mkvextract")})
    tools["mpv"] = Path(shutil.which("mpv") or "/usr/local/bin/mpv")
    tools["vsedit"] = Path(f'{settings["VSEDIT_PATH"]}-bin')
    installed_plugins = Path(settings["PLUGIN_PATH"])
    plugins = sorted(installed_plugins.glob("*.so"))
    if not plugins:
        raise RuntimeError(f"No VapourSynth plugins in {installed_plugins}")

    qt_root = Path(subprocess.check_output(["qtpaths6", "--plugin-dir"], text=True).strip())
    pyqt_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    if pyqt_root.resolve() != qt_root.resolve():
        raise RuntimeError("Use Ubuntu's python3-pyqt6 with the same Qt runtime as VSEdit and MKVToolNix")
    qt_sources = [qt_root / path for path in QT_PLUGINS]
    qt_destination = next((support / "PyQt6").glob("Qt*/plugins"))

    vs_wheel = Path(vapoursynth.__file__).resolve().parent
    vs_version = str(vapoursynth.__version__)
    if vs_version != "R79" or not (vs_wheel / "vspipe").is_file():
        raise RuntimeError("The Ubuntu package requires the VapourSynth R79 wheel with VSPipe")
    for metadata in vs_wheel.parent.glob("vapoursynth-*.dist-info/licenses"):
        shutil.copytree(metadata, support / "legal/vapoursynth", dirs_exist_ok=True)
    vs_binaries = sorted(vs_wheel.glob("*.so*"))
    stdlib = Path(sysconfig.get_path("stdlib"))
    extensions = [
        path for path in sorted((stdlib / "lib-dynload").glob("*.so"))
        if not path.name.startswith(("_test", "_tkinter", "_ctypes_test", "_xxtest"))
    ]
    libass = Path("/usr/lib/x86_64-linux-gnu/libass.so.9")
    binaries = [
        *tools.values(), *plugins, *qt_sources, libass, *extensions,
        vs_wheel / "vspipe", *vs_binaries,
    ]
    used_paths = set(binaries)
    dependencies = dependency_paths(binaries, used_paths)

    for name in ("bin", "libexec", "plugins"):
        (native / name).mkdir(parents=True)
    for program, source in tools.items():
        subprocess.run(["strip", "--strip-unneeded", "-o", native / "libexec" / program, source], check=True)
    for program in (*tools, "vspipe"):
        (native / "bin" / program).symlink_to("launch-tool")
    launcher = shutil.copy2(ROOT / "tools/launch_ubuntu_tool.sh", native / "bin/launch-tool")
    Path(launcher).chmod(0o755)
    shutil.copy2(ROOT / "tools/write_ubuntu_vsscript_config.py", native)

    for plugin in plugins:
        subprocess.run(["strip", "--strip-unneeded", "-o", native / "plugins" / plugin.name, plugin], check=True)
    shutil.copy2(installed_plugins / "nnedi3_weights.bin", native / "plugins")
    shutil.copytree(installed_plugins / "licenses/znedi3", support / "legal/vapoursynth/components/znedi3")
    if (installed_plugins / "models").is_dir():
        shutil.copytree(installed_plugins / "models", native / "plugins/models")
    for plugin, source in zip(QT_PLUGINS, qt_sources, strict=True):
        target = qt_destination / plugin
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (native / "qt-plugins").symlink_to(os.path.relpath(qt_destination, native), target_is_directory=True)

    sample = support / "vapoursynth"
    sample.mkdir(exist_ok=True)
    for source in (*vs_binaries, *vs_wheel.glob("*.py"), vs_wheel / "vspipe"):
        target = sample / source.name
        if not target.is_file():
            shutil.copy2(source, target)
    dependencies.setdefault("libass.so.9", libass.resolve())
    shared = 0
    private = native / "lib"
    for name, source in dependencies.items():
        if source.is_relative_to(vs_wheel):
            continue
        target = support / name
        if target.is_file():
            if filecmp.cmp(source, target, shallow=False):
                shared += 1
                continue
            # Keep differing host and wheel libraries isolated in the native tools.
            private.mkdir(exist_ok=True)
            target = private / name
        shutil.copy2(source, target)

    stage_python(support, native, stdlib, extensions)
    # Strip the staged copies after comparing them for deduplication.
    for library in support.rglob("*.so*"):
        if (library.suffix == ".so" or ".so." in library.name) and not library.is_symlink() and library.is_file():
            subprocess.run(["strip", "--strip-unneeded", library], check=True)
    generate_ubuntu_third_party_notices(
        {
            ROOT / "legal/ubuntu" / filename: support / "legal" / filename
            for filename in ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.zh-Hans.md")
        },
        {**settings, "MPV_PATH": tools["mpv"], "VSEDIT_PATH": tools["vsedit"]},
        PYINSTALLER_VERSION,
        soundfile.__libsndfile_version__,
        QT_VERSION_STR,
        PYQT_VERSION_STR,
        vs_version,
        plugin_notice_rows(installed_plugins, plugins),
    )
    if apt_paths := os.environ.get("BLURAY_APT_CACHE_PATHS"):
        used_paths.update((Path(sys.executable), stdlib / "os.py", Path(QtCore.__file__)))
        for command in ("as", "cc", "git", "ld", "pkg-config", "qtpaths6", "strip", "tar", "xz"):
            if executable := shutil.which(command):
                used_paths.add(Path(executable))
        for option in ("-print-file-name=libgcc.a", "-print-prog-name=cc1"):
            location = Path(subprocess.check_output(["cc", option], text=True).strip())
            if location.is_absolute():
                used_paths.add(location)
        with Path(apt_paths).open("a", encoding="utf-8") as stream:
            stream.writelines(f"{path}\n" for path in sorted(used_paths))
    print(f"Staged {len(tools) + 1} tools and {len(plugins)} filters with {shared} shared native libraries")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("support", type=Path, help="Path to the PyInstaller bundle's _internal directory")
    stage(parser.parse_args().support.resolve())
