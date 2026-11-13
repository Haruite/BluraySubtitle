"""Asynchronous SP-table scan lifecycle for ``BluraySubtitleGUI``.

``refresh_sp_table`` first builds a complete synchronous table3 and then calls
``_start_sp_table_scan`` once. The worker reads the captured row paths without
touching widgets and emits classification and default track-selection results.
The GUI thread applies those results row by row. Only after every result is
applied does ``_on_sp_table_scan_finished`` recompute dependent output names and
mark the scan ready. QThread cleanup happens last and may resume one Remux or
BDMV Encode click that ``main`` queued while the scan was active.
"""
import os
import threading
from typing import Optional

from PyQt6.QtCore import QTimer, QThread, Qt
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QToolButton

from src.core import ENCODE_SP_LABELS
from src.runtime.gui_runtime_classes.custom_table_widget import READ_ONLY_HINT_ROLE
from src.runtime.gui_runtime_classes.scan_progress_dialog import ScanProgressDialog
from src.runtime.gui_runtime_classes.sp_table_items import SP_STANDALONE_TRACKS_ROLE, SpSelectionItem
from src.runtime.gui_runtime_classes.sp_table_scan_worker import SpTableScanWorker
from src.runtime.sp import SpEntry
from .gui_base import BluraySubtitleGuiBase
from .theme_and_i18n import execution_button_stylesheet


