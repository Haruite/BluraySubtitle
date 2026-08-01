import threading
import traceback
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.core.i18n import translate_text
from src.exports.utils import print_tb_string_terminal, print_terminal_line
from src.runtime.encode import EncodeRequest
from src.runtime.encode_results import (
    EncodeBatchResult,
    format_encode_batch_error_summary,
)
from src.runtime import TaskCancelled
from src.runtime.services import BluraySubtitle


class EncodeWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    finished_with_warnings = pyqtSignal(str)
    finished_with_errors = pyqtSignal(str)
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, request: EncodeRequest, cancel_event: threading.Event):
        super().__init__()
        self.request = request
        self.cancel_event = cancel_event

    def run(self):
        try:
            from src.bdmv.chapter import chapter_tail_trim_clear, chapter_tail_trim_register_path
            from src.runtime.services_split.media_info_and_track_mapping import mpls_playlist_caches_clear

            request = self.request
            chapter_tail_trim_clear()
            if (not request.movie_mode) and request.episode_trim_copyright_tail:
                for _folder, selected_mpls in request.selected_mpls:
                    playlist_path = str(selected_mpls or '').strip()
                    if not playlist_path:
                        continue
                    if not playlist_path.lower().endswith('.mpls'):
                        playlist_path += '.mpls'
                    chapter_tail_trim_register_path(playlist_path)
            mpls_playlist_caches_clear()

            def progress_callback(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise TaskCancelled()

            service = BluraySubtitle(
                request.source_root,
                [row.subtitle_path for row in request.main_rows],
                False,
                progress_callback,
                movie_mode=request.movie_mode,
                mux_dolby_vision=request.mux_dolby_vision,
            )
            batch_result = service.episodes_encode(
                request,
                cancel_event=self.cancel_event,
            )
            if not isinstance(batch_result, EncodeBatchResult):
                raise RuntimeError(translate_text('Encode batch did not return a result'))
        except TaskCancelled:
            print_terminal_line('[BluraySubtitle] Encode worker: canceled.')
            self.canceled.emit()
        except Exception:
            traceback_text = traceback.format_exc()
            print_tb_string_terminal(traceback_text)
            self.failed.emit(traceback_text)
        else:
            warnings = tuple(getattr(service, 'encode_warnings', ()) or ())
            if batch_result.failed_rows:
                print_terminal_line(
                    translate_text(
                        '[BluraySubtitle] Encode worker: completed with row errors.'
                    )
                )
                self.finished_with_errors.emit(
                    format_encode_batch_error_summary(batch_result, warnings)
                )
            elif warnings:
                print_terminal_line(
                    translate_text(
                        '[BluraySubtitle] Encode worker: finished with warnings.'
                    )
                )
                self.finished_with_warnings.emit('\n\n'.join(str(warning) for warning in warnings))
            else:
                print_terminal_line('[BluraySubtitle] Encode worker: finished successfully.')
                self.finished.emit()
