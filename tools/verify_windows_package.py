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
    PE_ARM64, VSEDIT_PROGRAMS, VSEDIT_QT_LIBRARIES, clean_tool_environment, has_pe_machine,
    runtime_dependencies, verify_mkv_runtime, windows_machine,
)
from tools.windows_tool_paths import MKV_SETTINGS


def verify(bundle: Path, work: Path) -> None:
    suffix = "arm64" if windows_machine() == PE_ARM64 else "x64"
    package_name = f"BluraySubtitle_windows_{suffix}"
    if bundle.name != package_name or not (bundle / f"{package_name}.exe").is_file():
        raise RuntimeError(f"Expected the {package_name} package and executable")
    for path in bundle.rglob("*"):
        if path.suffix.lower() in {".exe", ".dll", ".pyd"} and not has_pe_machine(path):
            raise RuntimeError(f"Expected a {suffix} PE binary at {path.relative_to(bundle)}")

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

    def run(program: Path, *arguments, env=environment) -> str:
        result = subprocess.run(
            [program, *arguments], cwd=work, env=env, stdin=subprocess.DEVNULL,
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
    vspipe = internal / "Lib/site-packages/vapoursynth/vspipe.exe"
    expected_core = "Core R79"
    if not vspipe.is_file():
        vspipe = internal / "vspipe.exe"
        expected_core = "Core R57"
    vs_environment = dict(environment, PATH=str(internal) + os.pathsep + environment["PATH"])
    if expected_core not in run(vspipe, "--version", env=vs_environment).splitlines():
        raise RuntimeError(f"The bundled VSPipe did not report {expected_core}")
    subtitle = work / "字幕.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nBluraySubtitle\n", encoding="utf-8")
    if expected_core == "Core R79":
        for name in ("libass-9.dll", "libfftw3f-3.dll", "libshaderc_shared.dll", "vulkan-1.dll"):
            if len(list(internal.rglob(name))) != 1:
                raise RuntimeError(f"Expected one bundled copy of {name}")
    script = work / "bundled.vpy"
    script.write_text(
        "import vapoursynth as vs\nimport mvsfunc\n"
        "fmt = vs.core.query_video_format(vs.ColorFamily.YUV, vs.SampleType.INTEGER, 10, 1, 1)\n"
        "clip = vs.core.std.BlankClip(length=2, width=64, height=48, format=fmt.id)\n"
        "clip = vs.core.rgvs.RemoveGrain(clip, mode=1)\n"
        "assert clip.znedi3.nnedi3(field=0, dh=True).get_frame(0).height == 96\n"
        + ("assert vs.core.placebo.Deband and vs.core.dfttest.DFTTest and vs.core.lsmas.LWLibavSource\n"
           "clip = vs.core.assrender.TextSub(clip, '字幕.srt')\n" if expected_core == "Core R79" else "")
        + "clip.set_output()\n",
        encoding="utf-8",
    )
    output = work / "bundled.y4m"
    run(vspipe, "--container", "y4m", script, output, env=vs_environment)
    y4m = output.read_bytes()
    if not y4m.startswith(b"YUV4MPEG2 ") or y4m.count(b"FRAME\n") != 2:
        raise RuntimeError("The bundled VSPipe did not write two Y4M frames")

    audio = work / "audio.wav"
    with wave.open(os.fspath(audio), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", ""))
        output.writeframes(b"\0" * 9600)
    flac = work / "audio.flac"
    run(internal / "flac.exe", "--silent", "-o", flac, audio)
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
    print("Verified Windows binary architecture, standalone tools and shared runtimes.")


if __name__ == "__main__":
    main()
