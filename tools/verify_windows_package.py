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
    WIN7_QT_VERSION, WIN7_QT_SDK_VERSION, runtime_dependencies, verify_mkv_runtime, windows_machine,
)
from tools.windows_tool_paths import MKV_PROGRAMS


def verify_compatibility_imports(path: Path, qt: Path) -> None:
    import pefile

    unavailable = {
        b"WaitOnAddress", b"WakeByAddressAll", b"WakeByAddressSingle", b"ProcessPrng",
        b"CreateFile2", b"GetSystemTimePreciseAsFileTime", b"UiaRaiseNotificationEvent",
    }
    with pefile.PE(str(path), fast_load=True) as image:
        is_qt_library = path.suffix.lower() == ".dll" and path.name.lower().startswith("qt6")
        is_qt_plugin = path.is_relative_to(qt / "plugins") and path.suffix.lower() == ".dll"
        if is_qt_library and path.parent != qt / "bin":
            raise RuntimeError(f"Unexpected Qt library location: {path}")
        if is_qt_library or is_qt_plugin:
            expected = WIN7_QT_SDK_VERSION if path.name.lower() == "qt6websockets.dll" else WIN7_QT_VERSION
            image.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
            info = getattr(image, "VS_FIXEDFILEINFO", [])
            version = (f"{info[0].FileVersionMS >> 16}.{info[0].FileVersionMS & 0xffff}.{info[0].FileVersionLS >> 16}"
                       if info else "unknown")
            if version != expected:
                raise RuntimeError(f"{path.name} has Qt {version}; the Windows 7 package requires {expected}")
        image.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        missing = {entry.name for module in getattr(image, "DIRECTORY_ENTRY_IMPORT", ())
                   for entry in module.imports if entry.name in unavailable}
    if missing:
        raise RuntimeError(f"{path.name} imports APIs unavailable on Windows 7: {', '.join(x.decode('ascii') for x in sorted(missing))}")


