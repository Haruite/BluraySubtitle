"""Collect the shared Python and native tools for the Linux PyInstaller bundle."""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import sysconfig
from urllib.parse import urljoin
import zipfile

import numpy
import soundfile
import vapoursynth
from PyInstaller import __version__ as PYINSTALLER_VERSION
from PyQt6 import QtCore
from PyQt6.QtCore import PYQT_VERSION_STR, qVersion

from linux_runtime_libs import GLIBC, HOST_DRIVER
from stage_linux_portable import dependency_paths, remove_build_rpaths, stage_glibc, stage_qt
from update_third_party_notices import generate_linux_third_party_notices
from vapoursynth_plugin_versions import fallback_version, reported_version


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.runtime.mpv_environment import native_mpv_executable
from tools.mpv.install import UOSC_BINARY, UOSC_DIR, stage_bundled_mpv
from tools.mpv.vapoursynth.rife_assets import RIFE_LIBRARY

MULTIARCH = sysconfig.get_config_var("MULTIARCH")
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
    "libfmtconv.so": ("fmtconv", "https://gitlab.com/EleonoreMizo/fmtconv"),
    "libmiscfilters.so": ("MiscFilters", "AmusementClub/vapoursynth-classic"),
    "libremovegrain.so": ("RemoveGrain", "vapoursynth/vs-removegrain"),
    RIFE_LIBRARY: ("RIFE", "styler00dollar/VapourSynth-RIFE-ncnn-Vulkan"),
    "libsangnommod.so": ("SangNomMod", "HomeOfVapourSynthEvolution/VapourSynth-SangNomMod"),
    "libvivtc.so": ("VIVTC", "vapoursynth/vivtc"),
    "libvs_placebo.so": ("vs-placebo", "Lypheo/vs-placebo"),
    "libvslsmashsource.so": ("LSMASHSource", "HomeOfAviSynthPlusEvolution/L-SMASH-Works"),
    "libvsnlm_ispc.so": ("vs-nlm-ispc", "AmusementClub/vs-nlm-ispc"),
    f"libzsmooth.{MULTIARCH.split('-', 1)[0]}-gnu.so": ("zsmooth", "adworacz/zsmooth"),
    "mvtools.so": ("MVTools", "dubhatervapoursynth/vapoursynth-mvtools"),
    "znedi3.so": ("ZNEDI3", "vapoursynth/znedi3-pypi"),
}

STDLIB_EXCLUDES = {
    "site-packages", "dist-packages", "__pycache__", "test", "tests", "idlelib",
    "tkinter", "turtledemo", "ensurepip", "venv",
}
NUMPY_EXCLUDES = (".pyi", ".h", ".hpp", ".c", ".cpp", ".pxd", ".pyx", ".rst")


