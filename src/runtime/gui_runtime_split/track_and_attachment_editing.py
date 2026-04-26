"""Target module for track/chapter/attachment editing methods."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from functools import partial
from typing import Optional

import pycountry
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QPlainTextEdit, QWidget, QHBoxLayout, QPushButton, \
    QLabel, QTableWidget, QLineEdit, QTableWidgetItem, QToolButton, QFileDialog, QHeaderView, QComboBox

from src.bdmv import Chapter
from src.core import find_mkvtoolinx, MKV_EXTRACT_PATH, MKV_PROP_EDIT_PATH, mkvtoolnix_ui_language_arg, FFPROBE_PATH, \
    MKV_INFO_PATH, MKV_MERGE_PATH, get_mkvtoolnix_ui_language, ENCODE_SP_LABELS
from src.runtime.services import BluraySubtitle
from .gui_base import BluraySubtitleGuiBase


class TrackAttachmentEditingMixin(BluraySubtitleGuiBase):
        def _iter_selected_main_mpls_paths(self) -> list[str]:
            out: list[str] = []
            if not hasattr(self, 'table1') or not self.table1:
                return out
            for r in range(self.table1.rowCount()):
                root_item = self.table1.item(r, 0)
                root = root_item.text().strip() if root_item and root_item.text() else ''
                info = self.table1.cellWidget(r, 2)
                if not root or not isinstance(info, QTableWidget):
                    continue
                for i in range(info.rowCount()):
                    main_btn = info.cellWidget(i, 3)
                    if not isinstance(main_btn, QToolButton) or (not main_btn.isChecked()):
                        continue
                    mpls_item = info.item(i, 0)
                    mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
                    if not mpls_file:
                        continue
                    out.append(os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', mpls_file)))
            return out

        def _bdmv_root_from_mpls_path(self, mpls_path: str) -> str:
            try:
                p = os.path.normpath(str(mpls_path or ''))
                # .../<root>/BDMV/PLAYLIST/*.mpls
                return os.path.normpath(os.path.dirname(os.path.dirname(os.path.dirname(p))))
            except Exception:
                return ''

        def _sync_main_mpls_track_config_by_pid(
                self,
                source_mpls_path: str,
                source_streams: list[dict[str, object]],
                source_selected_indexes: set[str],
                source_convert_map: dict[str, str],
                source_language_map: dict[str, str],
        ):
            source_path = os.path.normpath(source_mpls_path)
            source_root = self._bdmv_root_from_mpls_path(source_path)
            selected_pids: set[int] = set()
            convert_by_pid: dict[int, str] = {}
            language_by_pid: dict[int, str] = {}
            for s in source_streams:
                idx = str(s.get('index', ''))
                pid = self._parse_stream_pid(s.get('pid'))
                if pid is None:
                    continue
                ctype = str(s.get('codec_type') or '').strip().lower()
                if idx in source_selected_indexes and ctype in ('audio', 'subtitle'):
                    selected_pids.add(pid)
                cv = str(source_convert_map.get(idx, '') or '').strip()
                if cv:
                    convert_by_pid[pid] = cv
                lg = str(source_language_map.get(idx, '') or '').strip()
                if lg:
                    language_by_pid[pid] = lg

            cfg_sel = getattr(self, '_track_selection_config', {})
            cfg_conv = getattr(self, '_track_convert_config', {})
            cfg_lang = getattr(self, '_track_language_config', {})

            for target_mpls_path in self._iter_selected_main_mpls_paths():
                target_path = os.path.normpath(target_mpls_path)
                if self._bdmv_root_from_mpls_path(target_path) != source_root:
                    # Only sync within the same disc volume.
                    continue
                target_key = f'main::{target_path}'
                if target_path == source_path:
                    # Source MPLS has already been saved from the dialog result.
                    continue
                m2ts_path = self._get_first_m2ts_for_mpls(target_path)
                if not m2ts_path:
                    continue
                target_streams = self._read_m2ts_track_info(m2ts_path)

                existing_sel = cfg_sel.get(target_key) or {}
                existing_selected = set((existing_sel.get('audio') or []) + (existing_sel.get('subtitle') or []))
                existing_convert = dict(cfg_conv.get(target_key) or {})
                existing_language = dict(cfg_lang.get(target_key) or {})

                audio: list[str] = list(existing_sel.get('audio') or [])
                subtitle: list[str] = list(existing_sel.get('subtitle') or [])
                t_convert: dict[str, str] = dict(existing_convert)
                t_language: dict[str, str] = dict(existing_language)
                audio_set = set(audio)
                subtitle_set = set(subtitle)
                for st in target_streams:
                    idx = str(st.get('index', ''))
                    pid = self._parse_stream_pid(st.get('pid'))
                    ctype = str(st.get('codec_type') or '').strip().lower()
                    if pid is not None and pid in selected_pids:
                        if ctype == 'audio' and idx not in audio_set:
                            audio.append(idx)
                            audio_set.add(idx)
                        elif ctype == 'subtitle' and idx not in subtitle_set:
                            subtitle.append(idx)
                            subtitle_set.add(idx)
                    elif pid is not None and pid in set(convert_by_pid.keys()) | set(language_by_pid.keys()):
                        # Same PID exists in source but not selected now -> deselect only this PID.
                        if idx in audio_set:
                            audio = [x for x in audio if x != idx]
                            audio_set.discard(idx)
                        if idx in subtitle_set:
                            subtitle = [x for x in subtitle if x != idx]
                            subtitle_set.discard(idx)
                    if (pid is not None) and (pid in convert_by_pid):
                        t_convert[idx] = convert_by_pid[pid]
                    if (pid is not None) and (pid in language_by_pid):
                        t_language[idx] = language_by_pid[pid]

                cfg_sel[target_key] = {'audio': audio, 'subtitle': subtitle}
                cfg_conv[target_key] = t_convert
                cfg_lang[target_key] = t_language

            self._track_selection_config = cfg_sel
            self._track_convert_config = cfg_conv
            self._track_language_config = cfg_lang

        def _conversion_options_for_stream(self, stream: dict[str, object], is_mkvinfo: bool) -> list[str]:
            codec_type = str(stream.get('codec_type') or '').strip().lower()
            codec_id = str(stream.get('codec_id') or '').strip().upper()
            codec_name = str(stream.get('codec_name') or '').strip().lower()
            try:
                bit_depth = int(str(stream.get('bit_depth') or '').strip())
            except Exception:
                bit_depth = 0

            options: list[str] = [self.t('No conversion')]
            if codec_type == 'video':
                if codec_id == 'V_MPEG4/ISO/AVC' or codec_name == 'h264':
                    options.append('h264(encoded)')
                elif codec_id == 'V_MPEG4/ISO/HEVC' or codec_name == 'hevc' or codec_name == 'h265':
                    options.append('h265(encoded)')
                return options

            if codec_type != 'audio':
                return options

            is_pcm = (
                codec_id in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG')
                or codec_name in ('lpcm', 'pcm_bluray')
                or codec_name.startswith('pcm')
            )
            is_lossless = is_pcm or codec_id in ('A_TRUEHD', 'A_MLP', 'A_FLAC') or codec_id.startswith('A_DTS')
            if is_lossless:
                options.append('ac3(640 kbps)')
            if is_pcm and bit_depth > 16:
                options.append('pcm(16bit)')
                return options
            if is_lossless and (not is_pcm):
                options.append('pcm(16bit)')
                if bit_depth >= 24:
                    options.append('lpcm(24bit)')
            return options

        def _codec_name_from_codec_id(self, codec_id: str) -> str:
            cid = str(codec_id or '').strip()
            if cid.startswith('A_DTS'):
                return 'dts'
            if cid in ('A_TRUEHD', 'A_MLP'):
                return 'truehd'
            if cid in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG'):
                return 'lpcm'
            if cid == 'A_AC3':
                return 'ac3'
            if cid == 'A_EAC3':
                return 'eac3'
            if cid == 'A_FLAC':
                return 'flac'
            if cid.startswith('A_MPEG/L3'):
                return 'mp3'
            if cid.startswith('A_MPEG/L2'):
                return 'mp2'
            if cid.startswith('A_AAC'):
                return 'aac'
            return cid.lower() or ''

        def _edit_chapters_for_mkv(self, mkv_path: str):
            try:
                find_mkvtoolinx()
            except Exception:
                pass
            if not MKV_EXTRACT_PATH or not MKV_PROP_EDIT_PATH:
                QMessageBox.information(self, " ", "mkvextract or mkvpropedit not found")
                return
            tmp_dir = tempfile.mkdtemp(prefix='BluraySubtitle_chapters_')
            chapter_path = os.path.join(tmp_dir, 'chapter.txt')
            extract_cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" chapters --simple "{chapter_path}"'
            subprocess.Popen(extract_cmd, shell=True).wait()
            try:
                with open(chapter_path, 'r', encoding='utf-8-sig') as fp:
                    content = fp.read()
            except Exception:
                content = ''

            dlg = QDialog(self)
            dlg.setWindowTitle(self.t('edit chapters'))
            layout = QVBoxLayout()
            dlg.setLayout(layout)
            editor = QPlainTextEdit(dlg)
            editor.setPlainText(content)
            layout.addWidget(editor)
            btn_row = QWidget(dlg)
            btn_layout = QHBoxLayout()
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_row.setLayout(btn_layout)
            btn_save = QPushButton(self.t('Save'), dlg)
            btn_close = QPushButton(self.t('Close'), dlg)
            btn_layout.addStretch(1)
            btn_layout.addWidget(btn_save)
            btn_layout.addWidget(btn_close)
            layout.addWidget(btn_row)
            status_label = QLabel('', dlg)
            status_label.setVisible(False)
            layout.addWidget(status_label)

            def on_save():
                try:
                    with open(chapter_path, 'w', encoding='utf-8') as fp:
                        fp.write(editor.toPlainText())
                except Exception:
                    self._show_error_dialog(traceback.format_exc())
                    return
                edit_cmd = f'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" --chapters "{chapter_path}"'
                print(f'{self.t("[chapter-debug] ")}{self.t("manual chapter edit apply: ")}{chapter_path} -> {mkv_path}')
                try:
                    p = subprocess.run(edit_cmd, shell=True, capture_output=True, text=True, encoding='utf-8',
                                       errors='ignore')
                    out = (p.stdout or '') + '\n' + (p.stderr or '')
                except Exception:
                    out = traceback.format_exc()
                is_error = ('Error' in out) or ('error' in out.lower())
                if is_error:
                    status_label.setText(self.t('Save failed, please check'))
                    status_label.setStyleSheet('color:#dc2626;')
                else:
                    status_label.setText(self.t('Chapters saved!'))
                    status_label.setStyleSheet('color:#16a34a;')
                status_label.setVisible(True)
                QTimer.singleShot(3000, lambda: status_label.setVisible(False))

            btn_save.clicked.connect(on_save)
            btn_close.clicked.connect(dlg.accept)
            dlg.resize(820, 560)
            dlg.exec()

        def _extract_attachment_to_temp_and_open(self, mkv_path: str, attachment_id: str, filename: str):
            try:
                find_mkvtoolinx()
            except Exception:
                pass
            if not MKV_EXTRACT_PATH:
                QMessageBox.information(self, " ", "mkvextract not found")
                return
            aid = str(attachment_id or '').strip()
            if not aid:
                QMessageBox.information(self, " ", "Attachment ID not found")
                return
            safe_name = os.path.basename(str(filename or '').strip()) or f'attachment_{aid}.bin'
            safe_name = safe_name.replace('\\', '_').replace('/', '_')
            tmp_dir = tempfile.mkdtemp(prefix='BluraySubtitle_attach_')
            out_path = os.path.join(tmp_dir, safe_name)
            cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" attachments {aid}:"{out_path}"'
            try:
                p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                out = (p.stdout or '') + '\n' + (p.stderr or '')
                if p.returncode != 0:
                    self._show_error_dialog(out.strip() or 'mkvextract failed')
                    return
            except Exception:
                self._show_error_dialog(traceback.format_exc())
                return
            self.open_folder_path(tmp_dir)

        def _extract_track_to_temp_and_open(self, mkv_path: str, track_id: int, codec_id: str):
            try:
                find_mkvtoolinx()
            except Exception:
                pass
            if not MKV_EXTRACT_PATH:
                return
            tmp_dir = tempfile.mkdtemp(prefix='BluraySubtitle_extract_')
            ext = self._mkvextract_ext_from_codec_id(codec_id)
            out_path = os.path.join(tmp_dir, f'track{track_id}{ext}')
            cmd = f'"{MKV_EXTRACT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" tracks {track_id}:"{out_path}"'
            subprocess.Popen(cmd, shell=True).wait()
            try:
                self.open_folder_path(tmp_dir)
            except Exception:
                pass

        def _mkvextract_ext_from_codec_id(self, codec_id: str) -> str:
            cid = str(codec_id or '').strip()
            if cid.startswith('A_AAC') or cid == 'A_AAC':
                return '.aac'
            if cid in ('A_AC3', 'A_EAC3'):
                return '.ac3'
            if cid == 'A_ALAC':
                return '.caf'
            if cid == 'A_DTS':
                return '.dts'
            if cid == 'A_FLAC':
                return '.flac'
            if cid == 'A_MPEG/L2':
                return '.mp2'
            if cid == 'A_MPEG/L3':
                return '.mp3'
            if cid == 'A_OPUS':
                return '.opus'
            if cid in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG'):
                return '.wav'
            if cid in ('A_TRUEHD', 'A_MLP'):
                return '.thd'
            if cid == 'A_TTA1':
                return '.tta'
            if cid == 'A_VORBIS':
                return '.ogg'
            if cid == 'A_WAVPACK4':
                return '.wv'
            if cid == 'S_HDMV/PGS':
                return '.sup'
            if cid == 'S_HDMV/TEXTST':
                return '.textst'
            if cid in ('S_TEXT/SSA', 'S_TEXT/ASS', 'S_SSA', 'S_ASS'):
                return '.ass'
            if cid in ('S_TEXT/UTF8', 'S_TEXT/ASCII'):
                return '.srt'
            if cid == 'S_VOBSUB':
                return '.sub'
            if cid == 'S_TEXT/USF':
                return '.usf'
            if cid == 'S_TEXT/WEBVTT':
                return '.vtt'
            if cid in ('V_MPEG1', 'V_MPEG2'):
                return '.mpg'
            if cid == 'V_MPEG4/ISO/AVC':
                return '.h264'
            if cid == 'V_MPEG4/ISO/HEVC':
                return '.h265'
            if cid == 'V_MS/VFW/FOURCC':
                return '.avi'
            if cid.startswith('V_REAL/'):
                return '.rm'
            if cid == 'V_THEORA':
                return '.ogg'
            if cid in ('V_VP8', 'V_VP9'):
                return '.ivf'
            return '.bin'

        def _on_edit_tracks_from_sp_table_clicked(self):
            self.on_edit_tracks_from_sp_table(-1)

        def _parse_stream_pid(self, raw_id: object) -> Optional[int]:
            if isinstance(raw_id, int):
                return int(raw_id)
            s = str(raw_id or '').strip()
            if not s:
                return None
            try:
                if s.lower().startswith('0x'):
                    return int(s, 16)
                if any(c in 'abcdefABCDEF' for c in s):
                    return int(s, 16)
                return int(s, 10)
            except Exception:
                try:
                    return int(s, 16)
                except Exception:
                    return None

        def _pid_lang_from_m2ts_track_info(self, tracks: list[dict[str, object]]) -> dict[int, str]:
            out: dict[int, str] = {}
            for s in tracks or []:
                if not isinstance(s, dict):
                    continue
                lang = str(s.get('language_from_pmt_descriptor') or 'und').strip() or 'und'
                try:
                    pid = int(s.get('pid'))
                    out[pid] = lang
                except Exception:
                    pass
            return out

        def _pid_lang_from_streams(self, streams: list[dict[str, object]]) -> dict[int, str]:
            out: dict[int, str] = {}
            for s in streams or []:
                lang = 'und'
                try:
                    direct = s.get('lang') or s.get('language')
                    if direct:
                        lang = str(direct)
                    else:
                        tags = s.get('tags') or {}
                        if isinstance(tags, dict):
                            tag_lang = tags.get('lang') or tags.get('language')
                            if tag_lang:
                                lang = str(tag_lang)
                except Exception:
                    lang = 'und'
                pid = self._parse_stream_pid(s.get('id'))
                if pid is not None:
                    out[pid] = lang
                try:
                    idx = int(str(s.get('index') or '').strip())
                    out[idx] = lang
                except Exception:
                    pass
            return out

        def _read_m2ts_track_info(self, m2ts_path: str) -> list[dict[str, object]]:
            streams = BluraySubtitle._m2ts_track_streams(m2ts_path)
            out: list[dict[str, object]] = []
            for s in streams:
                row = dict(s)
                row['index'] = str(row.get('index', ''))
                out.append(row)
            return out

        def _read_media_streams_local(self, media_path: str) -> list[dict[str, object]]:
            if not media_path or not os.path.exists(media_path):
                return []
            exe = FFPROBE_PATH if FFPROBE_PATH else 'ffprobe'
            try:
                p = subprocess.run(
                    [exe, "-v", "error", "-show_streams", "-of", "json", media_path],
                    capture_output=True,
                    text=True,
                    shell=False
                )
            except Exception:
                return []

        def _read_mkvinfo_attachments(self, mkv_path: str) -> list[dict[str, str]]:
            if not mkv_path or not os.path.exists(mkv_path):
                return []
            try:
                find_mkvtoolinx()
            except Exception:
                pass
            if not MKV_INFO_PATH:
                return []
            try:
                ui_lang = 'en' if sys.platform == 'win32' else 'en_US'
                p = subprocess.run(
                    [MKV_INFO_PATH, mkv_path, "--ui-language", ui_lang],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    shell=False
                )
            except Exception:
                return []
            stdout = p.stdout or ''
            out: list[dict[str, str]] = []
            cur: Optional[dict[str, str]] = None
            in_attachments = False
            for raw in stdout.splitlines():
                line = raw.strip()
                if line in ('|+ Attachments', '| + Attachments', '|  + Attachments'):
                    in_attachments = True
                    continue
                if not in_attachments:
                    continue
                if line in ('| + Attached', '|  + Attached', '|+ Attached'):
                    if cur and cur.get('filename'):
                        out.append(cur)
                    cur = {'filename': '', 'mime_type': '', 'uid': '', 'file_size': '', 'id': ''}
                    continue
                if cur is None:
                    continue
                if line.startswith('|  + File name: ') or line.startswith('| + File name: ') or line.startswith(
                        '|+ File name: '):
                    cur['filename'] = line.split(':', 1)[1].strip()
                    continue
                if line.startswith('|  + MIME type: ') or line.startswith('| + MIME type: ') or line.startswith(
                        '|+ MIME type: '):
                    cur['mime_type'] = line.split(':', 1)[1].strip()
                    continue
                if line.startswith('|  + File data: size ') or line.startswith('| + File data: size ') or line.startswith(
                        '|+ File data: size '):
                    nums = re.findall(r'\d+', line)
                    cur['file_size'] = nums[0] if nums else ''
                    continue
                if line.startswith('|  + File UID: ') or line.startswith('| + File UID: ') or line.startswith(
                        '|+ File UID: '):
                    nums = re.findall(r'\d+', line)
                    cur['uid'] = nums[0] if nums else ''
                    continue
                if line.startswith('|+ ') and line not in ('|+ Attached', '|+ Attachments'):
                    if cur and cur.get('filename'):
                        out.append(cur)
                    cur = None
                    in_attachments = False
            if cur and cur.get('filename'):
                out.append(cur)
            return out

        def _read_mkvinfo_tracks(self, mkv_path: str) -> list[dict[str, object]]:
            if not mkv_path or not os.path.exists(mkv_path):
                return []
            try:
                find_mkvtoolinx()
            except Exception:
                pass
            if not MKV_INFO_PATH:
                return []
            try:
                ui_lang = 'en' if sys.platform == 'win32' else 'en_US'
                p = subprocess.run(
                    [MKV_INFO_PATH, mkv_path, "--ui-language", ui_lang],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    shell=False
                )
            except Exception:
                return []
            stdout = p.stdout or ''
            tracks: list[dict[str, object]] = []
            cur: Optional[dict[str, object]] = None

            def flush():
                nonlocal cur
                if not cur:
                    return
                track_id = cur.get('track_id')
                if track_id is None:
                    cur = None
                    return
                lang = cur.get('language') or cur.get('lang') or ''
                bcp = cur.get('bcp47') or ''
                if not lang and bcp:
                    language = pycountry.languages.get(alpha_2=str(bcp).split('-')[0])
                    if language is None:
                        language = pycountry.languages.get(alpha_3=str(bcp).split('-')[0])
                    if language:
                        lang = getattr(language, "bibliographic", getattr(language, "alpha_3", None))
                cur['language'] = str(lang or 'und')
                cur['lang'] = cur['language']
                t = str(cur.get('track_type') or '').strip().lower()
                if t == 'audio':
                    cur['codec_type'] = 'audio'
                elif t in ('subtitles', 'subtitle'):
                    cur['codec_type'] = 'subtitle'
                else:
                    cur['codec_type'] = t or 'und'
                cur['codec_id'] = str(cur.get('codec_id') or '')
                cur['codec_name'] = self._codec_name_from_codec_id(str(cur.get('codec_id') or ''))
                cur['index'] = str(track_id)
                cur['track_number'] = int(track_id)
                tracks.append(cur)
                cur = None

            for raw in stdout.splitlines():
                line = raw.strip()
                if line in ('|+ Track', '| + Track', '|  + Track'):
                    flush()
                    cur = {}
                    continue
                if cur is None:
                    continue
                if line.startswith('|  + Track number: ') or line.startswith('| + Track number: ') or line.startswith(
                        '|+ Track number: '):
                    nums = re.findall(r'\d+', line)
                    if len(nums) >= 2:
                        cur['track_number_1based'] = int(nums[0])
                        cur['track_id'] = int(nums[1])
                    elif len(nums) == 1:
                        cur['track_number_1based'] = int(nums[0])
                        cur['track_id'] = int(nums[0]) - 1
                    continue
                if line.startswith('|  + Track UID: ') or line.startswith('| + Track UID: ') or line.startswith(
                        '|+ Track UID: '):
                    v = re.findall(r'\d+', line)
                    cur['track_uid'] = v[0] if v else ''
                    continue
                if line.startswith('|  + Track type: ') or line.startswith('| + Track type: ') or line.startswith(
                        '|+ Track type: '):
                    cur['track_type'] = line.split(':', 1)[1].strip()
                    continue
                if line.startswith('|  + Language (IETF BCP 47): ') or line.startswith(
                        '| + Language (IETF BCP 47): ') or line.startswith('|+ Language (IETF BCP 47): '):
                    cur['bcp47'] = line.split(':', 1)[1].strip()
                    continue
                if (line.startswith('|  + Language: ') or line.startswith('| + Language: ') or line.startswith(
                        '|+ Language: ')) and ('Language (IETF BCP 47):' not in line):
                    cur['language'] = line.split(':', 1)[1].strip()
                    continue
                if line.startswith('|  + Codec ID: ') or line.startswith('| + Codec ID: ') or line.startswith(
                        '|+ Codec ID: '):
                    cur['codec_id'] = line.split(':', 1)[1].strip()
                    continue
                if line.startswith('|  + Default duration: ') or line.startswith(
                        '| + Default duration: ') or line.startswith('|+ Default duration: '):
                    cur['default_duration'] = line.split(':', 1)[1].strip()
                    continue
                if line.startswith('|   + Sampling frequency: ') or line.startswith(
                        '|  + Sampling frequency: ') or line.startswith('| + Sampling frequency: '):
                    v = re.findall(r'[\d.]+', line)
                    cur['sampling_frequency'] = v[0] if v else ''
                    continue
                if line.startswith('|   + Channels: ') or line.startswith('|  + Channels: ') or line.startswith(
                        '| + Channels: '):
                    v = re.findall(r'\d+', line)
                    cur['channels'] = v[0] if v else ''
                    continue
                if line.startswith('|   + Bit depth: ') or line.startswith('|  + Bit depth: ') or line.startswith(
                        '| + Bit depth: '):
                    v = re.findall(r'\d+', line)
                    cur['bit_depth'] = v[0] if v else ''
                    continue
                if line.startswith('|   + Pixel width: ') or line.startswith('|  + Pixel width: ') or line.startswith(
                        '| + Pixel width: '):
                    v = re.findall(r'\d+', line)
                    cur['pixel_width'] = v[0] if v else ''
                    continue
                if line.startswith('|   + Pixel height: ') or line.startswith('|  + Pixel height: ') or line.startswith(
                        '| + Pixel height: '):
                    v = re.findall(r'\d+', line)
                    cur['pixel_height'] = v[0] if v else ''
                    continue

            flush()
            return tracks

        def _read_mkvmerge_attachment_ids(self, mkv_path: str) -> dict[str, str]:
            if not mkv_path or not os.path.exists(mkv_path):
                return {}
            try:
                find_mkvtoolinx()
            except Exception:
                pass
            if not MKV_MERGE_PATH:
                return {}
            try:
                p = subprocess.run(
                    [MKV_MERGE_PATH, "--identify", "--ui-language", "en", mkv_path],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    shell=False
                )
            except Exception:
                return {}
            out = {}
            for line in (p.stdout or '').splitlines():
                m = re.search(r"Attachment ID\s+(\d+):.*file name '([^']+)'", line)
                if not m:
                    continue
                out[m.group(2)] = m.group(1)
            return out

        def _read_mkvmerge_attachment_rows(self, mkv_path: str) -> list[dict[str, str]]:
            if not mkv_path or not os.path.exists(mkv_path):
                return []
            try:
                find_mkvtoolinx()
            except Exception:
                pass
            if not MKV_MERGE_PATH:
                return []
            try:
                p = subprocess.run(
                    [MKV_MERGE_PATH, "--identify", "--ui-language", "en", mkv_path],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    shell=False
                )
            except Exception:
                return []
            rows: list[dict[str, str]] = []
            for line in (p.stdout or '').splitlines():
                m = re.search(r"Attachment ID\s+(\d+):\s*type\s*'([^']+)',\s*size\s*(\d+)\s*bytes,\s*file name\s*'([^']+)'",
                              line)
                if not m:
                    continue
                rows.append({
                    'filename': m.group(4),
                    'mime_type': m.group(2),
                    'uid': '',
                    'file_size': m.group(3),
                    'id': m.group(1),
                })
            return rows

        def _show_attachments_dialog(self, mkv_path: str):
            try:
                find_mkvtoolinx()
            except Exception:
                pass

            dlg = QDialog(self)
            dlg.setWindowTitle(self.t('Edit Attachment'))
            layout = QVBoxLayout()
            dlg.setLayout(layout)

            table = QTableWidget(dlg)
            self._set_compact_table(table, row_height=22, header_height=22)
            cols = ['filename', 'mime_type', 'uid', 'file_size', 'id', 'extract']
            table.setColumnCount(len(cols))
            self._set_table_headers(table, cols)
            layout.addWidget(table)

            form = QWidget(dlg)
            form_layout = QHBoxLayout()
            form_layout.setContentsMargins(0, 0, 0, 0)
            form_layout.setSpacing(6)
            form.setLayout(form_layout)
            form_layout.addWidget(QLabel(self.t('filename'), form))
            name_edit = QLineEdit(form)
            name_edit.setMinimumWidth(160)
            form_layout.addWidget(name_edit)
            form_layout.addWidget(QLabel(self.t('mime_type'), form))
            mime_edit = QLineEdit(form)
            mime_edit.setMinimumWidth(150)
            form_layout.addWidget(mime_edit)
            form_layout.addWidget(QLabel(self.t('UID'), form))
            uid_edit = QLineEdit(form)
            uid_edit.setMinimumWidth(140)
            form_layout.addWidget(uid_edit)
            form_layout.addStretch(1)
            layout.addWidget(form)

            file_row = QWidget(dlg)
            file_layout = QHBoxLayout()
            file_layout.setContentsMargins(0, 0, 0, 0)
            file_layout.setSpacing(6)
            file_row.setLayout(file_layout)
            file_layout.addWidget(QLabel(self.t('Select attachment file'), file_row))
            file_edit = QLineEdit(file_row)
            file_edit.setMinimumWidth(360)
            file_layout.addWidget(file_edit)
            btn_browse = QPushButton(self.t('Select'), file_row)
            file_layout.addWidget(btn_browse)
            layout.addWidget(file_row)

            status_label = QLabel('', dlg)
            status_label.setVisible(False)
            layout.addWidget(status_label)

            btn_row = QWidget(dlg)
            btn_layout = QHBoxLayout()
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(6)
            btn_row.setLayout(btn_layout)
            btn_add = QPushButton(self.t('Add Attachment'), dlg)
            btn_replace = QPushButton(self.t('Replace'), dlg)
            btn_update = QPushButton(self.t('Update'), dlg)
            btn_delete = QPushButton(self.t('Delete'), dlg)
            btn_refresh = QPushButton(self.t('Refresh'), dlg)
            btn_close = QPushButton(self.t('Close'), dlg)
            btn_layout.addWidget(btn_add)
            btn_layout.addWidget(btn_replace)
            btn_layout.addWidget(btn_update)
            btn_layout.addWidget(btn_delete)
            btn_layout.addWidget(btn_refresh)
            btn_layout.addStretch(1)
            btn_layout.addWidget(btn_close)
            layout.addWidget(btn_row)

            state = {'rows': []}

            def set_status(ok: bool, details: str):
                if ok:
                    status_label.setText(self.t('Attachment updated!'))
                    status_label.setStyleSheet('color:#16a34a;')
                else:
                    status_label.setText(self.t('Attachment update failed, please check'))
                    status_label.setStyleSheet('color:#dc2626;')
                status_label.setVisible(True)
                QTimer.singleShot(3000, lambda: status_label.setVisible(False))
                if (not ok) and details:
                    self._show_error_dialog(details)

            def selector_for_row(r: dict[str, str]) -> str:
                aid = str(r.get('id') or '').strip()
                if aid:
                    return aid
                uid = str(r.get('uid') or '').strip()
                if uid:
                    return f'={uid}'
                fn = str(r.get('filename') or '').strip()
                if not fn:
                    return ''
                fn = fn.replace(':', r'\c')
                return f'name:{fn}'

            def refresh():
                rows_merge = self._read_mkvmerge_attachment_rows(mkv_path)
                rows_info = self._read_mkvinfo_attachments(mkv_path)
                uid_by_name = {str(x.get('filename') or ''): str(x.get('uid') or '') for x in rows_info}
                if rows_merge:
                    rows = rows_merge
                    for rr in rows:
                        rr['uid'] = uid_by_name.get(str(rr.get('filename') or ''), str(rr.get('uid') or ''))
                else:
                    rows = rows_info
                    ids = self._read_mkvmerge_attachment_ids(mkv_path)
                    for rr in rows:
                        fn = str(rr.get('filename') or '')
                        rr['id'] = ids.get(fn, '')
                state['rows'] = rows
                table.setRowCount(len(rows))
                for i, row in enumerate(rows):
                    for c, key in enumerate(cols):
                        if key == 'extract':
                            btn = QToolButton(table)
                            btn.setText(self.t('extract'))
                            aid = str(row.get('id', '') or '')
                            fn = str(row.get('filename', '') or '')
                            btn.clicked.connect(partial(self._extract_attachment_to_temp_and_open, mkv_path, aid, fn))
                            table.setCellWidget(i, c, btn)
                        else:
                            table.setItem(i, c, QTableWidgetItem(str(row.get(key, '') or '')))
                table.resizeColumnsToContents()

            def on_select_row():
                r = table.currentRow()
                if r < 0 or r >= len(state['rows']):
                    return
                row = state['rows'][r]
                name_edit.setText(str(row.get('filename') or ''))
                mime_edit.setText(str(row.get('mime_type') or ''))
                uid_edit.setText(str(row.get('uid') or ''))

            def browse_file():
                start = file_edit.text().strip()
                start_dir = os.path.dirname(start) if start else ''
                path = QFileDialog.getOpenFileName(dlg, self.t('Select'), start_dir)[0]
                if path:
                    file_edit.setText(os.path.normpath(path))

            def run_propedit(args: list[str]) -> tuple[bool, str]:
                if not MKV_PROP_EDIT_PATH:
                    return False, self.t('mkvpropedit not found')
                cmd = f'"{MKV_PROP_EDIT_PATH}" {mkvtoolnix_ui_language_arg()} "{mkv_path}" ' + ' '.join(args)
                try:
                    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    out = (p.stdout or '') + '\n' + (p.stderr or '')
                except Exception:
                    return False, traceback.format_exc()
                is_error = ('Error' in out) or ('error' in out.lower()) or (p.returncode != 0)
                return (not is_error), out.strip()

            def apply_replace():
                r = table.currentRow()
                if r < 0 or r >= len(state['rows']):
                    return
                src_file = self._normalize_path_input(file_edit.text())
                if not src_file or not os.path.isfile(src_file):
                    QMessageBox.information(self, " ", self.t('Select attachment file'))
                    return
                row = state['rows'][r]
                sel = selector_for_row(row)
                if not sel:
                    return
                args = []
                if name_edit.text().strip():
                    args.append(f'--attachment-name "{name_edit.text().strip()}"')
                if mime_edit.text().strip():
                    args.append(f'--attachment-mime-type "{mime_edit.text().strip()}"')
                if uid_edit.text().strip():
                    args.append(f'--attachment-uid "{uid_edit.text().strip()}"')
                args.append(f'--replace-attachment {sel}:"{src_file}"')
                ok, details = run_propedit(args)
                set_status(ok, details if not ok else '')
                if ok:
                    refresh()

            def apply_update():
                r = table.currentRow()
                if r < 0 or r >= len(state['rows']):
                    return
                row = state['rows'][r]
                sel = selector_for_row(row)
                if not sel:
                    return
                args = []
                if name_edit.text().strip():
                    args.append(f'--attachment-name "{name_edit.text().strip()}"')
                if mime_edit.text().strip():
                    args.append(f'--attachment-mime-type "{mime_edit.text().strip()}"')
                if uid_edit.text().strip():
                    args.append(f'--attachment-uid "{uid_edit.text().strip()}"')
                args.append(f'--update-attachment {sel}')
                ok, details = run_propedit(args)
                set_status(ok, details if not ok else '')
                if ok:
                    refresh()

            def apply_delete():
                r = table.currentRow()
                if r < 0 or r >= len(state['rows']):
                    return
                row = state['rows'][r]
                sel = selector_for_row(row)
                if not sel:
                    return
                ok, details = run_propedit([f'--delete-attachment {sel}'])
                set_status(ok, details if not ok else '')
                if ok:
                    refresh()

            def apply_add():
                src_file = self._normalize_path_input(file_edit.text())
                if not src_file or not os.path.isfile(src_file):
                    QMessageBox.information(self, " ", self.t('Select attachment file'))
                    return
                before_rows = list(state.get('rows') or [])
                before_set = {(str(x.get('id') or ''), str(x.get('filename') or '')) for x in before_rows}
                args = []
                if name_edit.text().strip():
                    args.append(f'--attachment-name "{name_edit.text().strip()}"')
                if mime_edit.text().strip():
                    args.append(f'--attachment-mime-type "{mime_edit.text().strip()}"')
                if uid_edit.text().strip():
                    args.append(f'--attachment-uid "{uid_edit.text().strip()}"')
                args.append(f'--add-attachment "{src_file}"')
                ok, details = run_propedit(args)
                if ok:
                    refresh()
                    after_rows = list(state.get('rows') or [])
                    after_set = {(str(x.get('id') or ''), str(x.get('filename') or '')) for x in after_rows}
                    expected_name = (name_edit.text().strip() or os.path.basename(src_file)).strip()
                    added = (len(after_set) > len(before_set)) or any(
                        str(x.get('filename') or '') == expected_name for x in after_rows)
                    if not added:
                        ok = False
                        details = (details + '\n\n' if details else '') + 'Attachment add verification failed.'
                set_status(ok, details if not ok else '')

            btn_browse.clicked.connect(browse_file)
            table.currentCellChanged.connect(lambda _r, _c, _pr, _pc: on_select_row())
            btn_refresh.clicked.connect(refresh)
            btn_add.clicked.connect(apply_add)
            btn_replace.clicked.connect(apply_replace)
            btn_update.clicked.connect(apply_update)
            btn_delete.clicked.connect(apply_delete)
            btn_close.clicked.connect(dlg.accept)

            refresh()
            if table.rowCount() > 0:
                table.setCurrentCell(0, 0)

            dlg.resize(980, 520)
            dlg.exec()

        def _show_tracks_dialog(
                self,
                title: str,
                streams: list[dict[str, object]],
                selected_indexes: Optional[set[str]] = None,
                pid_lang: Optional[dict[int, str]] = None,
                source_mkv: Optional[str] = None,
                convert_map: Optional[dict[str, str]] = None,
                language_map: Optional[dict[str, str]] = None
        ) -> Optional[set[str]]:
            dlg = QDialog(self)
            dlg.setWindowTitle(title)
            layout = QVBoxLayout()
            dlg.setLayout(layout)
            table = QTableWidget(dlg)
            self._set_compact_table(table, row_height=22, header_height=64)
            is_mkvinfo = any(('codec_id' in (s or {})) or ('track_id' in (s or {})) for s in (streams or []))
            if is_mkvinfo:
                cols = ['track_number', 'select', 'track_uid', 'track_type', 'language', 'codec_id', 'convert', 'extract']
            else:
                cols = [
                    'index', 'select', 'pid', 'program_number', 'pmt_pid', 'is_pcr_pid',
                    'stream_type', 'language', 'codec_type', 'codec_name', 'convert', 'language_from_pmt_descriptor'
                ]
            table.setColumnCount(len(cols))
            self._set_table_headers(table, cols)
            if not is_mkvinfo:
                try:
                    header_item = table.horizontalHeaderItem(cols.index('language_from_pmt_descriptor'))
                    if header_item:
                        header_item.setText('language_\nfrom_pmt_\ndescriptor')
                except Exception:
                    pass
            table.setRowCount(len(streams))
            selected = selected_indexes or set()
            pid_to_lang = pid_lang or {}
            original_languages: list[str] = []
            for r, s in enumerate(streams):
                idx_text = str(s.get('index', ''))
                codec_type = str(s.get('codec_type') or '')
                select_btn = QToolButton(table)
                select_btn.setCheckable(True)
                is_selected = (codec_type == 'video') or (idx_text in selected)
                select_btn.setChecked(is_selected)
                if codec_type == 'video':
                    select_btn.setEnabled(False)
                table.setCellWidget(r, cols.index('select'), select_btn)
                for c, key in enumerate(cols):
                    if key == 'select':
                        continue
                    if key == 'extract':
                        if source_mkv and is_mkvinfo:
                            btn = QToolButton(table)
                            btn.setText(self.t('extract'))
                            try:
                                tid = int(str(s.get('track_id') or s.get('index') or '').strip())
                            except Exception:
                                tid = -1
                            cid = str(s.get('codec_id') or '')
                            if tid >= 0:
                                btn.clicked.connect(partial(self._extract_track_to_temp_and_open, source_mkv, tid, cid))
                                table.setCellWidget(r, c, btn)
                            else:
                                table.setItem(r, c, QTableWidgetItem(''))
                        else:
                            table.setItem(r, c, QTableWidgetItem(''))
                        continue
                    if key == 'convert':
                        cb = QComboBox(table)
                        options = self._conversion_options_for_stream(s, is_mkvinfo)
                        cb.addItems(options)
                        idx_text = str(s.get('index', ''))
                        wanted = str((convert_map or {}).get(idx_text, '') or '').strip()
                        if wanted and wanted in options:
                            cb.setCurrentText(wanted)
                        else:
                            cb.setCurrentIndex(0)
                        table.setCellWidget(r, c, cb)
                        continue
                    if key == 'track_number' and is_mkvinfo:
                        v = s.get('track_number', s.get('track_id', ''))
                    elif key == 'language':
                        if is_mkvinfo:
                            v = s.get('language', s.get('lang', 'und'))
                        else:
                            v = 'und'
                            try:
                                pid = self._parse_stream_pid(s.get('pid'))
                                if pid is not None and pid in pid_to_lang:
                                    v = pid_to_lang.get(pid, 'und')
                                else:
                                    try:
                                        idx = int(str(s.get('index') or '').strip())
                                        v = pid_to_lang.get(idx, 'und')
                                    except Exception:
                                        v = 'und'
                            except Exception:
                                v = 'und'
                        override_lang = str((language_map or {}).get(idx_text, '') or '').strip()
                        if override_lang:
                            v = override_lang
                        item = QTableWidgetItem('' if v is None else str(v))
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        item.setBackground(QColor('#e0f0ff'))
                        table.setItem(r, c, item)
                        original_languages.append('' if v is None else str(v))
                        continue
                    else:
                        v = s.get(key, '')
                    table.setItem(r, c, QTableWidgetItem('' if v is None else str(v)))
            table.resizeColumnsToContents()
            if not is_mkvinfo:
                try:
                    stream_type_col = cols.index('stream_type')
                    lang_desc_col = cols.index('language_from_pmt_descriptor')
                    table.setColumnWidth(stream_type_col, 93)
                    table.setColumnWidth(lang_desc_col, 73)
                    header = table.horizontalHeader()
                    header.setSectionResizeMode(stream_type_col, QHeaderView.ResizeMode.Fixed)
                    header.setSectionResizeMode(lang_desc_col, QHeaderView.ResizeMode.Fixed)
                except Exception:
                    pass
            layout.addWidget(table)
            btn_row = QWidget(dlg)
            btn_layout = QHBoxLayout()
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_row.setLayout(btn_layout)
            btn_ok = QPushButton(self.t('Select'), dlg)
            btn_cancel = QPushButton(self.t('Cancel'), dlg)
            btn_cancel.clicked.connect(dlg.reject)
            status_label = QLabel(dlg)
            status_label.setVisible(False)

            def apply_and_accept():
                conversion_map: dict[str, str] = {}
                language_selected_map: dict[str, str] = {}
                if 'convert' in cols:
                    convert_col = cols.index('convert')
                    for r, st in enumerate(streams):
                        idx = str(st.get('index', ''))
                        cb = table.cellWidget(r, convert_col)
                        if isinstance(cb, QComboBox):
                            v = (cb.currentText() or '').strip()
                            if v and v != self.t('No conversion'):
                                conversion_map[idx] = v
                self._last_track_convert_map = conversion_map
                if 'language' in cols:
                    lang_col_for_save = cols.index('language')
                    for r, st in enumerate(streams):
                        idx = str(st.get('index', ''))
                        it = table.item(r, lang_col_for_save)
                        if it:
                            lv = str(it.text() or '').strip()
                            if lv:
                                language_selected_map[idx] = lv
                self._last_track_language_map = language_selected_map
                if source_mkv and is_mkvinfo and len(streams) == table.rowCount():
                    lang_col = cols.index('language') if 'language' in cols else -1
                    if lang_col >= 0:
                        changed: list[tuple[int, str]] = []
                        for r, s in enumerate(streams):
                            item = table.item(r, lang_col)
                            if not item:
                                continue
                            new_lang = str(item.text()).strip()
                            old_lang = original_languages[r] if r < len(original_languages) else ''
                            if not new_lang or new_lang == old_lang:
                                continue
                            try:
                                track_num = int(s.get('track_number_1based') or s.get('track_id') + 1)
                            except Exception:
                                try:
                                    track_num = int(str(s.get('track_id') or '').strip()) + 1
                                except Exception:
                                    try:
                                        track_num = int(str(s.get('index') or '').strip()) + 1
                                    except Exception:
                                        track_num = r + 1
                            changed.append((track_num, new_lang))
                        if changed:
                            try:
                                find_mkvtoolinx()
                            except Exception:
                                pass
                            exe = MKV_PROP_EDIT_PATH or shutil.which('mkvpropedit') or 'mkvpropedit'
                            if exe:
                                args = [exe]
                                try:
                                    ui = get_mkvtoolnix_ui_language()
                                    if ui:
                                        args += ['--ui-language', ui]
                                except Exception:
                                    pass
                                args.append(source_mkv)
                                for track_num, lang in changed:
                                    args += ['--edit', f'track:{track_num}', '--set', f'language={lang}']
                                try:
                                    p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                                                       errors='ignore', shell=False)
                                    if p.returncode == 0:
                                        try:
                                            updated_streams = self._read_mkvinfo_tracks(source_mkv)
                                            for r, s in enumerate(streams):
                                                if r < len(updated_streams):
                                                    new_lang_value = str(updated_streams[r].get('language',
                                                                                                updated_streams[r].get(
                                                                                                    'lang', 'und')))
                                                    lang_item = table.item(r, lang_col)
                                                    if lang_item:
                                                        lang_item.setText(new_lang_value)
                                        except Exception:
                                            pass
                                        status_label.setText(self.t('Language updated successfully!'))
                                        status_label.setStyleSheet('color:#16a34a;font-weight:bold;')
                                        status_label.setVisible(True)

                                        def on_success_timeout():
                                            status_label.setVisible(False)
                                            dlg.accept()

                                        QTimer.singleShot(3000, on_success_timeout)
                                    else:
                                        error_msg = f'mkvpropedit failed: {p.returncode}'
                                        if p.stdout or p.stderr:
                                            error_msg += f'\n{(p.stdout or "").strip()}\n{(p.stderr or "").strip()}'
                                        status_label.setText(error_msg)
                                        status_label.setStyleSheet('color:#dc2626;font-weight:bold;')
                                        status_label.setVisible(True)
                                        QTimer.singleShot(3000, lambda: status_label.setVisible(False))
                                except Exception as e:
                                    status_label.setText(f'Error: {str(e)}')
                                    status_label.setStyleSheet('color:#dc2626;font-weight:bold;')
                                    status_label.setVisible(True)
                                    QTimer.singleShot(3000, lambda: status_label.setVisible(False))
                            else:
                                status_label.setText(self.t('mkvpropedit not found'))
                                status_label.setStyleSheet('color:#dc2626;font-weight:bold;')
                                status_label.setVisible(True)
                                QTimer.singleShot(3000, lambda: status_label.setVisible(False))
                else:
                    dlg.accept()

            btn_ok.clicked.connect(apply_and_accept)
            btn_layout.addStretch(1)
            btn_layout.addWidget(btn_ok)
            btn_layout.addWidget(btn_cancel)
            layout.addWidget(btn_row)
            layout.addWidget(status_label)
            dlg.resize(980, 460)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return None
            selected_after: set[str] = set()
            for r, s in enumerate(streams):
                codec_type = str(s.get('codec_type') or '')
                idx_text = str(s.get('index', ''))
                btn = table.cellWidget(r, cols.index('select'))
                checked = isinstance(btn, QToolButton) and btn.isChecked()
                if codec_type == 'video' or checked:
                    selected_after.add(idx_text)
            return selected_after

        def _refresh_track_selection_config_for_selected_main(self):
            if self.get_selected_function_id() not in (3, 4, 5):
                return
            for mpls_path in self._get_selected_main_mpls_paths():
                try:
                    self._ensure_default_track_config_for_main(mpls_path)
                except Exception:
                    pass

        def _ensure_default_track_config_for_main(self, mpls_path: str):
            cfg = getattr(self, '_track_selection_config', None)
            if not isinstance(cfg, dict):
                self._track_selection_config = {}
                cfg = self._track_selection_config
            key = f'main::{os.path.normpath(mpls_path)}'
            if key in cfg:
                return
            m2ts_path = self._get_first_m2ts_for_mpls(mpls_path)
            if not m2ts_path:
                return
            chapter = Chapter(mpls_path)
            chapter.get_pid_to_language()
            streams = self._read_m2ts_track_info(m2ts_path)
            copy_audio_track, copy_sub_track = BluraySubtitle._default_track_selection_from_streams(
                streams,
                chapter.pid_to_lang
            )
            cfg[key] = {'audio': copy_audio_track, 'subtitle': copy_sub_track}

        def _inherit_main_track_config_for_sp_key(self, bdmv_index: int, mpls_file: str, sp_key: str):
            if not sp_key:
                return
            cfg = getattr(self, '_track_selection_config', None)
            if not isinstance(cfg, dict):
                self._track_selection_config = {}
                cfg = self._track_selection_config
            if sp_key in cfg:
                return
            mpls_name = str(mpls_file or '').strip()
            if not mpls_name:
                return
            main_mpls_path = self._get_main_mpls_path_for_bdmv_index(bdmv_index)
            if main_mpls_path:
                main_key = f'main::{os.path.normpath(main_mpls_path)}'
                if main_key in cfg:
                    main_cfg = cfg.get(main_key) or {}
                    cfg[sp_key] = {
                        'audio': list(main_cfg.get('audio') or []),
                        'subtitle': list(main_cfg.get('subtitle') or []),
                    }
                    return
            playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
            if playlist_dir:
                mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_name))
                alt_key = f'main::{mpls_path}'
                if alt_key in cfg:
                    main_cfg = cfg.get(alt_key) or {}
                    cfg[sp_key] = {
                        'audio': list(main_cfg.get('audio') or []),
                        'subtitle': list(main_cfg.get('subtitle') or []),
                    }

        def on_edit_attachments_from_mkv_row(self, table: QTableWidget, row_index: int):
            try:
                if table is self.table2:
                    src = self._get_remux_source_path_from_table2_row(row_index)
                else:
                    src = self._get_remux_source_path_from_table3_row(row_index)
                if not src or not os.path.exists(src):
                    QMessageBox.information(self, " ", "MKV file not found")
                    return
                self._show_attachments_dialog(src)
            except Exception:
                self._show_error_dialog(traceback.format_exc())

        def on_edit_chapters_from_mkv_row(self, table: QTableWidget, row_index: int):
            try:
                if table is self.table2:
                    src = self._get_remux_source_path_from_table2_row(row_index)
                else:
                    src = self._get_remux_source_path_from_table3_row(row_index)
                if not src or not os.path.exists(src):
                    QMessageBox.information(self, " ", "MKV file not found")
                    return
                self._edit_chapters_for_mkv(src)
            except Exception:
                self._show_error_dialog(traceback.format_exc())

        def on_edit_tracks_from_mkv_row(self, table: QTableWidget, row_index: int):
            try:
                if table is self.table2:
                    src = self._get_remux_source_path_from_table2_row(row_index)
                    key = f'mkv::{os.path.normpath(src)}'
                else:
                    src = self._get_remux_source_path_from_table3_row(row_index)
                    key = f'mkvsp::{os.path.normpath(src)}'
                if not src or not os.path.exists(src):
                    QMessageBox.information(self, " ", "MKV file not found")
                    return
                streams = self._read_mkvinfo_tracks(src)
                pid_lang = {}
                for s in streams:
                    try:
                        tid = int(str(s.get('track_id') or s.get('index') or '').strip())
                        pid_lang[tid] = str(s.get('language') or s.get('lang') or 'und')
                    except Exception:
                        pass
                cfg = getattr(self, '_track_selection_config', {})
                conv_cfg_all = getattr(self, '_track_convert_config', {})
                if key not in cfg:
                    a, s = BluraySubtitle._default_track_selection_from_streams(streams, pid_lang)
                    cfg[key] = {'audio': a, 'subtitle': s}
                selected = set((cfg.get(key, {}).get('audio') or []) + (cfg.get(key, {}).get('subtitle') or []))
                convert_map = dict((conv_cfg_all.get(key) or {}))
                selected_after = self._show_tracks_dialog(
                    self.t('edit tracks'),
                    streams,
                    selected,
                    pid_lang,
                    source_mkv=src,
                    convert_map=convert_map,
                    language_map=dict((getattr(self, '_track_language_config', {}).get(key) or {}))
                )
                if selected_after is None:
                    return
                audio: list[str] = []
                subtitle: list[str] = []
                for st in streams:
                    idx = str(st.get('index', ''))
                    if idx not in selected_after:
                        continue
                    ctype = str(st.get('codec_type') or '')
                    if ctype == 'audio':
                        audio.append(idx)
                    elif ctype == 'subtitle':
                        subtitle.append(idx)
                cfg[key] = {'audio': audio, 'subtitle': subtitle}
                conv_cfg = getattr(self, '_track_convert_config', {})
                conv_cfg[key] = dict(getattr(self, '_last_track_convert_map', {}) or {})
                self._track_convert_config = conv_cfg
                lang_cfg = getattr(self, '_track_language_config', {})
                lang_cfg[key] = dict(getattr(self, '_last_track_language_map', {}) or {})
                self._track_language_config = lang_cfg
                if self.get_selected_function_id() == 5:
                    self.on_select_function(force=True, keep_inputs=True, keep_state=True)
            except Exception:
                self._show_error_dialog(traceback.format_exc())

        def on_edit_tracks_from_mpls(self, mpls_path: str):
            try:
                m2ts_path = self._get_first_m2ts_for_mpls(mpls_path)
                if not m2ts_path:
                    QMessageBox.information(self, " ", "M2TS file not found")
                    return
                self._ensure_default_track_config_for_main(mpls_path)
                chapter = Chapter(mpls_path)
                chapter.get_pid_to_language()
                streams = self._read_m2ts_track_info(m2ts_path)
                pid_lang = chapter.pid_to_lang
                key = f'main::{os.path.normpath(mpls_path)}'
                cfg = getattr(self, '_track_selection_config', {}).get(key, {})
                selected = set((cfg.get('audio') or []) + (cfg.get('subtitle') or []))
                convert_map = dict((getattr(self, '_track_convert_config', {}).get(key) or {}))
                selected_after = self._show_tracks_dialog(
                    self.t('edit tracks'),
                    streams,
                    selected,
                    pid_lang,
                    convert_map=convert_map,
                    language_map=dict((getattr(self, '_track_language_config', {}).get(key) or {}))
                )
                if selected_after is None:
                    return
                audio: list[str] = []
                subtitle: list[str] = []
                for s in streams:
                    idx = str(s.get('index', ''))
                    if idx not in selected_after:
                        continue
                    ctype = str(s.get('codec_type') or '')
                    if ctype == 'audio':
                        audio.append(idx)
                    elif ctype == 'subtitle':
                        subtitle.append(idx)
                self._track_selection_config[key] = {'audio': audio, 'subtitle': subtitle}
                conv_cfg = getattr(self, '_track_convert_config', {})
                conv_cfg[key] = dict(getattr(self, '_last_track_convert_map', {}) or {})
                self._track_convert_config = conv_cfg
                lang_cfg = getattr(self, '_track_language_config', {})
                lang_cfg[key] = dict(getattr(self, '_last_track_language_map', {}) or {})
                self._track_language_config = lang_cfg
                self._sync_main_mpls_track_config_by_pid(
                    mpls_path,
                    streams,
                    set(selected_after),
                    dict(getattr(self, '_last_track_convert_map', {}) or {}),
                    dict(getattr(self, '_last_track_language_map', {}) or {}),
                )
                self._refresh_table1_remux_cmds()
                if self.get_selected_function_id() == 5:
                    self.on_select_function(force=True, keep_inputs=True, keep_state=True)
            except Exception:
                self._show_error_dialog(traceback.format_exc())

        def on_edit_tracks_from_sp_table(self, row: int):
            try:
                if row < 0 or row >= self.table3.rowCount():
                    sender = self.sender()
                    if sender is not None and hasattr(self, 'table3') and self.table3:
                        try:
                            row = self.table3.indexAt(sender.pos()).row()
                        except Exception:
                            row = -1
                if row < 0 or row >= self.table3.rowCount():
                    return
                bdmv_item = self.table3.item(row, ENCODE_SP_LABELS.index('bdmv_index'))
                bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
                mpls_item = self.table3.item(row, ENCODE_SP_LABELS.index('mpls_file'))
                mpls_file = mpls_item.text().strip() if mpls_item and mpls_item.text() else ''
                m2ts_item = self.table3.item(row, ENCODE_SP_LABELS.index('m2ts_file'))
                m2ts_text = m2ts_item.text().strip() if m2ts_item and m2ts_item.text() else ''
                entry = {'bdmv_index': bdmv_index, 'mpls_file': mpls_file, 'm2ts_file': m2ts_text, 'output_name': ''}
                key = BluraySubtitle._sp_track_key_from_entry(entry)
                cfg = getattr(self, '_track_selection_config', None)
                if not isinstance(cfg, dict):
                    self._track_selection_config = {}
                    cfg = self._track_selection_config

                pid_lang: dict[int, str] = {}
                streams: list[dict[str, object]] = []
                if mpls_file:
                    playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                    if not playlist_dir:
                        QMessageBox.information(self, " ",
                                                f"Matching Blu-ray directory not found (bdmv_index={bdmv_index}), cannot locate MPLS file")
                        return
                    mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_file))
                    if not os.path.exists(mpls_path):
                        QMessageBox.information(self, " ", f"MPLS file not found:\n{mpls_path}")
                        return
                    m2ts_path = self._get_first_m2ts_for_mpls(mpls_path)
                    if not m2ts_path:
                        QMessageBox.information(self, " ", "M2TS file not found")
                        return
                    chapter = Chapter(mpls_path)
                    chapter.get_pid_to_language()
                    streams = self._read_m2ts_track_info(m2ts_path)
                    pid_lang = chapter.pid_to_lang
                else:
                    m2ts_files = self._split_m2ts_files(m2ts_text)
                    if not m2ts_files:
                        QMessageBox.information(self, " ", "M2TS file not found")
                        return
                    stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
                    if not stream_dir:
                        QMessageBox.information(self, " ",
                                                f"Matching Blu-ray directory not found (bdmv_index={bdmv_index}), cannot locate M2TS file")
                        return
                    m2ts_path = os.path.normpath(os.path.join(stream_dir, m2ts_files[0]))
                    if not os.path.exists(m2ts_path):
                        QMessageBox.information(self, " ", f"M2TS file not found:\n{m2ts_path}")
                        return
                    streams = self._read_m2ts_track_info(m2ts_path)
                    # No MPLS language map available for pure m2ts rows; keep PMT descriptor as reference.
                    pid_lang = self._pid_lang_from_m2ts_track_info(streams)

                if key not in cfg:
                    self._inherit_main_track_config_for_sp_key(bdmv_index, mpls_file, key)
                if key not in cfg:
                    a, s = BluraySubtitle._default_track_selection_from_streams(streams, pid_lang)
                    cfg[key] = {'audio': a, 'subtitle': s}
                cur = cfg.get(key, {})
                selected = set((cur.get('audio') or []) + (cur.get('subtitle') or []))
                convert_map = dict((getattr(self, '_track_convert_config', {}).get(key) or {}))
                selected_after = self._show_tracks_dialog(
                    self.t('edit tracks'),
                    streams,
                    selected,
                    pid_lang,
                    convert_map=convert_map,
                    language_map=dict((getattr(self, '_track_language_config', {}).get(key) or {}))
                )
                if selected_after is None:
                    return
                audio: list[str] = []
                subtitle: list[str] = []
                for st in streams:
                    idx = str(st.get('index', ''))
                    if idx not in selected_after:
                        continue
                    ctype = str(st.get('codec_type') or '')
                    if ctype == 'audio':
                        audio.append(idx)
                    elif ctype == 'subtitle':
                        subtitle.append(idx)
                cfg[key] = {'audio': audio, 'subtitle': subtitle}
                conv_cfg = getattr(self, '_track_convert_config', {})
                conv_cfg[key] = dict(getattr(self, '_last_track_convert_map', {}) or {})
                self._track_convert_config = conv_cfg
                lang_cfg = getattr(self, '_track_language_config', {})
                lang_cfg[key] = dict(getattr(self, '_last_track_language_map', {}) or {})
                self._track_language_config = lang_cfg
                if mpls_file:
                    try:
                        playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                        if playlist_dir:
                            main_key = f'main::{os.path.normpath(os.path.join(playlist_dir, mpls_file))}'
                            cfg[main_key] = {'audio': list(audio), 'subtitle': list(subtitle)}
                        selected_main_path = self._get_main_mpls_path_for_bdmv_index(bdmv_index)
                        if selected_main_path:
                            selected_main_key = f'main::{os.path.normpath(selected_main_path)}'
                            cfg[selected_main_key] = {'audio': list(audio), 'subtitle': list(subtitle)}
                    except Exception:
                        pass
                keep_row = row
                keep_col = ENCODE_SP_LABELS.index('output_name')
                keep_h_scroll = self.table3.horizontalScrollBar().value() if self.table3.horizontalScrollBar() else 0
                keep_v_scroll = self.table3.verticalScrollBar().value() if self.table3.verticalScrollBar() else 0
                self._recompute_sp_output_names()
                try:
                    if self.table3.horizontalScrollBar():
                        self.table3.horizontalScrollBar().setValue(keep_h_scroll)
                    if self.table3.verticalScrollBar():
                        self.table3.verticalScrollBar().setValue(keep_v_scroll)
                    if 0 <= keep_row < self.table3.rowCount():
                        keep_item = self.table3.item(keep_row, keep_col) or self.table3.item(keep_row, 0)
                        if keep_item:
                            self.table3.setCurrentItem(keep_item)
                except Exception:
                    pass
                try:
                    self._refresh_table1_remux_cmds()
                except Exception:
                    pass
                if self.get_selected_function_id() == 5:
                    self.on_select_function(force=True, keep_inputs=True, keep_state=True)
            except Exception:
                self._show_error_dialog(traceback.format_exc())
