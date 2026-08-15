import threading
import traceback
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import pyqtSignal, QObject

from src.exports.utils import print_terminal_line, print_tb_string_terminal
from src.runtime import TaskCancelled
from src.runtime.services import BluraySubtitle


@dataclass(frozen=True)
class MergeSubtitleRequest:
    bdmv_path: str
    subtitle_files: tuple[str, ...]
    complete_bluray_folder: bool
    selected_mpls: tuple[tuple[str, str], ...]
    subtitle_suffix: str = ''
    movie_tasks: tuple[tuple[str, str, str], ...] = ()
    series_configuration: tuple[tuple[str, str, int, str], ...] = ()


class MergeWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, request: MergeSubtitleRequest, cancel_event: threading.Event):
        super().__init__()
        self.request = request
        self.cancel_event = cancel_event

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise TaskCancelled()

            progress_cb(text='Preparing')
            request = self.request
            service = BluraySubtitle(
                request.bdmv_path,
                list(request.subtitle_files),
                request.complete_bluray_folder,
                progress_cb,
                movie_mode=bool(request.movie_tasks),
            )
            service.merge_subtitles(
                list(request.selected_mpls),
                movie_tasks=list(request.movie_tasks),
                series_configuration=list(request.series_configuration),
                subtitle_suffix=request.subtitle_suffix,
                cancel_event=self.cancel_event,
            )
            service.completion()
            if self.cancel_event.is_set():
                raise TaskCancelled()
            if request.movie_tasks:
                print_terminal_line('[BluraySubtitle] Merge worker (movie mode): finished successfully.')
            else:
                print_terminal_line('[BluraySubtitle] Merge worker: finished successfully.')
        except TaskCancelled:
            print_terminal_line('[BluraySubtitle] Merge worker: canceled.')
            self.canceled.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)
        else:
            self.finished.emit()
