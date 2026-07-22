"""Auto-generated split target: remux_and_episode_workflows."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional

from PyQt6.QtWidgets import QTableWidget

from src.bdmv import Chapter
from src.core import find_mkvtoolnix, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.domain import MKV
from src.exports.utils import (
    get_index_to_m2ts_and_offset,
    get_time_str,
    force_remove_file,
    print_exc_terminal,
    run_shell_command_with_output,
)
from src.runtime.remux import RemuxMainJob, RemuxRequest
from .service_base import BluraySubtitleServiceBase
from ..services.cancelled import _Cancelled


def _svc_cls():
    from ..services.bluray_subtitle_entry import BluraySubtitle
    return BluraySubtitle


class RemuxEpisodeWorkflowsMixin(BluraySubtitleServiceBase):
    @staticmethod
    def _mkvmerge_exe() -> str:
        """Resolve mkvmerge executable path dynamically."""
        try:
            find_mkvtoolnix()
        except Exception:
            pass
        return core_settings.MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'

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

            jobs.append(RemuxMainJob(
                configuration_keys=tuple(matching_keys),
                configurations=tuple(configurations),
                bdmv_index=next(iter(bdmv_indexes)),
                command=command_lines[0],
                m2ts_file=m2ts_file,
                volume=volume,
                primary_output=os.path.normpath(
                    _svc_cls()._mkvmerge_output_path_from_cmd(command) or default_output
                ),
                mpls_path=mpls_path,
                audio_tracks=tuple(audio_tracks),
                subtitle_tracks=tuple(subtitle_tracks),
                expected_outputs=tuple(os.path.normpath(path) for path in expected_outputs),
                final_outputs=tuple(os.path.normpath(path) for path in final_outputs),
                track_language_overrides=tuple(
                    (str(track_index), str(language).strip())
                    for track_index, language in (
                        (request.track_language_config or {}).get(
                            f'main::{os.path.normpath(mpls_path)}', {}
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
                config_key = f'main::{os.path.normpath(job.mpls_path)}'
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
            if not primary_ok and clip_count == 1 and not split_output:
                self._progress(text=f'Mux fallback (single-clip aligned): BD_Vol_{job.volume}')
                if self._try_remux_mpls_single_clip_track_aligned(
                        job.mpls_path,
                        job.primary_output,
                        fallback_audio,
                        fallback_subtitle,
                        cancel_event=cancel_event,
                ):
                    primary_ok = all(os.path.isfile(path) for path in job.expected_outputs)
            if clip_count > 1 and not primary_ok:
                if split_output:
                    self._progress(text=f'Mux fallback (multi-episode split aligned): BD_Vol_{job.volume}')
                    self._try_remux_mpls_split_outputs_track_aligned(
                        job.mpls_path,
                        job.primary_output,
                        configurations,
                        fallback_audio,
                        fallback_subtitle,
                        cover,
                        cancel_event=cancel_event,
                    )
                    primary_ok = all(os.path.isfile(path) for path in job.expected_outputs)
                else:
                    self._progress(text=f'Mux fallback (multi-m2ts aligned): BD_Vol_{job.volume}')
                    self._try_remux_mpls_track_aligned_concat(
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

    def _run_shell_command(self, cmd: str) -> int:
        r, _ = self._run_shell_command_detailed(cmd)
        return int(r)

    def _run_single_command(self, cmd: str) -> int:
        if sys.platform != 'win32':
            cmd = self._fix_remux_shell_rm_glob(cmd)
        return run_shell_command_with_output(cmd)

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
        config_key = f'main::{os.path.normpath(mpls_path)}'
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
        mkvmerge_exe = self._mkvmerge_exe()
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
            index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)

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

        # Planning must finish before this task creates its first output directory.
        os.makedirs(dst_folder, exist_ok=True)
        self._build_main_episode_mkvs(jobs, cancel_event=cancel_event)
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        self._progress(385, 'Writing Chapters')
        mkv_files = self._post_remux_finalize_episodes(jobs, cancel_event)

        bdmv_index_conf: dict[int, list[dict[str, int | str]]] = {}
        for configuration in self.configuration.values():
            bdmv_index = int(configuration.get('bdmv_index') or 0)
            bdmv_index_conf.setdefault(bdmv_index, []).append(configuration)
        sp_entries = list(request.sp_entries)
        episode_output_names = list(request.episode_output_names)
        # 0–40 % (~0–400): main MPLS mux (in _build_main_episode_mkvs), rename, chapters, track languages.
        self._progress(400)

        # 40–50 % (~400–500): SP mux before main MKV lossless audio handling.
        # Outputs use paths under dst_folder (e.g. SPs/… in output_name); do not pre-create a dedicated SPs root.
        sp_output_base = dst_folder
        sp_mux_done = 0
        selected_sp_total = 0
        if sp_entries is not None:
            try:
                selected_sp_total = sum(
                    1 for e in sp_entries if bool(e.get('selected', True)) and str(e.get('output_name') or '').strip()
                )
            except Exception:
                selected_sp_total = 0

        def _progress_sp_mux(item_name: str):
            nonlocal sp_mux_done
            sp_mux_done += 1
            known_total = max(selected_sp_total, 1) if selected_sp_total > 0 else 0
            denom = known_total if known_total else 40
            frac = min(sp_mux_done, denom) / float(max(denom, 1))
            p = 400 + min(99, int(100 * frac))
            if known_total:
                self._progress(p, f'Muxing SP {sp_mux_done}/{known_total}: {item_name}')
            else:
                self._progress(p, f'Muxing SP {sp_mux_done}: {item_name}')

        if sp_entries is not None:
            self._create_sp_mkvs_from_entries(
                bdmv_index_conf,
                sp_entries,
                sp_output_base,
                cancel_event=cancel_event,
                progress_cb=lambda _idx, path: _progress_sp_mux(os.path.basename(path)),
                dst_folder=dst_folder,
                episode_output_names=list(episode_output_names or []),
                configuration_full=dict(self.configuration or {}),
            )
        else:
            single_volume = bool(getattr(self, 'movie_mode', False) and len(bdmv_index_conf) == 1)
            for bdmv_index in sorted(bdmv_index_conf.keys()):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                confs = bdmv_index_conf[bdmv_index]
                bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
                mpls_path = confs[0]['selected_mpls'] + '.mpls'
                index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_path))
                main_m2ts_files = set(index_to_m2ts.values())
                parsed_m2ts_files = set(main_m2ts_files)
                sp_index = 0
                for mpls_file in sorted(os.listdir(os.path.dirname(mpls_path))):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if not mpls_file.endswith('.mpls'):
                        continue
                    mpls_file_path = os.path.join(os.path.dirname(mpls_path), mpls_file)
                    if mpls_file_path != mpls_path:
                        index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_file_path))
                        if set(index_to_m2ts.values()).issubset(main_m2ts_files):
                            continue
                        if len(index_to_m2ts) > 1:
                            sp_index += 1
                            out_name = (f'SP0{sp_index}.mkv'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_SP0{sp_index}.mkv')
                            entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': '',
                                     'output_name': out_name}
                            key = _svc_cls()._sp_track_key_from_entry(entry)
                            copy_audio_track, copy_sub_track = self._select_tracks_for_source(mpls_file_path, {}, key)
                            cmd_audio_track, cmd_sub_track = _svc_cls()._map_selected_tracks_to_mpls_track_ids(
                                mpls_file_path, copy_audio_track, copy_sub_track
                            )
                            chapter_txt = os.path.join(dst_folder, 'SPs', f'{os.path.splitext(out_name)[0]}.chapter.txt')
                            try:
                                offs = self._write_chapter_txt_from_mpls(mpls_file_path, chapter_txt)
                                if len(offs) == 1 and offs[0] == 0.0:
                                    force_remove_file(chapter_txt)
                                    print(
                                        f'{self.t("[chapter-debug] ")}{self.t("remove trivial SP chapter file: ")}{chapter_txt}')
                                    chapter_txt = ''
                            except Exception:
                                print_exc_terminal()
                                chapter_txt = ''
                            if chapter_txt:
                                print(
                                    f'{self.t("[chapter-debug] ")}{self.t("legacy SP remux with chapter file: ")}{chapter_txt} -> {out_name}')
                            run_shell_command_with_output(
                                f'"{self._mkvmerge_exe()}" {mkvtoolnix_ui_language_arg()} '
                                f'{("--chapters " + "\"" + chapter_txt + "\"") if chapter_txt else ""} '
                                f'-o "{os.path.join(dst_folder, "SPs", out_name)}" '
                                f'{("-a " + ",".join(cmd_audio_track)) if cmd_audio_track else ""} '
                                f'{("-s " + ",".join(cmd_sub_track)) if cmd_sub_track else ""} '
                                f'"{mpls_file_path}"',
                            )
                            _progress_sp_mux(out_name)
                            if chapter_txt:
                                try:
                                    force_remove_file(chapter_txt)
                                    print(
                                        f'{self.t("[chapter-debug] ")}{self.t("remove temporary chapter file: ")}{chapter_txt}')
                                except Exception:
                                    pass
                            parsed_m2ts_files |= set(index_to_m2ts.values())
                stream_folder = os.path.dirname(mpls_path).replace('PLAYLIST', '') + 'STREAM'
                for stream_file in sorted(os.listdir(stream_folder)):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if stream_file not in parsed_m2ts_files and stream_file.endswith('.m2ts'):
                        if _svc_cls()._m2ts_duration_90k(os.path.join(stream_folder, stream_file)) > 30 * 90000:
                            src_stream = os.path.join(stream_folder, stream_file)
                            ext = '.mka' if _svc_cls()._is_audio_only_media(src_stream) else '.mkv'
                            out_name = (f'{stream_file[:-5]}{ext}'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_{stream_file[:-5]}{ext}')
                            entry = {'bdmv_index': bdmv_index, 'mpls_file': '', 'm2ts_file': stream_file,
                                     'output_name': out_name}
                            key = _svc_cls()._sp_track_key_from_entry(entry)
                            copy_audio_track, copy_sub_track = self._select_tracks_for_source(
                                os.path.join(stream_folder, stream_file), {}, key
                            )
                            subprocess.Popen(
                                f'"{self._mkvmerge_exe()}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(dst_folder, "SPs", out_name)}" '
                                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                                shell=True
                            ).wait()
                            _progress_sp_mux(out_name)

        self._progress(500)

        # 50–90 % (~500–900): main MPLS MKV audio (lossless extract / re-mux, etc.).
        i = 0
        n_main = max(len(mkv_files), 1)
        for mkv_file in mkv_files:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            i += 1
            self._progress(text=f'Compressing audio: {os.path.basename(mkv_file)}')
            self.flac_task(mkv_file, dst_folder, i)
            self._progress(500 + int(400 * i / n_main))
        if not mkv_files:
            self._progress(900)

        # 90–100 % (~900–1000): SP audio (files under dst_folder/SPs when present).
        sp_subdir = os.path.join(dst_folder, 'SPs')
        sp_files = (
            [sp for sp in os.listdir(sp_subdir) if sp.lower().endswith(('.mkv', '.mka'))]
            if os.path.isdir(sp_subdir) else []
        )
        sp_files.sort()
        total_sp = len(sp_files) or 1
        self._progress(900, 'Processing SP audio tracks')
        for idx, sp in enumerate(sp_files, start=1):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            self._progress(900 + int(100 * idx / total_sp), f'Processing SP audio tracks {idx}/{total_sp}: {sp}')
            self.flac_task(os.path.join(sp_subdir, sp), dst_folder, -1)

        self.completion()
        self._progress(1000, 'Done')

    def episodes_encode(self, table: Optional[QTableWidget], folder_path: str,
                        selected_mpls: Optional[list[tuple[str, str]]] = None,
                        configuration: Optional[dict[int, dict[str, int | str]]] = None,
                        cancel_event: Optional[threading.Event] = None,
                        ensure_tools: bool = True,
                        vpy_paths: Optional[list[str]] = None,
                        sp_vpy_paths: Optional[list[str]] = None,
                        sp_entries: Optional[list[dict[str, int | str]]] = None,
                        episode_output_names: Optional[list[str]] = None,
                        episode_subtitle_languages: Optional[list[str]] = None,
                        vspipe_mode: str = 'bundle',
                        x265_mode: str = 'bundle',
                        x265_params: str = '',
                        sub_pack_mode: str = 'external',
                        encode_tool: str = 'x265',
                        encode_bit_depth: str = '10'):
        """BDMV encode: remux (main + SP) under ``<out>/_encode_remux_stage/<disc>/``; encode writes to ``<out>/<disc>/``.

        Remux stays in the stage folder. ``EncodeMkvFolderWorker`` outputs directly to the final disc folder
        (main episode MKVs first, then ``SPs/``); no post-encode folder migration.
        """
        from ..gui_runtime_classes.encode_mkv_folder_worker import EncodeMkvFolderWorker

        vpy_paths = vpy_paths or []
        sp_vpy_paths = sp_vpy_paths or []
        episode_output_names = list(episode_output_names or [])
        episode_subtitle_languages = list(episode_subtitle_languages or [])
        default_vpy = os.path.join(os.getcwd(), 'vpy.vpy')

        def bridge_encode_folder(value: Optional[int] = None, text: Optional[str] = None) -> None:
            """Mux uses 0–1000; encode uses a separate 0–1000 on the same UI bar."""
            if value is not None:
                vv = max(0, min(1000, int(value)))
                self._progress(vv, text)
            elif text is not None:
                self._progress(text=text)

        base_out = os.path.normpath(folder_path)
        stage_parent = os.path.join(base_out, '_encode_remux_stage')
        selected_for_stage = list(selected_mpls or [])
        if not selected_for_stage:
            seen_stage_mpls: set[str] = set()
            for conf in (configuration or {}).values():
                mpls_path = _svc_cls()._resolve_mpls_path_from_conf(conf, self.bdmv_path)
                normalized_mpls = os.path.normcase(os.path.abspath(mpls_path))
                if normalized_mpls in seen_stage_mpls:
                    continue
                seen_stage_mpls.add(normalized_mpls)
                selected_for_stage.append((str(conf.get('folder') or self.bdmv_path), os.path.splitext(mpls_path)[0]))
        stage_request = RemuxRequest(
            bdmv_path=os.path.normpath(self.bdmv_path),
            subtitle_files=tuple(self.sub_files or []),
            complete_bluray_folder=bool(self.checked),
            output_folder=stage_parent,
            configuration=dict(configuration or {}),
            selected_mpls=tuple(selected_for_stage),
            sp_entries=tuple(sp_entries or []),
            episode_output_names=tuple(episode_output_names),
            episode_subtitle_languages=tuple(episode_subtitle_languages),
            movie_mode=bool(getattr(self, 'movie_mode', False)),
            mux_dolby_vision=bool(getattr(self, 'mux_dolby_vision', True)),
            track_selection_config=dict(getattr(self, 'track_selection_config', {}) or {}),
            track_language_config=dict(getattr(self, 'track_language_config', {}) or {}),
            track_lossless_audio_config=dict(getattr(self, 'track_lossless_audio_config', {}) or {}),
            default_lossless_audio_codec=str(
                getattr(self, 'default_lossless_audio_codec', 'flac') or 'flac'
            ),
            ensure_tools=ensure_tools,
        )
        dst_stage, main_jobs = self._prepare_remux_main_jobs(stage_request)
        os.makedirs(dst_stage, exist_ok=True)
        bdmv_index_conf: dict[int, list[dict[str, int | str]]] = {}
        for conf in self.configuration.values():
            bdmv_index_conf.setdefault(int(conf.get('bdmv_index') or 0), []).append(conf)
        final_disc = os.path.join(base_out, os.path.basename(self.bdmv_path))

        self._build_main_episode_mkvs(
            main_jobs,
            cancel_event=cancel_event,
            mux_progress_base=0,
            mux_progress_span=720,
        )

        self.checked = True
        self.episode_subtitle_languages = episode_subtitle_languages
        mkv_raw = [path for job in main_jobs for path in job.expected_outputs]
        mkv_files = self._apply_episode_output_names(mkv_raw, episode_output_names)
        self._remux_remap_chapter_skip_after_rename(mkv_files)
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        if not getattr(self, 'movie_mode', False):
            self._progress(760, 'Writing Chapters')
            self.add_chapter_to_mkv(
                mkv_files, table, selected_mpls=selected_mpls, cancel_event=cancel_event,
                configuration=self.configuration,
            )
        self._progress(800)

        sp_output_base = dst_stage
        sp_mux_done = 0
        selected_sp_total = 0
        if sp_entries is not None:
            try:
                selected_sp_total = sum(
                    1 for e in sp_entries if bool(e.get('selected', True)) and str(e.get('output_name') or '').strip()
                )
            except Exception:
                selected_sp_total = 0

        def _progress_sp_mux_enc(item_name: str):
            nonlocal sp_mux_done
            sp_mux_done += 1
            known_total = max(selected_sp_total, 1) if selected_sp_total > 0 else 0
            denom = known_total if known_total else 40
            frac = min(sp_mux_done, denom) / float(max(denom, 1))
            p = 800 + min(199, int(200 * frac))
            if known_total:
                self._progress(p, f'Muxing SP {sp_mux_done}/{known_total}: {item_name}')
            else:
                self._progress(p, f'Muxing SP {sp_mux_done}: {item_name}')

        created_sp: list[tuple[int, str]] = []
        if sp_entries is not None:
            created_sp = self._create_sp_mkvs_from_entries(
                bdmv_index_conf,
                sp_entries,
                sp_output_base,
                cancel_event=cancel_event,
                progress_cb=lambda _i, path: _progress_sp_mux_enc(os.path.basename(path)),
                dst_folder=dst_stage,
                episode_output_names=list(episode_output_names or []),
                configuration_full=dict(self.configuration or {}),
            )
        else:
            single_volume = bool(getattr(self, 'movie_mode', False) and len(bdmv_index_conf) == 1)
            for bdmv_index, confs in bdmv_index_conf.items():
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
                mpls_path = confs[0]['selected_mpls'] + '.mpls'
                index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_path))
                main_m2ts_files = set(index_to_m2ts.values())
                parsed_m2ts_files = set(main_m2ts_files)
                sp_index = 0
                for mpls_file in os.listdir(os.path.dirname(mpls_path)):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if not mpls_file.endswith('.mpls'):
                        continue
                    mpls_file_path = os.path.join(os.path.dirname(mpls_path), mpls_file)
                    if mpls_file_path != mpls_path:
                        index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(Chapter(mpls_file_path))
                        if set(index_to_m2ts.values()).issubset(main_m2ts_files):
                            continue
                        if len(index_to_m2ts) > 1:
                            sp_index += 1
                            out_name = (f'SP0{sp_index}.mkv'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_SP0{sp_index}.mkv')
                            entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': '',
                                     'output_name': out_name}
                            key = _svc_cls()._sp_track_key_from_entry(entry)
                            copy_audio_track, copy_sub_track = self._select_tracks_for_source(mpls_file_path, {}, key)
                            cmd_audio_track, cmd_sub_track = _svc_cls()._map_selected_tracks_to_mpls_track_ids(
                                mpls_file_path, copy_audio_track, copy_sub_track
                            )
                            chapter_txt = os.path.join(dst_stage, 'SPs', f'{os.path.splitext(out_name)[0]}.chapter.txt')
                            try:
                                offs = self._write_chapter_txt_from_mpls(mpls_file_path, chapter_txt)
                                if len(offs) == 1 and offs[0] == 0.0:
                                    force_remove_file(chapter_txt)
                                    print(
                                        f'{self.t("[chapter-debug] ")}{self.t("remove trivial SP chapter file: ")}{chapter_txt}')
                                    chapter_txt = ''
                            except Exception:
                                print_exc_terminal()
                                chapter_txt = ''
                            if chapter_txt:
                                print(
                                    f'{self.t("[chapter-debug] ")}{self.t("legacy SP remux with chapter file: ")}{chapter_txt} -> {out_name}')
                            run_shell_command_with_output(
                                f'"{self._mkvmerge_exe()}" {mkvtoolnix_ui_language_arg()} '
                                f'{("--chapters " + "\"" + chapter_txt + "\"") if chapter_txt else ""} '
                                f'-o "{os.path.join(dst_stage, "SPs", out_name)}" '
                                f'{("-a " + ",".join(cmd_audio_track)) if cmd_audio_track else ""} '
                                f'{("-s " + ",".join(cmd_sub_track)) if cmd_sub_track else ""} '
                                f'"{mpls_file_path}"',
                            )
                            _progress_sp_mux_enc(out_name)
                            if chapter_txt:
                                try:
                                    force_remove_file(chapter_txt)
                                    print(
                                        f'{self.t("[chapter-debug] ")}{self.t("remove temporary chapter file: ")}{chapter_txt}')
                                except Exception:
                                    pass
                            parsed_m2ts_files |= set(index_to_m2ts.values())
                stream_folder = os.path.dirname(mpls_path).replace('PLAYLIST', '') + 'STREAM'
                for stream_file in os.listdir(stream_folder):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if stream_file not in parsed_m2ts_files and stream_file.endswith('.m2ts'):
                        if _svc_cls()._m2ts_duration_90k(os.path.join(stream_folder, stream_file)) > 30 * 90000:
                            src_stream = os.path.join(stream_folder, stream_file)
                            ext = '.mka' if _svc_cls()._is_audio_only_media(src_stream) else '.mkv'
                            out_name = (f'{stream_file[:-5]}{ext}'
                                        if single_volume else f'BD_Vol_{bdmv_vol}_{stream_file[:-5]}{ext}')
                            entry = {'bdmv_index': bdmv_index, 'mpls_file': '', 'm2ts_file': stream_file,
                                     'output_name': out_name}
                            key = _svc_cls()._sp_track_key_from_entry(entry)
                            copy_audio_track, copy_sub_track = self._select_tracks_for_source(
                                os.path.join(stream_folder, stream_file), {}, key
                            )
                            run_shell_command_with_output(
                                f'"{self._mkvmerge_exe()}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(dst_stage, "SPs", out_name)}" '
                                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                            )
                            _progress_sp_mux_enc(out_name)

        self._progress(1000)

        mkv_rows: list[dict[str, str]] = []
        for i, mkv_file in enumerate(mkv_files):
            oname = episode_output_names[i] if i < len(episode_output_names) else os.path.basename(mkv_file)
            mkv_rows.append({
                'src_path': mkv_file,
                'output_name': oname,
                'sub_path': self.sub_files[i] if self.sub_files and i < len(self.sub_files) else '',
                'language': episode_subtitle_languages[i] if i < len(episode_subtitle_languages) else '',
                'vpy_path': vpy_paths[i] if i < len(vpy_paths) else default_vpy,
            })

        sp_rows: list[dict[str, str]] = []
        if created_sp:
            for entry_idx, sp_mkv_path in created_sp:
                if os.path.isdir(sp_mkv_path) or (not os.path.exists(sp_mkv_path)):
                    continue
                cur_sp_vpy = (
                    str(sp_vpy_paths[entry_idx - 1])
                    if sp_vpy_paths and 0 <= entry_idx - 1 < len(sp_vpy_paths) and sp_vpy_paths[entry_idx - 1]
                    else default_vpy
                )
                sp_rows.append({
                    'src_path': sp_mkv_path,
                    'output_name': os.path.basename(sp_mkv_path),
                    'vpy_path': cur_sp_vpy,
                })
        else:
            legacy_sp_dir = os.path.join(dst_stage, 'SPs')
            sp_files_list = sorted(
                f for f in os.listdir(legacy_sp_dir) if f.lower().endswith(('.mkv', '.mka'))
            ) if os.path.isdir(legacy_sp_dir) else []
            for idx, fn in enumerate(sp_files_list):
                sp_rows.append({
                    'src_path': os.path.join(legacy_sp_dir, fn),
                    'output_name': fn,
                    'vpy_path': sp_vpy_paths[idx] if idx < len(sp_vpy_paths) else default_vpy,
                })

        worker = EncodeMkvFolderWorker(
            mkv_rows=mkv_rows,
            sp_rows=sp_rows,
            remux_folder=dst_stage,
            output_folder=final_disc,
            cancel_event=cancel_event,
            vspipe_mode=vspipe_mode,
            x265_mode=x265_mode,
            x265_params=x265_params,
            sub_pack_mode=sub_pack_mode,
            encode_tool=encode_tool,
            encode_bit_depth=encode_bit_depth,
            use_getnative=bool(getattr(self, 'use_getnative', True)),
            track_selection_config=getattr(self, 'track_selection_config', {}) or {},
            track_language_config=getattr(self, 'track_language_config', {}) or {},
            track_lossless_audio_config=getattr(self, 'track_lossless_audio_config', {}) or {},
            default_lossless_audio_codec=str(getattr(self, 'default_lossless_audio_codec', '') or 'flac'),
            progress_bridge=bridge_encode_folder,
        )
        worker.run()

        if sub_pack_mode == 'external' and self.sub_files:
            for i, row in enumerate(mkv_rows):
                if i >= len(self.sub_files):
                    break
                sub_src = self.sub_files[i]
                sub_ext = os.path.splitext(sub_src)[1].lower()
                if sub_ext not in ('.ass', '.ssa', '.srt'):
                    continue
                out_nm = str(row.get('output_name') or '').strip()
                video_base = os.path.splitext(os.path.basename(out_nm))[0]
                sub_dst = os.path.join(final_disc, video_base + sub_ext)
                try:
                    shutil.copy2(sub_src, sub_dst)
                except Exception:
                    print_exc_terminal()

        try:
            shutil.rmtree(stage_parent, ignore_errors=True)
        except Exception:
            pass

        self.completion()
        self._progress(1000, 'Done')

    def _remux_exclude_audio_track_ids(
            self,
            mkv_file: str,
            track_info: dict[int, str],
            track_flac_map: dict[int, str],
            *,
            drop_all_source_audio: bool = False,
    ) -> list[int]:
        """mkvmerge ``-a !`` track IDs (from ``mkvmerge --identify``, not ffprobe index)."""
        from .media_info_and_track_mapping import MediaInfoTrackMappingMixin as _mit
        exclude: set[int] = set()
        if drop_all_source_audio:
            exclude.update(_mit._mkvmerge_track_ids_by_type(mkv_file, 'audio'))
        for tid in (getattr(self, '_audio_tracks_to_exclude', None) or set()):
            try:
                exclude.add(int(tid))
            except Exception:
                pass
        for tid in track_info:
            src = track_flac_map.get(tid)
            if src and os.path.isfile(str(src)):
                exclude.add(int(tid))
        if not drop_all_source_audio and exclude:
            mkv_audio = set(_mit._mkvmerge_track_ids_by_type(mkv_file, 'audio'))
            mkv_video = set(_mit._mkvmerge_track_ids_by_type(mkv_file, 'video'))
            if 0 in exclude and 0 in mkv_video and mkv_audio:
                exclude.discard(0)
                exclude.add(min(mkv_audio))
        for vid in _mit._mkvmerge_track_ids_by_type(mkv_file, 'video'):
            exclude.discard(int(vid))
        return sorted(exclude)

    def generate_remux_cmd(self, track_count, track_info, flac_files, output_file, mkv_file,
                           encoded_video_file: Optional[str] = None):
        from .media_info_and_track_mapping import MediaInfoTrackMappingMixin as _mit
        mkvmerge_exe = self._mkvmerge_exe()
        copy_audio_track = list(getattr(self, '_active_copy_audio_track', []) or [])
        copy_sub_track = list(getattr(self, '_active_copy_sub_track', []) or [])
        track_flac_map = getattr(self, '_track_flac_map', {}) or {}
        track_mux_sync_ms = getattr(self, '_track_mux_sync_ms', {}) or {}
        has_external_audio = any(
            track_flac_map.get(tid) and os.path.isfile(str(track_flac_map.get(tid)))
            for tid in track_info
        )
        drop_all_src_audio = bool(encoded_video_file and has_external_audio)
        exclude_audio_ids = self._remux_exclude_audio_track_ids(
            mkv_file, track_info, track_flac_map, drop_all_source_audio=drop_all_src_audio,
        )
        mkv_video_ids = set(_mit._mkvmerge_track_ids_by_type(mkv_file, 'video'))
        mkv_audio_ids = set(_mit._mkvmerge_track_ids_by_type(mkv_file, 'audio'))
        video_tracks = (
            '!' + ','.join(str(x) for x in sorted(mkv_video_ids))
        ) if mkv_video_ids else ''
        audio_tracks = ('!' + ','.join(str(x) for x in exclude_audio_ids)) if exclude_audio_ids else ''
        video_order = [f'0:{v}' for v in sorted(mkv_video_ids)]
        ext_order: list[str] = []
        mkv_order: list[str] = []
        pcm_track_count = 0
        language_options = []
        for _ in range(track_count + 1):
            if _ in mkv_video_ids:
                continue
            if _ in track_info:
                flac_src = track_flac_map.get(_)
                if not flac_src or not os.path.isfile(str(flac_src)):
                    if _ not in mkv_audio_ids:
                        mkv_order.append(f'0:{_}')
                    continue
                pcm_track_count += 1
                lang_opt = f'--language 0:{track_info[_]}'
                try:
                    sync_ms = int(track_mux_sync_ms.get(int(_)))
                except Exception:
                    sync_ms = 0
                sync_opt = f'-y 0:{sync_ms}' if sync_ms else ''
                language_options.append(f'{lang_opt} {sync_opt} "{flac_src}"'.strip())
                ext_order.append(f'{pcm_track_count}:0')
                continue
            if _ in exclude_audio_ids or _ in mkv_audio_ids:
                continue
            mkv_order.append(f'0:{_}')
        language_options = ' '.join(language_options)
        if not encoded_video_file:
            tracker_order = ','.join(video_order + ext_order + mkv_order)
            cmd = (
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                f'{"-a " + audio_tracks if audio_tracks else ""} "{mkv_file}" {language_options}')
        else:
            video_in = pcm_track_count + 1
            tracker_order = ','.join([f'{video_in}:0'] + ext_order + mkv_order)
            d_flag = f'-d {video_tracks} ' if video_tracks else ''
            cmd = (
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                f'{d_flag}{"-a " + audio_tracks if audio_tracks else ""} "{mkv_file}" {language_options} "{encoded_video_file}"')
        print(
            f'[encode-mux] exclude audio={exclude_audio_ids} video={sorted(mkv_video_ids)} '
            f'-d {video_tracks or "(none)"} track-order={tracker_order}',
            flush=True,
        )
        return cmd
