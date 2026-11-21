"""Exercise compatibility package media tools and VapourSynth plugins with generated inputs."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys


FILTERS = {
    "addgrain.dll": "result = core.grain.Add(clip, var=2.0, seed=1)",
    "assrender.dll": "result = core.assrender.TextSub(clip10, subtitle)",
    "avscompat.dll": """
try:
    core.avs.LoadPlugin('missing AviSynth plugin.dll')
except vs.Error:
    result = clip
else:
    raise RuntimeError('AviSynth bridge accepted a missing library')
""",
    "bilateral.dll": "result = core.bilateral.Bilateral(clip, sigmaS=1.5, sigmaR=0.05)",
    "descale.dll": "result = core.descale.Descale(core.resize.Point(clip, format=vs.GRAYS), 64, 48, kernel='bilinear')",
    "dfttest.dll": "result = core.dfttest.DFTTest(clip, sbsize=8, sosize=4, tbsize=1, sigma=2.0)",
    "eedi2.dll": "result = core.eedi2.EEDI2(clip, field=0)",
    "eedi3.dll": "result = core.eedi3.eedi3(clip, field=0, dh=True)",
    "eedi3m.dll": "result = core.eedi3m.EEDI3(clip, field=0, dh=True)",
    "fmtconv.dll": "result = core.fmtc.bitdepth(clip10, bits=8)",
    "libvslsmashsource.dll": "result = core.lsmas.LWLibavSource('source.mkv', cache=0)",
    "miscfilters.dll": "result = core.misc.AverageFrames(clip, weights=[1.0, 2.0, 1.0])",
    "mvtools.dll": """
