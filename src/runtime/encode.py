"""Plain-data contract and deterministic preflight for Blu-ray Encode."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from src.core import find_mkvtoolnix
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import get_vspipe_context, resolve_encoder_executable_path
from src.runtime.audio_conversion import validate_audio_conversion_tools
from src.runtime.sp import SpEntry


@dataclass(frozen=True)
class EncodeSettings:
    """Encode controls captured from the visible GUI at task launch."""

    vspipe_mode: str
    encoder_mode: str
    encoder_parameters: str
    subtitle_mode: str
    encoder: str
    bit_depth: str
    use_getnative: bool
    default_lossless_audio_codec: str


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
    episode_trim_copyright_tail: bool = False
    mux_dolby_vision: bool = True
    track_selection_config: dict[str, dict[str, list[str]]] | None = None
    track_language_config: dict[str, dict[str, str]] | None = None


def validate_encode_request(request: EncodeRequest, check_tools: bool = False) -> None:
    """Reject deterministic request errors before Encode creates an output."""
    if request.input_mode not in ('bdmv', 'remux'):
        raise ValueError(
            translate_text('Unsupported encode input mode: {mode}').format(mode=request.input_mode)
        )
    valid_settings = (
        ('vspipe_mode', request.settings.vspipe_mode, ('bundle', 'system')),
        ('encoder_mode', request.settings.encoder_mode, ('bundle', 'system')),
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
    for row_number, (row, is_sp_row) in enumerate(selected_rows, 1):
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
        if subtitle_path and not os.path.isfile(subtitle_path):
            raise FileNotFoundError(
                translate_text('Subtitle file does not exist: {path}').format(path=subtitle_path)
            )
        if not is_sp_row or (
                str(row.output_path).lower().endswith('.mkv')
                and not row.uses_main_output
        ):
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
        if request.input_mode != 'remux' and os.path.exists(output_path):
            raise FileExistsError(
                translate_text('Output file already exists: {path}').format(path=output_path)
            )

    if not check_tools:
        return
    if request.settings.vspipe_mode == 'bundle':
        vspipe_path, _environment = get_vspipe_context()
    else:
        vspipe_path = core_settings.VSPIPE_PATH
    if not (os.path.isfile(vspipe_path) or shutil.which(vspipe_path)):
        raise FileNotFoundError(
            translate_text('vspipe executable does not exist: {path}').format(path=vspipe_path)
        )
    encoder_path = resolve_encoder_executable_path(
        request.settings.encoder,
        request.settings.encoder_mode,
    )
    if not (os.path.isfile(encoder_path) or shutil.which(encoder_path)):
        raise FileNotFoundError(
            translate_text('Encoder executable does not exist: {path}').format(path=encoder_path)
        )
    find_mkvtoolnix()
    mkvmerge_path = core_settings.MKV_MERGE_PATH or shutil.which('mkvmerge')
    if not mkvmerge_path or not (os.path.isfile(mkvmerge_path) or shutil.which(mkvmerge_path)):
        raise FileNotFoundError(translate_text('mkvmerge not found'))
    if request.input_mode == 'remux':
        for row, _is_sp_row in selected_rows:
            source_extension = os.path.splitext(row.source_path)[1].lower()
            if os.path.exists(row.output_path) or source_extension not in ('.mkv', '.mka'):
                continue
            validate_audio_conversion_tools(
                row.source_path,
                row.audio_tracks,
                row.audio_codec_choices,
            )
    if any((languages or {}) for languages in (request.track_language_config or {}).values()):
        mkvpropedit_path = core_settings.MKV_PROP_EDIT_PATH or shutil.which('mkvpropedit')
        if not mkvpropedit_path or not (
                os.path.isfile(mkvpropedit_path) or shutil.which(mkvpropedit_path)
        ):
            raise FileNotFoundError(translate_text('mkvpropedit not found'))


__all__ = ['EncodeRequest', 'EncodeRow', 'EncodeSettings', 'validate_encode_request']
