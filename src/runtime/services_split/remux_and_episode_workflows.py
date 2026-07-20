"""Auto-generated split target: remux_and_episode_workflows."""
import os
import re
import shutil
import subprocess
import sys
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

    def _prepare_episode_run(
            self,
            folder_path: str,
            configuration: Optional[dict[int, dict[str, int | str]]],
            ensure_tools: bool,
    ) -> tuple[str, set[str], dict[int, list[dict[str, int | str]]]]:
        if configuration is None:
            raise ValueError(translate_text('Task configuration is required'))
        if not configuration:
            raise ValueError(translate_text('Task configuration is empty'))
        self.configuration = configuration

        bdmv_index_conf: dict[int, list[dict[str, int | str]]] = {}
        for row_number, conf in enumerate(self.configuration.values(), start=1):
            try:
                start_chapter = int(
                    conf.get('start_at_chapter')
                    or conf.get('chapter_index')
                    or 0
                )
                end_chapter = int(conf.get('end_at_chapter') or 0)
                bdmv_index = int(conf['bdmv_index'])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    translate_text('Invalid task configuration in row {row}').format(
                        row=row_number,
                    )
                ) from error
            if end_chapter > 0 and start_chapter >= end_chapter:
                raise ValueError(
                    translate_text(
                        'End chapter must be greater than start chapter in row {row}'
                    ).format(row=row_number)
                )
            bdmv_index_conf.setdefault(bdmv_index, []).append(conf)

        dst_folder = os.path.join(folder_path, os.path.basename(self.bdmv_path))
        if not os.path.exists(dst_folder):
            os.mkdir(dst_folder)

        try:
            mkv_files_before = {f for f in os.listdir(dst_folder) if f.lower().endswith(('.mkv', '.mka'))}
        except Exception:
            mkv_files_before = set()

        if ensure_tools:
            find_mkvtoolnix()

        return dst_folder, mkv_files_before, bdmv_index_conf

    def _collect_target_mkv_files(self, dst_folder: str, mkv_files_before: set[str]) -> list[str]:
        try:
            mkv_files_after = [f for f in os.listdir(dst_folder) if f.lower().endswith(('.mkv', '.mka'))]
        except Exception:
            mkv_files_after = []
        created = [os.path.join(dst_folder, f) for f in mkv_files_after if f not in mkv_files_before]
        if created:
            return sorted(created, key=self._mkv_sort_key)
        return sorted([os.path.join(dst_folder, f) for f in mkv_files_after], key=self._mkv_sort_key)

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
            bdmv_index_conf: dict[int, list[dict[str, int | str]]],
            dst_folder: str,
            cancel_event: Optional[threading.Event] = None,
            *,
            mux_progress_base: int = 0,
            mux_progress_span: int = 380,
    ) -> None:
        self._remux_chapter_skip_paths = set()
        bdmv_index_list = sorted(bdmv_index_conf.keys())
        for idx, bdmv_index in enumerate(bdmv_index_list, start=1):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            confs = list(bdmv_index_conf[bdmv_index])
            try:
                confs = sorted(
                    confs,
                    key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 1),
                )
            except Exception:
                pass
            remux_cmd, m2ts_file, bdmv_vol, output_file, mpls_path, pid_to_lang, copy_audio_track, copy_sub_track = self._make_main_mpls_remux_cmd(
                confs=confs,
                dst_folder=dst_folder,
                bdmv_index=bdmv_index,
                disc_count=len(bdmv_index_conf),
                ensure_disc_out_dir=True,
            )
            if mpls_path:
                config_key = f'main::{os.path.normpath(mpls_path)}'
                tracks_cfg = getattr(self, 'track_selection_config', {}) or {}
                if config_key in tracks_cfg:
                    cfg = tracks_cfg.get(config_key) or {}
                    na = len(cfg.get('audio') or [])
                    ns = len(cfg.get('subtitle') or [])
                    ref = os.path.basename(m2ts_file) if m2ts_file else ''
                    msg = (
                        f'{self.t("使用 edit-tracks 选轨，主 MPLS")} '
                        f'[{os.path.basename(mpls_path)}]: {na} audio, {ns} subtitle'
                    )
                    if ref:
                        msg += f' {self.t("（参考 m2ts: ")}{ref})'
                    print(msg)
                    self._progress(text=msg)
                else:
                    ref = os.path.basename(m2ts_file) if m2ts_file else ''
                    msg = (
                        f'{self.t("默认选轨，主 MPLS")} '
                        f'[{os.path.basename(mpls_path)}]'
                    )
                    if ref:
                        msg += f' {self.t("（参考 m2ts: ")}{ref})'
                    print(msg)
                    self._progress(text=msg)
            self._set_dovi_mux_plan_for_mpls(mpls_path)
            identify_ok = self._mkvmerge_identify_covers_remux_slots(
                mpls_path, copy_audio_track, copy_sub_track)
            if not identify_ok:
                print('[remux-fallback] skipping primary mkvmerge (see identify check lines above)')
            print(f'{self.t("Mux command: ")}{remux_cmd}')
            self._progress(text=f'{self.t("Muxing: ")}BD_Vol_{bdmv_vol}')
            if identify_ok:
                ret, line_rets = self._run_shell_command_detailed(remux_cmd)
            else:
                ret, line_rets = -1, [-1]
            try:
                ch_tmp = Chapter(mpls_path)
                n_clips = len(ch_tmp.in_out_time or [])
            except Exception:
                n_clips = 0
            cover = ''
            if n_clips > 1:
                try:
                    bdmv_dir = os.path.normpath(os.path.join(os.path.dirname(mpls_path), '..'))
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
            def _norm_skip(p: str) -> str:
                return os.path.normcase(os.path.normpath(p))

            out_n = os.path.normpath(output_file) if output_file else ''
            try:
                parsed_out = _svc_cls()._mkvmerge_output_path_from_cmd(remux_cmd)
                if parsed_out:
                    out_n = os.path.normpath(parsed_out)
            except Exception:
                pass
            out_exists = bool(out_n and os.path.isfile(out_n))
            expected_split_paths: list[str] = []
            lines_mx = _svc_cls()._remux_cmd_shell_lines(remux_cmd)
            if not lines_mx and (remux_cmd or '').strip():
                lines_mx = [(remux_cmd or '').strip()]
            if not line_rets:
                line_rets = [int(ret)]
            while len(line_rets) < len(lines_mx):
                line_rets.append(int(line_rets[-1]))
            line_rets = [int(x) for x in line_rets[:len(lines_mx)]] if lines_mx else line_rets
            ret_ok = (ret in (0, 1))
            primary_ok = True
            split_by_config = False
            line_mux_checks: list[dict[str, object]] = []
            if (not getattr(self, 'movie_mode', False)) and lines_mx and confs:
                for li, ln in enumerate(lines_mx):
                    rline = int(line_rets[li]) if li < len(line_rets) else int(ret)
                    rline_ok = rline in (0, 1)
                    ob, expected_line = _svc_cls()._mkvmerge_expected_paths_for_shell_line(
                        ln, confs, mpls_path)
                    if not expected_line:
                        continue
                    split_by_config = split_by_config or len(expected_line) > 1
                    exists_map_ln = {p: os.path.isfile(p) for p in expected_line}
                    ok_ln = rline_ok and all(exists_map_ln.values())
                    if (not ok_ln) and rline_ok and expected_line:
                        for retry_i in range(5):
                            time.sleep(0.2)
                            exists_map_ln = {p: os.path.isfile(p) for p in expected_line}
                            if all(exists_map_ln.values()):
                                ok_ln = True
                                break
                    line_mux_checks.append({
                        'expected': list(expected_line),
                        'ok': ok_ln,
                        'ret': rline,
                    })
                    if not ok_ln:
                        for p in expected_line:
                            self._remux_chapter_skip_paths.add(_norm_skip(p))
                    primary_ok = primary_ok and ok_ln
                if line_mux_checks:
                    expected_split_paths = []
                    for c in line_mux_checks:
                        expected_split_paths.extend(c['expected'])  # type: ignore[arg-type]
            if not line_mux_checks and (not getattr(self, 'movie_mode', False)) and out_n and confs:
                try:
                    ch_seg = Chapter(mpls_path)
                    segs_b = _svc_cls()._series_episode_segments_bounds(ch_seg, confs)
                    expected_split_paths = _svc_cls()._expected_mkvmerge_split_output_paths(out_n, len(segs_b))
                except Exception:
                    expected_split_paths = []
                try:
                    cmd_split_count = _svc_cls()._split_segment_count_from_mkvmerge_cmd(remux_cmd)
                except Exception:
                    cmd_split_count = None
                if out_n and isinstance(cmd_split_count, int) and cmd_split_count > 1:
                    expected_from_cmd = _svc_cls()._expected_mkvmerge_split_output_paths(out_n, cmd_split_count)
                    if len(expected_from_cmd) >= len(expected_split_paths):
                        expected_split_paths = expected_from_cmd
                split_by_config = len(expected_split_paths) > 1
                stem_base, ext_base = os.path.splitext(os.path.basename(out_n)) if out_n else ('', '.mkv')
                alt001 = os.path.join(os.path.dirname(out_n), f'{stem_base}-001{ext_base or ".mkv"}') if out_n else ''
                if split_by_config:
                    exists_map = {p: os.path.isfile(p) for p in expected_split_paths}
                    primary_ok = ret_ok and all(exists_map.values())
                    if (not primary_ok) and ret_ok and expected_split_paths:
                        for retry_i in range(5):
                            time.sleep(0.2)
                            exists_map = {p: os.path.isfile(p) for p in expected_split_paths}
                            if all(exists_map.values()):
                                primary_ok = True
                                break
                elif out_n and expected_split_paths:
                    primary_ok = ret_ok and (out_exists or (bool(alt001) and os.path.isfile(alt001)))
                else:
                    primary_ok = ret_ok and out_exists
                if not primary_ok and expected_split_paths:
                    for p in expected_split_paths:
                        self._remux_chapter_skip_paths.add(_norm_skip(p))
                elif not primary_ok and out_n:
                    self._remux_chapter_skip_paths.add(_norm_skip(out_n))
            if not line_mux_checks and getattr(self, 'movie_mode', False):
                primary_ok = ret_ok and out_exists
                if not primary_ok and out_n:
                    self._remux_chapter_skip_paths.add(_norm_skip(out_n))
            fb_audio, fb_sub = _svc_cls()._fallback_track_lists(remux_cmd, copy_audio_track, copy_sub_track)
            if not primary_ok and n_clips == 1:
                self._progress(text=f'Mux fallback (single-clip aligned): BD_Vol_{bdmv_vol}')
                if self._try_remux_mpls_single_clip_track_aligned(
                        mpls_path,
                        out_n,
                        fb_audio,
                        fb_sub,
                        cancel_event=cancel_event,
                ):
                    primary_ok = bool(out_n and os.path.isfile(out_n))
                    if primary_ok:
                        self._remux_chapter_skip_paths.discard(_norm_skip(out_n))
            if n_clips > 1 and not primary_ok:
                if split_by_config:
                    self._progress(text=f'Mux fallback (multi-episode split aligned): BD_Vol_{bdmv_vol}')
                    split_ok = self._try_remux_mpls_split_outputs_track_aligned(
                        mpls_path,
                        out_n,
                        confs,
                        fb_audio,
                        fb_sub,
                        cover,
                        cancel_event=cancel_event,
                    )
                    if split_ok:
                        primary_ok = all(os.path.isfile(p) for p in expected_split_paths)
                        if primary_ok:
                            for p in expected_split_paths:
                                self._remux_chapter_skip_paths.discard(_norm_skip(p))
                    else:
                        print(f'[remux-fallback-split] failed for BD_Vol_{bdmv_vol} (see logs above)')
                        self._progress(
                            text=f'Multi-episode split fallback failed: BD_Vol_{bdmv_vol} (see terminal [remux-fallback-split])')
                if n_clips > 1 and not primary_ok and (not split_by_config):
                    self._progress(text=f'Mux fallback (multi-m2ts aligned): BD_Vol_{bdmv_vol}')
                    if self._try_remux_mpls_track_aligned_concat(
                            mpls_path,
                            out_n,
                            fb_audio,
                            fb_sub,
                            cover,
                            cancel_event=cancel_event,
                    ):
                        ret = 0
                        if out_n and os.path.isfile(out_n):
                            self._remux_chapter_skip_paths.discard(_norm_skip(out_n))
            self._progress(
                mux_progress_base + int(idx / max(len(bdmv_index_list), 1) * mux_progress_span))

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
    ) -> tuple[str, str, str, str, str, dict[int, str], list[str], list[str]]:
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
        return remux_cmd, m2ts_file, bdmv_vol, output_file, mpls_path, chapter.pid_to_lang, copy_audio_track, copy_sub_track

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
            dst_folder: str,
            bdmv_index_conf: dict[int, list[dict[str, int | str]]],
            configuration: dict[int, dict[str, int | str]],
            episode_output_names: Optional[list[str]],
            cancel_event: Optional[threading.Event],
    ) -> tuple[list[str], bool]:
        """
        After mux: validate theoretical ``-o`` outputs vs disk (excluding split-check skips),
        optional chapter-debug from remux parse or table2 bounds, then rename to table2 names when counts align.

        Parses using ``main_remux_cmd`` from configuration (table1 remux column). If that string is empty,
        uses the built-in mux template from ``_make_main_mpls_remux_cmd`` (same as mux execution) only for
        parsing—not as a replacement for what was displayed in table1.

        Returns ``([], True)`` when validation fails (caller should fall back to raw collected mkvs).
        """
        cfg_sorted_keys = sorted(configuration.keys())
        names = episode_output_names or []
        skip_norm = getattr(self, '_remux_chapter_skip_paths', None) or set()
        path_by_conf_key: dict[int, str] = {}

        def _norm_path(p: str) -> str:
            return os.path.normcase(os.path.normpath(p))

        char_map = {
            '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'", '/': '／', '\\': '／', '|': '￨'
        }

        for bdmv_index in sorted(bdmv_index_conf.keys()):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            confs = sorted(
                list(bdmv_index_conf[bdmv_index]),
                key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 1),
            )
            built = self._make_main_mpls_remux_cmd(
                confs=confs,
                dst_folder=dst_folder,
                bdmv_index=bdmv_index,
                disc_count=len(bdmv_index_conf),
                ensure_disc_out_dir=True,
            )
            remux_cmd = str(built[0] or '').strip()
            built_mpls = str(built[4] or '').strip()
            mpls_path = ''
            if built_mpls:
                mpls_path = built_mpls if built_mpls.lower().endswith('.mpls') else (built_mpls + '.mpls')
            if not mpls_path:
                raw_mpls = str(confs[0].get('selected_mpls') or '').strip()
                mpls_path = raw_mpls if raw_mpls.lower().endswith('.mpls') else (raw_mpls + '.mpls' if raw_mpls else '')
            theory = _svc_cls().theoretical_remux_output_paths_ordered(remux_cmd, confs, mpls_path)
            if not theory:
                print(f'{self.t("[post-remux] ")}{self.t("abort: could not derive theoretical outputs from remux_cmd")}')
                return [], True
            for tp in theory:
                tn = _norm_path(tp)
                if tn in skip_norm:
                    continue
                if not os.path.isfile(tp):
                    print(f'{self.t("[post-remux] ")}{self.t("abort: missing expected output: ")}{tp}')
                    return [], True

            keys_vol = sorted(
                [k for k in cfg_sorted_keys if int(configuration[k].get('bdmv_index', 0)) == bdmv_index],
                key=lambda kk: int(configuration[kk].get('chapter_index') or configuration[kk].get('start_at_chapter') or 1),
            )
            bounds: Optional[list[tuple[int, int]]] = None
            rb = _svc_cls()._remux_parsed_chapter_bounds_for_theory_count(
                remux_cmd, confs, mpls_path, len(theory))
            if rb and len(rb) == len(theory):
                bounds = rb
            if bounds is None and len(theory) == len(confs):
                try:
                    segs_pc: list[tuple[int, int]] = []
                    for c in confs:
                        sm = str(c.get('selected_mpls') or '').strip()
                        mp_c = sm if sm.lower().endswith('.mpls') else (sm + '.mpls' if sm else '')
                        if not mp_c or not os.path.isfile(mp_c):
                            segs_pc = []
                            break
                        ch_c = Chapter(mp_c)
                        seg_one = _svc_cls()._series_episode_segments_bounds(ch_c, [c])
                        if len(seg_one) != 1:
                            segs_pc = []
                            break
                        segs_pc.append(seg_one[0])
                    if len(segs_pc) == len(theory):
                        bounds = segs_pc
                except Exception:
                    bounds = None
            if bounds is None and len(theory) == len(keys_vol):
                try:
                    ch = Chapter(mpls_path)
                    segs = _svc_cls()._series_episode_segments_bounds(ch, confs)
                    if len(segs) == len(theory):
                        bounds = segs
                except Exception:
                    bounds = None

            def _mpls_for_conf_index(idx: int) -> str:
                if idx < 0 or idx >= len(confs):
                    return mpls_path
                sm = str(confs[idx].get('selected_mpls') or '').strip()
                if not sm:
                    return mpls_path
                return sm if sm.lower().endswith('.mpls') else (sm + '.mpls')

            chapter_txt = os.path.join(os.getcwd(), 'chapter.txt')
            if bounds and len(bounds) == len(theory):
                for i, tp in enumerate(theory):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    if _norm_path(tp) in skip_norm:
                        continue
                    if not os.path.isfile(tp):
                        continue
                    s0, e0 = bounds[i]
                    self._write_remux_segment_chapter_txt(_mpls_for_conf_index(i), s0, e0, chapter_txt)
                    MKV(tp).add_chapter(self.checked)

            if len(theory) == len(keys_vol):
                for i, k in enumerate(keys_vol):
                    tp = theory[i]
                    if _norm_path(tp) in skip_norm:
                        continue
                    if os.path.isfile(tp):
                        path_by_conf_key[k] = tp

                for i, tp in enumerate(theory):
                    if _norm_path(tp) in skip_norm:
                        continue
                    k = keys_vol[i]
                    raw_name = ''
                    try:
                        if isinstance(k, int) and 0 <= k < len(names):
                            raw_name = str(names[k] or '').strip()
                    except Exception:
                        raw_name = ''
                    if not raw_name:
                        continue
                    new_base = ''.join(char_map.get(ch) or ch for ch in raw_name)
                    new_base = new_base.strip().rstrip('.')
                    if not new_base.lower().endswith('.mkv'):
                        new_base += '.mkv'
                    folder = os.path.dirname(tp)
                    new_path = os.path.join(folder, new_base)
                    cur = path_by_conf_key.get(k, tp)
                    if not cur or not os.path.isfile(cur):
                        continue
                    if os.path.normcase(cur) == os.path.normcase(new_path):
                        path_by_conf_key[k] = new_path
                        continue
                    if os.path.exists(new_path):
                        stem, ext = os.path.splitext(new_base)
                        n = 1
                        candidate = new_path
                        while os.path.exists(candidate):
                            candidate = os.path.join(folder, f'{stem} ({n}){ext}')
                            n += 1
                        new_path = candidate
                    try:
                        os.rename(cur, new_path)
                        path_by_conf_key[k] = new_path
                    except Exception:
                        print_exc_terminal()

        final_mkvs: list[str] = []
        for k in cfg_sorted_keys:
            p = path_by_conf_key.get(k)
            if p and os.path.isfile(p):
                final_mkvs.append(p)
        return final_mkvs, False

    def episodes_remux(self, table: Optional[QTableWidget], folder_path: str,
                       selected_mpls: Optional[list[tuple[str, str]]] = None,
                       configuration: Optional[dict[int, dict[str, int | str]]] = None,
                       cancel_event: Optional[threading.Event] = None,
                       ensure_tools: bool = True,
                       sp_entries: Optional[list[dict[str, int | str]]] = None,
                       episode_output_names: Optional[list[str]] = None,
                       episode_subtitle_languages: Optional[list[str]] = None):
        dst_folder, mkv_files_before, bdmv_index_conf = self._prepare_episode_run(
            folder_path, configuration, ensure_tools
        )

        self._build_main_episode_mkvs(bdmv_index_conf, dst_folder, cancel_event=cancel_event)

        self.checked = True
        self.episode_subtitle_languages = episode_subtitle_languages or []
        mkv_raw = self._collect_target_mkv_files(dst_folder, mkv_files_before)
        if getattr(self, 'movie_mode', False):
            mkv_files = self._apply_episode_output_names(mkv_raw, episode_output_names)
            self._remux_remap_chapter_skip_after_rename(mkv_files)
        else:
            self._progress(385, 'Writing Chapters')
            mkv_files, post_aborted = self._post_remux_finalize_episodes(
                dst_folder, bdmv_index_conf, self.configuration, episode_output_names, cancel_event)
            if post_aborted:
                print(f'{self.t("[post-remux] ")}{self.t("aborted chapter/rename pipeline (theory parse or missing outputs)")}')
                mkv_files = mkv_raw
            elif not mkv_files:
                mkv_files = mkv_raw
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        if getattr(self, 'movie_mode', False):
            self._progress(385, 'Writing Chapters')
            self.add_chapter_to_mkv(
                mkv_files, table, selected_mpls=selected_mpls, cancel_event=cancel_event,
                configuration=self.configuration,
            )
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
        os.makedirs(stage_parent, exist_ok=True)

        dst_stage, mkv_files_before, bdmv_index_conf = self._prepare_episode_run(
            stage_parent, configuration, ensure_tools)
        final_disc = os.path.join(base_out, os.path.basename(self.bdmv_path))

        self._build_main_episode_mkvs(
            bdmv_index_conf,
            dst_stage,
            cancel_event=cancel_event,
            mux_progress_base=0,
            mux_progress_span=720,
        )

        self.checked = True
        self.episode_subtitle_languages = episode_subtitle_languages
        mkv_raw = self._collect_target_mkv_files(dst_stage, mkv_files_before)
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
