"""Target module for remux command and episode-table linkage methods."""
import os
import threading
import time
import traceback
from functools import partial
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QCoreApplication, QThread
from PyQt6.QtWidgets import QTableWidget, QToolButton, QPlainTextEdit, QWidget, QTableWidgetItem, QComboBox, \
    QProgressDialog, QProgressBar, QMessageBox

from src.bdmv import Chapter
from src.core import BDMV_LABELS, DIY_BDMV_LABELS, DIY_REMUX_LABELS, find_mkvtoolinx, MKV_MERGE_PATH, \
    mkvtoolnix_ui_language_arg, ENCODE_REMUX_LABELS, ENCODE_REMUX_SP_LABELS, SUBTITLE_LABELS, ENCODE_LABELS, \
    REMUX_LABELS, CURRENT_UI_LANGUAGE, ENCODE_SP_LABELS
from src.domain import Subtitle
from src.exports.utils import get_time_str, get_index_to_m2ts_and_offset, print_exc_terminal, get_folder_size
from src.runtime.gui_runtime_classes.file_path_table_widget_item import FilePathTableWidgetItem
from src.runtime.gui_runtime_classes.remux_worker import RemuxWorker
from src.runtime.services import BluraySubtitle, _Cancelled
from .gui_base import BluraySubtitleGuiBase


