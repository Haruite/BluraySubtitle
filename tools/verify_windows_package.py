"""Smoke-test the launchers and runtime layout of an extracted Windows package."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.windows_native_tools import (
    VSEDIT_PROGRAMS, VSEDIT_QT_LIBRARIES, clean_tool_environment, runtime_dependencies, verify_mkv_runtime,
)
from tools.windows_tool_paths import MKV_SETTINGS


def verify(bundle: Path, work: Path) -> None:
    internal = bundle / "_internal"
    mkv = internal / "mkvtoolnix"
    editor = internal / "vsedit"
    qt = internal / "PyQt6/Qt6/bin"
    for name in VSEDIT_QT_LIBRARIES:
        if set(internal.rglob(name)) != {qt / name}:
            raise RuntimeError(f"Unexpected bundled locations for {name}")
    programs = [mkv / (Path(name).stem + "-native.exe") for name in MKV_SETTINGS]
    verify_mkv_runtime(programs, runtime_dependencies(programs, [mkv, internal]))

    environment = clean_tool_environment()
    for name in list(environment):
        if name.startswith(("_PYI_", "PYTHON", "VSSCRIPT", "VAPOURSYNTH", "BLURAYSUB_PLUGIN_PATH")):
            del environment[name]
    environment["PYTHONNOUSERSITE"] = "1"

    def run(program: Path, *arguments) -> str:
        result = subprocess.run(
            [program, *arguments], cwd=work, env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, encoding="utf-8", errors="replace", timeout=45,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise RuntimeError(f"{program.name} returned {result.returncode}: {result.stdout}{result.stderr}")
        return result.stdout + result.stderr

    for executable in MKV_SETTINGS:
        for location in (internal, mkv):
            output = run(location / executable, "--version")
            if not output.startswith(Path(executable).stem + " v"):
                raise RuntimeError(f"Unexpected {executable} version: {output}")
    if "VapourSynth Editor" not in run(editor / "vsedit.exe", "--version"):
        raise RuntimeError("The VSEdit launcher did not report its version")
    for executable in VSEDIT_PROGRAMS:
        if not (editor / executable).is_file() or not (editor / (Path(executable).stem + "-native.exe")).is_file():
            raise FileNotFoundError(f"Missing the bundled VSEdit entry point: {executable}")
    run(internal / "vspipe.exe", "--version")

    audio = work / "audio.wav"
    with wave.open(os.fspath(audio), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", ""))
        output.writeframes(b"\0" * 9600)
    flac = work / "audio.flac"
    run(internal / "flac.exe", "--silent", "-o", flac, audio)
    subtitle = work / "字幕.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nBluraySubtitle\n", encoding="utf-8")
    mux = work / "audio and subtitles.mkv"
    run(internal / "mkvmerge.exe", "-o", mux, flac, subtitle)
    run(internal / "mkvinfo.exe", "--summary", mux)
    run(internal / "mkvpropedit.exe", mux, "--edit", "info", "--set", "title=BluraySubtitle")
    info = json.loads(run(internal / "mkvmerge.exe", "-J", mux))
    if [track["properties"]["codec_id"] for track in info["tracks"]] != ["A_FLAC", "S_TEXT/UTF8"]:
        raise RuntimeError("The bundled MKVToolNix did not preserve both tracks")
    if info["container"]["properties"].get("title") != "BluraySubtitle":
        raise RuntimeError("The bundled mkvpropedit did not update the title")
    extracted = work / "extracted.srt"
    run(internal / "mkvextract.exe", mux, "tracks", f"1:{extracted}")
    if "BluraySubtitle" not in extracted.read_text(encoding="utf-8-sig"):
        raise RuntimeError("The bundled MKVToolNix did not extract the subtitle")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--seven-zip", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    with tempfile.TemporaryDirectory(prefix="verify package ", dir=archive.parent) as temporary:
        root = Path(temporary)
        subprocess.run([args.seven_zip, "x", archive, "-o" + str(root), "-y", "-bso0", "-bsp0"], check=True)
        verify(root / archive.stem, root)
    print("Verified the Windows archive, standalone tool launchers and shared Qt runtime.")


if __name__ == "__main__":
    main()
