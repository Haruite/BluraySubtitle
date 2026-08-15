import threading
import traceback
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.exports.utils import mkvmerge_cancellation_scope, print_tb_string_terminal, print_terminal_line
from src.runtime.remux import RemuxRequest
from src.runtime import TaskCancelled
from src.runtime.services import BluraySubtitle


class RemuxWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, request: RemuxRequest, cancel_event: threading.Event):
        super().__init__()
        self.request = request
        self.cancel_event = cancel_event

    def run(self):
        try:
            from src.runtime.services_split.media_info_and_track_mapping import mpls_playlist_caches_clear

            request = self.request
            mpls_playlist_caches_clear()

            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise TaskCancelled()

            bs = BluraySubtitle(
                request.bdmv_path,
                list(request.subtitle_files),
                request.complete_bluray_folder,
                progress_cb,
                movie_mode=request.movie_mode,
                mux_dolby_vision=request.mux_dolby_vision,
            )
            with mkvmerge_cancellation_scope(self.cancel_event):
                bs.episodes_remux(request, cancel_event=self.cancel_event)
            if self.cancel_event.is_set():
                raise TaskCancelled()
        except TaskCancelled:
            print_terminal_line('[BluraySubtitle] Remux worker: canceled.')
            self.canceled.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)
        else:
            print_terminal_line('[BluraySubtitle] Remux worker: finished successfully.')
            self.finished.emit()
