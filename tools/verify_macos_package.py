"""Verify the extracted macOS release with its native libraries, plugins and media tools."""

import json
import os
import platform
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_ass_extension import VERIFY_ASS_EXTENSION
from tools.macos_build_support import digest, message, run
from tools.macos_macho import inspect_macho

from tools.vapoursynth_plugin_releases import R79_PLUGIN_NAMESPACES


def verify_runtime(runtime):
    runtime = runtime.resolve(strict=True)
    manifest = json.loads((runtime / "runtime.json").read_text())
    arch = platform.machine()
    if manifest["architecture"] != arch:
        raise ValueError(f"Package is for {manifest['architecture']}, host is {arch}")
    for file in runtime.rglob("*"):
        if file.is_symlink():
            if not file.resolve(strict=True).is_relative_to(runtime):
                raise ValueError(f"External bundle symlink: {file}")
            continue
        if not file.is_file():
            continue
        info = inspect_macho(file, arch)
        if not info:
            continue
        threshold = (
            tuple(manifest["latest_qt_minimum"]) if file.is_relative_to(runtime / "qt/latest") else (11, 0, 0)
        )
        if info.minimum > threshold:
            raise ValueError(f"Deployment target {info.minimum} in {file}")
        for dep in info.loads:
            if dep.startswith(("/usr/lib/", "/System/Library/")):
                continue
            if not dep.startswith("@loader_path/"):
                raise ValueError(f"External load command {dep} in {file}")
            path = (file.parent / dep.removeprefix("@loader_path/")).resolve(strict=True)
            if not path.is_relative_to(runtime):
                raise ValueError(f"Dependency outside the bundle: {path}")

    with tempfile.TemporaryDirectory(prefix="BluraySubtitle media ") as tmp:
        work = Path(tmp)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("DYLD_", "QT_", "PYTHON", "VAPOURSYNTH", "VSSCRIPT"))
        }
        env.update(
            PATH="/usr/bin:/bin:/usr/sbin:/sbin",
            HOME=str(work),
            LANG="en_US.UTF-8",
            VAPOURSYNTH_EXTRA_PLUGIN_PATH=str(runtime / "plugins"),
            VK_DRIVER_FILES=str(runtime / "share/vulkan/icd.d/MoltenVK_icd.json"),
        )

        def execute(name, *args):
            result = subprocess.run(
                [runtime / "bin" / name, *map(str, args)],
                cwd=work,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
            )
            if result.returncode:
                raise RuntimeError(f"{name} {args} exited {result.returncode}: {result.stdout[-4500:]}")
            return result.stdout

        encoders = {line.split()[1] for line in execute("ffmpeg", "-hide_banner", "-encoders").splitlines()
                    if line.strip().startswith("V") and len(line.split()) > 1}
        if not {"h264_videotoolbox", "hevc_videotoolbox", "prores_videotoolbox", "ffv1_vulkan"} <= encoders:
            raise ValueError("FFmpeg is missing VideoToolbox or Vulkan encoders")
        if execute("bluraysub-gpu-capabilities", "--version").strip() != "2":
            raise ValueError("The packaged GPU capability query failed its version check")
        info = execute("vspipe", "--version")
        if "Core R79" not in info or "API R3" not in info:
            raise ValueError(info)
        for name, flag in (
            ("7zz", "i"),
            ("dovi_tool", "--version"),
            ("hdr10plus_tool", "--version"),
            ("tsMuxeR", "--version"),
            ("mkvinfo", "--version"),
            ("mkvextract", "--version"),
            ("mkvpropedit", "--version"),
            ("vsedit", "--version"),
        ):
            execute(name, flag)
        execute(
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x72:rate=24",
            "-frames:v",
            "4",
            "-c:v",
            "ffv1",
            "source.mkv",
        )
        (work / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n")
        script = work / "test.vpy"
        script.write_text(
            "import vapoursynth as vs\ncore = vs.core\n"
            f"assert {set(R79_PLUGIN_NAMESPACES.values())!r} <= {{p.namespace for p in core.plugins()}}\n"
            f"c = core.lsmas.LWLibavSource({str(work / 'source.mkv')!r}, cache=0)\n"
            "c = core.bilateral.Bilateral(c).rgvs.RemoveGrain(mode=[1]).zsmooth.RemoveGrain(mode=[1])\n"
            "c = core.nlm_ispc.NLMeans(c, d=0, a=2, s=2, h=0.6, channels='Y', wmode=3)\n"
            f"c = core.assrender.TextSub(c, {str(work / 'subtitle.srt')!r})\n"
            "core.fmtc.bitdepth(c, bits=10).set_output()\n"
        )
        execute("vspipe", "--container", "y4m", script, "frames.y4m")
        execute(
            "x265",
            "--y4m",
            "--input",
            "frames.y4m",
            "--output-depth",
            "10",
            "--preset",
            "ultrafast",
            "-o",
            "main.hevc",
        )
        execute("x264", "--demuxer", "y4m", "--preset", "ultrafast", "-o", "main.264", "frames.y4m")
        execute("SvtAv1EncApp", "-i", "frames.y4m", "-b", "main.ivf", "--input-depth", "10", "--preset", "12")
        execute("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=0.25", "audio.wav")
        execute(
            runtime / "python/bin/python3",
            "-I",
            "-B",
            "-c",
            VERIFY_ASS_EXTENSION + "\n"
            "from concurrent.futures import ProcessPoolExecutor\n"
            "import numpy as np, soundfile as sf, psutil, pycountry\n"
            "from PIL import Image\n"
            "samples, rate = sf.read('audio.wav')\n"
            "assert rate > 0 and np.dot(samples, samples) > 0\n"
            "assert Image.fromarray(np.zeros((8, 8), dtype=np.uint8)).size == (8, 8)\n"
            "assert psutil.virtual_memory().total and pycountry.languages.get(alpha_2='en')\n"
            "with ProcessPoolExecutor(1) as pool: assert pool.submit(sum, [1,2,3]).result(30) == 6",
        )
        execute("flac", "-s", "-o", "audio.flac", "audio.wav")
        execute("fdkaac", "-b", "96000", "-o", "audio.m4a", "audio.wav")
        execute("mkvmerge", "-o", "result.mkv", "main.hevc", "audio.m4a", "subtitle.srt")
        summary = json.loads(execute("ffprobe", "-v", "error", "-show_streams", "-of", "json", "result.mkv"))
        if {s["codec_name"] for s in summary["streams"]} != {"hevc", "aac", "subrip"}:
            raise ValueError("Unexpected streams in the verification remux")
        print(
            message("R79, API 3/4 filters, 10-bit HEVC, AVC, AV1, AAC, FLAC and subtitle remux passed."),
            flush=True,
        )


def verify_archive(archive):
    record = Path(str(archive) + ".txt").read_text().splitlines()
    if "sha256=" + digest(archive) not in record:
        raise ValueError("Archive checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="BluraySubtitle relocated ") as tmp:
        work = Path(tmp)
        run("ditto", "-x", "-k", archive, work)
        app = work / "BluraySubtitle.app"
        runtime = app / "Contents/Resources/Runtime"
        run("codesign", "--verify", "--deep", "--strict", app)
        executable = app / "Contents/MacOS/BluraySubtitle"
        with (app / "Contents/Info.plist").open("rb") as stream:
            icon = app / "Contents/Resources" / plistlib.load(stream)["CFBundleIconFile"]
        if icon.read_bytes()[:4] != b"icns":
            raise ValueError("Missing Finder icon")
        for filename in ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.zh-Hans.md"):
            notices = (runtime / "legal" / filename).read_text(encoding="utf-8")
            if not all(term in notices for term in ("Haruite", "MIT", "## 7-Zip", "## FFmpeg / FFprobe", "VapourSynth", "PyQt6", "libass", "plugins/libznedi3.dylib")):
                raise ValueError(f"Incomplete notices: {filename}")
        for tool in ("tools/macos_entry.py", "tools/macos_update.py", "tools/macos_finish_update.sh", "src/runtime/macos_files.js"):
            if not (runtime / "app" / tool).is_file():
                raise FileNotFoundError(tool)
        for item, required in ((app, 0o555), (executable, 0o555), (app / "Contents/Info.plist", 0o444)):
            if item.stat().st_mode & required != required:
                raise ValueError(f"Application permissions prevent shared use: {item}")
        launcher = inspect_macho(executable, platform.machine())
        if not launcher or launcher.minimum > (11, 0, 0):
            raise ValueError(f"Invalid macOS 11 launcher: {executable}")
        verify_runtime(runtime)
        run("codesign", "--verify", "--deep", "--strict", app)


if __name__ == "__main__":
    verify_archive(Path(sys.argv[1]).resolve())
