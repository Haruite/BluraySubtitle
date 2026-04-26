"""Target module for scan/worker hook methods of `BluraySubtitleGUI`."""
import os
import threading
import time
from typing import Optional

from PyQt6.QtCore import QTimer, QThread, Qt
from PyQt6.QtWidgets import QProgressDialog, QProgressBar, QTableWidgetItem, QToolButton

from src.core import ENCODE_SP_LABELS, ENCODE_REMUX_LABELS, ENCODE_LABELS
from src.runtime.gui_runtime_classes.sp_table_scan_worker import SpTableScanWorker
from src.runtime.services import BluraySubtitle
from .gui_base import BluraySubtitleGuiBase


class ScanWorkerHooksMixin(BluraySubtitleGuiBase):
        def _update_exe_button_progress(self, value: Optional[int] = None, text: Optional[str] = None):
            if not hasattr(self, 'exe_button') or not self.exe_button:
                return
            if not hasattr(self, '_exe_button_default_text'):
                self._exe_button_default_text = self.exe_button.text()
            if value is not None:
                self._exe_button_progress_value = int(value)
            if text is not None:
                self._exe_button_progress_text = self.t(str(text))

            v = int(getattr(self, '_exe_button_progress_value', 0))
            t = str(getattr(self, '_exe_button_progress_text', '')).strip()
            ratio = max(0.0, min(1.0, v / 1000.0))
            stop1 = f"{ratio:.3f}"
            stop2 = f"{min(1.0, ratio + 0.001):.3f}"
            percent = ratio * 100

            cancel_suffix = self.t("(click to cancel)") if getattr(self, '_current_cancel_event',
                                                            None) is not None and t != self.t('Canceling...') else ""
            if t:
                self.exe_button.setText(f"{t}{cancel_suffix} {percent:.1f}%")
            else:
                self.exe_button.setText(f"{percent:.1f}%")
            self.exe_button.setStyleSheet(
                "QPushButton{"
                f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #AAAAAA,stop:{stop1} #AAAAAA,stop:{stop2} #CCCCCC,stop:1 #CCCCCC);"
                "color:white;border:none;border-radius:5px;padding:2px 6px;"
                "}"
                "QPushButton:disabled{color:white;}"
            )

        def _on_exe_button_progress_value(self, value: int):
            self._update_exe_button_progress(value=value)

        def _on_exe_button_progress_text(self, text: str):
            self._update_exe_button_progress(text=self.t(text))

        def _reset_exe_button(self):
            if not hasattr(self, 'exe_button') or not self.exe_button:
                return
            default_text = getattr(self, '_exe_button_default_text', None)
            if default_text:
                self.exe_button.setText(default_text)
            self.exe_button.setStyleSheet('')
            self.exe_button.setEnabled(True)

        def _show_bottom_message(self, text: str, duration_ms: int = 10000):
            if not hasattr(self, 'bottom_message_label') or not self.bottom_message_label:
                return

            self._bottom_message_text = self.t(text)
            self._bottom_message_remaining = duration_ms // 1000

            self.bottom_message_label.setText(f"{self._bottom_message_text} ({self._bottom_message_remaining}s)")
            self.bottom_message_label.setVisible(True)

            if not hasattr(self, '_bottom_message_timer') or not self._bottom_message_timer:
                self._bottom_message_timer = QTimer(self)
                self._bottom_message_timer.setInterval(1000)

                def update_countdown():
                    self._bottom_message_remaining -= 1
                    if self._bottom_message_remaining <= 0:
                        self.bottom_message_label.setVisible(False)
                        self.bottom_message_label.setText('')
                        self._bottom_message_timer.stop()
                    else:
                        self.bottom_message_label.setText(
                            f"{self._bottom_message_text} ({self._bottom_message_remaining}s)")

                self._bottom_message_timer.timeout.connect(update_countdown)

            self._bottom_message_timer.stop()
            self._bottom_message_timer.start()

        def _start_sp_table_scan(self):
            try:
                if hasattr(self, '_sp_scan_cancel_event') and isinstance(self._sp_scan_cancel_event, threading.Event):
                    self._sp_scan_cancel_event.set()
            except Exception:
                pass
            try:
                if hasattr(self, '_sp_scan_thread') and isinstance(self._sp_scan_thread,
                                                                   QThread) and self._sp_scan_thread.isRunning():
                    self._sp_scan_thread.quit()
                    self._sp_scan_thread.wait(200)
            except Exception:
                pass

            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
            rows: list[dict[str, object]] = []
            select_all = bool(
                getattr(self, 'select_all_tracks_checkbox', None) and self.select_all_tracks_checkbox.isChecked())
            for r in range(self.table3.rowCount()):
                try:
                    bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
                except Exception:
                    continue
                stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
                playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                mpls_file = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
                mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_file)) if playlist_dir and mpls_file else ''
                m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                m2ts_files = self._split_m2ts_files(m2ts_text)
                m2ts_files_unique = list(dict.fromkeys([os.path.basename(x) for x in m2ts_files if x]))
                m2ts_paths = [os.path.normpath(os.path.join(stream_dir, f)) for f in
                              m2ts_files_unique] if stream_dir else []
                entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': ','.join(m2ts_files),
                         'output_name': ''}
                sp_key = BluraySubtitle._sp_track_key_from_entry(entry)
                sel_item = self.table3.item(r, ENCODE_SP_LABELS.index('select'))
                force_disabled = bool((not sel_item) or (not (sel_item.flags() & Qt.ItemFlag.ItemIsEnabled)))
                # Skip truly empty rows to avoid unnecessary scan/progress popup.
                if (not force_disabled) and (not mpls_path) and (not m2ts_paths):
                    continue
                rows.append({'row': r, 'm2ts_paths': m2ts_paths, 'mpls_path': mpls_path, 'sp_key': sp_key,
                             'force_disabled': force_disabled, 'select_all': select_all})

            if not rows:
                self._sp_scan_in_progress = False
                self._sp_scan_progress_dialog = None
                self._sp_scan_progress_bar = None
                self._sp_scan_progress_show_timer = None
                self._sp_scan_progress_rows_seen = set()
                self._sp_scan_progress_total = 0
                self._sp_scan_progress_done = 0
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

            cancel_event = threading.Event()
            self._sp_scan_cancel_event = cancel_event
            self._sp_scan_progress_dialog = progress_dialog
            self._sp_scan_progress_bar = bar
            self._sp_scan_progress_show_timer = show_timer
            self._sp_scan_progress_total = max(1, len(rows))
            self._sp_scan_progress_done = 0
            self._sp_scan_progress_rows_seen = set()
            thread = QThread(self)
            worker = SpTableScanWorker(rows, cancel_event)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.result.connect(self._on_sp_table_scan_result)
            self._sp_scan_in_progress = True

            def cleanup():
                try:
                    self._sp_scan_in_progress = False
                except Exception:
                    pass
                try:
                    t = getattr(self, '_sp_scan_progress_show_timer', None)
                    if isinstance(t, QTimer):
                        t.stop()
                except Exception:
                    pass
                try:
                    dlg = getattr(self, '_sp_scan_progress_dialog', None)
                    if isinstance(dlg, QProgressDialog):
                        dlg.close()
                        dlg.deleteLater()
                except Exception:
                    pass
                self._sp_scan_progress_dialog = None
                self._sp_scan_progress_bar = None
                self._sp_scan_progress_show_timer = None
                self._sp_scan_progress_rows_seen = set()
                self._sp_scan_progress_total = 0
                self._sp_scan_progress_done = 0
                try:
                    worker.deleteLater()
                except Exception:
                    pass
                try:
                    thread.quit()
                    thread.wait(200)
                    thread.deleteLater()
                except Exception:
                    pass

            worker.finished.connect(cleanup)
            worker.finished.connect(self._on_sp_table_scan_finished)
            worker.canceled.connect(cleanup)
            worker.failed.connect(lambda msg: (cleanup(), self._show_error_dialog(msg)))
            self._sp_scan_thread = thread
            self._sp_scan_worker = worker
            thread.start()

        def _on_sp_table_scan_result(self, row: int, disabled: bool, special: str, payload: object):
            try:
                sel_col = ENCODE_SP_LABELS.index('select')
                type_col = ENCODE_SP_LABELS.index('m2ts_type')
                out_col = ENCODE_SP_LABELS.index('output_name')
                tracks_col = ENCODE_SP_LABELS.index('tracks')
                play_col = ENCODE_SP_LABELS.index('play') if 'play' in ENCODE_SP_LABELS else -1
            except Exception:
                return
            if row < 0 or row >= self.table3.rowCount():
                return
            select_override = None
            sp_key = ''
            tracks_payload = {}
            m2ts_type = ''
            allow_tracks_when_disabled = False
            if isinstance(payload, dict):
                select_override = payload.get('select_override')
                sp_key = str(payload.get('sp_key') or '').strip()
                tracks_payload = payload.get('tracks') or {}
                m2ts_type = str(payload.get('m2ts_type') or '').strip()
                allow_tracks_when_disabled = bool(payload.get('allow_tracks_when_disabled') or False)
            try:
                self._updating_sp_table = True
                sel_item = self.table3.item(row, sel_col)
                if not sel_item:
                    sel_item = QTableWidgetItem('')
                    self.table3.setItem(row, sel_col, sel_item)
                user_flag = sel_item.data(Qt.ItemDataRole.UserRole)
                if disabled:
                    sel_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                    sel_item.setCheckState(Qt.CheckState.Unchecked)
                    sel_item.setData(Qt.ItemDataRole.UserRole, 'auto')
                else:
                    sel_item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                    if bool(select_override) and user_flag != 'user':
                        sel_item.setCheckState(Qt.CheckState.Checked)
                out_item = self.table3.item(row, out_col)
                if out_item:
                    out_item.setData(Qt.ItemDataRole.UserRole + 2, str(special or ''))
                type_item = self.table3.item(row, type_col)
                if not type_item:
                    type_item = QTableWidgetItem('')
                    self.table3.setItem(row, type_col, type_item)
                type_item.setText(m2ts_type)
                btn_tracks = self.table3.cellWidget(row, tracks_col)
                if isinstance(btn_tracks, QToolButton):
                    btn_tracks.setEnabled((not disabled) or allow_tracks_when_disabled)
                if play_col >= 0:
                    btn_play = self.table3.cellWidget(row, play_col)
                    if isinstance(btn_play, QToolButton):
                        btn_play.setEnabled(not disabled)
                try:
                    select_all = bool(
                        getattr(self, 'select_all_tracks_checkbox', None) and self.select_all_tracks_checkbox.isChecked())
                    if sp_key and isinstance(tracks_payload, dict) and tracks_payload and (not disabled):
                        cfg = getattr(self, '_track_selection_config', None)
                        if not isinstance(cfg, dict):
                            self._track_selection_config = {}
                            cfg = self._track_selection_config
                        if select_all:
                            cfg[sp_key] = {'audio': list(tracks_payload.get('audio') or []),
                                           'subtitle': list(tracks_payload.get('subtitle') or [])}
                        elif sp_key not in cfg:
                            bdmv_item = self.table3.item(row, ENCODE_SP_LABELS.index('bdmv_index'))
                            mpls_item = self.table3.item(row, ENCODE_SP_LABELS.index('mpls_file'))
                            try:
                                bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text() else 0
                            except Exception:
                                bdmv_index = 0
                            mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
                            self._inherit_main_track_config_for_sp_key(bdmv_index, mpls_file, sp_key)
                            if sp_key not in cfg:
                                cfg[sp_key] = {'audio': list(tracks_payload.get('audio') or []),
                                               'subtitle': list(tracks_payload.get('subtitle') or [])}
                except Exception:
                    pass
            finally:
                self._updating_sp_table = False
            try:
                seen = getattr(self, '_sp_scan_progress_rows_seen', None)
                if isinstance(seen, set):
                    seen.add(int(row))
                    done = len(seen)
                    self._sp_scan_progress_done = done
                    total = max(1, int(getattr(self, '_sp_scan_progress_total', 1) or 1))
                    bar = getattr(self, '_sp_scan_progress_bar', None)
                    if isinstance(bar, QProgressBar):
                        bar.setValue(int(done / total * 1000))
            except Exception:
                pass
            if not bool(getattr(self, '_sp_scan_in_progress', False)):
                try:
                    self._recompute_sp_output_names()
                except Exception:
                    pass

        def ensure_encode_row_widgets(self, row_index: int):
            if self.get_selected_function_id() != 4:
                return
            labels = ENCODE_REMUX_LABELS if getattr(self, '_encode_input_mode', 'bdmv') == 'remux' else ENCODE_LABELS
            vpy_col = labels.index('vpy_path')
            edit_col = labels.index('edit_vpy')
            preview_col = labels.index('preview_script')

            if not self.table2.cellWidget(row_index, vpy_col):
                self.table2.setCellWidget(row_index, vpy_col, self.create_vpy_path_widget(parent=self.table2))

            if not self.table2.cellWidget(row_index, edit_col):
                btn = QToolButton(self.table2)
                btn.setText(self.t('edit'))
                btn.clicked.connect(self.on_edit_vpy_clicked)
                self.table2.setCellWidget(row_index, edit_col, btn)

            if not self.table2.cellWidget(row_index, preview_col):
                btn = QToolButton(self.table2)
                btn.setText(self.t('preview'))
                btn.clicked.connect(self.on_preview_script_clicked)
                self.table2.setCellWidget(row_index, preview_col, btn)
