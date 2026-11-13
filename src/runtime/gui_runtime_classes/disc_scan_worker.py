"""Read the disc and playlist inventory outside the GUI thread."""

import os
import shutil
import tempfile
import threading
import traceback
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from types import MappingProxyType

from PyQt6.QtCore import QThread, pyqtSignal

from src.bdmv import Chapter
from src.domain.media.iso_playlists import extract_iso_playlists
from src.exports.utils import get_folder_size
from src.runtime import TaskCancelled
from src.runtime.services import BluraySubtitle
from src.runtime.sp import filter_m2ts_file_detail_by_basenames


# Short, unreferenced menu streams are excluded from duration-based auto-selection.
SP_ORPHAN_M2TS_SKIP_DURATION_BYTES = 512 * 1024


@dataclass(frozen=True)
class PlaylistInventory:
    path: str
    chapter: Chapter
    stream_files: tuple[str, ...]
    detail: str
    tracks: list[dict[str, object]]


@dataclass(frozen=True)
class DiscPlaylists:
    root: str
    source_path: str
    size: str
    chapters: Mapping[str, Chapter]
    main_playlists: frozenset[str]


@dataclass(frozen=True)
class DiscInventory:
    playlists: dict[str, PlaylistInventory]
    standalone_streams: dict[str, tuple[float, str, str]]


