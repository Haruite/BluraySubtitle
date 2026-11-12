"""Target module for output naming and track methods of `BluraySubtitleGUI`."""

import os
import re
from typing import Optional

from PyQt6.QtCore import QModelIndex, QSignalBlocker, Qt
from PyQt6.QtWidgets import QComboBox, QTableWidgetItem, QTableWidget, QToolButton

from src.core import REMUX_LABELS, DIY_REMUX_LABELS, ENCODE_LABELS, ENCODE_REMUX_LABELS, CURRENT_UI_LANGUAGE, ENCODE_SP_LABELS, \
    DIY_SP_LABELS, MPLS_INFO_LABELS
from src.runtime.gui_runtime_classes.custom_table_widget import READ_ONLY_HINT_ROLE
from src.runtime.gui_runtime_classes.sp_table_items import SpOutputNameItem, SpSelectionItem
from src.runtime.services import BluraySubtitle
from src.exports.utils import parse_time_to_seconds
from src.runtime.audio_conversion import is_immersive_audio_codec
from src.runtime.services_split.lifecycle_and_configuration import LifecycleConfigurationMixin
from src.runtime.sp import (
    SpEntry, media_track_key, filter_m2ts_file_detail_by_basenames,
    m2ts_file_detail_segments_contained_in,
)
from src.runtime.services_split.misc_workflows import (
    _movie_main_duration_by_bdmv_from_mpls_paths,
    _movie_sp_duration_matches_main,
)
from .gui_base import BluraySubtitleGuiBase


_SP_EPISODE_OUTPUT_KEY_ROLE = Qt.ItemDataRole.UserRole + 5


