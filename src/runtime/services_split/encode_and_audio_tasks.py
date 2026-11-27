"""Auto-generated split target: encode_and_audio_tasks."""

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import threading
import traceback
import uuid
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from configparser import ConfigParser
from contextvars import ContextVar
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import Optional

from ...core.tool_paths import bundle_directory, is_bundled_tool, tool_path
from ...core.video_format import OutputResolution, yuv_format_matches
from .service_base import BluraySubtitleServiceBase
from .media_info_and_track_mapping import MediaInfoTrackMappingMixin
from src.runtime.audio_conversion import AudioEncodingSettings, mux_with_audio_conversion
from src.runtime.dolby_vision import (
    DolbyVisionEncodePlan,
    edit_dolby_vision_rpu_for_crop,
    inject_dolby_vision_rpu,
    prepare_dolby_vision_encode,
    verify_dolby_vision_rpu,
)
from src.runtime.encode_command import CpuEncodeCommand, default_cpu_encode_command, format_encoder_command
from src.runtime.encode_source import (
    ActualEncodeSource,
    SourceColorMetadata,
    VapourSynthOutputMetadataMismatch,
    arguments_contain_option,
    build_automatic_encoder_metadata_arguments,
    extract_hdr10plus_metadata,
    hdr_to_sdr_source,
    inject_hdr10plus_metadata,
    parse_source_color_metadata,
    probe_actual_encode_source,
    probe_vapoursynth_frame_count,
    probe_vapoursynth_output_metadata,
    probe_video_geometry,
    probe_x265_dynamic_metadata_options,
    source_has_hdr10plus,
    verify_encoded_dimensions,
    verify_final_video_metadata,
    verify_hdr10plus_metadata,
    verify_sdr_encode,
    write_hdr_metadata_error_report,
)
from src.runtime.encode_results import EncodeTaskFailure
from src.runtime.hardware_encode import (
    GPU_MUXERS, GpuEncodeDevice, VideoEncodeChoice, hardware_encode_command,
    hardware_encoder_parameters,
)
from src.runtime.frame_check import run_full_frame_check
from src.runtime.video_timeline import (
    VPY_HARDSUB_CALL,
    VPY_HARDSUB_PATTERN,
    extract_video_timeline,
)
from src.runtime.video_crop import (
    VideoCropPlan,
    detect_black_borders,
    write_vapoursynth_crop,
)
from src.runtime.vpy_output import VpyOutputGeometry, remove_vpy_output_format, vpy_with_output_format
from src.runtime import TaskCancelled, worker_process_context
from ...core.i18n import translate_text
from ...exports.utils import (
    run_command,
    terminate_process_trees,
    run_vspipe,
    print_exc_terminal,
    get_vspipe_environment,
    force_remove_file,
    get_time_str,
    print_terminal_line,
    system_tool_environment,
)
from ...vs_tools.getnative import format_getnative_progress, getnative_batch as auto_getnative_batch

MIGRATE_METHODS = ['encode_task']
KEEP_GETNATIVE_ARTIFACTS = bool(str(os.getenv("BLURAYSUB_KEEP_GETNATIVE_ARTIFACTS", "") or "").strip() == "1")
# Bound the extracted samples and their VapourSynth working sets after reserving
# memory for the operating system and GUI.
GETNATIVE_MAX_PARALLEL_SAMPLES = 20
GETNATIVE_SAMPLES_PER_WORKER = 4
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


def _emit_encode_log_line(message: str, *, translate: bool = True) -> None:
    try:
        print_terminal_line(message, translate=translate)
    except Exception:
        print(message, flush=True)


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


def _record_encode_warning(service, message: str) -> None:
    warnings = getattr(service, 'encode_warnings', None)
    if not isinstance(warnings, list):
        warnings = []
        service.encode_warnings = warnings
    warnings.append(message)
    _emit_encode_log_line(f'[encode-source] {message}', translate=False)
    service._progress(text=message)


