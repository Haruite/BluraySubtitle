"""Auto-generated split target: media_info_and_track_mapping."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional

import numpy as np
import pycountry
import soundfile

from src.bdmv import M2TS, Chapter, pid_to_lang_from_m2ts_path
from src.core import FFPROBE_PATH, FFMPEG_PATH, FLAC_PATH, MKV_MERGE_PATH, \
    find_mkvtoolnix, get_mkvtoolnix_ui_language, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import get_effective_bit_depth, get_time_str, print_exc_terminal, get_index_to_m2ts_and_offset, run_command
from src.runtime.audio_conversion import AudioEncodingSettings
from .service_base import BluraySubtitleServiceBase
from src.runtime.dolby_vision import mux_dolby_vision_layers
from .. import TaskCancelled

# SP/detail views repeatedly query the same STREAM files and MPLS playlists. M2TS owns the parsed-value
# caches; this process cache only keeps one parser per unchanged file so all callers share those results.
_M2TS_PARSER_CACHE: dict[str, tuple[tuple[int, int], M2TS]] = {}
_M2TS_PARSER_CACHE_LOCK = threading.RLock()
_MPLS_PLAY_ROWS_CACHE: dict[str, list] = {}
_MPLS_TIMELINE_DETAIL_CACHE: dict[tuple[str, float, float], str] = {}


def mpls_playlist_caches_clear() -> None:
    """Clear MPLS-derived UI caches after playlist interpretation settings change."""
    _MPLS_PLAY_ROWS_CACHE.clear()
    _MPLS_TIMELINE_DETAIL_CACHE.clear()


def _normalized_media_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _cached_m2ts_parser(m2ts_path: str) -> Optional[M2TS]:
    path = _normalized_media_path(m2ts_path)
    try:
        stat = os.stat(path)
    except OSError:
        return None
    signature = (int(stat.st_size), int(stat.st_mtime_ns))
    with _M2TS_PARSER_CACHE_LOCK:
        cached = _M2TS_PARSER_CACHE.get(path)
        if cached and cached[0] == signature:
            return cached[1]
        parser = M2TS(path)
        _M2TS_PARSER_CACHE[path] = (signature, parser)
        return parser


def _m2ts_cached_pts_dur(m2ts_path: str) -> tuple[Optional[int], Optional[int]]:
    parser = _cached_m2ts_parser(m2ts_path)
    if parser is None:
        return None, None
    try:
        return parser.get_first_pts(m2ts=True), int(parser.get_duration())
    except (OSError, TypeError, ValueError):
        return None, None

def _mpls_play_rows_cached(mpls_path: str) -> list:
    key = _normalized_media_path(mpls_path)
    if key in _MPLS_PLAY_ROWS_CACHE:
        return _MPLS_PLAY_ROWS_CACHE[key]
    pr: list = []
    try:
        mp = str(mpls_path or '').strip()
        if not mp or not mp.lower().endswith('.mpls') or not os.path.isfile(mp):
            _MPLS_PLAY_ROWS_CACHE[key] = pr
            return pr
        ch = Chapter(mp)
        pr = list(ch.in_out_time or [])
    except Exception:
        pr = []
    _MPLS_PLAY_ROWS_CACHE[key] = pr
    return pr


def _svc_cls():
    from ..services.bluray_subtitle_entry import BluraySubtitle
    return BluraySubtitle


def _audio_file_channel_count(path: str) -> int:
    """Channel count of the first audio stream in a file; 0 if unknown."""
    if not path or not os.path.isfile(path):
        return 0
    try:
        info = soundfile.info(path)
        ch = int(info.channels)
        if ch > 0:
            return ch
    except Exception:
        pass
    try:
        proc = run_command(
            f'"{FFPROBE_PATH}" -v error -select_streams a:0 -show_entries stream=channels '
            f'-of default=noprint_wrappers=1:nokey=1 "{path}"',
            capture_output=True,
            text=True,
            timeout=60,
        )
        ch = int((proc.stdout or '').strip())
        return ch if ch > 0 else 0
    except Exception:
        return 0


class MediaInfoTrackMappingMixin(BluraySubtitleServiceBase):

    @staticmethod
    def _detect_sp_looping_mpls(mpls_path: str) -> Optional[dict[str, object]]:
        """
        Detect menu-like SP MPLS playlists that loop a short clip pattern.

        Returns dict with:
        - ``kind``: ``all_same`` | ``two_clip`` | ``tail_repeat``
        - ``max_clips``: 1 or 2 — how many ``in_out_time`` rows [remux-fallback] should mux
        - ``split_parts``: ``00:00:00.000-<t>`` for mkvmerge ``--split parts:`` (t = one or two items)
        """
        try:
            ios = list(Chapter(mpls_path).in_out_time or [])
        except Exception:
            return None
        if len(ios) < 2:
            return None
        keys = [(str(row[0] or '').strip(), int(row[1]), int(row[2])) for row in ios]
        durations = [max(0.0, (int(row[2]) - int(row[1])) / 45000.0) for row in ios]
        first_end = get_time_str(durations[0])
        first_split = f'00:00:00.000-{first_end if first_end != "0" else "00:00:00.000"}'
        if all(key == keys[0] for key in keys):
            return {'kind': 'all_same', 'max_clips': 1, 'split_parts': first_split}
        two_end = get_time_str(durations[0] + durations[1])
        split_two = f'00:00:00.000-{two_end if two_end != "0" else "00:00:00.000"}'
        k0, k1 = keys[0], keys[1]
        if all(k == keys[1] for k in keys[1:]):
            return {'kind': 'tail_repeat', 'max_clips': 2, 'split_parts': split_two}
        if all(k in (k0, k1) for k in keys):
            return {'kind': 'two_clip', 'max_clips': 2, 'split_parts': split_two}
        return None

    @staticmethod
    def _mpls_hevc_dv_video_pids(mpls_path: str) -> list[int]:
        """
        Dolby Vision BL+EL PIDs from play item 0 STN: HEVC (0x24) in video buckets plus every
        ``DVStreamEntries`` PID (EL is often listed there with a non-0x24 coding type).
        """
        try:
            from src.bdmv.mpls import MPLS
            mf = MPLS(os.path.normpath(mpls_path), strict=False)
            play_items = mf.data.get('PlayList', {}).get('PlayItems') or []
            if not play_items:
                return []
            stn = play_items[0].get('STNTable') or {}
        except Exception:
            return []
        pids: list[int] = []
        seen: set[int] = set()

        def _add_pid(entry: dict) -> None:
            se = entry.get('StreamEntry') or {}
            try:
                pid = int(se.get('RefToStreamPID'))
            except Exception:
                return
            if pid in seen:
                return
            seen.add(pid)
            pids.append(pid)

        for bucket in (
                'PrimaryVideoStreamEntries',
                'SecondaryVideoStreamEntries',
        ):
            for entry in stn.get(bucket) or []:
                if not isinstance(entry, dict):
                    continue
                attrs = entry.get('StreamAttributes') or {}
                try:
                    ct = int(attrs.get('StreamCodingType'))
                except Exception:
                    continue
                if ct != 0x24:
                    continue
                _add_pid(entry)
        for entry in stn.get('DVStreamEntries') or []:
            if isinstance(entry, dict):
                _add_pid(entry)
        return pids

    @staticmethod
    def detect_dovi_mux_pair(
            mpls_path: str,
            probe_m2ts: str,
            mux_dolby_vision: bool,
    ) -> Optional[dict[str, object]]:
        """
        Two HEVC-DV MPLS video PIDs where mkvmerge cannot map the second (EL) on ``probe_m2ts``.
        Falls back to two video PIDs on ``probe_m2ts`` when MPLS STN omits the EL layer entry.
        """
        mp = os.path.normpath(str(mpls_path or ''))
        probe = os.path.normpath(str(probe_m2ts or ''))
        if not mp.lower().endswith('.mpls') or not os.path.isfile(mp):
            return None
        if not probe or not os.path.isfile(probe):
            return None
        pids = _svc_cls()._mpls_hevc_dv_video_pids(mp)
        if len(pids) != 2:
            vpids = _svc_cls()._video_pids_on_m2ts(probe)
            if len(vpids) == 2:
                unmapped = [
                    p for p in vpids
                    if _svc_cls()._mkvmerge_tid_for_pid(probe, p, 'video') is None
                ]
                if len(unmapped) == 1:
                    el_pid = int(unmapped[0])
                    bl_pid = int(vpids[0]) if int(vpids[1]) == el_pid else int(vpids[1])
                    pids = [bl_pid, el_pid]
        if len(pids) != 2:
            return None
        bl_pid, el_pid = int(pids[0]), int(pids[1])
        if _svc_cls()._mkvmerge_tid_for_pid(probe, el_pid, 'video') is not None:
            return None
        return {
            'bl_pid': bl_pid,
            'el_pid': el_pid,
            'active': True,
            'mux_enabled': bool(mux_dolby_vision),
        }

    @staticmethod
    def _mkvmerge_dovi_primary_video_opts(
            mpls_path: str,
            dovi_plan: Optional[dict[str, object]],
    ) -> str:
        """``-d !id`` to drop EL on primary MPLS mux when DoVi pair is active but not dovi_tool-muxed."""
        if not dovi_plan or not dovi_plan.get('active') or dovi_plan.get('mux_enabled'):
            return ''
        try:
            el_pid = int(dovi_plan.get('el_pid'))
        except Exception:
            return ''
        tid = _svc_cls()._mkvmerge_tid_for_pid(mpls_path, el_pid, 'video')
        if tid is None:
            return ''
        return f'-d !{tid}'

    @staticmethod
    def _filter_video_pids_for_dovi_plan(
            video_pids: list[int],
            dovi_plan: Optional[dict[str, object]],
    ) -> list[int]:
        if not dovi_plan or not dovi_plan.get('active'):
            return list(video_pids)
        try:
            el_pid = int(dovi_plan.get('el_pid'))
        except Exception:
            return list(video_pids)
        if dovi_plan.get('mux_enabled'):
            return []
        return [p for p in video_pids if int(p) != el_pid]

    @staticmethod
    def mkvinfo_dolby_vision_track_id(mkv_path: str) -> Optional[int]:
        """
        Return mkvmerge/mkvextract video track id when *mkvinfo* reports Dolby Vision (dvvC block addition).

        Uses ``mkvinfo --ui-language en``; matches tracks whose block-addition mapping includes
        ``Dolby Vision configuration``.
        """
        mkv_path = os.path.normpath(str(mkv_path or ''))
        if not mkv_path or not os.path.isfile(mkv_path):
            return None
        try:
            find_mkvtoolnix()
        except Exception:
            pass
        info_exe = str(getattr(core_settings, 'MKV_INFO_PATH', '') or '').strip()
        if not info_exe or not os.path.isfile(info_exe):
            return None
        ui_lang = 'en' if sys.platform == 'win32' else 'en_US'
        try:
            proc = run_command(
                [info_exe, mkv_path, '--ui-language', ui_lang],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
            )
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        text = proc.stdout or ''
        in_track = False
        is_video = False
        has_dovi = False
        track_id: Optional[int] = None
        first_dovi_tid: Optional[int] = None

        def _flush_track() -> None:
            nonlocal in_track, is_video, has_dovi, track_id, first_dovi_tid
            if in_track and is_video and has_dovi and track_id is not None and first_dovi_tid is None:
                first_dovi_tid = int(track_id)
            in_track = False
            is_video = False
            has_dovi = False
            track_id = None

        for raw in text.splitlines():
            line = raw.strip()
            if line in ('|+ Track', '| + Track', '|  + Track'):
                _flush_track()
                in_track = True
                continue
            if not in_track:
                continue
            if (
                    line.startswith('|+ Track type: video')
                    or line.startswith('| + Track type: video')
                    or line.startswith('|  + Track type: video')
            ):
                is_video = True
                continue
            if 'track ID for mkvmerge & mkvextract:' in line:
                nums = re.findall(r'\d+', line.split(':', 1)[-1])
                if nums:
                    try:
                        track_id = int(nums[-1])
                    except Exception:
                        track_id = None
                continue
            low = line.lower()
            if 'dolby vision configuration' in low or 'dvvC'.lower() in low or '(dvvc)' in low:
                has_dovi = True
        _flush_track()
        return first_dovi_tid

    @staticmethod
    def _norm_lang_for_track_selection(raw: object) -> str:
        """Normalize ISO/BCP47/MKV language tags for default eng/zho track picking."""
        s = str(raw or '').strip().lower().replace('_', '-')
        if not s:
            return 'und'
        if s in ('eng', 'en') or s.startswith('en-'):
            return 'eng'
        if s in ('zho', 'chi', 'cmn', 'yue', 'nan', 'zh', 'chs', 'cht') or s.startswith('zh'):
            return 'zho'
        if s in ('jpn', 'ja') or s.startswith('ja-'):
            return 'jpn'
        if s in ('kor', 'ko') or s.startswith('ko-'):
            return 'kor'
        if len(s) >= 3 and re.match(r'^[a-z]{3}', s):
            return s[:3]
        return s if s else 'und'

    @staticmethod
    def _pid_lang_from_media_streams(streams: list[dict[str, object]]) -> dict[int, str]:
        """Build index/PID → language map from ffprobe/M2TS stream dicts (encode/remux defaults)."""
        out: dict[int, str] = {}
        for s in streams or []:
            if not isinstance(s, dict):
                continue
            lang = 'und'
            try:
                direct = s.get('lang') or s.get('language') or s.get('language_from_pmt_descriptor')
                if direct:
                    lang = str(direct)
                else:
                    tags = s.get('tags') or {}
                    if isinstance(tags, dict):
                        tag_lang = tags.get('lang') or tags.get('language')
                        if tag_lang:
                            lang = str(tag_lang)
            except Exception:
                lang = 'und'
            try:
                if len(lang) == 2:
                    language = pycountry.languages.get(alpha_2=lang.lower())
                    if language:
                        lang = getattr(language, 'bibliographic', getattr(language, 'alpha_3', None)) or lang
            except Exception:
                pass
            lang = _svc_cls()._norm_lang_for_track_selection(lang)
            try:
                idx = int(str(s.get('index') or '').strip())
                out[idx] = lang
            except Exception:
                pass
            try:
                sid = str(s.get('id') or '').strip()
                if sid:
                    if sid.lower().startswith('0x'):
                        out[int(sid, 16)] = lang
                    elif any(c in 'abcdefABCDEF' for c in sid):
                        out[int(sid, 16)] = lang
                    else:
                        out[int(sid, 10)] = lang
            except Exception:
                pass
            try:
                pid = int(str(s.get('pid') or '').strip())
                out[pid] = lang
            except Exception:
                pass
        return out

    @staticmethod
    def _default_track_selection_from_streams(
            streams: list[dict[str, object]],
            pid_to_lang: Optional[dict[int, str]] = None
    ) -> tuple[list[str], list[str]]:
        streams = streams or []
        pid_lang = pid_to_lang or {}

        def _parse_pid(raw_id: object) -> Optional[int]:
            s = str(raw_id or '').strip()
            if not s:
                return None
            try:
                if s.lower().startswith('0x'):
                    return int(s, 16)
                if any(c in 'abcdefABCDEF' for c in s):
                    return int(s, 16)
                return int(s, 10)
            except Exception:
                try:
                    return int(s, 16)
                except Exception:
                    return None

        def _get_lang(stream_info: dict[str, object]) -> str:
            pid = _parse_pid(stream_info.get('pid'))
            if pid is None:
                pid = _parse_pid(stream_info.get('id'))
            if pid is not None and pid in pid_lang:
                return _svc_cls()._norm_lang_for_track_selection(pid_lang.get(pid, 'und'))
            try:
                idx = int(str(stream_info.get('index') or '').strip())
                if idx in pid_lang:
                    return _svc_cls()._norm_lang_for_track_selection(pid_lang.get(idx, 'und'))
            except Exception:
                pass
            for key in ('language', 'lang'):
                if stream_info.get(key):
                    return _svc_cls()._norm_lang_for_track_selection(stream_info.get(key))
            tags = stream_info.get('tags')
            if isinstance(tags, dict):
                for key in ('language', 'lang'):
                    if tags.get(key):
                        return _svc_cls()._norm_lang_for_track_selection(tags.get(key))
            return 'und'

        audio_type_weight = {'': -1, 'aac': 1, 'ac3': 2, 'eac3': 3, 'lpcm': 4, 'dts': 5, 'dts_hd_ma': 6, 'truehd': 7}
        selected_eng_audio_track = ['', '']
        selected_zho_audio_track = ['', '']
        copy_sub_track: list[str] = []
        for stream_info in streams:
            codec_type = str(stream_info.get('codec_type') or '')
            if codec_type == 'audio':
                codec_name = str(stream_info.get('codec_name') or '')
                if codec_name == 'dts' and str(stream_info.get('profile') or '') == 'DTS-HD MA':
                    codec_name = 'dts_hd_ma'
                lang = _get_lang(stream_info)
                idx = str(stream_info.get('index') or '')
                if lang == 'eng':
                    if not selected_eng_audio_track[1] or audio_type_weight.get(codec_name, -1) > audio_type_weight.get(
                            selected_eng_audio_track[1], -1):
                        selected_eng_audio_track = [idx, codec_name]
                elif lang == 'zho':
                    if not selected_zho_audio_track[1] or audio_type_weight.get(codec_name, -1) > audio_type_weight.get(
                            selected_zho_audio_track[1], -1):
                        selected_zho_audio_track = [idx, codec_name]
            elif codec_type in ('subtitle', 'subtitles'):
                lang = _get_lang(stream_info)
                if lang in ['eng', 'zho']:
                    copy_sub_track.append(str(stream_info.get('index') or ''))
        if not copy_sub_track:
            for stream_info in streams:
                if str(stream_info.get('codec_type') or '') in ('subtitle', 'subtitles'):
                    copy_sub_track.append(str(stream_info.get('index') or ''))
                    break
        if not selected_zho_audio_track[0] and not selected_eng_audio_track[0]:
            copy_audio_track: list[str] = []
            for stream_info in streams:
                if str(stream_info.get('codec_type') or '') == 'audio':
                    copy_audio_track.append(str(stream_info.get('index') or ''))
                    break
            for stream_info in streams:
                if str(stream_info.get('codec_type') or '') == 'audio':
                    lang = _get_lang(stream_info)
                    idx = str(stream_info.get('index') or '')
                    if lang == 'jpn' and idx not in copy_audio_track:
                        copy_audio_track.append(idx)
        else:
            if selected_eng_audio_track[0] and selected_zho_audio_track[0]:
                copy_audio_track = [selected_eng_audio_track[0], selected_zho_audio_track[0]]
            elif not selected_eng_audio_track[0]:
                copy_audio_track = [selected_zho_audio_track[0]]
            else:
                copy_audio_track = [selected_eng_audio_track[0]]
            first_audio_index = 1
            for stream_info in streams:
                if str(stream_info.get('codec_type') or '') == 'audio':
                    first_audio_index = stream_info.get('index') or 1
                    break
            if str(first_audio_index) not in (selected_zho_audio_track[0], selected_eng_audio_track[0]):
                copy_audio_track.append(str(first_audio_index))
        return [x for x in copy_audio_track if x != ''], [x for x in copy_sub_track if x != '']

    @staticmethod
    def _read_media_streams(media_path: str) -> list[dict[str, object]]:
        if not media_path or not os.path.exists(media_path):
            return []
        exe = FFPROBE_PATH if FFPROBE_PATH else 'ffprobe'
        try:
            p = run_command(
                [exe, "-v", "error", "-show_streams", "-of", "json", media_path],
                capture_output=True,
                text=True,
            )
        except Exception:
            return []
        if p.returncode != 0:
            return []
        try:
            data = json.loads(p.stdout or "{}")
            streams = data.get('streams') or []
            return streams if isinstance(streams, list) else []
        except Exception:
            return []

    @staticmethod
    def _stream_service_id(stream: dict) -> Optional[int]:
        """MPEG-TS elementary stream id from stream metadata field ``id`` (e.g. ``0x1011``)."""
        if not isinstance(stream, dict):
            return None
        raw = stream.get('id')
        if raw is None:
            return None
        try:
            if isinstance(raw, int):
                return int(raw) & 0xFFFF
            s = str(raw).strip()
            if s.lower().startswith('0x'):
                return int(s, 16)
            return int(s, 0)
        except Exception:
            return None

    @staticmethod
    def _stream_index_to_service_pid(m2ts_path: str) -> dict[int, int]:
        """Map stream index (0,1,…) → TS PID from ``streams[].id``. m2ts has no reliable language tags."""
        out: dict[int, int] = {}
        for s in _svc_cls()._m2ts_track_streams(m2ts_path):
            if not isinstance(s, dict):
                continue
            if str(s.get('codec_type') or '') not in ('video', 'audio', 'subtitle', 'subtitles'):
                continue
            try:
                idx = int(s.get('index'))
            except Exception:
                continue
            pid = _svc_cls()._stream_service_id(s)
            if pid is not None:
                out[idx] = pid
        return out

    @staticmethod
    def _m2ts_track_streams(m2ts_path: str) -> list[dict[str, object]]:
        parser = _cached_m2ts_parser(m2ts_path)
        if parser is None:
            return []
        try:
            tracks = parser.get_tracks_info()
        except (OSError, TypeError, ValueError):
            return []
        streams: list[dict[str, object]] = []
        for index, track in enumerate(tracks):
            row = dict(track)
            try:
                pid = int(row['pid'])
            except (KeyError, TypeError, ValueError):
                pid = None
            row['codec_type'] = str(row.get('codec_type') or '')
            row['index'] = index
            row['id'] = f'0x{pid:04x}' if pid is not None else ''
            streams.append(row)
        return streams

    @staticmethod
    def _m2ts_duration_90k(m2ts_path: str) -> int:
        parser = _cached_m2ts_parser(m2ts_path)
        if parser is None:
            return 0
        try:
            return int(parser.get_duration())
        except (OSError, TypeError, ValueError):
            return 0

    @staticmethod
    def _m2ts_frame_count(m2ts_path: str) -> int:
        parser = _cached_m2ts_parser(m2ts_path)
        if parser is None:
            return -1
        try:
            return int(parser.get_total_frames())
        except (OSError, TypeError, ValueError):
            return -1
    @staticmethod
    def _video_frame_count_static(media_path: str) -> int:
        if not media_path or not os.path.exists(media_path):
            return -1
        exe = FFPROBE_PATH if FFPROBE_PATH else 'ffprobe'
        cmd = [exe, "-v", "error", "-count_frames", "-select_streams", "v:0",
               "-show_entries", "stream=nb_read_frames,nb_frames", "-of", "json", media_path]
        try:
            p = run_command(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        except Exception:
            return -1
        if p.returncode != 0:
            return -1
        try:
            data = json.loads(p.stdout or "{}")
        except Exception:
            return -1
        streams = data.get('streams') or []
        if not streams:
            return -2
        s0 = streams[0] if isinstance(streams[0], dict) else {}
        for k in ('nb_read_frames', 'nb_frames'):
            try:
                v = int(str(s0.get(k) or '').strip())
                if v >= 0:
                    return v
            except Exception:
                pass
        return -1

    @staticmethod
    def _is_audio_only_media(media_path: str) -> bool:
        if str(media_path or '').lower().endswith('.m2ts'):
            streams = _svc_cls()._m2ts_track_streams(media_path)
        else:
            streams = _svc_cls()._read_media_streams(media_path)
        if not streams:
            return False
        has_audio = False
        has_video = False
        for s in streams:
            c = str(s.get('codec_type') or '')
            if c == 'audio':
                has_audio = True
            elif c == 'video':
                has_video = True
        return has_audio and (not has_video)

    @staticmethod
    def _extract_single_audio_from_mka(output_file: str):
        if not output_file or not os.path.exists(output_file):
            return
        if not str(output_file).lower().endswith('.mka'):
            return
        streams = _svc_cls()._read_media_streams(output_file)
        audio_streams = [s for s in streams if str(s.get('codec_type') or '') == 'audio']
        if len(audio_streams) != 1:
            return
        codec = str(audio_streams[0].get('codec_name') or '').lower()
        ext_map = {
            'flac': 'flac',
            'wav': 'wav',
            'pcm_s16le': 'wav',
            'pcm_s24le': 'wav',
            'pcm_s32le': 'wav',
            'pcm_bluray': 'wav',
            'dts': 'dts',
            'truehd': 'thd',
            'mlp': 'thd',
            'ac3': 'ac3',
            'eac3': 'eac3',
            'aac': 'm4a',
            'opus': 'opus',
        }
        ext = ext_map.get(codec, codec or 'audio')
        if ext == 'mka':
            return
        dst = os.path.splitext(output_file)[0] + f'.{ext}'
        cmd = f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{output_file}" -map 0:a:0 -c copy "{dst}"'
        try:
            p = run_command(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if p.returncode == 0 and os.path.exists(dst):
                os.remove(output_file)
        except Exception:
            pass

    @staticmethod
    def _is_silent_audio_file(path: str, threshold_db: float = -60.0) -> tuple[bool, float]:
        y = None
        try:
            info = soundfile.info(path)
            frames = min(int(info.frames), int(info.samplerate) * 30)
            start = int(info.frames) // 2 if int(info.frames) > (frames * 2) else 0
            data, _sample_rate = soundfile.read(
                path,
                start=start,
                frames=frames,
                dtype='float32',
                always_2d=True,
            )
            y = data.mean(axis=1)
        except Exception:
            y = None
        if y is None:
            fd, tmp = tempfile.mkstemp(prefix=f"temp_sil_{os.getpid()}_", suffix=".wav")
            os.close(fd)
            try:
                run_command(
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{path}" -ac 1 -ar 22050 -c:a pcm_s16le "{tmp}"',
                    check=True
                )
                data, _sample_rate = soundfile.read(tmp, dtype='float32', always_2d=True)
                y = data.mean(axis=1)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
        frame_length = 2048
        hop_length = 512
        padded = np.pad(np.asarray(y, dtype=np.float32), frame_length // 2)
        squared = np.square(padded, dtype=np.float64)
        cumulative = np.concatenate(([0.0], np.cumsum(squared)))
        frame_starts = np.arange(0, padded.size - frame_length + 1, hop_length)
        frame_power = (
            cumulative[frame_starts + frame_length] - cumulative[frame_starts]
        ) / frame_length
        rms = np.sqrt(frame_power)
        minimum_amplitude = 1e-5
        reference_amplitude = max(minimum_amplitude, float(np.max(rms)))
        db = 20.0 * np.log10(np.maximum(minimum_amplitude, rms))
        db -= 20.0 * np.log10(reference_amplitude)
        db = np.maximum(db, float(np.max(db)) - 80.0)
        avg_db = float(np.mean(db))
        return avg_db < threshold_db, avg_db

    @staticmethod
    def _compress_audio_stream_to_flac(
            input_media: str,
            map_idx: str,
            out_flac: str,
            audio_encoding: AudioEncodingSettings = AudioEncodingSettings(),
    ) -> bool:
        if not input_media or not os.path.exists(input_media):
            return False
        if not out_flac:
            return False
        os.makedirs(os.path.dirname(out_flac) or '.', exist_ok=True)
        owns_tmp = True
        lower = str(input_media).lower()
        if lower.endswith(('.wav', '.w64')):
            tmp_wav = input_media
            owns_tmp = False
        else:
            fd, tmp_wav = tempfile.mkstemp(prefix=f"sp_audio_{os.getpid()}_", suffix=".wav")
            os.close(fd)
        tmp_wav2 = ''
        try:
            if owns_tmp:
                decode_result = run_command([
                    FFMPEG_PATH or 'ffmpeg', '-y', '-i', input_media,
                    '-map', f'0:{map_idx}', '-c:a', 'pcm_s24le', '-f', 'w64', tmp_wav,
                ])
                if decode_result.returncode != 0 or not os.path.isfile(tmp_wav) or os.path.getsize(tmp_wav) <= 0:
                    return False
            try:
                silent, _ = _svc_cls()._is_silent_audio_file(tmp_wav, -60.0)
            except Exception:
                silent = False
            if silent:
                if owns_tmp:
                    try:
                        os.remove(tmp_wav)
                    except Exception:
                        pass
                return False
            try:
                effective_bits = get_effective_bit_depth(tmp_wav)
            except Exception:
                effective_bits = 24
            if effective_bits <= 16:
                fd2, tmp_wav2 = tempfile.mkstemp(prefix=f"sp_audio16_{os.getpid()}_", suffix=".wav")
                os.close(fd2)
                conversion_result = run_command([
                    FFMPEG_PATH or 'ffmpeg', '-y', '-i', tmp_wav, '-c:a', 'pcm_s16le', tmp_wav2,
                ])
                if conversion_result.returncode == 0 and os.path.isfile(tmp_wav2) and os.path.getsize(tmp_wav2) > 0:
                    if owns_tmp:
                        try:
                            os.remove(tmp_wav)
                        except Exception:
                            pass
                    tmp_wav = tmp_wav2
                    owns_tmp = True
                    tmp_wav2 = ''
            ok = False
            if FLAC_PATH:
                try:
                    result = run_command([
                        FLAC_PATH,
                        f'-{audio_encoding.flac_compression_level}',
                        '-j',
                        str(os.cpu_count() or 1),
                        tmp_wav,
                        '-o',
                        out_flac,
                    ])
                    ok = result.returncode == 0 and os.path.isfile(out_flac) and os.path.getsize(out_flac) > 0
                except Exception:
                    ok = False
            if not ok:
                if os.path.isfile(out_flac):
                    os.remove(out_flac)
                try:
                    result = run_command([
                        FFMPEG_PATH or 'ffmpeg', '-y', '-i', tmp_wav,
                        '-c:a',
                        'flac',
                        '-compression_level',
                        str(audio_encoding.ffmpeg_flac_compression_level),
                        out_flac,
                    ])
                    ok = result.returncode == 0 and os.path.isfile(out_flac) and os.path.getsize(out_flac) > 0
                except Exception:
                    ok = False
            if not ok and os.path.isfile(out_flac):
                os.remove(out_flac)
            return ok
        finally:
            if tmp_wav2 and os.path.exists(tmp_wav2):
                try:
                    os.remove(tmp_wav2)
                except Exception:
                    pass
            if owns_tmp and tmp_wav and os.path.exists(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass

    @staticmethod
    def _pid_lang_from_mkvmerge_json(media_path: str) -> dict[int, str]:
        if not media_path or not os.path.exists(media_path):
            return {}
        try:
            find_mkvtoolnix()
        except Exception:
            pass
        exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
        try:
            p = run_command(
                [exe, "--identify", "--identification-format", "json", media_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
            )
        except Exception:
            return {}
        if p.returncode != 0:
            return {}
        try:
            data = json.loads(p.stdout or "{}")
        except Exception:
            return {}
        out: dict[int, str] = {}
        tracks = data.get('tracks') or []
        if not isinstance(tracks, list):
            return {}
        for t in tracks:
            if not isinstance(t, dict):
                continue
            props = t.get('properties') or {}
            if not isinstance(props, dict):
                props = {}
            lang = str(props.get('language') or 'und')
            if not lang:
                lang = 'und'
            for key in ('id',):
                try:
                    out[int(t.get(key))] = lang
                except Exception:
                    pass
            for key in ('stream_id', 'number'):
                try:
                    out[int(props.get(key))] = lang
                except Exception:
                    pass
        return out

    @staticmethod
    def _mkvmerge_identify_json(media_path: str) -> dict[str, object]:
        if not media_path or not os.path.exists(media_path):
            return {}
        try:
            find_mkvtoolnix()
        except Exception:
            pass
        exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
        try:
            p = run_command(
                [exe, "--identify", "--identification-format", "json", media_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
            )
        except Exception:
            return {}
        if p.returncode != 0:
            return {}
        try:
            data = json.loads(p.stdout or "{}")
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _mkvmerge_track_ids_by_type(media_path: str, track_type: str) -> list[int]:
        """mkvmerge JSON ``tracks[].id`` for *track_type* (``video`` / ``audio`` / ``subtitles``)."""
        want = str(track_type or '').strip().lower()
        if want == 'subtitle':
            want = 'subtitles'
        out: list[int] = []
        ident = _svc_cls()._mkvmerge_identify_json(media_path)
        for t in ident.get('tracks') or []:
            if not isinstance(t, dict):
                continue
            if str(t.get('type') or '').strip().lower() != want:
                continue
            try:
                out.append(int(t['id']))
            except Exception:
                continue
        return out

    @staticmethod
    def _int_from_mkvmerge_prop(raw: object) -> Optional[int]:
        s = str(raw or '').strip()
        if not s:
            return None
        try:
            if s.lower().startswith('0x'):
                return int(s, 16)
            return int(s, 10)
        except Exception:
            try:
                return int(s, 16)
            except Exception:
                return None

    @staticmethod
    def _map_selected_tracks_to_mpls_track_ids(
            mpls_path: str,
            selected_audio_track_indexes: list[str],
            selected_sub_track_indexes: list[str],
    ) -> tuple[list[str], list[str]]:
        """
        Convert selected first-m2ts stream indexes to mkvmerge MPLS track ids.

        ``selected_*_track_indexes`` are GUI selections based on first m2ts ``index``.
        For MPLS muxing, mkvmerge expects ``tracks[].id`` from
        ``mkvmerge --identify --identification-format json <mpls>``.
        """
        if not mpls_path or (not str(mpls_path).lower().endswith('.mpls')) or (not os.path.isfile(mpls_path)):
            return list(selected_audio_track_indexes or []), list(selected_sub_track_indexes or [])
        first_m2ts, _ = _svc_cls()._probe_m2ts_for_remux_source(mpls_path)
        if not first_m2ts or not os.path.isfile(first_m2ts):
            return list(selected_audio_track_indexes or []), list(selected_sub_track_indexes or [])

        streams = [s for s in _svc_cls()._m2ts_track_streams(first_m2ts) if isinstance(s, dict)]
        idx_to_pid_audio: dict[int, int] = {}
        idx_to_pid_sub: dict[int, int] = {}
        for s in streams:
            ctype = str(s.get('codec_type') or '').strip().lower()
            try:
                sidx = int(str(s.get('index') or '').strip())
            except Exception:
                continue
            pid = _svc_cls()._stream_service_id(s)
            if pid is None:
                continue
            if ctype == 'audio':
                idx_to_pid_audio[sidx] = pid
            elif ctype in ('subtitle', 'subtitles'):
                idx_to_pid_sub[sidx] = pid

        ident = _svc_cls()._mkvmerge_identify_json(mpls_path)
        tracks = ident.get('tracks') or []
        if not isinstance(tracks, list) or not tracks:
            return list(selected_audio_track_indexes or []), list(selected_sub_track_indexes or [])
        pid_to_ids_audio: dict[int, list[int]] = {}
        pid_to_ids_sub: dict[int, list[int]] = {}
        for t in tracks:
            if not isinstance(t, dict):
                continue
            t_type = str(t.get('type') or '').strip().lower()
            if t_type not in ('audio', 'subtitles'):
                continue
            try:
                tid = int(t.get('id'))
            except Exception:
                continue
            props = t.get('properties') or {}
            if not isinstance(props, dict):
                props = {}
            pid = _svc_cls()._int_from_mkvmerge_prop(props.get('stream_id'))
            if pid is None:
                pid = _svc_cls()._int_from_mkvmerge_prop(props.get('number'))
            if pid is None:
                continue
            if t_type == 'audio':
                pid_to_ids_audio.setdefault(pid, []).append(tid)
            else:
                pid_to_ids_sub.setdefault(pid, []).append(tid)

        def _map_selected(selected_indexes: list[str], idx_to_pid: dict[int, int], pid_to_ids: dict[int, list[int]]) -> list[str]:
            out: list[str] = []
            used: dict[int, int] = {}
            for raw_idx in selected_indexes or []:
                try:
                    idx = int(str(raw_idx).strip())
                except Exception:
                    continue
                pid = idx_to_pid.get(idx)
                if pid is None:
                    continue
                tids = pid_to_ids.get(pid) or []
                if not tids:
                    continue
                pos = used.get(pid, 0)
                if pos >= len(tids):
                    pos = len(tids) - 1
                used[pid] = pos + 1
                out.append(str(tids[pos]))
            return out

        mapped_audio = _map_selected(selected_audio_track_indexes, idx_to_pid_audio, pid_to_ids_audio)
        mapped_sub = _map_selected(selected_sub_track_indexes, idx_to_pid_sub, pid_to_ids_sub)
        # If mapping failed completely, keep previous behavior as fallback.
        if selected_audio_track_indexes and (not mapped_audio):
            mapped_audio = list(selected_audio_track_indexes)
        if selected_sub_track_indexes and (not mapped_sub):
            mapped_sub = list(selected_sub_track_indexes)
        return mapped_audio, mapped_sub

    @staticmethod
    def _fix_output_track_languages_with_mkvpropedit(
            output_mkv_path: str,
            input_m2ts_path: str,
            selected_audio_ids: list[str],
            selected_sub_ids: list[str],
            override_lang_by_source_index: Optional[dict[str, str]] = None,
            dovi_plan: Optional[dict[str, object]] = None,
    ) -> None:
        """Apply only the languages captured by Edit Tracks to one completed Remux output."""
        language_overrides = {
            str(source_index): str(language).strip()
            for source_index, language in (override_lang_by_source_index or {}).items()
            if str(language).strip()
        }
        if not language_overrides:
            return
        if not output_mkv_path or not os.path.isfile(output_mkv_path):
            raise FileNotFoundError(
                translate_text('Main remux output is missing: {path}').format(path=output_mkv_path)
            )
        if not input_m2ts_path or not os.path.isfile(input_m2ts_path):
            raise RuntimeError(
                translate_text('Configured track languages could not be mapped to: {path}').format(
                    path=output_mkv_path
                )
            )

        source_slots: dict[str, list[tuple[int, int, str]]] = {
            'video': [],
            'audio': [],
            'subtitles': [],
        }
        source_streams = [
            stream for stream in _svc_cls()._m2ts_track_streams(input_m2ts_path)
            if isinstance(stream, dict)
        ]
        streams_by_index = {
            str(stream.get('index', '')).strip(): stream
            for stream in source_streams
        }
        for source_order, stream in enumerate(source_streams):
            source_index = str(stream.get('index', '')).strip()
            track_type = str(stream.get('codec_type') or '').strip().lower()
            if track_type != 'video':
                continue
            pid = _svc_cls()._stream_service_id(stream)
            source_slots['video'].append((
                int(pid) if pid is not None else 0x7FFFFFFF,
                source_order,
                source_index,
            ))
        for track_type, selected_ids in (
                ('audio', selected_audio_ids),
                ('subtitles', selected_sub_ids),
        ):
            for selected_order, selected_id in enumerate(selected_ids):
                source_index = str(selected_id)
                stream = streams_by_index.get(source_index)
                if not stream:
                    continue
                source_type = str(stream.get('codec_type') or '').strip().lower()
                if source_type in ('subtitle', 'subtitles'):
                    source_type = 'subtitles'
                if source_type != track_type:
                    continue
                pid = _svc_cls()._stream_service_id(stream)
                source_slots[track_type].append((
                    int(pid) if pid is not None else 0x7FFFFFFF,
                    selected_order,
                    source_index,
                ))

        if isinstance(dovi_plan, dict) and dovi_plan.get('active'):
            try:
                enhancement_pid = int(dovi_plan.get('el_pid'))
            except (TypeError, ValueError):
                enhancement_pid = -1
            if dovi_plan.get('mux_enabled'):
                try:
                    base_pid = int(dovi_plan.get('bl_pid'))
                except (TypeError, ValueError):
                    base_pid = -1
                base_slots = [
                    slot for slot in source_slots['video']
                    if slot[0] == base_pid
                ]
                source_slots['video'] = base_slots or source_slots['video'][:1]
            elif enhancement_pid >= 0:
                source_slots['video'] = [
                    slot for slot in source_slots['video']
                    if slot[0] != enhancement_pid
                ]

        output_info = _svc_cls()._mkvmerge_identify_json(output_mkv_path)
        output_tracks = output_info.get('tracks') or []
        if not isinstance(output_tracks, list) or not output_tracks:
            raise RuntimeError(
                translate_text('Configured track languages could not be mapped to: {path}').format(
                    path=output_mkv_path
                )
            )
        output_by_type: dict[str, list[tuple[int, dict[str, object]]]] = {
            'video': [],
            'audio': [],
            'subtitles': [],
        }
        for output_index, track in enumerate(output_tracks):
            if not isinstance(track, dict):
                continue
            track_type = str(track.get('type') or '').strip().lower()
            if track_type in ('subtitle', 'subtitles'):
                track_type = 'subtitles'
            if track_type in output_by_type:
                output_by_type[track_type].append((output_index, track))

        edits: list[tuple[int, int, str]] = []
        for track_type, slots in source_slots.items():
            configured_slots = [
                slot for slot in slots if slot[2] in language_overrides
            ]
            if not configured_slots:
                continue
            typed_output_tracks = output_by_type[track_type]
            if len(typed_output_tracks) != len(slots):
                raise RuntimeError(
                    translate_text('Configured track languages could not be mapped to: {path}').format(
                        path=output_mkv_path
                    )
                )
            for source_position, source_slot in enumerate(slots):
                source_index = source_slot[2]
                desired_language = language_overrides.get(source_index)
                if not desired_language:
                    continue
                output_index, output_track = typed_output_tracks[source_position]
                properties = output_track.get('properties') or {}
                if not isinstance(properties, dict):
                    properties = {}
                actual_languages = {
                    str(properties.get(property_name) or '').strip().lower()
                    for property_name in ('language', 'language_ietf')
                    if str(properties.get(property_name) or '').strip()
                }
                if desired_language.lower() in actual_languages:
                    continue
                # `track:n` uses the one-based order returned by `mkvmerge --identify`.
                track_number = output_index + 1
                edits.append((output_index, track_number, desired_language))

        if not edits:
            return
        find_mkvtoolnix()
        executable = core_settings.MKV_PROP_EDIT_PATH or shutil.which('mkvpropedit')
        if not executable or not os.path.isfile(executable):
            raise FileNotFoundError(translate_text('mkvpropedit not found'))
        command = [executable]
        ui_language = get_mkvtoolnix_ui_language()
        if ui_language:
            command.extend(['--ui-language', ui_language])
        command.append(output_mkv_path)
        for _output_index, track_number, desired_language in edits:
            command.extend([
                '--edit',
                f'track:{track_number}',
                '--set',
                f'language={desired_language}',
            ])
        result = run_command(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace')
        if result.returncode not in (0, 1):
            raise RuntimeError(
                translate_text('mkvpropedit failed for: {path}').format(path=output_mkv_path)
            )

        verified_info = _svc_cls()._mkvmerge_identify_json(output_mkv_path)
        verified_tracks = verified_info.get('tracks') or []
        for output_index, _track_number, desired_language in edits:
            try:
                properties = verified_tracks[output_index].get('properties') or {}
                actual_languages = {
                    str(properties.get(property_name) or '').strip().lower()
                    for property_name in ('language', 'language_ietf')
                    if str(properties.get(property_name) or '').strip()
                }
            except (AttributeError, IndexError, TypeError):
                actual_languages = set()
            if desired_language.lower() not in actual_languages:
                raise RuntimeError(
                    translate_text('Track language correction did not apply to: {path}').format(
                        path=output_mkv_path
                    )
                )

    @staticmethod
    def _ordered_track_slots_for_remux(
            m2ts_path: str,
            copy_audio_track: list[str],
            copy_sub_track: list[str],
            dovi_plan: Optional[dict[str, object]] = None,
            mpls_path: str = '',
    ) -> list[dict[str, object]]:
        """Build ordered track slots from the tracks visible and selected in Edit Tracks.

        The GUI hides first-M2TS streams whose PID is absent from the MPLS stream table. Apply the same
        filter here so fallback never restores a hidden stream. Video is always selected in the GUI;
        audio and subtitle order comes from the captured selection lists. The source stream index is kept
        so a selected video slot can be mapped to the corresponding stream on later playlist clips.
        """
        streams = [stream for stream in _svc_cls()._m2ts_track_streams(m2ts_path) if isinstance(stream, dict)]
        visible_pids: Optional[set[int]] = None
        if mpls_path:
            chapter = Chapter(mpls_path)
            chapter.get_pid_to_language()
            visible_pids = {int(pid) for pid in chapter.pid_to_lang} or None
        visible_video_pids = [
            int(pid)
            for stream in streams
            if str(stream.get('codec_type') or '') == 'video'
            and (pid := _svc_cls()._stream_service_id(stream)) is not None
            and (visible_pids is None or int(pid) in visible_pids)
        ]
        selected_video_pids = (
            {int(dovi_plan['bl_pid'])} & set(visible_video_pids)
            if dovi_plan and dovi_plan.get('active') and dovi_plan.get('mux_enabled')
            else set(_svc_cls()._filter_video_pids_for_dovi_plan(visible_video_pids, dovi_plan))
        )
        selected_slots: list[dict[str, object]] = []
        for stream in streams:
            pid = _svc_cls()._stream_service_id(stream)
            if pid in selected_video_pids:
                selected_slots.append({
                    'type': 'video',
                    'pid': int(pid),
                    'index': str(stream.get('index', '')),
                })
        for audio_index in copy_audio_track or []:
            try:
                selected_index = int(str(audio_index).strip())
            except Exception:
                continue
            for stream in streams:
                if str(stream.get('codec_type') or '') != 'audio':
                    continue
                try:
                    if int(stream.get('index')) != selected_index:
                        continue
                except Exception:
                    continue
                pid = _svc_cls()._stream_service_id(stream)
                if pid is not None and (visible_pids is None or int(pid) in visible_pids):
                    selected_slots.append({'type': 'audio', 'pid': int(pid), 'index': str(selected_index)})
                break
        for subtitle_index in copy_sub_track or []:
            try:
                selected_index = int(str(subtitle_index).strip())
            except Exception:
                continue
            for stream in streams:
                if str(stream.get('codec_type') or '') not in ('subtitle', 'subtitles'):
                    continue
                try:
                    if int(stream.get('index')) != selected_index:
                        continue
                except Exception:
                    continue
                pid = _svc_cls()._stream_service_id(stream)
                if pid is not None and (visible_pids is None or int(pid) in visible_pids):
                    selected_slots.append({'type': 'subtitles', 'pid': int(pid), 'index': str(selected_index)})
                break
        return selected_slots

    @staticmethod
    def _video_pids_on_m2ts(m2ts_path: str) -> list[int]:
        """MPEG PIDs for video elementary streams on this ``m2ts`` (playlist order)."""
        pids: list[int] = []
        seen: set[int] = set()
        for s in _svc_cls()._m2ts_track_streams(m2ts_path):
            if not isinstance(s, dict):
                continue
            if str(s.get('codec_type') or '') != 'video':
                continue
            pid = _svc_cls()._stream_service_id(s)
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            pids.append(pid)
        return pids

    @staticmethod
    def _clip_ref_slots_for_m2ts(
            ref_slots: list[dict[str, object]],
            m2ts_path: str,
            dovi_plan: Optional[dict[str, object]] = None,
    ) -> Optional[list[dict[str, object]]]:
        """Map GUI-selected video indexes to this clip and retain selected audio/subtitle PID slots."""
        streams = [stream for stream in _svc_cls()._m2ts_track_streams(m2ts_path) if isinstance(stream, dict)]
        clip_video_pids = _svc_cls()._video_pids_on_m2ts(m2ts_path)
        allowed_video_pids = (
            {int(dovi_plan['bl_pid'])} & set(clip_video_pids)
            if dovi_plan and dovi_plan.get('active') and dovi_plan.get('mux_enabled')
            else set(_svc_cls()._filter_video_pids_for_dovi_plan(clip_video_pids, dovi_plan))
        )
        clip_slots: list[dict[str, object]] = []
        for reference_slot in ref_slots or []:
            if str(reference_slot.get('type') or '') != 'video':
                clip_slots.append(dict(reference_slot))
                continue
            selected_index = str(reference_slot.get('index') or '')
            current_stream = next(
                (
                    stream for stream in streams
                    if str(stream.get('codec_type') or '') == 'video'
                    and str(stream.get('index', '')) == selected_index
                    and _svc_cls()._stream_service_id(stream) in allowed_video_pids
                ),
                None,
            )
            if current_stream is None:
                return None
            clip_slots.append({
                'type': 'video',
                'pid': int(_svc_cls()._stream_service_id(current_stream)),
                'index': selected_index,
            })
        return clip_slots

    @staticmethod
    def _mkvmerge_tid_for_pid(m2ts_path: str, pid: int, slot_type: str) -> Optional[int]:
        """Resolve one MPEG transport PID to the input-local mkvmerge track ID.

        ``properties.stream_id`` is the authoritative direct match; ``properties.number`` is never treated as a
        PID. When mkvmerge omits stream IDs for audio/subtitle tracks, ffprobe streams and mkvmerge tracks of the
        same type are aligned by their relative order. ffprobe's global stream index is not a mkvmerge track ID.
        Video has no positional fallback because an unexposed HEVC/Dolby Vision stream must enter the tsMuxer
        recovery path instead of being guessed.
        """
        identify_track_type = {
            'video': 'video',
            'audio': 'audio',
            'subtitles': 'subtitles',
        }.get(slot_type)
        if not identify_track_type:
            return None
        identification = _svc_cls()._mkvmerge_identify_json(m2ts_path)
        for track in identification.get('tracks') or []:
            if not isinstance(track, dict) or str(track.get('type') or '').strip().lower() != identify_track_type:
                continue
            properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
            stream_pid = _svc_cls()._int_from_mkvmerge_prop(properties.get('stream_id'))
            if stream_pid != pid:
                continue
            try:
                return int(track.get('id'))
            except Exception:
                return None
        if slot_type == 'video':
            return None

        source_track_types = ('audio',) if slot_type == 'audio' else ('subtitle', 'subtitles')
        source_streams = [
            stream
            for stream in _svc_cls()._m2ts_track_streams(m2ts_path)
            if isinstance(stream, dict) and str(stream.get('codec_type') or '') in source_track_types
        ]
        source_position = next(
            (
                position
                for position, stream in enumerate(source_streams)
                if _svc_cls()._stream_service_id(stream) == pid
            ),
            -1,
        )
        if source_position < 0:
            return None
        identified_tracks = [
            track
            for track in identification.get('tracks') or []
            if isinstance(track, dict) and str(track.get('type') or '').strip().lower() == identify_track_type
        ]
        if source_position >= len(identified_tracks):
            return None
        try:
            return int(identified_tracks[source_position].get('id'))
        except Exception:
            return None

    @staticmethod
    def _map_slots_to_mkvmerge_track_ids(
            reference_slots: list[dict[str, object]],
            m2ts_path: str,
    ) -> Optional[list[int]]:
        """Map every reference PID slot to an input-local mkvmerge track ID without changing slot order."""
        mapped_track_ids: list[int] = []
        for slot in reference_slots:
            slot_type = str(slot.get('type') or '')
            try:
                pid = int(slot.get('pid'))
            except Exception:
                return None
            track_id = _svc_cls()._mkvmerge_tid_for_pid(m2ts_path, pid, slot_type)
            if track_id is None:
                return None
            mapped_track_ids.append(track_id)
        return mapped_track_ids

    @staticmethod
    def _resolve_mpls_path_from_conf(conf: dict[str, int | str], bdmv_root: str = '') -> str:
        """Absolute ``.mpls`` path from configuration row (``folder`` + ``selected_mpls`` stem or rel path)."""
        folder = os.path.normpath(str(conf.get('folder') or bdmv_root or '')).rstrip(os.sep)
        raw = str(conf.get('selected_mpls') or '').strip()
        if not raw:
            return ''
        if os.path.isfile(raw):
            return os.path.normpath(raw)
        if not folder:
            return raw if raw.lower().endswith('.mpls') else f'{raw}.mpls'
        norm = raw.replace('\\', '/')
        if norm.lower().endswith('.mpls'):
            if norm.lower().startswith('bdmv/playlist/'):
                return os.path.normpath(os.path.join(folder, *norm.split('/')))
            return os.path.normpath(os.path.join(folder, 'BDMV', 'PLAYLIST', os.path.basename(norm)))
        if norm.lower().startswith('bdmv/playlist/'):
            return os.path.normpath(os.path.join(folder, *norm.split('/')) + '.mpls')
        stem = os.path.splitext(os.path.basename(norm))[0]
        return os.path.normpath(os.path.join(folder, 'BDMV', 'PLAYLIST', f'{stem}.mpls'))

    @staticmethod
    def _probe_m2ts_for_remux_source(source_path: str) -> tuple[str, str]:
        """Return ``(first_playlist_m2ts, mpls_path_or_empty)`` for remux identify checks."""
        src = os.path.normpath(str(source_path or ''))
        if not src or not os.path.isfile(src):
            return '', ''
        if src.lower().endswith('.m2ts'):
            return src, ''
        if not src.lower().endswith('.mpls'):
            return '', ''
        try:
            ch = Chapter(src)
            playlist_dir = os.path.dirname(src)
            stream_dir = os.path.normpath(os.path.join(playlist_dir, '..', 'STREAM'))
            def _stream_m2ts_path(stem_or_name: str) -> str:
                name = str(stem_or_name or '').strip()
                if not name:
                    return ''
                if not name.lower().endswith('.m2ts'):
                    name = f'{name}.m2ts'
                return os.path.normpath(os.path.join(stream_dir, name))

            idx_to_m2ts, _ = get_index_to_m2ts_and_offset(ch)
            if idx_to_m2ts:
                first_key = sorted(idx_to_m2ts.keys())[0]
                probe = _stream_m2ts_path(idx_to_m2ts[first_key])
                if probe and os.path.isfile(probe):
                    return probe, src
            play_rows = list(ch.in_out_time or [])
            if play_rows:
                first_name = str(play_rows[0][0] or '').strip()
                if first_name:
                    probe = _stream_m2ts_path(first_name)
                    if os.path.isfile(probe):
                        return probe, src
        except Exception:
            pass
        return '', src

    @staticmethod
    def _mpls_identify_has_slot(ident: dict[str, object], slot: dict[str, object]) -> bool:
        typ = str(slot.get('type') or '').strip().lower()
        if typ == 'subtitle':
            typ = 'subtitles'
        tracks = [t for t in (ident.get('tracks') or []) if isinstance(t, dict)]
        if typ == 'video':
            return any(str(t.get('type') or '').strip().lower() == 'video' for t in tracks)
        try:
            want_pid = int(slot.get('pid'))
        except Exception:
            return False
        for t in tracks:
            if str(t.get('type') or '').strip().lower() != typ:
                continue
            props = t.get('properties') if isinstance(t.get('properties'), dict) else {}
            spid = _svc_cls()._int_from_mkvmerge_prop(props.get('stream_id'))
            if spid is None:
                spid = _svc_cls()._int_from_mkvmerge_prop(props.get('number'))
            if spid == want_pid:
                return True
        return False

    @staticmethod
    def _mpls_identify_pids_by_type(ident: dict[str, object]) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {'video': [], 'audio': [], 'subtitles': []}
        for t in ident.get('tracks') or []:
            if not isinstance(t, dict):
                continue
            typ = str(t.get('type') or '').strip().lower()
            if typ == 'subtitle':
                typ = 'subtitles'
            if typ not in out:
                continue
            props = t.get('properties') if isinstance(t.get('properties'), dict) else {}
            spid = _svc_cls()._int_from_mkvmerge_prop(props.get('stream_id'))
            if spid is None:
                spid = _svc_cls()._int_from_mkvmerge_prop(props.get('number'))
            if spid is not None:
                out[typ].append(int(spid))
        return out

    @staticmethod
    def _format_remux_slot_pid_list(slots: list[dict[str, object]]) -> str:
        formatted_slots: list[str] = []
        for slot in slots or []:
            track_type = str(slot.get('type') or '?')
            try:
                formatted_slots.append(f'{track_type}:0x{int(slot.get("pid")):04X}')
            except Exception:
                formatted_slots.append(f'{track_type}:?')
        return ', '.join(formatted_slots) if formatted_slots else '(none)'

    @staticmethod
    def _log_mkvmerge_identify_slot_gap(
            ident_path: str,
            probe_m2ts: str,
            ref_slots: list[dict[str, object]],
            ident: Optional[dict[str, object]],
            reason: str,
            missing_slots: Optional[list[dict[str, object]]] = None,
    ) -> None:
        print(f'[remux-fallback] mkvmerge --identify check failed: {reason}')
        if ident_path:
            print(f'[remux-fallback]   identify target: {ident_path}')
        if probe_m2ts:
            print(f'[remux-fallback]   probe m2ts: {probe_m2ts}')
        if ref_slots:
            print(f'[remux-fallback]   remux slots: {_svc_cls()._format_remux_slot_pid_list(ref_slots)}')
        if isinstance(ident, dict) and ident.get('tracks'):
            by_type = _svc_cls()._mpls_identify_pids_by_type(ident)
            video_pids_text = ', '.join(f'0x{pid:04X}' for pid in by_type.get('video') or []) or '(none)'
            audio_pids_text = ', '.join(f'0x{pid:04X}' for pid in by_type.get('audio') or []) or '(none)'
            subtitle_pids_text = ', '.join(f'0x{pid:04X}' for pid in by_type.get('subtitles') or []) or '(none)'
            print(
                f'[remux-fallback]   identify stream_id: video=[{video_pids_text}] '
                f'audio=[{audio_pids_text}] subtitles=[{subtitle_pids_text}]'
            )
        miss = list(missing_slots or [])
        if not miss and isinstance(ident, dict) and ref_slots:
            miss = [
                slot for slot in ref_slots
                if not _svc_cls()._mpls_identify_has_slot(ident, slot)
            ]
        if miss:
            print(f'[remux-fallback]   missing PID(s): {_svc_cls()._format_remux_slot_pid_list(miss)}')

    def _set_dovi_mux_plan_for_mpls(
            self,
            mpls_path: str,
            *,
            report_detected_pair: bool = False,
    ) -> None:
        probe_m2ts, _ = _svc_cls()._probe_m2ts_for_remux_source(mpls_path)
        self._dovi_mux_plan = _svc_cls().detect_dovi_mux_pair(
            mpls_path,
            probe_m2ts,
            getattr(self, 'mux_dolby_vision', True),
        )
        plan = self._dovi_mux_plan
        if not (isinstance(plan, dict) and plan.get('active')):
            self._dovi_mux_plan = None
            return
        if report_detected_pair:
            print(self.t(
                'MPLS Dolby Vision pair BL={base_pid} EL={enhancement_pid}; mux enabled: {enabled}'
            ).format(
                base_pid=f'0x{int(plan["bl_pid"]):04X}',
                enhancement_pid=f'0x{int(plan["el_pid"]):04X}',
                enabled=bool(plan.get('mux_enabled')),
            ))

    def _mkvmerge_identify_covers_remux_slots(
            self,
            source_path: str,
            copy_audio_track: list[str],
            copy_sub_track: list[str],
    ) -> bool:
        """
        True when ``mkvmerge --identify`` on ``source_path`` exposes every remux slot
        (video + selected audio/subtitle indices). Extra identify tracks are allowed.
        """
        src = os.path.normpath(str(source_path or ''))
        if not src or not os.path.isfile(src):
            _svc_cls()._log_mkvmerge_identify_slot_gap(
                src, '', [], None,
                'remux source path missing or not a file',
            )
            return False
        probe_m2ts, mpls_path = _svc_cls()._probe_m2ts_for_remux_source(src)
        ident_target = os.path.normpath(mpls_path or src)
        if not probe_m2ts or not os.path.isfile(probe_m2ts):
            _svc_cls()._log_mkvmerge_identify_slot_gap(
                ident_target, '', [], None,
                'cannot resolve first playlist m2ts for probe (no chapter marks and no play items?)',
            )
            return False
        dovi_plan = getattr(self, '_dovi_mux_plan', None)
        ref_slots = _svc_cls()._ordered_track_slots_for_remux(
            probe_m2ts, list(copy_audio_track or []), list(copy_sub_track or []),
            dovi_plan=dovi_plan if isinstance(dovi_plan, dict) else None,
            mpls_path=mpls_path,
        )
        if not ref_slots:
            _svc_cls()._log_mkvmerge_identify_slot_gap(
                ident_target, probe_m2ts, [], None,
                'no remux slots from edit-tracks selection (check -a/-s stream indices on probe m2ts)',
            )
            return False
        if src.lower().endswith('.m2ts'):
            if _svc_cls()._map_slots_to_mkvmerge_track_ids(ref_slots, src) is None:
                _svc_cls()._log_mkvmerge_identify_slot_gap(
                    ident_target, probe_m2ts, ref_slots, None,
                    'm2ts: cannot map remux slot PID to mkvmerge track id',
                    missing_slots=ref_slots,
                )
                return False
            return True
        ident = _svc_cls()._mkvmerge_identify_json(mpls_path or src)
        if not isinstance(ident, dict) or not ident.get('tracks'):
            _svc_cls()._log_mkvmerge_identify_slot_gap(
                ident_target, probe_m2ts, ref_slots, ident if isinstance(ident, dict) else None,
                'mkvmerge --identify returned no tracks',
            )
            return False
        missing_slots = [
            slot for slot in ref_slots
            if not _svc_cls()._mpls_identify_has_slot(ident, slot)
        ]
        if missing_slots:
            _svc_cls()._log_mkvmerge_identify_slot_gap(
                ident_target, probe_m2ts, ref_slots, ident,
                'remux slot PID not found on identify (stream_id / number)',
                missing_slots=missing_slots,
            )
            return False
        if isinstance(dovi_plan, dict) and dovi_plan.get('active') and dovi_plan.get('mux_enabled'):
            _svc_cls()._log_mkvmerge_identify_slot_gap(
                ident_target, probe_m2ts, ref_slots, ident,
                'Dolby Vision mux enabled (primary MPLS mkvmerge skipped; use remux-fallback with dovi_tool)',
            )
            return False
        return True

    @staticmethod
    def _track_lists_from_mkvmerge_cmd(cmd: str) -> tuple[Optional[list[str]], Optional[list[str]]]:
        """
        Best-effort parse of ``-a`` / ``-s`` track lists from a mkvmerge command line.
        Returns (audio_ids, subtitle_ids); each entry is None if that flag was not found
        (caller should keep defaults from ``_select_tracks_for_source``).
        Returns (None, None) only when neither flag appears.
        """
        if not (cmd or '').strip():
            return None, None

        def _last_flag(flag: str) -> Optional[list[str]]:
            line = re.sub(r'[\r\n]+', ' ', cmd)
            matches = list(re.finditer(rf'(?:^|[\s]){re.escape(flag)}\s+(\S+)', line))
            if not matches:
                return None
            tok = matches[-1].group(1).strip().strip('"').strip("'")
            if not tok or tok in ('*', '!'):
                return None
            parts = [p.strip() for p in tok.split(',') if p.strip()]
            return parts or None

        a = _last_flag('-a')
        s = _last_flag('-s')
        if a is None and s is None:
            return None, None
        return a, s

    @staticmethod
    def _fallback_track_lists(
            remux_cmd: str,
            copy_audio_track: list[str],
            copy_sub_track: list[str],
    ) -> tuple[list[str], list[str]]:
        """
        Lists for ``_try_remux_mpls_track_aligned`` / split fallback.

        Primary ``remux_cmd`` uses mkvmerge ``-a`` / ``-s`` with that tool's numbering (often per-type
        slots / identify IDs). Edit-tracks stores **M2TS stream row indices** for
        :meth:`_ordered_track_slots_for_remux`. Taking ``-a``/``-s`` from the failed primary command
        overwrites the user's selection with incompatible numbers (e.g. ``-a 1,8`` vs indices ``1`` and
        ``5``).
        """
        ca = list(copy_audio_track or [])
        cs = list(copy_sub_track or [])
        if ca or cs:
            return ca, cs
        pa, ps = _svc_cls()._track_lists_from_mkvmerge_cmd(remux_cmd)
        fa = list(pa) if pa is not None else []
        fs = list(ps) if ps is not None else []
        return fa, fs

    @staticmethod
    def _remux_cmd_shell_lines(cmd: str) -> list[str]:
        """Non-empty lines of ``remux_cmd`` (``\\n`` / ``\\r\\n``) for per-line parsing and execution."""
        return [ln.strip() for ln in (cmd or '').splitlines() if ln.strip()]

    @staticmethod
    def _split_segment_count_from_mkvmerge_one_line(line: str) -> Optional[int]:
        raw = (line or '').strip()
        if not raw:
            return None
        m = re.search(r'--split\s+("([^"]+)"|\'([^\']+)\'|(\S+))', raw)
        if not m:
            return None
        spec = (m.group(2) or m.group(3) or m.group(4) or '').strip()
        low = spec.lower()
        if low.startswith('parts:'):
            payload = spec[6:].strip()
            if not payload:
                return None
            segs = [x.strip() for x in payload.split(',') if x.strip()]
            return len(segs) if segs else None
        if low.startswith('chapters:'):
            payload = spec[9:].strip()
            if not payload:
                return None
            if payload.lower() in ('all',):
                return None
            cuts = [x.strip() for x in payload.split(',') if x.strip()]
            return (len(cuts) + 1) if cuts else 1
        return None

    @staticmethod
    def _split_segment_count_from_mkvmerge_cmd(cmd: str) -> Optional[int]:
        """
        Best-effort parse of mkvmerge ``--split`` (newline-split: sum counts from each line that has ``--split``).
        Supports ``--split parts:...`` and ``--split chapters:...``.
        """
        lines = _svc_cls()._remux_cmd_shell_lines(cmd)
        if not lines:
            return None
        total = 0
        found = False
        for ln in lines:
            n = _svc_cls()._split_segment_count_from_mkvmerge_one_line(ln)
            if isinstance(n, int) and n > 0:
                total += n
                found = True
        return total if found else None

    @staticmethod
    def _split_chapters_ints_from_mkvmerge_one_line(line: str) -> Optional[list[int]]:
        """Parse ``--split chapters:n,m,...`` from one command line; None if absent / unexpanded / invalid."""
        raw = (line or '').strip()
        if not raw or '{' in raw:
            return None
        m = re.search(r'--split\s+("([^"]+)"|\'([^\']+)\'|(\S+))', raw)
        if not m:
            return None
        spec = (m.group(2) or m.group(3) or m.group(4) or '').strip()
        low = spec.lower()
        if not low.startswith('chapters:'):
            return None
        payload = spec[9:].strip()
        if not payload or payload.lower() in ('all',):
            return None
        out: list[int] = []
        for x in payload.split(','):
            x = x.strip()
            if not x:
                continue
            try:
                out.append(int(x, 10))
            except ValueError:
                return None
        return out or None

    @staticmethod
    def _mkvmerge_output_path_from_line(line: str) -> Optional[str]:
        raw = (line or '').strip()
        if not raw:
            return None
        m = re.search(r'\s(?:-o|--output)\s+("[^"]*"|\'[^\']*\'|[^\s]+)', raw, re.IGNORECASE)
        if not m:
            return None
        p = (m.group(1) or '').strip()
        if len(p) >= 2 and p[0] == p[-1] and p[0] in '"\'':
            p = p[1:-1]
        return p.strip() or None


    @staticmethod
    def _mkvmerge_expected_paths_for_shell_line(
            line: str,
            confs: list[dict[str, int | str]],
            mpls_path_default: str,
    ) -> tuple[Optional[str], list[str]]:
        """
        For one shell line: primary ``-o`` path and expected MKV paths after ``--split``
        (``stem.mkv`` or ``stem-001.mkv`` …). Uses ``confs`` / default MPLS when segment
        count cannot be parsed from the line.
        """
        out = _svc_cls()._mkvmerge_output_path_from_line(line)
        if not out:
            return None, []
        out_n = os.path.normpath(out)
        nseg = _svc_cls()._split_segment_count_from_mkvmerge_one_line(line)
        if (nseg is None or nseg < 1) and '--split' in line.lower() and confs:
            stem_ln = _svc_cls()._mkvmerge_line_source_mpls_stem(line)
            sub: list[dict[str, int | str]] = []
            for c in confs:
                sc = os.path.splitext(os.path.basename(str(c.get('selected_mpls') or '').strip().replace('\\', '/')))[0]
                if stem_ln and sc and stem_ln.lower() != sc.lower():
                    continue
                sub.append(c)
            if not sub:
                sub = list(confs)
            sub.sort(key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 0))
            mp = ''
            for c in sub:
                kk = str(c.get('selected_mpls') or '').strip()
                cand = kk if kk.lower().endswith('.mpls') else (kk + '.mpls' if kk else '')
                if cand and os.path.isfile(cand):
                    mp = cand
                    break
            if not mp and mpls_path_default and os.path.isfile(mpls_path_default):
                mp = mpls_path_default
            if mp:
                try:
                    ch = Chapter(mp)
                    nseg = len(_svc_cls()._series_episode_segments_bounds(ch, sub))
                except Exception:
                    nseg = None
        if nseg is None or nseg < 1:
            nseg = 1
        if nseg <= 1:
            return out_n, [out_n]
        return out_n, _svc_cls()._expected_mkvmerge_split_output_paths(out_n, nseg)

    @staticmethod
    def _m2ts_clip_time_window_sec(m2ts_path: str, in_time: int, out_time: int) -> tuple[bool, float, float]:
        """
        (needs_split, start_sec, end_sec) for one playlist item.
        start = (in_time*2 - first_pts)/90000
        end   = start + (out_time-in_time)/45000
        No split when start==0 and end ~= file duration.
        """
        clip_sec = max(0.0, (out_time - in_time) / 45000.0)
        pts: Optional[int] = None
        dur90: Optional[int] = None
        try:
            if m2ts_path and os.path.isfile(m2ts_path):
                pts, dur90 = _m2ts_cached_pts_dur(m2ts_path)
        except Exception:
            pts = None
            dur90 = None
        if pts is None:
            return False, 0.0, clip_sec
        start_sec = (in_time * 2 - pts) / 90000.0
        end_sec = start_sec + clip_sec
        file_dur_sec = (dur90 / 90000.0) if (dur90 is not None and dur90 > 0) else clip_sec
        if abs(start_sec) < 1e-3 and abs(end_sec - file_dur_sec) < 1e-3:
            return False, 0.0, file_dur_sec
        s = max(0.0, start_sec)
        e = max(0.0, end_sec)
        if e <= s + 1e-3:
            # Guard against producing --split parts:00:00:00.000-00:00:00.000
            return False, 0.0, file_dur_sec
        return True, s, e

    @staticmethod
    def m2ts_sp_custom_segment_time_window_sec(mpls_path: str, output_name: str) -> Optional[tuple[float, float]]:
        """
        Time window (seconds on MPLS timeline) for SP ``output_name`` suffix like
        ``beginning_to_chapter_4`` — same chapter indices as ``_write_custom_chapter_for_segment``.
        """
        if not (mpls_path and output_name and str(mpls_path).strip()):
            return None
        if not os.path.isfile(mpls_path):
            return None
        m = re.search(r'(beginning|chapter_(\d+))_to_(chapter_(\d+)|ending)', output_name, re.IGNORECASE)
        if not m:
            return None
        try:
            chapter = Chapter(mpls_path)
            rows = sum(map(len, chapter.mark_info.values()))
            total_end = rows + 1
            start_idx = 1 if (m.group(1) or '').lower() == 'beginning' else int(m.group(2) or 1)
            g3 = (m.group(3) or '').lower()
            if g3 == 'ending':
                end_idx = total_end
            else:
                end_idx = int(m.group(4) or total_end)
            start_idx = max(1, min(start_idx, total_end))
            end_idx = max(start_idx + 1, min(end_idx, total_end))
            _, index_to_offset = get_index_to_m2ts_and_offset(chapter)

            def _off(idx: int) -> float:
                if idx >= total_end:
                    return chapter.get_total_time()
                return float(index_to_offset.get(idx, 0.0))

            return float(_off(start_idx)), float(_off(end_idx))
        except Exception:
            return None

    @staticmethod
    def m2ts_file_detail_whole_stream_file(m2ts_path: str) -> str:
        """``basename(start-end)`` for one .m2ts using container duration (no playlist in/out)."""
        name = os.path.basename(str(m2ts_path or '')) or ''
        if not m2ts_path or not os.path.isfile(m2ts_path):
            return f'{name}(00:00:00.000-00:00:00.000)'
        try:
            _pts, dur90 = _m2ts_cached_pts_dur(m2ts_path)
            end = max(0.0, (dur90 / 90000.0)) if (dur90 is not None and dur90 > 0) else 0.0
        except Exception:
            end = 0.0
        st = get_time_str(0.0)
        ed = get_time_str(end)
        if st == '0':
            st = '00:00:00.000'
        if ed == '0':
            ed = '00:00:00.000'
        return f'{name}({st}-{ed})'

    @staticmethod
    def m2ts_file_detail_from_mpls_playlist(mpls_path: str) -> str:
        """
        ``name.m2ts(start-end),...`` for each ``Chapter(mpls_path).in_out_time`` row.
        Per README: ``start = (in_time*2 - first_pts)/90000``,
        ``end = start + (out_time-in_time)/45000``; clip base name is tuple[0].
        """
        mp = str(mpls_path or '').strip()
        if not mp or not mp.lower().endswith('.mpls') or not os.path.isfile(mp):
            return ''
        playlist_dir = os.path.dirname(os.path.normpath(mp))
        stream_dir = os.path.normpath(os.path.join(playlist_dir, '..', 'STREAM'))
        try:
            rows = list(Chapter(mp).in_out_time or [])
        except Exception:
            return ''
        if not rows:
            return ''
        eps = 1e-5
        parts: list[str] = []
        for fname, in_time, out_time in rows:
            m2ts_path = os.path.join(stream_dir, f'{fname}.m2ts')
            base_name = f'{fname}.m2ts'
            clip_sec = max(0.0, (out_time - in_time) / 45000.0)
            if clip_sec <= eps:
                continue
            # UI detail always reflects playlist in/out (README formula), not whole-file shortcut.
            slice_start = 0.0
            slice_end = clip_sec
            if os.path.isfile(m2ts_path):
                try:
                    pts, _dur90 = _m2ts_cached_pts_dur(m2ts_path)
                    if pts is not None:
                        slice_start = max(0.0, (in_time * 2 - pts) / 90000.0)
                        slice_end = slice_start + clip_sec
                except Exception:
                    pass
            if slice_end <= slice_start + eps:
                continue
            st = get_time_str(slice_start)
            ed = get_time_str(slice_end)
            if st == '0':
                st = '00:00:00.000'
            if ed == '0':
                ed = '00:00:00.000'
            parts.append(f'{base_name}({st}-{ed})')
        return ','.join(parts)

    @staticmethod
    def m2ts_file_basenames_from_mpls_playlist(mpls_path: str) -> list[str]:
        """
        Playlist play-item order: each ``Chapter(mpls_path).in_out_time`` row contributes ``<clip>.m2ts``
        from the tuple's clip-information filename (first field).
        """
        mp = str(mpls_path or '').strip()
        if not mp or not mp.lower().endswith('.mpls') or not os.path.isfile(mp):
            return []
        try:
            rows = list(Chapter(mp).in_out_time or [])
        except Exception:
            return []
        return list(dict.fromkeys([f'{fname}.m2ts' for fname, _, _ in rows]))

    @staticmethod
    def m2ts_file_detail_for_standalone_m2ts_paths(m2ts_paths: list[str]) -> str:
        parts: list[str] = []
        for p in m2ts_paths or []:
            pn = os.path.normpath(str(p or '').strip())
            if not pn:
                continue
            parts.append(MediaInfoTrackMappingMixin.m2ts_file_detail_whole_stream_file(pn))
        return ','.join(parts)

    @staticmethod
    def m2ts_file_detail_for_mpls_timeline_window(mpls_path: str, w0: float, w1: float) -> str:
        """
        ``name.m2ts(start-end),...`` for the overlap of [w0,w1) with each playlist clip.
        Slice math matches ``_try_remux_mpls_split_outputs_track_aligned`` (multi-output fallback).
        """
        if w1 <= w0 + 1e-5:
            return ''
        mp = str(mpls_path or '').strip()
        if not mp or not mp.lower().endswith('.mpls') or not os.path.isfile(mp):
            return ''
        ck = (_normalized_media_path(mp), round(float(w0), 4), round(float(w1), 4))
        if ck in _MPLS_TIMELINE_DETAIL_CACHE:
            return _MPLS_TIMELINE_DETAIL_CACHE[ck]
        playlist_dir = os.path.dirname(os.path.normpath(mp))
        stream_dir = os.path.normpath(os.path.join(playlist_dir, '..', 'STREAM'))
        play_rows = _mpls_play_rows_cached(mp)
        if not play_rows:
            _MPLS_TIMELINE_DETAIL_CACHE[ck] = ''
            return ''
        eps = 1e-5
        parts: list[str] = []
        acc = 0.0
        for fname, in_time, out_time in play_rows:
            clip_acc = acc
            dur = max(0.0, (out_time - in_time) / 45000.0)
            seg_lo = max(w0, clip_acc)
            seg_hi = min(w1, clip_acc + dur)
            acc = clip_acc + dur
            if dur <= eps or seg_lo + eps >= seg_hi:
                continue
            m2ts_path = os.path.join(stream_dir, f'{fname}.m2ts')
            base_name = f'{fname}.m2ts'
            if not os.path.isfile(m2ts_path):
                continue
            need, a, b = MediaInfoTrackMappingMixin._m2ts_clip_time_window_sec(m2ts_path, in_time, out_time)
            full_lo = 0.0 if not need else float(a)
            full_hi = float(b)
            span = max(0.0, full_hi - full_lo)
            if span <= eps:
                continue
            p0 = (seg_lo - clip_acc) / dur
            p1 = (seg_hi - clip_acc) / dur
            p0 = min(1.0, max(0.0, p0))
            p1 = min(1.0, max(0.0, p1))
            if p1 <= p0 + eps / max(dur, eps):
                continue
            slice_start = full_lo + p0 * span
            slice_end = full_lo + p1 * span
            if slice_end <= slice_start + eps:
                continue
            st = get_time_str(slice_start)
            ed = get_time_str(slice_end)
            if st == '0':
                st = '00:00:00.000'
            if ed == '0':
                ed = '00:00:00.000'
            parts.append(f'{base_name}({st}-{ed})')
        result = ','.join(parts)
        _MPLS_TIMELINE_DETAIL_CACHE[ck] = result
        return result

    @staticmethod
    def m2ts_basenames_from_mpls_timeline_window(mpls_path: str, w0: float, w1: float) -> list[str]:
        """Ordered unique ``*.m2ts`` names used by ``m2ts_file_detail_for_mpls_timeline_window`` for [w0,w1)."""
        detail = MediaInfoTrackMappingMixin.m2ts_file_detail_for_mpls_timeline_window(mpls_path, w0, w1)
        out: list[str] = []
        for seg in (detail or '').split(','):
            seg = seg.strip()
            if not seg:
                continue
            head = seg.split('(', 1)[0].strip()
            bn = os.path.basename(head)
            if bn.lower().endswith('.m2ts') and bn not in out:
                out.append(bn)
        return out


    @staticmethod
    def _mkvmerge_select_flags_from_mapped(
            mapped_track_ids: list[int],
            identification: dict[str, object],
    ) -> tuple[str, str, str]:
        """Return mkvmerge video/audio/subtitle selectors for exactly the mapped input track IDs."""
        wanted_track_ids = set(map(int, mapped_track_ids))
        selected_by_type: dict[str, list[int]] = {'video': [], 'audio': [], 'subtitles': []}
        for track in identification.get('tracks') or []:
            if not isinstance(track, dict):
                continue
            try:
                track_id = int(track.get('id'))
            except Exception:
                continue
            track_type = str(track.get('type') or '')
            if track_id in wanted_track_ids and track_type in selected_by_type:
                selected_by_type[track_type].append(track_id)
        return tuple(
            ','.join(map(str, selected_by_type[track_type]))
            for track_type in ('video', 'audio', 'subtitles')
        )

    @staticmethod
    def _mkvmerge_das_flag_strings_for_m2ts(
            m2ts_path: str,
            copy_audio_track: list[str],
            copy_sub_track: list[str],
            dovi_plan: Optional[dict[str, object]] = None,
    ) -> tuple[str, str, str]:
        """
        mkvmerge ``-d`` / ``-a`` / ``-s`` values for one ``.m2ts`` (track ids, not stream row indices).

        Maps edit-tracks stream indices → PID → mkvmerge id; falls back to raw index strings when mapping fails.
        """
        path = os.path.normpath(str(m2ts_path or ''))
        if not path or not os.path.isfile(path):
            return '', '', ''

        def _index_fallback() -> tuple[str, str, str]:
            a_f = ','.join(str(x).strip() for x in (copy_audio_track or []) if str(x).strip())
            s_f = ','.join(str(x).strip() for x in (copy_sub_track or []) if str(x).strip())
            return '', a_f, s_f

        ref_slots = _svc_cls()._ordered_track_slots_for_remux(
            path,
            list(copy_audio_track or []),
            list(copy_sub_track or []),
            dovi_plan=dovi_plan if isinstance(dovi_plan, dict) else None,
        )
        if not ref_slots:
            return _index_fallback()
        mapped = _svc_cls()._map_slots_to_mkvmerge_track_ids(ref_slots, path)
        if not mapped:
            return _index_fallback()
        ident = _svc_cls()._mkvmerge_identify_json(path)
        video_ids, audio_ids, subtitle_ids = _svc_cls()._mkvmerge_select_flags_from_mapped(mapped, ident)
        if dovi_plan and dovi_plan.get('active') and dovi_plan.get('mux_enabled'):
            video_ids = ''
        return video_ids, audio_ids, subtitle_ids

    @staticmethod
    def _series_episode_segments_bounds(chapter: Chapter, confs: list[dict[str, int | str]]) -> list[tuple[int, int]]:
        """Same (start_chapter, end_chapter) pairs as the series branch of ``_make_main_mpls_remux_cmd``."""
        if not confs:
            return []
        confs_sorted = sorted(confs, key=lambda c: int(c.get('chapter_index') or c.get('start_at_chapter') or 1))
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        segments: list[tuple[int, int]] = []
        for i, c in enumerate(confs_sorted):
            s = int(c.get('start_at_chapter') or c.get('chapter_index') or 1)
            if c.get('end_at_chapter'):
                e = int(c.get('end_at_chapter') or total_end)
            elif i + 1 < len(confs_sorted):
                e = int(confs_sorted[i + 1].get('start_at_chapter') or confs_sorted[i + 1].get(
                    'chapter_index') or total_end)
            else:
                e = total_end
            s = max(1, min(s, total_end))
            e = max(s + 1, min(e, total_end))
            seg = (s, e)
            if segments and segments[-1] == seg:
                continue
            segments.append(seg)
        return segments

    @staticmethod
    def _episode_float_windows_from_config_bounds(
            mpls_path: str, confs: list[dict[str, int | str]],
    ) -> list[tuple[float, float]]:
        """MPLS timeline (start_sec, end_sec) windows matching table2 / ``confs`` episode chapter bounds."""
        if not mpls_path or (not confs) or (not os.path.isfile(mpls_path)):
            return []
        ch_tmp = Chapter(mpls_path)
        segs_tmp = _svc_cls()._series_episode_segments_bounds(ch_tmp, confs)
        if not segs_tmp:
            return []
        _i2m_tmp, i2o_tmp = get_index_to_m2ts_and_offset(ch_tmp)
        rows_tmp = sum(map(len, ch_tmp.mark_info.values()))
        total_end_tmp = rows_tmp + 1

        def _off_tmp(idx: int) -> float:
            if idx >= total_end_tmp:
                return ch_tmp.get_total_time()
            return float(i2o_tmp.get(idx, 0.0))

        return [(float(_off_tmp(s0)), float(_off_tmp(e0))) for s0, e0 in segs_tmp]

    @staticmethod
    def theoretical_remux_output_paths_ordered(
            cmd: str,
            confs: list[dict[str, int | str]],
            mpls_path_default: str,
    ) -> list[str]:
        """Ordered theoretical mkvmerge ``-o`` outputs for ``remux_cmd`` (same aggregation as split-check)."""
        lines = _svc_cls()._remux_cmd_shell_lines(cmd)
        if not lines and (cmd or '').strip():
            lines = [(cmd or '').strip()]
        ordered: list[str] = []
        for ln in lines:
            _ob, expected_line = _svc_cls()._mkvmerge_expected_paths_for_shell_line(
                ln, confs, mpls_path_default)
            if expected_line:
                ordered.extend(expected_line)
        return [os.path.normpath(p) for p in ordered]

    @staticmethod
    def _remux_parsed_chapter_bounds_for_theory_count(
            cmd: str,
            confs: list[dict[str, int | str]],
            mpls_path0: str,
            n_expect: int,
    ) -> Optional[list[tuple[int, int]]]:
        """Chapter index bounds derived only from ``remux_cmd`` parsing (multi-line / ``--split``), not table2."""
        if n_expect < 1:
            return None
        mb = _svc_cls()._chapter_split_bounds_from_multi_line_remux_cmd(cmd, confs)
        if mb and len(mb) == n_expect:
            return mb
        lines_chk = _svc_cls()._remux_cmd_shell_lines(cmd)
        if not lines_chk and (cmd or '').strip():
            lines_chk = [(cmd or '').strip()]
        stem0 = ''
        if mpls_path0:
            stem0 = os.path.splitext(os.path.basename(mpls_path0.replace('\\', '/')))[0]
        windows = _svc_cls()._split_parts_windows_from_mkvmerge_cmd(cmd, mpls_stem=stem0 or None)
        if not windows:
            for ln in lines_chk:
                cuts_ln = _svc_cls()._split_chapters_ints_from_mkvmerge_one_line(ln)
                if not cuts_ln:
                    continue
                stem_ln = _svc_cls()._mkvmerge_line_source_mpls_stem(ln)
                mpath_use = ''
                for c in confs:
                    raw_m = str(c.get('selected_mpls') or '').strip()
                    sc = os.path.splitext(os.path.basename(raw_m.replace('\\', '/')))[0]
                    if stem_ln and sc and stem_ln.lower() != sc.lower():
                        continue
                    cand = raw_m if raw_m.lower().endswith('.mpls') else (raw_m + '.mpls' if raw_m else '')
                    if cand and os.path.isfile(cand):
                        mpath_use = cand
                        break
                if not mpath_use and mpls_path0 and os.path.isfile(mpls_path0):
                    mpath_use = mpls_path0
                if mpath_use:
                    windows = _svc_cls()._time_windows_from_split_chapter_numbers(mpath_use, cuts_ln)
                    if windows:
                        break
        if windows and mpls_path0 and os.path.isfile(mpls_path0):
            bounds = _svc_cls()._chapter_bounds_from_split_windows(mpls_path0, windows)
            if len(bounds) == n_expect:
                return bounds
        return None

    @staticmethod
    def _time_windows_from_split_chapter_numbers(mpls_path: str, cuts: list[int]) -> list[tuple[float, float]]:
        """Turn ``--split chapters:`` cut numbers (split before chapter N) into MPLS time windows."""
        if not mpls_path or (not cuts) or (not os.path.isfile(mpls_path)):
            return []
        chapter = Chapter(mpls_path)
        _, i2o = get_index_to_m2ts_and_offset(chapter)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1

        def off(i: int) -> float:
            if i >= total_end:
                return chapter.get_total_time()
            return float(i2o.get(i, 0.0))

        cuts_sorted = sorted({int(c) for c in cuts if 1 < int(c) <= total_end})
        if not cuts_sorted:
            return []
        windows: list[tuple[float, float]] = []
        prev = 1
        for c in cuts_sorted:
            windows.append((off(prev), off(c)))
            prev = c
        windows.append((off(prev), chapter.get_total_time()))
        return windows

    @staticmethod
    def _expected_mkvmerge_split_output_paths(output_norm: str, n_segments: int) -> list[str]:
        """Paths ``stem-001.mkv`` … mkvmerge writes when ``-o stem.mkv`` and ``--split parts:``."""
        if n_segments <= 1 or not output_norm:
            return []
        d = os.path.dirname(output_norm)
        base = os.path.basename(output_norm)
        stem, ext = os.path.splitext(base)
        ex = ext if ext else '.mkv'
        return [os.path.join(d, f'{stem}-{k + 1:03d}{ex}') for k in range(n_segments)]

    @staticmethod
    def _filter_ref_slots_common_across_playlist(
            ref_slots: list[dict[str, object]],
            stream_dir: str,
            rows: list[tuple[str, int, int]],
    ) -> Optional[list[dict[str, object]]]:
        """
        Keep only slots whose PID exists (same codec_type) in every m2ts of this playlist.
        This implements "drop extra / keep common" to avoid aborting concat on missing optional tracks.
        """
        if not ref_slots:
            return []
        clip_pid_sets: list[dict[str, set[int]]] = []
        for fname, _in_time, _out_time in rows:
            m2ts_path = os.path.join(stream_dir, f'{fname}.m2ts')
            if not os.path.isfile(m2ts_path):
                return None
            by_type: dict[str, set[int]] = {'video': set(), 'audio': set(), 'subtitles': set()}
            for s in _svc_cls()._m2ts_track_streams(m2ts_path):
                if not isinstance(s, dict):
                    continue
                ct = str(s.get('codec_type') or '')
                if ct == 'video':
                    typ = 'video'
                elif ct == 'audio':
                    typ = 'audio'
                elif ct in ('subtitle', 'subtitles'):
                    typ = 'subtitles'
                else:
                    continue
                pid = _svc_cls()._stream_service_id(s)
                if pid is not None:
                    by_type[typ].add(pid)
            clip_pid_sets.append(by_type)
        kept: list[dict[str, object]] = []
        dropped: list[tuple[str, int]] = []
        for slot in ref_slots:
            typ = str(slot.get('type') or '')
            try:
                pid = int(slot.get('pid'))
            except Exception:
                dropped.append((typ, -1))
                continue
            ok = True
            for ps in clip_pid_sets:
                if pid not in ps.get(typ, set()):
                    ok = False
                    break
            if ok:
                kept.append(slot)
            else:
                dropped.append((typ, pid))
        if dropped:
            msg = ', '.join(f'{t}:{("0x%X" % p) if p >= 0 else "?"}' for t, p in dropped)
            print(f'[remux-fallback] drop non-common slots: {msg}')
        has_video = any(str(x.get('type') or '') == 'video' for x in kept)
        if not has_video:
            return None
        return kept


    @staticmethod
    def _tsmuxer_exe() -> str:
        p = str(core_settings.TS_MUXER_PATH or '').strip()
        if p and os.path.isfile(p):
            return p
        return shutil.which('tsMuxeR') or shutil.which('tsmuxer') or ''

    @staticmethod
    def _run_tsmuxer_probe(m2ts_path: str) -> str:
        exe = _svc_cls()._tsmuxer_exe()
        if not exe or not m2ts_path or not os.path.isfile(m2ts_path):
            return ''
        cmd = f'"{exe}" "{m2ts_path}"'
        try:
            p = run_command(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=120,
            )
            return (p.stdout or '') + ('\n' + (p.stderr or '') if p.stderr else '')
        except Exception:
            return ''

    @staticmethod
    def _parse_tsmuxer_probe_output(text: str) -> list[dict[str, object]]:
        lines = (text or '').replace('\r\n', '\n').split('\n')
        tracks: list[dict[str, object]] = []
        cur: Optional[dict[str, object]] = None
        for raw in lines:
            line = raw.strip()
            if line.startswith('Track ID:'):
                if isinstance(cur, dict) and cur.get('track_id') is not None:
                    tracks.append(cur)
                m = re.search(r'Track ID:\s*(\d+)', line, re.I)
                cur = {'track_id': int(m.group(1)) if m else None, 'stream_type': '', 'stream_id': '',
                       'delay_ms': None, 'fps': ''}
                continue
            if not isinstance(cur, dict):
                continue
            if line.startswith('Stream type:'):
                cur['stream_type'] = line.split(':', 1)[1].strip() if ':' in line else ''
                continue
            if line.startswith('Stream ID:'):
                cur['stream_id'] = line.split(':', 1)[1].strip() if ':' in line else ''
                continue
            if line.startswith('Stream info:'):
                inf = line.split(':', 1)[-1]
                mf = re.search(r'Frame rate:\s*([\d.]+)', inf, re.I)
                if mf:
                    cur['fps'] = mf.group(1).strip()
                continue
            if line.startswith('Stream delay:'):
                md = re.search(r'Stream delay:\s*(\d+)', line, re.I)
                if md:
                    cur['delay_ms'] = int(md.group(1))
                continue
        if isinstance(cur, dict) and cur.get('track_id') is not None:
            tracks.append(cur)
        return [t for t in tracks if t.get('track_id') is not None and str(t.get('stream_id') or '').strip()]

    @staticmethod
    def _tsmuxer_has_video_and_subtitles(tracks: list[dict[str, object]]) -> bool:
        has_v = False
        has_s = False
        for t in tracks:
            sid = str(t.get('stream_id') or '')
            st = str(t.get('stream_type') or '')
            if sid.upper().startswith('V_') or st.upper() in ('HEVC', 'H264', 'AVC', 'MPEG2', 'VC1', 'VVC'):
                has_v = True
            if 'PGS' in sid.upper() or 'PGS' in st.upper() or sid.upper().startswith('S_'):
                has_s = True
        return has_v and has_s


    @staticmethod
    def _tsmuxer_tracks_ordered_for_ref_slots(
            tsmuxer_tracks: list[dict[str, object]],
            ref_slots: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Probe rows for each ``ref_slots`` PID only, in slot list order (first occurrence per PID)."""
        by_tid: dict[int, dict[str, object]] = {}
        for t in tsmuxer_tracks or []:
            pid = _svc_cls()._tsmuxer_mpeg_pid(t)
            if pid is None:
                continue
            by_tid[pid] = t
        out: list[dict[str, object]] = []
        seen: set[int] = set()
        for slot in ref_slots or []:
            try:
                pid = int(slot.get('pid'))
            except Exception:
                continue
            if pid in seen:
                continue
            row = by_tid.get(pid)
            if row is not None:
                out.append(row)
                seen.add(pid)
        return out

    @staticmethod
    def _norm_lang_mkv(lcode: str) -> str:
        s = (lcode or '').strip().lower().replace('_', '-')
        if len(s) >= 3 and re.match(r'^[a-z]{3}', s):
            return s[:3]
        return 'und'

    @staticmethod
    def _write_tsmuxer_demux_meta(
            m2ts_path: str,
            tracks: list[dict[str, object]],
            pid_to_lang: dict[int, str],
            out_meta_path: str,
            fps_default: str,
    ) -> bool:
        try:
            rows = list(tracks or [])
            lines = [
                'MUXOPT --no-pcr-on-video-pid --new-audio-pes --demux --vbr --vbv-len=500',
            ]
            qm = m2ts_path.replace('"', '\\"')
            for t in rows:
                tid = _svc_cls()._tsmuxer_mpeg_pid(t)
                if tid is None:
                    continue
                sid = str(t.get('stream_id') or '').strip()
                if not sid:
                    continue
                lang = _svc_cls()._norm_lang_mkv(str(pid_to_lang.get(tid) or 'und'))
                seg = [sid, f'"{qm}"']
                dm = t.get('delay_ms')
                if dm is not None and int(dm) != 0:
                    seg.append(f'timeshift={int(dm)}ms')
                if sid.upper().startswith('S_') or 'PGS' in sid.upper():
                    fps = str(t.get('fps') or fps_default or '23.976').strip() or '23.976'
                    seg.append(f'fps={fps}')
                seg.append(f'track={tid}')
                seg.append(f'lang={lang}')
                lines.append(', '.join(seg))
            with open(out_meta_path, 'w', encoding='utf-8', newline='\n') as fp:
                fp.write('\n'.join(lines) + '\n')
            return True
        except Exception:
            return False

    @staticmethod
    def _collect_tsmuxer_demux_files(demux_dir: str, stem_hint: str) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        try:
            for fn in os.listdir(demux_dir):
                if fn.lower().endswith('.meta'):
                    continue
                m = re.search(r'\.track_(\d+)_', fn, re.I)
                if not m:
                    m = re.search(r'\.track_(\d+)\.', fn, re.I)
                if not m:
                    continue
                pid = int(m.group(1))
                out.append((pid, os.path.join(demux_dir, fn)))
        except Exception:
            return []
        out.sort(key=lambda x: x[0])
        return out




    @staticmethod
    def _tsmuxer_demux_audio_use_track0_after_identify(media_path: str, slot_type: str) -> bool:
        """Return whether a demuxed audio input must be restricted to track 0.

        tsMuxer may place TrueHD and its AC-3 core in one demuxed file. mkvmerge then sees two audio
        tracks in that single input, although the fallback slot represents one transport PID. Raw AC-3
        and PCM files are already single-track; other audio files are identified and restricted with
        ``-a 0`` only when mkvmerge reports more than one audio track.
        """
        normalized_slot_type = str(slot_type or '')
        if normalized_slot_type and normalized_slot_type != 'audio':
            return False
        if not media_path or not os.path.isfile(media_path):
            return False
        if not normalized_slot_type:
            lowercase_name = os.path.basename(media_path).lower()
            if lowercase_name.endswith(('.hevc', '.h264', '.264', '.sup', '.sub', '.jpg', '.png')):
                return False
        basename = os.path.basename(media_path).lower()
        if basename.endswith('.pcm') or (basename.endswith('.ac3') and '+' not in basename):
            return False
        identification = _svc_cls()._mkvmerge_identify_json(media_path)
        return sum(
            isinstance(track, dict) and str(track.get('type') or '').strip().lower() == 'audio'
            for track in identification.get('tracks') or []
        ) > 1

    @staticmethod
    def _mkvmerge_identify_tid_for_pid_file(media_path: str, pid: int) -> Optional[int]:
        """Return the mkvmerge track ID whose MPEG transport PID equals ``pid``."""
        identification = _svc_cls()._mkvmerge_identify_json(media_path)
        for track in identification.get('tracks') or []:
            if not isinstance(track, dict):
                continue
            properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
            stream_pid = _svc_cls()._int_from_mkvmerge_prop(properties.get('stream_id'))
            if stream_pid is None:
                stream_pid = _svc_cls()._int_from_mkvmerge_prop(properties.get('number'))
            if stream_pid != pid:
                continue
            try:
                return int(track.get('id'))
            except Exception:
                return None
        return None

    @staticmethod
    def _tsmuxer_mpeg_pid(track: dict[str, object]) -> Optional[int]:
        """Return the MPEG transport PID represented by one tsMuxer probe track."""
        try:
            track_id = int(track.get('track_id'))
        except Exception:
            track_id = None
        if track_id is not None and track_id >= 0x20:
            return track_id
        stream_id = str(track.get('stream_id') or '')
        pid_match = re.search(r'(?:^|[^0-9])(\d{3,5})(?:[^0-9]|$)', stream_id)
        if pid_match:
            try:
                return int(pid_match.group(1))
            except Exception:
                pass
        return track_id

    @staticmethod
    def _remux_fallback_run_tsmuxer_demux_subset(
            m2ts_path: str,
            work_dir: str,
            part_tag: str,
            pid_to_lang: dict[int, str],
            requested_pids: set[int],
            tsmuxer_tracks: list[dict[str, object]],
            *,
            path_tag: Optional[str] = None,
    ) -> Optional[dict[int, str]]:
        """Demux exactly ``requested_pids`` from one M2TS and return PID-to-file paths.

        Recovery is all-or-nothing: every requested PID must exist in the tsMuxer probe and every
        requested elementary stream must be produced. The caller can therefore merge the returned
        mapping without silently dropping a selected video, audio, or subtitle slot.
        """
        track_by_pid: dict[int, dict[str, object]] = {}
        for track in tsmuxer_tracks:
            pid = _svc_cls()._tsmuxer_mpeg_pid(track)
            if pid is not None and pid in requested_pids:
                track_by_pid[pid] = track
        if set(track_by_pid) != requested_pids:
            return None
        selected_tracks = [track_by_pid[pid] for pid in sorted(requested_pids)]
        frame_rate = next(
            (str(track.get('fps') or '').strip() for track in selected_tracks
             if str(track.get('stream_id') or '').upper().startswith('V_')
             and str(track.get('fps') or '').strip()),
            '23.976',
        )
        artifact_tag = path_tag or part_tag
        meta_path = os.path.join(work_dir, f'{artifact_tag}_tsmux.meta')
        if not _svc_cls()._write_tsmuxer_demux_meta(
                m2ts_path, selected_tracks, pid_to_lang, meta_path, frame_rate):
            return None
        try:
            with open(meta_path, 'r', encoding='utf-8', errors='replace') as meta_file:
                meta_text = meta_file.read()
            print(f'[remux-fallback] tsMuxer meta ({meta_path}):')
            print(meta_text.rstrip('\r\n') + '\n')
        except Exception as error:
            print(f'[remux-fallback] tsMuxer meta written {meta_path} (read-back failed: {error})')
        demux_dir = os.path.join(work_dir, f'{artifact_tag}_tsmux_out')
        os.makedirs(demux_dir, exist_ok=True)
        tsmuxer_executable = _svc_cls()._tsmuxer_exe()
        if not tsmuxer_executable:
            print('[remux-fallback] tsMuxeR executable not found')
            return None
        command = f'"{tsmuxer_executable}" "{meta_path}" "{demux_dir}"'
        print(f'[remux-fallback] {command}')
        try:
            return_code = run_command(
                command,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=7200,
            ).returncode
        except Exception:
            return None
        if return_code != 0:
            print(f'[remux-fallback] tsMuxer demux failed rc={return_code}')
            return None
        clip_stem = os.path.splitext(os.path.basename(m2ts_path))[0]
        demux_files = _svc_cls()._collect_tsmuxer_demux_files(demux_dir, clip_stem)
        demux_by_pid = {pid: demux_path for pid, demux_path in demux_files if pid in requested_pids}
        if set(demux_by_pid) != requested_pids:
            print('[remux-fallback] tsMuxer demux did not yield all requested PIDs')
            return None
        return demux_by_pid

    @staticmethod
    def _remux_fallback_promote_merge_to_part_out(part_out: str, merged_path: str) -> bool:
        """Replace the task-owned part output only after the merged replacement exists."""
        part_path = os.path.normpath(part_out)
        replacement_path = os.path.normpath(merged_path)
        if replacement_path == part_path:
            return os.path.isfile(part_path)
        if not os.path.isfile(replacement_path):
            return False
        try:
            if os.path.isfile(part_path):
                os.remove(part_path)
            os.replace(replacement_path, part_path)
        except OSError:
            return False
        return os.path.isfile(part_path)

    @staticmethod
    def _slot_pids_in_order(slots: list[dict[str, object]]) -> list[int]:
        ordered_pids: list[int] = []
        for slot in slots or []:
            try:
                ordered_pids.append(int(slot.get('pid')))
            except Exception:
                continue
        return ordered_pids

    def _remux_fallback_merge_demux_with_base(
            self,
            mkvmerge_executable: str,
            ui_language_argument: str,
            base_mkv: Optional[str],
            base_pid_list: list[int],
            demux_by_pid: dict[int, str],
            pid_to_lang: dict[int, str],
            output_mkv: str,
            split_argument: Optional[str] = None,
            *,
            base_track_by_pid: Optional[dict[int, int]] = None,
            selected_pid_order: list[int],
    ) -> bool:
        """Merge recovered streams into the current clip in the GUI-selected track order.

        ``base_track_by_pid`` maps transport PIDs to track IDs in the current MKV. Every tsMuxer output is a
        separate mkvmerge input whose elementary stream is track 0. ``selected_pid_order`` is the GUI-selected slot
        order captured from the GUI selection; it determines the final ``--track-order`` even when a recovered
        PID belongs before an already muxed track. A PID outside that selection is an error because fallback
        must not restore a track hidden by the MPLS or unselected in the GUI.
        """
        if not demux_by_pid:
            if base_mkv and os.path.isfile(base_mkv):
                try:
                    shutil.copy2(base_mkv, output_mkv)
                    return True
                except Exception:
                    return False
            return False
        base_pids = set(base_pid_list)
        demux_pids = sorted(demux_by_pid)
        all_pids = base_pids | set(demux_pids)
        unexpected_pids = all_pids - set(selected_pid_order)
        if unexpected_pids:
            print(translate_text('Fallback produced tracks outside the GUI selection: {pids}').format(
                pids=', '.join(f'0x{pid:04X}' for pid in sorted(unexpected_pids)),
            ))
            return False
        ordered_pids = [pid for pid in selected_pid_order if pid in all_pids]

        command_parts: list[str] = [f'"{mkvmerge_executable}"']
        if ui_language_argument:
            command_parts.append(ui_language_argument)
        if split_argument:
            command_parts.append(split_argument)
        first_demux_input_index = 0
        if base_mkv and os.path.isfile(base_mkv):
            command_parts.append(f'"{base_mkv}"')
            first_demux_input_index = 1
        demux_input_by_pid: dict[int, int] = {}
        for input_index, pid in enumerate(demux_pids, start=first_demux_input_index):
            elementary_path = demux_by_pid[pid]
            language = _svc_cls()._norm_lang_mkv(str(pid_to_lang.get(pid) or 'und'))
            command_parts.append(f'--language 0:{language}')
            extension = os.path.splitext(elementary_path)[1].lower()
            track_type = {
                '.sup': 'subtitles',
                '.hevc': 'video',
                '.h264': 'video',
                '.264': 'video',
                '.mkv': 'video',
            }.get(extension, 'audio')
            if _svc_cls()._tsmuxer_demux_audio_use_track0_after_identify(elementary_path, track_type):
                command_parts += ['-a', '0']
            command_parts.append(f'"{elementary_path}"')
            demux_input_by_pid[pid] = input_index

        base_track_ids = dict(base_track_by_pid or {})
        if not base_track_ids and base_pids:
            base_track_ids = {pid: track_id for track_id, pid in enumerate(base_pid_list)}
        track_order_parts: list[str] = []
        for pid in ordered_pids:
            if pid in base_pids and base_mkv and os.path.isfile(base_mkv):
                if pid not in base_track_ids:
                    print(f'[remux-fallback] merge: PID 0x{pid:04x} not in base track map')
                    return False
                track_order_parts.append(f'0:{base_track_ids[pid]}')
            else:
                track_order_parts.append(f'{demux_input_by_pid[pid]}:0')
        command_parts.append(f'--track-order {",".join(track_order_parts)}')
        command_parts += ['-o', f'"{output_mkv}"']
        command = ' '.join(command_parts)
        print(f'[remux-fallback] merge-append {command}')
        return self._run_single_command(command) in (0, 1) and os.path.isfile(output_mkv)

    def _remux_fallback_append_silence_pid_order(
            self,
            mkvmerge_executable: str,
            ui_language_argument: str,
            base_mkv: str,
            existing_pids: list[int],
            missing_audio_slots: list[dict[str, object]],
            reference_m2ts: str,
            clip_duration_sec: float,
            work_dir: str,
            part_tag: str,
            pid_to_lang: dict[int, str],
            output_mkv: str,
            *,
            selected_pid_order: list[int],
    ) -> Optional[list[int]]:
        """Append PCM silence for audio PIDs that tsMuxer could not recover.

        The first playlist M2TS supplies sample rate, channel count, and bit depth for each missing PID. Every
        placeholder spans the current clip window. Existing and synthesized tracks are reordered to the captured
        reference slots; non-audio tracks are never synthesized.
        """
        silence_path_by_pid: dict[int, str] = {}
        missing_audio_pids: list[int] = []
        reference_streams = _svc_cls()._m2ts_track_streams(reference_m2ts)
        for slot in missing_audio_slots:
            try:
                pid = int(slot.get('pid'))
            except Exception:
                continue
            template_stream = next(
                (
                    stream
                    for stream in reference_streams
                    if isinstance(stream, dict)
                    and str(stream.get('codec_type') or '') == 'audio'
                    and _svc_cls()._stream_service_id(stream) == pid
                ),
                None,
            )
            if not isinstance(template_stream, dict):
                print(f'[remux-fallback] silence: no template for PID 0x{pid:04x}')
                return None
            silence_path = os.path.join(work_dir, f'{part_tag}_sil_{pid:04x}.mka')
            if not _svc_cls()._create_silence_track_for_audio_slot(
                    template_stream, clip_duration_sec, silence_path
            ):
                print(f'[remux-fallback] silence: ffmpeg failed for PID 0x{pid:04x}')
                return None
            silence_path_by_pid[pid] = silence_path
            missing_audio_pids.append(pid)
        missing_audio_pids.sort()
        existing_pid_set = set(existing_pids)
        output_pid_set = existing_pid_set | set(missing_audio_pids)
        unexpected_pids = output_pid_set - set(selected_pid_order)
        if unexpected_pids:
            print(translate_text('Fallback produced tracks outside the GUI selection: {pids}').format(
                pids=', '.join(f'0x{pid:04X}' for pid in sorted(unexpected_pids)),
            ))
            return None
        output_pids = [pid for pid in selected_pid_order if pid in output_pid_set]

        command_parts: list[str] = [f'"{mkvmerge_executable}"']
        if ui_language_argument:
            command_parts.append(ui_language_argument)
        command_parts.append(f'"{base_mkv}"')
        for pid in missing_audio_pids:
            language = _svc_cls()._norm_lang_mkv(str(pid_to_lang.get(pid) or 'und'))
            command_parts += ['--language', f'0:{language}', f'"{silence_path_by_pid[pid]}"']
        silence_input_by_pid = {
            pid: input_index
            for input_index, pid in enumerate(missing_audio_pids, start=1)
        }
        track_order_parts: list[str] = []
        for pid in output_pids:
            if pid in existing_pid_set:
                track_order_parts.append(f'0:{existing_pids.index(pid)}')
            else:
                track_order_parts.append(f'{silence_input_by_pid[pid]}:0')
        command_parts.append(f'--track-order {",".join(track_order_parts)}')
        command_parts += ['-o', f'"{output_mkv}"']
        command = ' '.join(command_parts)
        print(f'[remux-fallback] silence-merge {command}')
        if self._run_single_command(command) not in (0, 1) or not os.path.isfile(output_mkv):
            return None
        return output_pids

    def _remux_aligned_clip(
            self,
            m2ts_path: str,
            mpls_path: str,
            reference_m2ts: str,
            reference_slots: list[dict[str, object]],
            part_output: str,
            split_argument: str,
            clip_duration_sec: float,
            work_dir: str,
            part_tag: str,
            mkvmerge_executable: str,
            ui_language_argument: str,
    ) -> bool:
        """Remux one playlist clip while preserving the reference transport-stream layout.

        The GUI-visible first-M2TS rows define the selected video indexes and audio/subtitle PIDs. Each
        selected video index is mapped to the corresponding PID on the current clip; tracks hidden by the MPLS
        never enter the fallback. The recovery order is:

        1. Mux every selected PID that mkvmerge can identify directly.
        2. For a selected dual-layer Dolby Vision pair, let tsMuxer extract BL/EL, combine them as profile
           8.1 with dovi_tool, and append the resulting BL.
        3. Recover every missing video or subtitle PID with tsMuxer. These tracks cannot be synthesized, so
           an incomplete probe or demux is a hard failure.
        4. Recover missing audio with tsMuxer; only audio still unavailable may be replaced by layout-matched
           silence derived from the same PID in the first playlist M2TS.

        The clip succeeds only when its final PID set exactly matches the expected set and the requested part
        output exists. No unrelated intermediate MKV may stand in for that output.
        """
        chapter = Chapter(mpls_path)
        chapter.get_pid_to_language()
        pid_to_lang = chapter.pid_to_lang if isinstance(chapter.pid_to_lang, dict) else {}
        dovi_plan = getattr(self, '_dovi_mux_plan', None)
        if not (isinstance(dovi_plan, dict) and dovi_plan.get('active')):
            dovi_plan = _svc_cls().detect_dovi_mux_pair(
                mpls_path,
                m2ts_path,
                getattr(self, 'mux_dolby_vision', True),
            )
            if isinstance(dovi_plan, dict) and dovi_plan.get('active'):
                self._dovi_mux_plan = dovi_plan
                print(
                    f'[dovi] clip Dolby Vision pair BL=0x{int(dovi_plan["bl_pid"]):04X} '
                    f'EL=0x{int(dovi_plan["el_pid"]):04X} '
                    f'mux={"on" if dovi_plan.get("mux_enabled") else "off"}'
                )
        if not (isinstance(dovi_plan, dict) and dovi_plan.get('active')):
            dovi_plan = None
        dovi_mux_video = bool(
            dovi_plan and dovi_plan.get('mux_enabled')
        )
        clip_slots = _svc_cls()._clip_ref_slots_for_m2ts(reference_slots, m2ts_path, dovi_plan)
        if clip_slots is None:
            print(translate_text('Selected video track is missing from playlist clip: {path}').format(path=m2ts_path))
            return False
        m2ts_identification = _svc_cls()._mkvmerge_identify_json(m2ts_path)
        mappable_slots: list[tuple[dict[str, object], int]] = []
        for slot in clip_slots:
            if dovi_mux_video and str(slot.get('type') or '') == 'video':
                continue
            try:
                pid = int(slot.get('pid'))
            except Exception:
                continue
            track_type = str(slot.get('type') or '')
            track_id = _svc_cls()._mkvmerge_tid_for_pid(m2ts_path, pid, track_type)
            if track_id is not None:
                mappable_slots.append((slot, track_id))
        # First mkvmerge writes directly to ``part_output``: later merge/silence steps use other paths
        # (``*_tsmux_merge.mkv`` / ``*_sil_merge.mkv``), so we avoid an extra ``*_mkvmerge.mkv`` file and
        # a redundant copy when no fallback runs.
        step_mkv = part_output
        m2ts_pid_list: list[int] = []
        # This map must describe the current MKV and is rebuilt after every merge that changes track order.
        base_track_by_pid: dict[int, int] = {}
        selected_pid_order = _svc_cls()._slot_pids_in_order(clip_slots)
        current_mkv: Optional[str] = None
        if mappable_slots:
            mapped_track_ids = [int(track_id) for _, track_id in mappable_slots]
            selected_video_ids, selected_audio_ids, selected_subtitle_ids = _svc_cls()._mkvmerge_select_flags_from_mapped(mapped_track_ids, m2ts_identification)
            # Preserve GUI-selected slot order; numeric PID order is not the product contract.
            ordered_mappable_slots = list(mappable_slots)
            for output_track_id, (slot, _track_id) in enumerate(ordered_mappable_slots):
                try:
                    base_track_by_pid[int(slot.get('pid'))] = output_track_id
                except Exception:
                    pass
            track_order_argument = ','.join(f'0:{track_id}' for _, track_id in ordered_mappable_slots)
            command_parts: list[str] = [f'"{mkvmerge_executable}"']
            if ui_language_argument:
                command_parts.append(ui_language_argument)
            if split_argument:
                command_parts.append(split_argument)
            command_parts += [f'--track-order {track_order_argument}', '-o', f'"{step_mkv}"']
            if dovi_mux_video:
                command_parts += ['-D']
            elif selected_video_ids:
                command_parts += ['-d', selected_video_ids]
            if selected_audio_ids:
                command_parts += ['-a', selected_audio_ids]
            if selected_subtitle_ids:
                command_parts += ['-s', selected_subtitle_ids]
            command_parts.append(f'"{m2ts_path}"')
            command = ' '.join(command_parts)
            print(f'[remux-fallback] {command}')
            if self._run_single_command(command) not in (0, 1) or not os.path.isfile(step_mkv):
                print('[remux-fallback] mkvmerge mux from m2ts failed')
                return False
            current_mkv = step_mkv
            m2ts_pid_list = [int(slot.get('pid')) for slot, _ in ordered_mappable_slots]
            print(f'[remux-fallback] m2ts_pid_list(after mkvmerge)={m2ts_pid_list}')
        if dovi_mux_video and dovi_plan:
            try:
                bl_pid = int(dovi_plan['bl_pid'])
                el_pid = int(dovi_plan['el_pid'])
            except Exception:
                return False
            probe_output = _svc_cls()._run_tsmuxer_probe(m2ts_path)
            tsmuxer_tracks = _svc_cls()._parse_tsmuxer_probe_output(probe_output)
            required_dolby_vision_pids = {bl_pid, el_pid}
            probed_pids = {
                transport_pid
                for track in tsmuxer_tracks
                for transport_pid in (_svc_cls()._tsmuxer_mpeg_pid(track),)
                if transport_pid is not None
            }
            if not required_dolby_vision_pids <= probed_pids:
                print(
                    '[remux-fallback] tsMuxer cannot supply Dolby Vision BL/EL PIDs; '
                    f'need={sorted(required_dolby_vision_pids)} probe={sorted(probed_pids)}'
                )
                return False
            print(
                f'[remux-fallback] tsMuxer Dolby Vision demux PIDs: '
                f'0x{bl_pid:04X}, 0x{el_pid:04X}'
            )
            demuxed_paths = self._remux_fallback_run_tsmuxer_demux_subset(
                m2ts_path, work_dir, part_tag, pid_to_lang, required_dolby_vision_pids, tsmuxer_tracks,
            )
            if demuxed_paths is None:
                return False
            base_layer_path = demuxed_paths.get(bl_pid)
            enhancement_layer_path = demuxed_paths.get(el_pid)
            if not base_layer_path or not enhancement_layer_path:
                return False
            try:
                mux_dolby_vision_layers(base_layer_path, enhancement_layer_path)
            except Exception as error:
                print(
                    translate_text('Dolby Vision mux failed: {error}').format(error=error)
                )
                return False
            demuxed_paths = {bl_pid: base_layer_path}

            merged_mkv = os.path.join(work_dir, f'{part_tag}_dovi_merge.mkv')
            dolby_vision_selected_pid_order = [bl_pid] + [
                pid for pid in _svc_cls()._slot_pids_in_order(clip_slots) if pid != bl_pid
            ]
            if not self._remux_fallback_merge_demux_with_base(
                    mkvmerge_executable,
                    ui_language_argument,
                    current_mkv,
                    m2ts_pid_list,
                    demuxed_paths,
                    pid_to_lang,
                    merged_mkv,
                    split_argument=split_argument,
                    base_track_by_pid=base_track_by_pid,
                    selected_pid_order=dolby_vision_selected_pid_order,
            ):
                return False
            if not _svc_cls()._remux_fallback_promote_merge_to_part_out(part_output, merged_mkv):
                return False
            current_mkv = part_output
            current_pid_set = set(m2ts_pid_list) | {bl_pid}
            m2ts_pid_list = [pid for pid in dolby_vision_selected_pid_order if pid in current_pid_set]
            base_track_by_pid = {pid: track_id for track_id, pid in enumerate(m2ts_pid_list)}
            print(f'[remux-fallback] m2ts_pid_list(after dovi_tool)={m2ts_pid_list}')
        expected_pid_set = {int(slot['pid']) for slot in clip_slots}
        if dovi_mux_video and dovi_plan:
            try:
                expected_pid_set.add(int(dovi_plan['bl_pid']))
            except Exception:
                pass
        available_pid_set = set(m2ts_pid_list)
        missing_slots = []
        for slot in clip_slots:
            if dovi_mux_video and str(slot.get('type') or '') == 'video':
                continue
            try:
                pid = int(slot.get('pid'))
            except Exception:
                continue
            if pid not in available_pid_set:
                missing_slots.append(slot)
        missing_non_audio_slots = [slot for slot in missing_slots if str(slot.get('type') or '') != 'audio']
        if isinstance(dovi_plan, dict) and dovi_plan.get('active'):
            skip_pids: set[int] = set()
            try:
                skip_pids.add(int(dovi_plan['el_pid']))
            except Exception:
                pass
            if dovi_plan.get('mux_enabled'):
                try:
                    skip_pids.add(int(dovi_plan['bl_pid']))
                except Exception:
                    pass
            if skip_pids:
                missing_non_audio_slots = [
                    slot for slot in missing_non_audio_slots
                    if int(slot.get('pid') or -1) not in skip_pids
                ]
        if missing_non_audio_slots:
            probe_output = _svc_cls()._run_tsmuxer_probe(m2ts_path)
            tsmuxer_tracks = _svc_cls()._parse_tsmuxer_probe_output(probe_output)
            required_pids = {int(slot['pid']) for slot in missing_non_audio_slots}
            probed_pids = {
                transport_pid
                for track in tsmuxer_tracks
                for transport_pid in (_svc_cls()._tsmuxer_mpeg_pid(track),)
                if transport_pid is not None
            }
            if not required_pids <= probed_pids:
                print(
                    '[remux-fallback] tsMuxer cannot supply all missing non-audio PIDs; '
                    f'need={sorted(required_pids)} probe={sorted(probed_pids)}; abort'
                )
                return False
            print(
                f'[remux-fallback] tsMuxer demux for missing PIDs: '
                f'{", ".join(f"0x{pid:04X}" for pid in sorted(required_pids))}'
            )
            demuxed_paths = self._remux_fallback_run_tsmuxer_demux_subset(
                m2ts_path, work_dir, part_tag, pid_to_lang, required_pids, tsmuxer_tracks,
            )
            if demuxed_paths is None:
                return False
            merged_mkv = os.path.join(work_dir, f'{part_tag}_tsmux_merge.mkv')
            if not self._remux_fallback_merge_demux_with_base(
                    mkvmerge_executable, ui_language_argument, current_mkv, m2ts_pid_list, demuxed_paths, pid_to_lang, merged_mkv,
                    split_argument=split_argument,
                    base_track_by_pid=base_track_by_pid,
                    selected_pid_order=selected_pid_order,
            ):
                return False
            if not _svc_cls()._remux_fallback_promote_merge_to_part_out(part_output, merged_mkv):
                return False
            current_mkv = part_output
            current_pid_set = set(m2ts_pid_list) | required_pids
            m2ts_pid_list = [pid for pid in selected_pid_order if pid in current_pid_set]
            base_track_by_pid = {pid: track_id for track_id, pid in enumerate(m2ts_pid_list)}
            print(f'[remux-fallback] m2ts_pid_list(after tsMuxer)={m2ts_pid_list}')
        available_pid_set = set(m2ts_pid_list)
        missing_audio_slots = [
            slot for slot in clip_slots
            if str(slot.get('type') or '') == 'audio' and int(slot.get('pid')) not in available_pid_set
        ]
        if missing_audio_slots and current_mkv:
            required_audio_pids = {int(slot['pid']) for slot in missing_audio_slots}
            audio_probe_output = _svc_cls()._run_tsmuxer_probe(m2ts_path)
            audio_tsmuxer_tracks = _svc_cls()._parse_tsmuxer_probe_output(audio_probe_output)
            probed_audio_pids = {
                transport_pid
                for track in audio_tsmuxer_tracks
                for transport_pid in (_svc_cls()._tsmuxer_mpeg_pid(track),)
                if transport_pid is not None
            }
            if required_audio_pids <= probed_audio_pids:
                audio_recovery_tag = f'{part_tag}_audrec'
                demuxed_audio_paths = self._remux_fallback_run_tsmuxer_demux_subset(
                    m2ts_path, work_dir, part_tag, pid_to_lang, required_audio_pids, audio_tsmuxer_tracks,
                    path_tag=audio_recovery_tag,
                )
                if demuxed_audio_paths is not None:
                    merged_audio_mkv = os.path.join(work_dir, f'{audio_recovery_tag}_merge.mkv')
                    if self._remux_fallback_merge_demux_with_base(
                            mkvmerge_executable, ui_language_argument, current_mkv, m2ts_pid_list, demuxed_audio_paths, pid_to_lang, merged_audio_mkv,
                            split_argument=split_argument,
                            base_track_by_pid=base_track_by_pid,
                            selected_pid_order=selected_pid_order,
                    ):
                        if not _svc_cls()._remux_fallback_promote_merge_to_part_out(part_output, merged_audio_mkv):
                            return False
                        current_mkv = part_output
                        current_pid_set = set(m2ts_pid_list) | required_audio_pids
                        m2ts_pid_list = [pid for pid in selected_pid_order if pid in current_pid_set]
                        base_track_by_pid = {pid: track_id for track_id, pid in enumerate(m2ts_pid_list)}
                        print(
                            f'[remux-fallback] m2ts_pid_list(after tsMuxer audio recovery)={m2ts_pid_list}'
                        )
                    else:
                        print('[remux-fallback] tsMuxer audio recovery merge failed; may try silence')
                else:
                    print('[remux-fallback] tsMuxer audio demux failed; may try silence')
            else:
                print(
                    f'[remux-fallback] tsMuxer probe missing some audio PIDs {sorted(required_audio_pids)}; '
                    f'will try silence if needed'
                )
        available_pid_set = set(m2ts_pid_list)
        missing_audio_slots = [
            slot for slot in clip_slots
            if str(slot.get('type') or '') == 'audio' and int(slot.get('pid')) not in available_pid_set
        ]
        if missing_audio_slots:
            if not current_mkv:
                print('[remux-fallback] no base MKV to append silence audio')
                return False
            silence_merged_mkv = os.path.join(work_dir, f'{part_tag}_sil_merge.mkv')
            updated_pids = self._remux_fallback_append_silence_pid_order(
                mkvmerge_executable, ui_language_argument, current_mkv, m2ts_pid_list, missing_audio_slots, reference_m2ts,
                clip_duration_sec, work_dir, part_tag, pid_to_lang, silence_merged_mkv,
                selected_pid_order=selected_pid_order,
            )
            if updated_pids is None:
                return False
            current_mkv = silence_merged_mkv
            m2ts_pid_list = updated_pids
            print(f'[remux-fallback] m2ts_pid_list(after silence)={m2ts_pid_list}')
        if not current_mkv or not os.path.isfile(current_mkv):
            print('[remux-fallback] no MKV output')
            return False
        if set(m2ts_pid_list) != expected_pid_set:
            print(
                f'[remux-fallback] PID set mismatch: expected {sorted(expected_pid_set)} got {m2ts_pid_list}'
            )
            return False
        try:
            if os.path.normpath(current_mkv) != os.path.normpath(part_output):
                shutil.copy2(current_mkv, part_output)
        except Exception:
            return False
        if not os.path.isfile(part_output):
            print(f'[remux-fallback] missing part output after mux: {part_output}')
            return False
        return True


    @staticmethod
    def _create_silence_track_for_audio_slot(
            reference_audio_stream: dict[str, object],
            duration_seconds: float,
            output_path: str,
    ) -> bool:
        """Create PCM silence with the reference PID's sample rate, channels, and effective bit depth.

        The original codec is intentionally not reproduced: this placeholder is used only after the selected
        audio PID is absent from the current clip and tsMuxer cannot recover it. The surrounding fallback keeps
        the PID slot and language while this function supplies a continuous timeline of the required length.
        """
        if duration_seconds <= 0.0:
            return False
        try:
            sample_rate = int(float(reference_audio_stream.get('sample_rate') or 48000))
        except Exception:
            sample_rate = 48000
        try:
            channel_count = int(reference_audio_stream.get('channels') or 2)
        except Exception:
            channel_count = 2
        try:
            bit_depth = int(reference_audio_stream.get('bits_per_raw_sample') or 0) or 16
        except Exception:
            bit_depth = 16
        channel_layout = {0: 'mono', 1: 'mono', 2: 'stereo', 6: '5.1', 8: '7.1'}.get(channel_count, 'stereo')
        pcm_codec = 'pcm_s24be' if bit_depth >= 20 else 'pcm_s16be'
        command = [
            FFMPEG_PATH or 'ffmpeg',
            '-y',
            '-f', 'lavfi',
            '-i', f'anullsrc=r={sample_rate}:cl={channel_layout}',
            '-t', f'{max(0.001, duration_seconds):.6f}',
            '-c:a', pcm_codec,
            output_path,
        ]
        try:
            result = run_command(command)
        except Exception:
            return False
        return result.returncode == 0 and os.path.isfile(output_path)

    def _try_remux_mpls_track_aligned(
            self,
            mpls_path: str,
            output_file: str,
            selected_audio_indices: list[str],
            selected_subtitle_indices: list[str],
            cover_path: str,
            cancel_event: Optional[threading.Event] = None,
            *,
            max_play_items: Optional[int] = None,
    ) -> bool:
        """Fallback from direct MPLS input to PID-aligned per-clip remuxing.

        The first play item converts only GUI-visible selected stream indices into required PID slots. For every
        retained play item, ``_remux_aligned_clip`` maps the selected video indices to that clip and requires the
        selected audio/subtitle PIDs. mkvmerge is attempted first; tsMuxer may recover any selected PID that mkvmerge
        cannot expose. Missing video or subtitle is fatal, while missing audio may become layout-matched PCM
        silence only after tsMuxer recovery fails. Each clip is trimmed to its MPLS in/out window, and successful
        parts are concatenated in playlist order with file append mode. Configured languages are applied by the
        caller after the complete fallback succeeds.

        ``max_play_items`` deliberately truncates recognized looping SP menus so repeated menu clips are muxed
        once instead of preserving artificial multi-hour loops.
        """
        try:
            find_mkvtoolnix()
        except Exception:
            pass
        mkvmerge_executable = MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'
        chapter = Chapter(mpls_path)
        playlist_folder = os.path.dirname(os.path.normpath(mpls_path))
        stream_folder = os.path.normpath(os.path.join(playlist_folder, '..', 'STREAM'))
        play_items = list(chapter.in_out_time or [])
        if max_play_items is not None and max_play_items > 0:
            play_items = play_items[:max_play_items]
        if not play_items:
            return False
        looping_sp = _svc_cls()._detect_sp_looping_mpls(mpls_path)
        if looping_sp and max_play_items is not None:
            print(
                f'[remux-fallback] SP looping playlist ({looping_sp.get("kind")}): '
                f'mux first {len(play_items)} play item(s) only'
            )
        reference_clip_name = play_items[0][0]
        reference_m2ts = os.path.join(stream_folder, f'{reference_clip_name}.m2ts')
        if not os.path.isfile(reference_m2ts):
            print(f'[remux-fallback] missing first m2ts: {reference_m2ts}')
            return False
        self._set_dovi_mux_plan_for_mpls(mpls_path)
        dovi_plan = getattr(self, '_dovi_mux_plan', None)
        if not (isinstance(dovi_plan, dict) and dovi_plan.get('active')):
            dovi_plan = None
        reference_slots = _svc_cls()._ordered_track_slots_for_remux(
            reference_m2ts,
            selected_audio_indices,
            selected_subtitle_indices,
            dovi_plan=dovi_plan,
            mpls_path=mpls_path,
        )
        if not reference_slots:
            print('[remux-fallback] no track slots from edit-tracks selection')
            return False
        try:
            ui_language_argument = (mkvtoolnix_ui_language_arg() or '').strip()
        except Exception:
            ui_language_argument = ''
        output_folder = os.path.dirname(os.path.normpath(output_file)) or '.'
        os.makedirs(output_folder, exist_ok=True)
        work_folder = os.path.join(
            output_folder,
            f'_remux_align_{os.getpid()}_{int(time.time() * 1000) & 0xFFFFFF}',
        )
        os.makedirs(work_folder, exist_ok=True)
        part_outputs: list[str] = []
        try:
            for play_item_index, (clip_name, in_time, out_time) in enumerate(play_items):
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                m2ts_path = os.path.join(stream_folder, f'{clip_name}.m2ts')
                if not os.path.isfile(m2ts_path):
                    print(f'[remux-fallback] missing m2ts: {m2ts_path}')
                    return False
                part_output = os.path.join(work_folder, f'part_{play_item_index:03d}.mkv')
                needs_split, clip_start, clip_end = _svc_cls()._m2ts_clip_time_window_sec(
                    m2ts_path, in_time, out_time,
                )
                split_argument = ''
                clip_duration_seconds = max(0.0, (out_time - in_time) / 45000.0)
                if needs_split:
                    start_timecode = get_time_str(clip_start)
                    end_timecode = get_time_str(clip_end)
                    if start_timecode == '0':
                        start_timecode = '00:00:00.000'
                    if end_timecode == '0':
                        end_timecode = '00:00:00.000'
                    split_argument = f'--split parts:{start_timecode}-{end_timecode}'
                    clip_duration_seconds = max(0.0, float(clip_end) - float(clip_start))
                part_tag = f'part_{play_item_index:03d}'
                try:
                    clip_ok = self._remux_aligned_clip(
                        m2ts_path, mpls_path, reference_m2ts, reference_slots, part_output, split_argument,
                        clip_duration_seconds, work_folder, part_tag, mkvmerge_executable, ui_language_argument,
                    )
                finally:
                    shutil.rmtree(os.path.join(work_folder, f'{part_tag}_tsmux_out'), ignore_errors=True)
                    shutil.rmtree(os.path.join(work_folder, f'{part_tag}_audrec_tsmux_out'), ignore_errors=True)
                if not clip_ok:
                    return False
                if not os.path.isfile(part_output):
                    print(f'[remux-fallback] missing part output after mux: {part_output}')
                    return False
                part_outputs.append(part_output)
            if not part_outputs:
                return False
            if cancel_event and cancel_event.is_set():
                raise TaskCancelled()
            if len(part_outputs) == 1:
                os.replace(part_outputs[0], output_file)
                return os.path.isfile(output_file)

            command = [mkvmerge_executable]
            if ui_language_argument:
                command.extend(ui_language_argument.split())
            command.extend(['--append-mode', 'file', '-o', output_file, part_outputs[0]])
            for part_output in part_outputs[1:]:
                command.extend(['+', part_output])
            if cover_path and os.path.isfile(cover_path):
                command.extend(['--attachment-name', 'Cover.jpg', '--attach-file', cover_path])
            print(f'[remux-fallback] concat: {subprocess.list2cmdline(command)}')
            result = run_command(command)
            if result.returncode not in (0, 1):
                print(f'[remux-fallback] concat failed rc={result.returncode}')
                return False
            return os.path.isfile(output_file)
        except TaskCancelled:
            raise
        except Exception:
            print_exc_terminal()
            return False
        finally:
            shutil.rmtree(work_folder, ignore_errors=True)

    def _try_remux_mpls_split_outputs_track_aligned(
            self,
            mpls_path: str,
            output_file: str,
            episode_configurations: list[dict[str, int | str]],
            selected_audio_indices: list[str],
            selected_subtitle_indices: list[str],
            cover_path: str,
            cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        """Create multiple PID-aligned episode outputs after direct MPLS splitting fails.

        Episode chapter bounds are converted to half-open MPLS timeline windows. The playlist is then scanned in
        order while tracking each play item's cumulative offset. Every overlap is projected onto that M2TS file's
        effective in/out window, remuxed through ``_remux_aligned_clip``, and concatenated into the corresponding
        episode output. Track completion follows the same rules as the single-output fallback: tsMuxer may recover
        selected PIDs, non-audio gaps fail, and only unrecoverable audio may receive PCM silence. Each requested
        part and final episode path must exist exactly; similarly named intermediate files are never substituted.
        """
        normalized_output = os.path.normpath(output_file) if output_file else ''
        if not normalized_output or getattr(self, 'movie_mode', False):
            print('[remux-fallback-split] skip: empty output path or movie_mode')
            return False
        try:
            find_mkvtoolnix()
        except Exception:
            pass
        mkvmerge_executable = MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'
        chapter = Chapter(mpls_path)
        episode_bounds = _svc_cls()._series_episode_segments_bounds(chapter, episode_configurations)
        expected_outputs = _svc_cls()._expected_mkvmerge_split_output_paths(normalized_output, len(episode_bounds))
        if len(episode_bounds) <= 1 or len(expected_outputs) != len(episode_bounds):
            print(
                f'[remux-fallback-split] skip: need 2+ episode segments; '
                f'segments={len(episode_bounds)} expected_files={len(expected_outputs)}'
            )
            return False
        playlist_folder = os.path.dirname(os.path.normpath(mpls_path))
        stream_folder = os.path.normpath(os.path.join(playlist_folder, '..', 'STREAM'))
        play_items = list(chapter.in_out_time or [])
        if len(play_items) < 2:
            print(f'[remux-fallback-split] skip: playlist has only {len(play_items)} clip(s)')
            return False
        reference_clip_name = play_items[0][0]
        reference_m2ts = os.path.join(stream_folder, f'{reference_clip_name}.m2ts')
        if not os.path.isfile(reference_m2ts):
            print(f'[remux-fallback-split] missing first m2ts: {reference_m2ts}')
            return False
        self._set_dovi_mux_plan_for_mpls(mpls_path)
        dovi_plan = getattr(self, '_dovi_mux_plan', None)
        if not (isinstance(dovi_plan, dict) and dovi_plan.get('active')):
            dovi_plan = None
        reference_slots = _svc_cls()._ordered_track_slots_for_remux(
            reference_m2ts,
            selected_audio_indices,
            selected_subtitle_indices,
            dovi_plan=dovi_plan,
            mpls_path=mpls_path,
        )
        if not reference_slots:
            print('[remux-fallback-split] no track slots from edit-tracks selection')
            return False
        try:
            ui_language_argument = (mkvtoolnix_ui_language_arg() or '').strip()
        except Exception:
            ui_language_argument = ''
        output_folder = os.path.dirname(normalized_output) or '.'
        os.makedirs(output_folder, exist_ok=True)
        work_folder = os.path.join(
            output_folder,
            f'_remux_split_align_{os.getpid()}_{int(time.time() * 1000) & 0xFFFFFF}',
        )
        os.makedirs(work_folder, exist_ok=True)
        chapter_count = sum(map(len, chapter.mark_info.values()))
        exclusive_playlist_end = chapter_count + 1
        _, index_to_offset = get_index_to_m2ts_and_offset(chapter)
        tolerance_seconds = 1e-5
        try:
            print(
                f'[remux-fallback-split] start: {len(episode_bounds)} episodes -> '
                f'{", ".join(os.path.basename(path) for path in expected_outputs)}'
            )
            try:
                self._progress(text=f'Multi-episode split fallback: {len(episode_bounds)} MKV...')
            except Exception:
                pass
            for episode_index, ((start_chapter, end_chapter), episode_output) in enumerate(
                    zip(episode_bounds, expected_outputs)
            ):
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                episode_start = (
                    chapter.get_total_time()
                    if start_chapter >= exclusive_playlist_end
                    else float(index_to_offset.get(start_chapter, 0.0))
                )
                episode_end = (
                    chapter.get_total_time()
                    if end_chapter >= exclusive_playlist_end
                    else float(index_to_offset.get(end_chapter, 0.0))
                )
                clip_outputs: list[str] = []
                playlist_offset = 0.0
                for clip_index, (clip_name, in_time, out_time) in enumerate(play_items):
                    if cancel_event and cancel_event.is_set():
                        raise TaskCancelled()
                    clip_start_on_playlist = playlist_offset
                    clip_duration = max(0.0, (out_time - in_time) / 45000.0)
                    overlap_start = max(episode_start, clip_start_on_playlist)
                    overlap_end = min(episode_end, clip_start_on_playlist + clip_duration)
                    playlist_offset = clip_start_on_playlist + clip_duration
                    if clip_duration <= tolerance_seconds or overlap_start + tolerance_seconds >= overlap_end:
                        continue
                    m2ts_path = os.path.join(stream_folder, f'{clip_name}.m2ts')
                    if not os.path.isfile(m2ts_path):
                        print(f'[remux-fallback-split] missing m2ts: {m2ts_path}')
                        return False
                    needs_clip_split, source_window_start, source_window_end = _svc_cls()._m2ts_clip_time_window_sec(
                        m2ts_path, in_time, out_time,
                    )
                    effective_start = 0.0 if not needs_clip_split else float(source_window_start)
                    effective_end = float(source_window_end)
                    effective_duration = max(0.0, effective_end - effective_start)
                    if effective_duration <= tolerance_seconds:
                        continue
                    overlap_start_ratio = min(
                        1.0,
                        max(0.0, (overlap_start - clip_start_on_playlist) / clip_duration),
                    )
                    overlap_end_ratio = min(
                        1.0,
                        max(0.0, (overlap_end - clip_start_on_playlist) / clip_duration),
                    )
                    if overlap_end_ratio <= overlap_start_ratio + tolerance_seconds / max(
                            clip_duration, tolerance_seconds
                    ):
                        continue
                    slice_start = effective_start + overlap_start_ratio * effective_duration
                    slice_end = effective_start + overlap_end_ratio * effective_duration
                    if slice_end <= slice_start + tolerance_seconds:
                        continue
                    full_window = (
                        slice_start <= effective_start + tolerance_seconds
                        and slice_end >= effective_end - tolerance_seconds
                    )
                    split_argument = ''
                    if not (full_window and not needs_clip_split):
                        split_start = source_window_start if full_window else slice_start
                        split_end = source_window_end if full_window else slice_end
                        start_timecode = get_time_str(split_start)
                        end_timecode = get_time_str(split_end)
                        if start_timecode == '0':
                            start_timecode = '00:00:00.000'
                        if end_timecode == '0':
                            end_timecode = '00:00:00.000'
                        split_argument = f'--split parts:{start_timecode}-{end_timecode}'
                    clip_duration_seconds = max(0.0, slice_end - slice_start)
                    part_output = os.path.join(work_folder, f'ep{episode_index:03d}_c{clip_index:03d}.mkv')
                    part_tag = f'ep{episode_index:03d}_c{clip_index:03d}'
                    try:
                        clip_ok = self._remux_aligned_clip(
                            m2ts_path, mpls_path, reference_m2ts, reference_slots, part_output, split_argument,
                            clip_duration_seconds, work_folder, part_tag, mkvmerge_executable, ui_language_argument,
                        )
                    finally:
                        shutil.rmtree(os.path.join(work_folder, f'{part_tag}_tsmux_out'), ignore_errors=True)
                        shutil.rmtree(os.path.join(work_folder, f'{part_tag}_audrec_tsmux_out'), ignore_errors=True)
                    if not clip_ok:
                        return False
                    if not os.path.isfile(part_output):
                        print(f'[remux-fallback-split] missing part after mux: {part_output}')
                        return False
                    clip_outputs.append(part_output)
                if not clip_outputs:
                    print(
                        f'[remux-fallback-split] no m2ts pieces for segment {episode_index} '
                        f'(time window {episode_start:.3f}s .. {episode_end:.3f}s)'
                    )
                    return False
                if cancel_event and cancel_event.is_set():
                    raise TaskCancelled()
                cover_argument = ''
                if cover_path and os.path.isfile(cover_path):
                    cover_argument = f'--attachment-name Cover.jpg --attach-file "{cover_path}"'
                command_parts = [f'"{mkvmerge_executable}"']
                if ui_language_argument:
                    command_parts.append(ui_language_argument)
                if len(clip_outputs) == 1:
                    command_parts += ['-o', f'"{episode_output}"', f'"{clip_outputs[0]}"']
                else:
                    command_parts += [
                        '--append-mode', 'file', '-o', f'"{episode_output}"', f'"{clip_outputs[0]}"',
                    ]
                    for clip_output in clip_outputs[1:]:
                        command_parts += ['+', f'"{clip_output}"']
                if cover_argument:
                    command_parts.append(cover_argument)
                command = ' '.join(command_parts)
                print(f'[remux-fallback-split] segment {episode_index + 1}: {command}')
                return_code = self._run_single_command(command)
                if return_code not in (0, 1):
                    print(
                        f'[remux-fallback-split] segment concat failed '
                        f'rc={return_code} seg={episode_index}'
                    )
                    return False
                if not os.path.isfile(episode_output):
                    print(f'[remux-fallback-split] missing output: {episode_output}')
                    return False
            return all(os.path.isfile(path) for path in expected_outputs)
        except TaskCancelled:
            raise
        except Exception:
            print_exc_terminal()
            return False
        finally:
            shutil.rmtree(work_folder, ignore_errors=True)

    def _select_tracks_for_source(
            self,
            source_path: str,
            pid_to_lang: Optional[dict[int, str]] = None,
            config_key: Optional[str] = None
    ) -> tuple[list[str], list[str]]:
        tracks_cfg = getattr(self, 'track_selection_config', {}) or {}
        if config_key and isinstance(tracks_cfg, dict) and config_key in tracks_cfg:
            cfg = tracks_cfg.get(config_key) or {}
            return list(cfg.get('audio') or []), list(cfg.get('subtitle') or [])
        probe_path = source_path
        if str(source_path).lower().endswith('.mpls') and os.path.exists(source_path):
            probe_m2ts, _ = _svc_cls()._probe_m2ts_for_remux_source(source_path)
            if probe_m2ts and os.path.isfile(probe_m2ts):
                probe_path = probe_m2ts
        if str(probe_path).lower().endswith('.m2ts'):
            streams = self._read_m2ts_track_info(probe_path)
        else:
            streams = _svc_cls()._read_media_streams(probe_path)
        pid_lang = pid_to_lang if isinstance(pid_to_lang, dict) else {}
        if (
                not pid_lang
                and str(probe_path).lower().endswith('.m2ts')
                and os.path.isfile(probe_path)
        ):
            try:
                pid_lang = pid_to_lang_from_m2ts_path(probe_path)
            except Exception:
                pid_lang = {}
        if not pid_lang:
            pid_lang = _svc_cls()._pid_lang_from_media_streams(streams)
        return _svc_cls()._default_track_selection_from_streams(streams, pid_lang)
