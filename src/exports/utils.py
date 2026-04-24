"""Utility/helper exports used across workflows."""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

import numpy as np
import soundfile

from ..core.i18n import translate_text

if sys.platform == 'win32':
    import winreg

from ..core import get_mkvtoolnix_ui_language, FFMPEG_PATH, FFPROBE_PATH
from ..core import mkvtoolnix_ui_language_arg


def get_folder_size(folder_path: str) -> str:
    byte = 0
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            byte += os.path.getsize(os.path.join(root, file))
    units = {'B': 0, 'KiB': 1, 'MiB': 2, 'GiB': 3, 'TiB': 6, 'PiB': 9}
    for unit, digits in units.items():
        if byte >= 1024:
            byte /= 1024
        else:
            return f'{round(byte, digits)} {unit}'


def get_time_str(duration: float) -> str:
    if duration == 0:
        return '0'
    try:
        duration = float(duration)
    except Exception:
        duration = 0.0
    hours, dur = divmod(duration, 3600.0)
    minutes, seconds = divmod(dur, 60.0)
    seconds = round(seconds, 3)
    if seconds >= 60.0:
        seconds -= 60.0
        minutes += 1.0
    if minutes >= 60.0:
        minutes -= 60.0
        hours += 1.0
    hs = f'{int(hours):02d}'
    ms = f'{int(minutes):02d}'
    ss = f'{seconds:06.3f}'
    return f'{hs}:{ms}:{ss}'


def format_ogm_chapter_timestamp(seconds: float) -> str:
    """Timestamp for OGM/Matroska simple chapter files: always ``HH:MM:SS.mmm``; zero is ``00:00:00.000``."""
    try:
        seconds = float(seconds)
    except Exception:
        seconds = 0.0
    if seconds <= 0.0:
        return '00:00:00.000'
    ts = get_time_str(seconds)
    return '00:00:00.000' if ts == '0' else ts


def append_ogm_chapter_lines(lines: list[str], chapter_index: int, time_seconds: float) -> None:
    """Append one chapter entry: ``CHAPTER01=00:00:00.000`` and ``CHAPTER01NAME=Chapter 01`` (1-based index)."""
    n = max(1, int(chapter_index))
    sid = f'{n:02d}'
    ts = format_ogm_chapter_timestamp(time_seconds)
    lines.append(f'CHAPTER{sid}={ts}')
    lines.append(f'CHAPTER{sid}NAME=Chapter {sid}')

def get_index_to_m2ts_and_offset(chapter) -> tuple[dict[int, str], dict[int, float]]:
    j = 1
    rows = sum(map(len, chapter.mark_info.values()))
    index_to_m2ts = {}
    index_to_offset = {}
    offset = 0
    for ref_to_play_item_id, mark_timestamps in chapter.mark_info.items():
        for mark_timestamp in mark_timestamps:
            index_to_m2ts[j] = chapter.in_out_time[ref_to_play_item_id][0] + '.m2ts'
            off = offset + (mark_timestamp -
                            chapter.in_out_time[ref_to_play_item_id][1]) / 45000
            index_to_offset[j] = off
            j += 1
        offset += (chapter.in_out_time[ref_to_play_item_id][2] -
                   chapter.in_out_time[ref_to_play_item_id][1]) / 45000
        index_to_offset[rows + j] = offset
    return index_to_m2ts, index_to_offset


def force_remove_folder(path):
    if sys.platform == 'win32':
        FILE_ATTRIBUTE_NORMAL = 0x80
        SetFileAttributesW = ctypes.windll.kernel32.SetFileAttributesW
        SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        SetFileAttributesW.restype = ctypes.c_int
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                SetFileAttributesW(os.path.join(root, name), FILE_ATTRIBUTE_NORMAL)
            for name in dirs:
                SetFileAttributesW(os.path.join(root, name), FILE_ATTRIBUTE_NORMAL)
        SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL)
        long_path = r'\\?\\' + os.path.abspath(path)
        shutil.rmtree(long_path, ignore_errors=True)
    else:
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)


