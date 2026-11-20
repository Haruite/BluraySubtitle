"""Exercise the tools in a relocated Linux package with a clean environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.linux_runtime_libs import kernel_requirement
from tools.mpv.install import LAZY_MENU, SHADER_PATH, SHADERS
from tools.mpv.vapoursynth.rife_assets import RIFE_FILES


def verify_xz_compatibility(archive: Path) -> None:
    listing = subprocess.check_output(["xz", "--robot", "-lvv", "--", archive], text=True)
    summary = next(line.split("\t") for line in listing.splitlines() if line.startswith("summary\t"))
    # The fourth summary column is the minimum decoder version in liblzma's numeric format.
    if int(summary[3]) > 50_000_002:
        raise RuntimeError("The package requires a newer decoder than XZ Utils 5.0.0")


def verify_native_binaries(bundle: Path) -> None:
    platform = sysconfig.get_platform()
    machine = {"linux-x86_64": 62, "linux-aarch64": 183}[platform]
    launcher = bundle / "BluraySubtitle"
    if not launcher.is_file() or launcher.is_symlink():
        raise RuntimeError("Missing packaged BluraySubtitle executable")
    if not launcher.read_bytes().startswith(b"#!/bin/sh\n"):
        raise RuntimeError("Missing portable shell launcher")
    bootloader = bundle / "_internal/BluraySubtitle"
    if not bootloader.is_file():
        raise RuntimeError("Missing PyInstaller bootloader")
    latest = bundle / "_internal/linux/qt/latest"
    for file in bundle.rglob("*"):
        if file.is_symlink() or not file.is_file():
            continue
        with file.open("rb") as stream:
            header = stream.read(20)
        if file != bootloader and not header.startswith(b"\x7fELF"):
            continue
        if not header.startswith(b"\x7fELF\x02\x01") or int.from_bytes(header[18:20], "little") != machine:
            raise RuntimeError(f"Expected a native {platform} binary: {file.relative_to(bundle)}")
        if not file.is_relative_to(latest) and kernel_requirement(file, note_required=False) > (3, 17, 0):
            raise RuntimeError(f"ELF ABI exceeds Linux 3.17: {file.relative_to(bundle)}")


def verify_gui_branches(bundle: Path, work: Path, env: dict[str, str]) -> None:
    support = bundle / "_internal"
    minimum = support / "linux/qt/latest/minimum-kernel"
    original = minimum.read_bytes()
    config = json.loads((support / "config.default.json").read_text(encoding="utf-8"))
    config["ui"].update(check_updates_on_startup=False, close_to_tray=False)
    (work / "config/config.json").write_text(json.dumps(config), encoding="utf-8")
    try:
        # Exercise both paths through the real launcher, using only this disposable extraction.
        for branch, threshold in (("latest", b"0 0 0\n"), ("6.6", b"999 0 0\n")):
            minimum.write_bytes(threshold)
            ready = work / f"gui-ready-{branch}"
            with (work / f"gui-{branch}.log").open("w+") as log, subprocess.Popen(
                [bundle / "BluraySubtitle", "--foreground"], cwd=work,
                env={**env, "BLURAY_SUBTITLE_UPDATE_READY": str(ready)}, stdout=log, stderr=subprocess.STDOUT,
            ) as app:
                try:
                    deadline = time.monotonic() + 25
                    while not ready.is_file() and app.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.1)
                    if not ready.is_file() or app.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(f"Qt {branch} GUI startup failed: {log.read()}")
                    maps = Path(f"/proc/{app.pid}/maps").read_text()
                    for library in ("linux/glibc/libc.so.6", f"linux/qt/{branch}/PyQt6/Qt6/lib/libQt6Core.so.6"):
                        assert str(support / library) in maps, library
                finally:
                    if app.poll() is None:
                        app.terminate()
                        try:
                            app.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            app.kill()
    finally:
        minimum.write_bytes(original)


def verify(bundle: Path, work: Path) -> None:
    verify_native_binaries(bundle)
    support = bundle / "_internal"
    settings_source = support / "src/core/settings.py"
    compile(settings_source.read_text(encoding="utf-8"), str(settings_source), "exec")
    legal = support / "legal"
    plugin_directory = support / "linux/plugins"
    for name in (*RIFE_FILES, "libvs_placebo.so"):
        file = plugin_directory / name
        if not file.is_file() or not file.stat().st_size:
            raise RuntimeError(f"Missing packaged VapourSynth component: {name}")
    plugins = {file.name for file in plugin_directory.glob("*.so")}
    assert (support / "tools/linux_update.py").is_file()
    commit = (support / "build-commit.txt").read_text(encoding="utf-8").splitlines()
    assert len(commit) == 2 and commit[0].startswith("commit=") and commit[1].startswith("commit_time=")
    for filename in ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.zh-Hans.md"):
        notice = (legal / filename).read_text(encoding="utf-8")
        if "{{" in notice or any(f"## {heading}" not in notice for heading in ("7-Zip", "FFmpeg", "mpv")):
            raise RuntimeError(f"Incomplete bundled notice: {filename}")
        listed = {line.split("`linux/plugins/", 1)[1].split("`", 1)[0]
                  for line in notice.splitlines() if "`linux/plugins/" in line}
        if listed != plugins:
            raise RuntimeError(f"{filename} does not list the bundled VapourSynth plugins")
    if not (legal / "vapoursynth/COPYING.LESSER").stat().st_size:
        raise RuntimeError("Empty bundled VapourSynth license")
    if not (support / "mpv").is_dir():
        raise RuntimeError("Missing bundled mpv configuration directory")
    menu_directory = support / "resource/mpv"
    uosc_files = (
        "scripts/uosc/main.lua", "scripts/uosc/bin/ziggy-linux",
        "fonts/uosc_icons.otf", "fonts/uosc_textures.ttf",
    )
    if not all((menu_directory / name).stat().st_size for name in uosc_files):
        raise RuntimeError("Incomplete bundled uosc")
    if not (legal / "uosc/LICENSE.LGPL").stat().st_size:
        raise RuntimeError("Empty bundled uosc license")
    if not all((menu_directory / SHADER_PATH / name).stat().st_size for name, _ in SHADERS):
        raise RuntimeError("Incomplete bundled mpv-lazy shaders")
    menus = [(menu_directory / f"menu.{language}.conf").read_text(encoding="utf-8") for language in ("en", "zh")]
    if not all(menu.strip() for menu in menus) or menus[0] == menus[1]:
        raise RuntimeError("The bundled mpv menus must contain both languages")
    if any(LAZY_MENU not in menu.splitlines() for menu in menus):
        raise RuntimeError("The bundled mpv menus must include mpv-lazy")

    native = support / "linux"
    commands = native / "bin"
    for name in ("path", "home", "runtime", "xdg", "config"):
        (work / name).mkdir(mode=0o700)
    for tool in ("dirname", "readlink"):
        (work / "path" / tool).symlink_to(Path("/usr/bin") / tool)
    env = {
        "PATH": str(work / "path"),
        "HOME": str(work / "home"),
        "LANG": "C.UTF-8",
        "QT_QPA_PLATFORM": "offscreen",
        "XDG_RUNTIME_DIR": str(work / "runtime"),
        "XDG_CONFIG_HOME": str(work / "xdg"),
        "XDG_CACHE_HOME": str(work / "cache"),
        "BLURAY_SUBTITLE_CONFIG_DIR": str(work / "config"),
    }

    verify_gui_branches(bundle, work, env)
    subprocess.run(
        [native / "python/bin/python3", "-c",
         "import vapoursynth as vs\n"
         "clip = vs.core.std.BlankClip(width=64, height=32, format=vs.GRAY8, color=[71])\n"
         "assert bytes(clip.zsmooth.RemoveGrain(mode=[1]).get_frame(0)[0])[0] == 71"],
        cwd=work, env=env, check=True, timeout=30,
    )
    # The build host's installed locales must not mask a failure on musl or NixOS.
    subprocess.run(
        [commands / "mkvmerge", "--version"], cwd=work,
        env={**env, "LC_ALL": "zz_ZZ.UTF-8", "LOCPATH": str(work / "absent-locales")},
        check=True, capture_output=True, timeout=15,
    )

    def run(tool, *args, audit=False):
        process = subprocess.run(
            [commands / tool, *args], cwd=work, env={**env, **({"LD_DEBUG": "libs"} if audit else {})},
            text=True, encoding="utf-8", errors="replace", capture_output=True, stdin=subprocess.DEVNULL, timeout=30,
        )
        if process.returncode:
            raise RuntimeError(f"{tool} returned {process.returncode}\n{process.stdout}\n{process.stderr[-5000:]}")
        if audit:
            for line in process.stderr.splitlines():
                if "calling init: " in line:
                    loaded = line.split("calling init: ", 1)[1].strip()
                    if loaded.startswith(("/usr/local/", "/home/")) and not Path(loaded).resolve().is_relative_to(support):
                        raise RuntimeError(f"{tool} loaded a host runtime library: {loaded}")
        return process.stdout, process.stderr

    _, trace = run("mpv", "--no-config", "--ao=pipewire", "--audio-device=help", audit=True)
    client = native / "pipewire"
    modules = {Path(line.split("calling init: ", 1)[1].strip()) for line in trace.splitlines()
               if "calling init: " in line and ("/spa-0.2/" in line or "/pipewire-0.3/libpipewire-module-" in line)}
    required = {
        client / "spa-0.2/support/libspa-support.so", client / "pipewire-0.3/libpipewire-module-protocol-native.so",
    }
    if not required.issubset(modules) or any(not path.is_relative_to(client) for path in modules):
        raise RuntimeError(f"mpv did not enumerate audio devices with the packaged PipeWire client modules: {modules}")

    media_libraries = {}
    for tool in ("mpv", "ffmpeg", "ffprobe"):
        _, trace = run(tool, "--version" if tool == "mpv" else "-version", audit=True)
        va_libraries = [Path(line.split("calling init: ", 1)[1].strip())
                        for line in trace.splitlines() if "calling init: " in line and "/libva.so." in line]
        if not va_libraries or not all(path.resolve().is_relative_to(support) for path in va_libraries):
            raise RuntimeError(f"{tool} requires the packaged libva: {va_libraries}")
        codec_libraries = {
            Path(line.split("calling init: ", 1)[1].strip())
            for line in trace.splitlines()
            if "calling init: " in line and "/libavcodec.so." in line
        }
        if len(codec_libraries) != 1:
            raise RuntimeError(f"{tool} did not load exactly one FFmpeg codec library")
        codec = codec_libraries.pop()
        if not codec.is_relative_to(support):
            raise RuntimeError(f"{tool} loaded FFmpeg outside the package: {codec}")
        media_libraries[tool] = codec
    if len(set(media_libraries.values())) != 1:
        raise RuntimeError(f"The playback tools use different FFmpeg libraries: {media_libraries}")
    apis = run("mpv", "--no-config", "--gpu-api=help")[0].splitlines()
    if not any(line.split(maxsplit=1)[:1] == ["vulkan"] for line in apis):
        raise RuntimeError("Packaged mpv does not support Vulkan")
    hwaccels = run("ffmpeg", "-hide_banner", "-hwaccels")[0].splitlines()
    if "vulkan" not in hwaccels:
        raise RuntimeError("Packaged FFmpeg does not support Vulkan")

    assert "Core R79" in "".join(run("vspipe", "--version"))
    assert "VapourSynth Editor" in "".join(run("vsedit", "--version"))
    assert "7-Zip" in "".join(run("7zz", "i"))
    assert "tsMuxeR" in "".join(run("tsMuxeR", "--help"))
    for tool in ("x264", "dovi_tool", "hdr10plus_tool"):
        assert any(run(tool, "--version"))

    source = work / "source.mkv"
    audio = work / "sample.wav"
    text = work / "sample.srt"
    text.write_text("1\n00:00:00,000 --> 00:00:00,500\nPackage verification\n", encoding="utf-8")
    run("ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000", "-t", "0.5",
        "-c:v", "ffv1", "-c:a", "pcm_s16le", source, audit=True)
    run("ffmpeg", "-hide_banner", "-loglevel", "error", "-i", source, "-vn", audio)
    avc = work / "lavf.h264"
    run("x264", "--demuxer", "lavf", "--frames", "4", "--preset", "ultrafast", "--threads", "2", "-o", avc, source)
    count, _ = run("ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                   "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", avc)
    assert count.strip() == "4", count
    flac = work / "sample.flac"
    aac = work / "sample.m4a"
    opus = work / "sample.opus"
    run("flac", "--silent", "-o", flac, audio)
    run("fdkaac", "-m", "3", "-o", aac, audio)
    run("ffmpeg", "-hide_banner", "-loglevel", "error", "-i", audio, "-c:a", "libopus", opus)
    assert all(path.stat().st_size > 500 for path in (flac, aac, opus))

    runtime_assertions = f"""from pathlib import Path
