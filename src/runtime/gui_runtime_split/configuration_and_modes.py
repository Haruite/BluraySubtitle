"""Target module for configuration and mode-related GUI methods."""
import os
import re
import traceback
from functools import partial
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QSizePolicy, QComboBox, QTableWidgetItem, QToolButton, QTableWidget

from src.bdmv import Chapter
from src.core import ENCODE_REMUX_LABELS, ENCODE_REMUX_SP_LABELS, ENCODE_LABELS, ENCODE_SP_LABELS, REMUX_LABELS, \
    DEFAULT_APPROX_EPISODE_DURATION_SECONDS, CURRENT_UI_LANGUAGE, SUBTITLE_LABELS, BDMV_LABELS, MKV_LABELS
from src.core.i18n import translate_text
from src.domain import Subtitle
from src.exports.utils import get_time_str, print_exc_terminal, get_index_to_m2ts_and_offset
from src.runtime.gui_runtime_classes.file_path_table_widget_item import FilePathTableWidgetItem
from src.runtime.services import BluraySubtitle
from .gui_base import BluraySubtitleGuiBase


class ConfigurationModesMixin(BluraySubtitleGuiBase):
        def _apply_encode_input_mode_ui(self):
            if self.get_selected_function_id() != 4:
                try:
                    if hasattr(self, 'bdmv_path_label') and self.bdmv_path_label:
                        self.bdmv_path_label.setText(self.t('选择BDMV所在的文件夹'))
                    if hasattr(self, 'remux_path_box') and self.remux_path_box:
                        self.remux_path_box.setVisible(False)
                    if hasattr(self, 'bluray_path_box') and self.bluray_path_box:
                        self.bluray_path_box.setVisible(True)
                    if hasattr(self, 'table1') and self.table1:
                        self.table1.setVisible(True)
                    if hasattr(self, 'label1_container') and self.label1_container:
                        self.label1_container.setVisible(True)
                        self.label1_container.setMinimumHeight(0)
                        self.label1_container.setMaximumHeight(16777215)
                        self.label1_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    if hasattr(self, 'label2_container') and self.label2_container:
                        self.label2_container.setMinimumHeight(0)
                        self.label2_container.setMaximumHeight(16777215)
                        self.label2_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                    if hasattr(self, 'tables_splitter') and self.tables_splitter:
                        total_h = max(320, self.tables_splitter.height() or self.height())
                        half = max(160, int(total_h * 0.5))
                        self.tables_splitter.setStretchFactor(0, 1)
                        self.tables_splitter.setStretchFactor(1, 1)
                        self.tables_splitter.setSizes([half, max(160, total_h - half)])
                    if hasattr(self, 'series_mode_radio') and self.series_mode_radio:
                        self.series_mode_radio.setEnabled(True)
                    if hasattr(self, 'movie_mode_radio') and self.movie_mode_radio:
                        self.movie_mode_radio.setEnabled(True)
                    if hasattr(self, 'approx_episode_minutes_combo') and self.approx_episode_minutes_combo:
                        self.approx_episode_minutes_combo.setEnabled(
                            self.series_mode_radio.isChecked() if hasattr(self, 'series_mode_radio') else True)
                except Exception:
                    pass
                return

            remux_mode = getattr(self, '_encode_input_mode', 'bdmv') == 'remux'
            try:
                self.label1.setText(self.t("选择文件夹"))
            except Exception:
                pass

            try:
                if hasattr(self, 'bluray_path_box') and self.bluray_path_box:
                    self.bluray_path_box.setVisible(not remux_mode)
                if hasattr(self, 'remux_path_box') and self.remux_path_box:
                    self.remux_path_box.setVisible(remux_mode)
                if hasattr(self, 'bdmv_path_label') and self.bdmv_path_label:
                    self.bdmv_path_label.setText(
                        self.t('选择remux所在文件夹') if remux_mode else self.t('选择BDMV所在的文件夹')
                    )
                if hasattr(self, 'table1') and self.table1:
                    self.table1.setVisible(not remux_mode)
                if hasattr(self, 'label1_container') and self.label1_container:
                    self.label1_container.setVisible(not remux_mode)
                if hasattr(self, 'select_all_tracks_row') and self.select_all_tracks_row:
                    self.select_all_tracks_row.setVisible(True)
            except Exception:
                pass
            try:
                if hasattr(self, 'tables_splitter') and self.tables_splitter:
                    if remux_mode:
                        total_h = max(320, self.tables_splitter.height() or self.height())
                        top_h = 0
                        if hasattr(self, 'label1_container') and self.label1_container:
                            self.label1_container.setMinimumHeight(0)
                            self.label1_container.setMaximumHeight(0)
                            self.label1_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                        if hasattr(self, 'label2_container') and self.label2_container:
                            self.label2_container.setMinimumHeight(0)
                            self.label2_container.setMaximumHeight(16777215)
                            self.label2_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                        self.tables_splitter.setStretchFactor(0, 0)
                        self.tables_splitter.setStretchFactor(1, 1)
                        self.tables_splitter.setSizes([top_h, max(220, total_h - top_h)])
                    else:
                        total_h = max(320, self.tables_splitter.height() or self.height())
                        half = max(160, int(total_h * 0.5))
                        if hasattr(self, 'label1_container') and self.label1_container:
                            self.label1_container.setMinimumHeight(0)
                            self.label1_container.setMaximumHeight(16777215)
                            self.label1_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                        if hasattr(self, 'label2_container') and self.label2_container:
                            self.label2_container.setMinimumHeight(0)
                            self.label2_container.setMaximumHeight(16777215)
                            self.label2_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                        self.tables_splitter.setStretchFactor(0, 1)
                        self.tables_splitter.setStretchFactor(1, 1)
                        self.tables_splitter.setSizes([half, max(160, total_h - half)])
            except Exception:
                pass

            try:
                if hasattr(self, 'series_mode_radio') and self.series_mode_radio:
                    self.series_mode_radio.setEnabled(not remux_mode)
                    if remux_mode:
                        self.series_mode_radio.setChecked(True)
                if hasattr(self, 'movie_mode_radio') and self.movie_mode_radio:
                    self.movie_mode_radio.setEnabled(not remux_mode)
                if hasattr(self, 'approx_episode_minutes_combo') and self.approx_episode_minutes_combo:
                    self.approx_episode_minutes_combo.setEnabled(
                        (not remux_mode) and bool(self.series_mode_radio.isChecked()))
            except Exception:
                pass

            if remux_mode:
                self.table2.setColumnCount(len(ENCODE_REMUX_LABELS))
                self._set_table_headers(self.table2, ENCODE_REMUX_LABELS)
                self.table3.setColumnCount(len(ENCODE_REMUX_SP_LABELS))
                self._set_table_headers(self.table3, ENCODE_REMUX_SP_LABELS)
                self._update_language_combo_enabled_state()
                if getattr(self, '_language_updating', False):
                    self.table2.resizeColumnsToContents()
                    self._resize_table_columns_for_language(self.table2)
                    self._scroll_table_h_to_right(self.table2)
                    self.table3.resizeColumnsToContents()
                    self._resize_table_columns_for_language(self.table3)
                    self._scroll_table_h_to_right(self.table3)
                else:
                    self.table2.setRowCount(0)
                    self.table3.setRowCount(0)
                    try:
                        self._populate_encode_from_remux_folder()
                    except Exception:
                        pass
            else:
                self.table2.setColumnCount(len(ENCODE_LABELS))
                self._set_table_headers(self.table2, ENCODE_LABELS)
                self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                self._set_table_headers(self.table3, ENCODE_SP_LABELS)

        def _apply_episode_mode_to_table2(self):
            if not hasattr(self, '_subtitle_scan_debounce'):
                return
            function_id = self.get_selected_function_id()
            if function_id == 1:
                if self._is_movie_mode():
                    self._refresh_movie_subtitle_table2()
                else:
                    self.on_subtitle_folder_path_change()
                return
            if function_id not in (3, 4):
                return
            if self._is_movie_mode():
                self._refresh_movie_table2()
                return
            configuration = getattr(self, '_last_configuration_34', None)
            if isinstance(configuration, dict) and configuration:
                # Mode toggle (movie <-> series) should not rebuild table3/SP scan.
                self.on_configuration(configuration, update_sp_table=False)

        def _collect_config_inputs(self) -> dict[str, object]:
            labels = ENCODE_LABELS if self.get_selected_function_id() == 4 else REMUX_LABELS
            start_col = labels.index('start_at_chapter')
            end_col = labels.index('end_at_chapter')
            bdmv_col = labels.index('bdmv_index')
            selected_mpls = self.get_selected_mpls_no_ext()
            # bdmv_index must match table1 row order (bdmv_index = row + 1), not "nth disc in selected list".
            bdmv_to_mpls: dict[int, str] = {}
            try:
                for r in range(self.table1.rowCount()):
                    it = self.table1.item(r, 0)
                    if not it or not str(it.text() or '').strip():
                        continue
                    root = os.path.normpath(it.text().strip())
                    bi = int(r + 1)
                    for folder, mpls_no_ext in selected_mpls:
                        if os.path.normpath(str(folder)) == root:
                            bdmv_to_mpls[bi] = str(mpls_no_ext).strip()
                            break
            except Exception:
                bdmv_to_mpls = {}
            start_values: dict[int, int] = {}
            end_values: dict[int, int] = {}
            row_bdmv: dict[int, int] = {}
            row_mpls: dict[int, str] = {}
            for r in range(self.table2.rowCount()):
                b_item = self.table2.item(r, bdmv_col)
                try:
                    bdmv = int(b_item.text().strip()) if b_item and b_item.text() else 0
                except Exception:
                    bdmv = 0
                row_bdmv[r] = bdmv
                try:
                    row_mpls[r] = str(b_item.data(Qt.ItemDataRole.UserRole) or '').strip() if b_item else ''
                except Exception:
                    row_mpls[r] = ''
                s = self.table2.cellWidget(r, start_col)
                e = self.table2.cellWidget(r, end_col)
                start_values[r] = int(s.currentData() or (s.currentIndex() + 1)) if isinstance(s, QComboBox) else 1
                if isinstance(e, QComboBox):
                    end_values[r] = int(e.currentData() or (e.currentIndex() + 1))
                else:
                    it = self.table2.item(r, end_col)
                    end_values[r] = int(it.data(Qt.ItemDataRole.UserRole + 1) or 0) if it else 0
            segment_states: dict[str, list[bool]] = {}
            for _, mpls_no_ext in selected_mpls:
                mpls_path = mpls_no_ext + '.mpls'
                nd = self._chapter_node_data(mpls_no_ext)
                rows = int(nd['rows'])
                saved = list(self._chapter_checkbox_states.get(mpls_path, []))
                if len(saved) < rows:
                    saved += [True] * (rows - len(saved))
                segment_states[mpls_no_ext] = saved[:rows]
            return {
                'selected_mpls': selected_mpls,
                'bdmv_to_mpls': bdmv_to_mpls,
                'row_bdmv': row_bdmv,
                'row_mpls': row_mpls,
                'start': start_values,
                'end': end_values,
                'segments': segment_states,
            }

        def _diff_config_inputs(self, prev: dict[str, object], cur: dict[str, object]) -> tuple[str, int]:
            p_seg = prev.get('segments', {}) if isinstance(prev, dict) else {}
            c_seg = cur.get('segments', {})
            if p_seg != c_seg:
                return 'segments', 0
            p_start = prev.get('start', {}) if isinstance(prev, dict) else {}
            c_start = cur.get('start', {})
            changed_rows = sorted([r for r in c_start.keys() if int(p_start.get(r, c_start[r])) != int(c_start[r])])
            if changed_rows:
                return 'start', int(changed_rows[0])
            p_end = prev.get('end', {}) if isinstance(prev, dict) else {}
            c_end = cur.get('end', {})
            changed_rows = sorted([r for r in c_end.keys() if int(p_end.get(r, c_end[r])) != int(c_end[r])])
            if changed_rows:
                return 'end', int(changed_rows[0])
            return 'none', -1

        def _generate_configuration_from_ui_inputs(self) -> dict[int, dict[str, int | str]]:
            busy = self._begin_delayed_busy(self.t('Regenerating configuration...'))
            try:
                inputs = self._collect_config_inputs()
                mode, changed_row = self._diff_config_inputs(getattr(self, '_last_config_inputs', {}), inputs)
                forced = getattr(self, '_chapter_combo_force_mode', None)
                if isinstance(forced, tuple) and len(forced) == 2:
                    try:
                        mode = str(forced[0] or mode)
                        changed_row = int(forced[1])
                    except Exception:
                        pass
                self._chapter_combo_force_mode = None
                self._last_config_inputs = inputs
                selected_mpls = list(inputs.get('selected_mpls') or [])
                if not selected_mpls:
                    return {}
                bdmv_to_mpls = dict(inputs.get('bdmv_to_mpls') or {})
                row_bdmv = dict(inputs.get('row_bdmv') or {})
                row_mpls = dict(inputs.get('row_mpls') or {})
                starts = dict(inputs.get('start') or {})
                ends = dict(inputs.get('end') or {})
                segments = dict(inputs.get('segments') or {})
                prev_conf = dict(getattr(self, '_last_configuration_34', {}) or {})
                approx_end_time = float(
                    getattr(self, 'approx_episode_duration_seconds', DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
                    or DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
                gui_sub_files: list[str] = []
                try:
                    for i in range(self.table2.rowCount()):
                        it = self.table2.item(i, 0)
                        p = it.text().strip() if it and it.text() else ''
                        if p and (p.endswith('.ass') or p.endswith('.ssa') or p.endswith('.srt') or p.endswith('.sup')):
                            gui_sub_files.append(p)
                except Exception:
                    gui_sub_files = []
                if gui_sub_files:
                    missing = [p for p in gui_sub_files if p and p not in self._subtitle_cache]
                    for p in missing:
                        try:
                            self._subtitle_cache[p] = Subtitle(p)
                        except Exception:
                            pass
                    sub_max_end = [self._subtitle_cache[p].max_end_time() if p in self._subtitle_cache else approx_end_time
                                   for p in gui_sub_files]
                else:
                    sub_max_end = []
                conf: dict[int, dict[str, int | str]] = {}
                rows = self.table2.rowCount()
                node_cache: dict[str, dict[str, object]] = {}
                remove_row = int(getattr(self, '_chapter_pending_remove_row', -1) or -1)
                self._chapter_pending_remove_row = -1
                for r in range(rows):
                    if r % 2 == 0:
                        self._tick_delayed_busy(busy, self.t('Regenerating configuration...'))
                    if remove_row >= 0 and int(r) == int(remove_row):
                        continue
                    bdmv_index = int(row_bdmv.get(r, 0) or 0)
                    mpls_no_ext = str(row_mpls.get(r, '') or '').strip()
                    if not mpls_no_ext:
                        mpls_no_ext = bdmv_to_mpls.get(bdmv_index, '')
                    if not mpls_no_ext:
                        continue
                    if mpls_no_ext in node_cache:
                        node = node_cache[mpls_no_ext]
                    else:
                        node = self._chapter_node_data(mpls_no_ext)
                        node_cache[mpls_no_ext] = node
                    total_rows = int(node['rows'])
                    offsets = dict(node['offsets'])
                    m2ts = dict(node['m2ts'])
                    checked = list(segments.get(mpls_no_ext, [True] * total_rows))
                    if len(checked) < total_rows:
                        checked += [True] * (total_rows - len(checked))
                    prev_same_mpls = bool((r - 1) in conf and str(conf[r - 1].get('selected_mpls') or '') == mpls_no_ext)
                    if r < changed_row and mode in ('start', 'end') and r in prev_conf:
                        conf[r] = dict(prev_conf[r])
                        conf[r]['chapter_segments_fully_checked'] = all(checked[:total_rows])
                        continue
                    start_idx = int(starts.get(r, 1) or 1)
                    start_idx = max(1, min(total_rows, start_idx))
                    while start_idx <= total_rows and not checked[start_idx - 1]:
                        start_idx += 1
                    if start_idx > total_rows:
                        start_idx = total_rows
                    if mode == 'segments':
                        first_checked = next((i for i in range(1, total_rows + 1) if checked[i - 1]), 1)
                        if not prev_same_mpls:
                            start_idx = first_checked
                        elif prev_same_mpls:
                            start_idx = int(conf[r - 1].get('end_at_chapter') or start_idx)
                            if start_idx <= total_rows and not checked[start_idx - 1]:
                                start_idx = next((i for i in range(start_idx, total_rows + 1) if checked[i - 1]),
                                                 first_checked)
                    if mode == 'end' and r > changed_row and changed_row in conf:
                        changed_mpls = str(row_mpls.get(changed_row, '') or '').strip()
                        if not changed_mpls:
                            changed_bdmv = int(row_bdmv.get(changed_row, 0) or 0)
                            changed_mpls = str(bdmv_to_mpls.get(changed_bdmv, '') or '').strip()
                        if changed_mpls != mpls_no_ext:
                            # End change in another mpls should not affect this row.
                            if r in prev_conf:
                                conf[r] = dict(prev_conf[r])
                                conf[r]['chapter_segments_fully_checked'] = all(checked[:total_rows])
                                continue
                    target_sec = float(sub_max_end[r] if r < len(sub_max_end) else approx_end_time)
                    chosen_end = int(ends.get(r, 0) or 0)
                    if mode == 'segments':
                        # On view-chapters state changes, always recompute episode end from
                        # current checked segments instead of keeping stale table2 end value.
                        chosen_end = 0
                    if chosen_end <= start_idx:
                        chosen_end = self._closest_endpoint(start_idx, target_sec, total_rows, offsets, m2ts, checked)
                    if chosen_end > total_rows + 1:
                        chosen_end = total_rows + 1
                    # If unchecked region starts before chosen end, cut here.
                    # Keep explicit table2 start/end selections authoritative for start/end edits.
                    if mode not in ('start', 'end'):
                        for k in range(start_idx, min(chosen_end, total_rows + 1)):
                            if k <= total_rows and not checked[k - 1]:
                                chosen_end = k
                                break
                    dur = max(0.0, float(offsets.get(chosen_end, offsets.get(total_rows + 1, 0.0))) - float(
                        offsets.get(start_idx, 0.0)))
                    folder = self._folder_path_for_bdmv_index_from_table1(bdmv_index)
                    if not folder and selected_mpls:
                        try:
                            folder = os.path.normpath(str(selected_mpls[0][0] or ''))
                        except Exception:
                            folder = ''
                    disc_output_name = ''
                    try:
                        prev_row_conf = prev_conf.get(r, {}) if isinstance(prev_conf, dict) else {}
                        if str(prev_row_conf.get('selected_mpls') or '') == mpls_no_ext:
                            disc_output_name = str(prev_row_conf.get('disc_output_name') or '').strip()
                        if not disc_output_name and isinstance(prev_conf, dict):
                            for _, pc in prev_conf.items():
                                if str(pc.get('selected_mpls') or '') == mpls_no_ext:
                                    disc_output_name = str(pc.get('disc_output_name') or '').strip()
                                    if disc_output_name:
                                        break
                    except Exception:
                        disc_output_name = ''
                    if not disc_output_name:
                        disc_output_name = self._resolve_output_name_from_mpls(mpls_no_ext)
                    conf[r] = {
                        'folder': folder,
                        'selected_mpls': mpls_no_ext,
                        'bdmv_index': bdmv_index,
                        'chapter_index': int(start_idx),
                        'start_at_chapter': int(start_idx),
                        'end_at_chapter': int(chosen_end),
                        'offset': get_time_str(float(offsets.get(start_idx, 0.0))),
                        'ep_duration': get_time_str(dur),
                        'disc_output_name': disc_output_name,
                        'chapter_segments_fully_checked': all(checked[:total_rows]),
                    }
                append_req = getattr(self, '_chapter_pending_append_episode', None)
                self._chapter_pending_append_episode = None
                append_new_key: Optional[int] = None
                append_after_row = -1
                if isinstance(append_req, dict):
                    try:
                        append_after_row = int(append_req.get('row') or -1)
                        req_mpls = str(append_req.get('mpls_no_ext') or '').strip()
                        req_bdmv = int(append_req.get('bdmv_index') or 0)
                        req_start = int(append_req.get('start_at_chapter') or 1)
                    except Exception:
                        req_mpls, req_bdmv, req_start = '', 0, 1
                        append_after_row = -1
                    if req_mpls and req_bdmv > 0:
                        node = node_cache.get(req_mpls) or self._chapter_node_data(req_mpls)
                        node_cache[req_mpls] = node
                        total_rows = int(node.get('rows') or 0)
                        offsets = dict(node.get('offsets') or {})
                        m2ts = dict(node.get('m2ts') or {})
                        checked = list(segments.get(req_mpls, [True] * total_rows))
                        if len(checked) < total_rows:
                            checked += [True] * (total_rows - len(checked))
                        if total_rows > 0:
                            start_idx = max(1, min(req_start, total_rows))
                            if checked and not checked[start_idx - 1]:
                                start_idx = next((i for i in range(start_idx, total_rows + 1) if checked[i - 1]), start_idx)
                            target_sec = float(sub_max_end[len(conf)] if len(conf) < len(sub_max_end) else approx_end_time)
                            chosen_end = self._closest_endpoint(start_idx, target_sec, total_rows, offsets, m2ts, checked)
                            if chosen_end <= start_idx:
                                chosen_end = min(total_rows + 1, start_idx + 1)
                            for k in range(start_idx, min(chosen_end, total_rows + 1)):
                                if k <= total_rows and not checked[k - 1]:
                                    chosen_end = k
                                    break
                            dur = max(
                                0.0,
                                float(offsets.get(chosen_end, offsets.get(total_rows + 1, 0.0))) - float(
                                    offsets.get(start_idx, 0.0))
                            )
                            folder = self._folder_path_for_bdmv_index_from_table1(req_bdmv)
                            if not folder and selected_mpls:
                                try:
                                    folder = os.path.normpath(str(selected_mpls[0][0] or ''))
                                except Exception:
                                    folder = ''
                            disc_output_name = self._resolve_output_name_from_mpls(req_mpls)
                            new_key = (max(conf.keys()) + 1) if conf else 0
                            append_new_key = int(new_key)
                            conf[new_key] = {
                                'folder': folder,
                                'selected_mpls': req_mpls,
                                'bdmv_index': req_bdmv,
                                'chapter_index': int(start_idx),
                                'start_at_chapter': int(start_idx),
                                'end_at_chapter': int(chosen_end),
                                'offset': get_time_str(float(offsets.get(start_idx, 0.0))),
                                'ep_duration': get_time_str(dur),
                                'disc_output_name': disc_output_name,
                                'chapter_segments_fully_checked': all(checked[:total_rows]),
                            }
                # Keep UI order stable: when split from ending, insert new row right after source row.
                if conf:
                    items = sorted(conf.items(), key=lambda kv: int(kv[0]))
                    if (append_new_key is not None) and (append_after_row >= 0):
                        idx_new = next((i for i, (k, _) in enumerate(items) if int(k) == int(append_new_key)), -1)
                        idx_after = next((i for i, (k, _) in enumerate(items) if int(k) == int(append_after_row)), -1)
                        if idx_new >= 0 and idx_after >= 0 and idx_new != idx_after + 1:
                            one = items.pop(idx_new)
                            if idx_new < idx_after:
                                idx_after -= 1
                            items.insert(idx_after + 1, one)
                    conf = {i: dict(v) for i, (_, v) in enumerate(items)}
                global CONFIGURATION
                CONFIGURATION = conf
                return conf
            finally:
                self._end_delayed_busy(busy)

        def _get_approx_episode_duration_seconds(self) -> float:
            combo = getattr(self, 'approx_episode_minutes_combo', None)
            raw = ''
            if isinstance(combo, QComboBox):
                raw = (combo.currentText() or '').strip()
            try:
                minutes = float(raw)
                if minutes <= 0:
                    minutes = DEFAULT_APPROX_EPISODE_DURATION_SECONDS / 60.0
            except Exception:
                minutes = DEFAULT_APPROX_EPISODE_DURATION_SECONDS / 60.0
            return minutes * 60.0

        def _is_movie_mode(self) -> bool:
            radio = getattr(self, 'movie_mode_radio', None)
            try:
                return bool(radio and radio.isChecked())
            except Exception:
                return False

        def _rebuild_configuration_for_function_34(self):
            if self.get_selected_function_id() not in (3, 4):
                return
            if not self.bdmv_folder_path.text().strip():
                return
            if self.table1.rowCount() == 0:
                return
            if self._is_movie_mode():
                self._refresh_movie_table2()
                return
            try:
                sub_files = [self.table2.item(i, 0).text() for i in range(self.table2.rowCount()) if self.table2.item(i, 0)]
                bs = BluraySubtitle(
                    self.bdmv_folder_path.text(),
                    sub_files,
                    self.checkbox1.isChecked(),
                    None,
                    approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
                )
                selected_mpls = self.get_selected_mpls_no_ext()
                if selected_mpls:
                    configuration = bs.generate_configuration_from_selected_mpls(selected_mpls)
                else:
                    configuration = bs.generate_configuration(self.table1)
                self.on_configuration(configuration)
            except Exception:
                print_exc_terminal()

        def on_configuration(self, configuration: dict[int, dict[str, int | str]], update_sp_table: bool = True):
            busy: Optional[dict[str, object]] = None
            try:
                if not configuration:
                    print(translate_text('Configuration is empty, skipping update'))
                    return
                function_id = self.get_selected_function_id()
                if function_id in (3, 4):
                    if bool(update_sp_table):
                        busy = self._begin_delayed_busy(self.t('Updating table rows...'))
                    self._last_configuration_34 = configuration
                    try:
                        self._selected_main_mpls_prev = {
                            os.path.normpath(str(m)) for _, m in self.get_selected_mpls_no_ext()
                        }
                    except Exception:
                        pass
                    old_sorting = self.table2.isSortingEnabled()
                    self.table2.setSortingEnabled(False)
                    chapter_cache: dict[str, Chapter] = {}

                    def _chapter_cached(mpls_no_ext: str) -> Chapter:
                        key = str(mpls_no_ext or '').strip()
                        if key in chapter_cache:
                            return chapter_cache[key]
                        ch_obj = Chapter(key + '.mpls')
                        chapter_cache[key] = ch_obj
                        return ch_obj

                    labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
                    duration_col = labels.index('ep_duration')
                    bdmv_col = labels.index('bdmv_index')
                    start_col = labels.index('start_at_chapter')
                    end_col = labels.index('end_at_chapter')
                    m2ts_col = labels.index('m2ts_file')
                    language_col = labels.index('language')
                    output_col = labels.index('output_name')
                    play_col = labels.index('play') if 'play' in labels else -1
                    auto_output_name_map = self._build_episode_output_name_map(configuration)
                    if self._is_movie_mode():
                        by_bdmv: dict[int, list[int]] = {}
                        for sub_index, con in configuration.items():
                            try:
                                bdmv_index = int(con.get('bdmv_index') or 0)
                            except Exception:
                                bdmv_index = 0
                            by_bdmv.setdefault(bdmv_index, []).append(sub_index)
                        for bdmv_index in by_bdmv:
                            by_bdmv[bdmv_index].sort(key=lambda i: int(configuration[i].get('chapter_index') or 0))

                        prev_lang_by_bdmv: dict[int, str] = {}
                        prev_auto_lang_by_bdmv: dict[int, str] = {}
                        prev_name_by_bdmv: dict[int, tuple[str, str]] = {}
                        try:
                            for r in range(self.table2.rowCount()):
                                bdmv_item = self.table2.item(r, bdmv_col)
                                if not bdmv_item or not bdmv_item.text().strip():
                                    continue
                                try:
                                    bdmv_index = int(bdmv_item.text().strip())
                                except Exception:
                                    continue
                                w = self.table2.cellWidget(r, language_col)
                                if isinstance(w, QComboBox):
                                    prev_lang_by_bdmv[bdmv_index] = w.currentText().strip()
                                    prev_auto_lang_by_bdmv[bdmv_index] = str(getattr(w, '_auto_lang', '') or '')
                                it = self.table2.item(r, output_col)
                                if it and it.text():
                                    auto = it.data(Qt.ItemDataRole.UserRole)
                                    prev_name_by_bdmv[bdmv_index] = (it.text().strip(),
                                                                     auto if isinstance(auto, str) else '')
                        except Exception:
                            pass

                        disc_rows = [k for k in sorted(by_bdmv.keys()) if k != 0] + ([0] if 0 in by_bdmv else [])
                        self.table2.setRowCount(len(disc_rows))

                        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'

                        sub_files_in_folder: list[str] = []
                        if self.subtitle_folder_path.text().strip():
                            try:
                                for file in sorted(os.listdir(self.subtitle_folder_path.text().strip())):
                                    if (file.endswith(".ass") or file.endswith(".ssa") or
                                            file.endswith('srt') or file.endswith('.sup')):
                                        sub_files_in_folder.append(
                                            os.path.normpath(os.path.join(self.subtitle_folder_path.text().strip(), file)))
                            except Exception:
                                pass

                        for row_i, bdmv_index in enumerate(disc_rows):
                            if row_i % 2 == 0:
                                self._tick_delayed_busy(busy, self.t('Updating table rows...'))
                            sub_indexes = by_bdmv.get(bdmv_index, [])
                            if not sub_indexes:
                                continue
                            first_sub_index = sub_indexes[0]
                            con0 = configuration[first_sub_index]
                            bdmv_item = QTableWidgetItem(str(bdmv_index))
                            bdmv_item.setData(Qt.ItemDataRole.UserRole, str(con0.get('selected_mpls') or ''))
                            self.table2.setItem(row_i, bdmv_col, bdmv_item)

                            chapter_combo = QComboBox()
                            chapter_combo.addItem('chapter 01', 1)
                            chapter_combo.setCurrentIndex(0)
                            chapter_combo._prev_start_value = int(chapter_combo.currentData() or 1)
                            chapter_combo.setEnabled(False)
                            self.table2.setCellWidget(row_i, start_col, chapter_combo)
                            end_combo = self._build_end_chapter_combo(1, False, 1, 2)
                            end_combo.currentIndexChanged.connect(
                                partial(self._on_end_chapter_combo_changed, row_i, labels))
                            self.table2.setCellWidget(row_i, end_col, end_combo)

                            chapter = _chapter_cached(str(con0['selected_mpls']))
                            total_time = chapter.get_total_time()
                            self.table2.setItem(row_i, duration_col, QTableWidgetItem(get_time_str(total_time)))

                            index_to_m2ts, _index_to_offset = get_index_to_m2ts_and_offset(chapter)
                            try:
                                rows = sum(map(len, chapter.mark_info.values()))
                                m2ts_files = sorted(
                                    list(set(index_to_m2ts[i] for i in range(1, rows + 1) if i in index_to_m2ts)))
                            except Exception:
                                m2ts_files = sorted(list(set(index_to_m2ts.values())))
                            self.table2.setItem(row_i, m2ts_col, QTableWidgetItem(', '.join(m2ts_files)))

                            prev_lang = prev_lang_by_bdmv.get(bdmv_index, '').strip()
                            prev_auto_lang = prev_auto_lang_by_bdmv.get(bdmv_index, '').strip()
                            if prev_lang and prev_auto_lang and prev_lang != prev_auto_lang:
                                final_lang = prev_lang
                            elif prev_lang and not prev_auto_lang:
                                final_lang = prev_lang
                            else:
                                final_lang = auto_lang
                            lang_combo = self.create_language_combo(final_lang)
                            lang_combo._auto_lang = auto_lang
                            self.table2.setCellWidget(row_i, language_col, lang_combo)

                            auto_name = auto_output_name_map.get(first_sub_index, '')
                            if auto_name:
                                auto_name = re.sub(r'^(?i:EP)\s*\d+\s*', '', auto_name)
                                auto_name = re.sub(r'\s*-\d{3}(?=\.mkv$)', '', auto_name)
                            prev_name, prev_auto = prev_name_by_bdmv.get(bdmv_index, ('', ''))
                            if prev_name and prev_auto and prev_name != prev_auto:
                                final_text = prev_name
                            else:
                                final_text = auto_name
                            new_item = QTableWidgetItem(final_text)
                            new_item.setData(Qt.ItemDataRole.UserRole, auto_name)
                            self.table2.setItem(row_i, output_col, new_item)

                            if sub_files_in_folder:
                                idx = first_sub_index
                                if 0 <= idx < len(sub_files_in_folder):
                                    self.table2.setItem(row_i, 0, FilePathTableWidgetItem(sub_files_in_folder[idx]))

                            self.ensure_encode_row_widgets(row_i)
                            if play_col >= 0:
                                btn_play = QToolButton(self.table2)
                                btn_play.setText(self.t('play'))
                                btn_play.clicked.connect(partial(self.on_play_table2_disc_row, row_i, bdmv_col, m2ts_col))
                                self.table2.setCellWidget(row_i, play_col, btn_play)
                    else:
                        self.table2.setRowCount(len(configuration))
                        for sub_index, con in configuration.items():
                            if int(sub_index) % 2 == 0:
                                self._tick_delayed_busy(busy, self.t('Updating table rows...'))
                            bdmv_item = QTableWidgetItem(str(con['bdmv_index']))
                            bdmv_item.setData(Qt.ItemDataRole.UserRole, str(con.get('selected_mpls') or ''))
                            self.table2.setItem(sub_index, bdmv_col, bdmv_item)
                            chapter_combo = QComboBox()
                            duration = 0
                            chapter = _chapter_cached(str(con['selected_mpls']))
                            rows = sum(map(len, chapter.mark_info.values()))
                            j1 = int(con.get('chapter_index') or 1)
                            next_con = configuration.get(sub_index + 1)
                            if con.get('end_at_chapter'):
                                j2 = int(con.get('end_at_chapter') or 0)
                            elif next_con and str(next_con.get('selected_mpls') or '') == str(
                                    con.get('selected_mpls') or ''):
                                # Same playlist: next episode's start defines this row's implicit end.
                                # Do not require folder equality (folder can be wrong if selected_mpls order
                                # was used as a disc index elsewhere); matching mpls is the stable key.
                                j2 = int(next_con.get('chapter_index') or 0)
                            else:
                                j2 = rows + 1
                            # Clamp bounds to avoid invalid chapter indices (e.g. rows+1 start).
                            j1 = max(1, min(j1, rows + 1))
                            j2 = max(j1 + 1, min(j2, rows + 1))
                            index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
                            m2ts_files = sorted(list(set([index_to_m2ts[i] for i in range(j1, j2) if i in index_to_m2ts])))
                            has_beginning = False
                            try:
                                has_beginning = bool(float(index_to_offset.get(1, 0.0) or 0.0) > 0.001)
                            except Exception:
                                has_beginning = False
                            options = self._build_start_chapter_options(rows, has_beginning)
                            for v, txt in options:
                                chapter_combo.addItem(txt, v)
                            selected_idx = 0
                            for i_opt in range(chapter_combo.count()):
                                if int(chapter_combo.itemData(i_opt) or 0) == int(con['chapter_index']):
                                    selected_idx = i_opt
                                    break
                            chapter_combo.setCurrentIndex(selected_idx)
                            chapter_combo._prev_start_value = int(
                                chapter_combo.currentData() or (chapter_combo.currentIndex() + 1))
                            chapter_combo.currentIndexChanged.connect(partial(self.on_chapter_combo, sub_index))
                            start_off = float(index_to_offset.get(j1, chapter.get_total_time()))
                            end_off = float(index_to_offset.get(j2, chapter.get_total_time()))
                            if end_off < start_off:
                                end_off = start_off
                            duration = end_off - start_off
                            duration = get_time_str(duration)
                            self.table2.setCellWidget(sub_index, start_col, chapter_combo)
                            end_combo = self._build_end_chapter_combo(rows, has_beginning, int(j1), int(j2))
                            end_combo.currentIndexChanged.connect(
                                partial(self._on_end_chapter_combo_changed, sub_index, labels))
                            self.table2.setCellWidget(sub_index, end_col, end_combo)
                            self.table2.setItem(sub_index, m2ts_col, QTableWidgetItem(', '.join(m2ts_files)))
                            self.table2.setItem(sub_index, duration_col, QTableWidgetItem(duration))

                            prev_lang_widget = self.table2.cellWidget(sub_index, language_col)
                            prev_lang = ''
                            prev_auto_lang = ''
                            if isinstance(prev_lang_widget, QComboBox):
                                prev_lang = prev_lang_widget.currentText().strip()
                                prev_auto_lang = str(getattr(prev_lang_widget, '_auto_lang', 'chi') or 'chi')
                            auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
                            if prev_lang and prev_lang != prev_auto_lang:
                                final_lang = prev_lang
                            else:
                                final_lang = auto_lang
                            lang_combo = self.create_language_combo(final_lang)
                            lang_combo._auto_lang = auto_lang
                            self.table2.setCellWidget(sub_index, language_col, lang_combo)
                            auto_name = auto_output_name_map.get(sub_index, '')
                            prev_item = self.table2.item(sub_index, output_col)
                            prev_text = prev_item.text().strip() if prev_item and prev_item.text() else ''
                            prev_auto = prev_item.data(Qt.ItemDataRole.UserRole) if prev_item else None
                            if prev_text and isinstance(prev_auto, str) and prev_text != prev_auto:
                                final_text = prev_text
                            else:
                                final_text = auto_name
                            new_item = QTableWidgetItem(final_text)
                            new_item.setData(Qt.ItemDataRole.UserRole, auto_name)
                            self.table2.setItem(sub_index, output_col, new_item)
                            self.ensure_encode_row_widgets(sub_index)
                            if play_col >= 0:
                                btn_play = QToolButton(self.table2)
                                btn_play.setText(self.t('play'))
                                btn_play.clicked.connect(
                                    partial(self.on_play_table2_disc_row, sub_index, bdmv_col, m2ts_col))
                                self.table2.setCellWidget(sub_index, play_col, btn_play)
                    if self.subtitle_folder_path.text().strip():
                        sub_files = []
                        try:
                            for file in sorted(os.listdir(self.subtitle_folder_path.text().strip())):
                                if (file.endswith(".ass") or file.endswith(".ssa") or
                                        file.endswith('srt') or file.endswith('.sup')):
                                    sub_files.append(
                                        os.path.normpath(os.path.join(self.subtitle_folder_path.text().strip(), file)))
                        except Exception:
                            pass
                        if sub_files:
                            for i, sub_file in enumerate(sub_files):
                                if (not self._is_movie_mode()) and i < len(configuration) and i < self.table2.rowCount():
                                    self.table2.setItem(i, 0, FilePathTableWidgetItem(sub_file))
                    self.table2.resizeColumnsToContents()
                    self._resize_table_columns_for_language(self.table2)
                    self._update_language_combo_enabled_state()
                    self._sync_end_chapter_min_constraints(labels)
                    self._apply_start_chapter_constraints(labels)
                    self._scroll_table_h_to_right(self.table2)
                    if function_id in (3, 4):
                        if update_sp_table:
                            self._tick_delayed_busy(busy, self.t('Refreshing SP table...'))
                            self.refresh_sp_table(configuration)
                        try:
                            self._refresh_table1_remux_cmds()
                        except Exception:
                            pass
                    self.table2.setSortingEnabled(old_sorting)
                else:
                    if self._is_movie_mode():
                        return
                    sub_check_state = [self.table2.item(sub_index, 0).checkState().value for sub_index in
                                       range(self.table2.rowCount())]
                    index_table = [sub_index for sub_index in range(len(sub_check_state)) if
                                   sub_check_state[sub_index] == 2]

                    bdmv_col = SUBTITLE_LABELS.index('bdmv_index')
                    chapter_col = SUBTITLE_LABELS.index('chapter_index')
                    offset_col = SUBTITLE_LABELS.index('offset')
                    ep_duration_col = SUBTITLE_LABELS.index('ep_duration')

                    for subtitle_index, row in enumerate(index_table):
                        con = configuration.get(subtitle_index)
                        if con:
                            self.table2.setItem(row, bdmv_col, QTableWidgetItem(str(con['bdmv_index'])))

                            chapter = Chapter(str(con['selected_mpls']) + '.mpls')
                            rows = sum(map(len, chapter.mark_info.values()))
                            chapter_combo = QComboBox()
                            chapter_combo.addItems([str(r + 1) for r in range(rows)])
                            chapter_combo.setCurrentIndex(con['chapter_index'] - 1)
                            chapter_combo.currentIndexChanged.connect(partial(self.on_chapter_combo, subtitle_index))
                            self.table2.setCellWidget(row, chapter_col, chapter_combo)
                            self.table2.setItem(row, offset_col, QTableWidgetItem(con['offset']))

                            duration = 0
                            j1 = int(con['chapter_index'])
                            next_con = configuration.get(subtitle_index + 1)
                            if next_con and next_con.get('folder') == con.get('folder') and next_con.get(
                                    'selected_mpls') == con.get('selected_mpls'):
                                j2 = int(next_con['chapter_index'])
                            else:
                                j2 = rows + 1
                            _index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
                            try:
                                if next_con and next_con.get('folder') == con.get('folder') and next_con.get(
                                        'selected_mpls') == con.get('selected_mpls'):
                                    duration = index_to_offset[j2] - index_to_offset[j1]
                                else:
                                    duration = chapter.get_total_time() - index_to_offset[j1]
                            except Exception:
                                duration = chapter.get_total_time()
                            self.table2.setItem(row, ep_duration_col, QTableWidgetItem(get_time_str(duration)))
                        else:
                            self.table2.setItem(row, bdmv_col, None)
                            self.table2.setItem(row, ep_duration_col, None)
                            self.table2.setCellWidget(row, chapter_col, None)
                            self.table2.setItem(row, offset_col, None)
                    self.table2.resizeColumnsToContents()
                    self.altered = True
            except Exception:
                self._show_error_dialog(traceback.format_exc())
                if hasattr(self, 'table3'):
                    self.table3.setRowCount(0)
                return
            finally:
                self._end_delayed_busy(busy)

        def on_select_function(self, force: bool = False, keep_inputs: bool = False, keep_state: bool = False):
            if getattr(self, '_language_updating', False):
                keep_inputs = True
                keep_state = True
            function_id = self.get_selected_function_id()
            if function_id not in (3, 4):
                self._cleanup_info_json_if_needed()

            last_function_id = int(getattr(self, '_selected_function_id', 0) or 0)
            if (not force) and function_id and last_function_id == function_id:
                return
            self._selected_function_id = function_id
            self._refresh_function_tabbar_theme()

            if hasattr(self, 'output_folder_row') and self.output_folder_row:
                self.output_folder_row.setVisible(function_id in (3, 4))
            if hasattr(self, 'select_all_tracks_row') and self.select_all_tracks_row:
                visible = function_id in (3, 4)
                self.select_all_tracks_row.setVisible(visible)
            if hasattr(self, 'episode_mode_row') and self.episode_mode_row:
                self.episode_mode_row.setVisible(function_id in (1, 3, 4))
            if hasattr(self, 'encode_source_row') and self.encode_source_row:
                self.encode_source_row.setVisible(function_id == 4)
            if hasattr(self, 'table3'):
                self.table3.setVisible(function_id in (3, 4))
                try:
                    labels = ENCODE_SP_LABELS
                    if function_id == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
                        labels = ENCODE_REMUX_SP_LABELS
                    if self.table3.columnCount() != len(labels):
                        self.table3.setColumnCount(len(labels))
                        self._set_table_headers(self.table3, labels)
                    is_encode = function_id == 4
                    if 'vpy_path' in labels:
                        self.table3.setColumnHidden(labels.index('vpy_path'), not is_encode)
                    if 'edit_vpy' in labels:
                        self.table3.setColumnHidden(labels.index('edit_vpy'), not is_encode)
                    if 'preview_script' in labels:
                        self.table3.setColumnHidden(labels.index('preview_script'), not is_encode)
                    self._scroll_table_h_to_right(self.table3)
                except Exception:
                    pass

            if function_id in (3, 4):
                try:
                    if self.table1.columnCount() != len(BDMV_LABELS):
                        self.table1.setColumnCount(len(BDMV_LABELS))
                        self._set_table_headers(self.table1, BDMV_LABELS)
                    cmd_col = BDMV_LABELS.index('remux_cmd') if 'remux_cmd' in BDMV_LABELS else -1
                    if cmd_col >= 0:
                        self.table1.setColumnWidth(cmd_col, 420 if getattr(self, '_language_code',
                                                                           CURRENT_UI_LANGUAGE) == 'zh' else 380)
                        self._refresh_table1_remux_cmds()
                except Exception:
                    pass
            if function_id != 4:
                self._encode_input_mode = 'bdmv'
                try:
                    if hasattr(self, 'encode_source_bdmv_radio') and self.encode_source_bdmv_radio:
                        self.encode_source_bdmv_radio.setChecked(True)
                except Exception:
                    pass
            try:
                self._apply_encode_input_mode_ui()
            except Exception:
                pass
            if function_id == 4:
                QTimer.singleShot(0, self.ensure_default_vpy_file)

            if function_id == 1:
                self.label2.setText(self.t("选择字幕文件夹"))
                self.exe_button.setText(self.t("生成字幕"))
                self.encode_box.setVisible(False)
                if not self.checkbox1.isVisible():
                    self.checkbox1.setVisible(True)
                    if hasattr(self, '_geometry') and self._geometry is not None:
                        self.restoreGeometry(self._geometry)
                self.checkbox1.setText(self.t('补全蓝光目录'))
                if hasattr(self, 'merge_options_row') and self.merge_options_row:
                    self.merge_options_row.setVisible(True)
                if hasattr(self, 'subtitle_suffix_label') and self.subtitle_suffix_label:
                    self.subtitle_suffix_label.setVisible(True)
                if hasattr(self, 'subtitle_suffix_combo') and self.subtitle_suffix_combo:
                    self.subtitle_suffix_combo.setVisible(True)
                if not keep_state:
                    self.table1.clear()
                    self.table1.setRowCount(0)
                    self.table1.setColumnCount(len(BDMV_LABELS))
                    self._set_table_headers(self.table1, BDMV_LABELS)
                    self.table2.clear()
                    self.table2.setRowCount(0)
                    self.table2.setColumnCount(len(SUBTITLE_LABELS))
                    self._set_table_headers(self.table2, SUBTITLE_LABELS)
                    self._set_table2_subtitle_column_order()

            if function_id == 2:
                self.label2.setText(self.t("选择mkv所在文件夹"))
                self.exe_button.setText(self.t("添加章节"))
                self.encode_box.setVisible(False)
                if not self.checkbox1.isVisible():
                    self.checkbox1.setVisible(True)
                    if hasattr(self, '_geometry') and self._geometry is not None:
                        self.restoreGeometry(self._geometry)
                self.checkbox1.setText(self.t('直接编辑原文件'))
                if hasattr(self, 'merge_options_row') and self.merge_options_row:
                    self.merge_options_row.setVisible(True)
                if hasattr(self, 'subtitle_suffix_label') and self.subtitle_suffix_label:
                    self.subtitle_suffix_label.setVisible(False)
                if hasattr(self, 'subtitle_suffix_combo') and self.subtitle_suffix_combo:
                    self.subtitle_suffix_combo.setVisible(False)
                if not keep_state:
                    self.table1.clear()
                    self.table1.setRowCount(0)
                    self.table1.setColumnCount(len(BDMV_LABELS))
                    self._set_table_headers(self.table1, BDMV_LABELS)
                    self.table2.clear()
                    self.table2.setRowCount(0)
                    self.table2.setColumnCount(len(MKV_LABELS))
                    self._set_table_headers(self.table2, MKV_LABELS)
                    self._set_table2_default_column_order()

            if function_id == 3:
                if not keep_state:
                    self._geometry = self.saveGeometry()
                self.label2.setText(self.t("选择字幕文件夹（可选）"))
                self.exe_button.setText(self.t("开始remux"))
                self.encode_box.setVisible(False)
                self.checkbox1.setVisible(False)
                if hasattr(self, 'merge_options_row') and self.merge_options_row:
                    self.merge_options_row.setVisible(False)
                if not keep_state:
                    self.table1.clear()
                    self.table1.setRowCount(0)
                    self.table1.setColumnCount(len(BDMV_LABELS))
                    self._set_table_headers(self.table1, BDMV_LABELS)
                    self.table2.clear()
                    self.table2.setRowCount(0)
                    self.table2.setColumnCount(len(REMUX_LABELS))
                    self._set_table_headers(self.table2, REMUX_LABELS)
                    self._set_table2_default_column_order()
                    if hasattr(self, 'table3'):
                        self.table3.clear()
                        self.table3.setRowCount(0)
                        self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                        self._set_table_headers(self.table3, ENCODE_SP_LABELS)

            if function_id == 4:
                if not keep_state:
                    self._geometry = self.saveGeometry()
                self.label2.setText(self.t("选择字幕文件夹（可选）"))
                self.exe_button.setText(self.t("开始压制"))
                self.checkbox1.setVisible(False)
                if hasattr(self, 'merge_options_row') and self.merge_options_row:
                    self.merge_options_row.setVisible(False)
                self.encode_box.setVisible(True)
                if not keep_state:
                    self.table1.clear()
                    self.table1.setRowCount(0)
                    self.table1.setColumnCount(len(BDMV_LABELS))
                    self._set_table_headers(self.table1, BDMV_LABELS)
                    self.table2.clear()
                    self.table2.setRowCount(0)
                    self.table2.setColumnCount(len(ENCODE_LABELS))
                    self._set_table_headers(self.table2, ENCODE_LABELS)
                    self._set_table2_default_column_order()
                    if hasattr(self, 'table3'):
                        self.table3.clear()
                        self.table3.setRowCount(0)
                        self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                        self._set_table_headers(self.table3, ENCODE_SP_LABELS)

            if not keep_inputs:
                self.bdmv_folder_path.clear()
                self.subtitle_folder_path.clear()
            try:
                self._reposition_subtitle_path_box()
            except Exception:
                pass
            self._refresh_function_tabbar_theme()

        def get_selected_function_id(self) -> int:
            try:
                tabbar = getattr(self, 'function_tabbar', None)
                if tabbar is not None:
                    idx = int(tabbar.currentIndex())
                    if idx >= 0:
                        return idx + 1
            except Exception:
                pass
            try:
                return int(getattr(self, '_selected_function_id', 1) or 1)
            except Exception:
                return 1

        def get_selected_mpls_no_ext(self) -> list[tuple[str, str]]:
            selected = []
            for bdmv_index in range(self.table1.rowCount()):
                folder_item = self.table1.item(bdmv_index, 0)
                if not folder_item:
                    continue
                info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                if not info:
                    continue
                for mpls_index in range(info.rowCount()):
                    main_btn: QToolButton = info.cellWidget(mpls_index, 3)
                    if main_btn and main_btn.isChecked():
                        mpls_item = info.item(mpls_index, 0)
                        if not mpls_item:
                            continue
                        mpls_file = mpls_item.text()
                        selected_mpls = os.path.normpath(os.path.join(folder_item.text(), 'BDMV', 'PLAYLIST', mpls_file))
                        if selected_mpls.lower().endswith('.mpls'):
                            selected.append((folder_item.text(), selected_mpls[:-5]))
                        else:
                            selected.append((folder_item.text(), selected_mpls))
            return selected
