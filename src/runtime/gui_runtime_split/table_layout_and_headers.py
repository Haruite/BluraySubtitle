"""Target module for table/layout/header methods of `BluraySubtitleGUI`."""
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QTableWidget, QComboBox, QHeaderView

from src.core import BDMV_LABELS, SUBTITLE_LABELS, MKV_LABELS, REMUX_LABELS, ENCODE_REMUX_LABELS, ENCODE_LABELS, \
    ENCODE_REMUX_SP_LABELS, ENCODE_SP_LABELS, DIY_BDMV_LABELS, DIY_SP_LABELS, DIY_REMUX_LABELS, CURRENT_UI_LANGUAGE
from .gui_base import BluraySubtitleGuiBase


class TableLayoutHeadersMixin(BluraySubtitleGuiBase):
    def _set_table_headers(self, table: QTableWidget, keys: list[str]):
        try:
            display_keys = list(keys)
            # For table2 (remux/encode views), show the language column as sub_language.
            if table is getattr(self, 'table2', None) and 'language' in display_keys:
                function_id = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 0
                if function_id in (3, 4, 5):
                    display_keys = ['sub_language' if k == 'language' else k for k in display_keys]
            table.setHorizontalHeaderLabels(self._localized_headers_for_keys(display_keys))
        except Exception:
            pass

    def _refresh_all_table_headers(self):
        try:
            if hasattr(self, 'table1') and self.table1:
                function_id = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 0
                self._set_table_headers(self.table1, DIY_BDMV_LABELS if function_id == 5 else BDMV_LABELS)
        except Exception:
            pass

        try:
            if hasattr(self, 'table2') and self.table2:
                function_id = self.get_selected_function_id()
                if function_id == 1:
                    self._set_table_headers(self.table2, SUBTITLE_LABELS)
                elif function_id == 2:
                    self._set_table_headers(self.table2, MKV_LABELS)
                elif function_id == 3:
                    self._set_table_headers(self.table2, REMUX_LABELS)
                elif function_id == 4:
                    labels = ENCODE_REMUX_LABELS if getattr(self, '_encode_input_mode',
                                                            'bdmv') == 'remux' else ENCODE_LABELS
                    self._set_table_headers(self.table2, labels)
                elif function_id == 5:
                    self._set_table_headers(self.table2, DIY_REMUX_LABELS)
                self._resize_table_columns_for_language(self.table2)
                self._scroll_table_h_to_right(self.table2)
        except Exception:
            pass

        try:
            if hasattr(self, 'table3') and self.table3:
                function_id = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 0
                if function_id == 5:
                    labels = DIY_SP_LABELS
                else:
                    labels = ENCODE_REMUX_SP_LABELS if getattr(self, '_encode_input_mode',
                                                               'bdmv') == 'remux' else ENCODE_SP_LABELS
                self._set_table_headers(self.table3, labels)
                self._resize_table_columns_for_language(self.table3)
                self._scroll_table_h_to_right(self.table3)
        except Exception:
            pass

        try:
            if hasattr(self, 'table1') and self.table1:
                for r in range(self.table1.rowCount()):
                    info_table = self.table1.cellWidget(r, 2)
                    if isinstance(info_table, QTableWidget):
                        info_keys = ['mpls_file', 'duration', 'chapters', 'main', 'play']
                        try:
                            if info_table.columnCount() > len(info_keys):
                                info_keys.append('tracks')
                        except Exception:
                            pass
                        self._set_table_headers(info_table, info_keys)
                        self._resize_table_columns_for_language(info_table)
        except Exception:
            pass

    def _adjust_combo_width_to_contents(self, combo: QComboBox, padding: int = 44, min_width: int = 80,
                                        max_width: int = 520):
        # PyQt6: bool(QComboBox()) is False — use explicit None check only.
        if combo is None:
            return
        try:
            fm = QFontMetrics(combo.font())
            longest = 0
            for i in range(combo.count()):
                longest = max(longest, fm.horizontalAdvance(combo.itemText(i)))
            w = int(longest + padding)
            w = max(min_width, min(max_width, w))
            combo.setFixedWidth(w)
        except Exception:
            pass

    def _resize_table_columns_for_language(self, table: QTableWidget):
        if not table:
            return
        try:
            table.resizeColumnsToContents()
        except Exception:
            pass
        try:
            header = table.horizontalHeader()
            fm = QFontMetrics(header.font())
            for col in range(table.columnCount()):
                item = table.horizontalHeaderItem(col)
                txt = item.text() if item else ''
                if not txt:
                    continue
                min_w = int(fm.horizontalAdvance(txt) + 24)
                if table.columnWidth(col) < min_w:
                    table.setColumnWidth(col, min_w)
        except Exception:
            pass
        try:
            if table is getattr(self, 'table2', None):
                function_id = self.get_selected_function_id()
                if function_id == 3:
                    col = REMUX_LABELS.index('output_name')
                    labels = REMUX_LABELS
                elif function_id == 4:
                    col = ENCODE_LABELS.index('output_name')
                    labels = ENCODE_LABELS
                elif function_id == 5:
                    col = -1
                    labels = DIY_REMUX_LABELS
                else:
                    col = -1
                    labels = []
                if col >= 0:
                    header = table.horizontalHeader()
                    header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                    fixed_limit = 160
                    fm_h = QFontMetrics(header.font())
                    header_item = table.horizontalHeaderItem(col)
                    max_w = fm_h.horizontalAdvance(header_item.text()) if header_item and header_item.text() else 0
                    fm_c = QFontMetrics(table.font())
                    for r in range(table.rowCount()):
                        it = table.item(r, col)
                        if it and it.text():
                            max_w = max(max_w, fm_c.horizontalAdvance(it.text()))
                    desired = min(fixed_limit, int(max_w + 24))
                    table.setColumnWidth(col, max(60, desired))
                if labels and 'play' in labels:
                    play_col = labels.index('play')
                    header = table.horizontalHeader()
                    header.setSectionResizeMode(play_col, QHeaderView.ResizeMode.Fixed)
                    table.setColumnWidth(play_col, 68)
            elif table is getattr(self, 'table3', None):
                header = table.horizontalHeader()
                # Keep output name readable but bounded.
                col_output = ENCODE_SP_LABELS.index('output_name')
                header.setSectionResizeMode(col_output, QHeaderView.ResizeMode.Fixed)
                fixed_limit = 160
                fm_h = QFontMetrics(header.font())
                header_item = table.horizontalHeaderItem(col_output)
                max_w = fm_h.horizontalAdvance(header_item.text()) if header_item and header_item.text() else 0
                fm_c = QFontMetrics(table.font())
                for r in range(table.rowCount()):
                    it = table.item(r, col_output)
                    if it and it.text():
                        max_w = max(max_w, fm_c.horizontalAdvance(it.text()))
                desired = min(fixed_limit, int(max_w + 24))
                table.setColumnWidth(col_output, max(60, desired))

                # Make m2ts_file column fixed-width and wrap long file lists.
                col_m2ts = ENCODE_SP_LABELS.index('m2ts_file')
                header.setSectionResizeMode(col_m2ts, QHeaderView.ResizeMode.Fixed)
                table.setColumnWidth(col_m2ts, 220)
                table.setWordWrap(True)
                table.resizeRowsToContents()
        except Exception:
            pass

    def _set_compact_table(self, table: QTableWidget, row_height: int = 22, header_height: int = 22):
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setDefaultSectionSize(row_height)
        table.verticalHeader().setMinimumSectionSize(row_height)
        table.horizontalHeader().setFixedHeight(header_height)

    def _scroll_table_h_to_right(self, table: QTableWidget):
        token = int(getattr(table, '_auto_scroll_token', 0) or 0) + 1
        table._auto_scroll_token = token

        def scroll(expected_token: int = token):
            if int(getattr(table, '_auto_scroll_token', 0) or 0) != int(expected_token):
                return
            bar = table.horizontalScrollBar()
            if bar.isSliderDown():
                return
            bar.setValue(bar.maximum())

        QTimer.singleShot(0, scroll)
        QTimer.singleShot(80, scroll)
        QTimer.singleShot(200, scroll)

    def _set_table_column_visual_order(self, table: QTableWidget, order: list[int]):
        header = table.horizontalHeader()
        for desired_visual_index, logical_index in enumerate(order):
            if logical_index < 0 or logical_index >= table.columnCount():
                continue
            current_visual_index = header.visualIndex(logical_index)
            if current_visual_index != desired_visual_index:
                header.moveSection(current_visual_index, desired_visual_index)

    def _set_table2_default_column_order(self):
        self._set_table_column_visual_order(self.table2, list(range(self.table2.columnCount())))

    def _set_table2_subtitle_column_order(self):
        if self.table2.columnCount() < 2:
            return
        order = list(range(self.table2.columnCount()))
        order[0], order[1] = order[1], order[0]
        self._set_table_column_visual_order(self.table2, order)

    def _refresh_language_column_defaults(self):
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4, 5) or not hasattr(self, 'table2') or not self.table2:
            return
        if function_id == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            labels = ENCODE_REMUX_LABELS
        else:
            labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
        try:
            lang_col = labels.index('language')
        except Exception:
            return
        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        for r in range(self.table2.rowCount()):
            w = self.table2.cellWidget(r, lang_col)
            if not isinstance(w, QComboBox):
                continue
            prev_auto = str(getattr(w, '_auto_lang', auto_lang) or auto_lang)
            prev_text = w.currentText().strip()
            if (not prev_text) or (prev_text == prev_auto):
                w.setCurrentText(auto_lang)
            w._auto_lang = auto_lang
        self._update_language_combo_enabled_state()

    def _update_language_combo_enabled_state(self):
        function_id = self.get_selected_function_id()
        if function_id not in (3, 4, 5) or not hasattr(self, 'table2') or not self.table2:
            return
        if function_id == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            labels = ENCODE_REMUX_LABELS
        else:
            labels = ENCODE_LABELS if function_id == 4 else REMUX_LABELS
        try:
            sub_col = labels.index('sub_path')
            lang_col = labels.index('language')
        except Exception:
            return
        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        for r in range(self.table2.rowCount()):
            sub_item = self.table2.item(r, sub_col)
            has_sub = bool(sub_item and sub_item.text() and sub_item.text().strip())
            w = self.table2.cellWidget(r, lang_col)
            if isinstance(w, QComboBox):
                w.setEnabled(has_sub)
                if not has_sub:
                    w.setCurrentText(auto_lang)
                    w._auto_lang = auto_lang
