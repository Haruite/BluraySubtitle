import os
import shutil
import threading
import traceback
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.exports.utils import force_remove_file, print_tb_string_terminal, print_terminal_line
from ..services import _Cancelled
from ..services import BluraySubtitle


class EncodeMkvFolderWorker(QObject):
    progress = pyqtSignal(int)
    label = pyqtSignal(str)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        mkv_rows: list[dict[str, str]],
        sp_rows: list[dict[str, str]],
        remux_folder: str,
        output_folder: str,
        cancel_event: threading.Event,
        vspipe_mode: str,
        x265_mode: str,
        x265_params: str,
        sub_pack_mode: str,
    ):
        super().__init__()
        self.mkv_rows = mkv_rows
        self.sp_rows = sp_rows
        self.remux_folder = str(remux_folder or '')
        self.output_folder = output_folder
        self.cancel_event = cancel_event
        self.vspipe_mode = vspipe_mode
        self.x265_mode = x265_mode
        self.x265_params = x265_params
        self.sub_pack_mode = sub_pack_mode

    def _link_or_copy(self, src: str, dst: str):
        if os.path.exists(dst):
            force_remove_file(dst)
        try:
            os.link(src, dst)
            return
        except Exception:
            pass
        shutil.copy2(src, dst)

    def _copy_non_mkv_from_remux_folder(self, src_root: str, dst_root: str):
        if not src_root or not os.path.isdir(src_root):
            return
        src_root = os.path.normpath(src_root)
        dst_root = os.path.normpath(dst_root)
        for cur, dirs, files in os.walk(src_root):
            if self.cancel_event.is_set():
                raise _Cancelled()
            rel = os.path.relpath(cur, src_root)
            if rel == '.':
                rel = ''
            dst_dir = os.path.join(dst_root, rel) if rel else dst_root
            os.makedirs(dst_dir, exist_ok=True)
            for d in dirs:
                os.makedirs(os.path.join(dst_dir, d), exist_ok=True)
            for fn in files:
                if fn.lower().endswith('.mkv'):
                    continue
                src = os.path.join(cur, fn)
                dst = os.path.join(dst_dir, fn)
                if os.path.exists(dst):
                    continue
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    pass

    def run(self):
        try:
            def progress_cb(value: Optional[int] = None, text: Optional[str] = None):
                if value is not None:
                    self.progress.emit(int(value))
                if text:
                    self.label.emit(str(text))
                if self.cancel_event.is_set():
                    raise _Cancelled()

            dst_folder = os.path.normpath(self.output_folder)
            os.makedirs(dst_folder, exist_ok=True)

            sub_files = [str(r.get('sub_path') or '') for r in self.mkv_rows]
            episode_subtitle_languages = [str(r.get('language') or '') for r in self.mkv_rows]

            bs = BluraySubtitle('', sub_files, True, progress_cb, movie_mode=True)
            bs.episode_subtitle_languages = episode_subtitle_languages

            total = max(1, len(self.mkv_rows) + len(self.sp_rows))
            done = 0
            for i, row in enumerate(self.mkv_rows):
                progress_cb(int(done / total * 1000), f'压制中 {done + 1}/{total}')
                src = os.path.normpath(str(row.get('src_path') or ''))
                out_name = str(row.get('output_name') or '').strip() or os.path.basename(src)
                if not out_name.lower().endswith('.mkv'):
                    out_name += '.mkv'
                dst = os.path.join(dst_folder, out_name)
                vpy_path = str(row.get('vpy_path') or '').strip()
                bs.encode_task(
                    dst,
                    dst_folder,
                    i + 1,
                    vpy_path,
                    self.vspipe_mode,
                    self.x265_mode,
                    self.x265_params,
                    self.sub_pack_mode,
                    source_file=src
                )
                done += 1

            sps_out = None
            for row in self.sp_rows:
                progress_cb(int(done / total * 1000), f'压制中 {done + 1}/{total}')
                src = os.path.normpath(str(row.get('src_path') or ''))
                out_name = str(row.get('output_name') or '').strip() or os.path.basename(src)
                if not out_name.lower().endswith('.mkv'):
                    out_name += '.mkv'
                if sps_out is None:
                    sps_out = os.path.join(dst_folder, 'SPs')
                    os.makedirs(sps_out, exist_ok=True)
                dst = os.path.join(sps_out, out_name)
                vpy_path = str(row.get('vpy_path') or '').strip()
                bs.encode_task(
                    dst,
                    sps_out,
                    -1,
                    vpy_path,
                    self.vspipe_mode,
                    self.x265_mode,
                    self.x265_params,
                    self.sub_pack_mode,
                    source_file=src
                )
                done += 1

            try:
                progress_cb(int(done / total * 1000), '复制非MKV文件')
                self._copy_non_mkv_from_remux_folder(self.remux_folder, dst_folder)
            except Exception:
                pass

            progress_cb(1000, '完成')
        except _Cancelled:
            print_terminal_line('[BluraySubtitle] Encode MKV-folder worker: canceled.')
            self.canceled.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)
        else:
            print_terminal_line('[BluraySubtitle] Encode MKV-folder worker: finished successfully.')
            self.finished.emit()
