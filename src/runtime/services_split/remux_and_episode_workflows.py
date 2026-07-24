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
    run_command,
)
from src.runtime.audio_conversion import mux_with_audio_conversion
from src.runtime.sp import SpEntry, SpJob, media_track_key
from src.runtime.remux import RemuxMainJob, RemuxRequest
from src.runtime.encode import EncodeRequest, EncodeRow
from .service_base import BluraySubtitleServiceBase
from ..services.cancelled import _Cancelled


def _svc_cls():
    from ..services.bluray_subtitle_entry import BluraySubtitle
    return BluraySubtitle


class RemuxEpisodeWorkflowsMixin(BluraySubtitleServiceBase):

    def _prepare_remux_main_jobs(self, request: RemuxRequest) -> tuple[str, list[RemuxMainJob]]:
        """Resolve every selected main playlist and all output paths before the first write."""
        if request.ensure_tools:
            find_mkvtoolnix()
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
                track_language_overrides=tuple(
                    (str(track_index), str(language).strip())
                    for track_index, language in (
                        (request.track_language_config or {}).get(
                            media_track_key('main', mpls_path), {}
                        ) or {}
                    ).items()
                    if str(language).strip()
                ),
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
        main_output_to_mpls: dict[str, str] = {}
        occupied_outputs: dict[str, str] = {}
        first_main_mpls_by_disc: dict[int, str] = {}
        for main_job in main_jobs:
            first_main_mpls_by_disc.setdefault(main_job.bdmv_index, main_job.mpls_path)
            for output_path in main_job.expected_outputs:
                occupied_outputs[os.path.normcase(os.path.abspath(output_path))] = 'main'
            for output_path in main_job.final_outputs:
                normalized_output = os.path.normcase(os.path.abspath(output_path))
                occupied_outputs[normalized_output] = 'main'
                main_output_to_mpls[normalized_output] = main_job.mpls_path

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

            if track_selection_config is None:
                selected_audio, selected_subtitles = self._select_tracks_for_source(
                    source_path,
                    config_key=None,
                )
                selected_tracks = {'audio': selected_audio, 'subtitle': selected_subtitles}
            elif entry.track_key not in track_selection_config:
                raise ValueError(
                    translate_text('SP row {row} has no captured track selection').format(
                        row=entry_index
                    )
                )
            else:
                selected_tracks = track_selection_config.get(entry.track_key) or {}
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

            normalized_output = os.path.normcase(output_path)
            episode_main_mpls_path = ''
            normalized_output_name = entry.output_name.replace('\\', '/')
            episode_linked = (
                not normalized_output_name.lower().startswith('sps/')
                and os.path.basename(normalized_output_name).upper().startswith('EP')
            )
            if episode_linked:
                episode_main_mpls_path = main_output_to_mpls.get(normalized_output, '')
                if not episode_main_mpls_path:
                    raise ValueError(
                        translate_text('SP row {row} does not match a planned episode output: {path}').format(
                            row=entry_index,
                            path=output_path,
                        )
                    )
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
            ))

        if any(job.track_language_overrides for job in planned_jobs):
            find_mkvtoolnix()
            mkvpropedit_path = core_settings.MKV_PROP_EDIT_PATH or shutil.which('mkvpropedit')
            if not mkvpropedit_path or not os.path.isfile(mkvpropedit_path):
                raise FileNotFoundError(translate_text('mkvpropedit not found'))
        return planned_jobs

    def _apply_episode_output_names(self, mkv_files: list[str], output_names: Optional[list[str]] = None) -> list[str]:
        total = len(mkv_files)
        if total <= 0:
            return mkv_files
        planned = output_names or []
        updated: list[str] = []
        char_map = {
            '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'", '/': '／', '\\': '／', '|': '￨'
        }
        for i, p in enumerate(mkv_files, start=1):
            folder = os.path.dirname(p)
            base = os.path.basename(p)
            user_name = planned[i - 1].strip() if i - 1 < len(planned) and isinstance(planned[i - 1], str) else ''
            new_base = user_name if user_name else base
            if new_base:
                new_base = ''.join(char_map.get(char) or char for char in new_base)
                new_base = new_base.strip().rstrip('.')
            if not new_base.lower().endswith('.mkv'):
                new_base += '.mkv'
            new_path = os.path.join(folder, new_base)
            if os.path.normcase(p) == os.path.normcase(new_path):
                updated.append(p)
                continue
            if not os.path.exists(p):
                updated.append(p)
                continue
            if os.path.exists(new_path):
                stem, ext = os.path.splitext(new_base)
                k = 1
                candidate = new_path
                while os.path.exists(candidate):
                    candidate = os.path.join(folder, f'{stem} ({k}){ext}')
                    k += 1
                new_path = candidate
            try:
                os.rename(p, new_path)
                updated.append(new_path)
            except Exception:
                updated.append(p)
        return updated

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
        completed_outputs: list[str] = []
        for job_index, job in enumerate(jobs, start=1):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
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
                if job.m2ts_file:
                    msg += f' {self.t("(reference M2TS: ")}{os.path.basename(job.m2ts_file)})'
                print(msg)
                self._progress(text=msg)

            self._set_dovi_mux_plan_for_mpls(job.mpls_path)
            identify_ok = self._mkvmerge_identify_covers_remux_slots(
                job.mpls_path, list(job.audio_tracks), list(job.subtitle_tracks)
            )
            if not identify_ok:
                print('[remux-fallback] skipping primary mkvmerge (see identify check lines above)')
            print(f'{self.t("Mux command: ")}{job.command}')
            self._progress(text=f'{self.t("Muxing: ")}BD_Vol_{job.volume}')
            if identify_ok:
                return_code, _line_return_codes = self._run_shell_command_detailed(job.command)
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

            try:
                clip_count = len(Chapter(job.mpls_path).in_out_time or [])
            except Exception:
                clip_count = 0
            cover = ''
            if clip_count > 1:
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

            fallback_audio, fallback_subtitle = _svc_cls()._fallback_track_lists(
                job.command, list(job.audio_tracks), list(job.subtitle_tracks)
            )
            split_output = len(job.expected_outputs) > 1
            if not primary_ok:
                if split_output and clip_count > 1:
                    self._progress(text=self.t(
                        'Multi-output track-aligned fallback: {name}'
                    ).format(name=f'BD_Vol_{job.volume}'))
                    self._try_remux_mpls_split_outputs_track_aligned(
                        job.mpls_path,
                        job.primary_output,
                        configurations,
                        fallback_audio,
                        fallback_subtitle,
                        cover,
                        cancel_event=cancel_event,
                    )
                elif not split_output:
                    self._progress(text=self.t(
                        'Track-aligned fallback: {name}'
                    ).format(name=f'BD_Vol_{job.volume}'))
                    self._try_remux_mpls_track_aligned(
                        job.mpls_path,
                        job.primary_output,
                        fallback_audio,
                        fallback_subtitle,
                        cover,
                        cancel_event=cancel_event,
                    )
                primary_ok = all(os.path.isfile(path) for path in job.expected_outputs)
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
                        self._progress(
                            text=f'{self.t("Correcting track languages: ")}'
                                 f'{os.path.basename(output_path)}'
                        )
                        _svc_cls()._fix_output_track_languages_with_mkvpropedit(
                            output_path,
                            job.m2ts_file,
                            list(job.audio_tracks),
                            list(job.subtitle_tracks),
                            dict(job.track_language_overrides),
                            getattr(self, '_dovi_mux_plan', None),
                        )
                except Exception:
                    for output_path in job.expected_outputs:
                        if os.path.isfile(output_path):
                            force_remove_file(output_path)
                    raise

            completed_outputs.extend(job.expected_outputs)
            self._progress(
                mux_progress_base + int(job_index / max(len(jobs), 1) * mux_progress_span)
            )
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
        self._set_dovi_mux_plan_for_mpls(mpls_path)
        dovi_video_opts = _svc_cls()._mkvmerge_dovi_primary_video_opts(
            mpls_path, getattr(self, '_dovi_mux_plan', None))
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
        chapter.get_pid_to_language()
        probe_m2ts, _mpls = _svc_cls()._probe_m2ts_for_remux_source(mpls_path)
        m2ts_file = probe_m2ts or ''
        config_key = media_track_key('main', mpls_path)
        copy_audio_track, copy_sub_track = self._select_tracks_for_source(
            probe_m2ts or mpls_path,
            chapter.pid_to_lang,
            config_key=config_key,
        )
        cmd_audio_track, cmd_sub_track = _svc_cls()._map_selected_tracks_to_mpls_track_ids(
            mpls_path, copy_audio_track, copy_sub_track
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
            default_audio_opts = (f'-a {",".join(cmd_audio_track)}' if cmd_audio_track else '')
            default_sub_opts = (f'-s {",".join(cmd_sub_track)}' if cmd_sub_track else '')
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            default_cmd = (
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} {dovi_video_opts} '
                f'--chapter-language eng -o "{output_file}" '
                f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip()
            # A main playlist owns one command; placeholders cover all output ranges for that playlist.
            custom_cmd = str(conf0.get('main_remux_cmd') or '').strip()
            remux_cmd = (
                custom_cmd.replace('{output_file}', output_file)
                .replace('{mpls_path}', mpls_path)
                .replace('{audio_opts}', default_audio_opts)
                .replace('{sub_opts}', default_sub_opts)
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
                pl: list[str] = []
                for s, e in segl:
                    st = get_time_str(_off(s))
                    ed = get_time_str(_off(e))
                    if st == '0':
                        st = '00:00:00.000'
                    if ed == '0':
                        ed = '00:00:00.000'
                    pl.append(f'{st}-{ed}')
                return ','.join(pl), csplit, use_parts

            parts_split, chapter_split, use_split_parts = _parts_chapter_for_sub_confs(confs)
            output_file = f'{os.path.join(disc_out_dir or dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
            default_audio_opts = (f'-a {",".join(cmd_audio_track)}' if cmd_audio_track else '')
            default_sub_opts = (f'-s {",".join(cmd_sub_track)}' if cmd_sub_track else '')
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            if use_split_parts:
                split_arg = (f'--split parts:{parts_split}' if parts_split else '')
            else:
                split_arg = (f'--split chapters:{chapter_split}' if chapter_split else '')
            default_cmd = (
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} {dovi_video_opts} {split_arg} '
                f'-o "{output_file}" {default_audio_opts} {default_sub_opts} {default_cover_opts} '
                f'"{mpls_path}"').strip()
            # A main playlist owns one command; split placeholders describe every selected episode range.
            custom_cmd = str(conf0.get('main_remux_cmd') or '').strip()
            remux_cmd = (
                custom_cmd.replace('{output_file}', output_file)
                .replace('{mpls_path}', mpls_path)
                .replace('{audio_opts}', default_audio_opts)
                .replace('{sub_opts}', default_sub_opts)
                .replace('{cover_opts}', default_cover_opts)
                .replace('{chapter_split}', chapter_split)
                .replace('{parts_split}', parts_split)
                if custom_cmd
                else default_cmd
            )
        remux_cmd = self._dedupe_remux_shell_lines(remux_cmd)
        return remux_cmd, m2ts_file, bdmv_vol, output_file, mpls_path, copy_audio_track, copy_sub_track

    def _remux_remap_chapter_skip_after_rename(self, mkv_files: list[str]) -> None:
        """Point ``_remux_chapter_skip_paths`` at post-rename paths when basename is unchanged."""
        try:
            old_sk = getattr(self, '_remux_chapter_skip_paths', None) or set()
            if not old_sk or not mkv_files:
                return
            by_bn = {
                os.path.normcase(os.path.basename(mf)): os.path.normcase(os.path.normpath(mf))
                for mf in mkv_files
            }
            repl: set[str] = set()
            for s in old_sk:
                bn = os.path.normcase(os.path.basename(str(s)))
                repl.add(by_bn.get(bn, os.path.normcase(os.path.normpath(str(s)))))
            self._remux_chapter_skip_paths = repl
        except Exception:
            pass

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
                    raise _Cancelled()
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
                        raise _Cancelled()
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
                        os.rename(expected_output, final_output)
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
        self.checked = request.complete_bluray_folder
        self.movie_mode = request.movie_mode
        self.sub_files = list(request.subtitle_files)
        self.episode_subtitle_languages = list(request.episode_subtitle_languages)
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
            raise _Cancelled()
        self._progress(385, 'Writing Chapters')
        self._post_remux_finalize_episodes(jobs, cancel_event)

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

        self._build_sp_outputs(
            sp_jobs,
            cancel_event=cancel_event,
            progress_cb=report_sp_output,
        )
        self._progress(900)
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
    ) -> None:
        """Encode every planned row through one shared execution path."""
        from src.runtime.services_split.encode_and_audio_tasks import encode_dovi_preflight_mkv_paths

        selected_sp_rows = [row for row in sp_rows if row.selected]
        # Remux-source outputs are durable checkpoints for multi-day Encode tasks.
        resume_existing_outputs = request.input_mode == 'remux'
        encode_sources = [
            row.source_path
            for row in main_rows
            if not (resume_existing_outputs and os.path.exists(row.output_path))
        ]
        encode_sources.extend(
            row.source_path
            for row in selected_sp_rows
            if (
                str(row.source_path).lower().endswith('.mkv')
                and not (resume_existing_outputs and os.path.exists(row.output_path))
            )
        )
        dolby_vision_error = encode_dovi_preflight_mkv_paths(
            encode_sources,
            request.settings.encoder,
            request.settings.bit_depth,
        )
        if dolby_vision_error:
            raise RuntimeError(dolby_vision_error)

        self.sub_files = [row.subtitle_path for row in main_rows]
        self.episode_subtitle_languages = [row.subtitle_language for row in main_rows]
        self.use_getnative = request.settings.use_getnative
        self.track_selection_config = copy.deepcopy(request.track_selection_config or {})
        self.track_language_config = copy.deepcopy(request.track_language_config or {})

        planned_output_paths = {
            os.path.normcase(os.path.abspath(row.output_path))
            for row in main_rows + selected_sp_rows
        }
        external_subtitles: list[tuple[str, str]] = []
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
                if os.path.exists(subtitle_destination) and not resume_existing_outputs:
                    raise FileExistsError(
                        translate_text('Output file already exists: {path}').format(
                            path=subtitle_destination
                        )
                    )
                planned_output_paths.add(normalized_destination)
                external_subtitles.append((row.subtitle_path, subtitle_destination))

        companion_files: list[tuple[str, str]] = []
        if companion_root and os.path.isdir(companion_root):
            root_path = os.path.abspath(os.path.normpath(companion_root))
            external_by_destination = {
                os.path.normcase(os.path.abspath(destination)): os.path.normcase(os.path.abspath(source))
                for source, destination in external_subtitles
            }
            for current_folder, _directories, filenames in os.walk(root_path):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                relative_folder = os.path.relpath(current_folder, root_path)
                for filename in filenames:
                    if filename.lower().endswith('.mkv'):
                        continue
                    source_path = os.path.join(current_folder, filename)
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
                    if os.path.exists(destination_path) and not resume_existing_outputs:
                        raise FileExistsError(
                            translate_text('Output file already exists: {path}').format(
                                path=destination_path
                            )
                        )
                    planned_output_paths.add(normalized_destination)
                    companion_files.append((source_path, destination_path))

        for planned_output_path in planned_output_paths:
            if os.path.exists(planned_output_path) and not resume_existing_outputs:
                raise FileExistsError(
                    translate_text('Output file already exists: {path}').format(
                        path=planned_output_path
                    )
                )
        os.makedirs(request.output_folder, exist_ok=True)
        total_rows = max(1, len(main_rows) + len(selected_sp_rows))
        completed_rows = 0

        for row in main_rows:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            self._progress(
                progress_base + int(completed_rows / total_rows * progress_span),
                self.t('Encoding {current}/{total}').format(
                    current=completed_rows + 1,
                    total=total_rows,
                ),
            )
            if os.path.exists(row.output_path):
                if resume_existing_outputs:
                    self._progress(
                        text=self.t('Skipping existing output: {path}').format(
                            path=row.output_path
                        )
                    )
                    completed_rows += 1
                    continue
                raise FileExistsError(
                    translate_text('Output file already exists: {path}').format(
                        path=row.output_path
                    )
                )
            os.makedirs(os.path.dirname(row.output_path), exist_ok=True)
            self.encode_task(
                row.output_path,
                row.vpy_path,
                request.settings.vspipe_mode,
                request.settings.encoder_mode,
                request.settings.encoder_parameters,
                request.settings.subtitle_mode,
                source_file=row.source_path,
                encoder=request.settings.encoder,
                bit_depth=request.settings.bit_depth,
                selected_audio_tracks=row.audio_tracks if request.input_mode == 'remux' else None,
                selected_subtitle_tracks=row.subtitle_tracks if request.input_mode == 'remux' else None,
                audio_codec_choices=row.audio_codec_choices,
                track_language_overrides=(
                    row.track_language_overrides
                    if request.input_mode == 'remux'
                    else ()
                ),
                subtitle_path=row.subtitle_path,
                subtitle_language=row.subtitle_language,
            )
            if not os.path.isfile(row.output_path):
                raise RuntimeError(
                    translate_text('Encode output is missing: {path}').format(
                        path=row.output_path
                    )
                )
            completed_rows += 1

        staged_main_sources = {
            os.path.normcase(os.path.abspath(row.source_path))
            for row in main_rows
        }
        for row in selected_sp_rows:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            self._progress(
                progress_base + int(completed_rows / total_rows * progress_span),
                self.t('Encoding {current}/{total}').format(
                    current=completed_rows + 1,
                    total=total_rows,
                ),
            )
            source_path = os.path.normpath(row.source_path)
            if os.path.normcase(os.path.abspath(source_path)) in staged_main_sources:
                # Episode-linked SP muxing has already modified this main source in the stage.
                completed_rows += 1
                continue
            if os.path.exists(row.output_path):
                if resume_existing_outputs:
                    self._progress(
                        text=self.t('Skipping existing output: {path}').format(
                            path=row.output_path
                        )
                    )
                    completed_rows += 1
                    continue
                raise FileExistsError(
                    translate_text('Output file already exists: {path}').format(
                        path=row.output_path
                    )
                )
            os.makedirs(os.path.dirname(row.output_path), exist_ok=True)
            if os.path.isdir(source_path):
                shutil.copytree(source_path, row.output_path)
            elif source_path.lower().endswith('.mka'):
                mux_with_audio_conversion(
                    source_path,
                    row.output_path,
                    selected_audio_tracks=row.audio_tracks if request.input_mode == 'remux' else None,
                    selected_subtitle_tracks=row.subtitle_tracks if request.input_mode == 'remux' else None,
                    audio_codec_choices=row.audio_codec_choices,
                    track_language_overrides=(
                        row.track_language_overrides
                        if request.input_mode == 'remux'
                        else ()
                    ),
                )
            elif source_path.lower().endswith('.mkv'):
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
                    selected_audio_tracks=row.audio_tracks if request.input_mode == 'remux' else None,
                    selected_subtitle_tracks=row.subtitle_tracks if request.input_mode == 'remux' else None,
                    audio_codec_choices=row.audio_codec_choices,
                    track_language_overrides=(
                        row.track_language_overrides
                        if request.input_mode == 'remux'
                        else ()
                    ),
                    subtitle_path=row.subtitle_path,
                    subtitle_language=row.subtitle_language,
                )
                if not os.path.isfile(row.output_path):
                    raise RuntimeError(
                        translate_text('Encode output is missing: {path}').format(
                            path=row.output_path
                        )
                    )
            else:
                shutil.copy2(source_path, row.output_path)
            completed_rows += 1

        if companion_files:
            self._progress(text=self.t('Copying companion files'))
            for source_path, destination_path in companion_files:
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                if os.path.exists(destination_path):
                    if resume_existing_outputs:
                        self._progress(
                            text=self.t('Skipping existing output: {path}').format(
                                path=destination_path
                            )
                        )
                        continue
                    raise FileExistsError(
                        translate_text('Output file already exists: {path}').format(
                            path=destination_path
                        )
                    )
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                shutil.copy2(source_path, destination_path)
        if external_subtitles:
            self._progress(text=self.t('Copying external subtitles'))
            for source_path, destination_path in external_subtitles:
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                if os.path.exists(destination_path):
                    if resume_existing_outputs:
                        self._progress(
                            text=self.t('Skipping existing output: {path}').format(
                                path=destination_path
                            )
                        )
                        continue
                    raise FileExistsError(
                        translate_text('Output file already exists: {path}').format(
                            path=destination_path
                        )
                    )
                shutil.copy2(source_path, destination_path)
        self._progress(progress_base + progress_span, 'Done')

    def episodes_encode(
            self,
            request: EncodeRequest,
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        """Run one complete Encode request without consulting GUI state."""
        self.checked = False
        self.movie_mode = request.movie_mode
        self.mux_dolby_vision = request.mux_dolby_vision

        if request.input_mode == 'remux':
            self._encode_mkv_rows(
                request,
                list(request.main_rows),
                list(request.sp_rows),
                cancel_event,
                companion_root=request.source_root,
            )
            return

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
            track_selection_config=copy.deepcopy(request.track_selection_config or {}),
            track_language_config=copy.deepcopy(request.track_language_config or {}),
            ensure_tools=False,
        )
        self.track_selection_config = copy.deepcopy(request.track_selection_config or {})
        self.track_language_config = copy.deepcopy(request.track_language_config or {})

        staging_parent_existed = os.path.isdir(request.staging_folder)
        staging_disc_folder = ''
        try:
            staging_disc_folder, main_jobs = self._prepare_remux_main_jobs(stage_request)
            sp_jobs = self._prepare_sp_jobs(
                sp_entries,
                staging_disc_folder,
                main_jobs,
                request.track_selection_config,
                request.track_language_config or {},
            )
            os.makedirs(staging_disc_folder, exist_ok=True)
            self._build_main_episode_mkvs(
                main_jobs,
                cancel_event=cancel_event,
                mux_progress_base=0,
                mux_progress_span=400,
            )
            self._progress(420, 'Writing Chapters')
            staged_main_files = self._post_remux_finalize_episodes(main_jobs, cancel_event)

            completed_sp_mux = 0

            def report_sp_mux(_entry_index: int, path: str) -> None:
                nonlocal completed_sp_mux
                completed_sp_mux += 1
                self._progress(
                    450 + int(completed_sp_mux / max(len(sp_jobs), 1) * 140),
                    self.t('Muxing SP {current}/{total}: {name}').format(
                        current=completed_sp_mux,
                        total=len(sp_jobs),
                        name=os.path.basename(path),
                    ),
                )

            created_sp_files = self._build_sp_outputs(
                sp_jobs,
                cancel_event=cancel_event,
                progress_cb=report_sp_mux,
            )
            staged_main_by_key = {
                configuration_key: staged_path
                for configuration_key, staged_path in zip(
                    sorted(configuration),
                    staged_main_files,
                )
            }
            linked_sp_audio_codecs: dict[str, list[str]] = {}
            for sp_row in request.sp_rows:
                if sp_row.selected and sp_row.uses_main_output:
                    output_key = os.path.normcase(os.path.abspath(sp_row.output_path))
                    linked_sp_audio_codecs.setdefault(output_key, []).extend(
                        sp_row.audio_codec_choices
                    )
            resolved_main_rows = [
                replace(
                    row,
                    source_path=staged_main_by_key[int(row.configuration_key)],
                    audio_codec_choices=(
                        row.audio_codec_choices
                        + tuple(linked_sp_audio_codecs.get(
                            os.path.normcase(os.path.abspath(row.output_path)),
                            (),
                        ))
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

            self._encode_mkv_rows(
                request,
                resolved_main_rows,
                resolved_sp_rows,
                cancel_event,
                progress_base=600,
                progress_span=400,
            )
        finally:
            if staging_disc_folder and os.path.isdir(staging_disc_folder):
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
