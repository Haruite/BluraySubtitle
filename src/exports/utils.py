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
from pathlib import Path
from threading import RLock
from typing import Callable, Optional

import numpy as np
import soundfile

from ..core.i18n import translate_text, _terminal_err_stream

from ..core.tool_paths import TOOL_EXECUTABLE_NAMES, bundle_directory, is_bundled_tool, tool_path

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
    executable = os.fsdecode(arguments[0]).strip('"')
    is_mkvmerge = (
        os.path.basename(executable).lower().startswith('mkvmerge')
        or os.path.normcase(executable) == os.path.normcase(tool_path("MKV_MERGE_PATH"))
    )
    return is_mkvmerge and any(
        str(argument) in ('-o', '--output') for argument in arguments[1:]
    )


def quote_tool_executable(path: str) -> str:
    return f'"{path}"' if sys.platform == 'win32' else shlex.quote(path)


def _terminate_process_tree(process) -> None:
    if process.poll() is not None:
        return
    if sys.platform == 'win32':
        try:
            subprocess.run(
                ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
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


def get_folder_size(folder_path: str, *, check_canceled: Callable[[], None] | None = None) -> str:
    byte = 0
    for root, _dirs, files in os.walk(folder_path):
        if check_canceled is not None:
            check_canceled()
        for file in files:
            if check_canceled is not None:
                check_canceled()
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

    ffmpeg = quote_tool_executable(tool_path("FFMPEG_PATH"))
    if delay_ms > 0:
        # Positive delay: pad with silence.
        cmd = f'{ffmpeg} {common_opts} -i {input_file_q} {map_str} -af "adelay={delay_ms}:all=1" {codec_str} {output_file_q}'

    elif delay_ms < 0:
        # Negative delay: trim from the start.
        start_time = abs(delay_ms) / 1000.0
        # Keep -ss after -i for decode-level accuracy on HD audio codecs.
        cmd = f'{ffmpeg} {common_opts} -i {input_file_q} -ss {start_time} {map_str} {codec_str} {output_file_q}'

    else:
        # No delay.
        cmd = f'{ffmpeg} {common_opts} -i {input_file_q} {map_str} {codec_str} {output_file_q}'

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


def third_party_notices_markdown_path(language: str) -> Optional[str]:
    """Resolve the selected UI language's notices in the bundle or source checkout."""
    filename = 'THIRD_PARTY_NOTICES.zh-Hans.md' if language == 'zh' else 'THIRD_PARTY_NOTICES.md'
    rel_candidates = (
        os.path.join('legal', filename),
        os.path.join('legal', 'windows' if sys.platform == 'win32' else 'ubuntu', filename),
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


_WINDOWS_PROCESS_LAUNCH_LOCK = RLock()


def system_tool_environment() -> dict[str, str]:
    """Use the caller's runtime environment without paths injected by the bundle."""
    env = os.environ.copy()
    runtime = getattr(sys, '_MEIPASS', None) if getattr(sys, 'frozen', False) else None
    if runtime:
        root = os.path.normcase(os.path.abspath(runtime))

        def from_bundle(path: str) -> bool:
            value = os.path.normcase(os.path.abspath(path.strip('"')))
            return value == root or value.startswith(root + os.sep)

        for name in ('PATH', 'PYTHONPATH', 'PYTHONHOME', 'VSSCRIPT_PATH',
                     'VAPOURSYNTH_EXTRA_PLUGIN_PATH', 'VAPOURSYNTH_PLUGINS', 'BLURAYSUB_PLUGIN_PATH'):
            if name in env:
                paths = [path for path in env[name].split(os.pathsep) if not path or not from_bundle(path)]
                if paths:
                    env[name] = os.pathsep.join(paths)
                else:
                    env.pop(name)
        if sys.platform.startswith('linux'):
            if 'LD_LIBRARY_PATH_ORIG' in env:
                env['LD_LIBRARY_PATH'] = env['LD_LIBRARY_PATH_ORIG']
            else:
                env.pop('LD_LIBRARY_PATH', None)
    return env


def run_vspipe(command: list[str], **kwargs):
    """Launch VSPipe using the system DLL search order for an external executable."""
    if sys.platform == 'win32' and bundle_directory() and not is_bundled_tool(command[0]):
        kwargs['system_dll_search'] = True
    return run_command(command, **kwargs)


def get_vspipe_environment(executable: str, plugin_path: str) -> dict[str, str]:
    """Build the VapourSynth environment for the resolved VSPipe executable."""
    if (bundle := bundle_directory()) and is_bundled_tool(executable):
        env = os.environ.copy()
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
        if sys.platform == 'win32':
            env['PATH'] = f"{bundle};{env.get('PATH', '')}"
            env['PYTHONNOUSERSITE'] = '1'
            for name in ('VAPOURSYNTH_EXTRA_PLUGIN_PATH', 'VAPOURSYNTH_PLUGINS', 'VSSCRIPT_PATH'):
                env.pop(name, None)
            if Path(executable).parent == bundle:
                env['PYTHONHOME'] = str(bundle)
                env['VAPOURSYNTH_PLUGINS'] = str(bundle / 'vapoursynth64/coreplugins')
    else:
        env = system_tool_environment()
    if sys.platform.startswith('linux'):
        env['BLURAYSUB_PLUGIN_PATH'] = plugin_path
    if plugin_path:
        env['VAPOURSYNTH_EXTRA_PLUGIN_PATH'] = plugin_path
    return env


def _spawn_command(command, kwargs, system_dll_search):
    if sys.platform != 'win32':
        return subprocess.Popen(command, **kwargs)
    # SetDllDirectory affects the process. Protect other tool launches and restore it
    # as soon as CreateProcess has copied the search order, before waiting for output.
    with _WINDOWS_PROCESS_LAUNCH_LOCK:
        if not system_dll_search:
            return subprocess.Popen(command, **kwargs)
        set_dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
        set_dll_directory.argtypes = (ctypes.c_wchar_p,)
        set_dll_directory.restype = ctypes.c_int
        if not set_dll_directory(None):
            raise ctypes.WinError()
        process = None
        try:
            process = subprocess.Popen(command, **kwargs)
            return process
        finally:
            if not set_dll_directory(sys._MEIPASS):
                error = ctypes.WinError()
                if process is not None:
                    process.kill()
                    process.wait()
                raise error


def run_command(
        command, *, wait: bool = True, log_template: str = '', cancel_event=None,
        system_dll_search: bool = False, **kwargs,
):
    """Run every external command through one process boundary."""
    if not wait and cancel_event is not None:
        raise ValueError('Cancellation requires waiting for the command.')
    kwargs.setdefault('shell', isinstance(command, str))
    if bundle_directory():
        if isinstance(command, str):
            try:
                arguments = shlex.split(command, posix=sys.platform != 'win32')
            except ValueError:
                arguments = []
        else:
            arguments = command
        if arguments:
            executable = os.path.normcase(os.fsdecode(arguments[0]).strip('"'))
            if os.path.isabs(executable) and not is_bundled_tool(executable) and any(
                    executable == os.path.normcase(tool_path(name)) for name in TOOL_EXECUTABLE_NAMES
            ):
                if kwargs.get('env') is None:
                    kwargs['env'] = system_tool_environment()
                system_dll_search = sys.platform == 'win32' or system_dll_search
    if log_template:
        command_text = command if isinstance(command, str) else subprocess.list2cmdline(command)
        print(translate_text(log_template).format(command=command_text), flush=True)
    stderr = kwargs.get('stderr')
    if (
            getattr(sys.stderr if stderr is None else stderr, 'accepts_ansi_color', False)
            and not kwargs.get('capture_output')
            and isinstance(command, (list, tuple)) and command
            and os.path.basename(os.fsdecode(command[0])).lower() in ('ffmpeg', 'ffmpeg.exe', 'ffprobe', 'ffprobe.exe')
    ):
        configured_environment = kwargs.get('env')
        environment = dict(os.environ if configured_environment is None else configured_environment)
        if 'AV_LOG_FORCE_NOCOLOR' not in environment and not environment.get('NO_COLOR'):
            environment.setdefault('AV_LOG_FORCE_COLOR', '1')
            if sys.platform == 'win32':
                # The Windows console palette in FFmpeg lacks 256-color indices.
                environment['TERM'] = 'ansi'
                environment.pop('AV_LOG_FORCE_256COLOR', None)
            kwargs['env'] = environment
    if cancel_event is None and wait:
        mux_cancel_event = _MKVMERGE_CANCEL_EVENT.get()
        if mux_cancel_event is not None and _is_mkvmerge_mux_command(command):
            cancel_event = mux_cancel_event
    if sys.platform == 'win32':
        flags = kwargs.get('creationflags', subprocess.CREATE_NEW_PROCESS_GROUP if cancel_event is not None else 0)
        if getattr(sys, 'frozen', False):
            flags |= subprocess.CREATE_NO_WINDOW
            if kwargs.get('stdin') is None and kwargs.get('input') is None:
                # Explicit standard handles keep child output connected to the windowed application's log.
                kwargs['stdin'] = subprocess.DEVNULL
        if flags:
            kwargs['creationflags'] = flags
    if cancel_event is None and not (sys.platform == 'win32' and getattr(sys, 'frozen', False)):
        return (subprocess.run if wait else subprocess.Popen)(command, **kwargs)
    if cancel_event is not None and cancel_event.is_set():
        from src.runtime import TaskCancelled
        raise TaskCancelled()
    if not wait:
        return _spawn_command(command, kwargs, system_dll_search)
    if cancel_event is not None and sys.platform != 'win32':
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
    process = _spawn_command(command, kwargs, system_dll_search)
    if cancel_event is None:
        with process:
            try:
                stdout, stderr = process.communicate(input_data, timeout=timeout)
            except subprocess.TimeoutExpired as error:
                process.kill()
                error.stdout, error.stderr = process.communicate()
                raise
            except BaseException:
                process.kill()
                raise
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            if check:
                result.check_returncode()
            return result

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


def print_terminal_line(message: str, *, translate: bool = True) -> None:
    print(translate_text(message) if translate else message, file=_terminal_err_stream(), flush=True)


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
    "fix_audio_delay_to_lossless",
    "get_effective_bit_depth",
    "get_vspipe_environment",
    "mkv_codec_id_is_dts_family",
    "mkvmerge_cancellation_scope",
    "run_command",
    "print_terminal_line",
    "print_exc_terminal",
    "print_tb_string_terminal",
]
