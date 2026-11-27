from contextvars import copy_context
import os
import threading
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from functools import partial

from PyQt6.QtCore import pyqtSignal, QObject

from src.core.i18n import translate_text
from src.domain import MKV, Subtitle
from src.domain.subtitles import ass_model, list_subtitle_files
from src.domain.subtitles.subtitle import ASS_EXTENSIONS
from src.exports.utils import get_time_str, print_terminal_line, print_exc_terminal, print_tb_string_terminal
from src.runtime import TaskCancelled, worker_process_context
from src.runtime.services import BluraySubtitle


class SubtitleFolderScanWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    result = pyqtSignal(object)
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, seq: int, mode: int, subtitle_folder: str, bdmv_path: str, checked: bool,
                 selected_mpls: list[tuple[str, str]], cancel_event: threading.Event,
                 movie_mode: bool = False, disc_folders: tuple[str, ...] = ()):
        super().__init__()
        self._context = copy_context()
        self.seq = seq
        self.mode = mode
        self.subtitle_folder = subtitle_folder
        self.bdmv_path = bdmv_path
        self.checked = checked
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.movie_mode = bool(movie_mode)
        self.disc_folders = disc_folders

    def run(self):
        self._context.run(self._run)

    def _run(self):
        try:
            if self.cancel_event.is_set():
                raise TaskCancelled()
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
                        raise TaskCancelled()
                    self.label.emit(f'Reading MKV {i + 1}/{len(mkv_paths)}')
                    rows.append((p, get_time_str(MKV(p).get_duration())))
                    self.progress.emit(int((i + 1) / total * 1000))
                if self.cancel_event.is_set():
                    raise TaskCancelled()
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': rows})
                print_terminal_line('[BluraySubtitle] Subtitle-folder scan worker: finished successfully (MKV list).')
                return

            folder = self.subtitle_folder.strip()
            files = list_subtitle_files(folder)
            if not files:
                if self.cancel_event.is_set():
                    raise TaskCancelled()
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': [], 'configuration': {}})
                print_terminal_line(
                    '[BluraySubtitle] Subtitle-folder scan worker: finished successfully (no subtitle files).')
                return

            self.label.emit('Parsing Subtitles 0/{}'.format(len(files)))
            self.progress.emit(0)

            try:
                durations = self._scan_durations(files)
            except TaskCancelled:
                raise
            except Exception as error:
                print(f'{translate_text("Parallel subtitle scan failed, switching to sequential scanning: ")}{error}')
                durations = self._scan_durations_single(files)

            if not durations:
                if self.cancel_event.is_set():
                    raise TaskCancelled()
                print(translate_text('Failed to load all subtitle files'))
                self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': [], 'configuration': {}})
                print_terminal_line(
                    '[BluraySubtitle] Subtitle-folder scan worker: finished successfully (no subtitles loaded).')
                return

            print(f'{translate_text("Loaded successfully ")}{len(durations)}{translate_text(" subtitle files")}')

            successful_files = [p for p in files if p in durations]
            rows = [(p, get_time_str(durations[p])) for p in successful_files]

            configuration = {}
            if not (self.movie_mode and self.mode in (1, 3, 4)):
                self.label.emit('Generating Configuration')
                self.progress.emit(850)
                try:
                    bs = BluraySubtitle(
                        self.bdmv_path, successful_files, self.checked, None, disc_folders=list(self.disc_folders),
                    )
                    configuration = bs.generate_configuration_from_selected_mpls(
                        self.selected_mpls,
                        cancel_event=self.cancel_event,
                        subtitle_durations=durations,
                    )
                except TaskCancelled:
                    raise
                except Exception as e:
                    print(f'{translate_text("Failed to generate configuration: ")}{str(e)}')
                    print_exc_terminal()
                    configuration = {}

            if self.cancel_event.is_set():
                raise TaskCancelled()
            self.progress.emit(1000)
            self.result.emit({'seq': self.seq, 'mode': self.mode, 'rows': rows, 'configuration': configuration,
                              'files': successful_files})
            print_terminal_line('[BluraySubtitle] Subtitle-folder scan worker: finished successfully.')
        except TaskCancelled:
            print_terminal_line('[BluraySubtitle] Subtitle-folder scan worker: canceled.')
            self.canceled.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)

    def _check_cancel(self):
        if self.cancel_event.is_set():
            raise TaskCancelled()

    def _scan_durations_single(self, files: list[str]) -> dict[str, float]:
        durations: dict[str, float] = {}
        total = len(files)
        for i, p in enumerate(files):
            self._check_cancel()
            try:
                durations[p] = Subtitle.read_duration(p, check_cancel=self._check_cancel)
                print(f'{translate_text("Subtitle file loaded ｢")}{p}｣')
            except TaskCancelled:
                raise
            except Exception as e:
                print(
                    f'{translate_text("Failed to load subtitle file ｢")}{p}｣: {type(e).__name__}: {str(e)}')
                print_exc_terminal()
            self.label.emit(f'Parsing Subtitles {i + 1}/{total} (loaded {len(durations)})')
            self.progress.emit(int((i + 1) / total * 700))
        return durations

    def _scan_durations(self, files: list[str]) -> dict[str, float]:
        if len(files) == 1:
            return self._scan_durations_single(files)

        durations: dict[str, float] = {}
        max_workers = min(len(files), os.cpu_count() or 1)
        thread_extensions = ('.sup',) + (ASS_EXTENSIONS if ass_model.ass_native else ())
        if all(path.lower().endswith(thread_extensions) for path in files):
            pool = ThreadPoolExecutor(max_workers=max_workers)
            scan = partial(Subtitle.read_duration, check_cancel=self._check_cancel)
        else:
            pool = ProcessPoolExecutor(max_workers=max_workers, mp_context=worker_process_context())
            scan = Subtitle.read_duration
        with pool as executor:
            futures = {executor.submit(scan, path): path for path in files}
            total = len(futures)
            for done, future in enumerate(as_completed(futures), 1):
                if self.cancel_event.is_set():
                    for pending in futures:
                        pending.cancel()
                    raise TaskCancelled()
                path = futures[future]
                try:
                    durations[path] = future.result()
                except TaskCancelled:
                    raise
                except Exception as error:
                    print(f'{translate_text("Failed to load subtitle file ｢")}{path}｣: {error}')
                self.label.emit(f'Parsing Subtitles {done}/{total}')
                self.progress.emit(int(done / total * 700))
        return durations