import os
import sys
import fractions
import mvsfunc
import numpy as np
import vapoursynth as vs

support = Path({str(support)!r})
assert Path(sys.prefix) == support / "linux/python"
assert f"python{{sys.version_info.major}}{{sys.version_info.minor}}.zip" in fractions.__file__
for module in (mvsfunc, np, vs):
    assert Path(module.__file__).resolve().is_relative_to(support), module.__file__
mapped = {{line.split(maxsplit=5)[-1] for line in Path("/proc/self/maps").read_text().splitlines()
          if "/libpython3." in line}}
assert mapped == {{str(support / f"libpython{{sys.version_info.major}}.{{sys.version_info.minor}}.so.1.0")}}, mapped
assert str(support / "linux/glibc/libc.so.6") in Path("/proc/self/maps").read_text()
"""
    vpy = work / "smoke.vpy"
    vpy.write_text(runtime_assertions + f"""
vs.core.std.LoadAllPlugins(os.environ["BLURAYSUB_PLUGIN_PATH"])
assert vs.core.descale.Descale and vs.core.bm3d
assert vs.core.placebo.Deband and vs.core.rife.RIFE
clip = vs.core.lsmas.LWLibavSource({str(source)!r}, cache=0)
if os.uname().machine == "aarch64":
    frame = clip.sangnom.SangNomMod().zsmooth.RemoveGrain(mode=[1]).get_frame(3)
    assert (frame.width, frame.height) == (clip.width, clip.height)
