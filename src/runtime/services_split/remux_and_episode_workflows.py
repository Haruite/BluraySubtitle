"""Auto-generated split target: remux_and_episode_workflows."""
import copy
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import replace
from typing import Optional

from src.bdmv import Chapter
from src.core import find_mkvtoolnix, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.domain import MKV
from src.exports.utils import (
    get_index_to_m2ts_and_offset,
    get_time_str,
    force_remove_file,
    print_terminal_line,
    run_command,
)
from src.runtime.audio_conversion import (
    audio_gap_sidecar_path,
    mux_with_audio_conversion,
    validate_audio_cleanup_tools,
    validate_audio_conversion_tools,
)
from src.runtime.sp import SpEntry, SpJob, media_track_key
from src.runtime.remux import RemuxMainJob, RemuxRequest
from src.runtime.encode import EncodeRequest, EncodeRow
from src.runtime.encode_results import (
    EncodeBatchResult,
    EncodeRowResult,
    EncodeTaskFailure,
    write_encode_row_error_report,
)
from .service_base import BluraySubtitleServiceBase
from .. import TaskCancelled


def _svc_cls():
    from ..services.bluray_subtitle_entry import BluraySubtitle
    return BluraySubtitle


def _copy_path_atomically(
        source_path: str, destination_path: str, *, preserve_failure_artifacts: bool = False,
) -> None:
    destination_folder = os.path.dirname(destination_path)
    os.makedirs(destination_folder, exist_ok=True)
    partial_prefix = f'.{os.path.basename(destination_path)}.partial-'
    source_is_directory = os.path.isdir(source_path)
    if source_is_directory:
        temporary_path = tempfile.mkdtemp(
            prefix=partial_prefix,
            dir=destination_folder,
        )
    else:
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=partial_prefix,
            dir=destination_folder,
        )
        os.close(file_descriptor)
    keep_partial = False
    try:
        if source_is_directory:
            shutil.copytree(source_path, temporary_path, dirs_exist_ok=True)
        else:
            shutil.copy2(source_path, temporary_path)
        if os.path.exists(destination_path):
            raise FileExistsError(
                translate_text('Output file already exists: {path}').format(
                    path=destination_path
                )
            )
        os.replace(temporary_path, destination_path)
    except FileExistsError:
        raise
    except OSError as error:
        if preserve_failure_artifacts:
            keep_partial = (
                any(files for _root, _directories, files in os.walk(temporary_path))
                if source_is_directory else os.path.getsize(temporary_path) > 0
            )
            if keep_partial:
                raise EncodeTaskFailure(
                    'Copying source', str(error), (temporary_path,),
                ) from error
        raise
    finally:
        if not keep_partial:
            if os.path.isdir(temporary_path):
                shutil.rmtree(temporary_path, ignore_errors=True)
            elif os.path.isfile(temporary_path):
                force_remove_file(temporary_path)