def _warn_unsupported_hdr_mode(
        service, feature: str, encoder: str, depth: str, path: str, chroma_format: str = 'yuv420',
) -> None:
    _record_encode_warning(service, translate_text(
        '{feature} cannot be preserved with {encoder} at {depth}-bit {chroma}. Encoding will continue: {path}'
    ).format(feature=feature, encoder=encoder, depth=depth, chroma=chroma_format, path=path))


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
    _record_encode_warning(service, warning)


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
        manual_arguments: tuple[str, ...],
        hdr10plus_json_path: str,
        dolby_vision_rpu_path: str,
        progress_name: str = '',
        *,
        hardware: bool = False,
        add_encoder_metadata: bool = True,
        chroma_format: str = 'yuv420',
        verify_resolution: bool = False,
        crop_plan: VideoCropPlan | None = None,
        source_probe: ActualEncodeSource | None = None,
        hdr_to_sdr: bool = False,
) -> tuple[
    tuple[str, ...],
    bool,
    bool,
    bool,
    SourceColorMetadata | None,
    int | None,
    int | None,
    VpyOutputGeometry | None,
]:
    """Probe one actual source and add only metadata options absent from the GUI."""
    progress_name = str(
        progress_name
        or os.path.splitext(os.path.basename(output_file))[0]
    ).strip()
    encoder_name = encoder if add_encoder_metadata else os.path.basename(encoder_executable)
    automatic_arguments: tuple[str, ...] = ()
    vpy_color_changed = False
    vpy_timeline = None
    source_frame_count = None
    hdr10plus_metadata_prepared = False
    geometry = None
    try:
        actual_source = source_probe if source_probe is not None else probe_actual_encode_source(source_path)
    except TaskCancelled:
        raise
    except Exception as error:
        if verify_resolution or hdr_to_sdr:
            raise
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
            automatic_arguments,
            vpy_color_changed,
            False,
            False,
            None,
            None,
            None,
            None,
        )

    input_metadata = parse_source_color_metadata(actual_source)
    source_is_hdr = bool(
        input_metadata.color_transfer in ('smpte2084', 'arib-std-b67')
        or input_metadata.mastering_display_x26x
        or input_metadata.content_light_level
    )
    hdr10plus_present = not hdr_to_sdr and source_has_hdr10plus(actual_source)
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
        (
            actual_source, vpy_color_changed, vpy_timeline, source_frame_count,
        ) = probe_vapoursynth_output_metadata(
            actual_source,
            vpy_path,
            vspipe_executable,
            vspipe_environment,
        )
    except (TaskCancelled, VapourSynthOutputMetadataMismatch):
        raise
    except Exception as error:
        if verify_resolution or hdr_to_sdr:
            raise
        _record_nonblocking_hdr_automation_failure(
            service,
            output_file,
            vpy_path,
            'Actual encode source and metadata planning',
            'Automatic encoder metadata parameter generation failed; '
            'encoding will continue: {path}. Error report: {report}',
            error,
        )
    else:
        geometry = actual_source.geometry
    if verify_resolution and (geometry is None or geometry.resize_input_size is None):
        raise RuntimeError(translate_text('Could not determine the resized VapourSynth output: {path}').format(path=vpy_path))
    source_after_crop = (
        (crop_plan.output_width, crop_plan.output_height) if crop_plan is not None else
        geometry.source_size if geometry is not None else None
    )
    service._progress(text=translate_text(
        'Planning automatic encoder metadata parameters: {name}'
    ).format(name=progress_name))
    include_static_hdr = not hdr_to_sdr and bit_depth != '8'
    if chroma_format != 'yuv420':
        actual_source = replace(actual_source, stream={**actual_source.stream, 'chroma_location': None})
    final_metadata = parse_source_color_metadata(actual_source)
    if not include_static_hdr:
        if not hdr_to_sdr and (source_is_hdr or final_metadata.color_transfer in ('smpte2084', 'arib-std-b67')):
            _warn_unsupported_hdr_mode(service, 'HDR', encoder_name, bit_depth, output_file, chroma_format)
        final_metadata = replace(
            final_metadata, mastering_display_x26x=None, mastering_display_svt=None, content_light_level=None,
        )
    elif source_is_hdr and vpy_color_changed:
        _record_encode_warning(service, translate_text(
            'Source HDR metadata will not be retained because the VapourSynth output changed '
            'color primaries or transfer characteristics: {path}'
        ).format(path=output_file))
    try:
        if add_encoder_metadata:
            automatic_arguments = build_automatic_encoder_metadata_arguments(
                actual_source,
                'x265' if hardware else encoder,
                manual_arguments,
                include_static_hdr=include_static_hdr,
            )
        if hardware and encoder == 'av1':
            # AV1 signals only left and top-left positions for 4:2:0.
            automatic_arguments = tuple(
                token for option, value in zip(automatic_arguments[::2], automatic_arguments[1::2])
                if option != '--chromaloc' or value in ('0', '2')
                for token in (option, value)
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
    hdr10plus_supported = chroma_format == 'yuv420' and (
        (encoder == 'hevc' and bit_depth == '10') if hardware else
        (encoder == 'x265' and bit_depth in ('10', '12'))
    )
    x265_dynamic_options = (
        probe_x265_dynamic_metadata_options(encoder_executable)
        if add_encoder_metadata and encoder == 'x265' and not vpy_color_changed and (
            (hdr10plus_present and hdr10plus_supported) or dolby_vision_rpu_path
        )
        else frozenset()
    )
    hdr10plus_error = None
    if (
            hdr10plus_present
            and not arguments_contain_option(manual_arguments, '--dhdr10-info')
    ):
        if not hdr10plus_supported:
            _warn_unsupported_hdr_mode(service, 'HDR10+', encoder_name, bit_depth, output_file, chroma_format)
        elif vpy_color_changed:
            _record_encode_warning(service, translate_text(
                'HDR10+ metadata will not be retained because the VapourSynth output changed '
                'color primaries or transfer characteristics: {path}'
            ).format(path=output_file))
        elif verify_resolution and geometry is not None and not geometry.follows_source_geometry(source_after_crop):
            _record_encode_warning(service, translate_text(
                'HDR10+ metadata will not be retained because the VapourSynth picture geometry '
                'cannot be mapped to the source: {path}'
            ).format(path=output_file))
        else:
            try:
                extract_hdr10plus_metadata(
                    actual_source,
                    hdr10plus_json_path,
                    vpy_timeline,
                    require_full_frame=bool(verify_resolution and geometry and (
                        geometry.was_resized or (crop_plan is not None and crop_plan.has_crop)
                    )),
                )
            except TaskCancelled:
                raise
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
        # The template is already translated; encoder options and paths are literal data.
        _emit_encode_log_line(f'[encode-source] {metadata_message}', translate=False)
        service._progress(text=metadata_message)
    return (
        automatic_arguments,
        vpy_color_changed,
        hdr10plus_metadata_prepared,
        native_dolby_vision,
        final_metadata,
        vpy_timeline[0] if vpy_timeline is not None else None,
        source_frame_count,
        geometry,
    )


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


def _wait_encode_process(
        process,
        cancel_event: Optional[threading.Event],
        process_group: tuple[object, ...],
) -> int:
    while True:
        if cancel_event is not None and cancel_event.is_set():
            terminate_process_trees(process_group, grace=2.0)
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
    Pipe VapourSynth Y4M into one encoder process.
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
    popen_kw: dict = {"bufsize": 0}
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

    vspipe_cmd = [str(vspipe_exe), "--container", "y4m", str(vpy_path), "-"]
    enc_cmd = [str(x) for x in encoder_cmd]
    cancel_event = _ENCODE_CANCEL_EVENT.get()

    p_v = run_vspipe(
        vspipe_cmd,
        wait=False,
        stdout=subprocess.PIPE,
        stderr=stderr_v,
        env=env_use,
        **popen_kw,
    )
    try:
        external_tool = bool(bundle_directory() and not is_bundled_tool(enc_cmd[0]))
        p_e = run_command(
            enc_cmd,
            wait=False,
            stdin=p_v.stdout,
            stdout=subprocess.DEVNULL,
            stderr=stderr_e,
            env=system_tool_environment() if external_tool else None,
            system_dll_search=external_tool and sys.platform == 'win32',
            **popen_kw,
        )
    except Exception:
        terminate_process_trees((p_v,), grace=2.0)
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
        terminate_process_trees(process_group, grace=2.0)
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
    vspipe_cmd = [str(vspipe_exe), "--container", "y4m", str(vpy_path), "-"]
    enc_cmd = [str(x) for x in encoder_cmd]
    cancel_event = _ENCODE_CANCEL_EVENT.get()
    try:
        with open(y4m_path, "wb") as y4m_f, tempfile.TemporaryFile() as stderr_file:
            p_v = run_vspipe(
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
                terminate_process_trees((p_v,), grace=2.0)
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
                terminate_process_trees((p_e,), grace=2.0)
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





_VPY_A_LINE_RE = re.compile(
    r'^(\s*)(#\s*)?(\ba\s*=\s*)(.+?)(\s*(#.*)?)\s*$',
)


def _write_vpy_video_source_a(vpy_path: str, video_path: str) -> bool:
    """Set the video source path in *vpy_path* (skip commented assignments)."""
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
    rhs = repr(video_path)
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


def _run_getnative_batch(image_progress, height_range, vspipe_path, plugin_path, threads):
    lo, hi = height_range
    options = {
        "src_heights": list(range(lo, hi + 1)),
        "plugin_path": plugin_path,
        "threads": threads,
    }
    directory = Path(vspipe_path).resolve().parent
    private_runtime = directory / "python-runtime.ini"
    if sysconfig.get_platform() != "win-arm64" or not private_runtime.is_file():
        return auto_getnative_batch(image_progress, **options)

    # A Classic installation on ARM64 supplies a private x64 interpreter.
    configuration = ConfigParser(interpolation=None)
    configuration.read(private_runtime, encoding="utf-8-sig")
    home = configuration.get("Python", "Home", fallback="")
    python = directory / home / "python.exe"
    if not home or not python.is_file():
        raise FileNotFoundError(translate_text("VapourSynth's x64 Python runtime is missing. Run Windows setup."))
    root = Path(__file__).resolve().parents[3]
    command = (
        "import json, sys; sys.path.insert(0, sys.argv[1]); "
        "from src.vs_tools.getnative import getnative_batch; "
        "print(json.dumps(getnative_batch(json.loads(sys.argv[2]), **json.loads(sys.argv[3]))))"
    )
    environment = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH"):
        environment.pop(key, None)
    result = run_command(
        [str(python), "-I", "-c", command, str(root), json.dumps(image_progress), json.dumps(options)],
        env=environment, capture_output=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or str(result.returncode))
    return json.loads(result.stdout.splitlines()[-1])


def _estimate_native_from_images_worker(
    image_progress: dict[str, Optional[str]],
    debug_dir: Optional[str],
    *,
    vspipe_path: Optional[str] = None,
    plugin_path: Optional[str] = None,
    threads: int = 1,
) -> dict[str, dict]:
    from PIL import Image

    results: dict[str, dict] = {}
    groups: dict[tuple[int, int, int, int], dict[str, Optional[str]]] = {}
    debug_paths = []

    def record_failure(image, error):
        results[image] = {
            "ok": False,
            "image": os.path.basename(image),
            "stage": "run_getnative",
            "error": f"{type(error).__name__} - {error}",
            "traceback": traceback.format_exc(limit=8),
        }

    def analyze(samples, height_range):
        try:
            detected = _run_getnative_batch(
                samples, height_range,
                tool_path("VSPIPE_PATH") if vspipe_path is None else vspipe_path,
                tool_path("PLUGIN_PATH") if plugin_path is None else plugin_path,
                threads,
            )
            results.update({
                image: {
                    "ok": True,
                    "image": os.path.basename(image),
                    "height": float(detected[image]["getnative_height"]),
                    "kernel": str(detected[image]["getnative_kernel"]),
                    "score": float(detected[image]["getnative_score"]),
                    "stage": "done",
                    "range": list(height_range),
                    "loader": "pil",
                    "curve_valid": int(detected[image]["getnative_curve_valid"]),
                    "edge_hit": int(detected[image]["getnative_edge_hit"]),
                    "decreasing_ratio": float(detected[image]["getnative_decreasing_ratio"]),
                }
                for image in samples
            })
        except Exception as error:
            if len(samples) == 1:
                record_failure(next(iter(samples)), error)
            else:
                # Isolate an unreadable sample or plugin that rejects a shared graph.
                for image, progress in samples.items():
                    analyze({image: progress}, height_range)

    try:
        for image, progress in image_progress.items():
            name = os.path.basename(image)
            try:
                with Image.open(image) as img:
                    width, height = img.size
                    sample = img.convert("RGB")
                    # Apply the metric's border exclusion to this blank-frame check.
                    if width > 10 and height > 10:
                        sample = sample.crop((5, 5, width - 5, height - 5))
                    uniform = all(low == high for low, high in sample.getextrema())
                if uniform:
                    results[image] = {"ok": True, "image": name, "stage": "sample_quality", "skip_reason": "uniform_frame"}
                    continue
                lo = max(240, int(height * 0.40))
                hi = min(height - 2, int(height * 0.98))
                if lo >= hi:
                    results[image] = {
                        "ok": False,
                        "image": name,
                        "stage": "range",
                        "error": f"invalid height search range - min_h={lo}, max_h={hi}, src_h={height}",
                    }
                    continue
                groups.setdefault((width, height, lo, hi), {})[image] = progress
            except Exception as error:
                record_failure(image, error)
                continue

            if debug_dir:
                try:
                    os.makedirs(debug_dir, exist_ok=True)
                    base = os.path.join(debug_dir, os.path.splitext(name)[0])
                    path = base
                    index = 1
                    while True:
                        try:
                            os.mkdir(path)
                            break
                        except FileExistsError:
                            path = f"{base}_{index}"
                            index += 1
                    debug_paths.append(path)
                    meta = {"image": name, "range": [lo, hi], "loader": "pil", "src_h": height}
                    with open(os.path.join(path, "meta.json"), "w", encoding="utf-8") as stream:
                        json.dump(meta, stream, ensure_ascii=False, indent=2)
                except OSError:
                    pass

        for (_, _, lo, hi), samples in groups.items():
            analyze(samples, (lo, hi))
    finally:
        if not KEEP_GETNATIVE_ARTIFACTS:
            for path in debug_paths:
                shutil.rmtree(path, ignore_errors=True)
    return results


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
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.available_physical)
        except (AttributeError, OSError):
            pass
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
        psutil = import_module("psutil")
    except (ImportError, NotImplementedError):
        pass
    else:
        try:
            return max(0, int(psutil.virtual_memory().available))
        except (OSError, NotImplementedError, psutil.Error):
            pass
    try:
        pages = max(0, os.sysconf("SC_AVPHYS_PAGES"))
        page_size = max(0, os.sysconf("SC_PAGE_SIZE"))
        return pages * page_size
    except (AttributeError, OSError, ValueError):
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
    memory_budget = max(0, free_memory - GETNATIVE_MEMORY_RESERVE_BYTES)
    memory_limit = memory_budget // GETNATIVE_ESTIMATED_SAMPLE_MEMORY_BYTES
    return max(1, min(GETNATIVE_MAX_PARALLEL_SAMPLES, available, memory_limit))


def _select_getnative_ranked_group(results: list[dict]) -> list[dict]:
    if not results:
        return []
    # Keep all support for each height instead of capping agreement at three samples.
    height_groups: dict[int, list[dict]] = {}
    for row in results:
        height_groups.setdefault(int(round(float(row.get("height", 0.0)))), []).append(row)
    _, winner = max(
        height_groups.items(),
        key=lambda item: (
            sum(_getnative_result_weight(row) for row in item[1]),
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
                        tool_path("FFMPEG_PATH"),
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
        getnative_paths = {"vspipe_path": tool_path("VSPIPE_PATH"), "plugin_path": tool_path("PLUGIN_PATH")}
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

                group_count = (len(batch) + GETNATIVE_SAMPLES_PER_WORKER - 1) // GETNATIVE_SAMPLES_PER_WORKER
                sample_groups = [batch[index::group_count] for index in range(group_count)]
                future_to_group: dict = {}
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
                    if result.get("skip_reason") == "uniform_frame":
                        _emit_encode_log_line(
                            f'{self.t("[BluraySubtitle] getnative sample skipped (uniform frame): ")}'
                            f'{os.path.basename(image)}'
                        )
                        return
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
                    with ProcessPoolExecutor(
                            max_workers=group_count, mp_context=worker_process_context(),
                    ) as executor:
                        for images in sample_groups:
                            future = executor.submit(
                                _estimate_native_from_images_worker,
                                {image: progress_files[image] for image in images},
                                GETNATIVE_DEBUG_DIR,
                                threads=len(images),
                                **getnative_paths,
                            )
                            future_to_group[future] = images
                        pending = set(future_to_group)
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
                                images = future_to_group[future]
                                try:
                                    results = future.result()
                                except Exception as e:
                                    results = {
                                        image: {
                                            "ok": False,
                                            "image": os.path.basename(image),
                                            "stage": "worker_process",
                                            "error": f"{type(e).__name__} - {e}",
                                        }
                                        for image in images
                                    }
                                for image in images:
                                    record_sample_result(image, results[image])
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
                    for images in sample_groups:
                        remaining = {image: None for image in images if image not in recorded_images}
                        if remaining:
                            results = _estimate_native_from_images_worker(
                                remaining, GETNATIVE_DEBUG_DIR, threads=len(remaining), **getnative_paths,
                            )
                            for image, result in results.items():
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
            audio_timeline_by_track: Optional[
                dict[int, tuple[tuple[float, float], ...]]
            ] = None,
            detect_audio_gaps: bool = False,
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
            hardware_device: GpuEncodeDevice | None = None,
            cpu_command: CpuEncodeCommand | None = None,
            chroma_format: str = 'yuv420',
            output_resolution: OutputResolution = OutputResolution(),
            hdr_to_sdr: bool = False,
            input_mode: str = 'remux',
    ) -> None:
        vpy_path = os.path.normpath(os.path.abspath(str(vpy_path or '').strip()))
        if not os.path.isfile(vpy_path):
            raise FileNotFoundError(
                translate_text('VPy file does not exist: {path}').format(path=vpy_path)
            )

        src_mkv = os.path.normpath(source_file)
        source_info = None
        output_folder = os.path.dirname(os.path.abspath(output_file))
        bd = bit_depth
        bits_int = int(bd)
        command = None
        hardware_choice = None
        if hardware_device is None:
            command = cpu_command or default_cpu_encode_command(
                encoder, bd, encoder_parameters, chroma_format=chroma_format,
            )
            encoder = command.encoder
        else:
            hardware_choice = VideoEncodeChoice(encoder, bd, encoder_parameters, hardware_device, chroma_format)
            chroma_format = hardware_choice.output_chroma_format
        manual_arguments = command.arguments[1:] if command is not None else tuple(
            hardware_encoder_parameters(encoder_parameters)
        )
        enc_exe = command.arguments[0] if command is not None else tool_path('FFMPEG_PATH')
        output_stem = os.path.splitext(os.path.basename(output_file))[0]
        progress_name = str(progress_name or output_stem).strip()
        video_progress_name = str(video_progress_name or progress_name).strip()
        encoded_extension = command.output_extension if command is not None else {
            'h264': '.h264',
            'hevc': '.hevc',
            'av1': '.ivf',
            'prores': '.prores.mkv',
            'ffv1': '.ffv1.mkv',
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
                    artifact_base + '.timestamps.txt',
                    artifact_base + encoded_extension + '.dovi.hevc',
                    artifact_base + encoded_extension + '.hdr10plus.hevc',
            )):
                break
        encoded_path = artifact_base + encoded_extension
        output_timestamps_path = artifact_base + '.timestamps.txt'
        hdr10plus_json_path = artifact_base + '.hdr10plus.json'
        dovi_injected_path = encoded_path + '.dovi.hevc'
        hdr10plus_injected_path = encoded_path + '.hdr10plus.hevc'
        hdr10plus_metadata_active = False
        native_hdr10plus = False
        vpy_video_source = src_mkv
        managed_lwi_source = ''
        crop_plan: VideoCropPlan | None = None
        encode_dovi_plan: Optional[DolbyVisionEncodePlan] = None
        dovi_completion_warning = ''
        preserve_dovi_work_folder = False
        if auto_crop_black_borders:
            try:
                self._progress(text=translate_text(
                    'Analyzing black borders: {name}'
                ).format(name=progress_name))
                crop_plan = detect_black_borders(src_mkv, cancel_event=cancel_event)
            except TaskCancelled:
                raise
            except Exception as error:
                raise EncodeTaskFailure(
                    'Automatic black-border analysis',
                    str(error),
                ) from error
            if crop_plan.has_crop:
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
        if not hdr_to_sdr and str(src_mkv).lower().endswith('.mkv') and os.path.isfile(src_mkv):
            dv_tid = MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id(src_mkv)
            if dv_tid is not None:
                if encoder not in ('x265', 'hevc') or bd != '10' or chroma_format != 'yuv420':
                    name = os.path.basename(enc_exe) if cpu_command is not None else encoder
                    _warn_unsupported_hdr_mode(self, 'Dolby Vision', name, bd, output_file, chroma_format)
                else:
                    self._progress(text=translate_text(
                        'Dolby Vision: preparing {name}'
                    ).format(name=progress_name))
                    try:
                        source_info = MediaInfoTrackMappingMixin._mkvmerge_identify_json(src_mkv)
                        default_duration_ns = next((
                            track.get('properties', {}).get('default_duration')
                            for track in source_info.get('tracks', []) if track.get('id') == dv_tid
                        ), None)
                        encode_dovi_plan = prepare_dolby_vision_encode(
                            src_mkv, int(dv_tid), output_folder, None if output_resolution.enabled else crop_plan,
                            default_duration_ns=default_duration_ns,
                            check_cancel=self._progress,
                        )
                    except TaskCancelled:
                        raise
                    except Exception as error:
                        _record_nonblocking_hdr_automation_failure(
                            self,
                            output_file,
                            src_mkv,
                            'Dolby Vision preparation',
                            'Dolby Vision metadata could not be prepared. Encoding will continue: '
                            '{path}. Error report: {report}',
                            error,
                        )
                    else:
                        vpy_video_source = encode_dovi_plan.base_layer_path
                        if encode_dovi_plan.fel_residual_discarded:
                            dovi_completion_warning = translate_text(
                                'Encoding completed from the base layer. The source has FEL or an '
                                'unrecognized enhancement layer; this tool workflow did not use '
                                'its image residuals: {path}'
                            ).format(path=output_file)

        failure_stage = 'VapourSynth preparation'
        try:
            source_probe = probe_actual_encode_source(vpy_video_source, cancel_event=cancel_event) if hdr_to_sdr else None
            sdr_source = hdr_to_sdr_source(source_probe, input_mode=input_mode) if source_probe is not None else None
            if sdr_source is not None and sdr_source.is_hdr:
                # Keep HDR precision through the user graph, then quantize the mapped output.
                bits_int = max(bits_int, 10)
                self._progress(text=translate_text('Converting HDR to SDR: {name}').format(name=progress_name))
            use_getnative = bool(getattr(self, "use_getnative", True))
            native_info = None
            if use_getnative:
                automatic_getnative_allowed = True
                try:
                    if source_probe is None:
                        source_width, source_height, _ = probe_video_geometry(vpy_video_source)
                    else:
                        source_width, source_height = (int(source_probe.stream[axis]) for axis in ('width', 'height'))
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
                        lines = remove_vpy_output_format(fp.read()).splitlines(keepends=True)
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
                        subtitle_value = repr(subtitle_real_path or '')
                        comment_prefix = '' if hardsub_enabled else '# '
                        new_line = (
                            f'{subtitle_match.group(1)}{comment_prefix}'
                            f'{subtitle_match.group(3)}{subtitle_value}'
                            f'{subtitle_match.group(4) or ""}\n'
                        )
                        new_lines.append(new_line)
                        updated = updated or new_line != line
                        continue

                    textsub_match = re.match(VPY_HARDSUB_PATTERN, raw)
                    if textsub_match:
                        comment_prefix = '' if hardsub_enabled else '# '
                        new_line = (
                            f'{textsub_match.group(1)}{comment_prefix}'
                            f'{VPY_HARDSUB_CALL}'
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
            script = Path(vpy_path)
            script.write_text(
                vpy_with_output_format(
                    script.read_text(encoding='utf-8'), bd, chroma_format, output_resolution, hdr_to_sdr=sdr_source,
                ),
                encoding='utf-8', newline='\r\n',
            )

            vspipe_exe = tool_path("VSPIPE_PATH")
            vspipe_env = get_vspipe_environment(vspipe_exe, tool_path("PLUGIN_PATH"))
            vspipe_env['BLURAYSUB_VPY_SOURCE'] = os.path.normpath(vpy_video_source)
            # Metadata probing does not render final subtitles and needs no timecodes.
            vspipe_env.pop('BLURAYSUB_VPY_TIMECODES', None)
            vspipe_env.pop('BLURAYSUB_VPY_FRAMES', None)

            failure_stage = 'Actual encode source and metadata planning'
            self._progress(text=translate_text(
                'Analyzing video source metadata: {name}'
            ).format(name=progress_name))
            (
                automatic_metadata_arguments,
                vpy_color_changed,
                hdr10plus_metadata_active,
                native_dolby_vision,
                expected_final_video_metadata,
                expected_output_frames,
                source_frame_count,
                geometry,
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
                manual_arguments,
                hdr10plus_json_path,
                encode_dovi_plan.rpu_path if encode_dovi_plan and not output_resolution.enabled else '',
                progress_name,
                hardware=hardware_device is not None,
                add_encoder_metadata=command is None or command.uses_metadata,
                chroma_format=chroma_format,
                verify_resolution=output_resolution.enabled,
                crop_plan=crop_plan,
                source_probe=source_probe,
                hdr_to_sdr=hdr_to_sdr,
            )
            if sdr_source is not None and sdr_source.is_hdr and (
                    expected_final_video_metadata is None
                    or expected_final_video_metadata.color_transfer in (None, 'smpte2084', 'arib-std-b67')
            ):
                raise ValueError(translate_text('The VapourSynth output could not be verified as SDR: {path}').format(
                    path=vpy_video_source,
                ))
            encoded_video_bt709 = bool(
                hdr_to_sdr and expected_final_video_metadata is not None
                and expected_final_video_metadata.color_range in ('tv', 'limited')
                and expected_final_video_metadata.color_primaries == expected_final_video_metadata.color_transfer
                == expected_final_video_metadata.color_matrix == 'bt709'
            )
            expected_size = geometry.output_size if output_resolution.enabled and geometry is not None else None
            if expected_size is not None:
                self._progress(text=translate_text('Output resolution for {name}: {width}×{height}').format(
                    name=progress_name, width=expected_size[0], height=expected_size[1],
                ))
            dolby_vision_geometry_valid = True
            if output_resolution.enabled and encode_dovi_plan is not None and not vpy_color_changed:
                after_crop = (
                    (crop_plan.output_width, crop_plan.output_height) if crop_plan is not None else geometry.source_size
                )
                if not geometry.follows_source_geometry(after_crop):
                    dolby_vision_geometry_valid = False
                    _record_encode_warning(self, translate_text(
                        'Dolby Vision metadata will not be retained because the VapourSynth picture geometry '
                        'cannot be mapped to the source: {path}'
                    ).format(path=output_file))
                elif geometry.was_resized or (crop_plan is not None and crop_plan.has_crop):
                    adjusted_rpu = os.path.join(encode_dovi_plan.work_folder, 'rpu-resized.bin')
                    try:
                        edit_dolby_vision_rpu_for_crop(
                            encode_dovi_plan.rpu_path, adjusted_rpu, crop_plan, encode_dovi_plan.work_folder,
                            resize_input=geometry.resize_input_size, resize_output=geometry.output_size,
                        )
                    except TaskCancelled:
                        raise
                    except Exception as error:
                        dolby_vision_geometry_valid = False
                        _record_nonblocking_hdr_automation_failure(
                            self, output_file, src_mkv, 'Dolby Vision preparation',
                            'Dolby Vision metadata could not be prepared. Encoding will continue: '
                            '{path}. Error report: {report}', error,
                        )
                    else:
                        encode_dovi_plan = replace(encode_dovi_plan, rpu_path=adjusted_rpu)
            failure_stage = 'Video timestamp preparation'
            if expected_output_frames is None:
                expected_output_frames = probe_vapoursynth_frame_count(
                    vpy_path, str(vspipe_exe), vspipe_env,
                )
            failure_stage = 'Video timestamp extraction'
            self._progress(text=translate_text(
                'Reading video timestamps: {name}'
            ).format(name=progress_name))
            if source_info is None:
                source_info = MediaInfoTrackMappingMixin._mkvmerge_identify_json(src_mkv)
            source_tracks = source_info.get('tracks', [])
            timestamp_scale = source_info.get('container', {}).get(
                'properties', {}
            ).get('timestamp_scale', 1_000_000)
            video_track = next(
                (track for track in source_tracks if track.get('type') == 'video'),
                None,
            )
            if video_track is None:
                raise ValueError(translate_text(
                    'No video track found: {path}'
                ).format(path=src_mkv))
            output_timeline = extract_video_timeline(
                src_mkv, int(video_track['id']), output_timestamps_path,
                cancel_event, frame_count=expected_output_frames,
                # FFprobe's printed times have microsecond precision.
                source_frame_count=(
                    source_frame_count if timestamp_scale % 1_000 == 0 else None
                ),
            )
            vspipe_env['BLURAYSUB_VPY_TIMECODES'] = output_timestamps_path
            vspipe_env['BLURAYSUB_VPY_FRAMES'] = str(expected_output_frames)
            native_hdr10plus = arguments_contain_option(
                automatic_metadata_arguments,
                '--dhdr10-info',
            )
            failure_stage = 'VapourSynth preparation'
            dolby_vision_metadata_active = bool(encode_dovi_plan and not vpy_color_changed and dolby_vision_geometry_valid)
            if encode_dovi_plan and vpy_color_changed:
                _record_encode_warning(self, translate_text(
                    'Dolby Vision metadata will not be retained because the '
                    'VapourSynth output changed color primaries or transfer '
                    'characteristics: {path}'
                ).format(path=output_file))

            if command is not None:
                enc_cmd = command.materialize(encoded_path, automatic_metadata_arguments)
            else:
                enc_cmd = hardware_encode_command(
                    enc_exe, hardware_choice,
                    ['-f', 'yuv4mpegpipe', '-i', 'pipe:0'],
                    ['-f', GPU_MUXERS[encoder], encoded_path],
                    metadata_args=automatic_metadata_arguments,
                )
            use_svt_win_temp_y4m = (
                sys.platform == "win32"
                and str(os.environ.get("BLURAYSUB_SVT_WIN_TEMP_Y4M", "") or "").strip() == "1"
                and command is not None and encoder == 'svtav1'
                and command.uses_builtin_encoder()
                and any(option in ('-i', '--input') and value == 'stdin'
                        for option, value in zip(enc_cmd, enc_cmd[1:]))
            )
            if use_svt_win_temp_y4m:
                cmd_echo = (
                    f'[temp y4m] "{vspipe_exe}" --container y4m "{vpy_path}" -  -->  "{enc_cmd[0]}" -i <temp.y4m> ... -b "{encoded_path}"'
                )
                try:
                    _emit_encode_log_line(
                        "[BluraySubtitle] SVT-AV1: temp y4m file mode (BLURAYSUB_SVT_WIN_TEMP_Y4M=1); high disk use."
                    )
                except Exception:
                    pass
            else:
                cmd_echo = f'"{vspipe_exe}" --container y4m "{vpy_path}" - | {format_encoder_command(enc_cmd)}'
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
            actual_video = probe_actual_encode_source(encoded_path) if hardware_device or hdr_to_sdr else None
            if hardware_device:
                verify_encoded_dimensions(encoded_path, actual_video.stream, expected_size)
                pixels = actual_video.stream.get('pix_fmt')
                if actual_video.codec_name != encoder or not yuv_format_matches(pixels, chroma_format, bd):
                    raise RuntimeError(translate_text(
                        'Hardware encoder did not produce the selected codec, bit depth and chroma sampling: {path}'
                    ).format(path=encoded_path))
            elif cpu_command is not None or chroma_format != 'yuv420' or expected_size is not None:
                command.verify_output(encoded_path, bd, chroma_format, expected_size=expected_size)
            if hdr_to_sdr:
                verify_sdr_encode(actual_video, expect_bt709=encoded_video_bt709)
            if encode_dovi_plan and dolby_vision_metadata_active:
                dolby_vision_verified = False
                if native_dolby_vision:
                    failure_stage = 'Dolby Vision RPU verification'
                    try:
                        verify_dolby_vision_rpu(
                            encoded_path,
                            expected_output_frames,
                            8,
                        )
                    except TaskCancelled:
                        raise
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
                    try:
                        inject_dolby_vision_rpu(
                            encoded_path, encode_dovi_plan, expected_frame_count=expected_output_frames,
                        )
                    except TaskCancelled:
                        raise
                    except Exception as error:
                        dolby_vision_metadata_active = False
                        _record_nonblocking_hdr_automation_failure(
                            self,
                            output_file,
                            output_file,
                            failure_stage,
                            'Dolby Vision metadata could not be verified in the encoded video. '
                            'Encoding will continue: {path}. Error report: {report}',
                            error,
                        )
            if hdr10plus_metadata_active:
                hdr10plus_verified = False
                if native_hdr10plus:
                    try:
                        verify_hdr10plus_metadata(encoded_path)
                    except TaskCancelled:
                        raise
                    except Exception:
                        pass
                    else:
                        hdr10plus_verified = True
                if not hdr10plus_verified:
                    try:
                        inject_hdr10plus_metadata(
                            encoded_path,
                            hdr10plus_json_path,
                            dolby_vision_frames=expected_output_frames if dolby_vision_metadata_active else None,
                        )
                    except TaskCancelled:
                        raise
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
                encoded_video_hdr=expected_final_video_metadata if hardware_device else None,
                encoded_video_bt709=encoded_video_bt709,
                video_timestamps_file=output_timestamps_path,
                subtitle_file=soft_subtitle,
                subtitle_language=subtitle_language,
                audio_encoding=audio_encoding,
                wave64_bit_depth=wave64_bit_depth,
                audio_timeline_by_track=audio_timeline_by_track,
                detect_audio_gaps=detect_audio_gaps,
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
            except TaskCancelled:
                raise
            except Exception as error:
                final_verification_errors.append(error)
            if hdr10plus_metadata_active:
                try:
                    verify_hdr10plus_metadata(output_file)
                except TaskCancelled:
                    raise
                except Exception as error:
                    final_verification_errors.append(error)
                    hdr10plus_metadata_active = False
            if dolby_vision_metadata_active:
                try:
                    verify_dolby_vision_rpu(
                        output_file,
                        expected_output_frames,
                        8,
                    )
                except TaskCancelled:
                    raise
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
                        ffmpeg_executable=tool_path("FFMPEG_PATH"),
                        ffprobe_executable=tool_path("FFPROBE_PATH"),
                        encoded_path=output_file,
                        expected_reference_frames=expected_output_frames,
                        frame_timestamps_ns=output_timeline.timestamps_ns[:-1],
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
            if dovi_completion_warning:
                self.encode_warnings.append(dovi_completion_warning)
                _emit_encode_log_line(f'[encode-dovi] {dovi_completion_warning}')
        except TaskCancelled:
            retained_artifacts = []
            for path in (
                    encoded_path,
                    output_timestamps_path,
                    hdr10plus_json_path,
                    dovi_injected_path,
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
                    output_timestamps_path,
                    hdr10plus_json_path,
                    dovi_injected_path,
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
            force_remove_file(output_timestamps_path)
            if os.path.isfile(encoded_path):
                force_remove_file(encoded_path)
            if os.path.isfile(dovi_injected_path):
                force_remove_file(dovi_injected_path)
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
