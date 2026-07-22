import threading
import traceback
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.exports.utils import print_tb_string_terminal, print_terminal_line
from src.runtime.remux import RemuxRequest
from src.runtime.services import _Cancelled, BluraySubtitle


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
            from src.bdmv.chapter import chapter_tail_trim_clear, chapter_tail_trim_register_path
            from src.runtime.services_split.media_info_and_track_mapping import mpls_playlist_caches_clear

            request = self.request
            chapter_tail_trim_clear()
            if (not request.movie_mode) and request.episode_trim_copyright_tail:
                for _folder, mpls_ne in request.selected_mpls:
                    stem = str(mpls_ne or '').strip()
                    if not stem:
                        continue
                    path = stem if stem.lower().endswith('.mpls') else stem + '.mpls'
                    chapter_tail_trim_register_path(path)
            mpls_playlist_caches_clear()

            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            bs = BluraySubtitle(
                request.bdmv_path,
                list(request.subtitle_files),
                request.complete_bluray_folder,
                progress_cb,
                movie_mode=request.movie_mode,
                mux_dolby_vision=request.mux_dolby_vision,
            )
            bs.track_selection_config = request.track_selection_config or {}
            bs.track_language_config = request.track_language_config or {}
            bs.track_lossless_audio_config = request.track_lossless_audio_config or {}
            bs.default_lossless_audio_codec = request.default_lossless_audio_codec
            bs.episodes_remux(request, cancel_event=self.cancel_event)
        except _Cancelled:
            print_terminal_line('[BluraySubtitle] Remux worker: canceled.')
            self.canceled.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)
        else:
            print_terminal_line('[BluraySubtitle] Remux worker: finished successfully.')
            self.finished.emit()
