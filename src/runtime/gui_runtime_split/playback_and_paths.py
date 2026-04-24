"""Target module for playback/path helper methods of `BluraySubtitleGUI`."""
import os
import re
import subprocess
import sys
import traceback
from urllib.parse import urlparse, unquote

from PyQt6.QtWidgets import QInputDialog, QToolButton, QMessageBox

from src.core import ENCODE_SP_LABELS, ENCODE_LABELS
from src.exports.utils import get_mpv_safe_path
from .gui_base import BluraySubtitleGuiBase


class PlaybackPathsMixin(BluraySubtitleGuiBase):
        def _normalize_path_input(self, text: str) -> str:
            s = str(text or '').strip()
            if not s:
                return ''
            if s.startswith('file://'):
                try:
                    parsed = urlparse(s)
                    path = unquote(parsed.path or '')
                    if sys.platform == 'win32' and re.match(r'^/[A-Za-z]:/', path):
                        path = path[1:]
                    s = path or s
                except Exception:
                    pass
            return os.path.normpath(os.path.expanduser(s))

        def _split_m2ts_files(self, text: str) -> list[str]:
            if not text:
                return []
            parts = re.split(r'[,\n;]+', str(text))
            return [p.strip() for p in parts if p and p.strip()]

        def _get_stream_dir_for_bdmv_index(self, bdmv_index: int) -> str:
            root = self._get_disc_root_for_bdmv_index(bdmv_index)
            if not root:
                return ''
            return os.path.normpath(os.path.join(root, 'BDMV', 'STREAM'))

        def _get_playlist_dir_for_bdmv_index(self, bdmv_index: int) -> str:
            root = self._get_disc_root_for_bdmv_index(bdmv_index)
            if not root:
                return ''
            return os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST'))

        def _get_disc_root_for_bdmv_index(self, bdmv_index: int) -> str:
            try:
                idx = int(bdmv_index)
            except Exception:
                idx = -1
            if not hasattr(self, 'table1') or not self.table1:
                return ''
            row_count = self.table1.rowCount()
            if row_count <= 0:
                return ''
            candidates: list[int] = []
            if idx > 0:
                candidates.extend([idx - 1, idx])
            else:
                candidates.append(0)
            candidates.extend([0, row_count - 1])
            seen: set[int] = set()
            for r in candidates:
                if r in seen:
                    continue
                seen.add(r)
                if r < 0 or r >= row_count:
                    continue
                try:
                    root_item = self.table1.item(r, 0)
                    root = root_item.text().strip() if root_item else ''
                except Exception:
                    root = ''
                if not root:
                    continue
                bdmv_dir = os.path.join(root, 'BDMV')
                playlist_dir = os.path.join(bdmv_dir, 'PLAYLIST')
                stream_dir = os.path.join(bdmv_dir, 'STREAM')
                if os.path.isdir(playlist_dir) and os.path.isdir(stream_dir):
                    return os.path.normpath(root)
                if os.path.isdir(bdmv_dir):
                    return os.path.normpath(root)
            return ''

        def _select_video_path(self, bdmv_index: int, m2ts_files: list[str]) -> str:
            if not m2ts_files:
                return ''
            stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
            if not stream_dir:
                return ''

            if len(m2ts_files) == 1:
                return os.path.normpath(os.path.join(stream_dir, m2ts_files[0]))

            item, ok = QInputDialog.getItem(
                self,
                self.t("选择m2ts文件"),
                self.t("检测到多个 m2ts 文件，请选择要预览的文件："),
                m2ts_files,
                0,
                False
            )
            if not ok or not item:
                return ''
            return os.path.normpath(os.path.join(stream_dir, str(item)))

        def _play_mpls_path(self, mpls_path: str):
            btn = QToolButton()
            btn.setText(self.t('play'))
            btn.setProperty('action', 'play')
            self.on_button_play(mpls_path, btn)

        def _play_m2ts_path(self, m2ts_path: str):
            if not m2ts_path or not os.path.exists(m2ts_path):
                QMessageBox.information(self, " ", f"未找到 m2ts 文件：\n{m2ts_path}")
                return
            if sys.platform == 'win32':
                mp4_exe_path = get_mpv_safe_path(".mp4")
                if mp4_exe_path and str(mp4_exe_path).lower().endswith('mpv.exe'):
                    subprocess.Popen(f'"{mp4_exe_path}" "{m2ts_path}"', shell=True).wait()
                    return
            self.open_file_path(m2ts_path)

        def on_play_table2_disc_row(self, row_index: int, bdmv_col: int, m2ts_col: int):
            try:
                bdmv_item = self.table2.item(row_index, bdmv_col)
                try:
                    bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
                except Exception:
                    bdmv_index = 0
                m2ts_item = self.table2.item(row_index, m2ts_col)
                m2ts_files = self._split_m2ts_files(m2ts_item.text() if m2ts_item else '')
                video_path = self._select_video_path(bdmv_index, m2ts_files)
                if video_path:
                    self._play_m2ts_path(video_path)
            except Exception:
                self._show_error_dialog(traceback.format_exc())

        def on_play_sp_table_row(self, row_index: int, bdmv_col: int, mpls_col: int, m2ts_col: int):
            try:
                bdmv_item = self.table3.item(row_index, bdmv_col)
                try:
                    bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
                except Exception:
                    bdmv_index = 0
                mpls_item = self.table3.item(row_index, mpls_col)
                mpls_file = (mpls_item.text().strip() if mpls_item and mpls_item.text() else '')
                if mpls_file:
                    playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                    if not playlist_dir:
                        QMessageBox.information(self, " ",
                                                f"未找到对应的蓝光目录（bdmv_index={bdmv_index}），无法定位 mpls 文件")
                        return
                    mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_file))
                    if os.path.exists(mpls_path):
                        self._play_mpls_path(mpls_path)
                        return
                    QMessageBox.information(self, " ", f"未找到 mpls 文件：\n{mpls_path}")
                    return
                m2ts_item = self.table3.item(row_index, m2ts_col)
                m2ts_files = self._split_m2ts_files(m2ts_item.text() if m2ts_item else '')
                video_path = self._select_video_path(bdmv_index, m2ts_files)
                if video_path:
                    self._play_m2ts_path(video_path)
            except Exception:
                self._show_error_dialog(traceback.format_exc())

        def _on_play_sp_table_row_clicked(self):
            try:
                sender = self.sender()
                if sender is None or not hasattr(self, 'table3') or not self.table3:
                    return
                row_index = self.table3.indexAt(sender.pos()).row()
                if row_index < 0:
                    return
                bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                self.on_play_sp_table_row(row_index, bdmv_col, mpls_col, m2ts_col)
            except Exception:
                self._show_error_dialog(traceback.format_exc())

        def _get_first_subtitle_path_for_bdmv_index(self, bdmv_index: int) -> str:
            if self.get_selected_function_id() != 4:
                return ''
            try:
                bdmv_col = ENCODE_LABELS.index('bdmv_index')
            except Exception:
                bdmv_col = 2
            for r in range(self.table2.rowCount()):
                item = self.table2.item(r, bdmv_col)
                if not item or not item.text().strip():
                    continue
                try:
                    if int(item.text().strip()) != int(bdmv_index):
                        continue
                except Exception:
                    continue
                sub_item = self.table2.item(r, 0)
                if sub_item and sub_item.text().strip():
                    return sub_item.text().strip()
            return ''
