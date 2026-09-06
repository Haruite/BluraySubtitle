"""Generate third-party notices for the Windows PyInstaller bundle."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
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


def generate_third_party_notices(
    template_outputs: Mapping[Path, Path],
    settings: Mapping[str, object],
    pyinstaller_version: str,
) -> None:
    """Render all language templates using one set of bundled component versions."""
    ffmpeg_build = _command_version(
        settings["FFMPEG_PATH"],
        ("-version",),
        r"^ffmpeg version\s+(\S+)",
    )
    ffmpeg_release = re.match(VERSION, ffmpeg_build)
    if not ffmpeg_release:
        raise RuntimeError(f"Unable to read FFmpeg release from: {ffmpeg_build}")

    software_root = Path(str(settings["X265_PATH"])).parent
    vapoursynth_root = Path(str(settings["VSEDIT_PATH"])).parent
    classic_version = _marker(
        vapoursynth_root / "vapoursynth-classic-version.txt"
    )
    classic_release, classic_api = classic_version.split(".", 1)
    python_state_path = vapoursynth_root / "python-embed-version.json"
    if not python_state_path.is_file():
        raise FileNotFoundError(f"Missing bundled software version marker: {python_state_path}")
    python_version = str(
        json.loads(python_state_path.read_text(encoding="utf-8-sig"))["python_version"]
    )

    versions = {
        "SEVEN_ZIP_VERSION": _command_version(
            settings["SEVEN_ZIP_PATH"], ("i",), rf"^7-Zip\s+({VERSION})"
        ),
        "FFMPEG_BUILD": ffmpeg_build,
        "FFMPEG_VERSION": ffmpeg_release.group(0),
        "FLAC_VERSION": _command_version(
            settings["FLAC_PATH"], ("--version",), rf"^flac\s+({VERSION})"
        ),
        "FDKAAC_VERSION": _command_version(
            settings["FDK_AAC_PATH"],
            ("-h",),
            rf"^fdkaac\s+({VERSION})",
            (0, 1),
        ),
        "FDK_AAC_VERSION": "2.0.3",
        "X264_VERSION": _command_version(
            settings["X264_PATH"], ("--version",), r"^x264\s+([^\r\n]+)"
        ),
        "X265_VERSION": _marker(software_root / "x265-version.txt"),
        "SVT_AV1_VERSION": _command_version(
            settings["SVT_AV1_PATH"],
            ("--version",),
            rf"\bv?({VERSION})\b",
        ),
        "TSMUXER_VERSION": _command_version(
            settings["TS_MUXER_PATH"],
            (),
            rf"tsMuxeR version\s+({VERSION})",
            (0, 4294967295),
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
        "LIBASS_VERSION": _marker(software_root / "libass-version.txt"),
        "MKVTOOLNIX_VERSION": _command_version(
            settings["MKV_MERGE_PATH"],
            ("--version",),
            rf"\bv({VERSION})",
        ),
        "VAPOURSYNTH_CLASSIC_VERSION": f"R{classic_release}.A{classic_api}",
        "PYTHON_VERSION": python_version,
        "VAPOURSYNTH_TOOLS_VERSION": _marker(
            vapoursynth_root / "vapoursynth-tools-version.txt"
        ),
        "VSEDIT_VERSION": "R19-mod-6.10",
        "PYINSTALLER_VERSION": pyinstaller_version,
    }

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
