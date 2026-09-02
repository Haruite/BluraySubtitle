"""Auto-generated split target: encode_and_audio_tasks."""

import ctypes
import hashlib
import json
import os
import re
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import multiprocessing
import uuid
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from contextvars import ContextVar
from typing import Optional

from ...core.settings import PLUGIN_PATH, VSPIPE_PATH
from ...core import FFMPEG_PATH, FFPROBE_PATH
from .service_base import BluraySubtitleServiceBase
from .media_info_and_track_mapping import MediaInfoTrackMappingMixin
from src.runtime.audio_conversion import AudioEncodingSettings, mux_with_audio_conversion
from src.runtime.dolby_vision import (
    DolbyVisionEncodePlan,
    dolby_vision_tool_path,
    inject_dolby_vision_rpu,
    prepare_dolby_vision_encode,
    verify_dolby_vision_rpu,
)
from src.runtime.encode_source import (
    SourceColorMetadata,
    VapourSynthOutputMetadataMismatch,
    arguments_contain_option,
    build_automatic_encoder_metadata_arguments,
    extract_hdr10plus_metadata,
    inject_hdr10plus_metadata,
    parse_source_color_metadata,
    probe_actual_encode_source,
    probe_vapoursynth_output_metadata,
    probe_x265_dynamic_metadata_options,
    source_has_hdr10plus,
    verify_final_video_metadata,
    verify_hdr10plus_metadata,
    write_hdr_metadata_error_report,
)
from src.runtime.encode_results import EncodeTaskFailure
from src.runtime.frame_check import run_full_frame_check
from src.runtime.video_crop import (
    VideoCropPlan,
    detect_black_borders,
    write_vapoursynth_crop,
)
from src.runtime import TaskCancelled
from ...core.i18n import translate_text
from ...exports.utils import (
    run_command,
    print_exc_terminal,
    get_vspipe_context,
    force_remove_file,
    get_time_str,
    print_terminal_line,
    resolve_encoder_executable_path,
)
from ...vs_tools.getnative import format_getnative_progress, getnative as auto_getnative

MIGRATE_METHODS = ['encode_task']
KEEP_GETNATIVE_ARTIFACTS = bool(str(os.getenv("BLURAYSUB_KEEP_GETNATIVE_ARTIFACTS", "") or "").strip() == "1")
# Each sample owns a memory-heavy VSPipe process, so concurrency is bounded by both a hard cap and
# a conservative working-set estimate after reserving memory for the operating system and GUI.
GETNATIVE_MAX_PARALLEL_SAMPLES = 20
GETNATIVE_ESTIMATED_SAMPLE_MEMORY_BYTES = 800 * 1024**2
GETNATIVE_MEMORY_RESERVE_BYTES = 2 * 1024**3
_ENCODE_CANCEL_EVENT: ContextVar[Optional[threading.Event]] = ContextVar(
    '_ENCODE_CANCEL_EVENT',
    default=None,
)

_GETNATIVE_DEBUG_DIR_ENV = str(os.getenv("BLURAYSUB_GETNATIVE_DEBUG_DIR", "") or "").strip()
GETNATIVE_DEBUG_DIR = os.path.abspath(_GETNATIVE_DEBUG_DIR_ENV) if _GETNATIVE_DEBUG_DIR_ENV else None


def _remove_managed_lwlibav_cache(source_path: str) -> None:
    """Prevent a reused source path from inheriting the default VPy's old index."""
    if not str(source_path or '').strip():
        return
    source_key = hashlib.sha1(
        os.path.normcase(os.path.abspath(source_path)).encode('utf-8')
    ).hexdigest()
    cache_path = os.path.join(
        tempfile.gettempdir(),
        f'bluraysub_lwlibav_{source_key}.lwi',
    )
    for path in (cache_path, cache_path + '.lock'):
        if os.path.isfile(path):
            force_remove_file(path)


def _normalize_x264_extra_for_bit_depth(extra: list[str], bd: str) -> list[str]:
    """Map x264 --profile to output depth: 8-bit → high, 10-bit → high10 (see x264 --output-depth)."""
    out = list(extra)
    b = str(bd or "").strip()
    if b not in ("8", "10"):
        return out
    want = "high10" if b == "10" else "high"

    i = 0
    found_profile = False
    while i < len(out):
        tok = out[i]
        if tok == "--profile" and i + 1 < len(out):
            found_profile = True
            pv = out[i + 1]
            if pv == "high" and want == "high10":
                out[i + 1] = "high10"
            elif pv == "high10" and want == "high":
                out[i + 1] = "high"
            i += 2
            continue
        if isinstance(tok, str) and tok.startswith("--profile="):
            found_profile = True
            key, _, val = tok.partition("=")
            if val == "high" and want == "high10":
                out[i] = f"{key}=high10"
            elif val == "high10" and want == "high":
                out[i] = f"{key}=high"
            i += 1
            continue
        i += 1

    if not found_profile and b == "10":
        out = ["--profile", "high10"] + out
    return out


def _emit_encode_log_line(message: str) -> None:
    try:
        print_terminal_line(message)
    except Exception:
        print(message, flush=True)


