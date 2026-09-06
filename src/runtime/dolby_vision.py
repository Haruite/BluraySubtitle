"""Shared Dolby Vision preparation and HEVC writing operations."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import tempfile
from dataclasses import dataclass
from typing import Callable

from src.core import find_mkvtoolnix, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import run_command
from src.runtime.video_crop import VideoCropPlan
from src.runtime import TaskCancelled


def dolby_vision_tool_path() -> str:
    """Return the configured or discoverable dovi_tool executable."""
    configured_path = str(core_settings.DOVI_TOOL_PATH or '').strip()
    if configured_path and os.path.isfile(configured_path):
        return configured_path
    return shutil.which('dovi_tool') or shutil.which('dovi_tool.exe') or ''


def read_dolby_vision_rpu_info(rpu_path: str) -> tuple[int | None, str]:
    """Read original metadata; only an explicit all-MEL result permits dropping EL."""
    try:
        result = run_command(
            [dolby_vision_tool_path(), 'info', '-s', '-i', rpu_path],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=7200,
        )
        result.check_returncode()
        match = re.search(
            r'^\s*Profile:\s*(\d+)(?:\s+\(([^)]+)\))?\s*$',
            result.stdout or '', re.MULTILINE,
        )
        if match:
            profile = int(match.group(1))
            layer_type = ('MEL' if match.group(2) == 'MEL' else 'FEL') if profile == 7 else ''
            return profile, layer_type
        raise ValueError(translate_text('Missing or mixed Dolby Vision profile summary'))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(translate_text(
            'Dolby Vision identification failed; treating the source as FEL: {path} ({error})'
        ).format(path=rpu_path, error=error))
        return None, 'FEL'


def inspect_dolby_vision(
        source_path: str,
        rpu_path: str,
        *,
        video_pid: int | None = None,
        check_cancel: Callable[[], None] | None = None,
) -> tuple[int | None, str]:
    """Extract original RPU without decoding video; classification failures use FEL."""
    processes = []
    try:
        with tempfile.TemporaryFile() as demux_errors:
            producer = None
            if video_pid is not None:
                producer = run_command(
                    [
                        core_settings.FFMPEG_PATH, '-nostdin', '-v', 'error',
                        '-i', source_path, '-map', f'0:i:{video_pid}',
                        '-c:v', 'copy', '-f', 'hevc', '-',
                    ],
                    wait=False, stdout=subprocess.PIPE, stderr=demux_errors,
                )
                processes.append(producer)
            extractor = run_command(
                [
                    dolby_vision_tool_path(), 'extract-rpu',
                    '-' if producer else source_path, '-o', rpu_path,
                ],
                wait=False, stdin=producer.stdout if producer else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
            )
            processes.append(extractor)
            if producer and producer.stdout:
                producer.stdout.close()
            deadline = time.monotonic() + 7200
            while True:
                if check_cancel:
                    check_cancel()
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(extractor.args, 7200)
                try:
                    output, _ = extractor.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if extractor.returncode:
                raise ValueError(output.strip() or translate_text(
                    'dovi_tool exited with code {code}'
                ).format(code=extractor.returncode))
            if producer and producer.wait(timeout=10):
                demux_errors.seek(0)
                raise ValueError(demux_errors.read().decode('utf-8', errors='replace').strip())
            return read_dolby_vision_rpu_info(rpu_path)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(translate_text(
            'Dolby Vision identification failed; treating the source as FEL: {path} ({error})'
        ).format(path=source_path, error=error))
        return None, 'FEL'
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.kill()
            process.wait()


@dataclass(frozen=True)
class DolbyVisionEncodePlan:
    """Task-owned files used to preserve Dolby Vision through an HEVC encode."""

    base_layer_path: str
    rpu_path: str
    work_folder: str
    fel_residual_discarded: bool = False

    def cleanup(self) -> None:
        if self.work_folder and os.path.isdir(self.work_folder):
            shutil.rmtree(self.work_folder, ignore_errors=True)


class DolbyVisionPreparationFailure(RuntimeError):
    """Preparation failure with extracted metadata retained for the caller."""

    def __init__(
            self,
            message: str,
            artifact_paths: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.artifact_paths = artifact_paths


def prepare_dolby_vision_encode(
        mkv_path: str,
        track_id: int,
        temporary_parent: str,
        crop_plan: VideoCropPlan | None = None,
        *,
        check_cancel: Callable[[], None] | None = None,
) -> DolbyVisionEncodePlan:
    """Identify the original layer and prepare base video plus profile 8.1 RPU for Encode."""
    source_path = os.path.abspath(os.path.normpath(mkv_path))
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)
    dovi_tool = dolby_vision_tool_path()
    if not dovi_tool:
        raise FileNotFoundError(translate_text('dovi_tool executable does not exist'))
    find_mkvtoolnix()
    mkvextract = str(core_settings.MKV_EXTRACT_PATH or '').strip() or shutil.which('mkvextract') or ''
    if not mkvextract:
        raise FileNotFoundError(translate_text('mkvextract not found'))

    os.makedirs(temporary_parent, exist_ok=True)
    work_folder = tempfile.mkdtemp(prefix='_dovi_encode_', dir=temporary_parent)
    source_hevc = os.path.join(work_folder, 'source.hevc')
    base_layer = os.path.join(work_folder, 'base-layer.hevc')
    rpu_path = os.path.join(work_folder, 'rpu.bin')
    original_rpu_path = os.path.join(work_folder, 'rpu-original.bin')
    extracted_rpu_path = (
        os.path.join(work_folder, 'rpu-source.bin')
        if crop_plan is not None and crop_plan.has_crop
        else rpu_path
    )
    try:
        extract_command = [mkvextract]
        ui_language = mkvtoolnix_ui_language_arg().strip()
        if ui_language:
            extract_command.extend(ui_language.split())
        extract_command.extend(['tracks', source_path, f'{int(track_id)}:{source_hevc}'])
        extract_result = run_command(extract_command)
        if (
                extract_result.returncode not in (0, 1)
                or not os.path.isfile(source_hevc)
                or os.path.getsize(source_hevc) == 0
        ):
            raise RuntimeError(
                translate_text('mkvextract did not create the Dolby Vision video track: {path}').format(
                    path=source_path
                )
            )

        source_profile, layer_type = inspect_dolby_vision(
            source_hevc, original_rpu_path, check_cancel=check_cancel,
        )
        fel_residual_discarded = source_profile is None or (
            source_profile == 7 and layer_type != 'MEL'
        )
        # Removing DV data also works for P8.1 inputs that have no enhancement layer to demux.
        base_command = [dovi_tool, 'remove', source_hevc, '-o', base_layer]
        if run_command(base_command, cwd=work_folder, timeout=7200,
                       log_template='Dolby Vision command: {command}').returncode != 0 or not (
                os.path.isfile(base_layer) and os.path.getsize(base_layer) > 0
        ):
            raise RuntimeError(
                translate_text('dovi_tool did not create the Dolby Vision base layer: {path}').format(
                    path=source_path
                )
            )

        # Convert the already extracted metadata after identifying the original EL.
        conversion_config = os.path.join(work_folder, 'rpu-conversion.json')
        with open(conversion_config, 'w', encoding='utf-8', newline='') as stream:
            stream.write('{"mode": 2}\r\n')
        rpu_command = [
            dovi_tool, 'editor', '-i', original_rpu_path,
            '-j', conversion_config, '-o', extracted_rpu_path,
        ]
        if run_command(rpu_command, cwd=work_folder, timeout=7200,
                       log_template='Dolby Vision command: {command}').returncode != 0 or not (
                os.path.isfile(extracted_rpu_path)
                and os.path.getsize(extracted_rpu_path) > 0
        ):
            raise RuntimeError(
                translate_text('dovi_tool did not create Dolby Vision RPU metadata: {path}').format(
                    path=source_path
                )
            )
        if crop_plan is not None and crop_plan.has_crop:
            edit_dolby_vision_rpu_for_crop(
                extracted_rpu_path,
                rpu_path,
                crop_plan,
                work_folder,
            )
        return DolbyVisionEncodePlan(
            base_layer, rpu_path, work_folder, fel_residual_discarded,
        )
    except TaskCancelled:
        shutil.rmtree(work_folder, ignore_errors=True)
        raise
    except Exception as error:
        artifact_paths = tuple(
            path
            for path in (original_rpu_path, extracted_rpu_path, rpu_path)
            if os.path.isfile(path) and os.path.getsize(path) > 0
        )
        if artifact_paths:
            raise DolbyVisionPreparationFailure(
                str(error),
                artifact_paths,
            ) from error
        shutil.rmtree(work_folder, ignore_errors=True)
        raise


def edit_dolby_vision_rpu_for_crop(
        source_rpu: str,
        output_rpu: str,
        crop_plan: VideoCropPlan,
        work_folder: str,
) -> None:
    """Subtract a fixed physical crop from every Dolby Vision L5 preset."""
    if not crop_plan.has_crop:
        raise ValueError('Dolby Vision RPU crop requires non-zero margins')
    dovi_tool = dolby_vision_tool_path()
    if not dovi_tool:
        raise FileNotFoundError(translate_text('dovi_tool executable does not exist'))
    level5_path = os.path.join(work_folder, 'rpu-level5.json')
    editor_path = os.path.join(work_folder, 'rpu-crop-editor.json')
    export_result = run_command(
        [
            dovi_tool,
            'export',
            '-i',
            source_rpu,
            '-d',
            f'level5={level5_path}',
        ],
        cwd=work_folder,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=7200,
        log_template='Dolby Vision command: {command}',
    )
    if export_result.returncode != 0 or not os.path.isfile(level5_path):
        detail = str(export_result.stderr or export_result.stdout or '').strip()
        raise RuntimeError(detail or translate_text(
            'dovi_tool did not export Dolby Vision L5 metadata: {path}'
        ).format(path=source_rpu))
    try:
        with open(level5_path, 'r', encoding='utf-8') as stream:
            editor_config = json.load(stream)
        if not isinstance(editor_config, dict):
            raise ValueError('Dolby Vision L5 editor config must be an object')
        active_area = editor_config.get('active_area')
        if not isinstance(active_area, dict):
            active_area = {'crop': True}
            editor_config['active_area'] = active_area
        else:
            presets = active_area.get('presets')
            if not isinstance(presets, list) or not presets:
                active_area.clear()
                active_area['crop'] = True
            else:
                margins = {
                    'left': crop_plan.left,
                    'right': crop_plan.right,
                    'top': crop_plan.top,
                    'bottom': crop_plan.bottom,
                }
                for preset in presets:
                    if not isinstance(preset, dict):
                        raise ValueError('Dolby Vision L5 preset must be an object')
                    for side, physical_crop in margins.items():
                        value = preset.get(side)
                        if type(value) is not int or value < 0:
                            raise ValueError(
                                f'Dolby Vision L5 {side} offset must be a non-negative integer'
                            )
                        preset[side] = max(0, value - physical_crop)
                active_area.pop('crop', None)
        with open(editor_path, 'w', encoding='utf-8', newline='') as stream:
            stream.write(
                json.dumps(editor_config, indent=2).replace('\n', '\r\n')
                + '\r\n'
            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            translate_text('Dolby Vision L5 metadata is invalid: {path}').format(
                path=level5_path
            )
        ) from error

    editor_result = run_command(
        [
            dovi_tool,
            'editor',
            '-i',
            source_rpu,
            '-j',
            editor_path,
            '-o',
            output_rpu,
        ],
        cwd=work_folder,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=7200,
        log_template='Dolby Vision command: {command}',
    )
    if editor_result.returncode != 0 or not (
            os.path.isfile(output_rpu) and os.path.getsize(output_rpu) > 0
    ):
        detail = str(editor_result.stderr or editor_result.stdout or '').strip()
        raise RuntimeError(detail or translate_text(
            'dovi_tool did not create cropped Dolby Vision RPU metadata: {path}'
        ).format(path=output_rpu))
    info_result = run_command(
        [dovi_tool, 'info', '-s', '-i', output_rpu],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=7200,
        log_template='Dolby Vision command: {command}',
    )
    summary = f'{info_result.stdout or ""}\n{info_result.stderr or ""}'
    profile_match = re.search(r'Profile:\s*(\d+)', summary, flags=re.IGNORECASE)
    if info_result.returncode != 0 or not profile_match or int(profile_match.group(1)) != 8:
        raise RuntimeError(
            translate_text('Cropped Dolby Vision RPU verification failed: {path}').format(
                path=output_rpu
            )
        )


def inject_dolby_vision_rpu(
        encoded_hevc: str,
        plan: DolbyVisionEncodePlan,
) -> None:
    """Inject profile 8.1 RPU metadata, retaining a non-empty partial output on failure."""
    encoded_path = os.path.abspath(os.path.normpath(encoded_hevc))
    if not encoded_path.lower().endswith('.hevc'):
        raise ValueError(
            translate_text('Dolby Vision output must be an HEVC stream: {path}').format(
                path=encoded_path
            )
        )
    dovi_tool = dolby_vision_tool_path()
    if not dovi_tool:
        raise FileNotFoundError(translate_text('dovi_tool executable does not exist'))
    temporary_output = encoded_path + '.dovi.hevc'
    if os.path.isfile(temporary_output):
        os.remove(temporary_output)
    command = [
        dovi_tool,
        'inject-rpu',
        '-i',
        encoded_path,
        '--rpu-in',
        plan.rpu_path,
        '-o',
        temporary_output,
    ]
    if run_command(command, timeout=7200,
                   log_template='Dolby Vision command: {command}').returncode != 0 or not (
            os.path.isfile(temporary_output) and os.path.getsize(temporary_output) > 0
    ):
        if os.path.isfile(temporary_output) and os.path.getsize(temporary_output) == 0:
            os.remove(temporary_output)
        raise RuntimeError(
            translate_text('dovi_tool did not create the injected HEVC output: {path}').format(
                path=encoded_path
            )
        )
    os.replace(temporary_output, encoded_path)


def verify_dolby_vision_rpu(
        encoded_hevc: str,
        expected_frame_count: int | None = None,
        expected_profile: int | None = None,
) -> None:
    """Require Dolby Vision RPU metadata and optionally verify its summary."""
    encoded_path = os.path.abspath(os.path.normpath(encoded_hevc))
    dovi_tool = dolby_vision_tool_path()
    if not dovi_tool:
        raise FileNotFoundError(translate_text('dovi_tool executable does not exist'))
    with tempfile.TemporaryDirectory(
            prefix='_dovi_verify_',
            dir=os.path.dirname(encoded_path),
    ) as verification_folder:
        rpu_path = os.path.join(verification_folder, 'rpu.bin')
        command = [dovi_tool, 'extract-rpu', encoded_path, '-o', rpu_path]
        if run_command(command, timeout=7200,
                       log_template='Dolby Vision command: {command}').returncode != 0 or not (
                os.path.isfile(rpu_path) and os.path.getsize(rpu_path) > 0
        ):
            raise RuntimeError(
                translate_text(
                    'dovi_tool did not find Dolby Vision RPU metadata: {path}'
                ).format(path=encoded_path)
            )
        if expected_frame_count is None and expected_profile is None:
            return
        result = run_command(
            [dovi_tool, 'info', '-s', '-i', rpu_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=7200,
            log_template='Dolby Vision command: {command}',
        )
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or '').strip()
            raise RuntimeError(
                detail or translate_text(
                    'dovi_tool did not return a Dolby Vision RPU summary: {path}'
                ).format(path=encoded_path)
            )
        summary = f'{result.stdout or ""}\n{result.stderr or ""}'
        checks = (
            ('frames', expected_frame_count, r'Frames:\s*(\d+)'),
            ('profile', expected_profile, r'Profile:\s*(\d+)'),
        )
        for field, expected, pattern in checks:
            if expected is None:
                continue
            match = re.search(pattern, summary, flags=re.IGNORECASE)
            actual = int(match.group(1)) if match else None
            if actual != expected:
                raise RuntimeError(
                    translate_text(
                        'Dolby Vision RPU summary mismatch for {field}: expected '
                        '{expected}, got {actual} ({path})'
                    ).format(
                        field=field,
                        expected=expected,
                        actual=actual if actual is not None else translate_text('unknown'),
                        path=encoded_path,
                    )
                )


def mux_dolby_vision_layers(
        base_layer: str, enhancement_layer: str, *, convert_to_p81: bool,
) -> None:
    """Convert confirmed MEL to P8.1 or preserve the original P7 BL, EL and RPU."""
    base_path = os.path.abspath(os.path.normpath(base_layer))
    enhancement_path = os.path.abspath(os.path.normpath(enhancement_layer))
    dovi_tool = dolby_vision_tool_path()
    if not dovi_tool:
        raise FileNotFoundError(translate_text('dovi_tool executable does not exist'))
    if not os.path.isfile(base_path):
        raise FileNotFoundError(base_path)
    if not os.path.isfile(enhancement_path):
        raise FileNotFoundError(enhancement_path)

    temporary_output = base_path + '.dovi-temp.hevc'
    if os.path.isfile(temporary_output):
        os.remove(temporary_output)
    command = [
        dovi_tool,
        *(['-m', '2'] if convert_to_p81 else []),
        'mux',
        '--bl',
        base_path,
        '--el',
        enhancement_path,
        *(['--discard'] if convert_to_p81 else []),
        '-o',
        temporary_output,
    ]
    try:
        if run_command(command, timeout=7200,
                       log_template='Dolby Vision command: {command}').returncode != 0 or not (
                os.path.isfile(temporary_output) and os.path.getsize(temporary_output) > 0
        ):
            raise RuntimeError(
                translate_text('dovi_tool did not create the combined Dolby Vision stream: {path}').format(
                    path=base_path
                )
            )
        os.replace(temporary_output, base_path)
    finally:
        if os.path.isfile(temporary_output):
            os.remove(temporary_output)


__all__ = [
    'DolbyVisionEncodePlan',
    'DolbyVisionPreparationFailure',
    'dolby_vision_tool_path',
    'edit_dolby_vision_rpu_for_crop',
    'inject_dolby_vision_rpu',
    'inspect_dolby_vision',
    'mux_dolby_vision_layers',
    'prepare_dolby_vision_encode',
    'verify_dolby_vision_rpu',
]
