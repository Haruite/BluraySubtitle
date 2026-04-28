"""Auto-generated split target: lifecycle_and_configuration."""
import ctypes
import json
import locale
import multiprocessing
import os
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as et
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Optional, Generator

from PyQt6.QtCore import QCoreApplication, QThread
from PyQt6.QtWidgets import QTableWidget, QToolButton

from src.bdmv import Chapter
from src.core import MKV_MERGE_PATH
from src.exports.utils import get_time_str
from .service_base import BluraySubtitleServiceBase
from ..services.cancelled import _Cancelled
from ...core import DEFAULT_APPROX_EPISODE_DURATION_SECONDS, CURRENT_UI_LANGUAGE
from ...core.i18n import translate_text
from ...domain import ISO, Subtitle
from ...domain.subtitles import parse_subtitle_worker as _parse_subtitle_worker


class LifecycleConfigurationMixin(BluraySubtitleServiceBase):
    def __init__(self, bluray_path: str, sub_files: list[str] = None, checked: bool = True,
                 progress_dialog: Optional[object] = None,
                 approx_episode_duration_seconds: float = DEFAULT_APPROX_EPISODE_DURATION_SECONDS,
                 movie_mode: bool = False):
        self.tmp_folders = []
        if sys.platform == 'win32':
            for root, dirs, files in os.walk(bluray_path):
                dirs.sort()  # Sort dirs to ensure consistent order on all platforms
                for file in sorted(files):  # Also sort files
                    if file.endswith(".iso") and os.path.getsize(os.path.join(root, file)) > 5 * 1024 ** 3:
                        iso_path = os.path.join(root, file)
                        drivers = self.get_available_drives()
                        iso = ISO(iso_path)
                        iso.mount()
                        drivers_1 = self.get_available_drives()
                        driver = tuple(drivers_1 - drivers)[0]
                        tmp_folder = iso_path[:-4]
                        try:
                            shutil.copytree(f'{driver}:\\BDMV\\PLAYLIST', f'{tmp_folder}\\BDMV\\PLAYLIST')
                        except:
                            pass
                        else:
                            self.tmp_folders.append(tmp_folder)
                        iso.close()
                        while len(self.get_available_drives()) == len(drivers_1):
                            pass
        self.sub_files = sub_files
        self.bdmv_path = bluray_path
        bluray_folders = []
        for root, dirs, files in os.walk(bluray_path):
            dirs.sort()  # Sort dirs to ensure consistent order on all platforms
            if 'BDMV' in dirs and 'PLAYLIST' in os.listdir(os.path.join(root, 'BDMV')):
                bluray_folders.append(root)
        self.bluray_folders = bluray_folders
        self.checked = checked
        self.progress_dialog = progress_dialog
        self.configuration = {}
        self._subtitle_cache: dict[str, Subtitle] = {}
        self.movie_mode = bool(movie_mode)
        self._sp_index_by_bdmv: dict[int, int] = {}
        try:
            val = float(approx_episode_duration_seconds)
            self.approx_episode_duration_seconds = val if val > 0 else DEFAULT_APPROX_EPISODE_DURATION_SECONDS
        except Exception:
            self.approx_episode_duration_seconds = DEFAULT_APPROX_EPISODE_DURATION_SECONDS

    def t(self, text: str) -> str:
        return translate_text(str(text), getattr(self, '_language_code', CURRENT_UI_LANGUAGE))

    def _progress(self, value: Optional[int] = None, text: Optional[str] = None):
        if self.progress_dialog is None:
            return
        if callable(self.progress_dialog):
            try:
                self.progress_dialog(value, text)
            except TypeError:
                if value is not None:
                    self.progress_dialog(value)
        else:
            if text is not None and hasattr(self.progress_dialog, 'setLabelText'):
                self.progress_dialog.setLabelText(translate_text(text))
            if value is not None and hasattr(self.progress_dialog, 'setValue'):
                self.progress_dialog.setValue(int(value))
        app = QCoreApplication.instance()
        if app and QThread.currentThread() == app.thread():
            QCoreApplication.processEvents()

    def _preload_subtitles(self, file_paths: list[str], cancel_event: Optional[threading.Event] = None):
        """Preload subtitles into cache with platform-aware fallback strategy."""
        if not file_paths:
            return
        missing = [p for p in file_paths if p and p not in self._subtitle_cache]
        if not missing:
            return

        # Choose loading strategy by platform.
        if sys.platform == 'win32':
            # Windows: use multiprocessing directly.
            self._preload_subtitles_multiprocess(missing, cancel_event)
        else:
            # Linux: try multiprocessing first, then fall back to single process.
            try:
                self._preload_subtitles_multiprocess(missing, cancel_event)
            except Exception as e:
                print(f'Multiprocessing parse failed, switching to single-process mode: {str(e)}')
                self._preload_subtitles_single(missing, cancel_event)

    def _preload_subtitles_single(self, file_paths: list[str], cancel_event: Optional[threading.Event] = None):
        """Parse subtitles in single-process mode."""
        for p in file_paths:
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            try:
                self._subtitle_cache[p] = Subtitle(p)
            except Exception as e:
                print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')

    def _preload_subtitles_multiprocess(self, file_paths: list[str], cancel_event: Optional[threading.Event] = None):
        """Parse subtitles in multiprocessing mode."""
        if len(file_paths) == 1:
            p = file_paths[0]
            try:
                self._subtitle_cache[p] = Subtitle(p)
            except Exception as e:
                print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
            return

        # On Linux, exit in worker subprocess to avoid recursive window spawning.
        if sys.platform != 'win32' and multiprocessing.current_process().name != 'MainProcess':
            return

        max_workers = min(len(file_paths), os.cpu_count() or 1)

        # Select multiprocessing context for Linux/Windows compatibility.
        if sys.platform == 'win32':
            mp_context = multiprocessing.get_context('spawn')
        else:
            # Linux defaults to fork; more stable for GUI, but requires __main__ guard.
            mp_context = multiprocessing.get_context('fork')

        try:
            with ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_context) as ex:
                futures = [ex.submit(_parse_subtitle_worker, p) for p in file_paths]
                for fut in as_completed(futures):
                    if cancel_event and cancel_event.is_set():
                        for f in futures:
                            f.cancel()
                        raise _Cancelled()
                    p = None
                    try:
                        p, sub = fut.result()
                        if sub is not None:
                            self._subtitle_cache[p] = sub
                    except Exception as e:
                        if p:
                            print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
                        else:
                            print(f'Failed to load subtitle file: {str(e)}')
        except Exception as e:
            # Propagate exception so caller can decide fallback behavior.
            raise Exception(f'Multiprocessing parse failed: {str(e)}')

    @staticmethod
    def get_available_drives():
        drives = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in range(65, 91):
            if bitmask & 1:
                drives.append(chr(letter))
            bitmask >>= 1
        return set(drives)

    def get_main_mpls(self, bluray_folder: str, checked: bool) -> str:
        mpls_folder = os.path.join(bluray_folder, 'BDMV', 'PLAYLIST')
        stream_folder = os.path.join(bluray_folder, 'BDMV', 'STREAM')
        selected_mpls = None
        max_indicator = 0
        for mpls_file_name in os.listdir(mpls_folder):
            if mpls_file_name[-5:].lower() != '.mpls':
                continue
            mpls_file_path = os.path.join(mpls_folder, mpls_file_name)
            chapter = Chapter(mpls_file_path)
            if checked:
                total_size = 1
            else:
                total_size = 0
                stream_files = set()
                for in_out_time in chapter.in_out_time:
                    if in_out_time[0] not in stream_files:
                        m2ts_file = os.path.join(stream_folder, f'{in_out_time[0]}.m2ts')
                        if os.path.exists(m2ts_file):
                            total_size += os.path.getsize(m2ts_file)
                        else:
                            print(f'\033[31mError, m2ts file ｢{m2ts_file}｣ in ｢{mpls_file_path}｣ not found\033[0m')
                    stream_files.add(in_out_time[0])
            indicator = chapter.get_total_time_no_repeat() * (1 + sum(map(len, chapter.mark_info.values())) / 5
                                                              ) * os.path.getsize(mpls_file_path) * total_size
            if indicator > max_indicator:
                max_indicator = indicator
                selected_mpls = mpls_file_path
        return selected_mpls

    def select_mpls_from_table(self, table: QTableWidget) -> Generator[str, Chapter, str]:
        for bdmv_index in range(table.rowCount()):
            bluray_folder = table.item(bdmv_index, 0).text()
            info: QTableWidget = table.cellWidget(bdmv_index, 2)
            for mpls_index in range(info.rowCount()):
                main_btn: QToolButton = info.cellWidget(mpls_index, 3)
                if main_btn.isChecked():
                    mpls_file = info.item(mpls_index, 0).text()
                    selected_mpls = os.path.join(bluray_folder, 'BDMV', 'PLAYLIST', mpls_file)
                    yield bluray_folder, Chapter(selected_mpls), selected_mpls[:-5]

    def _resolve_disc_output_name(self, selected_mpls_no_ext: str) -> str:
        cache = getattr(self, '_disc_output_name_cache', None)
        if cache is None:
            cache = {}
            self._disc_output_name_cache = cache
        if selected_mpls_no_ext in cache:
            return cache[selected_mpls_no_ext]

        mpls_path = selected_mpls_no_ext + '.mpls'
        meta_folder = os.path.join(os.path.join(mpls_path[:-19], 'META', 'DL'))
        output_name = ''
        # 1) Find first audio language from the first m2ts of selected main mpls.
        first_audio_lang = ''
        try:
            chapter = Chapter(mpls_path)
            if chapter.in_out_time:
                first_m2ts = os.path.join(os.path.dirname(os.path.dirname(mpls_path)), 'STREAM',
                                          chapter.in_out_time[0][0] + '.m2ts')
                mkvmerge_info = self._pid_lang_from_mkvmerge_json(first_m2ts)
                if mkvmerge_info:
                    exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
                    p = subprocess.run(
                        [exe, "--identify", "--identification-format", "json", first_m2ts],
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore',
                        shell=False
                    )
                    data = json.loads(p.stdout or "{}")
                    tracks = data.get('tracks') or []
                    for tr in tracks:
                        if isinstance(tr, dict) and str(tr.get('type') or '') == 'audio':
                            props = tr.get('properties') or {}
                            if isinstance(props, dict):
                                first_audio_lang = str(props.get('language') or '').strip().lower()
                            break
        except Exception:
            first_audio_lang = ''

        def _read_xml_title(xml_path: str) -> str:
            try:
                tree = et.parse(xml_path)
                _folder = tree.getroot()
                ns = {'di': 'urn:BDA:bdmv;discinfo'}
                node = _folder.find('.//di:name', ns)
                return (node.text or '').strip() if node is not None else ''
            except Exception:
                return ''

        if os.path.isdir(meta_folder):
            xml_files = sorted([f for f in os.listdir(meta_folder) if f.lower().endswith('.xml')])
            xml_map = {f.lower(): f for f in xml_files}
            # 2) Prefer XML title matching first-audio language.
            lang_candidates = []
            if first_audio_lang:
                lang_candidates.append(first_audio_lang)
                if first_audio_lang == 'jpn':
                    lang_candidates += ['ja', 'jpn']
                if first_audio_lang in ('zho', 'chi'):
                    lang_candidates += ['zh', 'zho', 'chi']
                if first_audio_lang == 'eng':
                    lang_candidates += ['en', 'eng']
            for lang in lang_candidates:
                for f in xml_files:
                    low = f.lower()
                    if low.startswith('bdmt_') and (low.endswith(f'_{lang}.xml') or low == f'bdmt_{lang}.xml'):
                        output_name = _read_xml_title(os.path.join(meta_folder, f))
                        if output_name:
                            break
                if output_name:
                    break
            # 3) Fallback by system language preference.
            if not output_name:
                try:
                    loc = locale.getlocale()
                    sys_lang = (loc[0] or '').lower() if isinstance(loc, tuple) and loc else ''
                except Exception:
                    sys_lang = ''
                prefer = ['zho', 'chi', 'zh'] if sys_lang.startswith('zh') else ['eng', 'en']
                for lang in prefer:
                    f = xml_map.get(f'bdmt_{lang}.xml')
                    if f:
                        output_name = _read_xml_title(os.path.join(meta_folder, f))
                        if output_name:
                            break
            # 4) Fallback first xml title.
            if not output_name:
                for f in xml_files:
                    output_name = _read_xml_title(os.path.join(meta_folder, f))
                    if output_name:
                        break
        # 5) No xml title -> use outer folder name of selected bluray input path.
        if not output_name:
            try:
                base = os.path.basename(os.path.normpath(str(getattr(self, 'bdmv_path', '') or '')).rstrip(os.sep))
                output_name = base or os.path.split(mpls_path[:-24])[-1]
            except Exception:
                output_name = os.path.split(mpls_path[:-24])[-1]
        char_map = {
            '?': '？', '*': '★', '<': '《', '>': '》', ':': '：', '"': "'", '/': '／', '\\': '／', '|': '￨'
        }
        output_name = ''.join(char_map.get(char) or char for char in output_name)
        cache[selected_mpls_no_ext] = output_name
        return output_name

    @staticmethod
    def _configuration_default_chapter_segments_checked(
            configuration: dict[int, dict[str, int | str]],
    ) -> None:
        for v in configuration.values():
            v.setdefault('chapter_segments_fully_checked', True)

    def generate_configuration(self, table: QTableWidget,
                               sub_combo_index: Optional[dict[int, int]] = None,
                               subtitle_index: Optional[int] = None) -> dict[int, dict[str, int | str]]:
        configuration = {}
        sub_index = 0
        bdmv_index = 0
        global CONFIGURATION
        approx_end_time = float(
            getattr(self, 'approx_episode_duration_seconds', DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
            or DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
        if self.sub_files:
            # Always use single process in main thread to avoid multiprocessing edge cases.
            missing = [p for p in self.sub_files if p and p not in self._subtitle_cache]
            if missing:
                # Use single-process loading directly in main thread.
                for p in missing:
                    try:
                        self._subtitle_cache[p] = Subtitle(p)
                    except Exception as e:
                        print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
            sub_max_end = [self._subtitle_cache[p].max_end_time() for p in self.sub_files]
        else:
            sub_max_end = []
        if sub_combo_index:
            chapter_index = sub_combo_index[sub_index]
            for folder, chapter, selected_mpls in self.select_mpls_from_table(table):
                disc_output_name = self._resolve_disc_output_name(selected_mpls)
                for bdmv_index in range(table.rowCount()):
                    if table.item(bdmv_index, 0).text() == folder:
                        break
                bdmv_index += 1
                offset = 0
                j = 1
                left_time = chapter.get_total_time()
                sub_end_time = sub_max_end[sub_index] if self.sub_files else approx_end_time
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    if sub_index <= subtitle_index and j == chapter_index:
                        sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                        configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                    'bdmv_index': bdmv_index, 'chapter_index': j,
                                                    'offset': get_time_str(offset),
                                                    'disc_output_name': disc_output_name}
                        sub_index += 1
                        if sub_combo_index.get(sub_index):
                            chapter_index = sub_combo_index[sub_index]
                    elif sub_index > subtitle_index:
                        if offset > sub_end_time - 300 or offset == 0:
                            if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                    and left_time > (
                                    sub_max_end[sub_index + 1] if self.sub_files else approx_end_time) - 180):
                                sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(offset),
                                                            'disc_output_name': disc_output_name}
                                sub_index += 1
                    if play_item_marks:
                        for mark in play_item_marks:
                            time_shift = offset + (mark - play_item_in_out_time[1]) / 45000
                            if sub_index <= subtitle_index and j == chapter_index:
                                sub_end_time = time_shift + (
                                    sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift),
                                                            'disc_output_name': disc_output_name}
                                sub_index += 1
                                if sub_combo_index.get(sub_index):
                                    chapter_index = sub_combo_index[sub_index]
                            elif sub_index > subtitle_index:
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_end_time = time_shift + (
                                        sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                                'bdmv_index': bdmv_index, 'chapter_index': j,
                                                                'offset': get_time_str(time_shift),
                                                                'disc_output_name': disc_output_name}
                                    sub_index += 1
                            j += 1
                    offset += (play_item_in_out_time[2] - play_item_in_out_time[1]) / 45000
                    left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000
            self._configuration_default_chapter_segments_checked(configuration)
            CONFIGURATION = configuration
            return configuration
        for folder, chapter, selected_mpls in self.select_mpls_from_table(table):
            disc_output_name = self._resolve_disc_output_name(selected_mpls)
            for bdmv_index in range(table.rowCount()):
                if table.item(bdmv_index, 0).text() == folder:
                    break
            bdmv_index += 1
            start_time = 0
            sub_end_time = sub_max_end[sub_index] if self.sub_files else approx_end_time
            left_time = chapter.get_total_time()
            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                        'bdmv_index': bdmv_index, 'chapter_index': 1, 'offset': '0',
                                        'disc_output_name': disc_output_name}
            j = 1
            for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                play_item_marks = chapter.mark_info.get(i)
                chapter_num = len(play_item_marks or [])
                if play_item_marks:
                    play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
                    time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                    if time_shift > sub_end_time - 300:
                        if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                and left_time > (
                                sub_max_end[sub_index + 1] if self.sub_files else approx_end_time) - 180):
                            sub_index += 1
                            sub_end_time = (
                                        time_shift + (sub_max_end[sub_index] if self.sub_files else approx_end_time))
                            configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                        'bdmv_index': bdmv_index, 'chapter_index': j,
                                                        'offset': get_time_str(time_shift),
                                                        'disc_output_name': disc_output_name}

                    if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                        k = j
                        for mark in play_item_marks[1:]:
                            k += 1
                            time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                            if time_shift > sub_end_time and (
                                    play_item_in_out_time[2] - mark) / 45000 > 1200:
                                sub_index += 1
                                sub_end_time = (time_shift + (
                                    sub_max_end[sub_index] if self.sub_files else approx_end_time))
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls,
                                                            'bdmv_index': bdmv_index, 'chapter_index': k,
                                                            'offset': get_time_str(time_shift),
                                                            'disc_output_name': disc_output_name}

                j += chapter_num
                start_time += play_item_in_out_time[2] - play_item_in_out_time[1]
                left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000

            sub_index += 1
            if sub_index == len(self.sub_files):
                break
        self._configuration_default_chapter_segments_checked(configuration)
        CONFIGURATION = configuration
        return configuration

    def generate_configuration_from_selected_mpls(self, selected_mpls: list[tuple[str, str]],
                                                  sub_combo_index: Optional[dict[int, int]] = None,
                                                  subtitle_index: Optional[int] = None,
                                                  cancel_event: Optional[threading.Event] = None
                                                  ) -> dict[int, dict[str, int | str]]:
        if not selected_mpls:
            return {}
        configuration = {}
        sub_index = 0
        global CONFIGURATION
        approx_end_time = float(
            getattr(self, 'approx_episode_duration_seconds', DEFAULT_APPROX_EPISODE_DURATION_SECONDS)
            or DEFAULT_APPROX_EPISODE_DURATION_SECONDS)

        if self.sub_files:
            # Always use single process in main thread to avoid multiprocessing edge cases.
            missing = [p for p in self.sub_files if p and p not in self._subtitle_cache]
            if missing:
                # Use single-process loading directly in main thread.
                for p in missing:
                    try:
                        self._subtitle_cache[p] = Subtitle(p)
                    except Exception as e:
                        print(f'Failed to load subtitle file ｢{p}｣: {str(e)}')
            sub_max_end = [self._subtitle_cache[p].max_end_time() for p in self.sub_files]
        else:
            sub_max_end = []

        # Keep bdmv_index stable with table1/disc sequence (not selected order).
        folder_to_bdmv_index: dict[str, int] = {}
        for i, f in enumerate(getattr(self, 'bluray_folders', []) or []):
            try:
                folder_to_bdmv_index[os.path.normpath(str(f))] = int(i + 1)
            except Exception:
                pass

        if sub_combo_index:
            chapter_index = sub_combo_index[sub_index]
            for folder, selected_mpls_no_ext in selected_mpls:
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                folder_n = os.path.normpath(str(folder))
                if folder_n not in folder_to_bdmv_index:
                    folder_to_bdmv_index[folder_n] = len(folder_to_bdmv_index) + 1
                bdmv_index = folder_to_bdmv_index[folder_n]
                disc_output_name = self._resolve_disc_output_name(selected_mpls_no_ext)
                chapter = Chapter(selected_mpls_no_ext + '.mpls')
                offset = 0
                j = 1
                left_time = chapter.get_total_time()
                sub_end_time = sub_max_end[sub_index] if self.sub_files else approx_end_time
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    if sub_index <= subtitle_index and j == chapter_index:
                        sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                        configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                    'bdmv_index': bdmv_index, 'chapter_index': j,
                                                    'offset': get_time_str(offset),
                                                    'disc_output_name': disc_output_name}
                        sub_index += 1
                        if sub_combo_index.get(sub_index):
                            chapter_index = sub_combo_index[sub_index]
                    elif sub_index > subtitle_index:
                        if offset > sub_end_time - 300 or offset == 0:
                            if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                    and left_time > (
                                    sub_max_end[sub_index + 1] if self.sub_files else approx_end_time) - 180):
                                sub_end_time = offset + (sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(offset),
                                                            'disc_output_name': disc_output_name}
                                sub_index += 1
                    if play_item_marks:
                        for mark in play_item_marks:
                            time_shift = offset + (mark - play_item_in_out_time[1]) / 45000
                            if sub_index <= subtitle_index and j == chapter_index:
                                sub_end_time = time_shift + (
                                    sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift),
                                                            'disc_output_name': disc_output_name}
                                sub_index += 1
                                if sub_combo_index.get(sub_index):
                                    chapter_index = sub_combo_index[sub_index]
                            elif sub_index > subtitle_index:
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_end_time = time_shift + (
                                        sub_max_end[sub_index] if self.sub_files else approx_end_time)
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                                'bdmv_index': bdmv_index, 'chapter_index': j,
                                                                'offset': get_time_str(time_shift),
                                                                'disc_output_name': disc_output_name}
                                    sub_index += 1
                            j += 1
                    offset += (play_item_in_out_time[2] - play_item_in_out_time[1]) / 45000
                    left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000
            self._configuration_default_chapter_segments_checked(configuration)
            CONFIGURATION = configuration
            return configuration

        if not self.sub_files:
            global_i = 0
            for group in self._group_selected_mpls_by_folder_runs(selected_mpls):
                part = self._volume_configuration_no_sub_files(group, cancel_event=cancel_event)
                for k in sorted(part.keys(), key=int):
                    configuration[global_i] = part[k]
                    global_i += 1
        else:
            for folder, selected_mpls_no_ext in selected_mpls:
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                folder_n = os.path.normpath(str(folder))
                if folder_n not in folder_to_bdmv_index:
                    folder_to_bdmv_index[folder_n] = len(folder_to_bdmv_index) + 1
                bdmv_index = folder_to_bdmv_index[folder_n]
                disc_output_name = self._resolve_disc_output_name(selected_mpls_no_ext)
                chapter = Chapter(selected_mpls_no_ext + '.mpls')
                start_time = 0
                sub_end_time = sub_max_end[sub_index] if self.sub_files else approx_end_time
                left_time = chapter.get_total_time()
                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                            'bdmv_index': bdmv_index, 'chapter_index': 1, 'offset': '0',
                                            'disc_output_name': disc_output_name}
                j = 1
                for i, play_item_in_out_time in enumerate(chapter.in_out_time):
                    play_item_marks = chapter.mark_info.get(i)
                    chapter_num = len(play_item_marks or [])
                    if play_item_marks:
                        play_item_duration_time = play_item_in_out_time[2] - play_item_in_out_time[1]
                        time_shift = (start_time + play_item_marks[0] - play_item_in_out_time[1]) / 45000
                        if time_shift > sub_end_time - 300:
                            if (((sub_index + 1 < len(self.sub_files)) if self.sub_files else True)
                                    and left_time > (
                                    sub_max_end[sub_index + 1] if self.sub_files else approx_end_time) - 180):
                                sub_index += 1
                                sub_end_time = (time_shift + (
                                    sub_max_end[sub_index] if self.sub_files else approx_end_time))
                                configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                            'bdmv_index': bdmv_index, 'chapter_index': j,
                                                            'offset': get_time_str(time_shift),
                                                            'disc_output_name': disc_output_name}

                        if play_item_duration_time / 45000 > 2600 and sub_end_time - time_shift < 1800:
                            k = j
                            for mark in play_item_marks[1:]:
                                k += 1
                                time_shift = (start_time + mark - play_item_in_out_time[1]) / 45000
                                if time_shift > sub_end_time and (
                                        play_item_in_out_time[2] - mark) / 45000 > 1200:
                                    sub_index += 1
                                    sub_end_time = (time_shift + (
                                        sub_max_end[sub_index] if self.sub_files else approx_end_time))
                                    configuration[sub_index] = {'folder': folder, 'selected_mpls': selected_mpls_no_ext,
                                                                'bdmv_index': bdmv_index, 'chapter_index': k,
                                                                'offset': get_time_str(time_shift),
                                                                'disc_output_name': disc_output_name}

                    j += chapter_num
                    start_time += play_item_in_out_time[2] - play_item_in_out_time[1]
                    left_time += (play_item_in_out_time[1] - play_item_in_out_time[2]) / 45000

                sub_index += 1
                if sub_index == len(self.sub_files):
                    break
        self._configuration_default_chapter_segments_checked(configuration)
        CONFIGURATION = configuration
        return configuration