def stage_python(support: Path, native: Path, stdlib: Path, extensions: list[Path]) -> None:
    python = native / "python"
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    dynload = python / "lib" / version / "lib-dynload"
    dynload.mkdir(parents=True)
    (python / "bin").mkdir()
    (python / "libexec").mkdir()
    (python / "bin/python3").symlink_to("../../bin/launch-tool")
    with zipfile.ZipFile(python / "lib" / (version.replace(".", "") + ".zip"), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for directory, folders, files in os.walk(stdlib):
            folders[:] = sorted(set(folders) - STDLIB_EXCLUDES)
            for name in sorted(files):
                if name.endswith(".py"):
                    file = Path(directory) / name
                    archive.write(file, file.relative_to(stdlib))
    for module in extensions:
        frozen = support / version / "lib-dynload" / module.name
        target = dynload / module.name
        if frozen.is_file() and filecmp.cmp(module, frozen, shallow=False):
            target.symlink_to(os.path.relpath(frozen, dynload))
        else:
            shutil.copy2(module, target)
    # The frozen GUI and VSScript embed the same uv-managed CPython library.
    library = support / sysconfig.get_config_var("INSTSONAME")
    if not library.is_file():
        raise FileNotFoundError(library)
    subprocess.run(
        [
            "cc", "-Os", "-s", "-x", "c", "-", "-L", str(support), f"-l:{library.name}",
            "-Wl,-rpath,$ORIGIN/../../..", "-o", str(python / "libexec/python3"),
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
        if release is None and plugin is not None:
            release = reported_version(plugin)
        version = f"`{release}`" if release else "—"
        source = urljoin("https://github.com/", project) if project else "—"
        rows.append(f"| {name} | {version} | `linux/plugins/{file.name}` | {source} |")
    return "\n".join(rows)


def pipewire_client_files() -> dict[Path, Path]:
    """Map the modules loaded by PipeWire's client.conf to their bundle paths."""
    system = Path("/usr/lib") / MULTIARCH
    files = {Path("/usr/share/pipewire/client.conf"): Path("client.conf")}
    modules = ("rt", "protocol-native", "client-node", "client-device", "adapter", "metadata", "session-manager")
    for name in modules:
        relative = Path("pipewire-0.3") / f"libpipewire-module-{name}.so"
        files[system / relative] = relative
    for plugin in ("audioconvert/libspa-audioconvert.so", "videoconvert/libspa-videoconvert.so",
                   "support/libspa-support.so", "support/libspa-dbus.so", "support/libspa-journal.so"):
        relative = Path("spa-0.2") / plugin
        files[system / relative] = relative
    return files


def stage(support: Path, uosc_bundle: Path) -> None:
    settings_file = os.environ.get("BLURAY_SETTINGS_FILE") or str(ROOT / "src/core/settings.py")
    settings = runpy.run_path(settings_file)
    native = support / "linux"
    tools = {tool: Path(settings[key]) for tool, key in TOOL_SETTINGS.items()}
    tools["bluraysub-gpu-capabilities"] = tools["ffmpeg"].with_name("bluraysub-gpu-capabilities")
    mkv = Path(os.environ["BLURAY_QT_TOOLS"])
    tools.update({name: mkv / name for name in ("mkvinfo", "mkvmerge", "mkvpropedit", "mkvextract")})
    tools["mpv"] = native_mpv_executable(Path(shutil.which("mpv") or "/usr/local/bin/mpv"))
    tools["vsedit"] = mkv / "vsedit"
    tools["ziggy-linux"] = uosc_bundle / UOSC_DIR / UOSC_BINARY
    installed_plugins = Path(settings["PLUGIN_PATH"])
    plugins = sorted(installed_plugins.glob("*.so"))
    if not plugins:
        raise RuntimeError(f"No VapourSynth plugins in {installed_plugins}")

    qt_tools = {n: tools[n] for n in ("vsedit", "mkvinfo", "mkvmerge", "mkvpropedit", "mkvextract")}
    vs_wheel = Path(vapoursynth.__file__).resolve().parent
    vs_version = str(vapoursynth.__version__)
    if vs_version != "R79" or not (vs_wheel / "vspipe").is_file():
        raise RuntimeError("The Linux package requires the VapourSynth R79 wheel with VSPipe")
    for metadata in vs_wheel.parent.glob("vapoursynth-*.dist-info/licenses"):
        shutil.copytree(metadata, support / "legal/vapoursynth", dirs_exist_ok=True)
    vs_binaries = sorted(vs_wheel.glob("*.so*"))
    stdlib = Path(sysconfig.get_path("stdlib"))
    shutil.copy2(stdlib / "LICENSE.txt", support / "legal/CPython-LICENSE.txt")
    extensions = [
        path for path in sorted((stdlib / "lib-dynload").glob("*.so"))
        if not path.name.startswith(("_test", "_tkinter", "_ctypes_test", "_xxtest"))
    ]
    libass = Path("/usr/lib") / MULTIARCH / "libass.so.9"
    pipewire = pipewire_client_files()
    binaries = [
        *(path for name, path in tools.items() if name not in qt_tools), *plugins, libass, *extensions,
        vs_wheel / "vspipe", *vs_binaries, *(file for file in pipewire if file.suffix == ".so"),
    ]
    used_paths = set(binaries).union(pipewire)
    dependencies = dependency_paths(binaries, used_paths, (vs_wheel,))

    for name in ("bin", "libexec", "plugins", "static"):
        (native / name).mkdir(parents=True)
    for source, relative in pipewire.items():
        target = native / "pipewire" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for program, source in tools.items():
        headers = subprocess.check_output(["readelf", "-lW", source], text=True, env=dict(os.environ, LC_ALL="C"))
        directory = "libexec" if "INTERP" in headers else "static"
        target = native / directory / program
        subprocess.run(["strip", "--strip-unneeded", "-o", target, source], check=True)
        if directory == "libexec":
            remove_build_rpaths(target)
    for program in (*tools, "vspipe"):
        (native / "bin" / program).symlink_to("launch-tool")
    launcher = shutil.copy2(ROOT / "tools/launch_linux_tool.sh", native / "bin/launch-tool")
    Path(launcher).chmod(0o755)
    shutil.copy2(ROOT / "tools/write_linux_vsscript_config.py", native)
    shutil.copy2(ROOT / "tools/linux_runtime.sh", native / "runtime.sh")

    for plugin in plugins:
        shutil.copy2(plugin, native / "plugins" / plugin.name)
    upstream_plugins = set()
    if MULTIARCH == "x86_64-linux-gnu":
        artifacts = {"libzsmooth.x86_64-gnu.so": "upstream", RIFE_LIBRARY: "upstream"}
    else:
        artifacts = {RIFE_LIBRARY: "armv8-a", "libvsnlm_ispc.so": "cortex-a53"}
    for name, kind in artifacts.items():
        target = native / "plugins" / name
        record = installed_plugins / f"{name}.{kind}.sha256"
        if not target.is_file() or not record.is_file():
            raise RuntimeError(f"Run setup_linux_environment.sh --mode Build to install the {kind} build of {name}")
        with target.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        expected = f"{checksum}  -".encode("ascii")
        stamp = record.read_bytes().strip()
        # NLM setup can prefix the checksum with the build identity used for cache validation.
        matches = stamp == expected or (name == "libvsnlm_ispc.so" and stamp.endswith(b" " + expected))
        if not matches:
            raise RuntimeError(f"Installed {name} differs from its {kind} build. Run setup_linux_environment.sh --mode Build")
        if kind == "upstream":
            upstream_plugins.add(target)
    shutil.copy2(installed_plugins / "nnedi3_weights.bin", native / "plugins")
    shutil.copytree(installed_plugins / "licenses/znedi3", support / "legal/vapoursynth/components/znedi3")
    if (installed_plugins / "models").is_dir():
        shutil.copytree(installed_plugins / "models", native / "plugins/models")
    sample = support / "vapoursynth"
    sample.mkdir(exist_ok=True)
    for source in (*vs_binaries, *vs_wheel.glob("*.py"), vs_wheel / "vspipe"):
        target = sample / source.name
        if not target.is_file():
            shutil.copy2(source, target)
    # R79 looks beside the loaded libvapoursynth name, including PyInstaller's top-level alias.
    for filters in sample.glob("libvapoursynthfilters*.so"):
        alias = support / filters.name
        if not alias.is_file():
            alias.symlink_to(filters.relative_to(support))
    remove_build_rpaths(sample / "vspipe")
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
    stage_glibc(support, Path("/usr/lib") / MULTIARCH, used_paths)
    # PyInstaller may collect system libraries independently of native-tool staging.
    for file in support.iterdir():
        if (GLIBC.fullmatch(file.name) or HOST_DRIVER.fullmatch(file.name)) and (file.is_file() or file.is_symlink()):
            file.unlink()
    # Inspect each Qt tool against its runtime after removing build-time RPATHs.
    qt_executables = [native / "libexec" / name for name in qt_tools]
    stage_qt(support, [path for path in qt_executables if path.is_file()], used_paths)
    for package in ("libglvnd0", "libdrm2", "libva2", "libvdpau1", "libvulkan1",
                    "libpipewire-0.3-modules", "libspa-0.2-modules"):
        copyright_file = Path("/usr/share/doc") / package / "copyright"
        shutil.copy2(copyright_file, support / "legal" / f"{package}-copyright")
        used_paths.add(copyright_file)
    shutil.copy2(
        "/usr/local/share/doc/bluraysubtitle-ffmpeg/hardware.txt",
        support / "legal/ffmpeg-hardware.txt",
    )
    if MULTIARCH == "x86_64-linux-gnu":
        vpl_copyright = Path("/usr/share/doc/libvpl-dev/copyright")
        shutil.copy2(vpl_copyright, support / "legal/onevpl-copyright")
        used_paths.add(vpl_copyright)
    # Strip the staged copies after comparing them for deduplication.
    for library in support.rglob("*.so*"):
        if (library.suffix == ".so" or ".so." in library.name) and not library.is_symlink() and library.is_file():
            if library not in upstream_plugins and not library.is_relative_to(native / "glibc"):
                remove_build_rpaths(library)
                subprocess.run(["strip", "--strip-unneeded", library], check=True)
    uosc_version = stage_bundled_mpv(support, uosc_bundle, str(tools["mpv"]))
    # uosc invokes Ziggy by its resource path, including when the editable mpv config is linked.
    ziggy = support / "resource/mpv" / UOSC_DIR / UOSC_BINARY
    ziggy.unlink()
    ziggy.symlink_to(os.path.relpath(native / "bin/ziggy-linux", ziggy.parent))
    generate_linux_third_party_notices(
        {
            ROOT / "legal/linux" / filename: support / "legal" / filename
            for filename in ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.zh-Hans.md")
        },
        {**settings, "MPV_PATH": tools["mpv"], "VSEDIT_PATH": native / "bin/vsedit", "MKVTOOLNIX_PATH": native / "bin"},
        PYINSTALLER_VERSION,
        soundfile.__libsndfile_version__,
        qVersion(),
        PYQT_VERSION_STR,
        vs_version,
        plugin_notice_rows(installed_plugins, plugins),
        uosc_version,
    )
    if apt_paths := os.environ.get("BLURAY_APT_CACHE_PATHS"):
        used_paths.update((Path(sys.executable), stdlib / "os.py", Path(QtCore.__file__)))
        for command in ("as", "cc", "git", "ld", "pkg-config", "patchelf", "bsdtar", "strip", "tar", "xz"):
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
    parser.add_argument("uosc_bundle", type=Path, help="Path to the unpacked native uosc release")
    args = parser.parse_args()
    stage(args.support.resolve(), args.uosc_bundle)