def _probe_video_dimensions(video_path: str) -> tuple[int, int]:
    """Return the first video stream dimensions without decoding the full source."""
    result = run_command(
        [
            str(FFPROBE_PATH or 'ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=width,height',
            '-of',
            'json',
            video_path,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or '').strip()
        raise RuntimeError(
            detail or f'ffprobe exited with code {result.returncode}'
        )
    try:
        payload = json.loads(result.stdout or '{}')
        stream = (payload.get('streams') or [])[0]
        width = int(stream['width'])
        height = int(stream['height'])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError('ffprobe returned invalid video dimensions') from error
    if width <= 0 or height <= 0:
        raise RuntimeError('ffprobe returned invalid video dimensions')
    return width, height


def _read_getnative_progress_messages(
    progress_files: dict[str, str],
    progress_positions: dict[str, int],
) -> list[str]:
    messages: list[str] = []
    for progress_path in progress_files.values():
        position = int(progress_positions.get(progress_path, 0))
        try:
            with open(progress_path, "rb") as progress_file:
                progress_file.seek(position)
                payload = progress_file.read()
        except OSError:
            continue
        complete_length = payload.rfind(b"\n") + 1
        if complete_length <= 0:
            continue
        progress_positions[progress_path] = position + complete_length
        for raw_line in payload[:complete_length].splitlines():
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, TypeError, ValueError):
                continue
            if not isinstance(event, dict):
                continue
            message = format_getnative_progress(event)
            if message:
                messages.append(message)
    return messages


def _record_nonblocking_hdr_automation_failure(
        service,
        output_file: str,
        source_path: str,
        stage_source: str,
        warning_source: str,
        error: Exception,
) -> None:
    stage = translate_text(stage_source)
    try:
        report_path = write_hdr_metadata_error_report(
            output_file,
            source_path,
            stage,
            error,
        )
    except Exception as report_error:
        report_path = ''
        _emit_encode_log_line(
            f'[encode-source] failed to write HDR metadata error report: {report_error}'
        )
    warning = translate_text(warning_source).format(
        path=source_path,
        report=report_path or translate_text('unavailable'),
    )
    warnings = getattr(service, 'encode_warnings', None)
    if not isinstance(warnings, list):
        warnings = []
        service.encode_warnings = warnings
    warnings.append(warning)
    _emit_encode_log_line(f'[encode-source] {warning}')
    service._progress(text=warning)


def _plan_automatic_encoder_metadata(
        service,
        output_file: str,
        source_path: str,
        vpy_path: str,
        vspipe_executable: str,
        vspipe_environment: dict[str, str],
        encoder: str,
        encoder_executable: str,
        bit_depth: str,
        encoder_parameters: str,
        hdr10plus_json_path: str,
        dolby_vision_rpu_path: str,
        progress_name: str = '',
) -> tuple[
    list[str],
    tuple[str, ...],
    bool,
    bool,
    bool,
    SourceColorMetadata | None,
    int | None,
]:
    """Probe one actual source and add only metadata options absent from the GUI."""
    progress_name = str(
        progress_name
        or os.path.splitext(os.path.basename(output_file))[0]
    ).strip()
    try:
        manual_arguments = shlex.split(
            encoder_parameters,
            posix=sys.platform != 'win32',
        )
    except ValueError:
        manual_arguments = encoder_parameters.split()
    automatic_arguments: tuple[str, ...] = ()
    vpy_color_changed = False
    vpy_timeline = None
    hdr10plus_metadata_prepared = False
    try:
        actual_source = probe_actual_encode_source(source_path)
    except Exception as error:
        _record_nonblocking_hdr_automation_failure(
            service,
            output_file,
            source_path,
            'Actual encode source detection',
            'Actual encode source detection failed; encoding will continue: '
            '{path}. Error report: {report}',
            error,
        )
        return (
            manual_arguments,
            automatic_arguments,
            vpy_color_changed,
            False,
            False,
            None,
            None,
        )

    source_message = translate_text(
        'Actual encode source: {name} (stream {stream}, codec {codec}); output: {output}'
    ).format(
        name=os.path.basename(actual_source.path),
        stream=actual_source.stream_index,
        codec=(
            translate_text('unknown')
            if actual_source.codec_name == 'unknown'
            else actual_source.codec_name
        ),
        output=progress_name,
    )
    _emit_encode_log_line(f'[encode-source] {source_message}')
    service._progress(text=source_message)
    service._progress(text=translate_text(
        'Analyzing VapourSynth output metadata: {name}'
    ).format(name=progress_name))
    try:
        actual_source, vpy_color_changed, vpy_timeline = probe_vapoursynth_output_metadata(
            actual_source,
            vpy_path,
            vspipe_executable,
            vspipe_environment,
        )
    except VapourSynthOutputMetadataMismatch:
        raise
    except Exception as error:
        _record_nonblocking_hdr_automation_failure(
            service,
            output_file,
            vpy_path,
            'Actual encode source and metadata planning',
            'Automatic encoder metadata parameter generation failed; '
            'encoding will continue: {path}. Error report: {report}',
            error,
        )
    service._progress(text=translate_text(
        'Planning automatic encoder metadata parameters: {name}'
    ).format(name=progress_name))
    try:
        automatic_arguments = build_automatic_encoder_metadata_arguments(
            actual_source,
            encoder,
            manual_arguments,
        )
    except Exception as error:
        _record_nonblocking_hdr_automation_failure(
            service,
            output_file,
            actual_source.path,
            'Automatic encoder metadata parameter generation',
            'Automatic encoder metadata parameter generation failed; '
            'encoding will continue: {path}. Error report: {report}',
            error,
        )
    x265_dynamic_options = (
        probe_x265_dynamic_metadata_options(encoder_executable)
        if encoder == 'x265' and (
            source_has_hdr10plus(actual_source)
            or (dolby_vision_rpu_path and not vpy_color_changed)
        )
        else frozenset()
    )
    hdr10plus_error = None
    if (
            source_has_hdr10plus(actual_source)
            and not arguments_contain_option(manual_arguments, '--dhdr10-info')
    ):
        if encoder != 'x265' or bit_depth not in ('10', '12'):
            hdr10plus_error = RuntimeError(translate_text(
                'HDR10+ preservation requires x265 with 10-bit or 12-bit output'
            ))
        elif vpy_color_changed:
            hdr10plus_error = RuntimeError(translate_text(
                'HDR10+ metadata does not match the changed VapourSynth color output'
            ))
        else:
            try:
                extract_hdr10plus_metadata(
                    actual_source,
                    hdr10plus_json_path,
                    vpy_timeline,
                )
            except Exception as error:
                hdr10plus_error = error
            else:
                hdr10plus_metadata_prepared = True
                if '--dhdr10-info' in x265_dynamic_options:
                    automatic_arguments += ('--dhdr10-info', hdr10plus_json_path)
    if hdr10plus_error is not None:
        _record_nonblocking_hdr_automation_failure(
            service,
            output_file,
            actual_source.path,
            'HDR10+ metadata preparation',
            'HDR10+ metadata will not be retained; encoding will continue: '
            '{path}. Error report: {report}',
            hdr10plus_error,
        )
    planned_arguments = tuple(manual_arguments) + automatic_arguments
    # x265 rejects Dolby Vision profile 8.1 without HRD/VBV and mastering-display data.
    # Do not invent rate-control settings; use native RPU writing only when the row already has them.
    manual_dolby_vision = (
        arguments_contain_option(planned_arguments, '--dolby-vision-profile')
        and arguments_contain_option(planned_arguments, '--dolby-vision-rpu')
    )
    native_dolby_vision = bool(
        encoder == 'x265'
        and dolby_vision_rpu_path
        and not vpy_color_changed
        and arguments_contain_option(planned_arguments, '--vbv-maxrate')
        and arguments_contain_option(planned_arguments, '--vbv-bufsize')
        and arguments_contain_option(planned_arguments, '--master-display')
        and (
            manual_dolby_vision
            or {
                '--dolby-vision-profile',
                '--dolby-vision-rpu',
            }.issubset(x265_dynamic_options)
        )
    )
    if native_dolby_vision:
        if not arguments_contain_option(
                planned_arguments,
                '--dolby-vision-profile',
        ):
            automatic_arguments += ('--dolby-vision-profile', '8.1')
        if not arguments_contain_option(
                planned_arguments,
                '--dolby-vision-rpu',
        ):
            automatic_arguments += ('--dolby-vision-rpu', dolby_vision_rpu_path)
    if automatic_arguments:
        metadata_message = translate_text(
            'Automatic encoder metadata parameters for {name} '
            '({encoder}): {parameters}'
        ).format(
            name=progress_name,
            encoder=encoder,
            parameters=' '.join(automatic_arguments),
        )
        _emit_encode_log_line(f'[encode-source] {metadata_message}')
        service._progress(text=metadata_message)
    return (
        manual_arguments,
        automatic_arguments,
        vpy_color_changed,
        hdr10plus_metadata_prepared,
        native_dolby_vision,
        parse_source_color_metadata(actual_source),
        vpy_timeline[0] if vpy_timeline is not None else None,
    )


def _format_encoder_cmd_for_echo(enc_cmd: list) -> str:
    """Shell-style echo string; always quote paths after ``-o`` / ``-b``."""
    parts: list[str] = []
    i = 0
    if enc_cmd:
        exe = str(enc_cmd[0])
        parts.append(f'"{exe}"' if (' ' in exe or ';' in exe) else exe)
        i = 1
    while i < len(enc_cmd):
        tok = str(enc_cmd[i])
        if tok in ('-o', '-b') and i + 1 < len(enc_cmd):
            parts.append(tok)
            parts.append(f'"{enc_cmd[i + 1]}"')
            i += 2
            continue
        if ' ' in tok or ';' in tok:
            parts.append(f'"{tok}"')
        else:
            parts.append(tok)
        i += 1
    return ' '.join(parts)



def _pump_subprocess_stderr_raw(stream) -> None:
    """Forward child stderr bytes unchanged (PyInstaller / no TTY)."""
    if stream is None:
        return
    out = getattr(sys.stderr, "buffer", None)
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if out is not None:
                try:
                    out.write(chunk)
                    out.flush()
                except Exception:
                    pass
            else:
                try:
                    sys.stderr.write(chunk.decode("utf-8", errors="replace"))
                    sys.stderr.flush()
                except Exception:
                    pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _terminate_encode_processes(processes: tuple[object, ...]) -> None:
    active = []
    for process in processes:
        if process is None or process in active:
            continue
        try:
            if process.poll() is None:
                if sys.platform == 'win32':
                    process.terminate()
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                active.append(process)
        except Exception:
            continue
    for process in active:
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                if sys.platform == 'win32':
                    process.kill()
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                process.wait(timeout=2.0)
            except Exception:
                pass
        except Exception:
            pass


def _wait_encode_process(
        process,
        cancel_event: Optional[threading.Event],
        process_group: tuple[object, ...],
) -> int:
    while True:
        if cancel_event is not None and cancel_event.is_set():
            _terminate_encode_processes(process_group)
            raise TaskCancelled()
        try:
            return int(process.wait(timeout=0.2))
        except subprocess.TimeoutExpired:
            continue


def _run_vspipe_piped_encode(
    vspipe_exe: str,
    vpy_path: str,
    encoder_cmd: list[str],
    env: Optional[dict],
) -> int:
    """
    vspipe --y4m | encoder (x264 / x265 / SvtAv1EncApp) without cmd.exe.
    In a real TTY, inherit the encoder stderr so x265 can use \\r line progress; otherwise pipe and
    forward stderr bytes unchanged (same as x264/SVT) so logs match the encoder's native output.
    """
    env_use = dict(env) if env else os.environ.copy()
    # Frozen builds pipe native progress because their stderr is not a real terminal.
    inherit_err = not (bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS"))
    try:
        stderr_is_tty = sys.stderr.isatty()
    except Exception:
        stderr_is_tty = False
    use_encoder_stderr_inherit = bool(inherit_err and stderr_is_tty)
    popen_kw: dict = {"env": env_use, "bufsize": 0}
    if sys.platform == "win32":
        popen_kw["creationflags"] = int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        if not inherit_err:
            popen_kw["creationflags"] |= int(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
    else:
        popen_kw['start_new_session'] = True
    stderr_v = None if inherit_err else subprocess.PIPE
    stderr_e = None if use_encoder_stderr_inherit else subprocess.PIPE

    vspipe_cmd = [str(vspipe_exe), "--y4m", str(vpy_path), "-"]
    enc_cmd = [str(x) for x in encoder_cmd]
    cancel_event = _ENCODE_CANCEL_EVENT.get()

    p_v = run_command(
        vspipe_cmd,
        wait=False,
        stdout=subprocess.PIPE,
        stderr=stderr_v,
        **popen_kw,
    )
    try:
        p_e = run_command(
            enc_cmd,
            wait=False,
            stdin=p_v.stdout,
            stdout=subprocess.DEVNULL,
            stderr=stderr_e,
            **popen_kw,
        )
    except Exception:
        _terminate_encode_processes((p_v,))
        raise
    if p_v.stdout is not None:
        p_v.stdout.close()

    pump_threads: list[threading.Thread] = []
    if stderr_v is not None:
        t_v = threading.Thread(target=_pump_subprocess_stderr_raw, args=(p_v.stderr,), daemon=True)
        t_v.start()
        pump_threads.append(t_v)
    if stderr_e is not None:
        t_e = threading.Thread(target=_pump_subprocess_stderr_raw, args=(p_e.stderr,), daemon=True)
        t_e.start()
        pump_threads.append(t_e)

    process_group = (p_e, p_v)
    try:
        rc_e = _wait_encode_process(p_e, cancel_event, process_group)
        rc_v = _wait_encode_process(p_v, cancel_event, process_group)
    except Exception:
        _terminate_encode_processes(process_group)
        raise
    finally:
        for thread in pump_threads:
            thread.join(timeout=1.0)
    if rc_e != 0:
        return rc_e
    return rc_v


def _run_vspipe_svt_win_tempfile_encode(
    vspipe_exe: str,
    vpy_path: str,
    encoder_cmd: list[str],
    env: Optional[dict],
    *,
    temp_dir: Optional[str] = None,
) -> int:
    """
    Windows-only escape hatch: vspipe → full .y4m on disk → SvtAv1EncApp -i <file>.
    Avoids pipe short-read / CRLF / CRT quirks; needs free disk space for the entire y4m stream.
    """
    env_use = dict(env) if env else os.environ.copy()
    popen_kw: dict = {"env": env_use}
    if sys.platform == "win32":
        popen_kw["creationflags"] = int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ) | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        popen_kw['start_new_session'] = True
    td = temp_dir
    if td:
        try:
            os.makedirs(td, exist_ok=True)
        except Exception:
            td = None
    fd, y4m_path = tempfile.mkstemp(
        prefix="bluraysub_svt_", suffix=".y4m", dir=td if td else None
    )
    os.close(fd)
    vspipe_cmd = [str(vspipe_exe), "--y4m", str(vpy_path), "-"]
    enc_cmd = [str(x) for x in encoder_cmd]
    cancel_event = _ENCODE_CANCEL_EVENT.get()
    try:
        with open(y4m_path, "wb") as y4m_f, tempfile.TemporaryFile() as stderr_file:
            p_v = run_command(
                vspipe_cmd,
                wait=False,
                stdout=y4m_f,
                stderr=stderr_file,
                **popen_kw,
            )
            try:
                vspipe_returncode = _wait_encode_process(
                    p_v,
                    cancel_event,
                    (p_v,),
                )
            except Exception:
                _terminate_encode_processes((p_v,))
                raise
            stderr_file.seek(0)
            vspipe_stderr = stderr_file.read()
        if vspipe_returncode != 0:
            try:
                tail = vspipe_stderr.decode("utf-8", errors="replace")[-600:]
                _emit_encode_log_line(
                    f"[BluraySubtitle] vspipe temp-y4m failed "
                    f"rc={vspipe_returncode}\n{tail}"
                )
            except Exception:
                pass
            return vspipe_returncode
        enc_fs = [y4m_path if a.lower() == "stdin" else a for a in enc_cmd]
        with tempfile.TemporaryFile() as stderr_file:
            p_e = run_command(
                enc_fs,
                wait=False,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                **popen_kw,
            )
            try:
                encoder_returncode = _wait_encode_process(
                    p_e,
                    cancel_event,
                    (p_e,),
                )
            except Exception:
                _terminate_encode_processes((p_e,))
                raise
            stderr_file.seek(0)
            encoder_stderr = stderr_file.read()
        if encoder_returncode != 0:
            try:
                tail = encoder_stderr.decode("utf-8", errors="replace")[-800:]
                if tail.strip():
                    _emit_encode_log_line(f"[BluraySubtitle] SvtAv1EncApp stderr (tail):\n{tail}")
            except Exception:
                pass
        return encoder_returncode
    finally:
        try:
            os.remove(y4m_path)
        except OSError:
            pass





def encode_dovi_preservation_supported(tool: str, encode_bit_depth: str) -> bool:
    """Return whether the current tools can inject Dolby Vision into the encoded stream."""
    return tool == 'x265' and int(encode_bit_depth) >= 10


def encode_dovi_preflight_mkv_paths(
        mkv_paths: list[str],
        encoder: str,
        bit_depth: str,
) -> Optional[str]:
    """Return the first deterministic Dolby Vision preflight error."""
    dolby_vision_paths = [
        path
        for raw_path in mkv_paths or []
        if (path := os.path.normpath(str(raw_path or '')))
        and os.path.isfile(path)
        and MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id(path) is not None
    ]
    if not dolby_vision_paths:
        return None
    if encoder == 'svtav1':
        return None
    if not encode_dovi_preservation_supported(encoder, bit_depth):
        return translate_text(
            'Dolby Vision preservation requires x265 with 10-bit or 12-bit output'
        )
    if not dolby_vision_tool_path():
        return translate_text('dovi_tool executable does not exist')
    return None

_VPY_A_LINE_RE = re.compile(
    r'^(\s*)(#\s*)?(\ba\s*=\s*)(.+?)(\s*(#.*)?)\s*$',
)


def _to_vpy_raw_string(value: str) -> str:
    return 'r"' + str(value or '').replace('"', '\\"') + '"'


def _write_vpy_video_source_a(vpy_path: str, video_path: str) -> bool:
    """Set ``a = r"..."`` in *vpy_path* (skip commented assignments)."""
    vpy_path = os.path.normpath(os.path.abspath(str(vpy_path or '').strip()))
    video_path = os.path.normpath(str(video_path or '').strip())
    if not vpy_path or not os.path.isfile(vpy_path) or not video_path:
        return False
    try:
        with open(vpy_path, 'r', encoding='utf-8') as fp:
            lines = fp.readlines()
    except Exception:
        print_exc_terminal()
        return False
    rhs = _to_vpy_raw_string(video_path)
    patched = False
    new_lines: list[str] = []
    for line in lines:
        raw = line.rstrip('\r\n')
        m = _VPY_A_LINE_RE.match(raw)
        if not m or m.group(1) or m.group(2):
            new_lines.append(line)
            continue
        indent, expr, suffix = m.group(1), m.group(3), m.group(5) or ''
        new_raw = f'{indent}{expr}{rhs}{suffix}'
        new_lines.append(new_raw + '\n')
        patched = True
    if not patched:
        insert_at = len(new_lines)
        for idx, line in enumerate(new_lines):
            if 'LWLibavSource' in line or 'ffms2.Source' in line:
                insert_at = idx
                break
        new_lines.insert(insert_at, f'a = {rhs}  # auto-generated by app\n')
    try:
        with open(vpy_path, 'w', encoding='utf-8') as fp:
            fp.writelines(new_lines)
    except Exception:
        print_exc_terminal()
        return False
    print(f'[encode] vpy a = {video_path}', flush=True)
    return True


def _estimate_native_from_image_worker(
    image_path: str,
    debug_dir: Optional[str],
    progress_jsonl: Optional[str] = None,
) -> dict:
    debug_out_dir = None
    previous_progress_jsonl = os.environ.get("BLURAYSUB_GETNATIVE_PROGRESS_JSONL")
    if progress_jsonl:
        os.environ["BLURAYSUB_GETNATIVE_PROGRESS_JSONL"] = os.path.abspath(progress_jsonl)
    try:
        # Keep worker independent from vapoursynth; VS work happens inside getnative.vpy via vspipe.
        from PIL import Image

        with Image.open(image_path) as img:
            h = int(img.height)
        loader = "pil"
        min_h = max(240, int(h * 0.40))
        max_h = min(h - 2, int(h * 0.98))
        if min_h >= max_h:
            return {
                "ok": False,
                "image": os.path.basename(image_path),
                "stage": "range",
                "error": f"invalid height search range - min_h={min_h}, max_h={max_h}, src_h={h}",
            }

        try:
            if debug_dir:
                os.makedirs(debug_dir, exist_ok=True)
                base = os.path.splitext(os.path.basename(image_path))[0]
                cand = os.path.join(debug_dir, base)
                if os.path.exists(cand):
                    k = 1
                    while True:
                        cand2 = os.path.join(debug_dir, f"{base}_{k}")
                        if not os.path.exists(cand2):
                            cand = cand2
                            break
                        k += 1
                os.makedirs(cand, exist_ok=True)
                meta = {
                    "image": os.path.basename(image_path),
                    "range": [int(min_h), int(max_h)],
                    "loader": loader,
                    "src_h": int(h),
                }
                with open(os.path.join(cand, "meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                debug_out_dir = cand
        except Exception:
            debug_out_dir = None

        def _run_getnative_in_range(lo: int, hi: int) -> tuple[float, str, float, dict]:
            out0 = auto_getnative(
                image_path,
                src_heights=tuple(range(lo, hi + 1)),
                debug_dir=debug_out_dir,
                fast_mode=True,
                score_quit=0.0,
                min_kernels=16,
                max_kernels=16,
                consensus_quit=False,
            )
            if isinstance(out0, dict):
                props0 = dict(out0)
            elif hasattr(out0, "get_frame"):
                props0 = dict(out0.get_frame(0).props)
            else:
                raise TypeError(f"unsupported getnative return type: {type(out0).__name__}")
            kernel0 = props0.get("getnative_kernel", "")
            if isinstance(kernel0, bytes):
                kernel0 = kernel0.decode("utf-8", errors="ignore")
            return (
                float(props0.get("getnative_height", 0.0)),
                str(kernel0),
                float(props0.get("getnative_score", 0.0)),
                dict(props0),
            )

        native_h, kernel, score, props = _run_getnative_in_range(min_h, max_h)
        curve_valid = int(props.get("getnative_curve_valid", 1))
        edge_hit = int(props.get("getnative_edge_hit", 0))
        dec_ratio = float(props.get("getnative_decreasing_ratio", 0.0))

        return {
            "ok": True,
            "height": native_h,
            "kernel": kernel,
            "score": score,
            "image": os.path.basename(image_path),
            "stage": "done",
            "range": [min_h, max_h],
            "loader": loader,
            "curve_valid": curve_valid,
            "edge_hit": edge_hit,
            "decreasing_ratio": dec_ratio,
        }
    except Exception as e:
        return {
            "ok": False,
            "image": os.path.basename(image_path),
            "stage": "run_getnative",
            "error": f"{type(e).__name__} - {e}",
            "traceback": traceback.format_exc(limit=8),
        }
    finally:
        if previous_progress_jsonl is None:
            os.environ.pop("BLURAYSUB_GETNATIVE_PROGRESS_JSONL", None)
        else:
            os.environ["BLURAYSUB_GETNATIVE_PROGRESS_JSONL"] = previous_progress_jsonl
        if debug_out_dir and not KEEP_GETNATIVE_ARTIFACTS:
            shutil.rmtree(debug_out_dir, ignore_errors=True)


def _getnative_result_weight(row: dict) -> float:
    score = min(2.0, max(0.0, float(row.get("score", 0.0))))
    height = max(1.0, float(row.get("height", 0.0)))
    search_range = row.get("range", []) or []
    range_high = (
        float(search_range[1])
        if isinstance(search_range, (list, tuple)) and len(search_range) >= 2
        else 1.0
    )
    relative_height = max(0.0, min(1.0, height / max(1.0, range_high)))
    return score * (relative_height**4.0)


def _getnative_available_memory_bytes() -> int:
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.available_physical)
        return 0
    # MemAvailable includes reclaimable caches, unlike SC_AVPHYS_PAGES.
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", encoding="ascii") as meminfo:
                for line in meminfo:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
        except (OSError, IndexError, TypeError, ValueError):
            pass
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, TypeError, ValueError):
        return 0


def _getnative_parallel_sample_count(
    cpu_count: Optional[int] = None,
    available_memory_bytes: Optional[int] = None,
) -> int:
    available = int(os.cpu_count() or 1) if cpu_count is None else int(cpu_count)
    free_memory = (
        _getnative_available_memory_bytes()
        if available_memory_bytes is None
        else max(0, int(available_memory_bytes))
    )
    memory_limit = GETNATIVE_MAX_PARALLEL_SAMPLES
    if free_memory > 0:
        memory_budget = max(0, free_memory - GETNATIVE_MEMORY_RESERVE_BYTES)
        memory_limit = max(1, memory_budget // GETNATIVE_ESTIMATED_SAMPLE_MEMORY_BYTES)
    return max(1, min(GETNATIVE_MAX_PARALLEL_SAMPLES, available, int(memory_limit)))


def _select_getnative_ranked_group(results: list[dict]) -> list[dict]:
    if not results:
        return []
    # Preserve the empirical ranking without rejecting sources that yield only sparse usable frames.
    height_groups: dict[int, list[dict]] = {}
    for row in results:
        height_groups.setdefault(int(round(float(row.get("height", 0.0)))), []).append(row)
    _, winner = max(
        height_groups.items(),
        key=lambda item: (
            sum(sorted((_getnative_result_weight(row) for row in item[1]), reverse=True)[:3]),
            item[0],
        ),
    )
    return winner


class EncodeAudioTasksMixin(BluraySubtitleServiceBase):

    @staticmethod
    def _frame_discriminability_score(image_path: str) -> float:
        """Higher score means frame is more suitable for native-res estimation."""
        try:
            from PIL import Image
            import numpy as np
        except Exception:
            return 0.0
        try:
            img = Image.open(image_path).convert("L")
            w, h = img.size
            # Speed guard: downscale large frames before scoring.
            max_w = 960
            if w > max_w:
                nh = max(2, int(round(h * max_w / w)))
                img = img.resize((max_w, nh), Image.Resampling.BILINEAR)
            arr = np.asarray(img, dtype=np.float32) / 255.0
            if arr.ndim != 2 or arr.size == 0:
                return 0.0
            # Edge energy (simple gradient), luminance variance, and entropy.
            gx = np.abs(arr[:, 1:] - arr[:, :-1]).mean() if arr.shape[1] > 1 else 0.0
            gy = np.abs(arr[1:, :] - arr[:-1, :]).mean() if arr.shape[0] > 1 else 0.0
            edge = float((gx + gy) * 0.5)
            std = float(arr.std())
            hist, _ = np.histogram(arr, bins=64, range=(0.0, 1.0))
            p = hist.astype(np.float64)
            s = float(p.sum())
            if s > 0:
                p /= s
                p = p[p > 0]
                entropy = float(-(p * np.log2(p)).sum() / 6.0)  # normalize roughly to [0,1]
            else:
                entropy = 0.0
            return edge * 0.55 + std * 0.30 + entropy * 0.15
        except Exception:
            return 0.0

    def _extract_sample_images(
        self,
        video_path: str,
        temp_dir: str,
        max_total: int = 100,
        score_map: Optional[dict[str, float]] = None,
    ) -> list[str]:
        shared_scores = score_map if score_map is not None else {}
        target = max(1, int(max_total))
        rounds = [
            ('select_not_mod_240', 'select=\'not(mod(n,240))\',scale=iw:ih'),
            ('select_not_mod_120', 'select=\'not(mod(n,120))\',scale=iw:ih'),
            ('select_not_mod_60', 'select=\'not(mod(n,60))\',scale=iw:ih'),
            ('fps_1_2', 'fps=1/2,scale=iw:ih'),
            ('fps_1', 'fps=1,scale=iw:ih'),
        ]
        try:
            for ridx, (_, vfexpr) in enumerate(rounds, start=1):
                pattern = os.path.join(temp_dir, f"frame_{ridx:02d}_%012d.png")
                proc = run_command(
                    [
                        FFMPEG_PATH,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        video_path,
                        "-vf",
                        vfexpr,
                        "-fps_mode",
                        "passthrough",
                        "-frames:v",
                        str(target),
                        "-frame_pts",
                        "1",
                        pattern,
                    ],
                    creationflags=(
                        int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        if sys.platform == "win32"
                        else 0
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode != 0:
                    detail = (proc.stderr or proc.stdout or "unknown FFmpeg error").strip()
                    raise RuntimeError(f"getnative frame extraction failed: {detail}")

                imgs = sorted(
                    os.path.join(temp_dir, n)
                    for n in os.listdir(temp_dir)
                    if n.lower().endswith(".png")
                )
                pending_scores = [path for path in imgs if path not in shared_scores]
                if pending_scores:
                    score_workers = max(1, min(len(pending_scores), GETNATIVE_MAX_PARALLEL_SAMPLES))
                    with ThreadPoolExecutor(max_workers=score_workers) as score_executor:
                        calculated_scores = score_executor.map(self._frame_discriminability_score, pending_scores)
                        shared_scores.update(zip(pending_scores, calculated_scores))

                ranked = sorted(shared_scores.items(), key=lambda kv: kv[1], reverse=True)
                selected = [p for p, _ in ranked][:target]
                _emit_encode_log_line(
                    f'{self.t("[BluraySubtitle] getnative frame-screen round ")}{ridx}/{len(rounds)} - '
                    f'{self.t("candidates=")}{len(shared_scores)}{self.t(", selected=")}{len(selected)}'
                )
                if len(selected) >= target:
                    return selected[:target]
                if len(shared_scores) >= target:
                    return selected[:target]

            ranked = sorted(shared_scores.items(), key=lambda kv: kv[1], reverse=True)
            return [p for p, _ in ranked][:target]
        except Exception:
            print_exc_terminal()
            return []


    def _infer_native_resolution(self, video_path: str) -> Optional[dict]:
        # Five only decides whether to schedule another complete round. Every sample
        # already launched in the current round finishes and every usable curve is kept.
        minimum_valid_to_stop = 5
        # Sparse sources may need more frames, but extraction remains round-incremental.
        max_total = 100
        valid_results: list[dict] = []
        sample_scores: dict[str, float] = {}
        evaluated_images: set[str] = set()
        temp_dir = None

        try:
            temp_dir = tempfile.mkdtemp(prefix="bluraysub_native_")
            evaluated = 0
            round_number = 0
            while len(valid_results) < minimum_valid_to_stop and evaluated < max_total:
                free_memory = _getnative_available_memory_bytes()
                parallel_samples = _getnative_parallel_sample_count(
                    available_memory_bytes=free_memory,
                )
                round_limit = min(
                    max_total - evaluated,
                    parallel_samples,
                )
                target_total = min(max_total, evaluated + round_limit)
                free_memory_gib = float(free_memory) / float(1024**3) if free_memory > 0 else 0.0
                sample_budget_mib = GETNATIVE_ESTIMATED_SAMPLE_MEMORY_BYTES / float(1024**2)
                _emit_encode_log_line(
                    f'{self.t("[BluraySubtitle] getnative capacity: ")}'
                    f'{self.t("available_memory=")}{free_memory_gib:.2f} GiB, '
                    f'{self.t("sample_budget=")}{sample_budget_mib:.0f} MiB, '
                    f'{self.t("parallel_samples=")}{parallel_samples}'
                )
                sample_images = self._extract_sample_images(
                    video_path,
                    temp_dir=temp_dir,
                    max_total=target_total,
                    score_map=sample_scores,
                )
                launch_limit = round_limit
                batch = [image for image in sample_images if image not in evaluated_images][:launch_limit]
                if not batch:
                    break
                evaluated_images.update(batch)
                evaluated += len(batch)
                round_number += 1

                _emit_encode_log_line(
                    f'{self.t("[BluraySubtitle] getnative round ")}{round_number} - '
                    f'{self.t("evaluating ")}{len(batch)}{self.t(" new samples ")}'
                    f'{self.t("(valid_so_far=")}{len(valid_results)})'
                )
                for idx, image in enumerate(batch, start=1):
                    _emit_encode_log_line(
                        f'{self.t("[BluraySubtitle] getnative sample begin ")}{idx}/{len(batch)} - {os.path.basename(image)}'
                    )

                max_workers = len(batch)
                future_to_image: dict = {}
                recorded_images: set[str] = set()
                progress_files: dict[str, str] = {}
                progress_positions: dict[str, int] = {}
                for progress_index, image in enumerate(batch, start=1):
                    progress_path = os.path.join(
                        temp_dir,
                        f"getnative_progress_{round_number:02d}_{progress_index:02d}.jsonl",
                    )
                    with open(progress_path, "wb"):
                        pass
                    progress_files[image] = progress_path

                def record_sample_result(image: str, result: dict) -> None:
                    recorded_images.add(image)
                    if not bool(result.get("ok", False)):
                        _emit_encode_log_line(
                            f'{self.t("[BluraySubtitle] getnative sample failed: ")}{os.path.basename(image)} '
                            f'{self.t("(stage=")}{result.get("stage", "unknown")}'
                            f'{self.t(", error=")}{result.get("error", "unknown")})'
                        )
                        tb = str(result.get("traceback", "") or "").strip()
                        if tb:
                            _emit_encode_log_line(
                                f'{self.t("[BluraySubtitle] getnative traceback for ")}{os.path.basename(image)}\n{tb}'
                            )
                        return
                    if int(result.get("curve_valid", 1)) == 1:
                        _emit_encode_log_line(
                            f'{self.t("[BluraySubtitle] getnative sample: ")}{result.get("image","")} -> '
                            f'{result.get("height",0):.2f}p {result.get("kernel","")} '
                            f'{self.t("score=")}{result.get("score",0):.6f} '
                            f'{self.t("range=")}{tuple(result.get("range", []))} '
                            f'{self.t("loader=")}{result.get("loader","unknown")} '
                            f'{self.t("curve_valid=")}{int(result.get("curve_valid", 1))} '
                            f'{self.t("edge_hit=")}{int(result.get("edge_hit", 0))} '
                            f'{self.t("dec_ratio=")}{float(result.get("decreasing_ratio", 0.0)):.3f}'
                        )
                        valid_results.append(result)
                    else:
                        _emit_encode_log_line(
                            f'{self.t("[BluraySubtitle] getnative sample rejected by curve-shape: ")}'
                            f'{result.get("image","")} {self.t("edge_hit=")}{result.get("edge_hit",0)} '
                            f'{self.t("decreasing_ratio=")}{float(result.get("decreasing_ratio",0.0)):.3f} '
                            f' -> {result.get("height",0):.2f}p {result.get("kernel","")} '
                            f'{self.t("score=")}{result.get("score",0):.6f}'
                        )

                try:
                    mp_method = "fork" if sys.platform != "win32" else "spawn"
                    mp_ctx = multiprocessing.get_context(mp_method)
                    with ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_ctx) as executor:
                        for image in batch:
                            future = executor.submit(
                                _estimate_native_from_image_worker,
                                image,
                                GETNATIVE_DEBUG_DIR,
                                progress_files[image],
                            )
                            future_to_image[future] = image
                        pending = set(future_to_image)
                        while pending:
                            for message in _read_getnative_progress_messages(
                                progress_files,
                                progress_positions,
                            ):
                                _emit_encode_log_line(message)
                            completed, pending = wait(
                                pending,
                                timeout=0.2,
                                return_when=FIRST_COMPLETED,
                            )
                            for message in _read_getnative_progress_messages(
                                progress_files,
                                progress_positions,
                            ):
                                _emit_encode_log_line(message)
                            for future in completed:
                                image = future_to_image[future]
                                try:
                                    result = future.result() or {}
                                except Exception as e:
                                    result = {
                                        "ok": False,
                                        "image": os.path.basename(image),
                                        "stage": "worker_process",
                                        "error": f"{type(e).__name__} - {e}",
                                    }
                                record_sample_result(image, result)
                        for message in _read_getnative_progress_messages(
                            progress_files,
                            progress_positions,
                        ):
                            _emit_encode_log_line(message)
                except Exception as e:
                    _emit_encode_log_line(
                        f'{self.t("[BluraySubtitle] getnative - multiprocessing unavailable, fallback to single process ")}'
                        f'({type(e).__name__} - {e})'
                    )
                    for image in (candidate for candidate in batch if candidate not in recorded_images):
                        result = _estimate_native_from_image_worker(image, GETNATIVE_DEBUG_DIR) or {}
                        record_sample_result(image, result)
                _emit_encode_log_line(
                    f'{self.t("[BluraySubtitle] getnative round complete: ")}'
                    f'{self.t("evaluated_total=")}{evaluated}, '
                    f'{self.t("valid_total=")}{len(valid_results)}, '
                    f'{self.t("minimum_to_stop=")}{minimum_valid_to_stop}'
                )
        finally:
            if temp_dir and not KEEP_GETNATIVE_ARTIFACTS:
                shutil.rmtree(temp_dir, ignore_errors=True)

        if len(valid_results) < 2:
            total_seen = max(1, int(evaluated))
            _emit_encode_log_line(
                f'[BluraySubtitle] getnative: insufficient valid curves ({len(valid_results)}/{total_seen})'
            )
            return None

        kept = _select_getnative_ranked_group(valid_results)
        heights = sorted(float(x["height"]) for x in kept)
        w2 = [_getnative_result_weight(x) for x in kept]
        wsum = float(sum(w2))
        if wsum <= 0:
            final_h = int(round(heights[len(heights) // 2]))
        else:
            final_h = int(round(sum(float(x["height"]) * w for x, w in zip(kept, w2)) / wsum))

        kernels: dict[str, float] = {}
        for r in kept:
            k = str(r.get("kernel", "") or "")
            kernels[k] = kernels.get(k, 0.0) + _getnative_result_weight(r)
        final_kernel = max(kernels.items(), key=lambda kv: kv[1])[0] if kernels else ""
        return {"height": final_h, "kernel": final_kernel, "confidence": max(x.get("score", 0.0) for x in kept)}

    def encode_task(
            self,
            output_file: str,
            vpy_path: str,
            vspipe_mode: str,
            encoder_mode: str,
            encoder_parameters: str,
            subtitle_mode: str,
            *,
            source_file: str,
            encoder: str,
            bit_depth: str,
            selected_audio_tracks: Optional[tuple[str, ...]],
            selected_subtitle_tracks: Optional[tuple[str, ...]],
            audio_codec_choices: tuple[str, ...],
            track_language_overrides: tuple[tuple[str, str], ...],
            subtitle_path: str = '',
            subtitle_language: str = '',
            audio_encoding: AudioEncodingSettings = AudioEncodingSettings(),
            wave64_bit_depth: int = 32,
            auto_crop_black_borders: bool = False,
            vpy_denoise_strength: float = 0.6,
            vpy_dehalo_strength: float = 0.0,
            vpy_dering_strength: float = 0.0,
            vpy_deband_strength: float = 0.5,
            vpy_antialiasing_strength: float = 0.5,
            check_corrupted_frames: bool = False,
            frame_check_luma_psnr_threshold_db: float = 30.0,
            frame_check_chroma_psnr_threshold_db: float = 30.0,
            progress_name: str = '',
            video_progress_name: str = '',
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        vpy_path = os.path.normpath(os.path.abspath(str(vpy_path or '').strip()))
        if not os.path.isfile(vpy_path):
            raise FileNotFoundError(
                translate_text('VPy file does not exist: {path}').format(path=vpy_path)
            )

        src_mkv = os.path.normpath(source_file)
        output_folder = os.path.dirname(os.path.abspath(output_file))
        bd = bit_depth
        bits_int = int(bd)
        output_stem = os.path.splitext(os.path.basename(output_file))[0]
        progress_name = str(progress_name or output_stem).strip()
        video_progress_name = str(video_progress_name or progress_name).strip()
        encoded_extension = {
            'x264': '.h264',
            'x265': '.hevc',
            'svtav1': '.ivf',
        }[encoder]
        while True:
            artifact_token = uuid.uuid4().hex[:12]
            artifact_base = os.path.join(
                output_folder,
                f'{output_stem}.partial.{artifact_token}',
            )
            if not any(os.path.exists(path) for path in (
                    artifact_base + encoded_extension,
                    artifact_base + '.hdr10plus.json',
                    artifact_base + encoded_extension + '.dovi.hevc',
                    artifact_base + encoded_extension + '.hdr10plus.hevc',
            )):
                break
        encoded_path = artifact_base + encoded_extension
        hdr10plus_json_path = artifact_base + '.hdr10plus.json'
        hdr10plus_injected_path = encoded_path + '.hdr10plus.hevc'
        hdr10plus_metadata_active = False
        native_hdr10plus = False
        vpy_video_source = src_mkv
        managed_lwi_source = ''
        crop_plan: VideoCropPlan | None = None
        encode_dovi_plan: Optional[DolbyVisionEncodePlan] = None
        preserve_dovi_work_folder = False
        if auto_crop_black_borders:
            try:
                self._progress(text=translate_text(
                    'Analyzing black borders: {name}'
                ).format(name=progress_name))
                crop_plan = detect_black_borders(src_mkv)
            except TaskCancelled:
                raise
            except Exception as error:
                raise EncodeTaskFailure(
                    'Automatic black-border analysis',
                    str(error),
                ) from error
            if crop_plan.has_crop:
                try:
                    manual_arguments = shlex.split(
                        encoder_parameters,
                        posix=sys.platform != 'win32',
                    )
                except ValueError:
                    manual_arguments = encoder_parameters.split()
                if arguments_contain_option(
                        manual_arguments,
                        '--dolby-vision-rpu',
                ):
                    raise EncodeTaskFailure(
                        'Automatic black-border analysis',
                        translate_text(
                            'Automatic cropping cannot be combined with a manually supplied '
                            'Dolby Vision RPU: {path}'
                        ).format(path=src_mkv),
                    )
                crop_message = translate_text(
                    'Detected crop for {name}: left {left}, right {right}, top {top}, '
                    'bottom {bottom}; {width}x{height}, {samples} time points'
                ).format(
                    name=progress_name,
                    left=crop_plan.left,
                    right=crop_plan.right,
                    top=crop_plan.top,
                    bottom=crop_plan.bottom,
                    width=crop_plan.output_width,
                    height=crop_plan.output_height,
                    samples=crop_plan.sample_count,
                )
            else:
                crop_message = translate_text(
                    'No removable black borders were detected for {name} '
                    '({samples} time points)'
                ).format(
                    name=progress_name,
                    samples=crop_plan.sample_count,
                )
            _emit_encode_log_line(f'[encode-crop] {crop_message}')
            self._progress(text=crop_message)
        if str(src_mkv).lower().endswith('.mkv') and os.path.isfile(src_mkv):
            dv_tid = MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id(src_mkv)
            if dv_tid is not None:
                if encoder == 'svtav1':
                    message = translate_text(
                        'Dolby Vision metadata will not be retained for SVT-AV1 output: {path}'
                    ).format(path=src_mkv)
                    print(f'[encode-dovi] {message}', flush=True)
                    try:
                        self._progress(text=message)
                    except TaskCancelled:
                        raise
                    except Exception:
                        pass
                else:
                    if not encode_dovi_preservation_supported(encoder, bd):
                        print(
                            f'[encode-dovi] '
                            f'{translate_text("Dolby Vision preservation requires x265 with 10-bit or 12-bit output")} '
                            f'({os.path.basename(src_mkv)})',
                            flush=True,
                        )
                        raise RuntimeError(
                            translate_text('Dolby Vision encode settings are not supported: {path}').format(
                                path=src_mkv
                            )
                        )
                    try:
                        self._progress(
                            text=translate_text('Dolby Vision: preparing {name}').format(
                                name=progress_name
                            )
                        )
                    except TaskCancelled:
                        raise
                    except Exception:
                        pass
                    try:
                        if crop_plan is None:
                            encode_dovi_plan = prepare_dolby_vision_encode(
                                src_mkv,
                                int(dv_tid),
                                output_folder,
                            )
                        else:
                            encode_dovi_plan = prepare_dolby_vision_encode(
                                src_mkv,
                                int(dv_tid),
                                output_folder,
                                crop_plan,
                            )
                    except Exception as error:
                        raise EncodeTaskFailure(
                            'Dolby Vision preparation',
                            str(error),
                            tuple(getattr(error, 'artifact_paths', ()) or ()),
                        ) from error
                    vpy_video_source = encode_dovi_plan.base_layer_path

        failure_stage = 'VapourSynth preparation'
        try:
            use_getnative = bool(getattr(self, "use_getnative", True))
            native_info = None
            if use_getnative:
                automatic_getnative_allowed = True
                try:
                    source_width, source_height = _probe_video_dimensions(
                        vpy_video_source
                    )
                except Exception as error:
                    automatic_getnative_allowed = False
                    message = translate_text(
                        'Could not probe source resolution for getnative; '
                        'automatic analysis was skipped: {error}'
                    ).format(error=f'{type(error).__name__}: {error}')
                    _emit_encode_log_line(
                        f'[encode-getnative] {message}'
                    )
                    self._progress(text=message)
                else:
                    # Confirmed GUI-contract exception: UHD getnative is manual-only.
                    if source_height > 1080:
                        automatic_getnative_allowed = False
                        message = translate_text(
                            'Automatic getnative was skipped for {width}x{height} source. '
                            'Run src/scripts/getnative_file.py manually and write the '
                            'detected parameters into the VPy if needed.'
                        ).format(width=source_width, height=source_height)
                        _emit_encode_log_line(f'[encode-getnative] {message}')
                        self._progress(text=message)
                if automatic_getnative_allowed:
                    _emit_encode_log_line(
                        f'{self.t("[BluraySubtitle] getnative - start analyzing ")}{os.path.basename(vpy_video_source)}')
                    try:
                        self._progress(text=f'{self.t("Getnative analyzing: ")}{progress_name}')
                    except TaskCancelled:
                        raise
                    except Exception:
                        pass
                    native_info = self._infer_native_resolution(vpy_video_source)
                    if native_info:
                        _emit_encode_log_line(
                            f'{self.t("[BluraySubtitle] getnative - ")}{os.path.basename(src_mkv)} -> '
                            f'{native_info["height"]}p ({native_info["kernel"]}, {self.t("score>=")}{native_info["confidence"]:.4f})'
                        )
                    else:
                        _emit_encode_log_line(
                            f'{self.t("[BluraySubtitle] getnative - ")}{os.path.basename(vpy_video_source)} -> '
                            f'{self.t("no confident native resolution")}'
                        )

            def update_vpy_script():
                if not os.path.exists(vpy_path):
                    return
                try:
                    with open(vpy_path, 'r', encoding='utf-8') as fp:
                        lines = fp.readlines()
                except Exception:
                    print_exc_terminal()
                    return

                subtitle_real_path = os.path.normpath(subtitle_path) if subtitle_path else None
                hardsub_enabled = subtitle_mode == 'hard' and bool(subtitle_real_path)

                def _patch_output_fmtc_bitdepth_line(line: str) -> tuple[str, bool]:
                    """
                    Only touch the *final* encode output depth:
                    - res = core.fmtc.bitdepth(res, bits=N)   (typical custom script)
                    - res = core.fmtc.bitdepth(src8, bits=N)  (default template)
                    Do NOT rewrite e.g. src16 = core.fmtc.bitdepth(src8, bits=8) — that desyncs the
                    filter chain and the y4m C tag vs --input-depth (garbage on any OS, easy to miss).
                    """
                    t = line.rstrip("\r\n")
                    s = t.lstrip()
                    if re.match(r"res\s*=\s*core\.fmtc\.bitdepth\s*\(\s*src8\s*,", s):
                        nl = re.sub(
                            r"(core\.fmtc\.bitdepth\(\s*src8\s*,\s*bits\s*=\s*)\d+",
                            lambda m: m.group(1) + str(bits_int),
                            line,
                            count=1,
                        )
                        return (nl, nl != line)
                    if re.match(r"res\s*=\s*core\.fmtc\.bitdepth\s*\(\s*res\s*,", s):
                        nl = re.sub(
                            r"(core\.fmtc\.bitdepth\(\s*res\s*,\s*bits\s*=\s*)\d+",
                            lambda m: m.group(1) + str(bits_int),
                            line,
                            count=1,
                        )
                        return (nl, nl != line)
                    return (line, False)

                updated = False
                new_lines = []
                processing_values = {
                    'denoise_strength': float(vpy_denoise_strength),
                    'dehalo_strength': float(vpy_dehalo_strength),
                    'dering_strength': float(vpy_dering_strength),
                    'deband_strength': float(vpy_deband_strength),
                    'antialiasing_strength': float(vpy_antialiasing_strength),
                }
                for line in lines:
                    raw = line.rstrip('\r\n')
                    stripped = line.lstrip()

                    processing_match = None
                    for processing_name, processing_value in processing_values.items():
                        match = re.match(
                            rf'^({re.escape(processing_name)}\s*=\s*)'
                            rf'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
                            rf'(\s*(#.*)?)$',
                            raw,
                        )
                        if match:
                            processing_match = (
                                match,
                                format(processing_value, '.6g'),
                            )
                            break
                    if processing_match is not None:
                        match, value = processing_match
                        new_lines.append(
                            f'{match.group(1)}{value}{match.group(2)}\n'
                        )
                        updated = True
                        continue

                    if stripped.startswith('native_h ='):
                        if not native_info:
                            new_lines.append(line)
                            continue
                        indent = line[:len(line) - len(stripped)]
                        comment = ''
                        if '#' in stripped:
                            comment = ' #' + stripped.split('#', 1)[1].rstrip('\n')
                        native_h = int(native_info["height"]) if native_info else 0
                        if native_h > 0 and native_h % 2:
                            native_h -= 1
                        new_lines.append(f'{indent}native_h = {native_h}{comment}\n')
                        updated = True
                        continue

                    if stripped.startswith('native_kernel ='):
                        if not native_info:
                            new_lines.append(line)
                            continue
                        indent = line[:len(line) - len(stripped)]
                        comment = ''
                        if '#' in stripped:
                            comment = ' #' + stripped.split('#', 1)[1].rstrip('\n')
                        native_kernel = str(native_info["kernel"]) if native_info else ""
                        native_kernel = native_kernel.replace('"', '\\"')
                        new_lines.append(f'{indent}native_kernel = "{native_kernel}"{comment}\n')
                        updated = True
                        continue

                    subtitle_match = re.match(
                        r'^(\s*)(#\s*)?(sub_file\s*=\s*)r?[\'"].*?[\'"]'
                        r'(\s*(#.*)?)$',
                        raw,
                    )
                    if subtitle_match:
                        subtitle_value = _to_vpy_raw_string(subtitle_real_path or '')
                        comment_prefix = '' if hardsub_enabled else '# '
                        new_line = (
                            f'{subtitle_match.group(1)}{comment_prefix}'
                            f'{subtitle_match.group(3)}{subtitle_value}'
                            f'{subtitle_match.group(4) or ""}\n'
                        )
                        new_lines.append(new_line)
                        updated = updated or new_line != line
                        continue

                    textsub_match = re.match(
                        r'^(\s*)(#\s*)?'
                        r'(res\s*=\s*core\.assrender\.TextSub\('
                        r'\s*res\s*,\s*file\s*=\s*sub_file\s*\))'
                        r'(\s*(#.*)?)$',
                        raw,
                    )
                    if textsub_match:
                        comment_prefix = '' if hardsub_enabled else '# '
                        new_line = (
                            f'{textsub_match.group(1)}{comment_prefix}'
                            f'{textsub_match.group(3)}'
                            f'{textsub_match.group(4) or ""}\n'
                        )
                        new_lines.append(new_line)
                        updated = updated or new_line != line
                        continue

                    nl, ch = _patch_output_fmtc_bitdepth_line(line)
                    if ch:
                        new_lines.append(nl)
                        updated = True
                        continue

                    new_lines.append(line)

                if not updated:
                    return
                script_text = ''.join(new_lines)
                try:
                    with open(vpy_path, 'w', encoding='utf-8') as fp:
                        fp.write(script_text)
                except Exception:
                    print_exc_terminal()

            update_vpy_script()
            managed_lwi_source = vpy_video_source
            _remove_managed_lwlibav_cache(managed_lwi_source)
            if not _write_vpy_video_source_a(vpy_path, vpy_video_source):
                print(
                    f'[encode] failed to set vpy source (a) in {vpy_path}',
                    flush=True,
                )
                raise RuntimeError(
                    translate_text('Failed to set the VPy video source: {path}').format(
                        path=vpy_path
                    )
                )
            write_vapoursynth_crop(
                vpy_path,
                crop_plan if auto_crop_black_borders else None,
            )

            if vspipe_mode == 'bundle':
                vspipe_exe, vspipe_env = get_vspipe_context()
            else:
                vspipe_exe, vspipe_env = VSPIPE_PATH, None
            vspipe_env = dict(vspipe_env) if vspipe_env else dict(os.environ)
            vspipe_env['BLURAYSUB_VPY_SOURCE'] = os.path.normpath(vpy_video_source)
            if str(PLUGIN_PATH or '').strip():
                vspipe_env['BLURAYSUB_PLUGIN_PATH'] = str(PLUGIN_PATH)
            enc_exe = resolve_encoder_executable_path(encoder, encoder_mode)

            failure_stage = 'Actual encode source and metadata planning'
            self._progress(text=translate_text(
                'Analyzing video source metadata: {name}'
            ).format(name=progress_name))
            (
                manual_encoder_arguments,
                automatic_metadata_arguments,
                vpy_color_changed,
                hdr10plus_metadata_active,
                native_dolby_vision,
                expected_final_video_metadata,
                expected_dynamic_metadata_frames,
            ) = _plan_automatic_encoder_metadata(
                self,
                output_file,
                vpy_video_source,
                vpy_path,
                str(vspipe_exe),
                vspipe_env,
                encoder,
                enc_exe,
                bd,
                encoder_parameters,
                hdr10plus_json_path,
                encode_dovi_plan.rpu_path if encode_dovi_plan else '',
                progress_name,
            )
            native_hdr10plus = arguments_contain_option(
                automatic_metadata_arguments,
                '--dhdr10-info',
            )
            failure_stage = 'VapourSynth preparation'
            if encode_dovi_plan and vpy_color_changed:
                message = translate_text(
                    'Dolby Vision metadata will not be retained because the '
                    'VapourSynth output changed color primaries or transfer '
                    'characteristics: {path}'
                ).format(path=vpy_path)
                self.encode_warnings.append(message)
                self._progress(text=message)

            extra = list(manual_encoder_arguments) + list(
                automatic_metadata_arguments
            )
            if encoder == 'x264':
                extra = _normalize_x264_extra_for_bit_depth(extra, bd)
            elif encoder == 'svtav1' and bd == '12' and not any(
                    str(arg).strip().lower() in ('--profile', '-profile')
                    or str(arg).strip().lower().startswith(('--profile=', '-profile='))
                    for arg in extra
            ):
                extra = ['--profile', '2'] + list(extra)

            if encoder == 'x264':
                enc_cmd = [enc_exe, '--demuxer', 'y4m', '-'] + extra + ['--output-depth', bd, '-o', encoded_path]
            elif encoder == 'x265':
                # Stdin is already '--y4m' '-' ; a trailing '-' is parsed as a second input (unused) and can abort x265.
                enc_cmd = (
                    [enc_exe]
                    + extra
                    + ['--y4m', '-', '--input-depth', bd, '--output-depth', bd, '-o', encoded_path]
                )
            else:
                # Windows: SVT-AV1 hand-tuned asm can corrupt output (upstream unfixed); force portable C paths.
                if sys.platform == "win32":
                    enc_cmd = [enc_exe, "--asm", "c", "-i", "stdin", "--input-depth", bd] + extra + ["-b", encoded_path]
                else:
                    enc_cmd = [enc_exe, "-i", "stdin", "--input-depth", bd] + extra + ["-b", encoded_path]

            use_svt_win_temp_y4m = (
                encoder == "svtav1"
                and sys.platform == "win32"
                and str(os.environ.get("BLURAYSUB_SVT_WIN_TEMP_Y4M", "") or "").strip() == "1"
            )
            if use_svt_win_temp_y4m:
                cmd_echo = (
                    f'[temp y4m] "{vspipe_exe}" --y4m "{vpy_path}" -  -->  "{enc_cmd[0]}" -i <temp.y4m> ... -b "{encoded_path}"'
                )
                try:
                    _emit_encode_log_line(
                        "[BluraySubtitle] SVT-AV1: temp y4m file mode (BLURAYSUB_SVT_WIN_TEMP_Y4M=1); high disk use."
                    )
                except Exception:
                    pass
            else:
                cmd_echo = f'"{vspipe_exe}" --y4m "{vpy_path}" - | {_format_encoder_cmd_for_echo(enc_cmd)}'
            print(f'{translate_text("Encode command:")}{cmd_echo}')
            failure_stage = 'Video encoding'
            self._progress(text=translate_text(
                'Encoding video: {name}'
            ).format(name=video_progress_name))
            cancel_token = _ENCODE_CANCEL_EVENT.set(cancel_event)
            try:
                if use_svt_win_temp_y4m:
                    enc_rc = _run_vspipe_svt_win_tempfile_encode(
                        str(vspipe_exe),
                        vpy_path,
                        enc_cmd,
                        vspipe_env,
                        temp_dir=os.path.dirname(encoded_path) or None,
                    )
                else:
                    enc_rc = _run_vspipe_piped_encode(
                        str(vspipe_exe),
                        vpy_path,
                        enc_cmd,
                        vspipe_env,
                    )
            finally:
                _ENCODE_CANCEL_EVENT.reset(cancel_token)
            if enc_rc != 0:
                _emit_encode_log_line(f"[BluraySubtitle] encode pipeline exited with code {enc_rc}")
            if enc_rc != 0:
                raise RuntimeError(
                    translate_text('Encode pipeline failed with exit code {code}: {path}').format(
                        code=enc_rc,
                        path=src_mkv,
                    )
                )
            if not os.path.isfile(encoded_path):
                raise RuntimeError(
                    translate_text('Encoded video output is missing: {path}').format(
                        path=encoded_path
                    )
                )
            if encode_dovi_plan and not vpy_color_changed:
                dolby_vision_verified = False
                if native_dolby_vision:
                    failure_stage = 'Dolby Vision RPU verification'
                    try:
                        verify_dolby_vision_rpu(
                            encoded_path,
                            expected_dynamic_metadata_frames,
                            8,
                        )
                    except Exception:
                        pass
                    else:
                        dolby_vision_verified = True
                if not dolby_vision_verified:
                    failure_stage = 'Dolby Vision RPU injection'
                    self._progress(
                        text=translate_text(
                            'Dolby Vision: injecting RPU into {name}'
                        ).format(name=progress_name)
                    )
                    inject_dolby_vision_rpu(encoded_path, encode_dovi_plan)
                    failure_stage = 'Dolby Vision RPU verification'
                    verify_dolby_vision_rpu(
                        encoded_path,
                        expected_dynamic_metadata_frames,
                        8,
                    )
            if hdr10plus_metadata_active:
                hdr10plus_verified = False
                if native_hdr10plus:
                    try:
                        verify_hdr10plus_metadata(encoded_path)
                    except Exception:
                        pass
                    else:
                        hdr10plus_verified = True
                if not hdr10plus_verified:
                    try:
                        inject_hdr10plus_metadata(
                            encoded_path,
                            hdr10plus_json_path,
                        )
                    except Exception as error:
                        _record_nonblocking_hdr_automation_failure(
                            self,
                            output_file,
                            encoded_path,
                            'HDR10+ encoded output verification',
                            'HDR10+ metadata was not written to the encoded output; '
                            'encoding will continue: {path}. Error report: {report}',
                            error,
                        )
                        hdr10plus_metadata_active = False
                    else:
                        if encode_dovi_plan and not vpy_color_changed:
                            failure_stage = 'Dolby Vision RPU verification'
                            verify_dolby_vision_rpu(
                                encoded_path,
                                expected_dynamic_metadata_frames,
                                8,
                            )
            soft_subtitle = subtitle_path if subtitle_mode == 'soft' else ''
            failure_stage = 'Final Matroska mux'

            def report_audio_progress(operation: str) -> None:
                self._progress(text=translate_text(
                    '{operation}: {name}'
                ).format(
                    operation=operation,
                    name=progress_name,
                ))

            mux_with_audio_conversion(
                src_mkv,
                output_file,
                selected_audio_tracks=selected_audio_tracks,
                selected_subtitle_tracks=selected_subtitle_tracks,
                audio_codec_choices=audio_codec_choices,
                track_language_overrides=track_language_overrides,
                encoded_video_file=encoded_path,
                subtitle_file=soft_subtitle,
                subtitle_language=subtitle_language,
                audio_encoding=audio_encoding,
                wave64_bit_depth=wave64_bit_depth,
                preserve_failure_artifacts=True,
                progress_callback=report_audio_progress,
            )
            self._progress(text=translate_text(
                'Verifying final video metadata: {name}'
            ).format(name=progress_name))
            final_verification_errors = []
            try:
                verify_final_video_metadata(
                    output_file,
                    expected_final_video_metadata,
                    automatic_metadata_arguments,
                )
            except Exception as error:
                final_verification_errors.append(error)
            if hdr10plus_metadata_active:
                try:
                    verify_hdr10plus_metadata(output_file)
                except Exception as error:
                    final_verification_errors.append(error)
                    hdr10plus_metadata_active = False
            if encode_dovi_plan and not vpy_color_changed:
                try:
                    verify_dolby_vision_rpu(
                        output_file,
                        expected_dynamic_metadata_frames,
                        8,
                    )
                except Exception as error:
                    final_verification_errors.append(error)
            if final_verification_errors:
                _record_nonblocking_hdr_automation_failure(
                    self,
                    output_file,
                    output_file,
                    'Final HDR metadata verification',
                    'Final HDR metadata verification failed; the output was '
                    'retained: {path}. Error report: {report}',
                    RuntimeError('; '.join(
                        str(error) for error in final_verification_errors
                    )),
                )
            if check_corrupted_frames:
                self._progress(text=translate_text(
                    'Checking encoded frames: {name}'
                ).format(name=progress_name))

                def report_frame_check_progress(
                        frames: int,
                        fps: float,
                        fraction: Optional[float],
                        remaining_seconds: Optional[float],
                ) -> None:
                    if fraction is None or remaining_seconds is None:
                        message = translate_text(
                            'Frame check progress: {name}; {frames} frames, '
                            '{fps:.1f} fps'
                        ).format(
                            name=progress_name,
                            frames=frames,
                            fps=fps,
                        )
                    else:
                        message = translate_text(
                            'Frame check progress: {name}; {percent:.1f}%, '
                            '{frames} frames, {fps:.1f} fps, ETA {eta}'
                        ).format(
                            name=progress_name,
                            percent=fraction * 100.0,
                            frames=frames,
                            fps=fps,
                            eta=get_time_str(remaining_seconds),
                        )
                    print_terminal_line(message)

                try:
                    frame_check = run_full_frame_check(
                        vspipe_executable=str(vspipe_exe),
                        vpy_path=vpy_path,
                        vspipe_environment=vspipe_env,
                        ffmpeg_executable=str(FFMPEG_PATH or 'ffmpeg'),
                        ffprobe_executable=str(FFPROBE_PATH or 'ffprobe'),
                        encoded_path=output_file,
                        expected_reference_frames=expected_dynamic_metadata_frames,
                        luma_psnr_threshold_db=(
                            frame_check_luma_psnr_threshold_db
                        ),
                        chroma_psnr_threshold_db=(
                            frame_check_chroma_psnr_threshold_db
                        ),
                        cancel_event=cancel_event,
                        progress_callback=report_frame_check_progress,
                    )
                except TaskCancelled:
                    raise
                except Exception as error:
                    message = translate_text(
                        'Frame check could not be completed for {name}: {error}'
                    ).format(
                        name=os.path.basename(output_file),
                        error=error,
                    )
                    self.encode_warnings.append(message)
                    self._progress(text=message)
                else:
                    if frame_check.status == 'pass':
                        self._progress(text=translate_text(
                            'Frame check passed: {path}'
                        ).format(path=frame_check.report_path))
                    else:
                        message_template = (
                            'Frame check did not complete for {name}. Report: {report}'
                            if frame_check.status == 'error'
                            else 'Frame check found potential corrupted frames in {name}. '
                                 'Report: {report}'
                        )
                        message = translate_text(message_template).format(
                            name=os.path.basename(output_file),
                            report=frame_check.report_path,
                        )
                        self.encode_warnings.append(message)
                        self._progress(text=message)
        except TaskCancelled:
            retained_artifacts = []
            for path in (
                    encoded_path,
                    hdr10plus_json_path,
                    encoded_path + '.dovi.hevc',
                    hdr10plus_injected_path,
            ):
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    retained_artifacts.append(path)
                elif os.path.isfile(path):
                    force_remove_file(path)
            if (
                    encode_dovi_plan
                    and os.path.isfile(encode_dovi_plan.rpu_path)
                    and os.path.getsize(encode_dovi_plan.rpu_path) > 0
            ):
                retained_artifacts.append(encode_dovi_plan.rpu_path)
                preserve_dovi_work_folder = True
            if retained_artifacts:
                _emit_encode_log_line(
                    translate_text('Encode cancellation preserved artifacts: {paths}').format(
                        paths=', '.join(retained_artifacts)
                    )
                )
            raise
        except Exception as error:
            retained_artifacts = list(
                tuple(getattr(error, 'artifact_paths', ()) or ())
            )
            for path in (
                    encoded_path,
                    hdr10plus_json_path,
                    encoded_path + '.dovi.hevc',
                    hdr10plus_injected_path,
            ):
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    retained_artifacts.append(path)
                elif os.path.isfile(path):
                    force_remove_file(path)
            if (
                    encode_dovi_plan
                    and os.path.isfile(encode_dovi_plan.rpu_path)
                    and os.path.getsize(encode_dovi_plan.rpu_path) > 0
            ):
                retained_artifacts.append(encode_dovi_plan.rpu_path)
                preserve_dovi_work_folder = True
            raise EncodeTaskFailure(
                failure_stage,
                str(error),
                tuple(dict.fromkeys(retained_artifacts)),
            ) from error
        else:
            if os.path.isfile(encoded_path):
                force_remove_file(encoded_path)
            if os.path.isfile(hdr10plus_injected_path):
                force_remove_file(hdr10plus_injected_path)
            if os.path.isfile(hdr10plus_json_path) and (
                    hdr10plus_metadata_active
                    or os.path.getsize(hdr10plus_json_path) == 0
            ):
                force_remove_file(hdr10plus_json_path)
        finally:
            _remove_managed_lwlibav_cache(managed_lwi_source)
            if encode_dovi_plan and not preserve_dovi_work_folder:
                encode_dovi_plan.cleanup()
