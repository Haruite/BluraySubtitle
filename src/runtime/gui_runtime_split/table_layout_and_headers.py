"""Target module for table/layout/header methods of `BluraySubtitleGUI`."""
from html import escape

from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QTableWidget, QComboBox, QHeaderView, QGroupBox, QLabel, QVBoxLayout, QSizePolicy, QAbstractItemView, QStyledItemDelegate, QToolTip

from src.core import BDMV_LABELS, SUBTITLE_LABELS, MKV_LABELS, REMUX_LABELS, ENCODE_REMUX_LABELS, ENCODE_LABELS, \
    ENCODE_REMUX_SP_LABELS, ENCODE_SP_LABELS, DIY_BDMV_LABELS, DIY_SP_LABELS, DIY_REMUX_LABELS, CURRENT_UI_LANGUAGE, \
    MPLS_INFO_LABELS, MPLS_INFO_TRACKS_LABELS
from .gui_base import BluraySubtitleGuiBase


class _FullTextDelegate(QStyledItemDelegate):
    def helpEvent(self, event, view, option, index):
        if event.type() == QEvent.Type.ToolTip and index.isValid() and not index.data(Qt.ItemDataRole.ToolTipRole):
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if isinstance(text, str) and text:
                QToolTip.showText(event.globalPos(), f'<qt>{escape(text)}</qt>', view)
                return True
        return super().helpEvent(event, view, option, index)


