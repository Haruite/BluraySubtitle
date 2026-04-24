import os
import shutil
import subprocess
import sys
from statistics import median
from struct import unpack
from typing import Optional, BinaryIO

from .core import InfoDict
from .structures.stream_attributes import StreamAttributes
from .structures.stream_entry import StreamEntry
from src.core import FFPROBE_PATH
from src.core.i18n import sp_debug_log
from src.core.i18n import translate_text


class M2TS:
    frame_size = 192
    _TS_PACKET = 188
    _SYNC = 0x47

    def __init__(self, filename: str):
        self.filename = filename
        self._cache_file_sig: Optional[tuple[int, int]] = None
        self._layout_cache: dict[Optional[bool], tuple[int, int, int]] = {}
        self._first_pts_cache: dict[tuple[Optional[bool], Optional[int], frozenset[int]], Optional[int]] = {}
        self._last_pts_cache: dict[tuple[Optional[bool], Optional[int], frozenset[int]], Optional[int]] = {}
        self._duration_cache: dict[tuple[bool, bool], int] = {}
        self._tracks_info_cache: dict[tuple[Optional[bool], int], list[dict[str, object]]] = {}
        self._m2ts_type_cache: dict[tuple[Optional[bool], int], str] = {}
        self._fps_cache: dict[tuple[Optional[bool], Optional[int], int, bool], Optional[float]] = {}
        self._total_frames_cache: Optional[int] = None

    def _current_file_signature(self) -> Optional[tuple[int, int]]:
        try:
            st = os.stat(self.filename)
            return int(st.st_size), int(st.st_mtime_ns)
        except OSError:
            return None

    def _clear_runtime_caches(self) -> None:
        self._layout_cache.clear()
        self._first_pts_cache.clear()
        self._last_pts_cache.clear()
        self._duration_cache.clear()
        self._tracks_info_cache.clear()
        self._m2ts_type_cache.clear()
        self._fps_cache.clear()
        self._total_frames_cache = None

    def _ensure_cache_valid(self) -> None:
        sig = self._current_file_signature()
        if self._cache_file_sig != sig:
            self._cache_file_sig = sig
            self._clear_runtime_caches()

    def _choose_transport_layout_cached(self, stream: BinaryIO, m2ts: Optional[bool]) -> tuple[int, int, int]:
        self._ensure_cache_valid()
        cached = self._layout_cache.get(m2ts)
        if cached is not None:
            return cached
        layout = M2TS._choose_transport_layout(stream, m2ts)
        self._layout_cache[m2ts] = layout
        return layout

    @staticmethod
    def _normalize_skip_pids(skip_pids: Optional[set[int]]) -> frozenset[int]:
        if not skip_pids:
            return frozenset()
        return frozenset(int(x) for x in skip_pids)

    @staticmethod
    def _pts_from_pes_header(p: bytes) -> int:
        pts = ((p[0] >> 1) & 0x07) << 30
        val = p[1] << 8 | p[2]
        pts |= (val >> 1) << 15
        val = p[3] << 8 | p[4]
        pts |= val >> 1
        return pts

    @staticmethod
    def _pes_payload_after_pointer(payload: bytes) -> bytes:
        if not payload:
            return b''
        pf = payload[0]
        after = payload[1 + pf:]
        if after.startswith(b'\x00\x00\x01'):
            return after
        if payload.startswith(b'\x00\x00\x01'):
            return payload
        return after

    @staticmethod
    def _ts_payload(pkt: bytes) -> tuple[Optional[bytes], int, bool]:
        if len(pkt) < M2TS._TS_PACKET or pkt[0] != M2TS._SYNC:
            return None, -1, False
        if pkt[1] & 0x80:
            pass
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        pusi = (pkt[1] & 0x40) != 0
        afc = (pkt[3] & 0x30) >> 4
        off = 4
        if afc & 2:
            if off >= len(pkt):
                return None, pid, pusi
            adapt_len = pkt[4]
            off = 5 + adapt_len
            if off > len(pkt):
                return None, pid, pusi
        if (afc & 1) == 0:
            return None, pid, pusi
        return pkt[off:M2TS._TS_PACKET], pid, pusi

    @staticmethod
    def _file_size(stream: BinaryIO) -> int:
        try:
            pos = stream.tell()
            stream.seek(0, os.SEEK_END)
            n = stream.tell()
            stream.seek(pos)
            return int(n)
        except OSError:
            return 256 * 1024

    @staticmethod
    def _score_alignment(buf: bytes, phase: int, stride: int, sync_off: int) -> int:
        c = 0
        pos = phase + sync_off
        while pos + M2TS._TS_PACKET <= len(buf):
            if buf[pos] == M2TS._SYNC:
                c += 1
            pos += stride
        return c

    @staticmethod
    def _best_phase_for_params(buf: bytes, stride: int, sync_off: int) -> tuple[int, int]:
        best_p, best_s = 0, -1
        for phase in range(stride):
            s = M2TS._score_alignment(buf, phase, stride, sync_off)
            if s > best_s:
                best_s = s
                best_p = phase
        return best_p, best_s

    @staticmethod
    def _choose_transport_layout(stream: BinaryIO, m2ts: Optional[bool]) -> tuple[int, int, int]:
        pos = stream.tell()
        sample = stream.read(min(512 * 1024, max(M2TS._file_size(stream), 512 * 1024)))
        stream.seek(pos)

        if m2ts is not None:
            stride, off = (M2TS.frame_size, 4) if m2ts else (M2TS._TS_PACKET, 0)
            phase, _ = M2TS._best_phase_for_params(sample, stride, off)
            return phase, stride, off

        best: tuple[int, int, int, int] = (-1, 0, M2TS.frame_size, 4)
        for stride, sync_off in ((M2TS.frame_size, 4), (M2TS._TS_PACKET, 0), (M2TS.frame_size, 0)):
            phase, score = M2TS._best_phase_for_params(sample, stride, sync_off)
            if score > best[0]:
                best = (score, phase, stride, sync_off)
        return best[1], best[2], best[3]

    @staticmethod
    def _scan_first_pts(
        stream: BinaryIO,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        skip_pids: Optional[set[int]] = None,
        debug: bool = False,
    ) -> Optional[int]:
        skip = skip_pids or set()
        skip |= {0x0000, 0x1FFF}

        start_phase, spacing, sync_off = M2TS._choose_transport_layout(stream, m2ts)
        stream.seek(start_phase)
        if debug:
            print(
                f'[M2TS.get_first_pts] seek={start_phase} stride={spacing} sync_off={sync_off}',
                file=sys.stderr,
            )

        pending: dict[int, bytearray] = {}
        total_read = 0
        pending_max = 256 * 1024

        while True:
            block = stream.read(spacing)
            if len(block) < spacing:
                break
            total_read += len(block)
            if max_bytes is not None and total_read > max_bytes:
                break
            if sync_off + M2TS._TS_PACKET > len(block):
                break
            pkt = block[sync_off:sync_off + M2TS._TS_PACKET]
            if pkt[0] != M2TS._SYNC:
                continue

            payload, pid, pusi = M2TS._ts_payload(pkt)
            if payload is None or pid in skip:
                continue

            if pusi:
                if not payload:
                    pending.pop(pid, None)
                    continue
                pf = payload[0]
                if not payload.startswith(b'\x00\x00\x01') and 1 + pf > len(payload):
                    pending.pop(pid, None)
                    continue
                pending[pid] = bytearray(M2TS._pes_payload_after_pointer(payload))
            else:
                if pid not in pending:
                    continue
                pending[pid].extend(payload)
                if len(pending[pid]) > pending_max:
                    pending.pop(pid, None)
                    continue

            buf = pending.get(pid)
            if not buf or len(buf) < 9:
                continue

            if buf[0:3] != b'\x00\x00\x01':
                pending.pop(pid, None)
                continue

            flags_hi = buf[6]
            if (flags_hi & 0xC0) != 0x80:
                pending.pop(pid, None)
                continue

            flags_lo = buf[7]
            pes_hdr_remain = buf[8]
            need = 9 + pes_hdr_remain
            if len(buf) < need:
                continue

            if (flags_lo & 0xC0) == 0:
                pending.pop(pid, None)
                continue

            if len(buf) < 14:
                continue

            pts = M2TS._pts_from_pes_header(bytes(buf[9:14]))
            pending.pop(pid, None)
            if debug:
                print(
                    f'{translate_text("[M2TS.get_first_pts] first PTS from PID 0x")}{pid:04x}'
                    f'{translate_text(" = ")}{pts}',
                    file=sys.stderr
                )
            return pts

        return None

    def get_first_pts(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        skip_pids: Optional[set[int]] = None,
        debug: bool = False,
    ) -> Optional[int]:
        """First presentation timestamp (90 kHz units) from elementary streams, or None."""
        self._ensure_cache_valid()
        cache_key = (m2ts, max_bytes, M2TS._normalize_skip_pids(skip_pids))
        if cache_key in self._first_pts_cache:
            return self._first_pts_cache[cache_key]
        with open(self.filename, 'rb') as f:
            pts = M2TS._scan_first_pts(f, m2ts=m2ts, max_bytes=max_bytes, skip_pids=skip_pids, debug=debug)
        if pts is not None:
            self._first_pts_cache[cache_key] = pts
            return pts
        if m2ts is not None:
            self._first_pts_cache[cache_key] = None
            return None
        for forced in (True, False):
            with open(self.filename, 'rb') as f:
                pts = M2TS._scan_first_pts(f, m2ts=forced, max_bytes=max_bytes, skip_pids=skip_pids, debug=debug)
            if pts is not None:
                self._first_pts_cache[cache_key] = pts
                return pts
        self._first_pts_cache[cache_key] = None
        return None

    @staticmethod
    def _scan_last_pts(
        stream: BinaryIO,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        skip_pids: Optional[set[int]] = None,
        start_pos: Optional[int] = None,
    ) -> Optional[int]:
        skip = skip_pids or set()
        skip |= {0x0000, 0x1FFF}

        start_phase, spacing, sync_off = M2TS._choose_transport_layout(stream, m2ts)
        scan_pos = start_phase if start_pos is None else max(start_phase, int(start_pos))
        # Align scan start to packet boundary selected by phase/spacing.
        if scan_pos > start_phase:
            scan_pos = start_phase + ((scan_pos - start_phase) // spacing) * spacing
        stream.seek(scan_pos)

        pending: dict[int, bytearray] = {}
        total_read = 0
        pending_max = 256 * 1024
        last_pts = None

        while True:
            block = stream.read(spacing)
            if len(block) < spacing:
                break
            total_read += len(block)
            if max_bytes is not None and total_read > max_bytes:
                break
            if sync_off + M2TS._TS_PACKET > len(block):
                break
            pkt = block[sync_off:sync_off + M2TS._TS_PACKET]
            if pkt[0] != M2TS._SYNC:
                continue

            payload, pid, pusi = M2TS._ts_payload(pkt)
            if payload is None or pid in skip:
                continue

            if pusi:
                if not payload:
                    pending.pop(pid, None)
                    continue
                pf = payload[0]
                if not payload.startswith(b'\x00\x00\x01') and 1 + pf > len(payload):
                    pending.pop(pid, None)
                    continue
                pending[pid] = bytearray(M2TS._pes_payload_after_pointer(payload))
            else:
                if pid not in pending:
                    continue
                pending[pid].extend(payload)
                if len(pending[pid]) > pending_max:
                    pending.pop(pid, None)
                    continue

            buf = pending.get(pid)
            if not buf or len(buf) < 14:
                continue
            if buf[0:3] != b'\x00\x00\x01':
                pending.pop(pid, None)
                continue

            flags_hi = buf[6]
            if (flags_hi & 0xC0) != 0x80:
                pending.pop(pid, None)
                continue

            flags_lo = buf[7]
            pes_hdr_remain = buf[8]
            need = 9 + pes_hdr_remain
            if len(buf) < need:
                continue
            if (flags_lo & 0xC0) == 0:
                pending.pop(pid, None)
                continue

            pts = M2TS._pts_from_pes_header(bytes(buf[9:14]))
            pending.pop(pid, None)
            last_pts = pts

        return last_pts

    def get_last_pts(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        skip_pids: Optional[set[int]] = None,
    ) -> Optional[int]:
        self._ensure_cache_valid()
        cache_key = (m2ts, max_bytes, M2TS._normalize_skip_pids(skip_pids))
        if cache_key in self._last_pts_cache:
            return self._last_pts_cache[cache_key]
        file_size = os.path.getsize(self.filename)
        # Search from file tail first; grow window progressively.
        tail_windows = [8 * 1024 * 1024, 32 * 1024 * 1024, 128 * 1024 * 1024]
        if max_bytes is not None:
            tail_windows = [max(1024 * 1024, int(max_bytes))]

        layouts = [m2ts] if m2ts is not None else [None, True, False]
        for layout in layouts:
            for win in tail_windows:
                start = max(file_size - win, 0)
                with open(self.filename, 'rb') as f:
                    pts = M2TS._scan_last_pts(
                        f, m2ts=layout, max_bytes=None, skip_pids=skip_pids, start_pos=start
                    )
                if pts is not None:
                    self._last_pts_cache[cache_key] = pts
                    return pts

        # Rare fallback: full-file pass (keeps correctness if tail lacks PUSI/PES start).
        if m2ts is not None:
            with open(self.filename, 'rb') as f:
                pts = M2TS._scan_last_pts(f, m2ts=m2ts, max_bytes=max_bytes, skip_pids=skip_pids)
            self._last_pts_cache[cache_key] = pts
            return pts
        for forced in (True, False):
            with open(self.filename, 'rb') as f:
                pts = M2TS._scan_last_pts(f, m2ts=forced, max_bytes=max_bytes, skip_pids=skip_pids)
            if pts is not None:
                self._last_pts_cache[cache_key] = pts
                return pts
        # Single-frame streams may only expose one valid PTS; in that case last == first.
        first_pts = self.get_first_pts(m2ts=m2ts, max_bytes=max_bytes, skip_pids=skip_pids, debug=False)
        self._last_pts_cache[cache_key] = first_pts
        return first_pts

    def get_duration(self, *, prefer_pcr: bool = True, use_pts_fallback: bool = True, debug: bool = False) -> int:
        self._ensure_cache_valid()
        cache_key = (bool(prefer_pcr), bool(use_pts_fallback))
        if cache_key in self._duration_cache:
            return self._duration_cache[cache_key]
        try:
            def _duration_by_pcr() -> int:
                with open(self.filename, "rb") as self.m2ts_file:
                    buffer_size = 256 * 1024
                    buffer_size -= buffer_size % self.frame_size
                    cur_pos = 0
                    first_pcr_val = -1
                    while cur_pos < buffer_size:
                        self.m2ts_file.read(7)
                        first_pcr_val = self.get_pcr_val()
                        self.m2ts_file.read(182)
                        if first_pcr_val != -1:
                            break
                        cur_pos += self.frame_size

                    buffer_size = 256 * 1024
                    buffer_size -= buffer_size % self.frame_size
                    last_pcr_val = self.get_last_pcr_val(buffer_size)
                    buffer_size *= 4

                    while last_pcr_val == -1 and buffer_size <= 1024 * 1024:
                        last_pcr_val = self.get_last_pcr_val(buffer_size)
                        buffer_size *= 4

                    if first_pcr_val == -1 or last_pcr_val == -1:
                        return 0
                    pcr_dur = max(int(last_pcr_val - first_pcr_val), 0)
                    return pcr_dur

            def _duration_by_pts() -> int:
                first_pts = self.get_first_pts(max_bytes=16 * 1024 * 1024)
                last_pts = self.get_last_pts()
                # Single-frame or sparse streams may expose only one boundary PTS.
                # Treat missing side as equal to known side so timeline remains valid.
                if first_pts is None and last_pts is not None:
                    first_pts = last_pts
                elif last_pts is None and first_pts is not None:
                    last_pts = first_pts
                if first_pts is not None and last_pts is not None:
                    pts_duration = int(last_pts - first_pts)
                    if pts_duration > 0:
                        return pts_duration
                    # Single-frame clips often have first_pts == last_pts.
                    fps = self.read_frame_rate_from_m2ts(use_ffprobe_fallback=True)
                    if fps and fps > 0:
                        one_frame_90k = int(round(90000.0 / float(fps)))
                        if one_frame_90k > 0:
                            return one_frame_90k
                return 0

            if prefer_pcr:
                dur = _duration_by_pcr()
                if dur > 0 or not use_pts_fallback:
                    self._duration_cache[cache_key] = dur
                    return dur
                dur = _duration_by_pts()
                self._duration_cache[cache_key] = dur
                return dur

            dur = _duration_by_pts()
            if dur > 0 or not use_pts_fallback:
                self._duration_cache[cache_key] = dur
                return dur
            dur = _duration_by_pcr()
            self._duration_cache[cache_key] = dur
            return dur
        except Exception:
            self._duration_cache[cache_key] = 0
            return 0

    def get_last_pcr_val(self, buffer_size) -> int:
        last_pcr_val = -1
        file_size = os.path.getsize(self.filename)
        cur_pos = max(file_size - file_size % self.frame_size - buffer_size, 0)
        buffer_end = cur_pos + buffer_size
        while cur_pos <= buffer_end - self.frame_size:
            self.m2ts_file.seek(cur_pos + 7)
            _last_pcr_val = self.get_pcr_val()
            if _last_pcr_val != -1:
                last_pcr_val = _last_pcr_val
            cur_pos += self.frame_size
        return last_pcr_val

    def unpack_bytes(self, n: int) -> Optional[int]:
        formats: dict[int, str] = {1: '>B', 2: '>H', 4: '>I', 8: '>Q'}
        try:
            data = self.m2ts_file.read(n)
        except Exception:
            return None
        if len(data) != n:
            return None
        return unpack(formats[n], data)[0]

    def get_pcr_val(self) -> int:
        b0 = self.unpack_bytes(1)
        b1 = self.unpack_bytes(1)
        b2 = self.unpack_bytes(1)
        if b0 is None or b1 is None or b2 is None:
            return -1
        af_exists = (b0 >> 5) % 2
        adaptive_field_length = b1
        pcr_exist = (b2 >> 4) % 2
        if af_exists and adaptive_field_length and pcr_exist:
            tmp = []
            for _ in range(4):
                b = self.unpack_bytes(1)
                if b is None:
                    return -1
                tmp.append(b)
            pcr = tmp[3] + (tmp[2] << 8) + (tmp[1] << 16) + (tmp[0] << 24)
            pcr_lo_raw = self.unpack_bytes(1)
            if pcr_lo_raw is None:
                return -1
            pcr_lo = pcr_lo_raw >> 7
            pcr_val = (pcr << 1) + pcr_lo
            return pcr_val
        return -1

    def read_frame_rate_from_m2ts(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = 128 * 1024 * 1024,
        sample_count: int = 24,
        use_ffprobe_fallback: bool = False,
        debug: bool = False,
    ) -> Optional[float]:
        self._ensure_cache_valid()
        fps_cache_key = (m2ts, max_bytes, int(sample_count), bool(use_ffprobe_fallback))
        if not debug and fps_cache_key in self._fps_cache:
            return self._fps_cache[fps_cache_key]

        def _probe_frame_rate_fallback(path: str) -> Optional[float]:
            exe = FFPROBE_PATH if FFPROBE_PATH else (shutil.which('ffprobe') or 'ffprobe')
            cmd = [
                exe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate,r_frame_rate",
                "-of",
                "default=nokey=1:noprint_wrappers=1",
                path,
            ]
            try:
                out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=8)
            except Exception:
                return None
            vals = [x.strip() for x in str(out or '').splitlines() if x.strip()]
            for s in vals:
                if "/" in s:
                    a, b = s.split("/", 1)
                    try:
                        num = float(a)
                        den = float(b)
                        if den != 0:
                            fps = num / den
                            if fps > 0:
                                return round(fps, 3)
                    except ValueError:
                        continue
                else:
                    try:
                        fps = float(s)
                        if fps > 0:
                            return round(fps, 3)
                    except ValueError:
                        continue
            return None

        def _iter_pes_pts(stream: BinaryIO):
            skip = {0x0000, 0x1FFF}
            start_phase, spacing, sync_off = M2TS._choose_transport_layout(stream, m2ts)
            stream.seek(start_phase)
            pending: dict[int, bytearray] = {}
            total_read = 0
            pending_max = 256 * 1024

            while True:
                block = stream.read(spacing)
                if len(block) < spacing:
                    break
                total_read += len(block)
                if max_bytes is not None and total_read > max_bytes:
                    break

                pkt = block[sync_off: sync_off + M2TS._TS_PACKET]
                if len(pkt) < M2TS._TS_PACKET or pkt[0] != M2TS._SYNC:
                    continue
                payload, pid, pusi = M2TS._ts_payload(pkt)
                if payload is None or pid in skip:
                    continue

                if pusi:
                    if not payload:
                        pending.pop(pid, None)
                        continue
                    pf = payload[0]
                    if not payload.startswith(b"\x00\x00\x01") and 1 + pf > len(payload):
                        pending.pop(pid, None)
                        continue
                    pending[pid] = bytearray(M2TS._pes_payload_after_pointer(payload))
                else:
                    if pid not in pending:
                        continue
                    pending[pid].extend(payload)
                    if len(pending[pid]) > pending_max:
                        pending.pop(pid, None)
                        continue

                buf = pending.get(pid)
                if not buf or len(buf) < 14:
                    continue
                if buf[0:3] != b"\x00\x00\x01":
                    pending.pop(pid, None)
                    continue

                stream_id = buf[3]
                flags_hi = buf[6]
                if (flags_hi & 0xC0) != 0x80:
                    pending.pop(pid, None)
                    continue
                flags_lo = buf[7]
                pes_hdr_remain = buf[8]
                need = 9 + pes_hdr_remain
                if len(buf) < need:
                    continue
                if (flags_lo & 0xC0) == 0:
                    pending.pop(pid, None)
                    continue

                pts = M2TS._pts_from_pes_header(bytes(buf[9:14]))
                pending.pop(pid, None)
                yield pid, stream_id, pts

        def _read_bits(data: bytes, bitpos: int, n: int) -> tuple[int, int]:
            v = 0
            for _ in range(n):
                byte_i = bitpos >> 3
                shift = 7 - (bitpos & 7)
                v = (v << 1) | ((data[byte_i] >> shift) & 1)
                bitpos += 1
            return v, bitpos

        def _read_ue(data: bytes, bitpos: int) -> tuple[int, int]:
            zeros = 0
            while True:
                bit, bitpos = _read_bits(data, bitpos, 1)
                if bit == 1:
                    break
                zeros += 1
            if zeros == 0:
                return 0, bitpos
            suffix, bitpos = _read_bits(data, bitpos, zeros)
            return ((1 << zeros) - 1) + suffix, bitpos

        def _read_se(data: bytes, bitpos: int) -> tuple[int, int]:
            code_num, bitpos = _read_ue(data, bitpos)
            val = (code_num + 1) // 2
            if code_num % 2 == 0:
                val = -val
            return val, bitpos

        def _rbsp_from_ebsp(ebsp: bytes) -> bytes:
            out = bytearray()
            i = 0
            while i < len(ebsp):
                if i + 2 < len(ebsp) and ebsp[i] == 0x00 and ebsp[i + 1] == 0x00 and ebsp[i + 2] == 0x03:
                    out.extend((0x00, 0x00))
                    i += 3
                else:
                    out.append(ebsp[i])
                    i += 1
            return bytes(out)

        def _h264_fps_from_sps_nal(sps_nal: bytes) -> Optional[float]:
            if len(sps_nal) < 4:
                return None
            rbsp = _rbsp_from_ebsp(sps_nal[1:])
            bitpos = 0
            try:
                profile_idc, bitpos = _read_bits(rbsp, bitpos, 8)
                _, bitpos = _read_bits(rbsp, bitpos, 8)
                _, bitpos = _read_bits(rbsp, bitpos, 8)
                _, bitpos = _read_ue(rbsp, bitpos)

                high_profiles = {100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135}
                if profile_idc in high_profiles:
                    chroma_format_idc, bitpos = _read_ue(rbsp, bitpos)
                    if chroma_format_idc == 3:
                        _, bitpos = _read_bits(rbsp, bitpos, 1)
                    _, bitpos = _read_ue(rbsp, bitpos)
                    _, bitpos = _read_ue(rbsp, bitpos)
                    _, bitpos = _read_bits(rbsp, bitpos, 1)
                    seq_scaling_matrix_present_flag, bitpos = _read_bits(rbsp, bitpos, 1)
                    if seq_scaling_matrix_present_flag:
                        max_lists = 8 if chroma_format_idc != 3 else 12
                        for i in range(max_lists):
                            present, bitpos = _read_bits(rbsp, bitpos, 1)
                            if present:
                                size = 16 if i < 6 else 64
                                last = 8
                                nxt = 8
                                for _ in range(size):
                                    if nxt != 0:
                                        delta, bitpos = _read_se(rbsp, bitpos)
                                        nxt = (last + delta + 256) % 256
                                    last = nxt if nxt != 0 else last

                _, bitpos = _read_ue(rbsp, bitpos)
                pic_order_cnt_type, bitpos = _read_ue(rbsp, bitpos)
                if pic_order_cnt_type == 0:
                    _, bitpos = _read_ue(rbsp, bitpos)
                elif pic_order_cnt_type == 1:
                    _, bitpos = _read_bits(rbsp, bitpos, 1)
                    _, bitpos = _read_se(rbsp, bitpos)
                    _, bitpos = _read_se(rbsp, bitpos)
                    n, bitpos = _read_ue(rbsp, bitpos)
                    for _ in range(n):
                        _, bitpos = _read_se(rbsp, bitpos)

                _, bitpos = _read_ue(rbsp, bitpos)
                _, bitpos = _read_bits(rbsp, bitpos, 1)
                _, bitpos = _read_ue(rbsp, bitpos)
                _, bitpos = _read_ue(rbsp, bitpos)
                frame_mbs_only_flag, bitpos = _read_bits(rbsp, bitpos, 1)
                if frame_mbs_only_flag == 0:
                    _, bitpos = _read_bits(rbsp, bitpos, 1)
                _, bitpos = _read_bits(rbsp, bitpos, 1)
                frame_cropping_flag, bitpos = _read_bits(rbsp, bitpos, 1)
                if frame_cropping_flag:
                    for _ in range(4):
                        _, bitpos = _read_ue(rbsp, bitpos)

                vui_present, bitpos = _read_bits(rbsp, bitpos, 1)
                if not vui_present:
                    return None
                ar_info, bitpos = _read_bits(rbsp, bitpos, 1)
                if ar_info:
                    ar_idc, bitpos = _read_bits(rbsp, bitpos, 8)
                    if ar_idc == 255:
                        _, bitpos = _read_bits(rbsp, bitpos, 16)
                        _, bitpos = _read_bits(rbsp, bitpos, 16)
                over_scan, bitpos = _read_bits(rbsp, bitpos, 1)
                if over_scan:
                    _, bitpos = _read_bits(rbsp, bitpos, 1)
                video_signal, bitpos = _read_bits(rbsp, bitpos, 1)
                if video_signal:
                    _, bitpos = _read_bits(rbsp, bitpos, 3)
                    _, bitpos = _read_bits(rbsp, bitpos, 1)
                    colour_desc, bitpos = _read_bits(rbsp, bitpos, 1)
                    if colour_desc:
                        _, bitpos = _read_bits(rbsp, bitpos, 24)
                chroma_loc, bitpos = _read_bits(rbsp, bitpos, 1)
                if chroma_loc:
                    _, bitpos = _read_ue(rbsp, bitpos)
                    _, bitpos = _read_ue(rbsp, bitpos)

                timing_info_present, bitpos = _read_bits(rbsp, bitpos, 1)
                if not timing_info_present:
                    return None
                num_units_in_tick, bitpos = _read_bits(rbsp, bitpos, 32)
                time_scale, bitpos = _read_bits(rbsp, bitpos, 32)
                if num_units_in_tick == 0:
                    return None
                fps = time_scale / (2.0 * num_units_in_tick)
                return round(fps, 3)
            except Exception:
                return None

        def _extract_h264_sps_from_annexb(es_data: bytes) -> Optional[bytes]:
            i = 0
            n = len(es_data)
            while i + 4 < n:
                if es_data[i: i + 3] == b"\x00\x00\x01":
                    sc = 3
                elif i + 4 < n and es_data[i: i + 4] == b"\x00\x00\x00\x01":
                    sc = 4
                else:
                    i += 1
                    continue
                start = i + sc
                j = start
                while j + 4 < n and es_data[j: j + 3] != b"\x00\x00\x01" and es_data[j: j + 4] != b"\x00\x00\x00\x01":
                    j += 1
                nal = es_data[start:j]
                if nal and (nal[0] & 0x1F) == 7:
                    return nal
                i = j
            return None

        try:
            if debug:
                sp_debug_log(
                    f'm2ts_fps_begin path={self.filename!r} m2ts={m2ts} '
                    f'max_bytes={max_bytes} sample_count={sample_count} '
                    f'use_ffprobe_fallback={use_ffprobe_fallback}'
                )
            video_stream_ids = set(range(0xE0, 0xF0))
            pts_by_pid: dict[int, list[int]] = {}
            es_by_pid: dict[int, bytearray] = {}

            with open(self.filename, "rb") as f:
                for pid, stream_id, pts in _iter_pes_pts(f):
                    if stream_id not in video_stream_ids:
                        continue
                    lst = pts_by_pid.setdefault(pid, [])
                    lst.append(pts)
                    if len(lst) >= sample_count + 1:
                        break

            if debug:
                pid_counts = {int(k): len(v) for k, v in pts_by_pid.items()}
                sp_debug_log(f'm2ts_fps_pts_collected pid_counts={pid_counts}')
            if not pts_by_pid:
                if use_ffprobe_fallback:
                    ff = _probe_frame_rate_fallback(self.filename)
                    if debug:
                        sp_debug_log(f'm2ts_fps source=ffprobe path={self.filename!r} fps={ff}')
                    self._fps_cache[fps_cache_key] = ff
                    return ff
                self._fps_cache[fps_cache_key] = None
                return None

            best_pid = max(pts_by_pid, key=lambda p: len(pts_by_pid[p]))
            if debug:
                sp_debug_log(f'm2ts_fps_best_pid pid=0x{int(best_pid):04x} count={len(pts_by_pid.get(best_pid) or [])}')
            with open(self.filename, "rb") as f:
                start_phase, spacing, sync_off = M2TS._choose_transport_layout(f, m2ts)
                if debug:
                    sp_debug_log(
                        f'm2ts_fps_layout start_phase={start_phase} spacing={spacing} sync_off={sync_off}'
                    )
                f.seek(start_phase)
                pending: dict[int, bytearray] = {}
                read_bytes = 0
                while True:
                    block = f.read(spacing)
                    if len(block) < spacing:
                        break
                    read_bytes += len(block)
                    if max_bytes is not None and read_bytes > max_bytes:
                        break
                    pkt = block[sync_off: sync_off + M2TS._TS_PACKET]
                    if len(pkt) < M2TS._TS_PACKET or pkt[0] != M2TS._SYNC:
                        continue
                    payload, pid, pusi = M2TS._ts_payload(pkt)
                    if payload is None or pid != best_pid:
                        continue
                    if pusi:
                        if not payload:
                            pending.pop(pid, None)
                            continue
                        pending[pid] = bytearray(M2TS._pes_payload_after_pointer(payload))
                    else:
                        if pid not in pending:
                            continue
                        pending[pid].extend(payload)
                    buf = pending.get(pid)
                    if not buf or len(buf) < 9 or buf[0:3] != b"\x00\x00\x01":
                        continue
                    hdr_len = 9 + buf[8]
                    if len(buf) < hdr_len:
                        continue
                    payload_es = buf[hdr_len:]
                    es_by_pid.setdefault(pid, bytearray()).extend(payload_es)
                    if len(es_by_pid[pid]) > 2 * 1024 * 1024:
                        if debug:
                            sp_debug_log(f'm2ts_fps_sps_buffer_limit pid=0x{int(pid):04x}')
                        break
                    sps = _extract_h264_sps_from_annexb(bytes(es_by_pid[pid]))
                    if sps:
                        fps = _h264_fps_from_sps_nal(sps)
                        if fps:
                            if debug:
                                sp_debug_log(f'm2ts_fps source=sps path={self.filename!r} fps={fps}')
                            self._fps_cache[fps_cache_key] = fps
                            return fps
                    pending.pop(pid, None)

            pts_list = pts_by_pid[best_pid]
            if debug:
                sp_debug_log(f'm2ts_fps_pts_list_len pid=0x{int(best_pid):04x} len={len(pts_list)}')
            if len(pts_list) < 2:
                if use_ffprobe_fallback:
                    ff = _probe_frame_rate_fallback(self.filename)
                    if debug:
                        sp_debug_log(f'm2ts_fps source=ffprobe path={self.filename!r} fps={ff}')
                    self._fps_cache[fps_cache_key] = ff
                    return ff
                self._fps_cache[fps_cache_key] = None
                return None
            deltas = []
            for a, b in zip(pts_list, pts_list[1:]):
                d = b - a
                if d > 0:
                    deltas.append(d)
            if debug:
                preview = deltas[:8]
                sp_debug_log(f'm2ts_fps_deltas count={len(deltas)} preview={preview}')
            if not deltas:
                if use_ffprobe_fallback:
                    ff = _probe_frame_rate_fallback(self.filename)
                    if debug:
                        sp_debug_log(f'm2ts_fps source=ffprobe path={self.filename!r} fps={ff}')
                    self._fps_cache[fps_cache_key] = ff
                    return ff
                self._fps_cache[fps_cache_key] = None
                return None

            delta = median(deltas)
            fps = 90000.0 / float(delta)
            if debug:
                sp_debug_log(f'm2ts_fps_raw delta={float(delta)} fps={fps}')
            common = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)
            best = min(common, key=lambda x: abs(x - fps))
            if abs(best - fps) / best < 0.01:
                if debug:
                    sp_debug_log(f'm2ts_fps source=pts path={self.filename!r} fps={fps:.6f} snapped={best}')
                self._fps_cache[fps_cache_key] = best
                return best
            fps_r = round(fps, 3)
            if debug:
                sp_debug_log(f'm2ts_fps source=pts path={self.filename!r} fps={fps_r}')
            if use_ffprobe_fallback:
                ff = _probe_frame_rate_fallback(self.filename)
                if ff is not None:
                    self._fps_cache[fps_cache_key] = ff
                    return ff
            self._fps_cache[fps_cache_key] = fps_r
            return fps_r
        except Exception:
            if use_ffprobe_fallback:
                ff = _probe_frame_rate_fallback(self.filename)
                self._fps_cache[fps_cache_key] = ff
                return ff
            self._fps_cache[fps_cache_key] = None
            return None

    def get_total_frames(self) -> int:
        self._ensure_cache_valid()
        if self._total_frames_cache is not None:
            return self._total_frames_cache
        # Accuracy-first path: use full FPS parsing.
        fps = self.read_frame_rate_from_m2ts()
        if not fps or fps <= 0.0:
            self._total_frames_cache = -1
            return -1

        # Accuracy-first duration: prefer PTS timeline, fallback to PCR only when needed.
        dur90 = self.get_duration(prefer_pcr=False, use_pts_fallback=True)
        if dur90 <= 0:
            dur90 = self.get_duration(prefer_pcr=True, use_pts_fallback=True)
        if dur90 <= 0:
            self._total_frames_cache = -1
            return -1
        dur_sec = float(dur90) / 90000.0
        frame_sec = 1.0 / float(fps)
        frames = int(round(dur_sec / frame_sec))
        self._total_frames_cache = frames if frames > 0 else -1
        return self._total_frames_cache

    @staticmethod
    def _ycbcr_to_rgba(y: int, cb: int, cr: int, alpha: int) -> tuple[int, int, int, int]:
        r = int(round(y + 1.402 * (cr - 128)))
        g = int(round(y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)))
        b = int(round(y + 1.772 * (cb - 128)))
        r = 0 if r < 0 else 255 if r > 255 else r
        g = 0 if g < 0 else 255 if g > 255 else g
        b = 0 if b < 0 else 255 if b > 255 else b
        a = 0 if alpha < 0 else 255 if alpha > 255 else alpha
        return r, g, b, a

    @staticmethod
    def _decode_pgs_rle(rle: bytes, width: int, height: int) -> Optional[bytes]:
        if width <= 0 or height <= 0:
            return None
        dst = bytearray(width * height)
        dst_i = 0
        x = 0
        y = 0
        i = 0
        n = len(rle)
        while i < n and y < height and dst_i < len(dst):
            b = rle[i]
            i += 1
            if b != 0:
                if x < width:
                    dst[dst_i] = b
                    dst_i += 1
                    x += 1
                continue
            if i >= n:
                break
            b2 = rle[i]
            i += 1
            if b2 == 0:
                # end of line
                if x < width:
                    pad = width - x
                    dst_i += pad
                x = 0
                y += 1
                continue
            has_color = (b2 & 0x80) != 0
            long_len = (b2 & 0x40) != 0
            if long_len:
                if i >= n:
                    break
                run_len = ((b2 & 0x3F) << 8) | rle[i]
                i += 1
            else:
                run_len = b2 & 0x3F
            color = 0
            if has_color:
                if i >= n:
                    break
                color = rle[i]
                i += 1
            for _ in range(run_len):
                if y >= height or dst_i >= len(dst):
                    break
                if x >= width:
                    x = 0
                    y += 1
                    if y >= height:
                        break
                dst[dst_i] = color
                dst_i += 1
                x += 1
        return bytes(dst)

    @staticmethod
    def _write_rgba_png(path: str, width: int, height: int, rgba: bytes) -> None:
        import struct
        import zlib

        def chunk(tag: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        raw = bytearray()
        stride = width * 4
        for y in range(height):
            raw.append(0)  # filter type 0
            s = y * stride
            raw.extend(rgba[s: s + stride])
        png = bytearray(b"\x89PNG\r\n\x1a\n")
        png.extend(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)))
        png.extend(chunk(b"IDAT", zlib.compress(bytes(raw), level=6)))
        png.extend(chunk(b"IEND", b""))
        with open(path, "wb") as f:
            f.write(png)

    @staticmethod
    def _extract_igs_pids(
        stream: BinaryIO,
        *,
        m2ts: Optional[bool] = None,
        max_scan_bytes: int = 8 * 1024 * 1024,
    ) -> set[int]:
        igs_pids: set[int] = set()
        pmt_pids: set[int] = set()
        parsed_pmts: set[int] = set()

        start_phase, spacing, sync_off = M2TS._choose_transport_layout(stream, m2ts)
        stream.seek(start_phase)
        total = 0
        while total < max_scan_bytes:
            block = stream.read(spacing)
            if len(block) < spacing:
                break
            total += len(block)
            pkt = block[sync_off: sync_off + M2TS._TS_PACKET]
            if len(pkt) < M2TS._TS_PACKET or pkt[0] != M2TS._SYNC:
                continue
            payload, pid, pusi = M2TS._ts_payload(pkt)
            if payload is None or not pusi or not payload:
                continue
            ptr = payload[0]
            start = 1 + ptr
            if start >= len(payload):
                continue
            sec = payload[start:]
            if len(sec) < 12:
                continue
            table_id = sec[0]
            section_len = ((sec[1] & 0x0F) << 8) | sec[2]
            section_end = 3 + section_len
            if section_end > len(sec) or section_end < 12:
                continue
            body_end = section_end - 4  # exclude CRC
            if table_id == 0x00 and pid == 0x0000:
                # PAT
                i = 8
                while i + 4 <= body_end:
                    program_number = (sec[i] << 8) | sec[i + 1]
                    pmt_pid = ((sec[i + 2] & 0x1F) << 8) | sec[i + 3]
                    if program_number != 0:
                        pmt_pids.add(pmt_pid)
                    i += 4
            elif table_id == 0x02 and pid in pmt_pids and pid not in parsed_pmts:
                parsed_pmts.add(pid)
                if body_end < 12:
                    continue
                prog_info_len = ((sec[10] & 0x0F) << 8) | sec[11]
                i = 12 + prog_info_len
                while i + 5 <= body_end:
                    stream_type = sec[i]
                    es_pid = ((sec[i + 1] & 0x1F) << 8) | sec[i + 2]
                    es_info_len = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
                    if stream_type == 0x91:
                        igs_pids.add(es_pid)
                    i += 5 + es_info_len
            if igs_pids and parsed_pmts:
                # enough for extraction
                pass
        return igs_pids

    @staticmethod
    def _codec_from_stream_type(stream_type: int, descriptors: bytes = b"") -> tuple[str, str]:
        # MPEG-TS stream_type mappings for common Blu-ray/media tracks.
        stream_type_map: dict[int, tuple[str, str]] = {
            0x01: ("video", "mpeg1video"),
            0x02: ("video", "mpeg2video"),
            0x03: ("audio", "mp3"),
            0x04: ("audio", "mp3"),
            0x0F: ("audio", "aac"),
            0x10: ("video", "mpeg4"),
            0x11: ("audio", "aac_latm"),
            0x1B: ("video", "h264"),
            0x20: ("video", "mvc"),
            0x24: ("video", "hevc"),
            0x42: ("video", "avs"),
            0xEA: ("video", "vc1"),
            0x80: ("audio", "pcm_bluray"),
            0x81: ("audio", "ac3"),
            0x82: ("audio", "dts"),
            0x83: ("audio", "truehd"),
            0x84: ("audio", "eac3"),
            0x85: ("audio", "dts_hd"),
            0x86: ("audio", "dts_hd_ma"),
            0xA1: ("audio", "eac3"),
            0xA2: ("audio", "dts_hd"),
            0x90: ("subtitle", "pgs"),
            0x91: ("subtitle", "igs"),
            0x92: ("subtitle", "textst"),
        }
        if stream_type in stream_type_map:
            return stream_type_map[stream_type]

        # For private data stream type, check descriptors for codec hints.
        if stream_type == 0x06 and descriptors:
            i = 0
            while i + 2 <= len(descriptors):
                tag = descriptors[i]
                ln = descriptors[i + 1]
                end = i + 2 + ln
                if end > len(descriptors):
                    break
                if tag == 0x6A:
                    return "audio", "ac3"
                if tag == 0x7A:
                    return "audio", "eac3"
                if tag == 0x7B:
                    return "audio", "dts"
                if tag == 0x7C:
                    return "audio", "aac"
                if tag == 0x56:
                    return "subtitle", "dvb_subtitle"
                if tag == 0x59:
                    return "subtitle", "dvb_teletext"
                i = end
        return "other", "unknown"

    @staticmethod
    def _stream_type_text(stream_type: int) -> str:
        stream_type_text_map: dict[int, str] = {
            0x01: "MPEG-1 video stream",
            0x02: "MPEG-2 video stream",
            0x1B: "MPEG-4 AVC video stream",
            0x20: "MPEG-4 MVC video stream",
            0xEA: "SMTPE VC-1 video stream",
            0x24: "HEVC video stream (including DV stream)",
            0x03: "MPEG-1 audio stream",
            0x04: "MPEG-2 audio stream",
            0x80: "LPCM audio stream (primary audio)",
            0x81: "Dolby Digital audio stream (primary audio)",
            0x82: "DTS audio stream (primary audio)",
            0x83: "Dolby Digital TrueHD audio stream (primary audio)",
            0x84: "Dolby Digital Plus audio stream (primary audio)",
            0x85: "DTS-HD High Resolution Audio audio stream (primary audio)",
            0x86: "DTS-HD Master Audio audio stream (primary audio)",
            0xA1: "Dolby Digital Plus audio stream (secondary audio)",
            0xA2: "DTS-HD audio stream (secondary audio)",
            0x90: "Presentation Graphics stream",
            0x91: "Interactive Graphics stream",
            0x92: "Text Subtitle stream",
        }
        text = stream_type_text_map.get(stream_type, "Unknown stream type")
        return f"{int(stream_type)}({text})"

    def get_tracks_info(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_scan_bytes: int = 8 * 1024 * 1024,
    ) -> list[dict[str, object]]:
        """
        Parse PAT/PMT and return elementary stream track metadata list.
        Each item includes at least pid/codec_type/codec_name.
        """
        self._ensure_cache_valid()
        cache_key = (m2ts, int(max_scan_bytes))
        cached = self._tracks_info_cache.get(cache_key)
        if cached is not None:
            return [dict(item) for item in cached]

        tracks_by_pid: dict[int, dict[str, object]] = {}
        pmt_pids: dict[int, int] = {}
        parsed_pmts: set[int] = set()
        pmt_pid_set: set[int] = set()

        with open(self.filename, "rb") as stream:
            start_phase, spacing, sync_off = self._choose_transport_layout_cached(stream, m2ts)
            stream.seek(start_phase)
            total = 0

            while total < max_scan_bytes:
                block = stream.read(spacing)
                if len(block) < spacing:
                    break
                total += len(block)
                pkt = block[sync_off: sync_off + M2TS._TS_PACKET]
                if len(pkt) < M2TS._TS_PACKET or pkt[0] != M2TS._SYNC:
                    continue

                payload, pid, pusi = M2TS._ts_payload(pkt)
                if payload is None or not pusi or not payload:
                    continue
                if pid != 0x0000 and pid not in pmt_pid_set:
                    continue

                ptr = payload[0]
                sec_pos = 1 + ptr
                if sec_pos >= len(payload):
                    continue
                sec_data = payload[sec_pos:]

                while len(sec_data) >= 3:
                    section_len = ((sec_data[1] & 0x0F) << 8) | sec_data[2]
                    section_total = 3 + section_len
                    if section_total < 12 or section_total > len(sec_data):
                        break
                    sec = sec_data[:section_total]
                    sec_data = sec_data[section_total:]
                    table_id = sec[0]
                    body_end = section_total - 4  # exclude CRC
                    if body_end < 8:
                        continue

                    if table_id == 0x00 and pid == 0x0000:
                        i = 8
                        while i + 4 <= body_end:
                            program_number = (sec[i] << 8) | sec[i + 1]
                            pmt_pid = ((sec[i + 2] & 0x1F) << 8) | sec[i + 3]
                            if program_number != 0:
                                pmt_pids[program_number] = pmt_pid
                                pmt_pid_set.add(pmt_pid)
                            i += 4
                    elif table_id == 0x02 and pid in pmt_pid_set:
                        if pid in parsed_pmts:
                            continue
                        parsed_pmts.add(pid)
                        program_number = (sec[3] << 8) | sec[4]
                        if body_end < 12:
                            continue
                        pcr_pid = ((sec[8] & 0x1F) << 8) | sec[9]
                        prog_info_len = ((sec[10] & 0x0F) << 8) | sec[11]
                        i = 12 + prog_info_len
                        while i + 5 <= body_end:
                            stream_type = sec[i]
                            es_pid = ((sec[i + 1] & 0x1F) << 8) | sec[i + 2]
                            es_info_len = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
                            desc_start = i + 5
                            desc_end = min(desc_start + es_info_len, body_end)
                            descriptors = sec[desc_start:desc_end]
                            codec_type, codec_name = M2TS._codec_from_stream_type(stream_type, descriptors)

                            lang = None
                            j = 0
                            while j + 2 <= len(descriptors):
                                tag = descriptors[j]
                                ln = descriptors[j + 1]
                                end = j + 2 + ln
                                if end > len(descriptors):
                                    break
                                if tag == 0x0A and ln >= 3:
                                    lang_bytes = descriptors[j + 2:j + 5]
                                    try:
                                        lang = lang_bytes.decode("ascii", errors="ignore").strip() or None
                                    except Exception:
                                        lang = None
                                    break
                                j = end

                            tracks_by_pid[es_pid] = {
                                "pid": es_pid,
                                "program_number": program_number,
                                "pmt_pid": pid,
                                "is_pcr_pid": es_pid == pcr_pid,
                                "stream_type": M2TS._stream_type_text(stream_type),
                                "codec_type": codec_type,
                                "codec_name": codec_name,
                                "language_from_pmt_descriptor": lang,
                            }
                            i += 5 + es_info_len
                if pmt_pids and len(parsed_pmts) >= len(set(pmt_pids.values())):
                    break

        tracks = [tracks_by_pid[k] for k in sorted(tracks_by_pid)]
        self._tracks_info_cache[cache_key] = [dict(item) for item in tracks]
        return tracks

    def get_track_info(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_scan_bytes: int = 8 * 1024 * 1024,
    ) -> list[dict[str, object]]:
        """Compatibility wrapper for singular API name."""
        return self.get_tracks_info(m2ts=m2ts, max_scan_bytes=max_scan_bytes)

    def get_m2ts_type(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_scan_bytes: int = 8 * 1024 * 1024,
    ) -> str:
        """
        Classify M2TS content type from detected track composition.
        Returns one of:
        - video
        - audio_only
        - igs_menu
        - subtitle_only
        - audio_with_subtitle
        - private_or_other
        - mixed_non_video
        - unknown
        """
        self._ensure_cache_valid()
        cache_key = (m2ts, int(max_scan_bytes))
        cached = self._m2ts_type_cache.get(cache_key)
        if cached is not None:
            return str(cached)
        tracks = self.get_tracks_info(m2ts=m2ts, max_scan_bytes=max_scan_bytes)
        v = M2TS.classify_tracks_type(tracks)
        self._m2ts_type_cache[cache_key] = str(v)
        return str(v)

    @staticmethod
    def classify_tracks_type(tracks: list[dict[str, object]]) -> str:
        """Classify M2TS content type from already parsed tracks."""
        if not tracks:
            return "unknown"

        has_video = False
        has_audio = False
        has_subtitle = False
        has_other = False
        has_igs = False

        for tr in tracks:
            ctype = str(tr.get("codec_type") or "other")
            cname = str(tr.get("codec_name") or "unknown")
            if ctype == "video":
                has_video = True
            elif ctype == "audio":
                has_audio = True
            elif ctype == "subtitle":
                has_subtitle = True
            else:
                has_other = True
            if cname == "igs":
                has_igs = True

        if has_video:
            return "video"
        if has_igs and not has_video:
            return "igs_menu"
        if has_audio and not has_subtitle and not has_other:
            return "audio_only"
        if has_subtitle and not has_audio and not has_other:
            return "subtitle_only"
        if has_audio and has_subtitle and not has_video:
            return "audio_with_subtitle"
        if has_other and not (has_video or has_audio or has_subtitle):
            return "private_or_other"
        return "mixed_non_video"

    def extract_igs_menu_png(
        self,
        output_dir: str,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = 512 * 1024 * 1024,
        max_frames: int = 1000,
        debug: bool = False,
    ) -> list[str]:
        """
        Extract IGS menu pages as PNG files (close to igstools output style).
        One image per page/state pair: normal|selected|activated x start|stop.
        """
        import os
        import struct

        os.makedirs(output_dir, exist_ok=True)
        out_files: list[str] = []

        def u8(buf: bytes, off: int) -> int:
            return buf[off]

        def u16(buf: bytes, off: int) -> int:
            return (buf[off] << 8) | buf[off + 1]

        def u24(buf: bytes, off: int) -> int:
            return (buf[off] << 16) | (buf[off + 1] << 8) | buf[off + 2]

        def parse_button_segment(body: bytes) -> Optional[dict[str, object]]:
            # Matches igstools/parser.py parse_button_segment (without command decoding usage).
            if len(body) < 13:
                return None
            width, height, fr_id, comp_num, comp_state, seq_desc, l1, l2, l3, model_flags = struct.unpack_from(
                ">HHBHBBBBBB", body, 0
            )
            _ = (fr_id, comp_num, comp_state, seq_desc, l1, l2, l3)  # parsed for alignment/compat
            p = 13
            if (model_flags & 0x80) == 0:
                if p + 10 > len(body):
                    return None
                p += 10  # composition_timeout_pts + selection_timeout_pts (5+5)
            if p + 3 > len(body):
                return None
            p += 3  # user_timeout_duration
            if p + 1 > len(body):
                return None
            page_count = body[p]
            p += 1

            pages: list[dict[str, object]] = []
            for _page_i in range(page_count):
                if p + 10 > len(body):
                    break
                page_id = body[p]
                p += 1
                p += 1  # unknown byte
                p += 8  # UO mask

                def read_effects() -> Optional[dict[str, object]]:
                    nonlocal p
                    if p + 1 > len(body):
                        return None
                    windows: dict[int, dict[str, int]] = {}
                    effects: list[dict[str, object]] = []
                    wcnt = body[p]
                    p += 1
                    for _ in range(wcnt):
                        if p + 9 > len(body):
                            return None
                        wid = body[p]
                        x = u16(body, p + 1)
                        y = u16(body, p + 3)
                        w = u16(body, p + 5)
                        h = u16(body, p + 7)
                        p += 9
                        windows[wid] = {"x": x, "y": y, "width": w, "height": h}
                    if p + 1 > len(body):
                        return None
                    ecnt = body[p]
                    p += 1
                    for _ in range(ecnt):
                        if p + 5 > len(body):
                            return None
                        duration = u24(body, p)
                        palette_idx = body[p + 3]
                        num_obj = body[p + 4]
                        p += 5
                        objs: list[dict[str, int]] = []
                        for _ in range(num_obj):
                            if p + 8 > len(body):
                                return None
                            obj_id = u16(body, p)
                            window_id = u16(body, p + 2)
                            ox = u16(body, p + 4)
                            oy = u16(body, p + 6)
                            p += 8
                            objs.append({"id": obj_id, "window": window_id, "x": ox, "y": oy})
                        effects.append({"duration": duration, "palette": palette_idx, "objects": objs})
                    return {"windows": windows, "effects": effects}

                in_eff = read_effects()
                if in_eff is None:
                    break
                out_eff = read_effects()
                if out_eff is None:
                    break

                if p + 7 > len(body):
                    break
                fr_div = body[p]
                def_button = u16(body, p + 1)
                def_activated = u16(body, p + 3)
                page_palette = body[p + 5]
                bog_count = body[p + 6]
                p += 7
                _ = (fr_div, def_button, def_activated)

                bogs: list[dict[str, object]] = []
                for _ in range(bog_count):
                    if p + 3 > len(body):
                        break
                    bog_def = u16(body, p)
                    btn_count = body[p + 2]
                    p += 3
                    _ = bog_def
                    buttons: list[dict[str, object]] = []
                    for _ in range(btn_count):
                        if p + 35 > len(body):
                            break
                        fields = struct.unpack_from(">HHB" + "H" * 15, body, p)
                        p += 35
                        button_id = fields[0]
                        bx = fields[3]
                        by = fields[4]
                        picstart_normal = fields[9]
                        picstop_normal = fields[10]
                        picstart_selected = fields[12]
                        picstop_selected = fields[13]
                        picstart_activated = fields[15]
                        picstop_activated = fields[16]
                        cmd_count = fields[17]
                        if p + cmd_count * 12 > len(body):
                            break
                        p += cmd_count * 12  # skip commands
                        buttons.append(
                            {
                                "id": button_id,
                                "x": bx,
                                "y": by,
                                "states": {
                                    "normal": {"start": picstart_normal, "stop": picstop_normal},
                                    "selected": {"start": picstart_selected, "stop": picstop_selected},
                                    "activated": {"start": picstart_activated, "stop": picstop_activated},
                                },
                            }
                        )
                    bogs.append({"buttons": buttons})

                pages.append({"id": page_id, "palette": page_palette, "bogs": bogs})

            return {"width": width, "height": height, "pages": pages}

        def overlay_rgba(dst: bytearray, dst_w: int, dst_h: int, src: bytes, src_w: int, src_h: int, x: int, y: int) -> None:
            if src_w <= 0 or src_h <= 0:
                return
            for sy in range(src_h):
                dy = y + sy
                if dy < 0 or dy >= dst_h:
                    continue
                srow = sy * src_w * 4
                drow = dy * dst_w * 4
                for sx in range(src_w):
                    dx = x + sx
                    if dx < 0 or dx >= dst_w:
                        continue
                    so = srow + sx * 4
                    do = drow + dx * 4
                    sa = src[so + 3]
                    if sa == 0:
                        continue
                    if sa == 255:
                        dst[do: do + 4] = src[so: so + 4]
                        continue
                    inv = 255 - sa
                    dr, dg, db, da = dst[do], dst[do + 1], dst[do + 2], dst[do + 3]
                    sr, sg, sb = src[so], src[so + 1], src[so + 2]
                    dst[do] = (sr * sa + dr * inv) // 255
                    dst[do + 1] = (sg * sa + dg * inv) // 255
                    dst[do + 2] = (sb * sa + db * inv) // 255
                    dst[do + 3] = min(255, sa + (da * inv) // 255)

        with open(self.filename, "rb") as f:
            igs_pids = M2TS._extract_igs_pids(f, m2ts=m2ts)
        if debug:
            print(f"[M2TS.extract_igs_menu_png] detected IGS PIDs: {[hex(x) for x in sorted(igs_pids)]}", file=sys.stderr)
        if not igs_pids:
            return out_files

        with open(self.filename, "rb") as f:
            start_phase, spacing, sync_off = M2TS._choose_transport_layout(f, m2ts)
            f.seek(start_phase)
            total = 0
            seg_buf: dict[int, bytearray] = {pid: bytearray() for pid in igs_pids}
            # Per PID parse state (similar to igstools model).
            palettes_by_pid: dict[int, list[dict[int, tuple[int, int, int, int]]]] = {pid: [] for pid in igs_pids}
            pictures_by_pid: dict[int, dict[int, dict[str, object]]] = {pid: {} for pid in igs_pids}
            pic_pending: dict[int, dict[int, dict[str, object]]] = {pid: {} for pid in igs_pids}
            menu_model_by_pid: dict[int, dict[str, object]] = {}

            while True:
                block = f.read(spacing)
                if len(block) < spacing:
                    break
                total += len(block)
                if max_bytes is not None and total > max_bytes:
                    break

                pkt = block[sync_off: sync_off + M2TS._TS_PACKET]
                if len(pkt) < M2TS._TS_PACKET or pkt[0] != M2TS._SYNC:
                    continue
                payload, pid, pusi = M2TS._ts_payload(pkt)
                if payload is None or pid not in igs_pids:
                    continue

                es = b""
                cur_pts = None
                if pusi:
                    pes = M2TS._pes_payload_after_pointer(payload)
                    if len(pes) >= 9 and pes[0:3] == b"\x00\x00\x01":
                        flags_lo = pes[7]
                        hdr_len = 9 + pes[8]
                        if (flags_lo & 0x80) and len(pes) >= 14:
                            cur_pts = M2TS._pts_from_pes_header(pes[9:14])
                        es = pes[hdr_len:] if hdr_len <= len(pes) else b""
                    else:
                        es = payload
                else:
                    es = payload
                if not es:
                    continue

                sb = seg_buf[pid]
                sb.extend(es)
                while len(sb) >= 3:
                    seg_type = sb[0]
                    seg_len = (sb[1] << 8) | sb[2]
                    if len(sb) < 3 + seg_len:
                        break
                    body = bytes(sb[3: 3 + seg_len])
                    del sb[: 3 + seg_len]

                    if seg_type == 0x14 and len(body) >= 2:
                        # Palette segment: igstools treats first 2 bytes as unknown.
                        pal: dict[int, tuple[int, int, int, int]] = {}
                        i = 2
                        while i + 5 <= len(body):
                            idx = body[i]
                            y = body[i + 1]
                            cr = body[i + 2]
                            cb = body[i + 3]
                            a = body[i + 4]
                            pal[idx] = M2TS._ycbcr_to_rgba(y, cb, cr, a)
                            i += 5
                        palettes_by_pid[pid].append(pal)
                    elif seg_type == 0x15 and len(body) >= 4:
                        # Picture segment (IGS object), supports continuation sequence.
                        obj_id = (body[0] << 8) | body[1]
                        seq = body[3]
                        first_in_seq = (seq & 0x80) != 0
                        st = pic_pending[pid].setdefault(obj_id, {"w": 0, "h": 0, "need": None, "data": bytearray()})
                        off = 4
                        if first_in_seq and len(body) >= 11:
                            total_obj = (body[4] << 16) | (body[5] << 8) | body[6]
                            w = (body[7] << 8) | body[8]
                            h = (body[9] << 8) | body[10]
                            st["w"] = w
                            st["h"] = h
                            st["need"] = max(total_obj - 4, 0)
                            st["data"] = bytearray()
                            off = 11
                        st["data"].extend(body[off:])
                        need = st.get("need")
                        if isinstance(need, int) and need >= 0 and len(st["data"]) >= need:
                            w = int(st.get("w") or 0)
                            h = int(st.get("h") or 0)
                            pix = M2TS._decode_pgs_rle(bytes(st["data"][:need]), w, h)
                            if pix is not None and w > 0 and h > 0:
                                pictures_by_pid[pid][obj_id] = {"w": w, "h": h, "pix": pix}
                            st["data"] = bytearray()
                            st["need"] = None
                    elif seg_type == 0x18:
                        # Button segment holds page/button topology/state mapping.
                        model = parse_button_segment(body)
                        if model:
                            menu_model_by_pid[pid] = model

            # Compose page-state PNG files, close to igstools menu_to_png output.
            states = (("normal", "start"), ("normal", "stop"),
                      ("selected", "start"), ("selected", "stop"),
                      ("activated", "start"), ("activated", "stop"))

            for pid in sorted(igs_pids):
                model = menu_model_by_pid.get(pid)
                if not model:
                    continue
                width = int(model.get("width") or 0)
                height = int(model.get("height") or 0)
                if width <= 0 or height <= 0:
                    continue
                palettes = palettes_by_pid.get(pid, [])
                pictures = pictures_by_pid.get(pid, {})
                pages = model.get("pages") or []
                for page in pages:
                    page_id = int(page.get("id") or 0)
                    pal_idx = int(page.get("palette") or 0)
                    pal = palettes[pal_idx] if 0 <= pal_idx < len(palettes) else {}
                    for state1, state2 in states:
                        canvas = bytearray(width * height * 4)
                        for bog in (page.get("bogs") or []):
                            for btn in (bog.get("buttons") or []):
                                # Same fallback preference as igstools.
                                prefs = ((state1, state2), (state1, "start"), ("normal", state2), ("normal", "start"))
                                chosen_id = None
                                btn_states = btn.get("states") or {}
                                for s1, s2 in prefs:
                                    sub = btn_states.get(s1) or {}
                                    pid_obj = sub.get(s2)
                                    if isinstance(pid_obj, int) and pid_obj != 0xFFFF and pid_obj in pictures:
                                        chosen_id = pid_obj
                                        break
                                if chosen_id is None:
                                    continue
                                pic = pictures[chosen_id]
                                pw = int(pic["w"])
                                ph = int(pic["h"])
                                pix = pic["pix"]
                                rgba = bytearray(pw * ph * 4)
                                for i_px, idx in enumerate(pix):
                                    r, g, b, a = pal.get(idx, (0, 0, 0, 0))
                                    o = i_px * 4
                                    rgba[o] = r
                                    rgba[o + 1] = g
                                    rgba[o + 2] = b
                                    rgba[o + 3] = a
                                overlay_rgba(canvas, width, height, bytes(rgba), pw, ph, int(btn.get("x") or 0), int(btn.get("y") or 0))
                        if len(out_files) >= max_frames:
                            return out_files
                        name = f"igs_pid{pid:04x}_page{page_id:03d}_{state1}_{state2}.png"
                        out_path = os.path.join(output_dir, name)
                        M2TS._write_rgba_png(out_path, width, height, bytes(canvas))
                        out_files.append(out_path)
                        if debug:
                            print(f"[M2TS.extract_igs_menu_png] write {name} ({width}x{height})", file=sys.stderr)

        return out_files

    @staticmethod
    def _mpls_stream_entry_from_pid(pid: int) -> StreamEntry:
        entry = StreamEntry()
        entry["Length"] = 9
        entry["StreamType"] = 1
        entry["RefToStreamPID"] = int(pid)
        return entry

    @staticmethod
    def _mpls_stream_attributes_from_clpi_info(sc_info: InfoDict) -> StreamAttributes:
        attrs = StreamAttributes()
        attrs["Length"] = 5
        stream_type = int(sc_info["StreamCodingType"])
        attrs["StreamCodingType"] = stream_type

        if stream_type in (0x01, 0x02, 0x1B, 0xEA):
            attrs["VideoFormat"] = int(sc_info.get("VideoFormat", 0))
            attrs["FrameRate"] = int(sc_info.get("FrameRate", 0))
        elif stream_type == 0x24:
            attrs["VideoFormat"] = int(sc_info.get("VideoFormat", 0))
            attrs["FrameRate"] = int(sc_info.get("FrameRate", 0))
            attrs["DynamicRangeType"] = int(sc_info.get("DynamicRangeType", 0))
            attrs["ColorSpace"] = int(sc_info.get("ColorSpace", 0))
            attrs["CRFlag"] = int(sc_info.get("CRFlag", 0))
            attrs["HDRPlusFlag"] = int(sc_info.get("HDRPlusFlag", 0))
        elif stream_type in (0x03, 0x04, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0xA1, 0xA2):
            attrs["AudioFormat"] = int(sc_info.get("AudioFormat", 0))
            attrs["SampleRate"] = int(sc_info.get("SampleRate", 0))
            attrs["LanguageCode"] = str(sc_info.get("Language", "und"))[:3].ljust(3, " ")
        elif stream_type in (0x90, 0x91):
            attrs["LanguageCode"] = str(sc_info.get("Language", "und"))[:3].ljust(3, " ")
        elif stream_type == 0x92:
            attrs["CharacterCode"] = int(sc_info.get("CharCode", 0))
            attrs["LanguageCode"] = str(sc_info.get("Language", "und"))[:3].ljust(3, " ")
        else:
            # Fallback for unknown/unsupported stream coding types: preserve stream type and force und language.
            attrs["StreamCodingType"] = stream_type
            attrs["LanguageCode"] = "und"
        return attrs

    @staticmethod
    def _stn_bucket_name_for_stream_type(stream_type: int) -> Optional[str]:
        if stream_type in (0x01, 0x02, 0x1B, 0xEA, 0x24):
            return "PrimaryVideoStreamEntries"
        if stream_type in (0x03, 0x04, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86):
            return "PrimaryAudioStreamEntries"
        if stream_type in (0xA1, 0xA2):
            return "SecondaryAudioStreamEntries"
        if stream_type in (0x90, 0x92):
            return "PrimaryPGStreamEntries"
        if stream_type == 0x91:
            return "PrimaryIGStreamEntries"
        if stream_type == 0x20:
            return "SecondaryVideoStreamEntries"
        return None

__all__ = ["M2TS"]

