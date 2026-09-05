"""Utility/helper exports used across workflows."""
import ctypes
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

import numpy as np
import soundfile

from ..core.i18n import translate_text, _terminal_err_stream

if sys.platform == 'win32':
    import winreg

from ..core import FFMPEG_PATH

_MKVMERGE_CANCEL_EVENT: ContextVar[object | None] = ContextVar(
    '_MKVMERGE_CANCEL_EVENT',
    default=None,
)


@contextmanager
def mkvmerge_cancellation_scope(cancel_event):
    """Make mkvmerge processes started in this task observe its cancel event."""
    token = _MKVMERGE_CANCEL_EVENT.set(cancel_event)
    try:
        yield
    finally:
        _MKVMERGE_CANCEL_EVENT.reset(token)


def _is_mkvmerge_mux_command(command) -> bool:
    if isinstance(command, str):
        try:
            arguments = shlex.split(command, posix=sys.platform != 'win32')
        except ValueError:
            return False
    else:
        arguments = list(command or [])
    if not arguments:
        return False
    executable = os.path.basename(str(arguments[0]).strip('"')).lower()
    return executable.startswith('mkvmerge') and any(
        str(argument) in ('-o', '--output') for argument in arguments[1:]
    )


def _terminate_process_tree(process) -> None:
    if process.poll() is not None:
        return
    if sys.platform == 'win32':
        try:
            subprocess.run(
                ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            pass
    try:
        process.wait(timeout=0.5)
        return
    except subprocess.TimeoutExpired:
        pass
    if sys.platform != 'win32':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass


def mkv_codec_id_is_dts_family(codec_id: str) -> bool:
    """
    True for Matroska DTS / DTS-HD (MA, HR, …) as reported by mkvinfo.
    Common values include ``A_DTS`` and ``A_MS/DTS``; the latter is not matched by ``startswith('A_DTS')``.
    """
    cid = str(codec_id or '').strip().upper()
    return bool(cid.startswith('A_') and 'DTS' in cid)


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


def parse_time_to_seconds(value: object, default: Optional[float] = 0.0) -> Optional[float]:
    """Parse a colon-separated time value, accepting hours, minutes, or seconds."""
    try:
        result = 0.0
        parts = [part for part in str(value or '').strip().split(':') if part]
        if not parts:
            return default
        for part in parts:
            result = result * 60.0 + float(part)
        return result
    except (TypeError, ValueError):
        return default


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
    """
    Map 1-based chapter indices to m2ts stem and playlist offset (seconds).

    Play items must be walked in **playlist order** (``in_out_time`` indices). Iterating
    ``mark_info`` dict keys alone is wrong when marks appear out of strict key order in the MPLS.
    """
    j = 1
    rows = sum(map(len, chapter.mark_info.values()))
    index_to_m2ts: dict[int, str] = {}
    index_to_offset: dict[int, float] = {}
    offset = 0.0
    for ref_to_play_item_id in range(len(chapter.in_out_time)):
        mark_timestamps = chapter.mark_info.get(ref_to_play_item_id) or []
        in_t = chapter.in_out_time[ref_to_play_item_id][1]
        out_t = chapter.in_out_time[ref_to_play_item_id][2]
        stem = chapter.in_out_time[ref_to_play_item_id][0] + '.m2ts'
        for mark_timestamp in mark_timestamps:
            index_to_m2ts[j] = stem
            index_to_offset[j] = offset + (mark_timestamp - in_t) / 45000.0
            j += 1
        offset += (out_t - in_t) / 45000.0
    index_to_offset[rows + 1] = offset
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
        run_command(cmd, check=True)
        print(f"Completed: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e}")


def get_effective_bit_depth(file_path, fallback_depth=24):
    """Estimate whether integer PCM effectively uses 16, 24, or 32 bits."""
    if soundfile is None:
        return fallback_depth
    info = soundfile.info(file_path)
    frames = min(int(info.frames), int(info.samplerate) * 10)
    start = int(info.frames) // 2 if int(info.frames) > (frames * 2) else 0
    data, _sample_rate = soundfile.read(
        file_path,
        start=start,
        frames=frames,
        dtype='int32',
    )
    if not data.size:
        return fallback_depth
    if np.all(data % 65536 == 0):
        return 16
    if np.all(data % 256 == 0):
        return 24
    return 32


def bundle_application_root() -> str:
    """PyInstaller extracted root, or cwd when running from source."""
    return getattr(sys, '_MEIPASS', os.path.abspath('.'))


def third_party_notices_markdown_path(language: str) -> Optional[str]:
    """Resolve the selected UI language's notices in the bundle or source checkout."""
    filename = 'THIRD_PARTY_NOTICES.zh-Hans.md' if language == 'zh' else 'THIRD_PARTY_NOTICES.md'
    rel_candidates = (
        os.path.join('legal', filename),
        filename,
    )
    seen: set[str] = set()
    roots: list[str] = []
    mei = getattr(sys, '_MEIPASS', None)
    if mei:
        roots.append(mei)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, '..', '..'))
    roots.append(repo_root)
    roots.append(os.path.abspath(os.getcwd()))
    for root in roots:
        norm_root = os.path.normcase(os.path.normpath(root))
        if norm_root in seen:
            continue
        seen.add(norm_root)
        for rel in rel_candidates:
            candidate = os.path.normpath(os.path.join(root, rel))
            if os.path.isfile(candidate):
                return candidate
    return None