class OutputTracksMixin(BluraySubtitleGuiBase):
    def _resolve_output_name_from_mpls(self, mpls_no_ext: str) -> str:
        root = self.bdmv_folder_path.text().strip() if hasattr(self, 'bdmv_folder_path') else ''
        return LifecycleConfigurationMixin.resolve_disc_output_title(root, mpls_no_ext)

    def _build_episode_output_name_map(self, configuration: dict[int, dict[str, int | str]]) -> dict[int, str]:
        if not configuration:
            return {}
        total = len(configuration)
        width = len(str(total))
        ordered_indices = sorted(configuration.keys())
        rows_by_volume: dict[int, list[int]] = {}
        volume_by_row: dict[int, int] = {}
        for sub_index in ordered_indices:
            con = configuration[sub_index]
            try:
                bdmv_index = int(con.get('bdmv_index') or 0)
            except Exception:
                bdmv_index = 0
            rows_by_volume.setdefault(bdmv_index, []).append(sub_index)
            volume_by_row[sub_index] = bdmv_index

        sequence_by_row: dict[int, int] = {}
        for rows in rows_by_volume.values():
            sequence_rows = rows
            if not all(str(configuration[i].get('selected_mpls') or '').strip() for i in rows):
                sequence_rows = sorted(rows, key=lambda i: int(configuration[i].get('chapter_index') or 0))
            for sequence, sub_index in enumerate(sequence_rows, 1):
                sequence_by_row[sub_index] = sequence

        result: dict[int, str] = {}
        for sub_index in ordered_indices:
            con = configuration[sub_index]
            bdmv_index = volume_by_row[sub_index]
            bdmv_vol = f'{bdmv_index:03d}'
            seq_in_vol = sequence_by_row[sub_index]
            output_name = str(con.get('disc_output_name') or '').strip()
            if not output_name:
                output_name = self._resolve_output_name_from_mpls(str(con.get('selected_mpls') or ''))
            ep_no = f'EP{str(sub_index + 1).zfill(width)}'
            result[sub_index] = f'{ep_no} {output_name}_BD_Vol_{bdmv_vol}-{seq_in_vol:03d}.mkv'
        return result

    def _get_episode_output_names_from_table2(self) -> list[str]:
        function_id = self.get_selected_function_id()
        labels = self._table2_labels_for_current_mode()
        if not labels or 'output_name' not in labels:
            return []
        column = labels.index('output_name')
        names = [
            item.text() if (item := self.table2.item(row, column)) is not None else ''
            for row in range(self.table2.rowCount())
        ]
        if function_id == 3:
            return names
        names = [name.strip() for name in names]
        if all(names) or self._is_movie_mode():
            return names
        configuration = getattr(self, '_last_configuration_34', None) or getattr(self, 'configuration', None)
        if not isinstance(configuration, dict) or not configuration:
            return names
        try:
            defaults = self._build_episode_output_name_map(configuration)
        except Exception:
            return names
        return [name or defaults.get(row, '') for row, name in enumerate(names)]

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
            return ENCODE_REMUX_LABELS if getattr(self, '_encode_input_mode', 'bdmv') == 'remux' else ENCODE_LABELS
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
        sub_pids = self._track_pid_sets_for_config_key(
            sub_key, mpls_path_fallback=sub_mpls_fallback,
        )
        sup_pids = self._track_pid_sets_for_config_key(
            sup_key, mpls_path_fallback=sup_mpls_fallback,
        )
        # No-MPLS single-M2TS indexes are source-local. If either side cannot
        # be resolved to real transport PIDs, keep the SP instead of declaring
        # it redundant.
        if sub_pids is None or sup_pids is None:
            return False
        sa, ss = sub_pids
        ma, ms = sup_pids
        if sa and not sa.issubset(ma):
            return False
        if ss and not ss.issubset(ms):
            return False
        return True

    def _track_pid_sets_for_config_key(
        self, key: str, *, mpls_path_fallback: str = '',
    ) -> Optional[tuple[set[int], set[int]]]:
        """Resolve captured selections to audio/subtitle transport PIDs."""
        mpls_path = os.path.normpath(str(mpls_path_fallback or '').strip())
        if not mpls_path or not os.path.isfile(mpls_path):
            return None
        selected_audio, selected_subtitles = self._track_id_sets_for_config_key(
            key, mpls_path_fallback=mpls_path,
        )
        if str(key or '').startswith('main::') or '::mpls::' in str(key or ''):
            try:
                return (
                    {int(str(pid).strip(), 0) for pid in selected_audio},
                    {int(str(pid).strip(), 0) for pid in selected_subtitles},
                )
            except (TypeError, ValueError):
                return None
        first_m2ts = self._get_first_m2ts_for_mpls(mpls_path)
        if not first_m2ts:
            return None
        streams = self._read_m2ts_track_info(first_m2ts)
        pid_by_audio_index: dict[str, int] = {}
        pid_by_subtitle_index: dict[str, int] = {}
        for stream in streams:
            index = str(stream.get('index') or '').strip()
            pid = self._parse_stream_pid(stream.get('pid'))
            stream_type = str(stream.get('codec_type') or '').strip().lower()
            if not index or pid is None:
                continue
            if stream_type == 'audio':
                pid_by_audio_index[index] = pid
            elif stream_type in ('subtitle', 'subtitles'):
                pid_by_subtitle_index[index] = pid
        if (
                not selected_audio.issubset(pid_by_audio_index)
                or not selected_subtitles.issubset(pid_by_subtitle_index)
        ):
            return None
        return (
            {pid_by_audio_index[index] for index in selected_audio},
            {pid_by_subtitle_index[index] for index in selected_subtitles},
        )

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
            main_key = media_track_key('main', main_mpls) if main_mpls else ''
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
                    btn = info.cellWidget(i, MPLS_INFO_LABELS.index('main'))
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
        movie_mode = self._is_movie_mode()
        main_duration_by_bdmv = self._movie_main_duration_map_from_table1() if movie_mode else {}
        for r in range(self.table3.rowCount()):
            sel_item = self.table3.item(r, sel_col)
            if not isinstance(sel_item, SpSelectionItem) or not sel_item.default_selected:
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
            sp_key = SpEntry.from_mapping(entry).track_key
            sp_mpls = ''
            if mpls_file:
                playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                if playlist_dir:
                    sp_mpls = os.path.normpath(os.path.join(playlist_dir, mpls_file))
            reason = ''
            if self._sp_covered_by_table2_episode_row(bdmv_index, sp_detail, sp_key, sp_mpls_path=sp_mpls):
                reason = ('Its timeline is already covered by the main movie.' if movie_mode
                          else 'Its timeline and selected tracks are already covered by a main output.')
            elif (main_dur := main_duration_by_bdmv.get(bdmv_index)) is not None:
                dur_item = self.table3.item(r, dur_col)
                dur_sec = parse_time_to_seconds(dur_item.text()) if dur_item else 0.0
                if _movie_sp_duration_matches_main(dur_sec, main_dur):
                    reason = 'Its duration is close to the main movie.'
            if reason:
                with QSignalBlocker(self.table3):
                    sel_item.set_default(False, reason)

    def _episode_output_names_by_detail(self) -> dict[tuple[int, str], str | None]:
        """Use the same disc and full-detail identity as the SP attachment planner."""
        labels = self._table2_labels_for_current_mode()
        if not labels or 'm2ts_file_detail' not in labels or 'output_name' not in labels or self._is_movie_mode():
            return {}
        detail_col = labels.index('m2ts_file_detail')
        disc_col = labels.index('bdmv_index')
        names: dict[tuple[int, str], str | None] = {}
        for row, output_name in enumerate(self._get_episode_output_names_from_table2()):
            disc_item = self.table2.item(row, disc_col)
            detail_item = self.table2.item(row, detail_col)
            if disc_item is None or detail_item is None:
                continue
            try:
                disc = int(disc_item.text())
            except ValueError:
                continue
            detail = detail_item.text().strip()
            if disc > 0 and detail:
                key = (disc, detail)
                name = output_name.strip()
                if name and not name.lower().endswith('.mkv'):
                    name += '.mkv'
                # Duplicate episode details have no unique attachment target.
                names[key] = None if key in names else name
        return names

    def _on_main_output_name_changed(self, first: QModelIndex, last: QModelIndex, roles: list[int]) -> None:
        # Row population emits dataChanged without roles. Its normal refresh handles SP membership.
        if Qt.ItemDataRole.EditRole not in roles or not getattr(self, 'table3', None):
            return
        labels = self._table2_labels_for_current_mode()
        if not labels or 'output_name' not in labels:
            return
        output_col = labels.index('output_name')
        if not first.column() <= output_col <= last.column():
            return
        names = self._episode_output_names_by_detail()
        if not names:
            return
        sp_output_col = ENCODE_SP_LABELS.index('output_name')
        for row in range(self.table3.rowCount()):
            item = self.table3.item(row, sp_output_col)
            if item is not None and (name := names.get(item.data(_SP_EPISODE_OUTPUT_KEY_ROLE))) is not None:
                item.setText(name)

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
        """Recompute names that depend on the current main rows and SP scan data.

        The scan completion boundary calls this after every row result has been
        applied. Interactive edits may call it again later, but task startup must
        only consume the resulting visible names and must not invoke it.
        """
        if not hasattr(self, 'table3') or not self.table3:
            return
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4, 5) or (function_id == 4 and self._encode_input_mode == 'remux'):
            return
        labels = DIY_SP_LABELS if function_id == 5 else ENCODE_SP_LABELS
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
        detail_col = labels.index('m2ts_file_detail')
        sel_col = labels.index('select')
        bdmv_col = labels.index('bdmv_index')
        mpls_col = labels.index('mpls_file')
        m2ts_col = labels.index('m2ts_file')
        type_col = labels.index('m2ts_type')
        dur_col = labels.index('duration')
        try:
            single_output_movie = bool(self._is_movie_mode() and self.table2.rowCount() == 1)
        except Exception:
            single_output_movie = False
        rows_by_vol: dict[int, list[int]] = {}
        for r in range(self.table3.rowCount()):
            try:
                bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                bdmv_index = 0
            rows_by_vol.setdefault(bdmv_index, []).append(r)
        if only_bdmv_index is not None:
            rows_by_vol = {k: v for k, v in rows_by_vol.items() if int(k) == int(only_bdmv_index)}

        episode_names = self._episode_output_names_by_detail()
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
                    out_item = SpOutputNameItem('')
                    self.table3.setItem(r, out_col, out_item)

                sel_it = self.table3.item(r, sel_col)
                can_select = bool(sel_it and sel_it.flags() & Qt.ItemFlag.ItemIsEnabled)
                selected = can_select and sel_it.checkState() == Qt.CheckState.Checked
                out_item.setData(READ_ONLY_HINT_ROLE, 'Select this item first.' if can_select and not selected else None)
                detail_item = self.table3.item(r, detail_col)
                episode_key = (bdmv_index, detail_item.text().strip() if detail_item else '')
                episode_name = episode_names.get(episode_key)
                was_linked = out_item.data(_SP_EPISODE_OUTPUT_KEY_ROLE) is not None
                out_item.setData(_SP_EPISODE_OUTPUT_KEY_ROLE, None)
                flags = out_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                if selected and episode_name is None:
                    flags |= Qt.ItemFlag.ItemIsEditable
                out_item.setFlags(flags)
                bdmv_vol = f'{bdmv_index:03d}'
                special = str(out_item.data(Qt.ItemDataRole.UserRole + 2) or '')
                name_suffix = str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '')
                mpls_file = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
                m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                type_item = self.table3.item(r, type_col)
                m2ts_type = type_item.text().strip() if type_item else ''
                video_only = bool(type_item and type_item.data(Qt.ItemDataRole.UserRole))
                if not selected:
                    out_item.setText('')
                    continue
                m2ts_files = [x.strip() for x in m2ts_text.split(',') if x.strip()]
                m2ts_files_unique = list(dict.fromkeys(m2ts_files))
                seq += 1
                def _set_sp_out(rel: str):
                    if episode_name is None:
                        edited_name = out_item.data(Qt.ItemDataRole.UserRole)
                        path = f'SPs/{rel}' if edited_name is None else edited_name
                    else:
                        out_item.setData(_SP_EPISODE_OUTPUT_KEY_ROLE, episode_key)
                        path = episode_name
                    out_item.setText(path)

                sp_no = str(seq).zfill(digits)
                base_name = (
                    f'SP{sp_no}' if single_output_movie else f'BD_Vol_{bdmv_vol}_SP{sp_no}'
                )
                if not mpls_file and m2ts_files:
                    m2ts_stem = os.path.splitext(os.path.basename(m2ts_files[0]))[0]
                    base_name = m2ts_stem if single_output_movie else f'BD_Vol_{bdmv_vol}_{m2ts_stem}'
                # Preserve custom suffix (e.g. chapter range suffix) across track edits and recompute.
                if not name_suffix and mpls_file and episode_name is None and not was_linked:
                    try:
                        cur_name = out_item.text().strip().replace('\\', '/')
                        cur_stem = os.path.splitext(cur_name)[0]
                        if cur_stem.lower().startswith('sps/'):
                            cur_stem = cur_stem[4:]
                        m = re.match(r'^(?:BD_Vol_\d+_)?SP\d+(.*)$', cur_stem)
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
                        d_sec = parse_time_to_seconds(d_item.text() if d_item else '')
                    except Exception:
                        d_sec = 0.0
                    if d_sec <= 0.0:
                        _set_sp_out(f'{base_with_suffix}')
                        continue
                key = SpEntry.from_mapping(self._table3_get_sp_entry_for_row(r)).track_key
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
                    # A video-only source has no optional audio/subtitle selection but still has
                    # its implicit video track to mux. Explicitly deselecting available optional
                    # tracks keeps the documented empty-name/skip behavior.
                    if video_only or (mpls_file and len(m2ts_files_unique) >= 3):
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
                            if mpls_file:
                                playlist_dir = self._get_playlist_dir_for_bdmv_index(
                                    bdmv_index
                                )
                                mpls_path = os.path.join(playlist_dir, mpls_file)
                                streams = self._read_mpls_track_info(mpls_path)
                            elif str(src).lower().endswith('.m2ts'):
                                streams = self._read_m2ts_track_info(src)
                            else:
                                streams = BluraySubtitle._read_media_streams(src)
                            for s in streams:
                                if str(s.get('codec_type') or '') != 'audio':
                                    continue
                                if str(s.get('index', '')) == str(sel_audio[0]):
                                    c = str(s.get('codec_name') or '').lower()
                                    if (
                                            self.get_selected_function_id() == 4
                                            and self._is_lossless_audio_stream_dict(s)
                                    ):
                                        configured_targets = (
                                            getattr(self, '_track_lossless_audio_config', {}) or {}
                                        ).get(key, {}) or {}
                                        target_codec = str(
                                            configured_targets.get(str(sel_audio[0]))
                                            or self._current_encode_lossless_audio_codec()
                                        ).strip().lower()
                                        ext = {'aac': 'm4a'}.get(target_codec, target_codec)
                                    elif self._is_lossless_audio_stream_dict(s):
                                        immersive_audio = is_immersive_audio_codec(
                                            c,
                                            s.get('profile'),
                                            s.get('track_name'),
                                        )
                                        convert_immersive = bool(
                                            self._app_config.remux.convert_immersive_audio_to_flac
                                        )
                                        if immersive_audio and not convert_immersive:
                                            ext = 'dts' if 'dts' in c else 'thd'
                                        else:
                                            ext = 'flac'
                                    elif c in ('dts', 'dts_hd'):
                                        ext = 'dts'
                                    elif c in ('truehd', 'mlp'):
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
                                        '.m2ts') else BluraySubtitle._read_media_streams(src)
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

    def _all_track_ids_from_streams(self, streams: list[dict[str, object]]) -> tuple[list[str], list[str]]:
        audio: list[str] = []
        subtitle: list[str] = []
        for s in streams or []:
            if s.get('_mpls_append_compatible') is False:
                continue
            idx = str(s.get('index', '')).strip()
            if idx == '':
                continue
            ctype = str(s.get('codec_type') or '')
            if ctype == 'audio':
                audio.append(idx)
            elif ctype in ('subtitle', 'subtitles'):
                subtitle.append(idx)
        return audio, subtitle

    def _cache_available_track_ids(
            self, key: str, streams: list[dict[str, object]],
    ) -> dict[str, list[str]]:
        audio, subtitle = self._all_track_ids_from_streams(streams)
        video = [
            str(stream.get('index', '')).strip()
            for stream in streams or []
            if str(stream.get('codec_type') or '').strip().lower() == 'video'
            and stream.get('_mpls_append_compatible') is not False
            and str(stream.get('index', '')).strip()
        ]
        available = getattr(self, '_available_track_selection_config', None)
        if not isinstance(available, dict):
            available = {}
            self._available_track_selection_config = available
        snapshot = {
            'video': video,
            'audio': list(audio),
            'subtitle': list(subtitle),
        }
        available[str(key)] = snapshot
        return snapshot

    def _apply_select_all_tracks_to_main_and_sp(self):
        if not isinstance(getattr(self, '_track_selection_config', None), dict):
            self._track_selection_config = {}
        if not getattr(self, 'select_all_tracks_checkbox', None) or (not self.select_all_tracks_checkbox.isChecked()):
            return
        available = getattr(self, '_available_track_selection_config', None)
        if not isinstance(available, dict):
            return
        visible_keys: set[str] = set()
        if self.get_selected_function_id() == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            for row in range(self.table2.rowCount()):
                source = self._get_remux_source_path_from_table2_row(row)
                if source:
                    visible_keys.add(media_track_key('mkv', source))
            if hasattr(self, 'table3') and self.table3:
                for row in range(self.table3.rowCount()):
                    source = self._get_remux_source_path_from_table3_row(row)
                    if source:
                        visible_keys.add(media_track_key('mkvsp', source))
        else:
            for mpls_path in self._get_selected_main_mpls_paths():
                visible_keys.add(media_track_key('main', mpls_path))
            if hasattr(self, 'table3') and self.table3 and self.table3.isVisible():
                select_column = ENCODE_SP_LABELS.index('select')
                for row in range(self.table3.rowCount()):
                    select_item = self.table3.item(row, select_column)
                    if not (
                            select_item
                            and select_item.flags() & Qt.ItemFlag.ItemIsEnabled
                            and select_item.checkState() == Qt.CheckState.Checked
                    ):
                        continue
                    entry = self._table3_get_sp_entry_for_row(row)
                    visible_keys.add(SpEntry.from_mapping(entry).track_key)

        for key in visible_keys:
            track_ids = available.get(key)
            if not isinstance(track_ids, dict):
                continue
            self._track_selection_config[key] = {
                'video': list(track_ids.get('video') or []),
                'audio': list(track_ids.get('audio') or []),
                'subtitle': list(track_ids.get('subtitle') or []),
            }

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

    def _set_sp_selection(self, selected: bool | None) -> None:
        labels = self.table3.property('columnKeys') or ()
        if 'select' not in labels:
            return
        column = labels.index('select')
        changed = False
        with QSignalBlocker(self.table3):
            for row in range(self.table3.rowCount()):
                item = self.table3.item(row, column)
                if isinstance(item, SpSelectionItem) and item.flags() & Qt.ItemFlag.ItemIsEnabled:
                    previous = item.checkState()
                    item.apply_selection(selected)
                    changed = changed or item.checkState() != previous
        if changed:
            self._refresh_sp_outputs_after_selection_change()

    def _refresh_sp_outputs_after_selection_change(self) -> None:
        try:
            if self.select_all_tracks_checkbox.isChecked():
                self._apply_select_all_tracks_to_main_and_sp()
            else:
                self._recompute_sp_output_names()
        except Exception as error:
            self._show_error_dialog(str(error))

    def _on_table3_item_changed(self, item: QTableWidgetItem):
        if getattr(self, '_updating_sp_table', False):
            return
        function_id = self.get_selected_function_id()
        if not item or function_id not in (3, 4, 5) or (function_id == 4 and self._encode_input_mode == 'remux'):
            return
        if item.column() == ENCODE_SP_LABELS.index('select'):
            with QSignalBlocker(self.table3):
                item.setData(Qt.ItemDataRole.UserRole, 'user')
            self._refresh_sp_outputs_after_selection_change()