def force_remove_file(file_path):
    if sys.platform == 'win32':
        FILE_ATTRIBUTE_NORMAL = 0x80
        SetFileAttributesW = ctypes.windll.kernel32.SetFileAttributesW
        SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        SetFileAttributesW.restype = ctypes.c_int
        long_path = r'\\?\\' + os.path.abspath(file_path)
        SetFileAttributesW(long_path, FILE_ATTRIBUTE_NORMAL)
        os.remove(long_path)
    else:
        if os.path.exists(file_path):
            os.remove(file_path)


def get_mpv_safe_path(extension=".mp4"):
    def clean(path):
        if not path: return None
        path = os.path.expandvars(path).strip()
        if '"' in path:
            path = path.split('"')[1]
        else:
            path = path.split(' ')[0]
        if not os.path.isabs(path):
            path = shutil.which(path)
        return path if path and os.path.exists(path) else None

    try:
        choice_path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{extension}\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, choice_path) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")

        if prog_id.startswith("AppX") or "WMP11" in prog_id or "Windows.Photos" in prog_id:
            return None

        base_name = prog_id.split('\\')[-1]  # Remove registry path prefix.
        names_to_try = [base_name]
        if not base_name.lower().endswith(".exe"):
            names_to_try.append(base_name + ".exe")
        if "mpv" in base_name.lower() and "mpv.exe" not in names_to_try:
            names_to_try.append("mpv.exe")

        for name in names_to_try:
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{name}\shell\open\command") as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    res = clean(val)
                    if res:
                        return res
            except:
                pass

            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"Applications\{name}\shell\open\command") as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    res = clean(val)
                    if res:
                        return res
            except:
                pass

            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    res = clean(val)
                    if res:
                        return res
            except:
                pass

    except Exception:
        pass

    return None


def fix_audio_delay_to_lossless(input_file, delay_ms, output_file, track_index=0):
    """Apply audio delay correction while preserving lossless output when possible."""
    # Quote paths to safely handle whitespace.
    input_file_q = f'"{input_file}"'
    output_file_q = f'"{output_file}"'

    ext = os.path.splitext(output_file)[1].lower()
    codec = "pcm_s24le"
    if ext in [".truehd", ".mlp"]:
        codec = "truehd"
    elif ext == ".flac":
        codec = "flac"

    map_str = f"-map 0:a:{track_index}"
    codec_str = f"-c:a {codec}"
    common_opts = "-hide_banner -loglevel error -y"

    if delay_ms > 0:
        # Positive delay: pad with silence.
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} {map_str} -af "adelay={delay_ms}:all=1" {codec_str} {output_file_q}'

    elif delay_ms < 0:
        # Negative delay: trim from the start.
        start_time = abs(delay_ms) / 1000.0
        # Keep -ss after -i for decode-level accuracy on HD audio codecs.
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} -ss {start_time} {map_str} {codec_str} {output_file_q}'

    else:
        # No delay.
        cmd = f'"{FFMPEG_PATH}" {common_opts} -i {input_file_q} {map_str} {codec_str} {output_file_q}'

    try:
        print(f"Run command: {cmd}")
        subprocess.run(cmd, shell=True, check=True)
        print(f"Completed: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e}")


def get_effective_bit_depth(file_path):
    if soundfile is None:
        return 24
    info = soundfile.info(file_path)
    frames = min(int(info.frames), int(info.samplerate) * 10)
    start = int(info.frames) // 2 if int(info.frames) > (frames * 2) else 0
    data, sr = soundfile.read(file_path, start=start, frames=frames, dtype='int32')
    return 16 if np.all(data % 65536 == 0) else 24


def get_audio_duration(file_path):
    """Return total audio duration in seconds using probed metadata."""
    cmd = f'"{FFPROBE_PATH}" -v error -show_entries format=duration:stream=duration -of json "{file_path}"'
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8')
    except Exception:
        return 0.0
    if proc.returncode != 0 or not (proc.stdout or '').strip():
        return 0.0
    try:
        data = json.loads(proc.stdout)
    except Exception:
        return 0.0
    try:
        duration = (data.get('format') or {}).get('duration')
        if duration not in (None, '', 'N/A'):
            return float(duration)
    except Exception:
        pass
    try:
        streams = data.get('streams') or []
        if streams:
            duration = (streams[0] or {}).get('duration')
            if duration not in (None, '', 'N/A'):
                return float(duration)
    except Exception:
        pass
    return 0.0


