"""Auto-generated split target: subtitle_and_chapter_pipeline."""
import os
import re
import shutil
import subprocess
import tempfile
import threading
from functools import reduce
from typing import Any, Callable, Optional

from PyQt6.QtWidgets import QTableWidget

from src.bdmv import Chapter, M2TS
from src.core import CONFIGURATION, FFMPEG_PATH, MKV_MERGE_PATH, MKV_EXTRACT_PATH, mkvtoolnix_ui_language_arg, \
    MKV_PROP_EDIT_PATH
from src.domain import MKV
from src.exports.utils import get_index_to_m2ts_and_offset, append_ogm_chapter_lines, force_remove_folder, \
    force_remove_file, print_terminal_line, print_exc_terminal, get_time_str
from .service_base import BluraySubtitleServiceBase
from ..services.cancelled import _Cancelled


def _svc_cls():
    from ..services.bluray_subtitle_entry import BluraySubtitle
    return BluraySubtitle


class SubtitleChapterPipelineMixin(BluraySubtitleServiceBase):
    @staticmethod
    def _read_m2ts_track_info(m2ts_path: str) -> list[dict[str, object]]:
        """Read stream metadata for one m2ts file."""
        try:
            return list(_svc_cls()._m2ts_track_streams(m2ts_path) or [])
        except Exception:
            return []

    @staticmethod
    def _pid_lang_from_m2ts_track_info(track_info: list[dict[str, object]]) -> dict[int, str]:
        """Convert track info list to pid->language mapping."""
        out: dict[int, str] = {}
        for row in list(track_info or []):
            if not isinstance(row, dict):
                continue
            pid_raw: Any = (
                row.get("pid")
                or row.get("service_id")
                or row.get("id")
                or row.get("stream_id")
            )
            try:
                pid = int(str(pid_raw), 0) if isinstance(pid_raw, str) else int(pid_raw)
            except Exception:
                continue
            tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
            lang = (
                row.get("language")
                or tags.get("language")
                or tags.get("LANGUAGE")
                or ""
            )
            lang = str(lang).strip().lower()
            if lang:
                out[pid] = lang
        return out

    def generate_bluray_subtitle(self, table: Optional[QTableWidget] = None,
                                 configuration: Optional[dict[int, dict[str, int | str]]] = None,
                                 cancel_event: Optional[threading.Event] = None):
        if configuration is not None:
            self.configuration = configuration
        elif CONFIGURATION:
            self.configuration = CONFIGURATION
        else:
            if table is None:
                raise ValueError('table is required when configuration is not provided')
            self.configuration = self.generate_configuration(table)
        if not self.sub_files:
            return
        self._preload_subtitles(self.sub_files, cancel_event=cancel_event)
        sub = self._subtitle_cache[self.sub_files[0]].clone()
        bdmv_index = 0
        conf = self.configuration[0]
        for sub_index, conf_tmp in self.configuration.items():
            self._progress(int((sub_index + 1) / len(self.sub_files) * 1000),
                           f'Merging {sub_index + 1}/{len(self.sub_files)}')
            if conf_tmp['bdmv_index'] != bdmv_index:
                if bdmv_index > 0:
                    self._progress(text='Writing Subtitle File')
                    if hasattr(sub, 'content'):
                        suffix = str(getattr(self, 'subtitle_suffix', '') or '')
                        sub.dump(conf['folder'] + suffix, conf['selected_mpls'] + suffix)
                    sub = self._subtitle_cache[self.sub_files[sub_index]].clone()
                bdmv_index = conf_tmp['bdmv_index']
            else:
                sub.append_subtitle(
                    self._subtitle_cache[self.sub_files[sub_index]],
                    reduce(lambda a, b: a * 60 + b, map(float, conf_tmp['offset'].split(':')))
                )
            conf = conf_tmp
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
        self._progress(text='Writing Subtitle File')
        if hasattr(sub, 'content'):
            suffix = str(getattr(self, 'subtitle_suffix', '') or '')
            sub.dump(conf['folder'] + suffix, conf['selected_mpls'] + suffix)
        self._progress(1000)

    def _group_mkv_paths_by_bdmv(self, sorted_paths: list[str], bdmv_keys: list[int]) -> dict[int, list[str]]:
        """Map episode MKV paths to configuration bdmv_index (from BD_Vol_XXX in filename)."""
        if not sorted_paths:
            return {k: [] for k in bdmv_keys}
        if len(bdmv_keys) == 1:
            return {bdmv_keys[0]: list(sorted_paths)}
        out: dict[int, list[str]] = {k: [] for k in bdmv_keys}
        for p in sorted_paths:
            m = re.search(r'BD_Vol_(\d{3})', os.path.basename(p or ''), re.I)
            if m:
                try:
                    v = int(m.group(1))
                except Exception:
                    continue
                if v in out:
                    out[v].append(p)
        return out

    @staticmethod
    def _detect_repeated_single_m2ts_mpls(mpls_path: str) -> tuple[bool, str]:
        """
        Detect menu-like MPLS that loops the exact same clip window repeatedly.
        Condition: in_out_time has >10 items and all entries are identical.
        Returns (True, "<clip>.m2ts") when matched.
        """
        try:
            ch = Chapter(mpls_path)
            ios = list(ch.in_out_time or [])
            if len(ios) <= 10:
                return False, ''
            first = ios[0]
            if any(tuple(x) != tuple(first) for x in ios[1:]):
                return False, ''
            clip = str(first[0] or '').strip()
            if not clip:
                return False, ''
            return True, f'{clip}.m2ts'
        except Exception:
            return False, ''

    def _write_remux_segment_chapter_txt(
            self,
            mpls_path: str,
            start_chapter: int,
            end_chapter: int,
            out_path: str,
    ) -> None:
        """Write OGM chapter file for one episode remux segment.

        Episode covers MPLS chapter marks with indices ``start_chapter`` .. ``end_chapter - 1``
        (same half-open interval as split). For each original mark ``j`` in that range:
        new index is ``j - start_chapter + 1`` (e.g. start 11 → new 01..06 for j=11..16),
        timestamp is ``offset(j) - offset(start_chapter)`` (first chapter is always 0).
        """
        chapter = Chapter(mpls_path)
        _, index_to_offset = get_index_to_m2ts_and_offset(chapter)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        s = max(1, min(int(start_chapter), total_end))
        e = max(s + 1, min(int(end_chapter), total_end))
        t0 = float(index_to_offset.get(s, 0.0))

        lines: list[str] = []
        for j in range(s, e):
            if j > rows:
                break
            new_idx = j - s + 1
            off = float(index_to_offset.get(j, 0.0))
            rel = max(0.0, off - t0)
            append_ogm_chapter_lines(lines, new_idx, rel)
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(lines) + ('\n' if lines else ''))
        print(
            f'{self.t("[chapter-debug] ")}{self.t("segment chapter file written: ")}{out_path} '
            f'(mpls={os.path.basename(mpls_path)} start={s} end={e} entries={len(lines) // 2})'
        )

    def _ordered_episode_confs_by_bdmv(
            self, configuration: dict[int, dict[str, int | str]]
    ) -> dict[int, list[dict[str, int | str]]]:
        by_bdmv: dict[int, list[dict[str, int | str]]] = {}
        for _, conf in (configuration or {}).items():
            bdmv_index = int(conf.get('bdmv_index') or 0)
            by_bdmv.setdefault(bdmv_index, []).append(conf)
        for bdmv_index, confs in by_bdmv.items():
            try:
                confs.sort(key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 0))
            except Exception:
                pass
            by_bdmv[bdmv_index] = confs
        return by_bdmv

    def _add_chapter_to_mkv_from_configuration(
            self,
            mkv_files: list[str],
            configuration: dict[int, dict[str, int | str]],
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        by_bdmv = self._ordered_episode_confs_by_bdmv(configuration)
        bdmv_keys = sorted(by_bdmv.keys())
        sorted_paths = sorted(mkv_files, key=self._mkv_sort_key)
        grouped = self._group_mkv_paths_by_bdmv(sorted_paths, bdmv_keys)
        total_mkv = sum(len(grouped.get(b, [])) for b in bdmv_keys)
        done = 0
        chapter_txt = os.path.join(os.getcwd(), 'chapter.txt')
        for bdmv_index in bdmv_keys:
            paths = grouped.get(bdmv_index, [])
            confs = by_bdmv.get(bdmv_index, [])
            n = min(len(paths), len(confs))
            if len(paths) != len(confs):
                print(
                    f'{self.t("add_chapter_to_mkv: BD Vol ")}{bdmv_index}'
                    f'{self.t(" MKV count (")}{len(paths)}'
                    f'{self.t(") differs from configuration count (")}{len(confs)}'
                    f'{self.t("), processing first ")}{n}{self.t(" items")}'
                )
            rows_cache: dict[str, int] = {}
            split_bounds_override: list[tuple[int, int]] = []
            try:
                first_conf = confs[0] if confs else {}
                mpls_key0 = str((first_conf or {}).get('selected_mpls') or '').strip()
                mpls_path0 = mpls_key0 if mpls_key0.lower().endswith('.mpls') else (
                    mpls_key0 + '.mpls' if mpls_key0 else '')
                cmd0 = str((first_conf or {}).get('main_remux_cmd') or '').strip()
                lines_chk = _svc_cls()._remux_cmd_shell_lines(cmd0)
                used_multiline_bounds = False
                if len(lines_chk) > 1:
                    mb = _svc_cls()._chapter_split_bounds_from_multi_line_remux_cmd(cmd0, confs)
                    if mb:
                        split_bounds_override = mb
                        used_multiline_bounds = True
                        print(
                            f'{self.t("[chapter-debug] ")}{self.t("multi-line remux_cmd chapter bounds (applied): ")}{len(mb)}'
                        )
                if not used_multiline_bounds:
                    stem0 = ''
                    if mpls_path0:
                        stem0 = os.path.splitext(os.path.basename(mpls_path0.replace('\\', '/')))[0]
                    has_split = any('--split' in ln.lower() for ln in lines_chk) if lines_chk else (
                        '--split' in cmd0.lower())
                    windows = _svc_cls()._split_parts_windows_from_mkvmerge_cmd(cmd0, mpls_stem=stem0 or None)
                    if not windows:
                        for ln in lines_chk:
                            cuts_ln = _svc_cls()._split_chapters_ints_from_mkvmerge_one_line(ln)
                            if not cuts_ln:
                                continue
                            stem_ln = _svc_cls()._mkvmerge_line_source_mpls_stem(ln)
                            mpath_use = ''
                            for c in confs:
                                raw_m = str(c.get('selected_mpls') or '').strip()
                                sc = os.path.splitext(os.path.basename(raw_m.replace('\\', '/')))[0]
                                if stem_ln and sc and stem_ln.lower() != sc.lower():
                                    continue
                                cand = raw_m if raw_m.lower().endswith('.mpls') else (raw_m + '.mpls' if raw_m else '')
                                if cand and os.path.isfile(cand):
                                    mpath_use = cand
                                    break
                            if not mpath_use and mpls_path0 and os.path.isfile(mpls_path0):
                                mpath_use = mpls_path0
                            if mpath_use:
                                windows = _svc_cls()._time_windows_from_split_chapter_numbers(mpath_use, cuts_ln)
                                if windows:
                                    break
                    if (not windows) and ('{parts_split}' in cmd0) and mpls_path0 and os.path.isfile(mpls_path0):
                        ch_tmp = Chapter(mpls_path0)
                        segs_tmp = _svc_cls()._series_episode_segments_bounds(ch_tmp, confs)
                        _i2m_tmp, i2o_tmp = get_index_to_m2ts_and_offset(ch_tmp)
                        rows_tmp = sum(map(len, ch_tmp.mark_info.values()))
                        total_end_tmp = rows_tmp + 1

                        def _off_tmp(idx: int) -> float:
                            if idx >= total_end_tmp:
                                return ch_tmp.get_total_time()
                            return float(i2o_tmp.get(idx, 0.0))

                        windows = [(float(_off_tmp(s0)), float(_off_tmp(e0))) for s0, e0 in segs_tmp]
                    if (not windows) and has_split and mpls_path0 and os.path.isfile(mpls_path0) and confs:
                        windows = _svc_cls()._episode_float_windows_from_config_bounds(mpls_path0, confs)
                        if windows:
                            print(
                                f'{self.t("[chapter-debug] ")}{self.t("derived split timeline from table2 chapter bounds: ")}{len(windows)}'
                            )
                    if windows and mpls_path0 and os.path.isfile(mpls_path0):
                        split_bounds_override = _svc_cls()._chapter_bounds_from_split_windows(mpls_path0, windows)
            except Exception:
                split_bounds_override = []
            skip_chapter_norm: set[str] = set()
            try:
                skip_chapter_norm = set(getattr(self, '_remux_chapter_skip_paths', None) or set())
            except Exception:
                skip_chapter_norm = set()
            for i in range(n):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                conf = confs[i]
                mkv_path = paths[i]
                try:
                    if skip_chapter_norm and os.path.normcase(os.path.normpath(mkv_path)) in skip_chapter_norm:
                        print(
                            f'{self.t("[chapter-debug] ")}{self.t("skip chapters (remux failed or split-check for this output): ")}{mkv_path}'
                        )
                        done += 1
                        self._progress(int(done / max(total_mkv, 1) * 1000))
                        continue
                except Exception:
                    pass
                mpls_key = str(conf.get('selected_mpls') or '').strip()
                if not mpls_key:
                    continue
                mpls_path = mpls_key if mpls_key.lower().endswith('.mpls') else mpls_key + '.mpls'
                if mpls_key not in rows_cache:
                    ch = Chapter(mpls_path)
                    rows_cache[mpls_key] = sum(map(len, ch.mark_info.values()))
                rows = rows_cache[mpls_key]
                total_end = rows + 1
                if i < len(split_bounds_override):
                    s, e = split_bounds_override[i]
                else:
                    s = int(conf.get('start_at_chapter') or conf.get('chapter_index') or 1)
                    if conf.get('end_at_chapter'):
                        e = int(conf.get('end_at_chapter') or total_end)
                    elif i + 1 < len(confs):
                        e = int(confs[i + 1].get('start_at_chapter') or confs[i + 1].get('chapter_index') or total_end)
                    else:
                        e = total_end
                s = max(1, min(s, total_end))
                e = max(s + 1, min(e, total_end))
                self._write_remux_segment_chapter_txt(mpls_path, s, e, chapter_txt)
                MKV(mkv_path).add_chapter(self.checked)
                done += 1
                self._progress(int(done / max(total_mkv, 1) * 1000))
        self._progress(1000)

    @staticmethod
    def _parse_timecode_to_sec(raw: str) -> Optional[float]:
        s = str(raw or '').strip()
        if not s:
            return None
        m = re.match(r'^(\d+):([0-5]?\d):([0-5]?\d(?:\.\d+)?)$', s)
        if not m:
            return None
        try:
            h = int(m.group(1))
            mi = int(m.group(2))
            sec = float(m.group(3))
            return h * 3600.0 + mi * 60.0 + sec
        except Exception:
            return None

    @staticmethod
    def _split_parts_windows_from_mkvmerge_one_line(line: str) -> list[tuple[float, float]]:
        raw = (line or '').strip()
        if not raw:
            return []
        m = re.search(r'--split\s+("([^"]+)"|\'([^\']+)\'|(\S+))', raw)
        if not m:
            return []
        spec = (m.group(2) or m.group(3) or m.group(4) or '').strip()
        low = spec.lower()
        if not low.startswith('parts:'):
            return []
        payload = spec[6:].strip()
        if not payload or '{' in payload or '}' in payload:
            return []
        out: list[tuple[float, float]] = []
        for seg in [x.strip() for x in payload.split(',') if x.strip()]:
            if '-' not in seg:
                continue
            a_raw, b_raw = seg.split('-', 1)
            a = _svc_cls()._parse_timecode_to_sec(a_raw)
            b = _svc_cls()._parse_timecode_to_sec(b_raw)
            if a is None or b is None:
                continue
            if b <= a + 1e-6:
                continue
            out.append((a, b))
        return out

    @staticmethod
    def _split_parts_windows_from_mkvmerge_cmd(cmd: str, *, mpls_stem: Optional[str] = None) -> list[tuple[float, float]]:
        """Parse ``--split parts:`` time windows; newline-split ``remux_cmd``, optional ``mpls_stem`` filters lines."""
        lines = _svc_cls()._remux_cmd_shell_lines(cmd)
        if not lines:
            return []
        filt = (mpls_stem or '').strip()
        if len(lines) == 1:
            return _svc_cls()._split_parts_windows_from_mkvmerge_one_line(lines[0])
        acc: list[tuple[float, float]] = []
        for ln in lines:
            if filt:
                st = _svc_cls()._mkvmerge_line_source_mpls_stem(ln)
                if st.lower() != filt.lower():
                    continue
            acc.extend(_svc_cls()._split_parts_windows_from_mkvmerge_one_line(ln))
        if acc:
            return acc
        if filt:
            for ln in lines:
                w = _svc_cls()._split_parts_windows_from_mkvmerge_one_line(ln)
                if w:
                    return w
        return []

    @staticmethod
    def _mkvmerge_line_source_mpls_stem(line: str) -> str:
        """Playlist stem (e.g. ``00001``) from the last ``.mpls`` path token on one mkvmerge command line."""
        line = (line or '').strip()
        if not line:
            return ''
        named = re.findall(r'["\']([^"\']+\.(?:mpls|MPLS))["\']', line)
        if named:
            return os.path.splitext(os.path.basename(named[-1]))[0]
        bare = re.findall(r'(?:^|\s)((?:[A-Za-z]:)?[^\s"\']+\.(?:mpls|MPLS))(?=\s|$)', line, re.I)
        if bare:
            return os.path.splitext(os.path.basename(bare[-1]))[0]
        return ''

    @staticmethod
    def _chapter_split_bounds_from_multi_line_remux_cmd(
            cmd0: str, confs: list[dict[str, object]],
    ) -> list[tuple[int, int]]:
        """
        When ``main_remux_cmd`` has multiple lines (separate mkvmerge invocations), map each line's
        ``--split parts:`` windows to episode rows in order: match playlist stem on the line to
        ``selected_mpls``, then convert time windows to chapter bounds on that playlist.
        """
        lines = _svc_cls()._remux_cmd_shell_lines(cmd0)
        if len(lines) <= 1:
            return []
        bounds_out: list[tuple[int, int]] = []
        ci = 0
        for ln in lines:
            wins = _svc_cls()._split_parts_windows_from_mkvmerge_one_line(ln)
            stem_ln = _svc_cls()._mkvmerge_line_source_mpls_stem(ln)
            if not wins and '--split' in ln.lower():
                cuts_ln = _svc_cls()._split_chapters_ints_from_mkvmerge_one_line(ln)
                sub_confs: list[dict[str, object]] = []
                for c in confs:
                    raw_m = str(c.get('selected_mpls') or '').strip()
                    sc = os.path.splitext(os.path.basename(raw_m.replace('\\', '/')))[0]
                    if stem_ln and sc and stem_ln.lower() != sc.lower():
                        continue
                    sub_confs.append(c)
                if stem_ln and not sub_confs:
                    continue
                if not sub_confs:
                    sub_confs = list(confs)
                sub_confs.sort(key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 0))
                mpath = ''
                for c in sub_confs:
                    kk = str(c.get('selected_mpls') or '').strip()
                    cand = kk if kk.lower().endswith('.mpls') else (kk + '.mpls' if kk else '')
                    if cand and os.path.isfile(cand):
                        mpath = cand
                        break
                if cuts_ln and mpath:
                    wins = _svc_cls()._time_windows_from_split_chapter_numbers(mpath, cuts_ln)
                if not wins and mpath and sub_confs:
                    wins = _svc_cls()._episode_float_windows_from_config_bounds(mpath, sub_confs)
            if not wins:
                continue
            for w0, w1 in wins:
                placed = False
                j = ci
                while j < len(confs):
                    conf = confs[j]
                    raw_m = str(conf.get('selected_mpls') or '').strip()
                    stem_c = os.path.splitext(os.path.basename(raw_m.replace('\\', '/')))[0]
                    if stem_ln and stem_c and stem_ln.lower() != stem_c.lower():
                        j += 1
                        continue
                    mpls_key = raw_m
                    mpls_path = mpls_key if mpls_key.lower().endswith('.mpls') else (mpls_key + '.mpls' if mpls_key else '')
                    if not mpls_path or not os.path.isfile(mpls_path):
                        j += 1
                        continue
                    bb = _svc_cls()._chapter_bounds_from_split_windows(mpls_path, [(w0, w1)])
                    if bb:
                        bounds_out.append(bb[0])
                    ci = j + 1
                    placed = True
                    break
                if not placed:
                    break
        return bounds_out

    @staticmethod
    def _chapter_bounds_from_split_windows(mpls_path: str, windows: list[tuple[float, float]]) -> list[tuple[int, int]]:
        if not mpls_path or (not windows):
            return []
        chapter = Chapter(mpls_path)
        _i2m, i2o = get_index_to_m2ts_and_offset(chapter)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        offsets = [float(i2o.get(i, 0.0)) for i in range(1, rows + 1)]
        eps = 1e-3

        def _first_idx_ge(val: float) -> int:
            for idx, off in enumerate(offsets, start=1):
                if off >= val - eps:
                    return idx
            return total_end

        bounds: list[tuple[int, int]] = []
        for w0, w1 in windows:
            s = _first_idx_ge(float(w0))
            e = _first_idx_ge(float(w1))
            if e <= s:
                e = min(total_end, s + 1)
            bounds.append((s, e))
        return bounds

    def _add_chapter_to_mkv_by_duration(
            self,
            mkv_files: list[str],
            table: Optional[QTableWidget] = None,
            selected_mpls: Optional[list[tuple[str, str]]] = None,
            cancel_event: Optional[threading.Event] = None,
    ) -> None:
        mkv_index = 0

        def _vol_from_name(p: str) -> Optional[int]:
            m = re.search(r'BD_Vol_(\d{3})', os.path.basename(p or ''))
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None

        mkv_files = sorted(mkv_files, key=self._mkv_sort_key)
        current_target_vol = _vol_from_name(mkv_files[0]) if mkv_files else None
        if selected_mpls is not None:
            iterator = ((folder, Chapter(selected_mpls_no_ext + '.mpls'), selected_mpls_no_ext)
                        for folder, selected_mpls_no_ext in selected_mpls)
        else:
            if table is None:
                return
            iterator = self.select_mpls_from_table(table)

        for folder, chapter, selected_mpls in iterator:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            while mkv_index < len(mkv_files):
                v = _vol_from_name(mkv_files[mkv_index])
                if current_target_vol is None or v is None or v == current_target_vol:
                    break
                mkv_index += 1
            if mkv_index >= len(mkv_files):
                break
            duration = MKV(mkv_files[mkv_index]).get_duration()
            print(f'{self.t("folder: ")}{folder}')
            print(f'{self.t("in_out_time: ")}{chapter.in_out_time}')
            print(f'{self.t("mark_info: ")}{chapter.mark_info}')
            print(f'{self.t("Episode: ")}{mkv_index + 1}, {self.t("Duration: ")}{duration}')

            play_item_duration_time_sum = 0
            episode_duration_time_sum = 0
            chapter_id = 0
            chapter_text = []
            volume_done = False
            for ref_to_play_item_id in range(len(chapter.in_out_time)):
                mark_timestamps = chapter.mark_info.get(ref_to_play_item_id) or []
                if volume_done:
                    break
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                clip_information_filename, in_time, out_time = chapter.in_out_time[ref_to_play_item_id]
                for mark_timestamp in mark_timestamps:
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    real_time = play_item_duration_time_sum + (
                            mark_timestamp - in_time) / 45000 - episode_duration_time_sum
                    if abs(real_time - duration) < 0.1:
                        with open(f'chapter.txt', 'w', encoding='utf-8-sig') as f:
                            f.write('\n'.join(chapter_text))
                        chapter_id = 0
                        episode_duration_time_sum += real_time
                        real_time = 0
                        mkv = MKV(mkv_files[mkv_index])
                        mkv.add_chapter(self.checked)
                        self._progress(int((mkv_index + 1) / len(mkv_files) * 1000))
                        mkv_index += 1
                        if mkv_index >= len(mkv_files):
                            volume_done = True
                            break
                        next_vol = _vol_from_name(mkv_files[mkv_index])
                        if current_target_vol is not None and next_vol is not None and next_vol != current_target_vol:
                            volume_done = True
                            break
                        duration = MKV(mkv_files[mkv_index]).get_duration()
                        print(f'{self.t("Episode: ")}{mkv_index + 1}, {self.t("Duration: ")}{duration}')
                        chapter_text.clear()

                    chapter_id += 1
                    append_ogm_chapter_lines(chapter_text, chapter_id, max(0.0, float(real_time)))
                play_item_duration_time_sum += (out_time - in_time) / 45000

            with open(f'chapter.txt', 'w', encoding='utf-8-sig') as f:
                f.write('\n'.join(chapter_text))
            if mkv_index < len(mkv_files):
                this_vol = _vol_from_name(mkv_files[mkv_index])
                if current_target_vol is None or this_vol is None or this_vol == current_target_vol:
                    mkv = MKV(mkv_files[mkv_index])
                    mkv.add_chapter(self.checked)
                    self._progress(int((mkv_index + 1) / len(mkv_files) * 1000))
                    mkv_index += 1
            current_target_vol = None
            if mkv_index < len(mkv_files):
                current_target_vol = _vol_from_name(mkv_files[mkv_index])

        self._progress(1000)

    def add_chapter_to_mkv(
            self,
            mkv_files,
            table: Optional[QTableWidget] = None,
            selected_mpls: Optional[list[tuple[str, str]]] = None,
            cancel_event: Optional[threading.Event] = None,
            configuration: Optional[dict[int, dict[str, int | str]]] = None,
    ):
        """Apply chapters to each episode MKV from configuration (remux / encode).

        For an episode with ``start_at_chapter=11`` and ``end_at_chapter=17``, writes six
        entries ``Chapter 01``..``Chapter 06`` at times 0 and ``offset(j)-offset(11)`` for
        MPLS marks ``j`` = 11..16 (new ordinal = ``j - 10`` in that example).
        """
        cfg = configuration if configuration is not None else self.configuration
        if cfg:
            self._add_chapter_to_mkv_from_configuration(mkv_files, cfg, cancel_event=cancel_event)
        else:
            self._add_chapter_to_mkv_by_duration(mkv_files, table, selected_mpls, cancel_event=cancel_event)

    def completion(self):  # complete Blu-ray folder; remove temporary files
        """Finalize folder layout after processing and clean temporary artifacts."""
        if self.checked:
            for folder in self.bluray_folders:
                bdmv = os.path.join(folder, 'BDMV')
                backup = os.path.join(bdmv, 'BACKUP')
                if os.path.exists(backup):
                    for item in os.listdir(backup):
                        if not os.path.exists(os.path.join(bdmv, item)):
                            if os.path.isdir(os.path.join(backup, item)):
                                shutil.copytree(os.path.join(backup, item), os.path.join(bdmv, item))
                            else:
                                shutil.copy(os.path.join(backup, item), os.path.join(bdmv, item))
                for item in 'AUXDATA', 'BDJO', 'JAR', 'META':
                    if not os.path.exists(os.path.join(bdmv, item)):
                        os.mkdir(os.path.join(bdmv, item))
        for tmp_folder in self.tmp_folders:
            try:
                force_remove_folder(tmp_folder)
            except:
                pass
        if os.path.exists('chapter.txt'):
            try:
                force_remove_file('chapter.txt')
            except:
                pass
        if os.path.exists('mkvinfo.txt'):
            try:
                force_remove_file('mkvinfo.txt')
            except:
                pass
        if os.path.exists('info.json'):
            try:
                force_remove_file('info.json')
            except:
                pass
        if os.path.exists('.meta'):
            try:
                force_remove_file('.meta')
            except:
                pass
        print_terminal_line('[BluraySubtitle] completion(): cleanup finished.')

    @staticmethod
    def _sp_output_is_episode_linked(output_name: str) -> bool:
        n = output_name.strip().replace('\\', '/')
        if n.lower().startswith('sps/'):
            return False
        return os.path.basename(n).upper().startswith('EP')

    def _conf_key_matching_episode_basename(
            self,
            basename: str,
            episode_output_names: list[str],
            configuration: dict[int, dict[str, int | str]],
    ):
        def _sort_key_conf(k: object) -> int:
            try:
                return int(k)  # type: ignore[arg-type]
            except Exception:
                return 0

        for key in sorted(configuration.keys(), key=_sort_key_conf):
            try:
                ki = int(key)
            except Exception:
                continue
            if ki < 0 or ki >= len(episode_output_names):
                continue
            cell = (episode_output_names[ki] or '').strip()
            if os.path.basename(cell.replace('\\', '/')) == basename:
                return key
        return None

    @staticmethod
    def _absolute_selected_mpls_from_conf_row(conf: dict[str, int | str], playlist_dir: str) -> str:
        smain = str(conf.get('selected_mpls') or '').strip()
        if not smain:
            return ''
        if os.path.isabs(smain) or ('/' in smain.replace('\\', '/')):
            return os.path.normpath(smain if smain.lower().endswith('.mpls') else smain + '.mpls')
        base = os.path.basename(smain.replace('\\', '/'))
        if not base.lower().endswith('.mpls'):
            base = base + '.mpls'
        if playlist_dir and os.path.isdir(playlist_dir):
            return os.path.normpath(os.path.join(playlist_dir, base))
        return ''

    def _compute_mkv_id_to_m2ts_pid_core(self, mp: str, mcfg: dict[str, object]) -> dict[int, int]:
        """Mux-slot index -> M2TS PID for first play-item m2ts: video (optional indices or first stream), then audio, then subtitle."""
        main_audio_idx = [str(x) for x in (mcfg.get('audio') or [])]
        main_sub_idx = [str(x) for x in (mcfg.get('subtitle') or [])]
        raw_vid = mcfg.get('video')
        main_video_idx = [str(x) for x in raw_vid] if isinstance(raw_vid, list) else []
        try:
            ch_m = Chapter(mp)
            idx_to_m2ts_m, _ = get_index_to_m2ts_and_offset(ch_m)
            if not idx_to_m2ts_m:
                return {}
            fk_m = sorted(idx_to_m2ts_m.keys())[0]
            stream_dir_m = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(mp)), 'STREAM'))
            first_m2ts_main = os.path.join(stream_dir_m, idx_to_m2ts_m[fk_m])
        except Exception:
            return {}
        if not os.path.isfile(first_m2ts_main):
            return {}
        streams_m = _svc_cls()._m2ts_track_streams(first_m2ts_main)
        by_idx: dict[str, int] = {}
        for s in streams_m or []:
            if not isinstance(s, dict):
                continue
            ix = str(s.get('index') or '').strip()
            if not ix:
                continue
            pid = _svc_cls()._stream_service_id(s)
            if pid is None:
                continue
            ctype = str(s.get('codec_type') or '').strip().lower()
            if ctype == 'subtitles':
                ctype = 'subtitle'
            if ctype not in ('audio', 'subtitle', 'video'):
                continue
            by_idx[ix] = int(pid)
        out: dict[int, int] = {}
        slot = 0
        if main_video_idx:
            for idx in main_video_idx:
                p = by_idx.get(str(idx).strip())
                if p is not None:
                    out[slot] = int(p)
                    slot += 1
        else:
            for s in streams_m or []:
                if not isinstance(s, dict):
                    continue
                if str(s.get('codec_type') or '').strip().lower() != 'video':
                    continue
                p = _svc_cls()._stream_service_id(s)
                if p is not None:
                    out[slot] = int(p)
                    slot += 1
                    break
        for group in (main_audio_idx, main_sub_idx):
            for idx in group:
                p = by_idx.get(str(idx).strip())
                if p is not None:
                    out[slot] = int(p)
                    slot += 1
        return out

    def _compute_mkv_id_to_m2ts_pid_for_main_mpls(self, mpls_path: str) -> dict[int, int]:
        """Mux-slot -> M2TS PID for episode main MPLS (video slot + configured audio + subtitle)."""
        mp = os.path.normpath(str(mpls_path or '').strip())
        if not mp.lower().endswith('.mpls'):
            mp = mp + '.mpls'
        tracks_cfg = getattr(self, 'track_selection_config', {}) or {}
        if not isinstance(tracks_cfg, dict):
            tracks_cfg = {}
        mcfg = tracks_cfg.get(f'main::{mp}') or {}
        return self._compute_mkv_id_to_m2ts_pid_core(mp, mcfg)

    @staticmethod
    def _ident_muxable_track_count(ident_ep: dict) -> int:
        """video + audio + subtitles entries in mkvmerge identify JSON (episode file)."""
        n = 0
        for t in (ident_ep.get('tracks') or []) if isinstance(ident_ep.get('tracks'), list) else []:
            if not isinstance(t, dict):
                continue
            typ = str(t.get('type') or '').strip().lower()
            if typ == 'subtitle':
                typ = 'subtitles'
            if typ in ('video', 'audio', 'subtitles'):
                n += 1
        return n

    @staticmethod
    def _episode_ident_track_type(ident_ep: dict, tid: int) -> str:
        """mkvmerge track ``type`` for ``tid`` in episode identify JSON (lowercase; subtitle -> subtitles)."""
        for t in (ident_ep.get('tracks') or []) if isinstance(ident_ep.get('tracks'), list) else []:
            if not isinstance(t, dict):
                continue
            try:
                if int(t.get('id')) != int(tid):
                    continue
            except Exception:
                continue
            typ = str(t.get('type') or '').strip().lower()
            if typ == 'subtitle':
                return 'subtitles'
            return typ
        return ''

    @staticmethod
    def _episode_sp_mux_mkv_cache_key(episode_mkv: str) -> str:
        return os.path.normcase(os.path.normpath(os.path.abspath(episode_mkv)))

    @staticmethod
    def _mkvmerge_ident_transport_pid(props: object) -> Optional[int]:
        """MPEG-TS PID from mkvmerge identify JSON (exclude Matroska track ordinals mistaken for PID)."""
        if not isinstance(props, dict):
            return None
        for key in ('stream_id', 'original_transport_stream_id'):
            v = _svc_cls()._int_from_mkvmerge_prop(props.get(key))
            if v is not None and 1 <= int(v) <= 0x1FFF:
                return int(v)
        return None

    @staticmethod
    def _mkvmerge_episode_tid_for_pid(ident_ep: dict, want_pid: int, allowed_types: tuple[str, ...]) -> Optional[int]:
        """Find mkvmerge track id in episode MKV for a Blu-ray transport PID."""
        allow = {x.lower() for x in allowed_types}
        if 'subtitle' in allow:
            allow.add('subtitles')
        fallbacks: list[tuple[int, int]] = []
        for t in (ident_ep.get('tracks') or []) if isinstance(ident_ep.get('tracks'), list) else []:
            if not isinstance(t, dict):
                continue
            typ = str(t.get('type') or '').strip().lower()
            if typ not in allow:
                continue
            try:
                tid = int(t.get('id'))
            except Exception:
                continue
            props = t.get('properties') if isinstance(t.get('properties'), dict) else {}
            got = SubtitleChapterPipelineMixin._mkvmerge_ident_transport_pid(props)
            if got is not None and int(got) == int(want_pid):
                return tid
            sid = _svc_cls()._int_from_mkvmerge_prop(props.get('stream_id'))
            if sid is not None and int(sid) == int(want_pid):
                return tid
        return None

    @staticmethod
    def _episode_ident_tid_transport_pid(ident_ep: dict, tid: int) -> Optional[int]:
        """Transport PID for one mkvmerge track id in episode MKV identify JSON."""
        for t in (ident_ep.get('tracks') or []) if isinstance(ident_ep.get('tracks'), list) else []:
            if not isinstance(t, dict):
                continue
            try:
                if int(t.get('id')) != int(tid):
                    continue
            except Exception:
                continue
            props = t.get('properties') if isinstance(t.get('properties'), dict) else {}
            p = SubtitleChapterPipelineMixin._mkvmerge_ident_transport_pid(props)
            if p is not None:
                return int(p)
            for key in ('stream_id', 'original_transport_stream_id'):
                p = _svc_cls()._int_from_mkvmerge_prop(props.get(key))
                if p is not None:
                    return int(p)
        return None

    @staticmethod
    def _merged_mkv_id_to_m2ts_pid_episode_sp(
            main_map: dict[int, int],
            sp_selected_pids: list[int],
    ) -> dict[int, int]:
        """After EP+SP mux: main playlist slots then SP transport PIDs not already in main (order = sp_selected_pids)."""
        main_vals = set(main_map.values())
        out: dict[int, int] = {i: main_map[i] for i in sorted(main_map.keys())}
        k = len(out)
        for p in sp_selected_pids:
            if p in main_vals:
                continue
            out[k] = int(p)
            k += 1
        return out

    def _mux_episode_linked_sp_mkvmerge(
            self,
            *,
            episode_mkv: str,
            sp_mpls_path: str,
            episode_main_mpls: str,
            cmd_audio_sp: list[str],
            cmd_sub_sp: list[str],
            cancel_event: Optional[threading.Event],
    ) -> bool:
        """Merge episode MKV (FID 0) + SP MPLS (FID 1).

        ``--track-order`` = unique union of (main_mpls_selected_pids + sp_selected_pids), sorted by PID;
        each PID maps to ``0:mkv_id`` if that PID is a value in ``mkv_id_to_m2ts_pid_main`` (key = mkvmerge
        track id), else ``1:track_id`` from ``mkvmerge --identify`` on ``sp_mpls_path``. Episode identify
        is only used to classify ``0:`` entries for ``-a`` / ``-s`` flags.
        """
        em_norm = os.path.normpath(episode_main_mpls)

        try:
            ch_m = Chapter(episode_main_mpls)
            idx_to_m2ts_m, _ = get_index_to_m2ts_and_offset(ch_m)
            if not idx_to_m2ts_m:
                return False
            fk_m = sorted(idx_to_m2ts_m.keys())[0]
            playlist_dir_m = os.path.dirname(episode_main_mpls)
            stream_dir_m = os.path.normpath(os.path.join(os.path.dirname(playlist_dir_m), 'STREAM'))
            first_m2ts_main = os.path.join(stream_dir_m, idx_to_m2ts_m[fk_m])
        except Exception:
            return False
        if not os.path.isfile(first_m2ts_main):
            return False

        ident_ep = _svc_cls()._mkvmerge_identify_json(episode_mkv)

        cache_key = self._episode_sp_mux_mkv_cache_key(episode_mkv)
        _sp_mux_cache = getattr(self, '_episode_sp_mux_last_after_mux_map', None)
        if not isinstance(_sp_mux_cache, dict):
            _sp_mux_cache = {}
            self._episode_sp_mux_last_after_mux_map = _sp_mux_cache
        _prev_mux_map = _sp_mux_cache.get(cache_key)
        _n_ident_muxable = self._ident_muxable_track_count(ident_ep)
        cached_episode_baseline_map: Optional[dict[int, int]] = None
        if (
                isinstance(_prev_mux_map, dict)
                and len(_prev_mux_map) > 0
                and _n_ident_muxable == len(_prev_mux_map)
        ):
            cached_episode_baseline_map = dict(_prev_mux_map)

        ident_sp = _svc_cls()._mkvmerge_identify_json(sp_mpls_path)
        sp_tid_to_pid: dict[int, int] = {}
        sp_tid_to_typ: dict[int, str] = {}
        for t in (ident_sp.get('tracks') or []) if isinstance(ident_sp.get('tracks'), list) else []:
            if not isinstance(t, dict):
                continue
            try:
                tid = int(t.get('id'))
            except Exception:
                continue
            typ = str(t.get('type') or '').strip().lower()
            props = t.get('properties') or {}
            if not isinstance(props, dict):
                props = {}
            pid = SubtitleChapterPipelineMixin._mkvmerge_ident_transport_pid(props)
            if pid is None:
                pid = _svc_cls()._int_from_mkvmerge_prop(props.get('stream_id'))
            if pid is None:
                pid = _svc_cls()._int_from_mkvmerge_prop(props.get('number'))
            if pid is None:
                continue
            if typ not in ('audio', 'subtitles', 'video'):
                continue
            sp_tid_to_pid[tid] = int(pid)
            sp_tid_to_typ[tid] = typ

        sp_selected_pids: list[int] = []
        for tid_str in list(cmd_audio_sp or []) + list(cmd_sub_sp or []):
            try:
                tid_sp = int(str(tid_str).strip())
            except Exception:
                continue
            pid_sp = sp_tid_to_pid.get(tid_sp)
            if pid_sp is not None:
                sp_selected_pids.append(int(pid_sp))

        if cached_episode_baseline_map is not None:
            mkv_map_main: dict[int, int] = dict(cached_episode_baseline_map)
        else:
            mkv_map_main = self._compute_mkv_id_to_m2ts_pid_for_main_mpls(em_norm)
        if not mkv_map_main:
            return False
        main_mpls_selected_pids = [mkv_map_main[i] for i in sorted(mkv_map_main.keys())]

        sp_pid_to_tid: dict[int, int] = {}
        for tid_sp in sorted(sp_tid_to_pid.keys()):
            sp_pid_to_tid.setdefault(int(sp_tid_to_pid[tid_sp]), int(tid_sp))

        ep_pid_to_mkv_id: dict[int, int] = {}
        for mkv_k in sorted(mkv_map_main.keys()):
            ep_pid_to_mkv_id[int(mkv_map_main[mkv_k])] = int(mkv_k)

        episode_pid_values = set(ep_pid_to_mkv_id.keys())
        pids_sorted = sorted(set(main_mpls_selected_pids) | set(sp_selected_pids))
        order_parts: list[str] = []
        for pid in pids_sorted:
            if pid in episode_pid_values:
                order_parts.append(f'0:{ep_pid_to_mkv_id[pid]}')
            else:
                tid_sp = sp_pid_to_tid.get(pid)
                if tid_sp is None:
                    return False
                order_parts.append(f'1:{tid_sp}')
        if not order_parts:
            return False
        order_str = ','.join(order_parts)

        sp_mux_includes_video = False
        af0: list[str] = []
        sf0: list[str] = []
        af1: list[str] = []
        sf1: list[str] = []
        for part in order_parts:
            seg = part.split(':', 1)
            if len(seg) != 2:
                continue
            try:
                fid_o = int(seg[0])
                tid_o = int(seg[1])
            except Exception:
                continue
            if fid_o == 0:
                ty_e = self._episode_ident_track_type(ident_ep, tid_o)
                if ty_e == 'video':
                    continue
                if ty_e == 'audio':
                    af0.append(str(tid_o))
                elif ty_e in ('subtitles', 'subtitle'):
                    sf0.append(str(tid_o))
            else:
                ty_s = str(sp_tid_to_typ.get(tid_o, '') or '').lower()
                if ty_s == 'video':
                    sp_mux_includes_video = True
                elif ty_s == 'audio':
                    af1.append(str(tid_o))
                elif ty_s in ('subtitles', 'subtitle'):
                    sf1.append(str(tid_o))

        stem, ext = os.path.splitext(episode_mkv)
        tmp_out = f'{stem}.tmp{ext}'
        try:
            if os.path.isfile(tmp_out):
                force_remove_file(tmp_out)
        except Exception:
            pass

        exe = MKV_MERGE_PATH or 'mkvmerge'
        ui_arg = mkvtoolnix_ui_language_arg().strip()
        cmd_parts: list[str] = [f'"{exe}"']
        if ui_arg:
            cmd_parts.append(ui_arg)
        cmd_parts.extend(['-o', f'"{tmp_out}"'])
        if af0:
            cmd_parts.extend(['-a', ','.join(af0)])
        if sf0:
            cmd_parts.extend(['-s', ','.join(sf0)])
        cmd_parts.append(f'"{episode_mkv}"')
        if not sp_mux_includes_video:
            cmd_parts.extend(['-d', '!0'])
        if af1:
            cmd_parts.extend(['-a', ','.join(af1)])
        if sf1:
            cmd_parts.extend(['-s', ','.join(sf1)])
        cmd_parts.append(f'"{sp_mpls_path}"')
        cmd_parts.extend(['--track-order', order_str])
        cmd = ' '.join(cmd_parts)

        print(f'[episode-sp-mux] mkvmerge: {cmd}')

        chapter_tmp = ''
        chapters_saved_ok = False
        try:
            fd, chapter_tmp = tempfile.mkstemp(suffix='.xml', prefix='ep_sp_chapters_')
            os.close(fd)
            ex_exe = MKV_EXTRACT_PATH or 'mkvextract'
            ui_ex = mkvtoolnix_ui_language_arg().strip()
            ex_cmd_parts = [f'"{ex_exe}"']
            if ui_ex:
                ex_cmd_parts.append(ui_ex)
            ex_cmd_parts.extend([f'"{episode_mkv}"', 'chapters', '--simple', f'"{chapter_tmp}"'])
            ex_cmd = ' '.join(ex_cmd_parts)
            if subprocess.Popen(ex_cmd, shell=True).wait() == 0:
                if os.path.isfile(chapter_tmp) and os.path.getsize(chapter_tmp) > 0:
                    chapters_saved_ok = True
            if not chapters_saved_ok:
                try:
                    force_remove_file(chapter_tmp)
                except Exception:
                    pass
                chapter_tmp = ''
        except Exception:
            chapter_tmp = ''
            chapters_saved_ok = False

        if cancel_event and cancel_event.is_set():
            if chapter_tmp:
                try:
                    force_remove_file(chapter_tmp)
                except Exception:
                    pass
            raise _Cancelled()
        ret = subprocess.Popen(cmd, shell=True).wait()
        if ret != 0 or (not os.path.isfile(tmp_out)):
            try:
                force_remove_file(tmp_out)
            except Exception:
                pass
            if chapter_tmp:
                try:
                    force_remove_file(chapter_tmp)
                except Exception:
                    pass
            return False
        try:
            force_remove_file(episode_mkv)
        except Exception:
            pass
        try:
            os.rename(tmp_out, episode_mkv)
        except Exception:
            try:
                force_remove_file(tmp_out)
            except Exception:
                pass
            if chapter_tmp:
                try:
                    force_remove_file(chapter_tmp)
                except Exception:
                    pass
            return False

        try:
            pe_exe = MKV_PROP_EDIT_PATH or 'mkvpropedit'
            ui_pe = mkvtoolnix_ui_language_arg().strip()
            clr_parts = [f'"{pe_exe}"']
            if ui_pe:
                clr_parts.append(ui_pe)
            clr_parts.extend([f'"{episode_mkv}"', '--chapters', '""'])
            subprocess.Popen(' '.join(clr_parts), shell=True).wait()
            if chapters_saved_ok and chapter_tmp and os.path.isfile(chapter_tmp):
                rst_parts = [f'"{pe_exe}"']
                if ui_pe:
                    rst_parts.append(ui_pe)
                rst_parts.extend([f'"{episode_mkv}"', '--chapters', f'"{chapter_tmp}"'])
                subprocess.Popen(' '.join(rst_parts), shell=True).wait()
        except Exception:
            pass
        finally:
            if chapter_tmp:
                try:
                    force_remove_file(chapter_tmp)
                except Exception:
                    pass

        mkv_after = self._merged_mkv_id_to_m2ts_pid_episode_sp(mkv_map_main, sp_selected_pids)
        _sp_mux_cache[cache_key] = dict(mkv_after)
        return True

    def _create_sp_mkvs_from_entries(
            self,
            bdmv_index_conf: dict[int, list[dict[str, int | str]]],
            sp_entries: list[dict[str, int | str]],
            sps_folder: str,
            cancel_event: Optional[threading.Event] = None,
            progress_cb: Optional[Callable[[int, str], None]] = None,
            dst_folder: Optional[str] = None,
            episode_output_names: Optional[list[str]] = None,
            configuration_full: Optional[dict[int, dict[str, int | str]]] = None,
    ) -> list[tuple[int, str]]:
        sp_index_by_bdmv: dict[int, int] = {}
        created: list[tuple[int, str]] = []
        cfg_full = configuration_full if configuration_full is not None else getattr(self, 'configuration', {}) or {}
        episode_names = list(episode_output_names or [])
        single_volume = bool(getattr(self, 'movie_mode', False) and len(bdmv_index_conf) == 1)
        selected_counts: dict[int, int] = {}
        for e in sp_entries:
            try:
                b = int(e.get('bdmv_index') or 0)
            except Exception:
                b = 0
            if b <= 0:
                continue
            if not bool(e.get('selected', True)):
                continue
            selected_counts[b] = selected_counts.get(b, 0) + 1
        for entry_idx, entry in enumerate(sp_entries, start=1):
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            try:
                sp_bdmv_index = int(entry.get('bdmv_index') or 0)
            except Exception:
                sp_bdmv_index = 0
            if sp_bdmv_index <= 0:
                continue

            bdmv_vol = '0' * (3 - len(str(sp_bdmv_index))) + str(sp_bdmv_index)
            bdmv_root = str(entry.get('bdmv_root') or '').strip()
            confs = bdmv_index_conf.get(sp_bdmv_index)
            main_mpls_path = ''
            playlist_dir = ''
            stream_dir = ''

            def _resolve_main_mpls_from_confs() -> str:
                if not confs:
                    return ''
                smain = str(confs[0].get('selected_mpls') or '').strip()
                if not smain:
                    return ''
                if os.path.isabs(smain) or ('/' in smain.replace('\\', '/')):
                    return smain if smain.lower().endswith('.mpls') else smain + '.mpls'
                base = os.path.basename(smain.replace('\\', '/'))
                if not base.lower().endswith('.mpls'):
                    base = base + '.mpls'
                if playlist_dir and os.path.isdir(playlist_dir):
                    return os.path.normpath(os.path.join(playlist_dir, base))
                return base if base.lower().endswith('.mpls') else base + '.mpls'

            if bdmv_root and os.path.isdir(os.path.normpath(os.path.join(bdmv_root, 'BDMV', 'PLAYLIST'))):
                root_n = os.path.normpath(bdmv_root)
                playlist_dir = os.path.join(root_n, 'BDMV', 'PLAYLIST')
                stream_dir = os.path.join(root_n, 'BDMV', 'STREAM')
                main_mpls_path = _resolve_main_mpls_from_confs()
            elif confs:
                smain = str(confs[0].get('selected_mpls') or '').strip()
                if smain:
                    main_mpls_path = smain if smain.lower().endswith('.mpls') else smain + '.mpls'
                    playlist_dir = os.path.normpath(os.path.dirname(main_mpls_path))
                    stream_dir = os.path.normpath(os.path.join(os.path.dirname(playlist_dir), 'STREAM'))
            if not playlist_dir or not os.path.isdir(playlist_dir):
                continue

            mpls_file = str(entry.get('mpls_file') or '').strip()
            m2ts_file = str(entry.get('m2ts_file') or '').strip()
            m2ts_type = str(entry.get('m2ts_type') or '').strip()
            output_name = str(entry.get('output_name') or '').strip()
            selected = bool(entry.get('selected', True))
            if (not selected) or (not output_name):
                continue

            sp_mkv_path = ''
            src_path = ''
            first_m2ts_for_lang = ''
            use_chapter_language = False
            if mpls_file:
                sp_index_by_bdmv[sp_bdmv_index] = sp_index_by_bdmv.get(sp_bdmv_index, 0) + 1
                width = max(2, len(str(max(selected_counts.get(sp_bdmv_index, 1), 1))))
                sp_no = str(sp_index_by_bdmv[sp_bdmv_index]).zfill(width)
                sp_mkv_path = os.path.join(sps_folder, f'BD_Vol_{bdmv_vol}_SP{sp_no}.mkv')
                src_path = os.path.join(playlist_dir, mpls_file)
                use_chapter_language = True
                try:
                    ch_lang = Chapter(src_path)
                    index_to_m2ts, _ = get_index_to_m2ts_and_offset(ch_lang)
                    if index_to_m2ts:
                        first_key = sorted(index_to_m2ts.keys())[0]
                        first_m2ts_for_lang = os.path.join(stream_dir, index_to_m2ts[first_key])
                except Exception:
                    first_m2ts_for_lang = ''
                try:
                    is_repeated_menu, repeated_m2ts = _svc_cls()._detect_repeated_single_m2ts_mpls(src_path)
                    if is_repeated_menu and repeated_m2ts:
                        src_path = os.path.join(stream_dir, repeated_m2ts)
                        first_m2ts_for_lang = src_path
                        # Menu-like repeated MPLS should remux the real m2ts directly.
                        use_chapter_language = False
                except Exception:
                    pass
            else:
                m2ts_files = [x.strip() for x in m2ts_file.split(',') if x.strip()]
                if m2ts_files:
                    m2ts_name = m2ts_files[0]
                    src_path = os.path.join(stream_dir, m2ts_name)
                    ext = '.mka' if _svc_cls()._is_audio_only_media(src_path) else '.mkv'
                    sp_mkv_path = os.path.join(sps_folder, f'BD_Vol_{bdmv_vol}_{m2ts_name[:-5]}{ext}')
                    first_m2ts_for_lang = src_path

            if not src_path or not sp_mkv_path:
                continue
            config_key = _svc_cls()._sp_track_key_from_entry(entry)
            try:
                tracks_cfg = getattr(self, 'track_selection_config', {}) or {}
                if (isinstance(tracks_cfg, dict)
                        and mpls_file
                        and config_key not in tracks_cfg):
                    main_key = f'main::{os.path.normpath(main_mpls_path)}' if main_mpls_path else ''
                    if main_key and main_key in tracks_cfg:
                        mcfg = tracks_cfg.get(main_key) or {}
                        tracks_cfg[config_key] = {
                            'audio': list(mcfg.get('audio') or []),
                            'subtitle': list(mcfg.get('subtitle') or []),
                        }
            except Exception:
                pass
            pid_to_lang: dict[int, str] = {}
            if mpls_file:
                try:
                    ch_pid = Chapter(os.path.join(playlist_dir, mpls_file))
                    ch_pid.get_pid_to_language()
                    pid_to_lang = ch_pid.pid_to_lang
                except Exception:
                    pid_to_lang = {}
            if use_chapter_language and not pid_to_lang:
                try:
                    ch_pid = Chapter(src_path)
                    ch_pid.get_pid_to_language()
                    pid_to_lang = ch_pid.pid_to_lang
                except Exception:
                    pid_to_lang = {}
            if (not pid_to_lang) and src_path.lower().endswith('.m2ts'):
                try:
                    pid_to_lang = self._pid_lang_from_m2ts_track_info(self._read_m2ts_track_info(src_path))
                except Exception:
                    pid_to_lang = {}
            copy_audio_track, copy_sub_track = self._select_tracks_for_source(
                src_path,
                pid_to_lang,
                config_key=config_key
            )
            cmd_audio_track = list(copy_audio_track)
            cmd_sub_track = list(copy_sub_track)
            if str(src_path).lower().endswith('.mpls'):
                cmd_audio_track, cmd_sub_track = _svc_cls()._map_selected_tracks_to_mpls_track_ids(
                    src_path, copy_audio_track, copy_sub_track
                )

            sp_playlist_mpls = ''
            if mpls_file:
                sp_playlist_mpls = os.path.normpath(os.path.join(playlist_dir, mpls_file))
            if (mpls_file and dst_folder and episode_output_names is not None
                    and sp_playlist_mpls and os.path.isfile(sp_playlist_mpls)
                    and self._sp_output_is_episode_linked(output_name)):
                bn = os.path.basename(output_name.strip().replace('\\', '/'))
                ck = self._conf_key_matching_episode_basename(bn, episode_names, cfg_full)
                if ck is not None:
                    conf_ep = cfg_full.get(ck) or {}
                    episode_main_mpls = self._absolute_selected_mpls_from_conf_row(conf_ep, playlist_dir)
                    episode_mkv = os.path.normpath(os.path.join(dst_folder, bn))
                    ca_ep, cs_ep = _svc_cls()._map_selected_tracks_to_mpls_track_ids(
                        sp_playlist_mpls, copy_audio_track, copy_sub_track)
                    if (episode_main_mpls and os.path.isfile(episode_main_mpls) and os.path.isfile(episode_mkv)):
                        ok = self._mux_episode_linked_sp_mkvmerge(
                            episode_mkv=episode_mkv,
                            sp_mpls_path=sp_playlist_mpls,
                            episode_main_mpls=os.path.normpath(episode_main_mpls),
                            cmd_audio_sp=list(ca_ep),
                            cmd_sub_sp=list(cs_ep),
                            cancel_event=cancel_event,
                        )
                        if ok and os.path.isfile(episode_mkv):
                            created.append((entry_idx, episode_mkv))
                            if progress_cb:
                                progress_cb(entry_idx, episode_mkv)
                continue

            if output_name:
                rel = output_name.strip().replace('\\', '/')
                if single_volume:
                    subdir, base_only = os.path.split(rel)
                    base_only = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', base_only)
                    rel = f'{subdir}/{base_only}' if subdir else base_only
                sp_mkv_path = os.path.normpath(os.path.join(sps_folder, rel))
            elif single_volume:
                base_name = os.path.basename(sp_mkv_path)
                base_name = re.sub(rf'(?i)^BD_Vol_{bdmv_vol}_', '', base_name)
                sp_mkv_path = os.path.join(sps_folder, base_name)

            # Special image / per-clip PNG folder modes from UI output name.
            if output_name.lower().endswith('.png') or ('.' not in os.path.basename(output_name)):
                # Match table3 m2ts_file column (comma-separated basenames); do not replace from MPLS
                # chapter/play-item expansion — that can disagree with the table and force folder mode.
                m2ts_list = [os.path.basename(x.strip()) for x in m2ts_file.split(',') if x.strip()]
                m2ts_list = list(dict.fromkeys([x for x in m2ts_list if x]))
                if (not m2ts_list) and mpls_file and str(src_path).lower().endswith('.mpls'):
                    try:
                        ch = Chapter(src_path)
                        idx_to_m2ts, _ = get_index_to_m2ts_and_offset(ch)
                        for k in sorted(idx_to_m2ts.keys()):
                            v = str(idx_to_m2ts.get(k) or '').strip()
                            if v and v not in m2ts_list:
                                m2ts_list.append(v)
                    except Exception:
                        pass
                uniq_m2ts = m2ts_list
                # Only igs_menu uses dedicated IGS parser for folder output.
                if (not mpls_file) and (m2ts_type == 'igs_menu') and len(uniq_m2ts) == 1 and (
                        '.' not in os.path.basename(output_name)):
                    folder_out = sp_mkv_path
                    os.makedirs(folder_out, exist_ok=True)
                    try:
                        if not stream_dir or not os.path.isdir(stream_dir):
                            stream_dir = os.path.normpath(os.path.join(os.path.dirname(playlist_dir), 'STREAM'))
                        src_menu = os.path.join(stream_dir, uniq_m2ts[0])
                        M2TS(src_menu).extract_igs_menu_png(folder_out)
                    except Exception:
                        print_exc_terminal()
                    created.append((entry_idx, folder_out))
                    if progress_cb:
                        progress_cb(entry_idx, folder_out)
                    continue
                if not stream_dir or not os.path.isdir(stream_dir):
                    stream_dir = os.path.normpath(os.path.join(os.path.dirname(playlist_dir), 'STREAM'))
                # Multiple distinct clips: extract folder of PNGs even if UI wrongly used .png (single-file) suffix.
                if len(uniq_m2ts) > 1:
                    folder_out = os.path.normpath(
                        os.path.join(sps_folder, os.path.splitext(output_name)[0])
                    )
                    os.makedirs(folder_out, exist_ok=True)
                    width = max(2, len(str(max(len(uniq_m2ts), 1))))
                    for n, m2 in enumerate(uniq_m2ts, start=1):
                        src_frame = os.path.join(stream_dir, m2)
                        stem = os.path.splitext(os.path.basename(m2))[0]
                        out_png = os.path.join(folder_out, f'{str(n).zfill(width)}-{stem}.png')
                        subprocess.Popen(
                            f'"{FFMPEG_PATH}" -y -i "{src_frame}" -frames:v 1 -update 1 "{out_png}"',
                            shell=True
                        ).wait()
                    created.append((entry_idx, folder_out))
                    if progress_cb:
                        progress_cb(entry_idx, folder_out)
                    continue
                if output_name.lower().endswith('.png'):
                    if uniq_m2ts:
                        src_frame = os.path.join(stream_dir, uniq_m2ts[0])
                        subprocess.Popen(
                            f'"{FFMPEG_PATH}" -y -i "{src_frame}" -frames:v 1 -update 1 "{sp_mkv_path}"',
                            shell=True
                        ).wait()
                        if os.path.exists(sp_mkv_path):
                            created.append((entry_idx, sp_mkv_path))
                            if progress_cb:
                                progress_cb(entry_idx, sp_mkv_path)
                    continue
                folder_out = sp_mkv_path
                os.makedirs(folder_out, exist_ok=True)
                width = max(2, len(str(max(len(uniq_m2ts), 1))))
                for n, m2 in enumerate(uniq_m2ts, start=1):
                    src_frame = os.path.join(stream_dir, m2)
                    stem = os.path.splitext(os.path.basename(m2))[0]
                    out_png = os.path.join(folder_out, f'{str(n).zfill(width)}-{stem}.png')
                    subprocess.Popen(
                        f'"{FFMPEG_PATH}" -y -i "{src_frame}" -frames:v 1 -update 1 "{out_png}"',
                        shell=True
                    ).wait()
                created.append((entry_idx, folder_out))
                if progress_cb:
                    progress_cb(entry_idx, folder_out)
                continue

            # Single selected audio track with raw extension: extract directly.
            out_ext = os.path.splitext(sp_mkv_path)[1].lower()
            if out_ext not in ('.mkv', '.mka'):
                if len(copy_audio_track) == 1 and len(copy_sub_track) == 0:
                    map_idx = str(copy_audio_track[0]).strip()
                    if out_ext == '.flac':
                        src_for_flac = first_m2ts_for_lang or src_path
                        _svc_cls()._compress_audio_stream_to_flac(src_for_flac, map_idx, sp_mkv_path)
                    else:
                        subprocess.Popen(
                            f'"{FFMPEG_PATH}" -y -i "{src_path}" -map 0:{map_idx} -c copy "{sp_mkv_path}"',
                            shell=True
                        ).wait()
                    if os.path.exists(sp_mkv_path):
                        created.append((entry_idx, sp_mkv_path))
                        if progress_cb:
                            progress_cb(entry_idx, sp_mkv_path)
                continue

            out_dir_mkv = os.path.dirname(os.path.normpath(sp_mkv_path))
            if out_dir_mkv:
                os.makedirs(out_dir_mkv, exist_ok=True)
            ch_stem = os.path.splitext(os.path.basename(sp_mkv_path))[0]
            chapter_txt = os.path.join(out_dir_mkv or '.', f'{ch_stem}.chapter.txt')

            # Check if this is a custom chapter segment (e.g. chapter_3_to_chapter_6, beginning_to_chapter_4, chapter_33_to_ending)
            custom_chapter = False
            custom_parts = ''
            if re.search(r'(beginning|chapter_\d+)_to_(chapter_\d+|ending)', output_name, re.IGNORECASE):
                if not (main_mpls_path and os.path.isfile(main_mpls_path)):
                    print(
                        f'[sp-mux-debug] skip custom chapter: main_mpls_path missing or not a file '
                        f'(got {main_mpls_path!r}); entry bdmv={sp_bdmv_index} mpls_file={mpls_file!r} '
                        f'bdmv_root={bdmv_root!r} conf0_mpls={(confs[0].get("selected_mpls") if confs else None)!r}'
                    )
                    custom_chapter = False
                else:
                    custom_chapter = True
                    self._write_custom_chapter_for_segment(main_mpls_path, chapter_txt, output_name)
                    print(
                        f'{self.t("[chapter-debug] ")}{self.t("custom SP chapter file ready: ")}{chapter_txt} ({output_name})')
                    try:
                        ch_tmp = Chapter(main_mpls_path)
                        _i2m, i2o = get_index_to_m2ts_and_offset(ch_tmp)
                        rows_tmp = sum(map(len, ch_tmp.mark_info.values()))
                        total_end = rows_tmp + 1
                        m = re.search(r'(beginning|chapter_(\d+))_to_(chapter_(\d+)|ending)', output_name, re.IGNORECASE)
                        if m:
                            start_idx = 1 if (m.group(1) or '').lower() == 'beginning' else int(m.group(2) or 1)
                            end_idx = total_end if (m.group(3) or '').lower() == 'ending' else int(m.group(4) or total_end)
                            start_idx = max(1, min(start_idx, total_end))
                            end_idx = max(start_idx + 1, min(end_idx, total_end))
                            st = get_time_str(float(i2o.get(start_idx, 0.0)))
                            ed = get_time_str(float(ch_tmp.get_total_time() if end_idx >= total_end else i2o.get(end_idx,
                                                                                                                 ch_tmp.get_total_time())))
                            if st == '0':
                                st = '00:00:00.000'
                            if ed == '0':
                                ed = '00:00:00.000'
                            custom_parts = f'{st}-{ed}'
                    except Exception:
                        custom_parts = ''

            mux_chapter_txt = ''
            if use_chapter_language or custom_chapter:
                if not custom_chapter:
                    try:
                        offs = self._write_chapter_txt_from_mpls(src_path, chapter_txt)
                        if not offs or (len(offs) == 1 and offs[0] == 0.0):
                            force_remove_file(chapter_txt)
                            print(
                                f'{self.t("[chapter-debug] ")}{self.t("remove trivial SP chapter file: ")}{chapter_txt}')
                            mux_chapter_txt = ''
                        else:
                            mux_chapter_txt = chapter_txt
                    except Exception:
                        print_exc_terminal()
                        mux_chapter_txt = ''
                else:
                    mux_chapter_txt = chapter_txt
                split_custom = (f'--split parts:{custom_parts} ' if custom_parts else '')
                chapters_arg = f'--chapters "{mux_chapter_txt}" ' if mux_chapter_txt else ''
                cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} '
                       f'{split_custom}'
                       f'{chapters_arg}'
                       f'-o "{sp_mkv_path}" '
                       f'{("-a " + ",".join(cmd_audio_track)) if cmd_audio_track else ""} '
                       f'{("-s " + ",".join(cmd_sub_track)) if cmd_sub_track else ""} '
                       f'"{src_path}"')
            else:
                cmd = (f'"{MKV_MERGE_PATH}" {mkvtoolnix_ui_language_arg()} -o "{sp_mkv_path}" '
                       f'{("-a " + ",".join(cmd_audio_track)) if cmd_audio_track else ""} '
                       f'{("-s " + ",".join(cmd_sub_track)) if cmd_sub_track else ""} '
                       f'"{src_path}"')
            ret_sp = subprocess.Popen(cmd, shell=True).wait()
            sp_ok = os.path.isfile(sp_mkv_path)
            if not sp_ok and (use_chapter_language or custom_chapter):
                stem_out, ext_out = os.path.splitext(sp_mkv_path)
                for suf in ('-001', '-01'):
                    alt_out = f'{stem_out}{suf}{ext_out}'
                    if os.path.isfile(alt_out):
                        sp_ok = True
                        break
            mux_failed = (ret_sp != 0 or not sp_ok)
            if mux_failed and str(src_path).lower().endswith('.mpls'):
                try:
                    n_fc = len(Chapter(src_path).in_out_time or [])
                except Exception:
                    n_fc = 0
                # Full-playlist concat does not reproduce ``--split parts:custom_parts`` windows from main MPLS.
                # Use m2ts indices from edit-tracks (_select_tracks_for_source), not cmd_audio_track / remux -a/-s.
                if n_fc > 1 and not (custom_chapter and str(custom_parts).strip()):
                    if self._try_remux_mpls_track_aligned_concat(
                            os.path.normpath(src_path),
                            os.path.normpath(sp_mkv_path),
                            copy_audio_track,
                            copy_sub_track,
                            '',
                            cancel_event=cancel_event,
                    ):
                        sp_ok = os.path.isfile(sp_mkv_path)
                        mux_failed = not sp_ok
            if mux_failed:
                try:
                    force_remove_file(chapter_txt)
                except Exception:
                    pass
                continue
            if use_chapter_language and sp_mkv_path.lower().endswith('.mkv') and os.path.exists(sp_mkv_path):
                try:
                    print(f'{self.t("[chapter-debug] ")}{self.t("clear chapters: ")}{sp_mkv_path}')
                    subprocess.Popen(
                        f'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{sp_mkv_path}" --chapters ""',
                        shell=True).wait()
                    if os.path.exists(chapter_txt):
                        print(
                            f'{self.t("[chapter-debug] ")}{self.t("apply chapter file: ")}{chapter_txt} -> {sp_mkv_path}')
                        subprocess.Popen(
                            f'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{sp_mkv_path}" --chapters "{chapter_txt}"',
                            shell=True).wait()
                        force_remove_file(chapter_txt)
                        print(f'{self.t("[chapter-debug] ")}{self.t("remove temporary chapter file: ")}{chapter_txt}')
                except:
                    pass
            if os.path.exists(sp_mkv_path):
                created.append((entry_idx, sp_mkv_path))
                if progress_cb:
                    progress_cb(entry_idx, sp_mkv_path)
        return created

    def _write_chapter_txt_from_mpls(self, mpls_path: str, chapter_txt_path: str) -> list[float]:
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        mpls_duration = chapter.get_total_time()

        offsets = []
        offset = 0
        for ref_to_play_item_id in range(len(in_out_time)):
            mark_timestamps = mark_info.get(ref_to_play_item_id) or []
            for mark_timestamp in mark_timestamps:
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    offsets.append(off)
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000

        offs = []
        for off in offsets:
            if off not in offs:
                offs.append(off)

        lines: list[str] = []
        for i, off in enumerate(offs, start=1):
            append_ogm_chapter_lines(lines, i, off)
        os.makedirs(os.path.dirname(chapter_txt_path) or '.', exist_ok=True)
        with open(chapter_txt_path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(lines) + ('\n' if lines else ''))
        print(
            f'{self.t("[chapter-debug] ")}{self.t("full chapter file written: ")}{chapter_txt_path} '
            f'(mpls={os.path.basename(mpls_path)} entries={len(lines) // 2})'
        )
        return offs

    def _get_chapter_offsets(self, mpls_path: str) -> list[float]:
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        mpls_duration = chapter.get_total_time()

        offsets = []
        offset = 0
        for ref_to_play_item_id in range(len(in_out_time)):
            mark_timestamps = mark_info.get(ref_to_play_item_id) or []
            for mark_timestamp in mark_timestamps:
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    offsets.append(off)
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000

        offs = []
        for off in offsets:
            if off not in offs:
                offs.append(off)
        return offs

    def _write_custom_chapter_for_segment(self, mpls_path: str, chapter_txt_path: str, output_name: str):
        """Parse SP suffix like beginning_to_chapter_4, chapter_33_to_chapter_40, chapter_33_to_ending; same bounds as --split parts."""
        if not (mpls_path and str(mpls_path).strip()):
            print(f'[sp-mux-debug] _write_custom_chapter_for_segment: empty mpls_path output_name={output_name!r}')
            return
        if not os.path.isfile(mpls_path):
            print(f'[sp-mux-debug] _write_custom_chapter_for_segment: not a file mpls_path={mpls_path!r}')
            return
        m = re.search(r'(beginning|chapter_(\d+))_to_(chapter_(\d+)|ending)', output_name, re.IGNORECASE)
        if not m:
            return
        chapter = Chapter(mpls_path)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        start_idx = 1 if (m.group(1) or '').lower() == 'beginning' else int(m.group(2) or 1)
        g3 = (m.group(3) or '').lower()
        if g3 == 'ending':
            end_idx = total_end
        else:
            end_idx = int(m.group(4) or total_end)
        start_idx = max(1, min(start_idx, total_end))
        end_idx = max(start_idx + 1, min(end_idx, total_end))
        self._write_remux_segment_chapter_txt(mpls_path, start_idx, end_idx, chapter_txt_path)

    def _mkv_sort_key(self, p: str):
        name = os.path.basename(p)
        m = re.search(r'BD_Vol_(\d{3})', name)
        vol = int(m.group(1)) if m else 9999
        m2 = re.search(r'-(\d{3})\.mkv$', name, re.IGNORECASE)
        seg = int(m2.group(1)) if m2 else 0
        return vol, seg, name.lower()
