"""Discover merge sources and read ISO playlists outside the GUI thread."""

import os
import shutil
import tempfile
import threading
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.i18n import translate_text
from src.domain.media.iso_playlists import extract_iso_playlists
from src.runtime import TaskCancelled


class MergeSourceScanWorker(QThread):
    label = pyqtSignal(str)

    def __init__(self, source_folder: str, temporary_folder: str,
                 cache: dict[tuple[str, int, int], str], cancel_event: threading.Event, parent=None):
        super().__init__(parent)
        self.source_folder = source_folder
        self.temporary_folder = temporary_folder
        self.cache = dict(cache)
        self.cancel_event = cancel_event
        self.sources: list[tuple[str, str]] = []
        self.error = ''
        self.was_canceled = False

    def run(self):
        created_directories = []
        try:
            iso_paths = []
            for root, dirs, files in os.walk(self.source_folder):
                if self.cancel_event.is_set():
                    raise TaskCancelled()
                dirs[:] = sorted(name for name in dirs if os.path.abspath(os.path.join(root, name)) != self.temporary_folder)
                if os.path.isdir(os.path.join(root, 'BDMV', 'PLAYLIST')):
                    self.sources.append((root, root))
                for name in sorted(files):
                    path = os.path.join(root, name)
                    if name.lower().endswith('.iso') and os.path.getsize(path) > 5 * 1024 ** 3:
                        iso_paths.append(path)
            for path in iso_paths:
                if self.cancel_event.is_set():
                    raise TaskCancelled()
                stat = os.stat(path)
                key = (os.path.abspath(path), stat.st_size, stat.st_mtime_ns)
                if key not in self.cache:
                    self.label.emit(translate_text('Reading ISO playlists: {path}').format(path=path))
                    destination = tempfile.mkdtemp(prefix='disc-', dir=self.temporary_folder)
                    created_directories.append(destination)
                    extract_iso_playlists(path, destination, self.cancel_event)
                    self.cache[key] = destination
                # Keep the real ISO path as source identity and output-name input.
                self.sources.append((self.cache[key], path))
        except TaskCancelled:
            self.was_canceled = True
        except Exception:
            self.error = traceback.format_exc()
        finally:
            if self.was_canceled or self.error:
                for directory in created_directories:
                    shutil.rmtree(directory, ignore_errors=True)
