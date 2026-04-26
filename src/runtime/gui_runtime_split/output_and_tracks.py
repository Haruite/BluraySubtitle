"""Target module for output naming and track methods of `BluraySubtitleGUI`."""
import json
import os
import re
import subprocess
import xml.etree.ElementTree as et
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QTableWidgetItem, QTableWidget, QToolButton

from src.bdmv import M2TS
from src.core import REMUX_LABELS, DIY_REMUX_LABELS, ENCODE_LABELS, CURRENT_UI_LANGUAGE, FFPROBE_PATH, ENCODE_SP_LABELS
from src.runtime.services import BluraySubtitle
from .gui_base import BluraySubtitleGuiBase


class OutputTracksMixin(BluraySubtitleGuiBase):
        def _resolve_output_name_from_mpls(self, mpls_no_ext: str) -> str:
            mpls_path = mpls_no_ext + '.mpls'
            meta_folder = os.path.join(os.path.join(mpls_path[:-19], 'META', 'DL'))
            output_name = ''
            if not os.path.exists(meta_folder):
                output_name = os.path.split(mpls_path[:-24])[-1]
            else:
                for filename in os.listdir(meta_folder):
                    if filename == 'bdmt_eng.xml':
                        try:
                            tree = et.parse(os.path.join(meta_folder, filename))
                            _folder = tree.getroot()
                            ns = {'di': 'urn:BDA:bdmv;discinfo'}
                            output_name = _folder.find('.//di:name', ns).text
                            break
                        except (et.ParseError, FileNotFoundError):
                            continue
                if not output_name:
                    for filename in os.listdir(meta_folder):
                        if filename == 'bdmt_zho.xml':
                            try:
                                tree = et.parse(os.path.join(meta_folder, filename))
                                _folder = tree.getroot()
                                ns = {'di': 'urn:BDA:bdmv;discinfo'}
                                output_name = _folder.find('.//di:name', ns).text
                                break
                            except (et.ParseError, FileNotFoundError):
                                continue
                if not output_name:
                    for filename in os.listdir(meta_folder):
                        try:
                            tree = et.parse(os.path.join(meta_folder, filename))
                            _folder = tree.getroot()
                            ns = {'di': 'urn:BDA:bdmv;discinfo'}
                            output_name = _folder.find('.//di:name', ns).text
                            break
                        except (et.ParseError, FileNotFoundError):
                            continue
                if not output_name:
                    output_name = os.path.split(mpls_path[:-24])[-1]
            char_map = {
                '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'", '/': '／', '\\': '／', '|': '￨'
            }
            return ''.join(char_map.get(char) or char for char in output_name)

        def _build_episode_output_name_map(self, configuration: dict[int, dict[str, int | str]]) -> dict[int, str]:
            if not configuration:
                return {}
            total = len(configuration)
            width = len(str(total))
            by_bdmv: dict[int, list[int]] = {}
            for sub_index, con in configuration.items():
                try:
                    bdmv_index = int(con.get('bdmv_index') or 0)
                except Exception:
                    bdmv_index = 0
                by_bdmv.setdefault(bdmv_index, []).append(sub_index)
            for bdmv_index in by_bdmv:
                by_bdmv[bdmv_index].sort(key=lambda i: int(configuration[i].get('chapter_index') or 0))

            result: dict[int, str] = {}
            for sub_index in sorted(configuration.keys()):
                con = configuration[sub_index]
                try:
                    bdmv_index = int(con.get('bdmv_index') or 0)
                except Exception:
                    bdmv_index = 0
                bdmv_vol = f'{bdmv_index:03d}'
                rows_in_vol = by_bdmv.get(bdmv_index, [])
                try:
                    seq_in_vol = rows_in_vol.index(sub_index) + 1
                except Exception:
                    seq_in_vol = 1
                output_name = str(con.get('disc_output_name') or '').strip()
                if not output_name:
                    output_name = self._resolve_output_name_from_mpls(str(con.get('selected_mpls') or ''))
                ep_no = f'EP{str(sub_index + 1).zfill(width)}'
                result[sub_index] = f'{ep_no} {output_name}_BD_Vol_{bdmv_vol}-{seq_in_vol:03d}.mkv'
            return result

        def _get_episode_output_names_from_table2(self) -> list[str]:
            names: list[str] = []
            function_id = self.get_selected_function_id()
            if function_id == 3:
                col = REMUX_LABELS.index('output_name')
            elif function_id == 5:
                return names
            elif function_id == 4:
                col = ENCODE_LABELS.index('output_name')
            else:
                return names
            auto_name_map: dict[int, str] = {}
            try:
                if function_id in (3, 4, 5) and (not self._is_movie_mode()):
                    conf = getattr(self, '_last_configuration_34', None)
                    if isinstance(conf, dict) and conf:
                        auto_name_map = self._build_episode_output_name_map(conf)
            except Exception:
                auto_name_map = {}
            for i in range(self.table2.rowCount()):
                item = self.table2.item(i, col)
                text = item.text().strip() if item and item.text() else ''
                if (not text) and i in auto_name_map:
                    text = auto_name_map.get(i, '')
                names.append(text)
            return names

        def _get_episode_subtitle_languages_from_table2(self) -> list[str]:
            langs: list[str] = []
            function_id = self.get_selected_function_id()
            if function_id == 3:
                col = REMUX_LABELS.index('language')
            elif function_id == 5:
                col = DIY_REMUX_LABELS.index('language')
            elif function_id == 4:
                col = ENCODE_LABELS.index('language')
            else:
                return langs
            default_lang = 'eng' if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh' else 'chi'
            for i in range(self.table2.rowCount()):
                w = self.table2.cellWidget(i, col)
                if isinstance(w, QComboBox):
                    v = w.currentText().strip()
                else:
                    it = self.table2.item(i, col)
                    v = it.text().strip() if it and it.text() else ''
                langs.append(v or default_lang)
            return langs

        def _video_frame_count(self, media_path: str) -> int:
            if not media_path or not os.path.exists(media_path):
                return -1
            if str(media_path).lower().endswith('.m2ts'):
                try:
                    return int(M2TS(media_path).get_total_frames())
                except Exception:
                    return -1
            cmd = (f'"{FFPROBE_PATH}" -v error -count_frames -select_streams v:0 '
                   f'-show_entries stream=nb_read_frames,nb_frames -of json "{media_path}"')
            try:
                p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                if p.returncode != 0:
                    return -1
                data = json.loads(p.stdout or '{}')
                streams = data.get('streams') or []
                if not streams:
                    return 0
                s0 = streams[0] if isinstance(streams[0], dict) else {}
                for k in ('nb_read_frames', 'nb_frames'):
                    try:
                        v = int(str(s0.get(k) or '').strip())
                        if v >= 0:
                            return v
                    except Exception:
                        pass
            except Exception:
                pass
            return -1

        def _table3_get_sp_entry_for_row(self, row: int) -> dict[str, int | str]:
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
            type_col = ENCODE_SP_LABELS.index('m2ts_type')
            out_col = ENCODE_SP_LABELS.index('output_name')
            sel_col = ENCODE_SP_LABELS.index('select')
            bdmv_item = self.table3.item(row, bdmv_col)
            mpls_item = self.table3.item(row, mpls_col)
            m2ts_item = self.table3.item(row, m2ts_col)
            type_item = self.table3.item(row, type_col)
            out_item = self.table3.item(row, out_col)
            sel_item = self.table3.item(row, sel_col)
            try:
                bi = int(bdmv_item.text()) if bdmv_item and bdmv_item.text() else 0
            except Exception:
                bi = 0
            bdmv_root = ''
            if bi > 0:
                try:
                    bdmv_root = str(self._get_disc_root_for_bdmv_index(bi) or '').strip()
                except Exception:
                    bdmv_root = ''
            return {
                'bdmv_index': bi,
                'mpls_file': mpls_item.text().strip() if mpls_item and mpls_item.text() else '',
                'm2ts_file': m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else '',
                'm2ts_type': type_item.text().strip() if type_item and type_item.text() else '',
                'output_name': out_item.text().strip() if out_item and out_item.text() else '',
                'selected': bool(
                    sel_item and sel_item.flags() & Qt.ItemFlag.ItemIsEnabled and sel_item.checkState() == Qt.CheckState.Checked),
                'bdmv_root': bdmv_root,
            }

        def _recompute_sp_output_names(self, only_bdmv_index: Optional[int] = None):
            if not hasattr(self, 'table3') or not self.table3:
                return
            out_col = ENCODE_SP_LABELS.index('output_name')
            sel_col = ENCODE_SP_LABELS.index('select')
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
            type_col = ENCODE_SP_LABELS.index('m2ts_type')
            rows_by_vol: dict[int, list[int]] = {}
            for r in range(self.table3.rowCount()):
                try:
                    bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
                except Exception:
                    bdmv_index = 0
                rows_by_vol.setdefault(bdmv_index, []).append(r)
            if only_bdmv_index is not None:
                rows_by_vol = {k: v for k, v in rows_by_vol.items() if int(k) == int(only_bdmv_index)}

            audio_only_cache: dict[tuple[int, str], bool] = {}
            single_audio_ext_cache: dict[tuple[int, str, str], str] = {}
            single_sub_ext_cache: dict[tuple[int, str, str], str] = {}
            for bdmv_index, rows in rows_by_vol.items():
                selected_rows = []
                for r in rows:
                    it = self.table3.item(r, sel_col)
                    if it and it.flags() & Qt.ItemFlag.ItemIsEnabled and it.checkState() == Qt.CheckState.Checked:
                        selected_rows.append(r)
                digits = max(2, len(str(max(len(selected_rows), 1))))
                seq = 0
                for r in rows:
                    out_item = self.table3.item(r, out_col)
                    if not out_item:
                        out_item = QTableWidgetItem('')
                        self.table3.setItem(r, out_col, out_item)
                    sel_it = self.table3.item(r, sel_col)
                    selected = bool(
                        sel_it and sel_it.flags() & Qt.ItemFlag.ItemIsEnabled and sel_it.checkState() == Qt.CheckState.Checked)
                    bdmv_vol = f'{bdmv_index:03d}'
                    special = str(out_item.data(Qt.ItemDataRole.UserRole + 2) or '')
                    name_suffix = str(out_item.data(Qt.ItemDataRole.UserRole + 3) or '')
                    mpls_file = self.table3.item(r, mpls_col).text().strip() if self.table3.item(r, mpls_col) else ''
                    m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                    m2ts_type = self.table3.item(r, type_col).text().strip() if self.table3.item(r, type_col) else ''
                    m2ts_files = [x.strip() for x in m2ts_text.split(',') if x.strip()]
                    m2ts_files_unique = list(dict.fromkeys(m2ts_files))
                    if not selected:
                        out_item.setText('')
                        continue
                    seq += 1
                    sp_no = str(seq).zfill(digits)
                    base_name = f'BD_Vol_{bdmv_vol}_SP{sp_no}'
                    if not mpls_file and m2ts_files:
                        base_name = f'BD_Vol_{bdmv_vol}_{os.path.splitext(os.path.basename(m2ts_files[0]))[0]}'
                    # Preserve custom suffix (e.g. chapter range suffix) across track edits and recompute.
                    if (not name_suffix) and mpls_file:
                        try:
                            cur_name = out_item.text().strip()
                            cur_stem = os.path.splitext(cur_name)[0]
                            m = re.match(r'^BD_Vol_\d+_SP\d+(.*)$', cur_stem)
                            if m and m.group(1):
                                name_suffix = m.group(1)
                                out_item.setData(Qt.ItemDataRole.UserRole + 3, name_suffix)
                        except Exception:
                            pass
                    base_with_suffix = f'{base_name}{name_suffix}'
                    # Table may list multiple m2ts while scan mis-tagged single_frame (e.g. large clips); folder output matches mux.
                    eff_special = special
                    if special == 'single_frame' and len(m2ts_files_unique) > 1:
                        eff_special = 'multi_frame'
                        try:
                            out_item.setData(Qt.ItemDataRole.UserRole + 2, 'multi_frame')
                        except Exception:
                            pass
                    if eff_special == 'single_frame':
                        out_item.setText(f'{base_with_suffix}.png')
                        continue
                    if eff_special == 'multi_frame':
                        out_item.setText(f'{base_with_suffix}')
                        continue
                    if (not mpls_file) and m2ts_type == 'igs_menu':
                        out_item.setText(f'{base_with_suffix}')
                        continue
                    # Zero-duration menu rows should use folder name (no extension),
                    # extracted by extract_igs_menu_png.
                    # Keep this robust for both:
                    # 1) direct single m2ts rows
                    # 2) mpls rows that include multiple one-frame m2ts clips
                    if (
                            ((not mpls_file) and len(m2ts_files_unique) == 1)
                            or (mpls_file and len(m2ts_files_unique) > 1)
                    ):
                        try:
                            d_item = self.table3.item(r, ENCODE_SP_LABELS.index('duration'))
                            d_sec = self._parse_display_time_to_seconds(d_item.text() if d_item else '')
                        except Exception:
                            d_sec = 0.0
                        if d_sec <= 0.0:
                            out_item.setText(f'{base_with_suffix}')
                            continue
                    key = BluraySubtitle._sp_track_key_from_entry(self._table3_get_sp_entry_for_row(r))
                    cfg = getattr(self, '_track_selection_config', {}) or {}
                    if not (isinstance(cfg, dict) and key in cfg):
                        # Undetermined multi-m2ts MPLS row: wait for async scan result
                        # (single_frame/multi_frame) before showing output name.
                        if mpls_file and len(m2ts_files_unique) > 1 and (special == ''):
                            out_item.setText('')
                        else:
                            out_item.setText(f'{base_with_suffix}.mkv')
                        continue
                    tr = cfg.get(key, {}) if isinstance(cfg, dict) else {}
                    sel_audio = list(tr.get('audio') or [])
                    sel_sub = list(tr.get('subtitle') or [])
                    if (not sel_audio) and (not sel_sub):
                        out_item.setText('')
                        continue
                    is_audio_only = False
                    if m2ts_files:
                        src = os.path.join(self._get_stream_dir_for_bdmv_index(bdmv_index), m2ts_files[0])
                        cache_key = (int(bdmv_index), os.path.normpath(src))
                        if cache_key in audio_only_cache:
                            is_audio_only = bool(audio_only_cache[cache_key])
                        else:
                            is_audio_only = BluraySubtitle._is_audio_only_media(src)
                            audio_only_cache[cache_key] = bool(is_audio_only)
                    if len(sel_audio) == 1 and len(sel_sub) == 0 and is_audio_only:
                        # Single audio -> extract raw elementary stream.
                        ext = 'audio'
                        if m2ts_files:
                            src = os.path.join(self._get_stream_dir_for_bdmv_index(bdmv_index), m2ts_files[0])
                            ext_cache_key = (int(bdmv_index), os.path.normpath(src), str(sel_audio[0]))
                            if ext_cache_key in single_audio_ext_cache:
                                ext = str(single_audio_ext_cache[ext_cache_key] or 'audio')
                            else:
                                if str(src).lower().endswith('.m2ts'):
                                    streams = self._read_m2ts_track_info(src)
                                else:
                                    streams = self._read_media_streams_local(src)
                                for s in streams:
                                    if str(s.get('codec_type') or '') != 'audio':
                                        continue
                                    if str(s.get('index', '')) == str(sel_audio[0]):
                                        c = str(s.get('codec_name') or '').lower()
                                        if c in ('pcm_bluray', 'pcm_s16le', 'pcm_s24le', 'pcm_s32le', 'dts', 'truehd',
                                                 'mlp'):
                                            ext = 'flac'
                                        else:
                                            ext = {'aac': 'm4a'}.get(c, c or 'audio')
                                        break
                                single_audio_ext_cache[ext_cache_key] = ext
                        out_item.setText(f'{base_with_suffix}.{ext}')
                        continue
                    if len(sel_audio) > 1 and len(sel_sub) == 0 and is_audio_only:
                        out_item.setText(f'{base_with_suffix}.mka')
                        continue
                    if not mpls_file:
                        if m2ts_type in ('private_or_other', 'mixed_non_video'):
                            out_item.setText('')
                            continue
                        if m2ts_type == 'audio_with_subtitle':
                            out_item.setText(f'{base_with_suffix}.mka')
                            continue
                        if m2ts_type == 'subtitle_only':
                            if len(sel_sub) <= 0:
                                out_item.setText('')
                                continue
                            if len(sel_sub) == 1:
                                ext = 'sup'
                                if m2ts_files:
                                    src = os.path.join(self._get_stream_dir_for_bdmv_index(bdmv_index), m2ts_files[0])
                                    ext_cache_key = (int(bdmv_index), os.path.normpath(src), str(sel_sub[0]))
                                    if ext_cache_key in single_sub_ext_cache:
                                        ext = str(single_sub_ext_cache[ext_cache_key] or 'sup')
                                    else:
                                        streams = self._read_m2ts_track_info(src) if str(src).lower().endswith(
                                            '.m2ts') else self._read_media_streams_local(src)
                                        for s in streams:
                                            if str(s.get('codec_type') or '') != 'subtitle':
                                                continue
                                            if str(s.get('index', '')) == str(sel_sub[0]):
                                                c = str(s.get('codec_name') or '').lower()
                                                if c in ('subrip', 'srt'):
                                                    ext = 'srt'
                                                else:
                                                    ext = 'sup'
                                                break
                                        single_sub_ext_cache[ext_cache_key] = ext
                                out_item.setText(f'{base_with_suffix}.{ext}')
                                continue
                            out_item.setText(f'{base_with_suffix}.mks')
                            continue
                    out_item.setText(f'{base_with_suffix}.mkv')

        def _all_track_ids_from_streams(self, streams: list[dict[str, object]]) -> tuple[list[str], list[str]]:
            audio: list[str] = []
            subtitle: list[str] = []
            for s in streams or []:
                idx = str(s.get('index', '')).strip()
                if idx == '':
                    continue
                ctype = str(s.get('codec_type') or '')
                if ctype == 'audio':
                    audio.append(idx)
                elif ctype == 'subtitle':
                    subtitle.append(idx)
            return audio, subtitle

        def _apply_select_all_tracks_to_main_and_sp(self):
            if not hasattr(self, '_track_selection_config') or not isinstance(
                    getattr(self, '_track_selection_config', None), dict):
                self._track_selection_config = {}
            if not getattr(self, 'select_all_tracks_checkbox', None) or (not self.select_all_tracks_checkbox.isChecked()):
                return
            if self.get_selected_function_id() == 4 and getattr(self, '_encode_input_mode', 'bdmv') == 'remux':
                try:
                    for r in range(self.table2.rowCount()):
                        src = self._get_remux_source_path_from_table2_row(r)
                        if not src or not os.path.exists(src):
                            continue
                        streams = self._read_mkvinfo_tracks(src)
                        a, s = self._all_track_ids_from_streams(streams)
                        self._track_selection_config[f'mkv::{os.path.normpath(src)}'] = {'audio': a, 'subtitle': s}
                except Exception:
                    pass
                try:
                    if hasattr(self, 'table3') and self.table3:
                        for r in range(self.table3.rowCount()):
                            src = self._get_remux_source_path_from_table3_row(r)
                            if not src or not os.path.exists(src):
                                continue
                            streams = self._read_mkvinfo_tracks(src)
                            a, s = self._all_track_ids_from_streams(streams)
                            self._track_selection_config[f'mkvsp::{os.path.normpath(src)}'] = {'audio': a, 'subtitle': s}
                except Exception:
                    pass
                return
            try:
                for row in range(self.table1.rowCount()):
                    root_item = self.table1.item(row, 0)
                    root = root_item.text().strip() if root_item and root_item.text() else ''
                    if not root:
                        continue
                    info = self.table1.cellWidget(row, 2)
                    if not isinstance(info, QTableWidget):
                        continue
                    selected_mpls_path = ''
                    for i in range(info.rowCount()):
                        main_btn = info.cellWidget(i, 3)
                        if isinstance(main_btn, QToolButton) and main_btn.isChecked():
                            mpls_item = info.item(i, 0)
                            if mpls_item and mpls_item.text().strip():
                                selected_mpls_path = os.path.normpath(
                                    os.path.join(root, 'BDMV', 'PLAYLIST', mpls_item.text().strip()))
                            break
                    if not selected_mpls_path:
                        continue
                    m2ts_path = self._get_first_m2ts_for_mpls(selected_mpls_path)
                    if not m2ts_path:
                        continue
                    streams = self._read_m2ts_track_info(m2ts_path)
                    a, s = self._all_track_ids_from_streams(streams)
                    self._track_selection_config[f'main::{os.path.normpath(selected_mpls_path)}'] = {'audio': a,
                                                                                                     'subtitle': s}
            except Exception:
                pass

            try:
                if hasattr(self, 'table3') and self.table3 and self.table3.isVisible() and ('select' in ENCODE_SP_LABELS):
                    sel_col = ENCODE_SP_LABELS.index('select')
                    bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
                    m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
                    mpls_col = ENCODE_SP_LABELS.index('mpls_file')
                    for r in range(self.table3.rowCount()):
                        it = self.table3.item(r, sel_col)
                        if not (it and it.flags() & Qt.ItemFlag.ItemIsEnabled and it.checkState() == Qt.CheckState.Checked):
                            continue
                        try:
                            bdmv_index = int(self.table3.item(r, bdmv_col).text().strip())
                        except Exception:
                            continue
                        stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
                        m2ts_text = self.table3.item(r, m2ts_col).text().strip() if self.table3.item(r, m2ts_col) else ''
                        m2ts_files = self._split_m2ts_files(m2ts_text)
                        if not (stream_dir and m2ts_files):
                            continue
                        first_m2ts = os.path.normpath(os.path.join(stream_dir, m2ts_files[0]))
                        streams = self._read_m2ts_track_info(first_m2ts)
                        a, s = self._all_track_ids_from_streams(streams)
                        entry = self._table3_get_sp_entry_for_row(r)
                        key = BluraySubtitle._sp_track_key_from_entry(entry)
                        self._track_selection_config[key] = {'audio': a, 'subtitle': s}
            except Exception:
                pass

            try:
                self._refresh_table1_remux_cmds()
            except Exception:
                pass
            try:
                self._recompute_sp_output_names()
            except Exception:
                pass

        def _on_select_all_tracks_toggled(self, checked: bool):
            try:
                if checked:
                    self._apply_select_all_tracks_to_main_and_sp()
            except Exception:
                pass

        def _on_table3_item_changed(self, item: QTableWidgetItem):
            if getattr(self, '_updating_sp_table', False):
                return
            if not item:
                return
            try:
                if item.column() == ENCODE_SP_LABELS.index('select'):
                    try:
                        item.setData(Qt.ItemDataRole.UserRole, 'user')
                    except Exception:
                        pass
                    self._recompute_sp_output_names()
                    try:
                        if getattr(self, 'select_all_tracks_checkbox',
                                   None) and self.select_all_tracks_checkbox.isChecked():
                            self._apply_select_all_tracks_to_main_and_sp()
                    except Exception:
                        pass
            except Exception:
                pass
