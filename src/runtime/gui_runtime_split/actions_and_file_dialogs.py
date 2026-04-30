"""Target module for button handlers and file/folder dialog actions."""
import datetime
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from functools import partial
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThread, QCoreApplication, QPoint, QEventLoop
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QWidget, QHBoxLayout, QPushButton, \
    QApplication, QProgressDialog, QProgressBar, QTableWidgetItem, QTableWidget, QToolButton, QComboBox, \
    QAbstractItemView, QMenu, QMessageBox, QSizePolicy, QRadioButton, QButtonGroup, QInputDialog, QFileDialog, QCheckBox

from src.bdmv import Chapter
from src.core import MKV_LABELS, REMUX_LABELS, DIY_REMUX_LABELS, ENCODE_LABELS, SUBTITLE_LABELS, ENCODE_REMUX_LABELS, \
    ENCODE_REMUX_SP_LABELS, CURRENT_UI_LANGUAGE, find_mkvtoolinx, is_docker
from src.core.i18n import translate_text
from src.domain import MKV, Ass, SRT, Subtitle
from src.exports.utils import print_terminal_line, print_tb_string_terminal, get_time_str, get_mpv_safe_path, \
    print_exc_terminal
from src.runtime.gui_runtime_classes.encode_mkv_folder_worker import EncodeMkvFolderWorker
from src.runtime.gui_runtime_classes.encode_worker import EncodeWorker
from src.runtime.gui_runtime_classes.file_path_table_widget_item import FilePathTableWidgetItem
from src.runtime.gui_runtime_classes.merge_worker import MergeWorker
from src.runtime.gui_runtime_classes.subtitle_folder_scan_worker import SubtitleFolderScanWorker
from src.runtime.services import BluraySubtitle, _Cancelled
from .gui_base import BluraySubtitleGuiBase


