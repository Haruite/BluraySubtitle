"""Target module for output naming and track methods of `BluraySubtitleGUI`."""
import json
import os
import re
import subprocess
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QTableWidgetItem, QTableWidget, QToolButton

from src.bdmv import M2TS, Chapter, pid_to_lang_from_m2ts_path
from src.core import REMUX_LABELS, DIY_REMUX_LABELS, ENCODE_LABELS, CURRENT_UI_LANGUAGE, FFPROBE_PATH, ENCODE_SP_LABELS, \
    DIY_SP_LABELS
from src.runtime.services import BluraySubtitle
from src.runtime.services_split.lifecycle_and_configuration import LifecycleConfigurationMixin
from src.runtime.services_split.misc_workflows import (
    _movie_main_duration_by_bdmv_from_mpls_paths,
    _movie_sp_duration_matches_main,
)
from .gui_base import BluraySubtitleGuiBase

_M2TS_DETAIL_SEGMENT_RE = re.compile(r'^(.+?)\(([^)]+)-([^)]+)\)\s*$')


def _parse_m2ts_detail_time_to_seconds(s: str) -> float:
    try:
        parts = [p for p in str(s or '').strip().split(':') if p != '']
        if not parts:
            return 0.0
        val = 0.0
        for n in parts:
            val = val * 60.0 + float(n)
        return val
    except Exception:
        return 0.0


def parse_m2ts_file_detail_segments(detail: str) -> list[tuple[str, float, float]]:
    """Parse ``clip.m2ts(HH:MM:SS.mmm-HH:MM:SS.mmm),...`` into (basename, start_sec, end_sec)."""
    text = str(detail or '').strip()
    if not text:
        return []
    segments: list[tuple[str, float, float]] = []
    for part in text.split(','):
        piece = part.strip()
        if not piece:
            continue
        m = _M2TS_DETAIL_SEGMENT_RE.match(piece)
        if not m:
            return []
        name = m.group(1).strip()
        start_sec = _parse_m2ts_detail_time_to_seconds(m.group(2))
        end_sec = _parse_m2ts_detail_time_to_seconds(m.group(3))
        segments.append((name, start_sec, end_sec))
    return segments


def m2ts_file_detail_segments_contained_in(sp_detail: str, episode_detail: str, *, eps: float = 0.05) -> bool:
    """True when every SP clip/time window lies inside some matching clip window on the episode row."""
    sp_segs = parse_m2ts_file_detail_segments(sp_detail)
    if not sp_segs:
        return False
    ep_segs = parse_m2ts_file_detail_segments(episode_detail)
    if not ep_segs:
        return False
    for name, s0, s1 in sp_segs:
        if s1 <= s0 + eps:
            continue
        matched = False
        for en, a0, a1 in ep_segs:
            if en != name:
                continue
            if s0 + eps >= a0 and s1 <= a1 + eps:
                matched = True
                break
        if not matched:
            return False
    return True


def filter_m2ts_file_detail_by_basenames(detail: str, basenames: list[str]) -> str:
    """Keep only ``clip.m2ts(start-end)`` segments whose basename is in ``basenames``."""
    wanted = {
        os.path.basename(str(b or '')).strip().lower()
        for b in basenames
        if str(b or '').strip()
    }
    if not wanted:
        return str(detail or '').strip()
    parts: list[str] = []
    for part in str(detail or '').split(','):
        piece = part.strip()
        if not piece:
            continue
        head = piece.split('(', 1)[0].strip().lower()
        if head in wanted:
            parts.append(piece)
    return ','.join(parts)


