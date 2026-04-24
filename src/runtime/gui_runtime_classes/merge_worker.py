import sys
import threading
import traceback
from typing import Optional

from PyQt6.QtCore import pyqtSignal, QObject

from src.core.i18n import translate_text
from src.domain import Subtitle
from src.exports.utils import print_terminal_line, print_tb_string_terminal
from src.runtime.services import _Cancelled, BluraySubtitle


class MergeWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, bdmv_path: str, sub_files: list[str], checked: bool,
                 selected_mpls: list[tuple[str, str]], cancel_event: threading.Event,
                 subtitle_suffix: str = ''):
        super().__init__()
        self.bdmv_path = bdmv_path
        self.sub_files = sub_files
        self.checked = checked
        self.selected_mpls = selected_mpls
        self.cancel_event = cancel_event
        self.movie_tasks: list[tuple[str, str, str]] = []
        self.subtitle_suffix = str(subtitle_suffix or '')

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            progress_cb(text='准备中')
            if self.movie_tasks:
                total = len(self.movie_tasks) or 1
                suffix = self.subtitle_suffix
                for idx, (sub_path, folder, selected_mpls_no_ext) in enumerate(self.movie_tasks, start=1):
                    if self.cancel_event.is_set():
                        raise _Cancelled()
                    progress_cb(int((idx - 1) / total * 1000), f'写入字幕文件 {idx}/{total}')
                    sub = Subtitle(sub_path)
                    if hasattr(sub, 'content'):
                        sub.dump(folder + suffix, selected_mpls_no_ext + suffix)
                progress_cb(1000, '完成')
                print_terminal_line('[BluraySubtitle] Merge worker (movie mode): finished successfully.')
            else:
                bs = BluraySubtitle(self.bdmv_path, self.sub_files, self.checked, progress_cb)
                bs.subtitle_suffix = self.subtitle_suffix

                # Select subtitle preload strategy by platform.
                if self.sub_files:
                    progress_cb(text='加载字幕')
                    if sys.platform == 'win32':
                        # Windows: prefer multiprocessing.
                        try:
                            bs._preload_subtitles_multiprocess(self.sub_files, self.cancel_event)
                        except Exception as e:
                            print(
                                f'{translate_text("Multiprocess load failed, switching to single process: ")}{str(e)}')
                            # Fallback to single-process loading.
                            for p in self.sub_files:
                                if self.cancel_event.is_set():
                                    raise _Cancelled()
                                try:
                                    bs._subtitle_cache[p] = Subtitle(p)
                                except Exception as e2:
                                    print(
                                        f'{translate_text("Failed to load subtitle file ｢")}{p}{translate_text("｣: ")}{str(e2)}')
                    else:
                        # Linux: try multiprocessing, then fallback to single process on failure.
                        try:
                            bs._preload_subtitles_multiprocess(self.sub_files, self.cancel_event)
                        except Exception as e:
                            print(
                                f'{translate_text("Multiprocess load failed, switching to single process: ")}{str(e)}')
                            # Fallback to single-process loading.
                            for p in self.sub_files:
                                if self.cancel_event.is_set():
                                    raise _Cancelled()
                                try:
                                    bs._subtitle_cache[p] = Subtitle(p)
                                except Exception as e2:
                                    print(
                                        f'{translate_text("Failed to load subtitle file ｢")}{p}{translate_text("｣: ")}{str(e2)}')

                progress_cb(text='生成配置')
                configuration = bs.generate_configuration_from_selected_mpls(
                    self.selected_mpls,
                    cancel_event=self.cancel_event
                )
                progress_cb(text='合并字幕')
                bs.generate_bluray_subtitle(configuration=configuration, cancel_event=self.cancel_event)
                bs.completion()
                print_terminal_line('[BluraySubtitle] Merge worker: finished successfully.')
        except _Cancelled:
            print_terminal_line('[BluraySubtitle] Merge worker: canceled.')
            self.canceled.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)
        else:
            self.finished.emit()