def resolve_encoder_executable_path(tool: str, mode: str) -> str:
    """
    Resolve x264 / x265 / SVT-AV1 encoder binary.

    ``mode`` is ``bundle`` (next to the frozen exe / bundle root) or ``system``
    (``X264_PATH`` / ``X265_PATH`` / ``SVT_AV1_PATH`` from settings).
    """
    from ..core.settings import X264_PATH, X265_PATH, SVT_AV1_PATH

    t = (tool or '').strip().lower()
    if t == 'svtav1':
        key = 'svtav1'
    elif t in ('x264', 'x265'):
        key = t
    else:
        key = 'x265'
    if mode == 'bundle':
        root = bundle_application_root()
        if sys.platform == 'win32':
            names = {'x264': 'x264.exe', 'x265': 'x265.exe', 'svtav1': 'SvtAv1EncApp.exe'}
        else:
            names = {'x264': 'x264', 'x265': 'x265', 'svtav1': 'SvtAv1EncApp'}
        return os.path.join(root, names[key])
    defaults = {'x264': X264_PATH, 'x265': X265_PATH, 'svtav1': SVT_AV1_PATH}
    return str(defaults[key])


def get_vspipe_context():
    """
    Resolve bundled vspipe path and runtime environment for nested package layout.
    """
    # 1) Resolve extracted bundle root.
    bundle_dir = bundle_application_root()

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


def run_command(command, *, wait: bool = True, log_template: str = '', **kwargs):
    """Run every external command through one process boundary."""
    kwargs.setdefault('shell', isinstance(command, str))
    if log_template:
        command_text = command if isinstance(command, str) else subprocess.list2cmdline(command)
        print(translate_text(log_template).format(command=command_text), flush=True)
    cancel_event = _MKVMERGE_CANCEL_EVENT.get()
    if not wait or cancel_event is None or not _is_mkvmerge_mux_command(command):
        return (subprocess.run if wait else subprocess.Popen)(command, **kwargs)
    if cancel_event.is_set():
        from src.runtime import TaskCancelled
        raise TaskCancelled()
    if sys.platform == 'win32':
        kwargs.setdefault('creationflags', subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs.setdefault('start_new_session', True)
    input_data = kwargs.pop('input', None)
    capture_output = kwargs.pop('capture_output', False)
    check = kwargs.pop('check', False)
    timeout = kwargs.pop('timeout', None)
    if input_data is not None:
        if kwargs.get('stdin') is not None:
            raise ValueError('stdin and input arguments may not both be used.')
        kwargs['stdin'] = subprocess.PIPE
    if capture_output:
        if kwargs.get('stdout') is not None or kwargs.get('stderr') is not None:
            raise ValueError('stdout and stderr arguments may not be used with capture_output.')
        kwargs['stdout'] = subprocess.PIPE
        kwargs['stderr'] = subprocess.PIPE
    process = subprocess.Popen(command, **kwargs)
    started_at = time.monotonic()
    stdout = None
    stderr = None
    try:
        while True:
            if cancel_event.is_set():
                _terminate_process_tree(process)
                from src.runtime import TaskCancelled
                raise TaskCancelled()
            poll_timeout = 0.1
            if timeout is not None:
                remaining = float(timeout) - (time.monotonic() - started_at)
                if remaining <= 0:
                    _terminate_process_tree(process)
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
                poll_timeout = min(poll_timeout, remaining)
            try:
                stdout, stderr = process.communicate(input=input_data, timeout=poll_timeout)
                break
            except subprocess.TimeoutExpired:
                input_data = None
        if cancel_event.is_set():
            from src.runtime import TaskCancelled
            raise TaskCancelled()
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
    except BaseException:
        _terminate_process_tree(process)
        raise


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
    "parse_time_to_seconds",
    "format_ogm_chapter_timestamp",
    "append_ogm_chapter_lines",
    "get_index_to_m2ts_and_offset",
    "force_remove_folder",
    "force_remove_file",
    "get_mpv_safe_path",
    "fix_audio_delay_to_lossless",
    "get_effective_bit_depth",
    "bundle_application_root",
    "resolve_encoder_executable_path",
    "get_vspipe_context",
    "mkv_codec_id_is_dts_family",
    "mkvmerge_cancellation_scope",
    "run_command",
    "print_terminal_line",
    "print_exc_terminal",
    "print_tb_string_terminal",
]
