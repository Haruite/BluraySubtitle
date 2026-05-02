import threading
import traceback
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.exports.utils import print_tb_string_terminal, print_terminal_line
from src.runtime.services import _Cancelled, BluraySubtitle


class RemuxWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, bdmv_path: str, sub_files: list[str], checked: bool, output_folder: str,
                 configuration: dict[int, dict[str, int | str]], selected_mpls: list[tuple[str, str]],
                 cancel_event: threading.Event, sp_entries: list[dict[str, int | str]],
                 episode_output_names: list[str], episode_subtitle_languages: list[str],
                 movie_mode: bool = False,
                 track_selection_config: Optional[dict[str, dict[str, list[str]]]] = None,
                 track_language_config: Optional[dict[str, dict[str, str]]] = None,
                 track_lossless_audio_config: Optional[dict[str, dict[str, str]]] = None):
        super().__init__()
        self.bdmv_path = bdmv_path
        self.sub_files = sub_files
        self.checked = checked
        self.output_folder = output_folder
        self.configuration = configuration
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.sp_entries = sp_entries
        self.episode_output_names = episode_output_names
        self.episode_subtitle_languages = episode_subtitle_languages
        self.movie_mode = bool(movie_mode)
        self.track_selection_config = track_selection_config or {}
        self.track_language_config = track_language_config or {}
        self.track_lossless_audio_config = track_lossless_audio_config or {}

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            bs = BluraySubtitle(self.bdmv_path, self.sub_files, self.checked, progress_cb, movie_mode=self.movie_mode)
            bs.configuration = self.configuration
            bs.track_selection_config = self.track_selection_config
            bs.track_language_config = self.track_language_config
            bs.track_lossless_audio_config = self.track_lossless_audio_config
            bs.episodes_remux(
                None,
                self.output_folder,
                selected_mpls=self.selected_mpls,
                configuration=self.configuration,
                cancel_event=self.cancel_event,
                ensure_tools=False,
                sp_entries=self.sp_entries,
                episode_output_names=self.episode_output_names,
                episode_subtitle_languages=self.episode_subtitle_languages
            )
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