class TableLayoutHeadersMixin(BluraySubtitleGuiBase):
    def _show_m2ts_file_detail_columns(self) -> None:
        """Show m2ts_file_detail on table2/table3 (movie mode: compare SP vs main row)."""
        try:
            fid = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 0
            if hasattr(self, 'table2') and self.table2:
                enc_remux = fid == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux'
                if fid == 3:
                    t2labels = list(REMUX_LABELS)
                elif enc_remux:
                    t2labels = list(ENCODE_REMUX_LABELS)
                elif fid == 4:
                    t2labels = list(ENCODE_LABELS)
                elif fid == 5:
                    t2labels = list(DIY_REMUX_LABELS)
                else:
                    t2labels = []
                if t2labels and 'm2ts_file_detail' in t2labels:
                    c = t2labels.index('m2ts_file_detail')
                    if c < self.table2.columnCount():
                        self.table2.setColumnHidden(c, False)
                        hdr = self.table2.horizontalHeader()
                        hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
                        self.table2.setColumnWidth(c, max(280, int(self.table2.columnWidth(c) or 0)))
            if hasattr(self, 'table3') and self.table3:
                remux_sp = fid == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux'
                if fid == 5:
                    t3labels = list(DIY_SP_LABELS)
                elif remux_sp:
                    t3labels = list(ENCODE_REMUX_SP_LABELS)
                else:
                    t3labels = list(ENCODE_SP_LABELS)
                if t3labels and 'm2ts_file_detail' in t3labels:
                    c = t3labels.index('m2ts_file_detail')
                    if c < self.table3.columnCount():
                        self.table3.setColumnHidden(c, False)
                        hdr = self.table3.horizontalHeader()
                        hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
                        self.table3.setColumnWidth(c, max(280, int(self.table3.columnWidth(c) or 0)))
        except Exception:
            pass

    def _apply_hidden_m2ts_file_detail_columns(self):
        """Hide m2ts_file_detail on table2/table3 (internal timeline detail; not shown in UI)."""
        try:
            fid = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 0
            if hasattr(self, 'table2') and self.table2:
                enc_remux = fid == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux'
                if fid == 3:
                    t2labels = list(REMUX_LABELS)
                elif enc_remux:
                    t2labels = list(ENCODE_REMUX_LABELS)
                elif fid == 4:
                    t2labels = list(ENCODE_LABELS)
                elif fid == 5:
                    t2labels = list(DIY_REMUX_LABELS)
                else:
                    t2labels = []
                if t2labels and 'm2ts_file_detail' in t2labels:
                    c = t2labels.index('m2ts_file_detail')
                    if c < self.table2.columnCount():
                        self.table2.setColumnHidden(c, True)
            if hasattr(self, 'table3') and self.table3:
                remux_sp = fid == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux'
                if fid == 5:
                    t3labels = list(DIY_SP_LABELS)
                elif remux_sp:
                    t3labels = list(ENCODE_REMUX_SP_LABELS)
                else:
                    t3labels = list(ENCODE_SP_LABELS)
                if t3labels and 'm2ts_file_detail' in t3labels:
                    c = t3labels.index('m2ts_file_detail')
                    if c < self.table3.columnCount():
                        self.table3.setColumnHidden(c, True)
        except Exception:
            pass

    def _set_table_headers(self, table: QTableWidget, keys: list[str]):
        table.setProperty('columnKeys', list(keys))
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
                self._scroll_table_to_primary_column(self.table2)
        except Exception:
            pass

        try:
            if hasattr(self, 'table3') and self.table3:
                function_id = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 0
                if function_id == 5:
                    labels = DIY_SP_LABELS
                else:
                    # Same rule as _resize_table_columns_for_language / refresh_sp_table: remux SP schema is only for
                    # encode (fid 4) + remux input — not for episode remux (fid 3). Wrong labels here shift headers
                    # vs logical columns (13 ENCODE_SP_* vs 9 ENCODE_REMUX_SP_*), so output_name appears under tracks.
                    remux_sp = function_id == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux'
                    labels = ENCODE_REMUX_SP_LABELS if remux_sp else ENCODE_SP_LABELS
                self._set_table_headers(self.table3, labels)
                self._resize_table_columns_for_language(self.table3)
                self._scroll_table_to_primary_column(self.table3)
        except Exception:
            pass

        try:
            if hasattr(self, 'table1') and self.table1:
                for r in range(self.table1.rowCount()):
                    info_table = self.table1.cellWidget(r, 2)
                    if isinstance(info_table, QTableWidget):
                        info_keys = (
                            MPLS_INFO_TRACKS_LABELS
                            if info_table.columnCount() == len(MPLS_INFO_TRACKS_LABELS)
                            else MPLS_INFO_LABELS
                        )
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
        if table is None:
            return
        if not isinstance(table.itemDelegate(), _FullTextDelegate):
            table.setItemDelegate(_FullTextDelegate(table))
        keys = list(table.property('columnKeys') or [])
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        table.resizeColumnsToContents()
        header_metrics = QFontMetrics(header.font())
        cell_metrics = QFontMetrics(table.font())
        for column, key in enumerate(keys):
            item = table.horizontalHeaderItem(column)
            minimum = header_metrics.horizontalAdvance(item.text() if item else '') + 28
            width = max(minimum, table.columnWidth(column))
            if key == 'output_name':
                # Give the actual filename its full width; the user can resize it afterwards.
                text_width = max((
                    cell_metrics.horizontalAdvance(table.item(row, column).text())
                    for row in range(table.rowCount()) if table.item(row, column)
                ), default=0)
                width = max(320, minimum, text_width + 36)
            elif key in ('path', 'sub_path'):
                width = max(minimum, min(360, max(220, width)))
            elif key == 'vpy_path':
                width = max(minimum, 300)
            elif key in ('m2ts_file', 'm2ts_file_detail'):
                width = max(minimum, min(280, width))
            elif key == 'remux_cmd':
                width = max(minimum, 480)
            elif key == 'info':
                width = max(620, max((
                    child.horizontalHeader().length() + child.verticalHeader().width() + 6
                    for row in range(table.rowCount())
                    if isinstance((child := table.cellWidget(row, column)), QTableWidget)
                ), default=0))
            table.setColumnWidth(column, width)
        self._apply_hidden_m2ts_file_detail_columns()

    def _set_compact_table(self, table: QTableWidget, row_height: int = 28, header_height: int = 28):
        row_height = max(row_height, table.fontMetrics().height() + 10)
        header_height = max(header_height, table.horizontalHeader().fontMetrics().height() + 10)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setMinimumSectionSize(row_height)
        table.verticalHeader().setDefaultSectionSize(row_height)
        table.horizontalHeader().setFixedHeight(header_height)

    def _scroll_table_to_primary_column(self, table: QTableWidget):
        def scroll():
            bar = table.horizontalScrollBar()
            if bar.isSliderDown():
                return
            keys = list(table.property('columnKeys') or [])
            primary = 'info' if table is getattr(self, 'table1', None) else 'output_name'
            if table.rowCount() == 0 or primary not in keys:
                bar.setValue(bar.minimum())
                return
            column = keys.index(primary)
            left = table.columnViewportPosition(column) + bar.value()
            spare = max(0, table.viewport().width() - table.columnWidth(column))
            bar.setValue(max(0, left - (spare // 2 if primary == 'output_name' else 0)))

        QTimer.singleShot(0, scroll)

    def _create_table_section(
            self, table: QTableWidget, title: str, description: str, minimum_height: int,
    ) -> tuple[QGroupBox, QLabel]:
        section = QGroupBox(self.t(title), self)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(10, 20, 10, 10)
        layout.setSpacing(8)
        hint = QLabel(self.t(description), section)
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(hint)
        table.setMinimumHeight(minimum_height)
        layout.addWidget(table)
        if table is self.table1:
            table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            table.verticalHeader().setMinimumSectionSize(160)
            table.verticalHeader().setDefaultSectionSize(220)
        return section, hint

    def _refresh_table_descriptions(self):
        if getattr(self, 'table2_section', None) is None:
            return
        function_id = self.get_selected_function_id()
        if function_id in (1, 2):
            self.table1_description.setText(self.t(
                'Select the main playlists for each disc. Use the row buttons to inspect chapters and timing.'
            ))
        else:
            self.table1_description.setText(self.t(
                'Select the main playlists for each disc. Inspect chapters, timing and tracks with the row buttons.'
            ))
        if function_id == 1:
            title = self.t('Subtitle alignment')
            description = self.t('Match subtitles to episodes, then adjust chapter selection and timing offsets.')
        elif function_id == 2:
            title = self.t('MKV files')
            description = self.t('These files receive the selected chapters. Review the source paths and durations.')
        elif function_id == 5:
            title = self.t('Main playlists')
            description = self.t('Review chapter ranges and track settings for the selected main playlists.')
        elif function_id == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            title = self.t('Main outputs')
            description = self.t('One row per main output. Adjust output names, tracks and the VPy script.')
        else:
            title = self.t('Main outputs')
            description = self.t('One row per main output. Adjust chapter ranges, output names and optional subtitles.')
        self.table2_section.setTitle(title)
        self.table2_description.setText(description)

    def _set_table_column_visual_order(self, table: QTableWidget, order: list[int]):
        header = table.horizontalHeader()
        for desired_visual_index, logical_index in enumerate(order):
            if logical_index < 0 or logical_index >= table.columnCount():
                continue
            current_visual_index = header.visualIndex(logical_index)
            if current_visual_index != desired_visual_index:
                header.moveSection(current_visual_index, desired_visual_index)

    def _reset_table3_column_layout(self):
        """Logical column index must match header label; hidden/detail columns + resize can desync on Windows."""
        if not hasattr(self, 'table3') or not self.table3:
            return
        t = self.table3
        hdr = t.horizontalHeader()
        hdr.setSectionsMovable(False)
        n = int(t.columnCount())
        if n <= 1:
            return
        try:
            self._set_table_column_visual_order(t, list(range(n)))
        except Exception:
            pass

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