super_clip = clip.mv.Super()
backward = super_clip.mv.Analyse(isb=True)
forward = super_clip.mv.Analyse(isb=False)
assert clip.mv.Degrain1(super_clip, backward, forward).get_frame(3).width == clip.width
clip = vs.core.fmtc.bitdepth(clip, bits=16)
assert clip.znedi3.nnedi3(field=0, dh=True).get_frame(0).height == clip.height * 2
clip = vs.core.nlm_ispc.NLMeans(clip, d=0, a=2, s=2, h=0.6, channels="Y", wmode=3)
clip = vs.core.fmtc.bitdepth(clip, bits=10)
vs.core.assrender.TextSub(clip, {str(text)!r}).set_output()
""", encoding="utf-8")
    frames = work / "sample.y4m"
    raw = work / "sample.hevc"
    output = work / "output.mkv"
    run("vspipe", "--container", "y4m", vpy, frames, audit=True)
    run("x265", "--y4m", "--input", frames, "--output", raw, "--preset", "ultrafast",
        "--pools", "2", "--frame-threads", "1", "--output-depth", "10", audit=True)
    run("mkvmerge", "--output", output, "--default-duration", "0:24fps", raw, flac, text, audit=True)
    run("mkvinfo", "--summary", output)
    run("mkvpropedit", output, "--edit", "info", "--set", "title=BluraySubtitle")
    extracted = work / "extracted.srt"
    run("mkvextract", output, "tracks", f"2:{extracted}")
    assert "Package verification" in extracted.read_text(encoding="utf-8-sig")
    data = json.loads(run("ffprobe", "-v", "error", "-count_frames", "-show_format", "-show_streams", "-of", "json", output)[0])
    assert [stream["codec_name"] for stream in data["streams"]] == ["hevc", "flac", "subrip"]
    assert data["streams"][0]["pix_fmt"] == "yuv420p10le"
    assert data["streams"][0]["nb_read_frames"] == "12"
    assert data["format"]["tags"]["title"] == "BluraySubtitle"
    av1 = work / "sample.ivf"
    run("SvtAv1EncApp", "-i", frames, "-b", av1, "--input-depth", "10", "--preset", "12",
        "--lp", "2", "--progress", "0", audit=True)
    streams = json.loads(run("ffprobe", "-v", "error", "-count_frames", "-show_entries",
                             "stream=codec_name,pix_fmt,nb_read_frames", "-of", "json", av1)[0])["streams"]
    assert streams == [{"codec_name": "av1", "pix_fmt": "yuv420p10le", "nb_read_frames": "12"}]
    print("R79, NumPy, NLM-ISPC, subtitle rendering, x265, SVT-AV1, FLAC/AAC/Opus and MKVToolNix passed.", flush=True)

    controls_probe = work / "mpv-controls.lua"
    controls_probe.write_text(
        """mp.add_timeout(0.5, function()
    local original_size = mp.get_property_number('sub-font-size')
    local applied = mp.commandv('apply-profile', 'mpv-lazy-subtitles')
        and mp.get_property_number('sub-font-size') ~= original_size
    local restored = mp.commandv('apply-profile', 'mpv-lazy-subtitles', 'restore')
        and mp.get_property_number('sub-font-size') == original_size
    mp.commandv('quit', applied and restored and mp.get_property_native('osc') == false and 0 or 1)
end)
""", encoding="utf-8",
    )
    run("mpv", "--idle=yes", "--force-window=no", "--vo=null", "--ao=null",
        "--osc=yes", f"--script={controls_probe}")
    context_options = (support / "mpv/script-opts/context_menu.conf").read_text(encoding="utf-8").splitlines()
    if "scale_with_window=no" not in context_options:
        raise RuntimeError("The bundled mpv context menu must scale with the display")

    mpv_script = work / "mpv.vpy"
    mpv_script.write_text(runtime_assertions + "\nvideo_in.set_output()\n", encoding="utf-8")
    mpv_log = work / "mpv.log"
    run("mpv", "--no-config", "--vo=null", "--ao=null", "--frames=1", "--no-terminal",
        "--no-osc", "--load-scripts=no", "--load-select=no", f"--log-file={mpv_log}",
        f"--vf=vapoursynth=file={mpv_script}:buffered-frames=4:concurrent-frames=2", frames, audit=True)
    assert "first video frame after restart shown" in mpv_log.read_text(encoding="utf-8")

    editor_log = work / "vsedit.log"
    editor_settings = work / "config/.vsscript/vsedit.config"
    with editor_log.open("w", encoding="utf-8") as log:
        editor = subprocess.Popen(
            [commands / "vsedit", vpy], cwd=work, env={**env, "LD_DEBUG": "libs"},
            stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            # VSEdit records the opened script in its recent files after loading it.
            deadline = time.monotonic() + 25
            while editor.poll() is None:
                if editor_settings.is_file() and vpy.name.encode() in editor_settings.read_bytes():
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"VSEdit did not open {vpy.name} before the timeout")
                time.sleep(0.1)
            else:
                raise RuntimeError(f"VSEdit exited with status {editor.returncode} while opening {vpy.name}")
        finally:
            if editor.poll() is None:
                editor.terminate()
            editor.wait(timeout=5)
    log_text = editor_log.read_text(encoding="utf-8", errors="replace")
    libpython, = support.glob("libpython3.*.so.1.0")
    editor_qt = native / "qt/6.6/PyQt6/Qt6"
    for library in (native / "glibc/libc.so.6", support / "vapoursynth/libvsscript.so", libpython,
                    editor_qt / "lib/libQt6Core.so.6", editor_qt / "plugins/platforms/libqoffscreen.so"):
        assert f"calling init: {library}" in log_text, library
    print("mpv and VSEdit loaded the packaged runtime.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    archive = parser.parse_args().archive
    verify_xz_compatibility(archive)
    with tempfile.TemporaryDirectory(prefix="bluraysubtitle-package-") as directory:
        work = Path(directory)
        relocated = work / "Relocated \u8def\u5f84"
        relocated.mkdir()
        with tarfile.open(archive, "r:xz") as package:
            package.extractall(relocated, filter="data")
        verify(relocated / "BluraySubtitle", work)
