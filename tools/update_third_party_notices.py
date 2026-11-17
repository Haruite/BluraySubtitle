"""Generate third-party notices for the PyInstaller bundles."""

from __future__ import annotations

from importlib.metadata import version
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import sysconfig
from typing import Mapping


VERSION = r"[0-9]+(?:\.[0-9]+){1,3}"
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def _command_version(
    path: object,
    arguments: tuple[str, ...],
    pattern: str,
    accepted_return_codes: tuple[int, ...] = (0,),
) -> str:
    executable = Path(str(path))
    if not executable.is_file():
        raise FileNotFoundError(f"Missing bundled software: {executable}")
    result = subprocess.run(
        [str(executable), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = result.stdout + result.stderr
    match = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
    if result.returncode not in accepted_return_codes or not match:
        raise RuntimeError(f"Unable to read version from {executable}: {output.strip()}")
    return match.group(1).strip()


def _marker(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Missing bundled software version marker: {path}")
    value = path.read_text(encoding="utf-8-sig").splitlines()[0].strip()
    if not value:
        raise RuntimeError(f"Empty bundled software version marker: {path}")
    return value


def _common_versions(
    settings: Mapping[str, object],
    pyinstaller_version: str,
    libsndfile_version: str,
    tsmuxer_arguments: tuple[str, ...],
    tsmuxer_return_codes: tuple[int, ...],
) -> dict[str, str]:
    ffmpeg_build = _command_version(
        settings["FFMPEG_PATH"],
        ("-version",),
        r"^ffmpeg version\s+(\S+)",
    )
    ffmpeg_release = re.match(rf"(?:n|v)?({VERSION})", ffmpeg_build)
    if not ffmpeg_release:
        raise RuntimeError(f"Unable to read FFmpeg release from: {ffmpeg_build}")

    return {
        "SEVEN_ZIP_VERSION": _command_version(
            settings["SEVEN_ZIP_PATH"], ("i",), rf"^7-Zip(?:\s+\([^)]+\))?\s+({VERSION})"
        ),
        "FFMPEG_BUILD": ffmpeg_build,
        "FFMPEG_VERSION": ffmpeg_release.group(1),
        "FLAC_VERSION": _command_version(
            settings["FLAC_PATH"], ("--version",), rf"^flac\s+({VERSION})"
        ),
        "FDKAAC_VERSION": _command_version(
            settings["FDK_AAC_PATH"],
            ("-h",),
            rf"^fdkaac\s+({VERSION})",
            (0, 1),
        ),
        "X264_VERSION": _command_version(
            settings["X264_PATH"], ("--version",), r"^x264\s+([^\r\n]+)"
        ),
        "SVT_AV1_VERSION": _command_version(
            settings["SVT_AV1_PATH"],
            ("--version",),
            rf"\bv?({VERSION})\b",
        ),
        "TSMUXER_VERSION": _command_version(
            settings["TS_MUXER_PATH"],
            tsmuxer_arguments,
            rf"tsMuxeR version\s+({VERSION})",
            tsmuxer_return_codes,
        ),
        "DOVI_TOOL_VERSION": _command_version(
            settings["DOVI_TOOL_PATH"],
            ("--version",),
            rf"^dovi_tool\s+({VERSION})",
        ),
        "HDR10PLUS_TOOL_VERSION": _command_version(
            settings["HDR10PLUS_TOOL_PATH"],
            ("--version",),
            rf"^hdr10plus_tool\s+({VERSION})",
        ),
        "MKVTOOLNIX_VERSION": _command_version(
            Path(str(settings["MKVTOOLNIX_PATH"])) / ("mkvmerge.exe" if sys.platform == "win32" else "mkvmerge"),
            ("--version",),
            rf"\bv({VERSION})",
        ),
        "PYTHON_VERSION": platform.python_version(),
        "NUMPY_VERSION": version("numpy"),
        "LIBSNDFILE_VERSION": libsndfile_version,
        "PYINSTALLER_VERSION": pyinstaller_version,
    }


def generate_third_party_notices(
    template_outputs: Mapping[Path, Path],
    settings: Mapping[str, object],
    pyinstaller_version: str,
    libsndfile_version: str,
    package_architecture: str,
) -> None:
    """Render both Windows notices for the components and build architecture."""
    arm64 = package_architecture == "arm64"
    software_root = Path(str(settings["X265_PATH"])).parent
    mkv_root = Path(str(settings["MKVTOOLNIX_PATH"]))
    mkv_build = json.loads((mkv_root / "mkvtoolnix-build.json").read_text(encoding="utf-8"))
    mkv_qt = mkv_build["qt_version"]
    mkv_qt_series = ".".join(mkv_qt.split(".")[:2])
    vapoursynth_root = Path(str(settings["VSPIPE_PATH"])).parent
    components = json.loads(
        (vapoursynth_root / "vapoursynth-components.json").read_text(encoding="utf-8")
    )["components"]
    native_rows = "\n".join(
        f"| {component['name']} | `{component['ref']}` | [source]({component['source_url']}) | `legal/vapoursynth/components/{name}/` |"
        for name, component in components.items() if "plugin" in component
    )
    state = json.loads((vapoursynth_root / "vapoursynth-build.json").read_text(encoding="utf-8-sig"))
    r79 = state["version"] == "79"
    if r79:
        vs_upstream = "https://github.com/vapoursynth/vapoursynth"
        vs_tag = "R79"
        vs_license = "LGPL-2.1-or-later"
    else:
        vs_upstream = "https://github.com/AmusementClub/vapoursynth-classic"
        classic_release, classic_api = state["version"].split(".", 1)
        vs_tag = f"R{classic_release}.A{classic_api}"
        vs_license = "LGPL-3.0-or-later"

    versions = {
        **_common_versions(settings, pyinstaller_version, libsndfile_version, (), (0, 4294967295)),
        "FDK_AAC_VERSION": "2.0.3",
        "X264_OPTIMIZATIONS": "NEON" if arm64 else "PGO + LTO",
        "X265_VERSION": _marker(software_root / "x265-version.txt"),
        "LIBASS_VERSION": _marker(software_root / "libass-version.txt"),
        "LIBASS_ASSEMBLY": "AArch64" if arm64 else "x86-64",
        "LIBASS_COMPILER_RUNTIME": (
            "LLVM libc++ (`Apache-2.0 WITH LLVM-exception`)"
            if arm64 else "GCC libstdc++ / libgcc (`GPL-3.0-or-later WITH GCC-exception-3.1`)"
        ),
        "MKVTOOLNIX_QT_VERSION": mkv_qt,
        "MKVTOOLNIX_QT_SOURCE": f"https://download.qt.io/archive/qt/{mkv_qt_series}/{mkv_qt}/submodules/qtbase-everywhere-src-{mkv_qt}.tar.xz",
        "VAPOURSYNTH_UPSTREAM": vs_upstream,
        "VAPOURSYNTH_VERSION": vs_tag,
        "VAPOURSYNTH_LICENSE": vs_license,
        "VAPOURSYNTH_NAME": "VapourSynth" if r79 else "VapourSynth Classic",
        "WINDOWS_ARCHITECTURE": package_architecture,
        "WINDOWS_MSYS2_ENVIRONMENT": "CLANGARM64" if arm64 else "UCRT64",
        "VAPOURSYNTH_COMPONENTS": native_rows,
        "VSEDIT_VERSION": components["vsedit"]["ref"],
        "VSEDIT_QT_VERSION": components["vsedit"]["qt_version"],
        "VSEDIT_QT_SOURCE": components["vsedit"]["qt_source_url"],
    }

    _render_notices(template_outputs, versions)


def generate_ubuntu_third_party_notices(
    template_outputs: Mapping[Path, Path],
    settings: Mapping[str, object],
    pyinstaller_version: str,
    libsndfile_version: str,
    qt_version: str,
    pyqt_version: str,
    vapoursynth_version: str,
    vapoursynth_components: str,
) -> None:
    """Render Ubuntu notices using the tools and Python libraries selected for staging."""
    python_architecture = {
        "x86_64-linux-gnu": "amd64",
        "aarch64-linux-gnu": "arm64",
    }[sysconfig.get_config_var("MULTIARCH")]
    versions = {
        **_common_versions(settings, pyinstaller_version, libsndfile_version, ("--help",), (0,)),
        "PYTHON_ARCHITECTURE": python_architecture,
        "FDK_AAC_VERSION": _command_version(
            "/usr/bin/pkg-config", ("--modversion", "fdk-aac"), rf"^({VERSION})$"
        ),
        "LIBASS_VERSION": _command_version(
            "/usr/bin/pkg-config", ("--modversion", "libass"), rf"^({VERSION})$"
        ),
        "X265_VERSION": _command_version(
            settings["X265_PATH"], ("--version",), r"HEVC encoder version\s+(\S+)"
        ),
        "MPV_VERSION": _command_version(
            settings["MPV_PATH"], ("--version",), r"^mpv\s+(\S+)"
        ),
        "VSEDIT_VERSION": _command_version(
            settings["VSEDIT_PATH"], ("--version",), r"^VapourSynth Editor\s+(\S+)"
        ),
        "QT_VERSION": qt_version,
        "PYQT_VERSION": pyqt_version,
        "VAPOURSYNTH_VERSION": vapoursynth_version,
        "VAPOURSYNTH_COMPONENTS": vapoursynth_components,
        "SOUNDFILE_VERSION": version("soundfile"),
        "PILLOW_VERSION": version("pillow"),
        "PYCOUNTRY_VERSION": version("pycountry"),
    }
    _render_notices(template_outputs, versions)


def _render_notices(template_outputs: Mapping[Path, Path], versions: Mapping[str, str]) -> None:
    for template_path, output_path in template_outputs.items():
        template = template_path.read_text(encoding="utf-8-sig")
        declared = set(PLACEHOLDER.findall(template))
        missing_values = declared - versions.keys()
        missing_declarations = versions.keys() - declared
        if missing_values or missing_declarations:
            raise RuntimeError(
                f"{template_path.name} software declarations do not match the updater: "
                f"missing values={sorted(missing_values)}, "
                f"missing declarations={sorted(missing_declarations)}"
            )
        for name, value in versions.items():
            template = template.replace("{{" + name + "}}", value)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(template.replace("\n", "\r\n").encode("utf-8"))