class ScanWorkerHooksMixin(BluraySubtitleGuiBase):
    def _dismiss_sp_scan_progress_ui(self):
        """Close SP table scan progress UI and clear refs (safe when restarting or early-exiting a scan)."""
        dialog = getattr(self, '_sp_scan_progress_dialog', None)
        if dialog is not None and dialog is not getattr(self, '_bdmv_load_dialog', None):
            dialog.finish()
        self._sp_scan_progress_dialog = None
        self._sp_scan_progress_done = 0

    def _on_sp_scan_thread_finished(self):
        """Release the scan thread after all of its queued results are applied."""
        finished_thread = self.sender()
        if getattr(self, '_sp_scan_thread', None) is not finished_thread:
            return
        pending_function_id = getattr(self, '_sp_scan_pending_function_id', None)
        scan_completed = bool(getattr(self, '_sp_scan_completed', False))
        load_dialog = getattr(self, '_bdmv_load_dialog', None)
        disc_load = load_dialog is not None and getattr(self, '_sp_scan_progress_dialog', None) is load_dialog
        scan_error = getattr(self, '_sp_scan_error', '')
        if disc_load and self._sp_scan_cancel_event.is_set() and not self._close_pending:
            self._bdmv_source_state_path = ''
            self._clear_bdmv_tables()
            scan_error = ''
        self._sp_scan_in_progress = False
        self._dismiss_sp_scan_progress_ui()
        self._sp_scan_cancel_event = None
        self._sp_scan_thread = None
        self._sp_scan_worker = None
        if disc_load:
            if scan_completed and not self._close_pending and not self._bdmv_load_cancel_event.is_set():
                self._run_bdmv_table_updates(self._build_sp_output_names())
            else:
                self._finish_bdmv_load(scan_error)
        elif scan_error and not self._close_pending:
            self._show_error_dialog(scan_error)
        if pending_function_id in (3, 4):
            self._sp_scan_pending_function_id = None
            self._reset_exe_button()
            if (
                    scan_completed
                    and not bool(getattr(self, '_close_pending', False))
                    and self.get_selected_function_id() == pending_function_id
            ):
                QTimer.singleShot(0, self.main)

    def _on_retired_sp_scan_thread_finished(self):
        """Release a canceled scan only after its worker thread has actually stopped."""
        finished_thread = self.sender()
        retired_scans = getattr(self, '_retired_sp_scans', None)
        if not isinstance(retired_scans, list):
            return
        self._retired_sp_scans = [
            (thread, worker)
            for thread, worker in retired_scans
            if thread is not finished_thread
        ]

    def _retire_sp_table_scan(self):
        """Invalidate and cancel the current scan while retaining its QObjects until thread exit."""
        cancel_event = getattr(self, '_sp_scan_cancel_event', None)
        if isinstance(cancel_event, threading.Event):
            cancel_event.set()

        thread = getattr(self, '_sp_scan_thread', None)
        worker = getattr(self, '_sp_scan_worker', None)
        self._sp_scan_cancel_event = None
        self._sp_scan_thread = None
        self._sp_scan_worker = None
        self._sp_scan_in_progress = False
        self._dismiss_sp_scan_progress_ui()

        if isinstance(thread, QThread) and thread.isRunning():
            retired_scans = getattr(self, '_retired_sp_scans', None)
            if not isinstance(retired_scans, list):
                retired_scans = []
                self._retired_sp_scans = retired_scans
            retired_scans.append((thread, worker))
            thread.finished.connect(self._on_retired_sp_scan_thread_finished)
            thread.requestInterruption()
            thread.quit()

        if getattr(self, '_sp_scan_pending_function_id', None) in (3, 4):
            self._sp_scan_pending_function_id = None
            self._reset_exe_button()

    def _update_exe_button_progress(self, value: Optional[int] = None, text: Optional[str] = None):
        if not hasattr(self, 'exe_button') or not self.exe_button:
            return
        if not hasattr(self, '_exe_button_default_text'):
            self._exe_button_default_text = self.exe_button.text()
        if value is not None:
            self._exe_button_progress_value = int(value)
        if text is not None:
            self._exe_button_progress_text = self.t(str(text))

        v = int(getattr(self, '_exe_button_progress_value', 0) or 0)
        t = str(getattr(self, '_exe_button_progress_text', '') or '').strip()
        ratio = max(0.0, min(1.0, v / 1000.0))
        percent = ratio * 100

        cancel_suffix = f" {self.t('(click to cancel)')}" if getattr(
            self, '_current_cancel_event', None
        ) is not None and t != self.t('Canceling...') else ""
        if t:
            self.exe_button.setText(f"{t}{cancel_suffix} {percent:.1f}%")
        else:
            self.exe_button.setText(f"{percent:.1f}%")
        self.exe_button.setStyleSheet(execution_button_stylesheet(QApplication.palette(), self._theme_mode, ratio))

    def _on_exe_button_progress_value(self, value: int):
        self._update_exe_button_progress(value=value)

    def _on_exe_button_progress_text(self, text: str):
        self._update_exe_button_progress(text=text)

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
        """Replace the previous scan with one snapshot of the completed table3.

        The synchronous refresh must finish adding, removing, and ordering rows
        before this method is called. The worker receives only paths, row
        indexes, stable track keys, and row state captured here. Starting
        a task must never call this method because that would invalidate the GUI
        snapshot that the task is about to execute.
        """
        if bool(getattr(self, '_close_pending', False)):
            return
        # The click applied to a replaced table snapshot must not resume after
        # its old scan finishes. Retaining the old worker prevents PyQt from
        # deleting a QObject whose run() method is still executing.
        self._retire_sp_table_scan()

        bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
        mpls_col = ENCODE_SP_LABELS.index('mpls_file')
        m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
        rows: list[dict[str, object]] = []
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
            sp_key = SpEntry.from_mapping(entry).track_key
            sel_item = self.table3.item(r, ENCODE_SP_LABELS.index('select'))
            force_disabled = bool((not sel_item) or (not (sel_item.flags() & Qt.ItemFlag.ItemIsEnabled)))
            # Skip truly empty rows to avoid unnecessary scan/progress popup.
            if (not force_disabled) and (not mpls_path) and (not m2ts_paths):
                continue
            rows.append({'row': r, 'm2ts_paths': m2ts_paths, 'mpls_path': mpls_path, 'sp_key': sp_key,
                         'force_disabled': force_disabled})
            playlist = self._loaded_playlist(mpls_path) if mpls_path else None
            if playlist is not None:
                rows[-1]['mpls_tracks'] = playlist.tracks

        if not rows:
            self._sp_scan_worker = None
            self._sp_scan_in_progress = False
            self._sp_scan_completed = True
            self._sp_scan_error = ''
            return

        label = self.t('Scanning bonus feature tracks...')
        progress_dialog = self._bdmv_load_dialog
        if progress_dialog is None:
            progress_dialog = ScanProgressDialog(self, label)
            self._apply_window_opacity(progress_dialog)
        else:
            progress_dialog.setLabelText(label)
            progress_dialog.set_cancel_enabled(True)
        progress_dialog.bar.setRange(0, len(rows))
        progress_dialog.bar.setValue(0)

        cancel_event = self._bdmv_load_cancel_event or threading.Event()
        self._sp_scan_cancel_event = cancel_event
        self._sp_scan_progress_dialog = progress_dialog
        self._sp_scan_progress_done = 0
        thread = QThread(self)
        worker = SpTableScanWorker(rows, cancel_event)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._on_sp_table_scan_result)
        self._sp_scan_in_progress = True
        self._sp_scan_completed = False
        self._sp_scan_error = ''
        # Let the GUI consume all results before quitting and deleting the sender.
        worker.finished.connect(self._on_sp_table_scan_finished)
        worker.finished.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        worker.canceled.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._on_sp_table_scan_failed)
        worker.failed.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_sp_scan_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._sp_scan_thread = thread
        self._sp_scan_worker = worker
        thread.start()

    def _on_sp_table_scan_failed(self, error: str):
        sender = self.sender()
        if sender is None or self._sp_scan_worker is not sender:
            return
        self._sp_scan_error = str(error or self.t('SP track scan failed; refresh the source before starting the task'))

    def _on_sp_table_scan_result(self, row: int, disabled: bool, special: str, payload: object):
        """Apply one result from the current worker without probing media again.

        Worker identity prevents a canceled/replaced scan from modifying the new
        table. The supplied track selection is already the result of the media
        probe and is stored directly under the row's stable SP key.
        """
        sender = self.sender()
        if (sender is None or self._sp_scan_worker is not sender or self._close_pending
                or self._sp_scan_cancel_event.is_set()):
            return
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
        sel_item = self.table3.item(row, sel_col)
        if not isinstance(sel_item, SpSelectionItem):
            return
        selection_default = None
        sp_key = ''
        tracks_payload = {}
        available_tracks = {}
        m2ts_type = ''
        video_only = False
        allow_tracks_when_disabled = False
        standalone_tracks = None
        if isinstance(payload, dict):
            selection_default = payload.get('selection_default')
            sp_key = str(payload.get('sp_key') or '').strip()
            tracks_payload = payload.get('tracks') or {}
            available_tracks = payload.get('available_tracks') or {}
            m2ts_type = str(payload.get('m2ts_type') or '').strip()
            video_only = bool(payload.get('video_only') or False)
            allow_tracks_when_disabled = bool(payload.get('allow_tracks_when_disabled') or False)
            standalone_tracks = payload.get('standalone_tracks')
        try:
            self._updating_sp_table = True
            flags = sel_item.flags()
            enabled = Qt.ItemFlag.ItemIsEnabled
            sel_item.setFlags(flags & ~enabled if disabled else flags | enabled)
            if selection_default is not None:
                sel_item.set_default(*selection_default)
            if disabled:
                sel_item.apply_selection(None)
            out_item = self.table3.item(row, out_col)
            if out_item:
                out_item.setData(Qt.ItemDataRole.UserRole + 2, str(special or ''))
                selected = sel_item.checkState() == Qt.CheckState.Checked
                out_item.setData(
                    READ_ONLY_HINT_ROLE, 'Select this item first.' if not disabled and not selected else None,
                )
                if not selected:
                    out_item.setFlags(out_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    out_item.setText('')
            type_item = self.table3.item(row, type_col)
            if not type_item:
                type_item = QTableWidgetItem('')
                self.table3.setItem(row, type_col, type_item)
            type_item.setText(m2ts_type)
            type_item.setData(Qt.ItemDataRole.UserRole, video_only)
            type_item.setData(SP_STANDALONE_TRACKS_ROLE, standalone_tracks)
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
                if sp_key and isinstance(tracks_payload, dict) and (not disabled):
                    # Do not call the MPLS default-selection path here. Besides
                    # repeating expensive work in the GUI thread, a second probe
                    # can fail independently and leave a visible selected row
                    # without the configuration already produced by the worker.
                    cfg = getattr(self, '_track_selection_config', None)
                    if not isinstance(cfg, dict):
                        self._track_selection_config = {}
                        cfg = self._track_selection_config
                    available_config = getattr(self, '_available_track_selection_config', None)
                    if not isinstance(available_config, dict):
                        available_config = {}
                        self._available_track_selection_config = available_config
                    available_snapshot = {
                        'audio': list(available_tracks.get('audio') or []),
                        'subtitle': list(available_tracks.get('subtitle') or []),
                    }
                    if 'video' in available_tracks:
                        available_snapshot['video'] = list(
                            available_tracks.get('video') or []
                        )
                    available_config[sp_key] = available_snapshot
                    if select_all:
                        selected_snapshot = {
                            'audio': list(available_config[sp_key]['audio']),
                            'subtitle': list(available_config[sp_key]['subtitle']),
                        }
                        if 'video' in available_config[sp_key]:
                            selected_snapshot['video'] = list(
                                available_config[sp_key]['video']
                            )
                        cfg[sp_key] = selected_snapshot
                    elif sp_key not in cfg:
                        selected_snapshot = {
                            'audio': list(tracks_payload.get('audio') or []),
                            'subtitle': list(tracks_payload.get('subtitle') or []),
                        }
                        if 'video' in tracks_payload:
                            selected_snapshot['video'] = list(
                                tracks_payload.get('video') or []
                            )
                        cfg[sp_key] = selected_snapshot
            except Exception:
                pass
        finally:
            self._updating_sp_table = False
        if self._sp_scan_progress_dialog is not None:
            self._sp_scan_progress_done += 1
            self._sp_scan_progress_dialog.bar.setValue(self._sp_scan_progress_done)
        if not bool(getattr(self, '_sp_scan_in_progress', False)):
            try:
                self._recompute_sp_output_names()
            except Exception:
                pass

    def ensure_encode_row_widgets(self, row_index: int, table: QTableWidget | None = None):
        if self.get_selected_function_id() != 4:
            return
        table = self.table2 if table is None else table
        labels = table.property('columnKeys') or ()
        if 'vpy_path' not in labels:
            return
        vpy_col = labels.index('vpy_path')
        if table.cellWidget(row_index, vpy_col) is None:
            table.setCellWidget(row_index, vpy_col, self.create_vpy_path_widget(parent=table))

        is_sp = table is self.table3
        actions = (
            (
                'edit_vpy', 'edit', 'Edit the VPy script with the default associated application.',
                self.on_edit_sp_vpy_clicked if is_sp else self.on_edit_vpy_clicked,
            ),
            (
                'preview_script', 'preview', 'Preview the VPy script with VSEdit.',
                self.on_preview_sp_scripts_clicked if is_sp else self.on_preview_script_clicked,
            ),
        )
        for key, label, tooltip, handler in actions:
            column = labels.index(key)
            if table.cellWidget(row_index, column) is None:
                button = QToolButton(table)
                button.setText(self.t(label))
                button.setProperty('toolTipSource', tooltip)
                button.setToolTip(self.t(tooltip))
                button.clicked.connect(handler)
                table.setCellWidget(row_index, column, button)
