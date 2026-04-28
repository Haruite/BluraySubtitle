"""Target module for SP/chapter segment synchronization methods."""
import os
import re
import traceback
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QTableWidgetItem, QToolButton, QComboBox, QTableWidget

from src.bdmv import Chapter
from src.core import ENCODE_SP_LABELS, SUBTITLE_LABELS, MKV_LABELS, ENCODE_LABELS, REMUX_LABELS
from src.exports.utils import get_index_to_m2ts_and_offset, get_time_str, print_exc_terminal
from src.runtime.services import BluraySubtitle
from .gui_base import BluraySubtitleGuiBase


class SpChapterSegmentLogicMixin(BluraySubtitleGuiBase):
    def _add_or_update_table3_mpls_as_sp(self, bdmv_index: int, mpls_path: str):
        if not hasattr(self, 'table3') or not self.table3:
            return
        if self.table3.columnCount() != len(ENCODE_SP_LABELS):
            self.table3.setColumnCount(len(ENCODE_SP_LABELS))
            self._set_table_headers(self.table3, ENCODE_SP_LABELS)
        try:
            chapter = Chapter(mpls_path)
            idx_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
            ordered: list[str] = []
            for k in sorted(idx_to_m2ts.keys()):
                v = str(idx_to_m2ts.get(k) or '').strip()
                if v and v not in ordered:
                    ordered.append(v)
            m2ts_files = ordered
            duration = float(chapter.get_total_time())
        except Exception:
            return
        mpls_file = os.path.basename(mpls_path)
        unique_m2ts = len(set(m2ts_files))
        default_selected = True if unique_m2ts >= 3 else bool(duration >= 30.0)

        sel_col = ENCODE_SP_LABELS.index('select')
        bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
        mpls_col = ENCODE_SP_LABELS.index('mpls_file')
        m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
        dur_col = ENCODE_SP_LABELS.index('duration')
        out_col = ENCODE_SP_LABELS.index('output_name')
        tracks_col = ENCODE_SP_LABELS.index('tracks')
        play_col = ENCODE_SP_LABELS.index('play')

        target_key = (int(bdmv_index), str(mpls_file), ','.join(m2ts_files))
        target_row = -1
        for r in range(self.table3.rowCount()):
            try:
                b = int(self.table3.item(r, bdmv_col).text().strip()) if self.table3.item(r, bdmv_col) else 0
            except Exception:
                b = 0
            mf = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
            m2 = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
            if (b, mf, m2) == target_key:
                target_row = r
                break
        if target_row < 0:
            target_row = self._find_table3_insert_row_for_entry(int(bdmv_index), str(mpls_file), ','.join(m2ts_files))
            self.table3.insertRow(target_row)

        try:
            self._updating_sp_table = True
            sel_item = self.table3.item(target_row, sel_col) or QTableWidgetItem('')
            sel_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            if sel_item.data(Qt.ItemDataRole.UserRole) != 'user':
                sel_item.setCheckState(Qt.CheckState.Checked if default_selected else Qt.CheckState.Unchecked)
            self.table3.setItem(target_row, sel_col, sel_item)
            self.table3.setItem(target_row, bdmv_col, QTableWidgetItem(str(bdmv_index)))
            self.table3.setItem(target_row, mpls_col, QTableWidgetItem(mpls_file))
            self.table3.setItem(target_row, m2ts_col, QTableWidgetItem(','.join(m2ts_files)))
            self.table3.setItem(target_row, dur_col, QTableWidgetItem(get_time_str(duration)))
            if not self.table3.item(target_row, out_col):
                self.table3.setItem(target_row, out_col, QTableWidgetItem(''))
            btn_tracks = QToolButton(self.table3)
            btn_tracks.setText(self.t('edit tracks'))
            btn_tracks.clicked.connect(self._on_edit_tracks_from_sp_table_clicked)
            self.table3.setCellWidget(target_row, tracks_col, btn_tracks)
            btn_play = QToolButton(self.table3)
            btn_play.setText(self.t('play'))
            btn_play.clicked.connect(self._on_play_sp_table_row_clicked)
            self.table3.setCellWidget(target_row, play_col, btn_play)
        finally:
            self._updating_sp_table = False

        self._recompute_sp_output_names(only_bdmv_index=bdmv_index)

    def _add_sp_entries_for_unchecked_segments(self, mpls_path: str, segments: list[tuple[int, int]], bdmv_index: int,
                                               chapter_to_m2ts: dict = None):
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time

        if chapter_to_m2ts is None:
            chapter_to_m2ts = {}

        # Get current sp_index for this bdmv_index
        sp_index = self._sp_index_by_bdmv.get(bdmv_index, 0)

        def _chapter_sort_value(name: str) -> int:
            s = str(name or '')
            if re.search(r'_beginning_to_', s, re.I):
                return 0
            m = re.search(r'_chapter_(\d+)_to_', s, re.I)
            return int(m.group(1)) if m else 10 ** 9

        def _find_insert_row(target_bdmv: int, target_mpls: str, target_start_chapter: int) -> int:
            if not hasattr(self, 'table3') or not self.table3:
                return 0
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            out_col = ENCODE_SP_LABELS.index('output_name')
            total = self.table3.rowCount()
            first_target_bdmv = -1
            for r in range(total):
                b_item = self.table3.item(r, bdmv_col)
                m_item = self.table3.item(r, mpls_col)
                o_item = self.table3.item(r, out_col)
                try:
                    b_val = int(b_item.text().strip()) if b_item and b_item.text() else 0
                except Exception:
                    b_val = 0
                m_val = m_item.text().strip() if m_item and m_item.text() else ''
                out_val = o_item.text().strip() if o_item and o_item.text() else ''
                if b_val == target_bdmv and first_target_bdmv < 0:
                    first_target_bdmv = r
                if b_val > target_bdmv:
                    return r
                if b_val < target_bdmv:
                    continue
                target_mpls_norm = str(target_mpls or '').strip()
                m_val_norm = str(m_val or '').strip()
                target_sort = (1 if not target_mpls_norm else 0, target_mpls_norm.lower())
                cur_sort = (1 if not m_val_norm else 0, m_val_norm.lower())
                if cur_sort > target_sort:
                    return r
                if cur_sort < target_sort:
                    continue
                if m_val_norm != target_mpls_norm:
                    continue
                cur_start = _chapter_sort_value(out_val)
                if target_start_chapter <= cur_start:
                    return r
            if first_target_bdmv >= 0:
                # Append after all rows of this bdmv when no same-mpls chapter slot is found.
                last = first_target_bdmv
                while last + 1 < total:
                    b_item2 = self.table3.item(last + 1, bdmv_col)
                    try:
                        b_val2 = int(b_item2.text().strip()) if b_item2 and b_item2.text() else 0
                    except Exception:
                        b_val2 = 0
                    if b_val2 != target_bdmv:
                        break
                    last += 1
                return last + 1
            return total

        # Visible chapter boundaries must match ChapterWindow (filter marks too close to MPLS end).
        mpls_duration = chapter.get_total_time()
        chapter_bounds: list[float] = []
        offset = 0
        for ref_to_play_item_id, mark_timestamps in mark_info.items():
            for mark_timestamp in mark_timestamps:
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    chapter_bounds.append(off)
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000
        chapter_bounds.append(mpls_duration)

        try:
            self._updating_sp_table = True
            for start_row, end_row in segments:
                if start_row < 0 or end_row < 0:
                    continue
                if start_row >= len(chapter_bounds) - 1 or end_row >= len(chapter_bounds) - 1:
                    continue
                sp_index += 1
                start_chapter = start_row + 1  # 1-based
                end_chapter = end_row + 2  # end is the next chapter

                # Calculate duration (indices align with view-chapters table rows)
                start_time = float(chapter_bounds[start_row])
                end_time = float(chapter_bounds[end_row + 1])
                duration = end_time - start_time

                # Collect m2ts files
                m2ts_files = []
                for i in range(start_row, end_row + 1):
                    m2ts = chapter_to_m2ts.get(i + 1)  # i+1 because chapter indices are 1-based
                    if m2ts:
                        m2ts_files.append(m2ts)

                m2ts_files = list(dict.fromkeys(m2ts_files))  # Remove duplicates while preserving order

                # Generate output name
                bdmv_vol = '0' * (3 - len(str(bdmv_index))) + str(bdmv_index)
                sp_no = str(sp_index).zfill(2)
                total_rows = len(chapter_bounds) - 1
                start_tag = f'chapter_{start_chapter}'
                end_tag = f'chapter_{end_chapter}'
                if start_row == 0:
                    start_tag = 'beginning'
                if end_row == total_rows - 1:
                    end_tag = 'ending'
                suffix = f'_{start_tag}_to_{end_tag}'
                out_name = f'BD_Vol_{bdmv_vol}_SP{sp_no}{suffix}.mkv'

                # Add to table3
                if hasattr(self, 'table3') and self.table3:
                    row = _find_insert_row(bdmv_index, os.path.basename(mpls_path), start_chapter)
                    self.table3.insertRow(row)
                    sel_col = ENCODE_SP_LABELS.index('select')
                    bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                    mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                    m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                    dur_col = ENCODE_SP_LABELS.index('duration')
                    out_col = ENCODE_SP_LABELS.index('output_name')
                    tracks_col = ENCODE_SP_LABELS.index('tracks')
                    play_col = ENCODE_SP_LABELS.index('play')

                    # Select checkbox
                    sel_item = QTableWidgetItem()
                    sel_item.setFlags(sel_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                    sel_item.setCheckState(Qt.CheckState.Checked if duration >= 30.0 else Qt.CheckState.Unchecked)
                    self.table3.setItem(row, sel_col, sel_item)

                    self.table3.setItem(row, bdmv_col, QTableWidgetItem(str(bdmv_index)))
                    self.table3.setItem(row, mpls_col, QTableWidgetItem(os.path.basename(mpls_path)))
                    self.table3.setItem(row, m2ts_col, QTableWidgetItem(','.join(m2ts_files)))
                    self.table3.setItem(row, dur_col, QTableWidgetItem(get_time_str(duration)))
                    out_item = QTableWidgetItem(out_name)
                    out_item.setData(Qt.ItemDataRole.UserRole + 3, suffix)
                    out_item.setData(Qt.ItemDataRole.UserRole + 4, 'chapter_segment_sp')
                    self.table3.setItem(row, out_col, out_item)

                    # New chapter-derived SP rows should reuse main MPLS track config directly.
                    try:
                        sp_entry = {
                            'bdmv_index': int(bdmv_index),
                            'mpls_file': os.path.basename(mpls_path),
                            'm2ts_file': ','.join(m2ts_files),
                            'output_name': out_name,
                        }
                        sp_key = BluraySubtitle._sp_track_key_from_entry(sp_entry)
                        cfg = getattr(self, '_track_selection_config', None)
                        if not isinstance(cfg, dict):
                            self._track_selection_config = {}
                            cfg = self._track_selection_config
                        self._inherit_main_track_config_for_sp_key(int(bdmv_index), os.path.basename(mpls_path), sp_key)
                    except Exception:
                        pass

                    # Set tracks button
                    btn_tracks = QToolButton(self.table3)
                    btn_tracks.setText(self.t('edit tracks'))
                    btn_tracks.clicked.connect(self._on_edit_tracks_from_sp_table_clicked)
                    self.table3.setCellWidget(row, tracks_col, btn_tracks)

                    # Set play button
                    btn_play = QToolButton(self.table3)
                    btn_play.setText(self.t('play'))
                    btn_play.clicked.connect(self._on_play_sp_table_row_clicked)
                    self.table3.setCellWidget(row, play_col, btn_play)
        finally:
            self._updating_sp_table = False

        # Update sp_index
        self._sp_index_by_bdmv[bdmv_index] = sp_index

        # Make table3 visible after adding entries
        if self.table3.rowCount() > 0:
            self.table3.setVisible(True)

        # Refresh sorting after adding entries (do not auto-scroll).
        if hasattr(self, 'table3') and self.table3:
            was_sorting = self.table3.isSortingEnabled()
            self.table3.setSortingEnabled(False)
            self.table3.setSortingEnabled(was_sorting)

    def _apply_end_combo_min_constraint(self, combo: QComboBox, min_allowed: int):
        model = combo.model()
        ending_value = int(combo.itemData(combo.count() - 1) or (combo.count()))
        for i in range(combo.count()):
            v = int(combo.itemData(i) or (i + 1))
            item = model.item(i) if hasattr(model, 'item') else None
            if item is not None:
                item.setEnabled((v >= min_allowed) or (v == ending_value))
        cur_v = int(combo.currentData() or (combo.currentIndex() + 1))
        if cur_v < min_allowed and cur_v != ending_value:
            for i in range(combo.count()):
                v = int(combo.itemData(i) or (i + 1))
                if (v >= min_allowed) or (v == ending_value):
                    combo.blockSignals(True)
                    combo.setCurrentIndex(i)
                    combo.blockSignals(False)
                    break

    def _apply_start_chapter_constraints(self, labels: list[str]):
        if 'start_at_chapter' not in labels:
            return
        start_col = labels.index('start_at_chapter')
        end_col = labels.index('end_at_chapter') if 'end_at_chapter' in labels else -1
        bdmv_col = labels.index('bdmv_index')
        bdmv_to_mpls = self._bdmv_to_first_main_mpls_from_table1()
        prev_end_by_bdmv: dict[int, int] = {}
        for r in range(self.table2.rowCount()):
            b_item = self.table2.item(r, bdmv_col)
            try:
                bdmv_index = int(b_item.text().strip()) if b_item and b_item.text() else 0
            except Exception:
                bdmv_index = 0
            combo = self.table2.cellWidget(r, start_col)
            if not isinstance(combo, QComboBox):
                continue
            min_allowed = prev_end_by_bdmv.get(bdmv_index, 1)
            mpls_no_ext = str(b_item.data(Qt.ItemDataRole.UserRole) or '').strip() if b_item else ''
            if not mpls_no_ext:
                mpls_no_ext = bdmv_to_mpls.get(bdmv_index, '')
            checked_states: list[bool] = []
            if mpls_no_ext:
                mpls_path = mpls_no_ext + '.mpls'
                checked_states = list(self._chapter_checkbox_states.get(mpls_path, []))
            # Make sure every item has stable numeric value data.
            for i in range(combo.count()):
                if combo.itemData(i) is None:
                    combo.setItemData(i, i + 1)
            model = combo.model()
            for i in range(combo.count()):
                v = int(combo.itemData(i) or (i + 1))
                item = model.item(i) if hasattr(model, 'item') else None
                if item is not None:
                    enabled_by_segment = True
                    if checked_states and 1 <= v <= len(checked_states):
                        enabled_by_segment = bool(checked_states[v - 1])
                    item.setEnabled((v >= min_allowed) and enabled_by_segment)
            cur_v = int(combo.currentData() or (combo.currentIndex() + 1))
            if cur_v < min_allowed:
                for i in range(combo.count()):
                    v = int(combo.itemData(i) or (i + 1))
                    if v >= min_allowed:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(i)
                        combo.blockSignals(False)
                        cur_v = v
                        break
            if end_col >= 0:
                end_val = 0
                end_combo = self.table2.cellWidget(r, end_col)
                if isinstance(end_combo, QComboBox):
                    try:
                        end_val = int(end_combo.currentData() or 0)
                    except Exception:
                        end_val = 0
                else:
                    end_item = self.table2.item(r, end_col)
                    if end_item:
                        try:
                            end_val = int(end_item.data(Qt.ItemDataRole.UserRole + 1) or 0)
                        except Exception:
                            end_val = 0
                prev_end_by_bdmv[bdmv_index] = end_val if end_val > 0 else cur_v
            else:
                prev_end_by_bdmv[bdmv_index] = cur_v

    def _build_end_chapter_combo(self, rows: int, has_beginning: bool, start_value: int,
                                 selected_value: int = 0) -> QComboBox:
        combo = QComboBox()
        for v in range(1, rows + 2):
            combo.addItem(self._chapter_label_text(v, rows, has_beginning, for_end=True), v)
        self._apply_end_combo_min_constraint(combo, max(1, int(start_value) + 1))
        if selected_value <= 0:
            selected_value = max(1, int(start_value) + 1)
        selected_idx = -1
        for i in range(combo.count()):
            if int(combo.itemData(i) or 0) == int(selected_value):
                selected_idx = i
                break
        if selected_idx < 0:
            for i in range(combo.count()):
                v = int(combo.itemData(i) or 0)
                if v >= max(1, int(start_value) + 1):
                    selected_idx = i
                    break
        if selected_idx >= 0:
            combo.setCurrentIndex(selected_idx)
        combo._prev_end_value = int(combo.currentData() or (combo.currentIndex() + 1))
        return combo

    def _build_start_chapter_options(self, rows: int, has_beginning: bool) -> list[tuple[int, str]]:
        return [(v, self._chapter_label_text(v, rows, has_beginning, for_end=False)) for v in range(1, rows + 1)]

    def _chapter_label_text(self, value: int, rows: int, has_beginning: bool, for_end: bool = False) -> str:
        if for_end and value >= rows + 1:
            return 'ending'
        # End selector should show explicit chapter index (same as --split chapters value).
        if for_end:
            return f'chapter {max(1, int(value)):02d}'
        if has_beginning and value == 1:
            return 'beginning'
        chapter_no = value - 1 if has_beginning else value
        if chapter_no < 1:
            chapter_no = 1
        return f'chapter {chapter_no:02d}'

    def _chapter_node_data(self, mpls_path_no_ext: str) -> dict[str, object]:
        chapter = Chapter(mpls_path_no_ext + '.mpls')
        index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
        rows = sum(map(len, chapter.mark_info.values()))
        offsets: dict[int, float] = {}
        for i in range(1, rows + 1):
            offsets[i] = float(index_to_offset.get(i, 0.0))
        offsets[rows + 1] = float(chapter.get_total_time())
        m2ts_map: dict[int, str] = {}
        for i in range(1, rows + 1):
            m2ts_map[i] = str(index_to_m2ts.get(i) or '')
        has_beginning = bool(offsets.get(1, 0.0) > 0.001)
        return {'rows': rows, 'offsets': offsets, 'm2ts': m2ts_map, 'has_beginning': has_beginning}

    def _closest_endpoint(self, start_idx: int, target_sec: float, rows: int, offsets: dict[int, float],
                          m2ts: dict[int, str], checked: list[bool]) -> int:
        candidates = [i for i in range(start_idx + 1, rows + 2) if (i == rows + 1) or checked[i - 1]]
        if not candidates:
            return min(rows + 1, start_idx + 1)
        chapter_end = min(candidates, key=lambda e: abs(
            (offsets.get(e, offsets[rows + 1]) - offsets.get(start_idx, 0.0)) - target_sec))
        file_candidates = []
        for e in candidates:
            if e == rows + 1:
                file_candidates.append(e)
                continue
            prev_f = m2ts.get(e - 1, '')
            cur_f = m2ts.get(e, '')
            if e == 1 or cur_f != prev_f:
                file_candidates.append(e)
        if not file_candidates:
            return chapter_end
        file_end = min(file_candidates, key=lambda e: abs(
            (offsets.get(e, offsets[rows + 1]) - offsets.get(start_idx, 0.0)) - target_sec))
        diff_file = (offsets.get(file_end, offsets[rows + 1]) - offsets.get(start_idx, 0.0)) - target_sec
        if (-target_sec * 0.25) <= diff_file <= (target_sec * 0.5):
            return file_end
        diff_ch = (offsets.get(chapter_end, offsets[rows + 1]) - offsets.get(start_idx, 0.0)) - target_sec
        score_file = diff_file if diff_file >= 0 else (-2.0 * diff_file)
        score_ch = diff_ch if diff_ch >= 0 else (-2.0 * diff_ch)
        return file_end if score_file <= score_ch else chapter_end

    def _filtered_chapter_visible_layout(self, mpls_path: str) -> tuple[list[int], dict[int, str]]:
        """Match ChapterWindow: visible chapter rows and chapter_to_m2ts (1-based keys in filtered order)."""
        chapter = Chapter(mpls_path)
        mark_info = chapter.mark_info
        in_out_time = chapter.in_out_time
        mpls_duration = chapter.get_total_time()
        chapter_to_m2ts: dict[int, str] = {}
        filtered_to_unfiltered: list[int] = []
        offset = 0
        ch_idx = 1
        unfiltered_c = 0
        for ref_to_play_item_id, mark_timestamps in mark_info.items():
            m2ts_base = in_out_time[ref_to_play_item_id][0] + '.m2ts'
            for mark_timestamp in mark_timestamps:
                unfiltered_c += 1
                off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                if mpls_duration - off >= 0.001:
                    filtered_to_unfiltered.append(unfiltered_c)
                    chapter_to_m2ts[ch_idx] = m2ts_base
                    ch_idx += 1
            offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000
        return filtered_to_unfiltered, chapter_to_m2ts

    def _find_table3_insert_row_for_entry(self, bdmv_index: int, mpls_file: str, m2ts_file: str) -> int:
        if not hasattr(self, 'table3') or not self.table3:
            return 0
        if self.table3.columnCount() != len(ENCODE_SP_LABELS):
            return self.table3.rowCount()
        try:
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
        except Exception:
            return self.table3.rowCount()

        def _row_sort_key(row_bdmv: int, row_mpls: str, row_m2ts: str):
            return (
                int(row_bdmv or 0),
                1 if not str(row_mpls or '').strip() else 0,
                str(row_mpls or ''),
                str(row_m2ts or ''),
            )

        target = _row_sort_key(int(bdmv_index), str(mpls_file), str(m2ts_file))
        for r in range(self.table3.rowCount()):
            try:
                rb = int(self.table3.item(r, bdmv_col).text().strip()) if self.table3.item(r, bdmv_col) else 0
            except Exception:
                rb = 0
            rm = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
            r2 = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
            if _row_sort_key(rb, rm, r2) > target:
                return r
        return self.table3.rowCount()

    def _get_first_m2ts_for_mpls(self, mpls_path: str) -> str:
        try:
            chapter = Chapter(mpls_path)
            index_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
            if not index_to_m2ts:
                return ''
            first_key = sorted(index_to_m2ts.keys())[0]
            m2ts_name = index_to_m2ts.get(first_key) or ''
            playlist_dir = os.path.dirname(mpls_path)
            bdmv_dir = os.path.dirname(playlist_dir)
            stream_dir = os.path.join(bdmv_dir, 'STREAM')
            return os.path.normpath(os.path.join(stream_dir, str(m2ts_name)))
        except Exception:
            return ''

    def _has_subtitle_in_table2(self) -> bool:
        try:
            function_id = self.get_selected_function_id()
            if self.table2.rowCount() <= 0:
                return False
            if function_id == 1:
                col = SUBTITLE_LABELS.index('path')
            elif function_id == 2:
                col = MKV_LABELS.index('path')
            elif function_id in (3, 4, 5):
                labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
                col = labels.index('sub_path')
            else:
                return False
            for r in range(self.table2.rowCount()):
                it = self.table2.item(r, col)
                if it and it.text() and it.text().strip():
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    def _is_auto_chapter_segment_sp_item(out_item: Optional[QTableWidgetItem]) -> bool:
        """SP rows derived from main-mpls chapter inclusion (checkbox / end_at_chapter tail). Not merged from refresh snapshot."""
        if not out_item:
            return False
        if out_item.data(Qt.ItemDataRole.UserRole + 4) == 'chapter_segment_sp':
            return True
        suf = str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '').strip()
        if not suf:
            return False
        return bool(re.search(r'^_(beginning|chapter_\d+)_to_(chapter_\d+|ending)$', suf, re.I))

    def _is_mpls_currently_main(self, mpls_path: str) -> bool:
        """True if this playlist file is the checked main MPLS for its disc row in table1."""
        try:
            norm_target = os.path.normpath(mpls_path)
        except Exception:
            return False
        if not norm_target.lower().endswith('.mpls'):
            norm_target = norm_target + '.mpls'
        for bdmv_index in range(self.table1.rowCount()):
            root_item = self.table1.item(bdmv_index, 0)
            if not root_item or not str(root_item.text() or '').strip():
                continue
            root = os.path.normpath(root_item.text().strip())
            info = self.table1.cellWidget(bdmv_index, 2)
            if not isinstance(info, QTableWidget):
                continue
            for mpls_i in range(info.rowCount()):
                it0 = info.item(mpls_i, 0)
                if not it0 or not str(it0.text() or '').strip():
                    continue
                row_mpls = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', it0.text().strip()))
                if row_mpls != norm_target:
                    continue
                main_btn = info.cellWidget(mpls_i, 3)
                return isinstance(main_btn, QToolButton) and main_btn.isChecked()
        return False

    def _max_sp_serial_for_bdmv(self, bdmv_index: int) -> int:
        mmax = 0
        if not hasattr(self, 'table3') or not self.table3:
            return 0
        try:
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            out_col = ENCODE_SP_LABELS.index('output_name')
        except Exception:
            return 0
        for r in range(self.table3.rowCount()):
            try:
                b = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                continue
            if b != bdmv_index:
                continue
            it = self.table3.item(r, out_col)
            t = it.text().strip() if it and it.text() else ''
            m = re.search(r'(?i)BD_Vol_\d+_SP(\d+)', t)
            if m:
                mmax = max(mmax, int(m.group(1)))
        return mmax

    def _on_end_chapter_combo_changed(self, row: int, labels: list[str]):
        if row < 0 or row >= self.table2.rowCount():
            return
        start_col = labels.index('start_at_chapter')
        end_col = labels.index('end_at_chapter')
        start_combo = self.table2.cellWidget(row, start_col)
        end_combo = self.table2.cellWidget(row, end_col)
        if isinstance(start_combo, QComboBox) and isinstance(end_combo, QComboBox):
            start_v = int(start_combo.currentData() or (start_combo.currentIndex() + 1))
            old_v = int(
                getattr(end_combo, '_prev_end_value', end_combo.currentData() or (end_combo.currentIndex() + 1)))
            self._apply_end_combo_min_constraint(end_combo, start_v + 1)
            new_v = int(end_combo.currentData() or (end_combo.currentIndex() + 1))
            if new_v != old_v:
                bdmv_col = labels.index('bdmv_index')
                b_item = self.table2.item(row, bdmv_col)
                try:
                    bdmv_index = int(b_item.text().strip()) if b_item and b_item.text() else 0
                except Exception:
                    bdmv_index = 0
                bdmv_to_mpls = self._bdmv_to_first_main_mpls_from_table1()
                mpls_no_ext = str(b_item.data(Qt.ItemDataRole.UserRole) or '').strip() if b_item else ''
                if not mpls_no_ext:
                    mpls_no_ext = bdmv_to_mpls.get(bdmv_index, '')
                # Next episode start must be on the same main MPLS.
                next_row_same_mpls = -1
                for r2 in range(row + 1, self.table2.rowCount()):
                    b2 = self.table2.item(r2, bdmv_col)
                    try:
                        b2i = int(b2.text().strip()) if b2 and b2.text() else 0
                    except Exception:
                        b2i = 0
                    m2 = str(b2.data(Qt.ItemDataRole.UserRole) or '').strip() if b2 else ''
                    if not m2:
                        m2 = bdmv_to_mpls.get(b2i, '')
                    if m2 != mpls_no_ext:
                        continue
                    next_row_same_mpls = r2
                    break
                if mpls_no_ext:
                    mpls_path = mpls_no_ext + '.mpls'
                    checked_states = list(self._chapter_checkbox_states.get(mpls_path, []))
                    try:
                        total_rows = int(self._chapter_node_data(mpls_no_ext).get('rows') or 0)
                    except Exception:
                        total_rows = 0
                    if len(checked_states) < total_rows:
                        checked_states += [True] * (total_rows - len(checked_states))
                    next_start = max(1, min(int(new_v), max(1, total_rows)))
                    if checked_states and total_rows > 0:
                        found = next((i for i in range(next_start, total_rows + 1) if checked_states[i - 1]), None)
                        if found is not None:
                            next_start = int(found)
                    if (new_v > old_v) and next_row_same_mpls >= 0 and total_rows > 0 and int(new_v) >= (
                            total_rows + 1):
                        # Expanded back to ending: collapse split row.
                        self._chapter_pending_remove_row = int(next_row_same_mpls)
                        self._chapter_pending_append_episode = None
                    elif next_row_same_mpls >= 0:
                        # Keep following row start synced to the current end.
                        if total_rows > 0 and int(new_v) >= (total_rows + 1):
                            self._chapter_pending_remove_row = int(next_row_same_mpls)
                            self._chapter_pending_append_episode = None
                        nxc = self.table2.cellWidget(next_row_same_mpls, start_col)
                        if isinstance(nxc, QComboBox):
                            for i in range(nxc.count()):
                                if int(nxc.itemData(i) or (i + 1)) == int(next_start):
                                    nxc.blockSignals(True)
                                    nxc.setCurrentIndex(i)
                                    nxc.blockSignals(False)
                                    nxc._prev_start_value = int(next_start)
                                    break
                    else:
                        was_ending = bool(total_rows > 0 and int(old_v) >= (total_rows + 1))
                        # Fallback: if previous value tracking was lost, infer by tail state.
                        if (not was_ending) and total_rows > 0:
                            try:
                                was_ending = int(new_v) <= total_rows and bool(int(old_v) == int(new_v))
                            except Exception:
                                was_ending = False
                        if (old_v > new_v) and was_ending:
                            # Special case: end changed from ending to earlier chapter on the tail episode.
                            # Request one extra episode starting at the current end.
                            self._chapter_pending_append_episode = {
                                'row': int(row),
                                'bdmv_index': int(bdmv_index),
                                'mpls_no_ext': str(mpls_no_ext),
                                'start_at_chapter': int(next_start),
                            }
                        else:
                            self._chapter_pending_append_episode = None
                self._chapter_combo_force_mode = ('end', int(row))
            end_combo._prev_end_value = int(end_combo.currentData() or (end_combo.currentIndex() + 1))
        self._chapter_change_reason = 'end'
        self._apply_start_chapter_constraints(labels)
        # End changes also trigger configuration regeneration.
        self.on_chapter_combo(row)

    def _on_sp_table_scan_finished(self):
        try:
            self._recompute_sp_output_names()
        except Exception:
            pass

    def _remove_table3_auto_chapter_sp_rows(self, bdmv_index: int, mpls_basename: str):
        if not hasattr(self, 'table3') or not self.table3:
            return
        if self.table3.columnCount() != len(ENCODE_SP_LABELS):
            return
        try:
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            out_col = ENCODE_SP_LABELS.index('output_name')
        except Exception:
            return
        target = (mpls_basename or '').strip()
        for r in range(self.table3.rowCount() - 1, -1, -1):
            try:
                b = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                continue
            if b != bdmv_index:
                continue
            m_item = self.table3.item(r, mpls_col)
            m_val = m_item.text().strip() if m_item and m_item.text() else ''
            if m_val != target:
                continue
            out_item = self.table3.item(r, out_col)
            if not self._is_auto_chapter_segment_sp_item(out_item):
                continue
            self.table3.removeRow(r)

    def _run_chapter_combo_update(self):
        if self.get_selected_function_id() not in (3, 4, 5):
            return
        try:
            forced = getattr(self, '_chapter_combo_force_mode', None)
            reason = str(getattr(self, '_chapter_change_reason', '') or '').strip()
            self._chapter_change_reason = ''
            try:
                cur_inputs = self._collect_config_inputs()
                mode, _ = self._diff_config_inputs(getattr(self, '_last_config_inputs', {}), cur_inputs)
            except Exception:
                mode = 'segments'
            if reason in ('start', 'end', 'segments'):
                mode = reason
            if isinstance(forced, tuple) and len(forced) == 2:
                try:
                    mode = str(forced[0] or mode)
                except Exception:
                    pass
            configuration = self._generate_configuration_from_ui_inputs()
            # Only view-chapters (segment checkbox) changes should refresh SP table.
            self.on_configuration(configuration, update_sp_table=(mode == 'segments'))
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def _set_segment_states_for_range(self, mpls_no_ext: str, start_idx: int, end_idx: int, checked: bool):
        if not mpls_no_ext:
            return
        mpls_path = mpls_no_ext + '.mpls'
        try:
            rows = int(self._chapter_node_data(mpls_no_ext).get('rows') or 0)
        except Exception:
            rows = 0
        if rows <= 0:
            return
        states = list(self._chapter_checkbox_states.get(mpls_path, []))
        if len(states) < rows:
            states += [True] * (rows - len(states))
        s = max(1, min(int(start_idx), rows))
        e = max(1, min(int(end_idx), rows))
        if s > e:
            s, e = e, s
        for i in range(s, e + 1):
            states[i - 1] = bool(checked)
        self._chapter_checkbox_states[mpls_path] = states

    def _snapshot_chapter_segment_sp_entries(self) -> list[dict[str, object]]:
        """Preserve ad-hoc SP rows across refresh; auto chapter-segment rows are re-applied via _sync_chapter_checkbox_sp_rows_all_volumes."""
        if not hasattr(self, 'table3') or not self.table3:
            return []
        if self.table3.columnCount() != len(ENCODE_SP_LABELS):
            return []
        try:
            sel_col = ENCODE_SP_LABELS.index('select')
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
            dur_col = ENCODE_SP_LABELS.index('duration')
            out_col = ENCODE_SP_LABELS.index('output_name')
        except Exception:
            return []
        out: list[dict[str, object]] = []
        for r in range(self.table3.rowCount()):
            out_item = self.table3.item(r, out_col)
            if not out_item:
                continue
            if self._is_auto_chapter_segment_sp_item(out_item):
                continue
            suffix = str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '').strip()
            if not suffix:
                continue
            try:
                bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
            except Exception:
                continue
            mpls_item = self.table3.item(r, mpls_col)
            m2ts_item = self.table3.item(r, m2ts_col)
            mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
            m2ts_text = m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else ''
            m2ts_files = [x.strip() for x in m2ts_text.split(',') if x.strip()]
            dur_item = self.table3.item(r, dur_col)
            dur = self._parse_display_time_to_seconds(dur_item.text() if dur_item else '')
            sel_item = self.table3.item(r, sel_col)
            default_selected = bool(sel_item and sel_item.checkState() == Qt.CheckState.Checked)
            is_disabled = bool((not sel_item) or (not (sel_item.flags() & Qt.ItemFlag.ItemIsEnabled)))
            special = str(out_item.data(Qt.ItemDataRole.UserRole + 2) or '')
            out.append({
                'bdmv_index': bdmv_index,
                'mpls_file': mpls_file,
                'm2ts_files': m2ts_files,
                'duration': dur,
                'default_selected': default_selected,
                'disabled': is_disabled,
                'special': special,
                'preserve_chapter_sp': True,
                'name_suffix': suffix,
            })
        return out

    def _sync_chapter_checkbox_sp_for_mpls(self, mpls_path: str, bdmv_index: int):
        if self.get_selected_function_id() not in (3, 4, 5):
            return
        path = mpls_path if str(mpls_path).lower().endswith('.mpls') else f'{mpls_path}.mpls'
        if not os.path.exists(path):
            return
        self._remove_table3_auto_chapter_sp_rows(bdmv_index, os.path.basename(path))
        self._sp_index_by_bdmv[bdmv_index] = self._max_sp_serial_for_bdmv(bdmv_index)
        segments, c2m = self._unchecked_segments_from_checkbox_states(path)
        if segments:
            self._add_sp_entries_for_unchecked_segments(path, segments, bdmv_index, c2m)

    def _sync_chapter_checkbox_sp_rows_all_volumes(self, configuration: dict[int, dict[str, int | str]]):
        if self.get_selected_function_id() not in (3, 4, 5) or not configuration:
            return
        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            return
        folder_to_bdmv: dict[str, int] = {}
        bdmv_to_mpls: dict[int, str] = {}
        for folder, mpls_no_ext in selected_mpls:
            if folder not in folder_to_bdmv:
                folder_to_bdmv[folder] = len(folder_to_bdmv) + 1
            bdmv_to_mpls[folder_to_bdmv[folder]] = mpls_no_ext
        for bdmv_index, mpls_no_ext in sorted(bdmv_to_mpls.items(), key=lambda x: x[0]):
            self._sync_chapter_checkbox_sp_for_mpls(mpls_no_ext + '.mpls', bdmv_index)

    def _sync_end_chapter_min_constraints(self, labels: list[str]):
        if 'start_at_chapter' not in labels or 'end_at_chapter' not in labels:
            return
        start_col = labels.index('start_at_chapter')
        end_col = labels.index('end_at_chapter')
        bdmv_col = labels.index('bdmv_index')
        bdmv_to_mpls = self._bdmv_to_first_main_mpls_from_table1()
        for r in range(self.table2.rowCount()):
            s = self.table2.cellWidget(r, start_col)
            e = self.table2.cellWidget(r, end_col)
            if isinstance(s, QComboBox) and isinstance(e, QComboBox):
                start_v = int(s.currentData() or (s.currentIndex() + 1))
                self._apply_end_combo_min_constraint(e, start_v + 1)
                b_item = self.table2.item(r, bdmv_col)
                try:
                    bdmv_index = int(b_item.text().strip()) if b_item and b_item.text() else 0
                except Exception:
                    bdmv_index = 0
                mpls_no_ext = str(b_item.data(Qt.ItemDataRole.UserRole) or '').strip() if b_item else ''
                if not mpls_no_ext:
                    mpls_no_ext = bdmv_to_mpls.get(bdmv_index, '')
                checked_states: list[bool] = []
                if mpls_no_ext:
                    checked_states = list(self._chapter_checkbox_states.get(mpls_no_ext + '.mpls', []))
                if checked_states:
                    model = e.model()
                    ending_value = int(e.itemData(e.count() - 1) or e.count())
                    last_chapter_checked = bool(checked_states[-1]) if checked_states else True
                    for i in range(e.count()):
                        v = int(e.itemData(i) or (i + 1))
                        item = model.item(i) if hasattr(model, 'item') else None
                        if item is None:
                            continue
                        if v == ending_value:
                            item.setEnabled(bool(last_chapter_checked))
                        elif 1 <= v <= len(checked_states):
                            item.setEnabled(item.isEnabled() and bool(checked_states[v - 1]))

    def _unchecked_segments_from_checkbox_states(self, mpls_path: str) -> tuple[list[tuple[int, int]], dict[int, str]]:
        """Filtered table row indices (same as ChapterWindow.get_unchecked_segments) from _chapter_checkbox_states."""
        path = mpls_path if str(mpls_path).lower().endswith('.mpls') else f'{mpls_path}.mpls'
        filtered_map, chapter_to_m2ts = self._filtered_chapter_visible_layout(path)
        if not filtered_map:
            return [], chapter_to_m2ts
        chapter = Chapter(path)
        rows = sum(map(len, chapter.mark_info.values()))
        states = list(self._chapter_checkbox_states.get(path, []))
        if len(states) < rows:
            states += [True] * (rows - len(states))
        unchecked_rows: list[int] = []
        for r, c in enumerate(filtered_map):
            if 1 <= c <= len(states) and (not states[c - 1]):
                unchecked_rows.append(r)
        segments: list[tuple[int, int]] = []
        if unchecked_rows:
            start = unchecked_rows[0]
            prev = unchecked_rows[0]
            for row_i in unchecked_rows[1:]:
                if row_i == prev + 1:
                    prev = row_i
                else:
                    segments.append((start, prev))
                    start = row_i
                    prev = row_i
            segments.append((start, prev))
        return segments, chapter_to_m2ts

    def on_chapter_combo(self, subtitle_index: int):
        if self.get_selected_function_id() in (3, 4, 5):
            if str(getattr(self, '_chapter_change_reason', '') or '') != 'end':
                self._chapter_change_reason = 'start'
            labels = ENCODE_LABELS if self.get_selected_function_id() == 4 else REMUX_LABELS
            try:
                row = int(subtitle_index)
            except Exception:
                row = -1
            if 0 <= row < self.table2.rowCount():
                start_col = labels.index('start_at_chapter')
                end_col = labels.index('end_at_chapter')
                bdmv_col = labels.index('bdmv_index')
                start_combo = self.table2.cellWidget(row, start_col)
                if isinstance(start_combo, QComboBox):
                    new_start = int(start_combo.currentData() or (start_combo.currentIndex() + 1))
                    old_start = int(getattr(start_combo, '_prev_start_value', new_start))
                    if (new_start > old_start) and (row > 0):
                        prev_end_combo = self.table2.cellWidget(row - 1, end_col)
                        prev_end = int(
                            prev_end_combo.currentData() or (prev_end_combo.currentIndex() + 1)) if isinstance(
                            prev_end_combo, QComboBox) else 0
                        b_cur = self.table2.item(row, bdmv_col)
                        b_prev = self.table2.item(row - 1, bdmv_col)
                        try:
                            bdmv_cur = int(b_cur.text().strip()) if b_cur and b_cur.text() else 0
                        except Exception:
                            bdmv_cur = 0
                        try:
                            bdmv_prev = int(b_prev.text().strip()) if b_prev and b_prev.text() else 0
                        except Exception:
                            bdmv_prev = 0
                        if (bdmv_cur == bdmv_prev) and prev_end > 0 and new_start > prev_end:
                            b_item = self.table2.item(row, bdmv_col)
                            mpls_no_ext = str(b_item.data(Qt.ItemDataRole.UserRole) or '').strip() if b_item else ''
                            if not mpls_no_ext:
                                selected_mpls = self.get_selected_mpls_no_ext()
                                bdmv_to_mpls: dict[int, str] = {}
                                for r in range(self.table1.rowCount()):
                                    it = self.table1.item(r, 0)
                                    if not it or not str(it.text() or '').strip():
                                        continue
                                    root = os.path.normpath(it.text().strip())
                                    bi = int(r + 1)
                                    for folder, m in selected_mpls:
                                        if os.path.normpath(str(folder)) == root:
                                            bdmv_to_mpls[bi] = str(m).strip()
                                            break
                                mpls_no_ext = bdmv_to_mpls.get(bdmv_cur, '')
                            self._set_segment_states_for_range(mpls_no_ext, prev_end, new_start - 1, False)
                    start_combo._prev_start_value = new_start
            self._sync_end_chapter_min_constraints(labels)
            self._pending_chapter_combo_index = int(subtitle_index)
            if hasattr(self, '_chapter_combo_debounce') and isinstance(self._chapter_combo_debounce, QTimer):
                self._chapter_combo_debounce.start()
            else:
                self._run_chapter_combo_update()
        else:
            sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount()) if
                         self.sub_check_state[sub_index] == 2]
            sub_combo_index = {}
            for sub_index in range(self.table2.rowCount()):
                if self.sub_check_state[sub_index] == 2:
                    chapter_col = SUBTITLE_LABELS.index('chapter_index')
                    w = self.table2.cellWidget(sub_index, chapter_col)
                    if isinstance(w, QComboBox) and w.isEnabled():
                        sub_combo_index[sub_index] = w.currentIndex() + 1
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if selected_mpls:
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, sub_combo_index,
                                                                             subtitle_index)
            else:
                configuration = bs.generate_configuration(self.table1, sub_combo_index, subtitle_index)
            self.on_configuration(configuration)

    def refresh_sp_table(self, configuration: dict[int, dict[str, int | str]]):
        function_id = self.get_selected_function_id()
        if function_id == 5:
            # DIY mode keeps remux-like table1/table2 only; no SP/table3 workflow.
            try:
                if hasattr(self, '_sp_scan_cancel_event') and self._sp_scan_cancel_event:
                    self._sp_scan_cancel_event.set()
            except Exception:
                pass
            try:
                if hasattr(self, '_sp_scan_progress_show_timer') and self._sp_scan_progress_show_timer:
                    self._sp_scan_progress_show_timer.stop()
            except Exception:
                pass
            try:
                if hasattr(self, '_sp_scan_progress_dialog') and self._sp_scan_progress_dialog:
                    self._sp_scan_progress_dialog.close()
                    self._sp_scan_progress_dialog.deleteLater()
            except Exception:
                pass
            self._sp_scan_progress_dialog = None
            self._sp_scan_progress_bar = None
            self._sp_scan_progress_show_timer = None
            self._sp_scan_progress_rows_seen = set()
            self._sp_scan_progress_total = 0
            self._sp_scan_progress_done = 0
            self._sp_scan_in_progress = False
            if hasattr(self, 'table3'):
                self.table3.setRowCount(0)
            return
        if function_id not in (3, 4, 5):
            if hasattr(self, 'table3'):
                self.table3.setRowCount(0)
            return
        if self._is_movie_mode():
            return
        try:
            if self.table3.columnCount() != len(ENCODE_SP_LABELS):
                self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                self._set_table_headers(self.table3, ENCODE_SP_LABELS)
            # Build selected-main map from table1 directly so SP rows can still be built
            # for discs with zero selected main MPLS (in that case, all playlist items are SP).
            selected_main_by_bdmv: dict[int, list[str]] = {}
            disc_root_by_bdmv: dict[int, str] = {}
            try:
                for r in range(self.table1.rowCount()):
                    bdmv_index = int(r + 1)
                    root_item = self.table1.item(r, 0)
                    root = root_item.text().strip() if root_item and root_item.text() else ''
                    if not root:
                        continue
                    disc_root_by_bdmv[bdmv_index] = root
                    info = self.table1.cellWidget(r, 2)
                    if not isinstance(info, QTableWidget):
                        selected_main_by_bdmv[bdmv_index] = []
                        continue
                    paths: list[str] = []
                    for i in range(info.rowCount()):
                        btn = info.cellWidget(i, 3)
                        if not (isinstance(btn, QToolButton) and btn.isChecked()):
                            continue
                        it = info.item(i, 0)
                        mpls_file = it.text().strip() if it and it.text() else ''
                        if not mpls_file:
                            continue
                        paths.append(os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_file)))
                    selected_main_by_bdmv[bdmv_index] = paths
            except Exception:
                print_exc_terminal()

            # Keep compatibility when table1 is unavailable by falling back to configuration.
            if not disc_root_by_bdmv:
                for _, conf in (configuration or {}).items():
                    try:
                        bdmv_index = int(conf.get('bdmv_index') or 0)
                    except Exception:
                        bdmv_index = 0
                    folder = str(conf.get('folder') or '').strip()
                    if bdmv_index <= 0 or (not folder):
                        continue
                    disc_root_by_bdmv.setdefault(bdmv_index, folder)
                    selected_main_by_bdmv.setdefault(bdmv_index, [])
                    mpls_no_ext = str(conf.get('selected_mpls') or '').strip()
                    if mpls_no_ext:
                        p = os.path.normpath(mpls_no_ext + '.mpls')
                        if p not in selected_main_by_bdmv[bdmv_index]:
                            selected_main_by_bdmv[bdmv_index].append(p)

            entries: list[dict[str, object]] = []
            for bdmv_index in sorted(disc_root_by_bdmv.keys()):
                root = disc_root_by_bdmv.get(bdmv_index, '')
                if not root:
                    continue
                playlist_dir = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST'))
                if not os.path.isdir(playlist_dir):
                    continue
                selected_main_paths = list(dict.fromkeys(selected_main_by_bdmv.get(bdmv_index, [])))
                selected_main_paths = [x for x in selected_main_paths if os.path.exists(x)]
                mpls_path = selected_main_paths[0] if selected_main_paths else ''
                try:
                    main_m2ts_files: set[str] = set()
                    for mp in selected_main_paths:
                        chapter = Chapter(mp)
                        index_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
                        for v in index_to_m2ts.values():
                            vv = str(v or '').strip()
                            if vv:
                                main_m2ts_files.add(vv)
                except Exception:
                    print_exc_terminal()
                    continue
                selected_main_basename_set = {os.path.basename(x) for x in selected_main_paths}

                try:
                    playlist_files = os.listdir(playlist_dir)
                except Exception:
                    print_exc_terminal()
                    playlist_files = []

                for mpls_file in sorted(playlist_files):
                    if not mpls_file.endswith('.mpls'):
                        continue
                    mpls_file_path = os.path.join(playlist_dir, mpls_file)
                    if os.path.basename(mpls_file_path) in selected_main_basename_set:
                        continue
                    try:
                        ch = Chapter(mpls_file_path)
                        idx_to_m2ts, _ = get_index_to_m2ts_and_offset(ch)
                    except Exception:
                        continue
                    ordered: list[str] = []
                    try:
                        for k in sorted(idx_to_m2ts.keys()):
                            v = str(idx_to_m2ts.get(k) or '').strip()
                            if v and v not in ordered:
                                ordered.append(v)
                    except Exception:
                        ordered = [str(x).strip() for x in idx_to_m2ts.values() if str(x).strip()]
                    m2ts_files = ordered
                    m2ts_set = set(m2ts_files)
                    default_selected = True
                    in_main_subset = bool(m2ts_set and m2ts_set.issubset(main_m2ts_files))
                    if in_main_subset:
                        default_selected = False
                    elif len(m2ts_set) >= 3:
                        default_selected = True
                    dur = ch.get_total_time()
                    try:
                        dur_for_select = float(ch.get_total_time_no_repeat())
                    except Exception:
                        dur_for_select = float(dur)
                    if len(m2ts_set) < 3 and dur_for_select < 30:
                        default_selected = False
                    entries.append({
                        'bdmv_index': bdmv_index,
                        'mpls_file': os.path.basename(mpls_file_path),
                        'm2ts_files': m2ts_files,
                        'm2ts_type': '',
                        'duration': dur,
                        'default_selected': bool(default_selected),
                        'disabled': False,
                        'special': '',
                    })

                # Add remaining m2ts not referenced by any playlist mpls.
                all_mpls_m2ts: set[str] = set()
                for pf in playlist_files:
                    if not pf.endswith('.mpls'):
                        continue
                    try:
                        ch2 = Chapter(os.path.join(playlist_dir, pf))
                        idx2, _ = get_index_to_m2ts_and_offset(ch2)
                        for _, v in idx2.items():
                            vv = str(v or '').strip()
                            if vv:
                                all_mpls_m2ts.add(vv)
                    except Exception:
                        continue
                stream_folder = os.path.join(os.path.dirname(playlist_dir), 'STREAM')
                if os.path.isdir(stream_folder):
                    try:
                        stream_files = sorted(os.listdir(stream_folder))
                    except Exception:
                        stream_files = []
                    for sf in stream_files:
                        if not sf.endswith('.m2ts'):
                            continue
                        if sf in all_mpls_m2ts:
                            continue
                        try:
                            dur = BluraySubtitle._m2ts_duration_90k(os.path.join(stream_folder, sf)) / 90000.0
                        except Exception:
                            dur = 0.0
                        entries.append({
                            'bdmv_index': bdmv_index,
                            'mpls_file': '',
                            'm2ts_files': [sf],
                            'm2ts_type': '',
                            'duration': dur,
                            # Zero-duration m2ts (typically IGS menu streams) should stay optional:
                            # keep row enabled, but default to unchecked.
                            'default_selected': bool(dur >= 30.0),
                            'disabled': False,
                            'special': '',
                        })

            def _sp_entry_sort_key(e: dict[str, object]):
                return (
                    int(e.get('bdmv_index') or 0),
                    1 if not str(e.get('mpls_file') or '').strip() else 0,
                    str(e.get('mpls_file') or ''),
                    ','.join([str(x) for x in (e.get('m2ts_files') or [])]),
                )

            def _sp_entry_key_tuple(e: dict[str, object]):
                return (
                    int(e.get('bdmv_index') or 0),
                    str(e.get('mpls_file') or ''),
                    ','.join([str(x) for x in (e.get('m2ts_files') or [])]),
                )

            entries = sorted(entries, key=_sp_entry_sort_key)
            preserved_sp = self._snapshot_chapter_segment_sp_entries()
            if preserved_sp:
                by_key: dict[tuple[int, str, str], dict[str, object]] = {}
                for e in entries:
                    by_key[_sp_entry_key_tuple(e)] = e
                for pe in preserved_sp:
                    k = _sp_entry_key_tuple(pe)
                    # Do not resurrect stale rows after main MPLS deselection.
                    # Preserve only rows that still exist in current computed entries.
                    if k in by_key:
                        by_key[k] = pe
                entries = sorted(by_key.values(), key=_sp_entry_sort_key)

            old_sorting = self.table3.isSortingEnabled()
            old_current_row = self.table3.currentRow()
            old_current_col = self.table3.currentColumn()
            old_h_scroll = self.table3.horizontalScrollBar().value() if self.table3.horizontalScrollBar() else 0
            old_v_scroll = self.table3.verticalScrollBar().value() if self.table3.verticalScrollBar() else 0
            self.table3.setSortingEnabled(False)
            try:
                self._updating_sp_table = True
                old_name_map: dict[tuple[int, str, str], tuple[str, Optional[str], str]] = {}
                row_cache: dict[tuple[int, str, str], dict[str, object]] = {}
                row_cache_out: dict[tuple[int, str, str, str], dict[str, object]] = {}
                sel_col = ENCODE_SP_LABELS.index('select')
                bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                type_col = ENCODE_SP_LABELS.index('m2ts_type')
                dur_col = ENCODE_SP_LABELS.index('duration')
                out_col = ENCODE_SP_LABELS.index('output_name')
                for r in range(self.table3.rowCount()):
                    bdmv_item = self.table3.item(r, bdmv_col)
                    mpls_item = self.table3.item(r, mpls_col)
                    m2ts_item = self.table3.item(r, m2ts_col)
                    out_item = self.table3.item(r, out_col)
                    sel_item_old = self.table3.item(r, sel_col)
                    if bdmv_item and out_item and out_item.text():
                        key = (int(bdmv_item.text() or 0), mpls_item.text() if mpls_item else '',
                               m2ts_item.text() if m2ts_item else '')
                        old_name_map[key] = (
                            out_item.text().strip(),
                            out_item.data(Qt.ItemDataRole.UserRole) if out_item else None,
                            str(out_item.data(Qt.ItemDataRole.UserRole + 2) or '').strip(),
                        )
                        cache_item = {
                            'selected': bool(
                                sel_item_old and sel_item_old.flags() & Qt.ItemFlag.ItemIsEnabled and sel_item_old.checkState() == Qt.CheckState.Checked),
                            'user_mark': str(sel_item_old.data(Qt.ItemDataRole.UserRole) or '') if sel_item_old else '',
                            'output_text': out_item.text().strip() if out_item else '',
                            'special': str(out_item.data(Qt.ItemDataRole.UserRole + 2) or '') if out_item else '',
                            'suffix': str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '') if out_item else '',
                            'm2ts_type': (
                                self.table3.item(r, type_col).text().strip() if self.table3.item(r, type_col) else ''),
                        }
                        row_cache[key] = cache_item
                        row_cache_out[(key[0], key[1], key[2], cache_item['output_text'])] = cache_item

                self.table3.setRowCount(len(entries))
                for i, e in enumerate(entries):
                    bdmv_index = int(e.get('bdmv_index') or 0)
                    mpls_file = str(e.get('mpls_file') or '')
                    m2ts_files = [str(x) for x in (e.get('m2ts_files') or [])]
                    m2ts_type = str(e.get('m2ts_type') or '')
                    dur = float(e.get('duration') or 0.0)
                    auto_out_name = ''
                    is_disabled = bool(e.get('disabled'))
                    default_selected = bool(e.get('default_selected'))
                    special = str(e.get('special') or '')
                    sel_item = QTableWidgetItem('')
                    sel_item.setCheckState(Qt.CheckState.Checked if default_selected else Qt.CheckState.Unchecked)
                    if is_disabled:
                        sel_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                        sel_item.setCheckState(Qt.CheckState.Unchecked)
                    else:
                        sel_item.setFlags(
                            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                    sel_item.setData(Qt.ItemDataRole.UserRole, 'auto')
                    self.table3.setItem(i, sel_col, sel_item)
                    self.table3.setItem(i, bdmv_col, QTableWidgetItem(str(bdmv_index)))
                    self.table3.setItem(i, mpls_col, QTableWidgetItem(mpls_file))
                    self.table3.setItem(i, m2ts_col, QTableWidgetItem(','.join(m2ts_files)))
                    self.table3.setItem(i, type_col, QTableWidgetItem(m2ts_type))
                    self.table3.setItem(i, dur_col, QTableWidgetItem(get_time_str(dur)))
                    tracks_col = ENCODE_SP_LABELS.index('tracks')
                    btn_tracks = QToolButton(self.table3)
                    btn_tracks.setText(self.t('edit tracks'))
                    btn_tracks.clicked.connect(self._on_edit_tracks_from_sp_table_clicked)
                    btn_tracks.setEnabled(not is_disabled)
                    self.table3.setCellWidget(i, tracks_col, btn_tracks)
                    play_col = ENCODE_SP_LABELS.index('play') if 'play' in ENCODE_SP_LABELS else -1
                    if play_col >= 0:
                        btn_play = QToolButton(self.table3)
                        btn_play.setText(self.t('play'))
                        btn_play.clicked.connect(self._on_play_sp_table_row_clicked)
                        btn_play.setEnabled(not is_disabled)
                        self.table3.setCellWidget(i, play_col, btn_play)
                    key = (bdmv_index, mpls_file, ','.join(m2ts_files))
                    prev = old_name_map.get(key)
                    prev_text = prev[0] if prev else ''
                    prev_auto = prev[1] if prev else None
                    prev_special = prev[2] if prev else ''
                    cache_hit = row_cache.get(key)
                    if not cache_hit:
                        cache_hit = row_cache_out.get((key[0], key[1], key[2], str(auto_out_name)))
                    if isinstance(cache_hit, dict):
                        try:
                            if bool(cache_hit.get('selected', False)):
                                sel_item.setCheckState(Qt.CheckState.Checked)
                            if str(cache_hit.get('user_mark') or ''):
                                sel_item.setData(Qt.ItemDataRole.UserRole, str(cache_hit.get('user_mark') or ''))
                            if str(cache_hit.get('m2ts_type') or '').strip():
                                m2ts_type = str(cache_hit.get('m2ts_type') or '').strip()
                                self.table3.setItem(i, type_col, QTableWidgetItem(m2ts_type))
                            if str(cache_hit.get('suffix') or ''):
                                out_item_suffix = str(cache_hit.get('suffix') or '')
                            else:
                                out_item_suffix = ''
                        except Exception:
                            out_item_suffix = ''
                    else:
                        out_item_suffix = ''
                    effective_special = special or prev_special
                    if e.get('preserve_chapter_sp'):
                        out_item = QTableWidgetItem('')
                        out_item.setData(Qt.ItemDataRole.UserRole, '')
                        out_item.setData(Qt.ItemDataRole.UserRole + 2, effective_special)
                        out_item.setData(Qt.ItemDataRole.UserRole + 3,
                                         str(e.get('name_suffix') or out_item_suffix or ''))
                    else:
                        if prev_text and isinstance(prev_auto, str) and prev_text != prev_auto:
                            final_text = prev_text
                        else:
                            final_text = auto_out_name
                        if isinstance(cache_hit, dict) and str(cache_hit.get('output_text') or '').strip():
                            cached_text = str(cache_hit.get('output_text') or '').strip()
                            if final_text == auto_out_name:
                                final_text = cached_text
                        out_item = QTableWidgetItem(final_text)
                        out_item.setData(Qt.ItemDataRole.UserRole, auto_out_name)
                        out_item.setData(Qt.ItemDataRole.UserRole + 2, effective_special)
                        out_item.setData(Qt.ItemDataRole.UserRole + 3, out_item_suffix)
                    self.table3.setItem(i, out_col, out_item)
                    if function_id == 4:
                        vpy_col = ENCODE_SP_LABELS.index('vpy_path')
                        edit_col = ENCODE_SP_LABELS.index('edit_vpy')
                        preview_col = ENCODE_SP_LABELS.index('preview_script')
                        self.table3.setCellWidget(i, vpy_col, self.create_vpy_path_widget(parent=self.table3))
                        btn = QToolButton(self.table3)
                        btn.setText(self.t('edit'))
                        btn.clicked.connect(self.on_edit_sp_vpy_clicked)
                        self.table3.setCellWidget(i, edit_col, btn)
                        btn2 = QToolButton(self.table3)
                        btn2.setText(self.t('preview'))
                        btn2.clicked.connect(self.on_preview_sp_scripts_clicked)
                        self.table3.setCellWidget(i, preview_col, btn2)
                    else:
                        for key in ('vpy_path', 'edit_vpy', 'preview_script'):
                            try:
                                col = ENCODE_SP_LABELS.index(key)
                            except Exception:
                                continue
                            self.table3.setItem(i, col, None)
                            self.table3.setCellWidget(i, col, None)
                self._recompute_sp_output_names()
                try:
                    self._sync_chapter_checkbox_sp_rows_all_volumes(configuration)
                except Exception:
                    print_exc_terminal()
                self._recompute_sp_output_names()
                self.table3.resizeColumnsToContents()
                self._resize_table_columns_for_language(self.table3)
                try:
                    if 0 <= old_current_row < self.table3.rowCount() and 0 <= old_current_col < self.table3.columnCount():
                        self.table3.setCurrentCell(old_current_row, old_current_col)
                    else:
                        self.table3.clearSelection()
                    if self.table3.horizontalScrollBar():
                        self.table3.horizontalScrollBar().setValue(old_h_scroll)
                    if self.table3.verticalScrollBar():
                        self.table3.verticalScrollBar().setValue(old_v_scroll)
                except Exception:
                    pass
            finally:
                self._updating_sp_table = False
                self.table3.setSortingEnabled(old_sorting)
            try:
                self._start_sp_table_scan()
            except Exception:
                pass
        except Exception:
            print_exc_terminal()
            self.table3.setRowCount(0)
