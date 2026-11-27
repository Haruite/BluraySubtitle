"""Exercise a relocated FreeBSD package with synthetic media and the Qt offscreen backend."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_ass_extension import VERIFY_ASS_EXTENSION


def verify_runtime(runtime: Path, work: Path):
    tools = runtime / "bin"
    home = work / "home"
    home.mkdir()
    configuration = work / "config"
    configuration.mkdir()
    environment = {"HOME": str(home), "PATH": "/bin:/usr/bin", "LANG": "C.UTF-8",
                   "XDG_CONFIG_HOME": str(home / ".config"), "QT_QPA_PLATFORM": "offscreen",
                   "BLURAY_SUBTITLE_CONFIG_DIR": str(configuration)}

    def run(program, *arguments):
        result = subprocess.run([tools / program, *arguments], cwd=work, env=environment, text=True,
                                capture_output=True, stdin=subprocess.DEVNULL, timeout=90)
        if result.returncode:
            raise RuntimeError(f"{program} exited {result.returncode}\n{result.stdout}\n{result.stderr}")
        return result.stdout

    manifest = json.loads((runtime / "runtime.json").read_bytes())
    run("python3", "-I", "-B", "-c", VERIFY_ASS_EXTENSION)
    assert "Core R79" in run("vspipe", "--version")
    for tool in ("mkvmerge", "mkvinfo", "mkvextract", "mkvpropedit", "dovi_tool", "hdr10plus_tool", "x264", "mpv"):
        run(tool, "--version")
    run("xclip", "-version")
    run("vsedit", "--version")
    protocols = run("mpv", "--no-config", "--list-protocols")
    assert any(line.strip().removesuffix("://") in ("bd", "bluray") for line in protocols.splitlines()), protocols
    assert "vulkan" in run("ffmpeg", "-hide_banner", "-hwaccels")
    run("python3", "-I", "-B", "-c", "from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QTranslator; "
        "from pathlib import Path; import sys; app = QCoreApplication([]); translator = QTranslator(); "
        "path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath); "
        "assert Path(path) == Path(sys.argv[1]) / 'qt/translations', path; "
        "assert translator.load('qtbase_zh_CN', path)", runtime)
    for name in ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.zh-Hans.md"):
        content = (runtime / "legal" / name).read_text(encoding="utf-8")
        assert "{{" not in content and all(word in content for word in ("ffmpeg", "mpv", "vapoursynth", "uosc"))
    source = work / "source.mkv"
    audio = work / "sample.wav"
    subtitle = work / "sample.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:00,500\nPackage verification\n", encoding="utf-8")
    compressed = work / "sample.7z"
    run("7zz", "a", compressed, subtitle.name)
    assert "Package verification" in run("7zz", "x", "-so", compressed, subtitle.name)
    run("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000", "-t", "0.5",
        "-c:v", "ffv1", "-c:a", "pcm_s16le", source)
    run("ffmpeg", "-v", "error", "-i", source, "-vn", audio)
    run("python3", "-I", "-B", "-c", "import soundfile,sys; waveform,rate=soundfile.read(sys.argv[1]); "
        "assert rate == 48000 and len(waveform) == 24000", audio)
    flac = work / "sample.flac"
    run("flac", "--silent", "-o", flac, audio)
    run("fdkaac", "-m", "3", "-o", work / "sample.m4a", audio)
    run("ffmpeg", "-v", "error", "-i", audio, "-c:a", "libopus", work / "sample.opus")
    avc = work / "sample.264"
    run("x264", "--demuxer", "lavf", "--frames", "4", "--preset", "ultrafast", "--threads", "2",
        "-o", avc, source)
    meta = work / "sample.meta"
    meta.write_text(f'MUXOPT --vbr\nV_MPEG4/ISO/AVC, "{avc}", fps=24\n', encoding="utf-8")
    transport = work / "sample.m2ts"
    run("tsMuxeR", meta, transport)
    assert "h264" in run("ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=codec_name", "-of", "csv=p=0", transport).splitlines()

    script = work / "sample.vpy"
    script.write_text(f"""from pathlib import Path
import numpy as np
from numpy.random import default_rng
import mvsfunc
import vapoursynth as vs
assert Path(vs.__file__).resolve().is_relative_to({str(runtime)!r})
assert Path(np.__file__).resolve().is_relative_to({str(runtime)!r})
assert default_rng(1).integers(10) < 10
core = vs.core
for name in {tuple(manifest['plugins'].values())!r}:
    getattr(core, name)
