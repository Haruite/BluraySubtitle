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
from src.core import CONFIGURATION, find_mkvtoolinx, MKV_MERGE_PATH, mkvtoolnix_ui_language_arg
from src.exports.utils import get_index_to_m2ts_and_offset, get_time_str, force_remove_file, print_exc_terminal
from .service_base import BluraySubtitleServiceBase
from ..services.cancelled import _Cancelled


def _svc_cls():
    from ..services.bluray_subtitle_entry import BluraySubtitle
    return BluraySubtitle


class RemuxEpisodeWorkflowsMixin(BluraySubtitleServiceBase):
    def _prepare_episode_run(
            self,
            table: Optional[QTableWidget],
            folder_path: str,
            configuration: Optional[dict[int, dict[str, int | str]]],
            ensure_tools: bool,
    ) -> tuple[str, set[str], dict[int, list[dict[str, int | str]]]]:
        if configuration is not None:
            self.configuration = configuration
        elif not CONFIGURATION:
            if table is None:
                self.configuration = {}
            else:
                self.configuration = self.generate_configuration(table)
        else:
            self.configuration = CONFIGURATION

        dst_folder = os.path.join(folder_path, os.path.basename(self.bdmv_path))
        if not os.path.exists(dst_folder):
            os.mkdir(dst_folder)

        try:
            mkv_files_before = {f for f in os.listdir(dst_folder) if f.lower().endswith(('.mkv', '.mka'))}
        except Exception:
            mkv_files_before = set()

        bdmv_index_conf: dict[int, list[dict[str, int | str]]] = {}
        for _, conf in self.configuration.items():
            bdmv_index = int(conf['bdmv_index'])
            if bdmv_index in bdmv_index_conf:
                bdmv_index_conf[bdmv_index].append(conf)
            else:
                bdmv_index_conf[bdmv_index] = [conf]

        if ensure_tools:
            find_mkvtoolinx()

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
    ) -> None:
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
            if m2ts_file:
                print(f'{self.t("Analyzing first stream file in mpls ｢")}{m2ts_file}{self.t("｣ tracks")}')
                self._progress(text=f'{self.t("Analyzing tracks: ")}{os.path.basename(m2ts_file)}')
            print(f'{self.t("Mux command: ")}{remux_cmd}')
            self._progress(text=f'{self.t("Muxing: ")}BD_Vol_{bdmv_vol}')
            ret = self._run_shell_command(remux_cmd)
            try:
                ch_tmp = Chapter(mpls_path)
                n_clips = len(ch_tmp.in_out_time or [])
            except Exception:
                n_clips = 0
            cover = ''
            if n_clips > 1:
                try:
                    meta_folder = os.path.join(mpls_path[:-19], 'META', 'DL')
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
            out_n = os.path.normpath(output_file) if output_file else ''
            out_exists = bool(out_n and os.path.isfile(out_n))
            expected_split_paths: list[str] = []
            if (not getattr(self, 'movie_mode', False)) and out_n and confs:
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
            ret_ok = (ret in (0, 1))
            stem_base, ext_base = os.path.splitext(os.path.basename(out_n)) if out_n else ('', '.mkv')
            alt001 = os.path.join(os.path.dirname(out_n), f'{stem_base}-001{ext_base or ".mkv"}') if out_n else ''
            print(
                f'[split-check] bdmv={bdmv_vol} ret={ret} ret_ok={ret_ok} out="{out_n}" n_clips={n_clips} split_by_config={split_by_config}')
            print(f'[split-check] expected_split_paths({len(expected_split_paths)}): {expected_split_paths}')
            print(f'[split-check] cmd_split_count={cmd_split_count} alt001="{alt001}" out_exists={out_exists}')
            if split_by_config:
                exists_map = {p: os.path.isfile(p) for p in expected_split_paths}
                print(f'[split-check] exists(initial): {exists_map}')
                primary_ok = ret_ok and all(exists_map.values())
                if (not primary_ok) and ret_ok and expected_split_paths:
                    # On some filesystems, split files may appear shortly after process exit.
                    # Retry briefly before deciding fallback is needed.
                    for retry_i in range(5):
                        time.sleep(0.2)
                        exists_map = {p: os.path.isfile(p) for p in expected_split_paths}
                        print(f'[split-check] exists(retry#{retry_i + 1}): {exists_map}')
                        if all(exists_map.values()):
                            primary_ok = True
                            break
            elif out_n and expected_split_paths:
                primary_ok = ret_ok and (out_exists or (bool(alt001) and os.path.isfile(alt001)))
            else:
                primary_ok = ret_ok and out_exists
            print(f'[split-check] primary_ok={primary_ok}')
            fb_audio, fb_sub = _svc_cls()._fallback_track_lists(remux_cmd, copy_audio_track, copy_sub_track)
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
                        ret = 0
                        primary_ok = all(os.path.isfile(p) for p in expected_split_paths)
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
            try:
                targets: list[str] = []
                out = os.path.normpath(output_file) if output_file else ''
                lang_cfg_all = getattr(self, 'track_language_config', {}) or {}
                lang_override = {}
                try:
                    lang_override = dict(lang_cfg_all.get(f'main::{os.path.normpath(mpls_path)}') or {})
                except Exception:
                    lang_override = {}
                if out:
                    out_dir = os.path.dirname(out)
                    base_stem = os.path.splitext(os.path.basename(out))[0]
                    if out_dir and os.path.isdir(out_dir):
                        for fn in os.listdir(out_dir):
                            low = fn.lower()
                            if (fn.startswith(base_stem)) and low.endswith(('.mkv', '.mka')):
                                fp = os.path.normpath(os.path.join(out_dir, fn))
                                if os.path.isfile(fp):
                                    targets.append(fp)
                    if os.path.exists(out):
                        targets.append(out)
                targets = sorted(list(dict.fromkeys(targets)))
                for t in targets:
                    _svc_cls()._fix_output_track_languages_with_mkvpropedit(
                        t,
                        m2ts_file,
                        pid_to_lang,
                        copy_audio_track,
                        copy_sub_track,
                        lang_override
                    )
            except Exception:
                pass
            self._progress(int(idx / max(len(bdmv_index_list), 1) * 300))

    def _run_shell_command(self, cmd: str) -> int:
        # Split multi-line commands and execute them sequentially
        commands = [line.strip() for line in cmd.split('\n') if line.strip()]
        if len(commands) <= 1:
            # Single command, execute as before
            return self._run_single_command(cmd)
        else:
            # Multiple commands, execute sequentially
            for single_cmd in commands:
                ret = self._run_single_command(single_cmd)
                if ret != 0:
                    return ret
            return 0

    def _run_single_command(self, cmd: str) -> int:
        if sys.platform == 'win32':
            return subprocess.Popen(cmd, shell=True).wait()

        def _fix_rm_glob(raw: str) -> str:
            # Convert rm "dir/*-007.mkv" -> rm "dir/"*-007.mkv so glob can expand.
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
            # If user chains cleanup with '&& rm', mkvmerge may return non-zero even when files are created,
            # so run cleanup unconditionally.
            out = re.sub(r'\s*&&\s*rm\b', r'; rm -f', out)
            return out

        cmd = _fix_rm_glob(cmd)
        try:
            return subprocess.Popen(['bash', '-lc', cmd]).wait()
        except Exception:
            return subprocess.Popen(cmd, shell=True).wait()

    def _make_main_mpls_remux_cmd(
            self,
            confs: list[dict[str, int | str]],
            dst_folder: str,
            bdmv_index: int,
            disc_count: int,
            *,
            ensure_disc_out_dir: bool = False,
    ) -> tuple[str, str, str, str, str, dict[int, str], list[str], list[str]]:
        mpls_path = confs[0]['selected_mpls'] + '.mpls'
        disc_name = ''
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
        m2ts_file = os.path.join(os.path.join(mpls_path[:-19], 'STREAM'), chapter.in_out_time[0][0] + '.m2ts')
        copy_audio_track, copy_sub_track = self._select_tracks_for_source(
            m2ts_file,
            chapter.pid_to_lang,
            config_key=f'main::{os.path.normpath(mpls_path)}'
        )
        meta_folder = os.path.join(os.path.join(mpls_path[:-19], 'META', 'DL'))
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
        try:
            output_name = str(confs[0].get('disc_output_name') or '').strip()
        except Exception:
            output_name = ''
        if not output_name:
            output_name = self._resolve_disc_output_name(confs[0]['selected_mpls'])

        bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
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
            default_audio_opts = (f'-a {",".join(copy_audio_track)}' if copy_audio_track else '')
            default_sub_opts = (f'-s {",".join(copy_sub_track)}' if copy_sub_track else '')
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            default_cmd = (
                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} --chapter-language eng -o "{output_file}" '
                f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip()
            custom_cmd = str(confs[0].get('main_remux_cmd') or '').strip()
            if custom_cmd:
                remux_cmd = (custom_cmd
                             .replace('{output_file}', output_file)
                             .replace('{mpls_path}', mpls_path)
                             .replace('{audio_opts}', default_audio_opts)
                             .replace('{sub_opts}', default_sub_opts)
                             .replace('{cover_opts}', default_cover_opts)
                             .replace('{chapter_split}', ''))
            else:
                remux_cmd = default_cmd
        else:
            confs_sorted = sorted(confs, key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 1))
            rows = sum(map(len, chapter.mark_info.values()))
            total_end = rows + 1
            segments = _svc_cls()._series_episode_segments_bounds(chapter, confs)
            chapter_starts = [int(c.get('start_at_chapter') or c.get('chapter_index') or 1) for c in confs_sorted]
            chapter_after_first = [s for s in chapter_starts[1:] if 1 < s <= rows]
            chapter_split = ','.join(map(str, chapter_after_first))
            use_split_parts = not bool(confs[0].get('chapter_segments_fully_checked', True)) if confs else False
            index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)

            def _off(idx: int) -> float:
                if idx >= total_end:
                    return chapter.get_total_time()
                return float(index_to_offset.get(idx, 0.0))

            parts_list: list[str] = []
            for s, e in segments:
                st = get_time_str(_off(s))
                ed = get_time_str(_off(e))
                if st == '0':
                    st = '00:00:00.000'
                if ed == '0':
                    ed = '00:00:00.000'
                parts_list.append(f'{st}-{ed}')
            parts_split = ','.join(parts_list)
            output_file = f'{os.path.join(disc_out_dir or dst_folder, output_name)}_BD_Vol_{bdmv_vol}.mkv'
            default_audio_opts = (f'-a {",".join(copy_audio_track)}' if copy_audio_track else '')
            default_sub_opts = (f'-s {",".join(copy_sub_track)}' if copy_sub_track else '')
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            if use_split_parts:
                split_arg = (f'--split parts:{parts_split}' if parts_split else '')
            else:
                split_arg = (f'--split chapters:{chapter_split}' if chapter_split else '')
            default_cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} {split_arg} -o "{output_file}" '
                           f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip()
            custom_cmd = str(confs[0].get('main_remux_cmd') or '').strip()
            if custom_cmd:
                remux_cmd = (custom_cmd
                             .replace('{output_file}', output_file)
                             .replace('{mpls_path}', mpls_path)
                             .replace('{audio_opts}', default_audio_opts)
                             .replace('{sub_opts}', default_sub_opts)
                             .replace('{cover_opts}', default_cover_opts)
                             .replace('{chapter_split}', chapter_split)
                             .replace('{parts_split}', parts_split))
            else:
                remux_cmd = default_cmd
        return remux_cmd, m2ts_file, bdmv_vol, output_file, mpls_path, chapter.pid_to_lang, copy_audio_track, copy_sub_track

    def episodes_remux(self, table: Optional[QTableWidget], folder_path: str,
                       selected_mpls: Optional[list[tuple[str, str]]] = None,
                       configuration: Optional[dict[int, dict[str, int | str]]] = None,
                       cancel_event: Optional[threading.Event] = None,
                       ensure_tools: bool = True,
                       sp_entries: Optional[list[dict[str, int | str]]] = None,
                       episode_output_names: Optional[list[str]] = None,
                       episode_subtitle_languages: Optional[list[str]] = None):
        dst_folder, mkv_files_before, bdmv_index_conf = self._prepare_episode_run(
            table, folder_path, configuration, ensure_tools
        )

        self._build_main_episode_mkvs(bdmv_index_conf, dst_folder, cancel_event=cancel_event)

        self.checked = True
        self.episode_subtitle_languages = episode_subtitle_languages or []
        mkv_files = self._collect_target_mkv_files(dst_folder, mkv_files_before)
        mkv_files = self._apply_episode_output_names(mkv_files, episode_output_names)
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        if not getattr(self, 'movie_mode', False):
            self._progress(310, 'Writing Chapters')
            self.add_chapter_to_mkv(
                mkv_files, table, selected_mpls=selected_mpls, cancel_event=cancel_event,
                configuration=self.configuration,
            )
            self._progress(400)

        i = 0
        for mkv_file in mkv_files:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            i += 1
            self._progress(text=f'Compressing audio: {os.path.basename(mkv_file)}')
            self.flac_task(mkv_file, dst_folder, i)
            self._progress(400 + int(400 * i / len(mkv_files)))

        sps_folder = dst_folder + os.sep + 'SPs'
        os.mkdir(sps_folder)

        if sp_entries is not None:
            self._create_sp_mkvs_from_entries(bdmv_index_conf, sp_entries, sps_folder, cancel_event=cancel_event)
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
                            chapter_txt = os.path.join(sps_folder, f'{os.path.splitext(out_name)[0]}.chapter.txt')
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
                            subprocess.Popen(f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} '
                                             f'{("--chapters " + "\"" + chapter_txt + "\"") if chapter_txt else ""} '
                                             f'-o "{os.path.join(sps_folder, out_name)}" '
                                             f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                             f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                             f'"{mpls_file_path}"',
                                             shell=True).wait()
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
                                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(sps_folder, out_name)}" '
                                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                                shell=True
                            ).wait()
        sp_files = [sp for sp in os.listdir(sps_folder) if sp.lower().endswith(('.mkv', '.mka'))]
        sp_files.sort()
        total_sp = len(sp_files) or 1
        self._progress(900, 'Processing SP audio tracks')
        for idx, sp in enumerate(sp_files, start=1):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            self._progress(900 + int(90 * idx / total_sp), f'Processing SP audio tracks {idx}/{total_sp}: {sp}')
            self.flac_task(sps_folder + os.sep + sp, sps_folder, -1)

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
                        sub_pack_mode: str = 'external'):
        dst_folder, mkv_files_before, bdmv_index_conf = self._prepare_episode_run(
            table, folder_path, configuration, ensure_tools
        )

        self._build_main_episode_mkvs(bdmv_index_conf, dst_folder, cancel_event=cancel_event)

        self.checked = True
        self.episode_subtitle_languages = episode_subtitle_languages or []
        mkv_files = self._collect_target_mkv_files(dst_folder, mkv_files_before)
        mkv_files = self._apply_episode_output_names(mkv_files, episode_output_names)
        if cancel_event and cancel_event.is_set():
            raise _Cancelled()
        if not getattr(self, 'movie_mode', False):
            self._progress(310, 'Writing Chapters')
            self.add_chapter_to_mkv(
                mkv_files, table, selected_mpls=selected_mpls, cancel_event=cancel_event,
                configuration=self.configuration,
            )
            self._progress(400)

        i = 0
        for mkv_file in mkv_files:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            i += 1
            self._progress(text=f'Encode and mux: {os.path.basename(mkv_file)}')
            vpy_path = None
            if vpy_paths and 0 <= (i - 1) < len(vpy_paths):
                vpy_path = vpy_paths[i - 1]
            if not vpy_path:
                vpy_path = os.path.join(os.getcwd(), 'vpy.vpy')
            self.encode_task(mkv_file, dst_folder, i, vpy_path, vspipe_mode, x265_mode, x265_params, sub_pack_mode)
            if sub_pack_mode == 'external' and self.sub_files and len(self.sub_files) >= i and i > -1:
                sub_src = self.sub_files[i - 1]
                sub_ext = os.path.splitext(sub_src)[1].lower()
                if sub_ext in ('.ass', '.ssa', '.srt'):
                    video_base = os.path.splitext(os.path.basename(mkv_file))[0]
                    sub_dst = os.path.join(dst_folder, video_base + sub_ext)
                    try:
                        shutil.copy2(sub_src, sub_dst)
                    except Exception:
                        print_exc_terminal()
            self._progress(400 + int(400 * i / len(mkv_files)))

        sps_folder = dst_folder + os.sep + 'SPs'
        os.mkdir(sps_folder)
        self._progress(900, 'Processing SP audio tracks')

        if sp_entries is not None:
            created_sp = self._create_sp_mkvs_from_entries(bdmv_index_conf, sp_entries, sps_folder,
                                                           cancel_event=cancel_event)
            total_sp = len(created_sp) or 1
            for idx, (entry_idx, sp_mkv_path) in enumerate(created_sp, start=1):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                self._progress(text=f'Encode and mux SPs: {os.path.basename(sp_mkv_path)}')
                if os.path.isdir(sp_mkv_path) or (not os.path.exists(sp_mkv_path)):
                    self._progress(900 + int(90 * idx / total_sp))
                    continue
                low = sp_mkv_path.lower()
                if low.endswith('.mka'):
                    self.flac_task(sp_mkv_path, sps_folder, -1)
                    self._progress(900 + int(90 * idx / total_sp))
                    continue
                if (not low.endswith('.mkv')):
                    self._progress(900 + int(90 * idx / total_sp))
                    continue
                if sp_vpy_paths and 0 <= (entry_idx - 1) < len(sp_vpy_paths) and sp_vpy_paths[entry_idx - 1]:
                    cur_sp_vpy = str(sp_vpy_paths[entry_idx - 1])
                else:
                    cur_sp_vpy = os.path.join(os.getcwd(), 'vpy.vpy')
                self.encode_task(sp_mkv_path, sps_folder, -1, cur_sp_vpy, vspipe_mode, x265_mode, x265_params,
                                 'external')
                self._progress(900 + int(90 * idx / total_sp))
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
                            chapter_txt = os.path.join(sps_folder, f'{os.path.splitext(out_name)[0]}.chapter.txt')
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
                            subprocess.Popen(f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} '
                                             f'{("--chapters " + "\"" + chapter_txt + "\"") if chapter_txt else ""} '
                                             f'-o "{os.path.join(sps_folder, out_name)}" '
                                             f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                             f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                             f'"{mpls_file_path}"',
                                             shell=True).wait()
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
                            subprocess.Popen(
                                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(sps_folder, out_name)}" '
                                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                                shell=True
                            ).wait()
            sp_files = [os.path.join(sps_folder, sp) for sp in os.listdir(sps_folder) if
                        sp.lower().endswith(('.mkv', '.mka'))]
            sp_files.sort()
            total_sp = len(sp_files) or 1
            for idx, sp_path in enumerate(sp_files, start=1):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                self._progress(text=f'Encode and mux SPs: {os.path.basename(sp_path)}')
                if sp_path.lower().endswith('.mka'):
                    self.flac_task(sp_path, sps_folder, -1)
                else:
                    if sp_vpy_paths and 0 <= (idx - 1) < len(sp_vpy_paths) and sp_vpy_paths[idx - 1]:
                        cur_sp_vpy = sp_vpy_paths[idx - 1]
                    else:
                        cur_sp_vpy = os.path.join(os.getcwd(), 'vpy.vpy')
                    self.encode_task(sp_path, sps_folder, -1, cur_sp_vpy, vspipe_mode, x265_mode, x265_params,
                                     'external')
                self._progress(900 + int(90 * idx / total_sp))

        self.completion()
        self._progress(1000, 'Done')

    def generate_remux_cmd(self, track_count, track_info, flac_files, output_file, mkv_file,
                           hevc_file: Optional[str] = None):
        copy_audio_track = list(getattr(self, '_active_copy_audio_track', []) or [])
        copy_sub_track = list(getattr(self, '_active_copy_sub_track', []) or [])
        track_flac_map = getattr(self, '_track_flac_map', {}) or {}
        audio_tracks_to_exclude = sorted(
            {int(x) for x in (getattr(self, '_audio_tracks_to_exclude', set()) or set()) if str(x).strip() != ''})
        tracker_order = []
        audio_tracks = []
        pcm_track_count = 0
        language_options = []
        for _ in range(track_count + 1):
            if _ in track_info:
                pcm_track_count += 1
                flac_src = track_flac_map.get(_)
                if not flac_src:
                    try:
                        flac_src = flac_files[pcm_track_count - 1]
                    except IndexError:
                        continue
                language_options.append(f'--language 0:{track_info[_]} "{flac_src}"')
                tracker_order.append(f'{pcm_track_count}:0')
            elif _ in audio_tracks_to_exclude:
                continue
            else:
                tracker_order.append(f'0:{_}')
        tracker_order = ','.join(tracker_order)
        audio_tracks = ('!' + ','.join([str(x) for x in audio_tracks_to_exclude])) if audio_tracks_to_exclude else ''
        language_options = ' '.join(language_options)
        if not hevc_file:
            return (
                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                f'{"-a " + audio_tracks if audio_tracks else ""} "{mkv_file}" {language_options}')
        else:
            tracker_order = f'{pcm_track_count + 1}:0,{tracker_order}'
            return (
                f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                f'-d !0 {"-a " + audio_tracks if audio_tracks else ""} "{mkv_file}" {language_options} "{hevc_file}"')
