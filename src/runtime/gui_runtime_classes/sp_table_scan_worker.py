import os
import threading
import traceback

from PyQt6.QtCore import QObject, pyqtSignal

from src.bdmv import M2TS, Chapter, pid_to_lang_from_m2ts_path
from src.core import FFMPEG_PATH
from src.exports.utils import print_tb_string_terminal, run_command
from src.runtime.services import BluraySubtitle


class SpTableScanWorker(QObject):
    """Probe one immutable snapshot of table3 rows outside the GUI thread.

    Paths and selection policy are captured before the thread starts. Media
    probes are cached by normalized path so repeated clips across playlists are
    read once per scan. Each result contains only row metadata, classification,
    and the calculated default track selection; the GUI thread remains the sole
    owner of widgets and applies the payload through its current worker identity.
    """

    result = pyqtSignal(int, bool, str, object)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, rows: list[dict[str, object]], cancel_event: threading.Event):
        super().__init__()
        self._rows = rows
        self._cancel_event = cancel_event

    def run(self):
        """Scan rows in visible order and emit exactly one result for each row."""
        try:
            # These caches belong to one table snapshot. They must not survive a
            # refresh because source files and visible selection policy can change.
            streams_cache: dict[str, list[dict[str, object]]] = {}
            still_image_cache: dict[str, bool] = {}
            audio_only_cache: dict[str, bool] = {}

            def _streams(path: str) -> list[dict[str, object]]:
                key = os.path.normpath(path or '')
                if key in streams_cache:
                    return streams_cache[key]
                try:
                    if str(key).lower().endswith('.m2ts'):
                        v = BluraySubtitle._m2ts_track_streams(key)
                    else:
                        v = BluraySubtitle._read_media_streams(key)
                except Exception:
                    v = []
                streams_cache[key] = v or []
                return streams_cache[key]

            def _available_tracks(streams: list[dict[str, object]]) -> dict[str, list[str]]:
                return {
                    'audio': [
                        str(stream.get('index', '')).strip()
                        for stream in streams
                        if str(stream.get('codec_type') or '') == 'audio'
                        and str(stream.get('index', '')).strip()
                    ],
                    'subtitle': [
                        str(stream.get('index', '')).strip()
                        for stream in streams
                        if str(stream.get('codec_type') or '') in ('subtitle', 'subtitles')
                        and str(stream.get('index', '')).strip()
                    ],
                }

            def _is_audio_only(path: str) -> bool:
                key = os.path.normpath(path or '')
                if key in audio_only_cache:
                    return audio_only_cache[key]
                try:
                    b = bool(BluraySubtitle._is_audio_only_media(key))
                except Exception:
                    b = False
                audio_only_cache[key] = b
                return b

            def _is_still_image(path: str) -> bool:
                key = os.path.normpath(path or '')
                if key in still_image_cache:
                    return still_image_cache[key]
                try:
                    video_track = next(
                        (stream for stream in _streams(key) if stream.get('codec_type') == 'video'),
                        None,
                    )
                    if video_track is None:
                        still_image_cache[key] = False
                        return False
                    frame_count = M2TS(key).count_video_frames_up_to(
                        13,
                        video_pid=int(video_track['pid']),
                        codec_name=str(video_track.get('codec_name') or ''),
                    )
                    if frame_count < 1 or frame_count > 12:
                        still_image_cache[key] = False
                        return False

                    # Only a source with at most 12 compressed access units reaches
                    # the decoder. Zero-threshold mpdecimate emits a second checksum
                    # as soon as any decoded frame differs from the first one.
                    result = run_command([
                        FFMPEG_PATH or 'ffmpeg', '-v', 'error', '-nostdin', '-i', key,
                        '-map', '0:v:0', '-an', '-sn', '-dn',
                        '-vf', 'trim=end_frame=12,mpdecimate=hi=0:lo=0:frac=1',
                        '-frames:v', '2', '-f', 'framemd5', '-',
                    ], capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=15)
                    decoded_images = [
                        line
                        for line in str(result.stdout or '').splitlines()
                        if line and not line.startswith('#') and ',' in line
                    ]
                    is_still = bool(result.returncode == 0 and len(decoded_images) == 1)
                except Exception:
                    is_still = False
                still_image_cache[key] = is_still
                return is_still

            for r in self._rows:
                if self._cancel_event.is_set():
                    self.canceled.emit()
                    return
                row = int(r.get('row') or 0)
                m2ts_paths: list[str] = list(r.get('m2ts_paths') or [])
                mpls_path = str(r.get('mpls_path') or '').strip()
                sp_key = str(r.get('sp_key') or '').strip()
                force_disabled = bool(r.get('force_disabled') or False)
                disabled = False
                special = ''
                select_override = None
                tracks_payload: dict[str, list[str]] = {}
                available_tracks: dict[str, list[str]] = {}
                m2ts_type = ''
                video_only = False
                allow_tracks_when_disabled = False

                if force_disabled:
                    disabled = True
                elif not m2ts_paths:
                    disabled = True
                else:
                    first = m2ts_paths[0]
                    if (not first) or (not os.path.exists(first)):
                        disabled = True
                    else:
                        try:
                            if not _streams(first):
                                disabled = True
                        except Exception:
                            disabled = True

                if not disabled:
                    try:
                        streams_first = _streams(m2ts_paths[0]) if m2ts_paths else []
                        try:
                            classified_type = str(M2TS.classify_tracks_type(streams_first) or '').strip()
                            video_only = bool(
                                classified_type == 'video'
                                and not any(
                                    str(stream.get('codec_type') or '') in ('audio', 'subtitle', 'subtitles')
                                    for stream in streams_first
                                )
                            )
                        except Exception:
                            classified_type = ''
                            video_only = False
                        if not mpls_path:
                            m2ts_type = classified_type
                            if m2ts_type in ('private_or_other', 'mixed_non_video'):
                                disabled = True
                                allow_tracks_when_disabled = True
                        if mpls_path and os.path.exists(mpls_path) and m2ts_paths:
                            try:
                                ch = Chapter(mpls_path)
                                ch.get_pid_to_language()
                                pid_to_lang = ch.pid_to_lang
                            except Exception:
                                pid_to_lang = {}
                            try:
                                streams = _streams(m2ts_paths[0])
                            except Exception:
                                streams = []
                            if pid_to_lang:
                                streams = [
                                    stream
                                    for stream in streams
                                    if BluraySubtitle._stream_service_id(stream) in pid_to_lang
                                ]
                            try:
                                available_tracks = _available_tracks(streams)
                                a, s = BluraySubtitle._default_track_selection_from_streams(streams, pid_to_lang)
                                tracks_payload = {'audio': a, 'subtitle': s}
                            except Exception:
                                tracks_payload = {}
                        elif m2ts_paths:
                            try:
                                streams = _streams(m2ts_paths[0])
                            except Exception:
                                streams = []
                            try:
                                pid_to_lang = {}
                                try:
                                    pid_to_lang = pid_to_lang_from_m2ts_path(m2ts_paths[0])
                                except Exception:
                                    pid_to_lang = {}
                                available_tracks = _available_tracks(streams)
                                a, s = BluraySubtitle._default_track_selection_from_streams(streams, pid_to_lang)
                                tracks_payload = {'audio': a, 'subtitle': s}
                            except Exception:
                                tracks_payload = {}
                        uniq_m2ts_paths = list(dict.fromkeys([p for p in m2ts_paths if p]))
                        still_candidate = bool(uniq_m2ts_paths)
                        for p in uniq_m2ts_paths:
                            if not os.path.exists(p):
                                still_candidate = False
                                break
                            # A lone large clip is normal video in this workflow. Multi-clip
                            # playlists keep their historical exemption because menu stills
                            # may be stored in larger individual files.
                            if len(uniq_m2ts_paths) == 1 and os.path.getsize(p) > 10 * 1024 * 1024:
                                still_candidate = False
                                break
                        if still_candidate:
                            still_images: list[bool] = []
                            for p in uniq_m2ts_paths:
                                if _is_audio_only(p):
                                    still_images = []
                                    break
                                still_images.append(_is_still_image(p))
                                if not still_images[-1]:
                                    break
                            if not disabled:
                                if len(uniq_m2ts_paths) == 1 and still_images == [True]:
                                    special = 'single_frame'
                                    select_override = True
                                elif (
                                        len(uniq_m2ts_paths) > 1
                                        and len(still_images) == len(uniq_m2ts_paths)
                                        and all(still_images)
                                ):
                                    special = 'multi_frame'
                                    select_override = True
                    except Exception:
                        pass

                self.result.emit(row, bool(disabled), str(special or ''), {
                    'select_override': select_override,
                    'sp_key': sp_key,
                    'tracks': tracks_payload,
                    'available_tracks': available_tracks,
                    'mpls_path': mpls_path,
                    'm2ts_type': m2ts_type,
                    'video_only': bool(video_only),
                    'allow_tracks_when_disabled': bool(allow_tracks_when_disabled),
                })

            if self._cancel_event.is_set():
                self.canceled.emit()
            else:
                self.finished.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)