core.num_threads = 2
sample = core.std.BlankClip(width=96, height=64, length=8, fpsnum=24, format=vs.YUV420P8, color=[72, 128, 128])
gray = core.resize.Point(core.std.ShufflePlanes(sample, 0, vs.GRAY), format=vs.GRAYS)
for result, size in (
    (gray.descale.Debicubic(64, 48), (64, 48)),
    (sample.grain.Add(var=4, seed=5), (96, 64)),
    (sample.bilateral.Bilateral(sigmaS=[1.5], sigmaR=[0.04]), (96, 64)),
    (sample.dfttest.DFTTest(sigma=3.0), (96, 64)),
    (sample.eedi2.EEDI2(field=0), (96, 128)),
    (sample.eedi3.eedi3(field=0, dh=True), (96, 128)),
    (sample.eedi3m.EEDI3(field=0, dh=True), (96, 128)),
    (sample.misc.AverageFrames(weights=[1, 2, 1]), (96, 64)),
    (sample.rgvs.RemoveGrain(mode=[1]), (96, 64)),
    (sample.sangnom.SangNomMod(order=1), (96, 64)),
    (sample.vivtc.VFM(order=1).vivtc.VDecimate(), (96, 64)),
):
    frame = result.get_frame(1)
    assert (frame.width, frame.height) == size
test = core.std.BlankClip(width=96, height=64, length=3, fpsnum=24, format=vs.RGBS)
assert core.ccd.CCD(test, threshold=4.0).get_frame(1).width == 96
test = core.std.BlankClip(width=96, height=64, length=3, fpsnum=24, format=vs.GRAY8, color=[71])
assert core.bm3d.Basic(test, sigma=[3.0]).get_frame(1).width == 96
assert bytes(test.zsmooth.RemoveGrain(mode=[1]).get_frame(0)[0])[0] == 71
clip = core.lsmas.LWLibavSource({str(source)!r}, cache=0)
super_clip = clip.mv.Super()
backward = super_clip.mv.Analyse(isb=True)
forward = super_clip.mv.Analyse(isb=False)
assert clip.mv.Degrain1(super_clip, backward, forward).get_frame(3).width == clip.width
clip = core.fmtc.bitdepth(clip, bits=16)
assert clip.znedi3.nnedi3(field=0, dh=True).get_frame(0).height == clip.height * 2
clip = core.nlm_ispc.NLMeans(clip, d=0, a=2, s=2, h=0.6, channels="Y", wmode=3)
clip = core.fmtc.bitdepth(clip, bits=10)
core.assrender.TextSub(clip, {str(subtitle)!r}).set_output()
""", encoding="utf-8")
    frames = work / "sample.y4m"
    run("vspipe", "--container", "y4m", script, frames)
    hevc = work / "sample.hevc"
    run("x265", "--y4m", "--input", frames, "--output", hevc, "--preset", "ultrafast", "--pools", "2",
        "--frame-threads", "1", "--output-depth", "10")
    target = work / "output.mkv"
    run("mkvmerge", "-o", target, "--default-duration", "0:24fps", hevc, flac, subtitle)
    run("mkvinfo", "--summary", target)
    run("mkvpropedit", target, "--edit", "info", "--set", "title=BluraySubtitle")
    extracted = work / "extracted.srt"
    run("mkvextract", target, "tracks", f"2:{extracted}")
    assert "Package verification" in extracted.read_text(encoding="utf-8-sig")
    streams = json.loads(run("ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", target))["streams"]
    assert [s["codec_name"] for s in streams] == ["hevc", "flac", "subrip"]
    assert (streams[0]["pix_fmt"], streams[0]["nb_read_frames"]) == ("yuv420p10le", "12")
    av1 = work / "sample.ivf"
    run("SvtAv1EncApp", "-i", frames, "-b", av1, "--input-depth", "10", "--preset", "12", "--lp", "2")
    streams = json.loads(run("ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", av1))["streams"]
    assert (streams[0]["codec_name"], streams[0]["pix_fmt"], streams[0]["nb_read_frames"]) == ("av1", "yuv420p10le", "12")
    playback = work / "preview.vpy"
    playback.write_text("import vapoursynth\nvideo_in.set_output()\n", encoding="utf-8")
    run("mpv", "--no-config", "--vo=null", "--ao=null", "--frames=1", "--msg-level=all=warn",
        f"--vf=vapoursynth=file={playback}:buffered-frames=4:concurrent-frames=2", frames)
    if (runtime / "app").is_dir():
        run("python3", "-I", "-B", "-c", f"""from pathlib import Path
import sys
sys._bluray_freebsd_runtime = Path({str(runtime)!r})
sys.path.insert(0, str(sys._bluray_freebsd_runtime / 'app'))
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from src.runtime.program_update import update_executable
assert update_executable() == sys._bluray_freebsd_runtime.parent / 'BluraySubtitle'
app = QApplication([])
window = BluraySubtitleGUI()
assert not window._app_config_errors, window._app_config_errors
window._startup_update_notice.set_check_enabled(False)
window.show()
app.processEvents()
assert window.isVisible()
QTimer.singleShot(0, app.quit)
app.exec()
""")
    print("FreeBSD media, plugin and Qt verification passed.", flush=True)


def verify_package(package: Path):
    with tempfile.TemporaryDirectory(prefix="bluraysubtitle-freebsd-check-") as temporary:
        verify_runtime(package / "_internal", Path(temporary))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="bluraysubtitle-freebsd-archive-") as temporary:
        directory = Path(temporary)
        with tarfile.open(sys.argv[1], "r:xz") as archive:
            archive.extractall(directory, filter="data")
        verify_runtime(directory / "BluraySubtitle/_internal", directory)
