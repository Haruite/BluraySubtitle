"""Auto-generated split target: media_info_and_track_mapping."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Optional

import librosa
import numpy as np
import pycountry
import soundfile

from src.bdmv import M2TS, Chapter
from src.core import FDK_AAC_PATH, FFPROBE_PATH, FFMPEG_PATH, FLAC_PATH, FLAC_THREADS, MKV_MERGE_PATH, MKV_PROP_EDIT_PATH, \
    find_mkvtoolinx, get_mkvtoolnix_ui_language, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import get_effective_bit_depth, get_time_str, print_exc_terminal, get_index_to_m2ts_and_offset, \
    fix_audio_delay_to_lossless, get_compressed_effective_depth
from .service_base import BluraySubtitleServiceBase
from ..services.cancelled import _Cancelled

# Per-process caches for SP/detail UI: same STREAM files and MPLS playlists are touched many times.
_M2TS_PTS_DUR_CACHE: dict[str, tuple[Optional[int], Optional[int]]] = {}
_MPLS_PLAY_ROWS_CACHE: dict[str, list] = {}
_MPLS_TIMELINE_DETAIL_CACHE: dict[tuple[str, float, float], str] = {}


def _m2ts_cache_key(path: str) -> str:
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(path)))
    except Exception:
        return os.path.normcase(os.path.normpath(path))


def _m2ts_cached_pts_dur(m2ts_path: str) -> tuple[Optional[int], Optional[int]]:
    key = _m2ts_cache_key(m2ts_path)
    if key in _M2TS_PTS_DUR_CACHE:
        return _M2TS_PTS_DUR_CACHE[key]
    pts: Optional[int] = None
    dur90: Optional[int] = None
    try:
        if m2ts_path and os.path.isfile(m2ts_path):
            m2 = M2TS(m2ts_path)
            pts = m2.get_first_pts(m2ts=True)
            try:
                dur90 = int(m2.get_duration())
            except Exception:
                dur90 = None
    except Exception:
        pts, dur90 = None, None
    _M2TS_PTS_DUR_CACHE[key] = (pts, dur90)
    return pts, dur90


def _mpls_play_rows_cached(mpls_path: str) -> list:
    key = _m2ts_cache_key(mpls_path)
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
        proc = subprocess.run(
            f'"{FFPROBE_PATH}" -v error -select_streams a:0 -show_entries stream=channels '
            f'-of default=noprint_wrappers=1:nokey=1 "{path}"',
            shell=True,
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
            if pid is not None and pid in pid_lang:
                return str(pid_lang.get(pid, 'und') or 'und')
            try:
                idx = int(str(stream_info.get('index') or '').strip())
                if idx in pid_lang:
                    return str(pid_lang.get(idx, 'und') or 'und')
            except Exception:
                pass
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
            p = subprocess.run(
                [exe, "-v", "error", "-show_streams", "-of", "json", media_path],
                capture_output=True,
                text=True,
                shell=False
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
        if not m2ts_path or not os.path.exists(m2ts_path):
            return []
        key = os.path.normpath(m2ts_path)
        try:
            st = os.stat(key)
            sig = (int(st.st_size), int(st.st_mtime_ns))
        except OSError:
            return []
        try:
            with _svc_cls()._m2ts_track_info_cache_lock:
                cached = _svc_cls()._m2ts_track_info_cache.get(key)
                if cached and cached[0] == sig:
                    out_cached = [dict(x) for x in (cached[1] or [])]
                    for r in out_cached:
                        if str(r.get('codec_type') or '') == 'subtitles':
                            r['codec_type'] = 'subtitle'
                    return out_cached
        except Exception:
            pass
        try:
            tracks = M2TS(key).get_track_info()
        except Exception:
            return []
        out: list[dict[str, object]] = []
        for i, t in enumerate(tracks or []):
            if not isinstance(t, dict):
                continue
            row = dict(t)
            try:
                pid = int(row.get('pid'))
            except Exception:
                pid = None
            # Keep M2TS / internal ``subtitle`` (ffprobe JSON may use ``subtitles`` elsewhere).
            row['codec_type'] = str(row.get('codec_type') or '')
            row['index'] = i
            row['id'] = f'0x{pid:04x}' if pid is not None else ''
            out.append(row)
        try:
            with _svc_cls()._m2ts_track_info_cache_lock:
                _svc_cls()._m2ts_track_info_cache[key] = (sig, [dict(x) for x in out])
        except Exception:
            pass
        return out

    @staticmethod
    def _m2ts_duration_90k(m2ts_path: str) -> int:
        key = os.path.normpath(str(m2ts_path or ''))
        if not key:
            return 0
        try:
            st = os.stat(key)
            sig = (int(st.st_size), int(st.st_mtime_ns))
        except Exception:
            return 0
        try:
            with _svc_cls()._m2ts_duration_cache_lock:
                cached = _svc_cls()._m2ts_duration_cache.get(key)
                if cached and cached[0] == sig:
                    return int(cached[1])
        except Exception:
            pass
        try:
            dur90 = int(M2TS(key).get_duration())
        except Exception:
            dur90 = 0
        try:
            with _svc_cls()._m2ts_duration_cache_lock:
                _svc_cls()._m2ts_duration_cache[key] = (sig, int(dur90))
        except Exception:
            pass
        return int(dur90)

    @staticmethod
    def _m2ts_frame_count(m2ts_path: str) -> int:
        key = os.path.normpath(str(m2ts_path or ''))
        if not key:
            return -1
        try:
            st = os.stat(key)
            sig = (int(st.st_size), int(st.st_mtime_ns))
        except Exception:
            return -1
        try:
            with _svc_cls()._m2ts_frame_count_cache_lock:
                cached = _svc_cls()._m2ts_frame_count_cache.get(key)
                if cached and cached[0] == sig:
                    return int(cached[1])
        except Exception:
            pass
        try:
            cnt = int(M2TS(key).get_total_frames())
        except Exception:
            cnt = -1
        try:
            with _svc_cls()._m2ts_frame_count_cache_lock:
                _svc_cls()._m2ts_frame_count_cache[key] = (sig, int(cnt))
        except Exception:
            pass
        return int(cnt)

    @staticmethod
    def _video_frame_count_static(media_path: str) -> int:
        if not media_path or not os.path.exists(media_path):
            return -1
        exe = FFPROBE_PATH if FFPROBE_PATH else 'ffprobe'
        cmd = [exe, "-v", "error", "-count_frames", "-select_streams", "v:0",
               "-show_entries", "stream=nb_read_frames,nb_frames", "-of", "json", media_path]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', shell=False)
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
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if p.returncode == 0 and os.path.exists(dst):
                os.remove(output_file)
        except Exception:
            pass

    @staticmethod
    def _is_silent_audio_file(path: str, threshold_db: float = -60.0) -> tuple[bool, float]:
        y = None
        if soundfile is not None:
            try:
                info = soundfile.info(path)
                frames = min(int(info.frames), int(info.samplerate) * 30)
                start = int(info.frames) // 2 if int(info.frames) > (frames * 2) else 0
                data, sr = soundfile.read(path, start=start, frames=frames, dtype='float32', always_2d=True)
                y = data.mean(axis=1)
            except Exception:
                y = None
        if y is None:
            fd, tmp = tempfile.mkstemp(prefix=f"temp_sil_{os.getpid()}_", suffix=".wav")
            os.close(fd)
            try:
                subprocess.run(
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{path}" -ac 1 -ar 22050 -c:a pcm_s16le "{tmp}"',
                    shell=True,
                    check=True
                )
                if soundfile is None:
                    y, sr = librosa.load(tmp, sr=None, mono=True)
                else:
                    data, sr = soundfile.read(tmp, dtype='float32', always_2d=True)
                    y = data.mean(axis=1)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
        rms = librosa.feature.rms(y=y)
        db = librosa.amplitude_to_db(rms, ref=np.max)
        avg_db = float(np.mean(db))
        return avg_db < threshold_db, avg_db

    @staticmethod
    def _compress_audio_stream_to_flac(input_media: str, map_idx: str, out_flac: str) -> bool:
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
                subprocess.Popen(
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{input_media}" -map 0:{map_idx} -c:a pcm_s24le -f w64 "{tmp_wav}"',
                    shell=True
                ).wait()
                if not os.path.exists(tmp_wav) or os.path.getsize(tmp_wav) <= 0:
                    return False
            try:
                silent, avg_db = _svc_cls()._is_silent_audio_file(tmp_wav, -60.0)
            except Exception:
                silent, avg_db = False, 0.0
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
                subprocess.Popen(
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{tmp_wav}" -c:a pcm_s16le "{tmp_wav2}"',
                    shell=True
                ).wait()
                if os.path.exists(tmp_wav2) and os.path.getsize(tmp_wav2) > 0:
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
                    subprocess.Popen(f'"{FLAC_PATH}" -8 -j {FLAC_THREADS} "{tmp_wav}" -o "{out_flac}"',
                                     shell=True).wait()
                    ok = os.path.exists(out_flac) and os.path.getsize(out_flac) > 0
                except Exception:
                    ok = False
            if not ok:
                try:
                    subprocess.Popen(
                        f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{tmp_wav}" -c:a flac "{out_flac}"',
                        shell=True
                    ).wait()
                    ok = os.path.exists(out_flac) and os.path.getsize(out_flac) > 0
                except Exception:
                    ok = False
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
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
        try:
            p = subprocess.run(
                [exe, "--identify", "--identification-format", "json", media_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                shell=False
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
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_MERGE_PATH if MKV_MERGE_PATH else 'mkvmerge'
        try:
            p = subprocess.run(
                [exe, "--identify", "--identification-format", "json", media_path],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                shell=False
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
        try:
            ch = Chapter(mpls_path)
            idx_to_m2ts, _ = get_index_to_m2ts_and_offset(ch)
            if not idx_to_m2ts:
                return list(selected_audio_track_indexes or []), list(selected_sub_track_indexes or [])
            first_key = sorted(idx_to_m2ts.keys())[0]
            playlist_dir = os.path.dirname(mpls_path)
            stream_dir = os.path.join(os.path.dirname(playlist_dir), 'STREAM')
            first_m2ts = os.path.join(stream_dir, idx_to_m2ts[first_key])
            if not os.path.isfile(first_m2ts):
                return list(selected_audio_track_indexes or []), list(selected_sub_track_indexes or [])
        except Exception:
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
            pid_to_lang: dict[int, str],
            selected_audio_ids: list[str],
            selected_sub_ids: list[str],
            override_lang_by_source_index: Optional[dict[str, str]] = None,
    ):
        """
        Post-mux language rewriting is disabled.

        mkvmerge already sets languages from stream metadata; MPLS ``pid_to_lang`` is incomplete when a
        playlist omits tracks, and SP/epilogue mux can add tracks whose order no longer matches a single
        MPLS PID map.
        """
        return

    @staticmethod
    def _ordered_track_slots_for_remux(
            m2ts_path: str,
            copy_audio_track: list[str],
            copy_sub_track: list[str],
    ) -> list[dict[str, object]]:
        """
        Build ordered ``{type, pid}`` slots from edit-tracks / remux selections (stream indices).

        Order: video (first video stream in file), then each selected audio index, then each selected
        subtitle index. ``m2ts_path`` is only the file used to map stream ``index`` → TS PID; it is not
        what defines the selection (that is ``copy_*`` from edit-tracks / remux cmd).
        """
        streams = [s for s in _svc_cls()._m2ts_track_streams(m2ts_path) if isinstance(s, dict)]
        out: list[dict[str, object]] = []
        for s in streams:
            if str(s.get('codec_type') or '') != 'video':
                continue
            pid = _svc_cls()._stream_service_id(s)
            if pid is not None:
                out.append({'type': 'video', 'pid': pid})
            break
        for aid in copy_audio_track or []:
            try:
                want_idx = int(str(aid).strip())
            except Exception:
                continue
            for s in streams:
                if str(s.get('codec_type') or '') != 'audio':
                    continue
                try:
                    if int(s.get('index')) != want_idx:
                        continue
                except Exception:
                    continue
                pid = _svc_cls()._stream_service_id(s)
                if pid is not None:
                    out.append({'type': 'audio', 'pid': pid})
                break
        for sid in copy_sub_track or []:
            try:
                want_idx = int(str(sid).strip())
            except Exception:
                continue
            for s in streams:
                if str(s.get('codec_type') or '') not in ('subtitle', 'subtitles'):
                    continue
                try:
                    if int(s.get('index')) != want_idx:
                        continue
                except Exception:
                    continue
                pid = _svc_cls()._stream_service_id(s)
                if pid is not None:
                    out.append({'type': 'subtitles', 'pid': pid})
                break
        return out

    @staticmethod
    def _mkvmerge_tid_for_pid(m2ts_path: str, pid: int, slot_type: str) -> Optional[int]:
        """
        mkvmerge ``tracks[].id`` for ``m2ts_path`` where PID and codec role match.

        **Video** uses **only** ``mkvmerge --identify`` (no fallback to ``M2TS.get_track_info()`` indices).
        When mkvmerge does not expose a video track (common on some HEVC m2ts), this returns ``None`` so
        callers can switch to the tsMuxer demux path.

        PID ↔ track id: match ``properties.stream_id`` to the MPEG PID only (do not use ``number``, which
        is not always the PID). If no ``stream_id`` match, align **ffprobe streams of that type in order**
        to **mkvmerge tracks of that type in order** — never use ffprobe's global ``index`` as mkvmerge id.
        """
        want = ''
        if slot_type == 'video':
            want = 'video'
        elif slot_type == 'audio':
            want = 'audio'
        elif slot_type == 'subtitles':
            want = 'subtitles'
        else:
            return None
        ident = _svc_cls()._mkvmerge_identify_json(m2ts_path)
        for t in ident.get('tracks') or []:
            if not isinstance(t, dict):
                continue
            if str(t.get('type') or '').strip().lower() != want:
                continue
            props = t.get('properties') if isinstance(t.get('properties'), dict) else {}
            spid = _svc_cls()._int_from_mkvmerge_prop(props.get('stream_id'))
            if spid is None or spid != pid:
                continue
            try:
                return int(t.get('id'))
            except Exception:
                return None
        if slot_type == 'video':
            return None
        streams = [s for s in _svc_cls()._m2ts_track_streams(m2ts_path) if isinstance(s, dict)]
        if slot_type == 'audio':
            type_streams = [s for s in streams if str(s.get('codec_type') or '') == 'audio']
        else:
            type_streams = [s for s in streams if str(s.get('codec_type') or '') in ('subtitle', 'subtitles')]
        k = -1
        for i, s in enumerate(type_streams):
            if _svc_cls()._stream_service_id(s) == pid:
                k = i
                break
        if k < 0:
            return None
        ident_tracks = [t for t in (ident.get('tracks') or []) if isinstance(t, dict)]
        same_type = [t for t in ident_tracks if str(t.get('type') or '').strip().lower() == want]
        if k >= len(same_type):
            return None
        try:
            return int(same_type[k].get('id'))
        except Exception:
            return None

    @staticmethod
    def _map_slots_to_mkvmerge_track_ids(
            ref_slots: list[dict[str, object]],
            m2ts_path: str,
    ) -> Optional[list[int]]:
        """Same slot order as ref_slots; each slot matched by PID on ``m2ts_path``."""
        mapped: list[int] = []
        for slot in ref_slots:
            typ = str(slot.get('type') or '')
            try:
                pid = int(slot.get('pid'))
            except Exception:
                return None
            tid = _svc_cls()._mkvmerge_tid_for_pid(m2ts_path, pid, typ)
            if tid is None:
                return None
            mapped.append(tid)
        return mapped

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
        Lists for ``_try_remux_mpls_track_aligned_concat`` / split fallback.

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
    def _mkvmerge_output_path_from_cmd(cmd: str) -> Optional[str]:
        """First ``-o`` / ``--output`` path when scanning ``remux_cmd`` line by line."""
        for ln in _svc_cls()._remux_cmd_shell_lines(cmd):
            p = _svc_cls()._mkvmerge_output_path_from_line(ln)
            if p:
                return p
        return _svc_cls()._mkvmerge_output_path_from_line(cmd or '')

    @staticmethod
    def _conf_selected_mpls_stem(conf: dict[str, int | str]) -> str:
        raw = str(conf.get('selected_mpls') or '').strip()
        return os.path.splitext(os.path.basename(raw.replace('\\', '/')))[0]

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
                sc = _svc_cls()._conf_selected_mpls_stem(c)
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
            if not os.path.isfile(m2ts_path):
                continue
            need, a, b = MediaInfoTrackMappingMixin._m2ts_clip_time_window_sec(m2ts_path, in_time, out_time)
            slice_start = 0.0 if not need else float(a)
            slice_end = float(b)
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
        ck = (_m2ts_cache_key(mp), round(float(w0), 4), round(float(w1), 4))
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
    def _mkvmerge_track_order_arg(mapped_ids: list[int]) -> str:
        return ','.join(f'0:{tid}' for tid in mapped_ids)

    @staticmethod
    def _mkvmerge_select_flags_from_mapped(mapped_ids: list[int], cur_identify: dict[str, object]) -> tuple[
        str, str, str]:
        """Return (d_flags, a_flags, s_flags) for mkvmerge: enable only mapped ids per type."""
        cur_tracks = [t for t in (cur_identify.get('tracks') or []) if isinstance(t, dict)]
        v_ids = []
        a_ids = []
        s_ids = []
        want = set(int(x) for x in mapped_ids)
        for t in cur_tracks:
            try:
                tid = int(t.get('id'))
            except Exception:
                continue
            if tid not in want:
                continue
            typ = str(t.get('type') or '')
            if typ == 'video':
                v_ids.append(tid)
            elif typ == 'audio':
                a_ids.append(tid)
            elif typ == 'subtitles':
                s_ids.append(tid)
        d_f = ','.join(str(x) for x in v_ids) if v_ids else ''
        a_f = ','.join(str(x) for x in a_ids) if a_ids else ''
        s_f = ','.join(str(x) for x in s_ids) if s_ids else ''
        return d_f, a_f, s_f

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
    def _audio_stream_by_pid(m2ts_path: str, pid: int) -> Optional[dict[str, object]]:
        for s in _svc_cls()._m2ts_track_streams(m2ts_path):
            if not isinstance(s, dict):
                continue
            if str(s.get('codec_type') or '') != 'audio':
                continue
            spid = _svc_cls()._stream_service_id(s)
            if spid == pid:
                return s
        return None

    @staticmethod
    def _tsmuxer_exe() -> str:
        for attr in ('TS_MUXER_PATH', 'TSMUXER_PATH'):
            try:
                p = str(getattr(core_settings, attr, '') or '').strip()
            except Exception:
                p = ''
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
            p = subprocess.run(
                cmd,
                shell=True,
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
    def _ref_slot_pid_set(ref_slots: list[dict[str, object]]) -> set[int]:
        out: set[int] = set()
        for slot in ref_slots or []:
            try:
                out.add(int(slot.get('pid')))
            except Exception:
                continue
        return out

    @staticmethod
    def _tsmuxer_tracks_ordered_for_ref_slots(
            tsmuxer_tracks: list[dict[str, object]],
            ref_slots: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """Probe rows for each ``ref_slots`` PID only, in slot list order (first occurrence per PID)."""
        by_tid: dict[int, dict[str, object]] = {}
        for t in tsmuxer_tracks or []:
            try:
                tid = int(t.get('track_id'))
            except Exception:
                continue
            by_tid[tid] = t
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
                tid = int(t['track_id'])
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
    def _probe_fps_from_tsmuxer_tracks(tracks: list[dict[str, object]]) -> str:
        for t in tracks:
            sid = str(t.get('stream_id') or '')
            if sid.upper().startswith('V_'):
                fps = str(t.get('fps') or '').strip()
                if fps:
                    return fps
        return '23.976'

    @staticmethod
    def _mkvmerge_audio_track_count(media_path: str) -> int:
        """Number of audio tracks mkvmerge reports for ``media_path`` (JSON identify)."""
        ident = _svc_cls()._mkvmerge_identify_json(media_path)
        n = 0
        for t in ident.get('tracks') or []:
            if isinstance(t, dict) and str(t.get('type') or '').strip().lower() == 'audio':
                n += 1
        return n

    @staticmethod
    def _tsmuxer_demux_skip_audio_identify(fpth: str) -> bool:
        """Plain ``.ac3`` / ``.pcm`` elementary files: assume single logical track; no ``--identify``."""
        bn = (os.path.basename(fpth or '') or '').lower()
        if bn.endswith('.pcm'):
            return True
        if bn.endswith('.ac3') and '+' not in bn:
            return True
        return False

    @staticmethod
    def _tsmuxer_demux_audio_use_track0_after_identify(fpth: str, slot_type: str) -> bool:
        """
        tsMuxer demux can yield TrueHD+AC-3 in one file (``*.ac3+thd``, ``*.thd``, …). mkvmerge then
        exposes multiple audio tracks; pass ``-a 0`` before that input to keep only track 0.

        Skips ``--identify`` for ``.ac3`` / ``.pcm`` only; all other audio inputs are probed, and
        ``-a 0`` is added when the reported audio track count is greater than 1.
        """
        st = str(slot_type or '')
        if st and st != 'audio':
            return False
        if not fpth or not os.path.isfile(fpth):
            return False
        if st == '':
            low = os.path.basename(fpth).lower()
            if low.endswith(('.hevc', '.h264', '.264', '.sup', '.sub', '.jpg', '.png')):
                return False
        if _svc_cls()._tsmuxer_demux_skip_audio_identify(fpth):
            return False
        return _svc_cls()._mkvmerge_audio_track_count(fpth) > 1

    @staticmethod
    def _mkvmerge_identify_tid_for_pid_file(media_path: str, pid: int) -> Optional[int]:
        """mkvmerge JSON identify ``tracks[].id`` whose MPEG PID matches ``pid``."""
        ident = _svc_cls()._mkvmerge_identify_json(media_path)
        for t in ident.get('tracks') or []:
            if not isinstance(t, dict):
                continue
            props = t.get('properties') if isinstance(t.get('properties'), dict) else {}
            spid = _svc_cls()._int_from_mkvmerge_prop(props.get('stream_id'))
            if spid is None:
                spid = _svc_cls()._int_from_mkvmerge_prop(props.get('number'))
            if spid != pid:
                continue
            try:
                return int(t.get('id'))
            except Exception:
                return None
        return None

    @staticmethod
    def _remux_fallback_demux_slot_guess(fpth: str) -> str:
        low = (os.path.basename(fpth or '') or '').lower()
        if low.endswith(('.sup',)):
            return 'subtitles'
        if low.endswith(('.hevc', '.h264', '.264', '.mkv')):
            return 'video'
        return 'audio'

    @staticmethod
    def _audio_stream_ok_for_pcm_silence_template(stream: dict[str, object]) -> bool:
        """PCM-based silence template: reject codecs we do not approximate with anullsrc→PCM."""
        c = str(stream.get('codec_name') or '').strip().lower()
        if not c:
            return False
        ok_tokens = (
            'pcm', 'ac3', 'eac3', 'truehd', 'dts', 'aac', 'opus', 'flac', 'mp3', 'atmos',
        )
        return any(tok in c for tok in ok_tokens)

    @staticmethod
    def _remux_fallback_run_tsmuxer_demux_subset(
            m2ts_path: str,
            work_dir: str,
            part_tag: str,
            pid_to_lang: dict[int, str],
            want_pids: set[int],
            tsm_all: list[dict[str, object]],
            *,
            path_tag: Optional[str] = None,
    ) -> Optional[dict[int, str]]:
        rows = []
        for t in tsm_all:
            try:
                tid = int(t.get('track_id'))
            except Exception:
                continue
            if tid in want_pids:
                rows.append(t)
        if len(rows) != len(want_pids):
            return None
        fps = _svc_cls()._probe_fps_from_tsmuxer_tracks(rows)
        fs_tag = path_tag if path_tag else part_tag
        meta_path = os.path.join(work_dir, f'{fs_tag}_tsmux.meta')
        if not _svc_cls()._write_tsmuxer_demux_meta(m2ts_path, rows, pid_to_lang, meta_path, fps):
            return None
        try:
            with open(meta_path, 'r', encoding='utf-8', errors='replace') as fp:
                meta_txt = fp.read()
            print(f'[remux-fallback] tsMuxer meta ({meta_path}):')
            print(meta_txt.rstrip('\r\n') + '\n')
        except Exception as ex:
            print(f'[remux-fallback] tsMuxer meta written {meta_path} (read-back failed: {ex})')
        demux_dir = os.path.join(work_dir, f'{fs_tag}_tsmux_out')
        os.makedirs(demux_dir, exist_ok=True)
        ts_exe = _svc_cls()._tsmuxer_exe()
        if not ts_exe:
            print('[remux-fallback] tsMuxeR executable not found')
            return None
        tcmd = f'"{ts_exe}" "{meta_path}" "{demux_dir}"'
        print(f'[remux-fallback] {tcmd}')
        try:
            rc0 = subprocess.run(tcmd, shell=True, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=7200).returncode
        except Exception:
            return None
        if rc0 != 0:
            print(f'[remux-fallback] tsMuxer demux failed rc={rc0}')
            return None
        stem = os.path.splitext(os.path.basename(m2ts_path))[0]
        files = _svc_cls()._collect_tsmuxer_demux_files(demux_dir, stem)
        out: dict[int, str] = {}
        for pid, fpth in files:
            if pid in want_pids:
                out[pid] = fpth
        if set(out.keys()) != want_pids:
            print('[remux-fallback] tsMuxer demux did not yield all requested PIDs')
            return None
        return out

    def _remux_fallback_merge_demux_with_base(
            self,
            exe: str,
            ui: str,
            base_mkv: Optional[str],
            base_pid_list: list[int],
            demux_by_pid: dict[int, str],
            pid_to_lang: dict[int, str],
            out_mkv: str,
    ) -> bool:
        """Merge ``base_mkv`` (optional) with elementary streams; ``--track-order`` by ascending PID."""
        if not demux_by_pid:
            if base_mkv and os.path.isfile(base_mkv):
                try:
                    shutil.copy2(base_mkv, out_mkv)
                    return True
                except Exception:
                    return False
            return False
        demux_pids_sorted = sorted(demux_by_pid.keys())
        paths = [demux_by_pid[p] for p in demux_pids_sorted]
        base_set = set(base_pid_list)
        all_pids = sorted(base_set | set(demux_pids_sorted))
        bits: list[str] = [f'"{exe}"']
        if ui:
            bits.append(ui)
        start_idx = 0
        if base_mkv and os.path.isfile(base_mkv):
            bits.append(f'"{base_mkv}"')
            start_idx = 1
        for pid, fpth in zip(demux_pids_sorted, paths):
            lang = _svc_cls()._norm_lang_mkv(str(pid_to_lang.get(pid) or 'und'))
            bits.append(f'--language 0:{lang}')
            sg = _svc_cls()._remux_fallback_demux_slot_guess(fpth)
            if _svc_cls()._tsmuxer_demux_audio_use_track0_after_identify(fpth, sg):
                bits += ['-a', '0']
            bits.append(f'"{fpth}"')
        order_parts: list[str] = []
        for pid in all_pids:
            if pid in base_set and base_mkv and os.path.isfile(base_mkv):
                try:
                    idx = base_pid_list.index(pid)
                except ValueError:
                    print(f'[remux-fallback] merge: PID 0x{pid:04x} not in base_pid_list')
                    return False
                order_parts.append(f'0:{idx}')
            else:
                try:
                    ix = demux_pids_sorted.index(pid)
                except ValueError:
                    print(f'[remux-fallback] merge: orphan PID 0x{pid:04x}')
                    return False
                order_parts.append(f'{start_idx + ix}:0')
        bits.append(f'--track-order {",".join(order_parts)}')
        bits += ['-o', f'"{out_mkv}"']
        cmd = ' '.join(bits)
        print(f'[remux-fallback] merge-append {cmd}')
        return self._run_single_command(cmd) == 0 and os.path.isfile(out_mkv)

    def _remux_fallback_append_silence_pid_order(
            self,
            exe: str,
            ui: str,
            base_mkv: str,
            m2ts_pid_list: list[int],
            audio_slots: list[dict[str, object]],
            first_m2ts: str,
            clip_duration_sec: float,
            work_dir: str,
            part_tag: str,
            pid_to_lang: dict[int, str],
            out_mkv: str,
    ) -> Optional[list[int]]:
        """Append PCM silence tracks for missing audio PIDs; output track-order by ascending PID."""
        sil_paths: dict[int, str] = {}
        audio_pids_sorted: list[int] = []
        for slot in audio_slots:
            try:
                pid = int(slot.get('pid'))
            except Exception:
                continue
            tmpl = _svc_cls()._audio_stream_by_pid(first_m2ts, pid)
            if not isinstance(tmpl, dict):
                print(f'[remux-fallback] silence: no template for PID 0x{pid:04x}')
                return None
            if not _svc_cls()._audio_stream_ok_for_pcm_silence_template(tmpl):
                print(
                    f'[remux-fallback] silence: unsupported audio codec for PID 0x{pid:04x} '
                    f'({tmpl.get("codec_name")!r})'
                )
                return None
            sp = os.path.join(work_dir, f'{part_tag}_sil_{pid:04x}.mka')
            if not _svc_cls()._create_silence_track_for_audio_slot(tmpl, clip_duration_sec, sp):
                print(f'[remux-fallback] silence: ffmpeg failed for PID 0x{pid:04x}')
                return None
            sil_paths[pid] = sp
            audio_pids_sorted.append(pid)
        audio_pids_sorted.sort()
        new_pid_union = sorted(set(m2ts_pid_list) | set(audio_pids_sorted))
        bits: list[str] = [f'"{exe}"']
        if ui:
            bits.append(ui)
        bits.append(f'"{base_mkv}"')
        for pid in audio_pids_sorted:
            lang = _svc_cls()._norm_lang_mkv(str(pid_to_lang.get(pid) or 'und'))
            bits += ['--language', f'0:{lang}', f'"{sil_paths[pid]}"']
        order_parts: list[str] = []
        sil_off = {pid: j for j, pid in enumerate(audio_pids_sorted)}
        for pid in new_pid_union:
            if pid in set(m2ts_pid_list):
                try:
                    idx = m2ts_pid_list.index(pid)
                except ValueError:
                    print(f'[remux-fallback] silence-merge: PID 0x{pid:04x} not in m2ts_pid_list')
                    return None
                order_parts.append(f'0:{idx}')
            else:
                order_parts.append(f'{1 + sil_off[pid]}:0')
        bits.append(f'--track-order {",".join(order_parts)}')
        bits += ['-o', f'"{out_mkv}"']
        cmd = ' '.join(bits)
        print(f'[remux-fallback] silence-merge {cmd}')
        if self._run_single_command(cmd) != 0 or not os.path.isfile(out_mkv):
            return None
        return new_pid_union

    def _patch_missing_audio_with_silence(
            self,
            mkv_path: str,
            ref_slots: list[dict[str, object]],
            first_m2ts: str,
            clip_duration_sec: float,
            work_dir: str,
            tag: str,
            exe: str,
            ui: str,
    ) -> bool:
        expected_audio = 0
        for slot in ref_slots or []:
            if str(slot.get('type') or '') != 'audio':
                continue
            try:
                int(slot.get('pid'))
                expected_audio += 1
            except Exception:
                pass
        ident = _svc_cls()._mkvmerge_identify_json(mkv_path)
        cur_tracks = [x for x in (ident.get('tracks') or []) if isinstance(x, dict)]
        n_aud = sum(1 for x in cur_tracks if str(x.get('type') or '') == 'audio')
        if expected_audio <= 0 or n_aud >= expected_audio:
            return True
        need = expected_audio - n_aud
        tmpl = None
        for s in ref_slots:
            if str(s.get('type') or '') != 'audio':
                continue
            tmpl = _svc_cls()._audio_stream_by_pid(first_m2ts, int(s['pid']))
            if isinstance(tmpl, dict):
                break
        if not isinstance(tmpl, dict):
            print('[remux-fallback] silence pad: no reference audio template')
            return False
        extra_paths: list[str] = []
        for j in range(need):
            sp = os.path.join(work_dir, f'{tag}_sil_pad_{j}.mka')
            if not _svc_cls()._create_silence_track_for_audio_slot(tmpl, clip_duration_sec, sp):
                print('[remux-fallback] silence pad: ffmpeg failed')
                return False
            extra_paths.append(sp)
        tmp_out = os.path.join(work_dir, f'{tag}_with_sil.mkv')
        n0 = len(cur_tracks)
        parts_b: list[str] = [f'"{exe}"']
        if ui:
            parts_b.append(ui)
        parts_b.append(f'"{mkv_path}"')
        for ep in extra_paths:
            parts_b += ['--language', '0:und', f'"{ep}"']
        to_parts2 = [f'0:{i}' for i in range(n0)]
        for j in range(len(extra_paths)):
            to_parts2.append(f'{j + 1}:0')
        parts_b += [f'--track-order {",".join(to_parts2)}', '-o', f'"{tmp_out}"']
        cmd2 = ' '.join(parts_b)
        print(f'[remux-fallback] silence-pad {cmd2}')
        if self._run_single_command(cmd2) != 0:
            return False
        try:
            os.replace(tmp_out, mkv_path)
        except Exception:
            try:
                shutil.copy2(tmp_out, mkv_path)
                os.remove(tmp_out)
            except Exception:
                return False
        return True

    def _remux_one_m2ts_clip_or_tsmuxer(
            self,
            m2ts_path: str,
            mpls_path: str,
            first_m2ts: str,
            ref_slots: list[dict[str, object]],
            part_out: str,
            split_arg: str,
            clip_duration_sec: float,
            work_dir: str,
            part_tag: str,
            exe: str,
            ui: str,
    ) -> bool:
        """
        Per-clip remux: ``mkvmerge --identify`` → mux selected PIDs; maintain ``m2ts_pid_list`` (sorted);
        Missing tracks: tsMuxer demux + merge when the probe lists those PIDs (video, subtitles, **or**
        audio). Any audio still missing afterward is filled with PCM silence if templates allow.
        """
        chapter = Chapter(mpls_path)
        chapter.get_pid_to_language()
        pid_to_lang = chapter.pid_to_lang if isinstance(chapter.pid_to_lang, dict) else {}
        ident_m2ts = _svc_cls()._mkvmerge_identify_json(m2ts_path)
        mux_entries: list[tuple[dict[str, object], int]] = []
        for slot in ref_slots:
            try:
                pid = int(slot.get('pid'))
            except Exception:
                continue
            typ = str(slot.get('type') or '')
            tid = _svc_cls()._mkvmerge_tid_for_pid(m2ts_path, pid, typ)
            if tid is not None:
                mux_entries.append((slot, tid))
        # First mkvmerge writes directly to ``part_out``: later merge/silence steps use other paths
        # (``*_tsmux_merge.mkv`` / ``*_sil_merge.mkv``), so we avoid an extra ``*_mkvmerge.mkv`` file and
        # a redundant copy when no fallback runs.
        step_mkv = part_out
        m2ts_pid_list: list[int] = []
        cur_mkv: Optional[str] = None
        if mux_entries:
            mapped_ids = [int(tid) for _, tid in mux_entries]
            d_f, a_f, s_f = _svc_cls()._mkvmerge_select_flags_from_mapped(mapped_ids, ident_m2ts)
            mux_sorted = sorted(mux_entries, key=lambda z: int(z[0].get('pid') or 0))
            to_arg = ','.join(f'0:{tid}' for _, tid in mux_sorted)
            bits: list[str] = [f'"{exe}"']
            if ui:
                bits.append(ui)
            if split_arg:
                bits.append(split_arg)
            bits += [f'--track-order {to_arg}', '-o', f'"{step_mkv}"']
            if d_f:
                bits += ['-d', d_f]
            if a_f:
                bits += ['-a', a_f]
            if s_f:
                bits += ['-s', s_f]
            bits.append(f'"{m2ts_path}"')
            cmd = ' '.join(bits)
            print(f'[remux-fallback] {cmd}')
            if self._run_single_command(cmd) != 0 or not os.path.isfile(step_mkv):
                print('[remux-fallback] mkvmerge mux from m2ts failed')
                return False
            cur_mkv = step_mkv
            m2ts_pid_list = sorted(int(s.get('pid')) for s, _ in mux_entries)
            print(f'[remux-fallback] m2ts_pid_list(after mkvmerge)={m2ts_pid_list}')
        ref_pid_set = _svc_cls()._ref_slot_pid_set(ref_slots)
        have = set(m2ts_pid_list)
        missing_slots = []
        for s in ref_slots:
            try:
                pid = int(s.get('pid'))
            except Exception:
                continue
            if pid not in have:
                missing_slots.append(s)
        missing_na = [s for s in missing_slots if str(s.get('type') or '') != 'audio']
        missing_au = [s for s in missing_slots if str(s.get('type') or '') == 'audio']
        if missing_na:
            probe_txt = _svc_cls()._run_tsmuxer_probe(m2ts_path)
            tsm_tracks = _svc_cls()._parse_tsmuxer_probe_output(probe_txt)
            need_pids = {int(s['pid']) for s in missing_na}
            ts_pids = {int(t['track_id']) for t in tsm_tracks}
            if not need_pids <= ts_pids:
                print('[remux-fallback] tsMuxer cannot supply all missing non-audio PIDs; abort')
                return False
            demux_map = self._remux_fallback_run_tsmuxer_demux_subset(
                m2ts_path, work_dir, part_tag, pid_to_lang, need_pids, tsm_tracks,
            )
            if demux_map is None:
                return False
            merged_mkv = os.path.join(work_dir, f'{part_tag}_tsmux_merge.mkv')
            if not self._remux_fallback_merge_demux_with_base(
                    exe, ui, cur_mkv, m2ts_pid_list, demux_map, pid_to_lang, merged_mkv):
                return False
            cur_mkv = merged_mkv
            m2ts_pid_list = sorted(set(m2ts_pid_list) | need_pids)
            print(f'[remux-fallback] m2ts_pid_list(after tsMuxer)={m2ts_pid_list}')
        have2 = set(m2ts_pid_list)
        missing_au = [
            s for s in ref_slots
            if str(s.get('type') or '') == 'audio' and int(s.get('pid')) not in have2
        ]
        if missing_au and cur_mkv:
            need_au = {int(s['pid']) for s in missing_au}
            probe_au = _svc_cls()._run_tsmuxer_probe(m2ts_path)
            tsm_au = _svc_cls()._parse_tsmuxer_probe_output(probe_au)
            ts_pids_au = {int(t['track_id']) for t in tsm_au}
            if need_au <= ts_pids_au:
                aud_tag = f'{part_tag}_audrec'
                demux_au = self._remux_fallback_run_tsmuxer_demux_subset(
                    m2ts_path, work_dir, part_tag, pid_to_lang, need_au, tsm_au,
                    path_tag=aud_tag,
                )
                if demux_au is not None:
                    merged_au = os.path.join(work_dir, f'{aud_tag}_merge.mkv')
                    if self._remux_fallback_merge_demux_with_base(
                            exe, ui, cur_mkv, m2ts_pid_list, demux_au, pid_to_lang, merged_au):
                        cur_mkv = merged_au
                        m2ts_pid_list = sorted(set(m2ts_pid_list) | need_au)
                        print(
                            f'[remux-fallback] m2ts_pid_list(after tsMuxer audio recovery)={m2ts_pid_list}'
                        )
                    else:
                        print('[remux-fallback] tsMuxer audio recovery merge failed; may try silence')
                else:
                    print('[remux-fallback] tsMuxer audio demux failed; may try silence')
            else:
                print(
                    f'[remux-fallback] tsMuxer probe missing some audio PIDs {sorted(need_au)}; '
                    f'will try silence if needed'
                )
        have3 = set(m2ts_pid_list)
        missing_au = [
            s for s in ref_slots
            if str(s.get('type') or '') == 'audio' and int(s.get('pid')) not in have3
        ]
        if missing_au:
            if not cur_mkv:
                print('[remux-fallback] no base MKV to append silence audio')
                return False
            sil_mkv = os.path.join(work_dir, f'{part_tag}_sil_merge.mkv')
            upd = self._remux_fallback_append_silence_pid_order(
                exe, ui, cur_mkv, m2ts_pid_list, missing_au, first_m2ts,
                clip_duration_sec, work_dir, part_tag, pid_to_lang, sil_mkv,
            )
            if upd is None:
                return False
            cur_mkv = sil_mkv
            m2ts_pid_list = upd
            print(f'[remux-fallback] m2ts_pid_list(after silence)={m2ts_pid_list}')
        if not cur_mkv or not os.path.isfile(cur_mkv):
            print('[remux-fallback] no MKV output')
            return False
        if set(m2ts_pid_list) != ref_pid_set:
            print(
                f'[remux-fallback] PID set mismatch: expected {sorted(ref_pid_set)} got {m2ts_pid_list}'
            )
            return False
        try:
            if os.path.normpath(cur_mkv) != os.path.normpath(part_out):
                shutil.copy2(cur_mkv, part_out)
        except Exception:
            return False
        if not os.path.isfile(part_out):
            prefix = part_tag
            try:
                cands = sorted(
                    os.path.join(work_dir, fn)
                    for fn in os.listdir(work_dir)
                    if fn.startswith(prefix) and fn.lower().endswith('.mkv')
                )
            except Exception:
                cands = []
            if not cands:
                print(f'[remux-fallback] missing part output after mux: {part_out}')
                return False
            try:
                shutil.copy2(cands[0], part_out)
            except Exception:
                print(f'[remux-fallback] missing part output after mux: {part_out}')
                return False
        return True

    @staticmethod
    def _channel_layout_from_count(ch: int) -> str:
        if ch <= 1:
            return 'mono'
        if ch == 2:
            return 'stereo'
        if ch == 6:
            return '5.1'
        if ch == 8:
            return '7.1'
        return 'stereo'

    @staticmethod
    def _build_slot_mux_plan_with_silence(
            ref_slots: list[dict[str, object]],
            m2ts_path: str,
    ) -> Optional[list[dict[str, object]]]:
        """
        Map each slot from edit-tracks selection (``ref_slots``: ``type`` + ``pid``) onto ``m2ts_path``.

        For each PID, find the mkvmerge/stream index on this clip; missing **audio** →
        ``needs_silence=True``; missing **video or subtitle** → ``None``.
        """
        out: list[dict[str, object]] = []
        for slot in ref_slots:
            typ = str(slot.get('type') or '')
            try:
                pid = int(slot.get('pid'))
            except Exception:
                return None
            tid = _svc_cls()._mkvmerge_tid_for_pid(m2ts_path, pid, typ)
            if tid is None:
                if typ == 'audio':
                    out.append({'type': typ, 'pid': pid, 'tid': None, 'needs_silence': True})
                    continue
                return None
            out.append({'type': typ, 'pid': pid, 'tid': tid, 'needs_silence': False})
        return out

    @staticmethod
    def _create_silence_track_for_audio_slot(
            ref_audio_stream: dict[str, object],
            duration_sec: float,
            out_path: str,
    ) -> bool:
        if duration_sec <= 0.0:
            return False
        try:
            sr = int(float(ref_audio_stream.get('sample_rate') or 48000))
        except Exception:
            sr = 48000
        try:
            ch = int(ref_audio_stream.get('channels') or 2)
        except Exception:
            ch = 2
        try:
            bits = int(ref_audio_stream.get('bits_per_raw_sample') or 0)
            if bits <= 0:
                bits = 16
        except Exception:
            bits = 16
        layout = _svc_cls()._channel_layout_from_count(ch)
        if bits >= 24:
            acodec = 'pcm_s24be'
        elif bits >= 20:
            acodec = 'pcm_s24be'
        else:
            acodec = 'pcm_s16be'
        ff = FFMPEG_PATH if FFMPEG_PATH else 'ffmpeg'
        cmd = (
            f'"{ff}" -y -f lavfi -i "anullsrc=r={sr}:cl={layout}" '
            f'-t {max(0.001, duration_sec):.6f} -c:a {acodec} "{out_path}"'
        )
        try:
            rc = subprocess.Popen(cmd, shell=True).wait()
        except Exception:
            return False
        return rc == 0 and os.path.isfile(out_path)

    def _try_remux_mpls_track_aligned_concat(
            self,
            mpls_path: str,
            output_file: str,
            copy_audio_track: list[str],
            copy_sub_track: list[str],
            cover: str,
            cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        """
        Fallback when direct ``mkvmerge … mpls`` fails (e.g. different track counts across m2ts).
        Slots come from edit-tracks / remux selection via ``_ordered_track_slots_for_remux`` (indices → PID
        using the playlist's first clip m2ts only as the lookup file). Each playlist clip is muxed with those
        PIDs aligned; ``--split parts`` per clip as needed, ``--track-order``, then ``+`` concat with
        ``--append-mode track``. Track languages are left as written by mkvmerge (no post-mux lang rewrite).
        """
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'
        chapter = Chapter(mpls_path)
        chapter.get_pid_to_language()
        playlist_dir = os.path.dirname(os.path.normpath(mpls_path))
        stream_dir = os.path.normpath(os.path.join(playlist_dir, '..', 'STREAM'))
        rows = list(chapter.in_out_time or [])
        if len(rows) < 2:
            return False
        first_name, _it0, _ot0 = rows[0]
        first_m2ts = os.path.join(stream_dir, f'{first_name}.m2ts')
        if not os.path.isfile(first_m2ts):
            print(f'[remux-fallback] missing first m2ts: {first_m2ts}')
            return False
        ref_slots = _svc_cls()._ordered_track_slots_for_remux(
            first_m2ts, copy_audio_track, copy_sub_track
        )
        if not ref_slots:
            print('[remux-fallback] no track slots from edit-tracks selection')
            return False
        ui = ''
        try:
            ui = (mkvtoolnix_ui_language_arg() or '').strip()
        except Exception:
            pass
        out_dir = os.path.dirname(os.path.normpath(output_file)) or '.'
        os.makedirs(out_dir, exist_ok=True)
        part_dir = os.path.join(out_dir, f'_remux_align_{os.getpid()}_{int(time.time() * 1000) & 0xFFFFFF}')
        os.makedirs(part_dir, exist_ok=True)
        parts: list[str] = []
        try:
            for idx, (fname, in_time, out_time) in enumerate(rows):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                m2ts_path = os.path.join(stream_dir, f'{fname}.m2ts')
                if not os.path.isfile(m2ts_path):
                    print(f'[remux-fallback] missing m2ts: {m2ts_path}')
                    return False
                part_out = os.path.join(part_dir, f'part_{idx:03d}.mkv')
                needs_split, t0, t1 = _svc_cls()._m2ts_clip_time_window_sec(m2ts_path, in_time, out_time)
                split_arg = ''
                clip_duration_sec = max(0.0, (out_time - in_time) / 45000.0)
                if needs_split:
                    st = get_time_str(t0)
                    ed = get_time_str(t1)
                    if st == '0':
                        st = '00:00:00.000'
                    if ed == '0':
                        ed = '00:00:00.000'
                    split_arg = f'--split parts:{st}-{ed}'
                    clip_duration_sec = max(0.0, float(t1) - float(t0))
                if not self._remux_one_m2ts_clip_or_tsmuxer(
                        m2ts_path,
                        mpls_path,
                        first_m2ts,
                        ref_slots,
                        part_out,
                        split_arg,
                        clip_duration_sec,
                        part_dir,
                        f'part_{idx:03d}',
                        exe,
                        ui,
                ):
                    return False
                actual_part = part_out
                if not os.path.isfile(actual_part):
                    prefix = f'part_{idx:03d}'
                    try:
                        cands = sorted(
                            os.path.join(part_dir, fn)
                            for fn in os.listdir(part_dir)
                            if fn.startswith(prefix) and fn.lower().endswith('.mkv')
                        )
                    except Exception:
                        cands = []
                    if not cands:
                        print(f'[remux-fallback] missing part output after mux: {part_out}')
                        return False
                    actual_part = cands[0]
                parts.append(actual_part)
            if not parts:
                return False
            if cancel_event and cancel_event.is_set():
                raise _Cancelled()
            cover_arg = ''
            if cover and os.path.isfile(cover):
                cover_arg = f'--attachment-name Cover.jpg --attach-file "{cover}"'
            concat_bits: list[str] = [f'"{exe}"']
            if ui:
                concat_bits.append(ui)
            concat_bits += ['--append-mode', 'track', '-o', f'"{output_file}"', f'"{parts[0]}"']
            for p in parts[1:]:
                concat_bits.append('+')
                concat_bits.append(f'"{p}"')
            if cover_arg:
                concat_bits.append(cover_arg)
            ccmd = ' '.join(concat_bits)
            while '  ' in ccmd:
                ccmd = ccmd.replace('  ', ' ')
            print(f'[remux-fallback] concat: {ccmd}')
            rc2 = self._run_single_command(ccmd)
            if rc2 != 0:
                print(f'[remux-fallback] concat failed rc={rc2}')
                return False
            return os.path.isfile(output_file)
        except _Cancelled:
            raise
        except Exception:
            print_exc_terminal()
            return False
        finally:
            try:
                shutil.rmtree(part_dir, ignore_errors=True)
            except Exception:
                pass

    def _try_remux_mpls_split_outputs_track_aligned(
            self,
            mpls_path: str,
            output_file: str,
            confs: list[dict[str, int | str]],
            copy_audio_track: list[str],
            copy_sub_track: list[str],
            cover: str,
            cancel_event: Optional[threading.Event] = None,
    ) -> bool:
        """
        Fallback when ``mkvmerge mpls`` with ``--split parts`` fails but multiple episode MKVs are required.
        For each episode window on the MPLS timeline, mux overlapping m2ts slices with PID-aligned
        ``--track-order``, then ``+`` concat slices; writes ``basename-001.mkv``, ``-002.mkv``, … like mkvmerge.
        ``copy_audio_track`` / ``copy_sub_track`` are edit-tracks / remux stream indices; slots are built with
        ``_ordered_track_slots_for_remux`` (indices → PID via first clip m2ts as lookup).
        """
        out_norm = os.path.normpath(output_file) if output_file else ''
        if not out_norm or getattr(self, 'movie_mode', False):
            print('[remux-fallback-split] skip: empty output path or movie_mode')
            return False
        try:
            find_mkvtoolinx()
        except Exception:
            pass
        exe = MKV_MERGE_PATH or shutil.which('mkvmerge') or 'mkvmerge'
        chapter = Chapter(mpls_path)
        chapter.get_pid_to_language()
        segments = _svc_cls()._series_episode_segments_bounds(chapter, confs)
        expected = _svc_cls()._expected_mkvmerge_split_output_paths(out_norm, len(segments))
        if len(segments) <= 1 or len(expected) != len(segments):
            print(
                f'[remux-fallback-split] skip: need 2+ episode segments; '
                f'segments={len(segments)} expected_files={len(expected)}'
            )
            return False
        playlist_dir = os.path.dirname(os.path.normpath(mpls_path))
        stream_dir = os.path.normpath(os.path.join(playlist_dir, '..', 'STREAM'))
        play_rows = list(chapter.in_out_time or [])
        if len(play_rows) < 2:
            print(f'[remux-fallback-split] skip: playlist has only {len(play_rows)} clip(s)')
            return False
        first_name, _it0, _ot0 = play_rows[0]
        first_m2ts = os.path.join(stream_dir, f'{first_name}.m2ts')
        if not os.path.isfile(first_m2ts):
            print(f'[remux-fallback-split] missing first m2ts: {first_m2ts}')
            return False
        ref_slots = _svc_cls()._ordered_track_slots_for_remux(
            first_m2ts, copy_audio_track, copy_sub_track
        )
        if not ref_slots:
            print('[remux-fallback-split] no track slots from edit-tracks selection')
            return False
        ui = ''
        try:
            ui = (mkvtoolnix_ui_language_arg() or '').strip()
        except Exception:
            pass
        out_dir = os.path.dirname(out_norm) or '.'
        os.makedirs(out_dir, exist_ok=True)
        part_dir = os.path.join(out_dir, f'_remux_split_align_{os.getpid()}_{int(time.time() * 1000) & 0xFFFFFF}')
        os.makedirs(part_dir, exist_ok=True)
        rows = sum(map(len, chapter.mark_info.values()))
        total_end = rows + 1
        _, index_to_offset = get_index_to_m2ts_and_offset(chapter)

        def _off(idx: int) -> float:
            if idx >= total_end:
                return chapter.get_total_time()
            return float(index_to_offset.get(idx, 0.0))

        eps = 1e-5
        try:
            print(
                f'[remux-fallback-split] start: {len(segments)} episodes -> '
                f'{", ".join(os.path.basename(p) for p in expected)}'
            )
            try:
                self._progress(text=f'Multi-episode split fallback: {len(segments)} MKV...')
            except Exception:
                pass
            for seg_idx, ((cs, ce), dest_path) in enumerate(zip(segments, expected)):
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                w0 = float(_off(cs))
                w1 = float(_off(ce))
                pieces: list[str] = []
                acc = 0.0
                for clip_idx, (fname, in_time, out_time) in enumerate(play_rows):
                    if cancel_event and cancel_event.is_set():
                        raise _Cancelled()
                    clip_acc = acc
                    dur = max(0.0, (out_time - in_time) / 45000.0)
                    seg_lo = max(w0, clip_acc)
                    seg_hi = min(w1, clip_acc + dur)
                    acc = clip_acc + dur
                    if dur <= eps or seg_lo + eps >= seg_hi:
                        continue
                    m2ts_path = os.path.join(stream_dir, f'{fname}.m2ts')
                    if not os.path.isfile(m2ts_path):
                        print(f'[remux-fallback-split] missing m2ts: {m2ts_path}')
                        return False
                    need, a, b = _svc_cls()._m2ts_clip_time_window_sec(m2ts_path, in_time, out_time)
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
                    is_full_window = (slice_start <= full_lo + eps) and (slice_end >= full_hi - eps)
                    if is_full_window and not need:
                        split_arg = ''
                    elif is_full_window and need:
                        st = get_time_str(a)
                        ed = get_time_str(b)
                        if st == '0':
                            st = '00:00:00.000'
                        if ed == '0':
                            ed = '00:00:00.000'
                        split_arg = f'--split parts:{st}-{ed}'
                    else:
                        st = get_time_str(slice_start)
                        ed = get_time_str(slice_end)
                        if st == '0':
                            st = '00:00:00.000'
                        if ed == '0':
                            ed = '00:00:00.000'
                        split_arg = f'--split parts:{st}-{ed}'
                    clip_duration_sec = max(0.0, slice_end - slice_start)
                    part_out = os.path.join(part_dir, f'ep{seg_idx:03d}_c{clip_idx:03d}.mkv')
                    if not self._remux_one_m2ts_clip_or_tsmuxer(
                            m2ts_path,
                            mpls_path,
                            first_m2ts,
                            ref_slots,
                            part_out,
                            split_arg,
                            clip_duration_sec,
                            part_dir,
                            f'ep{seg_idx:03d}_c{clip_idx:03d}',
                            exe,
                            ui,
                    ):
                        return False
                    actual_part = part_out
                    if not os.path.isfile(actual_part):
                        prefix = f'ep{seg_idx:03d}_c{clip_idx:03d}'
                        try:
                            cands = sorted(
                                os.path.join(part_dir, fn)
                                for fn in os.listdir(part_dir)
                                if fn.startswith(prefix) and fn.lower().endswith('.mkv')
                            )
                        except Exception:
                            cands = []
                        if not cands:
                            print(f'[remux-fallback-split] missing part after mux: {part_out}')
                            return False
                        actual_part = cands[0]
                    pieces.append(actual_part)
                if not pieces:
                    print(
                        f'[remux-fallback-split] no m2ts pieces for segment {seg_idx} '
                        f'(time window {w0:.3f}s .. {w1:.3f}s)'
                    )
                    return False
                if cancel_event and cancel_event.is_set():
                    raise _Cancelled()
                cover_arg = ''
                if cover and os.path.isfile(cover):
                    cover_arg = f'--attachment-name Cover.jpg --attach-file "{cover}"'
                if len(pieces) == 1:
                    concat_bits = [f'"{exe}"']
                    if ui:
                        concat_bits.append(ui)
                    concat_bits += ['-o', f'"{dest_path}"', f'"{pieces[0]}"']
                    if cover_arg:
                        concat_bits.append(cover_arg)
                else:
                    concat_bits = [f'"{exe}"']
                    if ui:
                        concat_bits.append(ui)
                    concat_bits += ['--append-mode', 'track', '-o', f'"{dest_path}"', f'"{pieces[0]}"']
                    for p in pieces[1:]:
                        concat_bits.append('+')
                        concat_bits.append(f'"{p}"')
                    if cover_arg:
                        concat_bits.append(cover_arg)
                ccmd = ' '.join(concat_bits)
                while '  ' in ccmd:
                    ccmd = ccmd.replace('  ', ' ')
                print(f'[remux-fallback-split] segment {seg_idx + 1}: {ccmd}')
                rc2 = self._run_single_command(ccmd)
                if rc2 != 0:
                    print(f'[remux-fallback-split] segment concat failed rc={rc2} seg={seg_idx}')
                    return False
                if not os.path.isfile(dest_path):
                    print(f'[remux-fallback-split] missing output: {dest_path}')
                    return False
            return all(os.path.isfile(p) for p in expected)
        except _Cancelled:
            raise
        except Exception:
            print_exc_terminal()
            return False
        finally:
            try:
                shutil.rmtree(part_dir, ignore_errors=True)
            except Exception:
                pass

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
            try:
                chapter = Chapter(source_path)
                index_to_m2ts, _ = get_index_to_m2ts_and_offset(chapter)
                if index_to_m2ts:
                    first_key = sorted(index_to_m2ts.keys())[0]
                    playlist_dir = os.path.dirname(source_path)
                    stream_dir = os.path.join(os.path.dirname(playlist_dir), 'STREAM')
                    m2ts_path = os.path.join(stream_dir, index_to_m2ts[first_key])
                    if os.path.exists(m2ts_path):
                        probe_path = m2ts_path
            except Exception:
                pass
        if str(probe_path).lower().endswith('.m2ts'):
            streams = self._read_m2ts_track_info(probe_path)
        else:
            streams = _svc_cls()._read_media_streams(probe_path)
        pid_lang = pid_to_lang or {}
        if not pid_lang:
            out: dict[int, str] = {}
            for s in streams or []:
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
                            lang = getattr(language, "bibliographic", getattr(language, "alpha_3", None)) or lang
                except Exception:
                    pass
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
            pid_lang = out
        return _svc_cls()._default_track_selection_from_streams(streams, pid_lang)

    @staticmethod
    def _sp_track_key_from_entry(entry: dict[str, int | str]) -> str:
        try:
            bdmv_index = int(entry.get('bdmv_index') or 0)
        except Exception:
            bdmv_index = 0
        mpls_file = str(entry.get('mpls_file') or '').strip()
        m2ts_file = str(entry.get('m2ts_file') or '').strip()
        if mpls_file:
            return f'sp::{bdmv_index}::mpls::{mpls_file}'
        first_m2ts = m2ts_file.split(',')[0].strip() if m2ts_file else ''
        return f'sp::{bdmv_index}::m2ts::{first_m2ts}'

    @staticmethod
    def _canonical_remux_mkv_path(path: str) -> str:
        """Stable comparison key for remux MKV paths (symlinks, slashes, Windows case)."""
        p = os.path.normpath(str(path or ''))
        try:
            if os.path.isfile(p):
                return os.path.normcase(os.path.normpath(os.path.realpath(p)))
        except Exception:
            pass
        return os.path.normcase(p)

    def _lossless_submap_from_track_cfg(self, cfg_all: dict[str, object], nk: str) -> dict[str, str]:
        """Collect lossless codec choices for nk using exact and fuzzy mkv:: / mkvsp:: keys."""
        out: dict[str, str] = {}
        if not nk:
            return out
        want = self._canonical_remux_mkv_path(nk)

        def ingest(sub: object) -> None:
            if not isinstance(sub, dict):
                return
            for ix, v in sub.items():
                vv = str(v or '').strip().lower()
                if vv in ('flac', 'aac', 'opus'):
                    out[str(ix)] = vv

        mkv_key = f'mkv::{os.path.normpath(nk)}'
        mkvsp_key = f'mkvsp::{os.path.normpath(nk)}'
        for k in (mkv_key, mkvsp_key):
            if k in cfg_all and isinstance(cfg_all[k], dict):
                ingest(cfg_all[k])
        if out:
            return out

        for prefix in ('mkv::', 'mkvsp::'):
            for k, sub in cfg_all.items():
                if not isinstance(k, str) or not k.startswith(prefix):
                    continue
                rest = k[len(prefix):].strip()
                if not rest:
                    continue
                if self._canonical_remux_mkv_path(rest) != want:
                    continue
                ingest(sub)
        if out:
            return out

        # Single remux key in project (common): user path differs slightly from stored key
        remux_entries: list[tuple[str, dict[str, str]]] = []
        for k, sub in cfg_all.items():
            if not isinstance(k, str) or not isinstance(sub, dict):
                continue
            if not (k.startswith('mkv::') or k.startswith('mkvsp::')):
                continue
            d: dict[str, str] = {}
            for ix, v in sub.items():
                vv = str(v or '').strip().lower()
                if vv in ('flac', 'aac', 'opus'):
                    d[str(ix)] = vv
            if d:
                remux_entries.append((k, d))
        if len(remux_entries) == 1:
            ingest(remux_entries[0][1])

        return out

    def _resolve_lossless_audio_map_for_mkv(self, mkv_path: str, episode_i: int) -> dict[str, str]:
        """Map mkv stream index (decimal string) -> flac|aac|opus from GUI track_lossless_audio_config."""
        out: dict[str, str] = {}
        cfg_all = getattr(self, 'track_lossless_audio_config', None) or {}
        if not isinstance(cfg_all, dict):
            return out
        nk = os.path.normpath(str(mkv_path or ''))
        out = self._lossless_submap_from_track_cfg(cfg_all, nk)
        if out:
            return out
        try:
            cfg = getattr(self, 'configuration', None) or {}
            keys = sorted(cfg.keys(), key=lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x)))
            ix = int(episode_i) - 1
            if keys and ix >= 0 and ix < len(keys):
                c = cfg.get(keys[ix], {}) or {}
                sm = str(c.get('selected_mpls') or '').strip()
                if sm:
                    if not sm.lower().endswith('.mpls'):
                        sm = sm + '.mpls'
                    base_name = os.path.basename(sm)
                    for root in list(getattr(self, 'bluray_folders', None) or []):
                        for cand in (
                            os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', base_name)),
                            os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST', sm)),
                        ):
                            if os.path.isfile(cand):
                                mk_main = f'main::{cand}'
                                if mk_main in cfg_all and isinstance(cfg_all[mk_main], dict):
                                    for ix2, v in (cfg_all[mk_main] or {}).items():
                                        vv = str(v or '').strip().lower()
                                        if vv in ('flac', 'aac', 'opus'):
                                            out[str(ix2)] = vv
                                return out
                    bp = getattr(self, 'bdmv_path', '') or ''
                    if bp:
                        cand = os.path.normpath(os.path.join(bp, 'BDMV', 'PLAYLIST', base_name))
                        if os.path.isfile(cand):
                            mk_main = f'main::{cand}'
                            if mk_main in cfg_all and isinstance(cfg_all[mk_main], dict):
                                for ix2, v in (cfg_all[mk_main] or {}).items():
                                    vv = str(v or '').strip().lower()
                                    if vv in ('flac', 'aac', 'opus'):
                                        out[str(ix2)] = vv
                            return out
        except Exception:
            pass
        return out

    @staticmethod
    def _lossless_codec_choice(map_by_idx: dict[str, str], idx_str: str, default: str = 'flac') -> str:
        v = str((map_by_idx or {}).get(str(idx_str), '') or '').strip().lower()
        if v in ('flac', 'aac', 'opus'):
            return v
        d = str(default or 'flac').strip().lower()
        return d if d in ('flac', 'aac', 'opus') else 'flac'

    @staticmethod
    def _wav_channel_count(wav_path: str) -> int:
        try:
            info = soundfile.info(wav_path)
            ch = int(info.channels)
            if ch > 0:
                return ch
        except Exception:
            pass
        try:
            proc = subprocess.run(
                f'"{FFPROBE_PATH}" -v error -select_streams a:0 -show_entries stream=channels '
                f'-of default=noprint_wrappers=1:nokey=1 "{wav_path}"',
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            ch = int((proc.stdout or '').strip())
            if ch > 0:
                return ch
        except Exception:
            pass
        return 2

    @staticmethod
    def _wav_channel_layout(wav_path: str) -> str:
        """ffprobe channel_layout for stream 0 (e.g. ``stereo``, ``5.1(side)``); empty if unknown."""
        if not wav_path or not os.path.isfile(wav_path):
            return ''
        try:
            proc = subprocess.run(
                f'"{FFPROBE_PATH}" -v error -select_streams a:0 '
                f'-show_entries stream=channel_layout -of default=noprint_wrappers=1:nokey=1 "{wav_path}"',
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return (proc.stdout or '').strip()
        except Exception:
            return ''

    @staticmethod
    def _ffmpeg_compress_wav_to_codec(wav_path: str, out_path: str, codec: str) -> bool:
        codec = str(codec or 'flac').strip().lower()
        if codec == 'flac':
            try:
                subprocess.run(
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{wav_path}" -c:a flac "{out_path}"',
                    shell=True,
                    check=False,
                )
                return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
            except Exception:
                return False
        if codec == 'aac':
            try:
                exe = (FDK_AAC_PATH or '').strip()
                if not exe:
                    return False
                subprocess.run(
                    f'"{exe}" -m 5 "{wav_path}" -o "{out_path}"',
                    shell=True,
                    check=False,
                )
                return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
            except Exception:
                return False
        if codec == 'opus':
            try:
                nch = MediaInfoTrackMappingMixin._wav_channel_count(wav_path)
                layout = MediaInfoTrackMappingMixin._wav_channel_layout(wav_path)
                br = '128k' if nch <= 2 else '256k'
                # Surround: libopus needs explicit mapping family (default -1 fails on layouts like 5.1(side)).
                map_f = '-mapping_family 1 ' if nch > 2 else ''
                af = ''
                if (layout or '').strip().lower() == '5.1(side)':
                    af = '-af "aformat=channel_layouts=5.1" '
                cmd = (
                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{wav_path}" '
                    f'{af}-c:a libopus {map_f}-b:a {br} "{out_path}"'
                )
                print(f'{translate_text("Opus encode command:")}{cmd}')
                subprocess.run(cmd, shell=True, check=False)
                return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
            except Exception:
                return False
        return False

    def process_audio_to_flac(self, output_file, dst_folder, i, source_file: Optional[str] = None) -> tuple[
        int, dict[int, str], list[str]]:
        dolby_truehd_tracks = []
        track_bits = {}
        track_id_delay_map = {}
        duplicate_track_source: dict[int, int] = {}
        self._track_flac_map = {}
        self._audio_tracks_to_exclude = set()
        flac_files = []
        src_mkv = os.path.normpath(source_file) if source_file else os.path.normpath(output_file)
        try:
            ei = int(i) if i is not None else -1
        except Exception:
            ei = -1
        la_map = self._resolve_lossless_audio_map_for_mkv(src_mkv, ei)
        default_la = str(getattr(self, 'default_lossless_audio_codec', '') or 'flac').strip().lower()
        if default_la not in ('flac', 'aac', 'opus'):
            default_la = 'flac'

        def _track_id_from_path(p: str) -> Optional[int]:
            name = os.path.basename(p or '')
            m = re.search(r'(?i)\.track(\d+)', name)
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None

        if os.path.exists(src_mkv):
            subprocess.Popen(
                f'"{FFPROBE_PATH}" -v error -show_streams -show_format -of json "{src_mkv}" >info.json 2>&1',
                shell=True).wait()
            with open('info.json', 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            for stream in data['streams']:
                try:
                    delay_val = float(stream.get('start_time', 0.0))
                except Exception:
                    delay_val = 0.0
                if abs(delay_val) > 1e-6:
                    track_id_delay_map[stream['index']] = delay_val
                if stream['codec_name'] == 'truehd' and stream.get('profile') == 'Dolby TrueHD + Dolby Atmos':
                    dolby_truehd_tracks.append(stream['index'])
                if stream['codec_name'] in ('truehd', 'dts'):
                    track_bits[stream['index']] = int(stream.get('bits_per_raw_sample') or 24)
        else:
            print('\033[31mError: movie mux failed, please check task output\033[0m')
        base = os.path.join(dst_folder, os.path.splitext(os.path.basename(output_file))[0])
        track_count, track_info = self.extract_lossless(src_mkv, dolby_truehd_tracks, output_base=base)
        if track_info:
            ext_fn_map = {}
            for file1 in os.listdir(dst_folder):
                file1_path = os.path.join(dst_folder, file1)
                if file1_path != output_file and not file1_path.endswith('.mkv') and '.track' in file1:
                    ext = file1_path.split('.')[-1]
                    if ext in ext_fn_map:
                        ext_fn_map[ext].append(file1_path)
                    else:
                        ext_fn_map[ext] = [file1_path]
            for ext, fns in ext_fn_map.items():
                if len(fns) > 1:
                    fns = sorted(fns, key=lambda p: (
                        _track_id_from_path(p) if _track_id_from_path(p) is not None else 10 ** 9, p))
                    fpts: list[tuple[np.ndarray, int, str, int]] = []
                    for fn in fns:
                        tmp_wav = None
                        fp_source = fn
                        track_id = _track_id_from_path(fn)
                        track_id_val = int(track_id) if track_id is not None else -1
                        n_ch = _audio_file_channel_count(fn)
                        try:
                            if ext not in ('wav', 'w64', 'flac'):
                                tmp_wav = os.path.splitext(fn)[0] + '.fp.wav'
                                subprocess.Popen(
                                    f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -ss 60 -t 30 -i "{fn}" '
                                    f'-ac 1 -ar 11025 -c:a pcm_s16le "{tmp_wav}"',
                                    shell=True
                                ).wait()
                                if os.path.exists(tmp_wav):
                                    fp_source = tmp_wav
                            y, sr = librosa.load(fp_source, sr=None, mono=True)
                            if y is None or len(y) == 0 or float(np.max(np.abs(y))) < 1e-8:
                                raise Exception('silent')
                            chroma = librosa.feature.chroma_stft(y=y, sr=sr, tuning=0.0)
                            fpt = np.mean(chroma, axis=1)
                        except Exception:
                            if tmp_wav and os.path.exists(tmp_wav):
                                try:
                                    os.remove(tmp_wav)
                                except Exception:
                                    pass
                            continue
                        finally:
                            if tmp_wav and os.path.exists(tmp_wav):
                                try:
                                    os.remove(tmp_wav)
                                except Exception:
                                    pass
                        duplicate_track = False
                        for j, (_fpt, _src_track_id, _src_fn, ch_prev) in enumerate(list(fpts)):
                            if n_ch > 0 and ch_prev > 0 and n_ch != ch_prev:
                                continue
                            denom = (np.linalg.norm(fpt) * np.linalg.norm(_fpt))
                            sim = (np.dot(fpt, _fpt) / denom) if denom else 0.0
                            if sim > 0.9997:
                                # Keep smaller track id when two tracks are considered duplicated.
                                keep_current = False
                                if track_id_val > -1 and _src_track_id > -1 and track_id_val < _src_track_id:
                                    keep_current = True
                                if keep_current:
                                    try:
                                        os.remove(_src_fn)
                                    except Exception:
                                        pass
                                    if _src_track_id > -1 and track_id_val > -1:
                                        duplicate_track_source[_src_track_id] = track_id_val
                                        self._audio_tracks_to_exclude.add(_src_track_id)
                                        track_info.pop(_src_track_id, None)
                                    fpts[j] = (fpt, track_id_val, fn, n_ch)
                                    print(f'Found duplicate audio track ｢{_src_fn}｣, deleted')
                                else:
                                    os.remove(fn)
                                    if track_id_val > -1 and _src_track_id > -1:
                                        duplicate_track_source[track_id_val] = _src_track_id
                                        self._audio_tracks_to_exclude.add(track_id_val)
                                        track_info.pop(track_id_val, None)
                                    print(f'Found duplicate audio track ｢{fn}｣, deleted')
                                duplicate_track = True
                                break
                        if not duplicate_track:
                            fpts.append((fpt, track_id_val, fn, n_ch))

            def _is_silent_audio(path: str, threshold_db: float = -60.0) -> tuple[bool, float]:
                try:
                    proc = subprocess.run(
                        f'"{FFMPEG_PATH}" -hide_banner -nostats -i "{path}" -af volumedetect -f null -',
                        shell=True,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore'
                    )
                    text_out = (proc.stderr or '') + '\n' + (proc.stdout or '')
                    m_mean = re.search(r'mean_volume:\s*([-\d\.]+)\s*dB', text_out)
                    m_max = re.search(r'max_volume:\s*([-\d\.]+)\s*dB', text_out)
                    mean_db = float(m_mean.group(1)) if m_mean else float('-inf')
                    max_db = float(m_max.group(1)) if m_max else float('-inf')
                    if mean_db == float('-inf') and max_db == float('-inf'):
                        return True, float('-inf')
                    return (max_db < threshold_db), mean_db
                except Exception:
                    pass
                y = None
                if soundfile is not None:
                    try:
                        info = soundfile.info(path)
                        frames = min(int(info.frames), int(info.samplerate) * 30)
                        start = int(info.frames) // 2 if int(info.frames) > (frames * 2) else 0
                        data, sr = soundfile.read(path, start=start, frames=frames, dtype='float32', always_2d=True)
                        y = data.mean(axis=1)
                    except Exception:
                        y = None

                if y is None:
                    fd, tmp = tempfile.mkstemp(prefix=f"temp_sil_{os.getpid()}_", suffix=".wav")
                    os.close(fd)
                    try:
                        subprocess.run(
                            f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{path}" '
                            f'-ac 1 -ar 22050 -c:a pcm_s16le "{tmp}"',
                            shell=True,
                            check=True
                        )
                        if soundfile is None:
                            y, sr = librosa.load(tmp, sr=None, mono=True)
                        else:
                            data, sr = soundfile.read(tmp, dtype='float32', always_2d=True)
                            y = data.mean(axis=1)
                    finally:
                        if os.path.exists(tmp):
                            try:
                                os.remove(tmp)
                            except Exception:
                                pass
                if y is None or len(y) == 0:
                    return True, float('-inf')
                if float(np.max(np.abs(y))) < 1e-8:
                    return True, float('-inf')
                rms = librosa.feature.rms(y=y)
                db = librosa.amplitude_to_db(rms, ref=np.max)
                avg_db = float(np.mean(db)) if db.size else float('-inf')
                if avg_db != avg_db:
                    return True, float('-inf')
                return avg_db < threshold_db, avg_db

            for file1 in os.listdir(dst_folder):
                file1_path = os.path.join(dst_folder, file1)
                if not os.path.isfile(file1_path):
                    continue
                track_id = _track_id_from_path(file1_path)
                if track_id is None:
                    continue
                if (file1_path != output_file and not file1_path.endswith('.mkv') and not file1_path.endswith('.lwi')
                        and not file1_path.endswith(('.hevc', '.h264', '.ivf')) and not file1_path.endswith('.ass')
                        and not file1_path.endswith('.ssa') and not file1_path.endswith('.srt')):
                    try:
                        silent, avg_db = _is_silent_audio(file1_path, -60.0)
                    except Exception:
                        silent = False
                        avg_db = 0.0
                    if silent:
                        try:
                            os.remove(file1_path)
                        except Exception:
                            pass
                        try:
                            track_id = _track_id_from_path(file1_path)
                            if track_id is not None:
                                track_info.pop(int(track_id), None)
                                self._audio_tracks_to_exclude.add(int(track_id))
                        except Exception:
                            pass
                        print(
                            f'{translate_text("Detected empty audio track ｢")}{file1_path}{translate_text("｣ average ")}{avg_db:.1f}{translate_text(" dB, deleted")}')
                        continue
                    print(f'{translate_text("Compressing audio track ｢")}{file1_path}{translate_text("｣")}')
                    track_id = int(track_id)
                    if track_id in track_id_delay_map:
                        delay_sec = track_id_delay_map[track_id]
                        delay_ms = int(round(delay_sec * 1000.0))
                        print(
                            f'{translate_text("Detected file ｢")}{file1_path}{translate_text("｣ has delay ")}{delay_ms} ms')
                        output_fn = os.path.splitext(file1_path)[0] + '.delayfix.wav'
                        fix_audio_delay_to_lossless(file1_path, delay_ms, output_fn)
                        if os.path.exists(output_fn):
                            try:
                                os.remove(file1_path)
                            except Exception:
                                pass
                            file1_path = output_fn

                    if file1_path.endswith('.wav'):
                        bits = track_bits.get(track_id, 16)
                        effective_bits = get_effective_bit_depth(file1_path)
                        if effective_bits < bits:
                            print(
                                f'{translate_text("Detected file ｢")}{file1_path}{translate_text("｣ effective bit depth is low, optimizing to 16-bit...")}')
                            codec = "pcm_s16le"
                            output_fn = os.path.splitext(file1_path)[0] + '(1).wav'
                            cmd = f'"{FFMPEG_PATH}" -hide_banner -loglevel error -i "{file1_path}" -c:a {codec} "{output_fn}" -y'
                            subprocess.run(cmd, shell=True, check=True)
                            if os.path.exists(output_fn):
                                print(f'{translate_text("Conversion completed: ｢")}{output_fn}{translate_text("｣")}')
                                os.remove(file1_path)
                                os.rename(output_fn, file1_path)

                        codec_choice = self._lossless_codec_choice(la_map, str(track_id), default_la)
                        base_no_ext = os.path.splitext(file1_path)[0]
                        flac_file = base_no_ext + '.flac'
                        if codec_choice == 'flac':
                            subprocess.Popen(f'"{FLAC_PATH}" -8 -j {FLAC_THREADS} "{file1_path}" -o "{flac_file}"',
                                             shell=True).wait()
                            if os.path.exists(flac_file):
                                delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                os.remove(file1_path)
                                print(
                                    f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to FLAC to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                self._audio_tracks_to_exclude.add(track_id)
                            else:
                                subprocess.Popen(f'{FFMPEG_PATH} -i "{file1_path}" -c:a flac "{flac_file}"',
                                                 shell=True).wait()
                                if os.path.exists(flac_file):
                                    delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                    os.remove(file1_path)
                                    print(
                                        f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to FLAC with ffmpeg to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                    self._audio_tracks_to_exclude.add(track_id)
                        else:
                            out_audio = base_no_ext + ('.m4a' if codec_choice == 'aac' else '.opus')
                            if self._ffmpeg_compress_wav_to_codec(file1_path, out_audio, codec_choice):
                                delta = os.path.getsize(file1_path) - os.path.getsize(out_audio)
                                os.remove(file1_path)
                                print(
                                    f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to ")}{codec_choice.upper()}{translate_text(" to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                self._audio_tracks_to_exclude.add(track_id)
                    else:
                        codec_choice2 = self._lossless_codec_choice(la_map, str(track_id), default_la)
                        # MKV already holds FLAC: mux extracted file as-is instead of decode→WAV→FLAC.
                        if codec_choice2 == 'flac' and file1_path.lower().endswith('.flac'):
                            print(
                                f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ is already FLAC, skipping re-encode")}')
                            self._audio_tracks_to_exclude.add(track_id)
                            continue
                        bits = track_bits.get(track_id, 24)
                        effective_bits = get_compressed_effective_depth(file1_path)
                        if effective_bits < bits:
                            print(
                                f'{translate_text("Detected file ｢")}{file1_path}{translate_text("｣ actual effective bit depth is ")}{effective_bits} bits')
                        wav_file = os.path.splitext(file1_path)[0] + '.wav'
                        # fdkaac only accepts classic RIFF WAVE; Wave64 (-f w64) yields "unsupported input file".
                        pcm_container = 'wav' if codec_choice2 in ('aac', 'opus') else 'w64'
                        subprocess.Popen(
                            f'"{FFMPEG_PATH}" -hide_banner -loglevel error -y -i "{file1_path}" '
                            f'-c:a pcm_s{effective_bits}le -f {pcm_container} "{wav_file}"',
                            shell=True).wait()
                        base_no_ext2 = os.path.splitext(file1_path)[0]
                        flac_file = base_no_ext2 + '.flac'
                        if codec_choice2 == 'flac':
                            subprocess.Popen(f'{FLAC_PATH} -8 -j {FLAC_THREADS} "{wav_file}" -o "{flac_file}"',
                                             shell=True).wait()
                            if os.path.exists(flac_file):
                                if os.path.getsize(flac_file) > os.path.getsize(file1_path):
                                    print(
                                        f'{translate_text("FLAC is larger than the original track, deleting ｢")}{flac_file}{translate_text("｣")}')
                                    os.remove(flac_file)
                                else:
                                    delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                    print(
                                        f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to FLAC to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                    self._audio_tracks_to_exclude.add(track_id)
                            else:
                                subprocess.Popen(f'{FFMPEG_PATH} -i "{wav_file}" -c:a flac "{flac_file}"',
                                                 shell=True).wait()
                                if os.path.exists(flac_file):
                                    if os.path.getsize(flac_file) > os.path.getsize(file1_path):
                                        print(
                                            f'{translate_text("ffmpeg-compressed FLAC is larger than the original track, deleting ｢")}{flac_file}{translate_text("｣")}')
                                        os.remove(flac_file)
                                    else:
                                        delta = os.path.getsize(file1_path) - os.path.getsize(flac_file)
                                        print(
                                            f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to FLAC with ffmpeg to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                        self._audio_tracks_to_exclude.add(track_id)
                                else:
                                    print('\033[31mError: ffmpeg compression also failed\033[0m')
                            os.remove(file1_path)
                            os.remove(wav_file)
                        else:
                            out_audio2 = base_no_ext2 + ('.m4a' if codec_choice2 == 'aac' else '.opus')
                            if self._ffmpeg_compress_wav_to_codec(wav_file, out_audio2, codec_choice2):
                                delta = os.path.getsize(file1_path) - os.path.getsize(out_audio2)
                                try:
                                    os.remove(file1_path)
                                except Exception:
                                    pass
                                try:
                                    os.remove(wav_file)
                                except Exception:
                                    pass
                                print(
                                    f'{translate_text("Track ｢")}{file1_path}{translate_text("｣ compressed to ")}{codec_choice2.upper()}{translate_text(" to reduce size ")}{delta / 1024 ** 2:.3f} MiB')
                                self._audio_tracks_to_exclude.add(track_id)
                            else:
                                print('\033[31mError: lossless audio intermediate encode failed\033[0m')
                                try:
                                    os.remove(wav_file)
                                except Exception:
                                    pass
            flac_files = []
            base_prefix = os.path.splitext(os.path.basename(output_file or ''))[0]
            _lossless_audio_suffixes = ('.flac', '.m4a', '.opus')
            for file1 in os.listdir(dst_folder):
                file1_path = os.path.join(dst_folder, file1)
                low = file1_path.lower()
                if not (os.path.isfile(file1_path) and low.endswith(_lossless_audio_suffixes)):
                    continue
                if base_prefix and (not file1.startswith(base_prefix)):
                    continue
                if '.track' not in file1.lower():
                    continue
                flac_files.append(file1_path)
            if not flac_files:
                for file1 in os.listdir(dst_folder):
                    file1_path = os.path.join(dst_folder, file1)
                    if file1_path != output_file:
                        if file1_path.endswith('.wav') and (
                                base_prefix and os.path.basename(file1_path).startswith(base_prefix)) and (
                                '.track' in os.path.basename(file1_path).lower()):
                            n = len(os.listdir(dst_folder))
                            print(
                                f'{translate_text("flac compressing wav file ｢")}{file1_path}{translate_text("｣ failed, will use ffmpeg to compress")}')
                            subprocess.Popen(
                                f'{FFMPEG_PATH} -i "{file1_path}" -c:a flac "{file1_path[:-4] + ".flac"}"',
                                shell=True).wait()
                            if len(os.listdir(dst_folder)) > n:
                                os.remove(file1_path)
                for file1 in os.listdir(dst_folder):
                    file1_path = os.path.join(dst_folder, file1)
                    low2 = file1_path.lower()
                    if not (os.path.isfile(file1_path) and low2.endswith(_lossless_audio_suffixes)):
                        continue
                    if base_prefix and (not file1.startswith(base_prefix)):
                        continue
                    if '.track' not in file1.lower():
                        continue
                    flac_files.append(file1_path)
            track_flac_map: dict[int, str] = {}
            for flac in flac_files:
                tid = _track_id_from_path(flac)
                if tid is not None:
                    track_flac_map[int(tid)] = flac
            self._track_flac_map = track_flac_map
            for tid in track_info.keys():
                try:
                    self._audio_tracks_to_exclude.add(int(tid))
                except Exception:
                    pass
        return track_count, track_info, flac_files