class DiscScanWorker(QThread):
    progress = pyqtSignal(str, object)
    sources_found = pyqtSignal(object)
    playlists_ready = pyqtSignal(int, object)

    def __init__(self, source_folder: str, function_id: int, movie_mode: bool,
                 temporary_folder: str, cache: dict[tuple[str, int, int], str],
                 previous_order: list[str], parent=None):
        super().__init__(parent)
        self.source_folder = source_folder
        self.function_id = function_id
        self.movie_mode = movie_mode
        self.temporary_folder = temporary_folder
        self.cache = dict(cache)
        self._previous_positions = {path: index for index, path in enumerate(previous_order)}
        self.cancel_event = threading.Event()
        self.discs: dict[str, DiscInventory] = {}
        self.error = ''
        self.was_canceled = False

    def check_canceled(self) -> None:
        if self.cancel_event.is_set():
            raise TaskCancelled()

    def run(self) -> None:
        created_directories = []
        try:
            sources: list[tuple[str, bool]] = []
            include_iso = self.function_id == 1
            for root, dirs, files in os.walk(self.source_folder):
                self.check_canceled()
                dirs.sort()
                if os.path.isdir(os.path.join(root, 'BDMV', 'PLAYLIST')):
                    sources.append((root, False))
                    # The Blu-ray structure is already found. Searching STREAM and BACKUP cannot find another disc.
                    if 'BDMV' in dirs:
                        dirs.remove('BDMV')
                if include_iso:
                    dirs[:] = [name for name in dirs if os.path.abspath(os.path.join(root, name)) != self.temporary_folder]
                    for name in sorted(files):
                        self.check_canceled()
                        path = os.path.join(root, name)
                        if name.lower().endswith('.iso') and os.path.getsize(path) > 5 * 1024 ** 3:
                            sources.append((path, True))
            sources.sort(key=lambda source: (
                self._previous_positions.get(os.path.normpath(source[0]), len(self._previous_positions)),
                os.path.normpath(source[0]),
            ))
            self.sources_found.emit(tuple(path for path, _ in sources))

            service = BluraySubtitle(self.source_folder, disc_folders=[])
            for index, (path, is_iso) in enumerate(sources, start=1):
                self.check_canceled()
                root = path
                iso_size = None
                if is_iso:
                    stat = os.stat(path)
                    iso_size = f'{stat.st_size / 1024 ** 3:.2f} GiB'
                    key = (os.path.abspath(path), stat.st_size, stat.st_mtime_ns)
                    if key not in self.cache:
                        self.progress.emit('Reading ISO playlists: {path}', {'path': path})
                        destination = tempfile.mkdtemp(prefix='disc-', dir=self.temporary_folder)
                        created_directories.append(destination)
                        extract_iso_playlists(path, destination, self.cancel_event)
                        self.cache[key] = destination
                    root = self.cache[key]
                self.progress.emit('Reading disc {current}/{total}', {'current': index, 'total': len(sources)})
                playlist_dir = os.path.join(root, 'BDMV', 'PLAYLIST')
                stream_dir = os.path.join(root, 'BDMV', 'STREAM')
                chapters: dict[str, Chapter] = {}
                names = sorted(name for name in os.listdir(playlist_dir) if name.lower().endswith('.mpls'))
                next_update = monotonic() + 0.2
                for number, name in enumerate(names, start=1):
                    self.check_canceled()
                    playlist_path = os.path.normpath(os.path.join(playlist_dir, name))
                    chapters[playlist_path] = Chapter(playlist_path)
                    if monotonic() >= next_update:
                        self.progress.emit('Reading disc {current}/{total} · playlist {playlist}/{playlists}', {
                            'current': index, 'total': len(sources), 'playlist': number, 'playlists': len(names),
                        })
                        next_update = monotonic() + 0.2
                use_playlist_only = False
                if self.function_id in (1, 2):
                    try:
                        use_playlist_only = not any(name.lower().endswith('.m2ts') for name in os.listdir(stream_dir))
                    except OSError:
                        use_playlist_only = True
                main = service.get_default_main_mpls(
                    root, use_playlist_only, movie_mode=self.movie_mode,
                    chapters=chapters, check_canceled=self.check_canceled,
                )
                size = iso_size if iso_size is not None else get_folder_size(root, check_canceled=self.check_canceled)
                # Playlist rows only need chapter data. Let them paint while we read stream timing and tracks.
                disc = DiscPlaylists(root, path, size, MappingProxyType(chapters), frozenset(main))
                self.playlists_ready.emit(index - 1, disc)
                playlists = self._read_playlists(chapters)
                standalone = self._read_standalone_streams(stream_dir, playlists) if self.function_id in (3, 4) else {}
                self.discs[os.path.normpath(root)] = DiscInventory(playlists, standalone)
            self.check_canceled()
        except TaskCancelled:
            self.was_canceled = True
        except Exception:
            self.error = traceback.format_exc()
        finally:
            if self.was_canceled or self.error:
                invalid = set(created_directories)
                for directory in invalid:
                    shutil.rmtree(directory, ignore_errors=True)
                self.cache = {key: path for key, path in self.cache.items() if path not in invalid}

    def _read_playlists(self, chapters: dict[str, Chapter]) -> dict[str, PlaylistInventory]:
        playlists = {}
        for path, chapter in chapters.items():
            self.check_canceled()
            stream_files = tuple(dict.fromkeys(f'{clip}.m2ts' for clip, _, _ in chapter.in_out_time))
            detail = ''
            tracks = []
            if self.function_id in (3, 4, 5):
                detail = BluraySubtitle.m2ts_file_detail_from_mpls_playlist(
                    path, chapter=chapter, check_canceled=self.check_canceled,
                )
                tracks = BluraySubtitle._mpls_track_streams(path)
            playlists[path] = PlaylistInventory(path, chapter, stream_files, detail, tracks)
        return playlists

    def _read_standalone_streams(
            self, stream_dir: str, playlists: dict[str, PlaylistInventory],
    ) -> dict[str, tuple[float, str, str]]:
        referenced = set()
        alternate_details = {}
        for playlist in playlists.values():
            self.check_canceled()
            if playlist.path.endswith('.mpls'):
                referenced.update(playlist.stream_files)
            else:
                for name in playlist.stream_files:
                    detail = filter_m2ts_file_detail_by_basenames(playlist.detail, [name])
                    if detail:
                        alternate_details.setdefault(name, detail)
        standalone = {}
        if not os.path.isdir(stream_dir):
            return standalone
        for name in sorted(os.listdir(stream_dir)):
            self.check_canceled()
            if not name.endswith('.m2ts') or name in referenced:
                continue
            path = os.path.join(stream_dir, name)
            duration, detail = BluraySubtitle._standalone_m2ts_timing(path, check_canceled=self.check_canceled)
            try:
                size = os.path.getsize(path)
            except OSError:
                reason = 'The size of this standalone M2TS could not be read.'
                duration = 0.0
            else:
                if size < SP_ORPHAN_M2TS_SKIP_DURATION_BYTES:
                    reason = 'This standalone M2TS is too small for duration-based selection.'
                    duration = 0.0
                else:
                    reason = 'No usable duration was found for this standalone M2TS.'
            standalone[name] = (duration, alternate_details.get(name, detail), reason)
        return standalone
