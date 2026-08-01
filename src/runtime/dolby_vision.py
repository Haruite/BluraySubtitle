"""Shared Dolby Vision preparation and HEVC writing operations."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass

from src.core import find_mkvtoolnix, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import run_command
from src.runtime.video_crop import VideoCropPlan


def dolby_vision_tool_path() -> str:
    """Return the configured or discoverable dovi_tool executable."""
    configured_path = str(core_settings.DOVI_TOOL_PATH or '').strip()
    if configured_path and os.path.isfile(configured_path):
        return configured_path
    return shutil.which('dovi_tool') or shutil.which('dovi_tool.exe') or ''


@dataclass(frozen=True)
class DolbyVisionEncodePlan:
    """Task-owned files used to preserve Dolby Vision through an HEVC encode."""

    base_layer_path: str
    rpu_path: str
    work_folder: str

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
) -> DolbyVisionEncodePlan:
    """Extract a Dolby Vision track, create a profile 8.1 BL, and extract converted RPU metadata."""
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
    enhancement_layer = os.path.join(work_folder, 'enhancement-layer.hevc')
    rpu_path = os.path.join(work_folder, 'rpu.bin')
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

        demux_command = [
            dovi_tool,
            '-m',
            '2',
            'demux',
            '-e',
            enhancement_layer,
            '-b',
            base_layer,
            source_hevc,
        ]
        if run_command(demux_command, cwd=work_folder, timeout=7200,
                       log_template='Dolby Vision command: {command}').returncode != 0 or not (
                os.path.isfile(base_layer) and os.path.getsize(base_layer) > 0
        ):
            raise RuntimeError(
                translate_text('dovi_tool did not create the Dolby Vision base layer: {path}').format(
                    path=source_path
                )
            )

        # The encoded output is single-layer, so its RPU must be converted from profile 7 to profile 8.1.
        rpu_command = [
            dovi_tool,
            '-m',
            '2',
            'extract-rpu',
            source_hevc,
            '-o',
            extracted_rpu_path,
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
        return DolbyVisionEncodePlan(base_layer, rpu_path, work_folder)
    except Exception as error:
        artifact_paths = tuple(
            path
            for path in (extracted_rpu_path, rpu_path)
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


def mux_dolby_vision_layers(base_layer: str, enhancement_layer: str) -> None:
    """Convert a dual-layer profile 7 pair to a single-layer profile 8.1 stream.

    dovi_tool mode 2 rewrites the RPU for profile 8.1 while ``--discard`` removes the enhancement-layer video.
    The result replaces the task-owned BL only after dovi_tool creates a non-empty temporary output.
    """
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
        '-m',
        '2',
        'mux',
        '--bl',
        base_path,
        '--el',
        enhancement_path,
        '--discard',
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
    'mux_dolby_vision_layers',
    'prepare_dolby_vision_encode',
    'verify_dolby_vision_rpu',
]