class ActionsAndDialogsMixin(BluraySubtitleGuiBase):
    @staticmethod
    def _append_compat_arg_if_missing(base: str, option_name: str, option_value: str = '') -> str:
        text = str(base or '').strip()
        pattern = rf'(^|\s){re.escape(option_name)}(\s|$)'
        if re.search(pattern, text):
            return text
        addon = option_name if not option_value else f'{option_name} {option_value}'
        return f'{text} {addon}'.strip()

    def _effective_encode_params(self) -> str:
        raw = self.x265_params_edit.toPlainText().strip() if hasattr(self, 'x265_params_edit') else ''
        use_compat = bool(
            getattr(self, 'use_bluray_compat_params_checkbox', None)
            and self.use_bluray_compat_params_checkbox.isChecked()
        )
        if not use_compat:
            return raw

        mode_label = str(getattr(self, 'x265_mode_label', None).text() if getattr(self, 'x265_mode_label', None) else '')
        is_x264 = mode_label.lower().startswith('x264')
        params = str(raw or '').strip()
        if is_x264:
            params = self._append_compat_arg_if_missing(params, '--profile', 'high')
            params = self._append_compat_arg_if_missing(params, '--level', '4.1')
            params = self._append_compat_arg_if_missing(params, '--keyint', '24')
        else:
            params = self._append_compat_arg_if_missing(params, '--profile', 'main10')
            params = self._append_compat_arg_if_missing(params, '--level-idc', '4.1')
            params = self._append_compat_arg_if_missing(params, '--vbv-maxrate', '30000')
            params = self._append_compat_arg_if_missing(params, '--vbv-bufsize', '30000')
        return params

    def _show_error_dialog(self, err_text: str):
        try:
            s = str(err_text or '').strip()
            if s:
                print_terminal_line('[BluraySubtitle] Error (printed to terminal for copy/paste):')
                print_tb_string_terminal(s, with_header=False)
        except Exception:
            pass
        dlg = QDialog(self)
        dlg.setWindowTitle(translate_text('Error'))
        layout = QVBoxLayout()
        dlg.setLayout(layout)
        hint = QLabel(translate_text('[BluraySubtitle] Error dialog: select text with mouse or use Copy.'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        editor = QPlainTextEdit(dlg)
        editor.setReadOnly(True)
        editor.setPlainText(str(err_text or ''))
        editor.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextEditorInteraction
        )
        editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(editor)
        btn_row = QWidget(dlg)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_row.setLayout(btn_layout)
        btn_copy = QPushButton(self.t('Copy Info'), dlg)
        btn_close = QPushButton(self.t('Close'), dlg)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_copy)
        btn_layout.addWidget(btn_close)
        layout.addWidget(btn_row)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(editor.toPlainText()))
        btn_close.clicked.connect(dlg.accept)
        dlg.resize(860, 520)
        editor.setFocus()
        dlg.exec()

    def _start_subtitle_folder_scan(self):
        folder = (self._pending_subtitle_folder or '').strip()
        if not folder or not os.path.isdir(folder):
            return

        # If a previous scan UI is still around, close it before starting a new scan.
        if getattr(self, '_subtitle_scan_show_timer', None):
            try:
                self._subtitle_scan_show_timer.stop()
            except Exception:
                pass
            self._subtitle_scan_show_timer = None
        if getattr(self, '_subtitle_scan_progress_dialog', None):
            try:
                self._subtitle_scan_progress_dialog.close()
                self._subtitle_scan_progress_dialog.deleteLater()
            except Exception:
                pass
            self._subtitle_scan_progress_dialog = None

        if hasattr(self, '_subtitle_scan_cancel_event') and self._subtitle_scan_cancel_event:
            self._subtitle_scan_cancel_event.set()
        if hasattr(self, '_subtitle_scan_thread') and self._subtitle_scan_thread:
            try:
                self._subtitle_scan_thread.quit()
                self._subtitle_scan_thread.finished.connect(self._subtitle_scan_thread.deleteLater)
            except Exception:
                pass
            self._subtitle_scan_thread = None
        if hasattr(self, '_subtitle_scan_worker') and self._subtitle_scan_worker:
            try:
                self._subtitle_scan_worker.deleteLater()
            except Exception:
                pass
            self._subtitle_scan_worker = None

        function_id = self.get_selected_function_id()
        if function_id == 1:
            mode = 1
            title = 'Reading Subtitles'
        elif function_id == 2:
            mode = 2
            title = 'Reading MKV'
        elif function_id in (3, 5):
            mode = 3
            title = 'Reading Subtitles'
        else:
            mode = 4
            title = 'Reading Subtitles'

        if not hasattr(self, '_subtitle_scan_seq'):
            self._subtitle_scan_seq = 0
        self._subtitle_scan_seq += 1
        seq = self._subtitle_scan_seq
        cancel_event = threading.Event()
        self._subtitle_scan_cancel_event = cancel_event

        selected_mpls = self.get_selected_mpls_no_ext()

        progress_dialog = QProgressDialog(self.t(title), self.t('Cancel'), 0, 1000, self)
        progress_dialog.setMinimumWidth(400)
        bar = QProgressBar(progress_dialog)
        bar.setRange(0, 1000)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_dialog.setBar(bar)

        def update_bar_format(val):
            bar.setFormat(f"{val / 10.0:.1f}%")

        bar.valueChanged.connect(update_bar_format)
        update_bar_format(0)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dialog.canceled.connect(cancel_event.set)
        self._subtitle_scan_progress_dialog = progress_dialog

        show_timer = QTimer(self)
        show_timer.setSingleShot(True)
        show_timer.setInterval(2000)
        self._subtitle_scan_show_timer = show_timer

        def show_if_still_running():
            if getattr(self, '_subtitle_scan_thread', None) and self._subtitle_scan_thread.isRunning():
                if getattr(self, '_subtitle_scan_progress_dialog', None):
                    self._subtitle_scan_progress_dialog.show()

        show_timer.timeout.connect(show_if_still_running)
        show_timer.start()

        self._subtitle_scan_thread = QThread(self)
        self._subtitle_scan_worker = SubtitleFolderScanWorker(
            seq,
            mode,
            folder,
            self.bdmv_folder_path.text(),
            self.checkbox1.isChecked(),
            selected_mpls,
            cancel_event,
            movie_mode=self._is_movie_mode()
        )
        self._subtitle_scan_worker.moveToThread(self._subtitle_scan_thread)
        self._subtitle_scan_thread.started.connect(self._subtitle_scan_worker.run)
        self._subtitle_scan_worker.progress.connect(progress_dialog.setValue)
        self._subtitle_scan_worker.label.connect(lambda text: progress_dialog.setLabelText(self.t(text)))

        def cleanup():
            if getattr(self, '_subtitle_scan_show_timer', None):
                try:
                    self._subtitle_scan_show_timer.stop()
                except Exception:
                    pass
                self._subtitle_scan_show_timer = None
            if getattr(self, '_subtitle_scan_progress_dialog', None):
                try:
                    self._subtitle_scan_progress_dialog.close()
                    self._subtitle_scan_progress_dialog.deleteLater()
                except Exception:
                    pass
                self._subtitle_scan_progress_dialog = None
            if getattr(self, '_subtitle_scan_thread', None):
                try:
                    t_wait = time.perf_counter()
                    print('[ShutdownDebug] subtitle_scan_thread.quit()')
                    self._subtitle_scan_thread.quit()
                    self._subtitle_scan_thread.wait()
                    print(f"[ShutdownDebug] subtitle_scan_thread.wait() done in {(time.perf_counter() - t_wait) * 1000:.1f} ms")
                    self._subtitle_scan_thread.deleteLater()
                except Exception:
                    pass
                self._subtitle_scan_thread = None
            if getattr(self, '_subtitle_scan_worker', None):
                try:
                    self._subtitle_scan_worker.deleteLater()
                except Exception:
                    pass
                self._subtitle_scan_worker = None
            self._subtitle_scan_cancel_event = None

        def on_result(payload: object):
            if not isinstance(payload, dict) or payload.get('seq') != seq:
                return
            cleanup()
            if payload.get('mode') == 1 and self._is_movie_mode():
                self._refresh_movie_subtitle_table2(payload.get('rows') or [])
                self._update_main_row_play_button()
                return
            if payload.get('mode') in (3, 4, 5) and self._is_movie_mode():
                rows = payload.get('rows') or []
                for i, (path, _dur) in enumerate(rows):
                    if i < self.table2.rowCount():
                        self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
                self._refresh_movie_table2()
                self._update_main_row_play_button()
                return
            if payload.get('mode') == 2:
                self.table2.clear()
                self.table2.setColumnCount(len(MKV_LABELS))
                self._set_table_headers(self.table2, MKV_LABELS)
                self._set_table2_default_column_order()
                rows = payload.get('rows') or []
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
                return

            rows = payload.get('rows') or []
            if payload.get('mode') == 3:
                if not rows:
                    # In remux/encode flows subtitle folder is optional; keep current rows.
                    return
                self.table2.clear()
                self.table2.setColumnCount(len(REMUX_LABELS))
                self._set_table_headers(self.table2, REMUX_LABELS)
                self._set_table2_default_column_order()
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
            elif payload.get('mode') == 4:
                if not rows:
                    # In remux/encode flows subtitle folder is optional; keep current rows.
                    return
                self.table2.clear()
                self.table2.setColumnCount(len(ENCODE_LABELS))
                self._set_table_headers(self.table2, ENCODE_LABELS)
                self._set_table2_default_column_order()
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                    self.ensure_encode_row_widgets(i)
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
            elif payload.get('mode') == 5:
                if not rows:
                    # In remux/encode flows subtitle folder is optional; keep current rows.
                    return
                self.table2.clear()
                self.table2.setColumnCount(len(DIY_REMUX_LABELS))
                self._set_table_headers(self.table2, DIY_REMUX_LABELS)
                self._set_table2_default_column_order()
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    self.table2.setItem(i, 0, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, 1, QTableWidgetItem(dur))
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)
            else:
                self.table2.clear()
                self.table2.setColumnCount(len(SUBTITLE_LABELS))
                self._set_table_headers(self.table2, SUBTITLE_LABELS)
                self._set_table2_subtitle_column_order()
                self.table2.setRowCount(len(rows))
                for i, (path, dur) in enumerate(rows):
                    check_item = QTableWidgetItem()
                    check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    check_item.setCheckState(Qt.CheckState.Checked)
                    self.table2.setItem(i, 0, check_item)
                    self.table2.setItem(i, 1, FilePathTableWidgetItem(path))
                    self.table2.setItem(i, SUBTITLE_LABELS.index('sub_duration'), QTableWidgetItem(dur))

                self._update_main_row_play_button()
                for bdmv_index in range(self.table1.rowCount()):
                    info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                    if info:
                        info.resizeColumnsToContents()

                self.sub_check_state = [2 for _ in range(self.table2.rowCount())]
                try:
                    self.table2.cellClicked.disconnect(self.on_subtitle_select)
                except Exception:
                    pass
                self.table2.cellClicked.connect(self.on_subtitle_select)
                self.table2.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                try:
                    self.table2.customContextMenuRequested.disconnect(self.on_subtitle_menu)
                except Exception:
                    pass
                self.table2.customContextMenuRequested.connect(self.on_subtitle_menu)
                self.table2.resizeColumnsToContents()
                self._scroll_table_h_to_right(self.table2)

            configuration = payload.get('configuration') or {}
            if configuration:
                self.on_configuration(configuration)
            elif self.get_selected_function_id() in (3, 4, 5) and (not self._is_movie_mode()):
                # Keep existing episode rows when subtitle scan returns empty results.
                # In remux/encode modes, table2 is source-driven by main MPLS selection,
                # not subtitle-folder scan results.
                pass

        def on_canceled():
            cleanup()

        def on_failed(message: str):
            cleanup()
            self._show_error_dialog(message)

        self._subtitle_scan_worker.result.connect(on_result)
        self._subtitle_scan_worker.canceled.connect(on_canceled)
        self._subtitle_scan_worker.failed.connect(on_failed)
        self._subtitle_scan_thread.start()

    def _populate_encode_from_remux_folder(self):
        if self.get_selected_function_id() != 4 or getattr(self, '_encode_input_mode', 'bdmv') != 'remux':
            return
        folder = self._normalize_path_input(self.remux_folder_path.text() if hasattr(self, 'remux_folder_path') else '')
        if not folder or not os.path.isdir(folder):
            return
        start_ts = time.time()
        progress_dialog = QProgressDialog(self.t('Loading...'), '', 0, 1000, self)
        progress_dialog.setMinimumWidth(420)
        bar = QProgressBar(progress_dialog)
        bar.setRange(0, 1000)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_dialog.setBar(bar)
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        show_timer = QTimer(self)
        show_timer.setSingleShot(True)
        show_timer.setInterval(2000)

        def show_if_needed():
            try:
                if (time.time() - start_ts) >= 2.0:
                    progress_dialog.show()
            except Exception:
                pass

        show_timer.timeout.connect(show_if_needed)
        show_timer.start()
        mkvs = [f for f in os.listdir(folder) if f.lower().endswith('.mkv') and os.path.isfile(os.path.join(folder, f))]
        mkvs.sort(key=lambda x: x.lower())
        self.table2.setSortingEnabled(False)
        self.table2.setRowCount(len(mkvs))
        for r, name in enumerate(mkvs):
            src = os.path.normpath(os.path.join(folder, name))
            sub_col = ENCODE_REMUX_LABELS.index('sub_path')
            lang_col = ENCODE_REMUX_LABELS.index('language')
            dur_col = ENCODE_REMUX_LABELS.index('ep_duration')
            out_col = ENCODE_REMUX_LABELS.index('output_name')
            play_col = ENCODE_REMUX_LABELS.index('play')
            tracks_col = ENCODE_REMUX_LABELS.index('edit_tracks')
            chapters_col = ENCODE_REMUX_LABELS.index('edit_chapters')
            attachments_col = ENCODE_REMUX_LABELS.index('edit_attachments')
            self.table2.setItem(r, sub_col, FilePathTableWidgetItem(''))
            combo = self.create_language_combo(parent=self.table2)
            self.table2.setCellWidget(r, lang_col, combo)
            try:
                dur = MKV(src).get_duration()
                self.table2.setItem(r, dur_col, QTableWidgetItem(get_time_str(dur)))
            except Exception:
                self.table2.setItem(r, dur_col, QTableWidgetItem(''))
            out_item = QTableWidgetItem(name)
            out_item.setData(Qt.ItemDataRole.UserRole, src)
            self.table2.setItem(r, out_col, out_item)
            btn_play = QToolButton(self.table2)
            btn_play.setText(self.t('play'))
            btn_play.clicked.connect(partial(self.open_file_path, src))
            self.table2.setCellWidget(r, play_col, btn_play)
            btn_tracks = QToolButton(self.table2)
            btn_tracks.setText(self.t('edit tracks'))
            btn_tracks.clicked.connect(partial(self.on_edit_tracks_from_mkv_row, self.table2, r))
            self.table2.setCellWidget(r, tracks_col, btn_tracks)
            btn_chapters = QToolButton(self.table2)
            btn_chapters.setText(self.t('edit'))
            btn_chapters.clicked.connect(partial(self.on_edit_chapters_from_mkv_row, self.table2, r))
            self.table2.setCellWidget(r, chapters_col, btn_chapters)
            btn_attachments = QToolButton(self.table2)
            btn_attachments.setText(self.t('edit'))
            btn_attachments.clicked.connect(partial(self.on_edit_attachments_from_mkv_row, self.table2, r))
            self.table2.setCellWidget(r, attachments_col, btn_attachments)
            self.ensure_encode_row_widgets(r)
            if (time.time() - start_ts) >= 2.0:
                try:
                    bar.setValue(int((r + 1) / max(1, len(mkvs)) * 1000))
                except Exception:
                    pass
                QCoreApplication.processEvents()
        self.table2.resizeColumnsToContents()
        self._resize_table_columns_for_language(self.table2)
        self._scroll_table_h_to_right(self.table2)
        self._update_language_combo_enabled_state()
        self.table2.setSortingEnabled(True)
        try:
            show_timer.stop()
            progress_dialog.close()
            progress_dialog.deleteLater()
        except Exception:
            pass
        self._populate_encode_sps_from_remux_folder(folder)

    def _populate_encode_sps_from_remux_folder(self, folder: str):
        if self.get_selected_function_id() != 4 or getattr(self, '_encode_input_mode', 'bdmv') != 'remux':
            return
        sp_folder = os.path.join(folder, 'SPs')
        if not os.path.isdir(sp_folder):
            self.table3.setRowCount(0)
            return
        start_ts = time.time()
        progress_dialog = QProgressDialog(self.t('Loading...'), '', 0, 1000, self)
        progress_dialog.setMinimumWidth(420)
        bar = QProgressBar(progress_dialog)
        bar.setRange(0, 1000)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_dialog.setBar(bar)
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        show_timer = QTimer(self)
        show_timer.setSingleShot(True)
        show_timer.setInterval(2000)

        def show_if_needed():
            try:
                if (time.time() - start_ts) >= 2.0:
                    progress_dialog.show()
            except Exception:
                pass

        show_timer.timeout.connect(show_if_needed)
        show_timer.start()
        mkvs = [f for f in os.listdir(sp_folder) if
                f.lower().endswith('.mkv') and os.path.isfile(os.path.join(sp_folder, f))]
        mkvs.sort(key=lambda x: x.lower())
        self.table3.setSortingEnabled(False)
        self.table3.setRowCount(len(mkvs))
        for r, name in enumerate(mkvs):
            src = os.path.normpath(os.path.join(sp_folder, name))
            dur_col = ENCODE_REMUX_SP_LABELS.index('duration')
            out_col = ENCODE_REMUX_SP_LABELS.index('output_name')
            play_col = ENCODE_REMUX_SP_LABELS.index('play')
            tracks_col = ENCODE_REMUX_SP_LABELS.index('edit_tracks')
            chapters_col = ENCODE_REMUX_SP_LABELS.index('edit_chapters')
            attachments_col = ENCODE_REMUX_SP_LABELS.index('edit_attachments')
            try:
                dur = MKV(src).get_duration()
                self.table3.setItem(r, dur_col, QTableWidgetItem(get_time_str(dur)))
            except Exception:
                self.table3.setItem(r, dur_col, QTableWidgetItem(''))
            out_item = QTableWidgetItem(name)
            out_item.setData(Qt.ItemDataRole.UserRole, src)
            self.table3.setItem(r, out_col, out_item)
            btn_play = QToolButton(self.table3)
            btn_play.setText(self.t('play'))
            btn_play.clicked.connect(partial(self.open_file_path, src))
            self.table3.setCellWidget(r, play_col, btn_play)
            btn_tracks = QToolButton(self.table3)
            btn_tracks.setText(self.t('edit tracks'))
            btn_tracks.clicked.connect(partial(self.on_edit_tracks_from_mkv_row, self.table3, r))
            self.table3.setCellWidget(r, tracks_col, btn_tracks)
            btn_chapters = QToolButton(self.table3)
            btn_chapters.setText(self.t('edit'))
            btn_chapters.clicked.connect(partial(self.on_edit_chapters_from_mkv_row, self.table3, r))
            self.table3.setCellWidget(r, chapters_col, btn_chapters)
            btn_attachments = QToolButton(self.table3)
            btn_attachments.setText(self.t('edit'))
            btn_attachments.clicked.connect(partial(self.on_edit_attachments_from_mkv_row, self.table3, r))
            self.table3.setCellWidget(r, attachments_col, btn_attachments)
            vpy_col = ENCODE_REMUX_SP_LABELS.index('vpy_path')
            edit_col = ENCODE_REMUX_SP_LABELS.index('edit_vpy')
            preview_col = ENCODE_REMUX_SP_LABELS.index('preview_script')
            if not self.table3.cellWidget(r, vpy_col):
                self.table3.setCellWidget(r, vpy_col, self.create_vpy_path_widget(parent=self.table3))
            if not self.table3.cellWidget(r, edit_col):
                btn = QToolButton(self.table3)
                btn.setText(self.t('edit'))
                btn.clicked.connect(self.on_edit_sp_vpy_clicked)
                self.table3.setCellWidget(r, edit_col, btn)
            if not self.table3.cellWidget(r, preview_col):
                btn = QToolButton(self.table3)
                btn.setText(self.t('preview'))
                btn.clicked.connect(self.on_preview_sp_scripts_clicked)
                self.table3.setCellWidget(r, preview_col, btn)
            if (time.time() - start_ts) >= 2.0:
                try:
                    bar.setValue(int((r + 1) / max(1, len(mkvs)) * 1000))
                except Exception:
                    pass
                QCoreApplication.processEvents()
        self.table3.resizeColumnsToContents()
        self._resize_table_columns_for_language(self.table3)
        self._scroll_table_h_to_right(self.table3)
        self.table3.setSortingEnabled(True)
        try:
            show_timer.stop()
            progress_dialog.close()
            progress_dialog.deleteLater()
        except Exception:
            pass

    def add_chapters(self):
        cancel_event = threading.Event()
        self._current_cancel_event = cancel_event
        self._exe_button_default_text = self.exe_button.text()
        self._update_exe_button_progress(0, 'Editing' if self.checkbox1.isChecked() else 'Muxing')

        # Use sorted mkv files if table is sorted, otherwise use original order
        mkv_files = self.get_mkv_files_in_table_order()
        if not mkv_files:
            mkv_files = [self.table2.item(mkv_index, 0).text() for mkv_index in range(self.table2.rowCount())]
        try:
            chapter_cfg: dict[int, dict[str, int | str]] = {}
            try:
                if not self._is_movie_mode():
                    chapter_cfg = self._generate_configuration_from_ui_inputs()
            except Exception:
                chapter_cfg = {}
            bs = BluraySubtitle(
                self.bdmv_folder_path.text(),
                mkv_files,
                self.checkbox1.isChecked(),
                self._update_exe_button_progress
            )
            bs.configuration = chapter_cfg
            bs.add_chapter_to_mkv(
                mkv_files, self.table1, cancel_event=cancel_event,
                configuration=chapter_cfg if chapter_cfg else None,
            )
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
            if self.checkbox1.isChecked():
                self._show_bottom_message('Chapters added to MKV successfully')
            else:
                self._show_bottom_message('Chapters added successfully, new MKV is in output folder')
        except _Cancelled:
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
        except Exception as e:
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
            self._show_error_dialog(traceback.format_exc())
        else:
            bs.completion()

    def create_language_combo(self, initial: str = 'chi', parent: Optional[QWidget] = None) -> QComboBox:
        combo = QComboBox(parent)
        combo.setEditable(True)
        combo.addItems(['chi', 'zho', 'jpn', 'eng', 'kor', 'und'])
        auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
        combo.setCurrentText((initial or auto_lang).strip() or auto_lang)
        combo._auto_lang = auto_lang
        return combo

    def edit_subtitle(self, path: str):
        class SubtitleEditDialog(QDialog):
            def __init__(this):
                super(SubtitleEditDialog, this).__init__()
                this.altered = False
                this.setWindowTitle(f"{self.t('Edit Subtitle')}: {path}")
                layout = QVBoxLayout()
                this.table_widget = QTableWidget()
                this.table_widget.horizontalHeader().setSortIndicatorShown(True)
                this.table_widget.setSortingEnabled(True)
                if path.endswith('.ass') or path.endswith('.ssa'):
                    try:
                        with open(path, 'r', encoding='utf-8-sig') as fp:
                            this.subtitle = Ass(fp)
                    except Exception as e:
                        with open(path, 'r', encoding='utf-16') as fp:
                            this.subtitle = Ass(fp)
                    this.keys = list(this.subtitle.events[0].__dict__.keys())
                    this.table_widget.setColumnCount(len(this.keys) + 1)
                    this.table_widget.setHorizontalHeaderLabels(['index'] + this.keys)
                    this.table_widget.setRowCount(len(this.subtitle.events))
                    for i in range(len(this.subtitle.events)):
                        this.table_widget.setItem(i, 0, QTableWidgetItem(
                            ((len(str(len(this.subtitle.events)))) - len(str(i + 1))) * '0' + str(i + 1)))
                        for j in range(len(this.keys)):
                            item = getattr(this.subtitle.events[i], this.keys[j])
                            if isinstance(item, datetime.timedelta):
                                if len(str(item)) == 14:
                                    item = str(item)[:-3]
                                elif len(str(item)) == 7:
                                    item = f'{str(item)}.000'
                            item = str(item)
                            this.table_widget.setItem(i, j + 1, QTableWidgetItem(item))
                    this.table_widget.horizontalHeader().setSortIndicator(4, Qt.SortOrder.DescendingOrder)
                    this.setMinimumWidth(1000)
                    this.setMinimumHeight(800)
                elif path.endswith('.srt'):
                    try:
                        with open(path, 'r', encoding='utf-8-sig') as fp:
                            this.subtitle = SRT(fp)
                    except Exception as e:
                        with open(path, 'r', encoding='utf-16') as fp:
                            this.subtitle = SRT(fp)
                    this.table_widget.setColumnCount(4)
                    this.table_widget.setHorizontalHeaderLabels(['index', 'start', 'end', 'text'])
                    this.table_widget.setRowCount(len(this.subtitle.lines))
                    m_len = len(str(this.subtitle.lines[-1][0]))
                    for i, line in enumerate(this.subtitle.lines):
                        this.table_widget.setItem(i, 0,
                                                  QTableWidgetItem((m_len - len(str(line[0]))) * '0' + str(line[0])))
                        this.table_widget.setItem(i, 1, QTableWidgetItem(line[1]))
                        this.table_widget.setItem(i, 2, QTableWidgetItem(line[2]))
                        this.table_widget.setItem(i, 3, QTableWidgetItem(line[3]))
                    this.table_widget.horizontalHeader().setSortIndicator(2, Qt.SortOrder.DescendingOrder)
                    this.setMinimumWidth(600)
                    this.setMinimumHeight(600)

                this.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                this.customContextMenuRequested.connect(this.on_subtitle_edit_menu)
                this.table_widget.resizeColumnsToContents()
                layout.addWidget(this.table_widget)
                this.save_button = QPushButton('save')
                this.save_button.clicked.connect(this.save_subtitle)
                layout.addWidget(this.save_button)
                this.setLayout(layout)
                this.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                this.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
                this.table_widget.itemChanged.connect(this.on_subtitle_changed)

            def on_subtitle_edit_menu(this, pos: QPoint):
                row_indexes = {i.row() for i in this.table_widget.selectionModel().selection().indexes()}
                menu = QMenu()
                item = menu.addAction('remove')
                screen_pos = this.table_widget.mapToGlobal(pos)
                action = menu.exec(screen_pos)
                if action == item:
                    row_indexes = list(row_indexes)
                    row_indexes.sort()
                    if row_indexes:
                        this.altered = True
                    for i, row_index in enumerate(row_indexes):
                        if hasattr(this.subtitle, 'lines'):
                            this.subtitle.delete_lines.add(int(this.table_widget.item(row_index - i, 0).text()))
                        else:
                            this.subtitle.delete_lines.add(int(this.table_widget.item(row_index - i, 0).text()) - 1)
                        this.table_widget.removeRow(row_index - i)

            def on_subtitle_changed(this, item: QTableWidgetItem):
                if path.endswith('.ass') or path.endswith('.ssa'):
                    setattr(this.subtitle.events[int(this.table_widget.item(item.row(), 0).text()) - 1],
                            this.keys[item.column() - 1], item.text())
                    this.altered = True
                if path.endswith('.srt'):
                    this.subtitle.lines[item.row()][item.column()] = item.text()
                    this.altered = True

            def save_subtitle(this):
                if this.altered:
                    with open(path + '.bak', 'a', encoding='utf-8-sig') as fp:
                        this.subtitle.dump_file(fp)
                    os.remove(path)
                    os.rename(path + '.bak', path)
                self.on_subtitle_folder_path_change()
                this.altered = False

        subtitle_edit_dialog = SubtitleEditDialog()
        subtitle_edit_dialog.exec()

    def encode_bluray(self):
        output_folder = os.path.normpath(self.output_folder_path.text().strip()) if hasattr(self,
                                                                                            'output_folder_path') else ''
        if not output_folder:
            QMessageBox.information(self, " ", "Output folder is not selected")
            return
        if not os.path.isdir(output_folder):
            QMessageBox.information(self, " ", "Output folder does not exist")
            return
        self.ensure_default_vpy_file()
        find_mkvtoolinx()

        cancel_event = threading.Event()
        self._current_cancel_event = cancel_event
        self._exe_button_default_text = self.exe_button.text()
        self._update_exe_button_progress(0, 'Preparing')

        if getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
            folder = self._normalize_path_input(
                self.remux_folder_path.text() if hasattr(self, 'remux_folder_path') else '')
            if not folder or not os.path.isdir(folder):
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                QMessageBox.information(self, " ", "Select the remux folder")
                return
            try:
                remux_folder = os.path.normpath(folder)
                output_norm = os.path.normpath(output_folder)
                parent_of_remux = os.path.normpath(os.path.dirname(remux_folder.rstrip(os.sep)))
                if output_norm == parent_of_remux:
                    self._current_cancel_event = None
                    self._reset_exe_button()
                    self.exe_button.setEnabled(True)
                    QMessageBox.information(self, " ", "Output folder is parent of input folder, please change output folder")
                    return
            except Exception:
                pass
            output_folder = self._resolve_remux_output_folder(output_folder)

            mkv_rows: list[dict[str, str]] = []
            for i in range(self.table2.rowCount()):
                src = self._get_remux_source_path_from_table2_row(i)
                if not src or not os.path.exists(src):
                    continue
                try:
                    out_col = ENCODE_REMUX_LABELS.index('output_name')
                    lang_col = ENCODE_REMUX_LABELS.index('language')
                    sub_col = ENCODE_REMUX_LABELS.index('sub_path')
                except Exception:
                    out_col, lang_col, sub_col = 3, 1, 0
                out_item = self.table2.item(i, out_col)
                out_name = out_item.text().strip() if out_item and out_item.text() else os.path.basename(src)
                sub_item = self.table2.item(i, sub_col)
                sub_path = sub_item.text().strip() if sub_item and sub_item.text() else ''
                lang = ''
                combo = self.table2.cellWidget(i, lang_col)
                if isinstance(combo, QComboBox):
                    lang = str(combo.currentData() or combo.currentText() or '').strip()
                vpy_path = self.get_vpy_path_from_row(i) or self.get_default_vpy_path()
                mkv_rows.append({
                    'src_path': src,
                    'output_name': out_name,
                    'sub_path': sub_path,
                    'language': lang,
                    'vpy_path': vpy_path,
                })

            sp_rows: list[dict[str, str]] = []
            if hasattr(self, 'table3'):
                for i in range(self.table3.rowCount()):
                    src = self._get_remux_source_path_from_table3_row(i)
                    if not src or not os.path.exists(src):
                        continue
                    try:
                        out_col = ENCODE_REMUX_SP_LABELS.index('output_name')
                    except Exception:
                        out_col = 1
                    out_item = self.table3.item(i, out_col)
                    out_name = out_item.text().strip() if out_item and out_item.text() else os.path.basename(src)
                    vpy_path = self.get_sp_vpy_path_from_row(i) or self.get_default_vpy_path()
                    sp_rows.append({
                        'src_path': src,
                        'output_name': out_name,
                        'vpy_path': vpy_path,
                    })

            vspipe_mode = 'bundle' if self.vspipe_mode_combo.currentText() == 'Built-in' else 'system'
            x265_mode = 'bundle' if self.x265_mode_combo.currentText() == 'Built-in' else 'system'
            x265_params = self._effective_encode_params()
            use_getnative = bool(getattr(self, "use_getnative_checkbox", None) and self.use_getnative_checkbox.isChecked())
            if self.sub_pack_hard_radio.isChecked():
                sub_pack_mode = 'hard'
            elif self.sub_pack_soft_radio.isChecked():
                sub_pack_mode = 'soft'
            else:
                sub_pack_mode = 'external'

            self._encode_thread = QThread(self)
            self._encode_worker = EncodeMkvFolderWorker(
                mkv_rows=mkv_rows,
                sp_rows=sp_rows,
                remux_folder=remux_folder,
                output_folder=output_folder,
                cancel_event=cancel_event,
                vspipe_mode=vspipe_mode,
                x265_mode=x265_mode,
                x265_params=x265_params,
                sub_pack_mode=sub_pack_mode,
                use_getnative=use_getnative,
            )
            self._encode_worker.moveToThread(self._encode_thread)
            self._encode_thread.started.connect(self._encode_worker.run)
            self._encode_worker.progress.connect(self._on_exe_button_progress_value)
            self._encode_worker.label.connect(self._on_exe_button_progress_text)

            def cleanup():
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                if hasattr(self, '_encode_thread') and self._encode_thread:
                    t_wait = time.perf_counter()
                    print('[ShutdownDebug] encode_thread(remux-mode).quit()')
                    self._encode_thread.quit()
                    self._encode_thread.wait()
                    print(f"[ShutdownDebug] encode_thread(remux-mode).wait() done in {(time.perf_counter() - t_wait) * 1000:.1f} ms")
                    self._encode_thread.deleteLater()
                    self._encode_thread = None
                if hasattr(self, '_encode_worker') and self._encode_worker:
                    self._encode_worker.deleteLater()
                    self._encode_worker = None

            def on_finished():
                cleanup()
                self._show_bottom_message('Blu-ray encode completed!')

            def on_canceled():
                cleanup()

            def on_failed(message: str):
                cleanup()
                self._show_error_dialog(message)

            self._encode_worker.finished.connect(on_finished)
            self._encode_worker.canceled.connect(on_canceled)
            self._encode_worker.failed.connect(on_failed)
            self._encode_thread.start()
            return

        sub_files = [self.table2.item(i, 0).text() for i in range(0, self.table2.rowCount()) if self.table2.item(i, 0)]
        episode_output_names = self._get_episode_output_names_from_table2()
        episode_subtitle_languages = self._get_episode_subtitle_languages_from_table2()
        vpy_paths = []
        for i in range(self.table2.rowCount()):
            try:
                vpy_paths.append(self.get_vpy_path_from_row(i))
            except Exception:
                vpy_paths.append(self.get_default_vpy_path())
        sp_vpy_paths = []
        sp_entries = []
        if hasattr(self, 'table3'):
            for i in range(self.table3.rowCount()):
                try:
                    sp_vpy_paths.append(self.get_sp_vpy_path_from_row(i))
                except Exception:
                    sp_vpy_paths.append(self.get_default_vpy_path())
                try:
                    sp_entries.append(self._table3_get_sp_entry_for_row(i))
                except Exception:
                    sp_entries.append({
                        'bdmv_index': 0, 'mpls_file': '', 'm2ts_file': '', 'selected': False, 'output_name': '',
                        'bdmv_root': '',
                    })
        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
            QMessageBox.information(self, " ", "Main MPLS is not selected")
            return
        configuration: dict[int, dict[str, int | str]] = {}
        if self._is_movie_mode():
            self._refresh_movie_table2()
            configuration = getattr(self, '_movie_configuration', {}) or {}
            if not configuration:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                QMessageBox.information(self, " ", "Configuration is empty, skipping update")
                return
        else:
            try:
                bs = BluraySubtitle(
                    self.bdmv_folder_path.text(),
                    sub_files,
                    self.checkbox1.isChecked(),
                    self._update_exe_button_progress,
                    approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
                )
                configuration = bs.generate_configuration_from_selected_mpls(selected_mpls, cancel_event=cancel_event)
            except _Cancelled:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                return
            except Exception as e:
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                self._show_error_dialog(traceback.format_exc())
                return

        try:
            self._apply_main_remux_cmds_to_configuration(configuration)
        except Exception:
            pass

        vspipe_mode = 'bundle' if self.vspipe_mode_combo.currentText() == 'Built-in' else 'system'
        x265_mode = 'bundle' if self.x265_mode_combo.currentText() == 'Built-in' else 'system'
        x265_params = self._effective_encode_params()
        use_getnative = bool(getattr(self, "use_getnative_checkbox", None) and self.use_getnative_checkbox.isChecked())
        if self.sub_pack_hard_radio.isChecked():
            sub_pack_mode = 'hard'
        elif self.sub_pack_soft_radio.isChecked():
            sub_pack_mode = 'soft'
        else:
            sub_pack_mode = 'external'

        self._encode_thread = QThread(self)
        self._encode_worker = EncodeWorker(
            self.bdmv_folder_path.text(),
            sub_files,
            self.checkbox1.isChecked(),
            output_folder,
            configuration,
            selected_mpls,
            cancel_event,
            vpy_paths,
            sp_vpy_paths,
            sp_entries,
            episode_output_names,
            episode_subtitle_languages,
            vspipe_mode,
            x265_mode,
            x265_params,
            sub_pack_mode,
            use_getnative=use_getnative,
            movie_mode=self._is_movie_mode(),
            track_selection_config=getattr(self, '_track_selection_config', {}),
            track_language_config=getattr(self, '_track_language_config', {})
        )
        self._encode_worker.moveToThread(self._encode_thread)
        self._encode_thread.started.connect(self._encode_worker.run)
        self._encode_worker.progress.connect(self._on_exe_button_progress_value)
        self._encode_worker.label.connect(self._on_exe_button_progress_text)

        def cleanup():
            self._current_cancel_event = None
            self._reset_exe_button()
            self.exe_button.setEnabled(True)
            if hasattr(self, '_encode_thread') and self._encode_thread:
                t_wait = time.perf_counter()
                print('[ShutdownDebug] encode_thread(bdmv-mode).quit()')
                self._encode_thread.quit()
                self._encode_thread.wait()
                print(f"[ShutdownDebug] encode_thread(bdmv-mode).wait() done in {(time.perf_counter() - t_wait) * 1000:.1f} ms")
                self._encode_thread.deleteLater()
                self._encode_thread = None
            if hasattr(self, '_encode_worker') and self._encode_worker:
                self._encode_worker.deleteLater()
                self._encode_worker = None

        def on_finished():
            cleanup()
            self._show_bottom_message('Blu-ray encode completed!')

        def on_canceled():
            cleanup()

        def on_failed(message: str):
            cleanup()
            self._show_error_dialog(message)

        self._encode_worker.finished.connect(on_finished)
        self._encode_worker.canceled.connect(on_canceled)
        self._encode_worker.failed.connect(on_failed)
        self._encode_thread.start()

    def generate_subtitle(self, silent_mode: bool = False):
        if self._is_movie_mode():
            selected_mpls = self.get_selected_mpls_no_ext()
            if not selected_mpls:
                if not silent_mode:
                    QMessageBox.information(self, " ", "Main MPLS is not selected")
                return False

            folder_to_bdmv: dict[str, int] = {}
            bdmv_to_info: dict[int, tuple[str, str]] = {}
            for folder, mpls_no_ext in selected_mpls:
                if folder not in folder_to_bdmv:
                    folder_to_bdmv[folder] = len(folder_to_bdmv) + 1
                bdmv_to_info[folder_to_bdmv[folder]] = (folder, mpls_no_ext)

            try:
                bdmv_col = SUBTITLE_LABELS.index('bdmv_index')
            except Exception:
                bdmv_col = 4

            tasks: list[tuple[str, str, str]] = []
            for r in range(self.table2.rowCount()):
                it = self.table2.item(r, 0)
                if not it or it.checkState() != Qt.CheckState.Checked:
                    continue
                p_item = self.table2.item(r, 1)
                if not p_item or not p_item.text().strip():
                    continue
                sub_path = p_item.text().strip()
                if not os.path.exists(sub_path):
                    continue
                bdmv_item = self.table2.item(r, bdmv_col)
                try:
                    bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
                except Exception:
                    bdmv_index = 0
                info = bdmv_to_info.get(bdmv_index)
                if not info:
                    continue
                folder, mpls_no_ext = info
                tasks.append((sub_path, folder, mpls_no_ext))

            if not tasks:
                if not silent_mode:
                    QMessageBox.information(self, " ", "Subtitle file is not selected")
                return False

            cancel_event = threading.Event()
            self._current_cancel_event = cancel_event
            self._exe_button_default_text = self.exe_button.text()
            self._exe_button_progress_value = 0
            self._exe_button_progress_text = 'Generating Subtitles'
            self._update_exe_button_progress(0, 'Generating Subtitles')
            self._merge_thread = QThread(self)
            self._merge_worker = MergeWorker(
                self.bdmv_folder_path.text(),
                [],
                self.checkbox1.isChecked(),
                selected_mpls,
                cancel_event,
                subtitle_suffix=self._get_subtitle_suffix()
            )
            self._merge_worker.movie_tasks = tasks
            self._merge_worker.moveToThread(self._merge_thread)
            self._merge_thread.started.connect(self._merge_worker.run)
            self._merge_worker.progress.connect(self._on_exe_button_progress_value)
            self._merge_worker.label.connect(self._on_exe_button_progress_text)

            success = False

            def cleanup():
                self._current_cancel_event = None
                self._reset_exe_button()
                if hasattr(self, '_merge_thread') and self._merge_thread:
                    t_wait = time.perf_counter()
                    print('[ShutdownDebug] merge_thread(movie).quit()')
                    self._merge_thread.quit()
                    self._merge_thread.wait()
                    print(f"[ShutdownDebug] merge_thread(movie).wait() done in {(time.perf_counter() - t_wait) * 1000:.1f} ms")
                    self._merge_thread.deleteLater()
                    self._merge_thread = None
                if hasattr(self, '_merge_worker') and self._merge_worker:
                    self._merge_worker.deleteLater()
                    self._merge_worker = None
                self.altered = False

            def on_finished():
                nonlocal success
                success = True
                cleanup()
                if not silent_mode:
                    self._show_bottom_message("Subtitle generation completed!", 10000)

            def on_canceled():
                cleanup()

            def on_failed(message: str):
                cleanup()
                if not silent_mode:
                    self._show_error_dialog(message)

            self._merge_worker.finished.connect(on_finished)
            self._merge_worker.canceled.connect(on_canceled)
            self._merge_worker.failed.connect(on_failed)
            self._merge_thread.start()
            if silent_mode:
                loop = QEventLoop()

                def quit_loop():
                    if loop.isRunning():
                        loop.quit()

                self._merge_worker.finished.connect(quit_loop)
                self._merge_worker.canceled.connect(quit_loop)
                self._merge_worker.failed.connect(quit_loop)
                loop.exec()
                return success
            return True

        sub_files = []
        for sub_index in range(self.table2.rowCount()):
            if self.sub_check_state[sub_index] != 2:
                continue
            item = self.table2.item(sub_index, 1)
            if item and item.text():
                sub_files.append(item.text())
        if not sub_files:
            if not silent_mode:
                QMessageBox.information(self, " ", "Subtitle file is not selected")
            return False

        selected_mpls = self.get_selected_mpls_no_ext()
        if not selected_mpls:
            if not silent_mode:
                QMessageBox.information(self, " ", "Main MPLS is not selected")
            return False

        cancel_event = threading.Event()
        self._current_cancel_event = cancel_event
        self._exe_button_default_text = self.exe_button.text()
        self._exe_button_progress_value = 0
        self._exe_button_progress_text = 'Generating Subtitles'
        self._update_exe_button_progress(0, 'Generating Subtitles')
        self._merge_thread = QThread(self)
        self._merge_worker = MergeWorker(
            self.bdmv_folder_path.text(),
            sub_files,
            self.checkbox1.isChecked(),
            selected_mpls,
            cancel_event,
            subtitle_suffix=self._get_subtitle_suffix()
        )
        self._merge_worker.moveToThread(self._merge_thread)
        self._merge_thread.started.connect(self._merge_worker.run)
        self._merge_worker.progress.connect(self._on_exe_button_progress_value)
        self._merge_worker.label.connect(self._on_exe_button_progress_text)

        success = False

        def cleanup():
            self._current_cancel_event = None
            self._reset_exe_button()
            if hasattr(self, '_merge_thread') and self._merge_thread:
                t_wait = time.perf_counter()
                print('[ShutdownDebug] merge_thread(series).quit()')
                self._merge_thread.quit()
                self._merge_thread.wait()
                print(f"[ShutdownDebug] merge_thread(series).wait() done in {(time.perf_counter() - t_wait) * 1000:.1f} ms")
                self._merge_thread.deleteLater()
                self._merge_thread = None
            if hasattr(self, '_merge_worker') and self._merge_worker:
                self._merge_worker.deleteLater()
                self._merge_worker = None
            self.altered = False

        def on_finished():
            nonlocal success
            success = True
            cleanup()
            if not silent_mode:
                self._show_bottom_message("Subtitle generation completed!", 10000)

        def on_canceled():
            cleanup()

        def on_failed(message: str):
            cleanup()
            if not silent_mode:
                self._show_error_dialog(message)

        self._merge_worker.finished.connect(on_finished)
        self._merge_worker.canceled.connect(on_canceled)
        self._merge_worker.failed.connect(on_failed)
        self._merge_thread.start()
        if silent_mode:
            loop = QEventLoop()

            def quit_loop():
                if loop.isRunning():
                    loop.quit()

            self._merge_worker.finished.connect(quit_loop)
            self._merge_worker.canceled.connect(quit_loop)
            self._merge_worker.failed.connect(quit_loop)
            loop.exec()
        return success

    def init_encode_box(self):
        self._x265_preset_params = {
            'Fast': '--preset fast --crf 20 --aq-mode 2 --bframes 8 --ref 4 --me 2 --subme 2',
            'Balanced': '--preset slower --crf 18 --aq-mode 3 --bframes 8 --ref 5 --me 3 --subme 4',
            'High Quality': '--preset slower --crf 16 --aq-mode 3 --bframes 8 --psy-rd 2.0 --psy-rdoq 1.0 --deblock -1:-1 --rc-lookahead 60 --ref 6 --subme 5',
            'Extreme': '--preset placebo --crf 14 --pme --pmode --aq-mode 3 --aq-strength 1.0 --cbqpoffs -2 --crqpoffs -2 --bframes 12 --b-adapt 2 --ref 6 --rc-lookahead 120 --lookahead-threads 0 --psy-rd 2.5 --psy-rdoq 2.0 --rdoq-level 2 --deblock -2:-2 --qcomp 0.65 --merange 57 --no-sao --no-strong-intra-smoothing',
            'Custom': ''
        }
        self._x264_preset_params = {
            'Fast': '--preset fast --crf 20 --profile high --level 4.1 --bframes 4 --ref 4',
            'Balanced': '--preset medium --crf 18 --profile high --level 4.1 --bframes 6 --ref 5 --deblock -1:-1',
            'High Quality': '--preset slow --crf 16 --profile high --level 4.1 --bframes 8 --ref 6 --deblock -1:-1 --aq-mode 2',
            'Extreme': '--preset veryslow --crf 14 --profile high --level 4.1 --bframes 10 --ref 8 --aq-mode 2 --trellis 2',
            'Custom': ''
        }
        self._encode_preset_params = dict(self._x265_preset_params)
        self._encode_setting_updating = False

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.encode_box.setLayout(layout)

        tools_row = QWidget(self.encode_box)
        tools_layout = QHBoxLayout()
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(4)
        tools_row.setLayout(tools_layout)

        tools_layout.addWidget(QLabel('vspipe:', tools_row))
        self.vspipe_mode_combo = QComboBox(tools_row)
        self.vspipe_mode_combo.addItems(['Built-in', 'System'])
        tools_layout.addWidget(self.vspipe_mode_combo)

        self.x265_mode_label = QLabel('x265:', tools_row)
        tools_layout.addWidget(self.x265_mode_label)
        self.x265_mode_combo = QComboBox(tools_row)
        self.x265_mode_combo.addItems(['Built-in', 'System'])
        tools_layout.addWidget(self.x265_mode_combo)

        is_pyinstaller_bundle = bool(getattr(sys, 'frozen', False)) and hasattr(sys, '_MEIPASS')
        if not is_pyinstaller_bundle:
            self.vspipe_mode_combo.setCurrentText('System')
            self.vspipe_mode_combo.setEnabled(False)
            self.x265_mode_combo.setCurrentText('System')
            self.x265_mode_combo.setEnabled(False)
        elif is_docker():
            self.vspipe_mode_combo.setCurrentText('System')
            self.x265_mode_combo.setCurrentText('System')

        self.x265_params_label = QLabel(self.t('x265 Params:'), tools_row)
        tools_layout.addWidget(self.x265_params_label)
        self.x265_preset_combo = QComboBox(tools_row)
        self.x265_preset_combo.addItem('Fast', 'Fast')
        self.x265_preset_combo.addItem('Balanced', 'Balanced')
        self.x265_preset_combo.addItem('High Quality', 'High Quality')
        self.x265_preset_combo.addItem('Extreme', 'Extreme')
        self.x265_preset_combo.addItem('Custom', 'Custom')
        idx_balanced = self.x265_preset_combo.findData('Balanced')
        self.x265_preset_combo.setCurrentIndex(0 if idx_balanced < 0 else idx_balanced)
        self._adjust_combo_width_to_contents(self.x265_preset_combo)
        tools_layout.addWidget(self.x265_preset_combo)

        tools_layout.addStretch(1)
        self.use_getnative_checkbox = QCheckBox(self.t('Use getnative for native resolution'), tools_row)
        self.use_getnative_checkbox.setChecked(True)
        tools_layout.addWidget(self.use_getnative_checkbox)
        self.use_bluray_compat_params_checkbox = QCheckBox(self.t('Use Blu-ray compatible params'), tools_row)
        self.use_bluray_compat_params_checkbox.setChecked(False)
        tools_layout.addWidget(self.use_bluray_compat_params_checkbox)
        layout.addWidget(tools_row)

        self.x265_params_edit = QPlainTextEdit(self.encode_box)
        self.x265_params_edit.setFixedHeight(46)
        self.x265_params_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.x265_params_edit)

        def set_params_for_preset(preset: str):
            params = self._encode_preset_params.get(preset, '')
            self._encode_setting_updating = True
            try:
                self.x265_params_edit.setPlainText(params)
            finally:
                self._encode_setting_updating = False

        def on_preset_changed():
            preset = str(self.x265_preset_combo.currentData() or self.x265_preset_combo.currentText() or '')
            if preset == 'Custom':
                return
            set_params_for_preset(preset)

        def on_params_edited():
            if self._encode_setting_updating:
                return
            if str(self.x265_preset_combo.currentData() or '') != 'Custom':
                idx_custom = self.x265_preset_combo.findData('Custom')
                if idx_custom >= 0:
                    self.x265_preset_combo.setCurrentIndex(idx_custom)

        self.x265_preset_combo.currentIndexChanged.connect(on_preset_changed)
        self.x265_params_edit.textChanged.connect(on_params_edited)
        set_params_for_preset(str(self.x265_preset_combo.currentData() or 'Balanced'))

        sub_pack_row = QWidget(self.encode_box)
        sub_pack_layout = QHBoxLayout()
        sub_pack_layout.setContentsMargins(0, 0, 0, 0)
        sub_pack_layout.setSpacing(4)
        sub_pack_row.setLayout(sub_pack_layout)

        sub_pack_layout.addWidget(QLabel('Subtitle Packaging:', sub_pack_row))
        self.sub_pack_external_radio = QRadioButton('External', sub_pack_row)
        self.sub_pack_soft_radio = QRadioButton('Softsub', sub_pack_row)
        self.sub_pack_hard_radio = QRadioButton('Hardsub', sub_pack_row)
        self.sub_pack_external_radio.setChecked(True)

        sub_pack_layout.addWidget(self.sub_pack_external_radio)
        sub_pack_layout.addWidget(self.sub_pack_soft_radio)
        sub_pack_layout.addWidget(self.sub_pack_hard_radio)
        sub_pack_layout.addStretch(1)
        layout.addWidget(sub_pack_row)

        sub_pack_group = QButtonGroup(sub_pack_row)
        sub_pack_group.addButton(self.sub_pack_external_radio)
        sub_pack_group.addButton(self.sub_pack_soft_radio)
        sub_pack_group.addButton(self.sub_pack_hard_radio)
        self._sub_pack_group = sub_pack_group
        self._sub_pack_row = sub_pack_row

        def on_sub_pack_changed():
            if self.get_selected_function_id() != 4:
                return
            if not self.subtitle_folder_path.text().strip():
                return
            self.set_vpy_hardsub_enabled(self.sub_pack_hard_radio.isChecked())

        self.sub_pack_external_radio.toggled.connect(on_sub_pack_changed)
        self.sub_pack_soft_radio.toggled.connect(on_sub_pack_changed)
        self.sub_pack_hard_radio.toggled.connect(on_sub_pack_changed)

        def update_sub_pack_enabled_state():
            enabled = self.get_selected_function_id() == 4 and bool(self.subtitle_folder_path.text().strip())
            self._sub_pack_row.setEnabled(enabled)
            if not enabled:
                self.sub_pack_external_radio.setChecked(True)
                self.set_vpy_hardsub_enabled(False)

        self.subtitle_folder_path.textChanged.connect(lambda _=None: update_sub_pack_enabled_state())
        update_sub_pack_enabled_state()

    def main(self):
        if getattr(self, '_current_cancel_event', None) is not None:
            self._current_cancel_event.set()
            self.exe_button.setEnabled(False)
            self._update_exe_button_progress(text='Canceling...')
            return

        function_id = self.get_selected_function_id()
        if function_id == 1:
            self.generate_subtitle()
        if function_id == 2:
            self.add_chapters()
        if function_id == 3:
            self.remux_episodes()
        if function_id == 4:
            self.encode_bluray()
        if function_id == 5:
            QMessageBox.information(self, " ", self.t("Blu-ray DIY is not implemented yet"))

    def on_button_click(self, mpls_path: str, is_main_at_build: bool = True, bdmv_index: int = 0):
        is_main = self._is_mpls_currently_main(mpls_path)

        class ChapterWindow(QDialog):
            def __init__(this):
                super(ChapterWindow, this).__init__()
                this.setWindowTitle(f"{self.t('Chapters')}: {mpls_path}")
                layout = QVBoxLayout()
                this.table_widget = QTableWidget()
                self._set_compact_table(this.table_widget, row_height=20, header_height=20)
                this.table_widget.setColumnCount(4)
                self._set_table_headers(this.table_widget, ['select', 'start', 'end', 'file'])
                chapter = Chapter(mpls_path)
                this.chapter = chapter
                mark_info = chapter.mark_info
                in_out_time = chapter.in_out_time
                mpls_duration = chapter.get_total_time()

                offs = []
                offset = 0
                chapter_to_m2ts = {}
                ch_idx = 1
                for ref_to_play_item_id, mark_timestamps in mark_info.items():
                    m2ts = in_out_time[ref_to_play_item_id][0] + '.m2ts'
                    for mark_timestamp in mark_timestamps:
                        off = offset + (mark_timestamp - in_out_time[ref_to_play_item_id][1]) / 45000
                        if mpls_duration - off >= 0.001:
                            offs.append(off)
                            chapter_to_m2ts[ch_idx] = m2ts
                            ch_idx += 1
                    offset += (in_out_time[ref_to_play_item_id][2] - in_out_time[ref_to_play_item_id][1]) / 45000

                this.chapter_to_m2ts = chapter_to_m2ts
                this.table_widget.setRowCount(len(offs))

                # Get saved checkbox states for this mpls_path
                saved_states = self._chapter_checkbox_states.get(mpls_path, [])

                for i, off in enumerate(offs):
                    item = QTableWidgetItem(f'Chapter {i + 1:02d} - {get_time_str(off)}')
                    this.table_widget.setItem(i, 1, item)
                    item = QTableWidgetItem()
                    if is_main:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                        # Restore saved state or default to Checked
                        if i < len(saved_states):
                            item.setCheckState(Qt.CheckState.Checked if saved_states[i] else Qt.CheckState.Unchecked)
                        else:
                            item.setCheckState(Qt.CheckState.Checked)
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Unchecked)
                    this.table_widget.setItem(i, 0, item)
                    this.table_widget.setItem(i, 3, QTableWidgetItem(chapter_to_m2ts.get(i + 1, '')))
                for i in range(len(offs) - 1):
                    this.table_widget.setItem(i, 2,
                                              QTableWidgetItem(f'Chapter {i + 2:02d} - {get_time_str(offs[i + 1])}'))
                if offs:
                    this.table_widget.setItem(len(offs) - 1, 2,
                                              QTableWidgetItem(f'Ending - {get_time_str(mpls_duration)}'))
                this.table_widget.resizeColumnsToContents()
                layout.addWidget(this.table_widget)

                # Add OK and Cancel buttons
                button_layout = QHBoxLayout()
                select_all_button = QPushButton(self.t('Select all'))
                ok_button = QPushButton(self.t('OK') if is_main else self.t('Close'))
                cancel_button = QPushButton(self.t('Cancel'))
                select_all_button.setEnabled(bool(is_main))
                select_all_button.clicked.connect(this.select_all_chapters)
                button_layout.addWidget(select_all_button)
                ok_button.clicked.connect(this.accept)
                cancel_button.clicked.connect(this.reject)
                if not is_main:
                    cancel_button.setVisible(False)
                button_layout.addWidget(ok_button)
                button_layout.addWidget(cancel_button)
                layout.addLayout(button_layout)

                this.setLayout(layout)
                this.setMinimumWidth(500)
                height = len(offs) * 30 + 100
                height = 1000 if height > 1000 else height
                if len(offs) > 1:
                    this.setMinimumHeight(height)

            def get_unchecked_segments(this):
                unchecked_rows = []
                for row in range(this.table_widget.rowCount()):
                    item = this.table_widget.item(row, 0)
                    if item and item.checkState() == Qt.CheckState.Unchecked:
                        unchecked_rows.append(row)
                # Find consecutive segments
                segments = []
                if unchecked_rows:
                    start = unchecked_rows[0]
                    prev = unchecked_rows[0]
                    for r in unchecked_rows[1:]:
                        if r == prev + 1:
                            prev = r
                        else:
                            segments.append((start, prev))
                            start = r
                            prev = r
                    segments.append((start, prev))
                return segments

            def select_all_chapters(this):
                for row in range(this.table_widget.rowCount()):
                    item = this.table_widget.item(row, 0)
                    if not item:
                        continue
                    if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                        item.setCheckState(Qt.CheckState.Checked)

        chapter_window = ChapterWindow()
        result = chapter_window.exec()
        if result == QDialog.DialogCode.Accepted:
            if not self._is_mpls_currently_main(mpls_path):
                return
            # Save checkbox states for this mpls_path
            states = []
            for row in range(chapter_window.table_widget.rowCount()):
                item = chapter_window.table_widget.item(row, 0)
                if item:
                    states.append(item.checkState() == Qt.CheckState.Checked)
            self._chapter_checkbox_states[mpls_path] = states
            progress = QProgressDialog(self.t('Applying chapter selection...'), '', 0, 0, self)
            progress.setCancelButton(None)
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumWidth(420)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.show()
            QCoreApplication.processEvents()
            try:
                if self.get_selected_function_id() in (3, 4):
                    progress.setLabelText(self.t('Regenerating configuration...'))
                    QCoreApplication.processEvents()
                    cfg = self._generate_configuration_from_ui_inputs()
                    self.on_configuration(cfg, update_sp_table=False)
            except Exception:
                self._show_error_dialog(traceback.format_exc())
            try:
                if self.get_selected_function_id() in (3, 4):
                    progress.setLabelText(self.t('Refreshing SP table...'))
                    QCoreApplication.processEvents()
                    self._sync_chapter_checkbox_sp_for_mpls(mpls_path, bdmv_index)
                    self._recompute_sp_output_names(only_bdmv_index=bdmv_index)
            except Exception:
                self._show_error_dialog(traceback.format_exc())
            finally:
                progress.close()
                progress.deleteLater()

    def on_button_main(self, mpls_path: str, clicked_checked: Optional[bool] = None):
        def has_subtitle_in_table2() -> bool:
            return self._has_subtitle_in_table2()

        subtitle = has_subtitle_in_table2()
        applied_checked: Optional[bool] = None
        for bdmv_index in range(self.table1.rowCount()):
            root_item = self.table1.item(bdmv_index, 0)
            root = root_item.text().strip() if root_item and root_item.text() else ''
            if not root:
                continue
            info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
            if not isinstance(info, QTableWidget):
                continue
            for mpls_index in range(info.rowCount()):
                item = info.item(mpls_index, 0)
                mpls_file = item.text().strip() if item and item.text() else ''
                if not mpls_file:
                    continue
                row_mpls = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_file))
                if row_mpls != os.path.normpath(mpls_path):
                    continue
                main_btn = info.cellWidget(mpls_index, 3)
                checked = bool(clicked_checked) if clicked_checked is not None else bool(
                    isinstance(main_btn, QToolButton) and main_btn.isChecked())
                if isinstance(main_btn, QToolButton):
                    main_btn.setChecked(checked)
                applied_checked = bool(checked)
                play_btn = info.cellWidget(mpls_index, 4)
                if play_btn:
                    play_btn.setProperty('action', 'preview' if (checked and subtitle) else 'play')
                    play_btn.setText(self.t('preview') if (checked and subtitle) else self.t('play'))
                if self.get_selected_function_id() in (3, 4, 5) and info.columnCount() > 5:
                    btn_tracks = QToolButton()
                    btn_tracks.setText(self.t('edit tracks'))
                    can_edit_tracks = True
                    if self.get_selected_function_id() == 5:
                        is_simple_diy = bool(getattr(self, 'diy_simple_radio', None) and self.diy_simple_radio.isChecked())
                        can_edit_tracks = is_simple_diy
                    if can_edit_tracks:
                        btn_tracks.clicked.connect(partial(self.on_edit_tracks_from_mpls, row_mpls))
                    else:
                        btn_tracks.setEnabled(False)
                    info.setCellWidget(mpls_index, 5, btn_tracks)
                break
        if self.get_selected_function_id() in (3, 4, 5):
            self._refresh_track_selection_config_for_selected_main()
            try:
                self._refresh_table1_remux_cmds()
            except Exception:
                pass
        if self.get_selected_function_id() in (3, 4, 5) and self._is_movie_mode():
            self._refresh_movie_table2()
        else:
            self._resync_episode_tables_from_main_mpls_selection()

    def on_button_play(self, mpls_path: str, btn: QToolButton):
        def _select_subtitle_file_for_mpls(mpls_path: str) -> Optional[str]:
            try:
                mpls_name = mpls_path[:-5]
                folder = os.path.dirname(mpls_name)
                base = os.path.basename(mpls_name)
                if not folder or not os.path.isdir(folder):
                    return None
                candidates = []
                for f in os.listdir(folder):
                    if not (f.endswith('.ass') or f.endswith('.srt') or f.endswith('.ssa')):
                        continue
                    if not f.startswith(base):
                        continue
                    candidates.append(os.path.normpath(os.path.join(folder, f)))
                candidates.sort()
                if not candidates:
                    return None
                if len(candidates) == 1:
                    return candidates[0]
                display = [os.path.basename(p) for p in candidates]
                item, ok = QInputDialog.getItem(
                    self,
                    self.t("Select subtitle file"),
                    self.t("Multiple subtitle files detected, choose one for preview:"),
                    display,
                    0,
                    False
                )
                if not ok or not item:
                    return None
                try:
                    idx = display.index(str(item))
                except Exception:
                    return None
                return candidates[idx]
            except Exception:
                return None

        def mpv_play_mpls(mpls_path, mpv_path):
            sub_file = _select_subtitle_file_for_mpls(mpls_path)
            if sub_file:
                subprocess.Popen(
                    f'"{mpv_path}" --sub-file="{sub_file}" bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                    shell=True).wait()
            else:
                subprocess.Popen(f'"{mpv_path}" bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                                 shell=True).wait()
            return

        action = btn.property('action') or ''
        is_preview = (action == 'preview') or (btn.text() in ('preview', self.t('preview')))
        if is_preview and self.altered:
            # Generate subtitles only when no subtitle file exists.
            mpls_name = mpls_path[:-5]
            has_subtitle = (os.path.exists(mpls_name + '.ass') or
                            os.path.exists(mpls_name + '.srt') or
                            os.path.exists(mpls_name + '.ssa'))
            if not has_subtitle:
                success = self.generate_subtitle(silent_mode=True)
                if success:
                    # Re-check subtitle existence after generation.
                    has_subtitle = (os.path.exists(mpls_name + '.ass') or
                                    os.path.exists(mpls_name + '.srt') or
                                    os.path.exists(mpls_name + '.ssa'))
            if not has_subtitle:
                # Still allow playback even if subtitle generation failed.
                QMessageBox.information(self, "Prompt", "Subtitle file does not exist; playback will continue without subtitles")
        elif is_preview:
            # Check whether subtitle file exists.
            mpls_name = mpls_path[:-5]
            has_subtitle = (os.path.exists(mpls_name + '.ass') or
                            os.path.exists(mpls_name + '.srt') or
                            os.path.exists(mpls_name + '.ssa'))
            if not has_subtitle:
                QMessageBox.information(self, "Prompt", "Subtitle file does not exist; playback will continue without subtitles")
        if sys.platform != 'linux':
            if sys.platform == 'win32':
                mp4_exe_path = get_mpv_safe_path(".mp4")
                if mp4_exe_path:
                    if mp4_exe_path.endswith('mpv.exe'):
                        mpv_play_mpls(mpls_path, mp4_exe_path)
                        return
            os.startfile(mpls_path)
        else:
            in_docker = False
            try:
                if os.path.exists('/.dockerenv'):
                    in_docker = True
            except Exception:
                pass
            if not in_docker:
                try:
                    with open('/proc/1/cgroup', 'r', encoding='utf-8', errors='ignore') as fp:
                        cg = fp.read()
                    if ('docker' in cg) or ('kubepods' in cg) or ('containerd' in cg):
                        in_docker = True
                except Exception:
                    pass
            if in_docker:
                try:
                    my_env = os.environ.copy()
                    my_env["LD_LIBRARY_PATH"] = "/usr/local/lib/mpv-bundle:" + my_env.get("LD_LIBRARY_PATH", "")
                    sub_file = _select_subtitle_file_for_mpls(mpls_path)
                    if sub_file:
                        subprocess.Popen(
                            f'mpv --vo=x11 --profile=sw-fast --hwdec=no --framedrop=vo --sub-file="{sub_file}" bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                            shell=True, env=my_env).wait()
                    else:
                        subprocess.Popen(
                            f'mpv --vo=x11 --profile=sw-fast --hwdec=no --framedrop=vo bd://mpls/{mpls_path[-10:-5]} --bluray-device="{mpls_path[:-25]}"',
                            shell=True, env=my_env).wait()
                    return
                except Exception:
                    pass
            try:
                output = subprocess.check_output(["xdg-mime", "query", "default", "x-content/video-bluray"])
                desktop_file = output.decode('utf-8').strip()
                if not desktop_file:
                    output = subprocess.check_output(["xdg-mime", "query", "default", "video/mp4"])
                    desktop_file = output.decode('utf-8').strip()
                # Enable Blu-ray support in Linux mpv build by running in source directory:
                # echo "--enable-libbluray" > ffmpeg_options
                # and
                # echo "-Dlibbluray=enabled" > mpv_options
                if 'mpv' in desktop_file:
                    mpv_play_mpls(mpls_path, 'mpv')
            except:
                pass
            subprocess.run(['xdg-open', mpls_path])

    def on_subtitle_drop(self):
        try:
            if self.get_selected_function_id() in (3, 4, 5) and self._is_movie_mode():
                self._refresh_movie_table2()
                return
            if self.get_selected_function_id() in (3, 4, 5):
                sub_files = [self.table2.item(sub_index, 0).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0)]
            else:
                sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).checkState() == 2]
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
        except Exception as e:
            print(f'{translate_text("Subtitle drag-in failed: ")}{str(e)}')
            print_exc_terminal()
            # Log error information without showing a popup dialog.
            print(translate_text('Subtitle drag-in failed, please check the subtitle files and Blu-ray path'))

    def on_subtitle_folder_path_change(self):
        raw = self.subtitle_folder_path.text()
        folder = self._normalize_path_input(raw)
        if raw.strip().startswith('file://') and folder and folder != raw.strip():
            try:
                self.subtitle_folder_path.blockSignals(True)
                self.subtitle_folder_path.setText(folder)
            finally:
                self.subtitle_folder_path.blockSignals(False)
        self._pending_subtitle_folder = folder
        self._update_language_combo_enabled_state()
        if self.get_selected_function_id() == 5 and bool(
                getattr(self, 'diy_simple_radio', None) and self.diy_simple_radio.isChecked()):
            # Simple DIY subtitle settings are independent from episode configuration.
            self._save_simple_diy_subtitle_config()
            return
        if hasattr(self, '_subtitle_scan_cancel_event') and self._subtitle_scan_cancel_event:
            self._subtitle_scan_cancel_event.set()
        if not folder:
            self._subtitle_scan_debounce.stop()
            return
        self._subtitle_scan_debounce.stop()
        self._subtitle_scan_debounce.start()

    def on_subtitle_menu(self, pos: QPoint):
        row_indexes = [i.row() for i in self.table2.selectionModel().selection().indexes()]
        column_indexes = [i.column() for i in self.table2.selectionModel().selection().indexes()]
        if any(column_index == 1 for column_index in column_indexes):
            menu = QMenu()
            item = menu.addAction('edit')
            screen_pos = self.table2.mapToGlobal(pos)
            action = menu.exec(screen_pos)
            if action == item:
                for i, row_index in enumerate(row_indexes):
                    if column_indexes[i] == 1:
                        self.edit_subtitle(self.table2.item(row_index, 1).text())

    def on_subtitle_select(self):
        sub_check_state = [self.table2.item(sub_index, 0).checkState().value for sub_index in
                           range(self.table2.rowCount())]
        if sub_check_state != self.sub_check_state:
            self.sub_check_state = sub_check_state
            if self.get_selected_function_id() == 1 and self._is_movie_mode():
                return
            sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                         if self.sub_check_state[sub_index] == 2]
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
        for sub_index, check_state in enumerate(self.sub_check_state):
            if check_state != 2:
                bdmv_col = SUBTITLE_LABELS.index('bdmv_index')
                chapter_col = SUBTITLE_LABELS.index('chapter_index')
                offset_col = SUBTITLE_LABELS.index('offset')
                ep_duration_col = SUBTITLE_LABELS.index('ep_duration')
                self.table2.setItem(sub_index, bdmv_col, None)
                self.table2.setItem(sub_index, ep_duration_col, None)
                self.table2.setCellWidget(sub_index, chapter_col, None)
                self.table2.setItem(sub_index, offset_col, None)

    def on_subtitle_table_sorted(self, logicalIndex: int, order: Qt.SortOrder):
        # Handle path column sorting based on which function is selected
        # For radio2 (mkv chapters), path is at index 0 (MKV_LABELS) - no configuration rebuild needed
        # For radio3/4, path is at index 0 (REMUX_LABELS / ENCODE_LABELS)
        # For others, path is at index 1 (SUBTITLE_LABELS)
        if self.get_selected_function_id() == 2:
            if logicalIndex != 0:
                return
            # For radio2, just update the duration column after sorting
            for i in range(self.table2.rowCount()):
                item = self.table2.item(i, 0)
                if item and os.path.exists(item.text()):
                    self.table2.setItem(i, 1, QTableWidgetItem(get_time_str(MKV(item.text()).get_duration())))
            return
        else:
            sort_col = 0 if (self.get_selected_function_id() in (3, 4, 5)) else 1
            if logicalIndex != sort_col:
                return

        if self.table2.rowCount() == 0:
            return
        try:
            # update row-specific computed columns
            if self.get_selected_function_id() == 1:
                if self._is_movie_mode():
                    return
                for i in range(self.table2.rowCount()):
                    item = self.table2.item(i, 1)
                    if item and os.path.exists(item.text()):
                        self.table2.setItem(i, SUBTITLE_LABELS.index('sub_duration'),
                                            QTableWidgetItem(get_time_str(Subtitle(item.text()).max_end_time())))

            if self.get_selected_function_id() in (3, 4, 5) and self._is_movie_mode():
                return

            # Rebuild configuration after sorting
            if self.get_selected_function_id() in (3, 4, 5):
                sub_files = [self.table2.item(sub_index, 0).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).text()]
            else:
                sub_files = [self.table2.item(sub_index, 1).text() for sub_index in range(self.table2.rowCount())
                             if self.table2.item(sub_index, 0) and self.table2.item(sub_index, 0).checkState() == 2]
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

    def open_file_path(self, path: str):
        path = self._normalize_path_input(path)
        if not path:
            QMessageBox.information(self, " ", "File path is empty")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "Open File Failed", f"File does not exist:\n{path}")
            return
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            QMessageBox.warning(self, "Open File Failed", f"Cannot open file:\n{path}\n\n{e}")

    def open_folder_path(self, path: str):
        path = self._normalize_path_input(path)
        if not path:
            QMessageBox.information(self, " ", "Folder path is empty")
            return

        normalized = path
        if os.path.isfile(normalized):
            normalized = os.path.normpath(os.path.dirname(normalized))

        if not os.path.isdir(normalized):
            QMessageBox.warning(self, "Open Folder Failed", f"Folder does not exist:\n{normalized}")
            return

        try:
            if sys.platform == 'win32':
                os.startfile(normalized)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', normalized])
            else:
                subprocess.Popen(['xdg-open', normalized])
        except Exception as e:
            QMessageBox.warning(self, "Open Folder Failed", f"Cannot open folder:\n{normalized}\n\n{e}")

    def select_bdmv_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("Select folder"))
        if folder:
            self.bdmv_folder_path.setText(os.path.normpath(folder))

    def select_output_folder(self):
        start = self.output_folder_path.text().strip() if hasattr(self, 'output_folder_path') else ''
        folder = QFileDialog.getExistingDirectory(self, self.t("Select Output Folder"), start)
        if folder:
            self.output_folder_path.setText(os.path.normpath(folder))

    def select_remux_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("Select folder"))
        if folder and hasattr(self, 'remux_folder_path'):
            self.remux_folder_path.setText(os.path.normpath(folder))

    def select_subtitle_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("Select folder"))
        if folder:
            self.subtitle_folder_path.setText(os.path.normpath(folder))