def get_compressed_effective_depth(file_path, check_duration=10):
    """Estimate effective bit depth from a middle sample window of compressed audio."""
    if soundfile is None:
        return 24
    total_duration = get_audio_duration(file_path)
    start_time = total_duration / 2 if total_duration > (check_duration * 2) else 0.0
    fd, temp_wav = tempfile.mkstemp(prefix=f"temp_depth_check_{os.getpid()}_", suffix=".wav")
    os.close(fd)

    try:
        cmd = f'"{FFMPEG_PATH}" -hide_banner -loglevel error -ss {start_time} -i "{file_path}" -t {check_duration} -map 0:a:0 -c:a pcm_s24le "{temp_wav}" -y'
        subprocess.run(cmd, shell=True, check=True)
        data, sr = soundfile.read(temp_wav, dtype='int32')
        is_16bit = np.all(data % 65536 == 0)
        return 16 if is_16bit else 24
    finally:
        if os.path.exists(temp_wav):
            os.remove(temp_wav)


def get_vspipe_context():
    """
    Resolve bundled vspipe path and runtime environment for nested package layout.
    """
    # 1) Resolve extracted bundle root.
    bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath("."))

    # 2) Locate nested release folder.
    # Expected layout: _MEIPASS/vs_pkg/vspipe(.exe)
    vs_pkg_dir = os.path.join(bundle_dir, "vs_pkg")

    # 3) Build environment.
    env = os.environ.copy()

    # Remove parent-process Python variables to avoid runtime conflicts.
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)

    if sys.platform == 'win32':
        vspipe_exe = os.path.join(vs_pkg_dir, "vspipe.exe")
        # python313.dll is in vs_pkg root; add it to PATH.
        env['PATH'] = f"{vs_pkg_dir};{env.get('PATH', '')}"
        # Point vspipe to the embedded Python home.
        env['PYTHONHOME'] = vs_pkg_dir
        # Plugin directory mirrors original release-x64 structure.
        env['VAPOURSYNTH_PLUGINS'] = os.path.join(vs_pkg_dir, "vapoursynth64", "coreplugins")

    else:  # Linux
        vspipe_exe = os.path.join(vs_pkg_dir, "vspipe")
        env['LD_LIBRARY_PATH'] = f"{vs_pkg_dir}:{env.get('LD_LIBRARY_PATH', '')}"
        env['PYTHONHOME'] = vs_pkg_dir
        env['PATH'] = f"{vs_pkg_dir}:{env.get('PATH', '')}"
        # Assume Linux plugin structure is consistent.
        env['VAPOURSYNTH_PLUGINS'] = os.path.join(vs_pkg_dir, "plugins")

    return vspipe_exe, env


def print_terminal_line(message: str) -> None:
    print(translate_text(message), file=_terminal_err_stream(), flush=True)


def print_exc_terminal() -> None:
    s = traceback.format_exc()
    if not s or s.strip() == 'NoneType: None':
        return
    print_tb_string_terminal(s, with_header=True)


def print_tb_string_terminal(tb: str, *, with_header: bool = True) -> None:
    out = _terminal_err_stream()
    if with_header:
        print(translate_text('[BluraySubtitle] --- traceback (copy from terminal) ---'), file=out, flush=True)
    for line in (tb or '').rstrip().split('\n'):
        print(line, file=out, flush=True)


__all__ = [
    "get_mkvtoolnix_ui_language",
    "mkvtoolnix_ui_language_arg",
    "get_folder_size",
    "get_time_str",
    "format_ogm_chapter_timestamp",
    "append_ogm_chapter_lines",
    "get_index_to_m2ts_and_offset",
    "force_remove_folder",
    "force_remove_file",
    "get_mpv_safe_path",
    "fix_audio_delay_to_lossless",
    "get_effective_bit_depth",
    "get_audio_duration",
    "get_compressed_effective_depth",
    "get_vspipe_context",
    "print_terminal_line",
    "print_exc_terminal",
    "print_tb_string_terminal",
]

