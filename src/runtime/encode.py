"""Plain-data contract and deterministic preflight for Blu-ray Encode."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.core.i18n import translate_text
from src.core.tool_paths import ENCODER_PATH_NAMES, require_tool_path, tool_path
from src.runtime.audio_conversion import (
    AudioEncodingSettings,
    validate_audio_cleanup_tools,
    validate_audio_conversion_tools,
)
from src.runtime.frame_check import frame_check_report_path
from src.runtime.encode_source import probe_svt_av1_bit_depths
from src.runtime.hardware_encode import GPU_BACKENDS, VideoEncodeChoice, hardware_encoder_parameters
from src.runtime.sp import SpEntry


@dataclass(frozen=True)
class EncodeSettings:
    """Encode controls captured at task launch."""

    encoder_parameters: str
    subtitle_mode: str
    encoder: str
    bit_depth: str
    use_getnative: bool
    default_lossless_audio_codec: str
    auto_crop_black_borders: bool = False
    output_comparison_images: bool = True
    check_corrupted_frames: bool = False
    frame_check_luma_psnr_threshold_db: float = 30.0
    frame_check_chroma_psnr_threshold_db: float = 30.0
    vpy_denoise_strength: float = 0.6
    vpy_dehalo_strength: float = 0.0
    vpy_dering_strength: float = 0.0
    vpy_deband_strength: float = 0.5
    vpy_antialiasing_strength: float = 0.5
    audio_encoding: AudioEncodingSettings = AudioEncodingSettings()

    def cpu_encode_choice(self) -> VideoEncodeChoice:
        return VideoEncodeChoice(self.encoder, self.bit_depth, self.encoder_parameters)


@dataclass(frozen=True)
class EncodeRow:
    """One visible main or SP row and its exact planned output."""

    source_path: str
    output_path: str
    vpy_path: str
    subtitle_path: str = ''
    subtitle_language: str = ''
    configuration_key: int | None = None
    configuration: dict[str, int | str] | None = None
    sp_entry: SpEntry | None = None
    selected: bool = True
    uses_main_output: bool = False
    audio_tracks: tuple[str, ...] = ()
    subtitle_tracks: tuple[str, ...] = ()
    audio_codec_choices: tuple[str, ...] = ()
    track_language_overrides: tuple[tuple[str, str], ...] = ()
    video_encode: VideoEncodeChoice | None = None


@dataclass(frozen=True)
class EncodeRequest:
    """Complete GUI snapshot consumed by one Encode worker."""

    input_mode: str
    source_root: str
    output_folder: str
    staging_folder: str
    main_rows: tuple[EncodeRow, ...]
    sp_rows: tuple[EncodeRow, ...]
    settings: EncodeSettings
    selected_mpls: tuple[tuple[str, str], ...] = ()
    movie_mode: bool = False
    mux_dolby_vision: bool = True
    allow_partial_missing_non_video_tracks: bool = False
    track_selection_config: dict[str, dict[str, list[str]]] | None = None
    track_language_config: dict[str, dict[str, str]] | None = None
    main_alternate_mpls: dict[str, tuple[str, ...]] | None = None


def validate_encode_request(request: EncodeRequest, check_tools: bool = False) -> None:
    """Reject deterministic request errors before Encode creates an output."""
    if request.input_mode not in ('bdmv', 'remux'):
        raise ValueError(
            translate_text('Unsupported encode input mode: {mode}').format(mode=request.input_mode)
        )
    valid_settings = (
        ('subtitle_mode', request.settings.subtitle_mode, ('external', 'soft', 'hard')),
        ('encoder', request.settings.encoder, ('x264', 'x265', 'svtav1')),
        ('bit_depth', request.settings.bit_depth, ('8', '10', '12')),
        (
            'default_lossless_audio_codec',
            request.settings.default_lossless_audio_codec,
            ('flac', 'aac', 'opus'),
        ),
    )
    for setting_name, setting_value, allowed_values in valid_settings:
        if setting_value not in allowed_values or (
                setting_name == 'bit_depth'
                and request.settings.encoder == 'x264'
                and setting_value == '12'
        ):
            raise ValueError(
                translate_text('Invalid encode setting: {name}={value}').format(
                    name=setting_name,
                    value=setting_value,
                )
            )
    for setting_name, setting_value, minimum, maximum in (
            (
                'frame_check_luma_psnr_threshold_db',
                request.settings.frame_check_luma_psnr_threshold_db,
                0.0,
                100.0,
            ),
            (
                'frame_check_chroma_psnr_threshold_db',
                request.settings.frame_check_chroma_psnr_threshold_db,
                0.0,
                100.0,
            ),
            ('vpy_denoise_strength', request.settings.vpy_denoise_strength, 0.0, 3.0),
            ('vpy_dehalo_strength', request.settings.vpy_dehalo_strength, 0.0, 1.0),
            ('vpy_dering_strength', request.settings.vpy_dering_strength, 0.0, 1.0),
            ('vpy_deband_strength', request.settings.vpy_deband_strength, 0.0, 1.0),
            (
                'vpy_antialiasing_strength',
                request.settings.vpy_antialiasing_strength,
                0.0,
                1.0,
            ),
    ):
        if (
                isinstance(setting_value, bool)
                or not isinstance(setting_value, (int, float))
                or not minimum <= float(setting_value) <= maximum
        ):
            raise ValueError(
                translate_text('Invalid encode setting: {name}={value}').format(
                    name=setting_name,
                    value=setting_value,
                )
            )
    source_root = os.path.abspath(os.path.normpath(request.source_root))
    output_folder = os.path.abspath(os.path.normpath(request.output_folder))
    if not os.path.isdir(source_root):
        raise FileNotFoundError(
            translate_text('Encode source folder does not exist: {path}').format(path=source_root)
        )
    output_parent = os.path.dirname(output_folder)
    if os.path.exists(output_folder) and not os.path.isdir(output_folder):
        raise NotADirectoryError(translate_text('Output folder does not exist'))
    if not os.path.exists(output_folder) and not os.path.isdir(output_parent):
        raise FileNotFoundError(translate_text('Output folder does not exist'))
    try:
        output_is_in_source = os.path.commonpath((source_root, output_folder)) == source_root
    except ValueError:
        output_is_in_source = False
    if output_is_in_source:
        raise ValueError(
            translate_text('Encode output folder cannot be inside the source folder: {path}').format(
                path=output_folder
            )
        )
    if not request.main_rows:
        raise ValueError(translate_text('Encode task has no main rows'))

    if request.input_mode == 'bdmv':
        if not request.selected_mpls:
            raise ValueError(translate_text('Main MPLS is not selected'))

        def resolve_playlist_path(playlist_root: str, playlist_value: str) -> str:
            root = os.path.normpath(str(playlist_root or request.source_root)).rstrip(os.sep)
            raw_playlist = str(playlist_value or '').strip()
            if os.path.isfile(raw_playlist):
                return os.path.abspath(os.path.normpath(raw_playlist))
            normalized_playlist = raw_playlist.replace('\\', '/')
            if normalized_playlist.lower().endswith('.mpls'):
                if normalized_playlist.lower().startswith('bdmv/playlist/'):
                    return os.path.abspath(os.path.join(root, *normalized_playlist.split('/')))
                playlist_name = os.path.basename(normalized_playlist)
            else:
                playlist_name = os.path.splitext(os.path.basename(normalized_playlist))[0] + '.mpls'
            return os.path.abspath(os.path.join(root, 'BDMV', 'PLAYLIST', playlist_name))

        selected_playlist_paths: set[str] = set()
        for playlist_root, selected_playlist in request.selected_mpls:
            playlist_path = resolve_playlist_path(playlist_root, selected_playlist)
            if not os.path.isfile(playlist_path):
                raise FileNotFoundError(
                    translate_text('Selected main playlist does not exist: {path}').format(
                        path=playlist_path
                    )
                )
            normalized_playlist = os.path.normcase(playlist_path)
            if normalized_playlist in selected_playlist_paths:
                raise ValueError(
                    translate_text('Selected main playlist is duplicated: {path}').format(
                        path=playlist_path
                    )
                )
            selected_playlist_paths.add(normalized_playlist)
        configuration_keys = [row.configuration_key for row in request.main_rows]
        if any(key is None or row.configuration is None for key, row in zip(configuration_keys, request.main_rows)):
            raise ValueError(translate_text('Encode main row has no task configuration'))
        if len(set(configuration_keys)) != len(configuration_keys):
            raise ValueError(translate_text('Encode main rows contain duplicate task configuration keys'))
        configured_playlist_paths: set[str] = set()
        for row in request.main_rows:
            row_configuration = row.configuration or {}
            configured_playlist = resolve_playlist_path(
                str(row_configuration.get('folder') or request.source_root),
                str(row_configuration.get('selected_mpls') or ''),
            )
            normalized_configured_playlist = os.path.normcase(configured_playlist)
            if normalized_configured_playlist not in selected_playlist_paths:
                raise ValueError(
                    translate_text('Task row references an unselected main playlist: {path}').format(
                        path=configured_playlist
                    )
                )
            configured_playlist_paths.add(normalized_configured_playlist)
        unconfigured_playlists = selected_playlist_paths - configured_playlist_paths
        if unconfigured_playlists:
            raise ValueError(
                translate_text('Selected main playlist has no task rows: {path}').format(
                    path=next(iter(unconfigured_playlists))
                )
            )
        if request.staging_folder:
            staging_folder = os.path.abspath(os.path.normpath(request.staging_folder))
            if os.path.isdir(staging_folder) and any(os.scandir(staging_folder)):
                raise FileExistsError(
                    translate_text('Encode staging folder is not empty: {path}').format(
                        path=staging_folder
                    )
                )

    reserved_names = {'CON', 'PRN', 'AUX', 'NUL'} | {
        f'{prefix}{number}'
        for prefix in ('COM', 'LPT')
        for number in range(1, 10)
    }
    planned_outputs: set[str] = set()
    selected_rows = [(row, False) for row in request.main_rows]
    selected_rows.extend((row, True) for row in request.sp_rows if row.selected)

    def is_valid_remux_checkpoint(row: EncodeRow) -> bool:
        if request.input_mode != 'remux' or not os.path.exists(row.output_path):
            return False
        if os.path.isdir(row.source_path):
            return os.path.isdir(row.output_path)
        return os.path.isfile(row.output_path) and os.path.getsize(row.output_path) > 0

    for row_number, (row, is_sp_row) in enumerate(selected_rows, 1):
        row_is_checkpoint = is_valid_remux_checkpoint(row)
        choice = row.video_encode
        if not row_is_checkpoint and choice is not None:
            device = choice.device
            if device is None:
                supported = choice.encoder in ENCODER_PATH_NAMES and choice.bit_depth in (
                    ('8', '10') if choice.encoder == 'x264' else ('8', '10', '12')
                )
            else:
                supported = device.backend in GPU_BACKENDS and (choice.encoder, choice.bit_depth) in device.formats
            if not supported:
                raise ValueError(translate_text('Unsupported video encoding mode in row {row}').format(row=row_number))
            if device is not None:
                try:
                    hardware_encoder_parameters(choice.parameters)
                except ValueError as error:
                    raise ValueError(translate_text('Video encoding parameters in row {row}: {detail}').format(
                        row=row_number, detail=error,
                    )) from error
        if len(row.audio_tracks) != len(row.audio_codec_choices):
            raise ValueError(
                translate_text('Audio codec choices do not match selected tracks in row {row}').format(
                    row=row_number
                )
            )
        if any(codec not in ('flac', 'aac', 'opus') for codec in row.audio_codec_choices):
            raise ValueError(
                translate_text('Invalid audio codec choice in row {row}').format(row=row_number)
            )
        source_path = os.path.abspath(os.path.normpath(row.source_path)) if row.source_path else ''
        if request.input_mode == 'remux' and not os.path.isfile(source_path):
            message = 'SP source does not exist in row {row}' if is_sp_row \
                else 'Encode source does not exist in row {row}'
            raise FileNotFoundError(translate_text(message).format(row=row_number))
        subtitle_path = os.path.abspath(os.path.normpath(row.subtitle_path)) if row.subtitle_path else ''
        external_subtitle_is_checkpoint = False
        if (
                row_is_checkpoint
                and subtitle_path
                and request.settings.subtitle_mode == 'external'
        ):
            subtitle_extension = os.path.splitext(subtitle_path)[1]
            external_subtitle_path = (
                os.path.splitext(os.path.abspath(row.output_path))[0]
                + subtitle_extension
            )
            external_subtitle_is_checkpoint = os.path.isfile(
                external_subtitle_path
            )
        subtitle_source_is_required = not row_is_checkpoint or (
            request.settings.subtitle_mode == 'external'
            and not external_subtitle_is_checkpoint
        )
        if (
                subtitle_path
                and subtitle_source_is_required
                and not os.path.isfile(subtitle_path)
        ):
            raise FileNotFoundError(
                translate_text('Subtitle file does not exist: {path}').format(path=subtitle_path)
            )
        if (
                subtitle_path
                and not row_is_checkpoint
                and request.settings.subtitle_mode == 'hard'
                and os.path.splitext(subtitle_path)[1].lower() not in ('.ass', '.ssa', '.srt')
        ):
            raise ValueError(
                translate_text('Hardsub supports only ASS/SSA/SRT: {path}').format(
                    path=subtitle_path
                )
            )
        if (not row_is_checkpoint) and (not is_sp_row or (
                str(row.output_path).lower().endswith('.mkv')
                and not row.uses_main_output
        )):
            vpy_path = os.path.abspath(os.path.normpath(row.vpy_path)) if row.vpy_path else ''
            if not os.path.isfile(vpy_path):
                raise FileNotFoundError(
                    translate_text('VPy file does not exist in row {row}: {path}').format(
                        row=row_number,
                        path=vpy_path,
                    )
                )

        output_path = os.path.abspath(os.path.normpath(row.output_path)) if row.output_path else ''
        output_name = os.path.basename(output_path)
        if (
                (not is_sp_row and not output_name.lower().endswith('.mkv'))
                or not output_name
                or not os.path.splitext(output_name)[0]
                or (
                    not is_sp_row
                    and os.path.normcase(os.path.dirname(output_path))
                    != os.path.normcase(output_folder)
                )
                or output_name.rstrip(' .') != output_name
                or any(character in output_name for character in '<>:"/\\|?*')
                or any(ord(character) < 32 for character in output_name)
                or os.path.splitext(output_name)[0].upper() in reserved_names
        ):
            raise ValueError(
                translate_text('Invalid encode output name in row {row}: {name}').format(
                    row=row_number,
                    name=output_name,
                )
            )
        try:
            output_is_planned = bool(output_path) and os.path.commonpath(
                (output_folder, output_path)
            ) == output_folder
        except ValueError:
            output_is_planned = False
        if not output_is_planned:
            raise ValueError(
                translate_text('Encode output is outside the selected output folder: {path}').format(
                    path=output_path
                )
            )
        normalized_output = os.path.normcase(output_path)
        if normalized_output in planned_outputs:
            if not (request.input_mode == 'bdmv' and is_sp_row and row.uses_main_output):
                raise ValueError(translate_text('Duplicate output path: {path}').format(path=output_path))
        planned_outputs.add(normalized_output)
        if os.path.exists(output_path):
            if request.input_mode != 'remux':
                raise FileExistsError(
                    translate_text('Output file already exists: {path}').format(path=output_path)
                )
            if not row_is_checkpoint:
                raise FileExistsError(
                    translate_text('Existing resumable output is invalid: {path}').format(path=output_path)
                )
        elif request.settings.check_corrupted_frames and (
                not is_sp_row
                or (
                    output_name.lower().endswith('.mkv')
                    and not row.uses_main_output
                )
        ):
            report_path = frame_check_report_path(output_path)
            if os.path.exists(report_path):
                raise FileExistsError(
                    translate_text('Frame check report already exists: {path}').format(
                        path=report_path
                    )
                )

    if not check_tools:
        return
    pending_rows = [
        (row, is_sp_row)
        for row, is_sp_row in selected_rows
        if not is_valid_remux_checkpoint(row)
    ]
    pending_video_rows = [
        (row, is_sp_row)
        for row, is_sp_row in pending_rows
        if not is_sp_row or (
            str(row.output_path).lower().endswith('.mkv')
            and not row.uses_main_output
        )
    ]
    pending_matroska_rows = [
        (row, is_sp_row)
        for row, is_sp_row in pending_rows
        if os.path.splitext(row.output_path)[1].lower() in ('.mkv', '.mka', '.mks')
    ]
    if pending_video_rows:
        require_tool_path("VSPIPE_PATH")
        if tool_path("PLUGIN_PATH"):
            require_tool_path("PLUGIN_PATH")
        choices = {row.video_encode or request.settings.cpu_encode_choice() for row, _ in pending_video_rows}
        for encoder, depth in {(choice.encoder, choice.bit_depth) for choice in choices if choice.device is None}:
            encoder_path = require_tool_path(ENCODER_PATH_NAMES[encoder])
            if encoder == 'svtav1' and depth == '12' and '12' not in probe_svt_av1_bit_depths(encoder_path):
                raise ValueError(translate_text(
                    'The selected SVT-AV1 encoder does not advertise 12-bit support: {path}'
                ).format(path=encoder_path))
        if any(choice.device is not None for choice in choices):
            require_tool_path("FFMPEG_PATH")
            require_tool_path("FFPROBE_PATH")
            require_tool_path("MKV_INFO_PATH")
    if pending_matroska_rows:
        require_tool_path("MKV_MERGE_PATH")
        if pending_video_rows:
            require_tool_path("MKV_EXTRACT_PATH")
    if request.input_mode == 'bdmv' and any(
            row.audio_tracks or row.audio_codec_choices
            for row, _is_sp_row in pending_rows
    ):
        validate_audio_cleanup_tools()
    if request.input_mode == 'remux':
        for row, _is_sp_row in pending_rows:
            source_extension = os.path.splitext(row.source_path)[1].lower()
            if source_extension not in ('.mkv', '.mka'):
                continue
            validate_audio_conversion_tools(
                row.source_path,
                row.audio_tracks,
                row.audio_codec_choices,
            )
    if request.input_mode == 'bdmv' and pending_rows and any(
            (languages or {})
            for languages in (request.track_language_config or {}).values()
    ):
        require_tool_path("MKV_PROP_EDIT_PATH")
    if (
            request.settings.output_comparison_images
            or (
                pending_video_rows
                and (
                    request.settings.auto_crop_black_borders
                    or request.settings.check_corrupted_frames
                )
            )
    ):
        require_tool_path("FFMPEG_PATH")
        require_tool_path("FFPROBE_PATH")


__all__ = ['EncodeRequest', 'EncodeRow', 'EncodeSettings', 'validate_encode_request']
