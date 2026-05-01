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
from src.core import CONFIGURATION, find_mkvtoolinx, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.domain import MKV
from src.exports.utils import get_index_to_m2ts_and_offset, get_time_str, force_remove_file, print_exc_terminal
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
            find_mkvtoolinx()
        except Exception:
            pass
        return core_settings.MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'

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
            try:
                if conf.get('end_at_chapter') is not None:
                    s = int(conf.get('start_at_chapter') or conf.get('chapter_index') or 0)
                    e = int(conf.get('end_at_chapter') or 0)
                    if e > 0 and s >= e:
                        continue
            except Exception:
                pass
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
            if m2ts_file:
                print(f'{self.t("Analyzing first stream file in mpls ｢")}{m2ts_file}{self.t("｣ tracks")}')
                self._progress(text=f'{self.t("Analyzing tracks: ")}{os.path.basename(m2ts_file)}')
            print(f'{self.t("Mux command: ")}{remux_cmd}')
            self._progress(text=f'{self.t("Muxing: ")}BD_Vol_{bdmv_vol}')
            ret, line_rets = self._run_shell_command_detailed(remux_cmd)
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
            try:
                targets: list[str] = []
                lang_cfg_all = getattr(self, 'track_language_config', {}) or {}
                try:
                    lang_override = dict(lang_cfg_all.get(f'main::{os.path.normpath(mpls_path)}') or {})
                except Exception:
                    lang_override = {}
                outs_seen: set[str] = set()
                for ln in lines_mx:
                    o = _svc_cls()._mkvmerge_output_path_from_line(ln)
                    if not o:
                        continue
                    o = os.path.normpath(o)
                    if o in outs_seen:
                        continue
                    outs_seen.add(o)
                    out_dir = os.path.dirname(o)
                    base_stem = os.path.splitext(os.path.basename(o))[0]
                    if out_dir and os.path.isdir(out_dir):
                        for fn in os.listdir(out_dir):
                            low = fn.lower()
                            if (fn.startswith(base_stem)) and low.endswith(('.mkv', '.mka')):
                                fp = os.path.normpath(os.path.join(out_dir, fn))
                                if os.path.isfile(fp):
                                    targets.append(fp)
                    if os.path.exists(o):
                        targets.append(o)
                out_fb = out_n if out_n else (os.path.normpath(output_file) if output_file else '')
                if out_fb and out_fb not in outs_seen:
                    out_dir = os.path.dirname(out_fb)
                    base_stem = os.path.splitext(os.path.basename(out_fb))[0]
                    if out_dir and os.path.isdir(out_dir):
                        for fn in os.listdir(out_dir):
                            low = fn.lower()
                            if (fn.startswith(base_stem)) and low.endswith(('.mkv', '.mka')):
                                fp = os.path.normpath(os.path.join(out_dir, fn))
                                if os.path.isfile(fp):
                                    targets.append(fp)
                    if os.path.exists(out_fb):
                        targets.append(out_fb)
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
            default_audio_opts = (f'-a {",".join(copy_audio_track)}' if copy_audio_track else '')
            default_sub_opts = (f'-s {",".join(copy_sub_track)}' if copy_sub_track else '')
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            default_cmd = (
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} --chapter-language eng -o "{output_file}" '
                f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip()
            tpls_mv = [str(c.get('main_remux_cmd') or '').strip() for c in confs]
            nonempty_mv = [t for t in tpls_mv if t]
            if not nonempty_mv:
                remux_cmd = default_cmd
            elif len(set(nonempty_mv)) == 1 and all(tpls_mv):
                u = tpls_mv[0]
                remux_cmd = (u.replace('{output_file}', output_file)
                             .replace('{mpls_path}', mpls_path)
                             .replace('{audio_opts}', default_audio_opts)
                             .replace('{sub_opts}', default_sub_opts)
                             .replace('{cover_opts}', default_cover_opts)
                             .replace('{chapter_split}', '')
                             .replace('{parts_split}', ''))
            else:
                lines_mv: list[str] = []
                for i, c in enumerate(confs):
                    t = str(c.get('main_remux_cmd') or '').strip()
                    if t:
                        lines_mv.append(
                            t.replace('{output_file}', output_file)
                            .replace('{mpls_path}', mpls_path)
                            .replace('{audio_opts}', default_audio_opts)
                            .replace('{sub_opts}', default_sub_opts)
                            .replace('{cover_opts}', default_cover_opts)
                            .replace('{chapter_split}', '')
                            .replace('{parts_split}', ''))
                    else:
                        od, ob = os.path.split(output_file)
                        stem_o, ext_o = os.path.splitext(ob)
                        out_i = os.path.join(od, f'{stem_o}_line{i + 1:02d}{ext_o or ".mkv"}')
                        lines_mv.append(
                            (f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} --chapter-language eng -o "{out_i}" '
                             f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip())
                remux_cmd = '\n'.join(lines_mv)
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
            default_audio_opts = (f'-a {",".join(copy_audio_track)}' if copy_audio_track else '')
            default_sub_opts = (f'-s {",".join(copy_sub_track)}' if copy_sub_track else '')
            default_cover_opts = (f'--attachment-name Cover.jpg --attach-file "{cover}"' if cover else '')
            if use_split_parts:
                split_arg = (f'--split parts:{parts_split}' if parts_split else '')
            else:
                split_arg = (f'--split chapters:{chapter_split}' if chapter_split else '')
            default_cmd = (f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} {split_arg} -o "{output_file}" '
                           f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip()
            tpls = [str(c.get('main_remux_cmd') or '').strip() for c in confs]
            nonempty = [t for t in tpls if t]
            if not nonempty:
                remux_cmd = default_cmd
            elif len(set(nonempty)) == 1 and all(tpls):
                u = tpls[0]
                remux_cmd = (u.replace('{output_file}', output_file)
                             .replace('{mpls_path}', mpls_path)
                             .replace('{audio_opts}', default_audio_opts)
                             .replace('{sub_opts}', default_sub_opts)
                             .replace('{cover_opts}', default_cover_opts)
                             .replace('{chapter_split}', chapter_split)
                             .replace('{parts_split}', parts_split))
            else:
                lines_ep: list[str] = []
                for i, c in enumerate(confs):
                    ps_i, cs_i, usp_i = _parts_chapter_for_sub_confs([c])
                    t = str(c.get('main_remux_cmd') or '').strip()
                    if usp_i:
                        split_arg_i = (f'--split parts:{ps_i}' if ps_i else '')
                    else:
                        split_arg_i = (f'--split chapters:{cs_i}' if cs_i else '')
                    if t:
                        lines_ep.append(
                            t.replace('{output_file}', output_file)
                            .replace('{mpls_path}', mpls_path)
                            .replace('{audio_opts}', default_audio_opts)
                            .replace('{sub_opts}', default_sub_opts)
                            .replace('{cover_opts}', default_cover_opts)
                            .replace('{chapter_split}', cs_i)
                            .replace('{parts_split}', ps_i))
                    else:
                        od, ob = os.path.split(output_file)
                        stem_o, ext_o = os.path.splitext(ob)
                        out_i = os.path.join(od, f'{stem_o}_line{i + 1:02d}{ext_o or ".mkv"}')
                        lines_ep.append(
                            (f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} {split_arg_i} -o "{out_i}" '
                             f'{default_audio_opts} {default_sub_opts} {default_cover_opts} "{mpls_path}"').strip())
                remux_cmd = '\n'.join(lines_ep)
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
            table, folder_path, configuration, ensure_tools
        )

        self._build_main_episode_mkvs(bdmv_index_conf, dst_folder, cancel_event=cancel_event)

        self.checked = True
        self.episode_subtitle_languages = episode_subtitle_languages or []
        mkv_raw = self._collect_target_mkv_files(dst_folder, mkv_files_before)
        if getattr(self, 'movie_mode', False):
            mkv_files = self._apply_episode_output_names(mkv_raw, episode_output_names)
            self._remux_remap_chapter_skip_after_rename(mkv_files)
        else:
            self._progress(310, 'Writing Chapters')
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
            self._progress(400 + int(400 * i / max(len(mkv_files), 1)))

        sps_folder = dst_folder + os.sep + 'SPs'
        os.mkdir(sps_folder)
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
            p = 800 + min(95, int(95 * min(sp_mux_done, denom) / denom))
            if known_total:
                self._progress(p, f'Muxing SP {sp_mux_done}/{known_total}: {item_name}')
            else:
                self._progress(p, f'Muxing SP {sp_mux_done}: {item_name}')

        if sp_entries is not None:
            self._create_sp_mkvs_from_entries(
                bdmv_index_conf,
                sp_entries,
                sps_folder,
                cancel_event=cancel_event,
                progress_cb=lambda _idx, path: _progress_sp_mux(os.path.basename(path)),
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
                            subprocess.Popen(f'"{self._mkvmerge_exe()}" {mkvtoolnix_ui_language_arg()} '
                                             f'{("--chapters " + "\"" + chapter_txt + "\"") if chapter_txt else ""} '
                                             f'-o "{os.path.join(sps_folder, out_name)}" '
                                             f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                             f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                             f'"{mpls_file_path}"',
                                             shell=True).wait()
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
                                f'"{self._mkvmerge_exe()}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(sps_folder, out_name)}" '
                                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                                f'"{os.path.join(stream_folder, stream_file)}"',
                                shell=True
                            ).wait()
                            _progress_sp_mux(out_name)
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
        self._remux_remap_chapter_skip_after_rename(mkv_files)
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
            try:
                if os.path.basename(mkv_file) in mkv_files_before and os.path.exists(mkv_file):
                    self._progress(400 + int(400 * i / len(mkv_files)))
                    continue
            except Exception:
                pass
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
                            subprocess.Popen(f'"{self._mkvmerge_exe()}" {mkvtoolnix_ui_language_arg()} '
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
                                f'"{self._mkvmerge_exe()}" {mkvtoolnix_ui_language_arg()} -o "{os.path.join(sps_folder, out_name)}" '
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
        mkvmerge_exe = self._mkvmerge_exe()
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
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                f'{"-a " + audio_tracks if audio_tracks else ""} "{mkv_file}" {language_options}')
        else:
            tracker_order = f'{pcm_track_count + 1}:0,{tracker_order}'
            return (
                f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} -o "{output_file}" --track-order {tracker_order} '
                f'{("-a " + ",".join(copy_audio_track)) if copy_audio_track else ""} '
                f'{("-s " + ",".join(copy_sub_track)) if copy_sub_track else ""} '
                f'-d !0 {"-a " + audio_tracks if audio_tracks else ""} "{mkv_file}" {language_options} "{hevc_file}"')
