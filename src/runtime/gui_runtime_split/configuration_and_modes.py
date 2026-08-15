"""Target module for configuration and mode-related GUI methods."""
import copy
import os
import re
import traceback
from functools import partial
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QSizePolicy, QComboBox, QTableWidgetItem, QToolButton, QTableWidget

from src.bdmv.chapter import Chapter, episode_tail_trim_plan
from src.core import ENCODE_REMUX_LABELS, ENCODE_REMUX_SP_LABELS, ENCODE_LABELS, ENCODE_SP_LABELS, REMUX_LABELS, \
    DEFAULT_APPROX_EPISODE_DURATION_SECONDS, CURRENT_UI_LANGUAGE, SUBTITLE_LABELS, BDMV_LABELS, MKV_LABELS, \
    DIY_BDMV_LABELS, DIY_SP_LABELS, DIY_REMUX_LABELS, MPLS_INFO_LABELS
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
                    self.bdmv_path_label.setText(self.t('Select the BDMV folder'))
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
                if hasattr(self, 'remux_flac_checkbox') and self.remux_flac_checkbox:
                    self.remux_flac_checkbox.setVisible(self.get_selected_function_id() == 3)
            except Exception:
                pass
            return

        remux_mode = getattr(self, '_encode_input_mode', 'bdmv') == 'remux'
        try:
            self.label1.setText(self.t("Select folder"))
        except Exception:
            pass

        try:
            if hasattr(self, 'bluray_path_box') and self.bluray_path_box:
                self.bluray_path_box.setVisible(not remux_mode)
            if hasattr(self, 'remux_path_box') and self.remux_path_box:
                self.remux_path_box.setVisible(remux_mode)
            if hasattr(self, 'bdmv_path_label') and self.bdmv_path_label:
                self.bdmv_path_label.setText(
                    self.t('Select the remux folder') if remux_mode else self.t('Select the BDMV folder')
                )
            if hasattr(self, 'table1') and self.table1:
                self.table1.setVisible(not remux_mode)
            if hasattr(self, 'label1_container') and self.label1_container:
                self.label1_container.setVisible(not remux_mode)
            if hasattr(self, 'select_all_tracks_row') and self.select_all_tracks_row:
                self.select_all_tracks_row.setVisible(True)
            if hasattr(self, 'trim_copyright_tail_checkbox') and self.trim_copyright_tail_checkbox:
                self.trim_copyright_tail_checkbox.setVisible(not remux_mode)
            if hasattr(self, 'mux_dolby_vision_checkbox') and self.mux_dolby_vision_checkbox:
                self.mux_dolby_vision_checkbox.setVisible(not remux_mode)
            if hasattr(self, 'remux_flac_checkbox') and self.remux_flac_checkbox:
                self.remux_flac_checkbox.setVisible(False)
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
            for c in range(self.table2.columnCount()):
                self.table2.setColumnHidden(c, False)
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
            # BDMV vs remux use different column counts and semantics (ENCODE_LABELS has bdmv/chapter/m2ts;
            # ENCODE_REMUX has output/vpy earlier + mkv track buttons). If we only resize columns, old
            # QTableWidgetItem / cellWidget stay at the same (row,col) and appear under wrong headers.
            self.table2.setColumnCount(len(ENCODE_LABELS))
            self._set_table_headers(self.table2, ENCODE_LABELS)
            for c in range(self.table2.columnCount()):
                self.table2.setColumnHidden(c, False)
            self.table3.setColumnCount(len(ENCODE_SP_LABELS))
            self._set_table_headers(self.table3, ENCODE_SP_LABELS)
            self.table2.setRowCount(0)
            self.table3.setRowCount(0)
            self._set_table2_default_column_order()
            self._update_language_combo_enabled_state()
            try:
                cfg = getattr(self, '_last_configuration_34', None)
                if isinstance(cfg, dict) and cfg:
                    self.on_configuration(cfg, update_sp_table=True)
                elif self._is_movie_mode():
                    self._refresh_movie_table2()
            except Exception:
                print_exc_terminal()
            try:
                self.table2.resizeColumnsToContents()
                self._resize_table_columns_for_language(self.table2)
                if self._is_movie_mode():
                    fid = self.get_selected_function_id()
                    if fid == 4:
                        t2labels = list(ENCODE_LABELS)
                    elif fid == 5:
                        t2labels = list(DIY_REMUX_LABELS)
                    else:
                        t2labels = list(REMUX_LABELS)
                    self._finalize_movie_mode_table2_layout(t2labels)
                else:
                    self._scroll_table_h_to_right(self.table2)
                self.table3.resizeColumnsToContents()
                self._resize_table_columns_for_language(self.table3)
                self._scroll_table_h_to_right(self.table3)
            except Exception:
                pass

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
        if function_id not in (3, 4, 5):
            return
        self._full_refresh_remux_encode_tables_for_mode()

    def _update_trim_copyright_tail_checkbox_for_episode_movie_mode(self) -> None:
        """Movie mode: trim checkbox off and disabled. Series mode: restore last series choice (default on)."""
        cb = getattr(self, 'trim_copyright_tail_checkbox', None)
        if not cb or self.get_selected_function_id() not in (3, 4):
            return
        try:
            if self._is_movie_mode():
                if cb.isEnabled():
                    try:
                        self._trim_tail_last_series_checked = bool(cb.isChecked())
                    except Exception:
                        self._trim_tail_last_series_checked = True
                cb.blockSignals(True)
                cb.setEnabled(False)
                cb.setChecked(False)
                cb.blockSignals(False)
            else:
                cb.blockSignals(True)
                cb.setEnabled(True)
                cb.setChecked(bool(getattr(self, '_trim_tail_last_series_checked', True)))
                cb.blockSignals(False)
        except Exception:
            try:
                cb.blockSignals(False)
            except Exception:
                pass

    def _collect_config_inputs(self) -> dict[str, object]:
        current_fid = self.get_selected_function_id()
        if current_fid == 4:
            labels = ENCODE_LABELS
        elif current_fid == 5:
            labels = DIY_REMUX_LABELS
        else:
            labels = REMUX_LABELS
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

    def _on_trim_copyright_tail_toggled(self, _checked: bool = False) -> None:
        try:
            cb = getattr(self, 'trim_copyright_tail_checkbox', None)
            if cb and cb.isEnabled() and (not self._is_movie_mode()):
                self._trim_tail_last_series_checked = bool(cb.isChecked())
        except Exception:
            pass
        try:
            function_id = self.get_selected_function_id()
            configuration = getattr(self, '_last_configuration_34', None)
            if function_id in (3, 4) and isinstance(configuration, dict) and configuration:
                # Tail trimming is a post-split operation. Keep every visible episode bound intact and
                # update only the per-episode cut plan and its M2TS preview.
                updated_configuration = {
                    int(key): dict(row)
                    for key, row in configuration.items()
                    if isinstance(row, dict)
                }
                self._apply_episode_copyright_trim_to_configuration(
                    updated_configuration,
                    bool(cb and cb.isChecked() and (not self._is_movie_mode())),
                )
                self._last_configuration_34 = updated_configuration
                labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
                self._refresh_table2_m2ts_duration_from_widgets(labels)
            self._refresh_table1_remux_cmds()
        except Exception:
            print_exc_terminal()

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

    def _segment_diff_mpls(self, prev: dict[str, object], cur: dict[str, object]) -> set[str]:
        """MPLS stems whose view-chapters checkbox states changed."""
        p_seg = prev.get('segments', {}) if isinstance(prev, dict) else {}
        c_seg = cur.get('segments', {}) if isinstance(cur, dict) else {}
        out: set[str] = set()
        for m in set(p_seg.keys()) | set(c_seg.keys()):
            if list(p_seg.get(m, [])) != list(c_seg.get(m, [])):
                out.add(str(m))
        return out

    def _apply_episode_copyright_trim_to_configuration(
            self,
            configuration: dict[int, dict[str, int | str]],
            enabled: bool,
    ) -> None:
        """Attach per-episode tail cuts without changing authored chapter or play-item data."""
        for row in configuration.values():
            row.pop('copyright_trim_end_offset', None)
        if not enabled:
            return

        chapter_cache: dict[str, tuple[Chapter, dict[int, float], int]] = {}
        for row in configuration.values():
            mpls_path = self._main_mpls_abs_path_for_remux_cmd_lookup(row)
            if not mpls_path or not os.path.isfile(mpls_path):
                continue
            if mpls_path not in chapter_cache:
                chapter = Chapter(mpls_path)
                _index_to_m2ts, index_to_offset = get_index_to_m2ts_and_offset(chapter)
                total_end = sum(map(len, chapter.mark_info.values())) + 1
                chapter_cache[mpls_path] = (chapter, index_to_offset, total_end)
            chapter, index_to_offset, total_end = chapter_cache[mpls_path]
            start_chapter = int(row.get('start_at_chapter') or row.get('chapter_index') or 1)
            end_chapter = int(row.get('end_at_chapter') or total_end)
            start_offset = (
                chapter.get_total_time()
                if start_chapter >= total_end
                else float(index_to_offset.get(start_chapter, 0.0))
            )
            end_offset = (
                chapter.get_total_time()
                if end_chapter >= total_end
                else float(index_to_offset.get(end_chapter, chapter.get_total_time()))
            )
            trimmed_end, _removed_m2ts = episode_tail_trim_plan(
                chapter,
                start_offset,
                end_offset,
            )
            if trimmed_end >= end_offset - (1.0 / 45000.0):
                continue
            row['copyright_trim_end_offset'] = f'{trimmed_end:.6f}'

    def _generate_configuration_from_ui_inputs(self) -> dict[int, dict[str, int | str]]:
        busy = self._begin_delayed_busy(self.t('Regenerating configuration...'))
        try:
            inputs = self._collect_config_inputs()
            old_inputs = getattr(self, '_last_config_inputs', {}) or {}
            mode, changed_row = self._diff_config_inputs(old_inputs, inputs)
            segment_changed_mpls: set[str] = set()
            if mode == 'segments':
                segment_changed_mpls = self._segment_diff_mpls(old_inputs, inputs)
            forced = getattr(self, '_chapter_combo_force_mode', None)
            if isinstance(forced, tuple) and len(forced) == 2:
                try:
                    mode = str(forced[0] or mode)
                    changed_row = int(forced[1])
                except Exception:
                    pass
            self._chapter_combo_force_mode = None
            self._last_config_inputs = inputs

            _trim_cb = getattr(self, 'trim_copyright_tail_checkbox', None)
            want_tail_trim = bool(
                _trim_cb and _trim_cb.isChecked()
                and (not self._is_movie_mode())
                and self.get_selected_function_id() in (3, 4)
            )

            def _chapter_seg_fully_checked(_mpls_key: str, checked_list: list[bool], total: int) -> bool:
                if total <= 0:
                    return True
                return all(checked_list[:total])
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
            target_seconds_by_row: dict[int, float] = {}
            for row_index in range(self.table2.rowCount()):
                target_seconds_by_row[row_index] = approx_end_time
                try:
                    subtitle_item = self.table2.item(row_index, 0)
                    subtitle_path = (
                        subtitle_item.text().strip()
                        if subtitle_item and subtitle_item.text()
                        else ''
                    )
                except Exception:
                    subtitle_path = ''
                if not subtitle_path.lower().endswith(('.ass', '.ssa', '.srt', '.sup')):
                    continue
                if subtitle_path not in self._subtitle_cache:
                    try:
                        self._subtitle_cache[subtitle_path] = Subtitle(subtitle_path)
                    except Exception:
                        continue
                try:
                    target_seconds_by_row[row_index] = float(
                        self._subtitle_cache[subtitle_path].max_end_time()
                    )
                except Exception:
                    target_seconds_by_row[row_index] = approx_end_time
            changed_mpls = ''
            if mode in ('start', 'end') and changed_row >= 0:
                changed_mpls = str(row_mpls.get(changed_row, '') or '').strip()
                if not changed_mpls and changed_row in prev_conf:
                    changed_mpls = str(
                        prev_conf[changed_row].get('selected_mpls') or ''
                    ).strip()
                if not changed_mpls:
                    changed_bdmv = int(row_bdmv.get(changed_row, 0) or 0)
                    changed_mpls = str(bdmv_to_mpls.get(changed_bdmv, '') or '').strip()
            conf: dict[int, dict[str, int | str]] = {}
            rows = self.table2.rowCount()
            node_cache: dict[str, dict[str, object]] = {}
            last_end_by_mpls: dict[str, int] = {}
            pending_remove_rows = getattr(self, '_chapter_pending_remove_row', -1)
            remove_rows: set[int] = set()
            if isinstance(pending_remove_rows, (list, tuple, set, frozenset)):
                for pending_row in pending_remove_rows:
                    try:
                        remove_rows.add(int(pending_row))
                    except (TypeError, ValueError):
                        continue
            else:
                try:
                    pending_row = int(pending_remove_rows or -1)
                    if pending_row >= 0:
                        remove_rows.add(pending_row)
                except (TypeError, ValueError):
                    pass
            self._chapter_pending_remove_row = -1
            for r in range(rows):
                if r % 2 == 0:
                    self._tick_delayed_busy(busy, self.t('Regenerating configuration...'))
                if int(r) in remove_rows:
                    continue
                bdmv_index = int(row_bdmv.get(r, 0) or 0)
                mpls_no_ext = str(row_mpls.get(r, '') or '').strip()
                if not mpls_no_ext:
                    prev_row = prev_conf.get(r, {}) if isinstance(prev_conf, dict) else {}
                    mpls_no_ext = str(prev_row.get('selected_mpls') or '').strip()
                if not mpls_no_ext:
                    mpls_no_ext = str(bdmv_to_mpls.get(bdmv_index, '') or '').strip()
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
                previous_matches_mpls = bool(
                    r in prev_conf
                    and str(prev_conf[r].get('selected_mpls') or '').strip() == mpls_no_ext
                )
                freeze_chapter_edit_row = bool(
                    mode in ('start', 'end')
                    and previous_matches_mpls
                    and (
                        r < changed_row
                        or (changed_mpls and mpls_no_ext != changed_mpls)
                    )
                )
                if freeze_chapter_edit_row:
                    conf[r] = dict(prev_conf[r])
                    conf[r]['chapter_segments_fully_checked'] = _chapter_seg_fully_checked(mpls_no_ext, checked, total_rows)
                    last_end_by_mpls[mpls_no_ext] = int(conf[r].get('end_at_chapter') or 0)
                    continue
                if (
                        mode == 'segments'
                        and segment_changed_mpls
                        and mpls_no_ext
                        and mpls_no_ext not in segment_changed_mpls
                        and r in prev_conf
                        and str(prev_conf[r].get('selected_mpls') or '').strip() == mpls_no_ext
                ):
                    conf[r] = dict(prev_conf[r])
                    conf[r]['chapter_segments_fully_checked'] = _chapter_seg_fully_checked(mpls_no_ext, checked, total_rows)
                    last_end_by_mpls[mpls_no_ext] = int(conf[r].get('end_at_chapter') or 0)
                    continue
                raw_start = int(starts.get(r, 1) or 1)
                raw_end = int(ends.get(r, 0) or 0)
                start_idx = max(1, min(total_rows, raw_start))
                while start_idx <= total_rows and not checked[start_idx - 1]:
                    start_idx += 1
                if start_idx > total_rows:
                    continue
                if mode == 'segments':
                    first_checked = next(
                        (i for i in range(1, total_rows + 1) if checked[i - 1]),
                        None,
                    )
                    if first_checked is None:
                        continue
                    inherited_end = int(last_end_by_mpls.get(mpls_no_ext, 0) or 0)
                    if inherited_end <= 0:
                        start_idx = first_checked
                    else:
                        start_idx = inherited_end
                        if start_idx > total_rows:
                            continue
                        if not checked[start_idx - 1]:
                            nxt_checked = next((i for i in range(start_idx, total_rows + 1) if checked[i - 1]), None)
                            if nxt_checked is None:
                                continue
                            start_idx = nxt_checked
                chapter_edit_row = bool(
                    mode in ('start', 'end')
                    and changed_mpls
                    and mpls_no_ext == changed_mpls
                    and r >= changed_row
                )
                if chapter_edit_row and r > changed_row:
                    inherited_end = int(last_end_by_mpls.get(mpls_no_ext, 0) or 0)
                    if inherited_end > total_rows:
                        continue
                    if inherited_end > 0:
                        start_idx = inherited_end
                        while start_idx <= total_rows and not checked[start_idx - 1]:
                            start_idx += 1
                        if start_idx > total_rows:
                            continue
                target_sec = float(target_seconds_by_row.get(r, approx_end_time))
                recompute_end = bool(
                    mode == 'segments'
                    or (mode == 'start' and chapter_edit_row)
                    or (mode == 'end' and chapter_edit_row and r > changed_row)
                )
                chosen_end = raw_end
                if recompute_end:
                    chosen_end = 0
                if chosen_end <= start_idx:
                    chosen_end = self._closest_endpoint(
                        start_idx, target_sec, total_rows, offsets, m2ts, checked, approx_end_time)
                if chosen_end > total_rows + 1:
                    chosen_end = total_rows + 1
                # Default-generated ranges stop at the first unchecked segment.
                if recompute_end:
                    for k in range(start_idx, min(chosen_end, total_rows + 1)):
                        if k <= total_rows and not checked[k - 1]:
                            chosen_end = k
                            break
                if int(start_idx) >= int(chosen_end):
                    continue
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
                    'chapter_segments_fully_checked': _chapter_seg_fully_checked(mpls_no_ext, checked, total_rows),
                }
                last_end_by_mpls[mpls_no_ext] = int(chosen_end)
            # Sync continuation markers from actual conf (includes frozen start/end rows that skipped updates).
            last_end_by_mpls.clear()
            for _rk in sorted(conf.keys(), key=lambda x: int(x)):
                _row = conf.get(_rk) or {}
                _m = str(_row.get('selected_mpls') or '').strip()
                if _m:
                    last_end_by_mpls[_m] = int(_row.get('end_at_chapter') or 0)
            # Add episode rows until each MPLS playlist tail is covered (table2 row count must not cap segments).
            _exp_guard = 0
            while conf and _exp_guard < 512:
                _exp_guard += 1
                _expanded = False
                for mpls_no_ext, node in list(node_cache.items()):
                    if mode == 'segments' and segment_changed_mpls and mpls_no_ext not in segment_changed_mpls:
                        continue
                    if mode in ('start', 'end') and changed_mpls and mpls_no_ext != changed_mpls:
                        continue
                    total_rows = int(node['rows'])
                    offsets = dict(node['offsets'])
                    m2ts = dict(node['m2ts'])
                    checked = list(segments.get(mpls_no_ext, [True] * total_rows))
                    if len(checked) < total_rows:
                        checked += [True] * (total_rows - len(checked))
                    le = int(last_end_by_mpls.get(mpls_no_ext, 0) or 0)
                    if le >= total_rows + 1:
                        continue
                    start_idx = le
                    if start_idx > total_rows:
                        continue
                    while start_idx <= total_rows and not checked[start_idx - 1]:
                        start_idx += 1
                    if start_idx > total_rows:
                        last_end_by_mpls[mpls_no_ext] = total_rows + 1
                        continue
                    bdmv_index = 0
                    folder = ''
                    disc_output_name = ''
                    for _k, _row in conf.items():
                        if str(_row.get('selected_mpls') or '') == mpls_no_ext:
                            bdmv_index = int(_row.get('bdmv_index') or 0)
                            folder = str(_row.get('folder') or '')
                            disc_output_name = str(_row.get('disc_output_name') or '')
                            break
                    if bdmv_index <= 0:
                        continue
                    target_sec = approx_end_time
                    chosen_end = self._closest_endpoint(
                        start_idx, target_sec, total_rows, offsets, m2ts, checked, approx_end_time)
                    for k in range(start_idx, min(chosen_end, total_rows + 1)):
                        if k <= total_rows and not checked[k - 1]:
                            chosen_end = k
                            break
                    if chosen_end <= start_idx:
                        last_end_by_mpls[mpls_no_ext] = total_rows + 1
                        continue
                    dur = max(
                        0.0,
                        float(offsets.get(chosen_end, offsets.get(total_rows + 1, 0.0))) - float(
                            offsets.get(start_idx, 0.0)))
                    if not folder:
                        folder = self._folder_path_for_bdmv_index_from_table1(bdmv_index)
                    if not folder and selected_mpls:
                        try:
                            folder = os.path.normpath(str(selected_mpls[0][0] or ''))
                        except Exception:
                            folder = ''
                    if not disc_output_name:
                        disc_output_name = self._resolve_output_name_from_mpls(mpls_no_ext)
                    new_key = (max(conf.keys()) + 1) if conf else 0
                    conf[int(new_key)] = {
                        'folder': folder,
                        'selected_mpls': mpls_no_ext,
                        'bdmv_index': bdmv_index,
                        'chapter_index': int(start_idx),
                        'start_at_chapter': int(start_idx),
                        'end_at_chapter': int(chosen_end),
                        'offset': get_time_str(float(offsets.get(start_idx, 0.0))),
                        'ep_duration': get_time_str(dur),
                        'disc_output_name': disc_output_name,
                        'chapter_segments_fully_checked': _chapter_seg_fully_checked(mpls_no_ext, checked, total_rows),
                    }
                    last_end_by_mpls[mpls_no_ext] = int(chosen_end)
                    _expanded = True
                    break
                if not _expanded:
                    break
            self._chapter_pending_append_episode = None
            bounded_conf: dict[int, dict[str, int | str]] = {}
            for conf_key, conf_row in conf.items():
                conf_mpls = str(conf_row.get('selected_mpls') or '').strip()
                conf_node = node_cache.get(conf_mpls)
                if not conf_node:
                    continue
                try:
                    conf_rows = int(conf_node.get('rows') or 0)
                    conf_start = int(
                        conf_row.get('start_at_chapter')
                        or conf_row.get('chapter_index')
                        or 0
                    )
                    conf_end = int(conf_row.get('end_at_chapter') or 0)
                except (TypeError, ValueError):
                    continue
                if not (1 <= conf_start < conf_end <= conf_rows + 1):
                    continue
                bounded_conf[int(conf_key)] = conf_row
            conf = bounded_conf
            if conf:
                conf = BluraySubtitle._configuration_drop_invalid_episode_rows(conf)
            if conf:
                items = sorted(conf.items(), key=lambda kv: int(kv[0]))
                playlist_order: dict[str, int] = {}
                for _, selected_mpls_no_ext in selected_mpls:
                    normalized_mpls = os.path.normcase(os.path.normpath(
                        str(selected_mpls_no_ext or '').strip()
                    ))
                    if normalized_mpls:
                        playlist_order.setdefault(normalized_mpls, len(playlist_order))
                fallback_order = len(playlist_order)
                items.sort(key=lambda item: playlist_order.get(
                    os.path.normcase(os.path.normpath(
                        str(item[1].get('selected_mpls') or '').strip()
                    )),
                    fallback_order,
                ))
                conf = {i: dict(v) for i, (_, v) in enumerate(items)}
            self._apply_episode_copyright_trim_to_configuration(conf, want_tail_trim)
            return conf
        finally:
            self._end_delayed_busy(busy)

    def _configuration_for_service_run(self) -> dict[int, dict[str, int | str]]:
        """Capture the current visible task without rebuilding any GUI table.

        Table1, table2, and table3 have already been refreshed before the Execute
        button becomes useful. Calling ``on_configuration`` or a movie/series
        refresh here would rebuild table3 and start a new SP scan after ``main``
        has passed its readiness gate. The returned copy is therefore created
        only from the configuration represented by the current visible controls.
        """
        configuration = (
            getattr(self, '_movie_configuration', None)
            if self._is_movie_mode()
            else self._generate_configuration_from_ui_inputs()
        )
        if not isinstance(configuration, dict) or not configuration:
            raise ValueError(self.t('Task configuration is empty'))
        labels = self._table2_labels_for_current_mode()
        if labels and 'm2ts_file_detail' in labels:
            detail_col = labels.index('m2ts_file_detail')
            for table_row, configuration_key in enumerate(
                    sorted(configuration, key=lambda key: int(key))):
                if table_row >= self.table2.rowCount():
                    break
                detail_item = self.table2.item(table_row, detail_col)
                configuration[configuration_key]['m2ts_file_detail'] = (
                    detail_item.text().strip()
                    if detail_item and detail_item.text()
                    else ''
                )
        self._apply_main_remux_cmds_to_configuration(configuration)
        return copy.deepcopy(configuration)

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

    def _full_refresh_remux_encode_tables_for_mode(self) -> None:
        """Rebuild table2 and table3 after the source or movie/series mode changes.

        A full series refresh has two ordered passes: build table2 from the
        selected main playlists, then read the newly created visible controls
        back into a configuration used for the sole table3 refresh. Table3 owns
        the subsequent asynchronous SP scan.
        """
        if self.get_selected_function_id() not in (3, 4, 5):
            return
        if not self.bdmv_folder_path.text().strip() or self.table1.rowCount() == 0:
            return
        if self._is_movie_mode():
            self._refresh_movie_table2()
            return
        try:
            sub_files = [
                self.table2.item(i, 0).text().strip()
                for i in range(self.table2.rowCount())
                if self.table2.item(i, 0) and self.table2.item(i, 0).text()
            ]
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                None,
                approx_episode_duration_seconds=self._get_approx_episode_duration_seconds(),
            )
            selected_mpls = self.get_selected_mpls_no_ext()
            if not selected_mpls:
                self.table2.setRowCount(0)
                self.refresh_sp_table({})
                self._last_configuration_34 = {}
                try:
                    self._selected_main_mpls_prev = set()
                except Exception:
                    pass
                return
            configuration = bs.generate_configuration_from_selected_mpls(selected_mpls)
            # The first pass creates all table2 widgets. Their visible values are
            # authoritative, so read them back before the only table3 refresh.
            self.on_configuration(configuration, update_sp_table=False)
            # A full source refresh must classify the second pass as a segment rebuild. The first-pass widgets
            # are only inputs to that rebuild, not the comparison baseline for a later user edit.
            self._last_config_inputs = {}
            current_configuration = self._generate_configuration_from_ui_inputs() if self.table2.rowCount() > 0 else {}
            self.on_configuration(current_configuration or configuration, update_sp_table=True)
        except Exception:
            print_exc_terminal()

    def _rebuild_configuration_for_function_34(self):
        if self.get_selected_function_id() not in (3, 4, 5):
            return
        if not self.bdmv_folder_path.text().strip():
            return
        if self.table1.rowCount() == 0:
            return
        if self._is_movie_mode():
            self._refresh_movie_table2()
            return
        try:
            if self.table2.rowCount() > 0:
                configuration = self._generate_configuration_from_ui_inputs()
            else:
                sub_files = [self.table2.item(i, 0).text() for i in range(self.table2.rowCount()) if
                             self.table2.item(i, 0)]
                bs = BluraySubtitle(
                    self.bdmv_folder_path.text(),
                    sub_files,
                    self.checkbox1.isChecked(),
                    None,
                    approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
                )
                configuration = bs.generate_configuration_from_selected_mpls(self.get_selected_mpls_no_ext())

            self.on_configuration(configuration)
        except Exception:
            print_exc_terminal()

    def on_configuration(self, configuration: dict[int, dict[str, int | str]], update_sp_table: bool = True):
        """Apply a configuration to table2 and optionally rebuild table3 once.

        ``update_sp_table=False`` is used by the first pass of a series refresh
        while table2 widgets are still being created. When true,
        ``refresh_sp_table`` runs only after table2 is stable; that method starts
        the asynchronous scan whose readiness is enforced by ``main``.
        """
        busy: Optional[dict[str, object]] = None
        try:
            if not configuration:
                print(translate_text('Configuration is empty, skipping update'))
                return
            function_id = self.get_selected_function_id()
            if function_id in (3, 4, 5):
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

                if function_id == 4:
                    labels = ENCODE_LABELS
                elif function_id == 5:
                    labels = DIY_REMUX_LABELS
                else:
                    labels = REMUX_LABELS
                duration_col = labels.index('ep_duration')
                bdmv_col = labels.index('bdmv_index')
                start_col = labels.index('start_at_chapter')
                end_col = labels.index('end_at_chapter')
                m2ts_col = labels.index('m2ts_file')
                m2ts_detail_col = labels.index('m2ts_file_detail') if 'm2ts_file_detail' in labels else -1
                language_col = labels.index('language')
                output_col = labels.index('output_name') if 'output_name' in labels else -1
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
                            if output_col >= 0:
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

                        self._apply_movie_mode_table2_chapter_widgets(
                            row_i,
                            labels,
                            str(con0.get('selected_mpls') or ''),
                            connect_end_handler=True,
                        )

                        chapter = _chapter_cached(str(con0['selected_mpls']))
                        total_time = chapter.get_total_time()
                        self.table2.setItem(row_i, duration_col, QTableWidgetItem(get_time_str(total_time)))

                        index_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
                        try:
                            m2ts_files = list(dict.fromkeys(
                                [f'{stem}.m2ts' for stem, _, _ in (chapter.in_out_time or [])]))
                        except Exception:
                            m2ts_files = []
                        if not m2ts_files:
                            try:
                                rows = sum(map(len, chapter.mark_info.values()))
                                m2ts_files = list(dict.fromkeys(
                                    index_to_m2ts[i] for i in range(1, rows + 1) if i in index_to_m2ts))
                            except Exception:
                                m2ts_files = list(dict.fromkeys(index_to_m2ts[k] for k in index_to_m2ts))
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
                        self.table2.setItem(row_i, language_col, None)
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
                        if m2ts_detail_col >= 0:
                            sm = str(con0.get('selected_mpls') or '').strip()
                            mpls_full = sm if sm.lower().endswith('.mpls') else (f'{sm}.mpls' if sm else '')
                            detail_txt = ''
                            if mpls_full and os.path.isfile(mpls_full):
                                try:
                                    detail_txt = self._m2ts_file_detail_from_mpls_path(mpls_full)
                                except Exception:
                                    detail_txt = ''
                            self.table2.setItem(row_i, m2ts_detail_col, QTableWidgetItem(detail_txt))
                        if output_col >= 0:
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
                            self.table2.setItem(row_i, play_col, None)
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
                        # A start must be a real chapter node; ending is end-only.
                        j1 = max(1, min(j1, max(1, rows)))
                        j2 = min(rows + 1, max(j1 + 1, j2))
                        sm = str(con.get('selected_mpls') or '').strip()
                        m2ts_joined, detail_txt, duration = self._table2_m2ts_detail_duration_from_chapter_bounds(
                            sm, j1, j2)
                        try:
                            has_beginning = bool(
                                self._chapter_node_data(str(con['selected_mpls'])).get('has_beginning'))
                        except Exception:
                            has_beginning = False
                        for chapter_value in range(1, rows + 1):
                            chapter_combo.addItem(
                                self._chapter_label_text(chapter_value, rows, has_beginning), chapter_value
                            )
                        selected_idx = 0
                        for i_opt in range(chapter_combo.count()):
                            if int(chapter_combo.itemData(i_opt) or 0) == int(con['chapter_index']):
                                selected_idx = i_opt
                                break
                        chapter_combo.setCurrentIndex(selected_idx)
                        chapter_combo._prev_start_value = int(
                            chapter_combo.currentData() or (chapter_combo.currentIndex() + 1))
                        chapter_combo.currentIndexChanged.connect(partial(self.on_chapter_combo, sub_index))
                        self.table2.setCellWidget(sub_index, start_col, chapter_combo)
                        end_combo = self._build_end_chapter_combo(rows, has_beginning, int(j1), int(j2))
                        end_combo.currentIndexChanged.connect(
                            partial(self._on_end_chapter_combo_changed, sub_index, labels))
                        self.table2.setCellWidget(sub_index, end_col, end_combo)
                        self.table2.setItem(sub_index, m2ts_col, QTableWidgetItem(m2ts_joined))
                        if m2ts_detail_col >= 0:
                            self.table2.setItem(sub_index, m2ts_detail_col, QTableWidgetItem(detail_txt))
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
                        self.table2.setItem(sub_index, language_col, None)
                        self.table2.setCellWidget(sub_index, language_col, lang_combo)
                        if output_col >= 0:
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
                            self.table2.setItem(sub_index, play_col, None)
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
                if self._is_movie_mode():
                    self._finalize_movie_mode_table2_layout(labels)
                else:
                    self._sync_end_chapter_min_constraints(labels)
                    self._apply_start_chapter_constraints(labels)
                self._refresh_table2_m2ts_duration_from_widgets(labels)

                if self._is_movie_mode():
                    self._finalize_movie_mode_table2_layout(labels)
                else:
                    self._scroll_table_h_to_right(self.table2)
                    # Continuation rows may have been regenerated from the edited bound. Compare the next user
                    # action with these visible rows, not with the pre-regeneration snapshot.
                    self._last_config_inputs = self._collect_config_inputs()
                if function_id in (3, 4, 5):
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
                        bdmv_item = QTableWidgetItem(str(con['bdmv_index']))
                        bdmv_item.setData(Qt.ItemDataRole.UserRole, str(con['selected_mpls']))
                        self.table2.setItem(row, bdmv_col, bdmv_item)

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
                        _, index_to_offset = get_index_to_m2ts_and_offset(chapter)
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
        if function_id not in (3, 4, 5):
            try:
                if os.path.exists('info.json'):
                    force_remove_file('info.json')
            except Exception:
                pass

        last_function_id = int(getattr(self, '_selected_function_id', 0) or 0)
        if (not force) and function_id and last_function_id == function_id:
            return
        if last_function_id in (3, 4) and last_function_id != function_id:
            self._retire_sp_table_scan()
        self._remember_output_folder_for_function(last_function_id)
        # Keep previous behavior: remove temporary default vpy when leaving encode mode.
        if last_function_id == 4 and function_id != 4:
            try:
                self.delete_default_vpy_file()
            except Exception:
                pass
        self._selected_function_id = function_id
        self._restore_output_folder_for_function(function_id)
        self._refresh_function_tabbar_theme()

        if hasattr(self, 'output_folder_row') and self.output_folder_row:
            self.output_folder_row.setVisible(function_id in (3, 4, 5))
        if hasattr(self, 'select_all_tracks_row') and self.select_all_tracks_row:
            visible = function_id in (3, 4)
            self.select_all_tracks_row.setVisible(visible)
        if hasattr(self, 'remux_flac_checkbox') and self.remux_flac_checkbox:
            self.remux_flac_checkbox.setVisible(function_id == 3)
        if hasattr(self, 'subtitle_formats_hint_label') and self.subtitle_formats_hint_label:
            self.subtitle_formats_hint_label.setVisible(function_id == 5)
        if hasattr(self, 'subtitle_convert_checkbox') and self.subtitle_convert_checkbox:
            self.subtitle_convert_checkbox.setVisible(function_id == 5)
        if hasattr(self, 'subtitle_bluray_compat_checkbox') and self.subtitle_bluray_compat_checkbox:
            simple_diy = bool(getattr(self, 'diy_simple_radio', None) and self.diy_simple_radio.isChecked())
            self.subtitle_bluray_compat_checkbox.setVisible(function_id == 5 and simple_diy)
        if hasattr(self, 'use_bluray_compat_params_checkbox') and self.use_bluray_compat_params_checkbox:
            # x264/x265 Blu-ray compatibility params are only for DIY workflow.
            self.use_bluray_compat_params_checkbox.setVisible(function_id == 5)
        if hasattr(self, 'subtitle_hint_row') and self.subtitle_hint_row:
            self.subtitle_hint_row.setVisible(function_id == 5)
        if hasattr(self, 'track_scope_row') and self.track_scope_row:
            simple_diy = bool(getattr(self, 'diy_simple_radio', None) and self.diy_simple_radio.isChecked())
            self.track_scope_row.setVisible(function_id == 5 and simple_diy)
        if hasattr(self, 'simple_diy_sub_lang_combo') and self.simple_diy_sub_lang_combo:
            self.simple_diy_sub_lang_combo.setVisible(function_id == 5 and simple_diy)
        if hasattr(self, 'simple_diy_sub_lang_label') and self.simple_diy_sub_lang_label:
            self.simple_diy_sub_lang_label.setVisible(function_id == 5 and simple_diy)
        if hasattr(self, 'simple_diy_add_sub_row_btn') and self.simple_diy_add_sub_row_btn:
            if function_id == 5 and simple_diy:
                row_count = 1 + len(getattr(self, '_simple_diy_sub_rows', []) or [])
                self.simple_diy_add_sub_row_btn.setVisible(row_count == 1)
            else:
                self.simple_diy_add_sub_row_btn.setVisible(False)
        if hasattr(self, 'simple_diy_remove_sub_row_btn') and self.simple_diy_remove_sub_row_btn:
            if function_id == 5 and simple_diy:
                row_count = 1 + len(getattr(self, '_simple_diy_sub_rows', []) or [])
                self.simple_diy_remove_sub_row_btn.setVisible(row_count > 1)
            else:
                self.simple_diy_remove_sub_row_btn.setVisible(False)
        if hasattr(self, 'simple_diy_extra_sub_rows') and self.simple_diy_extra_sub_rows:
            self.simple_diy_extra_sub_rows.setVisible(function_id == 5 and simple_diy)
        if hasattr(self, 'episode_mode_row') and self.episode_mode_row:
            self.episode_mode_row.setVisible(function_id in (1, 3, 4, 5))
        if hasattr(self, 'diy_mode_row') and self.diy_mode_row:
            self.diy_mode_row.setVisible(function_id == 5)
        if hasattr(self, 'subtitle_path_box') and self.subtitle_path_box:
            self.subtitle_path_box.setVisible(True)
        if hasattr(self, 'encode_source_row') and self.encode_source_row:
            self.encode_source_row.setVisible(function_id == 4)
        if hasattr(self, '_sub_pack_row') and self._sub_pack_row:
            self._sub_pack_row.setVisible(function_id == 4)
        if hasattr(self, 'table3'):
            self.table3.setVisible(function_id in (3, 4))
            try:
                labels = DIY_SP_LABELS if function_id == 5 else ENCODE_SP_LABELS
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
                try:
                    self._apply_hidden_m2ts_file_detail_columns()
                except Exception:
                    pass
                self._scroll_table_h_to_right(self.table3)
            except Exception:
                pass

        if function_id in (3, 4, 5):
            try:
                try:
                    self._update_trim_copyright_tail_checkbox_for_episode_movie_mode()
                except Exception:
                    pass
                table1_labels = DIY_BDMV_LABELS if function_id == 5 else BDMV_LABELS
                if self.table1.columnCount() != len(table1_labels):
                    self.table1.setColumnCount(len(table1_labels))
                    self._set_table_headers(self.table1, table1_labels)
                cmd_col = table1_labels.index('remux_cmd') if 'remux_cmd' in table1_labels else -1
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
            self.label2.setText(self.t("Select the subtitle folder"))
            self.exe_button.setText(self.t("Generate Subtitles"))
            self.encode_box.setVisible(False)
            if not self.checkbox1.isVisible():
                self.checkbox1.setVisible(True)
            self.checkbox1.setText(self.t('Complete Blu-ray Folder'))
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
            self.label2.setText(self.t("Select the MKV folder"))
            self.exe_button.setText(self.t("Add Chapters"))
            self.encode_box.setVisible(False)
            if not self.checkbox1.isVisible():
                self.checkbox1.setVisible(True)
            self.checkbox1.setText(self.t('Edit Original File Directly'))
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
            self.label2.setText(self.t("Select the subtitle folder (optional)"))
            self.exe_button.setText(self.t("Start Remux"))
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
                for c in range(self.table2.columnCount()):
                    self.table2.setColumnHidden(c, False)
                try:
                    self._apply_hidden_m2ts_file_detail_columns()
                except Exception:
                    pass
                self._set_table2_default_column_order()
                if hasattr(self, 'table3'):
                    self.table3.clear()
                    self.table3.setRowCount(0)
                    self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                    self._set_table_headers(self.table3, ENCODE_SP_LABELS)

        if function_id == 4:
            self.label2.setText(self.t("Select the subtitle folder (optional)"))
            self.exe_button.setText(self.t("Start Encode"))
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
                for c in range(self.table2.columnCount()):
                    self.table2.setColumnHidden(c, False)
                try:
                    self._apply_hidden_m2ts_file_detail_columns()
                except Exception:
                    pass
                self._set_table2_default_column_order()
                if hasattr(self, 'table3'):
                    self.table3.clear()
                    self.table3.setRowCount(0)
                    self.table3.setColumnCount(len(ENCODE_SP_LABELS))
                    self._set_table_headers(self.table3, ENCODE_SP_LABELS)

        if function_id == 5:
            self.label2.setText(self.t("Select the subtitle folder (optional)"))
            self.exe_button.setText(self.t("Start DIY (Not implemented yet)"))
            self.encode_box.setVisible(False)
            self.checkbox1.setVisible(False)
            if hasattr(self, 'merge_options_row') and self.merge_options_row:
                self.merge_options_row.setVisible(False)
            if self.table2.columnCount() != len(DIY_REMUX_LABELS):
                self.table2.setColumnCount(len(DIY_REMUX_LABELS))
                self._set_table_headers(self.table2, DIY_REMUX_LABELS)
            if hasattr(self, 'table3') and self.table3 and self.table3.columnCount() != len(DIY_SP_LABELS):
                self.table3.setColumnCount(len(DIY_SP_LABELS))
                self._set_table_headers(self.table3, DIY_SP_LABELS)
            if not keep_state:
                self.table1.clear()
                self.table1.setRowCount(0)
                self.table1.setColumnCount(len(DIY_BDMV_LABELS))
                self._set_table_headers(self.table1, DIY_BDMV_LABELS)
                self.table2.clear()
                self.table2.setRowCount(0)
                self.table2.setColumnCount(len(DIY_REMUX_LABELS))
                self._set_table_headers(self.table2, DIY_REMUX_LABELS)
                self._set_table2_default_column_order()
                if hasattr(self, 'table3'):
                    self.table3.clear()
                    self.table3.setRowCount(0)
                    self.table3.setColumnCount(len(DIY_SP_LABELS))
                    self._set_table_headers(self.table3, DIY_SP_LABELS)
            if hasattr(self, 'table3'):
                self.table3.setVisible(False)
            simple_diy = bool(getattr(self, 'diy_simple_radio', None) and self.diy_simple_radio.isChecked())
            if hasattr(self, 'label2'):
                self.label2.setText(self.t("Select subtitles folder"))
            if hasattr(self, 'simple_diy_sub_lang_combo') and self.simple_diy_sub_lang_combo:
                default_lang = 'chi' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) == 'zh' else 'eng'
                if (self.simple_diy_sub_lang_combo.currentText() or '').strip() in ('', 'und'):
                    self.simple_diy_sub_lang_combo.setCurrentText(default_lang)
            if simple_diy and hasattr(self, 'table2') and self.table2:
                try:
                    if 'sub_path' in DIY_REMUX_LABELS:
                        self.table2.setColumnHidden(DIY_REMUX_LABELS.index('sub_path'), True)
                    if 'language' in DIY_REMUX_LABELS:
                        self.table2.setColumnHidden(DIY_REMUX_LABELS.index('language'), True)
                except Exception:
                    pass
            elif hasattr(self, 'table2') and self.table2:
                try:
                    if 'sub_path' in DIY_REMUX_LABELS:
                        self.table2.setColumnHidden(DIY_REMUX_LABELS.index('sub_path'), False)
                    if 'language' in DIY_REMUX_LABELS:
                        self.table2.setColumnHidden(DIY_REMUX_LABELS.index('language'), False)
                except Exception:
                    pass
            if simple_diy:
                try:
                    need_encode = False
                    conv_cfg = getattr(self, '_track_convert_config', {}) or {}
                    for mp in conv_cfg.values():
                        vals = [str(v or '') for v in (mp or {}).values()]
                        if any(v in ('h264(encoded)', 'h265(encoded)') for v in vals):
                            need_encode = True
                            break
                    self.encode_box.setVisible(need_encode)
                    if need_encode and hasattr(self, '_apply_encode_codec_slot_visibility'):
                        self._apply_encode_codec_slot_visibility()
                    if hasattr(self, '_sub_pack_row') and self._sub_pack_row:
                        self._sub_pack_row.setVisible(False)
                    if (
                        getattr(self, 'encode_tool_combo', None) is not None
                        and getattr(self, 'x265_params_label', None) is not None
                    ):
                        use_x264 = any(
                            str(v or '') == 'h264(encoded)'
                            for mp in conv_cfg.values() for v in (mp or {}).values()
                        )
                        if use_x264:
                            self.encode_tool_combo.setCurrentText('x264')
                        else:
                            self.encode_tool_combo.setCurrentText('x265')
                        if hasattr(self, '_refresh_encode_tool_dependent_ui'):
                            self._refresh_encode_tool_dependent_ui(True)
                except Exception:
                    pass

        if not keep_inputs:
            self.bdmv_folder_path.clear()
            self.subtitle_folder_path.clear()
        try:
            self._reposition_subtitle_path_box()
        except Exception:
            pass
        self._refresh_function_tabbar_theme()
        # Encode / DIY+encode: update codec row vs DIY hint, then refill bit depth (Blu-ray Encode has full BPP list).
        try:
            if hasattr(self, '_apply_encode_codec_slot_visibility'):
                self._apply_encode_codec_slot_visibility()
            box = getattr(self, 'encode_box', None)
            if box is not None and box.isVisible() and hasattr(self, '_refresh_encode_tool_dependent_ui'):
                self._refresh_encode_tool_dependent_ui(False)
        except Exception:
            pass

    def get_selected_function_id(self) -> int:
        try:
            tabbar = getattr(self, 'function_tabbar', None)
            if tabbar is not None:
                idx = int(tabbar.currentIndex())
                if idx >= 0:
                    order = list(getattr(self, '_function_id_order', [1, 2, 3, 4]))
                    if idx < len(order):
                        return int(order[idx])
        except Exception:
            pass
        try:
            return int(getattr(self, '_selected_function_id', 3) or 3)
        except Exception:
            return 3

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
                main_btn: QToolButton = info.cellWidget(mpls_index, MPLS_INFO_LABELS.index('main'))
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