class RemuxEpisodeLayoutMixin(BluraySubtitleGuiBase):
        def _apply_main_remux_cmds_to_configuration(self, configuration: dict[int, dict[str, int | str]]):
            cmd_map = self._collect_main_remux_cmd_map_from_table1()
            if not cmd_map:
                return
            for _, conf in configuration.items():
                try:
                    mpls_path = os.path.normpath(str(conf.get('selected_mpls') or '') + '.mpls')
                except Exception:
                    continue
                cmd = cmd_map.get(mpls_path, '')
                if cmd:
                    conf['main_remux_cmd'] = cmd

        def _bdmv_index_for_table1_folder_norm(self, folder_norm: str) -> int:
            try:
                fn = os.path.normpath(str(folder_norm or ''))
                for r in range(self.table1.rowCount()):
                    it = self.table1.item(r, 0)
                    if not it or not str(it.text() or '').strip():
                        continue
                    if os.path.normpath(it.text().strip()) == fn:
                        return int(r + 1)
            except Exception:
                pass
            return 0

        def _bdmv_to_first_main_mpls_from_table1(self) -> dict[int, str]:
            """table1 row order -> first selected main mpls (no ext) for that disc; matches bdmv_index column."""
            out: dict[int, str] = {}
            try:
                selected = self.get_selected_mpls_no_ext()
                for r in range(self.table1.rowCount()):
                    it = self.table1.item(r, 0)
                    if not it or not str(it.text() or '').strip():
                        continue
                    root = os.path.normpath(it.text().strip())
                    bi = int(r + 1)
                    for folder, m in selected:
                        if os.path.normpath(str(folder)) == root:
                            out[bi] = str(m).strip()
                            break
            except Exception:
                pass
            return out

        def _collect_main_remux_cmd_map_from_table1(self) -> dict[str, str]:
            out: dict[str, str] = {}
            if not hasattr(self, 'table1') or not self.table1:
                return out
            cmd_col = BDMV_LABELS.index('remux_cmd') if 'remux_cmd' in BDMV_LABELS else -1
            if cmd_col < 0:
                return out
            for r in range(self.table1.rowCount()):
                root_item = self.table1.item(r, 0)
                if not root_item:
                    continue
                root = root_item.text().strip()
                info = self.table1.cellWidget(r, 2)
                if not isinstance(info, QTableWidget):
                    continue
                selected_paths: list[str] = []
                for i in range(info.rowCount()):
                    btn = info.cellWidget(i, 3)
                    if isinstance(btn, QToolButton) and btn.isChecked():
                        item = info.item(i, 0)
                        if item and item.text().strip():
                            selected_paths.append(
                                os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', item.text().strip())))
                if not selected_paths:
                    continue
                editor = self.table1.cellWidget(r, cmd_col)
                if isinstance(editor, QPlainTextEdit):
                    lines = [ln.strip() for ln in editor.toPlainText().splitlines() if ln.strip()]
                    if not lines:
                        continue
                    for i, mpls_path in enumerate(selected_paths):
                        if i < len(lines):
                            out[mpls_path] = lines[i]
            return out

        def _build_main_remux_cmd_template(
                self,
                mpls_path: str,
                bdmv_index: int,
                root: str,
                *,
                name_seq_index: int = 0,
                name_seq_total: int = 1,
        ) -> str:
            try:
                find_mkvtoolinx()
            except Exception:
                pass
            try:
                output_folder = os.path.normpath(self.output_folder_path.text().strip()) if hasattr(self,
                                                                                                    'output_folder_path') else ''
            except Exception:
                output_folder = ''
            confs: list[dict[str, int | str]] = []
            target_mpls_no_ext = os.path.normpath(str(mpls_path or '').strip())
            if target_mpls_no_ext.lower().endswith('.mpls'):
                target_mpls_no_ext = target_mpls_no_ext[:-5]
            try:
                latest = getattr(self, '_last_configuration_34', {}) or {}
                for _, conf in latest.items():
                    try:
                        conf_mpls_no_ext = os.path.normpath(str(conf.get('selected_mpls') or '').strip())
                        if int(conf.get('bdmv_index') or 0) == int(bdmv_index) and conf_mpls_no_ext == target_mpls_no_ext:
                            confs.append(conf)
                    except Exception:
                        pass
            except Exception:
                confs = []
            disc_count = 1
            try:
                latest = getattr(self, '_last_configuration_34', {}) or {}
                disc_count = len({int(v.get('bdmv_index') or 0) for v in latest.values() if isinstance(v, dict)}) or 1
            except Exception:
                disc_count = 1
            if not confs:
                confs = [{'selected_mpls': mpls_path[:-5], 'chapter_index': 1}]
            try:
                confs = sorted(confs, key=lambda c: int(c.get('chapter_index') or 0))
            except Exception:
                pass
            if int(name_seq_total) > 1:
                try:
                    seq_tag = f'_{int(name_seq_index) + 1}'
                    for c in confs:
                        base = str(c.get('disc_output_name') or '').strip()
                        if base:
                            c['disc_output_name'] = f'{base}{seq_tag}'
                except Exception:
                    pass
            try:
                top = ''
                try:
                    top = os.path.normpath(self.bdmv_folder_path.text().strip()) if hasattr(self,
                                                                                            'bdmv_folder_path') else ''
                except Exception:
                    top = ''
                bs = BluraySubtitle(top or root, [], False, None, movie_mode=self._is_movie_mode())
                bs.track_selection_config = getattr(self, '_track_selection_config', {}) or {}
                bs.movie_mode = bool(self._is_movie_mode())
                cmd, _m2ts, _vol, _out, _mpls, _pid, _a, _s = bs._make_main_mpls_remux_cmd(confs, output_folder or '',
                                                                                           int(bdmv_index), disc_count)
                return cmd
            except Exception:
                try:
                    mkvmerge_exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
                    return f'"{mkvmerge_exe}" {mkvtoolnix_ui_language_arg()} -o "{output_folder}" "{mpls_path}"'
                except Exception:
                    return ''

        def _create_main_remux_cmd_editor(self, text: str, parent: Optional[QWidget] = None) -> QPlainTextEdit:
            editor = QPlainTextEdit(parent if parent is not None else self.table1)
            editor._auto_cmd = text or ''
            editor._user_modified = False
            editor._updating_cmd = True
            editor.setPlainText(text or '')
            editor._updating_cmd = False
            editor.setReadOnly(False)
            editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

            def mark_modified():
                if getattr(editor, '_updating_cmd', False):
                    return
                editor._user_modified = True

            editor.textChanged.connect(mark_modified)
            return editor

        def _folder_path_for_bdmv_index_from_table1(self, bdmv_index: int) -> str:
            """Bluray root folder for disc column bdmv_index (1-based, same as table1 row + 1)."""
            try:
                r = int(bdmv_index) - 1
                if 0 <= r < self.table1.rowCount():
                    it = self.table1.item(r, 0)
                    t = str(it.text() or '').strip() if it else ''
                    if t:
                        return os.path.normpath(t)
            except Exception:
                pass
            return ''

        @staticmethod
        def _folder_set_mains_from_configuration(last_cfg: dict[int, dict[str, int | str]]) -> dict[str, set[str]]:
            out: dict[str, set[str]] = {}
            for _, c in (last_cfg or {}).items():
                if not isinstance(c, dict):
                    continue
                fn = os.path.normpath(str(c.get('folder') or ''))
                m = os.path.normpath(str(c.get('selected_mpls') or ''))
                if fn and m:
                    out.setdefault(fn, set()).add(m)
            return out

        @staticmethod
        def _folder_set_mains_from_selected(selected: list[tuple[str, str]]) -> dict[str, set[str]]:
            out: dict[str, set[str]] = {}
            for folder, m in selected or []:
                fn = os.path.normpath(str(folder))
                out.setdefault(fn, set()).add(os.path.normpath(str(m)))
            return out

        def _folders_with_changed_main_selection(
                self,
                selected: list[tuple[str, str]],
                last_cfg: dict[int, dict[str, int | str]],
        ) -> set[str]:
            cur = self._folder_set_mains_from_selected(selected)
            prev = self._folder_set_mains_from_configuration(last_cfg)
            keys = set(cur.keys()) | set(prev.keys())
            return {fn for fn in keys if cur.get(fn, set()) != prev.get(fn, set())}

        def _get_main_mpls_path_for_bdmv_index(self, bdmv_index: int) -> str:
            try:
                idx = int(bdmv_index) - 1
            except Exception:
                return ''
            if idx < 0 or idx >= self.table1.rowCount():
                return ''
            info = self.table1.cellWidget(idx, 2)
            if not isinstance(info, QTableWidget):
                return ''
            root_item = self.table1.item(idx, 0)
            root = root_item.text().strip() if root_item and root_item.text() else ''
            if not root:
                return ''
            for mpls_index in range(info.rowCount()):
                main_btn = info.cellWidget(mpls_index, 3)
                if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                    mpls_item = info.item(mpls_index, 0)
                    if mpls_item and mpls_item.text():
                        return os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip()))
            return ''

        def _get_remux_source_path_from_table2_row(self, row_index: int) -> str:
            try:
                out_col = ENCODE_REMUX_LABELS.index('output_name')
            except Exception:
                out_col = 3
            item = self.table2.item(row_index, out_col)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, str) and data:
                    return os.path.normpath(data)
            if hasattr(self, 'remux_folder_path'):
                folder = self._normalize_path_input(self.remux_folder_path.text())
                if folder and item and item.text().strip():
                    return os.path.normpath(os.path.join(folder, item.text().strip()))
            return ''

        def _get_remux_source_path_from_table3_row(self, row_index: int) -> str:
            try:
                out_col = ENCODE_REMUX_SP_LABELS.index('output_name')
            except Exception:
                out_col = 1
            item = self.table3.item(row_index, out_col)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(data, str) and data:
                    return os.path.normpath(data)
            if hasattr(self, 'remux_folder_path'):
                folder = self._normalize_path_input(self.remux_folder_path.text())
                sp_folder = os.path.join(folder, 'SPs') if folder else ''
                if sp_folder and item and item.text().strip():
                    return os.path.normpath(os.path.join(sp_folder, item.text().strip()))
            return ''

        def _get_root_for_bdmv_index(self, bdmv_index: int) -> str:
            try:
                idx = int(bdmv_index) - 1
            except Exception:
                return ''
            if idx < 0 or idx >= self.table1.rowCount():
                return ''
            it = self.table1.item(idx, 0)
            return it.text().strip() if it and it.text() else ''

        def _get_selected_main_mpls_paths(self) -> list[str]:
            out: list[str] = []
            for bdmv_index in range(self.table1.rowCount()):
                info = self.table1.cellWidget(bdmv_index, 2)
                if not isinstance(info, QTableWidget):
                    continue
                root_item = self.table1.item(bdmv_index, 0)
                root = root_item.text().strip() if root_item and root_item.text() else ''
                if not root:
                    continue
                for mpls_index in range(info.rowCount()):
                    main_btn = info.cellWidget(mpls_index, 3)
                    if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                        mpls_item = info.item(mpls_index, 0)
                        if mpls_item and mpls_item.text():
                            out.append(os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip())))
            return out

        def _merge_volume_part_from_last_cfg(
                self,
                part: dict[int, dict[str, int | str]],
                last_cfg: dict[int, dict[str, int | str]],
                bdmv_index: int,
        ) -> None:
            """Restore end_at_chapter / disc_output_name on regenerated no-sub rows when episode keys match."""
            if not part or not last_cfg or bdmv_index <= 0:
                return
            prev_rows = [
                dict(v)
                for _, v in sorted(last_cfg.items(), key=lambda kv: int(kv[0]))
                if int(v.get('bdmv_index') or 0) == int(bdmv_index)
            ]
            if not prev_rows:
                return

            def ch_rows(mpl: str) -> int:
                try:
                    return int(self._chapter_node_data(str(mpl).strip()).get('rows') or 0)
                except Exception:
                    return 0

            def _copy_prefs(new_c: dict[str, int | str], pr: dict[str, int | str]) -> None:
                don = str(pr.get('disc_output_name') or '').strip()
                if don:
                    new_c['disc_output_name'] = don
                try:
                    ei = int(pr.get('end_at_chapter'))
                    st = int(new_c.get('chapter_index') or 1)
                    tr = ch_rows(str(new_c.get('selected_mpls') or '').strip())
                    if tr > 0 and ei > st and ei <= tr + 1:
                        new_c['end_at_chapter'] = ei
                except Exception:
                    pass

            items = sorted(part.items(), key=lambda kv: int(kv[0]))
            if len(items) == len(prev_rows):
                seq_ok = True
                for (_, nc), pr in zip(items, prev_rows):
                    if str(nc.get('selected_mpls') or '').strip() != str(pr.get('selected_mpls') or '').strip():
                        seq_ok = False
                        break
                    if int(nc.get('chapter_index') or 1) != int(pr.get('chapter_index') or 1):
                        seq_ok = False
                        break
                if seq_ok:
                    for (_, new_c), pr in zip(items, prev_rows):
                        _copy_prefs(new_c, pr)
                    return

            used: set[int] = set()
            for _, new_c in items:
                mpl_n = str(new_c.get('selected_mpls') or '').strip()
                if not mpl_n:
                    continue
                ch_n = int(new_c.get('chapter_index') or 1)
                strict = [
                    j
                    for j, pr in enumerate(prev_rows)
                    if j not in used
                       and str(pr.get('selected_mpls') or '').strip() == mpl_n
                       and int(pr.get('chapter_index') or 1) == ch_n
                ]
                pick = strict[0] if len(strict) == 1 else -1
                if pick < 0:
                    for j, pr in enumerate(prev_rows):
                        if j in used:
                            continue
                        if str(pr.get('selected_mpls') or '').strip() == mpl_n:
                            pick = j
                            break
                if pick < 0:
                    continue
                used.add(pick)
                pr = prev_rows[pick]
                _copy_prefs(new_c, pr)

        def _refresh_movie_subtitle_table2(self, rows: Optional[list[tuple[str, str]]] = None):
            if self.get_selected_function_id() != 1:
                return
            selected_mpls = self.get_selected_mpls_no_ext()
            if not selected_mpls:
                return

            folder_to_bdmv: dict[str, int] = {}
            discs: list[tuple[int, str]] = []
            for folder, mpls_no_ext in selected_mpls:
                if folder not in folder_to_bdmv:
                    folder_to_bdmv[folder] = len(folder_to_bdmv) + 1
                discs.append((folder_to_bdmv[folder], mpls_no_ext))
            discs.sort(key=lambda x: x[0])

            def parse_time_str_to_seconds(s: str) -> Optional[float]:
                try:
                    parts = [p for p in str(s or '').strip().split(':') if p != '']
                    if not parts:
                        return None
                    nums = [float(p) for p in parts]
                    val = 0.0
                    for n in nums:
                        val = val * 60.0 + float(n)
                    return val
                except Exception:
                    return None

            file_rows: list[tuple[str, str, Optional[float]]] = []
            if rows:
                for p, d in rows:
                    if not p:
                        continue
                    dur_str = str(d or '').strip()
                    file_rows.append((str(p).strip(), dur_str, parse_time_str_to_seconds(dur_str)))
            else:
                folder = self.subtitle_folder_path.text().strip()
                if folder and os.path.isdir(folder):
                    paths = []
                    for f in sorted(os.listdir(folder)):
                        if f.endswith(".ass") or f.endswith(".ssa") or f.endswith('srt') or f.endswith('.sup'):
                            paths.append(os.path.normpath(os.path.join(folder, f)))
                    for p in paths:
                        try:
                            sec = float(Subtitle(p).max_end_time())
                            file_rows.append((p, get_time_str(sec), sec))
                        except Exception:
                            file_rows.append((p, 'Unknown', None))

            sub_duration_col = SUBTITLE_LABELS.index('sub_duration')
            ep_duration_col = SUBTITLE_LABELS.index('ep_duration')
            bdmv_col = SUBTITLE_LABELS.index('bdmv_index')
            chapter_col = SUBTITLE_LABELS.index('chapter_index')
            offset_col = SUBTITLE_LABELS.index('offset')
            warn_col = SUBTITLE_LABELS.index('warning')

            old_sorting = self.table2.isSortingEnabled()
            self.table2.setSortingEnabled(False)
            try:
                self.table2.clear()
                self.table2.setColumnCount(len(SUBTITLE_LABELS))
                self._set_table_headers(self.table2, SUBTITLE_LABELS)
                self._set_table2_subtitle_column_order()
                self.table2.setRowCount(len(discs))

                for i, (bdmv_index, mpls_no_ext) in enumerate(discs):
                    check_item = QTableWidgetItem()
                    check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    check_item.setCheckState(Qt.CheckState.Checked)
                    self.table2.setItem(i, 0, check_item)

                    if i < len(file_rows):
                        p, dur, sub_sec = file_rows[i]
                        self.table2.setItem(i, 1, FilePathTableWidgetItem(p))
                        self.table2.setItem(i, sub_duration_col, QTableWidgetItem(dur))
                    else:
                        self.table2.setItem(i, 1, FilePathTableWidgetItem(''))
                        self.table2.setItem(i, sub_duration_col, QTableWidgetItem(''))
                        sub_sec = None

                    try:
                        total_time = Chapter(mpls_no_ext + '.mpls').get_total_time()
                        self.table2.setItem(i, ep_duration_col, QTableWidgetItem(get_time_str(total_time)))
                    except Exception:
                        self.table2.setItem(i, ep_duration_col, QTableWidgetItem('Unknown'))
                        total_time = None

                    self.table2.setItem(i, bdmv_col, QTableWidgetItem(str(bdmv_index)))

                    chapter_combo = QComboBox(self.table2)
                    chapter_combo.addItems(['1'])
                    chapter_combo.setCurrentIndex(0)
                    chapter_combo.setEnabled(False)
                    self.table2.setCellWidget(i, chapter_col, chapter_combo)

                    self.table2.setItem(i, offset_col, QTableWidgetItem('0'))

                    warn_item = QTableWidgetItem('')
                    try:
                        if isinstance(sub_sec, (int, float)) and isinstance(total_time, (int, float)) and total_time > 0:
                            if float(sub_sec) <= float(total_time) / 2.0:
                                warn_item.setText('!')
                                warn_item.setToolTip(self.t('May require series mode'))
                    except Exception:
                        pass
                    self.table2.setItem(i, warn_col, warn_item)

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
            finally:
                self.table2.setSortingEnabled(old_sorting)

            self.table2.resizeColumnsToContents()
            self._resize_table_columns_for_language(self.table2)
            self._scroll_table_h_to_right(self.table2)
            self._update_main_row_play_button()

        def _refresh_movie_table2(self):
            function_id = self.get_selected_function_id()
            if function_id not in (3, 4, 5):
                return
            selected_mpls = self.get_selected_mpls_no_ext()
            if function_id == 4:
                labels = ENCODE_LABELS
            elif function_id == 5:
                labels = DIY_REMUX_LABELS
            else:
                labels = REMUX_LABELS
            duration_col = labels.index('ep_duration')
            bdmv_col = labels.index('bdmv_index')
            chapter_col = labels.index('start_at_chapter')
            end_col = labels.index('end_at_chapter')
            m2ts_col = labels.index('m2ts_file')
            language_col = labels.index('language')
            output_col = labels.index('output_name') if 'output_name' in labels else -1

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
                            prev_name_by_bdmv[bdmv_index] = (it.text().strip(), auto if isinstance(auto, str) else '')
            except Exception:
                pass

            folder_to_bdmv: dict[str, int] = {}
            disc_rows: list[tuple[int, str, str]] = []
            for folder, mpls_no_ext in selected_mpls:
                if folder not in folder_to_bdmv:
                    folder_to_bdmv[folder] = len(folder_to_bdmv) + 1
                bdmv_index = folder_to_bdmv[folder]
                disc_rows.append((bdmv_index, folder, mpls_no_ext))
            disc_rows.sort(key=lambda x: x[0])
            single_volume = len(disc_rows) == 1

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

            auto_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
            configuration: dict[int, dict[str, int | str]] = {}

            old_sorting = self.table2.isSortingEnabled()
            self.table2.setSortingEnabled(False)
            try:
                self.table2.setRowCount(len(disc_rows))
                for row_i, (bdmv_index, folder, mpls_no_ext) in enumerate(disc_rows):
                    mpls_path = mpls_no_ext + '.mpls'
                    chapter = Chapter(mpls_path)
                    total_time = chapter.get_total_time()
                    index_to_m2ts, _index_to_offset = get_index_to_m2ts_and_offset(chapter)
                    m2ts_files = sorted(list(set(index_to_m2ts.values())))
                    disc_name = self._resolve_output_name_from_mpls(mpls_no_ext)
                    bdmv_vol = f'{bdmv_index:03d}'
                    auto_name = f'{disc_name}.mkv' if single_volume else f'{disc_name}_BD_Vol_{bdmv_vol}.mkv'

                    if sub_files_in_folder and row_i < len(sub_files_in_folder):
                        self.table2.setItem(row_i, 0, FilePathTableWidgetItem(sub_files_in_folder[row_i]))

                    self.table2.setItem(row_i, bdmv_col, QTableWidgetItem(str(bdmv_index)))
                    chapter_combo = QComboBox()
                    chapter_combo.addItem('chapter 01', 1)
                    chapter_combo.setCurrentIndex(0)
                    chapter_combo._prev_start_value = int(chapter_combo.currentData() or 1)
                    chapter_combo.setEnabled(False)
                    self.table2.setCellWidget(row_i, chapter_col, chapter_combo)
                    end_combo = self._build_end_chapter_combo(1, False, 1, 2)
                    end_combo.currentIndexChanged.connect(partial(self._on_end_chapter_combo_changed, row_i, labels))
                    self.table2.setCellWidget(row_i, end_col, end_combo)
                    self.table2.setItem(row_i, m2ts_col, QTableWidgetItem(', '.join(m2ts_files)))
                    self.table2.setItem(row_i, duration_col, QTableWidgetItem(get_time_str(total_time)))

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

                    prev_name, prev_auto = prev_name_by_bdmv.get(bdmv_index, ('', ''))
                    if prev_name and prev_auto and prev_name != prev_auto:
                        final_text = prev_name
                    else:
                        final_text = auto_name
                    if output_col >= 0:
                        out_item = QTableWidgetItem(final_text)
                        out_item.setData(Qt.ItemDataRole.UserRole, auto_name)
                        self.table2.setItem(row_i, output_col, out_item)

                    if function_id == 4:
                        self.ensure_encode_row_widgets(row_i)

                    configuration[row_i] = {
                        'folder': folder,
                        'selected_mpls': mpls_no_ext,
                        'bdmv_index': bdmv_index,
                        'chapter_index': 1,
                        'offset': '0',
                        'disc_output_name': disc_name,
                        'output_name': final_text,
                    }
            finally:
                self.table2.setSortingEnabled(old_sorting)

            self._movie_configuration = configuration
            if function_id in (3, 4, 5):
                self.refresh_sp_table(configuration)
            self.table2.resizeColumnsToContents()
            self._resize_table_columns_for_language(self.table2)
            self._update_language_combo_enabled_state()
            self._sync_end_chapter_min_constraints(labels)
            self._apply_start_chapter_constraints(labels)
            self._scroll_table_h_to_right(self.table2)

        def _refresh_table1_remux_cmds(self):
            if not hasattr(self, 'table1') or not self.table1:
                return
            if 'remux_cmd' not in BDMV_LABELS:
                return
            cmd_col = BDMV_LABELS.index('remux_cmd')
            for row in range(self.table1.rowCount()):
                root_item = self.table1.item(row, 0)
                root = root_item.text().strip() if root_item and root_item.text() else ''
                if not root:
                    continue
                info = self.table1.cellWidget(row, 2)
                if not isinstance(info, QTableWidget):
                    continue
                selected_mpls_paths: list[str] = []
                for i in range(info.rowCount()):
                    main_btn = info.cellWidget(i, 3)
                    if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                        mpls_item = info.item(i, 0)
                        if mpls_item and mpls_item.text().strip():
                            selected_mpls_paths.append(
                                os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip())))
                editor = self.table1.cellWidget(row, cmd_col)
                if not isinstance(editor, QPlainTextEdit):
                    editor = self._create_main_remux_cmd_editor('', self.table1)
                    self.table1.setCellWidget(row, cmd_col, editor)
                    self.table1.setRowHeight(row, max(self.table1.rowHeight(row), 100))
                if not selected_mpls_paths:
                    editor._updating_cmd = True
                    editor._auto_cmd = ''
                    editor._user_modified = False
                    editor.setPlainText('')
                    editor._updating_cmd = False
                    continue
                auto_cmd_lines: list[str] = []
                total_paths = len(selected_mpls_paths)
                for idx_path, selected_mpls_path in enumerate(selected_mpls_paths):
                    resolved_bdmv_index = self._resolve_bdmv_index_for_main_mpls(selected_mpls_path, row + 1)
                    auto_cmd_lines.append(
                        self._build_main_remux_cmd_template(
                            selected_mpls_path,
                            resolved_bdmv_index,
                            root,
                            name_seq_index=idx_path,
                            name_seq_total=total_paths,
                        )
                    )
                auto_cmd = '\n'.join([x for x in auto_cmd_lines if str(x).strip()])
                cur_txt = editor.toPlainText()
                if (not getattr(editor, '_user_modified', False)) or (not cur_txt.strip()) or (
                        cur_txt == getattr(editor, '_auto_cmd', '')):
                    editor._updating_cmd = True
                    editor._auto_cmd = auto_cmd
                    editor.setPlainText(auto_cmd)
                    editor._updating_cmd = False

        def _remove_table2_rows_by_bdmv_index(self, bdmv_index: int):
            if not hasattr(self, 'table2') or not self.table2:
                return
            function_id = self.get_selected_function_id()
            if function_id not in (3, 4, 5):
                return
            if function_id == 4:
                labels = ENCODE_LABELS
            elif function_id == 5:
                labels = DIY_REMUX_LABELS
            else:
                labels = REMUX_LABELS
            if 'bdmv_index' not in labels:
                return
            col = labels.index('bdmv_index')
            for r in range(self.table2.rowCount() - 1, -1, -1):
                it = self.table2.item(r, col)
                if not it:
                    continue
                try:
                    b = int(str(it.text() or '').strip())
                except Exception:
                    continue
                if b == int(bdmv_index):
                    self.table2.removeRow(r)

        def _resolve_bdmv_index_for_main_mpls(self, mpls_path: str, fallback_index: int) -> int:
            """Resolve bdmv_index from latest configuration using selected main mpls path."""
            try:
                target = os.path.normpath(str(mpls_path or '').strip())
            except Exception:
                target = ''
            if not target:
                return int(fallback_index)
            try:
                latest = getattr(self, '_last_configuration_34', {}) or {}
                for conf in latest.values():
                    if not isinstance(conf, dict):
                        continue
                    conf_mpls = os.path.normpath(str(conf.get('selected_mpls') or '') + '.mpls')
                    if conf_mpls == target:
                        val = int(conf.get('bdmv_index') or 0)
                        if val > 0:
                            return val
            except Exception:
                pass
            return int(fallback_index)

        def _resolve_remux_output_folder(self, base_folder: str) -> str:
            if self.get_selected_function_id() == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
                remux_folder = self._normalize_path_input(
                    self.remux_folder_path.text() if hasattr(self, 'remux_folder_path') else '')
                if remux_folder:
                    folder_name = os.path.basename(remux_folder.rstrip(os.sep))
                    if folder_name:
                        return os.path.join(base_folder, folder_name)
            return base_folder

        def _resync_episode_tables_from_main_mpls_selection(self) -> None:
            """After main MPLS toggles, refresh only affected main-mpls configuration."""
            if self.get_selected_function_id() not in (3, 4, 5) or self._is_movie_mode():
                return
            try:
                selected = self.get_selected_mpls_no_ext()
                if not selected:
                    self.table2.setRowCount(0)
                    self.refresh_sp_table({})
                    self._last_configuration_34 = {}
                    self._selected_main_mpls_prev = set()
                    return
                current_set = {os.path.normpath(str(m)) for _, m in selected}
                prev_set = set(getattr(self, '_selected_main_mpls_prev', set()) or set())
                last_cfg = dict(getattr(self, '_last_configuration_34', {}) or {})
                sub_files: list[str] = []
                selected_fid = self.get_selected_function_id()
                if selected_fid == 4:
                    labels = ENCODE_LABELS
                elif selected_fid == 5:
                    labels = DIY_REMUX_LABELS
                else:
                    labels = REMUX_LABELS
                try:
                    sub_col = labels.index('sub_path')
                    for r in range(self.table2.rowCount()):
                        it = self.table2.item(r, sub_col)
                        p = it.text().strip() if it and it.text() else ''
                        if p:
                            sub_files.append(p)
                except Exception:
                    sub_files = []
                bs = BluraySubtitle(
                    self.bdmv_folder_path.text(),
                    sub_files,
                    self.checkbox1.isChecked(),
                    None,
                    approx_episode_duration_seconds=self._get_approx_episode_duration_seconds(),
                )
                prev_folder_mains = self._folder_set_mains_from_configuration(last_cfg)
                cur_folder_mains = self._folder_set_mains_from_selected(selected)
                affected = self._folders_with_changed_main_selection(selected, last_cfg)
                if sub_files or not last_cfg or not prev_set:
                    full_cfg = bs.generate_configuration_from_selected_mpls(selected)
                    configuration = {
                        i: dict(c) if isinstance(c, dict) else c
                        for i, (_, c) in enumerate(sorted((full_cfg or {}).items(), key=lambda kv: int(kv[0])))
                    }
                else:
                    if not affected:
                        configuration = {
                            i: dict(c) if isinstance(c, dict) else c
                            for i, (_, c) in enumerate(sorted(last_cfg.items(), key=lambda kv: int(kv[0])))
                        }
                    else:
                        merged_list: list[dict[str, int | str]] = []
                        for folder_norm in self._table1_bluray_folder_order():
                            if folder_norm in affected:
                                vol_pairs = [(f, m) for f, m in selected if os.path.normpath(str(f)) == folder_norm]
                                if vol_pairs:
                                    part = bs._volume_configuration_no_sub_files(vol_pairs, cancel_event=None)
                                    bi_merge = self._bdmv_index_for_table1_folder_norm(folder_norm)
                                    if bi_merge > 0:
                                        self._merge_volume_part_from_last_cfg(part, last_cfg, bi_merge)
                                    for _, c in sorted(part.items(), key=lambda kv: int(kv[0])):
                                        merged_list.append(dict(c))
                            else:
                                bi = self._bdmv_index_for_table1_folder_norm(folder_norm)
                                if bi <= 0:
                                    continue
                                for _, c in sorted(last_cfg.items(), key=lambda kv: int(kv[0])):
                                    if not isinstance(c, dict):
                                        continue
                                    try:
                                        cbi = int(c.get('bdmv_index') or 0)
                                    except Exception:
                                        cbi = 0
                                    if cbi == bi:
                                        merged_list.append(dict(c))
                        configuration = {i: c for i, c in enumerate(merged_list)}
                        BluraySubtitle._configuration_default_chapter_segments_checked(configuration)
                self._selected_main_mpls_prev = current_set
                if configuration:
                    # Keep table2 regeneration, but reconnect main-toggle path to incremental table3 updates.
                    self.on_configuration(configuration, update_sp_table=False)
                    # Recompute SP rows only for affected volumes using existing incremental methods.
                    for folder_norm in sorted(affected):
                        bdmv_index = self._bdmv_index_for_table1_folder_norm(folder_norm)
                        if bdmv_index <= 0:
                            continue
                        prev_mains = set(prev_folder_mains.get(folder_norm, set()))
                        cur_mains = set(cur_folder_mains.get(folder_norm, set()))
                        to_add_sp = sorted(prev_mains - cur_mains)
                        to_remove_sp = sorted(cur_mains - prev_mains)

                        for mpls_no_ext in to_add_sp:
                            try:
                                self._add_or_update_table3_mpls_as_sp(int(bdmv_index), str(mpls_no_ext) + '.mpls')
                            except Exception:
                                print_exc_terminal()
                        for mpls_no_ext in to_remove_sp:
                            try:
                                self._remove_table3_rows_for_main_mpls(int(bdmv_index), str(mpls_no_ext) + '.mpls')
                            except Exception:
                                print_exc_terminal()
                    try:
                        self._recompute_sp_output_names()
                    except Exception:
                        pass
                else:
                    self.table2.setRowCount(0)
                    self.refresh_sp_table({})
            except Exception:
                print_exc_terminal()

        def _remove_table3_rows_for_main_mpls(self, bdmv_index: int, mpls_path: str):
            """Remove table3 rows that correspond to a now-selected main MPLS."""
            if not hasattr(self, 'table3') or not self.table3:
                return
            if self.table3.columnCount() <= 0:
                return
            try:
                bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                out_col = ENCODE_SP_LABELS.index('output_name')
            except Exception:
                return
            try:
                chapter = Chapter(mpls_path)
                idx_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
                ordered: list[str] = []
                for k in sorted(idx_to_m2ts.keys()):
                    v = str(idx_to_m2ts.get(k) or '').strip()
                    if v and v not in ordered:
                        ordered.append(v)
                target_m2ts = ','.join(ordered)
            except Exception:
                target_m2ts = ''
            target_mpls = os.path.basename(mpls_path)
            for r in range(self.table3.rowCount() - 1, -1, -1):
                try:
                    rb = int(self.table3.item(r, bdmv_col).text().strip()) if self.table3.item(r, bdmv_col) else 0
                except Exception:
                    rb = 0
                if rb != int(bdmv_index):
                    continue
                rm = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
                if rm != target_mpls:
                    continue
                out_item = self.table3.item(r, out_col)
                if self._is_auto_chapter_segment_sp_item(out_item):
                    continue
                r2 = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                if target_m2ts and r2 != target_m2ts:
                    continue
                self.table3.removeRow(r)

        @staticmethod
        def _parse_display_time_to_seconds(s: str) -> float:
            try:
                parts = [p for p in str(s or '').strip().split(':') if p != '']
                if not parts:
                    return 0.0
                val = 0.0
                for n in parts:
                    val = val * 60.0 + float(n)
                return val
            except Exception:
                return 0.0

        def _table1_bluray_folder_order(self) -> list[str]:
            out: list[str] = []
            try:
                for r in range(self.table1.rowCount()):
                    it = self.table1.item(r, 0)
                    if it and str(it.text() or '').strip():
                        out.append(os.path.normpath(it.text().strip()))
            except Exception:
                pass
            return out

        def _update_main_row_play_button(self):
            subtitle = self._has_subtitle_in_table2()
            for bdmv_index in range(self.table1.rowCount()):
                info: QTableWidget = self.table1.cellWidget(bdmv_index, 2)
                if not info:
                    continue
                for mpls_index in range(info.rowCount()):
                    main_btn: QToolButton = info.cellWidget(mpls_index, 3)
                    if main_btn and main_btn.isChecked():
                        play_btn = info.cellWidget(mpls_index, 4)
                        if play_btn:
                            play_btn.setProperty('action', 'preview' if subtitle else 'play')
                            play_btn.setText(self.t('preview') if subtitle else self.t('play'))
                            info.resizeColumnsToContents()

        def get_mkv_files_in_table_order(self):
            """
            Get mkv files from table2 in the order they are displayed (respecting sorting).
            """
            mkv_files = []
            # Get the path column index based on selected function
            if self.get_selected_function_id() == 2:
                path_col = 0  # MKV_LABELS = ['path', 'duration']
                sort_col = 0
            else:
                path_col = 1  # SUBTITLE_LABELS = ['select', 'path', ...]
                sort_col = 1

            # Get all rows with their data
            rows_data = []
            for row_index in range(self.table2.rowCount()):
                item = self.table2.item(row_index, path_col)
                if item and item.text():
                    rows_data.append((row_index, item.text()))

            # Check if table is sorted on path column
            sort_column = self.table2.horizontalHeader().sortIndicatorSection()
            sort_order = self.table2.horizontalHeader().sortIndicatorOrder()

            # If sorted on path column, sort rows_data accordingly
            if sort_column == sort_col:
                rows_data.sort(key=lambda x: x[1], reverse=(sort_order == Qt.SortOrder.DescendingOrder))

            # Extract the sorted mkv file paths
            for _, path in rows_data:
                if path:
                    mkv_files.append(path)

            return mkv_files

        def on_bdmv_folder_path_change(self):
            raw = self.bdmv_folder_path.text()
            bdmv_path = self._normalize_path_input(raw)
            if raw.strip().startswith('file://') and bdmv_path and bdmv_path != raw.strip():
                try:
                    self.bdmv_folder_path.blockSignals(True)
                    self.bdmv_folder_path.setText(bdmv_path)
                finally:
                    self.bdmv_folder_path.blockSignals(False)
            try:
                if hasattr(self, 'output_folder_path') and self.output_folder_path:
                    auto_output = os.path.normpath(os.path.dirname(bdmv_path)) if bdmv_path else ''
                    current_output = self.output_folder_path.text().strip()
                    last_auto = getattr(self, '_auto_output_folder', '')
                    if current_output == '' or current_output == last_auto:
                        self._auto_output_folder = auto_output
                        if auto_output:
                            self.output_folder_path.setText(auto_output)
                        else:
                            self.output_folder_path.clear()
            except Exception:
                pass
            table_ok = False
            if bdmv_path:
                try:
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
                    table1_labels = DIY_BDMV_LABELS if self.get_selected_function_id() == 5 else BDMV_LABELS
                    self.table1.setColumnCount(len(table1_labels))
                    self._set_table_headers(self.table1, table1_labels)
                    i = 0
                    for root, dirs, files in os.walk(bdmv_path):
                        dirs.sort()  # Sort dirs to ensure consistent order on all platforms
                        if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                            i += 1
                        if (time.time() - start_ts) >= 2.0:
                            QCoreApplication.processEvents()
                    self.table1.setRowCount(i)
                    i = 0
                    for root, dirs, files in os.walk(bdmv_path):
                        dirs.sort()  # Sort dirs to ensure consistent order on all platforms
                        if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                            table_widget = QTableWidget()
                            self._set_compact_table(table_widget, row_height=20, header_height=20)
                            info_headers = ['mpls_file', 'duration', 'chapters', 'main', 'play']
                            if self.get_selected_function_id() in (3, 4, 5):
                                info_headers.append('tracks')
                            table_widget.setColumnCount(len(info_headers))
                            self._set_table_headers(table_widget, info_headers)
                            mpls_files = sorted(
                                [f for f in os.listdir(os.path.join(root, 'BDMV', 'PLAYLIST')) if f.endswith('.mpls')])
                            table_widget.setRowCount(len(mpls_files))
                            mpls_n = 0
                            checked = False
                            if self.get_selected_function_id() == 1:
                                stream_dir = os.path.join(root, 'BDMV', 'STREAM')
                                if not os.path.isdir(stream_dir):
                                    checked = True
                                else:
                                    try:
                                        checked = not any(
                                            f.lower().endswith('.m2ts') for f in os.listdir(stream_dir)
                                        )
                                    except Exception:
                                        checked = True
                            selected_mpls = os.path.normpath(BluraySubtitle(root).get_main_mpls(root, checked))
                            for mpls_file in mpls_files:
                                table_widget.setItem(mpls_n, 0, QTableWidgetItem(mpls_file))
                                mpls_path = os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_file))
                                total_time = Chapter(mpls_path).get_total_time()
                                total_time_str = get_time_str(total_time)
                                table_widget.setItem(mpls_n, 1, QTableWidgetItem(total_time_str))
                                btn1 = QToolButton()
                                btn1.setText(self.t('view chapters'))
                                btn1.clicked.connect(
                                    partial(self.on_button_click, mpls_path, mpls_path == selected_mpls, i + 1))
                                table_widget.setCellWidget(mpls_n, 2, btn1)
                                btn2 = QToolButton()
                                btn2.setCheckable(True)
                                btn2.setChecked(mpls_path == selected_mpls)
                                btn2.clicked.connect(partial(self.on_button_main, mpls_path))
                                table_widget.setCellWidget(mpls_n, 3, btn2)
                                btn3 = QToolButton()
                                btn3.setText(self.t('play'))
                                btn3.setProperty('action', 'play')
                                btn3.clicked.connect(partial(self.on_button_play, mpls_path, btn3))
                                table_widget.setCellWidget(mpls_n, 4, btn3)
                                if self.get_selected_function_id() in (3, 4, 5):
                                    show_tracks = (mpls_path == selected_mpls)
                                    if self.get_selected_function_id() == 5:
                                        is_simple_diy = bool(getattr(self, 'diy_simple_radio', None) and self.diy_simple_radio.isChecked())
                                    show_tracks = is_simple_diy
                                    btn4 = QToolButton()
                                    btn4.setText(self.t('edit tracks'))
                                    if show_tracks:
                                        btn4.clicked.connect(partial(self.on_edit_tracks_from_mpls, mpls_path))
                                    else:
                                        btn4.setEnabled(False)
                                    table_widget.setCellWidget(mpls_n, 5, btn4)
                                table_widget.resizeColumnsToContents()
                                mpls_n += 1
                                if (time.time() - start_ts) >= 2.0:
                                    QCoreApplication.processEvents()
                            self.table1.setItem(i, 0, FilePathTableWidgetItem(os.path.normpath(root)))
                            self.table1.setItem(i, 1, QTableWidgetItem(get_folder_size(root)))
                            self.table1.setCellWidget(i, 2, table_widget)
                            if self.get_selected_function_id() in (3, 4):
                                resolved_bdmv_index = self._resolve_bdmv_index_for_main_mpls(selected_mpls, i + 1)
                                cmd_text = self._build_main_remux_cmd_template(selected_mpls, resolved_bdmv_index, root)
                                self.table1.setCellWidget(i, BDMV_LABELS.index('remux_cmd'),
                                                          self._create_main_remux_cmd_editor(cmd_text, self.table1))
                            elif self.get_selected_function_id() not in (3, 4, 5):
                                self.table1.setItem(i, BDMV_LABELS.index('remux_cmd'), QTableWidgetItem(''))
                            self.table1.setRowHeight(i, 100)
                            i += 1
                            if (time.time() - start_ts) >= 2.0:
                                QCoreApplication.processEvents()
                    self.table1.resizeColumnsToContents()
                    if self.get_selected_function_id() in (3, 4):
                        self.table1.setColumnWidth(2, 620 if getattr(self, '_language_code',
                                                                     CURRENT_UI_LANGUAGE) == 'zh' else 560)
                        self.table1.setColumnWidth(3, 420 if getattr(self, '_language_code',
                                                                     CURRENT_UI_LANGUAGE) == 'zh' else 380)
                    elif self.get_selected_function_id() == 5:
                        self.table1.setColumnWidth(2, 620 if getattr(self, '_language_code',
                                                                     CURRENT_UI_LANGUAGE) == 'zh' else 560)
                    else:
                        self.table1.setColumnWidth(2, 420 if getattr(self, '_language_code',
                                                                     CURRENT_UI_LANGUAGE) == 'zh' else 370)
                        self.table1.setColumnWidth(3, 0)
                    self._scroll_table_h_to_right(self.table1)
                    table_ok = True
                    try:
                        show_timer.stop()
                        progress_dialog.close()
                        progress_dialog.deleteLater()
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        show_timer.stop()
                        progress_dialog.close()
                        progress_dialog.deleteLater()
                    except Exception:
                        pass
                    self.table1.clear()
                    table1_labels = DIY_BDMV_LABELS if self.get_selected_function_id() == 5 else BDMV_LABELS
                    self.table1.setColumnCount(len(table1_labels))
                    self._set_table_headers(self.table1, table1_labels)
                    self.table1.setRowCount(0)
            if bdmv_path and table_ok and self.get_selected_function_id() in (3, 4, 5):
                self._refresh_track_selection_config_for_selected_main()
            self.altered = True
            if self.get_selected_function_id() in (3, 4, 5) and bdmv_path and table_ok:
                if self._is_movie_mode():
                    self._refresh_movie_table2()
                else:
                    configuration = BluraySubtitle(
                        self.bdmv_folder_path.text(),
                        [],
                        self.checkbox1.isChecked(),
                        None,
                        approx_episode_duration_seconds=self._get_approx_episode_duration_seconds()
                    ).generate_configuration(self.table1)
                    self.on_configuration(configuration)

        def remux_episodes(self):
            output_folder = os.path.normpath(self.output_folder_path.text().strip()) if hasattr(self,
                                                                                                'output_folder_path') else ''
            if not output_folder:
                QMessageBox.information(self, " ", "Output folder is not selected")
                return
            if not os.path.isdir(output_folder):
                QMessageBox.information(self, " ", "Output folder does not exist")
                return
            find_mkvtoolinx()

            cancel_event = threading.Event()
            self._current_cancel_event = cancel_event
            self._exe_button_default_text = self.exe_button.text()
            self._update_exe_button_progress(0, 'Preparing')

            sub_files = [self.table2.item(i, 0).text() for i in range(0, self.table2.rowCount()) if self.table2.item(i, 0)]
            episode_output_names = self._get_episode_output_names_from_table2()
            episode_subtitle_languages = self._get_episode_subtitle_languages_from_table2()
            sp_entries = []
            if hasattr(self, 'table3'):
                for i in range(self.table3.rowCount()):
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

            self._remux_thread = QThread(self)
            self._remux_worker = RemuxWorker(
                self.bdmv_folder_path.text(),
                sub_files,
                self.checkbox1.isChecked(),
                output_folder,
                configuration,
                selected_mpls,
                cancel_event,
                sp_entries,
                episode_output_names,
                episode_subtitle_languages,
                movie_mode=self._is_movie_mode(),
                track_selection_config=getattr(self, '_track_selection_config', {})
            )
            self._remux_worker.moveToThread(self._remux_thread)
            self._remux_thread.started.connect(self._remux_worker.run)
            self._remux_worker.progress.connect(self._on_exe_button_progress_value)
            self._remux_worker.label.connect(self._on_exe_button_progress_text)

            def cleanup():
                self._current_cancel_event = None
                self._reset_exe_button()
                self.exe_button.setEnabled(True)
                if hasattr(self, '_remux_thread') and self._remux_thread:
                    self._remux_thread.quit()
                    self._remux_thread.wait()
                    self._remux_thread.deleteLater()
                    self._remux_thread = None
                if hasattr(self, '_remux_worker') and self._remux_worker:
                    self._remux_worker.deleteLater()
                    self._remux_worker = None

            def on_finished():
                cleanup()
                self._show_bottom_message('Blu-ray remux completed!')

            def on_canceled():
                cleanup()

            def on_failed(message: str):
                cleanup()
                self._show_error_dialog(message)

            self._remux_worker.finished.connect(on_finished)
            self._remux_worker.canceled.connect(on_canceled)
            self._remux_worker.failed.connect(on_failed)
            self._remux_thread.start()
            return