super_clip = core.mv.Super(clip, pel=1)
vectors = core.mv.Analyse(super_clip, isb=False, delta=1, blksize=8)
result = core.mv.Compensate(clip, super_clip, vectors)
""",
    "removegrainvs.dll": "result = core.rgvs.RemoveGrain(clip, mode=1)",
    "vivtc.dll": "result = core.vivtc.VDecimate(core.vivtc.VFM(clip, order=1))",
    "vs_sangnommod.dll": "result = core.sangnom.SangNom(clip, order=1)",
    "vsnlm_ispc.dll": "result = core.nlm_ispc.NLMeans(clip10, d=0, a=2, s=2, h=0.6, channels='Y', wmode=3)",
    "znedi3.dll": "result = core.znedi3.nnedi3(clip, field=0, dh=True)",
    "zsmooth.dll": "result = core.zsmooth.RemoveGrain(clip, mode=1)",
}


def verify_win7_system_imports(binaries: list[Path]) -> None:
    """On Windows 7, check eager system imports against the guest's actual DLL exports."""
    if sys.getwindowsversion().platform_version[:2] != (6, 1):
        return
    import pefile

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LoadLibraryExW.argtypes = (wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD)
    kernel.LoadLibraryExW.restype = wintypes.HMODULE
    kernel.GetProcAddress.argtypes = (wintypes.HMODULE, ctypes.c_void_p)
    kernel.GetProcAddress.restype = ctypes.c_void_p
    kernel.FreeLibrary.argtypes = (wintypes.HMODULE,)
    shipped = {path.name.casefold() for path in binaries}
    libraries = {}
    missing = []
    try:
        for path in sorted(binaries):
            with pefile.PE(str(path), fast_load=True) as image:
                image.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
                for entry in getattr(image, "DIRECTORY_ENTRY_IMPORT", ()):
                    name = entry.dll.decode("ascii").lower()
                    if name in shipped:
                        continue
                    if name not in libraries:
                        libraries[name] = kernel.LoadLibraryExW(name, None, 0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
                    handle = libraries[name]
                    if not handle:
                        missing.append(f"{path.name} requires {name}")
                        continue
                    for symbol in entry.imports:
                        address = ctypes.c_char_p(symbol.name) if symbol.name else ctypes.c_void_p(symbol.ordinal)
                        if not kernel.GetProcAddress(handle, ctypes.cast(address, ctypes.c_void_p)):
                            export = symbol.name.decode("ascii", errors="replace") if symbol.name else str(symbol.ordinal)
                            missing.append(f"{path.name} requires {name}!{export}")
    finally:
        for handle in libraries.values():
            if handle:
                kernel.FreeLibrary(handle)
    if missing:
        raise RuntimeError("Unavailable Windows 7 system imports:\n" + "\n".join(missing))


def verify_filters(internal: Path, vspipe: Path, work: Path, run, environment: dict[str, str]) -> None:
    plugins = {path.name.lower() for path in (vspipe.parent / "plugins").glob("*.dll")}
    if plugins != FILTERS.keys():
        raise RuntimeError(f"Uncovered plugins: {sorted(plugins - FILTERS.keys())}; missing: {sorted(FILTERS.keys() - plugins)}")
    sample = (
        "import vapoursynth as vs\ncore = vs.core\ncore.num_threads = 2\n"
        "half = core.std.BlankClip(width=48,height=64,length=8,format=vs.YUV420P8,color=[48,128,128])\n"
        "clip = core.std.StackHorizontal([half, core.std.Invert(half)])\n"
        "clip10 = core.resize.Point(clip, format=vs.YUV420P10)\n"
        "subtitle = '\u5b57\u5e55.srt'\n"
    )
    script = work / "verify-filter.vpy"
    failures = []
    for name, test in FILTERS.items():
        script.write_text(sample + test + "\nassert result.get_frame(0).width > 0\nresult.set_output()\n", encoding="utf-8")
        try:
            run(vspipe, "--info", script, "-", env=environment)
        except (OSError, RuntimeError) as error:
            failures.append(f"{name}: {error}")
        else:
            print(f"Verified VapourSynth plugin {name}", flush=True)
    if failures:
        raise RuntimeError("VapourSynth plugin verification failed:\n" + "\n".join(failures))

    # VSMLRT is a Python interface for separately installed inference backends.
    modules = sorted(path.stem for path in internal.glob("*.py") if path.stem != "vsmlrt")
    script.write_text(
        sample + f"import importlib\nfor module in {modules!r}:\n    importlib.import_module(module)\n"
        "clip.set_output()\n",
        encoding="utf-8",
    )
    run(vspipe, "--info", script, "-", env=environment)
    print(f"Verified VapourSynth Python modules: {', '.join(modules)}", flush=True)


def verify_media_tools(internal: Path, work: Path, run) -> None:
    def codec(path: Path) -> str:
        result = run(internal / "ffprobe.exe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "json", path)
        (stream,) = json.loads(result)["streams"]
        return stream["codec_name"]

    run(internal / "7z.exe", "a", "-t7z", work / "probe.7z", work / "audio.wav")
    run(internal / "7z.exe", "t", work / "probe.7z")
    verify_sndfile(internal, work / "audio.wav")
    run(internal / "fdkaac.exe", "-b", "96000", "-o", work / "audio.m4a", work / "audio.wav")
    if codec(work / "audio.m4a") != "aac":
        raise RuntimeError("fdkaac did not produce AAC audio")
    run(internal / "ffmpeg.exe", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=128x96:rate=24",
        "-frames:v", "4", "-pix_fmt", "yuv420p", "-f", "yuv4mpegpipe", work / "encoder.y4m")
    y4m = work / "encoder.y4m"
    h264 = work / "video.264"
    hevc = work / "video.hevc"
    av1 = work / "video.ivf"
    run(internal / "x264.exe", "--preset", "ultrafast", "--demuxer", "y4m", "-o", h264, y4m)
    run(internal / "x265.exe", "--preset", "ultrafast", "--y4m", "--input", y4m, "--output", hevc)
    run(internal / "SvtAv1EncApp.exe", "--preset", "12", "-i", y4m, "-b", av1)
    if [codec(path) for path in (h264, hevc, av1)] != ["h264", "hevc", "av1"]:
        raise RuntimeError("The bundled video encoders did not produce the requested codecs")

    meta = work / "tsmuxer.meta"
    meta.write_text(f'MUXOPT --vbr\nV_MPEG4/ISO/AVC, "{h264.name}", fps=24\n', encoding="ascii")
    run(internal / "tsMuxeR.exe", meta, work / "video.m2ts")
    if codec(work / "video.m2ts") != "h264":
        raise RuntimeError("tsMuxeR did not mux the AVC input")

    dovi = internal / "dovi_tool.exe"
    config = work / "dovi.json"
    config.write_text(json.dumps({"cm_version": "V29", "length": 4, "level6": {
        "max_display_mastering_luminance": 1000, "min_display_mastering_luminance": 1,
        "max_content_light_level": 1000, "max_frame_average_light_level": 400,
    }}), encoding="ascii")
    rpu = work / "generated.rpu"
    run(dovi, "generate", "-j", config, "-o", rpu)
    run(dovi, "info", "-i", rpu, "-f", "0")

    hdr10plus = internal / "hdr10plus_tool.exe"
    metadata = work / "hdr10plus.json"
    metadata.write_text(json.dumps({
        "JSONInfo": {"HDR10plusProfile": "A", "Version": "1.0"},
        "SceneInfo": [{
            "LuminanceParameters": {
                "AverageRGB": 300, "MaxScl": [1000, 950, 900],
                "LuminanceDistributions": {"DistributionIndex": [1, 5, 10, 25, 50, 75, 90, 95, 99],
                                           "DistributionValues": [10, 25, 50, 150, 300, 525, 750, 850, 950]},
            },
            "NumberOfWindows": 1, "TargetedSystemDisplayMaximumLuminance": 0,
            "SceneFrameIndex": frame, "SceneId": 0, "SequenceFrameIndex": frame,
        } for frame in range(4)],
        "SceneInfoSummary": {"SceneFirstFrameIndex": [0], "SceneFrameNumbers": [4]},
        "ToolInfo": {"Tool": "BluraySubtitle package verification", "Version": "1.0"},
    }), encoding="ascii")
    tagged = work / "hdr10plus.hevc"
    extracted = work / "hdr10plus-extracted.json"
    run(hdr10plus, "inject", "-i", hevc, "-j", metadata, "-o", tagged)
    run(hdr10plus, "extract", tagged, "-o", extracted)
    if len(json.loads(extracted.read_text(encoding="utf-8"))["SceneInfo"]) != 4:
        raise RuntimeError("HDR10+ metadata did not round-trip for every HEVC frame")
    print("Verified 7-Zip, AAC, AVC, HEVC, AV1, M2TS, Dolby Vision and HDR10+", flush=True)


def verify_sndfile(internal: Path, audio: Path) -> None:
    class AudioInfo(ctypes.Structure):
        _fields_ = [("frames", ctypes.c_int64), ("sample_rate", ctypes.c_int), ("channels", ctypes.c_int),
                    ("format", ctypes.c_int), ("sections", ctypes.c_int), ("seekable", ctypes.c_int)]

    with os.add_dll_directory(str(internal)):
        library = ctypes.CDLL(str(internal / "_soundfile_data/libsndfile_x64.dll"))
    release_library = ctypes.WinDLL("kernel32").FreeLibrary
    release_library.argtypes = (wintypes.HMODULE,)
    try:
        library.sf_wchar_open.argtypes = (wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(AudioInfo))
        library.sf_wchar_open.restype = ctypes.c_void_p
        library.sf_close.argtypes = (ctypes.c_void_p,)
        info = AudioInfo()
        handle = library.sf_wchar_open(str(audio), 0x10, ctypes.byref(info))  # SFM_READ
        if not handle:
            raise RuntimeError("libsndfile could not open the bundled audio probe")
        if library.sf_close(handle) != 0 or (info.frames, info.sample_rate, info.channels) != (4800, 48000, 1):
            raise RuntimeError("libsndfile returned unexpected WAV properties")
    finally:
        # The archive extractor must be able to delete the test DLL before Python exits.
        release_library(library._handle)
    print("Verified libsndfile WAV inspection", flush=True)
