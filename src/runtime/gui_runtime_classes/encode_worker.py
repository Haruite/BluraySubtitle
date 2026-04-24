import threading
import traceback
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.exports.utils import print_terminal_line, print_tb_string_terminal
from src.runtime.services import _Cancelled, BluraySubtitle


class EncodeWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, bdmv_path: str, sub_files: list[str], checked: bool, output_folder: str,
                 configuration: dict[int, dict[str, int | str]], selected_mpls: list[tuple[str, str]],
                 cancel_event: threading.Event, vpy_paths: list[str], sp_vpy_paths: list[str], sp_entries: list[dict[str, int | str]],
                 episode_output_names: list[str], episode_subtitle_languages: list[str],
                 vspipe_mode: str, x265_mode: str, x265_params: str, sub_pack_mode: str,
                 movie_mode: bool = False,
                 track_selection_config: Optional[dict[str, dict[str, list[str]]]] = None):
        super().__init__()
        self.bdmv_path = bdmv_path
        self.sub_files = sub_files
        self.checked = checked
        self.output_folder = output_folder
        self.configuration = configuration
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.vpy_paths = vpy_paths
        self.sp_vpy_paths = sp_vpy_paths
        self.sp_entries = sp_entries
        self.episode_output_names = episode_output_names
        self.episode_subtitle_languages = episode_subtitle_languages
        self.vspipe_mode = vspipe_mode
        self.x265_mode = x265_mode
        self.x265_params = x265_params
        self.sub_pack_mode = sub_pack_mode
        self.movie_mode = bool(movie_mode)
        self.track_selection_config = track_selection_config or {}

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
            bs.episodes_encode(
                None,
                self.output_folder,
                selected_mpls=self.selected_mpls,
                configuration=self.configuration,
                cancel_event=self.cancel_event,
                ensure_tools=False,
                vpy_paths=self.vpy_paths,
                sp_vpy_paths=self.sp_vpy_paths,
                sp_entries=self.sp_entries,
                episode_output_names=self.episode_output_names,
                episode_subtitle_languages=self.episode_subtitle_languages,
                vspipe_mode=self.vspipe_mode,
                x265_mode=self.x265_mode,
                x265_params=self.x265_params,
                sub_pack_mode=self.sub_pack_mode
            )
        except _Cancelled:
            print_terminal_line('[BluraySubtitle] Encode worker: canceled.')
            self.canceled.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)
        else:
            print_terminal_line('[BluraySubtitle] Encode worker: finished successfully.')
            self.finished.emit()
