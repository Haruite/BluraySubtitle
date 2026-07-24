"""Shared Dolby Vision preparation and HEVC writing operations."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from src.core import find_mkvtoolnix, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text


def dolby_vision_tool_path() -> str:
    """Return the configured or discoverable dovi_tool executable."""
    configured_path = str(core_settings.DOVI_TOOL_PATH or '').strip()
    if configured_path and os.path.isfile(configured_path):
        return configured_path
    return shutil.which('dovi_tool') or shutil.which('dovi_tool.exe') or ''


def _run_dolby_vision_command(
        command: list[str],
        *,
        cwd: str | None = None,
        timeout: int = 7200,
) -> int:
    print(
        translate_text('Dolby Vision command: {command}').format(
            command=subprocess.list2cmdline(command)
        ),
        flush=True,
    )
    completed = subprocess.run(
        command,
        cwd=cwd,
        shell=False,
        timeout=timeout,
    )
    return int(completed.returncode)


@dataclass(frozen=True)
class DolbyVisionEncodePlan:
    """Task-owned files used to preserve Dolby Vision through an HEVC encode."""

    base_layer_path: str
    rpu_path: str
    work_folder: str

    def cleanup(self) -> None:
        if self.work_folder and os.path.isdir(self.work_folder):
            shutil.rmtree(self.work_folder, ignore_errors=True)


def prepare_dolby_vision_encode(
        mkv_path: str,
        track_id: int,
        temporary_parent: str,
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
    try:
        extract_command = [mkvextract]
        ui_language = mkvtoolnix_ui_language_arg().strip()
        if ui_language:
            extract_command.extend(ui_language.split())
        extract_command.extend(['tracks', source_path, f'{int(track_id)}:{source_hevc}'])
        extract_result = subprocess.run(extract_command, shell=False)
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
        if _run_dolby_vision_command(demux_command, cwd=work_folder) != 0 or not (
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
            rpu_path,
        ]
        if _run_dolby_vision_command(rpu_command, cwd=work_folder) != 0 or not (
                os.path.isfile(rpu_path) and os.path.getsize(rpu_path) > 0
        ):
            raise RuntimeError(
                translate_text('dovi_tool did not create Dolby Vision RPU metadata: {path}').format(
                    path=source_path
                )
            )
        return DolbyVisionEncodePlan(base_layer, rpu_path, work_folder)
    except Exception:
        shutil.rmtree(work_folder, ignore_errors=True)
        raise


def inject_dolby_vision_rpu(encoded_hevc: str, plan: DolbyVisionEncodePlan) -> None:
    """Inject profile 8.1 RPU metadata and replace the encoded HEVC only after success."""
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
    try:
        if _run_dolby_vision_command(command) != 0 or not (
                os.path.isfile(temporary_output) and os.path.getsize(temporary_output) > 0
        ):
            raise RuntimeError(
                translate_text('dovi_tool did not create the injected HEVC output: {path}').format(
                    path=encoded_path
                )
            )
        os.replace(temporary_output, encoded_path)
    finally:
        if os.path.isfile(temporary_output):
            os.remove(temporary_output)


def mux_dolby_vision_layers(base_layer: str, enhancement_layer: str) -> None:
    """Combine task-owned BL and EL streams as profile 8.1 and replace BL atomically."""
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
        if _run_dolby_vision_command(command) != 0 or not (
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
    'dolby_vision_tool_path',
    'inject_dolby_vision_rpu',
    'mux_dolby_vision_layers',
    'prepare_dolby_vision_encode',
]
