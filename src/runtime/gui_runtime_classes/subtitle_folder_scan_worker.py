import multiprocessing
import os
import sys
import threading
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

from PyQt6.QtCore import pyqtSignal, QObject

from src.core.i18n import translate_text
from src.domain import MKV, Subtitle
from src.domain.subtitles import parse_subtitle_worker as _parse_subtitle_worker
from src.exports.utils import get_time_str, print_terminal_line, print_exc_terminal, print_tb_string_terminal
from src.runtime.services import _Cancelled, BluraySubtitle


class SubtitleFolderScanWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    result = pyqtSignal(object)
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, seq: int, mode: int, subtitle_folder: str, bdmv_path: str, checked: bool,
                 selected_mpls: list[tuple[str, str]], cancel_event: threading.Event,
                 movie_mode: bool = False):
        super().__init__()
        self.seq = seq
        self.mode = mode
        self.subtitle_folder = subtitle_folder
        self.bdmv_path = bdmv_path
        self.checked = checked
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.movie_mode = bool(movie_mode)

    def run(self):
        try:
            if self.mode == 2:
                root = self.subtitle_folder.strip()
                mkv_paths = [
                    os.path.normpath(os.path.join(root, f))
                    for f in os.listdir(root)
                    if f.lower().endswith('.mkv') and os.path.isfile(os.path.join(root, f))
                ]
                mkv_paths.sort()
                rows = []
                total = len(mkv_paths) or 1
                for i, p in enumerate(mkv_paths):
                    if self.cancel_event.is_set():
                        raise _Cancelled()
                    self.label.emit(f'读取MKV {i + 1}/{len(mkv_paths)}')
                    rows.append((p, get_time_str(MKV(p).get_duration())))
                    self.progress.emit(int((i + 1) / total * 1000))
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': rows})
                print_terminal_line('[BluraySubtitle] Subtitle-folder scan worker: finished successfully (MKV list).')
                return

            folder = self.subtitle_folder.strip()
            files = []
            for f in os.listdir(folder):
                if f.endswith(".ass") or f.endswith(".ssa") or f.endswith('srt') or f.endswith('.sup'):
                    files.append(os.path.normpath(os.path.join(folder, f)))
            files.sort()
            if not files:
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': [], 'configuration': {}})
                print_terminal_line(
                    '[BluraySubtitle] Subtitle-folder scan worker: finished successfully (no subtitle files).')
                return

            self.label.emit('解析字幕 0/{}'.format(len(files)))
            self.progress.emit(0)

            # Choose subtitle parsing strategy by platform.
            if sys.platform == 'win32':
                # Windows: use multiprocessing.
                subtitle_cache = self._parse_subtitles_multiprocess(files)
            else:
                # Linux: try multiprocessing, then fallback to single process on failure.
                try:
                    subtitle_cache = self._parse_subtitles_multiprocess(files)
                except Exception as e:
                    print(
                        f'{translate_text("Multiprocessing parse failed, switching to single-process mode: ")}{str(e)}')
                    subtitle_cache = self._parse_subtitles_single(files)

            if not subtitle_cache:
                print(translate_text('Failed to load all subtitle files'))
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': [], 'configuration': {}})
                print_terminal_line(
                    '[BluraySubtitle] Subtitle-folder scan worker: finished successfully (no subtitles loaded).')
                return

            print(f'{translate_text("Loaded successfully ")}{len(subtitle_cache)}{translate_text(" subtitle files")}')

            successful_files = [p for p in files if p in subtitle_cache]

            try:
                rows = [(p, get_time_str(subtitle_cache[p].max_end_time())) for p in successful_files]
            except Exception as e:
                print(f'{translate_text("Failed to get subtitle duration: ")}{str(e)}')
                rows = [(p, '未知') for p in successful_files]

            configuration = {}
            if not (self.movie_mode and self.mode in (1, 3, 4)):
                self.label.emit('生成配置')
                self.progress.emit(850)
                try:
                    bs = BluraySubtitle(self.bdmv_path, successful_files, self.checked, None)
                    bs._subtitle_cache = subtitle_cache
                    configuration = bs.generate_configuration_from_selected_mpls(
                        self.selected_mpls,
                        cancel_event=self.cancel_event
                    )
                except Exception as e:
                    print(f'{translate_text("Failed to generate configuration: ")}{str(e)}')
                    print_exc_terminal()
                    configuration = {}

            self.progress.emit(1000)
            self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': rows, 'configuration': configuration,
                              'files': successful_files})
            print_terminal_line('[BluraySubtitle] Subtitle-folder scan worker: finished successfully.')
        except _Cancelled:
            print_terminal_line('[BluraySubtitle] Subtitle-folder scan worker: canceled.')
            self.canceled.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)

    def _parse_subtitles_with_fallback(self, files: list[str]) -> dict[str, Subtitle]:
        """Try multiprocessing subtitle parsing and fall back to single process on failure."""
        subtitle_cache: dict[str, Subtitle] = {}
        try:
            return self._parse_subtitles_multiprocess(files)
        except Exception as e:
            print(f'{translate_text("Multiprocessing parse failed, switching to single-process mode: ")}{str(e)}')
            return self._parse_subtitles_single(files)

    def _parse_subtitles_single(self, files: list[str]) -> dict[str, Subtitle]:
        """Parse subtitles in single-process mode."""
        subtitle_cache: dict[str, Subtitle] = {}
        total = len(files)
        loaded_count = 0
        for i, p in enumerate(files):
            if self.cancel_event.is_set():
                raise _Cancelled()
            try:
                sub = Subtitle(p)
                subtitle_cache[p] = sub
                loaded_count += 1
                print(f'{translate_text("Subtitle file loaded ｢")}{p}{translate_text("｣")}')
            except Exception as e:
                print(
                    f'{translate_text("Failed to load subtitle file ｢")}{p}{translate_text("｣: ")}{type(e).__name__}: {str(e)}')
                print_exc_terminal()
            self.label.emit(f'解析字幕 {i + 1}/{total}（已加载 {loaded_count}）')
            self.progress.emit(int((i + 1) / total * 700))
        return subtitle_cache

    def _parse_subtitles_multiprocess(self, files: list[str]) -> dict[str, Subtitle]:
        """Parse subtitles in multiprocessing mode."""
        if len(files) == 1:
            # For a single file, use single-process directly.
            return self._parse_subtitles_single(files)

        subtitle_cache: dict[str, Subtitle] = {}
        max_workers = min(len(files), os.cpu_count() or 1)
        try:
            mp_context = multiprocessing.get_context('spawn')
        except ValueError:
            mp_context = None
        try:
            with ProcessPoolExecutor(max_workers=max_workers, mp_context=mp_context) as ex:
                futures = [ex.submit(_parse_subtitle_worker, p) for p in files]
                done = 0
                total = len(futures)
                for fut in as_completed(futures):
                    if self.cancel_event.is_set():
                        for f in futures:
                            f.cancel()
                        raise _Cancelled()
                    p = None
                    try:
                        p, sub = fut.result()
                        if sub is not None:
                            subtitle_cache[p] = sub
                    except Exception as e:
                        if p:
                            print(
                                f'{translate_text("Failed to load subtitle file ｢")}{p}{translate_text("｣: ")}{str(e)}')
                        else:
                            print(f'{translate_text("Failed to load subtitle file: ")}{str(e)}')
                    done += 1
                    self.label.emit(f'解析字幕 {done}/{total}')
                    self.progress.emit(int(done / total * 700))
        except Exception as e:
            # Propagate exception so the caller can handle fallback.
            raise Exception(f'Multiprocessing parse failed: {str(e)}')
        return subtitle_cache