def verify(bundle: Path, work: Path) -> None:
    suffix = "arm64" if windows_machine() == PE_ARM64 else "x64"
    compatibility = suffix == "x64" and bundle.name == "BluraySubtitle_windows_x64_compat"
    package_name = f"BluraySubtitle_windows_{suffix}" + ("_compat" if compatibility else "")
    if bundle.name != package_name or not (bundle / f"{package_name}.exe").is_file():
        raise RuntimeError(f"Expected the {package_name} package and executable")
    internal = bundle / "_internal"
    qt = internal / "PyQt6/Qt6"
    binaries = [path for path in bundle.rglob("*") if path.suffix.lower() in {".exe", ".dll", ".pyd"}]
    for path in binaries:
        if not has_pe_machine(path):
            raise RuntimeError(f"Expected a {suffix} PE binary at {path.relative_to(bundle)}")
        if compatibility:
            verify_compatibility_imports(path, qt)

    mkv = internal / "mkvtoolnix"
    editor = internal / "vsedit"
    for name in VSEDIT_QT_LIBRARIES:
        if set(internal.rglob(name)) != {qt / "bin" / name}:
            raise RuntimeError(f"Unexpected bundled locations for {name}")
    programs = [mkv / (Path(name).stem + "-native.exe") for name in MKV_PROGRAMS]
    verify_mkv_runtime(programs, runtime_dependencies(programs, [mkv, internal]))

    environment = clean_tool_environment()
    for name in list(environment):
        if name.startswith(("_PYI_", "PYTHON", "VSSCRIPT", "VAPOURSYNTH", "BLURAYSUB_PLUGIN_PATH")):
            del environment[name]
    environment["PYTHONNOUSERSITE"] = "1"

    def run(program: Path, *arguments, env=environment, accepted_codes=(0,)) -> str:
        try:
            result = subprocess.run(
                [program, *arguments], cwd=work, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, encoding="utf-8", errors="replace", timeout=45,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"{program.name} did not finish within 45 seconds") from error
        if result.returncode not in accepted_codes:
            raise RuntimeError(f"{program.name} returned {result.returncode}: {result.stdout}{result.stderr}")
        return result.stdout + result.stderr

    if not compatibility:
        if run(internal / "bluraysub-gpu-capabilities.exe", "--version").strip() != "2":
            raise RuntimeError("The packaged GPU capability query failed its version check")
        encoders = run(internal / "ffmpeg.exe", "-hide_banner", "-encoders")
        if not any(line.split()[1:2] == ["ffv1_vulkan"] for line in encoders.splitlines()):
            raise RuntimeError("FFmpeg is missing the Vulkan FFV1 encoder")

    for executable in MKV_PROGRAMS:
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
        shared = ["libass-9.dll", "libfftw3f-3.dll", "libshaderc_shared.dll"]
        if not compatibility:
            shared.append("vulkan-1.dll")
        for name in shared:
            if len(list(internal.rglob(name))) != 1:
                raise RuntimeError(f"Expected one bundled copy of {name}")
        run(internal / "ffmpeg.exe", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=24",
            "-frames:v", "2", "-c:v", "ffv1", "-pix_fmt", "yuv420p10le", work / "source.mkv")
        clip_source = "clip = vs.core.lsmas.LWLibavSource('source.mkv', cache=0)"
    else:
        clip_source = (
            "fmt = vs.core.query_video_format(vs.ColorFamily.YUV, vs.SampleType.INTEGER, 10, 1, 1)\n"
            "clip = vs.core.std.BlankClip(length=2, width=64, height=48, format=fmt.id)"
        )
    script = work / "bundled.vpy"
    script.write_text(
        "import vapoursynth as vs\nimport mvsfunc\n"
        f"{clip_source}\n"
        "clip = vs.core.rgvs.RemoveGrain(clip, mode=1)\n"
        "assert clip.znedi3.nnedi3(field=0, dh=True).get_frame(0).height == 96\n"
        + ("clip = vs.core.zsmooth.RemoveGrain(clip, mode=1)\n" if compatibility else "")
        + ("assert vs.core.dfttest.DFTTest\n"
           "clip = vs.core.nlm_ispc.NLMeans(clip, d=0, a=2, s=2, h=0.6, channels='Y', wmode=3)\n"
           "clip = vs.core.assrender.TextSub(clip, '字幕.srt')\n" if expected_core == "Core R79" else "")
        + ("assert vs.core.placebo.Deband\n" if expected_core == "Core R79" and not compatibility else "")
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
    if compatibility:
        from tools.verify_windows_compat_components import verify_filters, verify_media_tools, verify_win7_system_imports

        for executable in VSEDIT_PROGRAMS[1:]:
            if executable == "vsedit-encode.exe":
                output = run(editor / executable, accepted_codes=(4294967294,))
                if "Please provide the path to your script" not in output:
                    raise RuntimeError(f"Unexpected startup response from {executable}: {output}")
            elif "VapourSynth Editor" not in run(editor / executable, "--version"):
                raise RuntimeError(f"Unexpected version from {executable}")
        failures = []
        for test, arguments in (
            (verify_media_tools, (internal, work, run)),
            (verify_filters, (internal, vspipe, work, run, vs_environment)),
            (verify_win7_system_imports, (binaries,)),
        ):
            try:
                test(*arguments)
            except (OSError, RuntimeError) as error:
                failures.append(str(error))
        if failures:
            raise RuntimeError("\n".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="A 7z archive or an extracted package directory")
    parser.add_argument("--seven-zip", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    if not package.is_dir() and not args.seven_zip:
        parser.error("--seven-zip is required to verify an archive")
    with tempfile.TemporaryDirectory(prefix="verify package ", dir=package.parent) as temporary:
        root = Path(temporary)
        if package.is_dir():
            verify(package, root)
        else:
            subprocess.run([args.seven_zip, "x", package, "-o" + str(root), "-y", "-bso0", "-bsp0"], check=True)
            verify(root / package.stem, root)
    print("Verified Windows binary architecture, standalone tools and shared runtimes.")


if __name__ == "__main__":
    main()
