import os
import threading
import traceback

from PyQt6.QtCore import QObject, pyqtSignal

from src.bdmv import M2TS, Chapter
from src.exports.utils import print_terminal_line, print_tb_string_terminal
from src.runtime.services import BluraySubtitle


class SpTableScanWorker(QObject):
    result = pyqtSignal(int, bool, str, object)
    finished = pyqtSignal()
    canceled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, rows: list[dict[str, object]], cancel_event: threading.Event):
        super().__init__()
        self._rows = rows
        self._cancel_event = cancel_event

    def run(self):
        try:
            streams_cache: dict[str, list[dict[str, object]]] = {}
            frame_count_cache: dict[str, int] = {}
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

            def _frame_count(path: str) -> int:
                key = os.path.normpath(path or '')
                if key in frame_count_cache:
                    return frame_count_cache[key]
                try:
                    c = BluraySubtitle._m2ts_frame_count(key)
                except Exception:
                    c = -1
                frame_count_cache[key] = int(c)
                return frame_count_cache[key]

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

            for r in self._rows:
                if self._cancel_event.is_set():
                    self.canceled.emit()
                    return
                row = int(r.get('row') or 0)
                m2ts_paths: list[str] = list(r.get('m2ts_paths') or [])
                mpls_path = str(r.get('mpls_path') or '').strip()
                sp_key = str(r.get('sp_key') or '').strip()
                force_disabled = bool(r.get('force_disabled') or False)
                select_all = bool(r.get('select_all') or False)
                disabled = False
                disabled_reason = ''
                special = ''
                select_override = None
                tracks_payload: dict[str, list[str]] = {}
                m2ts_type = ''
                allow_tracks_when_disabled = False

                if force_disabled:
                    disabled = True
                    disabled_reason = 'force_disabled'
                elif not m2ts_paths:
                    disabled = True
                    disabled_reason = 'empty_m2ts_paths'
                else:
                    first = m2ts_paths[0]
                    if (not first) or (not os.path.exists(first)):
                        disabled = True
                        disabled_reason = 'first_missing'
                    else:
                        try:
                            if not _streams(first):
                                disabled = True
                                disabled_reason = 'first_no_streams'
                        except Exception:
                            disabled = True
                            disabled_reason = 'first_streams_exception'

                if not disabled:
                    try:
                        if (not mpls_path) and m2ts_paths:
                            try:
                                streams_first = _streams(m2ts_paths[0])
                                m2ts_type = str(M2TS.classify_tracks_type(streams_first) or '').strip()
                            except Exception:
                                m2ts_type = ''
                            if m2ts_type in ('private_or_other', 'mixed_non_video'):
                                disabled = True
                                disabled_reason = f'm2ts_type={m2ts_type}'
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
                            try:
                                if select_all:
                                    a = [str(x.get('index', '')).strip() for x in streams if str(x.get('codec_type') or '') == 'audio' and str(x.get('index', '')).strip() != '']
                                    s = [str(x.get('index', '')).strip() for x in streams if str(x.get('codec_type') or '') == 'subtitle' and str(x.get('index', '')).strip() != '']
                                else:
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
                                if select_all:
                                    a = [str(x.get('index', '')).strip() for x in streams if str(x.get('codec_type') or '') == 'audio' and str(x.get('index', '')).strip() != '']
                                    s = [str(x.get('index', '')).strip() for x in streams if str(x.get('codec_type') or '') == 'subtitle' and str(x.get('index', '')).strip() != '']
                                else:
                                    a, s = BluraySubtitle._default_track_selection_from_streams(streams, {})
                                tracks_payload = {'audio': a, 'subtitle': s}
                            except Exception:
                                tracks_payload = {}
                        uniq_m2ts_paths = list(dict.fromkeys([p for p in m2ts_paths if p]))
                        sizes_ok = True
                        for p in uniq_m2ts_paths:
                            if (not p) or (not os.path.exists(p)):
                                sizes_ok = False
                                break
                            # >1MB means not a one-frame menu clip: stop menu-png classification immediately.
                            if os.path.getsize(p) > 1 * 1024 * 1024:
                                sizes_ok = False
                                break
                        if sizes_ok:
                            frame_counts: list[int] = []
                            any_video = False
                            for p in uniq_m2ts_paths:
                                if _is_audio_only(p):
                                    frame_counts = []
                                    any_video = False
                                    break
                                c = _frame_count(p)
                                if c == -2:
                                    frame_counts = []
                                    any_video = False
                                    break
                                if c < 0:
                                    # For multi-m2ts playlists, unknown frame count on a subset of clips
                                    # should not invalidate one-frame menu classification entirely.
                                    # Keep this clip as unknown and continue using known clips.
                                    continue
                                any_video = True
                                frame_counts.append(c)
                            if (not disabled) and any_video and frame_counts:
                                if len(uniq_m2ts_paths) == 1 and frame_counts[0] <= 1:
                                    special = 'single_frame'
                                    select_override = True
                                elif len(uniq_m2ts_paths) > 1 and all(x <= 1 for x in frame_counts):
                                    special = 'multi_frame'
                                    select_override = True
                    except Exception:
                        pass
                if disabled:
                    try:
                        if mpls_path:
                            print_terminal_line(
                                f'[SPDebug] row_disabled row={row} reason={str(locals().get("disabled_reason", "unknown"))} '
                                f'mpls={os.path.basename(mpls_path)} m2ts_count={len(m2ts_paths)} force={bool(force_disabled)}'
                            )
                    except Exception:
                        pass

                self.result.emit(row, bool(disabled), str(special or ''), {
                    'select_override': select_override,
                    'sp_key': sp_key,
                    'tracks': tracks_payload,
                    'mpls_path': mpls_path,
                    'm2ts_type': m2ts_type,
                    'allow_tracks_when_disabled': bool(allow_tracks_when_disabled),
                })

            self.finished.emit()
        except Exception:
            tb = traceback.format_exc()
            print_tb_string_terminal(tb)
            self.failed.emit(tb)