class OutputTracksMixin(BluraySubtitleGuiBase):
    def _resolve_output_name_from_mpls(self, mpls_no_ext: str) -> str:
        raw = str(mpls_no_ext or '').strip()
        if not raw:
            return ''
        mpls_full = raw if raw.lower().endswith('.mpls') else raw + '.mpls'
        try:
            folder = os.path.normpath(os.path.join(os.path.dirname(os.path.normpath(mpls_full)), '..', '..'))
        except Exception:
            folder = ''
        if (not folder) or (not os.path.isdir(os.path.join(folder, 'BDMV'))):
            try:
                folder = os.path.normpath(self.bdmv_folder_path.text().strip()) if hasattr(self, 'bdmv_folder_path') else ''
            except Exception:
                folder = ''
        stem = raw[:-5] if raw.lower().endswith('.mpls') else raw
        stem = os.path.normpath(stem)
        return LifecycleConfigurationMixin.resolve_disc_output_title(folder, stem)

    def _build_episode_output_name_map(self, configuration: dict[int, dict[str, int | str]]) -> dict[int, str]:
        if not configuration:
            return {}
        total = len(configuration)
        width = len(str(total))
        by_bdmv: dict[int, list[int]] = {}
        for sub_index, con in configuration.items():
            try:
                bdmv_index = int(con.get('bdmv_index') or 0)
            except Exception:
                bdmv_index = 0
            by_bdmv.setdefault(bdmv_index, []).append(sub_index)
        for bdmv_index in by_bdmv:
            by_bdmv[bdmv_index].sort(key=lambda i: int(configuration[i].get('chapter_index') or 0))

        result: dict[int, str] = {}
        for sub_index in sorted(configuration.keys()):
            con = configuration[sub_index]
            try:
                bdmv_index = int(con.get('bdmv_index') or 0)
            except Exception:
                bdmv_index = 0
            bdmv_vol = f'{bdmv_index:03d}'
            rows_in_vol = by_bdmv.get(bdmv_index, [])
            try:
                seq_in_vol = rows_in_vol.index(sub_index) + 1
            except Exception:
                seq_in_vol = 1
            output_name = str(con.get('disc_output_name') or '').strip()
            if not output_name:
                output_name = self._resolve_output_name_from_mpls(str(con.get('selected_mpls') or ''))
            ep_no = f'EP{str(sub_index + 1).zfill(width)}'
            result[sub_index] = f'{ep_no} {output_name}_BD_Vol_{bdmv_vol}-{seq_in_vol:03d}.mkv'
        return result

    def _get_episode_output_names_from_table2(self) -> list[str]:
        names: list[str] = []
        function_id = self.get_selected_function_id()
        if function_id == 3:
            col = REMUX_LABELS.index('output_name')
        elif function_id == 5:
            return names
        elif function_id == 4:
            col = ENCODE_LABELS.index('output_name')
        else:
            return names
        auto_name_map: dict[int, str] = {}
        try:
            if function_id in (3, 4, 5) and (not self._is_movie_mode()):
                conf = (
                    getattr(self, '_last_configuration_34', None)
                    or getattr(self, 'configuration', None)
                )
                if isinstance(conf, dict) and conf:
                    auto_name_map = self._build_episode_output_name_map(conf)
        except Exception:
            auto_name_map = {}
        exact_remux_name = function_id == 3
        for i in range(self.table2.rowCount()):
            item = self.table2.item(i, col)
            text = item.text() if exact_remux_name and item else (
                item.text().strip() if item and item.text() else ''
            )
            if (not text) and i in auto_name_map and not exact_remux_name:
                text = auto_name_map.get(i, '')
            names.append(text)
        return names

    def _get_episode_subtitle_languages_from_table2(self) -> list[str]:
        langs: list[str] = []
        function_id = self.get_selected_function_id()
        if function_id == 3:
            col = REMUX_LABELS.index('language')
        elif function_id == 5:
            col = DIY_REMUX_LABELS.index('language')
        elif function_id == 4:
            col = ENCODE_LABELS.index('language')
        else:
            return langs
        default_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        for i in range(self.table2.rowCount()):
            w = self.table2.cellWidget(i, col)
            if isinstance(w, QComboBox):
                v = w.currentText().strip()
            else:
                it = self.table2.item(i, col)
                v = it.text().strip() if it and it.text() else ''
            langs.append(v or default_lang)
        return langs

    def _video_frame_count(self, media_path: str) -> int:
        if not media_path or not os.path.exists(media_path):
            return -1
        if str(media_path).lower().endswith('.m2ts'):
            try:
                return int(M2TS(media_path).get_total_frames())
            except Exception:
                return -1
        cmd = (f'"{FFPROBE_PATH}" -v error -count_frames -select_streams v:0 '
               f'-show_entries stream=nb_read_frames,nb_frames -of json "{media_path}"')
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if p.returncode != 0:
                return -1
            data = json.loads(p.stdout or '{}')
            streams = data.get('streams') or []
            if not streams:
                return 0
            s0 = streams[0] if isinstance(streams[0], dict) else {}
            for k in ('nb_read_frames', 'nb_frames'):
                try:
                    v = int(str(s0.get(k) or '').strip())
                    if v >= 0:
                        return v
                except Exception:
                    pass
        except Exception:
            pass
        return -1

    def _table3_get_sp_entry_for_row(self, row: int) -> dict[str, int | str]:
        bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
        mpls_col = ENCODE_SP_LABELS.index('mpls_file')
        m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
        type_col = ENCODE_SP_LABELS.index('m2ts_type')
        out_col = ENCODE_SP_LABELS.index('output_name')
        sel_col = ENCODE_SP_LABELS.index('select')
        bdmv_item = self.table3.item(row, bdmv_col)
        mpls_item = self.table3.item(row, mpls_col)
        m2ts_item = self.table3.item(row, m2ts_col)
        type_item = self.table3.item(row, type_col)
        out_item = self.table3.item(row, out_col)
        sel_item = self.table3.item(row, sel_col)
        try:
            bi = int(bdmv_item.text()) if bdmv_item and bdmv_item.text() else 0
        except Exception:
            bi = 0
        bdmv_root = ''
        if bi > 0:
            try:
                bdmv_root = str(self._get_disc_root_for_bdmv_index(bi) or '').strip()
            except Exception:
                bdmv_root = ''
        det_txt = ''
        try:
            if 'm2ts_file_detail' in ENCODE_SP_LABELS:
                dc = ENCODE_SP_LABELS.index('m2ts_file_detail')
                dit = self.table3.item(row, dc)
                det_txt = dit.text().strip() if dit and dit.text() else ''
        except Exception:
            det_txt = ''
        return {
            'bdmv_index': bi,
            'mpls_file': mpls_item.text().strip() if mpls_item and mpls_item.text() else '',
            'm2ts_file': m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else '',
            'm2ts_file_detail': det_txt,
            'm2ts_type': type_item.text().strip() if type_item and type_item.text() else '',
            'output_name': out_item.text().strip() if out_item and out_item.text() else '',
            'selected': bool(
                sel_item and sel_item.flags() & Qt.ItemFlag.ItemIsEnabled and sel_item.checkState() == Qt.CheckState.Checked),
            'bdmv_root': bdmv_root,
        }

    def _m2ts_file_detail_from_mpls_path(self, mpls_path: str) -> str:
        """Full path to ``*.mpls``; detail string follows README ``in_out_time`` + first_pts formula."""
        mp = str(mpls_path or '').strip()
        if not mp or not os.path.isfile(mp):
            return ''
        return BluraySubtitle.m2ts_file_detail_from_mpls_playlist(mp)

    def _m2ts_file_detail_for_sp_table_row(self, row: int, labels: Optional[list[str]] = None) -> str:
        if row < 0 or not hasattr(self, 'table3') or not self.table3:
            return ''
        labels = labels or (
            DIY_SP_LABELS if self.get_selected_function_id() == 5 else ENCODE_SP_LABELS
        )
        if 'm2ts_file_detail' not in labels:
            return ''
        try:
            bdmv_col = labels.index('bdmv_index')
            mpls_col = labels.index('mpls_file')
            m2ts_col = labels.index('m2ts_file')
        except Exception:
            return ''
        bdmv_item = self.table3.item(row, bdmv_col)
        try:
            bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text() else 0
        except Exception:
            bdmv_index = 0
        mpls_file = self.table3.item(row, mpls_col).text().strip() if self.table3.item(row, mpls_col) else ''
        m2ts_text = self.table3.item(row, m2ts_col).text().strip() if self.table3.item(row, m2ts_col) else ''
        m2ts_files = self._split_m2ts_files(m2ts_text)
        return self._sp_m2ts_detail_for_entry(bdmv_index, mpls_file, m2ts_files)

    def _table2_labels_for_current_mode(self):
        fid = self.get_selected_function_id()
        if fid == 3:
            return REMUX_LABELS
        if fid == 4:
            return ENCODE_LABELS
        if fid == 5:
            return DIY_REMUX_LABELS
        return None

    def _track_id_sets_for_config_key(
        self, key: str, *, mpls_path_fallback: str = '',
    ) -> tuple[set[str], set[str]]:
        cfg = getattr(self, '_track_selection_config', {}) or {}
        if isinstance(cfg, dict) and key in cfg and isinstance(cfg[key], dict):
            tr = cfg[key]
            return (
                {str(x) for x in (tr.get('audio') or []) if str(x).strip()},
                {str(x) for x in (tr.get('subtitle') or []) if str(x).strip()},
            )
        mp = str(mpls_path_fallback or '').strip()
        if mp and os.path.isfile(mp):
            try:
                pair = self._default_track_lists_for_mpls_path(mp)
                if pair:
                    return {str(x) for x in pair[0]}, {str(x) for x in pair[1]}
            except Exception:
                pass
        return set(), set()

    def _track_selection_contained_in(self, sub_key: str, sup_key: str, *,
                                    sub_mpls_fallback: str = '', sup_mpls_fallback: str = '') -> bool:
        sa, ss = self._track_id_sets_for_config_key(sub_key, mpls_path_fallback=sub_mpls_fallback)
        ma, ms = self._track_id_sets_for_config_key(sup_key, mpls_path_fallback=sup_mpls_fallback)
        if sa and not sa.issubset(ma):
            return False
        if ss and not ss.issubset(ms):
            return False
        return True

    def _iter_table2_episode_m2ts_details(self, bdmv_index: int):
        """Yield (m2ts_file_detail, main_mpls_full_path) for table2 rows on this disc."""
        labels = self._table2_labels_for_current_mode()
        if not labels or 'm2ts_file_detail' not in labels:
            return
        try:
            det_col = labels.index('m2ts_file_detail')
            bdmv_col = labels.index('bdmv_index')
        except Exception:
            return
        bi = int(bdmv_index)
        for r in range(self.table2.rowCount()):
            try:
                b_item = self.table2.item(r, bdmv_col)
                row_bdmv = int(b_item.text().strip()) if b_item and b_item.text() else 0
            except Exception:
                row_bdmv = 0
            if row_bdmv != bi:
                continue
            it_det = self.table2.item(r, det_col)
            det = (it_det.text() if it_det and it_det.text() else '').strip()
            if not det:
                continue
            mpls_stem = ''
            try:
                if b_item:
                    mpls_stem = str(b_item.data(Qt.ItemDataRole.UserRole) or '').strip()
            except Exception:
                mpls_stem = ''
            if not mpls_stem:
                try:
                    mpls_stem = str(self._bdmv_to_first_main_mpls_from_table1().get(bi, '') or '').strip()
                except Exception:
                    mpls_stem = ''
            if not mpls_stem:
                yield det, ''
                continue
            mpls_full = mpls_stem if mpls_stem.lower().endswith('.mpls') else f'{mpls_stem}.mpls'
            playlist_dir = self._get_playlist_dir_for_bdmv_index(bi)
            if playlist_dir and not os.path.isabs(mpls_full):
                mpls_full = os.path.normpath(os.path.join(playlist_dir, os.path.basename(mpls_full)))
            else:
                mpls_full = os.path.normpath(mpls_full)
            yield det, mpls_full

    def _m2ts_detail_for_stream_on_disc_playlists(
        self, bdmv_index: int, m2ts_files: list[str],
    ) -> str:
        """Match orphan STREAM clips to a playlist ``in_out_time`` window before whole-file fallback."""
        playlist_dir = self._get_playlist_dir_for_bdmv_index(int(bdmv_index))
        if not playlist_dir or not os.path.isdir(playlist_dir):
            return ''
        segments: list[str] = []
        for bn in m2ts_files or []:
            bn = os.path.basename(str(bn or '').strip())
            if not bn:
                continue
            found = ''
            try:
                for mpls in sorted(os.listdir(playlist_dir)):
                    if not str(mpls).lower().endswith('.mpls'):
                        continue
                    mp = os.path.normpath(os.path.join(playlist_dir, mpls))
                    if not os.path.isfile(mp):
                        continue
                    full = BluraySubtitle.m2ts_file_detail_from_mpls_playlist(mp).strip()
                    if not full:
                        continue
                    filt = filter_m2ts_file_detail_by_basenames(full, [bn])
                    if filt:
                        found = filt
                        break
            except Exception:
                found = ''
            if found:
                segments.extend([p.strip() for p in found.split(',') if p.strip()])
        return ','.join(segments)

    def _sp_m2ts_detail_for_entry(self, bdmv_index: int, mpls_file: str, m2ts_files: list[str]) -> str:
        """SP ``m2ts_file_detail``: MPLS rows use ``in_out_time`` via ``m2ts_file_detail_from_mpls_playlist``."""
        mpls_name = str(mpls_file or '').strip()
        playlist_dir = self._get_playlist_dir_for_bdmv_index(int(bdmv_index))
        if mpls_name and playlist_dir:
            mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_name))
            if os.path.isfile(mpls_path):
                try:
                    detail = BluraySubtitle.m2ts_file_detail_from_mpls_playlist(mpls_path).strip()
                    if detail and m2ts_files:
                        detail = filter_m2ts_file_detail_by_basenames(detail, m2ts_files)
                    return detail
                except Exception:
                    return ''
            return ''
        disc_detail = self._m2ts_detail_for_stream_on_disc_playlists(bdmv_index, m2ts_files)
        if disc_detail:
            return disc_detail
        paths: list[str] = []
        stream_dir = self._get_stream_dir_for_bdmv_index(int(bdmv_index))
        for bn in m2ts_files or []:
            bn = str(bn or '').strip()
            if not bn:
                continue
            if stream_dir:
                paths.append(os.path.normpath(os.path.join(stream_dir, bn)))
        if paths:
            try:
                return BluraySubtitle.m2ts_file_detail_for_standalone_m2ts_paths(paths).strip()
            except Exception:
                pass
        return ''

    def _sp_covered_by_table2_movie_row(self, bdmv_index: int, sp_detail: str) -> bool:
        """Movie mode: SP redundant when m2ts_detail equals or is contained in some table2 row (no track check)."""
        sp_detail = str(sp_detail or '').strip()
        if not sp_detail:
            return False
        for ep_detail, _main_mpls in self._iter_table2_episode_m2ts_details(bdmv_index):
            ep_detail = str(ep_detail or '').strip()
            if not ep_detail:
                continue
            if sp_detail == ep_detail:
                return True
            if m2ts_file_detail_segments_contained_in(sp_detail, ep_detail):
                return True
        return False

    def _sp_covered_by_table2_episode_row(
        self, bdmv_index: int, sp_detail: str, sp_track_key: str, *,
        sp_mpls_path: str = '',
    ) -> bool:
        """SP row is redundant when its timeline and tracks are already covered by some table2 episode row."""
        sp_detail = str(sp_detail or '').strip()
        if not sp_detail:
            return False
        if self._is_movie_mode():
            return self._sp_covered_by_table2_movie_row(bdmv_index, sp_detail)
        for ep_detail, main_mpls in self._iter_table2_episode_m2ts_details(bdmv_index):
            if not m2ts_file_detail_segments_contained_in(sp_detail, ep_detail):
                continue
            main_key = f'main::{os.path.normpath(main_mpls)}' if main_mpls else ''
            if not main_key:
                return True
            if self._track_selection_contained_in(
                sp_track_key, main_key,
                sub_mpls_fallback=sp_mpls_path, sup_mpls_fallback=main_mpls,
            ):
                return True
        return False

    def _movie_main_duration_map_from_table1(self) -> dict[int, float]:
        selected_main_by_bdmv: dict[int, list[str]] = {}
        try:
            for r in range(self.table1.rowCount()):
                bdmv_index = int(r + 1)
                root_item = self.table1.item(r, 0)
                root = root_item.text().strip() if root_item and root_item.text() else ''
                if not root:
                    continue
                info = self.table1.cellWidget(r, 2)
                if not isinstance(info, QTableWidget):
                    continue
                paths: list[str] = []
                for i in range(info.rowCount()):
                    btn = info.cellWidget(i, 3)
                    if not (isinstance(btn, QToolButton) and btn.isChecked()):
                        continue
                    it = info.item(i, 0)
                    mpls_file = it.text().strip() if it and it.text() else ''
                    if mpls_file:
                        paths.append(os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_file)))
                if paths:
                    selected_main_by_bdmv[bdmv_index] = paths
        except Exception:
            pass
        return _movie_main_duration_by_bdmv_from_mpls_paths(selected_main_by_bdmv)

    def _apply_table3_uncheck_rows_covered_by_table2(self) -> None:
        """Uncheck auto SP rows whose content is already muxed via a table2 episode row."""
        if not hasattr(self, 'table3') or not self.table3:
            return
        if self.get_selected_function_id() not in (3, 4, 5):
            return
        try:
            sel_col = ENCODE_SP_LABELS.index('select')
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
            det_col = ENCODE_SP_LABELS.index('m2ts_file_detail')
            dur_col = ENCODE_SP_LABELS.index('duration')
        except Exception:
            return
        main_duration_by_bdmv: dict[int, float] = {}
        if self._is_movie_mode():
            main_duration_by_bdmv = self._movie_main_duration_map_from_table1()
        for r in range(self.table3.rowCount()):
            sel_item = self.table3.item(r, sel_col)
            if not sel_item:
                continue
            if not (sel_item.flags() & Qt.ItemFlag.ItemIsEnabled):
                continue
            if str(sel_item.data(Qt.ItemDataRole.UserRole) or '').strip() == 'user':
                continue
            try:
                bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                continue
            mpls_item = self.table3.item(r, mpls_col)
            mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
            m2ts_item = self.table3.item(r, m2ts_col)
            m2ts_text = m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else ''
            det_item = self.table3.item(r, det_col)
            sp_detail = det_item.text().strip() if det_item and det_item.text() else ''
            if not sp_detail:
                sp_detail = self._m2ts_file_detail_for_sp_table_row(r, ENCODE_SP_LABELS).strip()
            entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': m2ts_text, 'output_name': ''}
            sp_key = BluraySubtitle._sp_track_key_from_entry(entry)
            sp_mpls = ''
            if mpls_file:
                playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                if playlist_dir:
                    sp_mpls = os.path.normpath(os.path.join(playlist_dir, mpls_file))
            if self._sp_covered_by_table2_episode_row(bdmv_index, sp_detail, sp_key, sp_mpls_path=sp_mpls):
                sel_item.setCheckState(Qt.CheckState.Unchecked)
                continue
            if self._is_movie_mode():
                main_dur = main_duration_by_bdmv.get(bdmv_index)
                if main_dur is not None:
                    dur_item = self.table3.item(r, dur_col)
                    dur_sec = 0.0
                    if dur_item and dur_item.text().strip():
                        try:
                            parts = [p for p in dur_item.text().strip().split(':') if p != '']
                            for n in parts:
                                dur_sec = dur_sec * 60.0 + float(n)
                        except Exception:
                            dur_sec = 0.0
                    if _movie_sp_duration_matches_main(dur_sec, main_dur):
                        sel_item.setCheckState(Qt.CheckState.Unchecked)

    def _table2_output_name_if_same_m2ts_detail(self, bdmv_index: int, detail_sp: str) -> str:
        labels = self._table2_labels_for_current_mode()
        if not labels or 'm2ts_file_detail' not in labels or 'output_name' not in labels:
            return ''
        d_sp = (detail_sp or '').strip()
        if not d_sp:
            return ''
        try:
            det_col = labels.index('m2ts_file_detail')
            out_col = labels.index('output_name')
            bdmv_col = labels.index('bdmv_index')
        except Exception:
            return ''
        bi = int(bdmv_index)
        for r in range(self.table2.rowCount()):
            try:
                it_b = self.table2.item(r, bdmv_col)
                row_bdmv = int(it_b.text().strip()) if it_b and it_b.text() else 0
            except Exception:
                row_bdmv = 0
            if row_bdmv != bi:
                continue
            it_det = self.table2.item(r, det_col)
            det_t2 = (it_det.text() if it_det and it_det.text() else '').strip()
            if det_t2 != d_sp:
                continue
            it_out = self.table2.item(r, out_col)
            return (it_out.text() if it_out and it_out.text() else '').strip()
        return ''

    def _sp_output_display_path(
        self,
        bdmv_index: int,
        row_r: int,
        candidate_rel: str,
        *,
        detail_override: Optional[str] = None,
        table2_detail_out_map: Optional[dict[str, str]] = None,
    ) -> str:
        cand = (candidate_rel or '').strip().replace('\\', '/')
        if not cand:
            return ''
        if detail_override is not None:
            detail = (detail_override or '').strip()
        else:
            detail = self._m2ts_file_detail_for_sp_table_row(row_r, ENCODE_SP_LABELS).strip()
        if table2_detail_out_map is not None:
            linked = (table2_detail_out_map.get(detail) or '').strip()
        else:
            linked = self._table2_output_name_if_same_m2ts_detail(bdmv_index, detail)
        if linked:
            return linked.replace('\\', '/')
        low = cand.lower()
        if low.startswith('sps/'):
            return cand
        return f'SPs/{cand}'

    def _refresh_table3_m2ts_file_detail(self, only_bdmv_index: Optional[int] = None):
        if not hasattr(self, 'table3') or not self.table3:
            return
        labels = DIY_SP_LABELS if self.get_selected_function_id() == 5 else ENCODE_SP_LABELS
        if 'm2ts_file_detail' not in labels:
            return
        try:
            bdmv_col = labels.index('bdmv_index')
        except Exception:
            return
        for r in range(self.table3.rowCount()):
            if only_bdmv_index is not None:
                try:
                    if int(self.table3.item(r, bdmv_col).text().strip()) != int(only_bdmv_index):
                        continue
                except Exception:
                    continue
            self._sync_sp_table_row_m2ts_column_from_detail(r, labels)

    def _sync_sp_table_row_m2ts_column_from_detail(self, row: int, labels: Optional[list[str]] = None) -> None:
        """Fill ``m2ts_file_detail``; set ``m2ts_file`` from MPLS ``in_out_time`` order (clip stem → ``.m2ts``)."""
        if row < 0 or not hasattr(self, 'table3') or not self.table3:
            return
        labels = labels or (
            DIY_SP_LABELS if self.get_selected_function_id() == 5 else ENCODE_SP_LABELS
        )
        if 'm2ts_file' not in labels or 'm2ts_file_detail' not in labels:
            return
        try:
            det_col = labels.index('m2ts_file_detail')
            m2_col = labels.index('m2ts_file')
            mpls_col = labels.index('mpls_file')
            bdmv_col = labels.index('bdmv_index')
        except Exception:
            return
        try:
            bdmv_index = int(self.table3.item(row, bdmv_col).text().strip())
        except Exception:
            bdmv_index = 0
        mpls_item = self.table3.item(row, mpls_col)
        mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
        playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
        sp_mpls = os.path.normpath(os.path.join(playlist_dir, mpls_file)) if playlist_dir and mpls_file else ''

        txt = self._m2ts_file_detail_for_sp_table_row(row, labels).strip()
        dit = self.table3.item(row, det_col)
        if not dit:
            dit = QTableWidgetItem('')
            self.table3.setItem(row, det_col, dit)
        dit.setText(txt)

        extracted: list[str] = []
        if sp_mpls and os.path.isfile(sp_mpls):
            extracted = list(BluraySubtitle.m2ts_file_basenames_from_mpls_playlist(sp_mpls))
        elif not mpls_file:
            m2ts_text = self.table3.item(row, m2_col).text().strip() if self.table3.item(row, m2_col) else ''
            for f in self._split_m2ts_files(m2ts_text):
                bn = os.path.basename(f.strip())
                if bn.lower().endswith('.m2ts') and bn not in extracted:
                    extracted.append(bn)

        if extracted:
            self.table3.setItem(row, m2_col, QTableWidgetItem(','.join(extracted)))

    def _recompute_sp_output_names(self, only_bdmv_index: Optional[int] = None):
        if not hasattr(self, 'table3') or not self.table3:
            return
        labels = DIY_SP_LABELS if self.get_selected_function_id() == 5 else ENCODE_SP_LABELS
        if 'output_name' not in labels:
            try:
                self._refresh_table3_m2ts_file_detail(only_bdmv_index)
            except Exception:
                pass
            return
        try:
            self._refresh_table3_m2ts_file_detail(only_bdmv_index)
        except Exception:
            pass
        out_col = labels.index('output_name')
        sel_col = labels.index('select')
        bdmv_col = labels.index('bdmv_index')
        mpls_col = labels.index('mpls_file')
        m2ts_col = labels.index('m2ts_file')
        type_col = labels.index('m2ts_type')
        dur_col = labels.index('duration')
        rows_by_vol: dict[int, list[int]] = {}
        for r in range(self.table3.rowCount()):
            try:
                bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                bdmv_index = 0
            rows_by_vol.setdefault(bdmv_index, []).append(r)
        if only_bdmv_index is not None:
            rows_by_vol = {k: v for k, v in rows_by_vol.items() if int(k) == int(only_bdmv_index)}

        t2_by_bdmv: dict[int, dict[str, str]] = {}
        labels_t2 = self._table2_labels_for_current_mode()
        try:
            if labels_t2 and 'm2ts_file_detail' in labels_t2 and 'output_name' in labels_t2:
                # Must not reuse names `out_col` / `det_col`: table2 REMUX_LABELS indices differ from table3
                # ENCODE_SP_LABELS (e.g. output_name is 8 vs 7); overwriting broke SP output → tracks column.
                det_col_t2 = labels_t2.index('m2ts_file_detail')
                out_col_t2 = labels_t2.index('output_name')
                bdmv_col_t2 = labels_t2.index('bdmv_index')
                for r2 in range(self.table2.rowCount()):
                    it_b = self.table2.item(r2, bdmv_col_t2)
                    try:
                        bi = int(it_b.text().strip()) if it_b and it_b.text() else 0
                    except Exception:
                        bi = 0
                    if bi <= 0:
                        continue
                    it_det = self.table2.item(r2, det_col_t2)
                    it_out = self.table2.item(r2, out_col_t2)
                    det_txt = (it_det.text() if it_det and it_det.text() else '').strip()
                    out_txt = (it_out.text() if it_out and it_out.text() else '').strip()
                    if det_txt:
                        t2_by_bdmv.setdefault(bi, {})[det_txt] = out_txt
        except Exception:
            t2_by_bdmv = {}

        sp_detail_cache: dict[tuple[int, str, str], str] = {}
        audio_only_cache: dict[tuple[int, str], bool] = {}
        single_audio_ext_cache: dict[tuple[int, str, str], str] = {}
        single_sub_ext_cache: dict[tuple[int, str, str], str] = {}
        for bdmv_index, rows in rows_by_vol.items():
            selected_rows = []
            for r in rows:
                it = self.table3.item(r, sel_col)
                if it and it.flags() & Qt.ItemFlag.ItemIsEnabled and it.checkState() == Qt.CheckState.Checked:
                    selected_rows.append(r)
            digits = max(2, len(str(max(len(selected_rows), 1))))
            seq = 0
            for r in rows:
                out_item = self.table3.item(r, out_col)
                if not out_item:
                    out_item = QTableWidgetItem('')
                    self.table3.setItem(r, out_col, out_item)

                sel_it = self.table3.item(r, sel_col)
                selected = bool(
                    sel_it and sel_it.flags() & Qt.ItemFlag.ItemIsEnabled and sel_it.checkState() == Qt.CheckState.Checked)
                bdmv_vol = f'{bdmv_index:03d}'
                special = str(out_item.data(Qt.ItemDataRole.UserRole + 2) or '')
                name_suffix = str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '')
                mpls_file = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
                m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                m2ts_type = self.table3.item(r, type_col).text().strip() if self.table3.item(r, type_col) else ''
                m2ts_files = [x.strip() for x in m2ts_text.split(',') if x.strip()]
                m2ts_files_unique = list(dict.fromkeys(m2ts_files))
                if not selected:
                    out_item.setText('')
                    continue
                m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                m2ts_files = [x.strip() for x in m2ts_text.split(',') if x.strip()]
                m2ts_files_unique = list(dict.fromkeys(m2ts_files))
                seq += 1
                detail_key = (int(bdmv_index), str(mpls_file or ''), str(m2ts_text or ''))
                if detail_key not in sp_detail_cache:
                    sp_detail_cache[detail_key] = self._m2ts_file_detail_for_sp_table_row(r, labels).strip()
                detail_row = sp_detail_cache[detail_key]

                def _set_sp_out(rel: str):
                    out_item.setText(self._sp_output_display_path(
                        bdmv_index, r, rel,
                        detail_override=detail_row,
                        table2_detail_out_map=t2_by_bdmv.get(int(bdmv_index)),
                    ))

                sp_no = str(seq).zfill(digits)
                base_name = f'BD_Vol_{bdmv_vol}_SP{sp_no}'
                if not mpls_file and m2ts_files:
                    base_name = f'BD_Vol_{bdmv_vol}_{os.path.splitext(os.path.basename(m2ts_files[0]))[0]}'
                # Preserve custom suffix (e.g. chapter range suffix) across track edits and recompute.
                if (not name_suffix) and mpls_file:
                    try:
                        cur_name = out_item.text().strip().replace('\\', '/')
                        cur_stem = os.path.splitext(cur_name)[0]
                        if cur_stem.lower().startswith('sps/'):
                            cur_stem = cur_stem[4:]
                        m = re.match(r'^BD_Vol_\d+_SP\d+(.*)$', cur_stem)
                        if m and m.group(1):
                            name_suffix = m.group(1)
                            out_item.setData(Qt.ItemDataRole.UserRole + 3, name_suffix)
                    except Exception:
                        pass
                base_with_suffix = f'{base_name}{name_suffix}'
                # Table may list multiple m2ts while scan mis-tagged single_frame (e.g. large clips); folder output matches mux.
                eff_special = special
                if special == 'single_frame' and len(m2ts_files_unique) > 1:
                    eff_special = 'multi_frame'
                    try:
                        out_item.setData(Qt.ItemDataRole.UserRole + 2, 'multi_frame')
                    except Exception:
                        pass
                if eff_special == 'single_frame':
                    _set_sp_out(f'{base_with_suffix}.png')
                    continue
                if eff_special == 'multi_frame':
                    _set_sp_out(f'{base_with_suffix}')
                    continue
                if (not mpls_file) and m2ts_type == 'igs_menu':
                    _set_sp_out(f'{base_with_suffix}')
                    continue
                # Zero-duration menu rows should use folder name (no extension),
                # extracted by extract_igs_menu_png.
                # Keep this robust for both:
                # 1) direct single m2ts rows
                # 2) mpls rows that include multiple one-frame m2ts clips
                if (
                        ((not mpls_file) and len(m2ts_files_unique) == 1)
                        or (mpls_file and len(m2ts_files_unique) > 1)
                ):
                    try:
                        d_item = self.table3.item(r, dur_col)
                        d_sec = self._parse_display_time_to_seconds(d_item.text() if d_item else '')
                    except Exception:
                        d_sec = 0.0
                    if d_sec <= 0.0:
                        _set_sp_out(f'{base_with_suffix}')
                        continue
                key = BluraySubtitle._sp_track_key_from_entry(self._table3_get_sp_entry_for_row(r))
                cfg = getattr(self, '_track_selection_config', {}) or {}
                if not (isinstance(cfg, dict) and key in cfg):
                    # Undetermined multi-m2ts MPLS row: wait for async scan (single_frame / multi_frame)
                    # only when 2 clips; 3+ distinct clips default to normal mux (README) and are not
                    # single-frame galleries.
                    if (
                        mpls_file
                        and len(m2ts_files_unique) > 1
                        and (special == '')
                        and len(m2ts_files_unique) < 3
                    ):
                        out_item.setText('')
                    else:
                        _set_sp_out(f'{base_with_suffix}.mkv')
                    continue
                tr = cfg.get(key, {}) if isinstance(cfg, dict) else {}
                sel_audio = list(tr.get('audio') or [])
                sel_sub = list(tr.get('subtitle') or [])
                if (not sel_audio) and (not sel_sub):
                    # README: no tracks → skip mux; exception: multi-clip MPLS (3+ distinct STREAM files)
                    # still shows default .mkv name so short bonus playlists are not stuck blank.
                    if mpls_file and len(m2ts_files_unique) >= 3:
                        _set_sp_out(f'{base_with_suffix}.mkv')
                    else:
                        out_item.setText('')
                    continue
                is_audio_only = False
                if m2ts_files:
                    src = os.path.join(self._get_stream_dir_for_bdmv_index(bdmv_index), m2ts_files[0])
                    cache_key = (int(bdmv_index), os.path.normpath(src))
                    if cache_key in audio_only_cache:
                        is_audio_only = bool(audio_only_cache[cache_key])
                    else:
                        is_audio_only = BluraySubtitle._is_audio_only_media(src)
                        audio_only_cache[cache_key] = bool(is_audio_only)
                if len(sel_audio) == 1 and len(sel_sub) == 0 and is_audio_only:
                    # Single audio -> extract raw elementary stream.
                    ext = 'audio'
                    if m2ts_files:
                        src = os.path.join(self._get_stream_dir_for_bdmv_index(bdmv_index), m2ts_files[0])
                        ext_cache_key = (int(bdmv_index), os.path.normpath(src), str(sel_audio[0]))
                        if ext_cache_key in single_audio_ext_cache:
                            ext = str(single_audio_ext_cache[ext_cache_key] or 'audio')
                        else:
                            if str(src).lower().endswith('.m2ts'):
                                streams = self._read_m2ts_track_info(src)
                            else:
                                streams = self._read_media_streams_local(src)
                            for s in streams:
                                if str(s.get('codec_type') or '') != 'audio':
                                    continue
                                if str(s.get('index', '')) == str(sel_audio[0]):
                                    c = str(s.get('codec_name') or '').lower()
                                    if c in ('pcm_bluray', 'pcm_s16le', 'pcm_s24le', 'pcm_s32le', 'dts', 'truehd',
                                             'mlp'):
                                        ext = 'flac'
                                    else:
                                        ext = {'aac': 'm4a'}.get(c, c or 'audio')
                                    break
                            single_audio_ext_cache[ext_cache_key] = ext
                    _set_sp_out(f'{base_with_suffix}.{ext}')
                    continue
                if len(sel_audio) > 1 and len(sel_sub) == 0 and is_audio_only:
                    _set_sp_out(f'{base_with_suffix}.mka')
                    continue
                if not mpls_file:
                    if m2ts_type in ('private_or_other', 'mixed_non_video'):
                        out_item.setText('')
                        continue
                    if m2ts_type == 'audio_with_subtitle':
                        _set_sp_out(f'{base_with_suffix}.mka')
                        continue
                    if m2ts_type == 'subtitle_only':
                        if len(sel_sub) <= 0:
                            out_item.setText('')
                            continue
                        if len(sel_sub) == 1:
                            ext = 'sup'
                            if m2ts_files:
                                src = os.path.join(self._get_stream_dir_for_bdmv_index(bdmv_index), m2ts_files[0])
                                ext_cache_key = (int(bdmv_index), os.path.normpath(src), str(sel_sub[0]))
                                if ext_cache_key in single_sub_ext_cache:
                                    ext = str(single_sub_ext_cache[ext_cache_key] or 'sup')
                                else:
                                    streams = self._read_m2ts_track_info(src) if str(src).lower().endswith(
                                        '.m2ts') else self._read_media_streams_local(src)
                                    for s in streams:
                                        if str(s.get('codec_type') or '') not in ('subtitle', 'subtitles'):
                                            continue
                                        if str(s.get('index', '')) == str(sel_sub[0]):
                                            c = str(s.get('codec_name') or '').lower()
                                            if c in ('subrip', 'srt'):
                                                ext = 'srt'
                                            else:
                                                ext = 'sup'
                                            break
                                    single_sub_ext_cache[ext_cache_key] = ext
                            _set_sp_out(f'{base_with_suffix}.{ext}')
                            continue
                        _set_sp_out(f'{base_with_suffix}.mks')
                        continue
                _set_sp_out(f'{base_with_suffix}.mkv')

        try:
            self._refresh_table3_m2ts_file_detail(only_bdmv_index)
        except Exception:
            pass

    def _all_track_ids_from_streams(self, streams: list[dict[str, object]]) -> tuple[list[str], list[str]]:
        audio: list[str] = []
        subtitle: list[str] = []
        for s in streams or []:
            idx = str(s.get('index', '')).strip()
            if idx == '':
                continue
            ctype = str(s.get('codec_type') or '')
            if ctype == 'audio':
                audio.append(idx)
            elif ctype in ('subtitle', 'subtitles'):
                subtitle.append(idx)
        return audio, subtitle

    def _apply_select_all_tracks_to_main_and_sp(self):
        if not hasattr(self, '_track_selection_config') or not isinstance(
                getattr(self, '_track_selection_config', None), dict):
            self._track_selection_config = {}
        if not getattr(self, 'select_all_tracks_checkbox', None) or (not self.select_all_tracks_checkbox.isChecked()):
            return
        if self.get_selected_function_id() == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            try:
                for r in range(self.table2.rowCount()):
                    src = self._get_remux_source_path_from_table2_row(r)
                    if not src or not os.path.exists(src):
                        continue
                    streams = self._read_mkvinfo_tracks(src)
                    a, s = self._all_track_ids_from_streams(streams)
                    self._track_selection_config[f'mkv::{os.path.normpath(src)}'] = {'audio': a, 'subtitle': s}
            except Exception:
                pass
            try:
                if hasattr(self, 'table3') and self.table3:
                    for r in range(self.table3.rowCount()):
                        src = self._get_remux_source_path_from_table3_row(r)
                        if not src or not os.path.exists(src):
                            continue
                        streams = self._read_mkvinfo_tracks(src)
                        a, s = self._all_track_ids_from_streams(streams)
                        self._track_selection_config[f'mkvsp::{os.path.normpath(src)}'] = {'audio': a, 'subtitle': s}
            except Exception:
                pass
            return
        try:
            for row in range(self.table1.rowCount()):
                root_item = self.table1.item(row, 0)
                root = root_item.text().strip() if root_item and root_item.text() else ''
                if not root:
                    continue
                info = self.table1.cellWidget(row, 2)
                if not isinstance(info, QTableWidget):
                    continue
                selected_mpls_path = ''
                for i in range(info.rowCount()):
                    main_btn = info.cellWidget(i, 3)
                    if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                        mpls_item = info.item(i, 0)
                        if mpls_item and mpls_item.text().strip():
                            selected_mpls_path = os.path.normpath(
                                os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip()))
                        break
                if not selected_mpls_path:
                    continue
                m2ts_path = self._get_first_m2ts_for_mpls(selected_mpls_path)
                if not m2ts_path:
                    continue
                streams = self._read_m2ts_track_info(m2ts_path)
                try:
                    ch = Chapter(selected_mpls_path)
                    ch.get_pid_to_language()
                    streams = self._filter_streams_by_pid_lang(streams, ch.pid_to_lang)
                except Exception:
                    pass
                a, s = self._all_track_ids_from_streams(streams)
                self._track_selection_config[f'main::{os.path.normpath(selected_mpls_path)}'] = {'audio': a,
                                                                                                 'subtitle': s}
        except Exception:
            pass

        try:
            if hasattr(self, 'table3') and self.table3 and self.table3.isVisible() and ('select' in ENCODE_SP_LABELS):
                sel_col = ENCODE_SP_LABELS.index('select')
                bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                for r in range(self.table3.rowCount()):
                    it = self.table3.item(r, sel_col)
                    if not (it and it.flags() & Qt.ItemFlag.ItemIsEnabled and it.checkState() == Qt.CheckState.Checked):
                        continue
                    try:
                        bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
                    except Exception:
                        continue
                    streams: list[dict[str, object]] = []
                    mpls_file = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
                    if mpls_file:
                        playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                        if not playlist_dir:
                            continue
                        mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_file))
                        if not os.path.isfile(mpls_path):
                            continue
                        first_m2ts = self._get_first_m2ts_for_mpls(mpls_path)
                        if not first_m2ts:
                            continue
                        streams = self._read_m2ts_track_info(first_m2ts)
                        try:
                            ch = Chapter(mpls_path)
                            ch.get_pid_to_language()
                            streams = self._filter_streams_by_pid_lang(streams, ch.pid_to_lang)
                        except Exception:
                            pass
                    else:
                        stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
                        m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                        m2ts_files = self._split_m2ts_files(m2ts_text)
                        if not (stream_dir and m2ts_files):
                            continue
                        first_m2ts = os.path.normpath(os.path.join(stream_dir, m2ts_files[0]))
                        streams = self._read_m2ts_track_info(first_m2ts)
                        try:
                            pl = pid_to_lang_from_m2ts_path(first_m2ts)
                            if pl:
                                streams = self._filter_streams_by_pid_lang(streams, pl)
                        except Exception:
                            pass
                    a, s = self._all_track_ids_from_streams(streams)
                    entry = self._table3_get_sp_entry_for_row(r)
                    key = BluraySubtitle._sp_track_key_from_entry(entry)
                    self._track_selection_config[key] = {'audio': a, 'subtitle': s}
        except Exception:
            pass

        try:
            self._refresh_table1_remux_cmds()
        except Exception:
            pass
        try:
            self._recompute_sp_output_names()
        except Exception:
            pass

    def _on_select_all_tracks_toggled(self, checked: bool):
        try:
            if checked:
                self._apply_select_all_tracks_to_main_and_sp()
        except Exception:
            pass

    def _on_table3_item_changed(self, item: QTableWidgetItem):
        if getattr(self, '_updating_sp_table', False):
            return
        if not item:
            return
        try:
            if item.column() == ENCODE_SP_LABELS.index('select'):
                try:
                    item.setData(Qt.ItemDataRole.UserRole, 'user')
                except Exception:
                    pass
                self._recompute_sp_output_names()
                try:
                    if getattr(self, 'select_all_tracks_checkbox',
                               None) and self.select_all_tracks_checkbox.isChecked():
                        self._apply_select_all_tracks_to_main_and_sp()
                except Exception:
                    pass
        except Exception:
            pass