class RemuxEpisodeWorkflowsMixin(BluraySubtitleServiceBase):

    def _prepare_remux_main_jobs(self, request: RemuxRequest) -> tuple[str, list[RemuxMainJob]]:
        """Resolve every selected main playlist and all output paths before the first write."""
        if request.ensure_tools:
            find_mkvtoolnix()
        self.track_selection_config = copy.deepcopy(
            request.track_selection_config or {}
        )
        alternate_mpls_by_main = {
            os.path.normcase(os.path.abspath(main_path)): tuple(paths or ())
            for main_path, paths in (request.main_alternate_mpls or {}).items()
            if str(main_path).strip()
        }
        self.main_alternate_mpls = dict(alternate_mpls_by_main)
        output_parent = os.path.dirname(os.path.normpath(request.output_folder))
        if os.path.exists(request.output_folder) and not os.path.isdir(request.output_folder):
            raise NotADirectoryError(translate_text('Output folder does not exist'))
        if not os.path.exists(request.output_folder) and not os.path.isdir(output_parent):
            raise FileNotFoundError(translate_text('Output folder does not exist'))
        if not request.configuration:
            raise ValueError(translate_text('Task configuration is empty'))
        if not request.selected_mpls:
            raise ValueError(translate_text('Main MPLS is not selected'))

        configuration = {
            int(key): dict(value)
            for key, value in request.configuration.items()
            if isinstance(value, dict)
        }
        if len(configuration) != len(request.configuration):
            raise ValueError(translate_text('Task configuration contains an invalid row'))
        ordered_keys = sorted(configuration)
        if len(request.episode_output_names) != len(ordered_keys):
            raise ValueError(translate_text(
                'The number of episode output names ({name_count}) must match the task row count ({row_count})'
            ).format(name_count=len(request.episode_output_names), row_count=len(ordered_keys)))
        if len(request.episode_subtitle_languages) != len(ordered_keys):
            raise ValueError(translate_text(
                'The number of subtitle languages ({language_count}) must match the task row count ({row_count})'
            ).format(language_count=len(request.episode_subtitle_languages), row_count=len(ordered_keys)))
        if len(request.subtitle_files) != len(ordered_keys):
            raise ValueError(translate_text(
                'Could not map all selected subtitle files to the selected main playlists'
            ))
        missing_subtitle = next(
            (
                str(subtitle_path).strip()
                for subtitle_path in request.subtitle_files
                if str(subtitle_path).strip() and not os.path.isfile(str(subtitle_path).strip())
            ),
            '',
        )
        if missing_subtitle:
            raise FileNotFoundError(
                translate_text('Subtitle file does not exist: {path}').format(path=missing_subtitle)
            )

        self.configuration = configuration
        row_position = {key: position for position, key in enumerate(ordered_keys)}
        dst_folder = os.path.join(
            os.path.normpath(request.output_folder),
            os.path.basename(os.path.normpath(request.bdmv_path).rstrip(os.sep)),
        )
        disc_count = len({int(configuration[key].get('bdmv_index') or 0) for key in ordered_keys})
        unmatched_keys = set(ordered_keys)
        selected_paths: set[str] = set()
        jobs: list[RemuxMainJob] = []

        for folder, selected_mpls in request.selected_mpls:
            selected_conf = {'folder': folder, 'selected_mpls': selected_mpls}
            selected_path = _svc_cls()._resolve_mpls_path_from_conf(selected_conf, request.bdmv_path)
            selected_norm = os.path.normcase(os.path.abspath(selected_path))
            if selected_norm in selected_paths:
                raise ValueError(
                    translate_text('Selected main playlist is duplicated: {path}').format(path=selected_path)
                )
            selected_paths.add(selected_norm)
            if not os.path.isfile(selected_path):
                raise FileNotFoundError(
                    translate_text('Selected main playlist does not exist: {path}').format(path=selected_path)
                )

            matching_keys = [
                key for key in ordered_keys
                if os.path.normcase(os.path.abspath(
                    _svc_cls()._resolve_mpls_path_from_conf(configuration[key], request.bdmv_path)
                )) == selected_norm
            ]
            if not matching_keys:
                raise ValueError(
                    translate_text('Selected main playlist has no task rows: {path}').format(path=selected_path)
                )
            matching_keys.sort(
                key=lambda key: int(
                    configuration[key].get('chapter_index')
                    or configuration[key].get('start_at_chapter')
                    or 1
                )
            )
            unmatched_keys.difference_update(matching_keys)
            configurations = [configuration[key] for key in matching_keys]
            bdmv_indexes = {int(conf.get('bdmv_index') or 0) for conf in configurations}
            if len(bdmv_indexes) != 1 or next(iter(bdmv_indexes)) <= 0:
                raise ValueError(
                    translate_text('Main playlist task rows have inconsistent disc indexes: {path}').format(
                        path=selected_path
                    )
                )
            for key in matching_keys:
                conf = configuration[key]
                try:
                    start_chapter = int(conf.get('start_at_chapter') or conf.get('chapter_index') or 0)
                    end_chapter = int(conf.get('end_at_chapter') or 0)
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        translate_text('Invalid task configuration in row {row}').format(
                            row=row_position[key] + 1
                        )
                    ) from error
                if end_chapter > 0 and start_chapter >= end_chapter:
                    raise ValueError(
                        translate_text('End chapter must be greater than start chapter in row {row}').format(
                            row=row_position[key] + 1
                        )
                    )

            explicit_commands = {
                str(conf.get('main_remux_cmd') or '').strip()
                for conf in configurations
                if str(conf.get('main_remux_cmd') or '').strip()
            }
            if len(explicit_commands) > 1:
                raise ValueError(
                    translate_text('Main playlist task rows have conflicting remux commands: {path}').format(
                        path=selected_path
                    )
                )

            built = self._make_main_mpls_remux_cmd(
                configurations,
                dst_folder,
                next(iter(bdmv_indexes)),
                max(disc_count, 1),
                ensure_disc_out_dir=False,
            )
            command, m2ts_file, volume, default_output, mpls_path, audio_tracks, subtitle_tracks = built
            command_lines = _svc_cls()._remux_cmd_shell_lines(command)
            if len(command_lines) != 1:
                raise ValueError(
                    translate_text('Each selected main playlist must have exactly one remux command: {path}').format(
                        path=mpls_path
                    )
                )
            expected_outputs = _svc_cls().theoretical_remux_output_paths_ordered(
                command, configurations, mpls_path
            )
            if not expected_outputs:
                raise ValueError(
                    translate_text('Could not derive remux outputs from the command for: {path}').format(
                        path=mpls_path
                    )
                )
            if len(expected_outputs) != len(configurations):
                raise ValueError(translate_text(
                    'The remux output count ({output_count}) must match the task row count ({row_count}) for: {path}'
                ).format(
                    output_count=len(expected_outputs),
                    row_count=len(configurations),
                    path=mpls_path,
                ))

            final_outputs: list[str] = []
            for key, expected_output in zip(matching_keys, expected_outputs):
                output_name = str(request.episode_output_names[row_position[key]] or '')
                if not output_name.strip():
                    raise ValueError(
                        translate_text('Episode output name is empty in row {row}').format(
                            row=row_position[key] + 1
                        )
                    )
                reserved_names = {'CON', 'PRN', 'AUX', 'NUL'} | {
                    f'{prefix}{number}'
                    for prefix in ('COM', 'LPT')
                    for number in range(1, 10)
                }
                if (
                        output_name.rstrip(' .') != output_name
                        or output_name != os.path.basename(output_name)
                        or any(character in output_name for character in '<>:"/\\|?*')
                        or any(ord(character) < 32 for character in output_name)
                        or os.path.splitext(output_name)[0].upper() in reserved_names
                ):
                    raise ValueError(
                        translate_text('Invalid episode output name in row {row}: {name}').format(
                            row=row_position[key] + 1,
                            name=output_name,
                        )
                    )
                if not output_name.lower().endswith('.mkv'):
                    output_name += '.mkv'
                final_outputs.append(os.path.join(os.path.dirname(expected_output), output_name))

            command_output = next(
                (path for line in _svc_cls()._remux_cmd_shell_lines(command)
                 if (path := _svc_cls()._mkvmerge_output_path_from_line(line))),
                None,
            ) or _svc_cls()._mkvmerge_output_path_from_line(command)
            main_track_configuration = dict(
                self.track_selection_config.get(media_track_key('main', mpls_path)) or {}
            )
            main_track_configuration.setdefault('audio', list(audio_tracks))
            main_track_configuration.setdefault('subtitle', list(subtitle_tracks))
            alternate_mpls_paths = tuple(
                os.path.normpath(path)
                for path in alternate_mpls_by_main.get(selected_norm, ())
                if str(path).strip()
            )
            selected_pid_slots = _svc_cls()._selected_pid_slots_for_mpls(
                mpls_path,
                main_track_configuration,
                alternate_mpls_paths=alternate_mpls_paths,
            )
            selected_pid_tuples = [
                (str(slot['type']), int(slot['pid'])) for slot in selected_pid_slots
            ]
            selected_source_slots = tuple(
                (
                    os.path.normpath(str(slot.get('_mpls_source_path') or mpls_path)),
                    str(slot.get('_mpls_bucket') or slot.get('type') or ''),
                    int(slot.get('_mpls_slot_index') or 0),
                )
                for slot in selected_pid_slots
            )
            language_overrides = _svc_cls()._mpls_default_language_map(
                mpls_path,
                selected_pid_tuples,
                (request.track_language_config or {}).get(
                    media_track_key('main', mpls_path), {}
                ) or {},
                alternate_mpls_paths=alternate_mpls_paths,
                selected_source_slots=selected_source_slots,
            )
            jobs.append(RemuxMainJob(
                configuration_keys=tuple(matching_keys),
                configurations=tuple(configurations),
                bdmv_index=next(iter(bdmv_indexes)),
                command=command_lines[0],
                m2ts_file=m2ts_file,
                volume=volume,
                primary_output=os.path.normpath(command_output or default_output),

                mpls_path=mpls_path,
                audio_tracks=tuple(audio_tracks),
                subtitle_tracks=tuple(subtitle_tracks),
                expected_outputs=tuple(os.path.normpath(path) for path in expected_outputs),
                final_outputs=tuple(os.path.normpath(path) for path in final_outputs),
                m2ts_file_details=tuple(
                    str(conf.get('m2ts_file_detail') or '').strip()
                    for conf in configurations
                ),
                track_language_overrides=tuple(
                    (str(track_index), str(language).strip())
                    for track_index, language in language_overrides.items()
                    if str(language).strip()
                ),
                track_pids=tuple(selected_pid_tuples),
                alternate_mpls_paths=alternate_mpls_paths,
                track_source_slots=selected_source_slots,
            ))

        if unmatched_keys:
            first_key = min(unmatched_keys)
            unmatched_path = _svc_cls()._resolve_mpls_path_from_conf(
                configuration[first_key], request.bdmv_path
            )
            raise ValueError(
                translate_text('Task row references an unselected main playlist: {path}').format(
                    path=unmatched_path
                )
            )

        path_owners: dict[str, tuple[int, int]] = {}
        for job_index, job in enumerate(jobs):
            for output_index, (expected_output, final_output) in enumerate(
                    zip(job.expected_outputs, job.final_outputs)):
                owner = (job_index, output_index)
                for output_path in (expected_output, final_output):
                    normalized_path = os.path.normcase(os.path.abspath(output_path))
                    previous_owner = path_owners.get(normalized_path)
                    if previous_owner is not None and previous_owner != owner:
                        raise ValueError(
                            translate_text('Duplicate output path: {path}').format(path=output_path)
                        )
                    path_owners[normalized_path] = owner
                    if os.path.exists(output_path):
                        raise FileExistsError(
                            translate_text('Output file already exists: {path}').format(path=output_path)
                        )
        if any(job.track_language_overrides for job in jobs):
            find_mkvtoolnix()
            mkvpropedit_path = core_settings.MKV_PROP_EDIT_PATH or shutil.which('mkvpropedit')
            if not mkvpropedit_path or not os.path.isfile(mkvpropedit_path):
                raise FileNotFoundError(translate_text('mkvpropedit not found'))
        return dst_folder, jobs

    def _prepare_sp_jobs(
            self,
            entries: tuple[SpEntry, ...],
            destination_folder: str,
            main_jobs: list[RemuxMainJob],
            track_selection_config: dict[str, dict[str, list[str]]] | None,
            track_language_config: dict[str, dict[str, str]],
    ) -> list[SpJob]:
        """Resolve selected SP rows and all exact outputs before the first write."""
        destination_root = os.path.abspath(os.path.normpath(destination_folder))
        episode_targets_by_detail: dict[
            tuple[int, str], list[tuple[str, str]]
        ] = {}
        occupied_outputs: dict[str, str] = {}
        first_main_mpls_by_disc: dict[int, str] = {}
        for main_job in main_jobs:
            first_main_mpls_by_disc.setdefault(main_job.bdmv_index, main_job.mpls_path)
            for output_path in main_job.expected_outputs:
                occupied_outputs[os.path.normcase(os.path.abspath(output_path))] = 'main'
            for output_path in main_job.final_outputs:
                normalized_output = os.path.normcase(os.path.abspath(output_path))
                occupied_outputs[normalized_output] = 'main'
            for detail, output_path in zip(
                    main_job.m2ts_file_details, main_job.final_outputs):
                detail = str(detail or '').strip()
                if detail:
                    episode_targets_by_detail.setdefault(
                        (main_job.bdmv_index, detail), []
                    ).append((
                        os.path.abspath(output_path),
                        main_job.mpls_path,
                    ))

        planned_jobs: list[SpJob] = []
        for entry_index, entry in enumerate(entries, start=1):
            if not entry.selected or not entry.output_name:
                continue
            if entry.bdmv_index <= 0:
                raise ValueError(
                    translate_text('SP row {row} has an invalid Blu-ray disc index').format(
                        row=entry_index
                    )
                )
            disc_root = os.path.abspath(os.path.normpath(entry.bdmv_root)) if entry.bdmv_root else ''
            playlist_folder = os.path.join(disc_root, 'BDMV', 'PLAYLIST') if disc_root else ''
            stream_folder = os.path.join(disc_root, 'BDMV', 'STREAM') if disc_root else ''
            if not os.path.isdir(playlist_folder) or not os.path.isdir(stream_folder):
                raise FileNotFoundError(
                    translate_text('SP row {row} has no matching Blu-ray directory').format(
                        row=entry_index
                    )
                )

            if entry.mpls_file:
                source_path = os.path.abspath(os.path.join(playlist_folder, entry.mpls_file))
                if not os.path.isfile(source_path):
                    raise FileNotFoundError(
                        translate_text('SP source does not exist in row {row}: {path}').format(
                            row=entry_index,
                            path=source_path,
                        )
                    )
                first_m2ts_path, _pid_languages = _svc_cls()._probe_m2ts_for_remux_source(
                    source_path
                )
                first_m2ts_path = os.path.abspath(first_m2ts_path) if first_m2ts_path else ''
            else:
                if not entry.m2ts_files:
                    raise ValueError(
                        translate_text('SP row {row} has no source file').format(row=entry_index)
                    )
                source_paths = [
                    os.path.abspath(os.path.join(stream_folder, filename))
                    for filename in entry.m2ts_files
                ]
                missing_source = next(
                    (path for path in source_paths if not os.path.isfile(path)),
                    '',
                )
                if missing_source:
                    raise FileNotFoundError(
                        translate_text('SP source does not exist in row {row}: {path}').format(
                            row=entry_index,
                            path=missing_source,
                        )
                    )
                source_path = source_paths[0]
                first_m2ts_path = source_path
            if not first_m2ts_path or not os.path.isfile(first_m2ts_path):
                raise FileNotFoundError(
                    translate_text('SP source does not exist in row {row}: {path}').format(
                        row=entry_index,
                        path=first_m2ts_path or source_path,
                    )
                )

            output_path = os.path.abspath(os.path.normpath(os.path.join(
                destination_root,
                entry.output_name.replace('/', os.sep),
            )))
            try:
                output_in_destination = os.path.commonpath(
                    (destination_root, output_path)
                ) == destination_root
            except ValueError:
                output_in_destination = False
            if not output_in_destination or output_path == destination_root:
                raise ValueError(
                    translate_text('SP output is outside the selected output folder: {path}').format(
                        path=output_path
                    )
                )

            is_image_output = (
                output_path.lower().endswith('.png')
                or not os.path.splitext(os.path.basename(output_path))[1]
            )
            if is_image_output:
                selected_tracks: dict[str, list[str]] = {
                    'video': [], 'audio': [], 'subtitle': [],
                }
            elif track_selection_config is None:
                if entry.mpls_file:
                    mpls_streams = _svc_cls()._mpls_track_streams(source_path)
                    pid_to_lang = {
                        int(stream['pid']): str(stream.get('language') or 'und')
                        for stream in mpls_streams
                        if stream.get('pid') is not None
                    }
                    selected_audio, selected_subtitles = (
                        _svc_cls()._default_track_selection_from_streams(
                            mpls_streams,
                            pid_to_lang,
                        )
                    )
                else:
                    selected_audio, selected_subtitles = self._select_tracks_for_source(
                        source_path,
                        config_key=None,
                    )
                selected_tracks = {
                    'audio': selected_audio,
                    'subtitle': selected_subtitles,
                }
            elif entry.track_key not in track_selection_config:
                raise ValueError(
                    translate_text('SP row {row} has no captured track selection').format(
                        row=entry_index
                    )
                )
            else:
                selected_tracks = track_selection_config.get(entry.track_key) or {}

            selected_pid_slots: list[dict[str, object]] = []
            if entry.mpls_file and not is_image_output:
                selected_pid_slots = _svc_cls()._selected_pid_slots_for_mpls(
                    source_path, selected_tracks
                )
                selected_tracks = {
                    'audio': [
                        str(int(slot['pid'])) for slot in selected_pid_slots
                        if str(slot.get('type') or '') == 'audio'
                    ],
                    'subtitle': [
                        str(int(slot['pid'])) for slot in selected_pid_slots
                        if str(slot.get('type') or '') in ('subtitle', 'subtitles')
                    ],
                }

            normalized_output = os.path.normcase(output_path)
            episode_main_mpls_path = ''
            matching_episode_targets = (
                episode_targets_by_detail.get(
                    (entry.bdmv_index, entry.m2ts_file_detail.strip()), []
                )
                if not bool(getattr(self, 'movie_mode', False))
                and entry.m2ts_file_detail.strip()
                else []
            )
            episode_linked = len(matching_episode_targets) == 1
            if episode_linked:
                target_output, episode_main_mpls_path = matching_episode_targets[0]
                visible_output_name = os.path.normcase(os.path.normpath(
                    entry.output_name.replace('/', os.sep)
                ))
                target_output_name = os.path.normcase(os.path.basename(target_output))
                if visible_output_name != target_output_name:
                    raise ValueError(
                        translate_text('SP row {row} does not match a planned episode output: {path}').format(
                            row=entry_index,
                            path=output_path,
                        )
                    )
                # A user-edited main remux command owns the actual staging directory.
                # The linked SP row names the episode, so append to that command-derived
                # output instead of the default stage.
                output_path = os.path.abspath(os.path.normpath(target_output))
                normalized_output = os.path.normcase(output_path)
            else:
                if normalized_output in occupied_outputs:
                    raise ValueError(
                        translate_text('Duplicate output path: {path}').format(path=output_path)
                    )
                if os.path.exists(output_path):
                    raise FileExistsError(
                        translate_text('Output file already exists: {path}').format(path=output_path)
                    )
                occupied_outputs[normalized_output] = 'sp'

            language_overrides = track_language_config.get(entry.track_key) or {}
            if entry.mpls_file and not is_image_output:
                selected_source_slots = tuple(
                    (
                        os.path.normpath(str(slot.get('_mpls_source_path') or source_path)),
                        str(slot.get('_mpls_bucket') or slot.get('type') or ''),
                        int(slot.get('_mpls_slot_index') or 0),
                    )
                    for slot in selected_pid_slots
                )
                language_overrides = _svc_cls()._mpls_default_language_map(
                    source_path,
                    [
                        (str(slot['type']), int(slot['pid']))
                        for slot in selected_pid_slots
                    ],
                    language_overrides,
                    selected_source_slots=selected_source_slots,
                )
            else:
                selected_source_slots = ()
            output_extension = os.path.splitext(output_path)[1].lower()
            if language_overrides and output_extension not in ('.mkv', '.mka', '.mks'):
                raise ValueError(
                    translate_text(
                        'Track languages cannot be applied to SP output in row {row}: {path}'
                    ).format(
                        row=entry_index,
                        path=output_path,
                    )
                )

            planned_jobs.append(SpJob(
                entry_index=entry_index,
                entry=entry,
                source_path=source_path,
                first_m2ts_path=first_m2ts_path,
                output_path=output_path,
                main_mpls_path=first_main_mpls_by_disc.get(entry.bdmv_index, ''),
                episode_main_mpls_path=episode_main_mpls_path,
                audio_tracks=tuple(selected_tracks.get('audio') or ()),
                subtitle_tracks=tuple(selected_tracks.get('subtitle') or ()),
                track_language_overrides=tuple(
                    (str(track_index), str(language).strip())
                    for track_index, language in language_overrides.items()
                    if str(language).strip()
                ),
                track_pids=tuple(
                    (str(slot['type']), int(slot['pid']))
                    for slot in selected_pid_slots
                ),
                track_source_slots=selected_source_slots,
            ))

        if any(job.track_language_overrides for job in planned_jobs):
            find_mkvtoolnix()
            mkvpropedit_path = core_settings.MKV_PROP_EDIT_PATH or shutil.which('mkvpropedit')
            if not mkvpropedit_path or not os.path.isfile(mkvpropedit_path):
                raise FileNotFoundError(translate_text('mkvpropedit not found'))
        return planned_jobs

    def _build_main_episode_mkvs(
            self,
            jobs: list[RemuxMainJob],
            cancel_event: Optional[threading.Event] = None,
            *,
            mux_progress_base: int = 0,
            mux_progress_span: int = 380,
    ) -> list[str]:
        """Execute each planned main-playlist command and require every planned output."""
        self._remux_chapter_skip_paths = set()
        self._remux_fallback_track_slots = {}
        self._remux_fallback_track_source_slots = {}
        self._remux_fallback_track_signatures = {}
        self._remux_fallback_audio_timelines = {}
        self._remux_fallback_audio_timeline_durations = {}
        completed_outputs: list[str] = []
        for job_index, job in enumerate(jobs, start=1):
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            job_progress_base = mux_progress_base + int(
                (job_index - 1) / max(len(jobs), 1) * mux_progress_span
            )
            job_progress_end = mux_progress_base + int(
                job_index / max(len(jobs), 1) * mux_progress_span
            )
            configurations = [dict(conf) for conf in job.configurations]
            if job.mpls_path:
                config_key = media_track_key('main', job.mpls_path)
                tracks_cfg = getattr(self, 'track_selection_config', {}) or {}
                if config_key in tracks_cfg:
                    cfg = tracks_cfg.get(config_key) or {}
                    audio_count = len(cfg.get('audio') or [])
                    subtitle_count = len(cfg.get('subtitle') or [])
                    msg = (
                        f'{self.t("Using tracks selected in Edit Tracks for main MPLS")} '
                        f'[{os.path.basename(job.mpls_path)}]: '
                        f'{audio_count} audio, {subtitle_count} subtitle'
                    )
                else:
                    msg = (
                        f'{self.t("Using default track selection for main MPLS")} '
                        f'[{os.path.basename(job.mpls_path)}]'
                    )
                print(msg)
                self._progress(text=msg)

            main_pid_slots = list(job.track_pids)
            if job.mpls_path and main_pid_slots:
                main_pid_slots = self._validate_mpls_tracks_for_execution(
                    job.mpls_path,
                    main_pid_slots,
                    alternate_mpls_paths=job.alternate_mpls_paths,
                    selected_source_slots=job.track_source_slots,
                )
            mpls_identification: Optional[dict[str, object]] = None
            if not main_pid_slots:
                _svc_cls()._log_mkvmerge_identify_slot_gap(
                    job.mpls_path,
                    '',
                    [],
                    None,
                    'main MPLS job has no captured PID selection',
                )
                identify_ok = False
            else:
                mpls_identification = _svc_cls()._mkvmerge_identify_json(job.mpls_path)
                self._set_dovi_mux_plan_for_mpls(
                    job.mpls_path, report_detected_pair=True
                )
                identify_ok = self._mkvmerge_identify_covers_remux_slots(
                    job.mpls_path,
                    list(job.audio_tracks),
                    list(job.subtitle_tracks),
                    selected_pid_slots=main_pid_slots,
                    identification=mpls_identification,
                    alternate_mpls_paths=job.alternate_mpls_paths,
                    selected_source_slots=job.track_source_slots,
                )
            if not identify_ok:
                print('[remux-fallback] skipping primary mkvmerge (see identify check lines above)')
            resolved_command = job.command
            if identify_ok and main_pid_slots and mpls_identification is not None:
                resolved_command = _svc_cls()._resolve_main_remux_track_placeholders(
                    job.command,
                    main_pid_slots,
                    mpls_identification,
                    getattr(self, '_dovi_mux_plan', None),
                )
            print(f'{self.t("Mux command: ")}{resolved_command}')
            job_progress_name = (
                f'BD_Vol_{job.volume} [{os.path.basename(job.mpls_path)}]'
            )
            self._progress(text=f'{self.t("Muxing: ")}{job_progress_name}')
            if identify_ok:
                try:
                    return_code, _line_return_codes = self._run_shell_command_detailed(resolved_command)
                except TaskCancelled:
                    for output_path in job.expected_outputs:
                        if os.path.isfile(output_path):
                            force_remove_file(output_path)
                    raise
            else:
                return_code = -1

            primary_ok = return_code in (0, 1) and all(
                os.path.isfile(path) for path in job.expected_outputs
            )
            if return_code in (0, 1) and not primary_ok:
                for _attempt in range(5):
                    time.sleep(0.2)
                    if all(os.path.isfile(path) for path in job.expected_outputs):
                        primary_ok = True
                        break

            cover = ''
            try:
                bdmv_dir = os.path.normpath(os.path.join(os.path.dirname(job.mpls_path), '..'))
                meta_folder = os.path.join(bdmv_dir, 'META', 'DL')
                cover_size = 0
                if os.path.exists(meta_folder):
                    for filename in os.listdir(meta_folder):
                        if filename.endswith(('.jpg', '.JPG', '.JPEG', '.jpeg', '.png', '.PNG')):
                            fp = os.path.join(meta_folder, filename)
                            sz = os.path.getsize(fp)
                            if sz > cover_size:
                                cover = fp
                                cover_size = sz
            except Exception:
                cover = ''

            split_output = len(job.expected_outputs) > 1
            if not primary_ok:
                for output_path in job.expected_outputs:
                    if os.path.isfile(output_path):
                        force_remove_file(output_path)
                fallback_ok = False
                if split_output and main_pid_slots:
                    self._progress(text=self.t(
                        'Multi-output track-aligned fallback: {name}'
                    ).format(name=job_progress_name))
                    fallback_kwargs = {
                        'cancel_event': cancel_event,
                        'progress_base': job_progress_base,
                        'progress_span': job_progress_end - job_progress_base,
                        'alternate_mpls_paths': job.alternate_mpls_paths,
                        'selected_source_slots': job.track_source_slots,
                    }
                    fallback_kwargs['selected_pid_slots'] = main_pid_slots
                    fallback_ok = self._try_remux_mpls_split_outputs_track_aligned(
                        job.mpls_path,
                        job.primary_output,
                        configurations,
                        cover,
                        **fallback_kwargs,
                    )
                elif main_pid_slots:
                    self._progress(text=self.t(
                        'Track-aligned fallback: {name}'
                    ).format(name=job_progress_name))
                    fallback_kwargs = {
                        'cancel_event': cancel_event,
                        'selected_pid_slots': main_pid_slots,
                        'alternate_mpls_paths': job.alternate_mpls_paths,
                        'selected_source_slots': job.track_source_slots,
                    }
                    fallback_ok = self._try_remux_mpls_track_aligned(
                        job.mpls_path,
                        job.primary_output,
                        cover,
                        **fallback_kwargs,
                    )
                primary_ok = fallback_ok and all(
                    os.path.isfile(path) for path in job.expected_outputs
                )
            if not primary_ok:
                missing_outputs = [path for path in job.expected_outputs if not os.path.isfile(path)]
                for output_path in job.expected_outputs:
                    if os.path.isfile(output_path):
                        force_remove_file(output_path)
                raise RuntimeError(
                    translate_text('Main remux failed for {path}; missing outputs: {outputs}').format(
                        path=job.mpls_path,
                        outputs=', '.join(missing_outputs) or ', '.join(job.expected_outputs),
                    )
                )

            if job.track_language_overrides:
                try:
                    for output_path in job.expected_outputs:
                        output_pid_slots = list(
                            self._remux_fallback_track_slots.get(
                                os.path.normcase(os.path.abspath(output_path)),
                                main_pid_slots,
                            )
                        )
                        output_source_slots = tuple(
                            self._remux_fallback_track_source_slots.get(
                                os.path.normcase(os.path.abspath(output_path)),
                                job.track_source_slots,
                            )
                        )
                        self._progress(
                            text=f'{self.t("Correcting track languages: ")}'
                                 f'{os.path.basename(output_path)}'
                        )
                        language_args = [
                            output_path,
                            job.mpls_path if main_pid_slots else job.m2ts_file,
                            list(job.audio_tracks),
                            list(job.subtitle_tracks),
                            dict(job.track_language_overrides),
                            getattr(self, '_dovi_mux_plan', None),
                        ]
                        if main_pid_slots:
                            _svc_cls()._fix_output_track_languages_with_mkvpropedit(
                                *language_args,
                                selected_pid_slots=output_pid_slots,
                                selected_source_slots=output_source_slots,
                            )
                        else:
                            _svc_cls()._fix_output_track_languages_with_mkvpropedit(*language_args)
                except Exception:
                    for output_path in job.expected_outputs:
                        if os.path.isfile(output_path):
                            force_remove_file(output_path)
                    raise

            warning_list = getattr(self, 'remux_warnings', None)
            if not isinstance(warning_list, list):
                warning_list = getattr(self, 'encode_warnings', None)
            if not isinstance(warning_list, list):
                warning_list = []
                self.remux_warnings = warning_list
            for output_path in job.expected_outputs:
                output_pid_slots = list(
                    self._remux_fallback_track_slots.get(
                        os.path.normcase(os.path.abspath(output_path)),
                        main_pid_slots,
                    )
                )
                try:
                    output_warnings = self._remux_output_track_warnings(
                        output_path,
                        getattr(self, '_dovi_mux_plan', None),
                        output_pid_slots,
                    )
                except TaskCancelled:
                    raise
                except Exception as error:
                    output_warnings = [translate_text(
                        'Remux output track validation failed: {path}. {error}'
                    ).format(path=output_path, error=error)]
                warning_list.extend(output_warnings)
                for warning in output_warnings:
                    print(f'{translate_text("[remux-verify] ")}{warning}')

            completed_outputs.extend(job.expected_outputs)
            self._progress(job_progress_end)
        return completed_outputs

    @staticmethod
    def _dedupe_remux_shell_lines(cmd: str) -> str:
        """Drop duplicate non-empty lines so the same mkvmerge invocation is not run twice."""
        lines = [ln.strip() for ln in (cmd or '').splitlines() if ln.strip()]
        if len(lines) <= 1:
            return (cmd or '').strip()
        seen: set[str] = set()
        uniq: list[str] = []
        for ln in lines:
            if ln in seen:
                continue
            seen.add(ln)
            uniq.append(ln)
        return '\n'.join(uniq)

    def _run_shell_command_detailed(self, cmd: str) -> tuple[int, list[int]]:
        """Run ``remux_cmd`` line-by-line; return (max exit code, per-line codes)."""
        commands = [line.strip() for line in cmd.splitlines() if line.strip()]
        if not commands:
            return 0, []
        if len(commands) <= 1:
            r = self._run_single_command(cmd)
            return r, [int(r)]
        rets = [int(self._run_single_command(c)) for c in commands]
        return (max(rets) if rets else 0), rets

    def _run_single_command(self, cmd: str) -> int:
        if sys.platform != 'win32':
            cmd = self._fix_remux_shell_rm_glob(cmd)
        return int(run_command(cmd).returncode)

    @staticmethod
    def _fix_remux_shell_rm_glob(raw: str) -> str:
        def _fix_quoted_token(m):
            token = m.group(1)
            if '*' not in token or '/' not in token:
                return m.group(0)
            i = token.rfind('/')
            if i < 0:
                return m.group(0)
            prefix = token[:i + 1]
            suffix = token[i + 1:]
            if '*' not in suffix:
                return m.group(0)
            return f'"{prefix}"{suffix}'

        out = re.sub(r'"([^"]*\*[^"]*)"', _fix_quoted_token, raw)
        out = re.sub(r'\s*&&\s*rm\b', r'; rm -f', out)
        return out

    def _make_main_mpls_remux_cmd(
            self,
            confs: list[dict[str, int | str]],
            dst_folder: str,
            bdmv_index: int,
            disc_count: int,
            *,
            ensure_disc_out_dir: bool = False,
    ) -> tuple[str, str, str, str, str, list[str], list[str]]:
        conf0 = confs[0]
        mpls_path = _svc_cls()._resolve_mpls_path_from_conf(
            conf0, str(getattr(self, 'bdmv_path', '') or ''))
        if not mpls_path or not os.path.isfile(mpls_path):
            raise FileNotFoundError(mpls_path or str(conf0.get('selected_mpls') or ''))
        try:
            disc_name = os.path.basename(os.path.normpath(str(getattr(self, 'bdmv_path', '') or '')).rstrip(os.sep))
        except Exception:
            disc_name = ''
        disc_name = disc_name or 'BDMV'
        disc_out_dir = ''
        if dst_folder:
            try:
                if os.path.basename(os.path.normpath(dst_folder).rstrip(os.sep)) == disc_name:
                    disc_out_dir = dst_folder
                else:
                    disc_out_dir = os.path.join(dst_folder, disc_name)
            except Exception:
                disc_out_dir = os.path.join(dst_folder, disc_name)
        if disc_out_dir and ensure_disc_out_dir:
            try:
                os.makedirs(disc_out_dir, exist_ok=True)
            except Exception:
                disc_out_dir = dst_folder

        chapter = Chapter(mpls_path)
        m2ts_file = ''
        if chapter.in_out_time:
            m2ts_file = os.path.normpath(os.path.join(
                os.path.dirname(mpls_path), '..', 'STREAM',
                f'{chapter.in_out_time[0][0]}.m2ts',
            ))
        config_key = media_track_key('main', mpls_path)
        tracks_cfg = getattr(self, 'track_selection_config', {}) or {}
        if isinstance(tracks_cfg, dict) and config_key in tracks_cfg:
            selected_track_pids = tracks_cfg.get(config_key) or {}
            copy_audio_track = list(selected_track_pids.get('audio') or [])
            copy_sub_track = list(selected_track_pids.get('subtitle') or [])
        else:
            mpls_streams = _svc_cls()._mpls_track_streams(mpls_path)
            pid_to_lang = {
                int(stream['pid']): str(stream.get('language') or 'und')
                for stream in mpls_streams
                if stream.get('pid') is not None
            }
            copy_audio_track, copy_sub_track = _svc_cls()._default_track_selection_from_streams(
                mpls_streams,
                pid_to_lang,
            )
        bdmv_dir = os.path.normpath(os.path.join(os.path.dirname(mpls_path), '..'))
        meta_folder = os.path.join(bdmv_dir, 'META', 'DL')
        cover = ''
        cover_size = 0
        if os.path.exists(meta_folder):
            for filename in os.listdir(meta_folder):
                if filename.endswith('.jpg') or filename.endswith('.JPG') or filename.endswith(
                        '.JPEG') or filename.endswith('.jpeg') or filename.endswith('.png') or filename.endswith(
                        '.PNG'):
                    if os.path.getsize(os.path.join(meta_folder, filename)) > cover_size:
                        cover = os.path.join(meta_folder, filename)
                        cover_size = os.path.getsize(os.path.join(meta_folder, filename))
        stem = os.path.splitext(os.path.basename(mpls_path))[0]
        try:
            output_name = str(conf0.get('disc_output_name') or '').strip()
        except Exception:
            output_name = ''
        resolved_title = self._resolve_disc_output_name(stem)
        bdmv_bn = ''
        try:
            bdmv_bn = os.path.basename(os.path.normpath(str(getattr(self, 'bdmv_path', '') or '')).rstrip(os.sep))
        except Exception:
            bdmv_bn = ''
        if not output_name or (bdmv_bn and output_name == bdmv_bn):
            output_name = resolved_title

        bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
        try:
            find_mkvtoolnix()
        except Exception:
            pass
        mkvmerge_exe = core_settings.MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'
        if getattr(self, 'movie_mode', False):
            try:
                output_name_from_conf = str(confs[0].get('output_name') or '').strip()
            except Exception:
                output_name_from_conf = ''
            if output_name_from_conf:
                base = output_name_from_conf
                if not base.lower().endswith('.mkv'):
                    base += '.mkv'
                output_file = base if os.path.isabs(base) else os.path.join(disc_out_dir or dst_folder, base)
            else:
                output_file = f'{os.path.join(disc_out_dir or dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
            if disc_count == 1:
                out_dir = os.path.dirname(output_file)
                out_base = os.path.basename(output_file)
                out_base = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', out_base)
                out_base = re.sub(rf'(?i)_BD_Vol_{bdmv_vol}(?=\.mkv$)', '', out_base)
                output_file = os.path.join(out_dir, out_base)
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            default_cmd = (
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} '
                f'--chapter-language eng -o "{output_file}" '
                f'{default_cover_opts} "{mpls_path}"').strip()
            # A main playlist owns one command; placeholders cover all output ranges for that playlist.
            custom_cmd = str(conf0.get('main_remux_cmd') or '').strip()
            remux_cmd = (
                custom_cmd.replace('{output_file}', output_file)
                .replace('{mpls_path}', mpls_path)
                .replace('{cover_opts}', default_cover_opts)
                .replace('{chapter_split}', '')
                .replace('{parts_split}', '')
                if custom_cmd
                else default_cmd
            )
        else:
            rows = sum(map(len, chapter.mark_info.values()))
            total_end = rows + 1
            _, index_to_offset = get_index_to_m2ts_and_offset(chapter)

            def _off(idx: int) -> float:
                if idx >= total_end:
                    return chapter.get_total_time()
                return float(index_to_offset.get(idx, 0.0))

            def _parts_chapter_for_sub_confs(sub_confs: list[dict[str, int | str]]) -> tuple[str, str, bool]:
                if not sub_confs:
                    return '', '', False
                segl = _svc_cls()._series_episode_segments_bounds(chapter, sub_confs)
                cstarts = [int(s) for s, _ in segl]
                cafter = [s for s in cstarts[1:] if 1 < s <= rows]
                csplit = ','.join(map(str, cafter))
                use_parts = not bool(sub_confs[0].get('chapter_segments_fully_checked', True))
                trim_end_by_start: dict[int, float] = {}
                for sub_conf in sub_confs:
                    raw_trim_end = str(sub_conf.get('copyright_trim_end_offset') or '').strip()
                    if not raw_trim_end:
                        continue
                    try:
                        trim_start = int(sub_conf.get('start_at_chapter') or sub_conf.get('chapter_index') or 1)
                        trim_end_by_start[trim_start] = float(raw_trim_end)
                    except (TypeError, ValueError):
                        continue
                pl: list[str] = []
                for s, e in segl:
                    start_offset = _off(s)
                    end_offset = _off(e)
                    trimmed_end = trim_end_by_start.get(int(s))
                    if trimmed_end is not None and start_offset < trimmed_end < end_offset:
                        end_offset = trimmed_end
                        use_parts = True
                    st = get_time_str(start_offset)
                    ed = get_time_str(end_offset)
                    if st == '0':
                        st = '00:00:00.000'
                    if ed == '0':
                        ed = '00:00:00.000'
                    pl.append(f'{st}-{ed}')
                return ','.join(pl), csplit, use_parts

            parts_split, chapter_split, use_split_parts = _parts_chapter_for_sub_confs(confs)
            output_file = f'{os.path.join(disc_out_dir or dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            if use_split_parts:
                split_arg = (f'--split parts:{parts_split}' if parts_split else '')
            else:
                split_arg = (f'--split chapters:{chapter_split}' if chapter_split else '')
            default_cmd = (
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} {split_arg} '
                f'-o "{output_file}" {default_cover_opts} '
                f'"{mpls_path}"').strip()
            # A main playlist owns one command; split placeholders describe every selected episode range.
            custom_cmd = str(conf0.get('main_remux_cmd') or '').strip()
            remux_cmd = (
                custom_cmd.replace('{output_file}', output_file)
                .replace('{mpls_path}', mpls_path)
                .replace('{cover_opts}', default_cover_opts)
                .replace('{chapter_split}', chapter_split)
                .replace('{parts_split}', parts_split)
                if custom_cmd
                else default_cmd
            )
        remux_cmd = _svc_cls()._main_remux_command_with_track_placeholders(
            self._dedupe_remux_shell_lines(remux_cmd),
            mpls_path,
        )
        return remux_cmd, m2ts_file, bdmv_vol, output_file, mpls_path, copy_audio_track, copy_sub_track

    def _post_remux_finalize_episodes(
            self,
            jobs: list[RemuxMainJob],
            cancel_event: Optional[threading.Event],
    ) -> list[str]:
        """Write per-row chapters and apply the exact planned GUI output names."""
        final_by_configuration_key: dict[int, str] = {}
        with tempfile.TemporaryDirectory(prefix='bluray-subtitle-remux-chapters-') as temporary_directory:
            chapter_index = 0
            for job in jobs:
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                configurations = [dict(conf) for conf in job.configurations]
                bounds = _svc_cls()._remux_parsed_chapter_bounds_for_theory_count(
                    job.command,
                    configurations,
                    job.mpls_path,
                    len(job.expected_outputs),
                )
                if bounds is None:
                    bounds = _svc_cls()._series_episode_segments_bounds(
                        Chapter(job.mpls_path), configurations
                    )
                if len(bounds) != len(job.expected_outputs):
                    raise ValueError(
                        translate_text('Could not map chapter ranges to remux outputs for: {path}').format(
                            path=job.mpls_path
                        )
                    )

                for configuration_key, expected_output, final_output, (start_chapter, end_chapter) in zip(
                        job.configuration_keys,
                        job.expected_outputs,
                        job.final_outputs,
                        bounds,
                ):
                    if cancel_event and cancel_event.is_set():
                        raise TaskCancelled()
                    if not os.path.isfile(expected_output):
                        raise RuntimeError(
                            translate_text('Main remux output is missing: {path}').format(
                                path=expected_output
                            )
                        )
                    chapter_index += 1
                    chapter_path = os.path.join(
                        temporary_directory, f'chapter-{chapter_index:04d}.txt'
                    )
                    self._write_remux_segment_chapter_txt(
                        job.mpls_path,
                        start_chapter,
                        end_chapter,
                        chapter_path,
                    )
                    MKV(expected_output).add_chapter(True, chapter_path)
                    if os.path.normcase(expected_output) != os.path.normcase(final_output):
                        source_key = os.path.normcase(os.path.abspath(expected_output))
                        destination_key = os.path.normcase(os.path.abspath(final_output))
                        os.rename(expected_output, final_output)
                        for cache_name in (
                                '_remux_fallback_track_slots',
                                '_remux_fallback_track_source_slots',
                                '_remux_fallback_track_signatures',
                                '_remux_fallback_audio_timelines',
                                '_remux_fallback_audio_timeline_durations'):
                            cache = getattr(self, cache_name, None)
                            if not isinstance(cache, dict):
                                continue
                            cached_value = cache.pop(source_key, None)
                            if cached_value is not None:
                                cache[destination_key] = cached_value
                    final_by_configuration_key[configuration_key] = final_output

        ordered_keys = sorted(self.configuration)
        if set(final_by_configuration_key) != set(ordered_keys):
            raise RuntimeError(translate_text('Remux did not produce an output for every task row'))
        return [final_by_configuration_key[key] for key in ordered_keys]

    def episodes_remux(
            self,
            request: RemuxRequest,
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        """Run one complete Remux request without consulting GUI or directory contents."""
        self.remux_warnings = []
        self.checked = request.complete_bluray_folder
        self.movie_mode = request.movie_mode
        self.sub_files = list(request.subtitle_files)
        self.episode_subtitle_languages = list(request.episode_subtitle_languages)
        self._language_code = request.language_code
        self.allow_partial_missing_non_video_tracks = bool(
            request.allow_partial_missing_non_video_tracks
        )
        if request.clean_audio_tracks:
            validate_audio_cleanup_tools()
        dst_folder, jobs = self._prepare_remux_main_jobs(request)
        sp_jobs = self._prepare_sp_jobs(
            request.sp_entries,
            dst_folder,
            jobs,
            request.track_selection_config,
            request.track_language_config or {},
        )

        # Planning must finish before this task creates its first output directory.
        os.makedirs(dst_folder, exist_ok=True)
        self._build_main_episode_mkvs(jobs, cancel_event=cancel_event)
        if cancel_event and cancel_event.is_set():
            raise TaskCancelled()
        self._progress(385, 'Writing Chapters')
        main_outputs = self._post_remux_finalize_episodes(jobs, cancel_event)

        self._progress(400)
        completed_sp_jobs = 0

        def report_sp_output(_entry_index: int, path: str) -> None:
            nonlocal completed_sp_jobs
            completed_sp_jobs += 1
            self._progress(
                400 + int(completed_sp_jobs / max(len(sp_jobs), 1) * 100),
                self.t('Muxing SP {current}/{total}: {name}').format(
                    current=completed_sp_jobs,
                    total=len(sp_jobs),
                    name=os.path.basename(path),
                ),
            )

        sp_outputs = self._build_sp_outputs(
            sp_jobs,
            cancel_event=cancel_event,
            progress_cb=report_sp_output,
            audio_encoding=request.audio_encoding,
        )
        task_outputs = list(dict.fromkeys(
            main_outputs + [path for _entry_index, path in sp_outputs]
        ))
        normalized_main_outputs = {
            os.path.normcase(os.path.abspath(output_path))
            for output_path in main_outputs
        }
        subtitle_by_output = {
            os.path.normcase(os.path.abspath(output_path)): (
                str(subtitle_path).strip(),
                str(subtitle_language).strip(),
            )
            for output_path, subtitle_path, subtitle_language in zip(
                main_outputs,
                request.subtitle_files,
                request.episode_subtitle_languages,
            )
            if str(subtitle_path).strip()
        }
        if (
                request.clean_audio_tracks
                or request.convert_lossless_audio_to_flac
                or subtitle_by_output
                or bool(getattr(self, '_remux_fallback_audio_timelines', {}))
        ):
            main_matroska_outputs = []
            sp_matroska_outputs = []
            for output_path in task_outputs:
                normalized_output_path = os.path.normcase(os.path.abspath(output_path))
                subtitle_input = subtitle_by_output.get(normalized_output_path, ('', ''))
                if (
                        os.path.splitext(output_path)[1].lower() in ('.mkv', '.mka', '.mks')
                        and (
                            request.clean_audio_tracks
                            or request.convert_lossless_audio_to_flac
                            or subtitle_input[0]
                            or normalized_output_path in getattr(
                                self, '_remux_fallback_audio_timelines', {}
                            )
                        )
                ):
                    output_entry = (output_path, *subtitle_input)
                    if normalized_output_path in normalized_main_outputs:
                        main_matroska_outputs.append(output_entry)
                    else:
                        sp_matroska_outputs.append(output_entry)
            try:
                if request.clean_audio_tracks or request.convert_lossless_audio_to_flac:
                    for output_path, _subtitle_path, _subtitle_language in (
                            main_matroska_outputs + sp_matroska_outputs):
                        validate_audio_conversion_tools(
                            output_path,
                            None,
                            (),
                            convert_all_lossless_to_flac=request.convert_lossless_audio_to_flac,
                            convert_immersive_audio_to_flac=request.convert_immersive_audio_to_flac,
                        )
                for output_group, progress_start, progress_span in (
                        (main_matroska_outputs, 500, 400),
                        (sp_matroska_outputs, 900, 100),
                ):
                    for output_index, (output_path, subtitle_path, subtitle_language) in enumerate(
                            output_group, start=1):
                        if cancel_event and cancel_event.is_set():
                            raise TaskCancelled()
                        self._progress(
                            progress_start + int(
                                (output_index - 1) / len(output_group) * progress_span
                            ),
                            self.t(
                                'Converting lossless audio to FLAC: {name}'
                                if request.convert_lossless_audio_to_flac
                                else (
                                    'Checking silent and duplicate audio: {name}'
                                    if request.clean_audio_tracks
                                    else 'Muxing subtitle: {name}'
                                )
                            ).format(
                                name=os.path.basename(output_path)
                            ),
                        )
                        mux_with_audio_conversion(
                            output_path,
                            output_path,
                            selected_audio_tracks=None,
                            selected_subtitle_tracks=None,
                            audio_codec_choices=(),
                            convert_all_lossless_to_flac=request.convert_lossless_audio_to_flac,
                            convert_immersive_audio_to_flac=request.convert_immersive_audio_to_flac,
                            clean_audio_tracks=request.clean_audio_tracks,
                            subtitle_file=subtitle_path,
                            subtitle_language=subtitle_language,
                            audio_encoding=request.audio_encoding,
                            wave64_bit_depth=24,
                            audio_timeline_by_track=dict(
                                getattr(
                                    self, '_remux_fallback_audio_timelines', {}
                                ).get(
                                    os.path.normcase(os.path.abspath(output_path)),
                                    {},
                                )
                            ),
                            audio_timeline_duration_seconds=(
                                getattr(
                                    self,
                                    '_remux_fallback_audio_timeline_durations',
                                    {},
                                ).get(os.path.normcase(os.path.abspath(output_path)))
                            ),
                            write_audio_gaps=True,
                        )
                        self._progress(
                            progress_start + int(
                                output_index / len(output_group) * progress_span
                            )
                        )
            except Exception:
                for output_path in task_outputs:
                    if os.path.isdir(output_path):
                        shutil.rmtree(output_path, ignore_errors=True)
                    elif os.path.isfile(output_path):
                        force_remove_file(output_path)
                    sidecar_path = audio_gap_sidecar_path(output_path)
                    if os.path.isfile(sidecar_path):
                        force_remove_file(sidecar_path)
                raise
        self.completion()
        self._progress(1000, 'Done')

    def _encode_mkv_rows(
            self,
            request: EncodeRequest,
            main_rows: list[EncodeRow],
            sp_rows: list[EncodeRow],
            cancel_event: Optional[threading.Event],
            *,
            companion_root: str = '',
            progress_base: int = 0,
            progress_span: int = 1000,
            main_progress_span: Optional[int] = None,
            sp_progress_span: Optional[int] = None,
    ) -> EncodeBatchResult:
        """Encode every planned row through one shared execution path."""
        from src.runtime.services_split.encode_and_audio_tasks import encode_dovi_preflight_mkv_paths

        selected_sp_rows = [row for row in sp_rows if row.selected]
        # Remux-source outputs are durable checkpoints for multi-day Encode tasks.
        resume_existing_outputs = request.input_mode == 'remux'
        encode_sources = [
            row.source_path
            for row in main_rows
            if not (resume_existing_outputs and os.path.isfile(row.output_path) and os.path.getsize(row.output_path) > 0)
        ]
        encode_sources.extend(
            row.source_path
            for row in selected_sp_rows
            if (
                str(row.source_path).lower().endswith('.mkv')
                and not (resume_existing_outputs and os.path.isfile(row.output_path) and os.path.getsize(row.output_path) > 0)
            )
        )
        dolby_vision_error = encode_dovi_preflight_mkv_paths(
            encode_sources,
            request.settings.encoder,
            request.settings.bit_depth,
        )
        if dolby_vision_error:
            raise RuntimeError(dolby_vision_error)

        self.encode_warnings = []
        row_results: list[EncodeRowResult] = []
        self.sub_files = [row.subtitle_path for row in main_rows]
        self.episode_subtitle_languages = [row.subtitle_language for row in main_rows]
        self.use_getnative = request.settings.use_getnative
        if request.settings.auto_crop_black_borders:
            warning = translate_text(
                'Automatic black-border detection can be wrong; verify the encoded picture.'
            )
            self._progress(text=warning)

        def write_comparison_images(
                row: EncodeRow,
                source_path: str,
                row_number: int,
                progress_name: str,
        ) -> None:
            self._progress(text=self.t(
                'Generating comparison images: {name}'
            ).format(name=progress_name))
            frame_counts: list[int] = []
            # The encoded clip owns the comparison length. Decode it first, then stop
            # the source scan as soon as it reaches the same number of frames.
            scan_paths = (row.output_path, source_path)
            for scan_index, scan_path in enumerate(scan_paths, start=1):
                def report_frame_scan(
                        frames: int,
                        fps: float,
                        fraction: Optional[float],
                        remaining_seconds: Optional[float],
                ) -> None:
                    if fraction is None or remaining_seconds is None:
                        message = self.t(
                            'Comparison frame scan {current}/{total}: {name}; '
                            '{frames} frames, {fps:.1f} fps'
                        ).format(
                            current=scan_index,
                            total=len(scan_paths),
                            name=progress_name,
                            frames=frames,
                            fps=fps,
                        )
                    else:
                        message = self.t(
                            'Comparison frame scan {current}/{total}: {name}; '
                            '{percent:.1f}%, {frames} frames, {fps:.1f} fps, '
                            'ETA {eta}'
                        ).format(
                            current=scan_index,
                            total=len(scan_paths),
                            name=progress_name,
                            percent=fraction * 100.0,
                            frames=frames,
                            fps=fps,
                            eta=get_time_str(remaining_seconds),
                        )
                    print_terminal_line(message)

                frame_counts.append(self._video_frame_count_static(
                    scan_path,
                    progress_callback=report_frame_scan,
                    cancel_event=cancel_event,
                    max_frames=(frame_counts[0] if frame_counts else None),
                ))
            encoded_frames, source_frames = frame_counts
            shared_frames = min(source_frames, encoded_frames)
            if shared_frames <= 0:
                raise RuntimeError(
                    translate_text(
                        'Could not determine a shared comparison frame for: {path}'
                    ).format(path=row.output_path)
                )
            frame_number = shared_frames // 2
            output_stem = os.path.splitext(os.path.basename(row.output_path))[0]
            short_stem = re.sub(
                r'[<>:"/\\|?*\x00-\x1f]+',
                '_',
                output_stem,
            )
            short_stem = re.sub(r'\s+', '_', short_stem).strip(' ._')[:40]
            if not short_stem:
                short_stem = 'output'
            comparison_folder = os.path.join(
                os.path.dirname(row.output_path),
                'Compare',
            )
            image_base = (
                f'{row_number:03d}-{short_stem}-f{frame_number:06d}'
            )
            image_pairs = (
                (source_path, os.path.join(
                    comparison_folder,
                    image_base + '-source.png',
                )),
                (row.output_path, os.path.join(
                    comparison_folder,
                    image_base + '-encoded.png',
                )),
            )
            if all(
                    os.path.isfile(image_path)
                    and os.path.getsize(image_path) > 0
                    for _media_path, image_path in image_pairs
            ):
                return
            os.makedirs(comparison_folder, exist_ok=True)
            ffmpeg_path = str(core_settings.FFMPEG_PATH or 'ffmpeg')
            for media_path, image_path in image_pairs:
                if os.path.exists(image_path):
                    if os.path.isfile(image_path) and os.path.getsize(image_path) > 0:
                        continue
                    raise FileExistsError(
                        translate_text(
                            'Comparison image output is invalid: {path}'
                        ).format(path=image_path)
                    )
                command = [
                    ffmpeg_path,
                    '-hide_banner',
                    '-loglevel',
                    'error',
                    '-nostdin',
                    '-n',
                    '-i',
                    media_path,
                    '-map',
                    '0:v:0',
                    '-vf',
                    f'select=eq(n\\,{frame_number})',
                    '-fps_mode',
                    'passthrough',
                    '-frames:v',
                    '1',
                    '-update',
                    '1',
                    image_path,
                ]
                result = run_command(
                    command,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                )
                if result.returncode != 0 or not (
                        os.path.isfile(image_path)
                        and os.path.getsize(image_path) > 0
                ):
                    if os.path.isfile(image_path) and os.path.getsize(image_path) == 0:
                        force_remove_file(image_path)
                    detail = str(result.stderr or result.stdout or '').strip()
                    raise RuntimeError(
                        translate_text(
                            'Could not create comparison image: {path}. {error}'
                        ).format(
                            path=image_path,
                            error=detail or translate_text('unknown error'),
                        )
                    )
            self._progress(
                text=self.t('Comparison images saved: {path}').format(
                    path=comparison_folder
                )
            )

        def write_comparison_images_or_warn(
                row: EncodeRow,
                source_path: str,
                row_number: int,
                progress_name: str,
        ) -> None:
            if not request.settings.output_comparison_images:
                return
            try:
                write_comparison_images(
                    row,
                    source_path,
                    row_number,
                    progress_name,
                )
            except TaskCancelled:
                raise
            except Exception as error:
                message = translate_text(
                    'Comparison images could not be created for {name}: {error}'
                ).format(
                    name=os.path.basename(row.output_path),
                    error=str(error),
                )
                self.encode_warnings.append(message)
                self._progress(text=message)

        def record_completed_row(
                row: EncodeRow,
                row_type: str,
                warning_start: int,
        ) -> None:
            row_warnings = tuple(self.encode_warnings[warning_start:])
            row_results.append(EncodeRowResult(
                row_type=row_type,
                source_path=row.source_path,
                output_path=row.output_path,
                status=(
                    'completed_with_warnings'
                    if row_warnings
                    else 'completed'
                ),
                warnings=row_warnings,
            ))

        def record_failed_row(
                row: EncodeRow,
                row_type: str,
                warning_start: int,
                error: Exception,
        ) -> None:
            artifact_paths = tuple(dict.fromkeys(
                os.path.abspath(os.path.normpath(path))
                for path in tuple(getattr(error, 'artifact_paths', ()) or ())
                if (
                    (os.path.isfile(path) and os.path.getsize(path) > 0)
                    or os.path.isdir(path)
                )
            ))
            stage = str(getattr(error, 'stage', '') or 'Encode row execution')
            try:
                report_path = write_encode_row_error_report(
                    row_type,
                    row.source_path,
                    row.output_path,
                    stage,
                    error,
                    artifact_paths,
                )
            except Exception as report_error:
                report_path = ''
                print(
                    translate_text(
                        'Failed to write Encode row error report: {error}'
                    ).format(error=report_error),
                    flush=True,
                )
            failure_message = translate_text(
                'Encode row failed; later rows will continue: {path}. '
                'Error report: {report}'
            ).format(
                path=row.output_path,
                report=report_path or translate_text('unavailable'),
            )
            prior_warnings = tuple(self.encode_warnings[warning_start:])
            self.encode_warnings.append(failure_message)
            self._progress(text=failure_message)
            row_results.append(EncodeRowResult(
                row_type=row_type,
                source_path=row.source_path,
                output_path=row.output_path,
                status=(
                    'failed_with_artifacts'
                    if artifact_paths
                    else 'failed'
                ),
                message=str(error),
                report_path=report_path,
                artifact_paths=artifact_paths,
                warnings=prior_warnings + (failure_message,),
            ))

        def execute_video_row(
                row: EncodeRow,
                source_path: str,
                progress_name: str,
                video_progress_name: str = '',
        ) -> None:
            video_progress_name = str(
                video_progress_name or os.path.basename(row.output_path)
            ).strip()
            self.encode_task(
                row.output_path,
                row.vpy_path,
                request.settings.vspipe_mode,
                request.settings.encoder_mode,
                request.settings.encoder_parameters,
                request.settings.subtitle_mode,
                source_file=source_path,
                encoder=request.settings.encoder,
                bit_depth=request.settings.bit_depth,
                selected_audio_tracks=(
                    row.audio_tracks if request.input_mode == 'remux' else None
                ),
                selected_subtitle_tracks=(
                    row.subtitle_tracks if request.input_mode == 'remux' else None
                ),
                audio_codec_choices=row.audio_codec_choices,
                track_language_overrides=(
                    row.track_language_overrides
                    if request.input_mode == 'remux'
                    else ()
                ),
                subtitle_path=row.subtitle_path,
                subtitle_language=row.subtitle_language,
                audio_encoding=request.settings.audio_encoding,
                wave64_bit_depth=(24 if request.input_mode == 'bdmv' else 32),
                audio_timeline_by_track=dict(
                    getattr(self, '_remux_fallback_audio_timelines', {}).get(
                        os.path.normcase(os.path.abspath(source_path)),
                        {},
                    )
                ),
                detect_audio_gaps=(request.input_mode == 'remux'),
                auto_crop_black_borders=request.settings.auto_crop_black_borders,
                vpy_denoise_strength=request.settings.vpy_denoise_strength,
                vpy_dehalo_strength=request.settings.vpy_dehalo_strength,
                vpy_dering_strength=request.settings.vpy_dering_strength,
                vpy_deband_strength=request.settings.vpy_deband_strength,
                vpy_antialiasing_strength=(
                    request.settings.vpy_antialiasing_strength
                ),
                check_corrupted_frames=request.settings.check_corrupted_frames,
                frame_check_luma_psnr_threshold_db=(
                    request.settings.frame_check_luma_psnr_threshold_db
                ),
                frame_check_chroma_psnr_threshold_db=(
                    request.settings.frame_check_chroma_psnr_threshold_db
                ),
                progress_name=progress_name,
                video_progress_name=video_progress_name,
                cancel_event=cancel_event,
            )
            if not os.path.isfile(row.output_path):
                raise RuntimeError(
                    translate_text('Encode output is missing: {path}').format(
                        path=row.output_path
                    )
                )

        planned_output_paths = {
            os.path.normcase(os.path.abspath(row.output_path))
            for row in main_rows + selected_sp_rows
        }
        external_subtitles: list[tuple[str, str, str]] = []
        if request.settings.subtitle_mode == 'external':
            for row in main_rows:
                if not row.subtitle_path:
                    continue
                subtitle_extension = os.path.splitext(row.subtitle_path)[1]
                subtitle_destination = os.path.join(
                    os.path.dirname(row.output_path),
                    os.path.splitext(os.path.basename(row.output_path))[0] + subtitle_extension,
                )
                normalized_destination = os.path.normcase(os.path.abspath(subtitle_destination))
                if normalized_destination in planned_output_paths:
                    raise ValueError(
                        translate_text('Duplicate output path: {path}').format(
                            path=subtitle_destination
                        )
                    )
                if os.path.exists(subtitle_destination) and (not resume_existing_outputs or not os.path.isfile(subtitle_destination)):
                    raise FileExistsError(
                        translate_text(
                            'Existing resumable output is invalid: {path}'
                            if resume_existing_outputs else 'Output file already exists: {path}'
                        ).format(path=subtitle_destination)
                    )
                planned_output_paths.add(normalized_destination)
                external_subtitles.append((
                    row.subtitle_path,
                    subtitle_destination,
                    row.output_path,
                ))

        companion_files: list[tuple[str, str]] = []
        if companion_root and os.path.isdir(companion_root):
            root_path = os.path.abspath(os.path.normpath(companion_root))
            encoded_source_paths = {
                os.path.normcase(os.path.abspath(row.source_path))
                for row in main_rows + selected_sp_rows
                if row.source_path
            }
            external_by_destination = {
                os.path.normcase(os.path.abspath(destination)): os.path.normcase(os.path.abspath(source))
                for source, destination, _video_output in external_subtitles
            }
            for current_folder, _directories, filenames in os.walk(root_path):
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                relative_folder = os.path.relpath(current_folder, root_path)
                for filename in filenames:
                    source_path = os.path.join(current_folder, filename)
                    if os.path.normcase(os.path.abspath(source_path)) in encoded_source_paths:
                        continue
                    if filename.lower().endswith('.mkv.audio-gaps.json') or (
                            filename.lower().endswith('.mka.audio-gaps.json')):
                        owner_path = source_path[:-len('.audio-gaps.json')]
                        if os.path.normcase(os.path.abspath(owner_path)) in encoded_source_paths:
                            continue
                    relative_path = filename if relative_folder == '.' else os.path.join(relative_folder, filename)
                    destination_path = os.path.join(request.output_folder, relative_path)
                    normalized_destination = os.path.normcase(os.path.abspath(destination_path))
                    if (
                            normalized_destination in external_by_destination
                            and external_by_destination[normalized_destination]
                            == os.path.normcase(os.path.abspath(source_path))
                    ):
                        continue
                    if normalized_destination in planned_output_paths:
                        raise ValueError(
                            translate_text('Duplicate output path: {path}').format(
                                path=destination_path
                            )
                        )
                    if os.path.exists(destination_path) and (not resume_existing_outputs or not os.path.isfile(destination_path)):
                        raise FileExistsError(
                            translate_text(
                                'Existing resumable output is invalid: {path}'
                                if resume_existing_outputs else 'Output file already exists: {path}'
                            ).format(path=destination_path)
                        )
                    planned_output_paths.add(normalized_destination)
                    companion_files.append((source_path, destination_path))

        for row in main_rows + selected_sp_rows:
            if not os.path.exists(row.output_path):
                continue
            source_path = os.path.normpath(row.source_path)
            valid_checkpoint = (
                os.path.isdir(row.output_path)
                if os.path.isdir(source_path)
                else os.path.isfile(row.output_path)
                and os.path.getsize(row.output_path) > 0
            )
            if not (resume_existing_outputs and valid_checkpoint):
                raise FileExistsError(
                    translate_text(
                        'Existing resumable output is invalid: {path}'
                        if resume_existing_outputs else 'Output file already exists: {path}'
                    ).format(path=row.output_path)
                )

        os.makedirs(request.output_folder, exist_ok=True)
        total_rows = max(1, len(main_rows) + len(selected_sp_rows))
        completed_rows = 0
        completed_main_rows = 0
        completed_sp_rows = 0
        weighted_progress = (
            main_progress_span is not None
            and sp_progress_span is not None
        )

        def row_progress(category: str) -> int:
            if not weighted_progress:
                return progress_base + int(
                    completed_rows / total_rows * progress_span
                )
            if category == 'main':
                return progress_base + int(
                    completed_main_rows
                    / max(len(main_rows), 1)
                    * main_progress_span
                )
            return progress_base + main_progress_span + int(
                completed_sp_rows
                / max(len(selected_sp_rows), 1)
                * sp_progress_span
            )

        for row in main_rows:
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            warning_start = len(self.encode_warnings)
            progress_name = f'EP{completed_main_rows + 1:02d}'
            self._progress(
                row_progress('main'),
                self.t('Preparing episode {current}/{total}: {name}').format(
                    current=completed_main_rows + 1,
                    total=len(main_rows),
                    name=progress_name,
                ),
            )
            if os.path.exists(row.output_path):
                self._progress(
                    text=self.t('Skipping existing output: {path}').format(
                        path=row.output_path
                    )
                )
                write_comparison_images_or_warn(
                    row,
                    row.source_path,
                    completed_rows + 1,
                    progress_name,
                )
                record_completed_row(row, 'Main row', warning_start)
                completed_rows += 1
                completed_main_rows += 1
                continue
            os.makedirs(os.path.dirname(row.output_path), exist_ok=True)
            try:
                execute_video_row(row, row.source_path, progress_name)
            except TaskCancelled:
                raise
            except Exception as error:
                record_failed_row(row, 'Main row', warning_start, error)
            else:
                write_comparison_images_or_warn(
                    row,
                    row.source_path,
                    completed_rows + 1,
                    progress_name,
                )
                record_completed_row(row, 'Main row', warning_start)
            completed_rows += 1
            completed_main_rows += 1

        staged_main_sources = {
            os.path.normcase(os.path.abspath(row.source_path))
            for row in main_rows
        }
        # Copy-only image folders and extracted assets are still selected table3
        # rows, so they consume the same visible SP sequence as encoded videos.
        for sp_sequence_number, row in enumerate(selected_sp_rows, start=1):
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            warning_start = len(self.encode_warnings)
            progress_name = f'SP{sp_sequence_number:02d}'
            self._progress(
                row_progress('sp'),
                self.t('Preparing SP {current}/{total}: {name}').format(
                    current=sp_sequence_number,
                    total=len(selected_sp_rows),
                    name=progress_name,
                ),
            )
            source_path = os.path.normpath(row.source_path)
            if os.path.normcase(os.path.abspath(source_path)) in staged_main_sources:
                # Episode-linked SP muxing has already modified this main source in the stage.
                record_completed_row(row, 'SP row', warning_start)
                completed_rows += 1
                completed_sp_rows += 1
                continue
            if os.path.exists(row.output_path):
                self._progress(
                    text=self.t('Skipping existing output: {path}').format(
                        path=row.output_path
                    )
                )
                if source_path.lower().endswith('.mkv'):
                    write_comparison_images_or_warn(
                        row,
                        source_path,
                        completed_rows + 1,
                        progress_name,
                    )
                record_completed_row(row, 'SP row', warning_start)
                completed_rows += 1
                completed_sp_rows += 1
                continue
            os.makedirs(os.path.dirname(row.output_path), exist_ok=True)
            try:
                if os.path.isdir(source_path):
                    _copy_path_atomically(source_path, row.output_path, preserve_failure_artifacts=True)
                elif source_path.lower().endswith('.mka'):
                    mux_with_audio_conversion(
                        source_path,
                        row.output_path,
                        selected_audio_tracks=(
                            row.audio_tracks if request.input_mode == 'remux' else None
                        ),
                        selected_subtitle_tracks=(
                            row.subtitle_tracks if request.input_mode == 'remux' else None
                        ),
                        audio_codec_choices=row.audio_codec_choices,
                        track_language_overrides=(
                            row.track_language_overrides
                            if request.input_mode == 'remux'
                            else ()
                        ),
                        audio_encoding=request.settings.audio_encoding,
                        wave64_bit_depth=(
                            24 if request.input_mode == 'bdmv' else 32
                        ),
                        audio_timeline_by_track=dict(
                            getattr(
                                self, '_remux_fallback_audio_timelines', {}
                            ).get(
                                os.path.normcase(os.path.abspath(source_path)),
                                {},
                            )
                        ),
                        detect_audio_gaps=(request.input_mode == 'remux'),
                        preserve_failure_artifacts=True,
                        progress_callback=lambda operation, name=progress_name: self._progress(
                            text=self.t('{operation}: {name}').format(
                                operation=operation,
                                name=name,
                            )
                        ),
                    )
                elif source_path.lower().endswith('.mkv'):
                    original_name = os.path.basename(
                        row.sp_entry.output_name
                        if row.sp_entry is not None
                        else row.output_path
                    )
                    execute_video_row(
                        row,
                        source_path,
                        progress_name,
                        video_progress_name=original_name,
                    )
                else:
                    _copy_path_atomically(source_path, row.output_path, preserve_failure_artifacts=True)
            except (TaskCancelled, FileExistsError):
                raise
            except Exception as error:
                record_failed_row(row, 'SP row', warning_start, error)
            else:
                if source_path.lower().endswith('.mkv'):
                    write_comparison_images_or_warn(
                        row,
                        source_path,
                        completed_rows + 1,
                        progress_name,
                    )
                record_completed_row(row, 'SP row', warning_start)
            completed_rows += 1
            completed_sp_rows += 1

        if companion_files:
            self._progress(text=self.t('Copying companion files'))
            for source_path, destination_path in companion_files:
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                if os.path.exists(destination_path):
                    if resume_existing_outputs and os.path.isfile(destination_path):
                        self._progress(
                            text=self.t('Skipping existing output: {path}').format(path=destination_path)
                        )
                        continue
                    raise FileExistsError(
                        translate_text(
                            'Existing resumable output is invalid: {path}'
                            if resume_existing_outputs else 'Output file already exists: {path}'
                        ).format(path=destination_path)
                    )
                _copy_path_atomically(source_path, destination_path)
        if external_subtitles:
            self._progress(text=self.t('Copying external subtitles'))
            for source_path, destination_path, video_output_path in external_subtitles:
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                if not os.path.isfile(video_output_path):
                    continue
                if os.path.exists(destination_path):
                    if resume_existing_outputs and os.path.isfile(destination_path):
                        self._progress(
                            text=self.t('Skipping existing output: {path}').format(path=destination_path)
                        )
                        continue
                    raise FileExistsError(
                        translate_text(
                            'Existing resumable output is invalid: {path}'
                            if resume_existing_outputs else 'Output file already exists: {path}'
                        ).format(path=destination_path)
                    )
                _copy_path_atomically(source_path, destination_path)
        final_progress = (
            progress_base + main_progress_span + sp_progress_span
            if weighted_progress
            else progress_base + progress_span
        )
        self._progress(final_progress, 'Done')
        batch_result = EncodeBatchResult(tuple(row_results))
        return batch_result

    def episodes_encode(
            self,
            request: EncodeRequest,
            cancel_event: Optional[threading.Event] = None,
    ) -> EncodeBatchResult:
        """Run one complete Encode request without consulting GUI state."""
        self.checked = False
        self.movie_mode = request.movie_mode
        self.mux_dolby_vision = request.mux_dolby_vision
        self.allow_partial_missing_non_video_tracks = bool(
            request.allow_partial_missing_non_video_tracks
        )

        if request.input_mode == 'remux':
            return self._encode_mkv_rows(
                request,
                list(request.main_rows),
                list(request.sp_rows),
                cancel_event,
                companion_root=request.source_root,
            )

        configuration = {
            int(row.configuration_key): dict(row.configuration or {})
            for row in request.main_rows
        }
        subtitle_files = tuple(row.subtitle_path for row in request.main_rows)
        episode_output_names = tuple(
            os.path.basename(row.output_path)
            for row in request.main_rows
        )
        episode_subtitle_languages = tuple(
            row.subtitle_language
            for row in request.main_rows
        )
        if any(row.sp_entry is None for row in request.sp_rows):
            raise ValueError(translate_text('Encode SP row has no task configuration'))
        sp_entries = tuple(
            row.sp_entry for row in request.sp_rows if row.sp_entry is not None
        )
        preserve_dolby_vision = (
            request.mux_dolby_vision and request.settings.encoder != 'svtav1'
        )
        if request.mux_dolby_vision and not preserve_dolby_vision:
            message = translate_text(
                'Dolby Vision metadata will not be retained for SVT-AV1 output: {path}'
            ).format(path=request.source_root)
            print(f'[encode-dovi] {message}', flush=True)
            self._progress(text=message)

        stage_request = RemuxRequest(
            bdmv_path=request.source_root,
            subtitle_files=subtitle_files,
            complete_bluray_folder=False,
            output_folder=request.staging_folder,
            configuration=configuration,
            selected_mpls=request.selected_mpls,
            sp_entries=sp_entries,
            episode_output_names=episode_output_names,
            episode_subtitle_languages=episode_subtitle_languages,
            movie_mode=request.movie_mode,
            mux_dolby_vision=preserve_dolby_vision,
            convert_lossless_audio_to_flac=False,
            allow_partial_missing_non_video_tracks=(
                request.allow_partial_missing_non_video_tracks
            ),
            clean_audio_tracks=False,
            track_selection_config=copy.deepcopy(request.track_selection_config or {}),
            track_language_config=copy.deepcopy(request.track_language_config or {}),
            main_alternate_mpls=copy.deepcopy(request.main_alternate_mpls or {}),
            ensure_tools=False,
        )

        staging_parent_existed = os.path.isdir(request.staging_folder)
        staging_disc_folder = ''
        planned_main_stage_files: list[str] = []
        staged_main_files: list[str] = []
        created_sp_files: list[tuple[int, str]] = []
        main_stage_started = False
        batch_result: Optional[EncodeBatchResult] = None
        try:
            staging_disc_folder, main_jobs = self._prepare_remux_main_jobs(stage_request)
            planned_main_stage_files = list(dict.fromkeys(
                output_path
                for job in main_jobs
                for output_path in (*job.expected_outputs, *job.final_outputs)
            ))
            final_encode_outputs = {
                os.path.normcase(os.path.abspath(row.output_path))
                for row in request.main_rows + tuple(
                    row for row in request.sp_rows if row.selected
                )
                if row.output_path
            }
            staging_collision = next((
                output_path
                for job in main_jobs
                for output_path in (*job.expected_outputs, *job.final_outputs)
                if os.path.normcase(os.path.abspath(output_path)) in final_encode_outputs
            ), '')
            if staging_collision:
                raise ValueError(
                    translate_text('Duplicate output path: {path}').format(
                        path=staging_collision
                    )
                )
            sp_jobs = self._prepare_sp_jobs(
                sp_entries,
                staging_disc_folder,
                main_jobs,
                request.track_selection_config,
                request.track_language_config or {},
            )
            sp_original_name_by_entry_index = {
                job.entry_index: os.path.basename(job.entry.output_name)
                for job in sp_jobs
            }
            os.makedirs(staging_disc_folder, exist_ok=True)
            main_stage_started = True
            self._build_main_episode_mkvs(
                main_jobs,
                cancel_event=cancel_event,
                mux_progress_base=0,
                mux_progress_span=160,
            )
            self._progress(160, 'Writing Chapters')
            staged_main_files = self._post_remux_finalize_episodes(main_jobs, cancel_event)
            self._progress(160)

            completed_sp_mux = 0

            def report_sp_mux(entry_index: int, path: str) -> None:
                nonlocal completed_sp_mux
                completed_sp_mux += 1
                self._progress(
                    160 + int(completed_sp_mux / max(len(sp_jobs), 1) * 40),
                    self.t('Muxing SP {current}/{total}: {name}').format(
                        current=completed_sp_mux,
                        total=len(sp_jobs),
                        name=sp_original_name_by_entry_index.get(
                            entry_index,
                            os.path.basename(path),
                        ),
                    ),
                )

            created_sp_files = self._build_sp_outputs(
                sp_jobs,
                cancel_event=cancel_event,
                progress_cb=report_sp_mux,
                audio_encoding=request.settings.audio_encoding,
                standalone_audio_targets={
                    index: row.audio_codec_choices[0]
                    for index, row in enumerate(request.sp_rows, start=1)
                    if (
                        row.selected
                        and not row.uses_main_output
                        and len(row.audio_tracks) == 1
                        and not row.subtitle_tracks
                        and len(row.audio_codec_choices) == 1
                        and os.path.splitext(row.output_path)[1].lower()
                        == {'flac': '.flac', 'aac': '.m4a', 'opus': '.opus'}.get(
                            row.audio_codec_choices[0], ''
                        )
                    )
                },
            )
            self._progress(200)
            staged_main_by_key = {
                configuration_key: staged_path
                for configuration_key, staged_path in zip(
                    sorted(configuration),
                    staged_main_files,
                )
            }
            linked_sp_audio_codec_by_signature: dict[
                str, dict[tuple[tuple[str, int], ...], str]
            ] = {}
            for sp_row in request.sp_rows:
                if not (sp_row.selected and sp_row.uses_main_output and sp_row.sp_entry):
                    continue
                entry = sp_row.sp_entry
                if not entry.mpls_file:
                    continue
                output_key = os.path.normcase(os.path.abspath(sp_row.output_path))
                provider_by_signature = linked_sp_audio_codec_by_signature.setdefault(
                    output_key, {}
                )
                source_mpls = os.path.abspath(os.path.join(
                    entry.bdmv_root, 'BDMV', 'PLAYLIST', entry.mpls_file
                ))
                for selection_key, codec in zip(
                        sp_row.audio_tracks, sp_row.audio_codec_choices):
                    selected_slots = _svc_cls()._selected_pid_slots_for_mpls(
                        source_mpls,
                        {'audio': [str(selection_key)]},
                    )
                    audio_slot = next(
                        (
                            slot for slot in selected_slots
                            if str(slot.get('type') or '') == 'audio'
                        ),
                        None,
                    )
                    if audio_slot is None:
                        continue
                    signature = _svc_cls()._mpls_track_mapping_signature(audio_slot)
                    if signature:
                        provider_by_signature.setdefault(signature, codec)

            linked_sp_audio_codecs: dict[str, tuple[str, ...]] = {}
            for row in request.main_rows:
                output_key = os.path.normcase(os.path.abspath(row.output_path))
                staged_path = staged_main_by_key[int(row.configuration_key)]
                staged_key = os.path.normcase(os.path.abspath(staged_path))
                original_signature_map = (
                    getattr(self, '_episode_sp_mux_original_main_signatures', {}) or {}
                ).get(staged_key, {})
                final_signature_map = (
                    getattr(self, '_episode_sp_mux_last_after_mux_signatures', {}) or {}
                ).get(staged_key, {})
                provider_by_signature = linked_sp_audio_codec_by_signature.get(
                    output_key, {}
                )
                linked_sp_audio_codecs[output_key] = tuple(
                    provider_by_signature[signature]
                    for track_id, signature in sorted(final_signature_map.items())
                    if track_id not in original_signature_map
                    and signature in provider_by_signature
                )
            resolved_main_rows = [
                replace(
                    row,
                    source_path=staged_main_by_key[int(row.configuration_key)],
                    audio_codec_choices=(
                        row.audio_codec_choices
                        + linked_sp_audio_codecs.get(
                            os.path.normcase(os.path.abspath(row.output_path)),
                            (),
                        )
                    ),
                )
                for row in request.main_rows
            ]
            staged_sp_by_index = {
                entry_index: staged_path
                for entry_index, staged_path in created_sp_files
                if os.path.exists(staged_path)
            }
            resolved_sp_rows: list[EncodeRow] = []
            for entry_index, row in enumerate(request.sp_rows, start=1):
                if not row.selected:
                    continue
                staged_path = staged_sp_by_index.get(entry_index)
                if not staged_path:
                    raise RuntimeError(
                        translate_text('Selected SP output is missing: {path}').format(
                            path=row.output_path
                        )
                    )
                resolved_sp_rows.append(replace(row, source_path=staged_path))

            batch_result = self._encode_mkv_rows(
                request,
                resolved_main_rows,
                resolved_sp_rows,
                cancel_event,
                progress_base=200,
                main_progress_span=640,
                sp_progress_span=160,
            )
        finally:
            if main_stage_started and request.staging_folder:
                managed_stage_root = os.path.abspath(os.path.normpath(request.staging_folder))
                for staged_main_file in planned_main_stage_files:
                    staged_path = os.path.abspath(os.path.normpath(staged_main_file))
                    try:
                        is_managed_stage = os.path.commonpath(
                            (managed_stage_root, staged_path)
                        ) == managed_stage_root
                    except ValueError:
                        is_managed_stage = False
                    if not is_managed_stage and os.path.isfile(staged_path):
                        force_remove_file(staged_path)
            if (
                    staging_disc_folder
                    and os.path.isdir(staging_disc_folder)
            ):
                shutil.rmtree(staging_disc_folder, ignore_errors=True)
            if (
                    not staging_parent_existed
                    and request.staging_folder
                    and os.path.isdir(request.staging_folder)
            ):
                try:
                    os.rmdir(request.staging_folder)
                except OSError:
                    pass
        if batch_result is None:
            raise RuntimeError(translate_text('Encode batch did not return a result'))
        return batch_result
