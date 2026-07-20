import threading
import traceback
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.core.i18n import translate_text
from src.exports.utils import print_terminal_line, print_tb_string_terminal
from src.runtime.services import BluraySubtitle, _Cancelled


@dataclass(frozen=True)
class AddChaptersRequest:
    bdmv_path: str
    mkv_targets: tuple[tuple[str, str], ...]
    selected_mpls: tuple[str, ...]
    edit_original: bool


class ChapterWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, request: AddChaptersRequest, cancel_event: threading.Event):
        super().__init__()
        self.request = request
        self.cancel_event = cancel_event

    def run(self) -> None:
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None) -> None:
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            request = self.request
            progress_cb(0, 'Preparing')
            service = BluraySubtitle(
                request.bdmv_path,
                [source_path for source_path, _ in request.mkv_targets],
                request.edit_original,
                progress_cb,
            )
            service.add_chapters_to_mkv(
                list(request.mkv_targets),
                list(request.selected_mpls),
                request.edit_original,
                cancel_event=self.cancel_event,
            )
            print_terminal_line(translate_text('[BluraySubtitle] Add-chapters worker: finished successfully.'))
        except _Cancelled:
            print_terminal_line(translate_text('[BluraySubtitle] Add-chapters worker: canceled.'))
            self.canceled.emit()
        except Exception:
            error_text = traceback.format_exc()
            print_tb_string_terminal(error_text)
            self.failed.emit(error_text)
        else:
            self.finished.emit()
