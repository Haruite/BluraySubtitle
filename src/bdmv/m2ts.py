import os
import shutil
import subprocess
import sys
from typing import Optional, BinaryIO

from .core import InfoDict, unpack_bytes
from .structures.stream_attributes import StreamAttributes
from .structures.stream_entry import StreamEntry
from src.core import FFPROBE_PATH
from src.core.i18n import sp_debug_log, translate_text
from src.exports.utils import run_command


class _BitReader:
    """Minimal big-endian bit reader for AVC/HEVC parameter sets."""

    def __init__(self, data: bytes):
        self._value = int.from_bytes(data, 'big')
        self._length = len(data) * 8
        self._position = 0

    def read(self, count: int) -> int:
        if count < 0 or self._position + count > self._length:
            raise ValueError('Parameter set ended before the requested bits')
        self._position += count
        return (self._value >> (self._length - self._position)) & ((1 << count) - 1) if count else 0

    def unsigned_golomb(self) -> int:
        leading_zeroes = 0
        while self.read(1) == 0:
            leading_zeroes += 1
            if leading_zeroes > 31:
                raise ValueError('Invalid exponential-Golomb code')
        return (1 << leading_zeroes) - 1 + self.read(leading_zeroes)

    def signed_golomb(self) -> int:
        code_number = self.unsigned_golomb()
        value = (code_number + 1) // 2
        return -value if code_number % 2 == 0 else value


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
        self._fps_cache: dict[tuple[Optional[bool], Optional[int], bool], Optional[float]] = {}
        self._total_frames_cache: Optional[int] = None


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
        try:
            stat = os.stat(self.filename)
            sig = (int(stat.st_size), int(stat.st_mtime_ns))
        except OSError:
            sig = None
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
    def _choose_transport_layout(stream: BinaryIO, m2ts: Optional[bool]) -> tuple[int, int, int]:
        """Return packet phase, stride, and TS-header offset for M2TS or plain MPEG-TS input."""
        position = stream.tell()
        sample = stream.read(512 * 1024)
        stream.seek(position)
        layouts = ((M2TS.frame_size, 4),) if m2ts is True else ((M2TS._TS_PACKET, 0),) if m2ts is False else (
            (M2TS.frame_size, 4), (M2TS._TS_PACKET, 0), (M2TS.frame_size, 0)
        )
        best_score, best_phase, best_stride, best_sync_offset = -1, 0, layouts[0][0], layouts[0][1]
        for stride, sync_offset in layouts:
            for phase in range(stride):
                packet_end = len(sample) - M2TS._TS_PACKET + 1
                score = sample[phase + sync_offset:packet_end:stride].count(b'\x47')
                if score > best_score:
                    best_score, best_phase, best_stride, best_sync_offset = score, phase, stride, sync_offset
        return best_phase, best_stride, best_sync_offset

    @staticmethod
    def _iter_transport_packets(
        stream: BinaryIO,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        start_pos: Optional[int] = None,
        layout: Optional[tuple[int, int, int]] = None,
    ):
        """Yield aligned 188-byte TS packets while reading the source in large blocks."""
        packet_phase, stride, sync_offset = layout or M2TS._choose_transport_layout(stream, m2ts)
        scan_pos = packet_phase if start_pos is None else max(packet_phase, int(start_pos))
        scan_pos = packet_phase + ((scan_pos - packet_phase) // stride) * stride
        stream.seek(scan_pos)
        remaining = None if max_bytes is None else max(int(max_bytes), 0)
        chunk_size = 4 * 1024 * 1024
        chunk_size -= chunk_size % stride
        while remaining is None or remaining >= stride:
            read_size = chunk_size if remaining is None else min(chunk_size, remaining - remaining % stride)
            if read_size < stride:
                break
            block = stream.read(read_size)
            complete_bytes = len(block) - len(block) % stride
            for offset in range(0, complete_bytes, stride):
                packet = block[offset + sync_offset:offset + sync_offset + M2TS._TS_PACKET]
                if len(packet) == M2TS._TS_PACKET and packet[0] == M2TS._SYNC:
                    yield packet
            if remaining is not None:
                remaining -= complete_bytes
            if len(block) < read_size or complete_bytes < len(block):
                break

    @staticmethod
    def _scan_first_pts(
        stream: BinaryIO,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = None,
        skip_pids: Optional[set[int]] = None,
        debug: bool = False,
    ) -> Optional[int]:
        skip = set(skip_pids or ()) | {0x0000, 0x1FFF}
        layout = M2TS._choose_transport_layout(stream, m2ts)
        if debug:
            print(translate_text(
                '[M2TS.get_first_pts] seek={seek} stride={stride} sync offset={offset}'
            ).format(seek=layout[0], stride=layout[1], offset=layout[2]), file=sys.stderr)

        pending: dict[int, bytearray] = {}
        pending_max = 256 * 1024
        for packet in M2TS._iter_transport_packets(stream, max_bytes=max_bytes, layout=layout):
            payload, pid, pusi = M2TS._ts_payload(packet)
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
                print(translate_text(
                    '[M2TS.get_first_pts] first PTS from PID 0x{pid} = {pts}'
                ).format(pid=f'{pid:04x}', pts=pts), file=sys.stderr)
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
        skip = set(skip_pids or ()) | {0x0000, 0x1FFF}
        pending: dict[int, bytearray] = {}
        pending_max = 256 * 1024
        last_pts = None

        for packet in M2TS._iter_transport_packets(stream, m2ts=m2ts, max_bytes=max_bytes, start_pos=start_pos):
            payload, pid, pusi = M2TS._ts_payload(packet)
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

    @staticmethod
    def _pcr_from_packet(packet: bytes) -> Optional[int]:
        """Return the 33-bit PCR base in 90 kHz units; the 27 MHz extension is not needed for clip duration."""
        adaptation_control = (packet[3] >> 4) & 0x03 if len(packet) == M2TS._TS_PACKET else 0
        if adaptation_control & 0x02 and packet[4] >= 7 and packet[5] & 0x10:
            return (unpack_bytes(packet, 6, 4) << 1) + (packet[10] >> 7)
        return None

    def get_duration(self, *, prefer_pcr: bool = True, use_pts_fallback: bool = True, debug: bool = False) -> int:
        self._ensure_cache_valid()
        cache_key = (bool(prefer_pcr), bool(use_pts_fallback))
        if cache_key in self._duration_cache:
            return self._duration_cache[cache_key]

        duration = 0
        for clock in (('pcr', 'pts') if prefer_pcr else ('pts', 'pcr'))[:2 if use_pts_fallback else 1]:
            if clock == 'pcr':
                try:
                    with open(self.filename, 'rb') as stream:
                        layout = self._choose_transport_layout_cached(stream, None)
                        first_pcr = next((value for packet in M2TS._iter_transport_packets(
                            stream, max_bytes=256 * 1024, layout=layout
                        ) if (value := M2TS._pcr_from_packet(packet)) is not None), None)
                        last_pcr = None
                        file_size = os.path.getsize(self.filename)
                        for window_size in (256 * 1024, 1024 * 1024):
                            for packet in M2TS._iter_transport_packets(
                                stream, max_bytes=window_size, start_pos=max(file_size - window_size, 0), layout=layout
                            ):
                                value = M2TS._pcr_from_packet(packet)
                                if value is not None:
                                    last_pcr = value
                            if last_pcr is not None:
                                break
                    duration = max(int(last_pcr - first_pcr), 0) if first_pcr is not None and last_pcr is not None else 0
                except OSError:
                    duration = 0
            else:
                first_pts = self.get_first_pts(max_bytes=16 * 1024 * 1024)
                last_pts = self.get_last_pts()
                if first_pts is not None and last_pts is not None:
                    duration = int(last_pts - first_pts)
                    if duration <= 0:
                        fps = self.read_frame_rate_from_m2ts(use_ffprobe_fallback=True)
                        duration = int(round(90000.0 / fps)) if fps else 0
            if duration > 0:
                break

        self._duration_cache[cache_key] = duration
        return duration
    @staticmethod
    def _frame_rate_from_parameter_sets(elementary_stream: bytes, codec_name: str) -> Optional[float]:
        """Read AVC SPS or HEVC VPS timing using the same parameter-set rules as tsMuxer."""
        search_position = 0
        while True:
            start_code = elementary_stream.find(b'\x00\x00\x01', search_position)
            if start_code < 0:
                return None
            nal_start = start_code + 3
            next_start_code = elementary_stream.find(b'\x00\x00\x01', nal_start)
            nal = elementary_stream[nal_start:next_start_code if next_start_code >= 0 else len(elementary_stream)]
            search_position = next_start_code if next_start_code >= 0 else len(elementary_stream)
            try:
                if codec_name == 'hevc' and len(nal) >= 4 and ((nal[0] >> 1) & 0x3F) == 32:
                    # HEVC timing is normally carried by the VPS on Blu-ray. Unlike AVC, HEVC time_scale is
                    # already the frame clock and is not divided by two (tsMuxer HevcVpsUnit::deserialize).
                    bits = _BitReader(nal[2:].replace(b'\x00\x00\x03', b'\x00\x00'))
                    bits.read(12)
                    max_sub_layers = bits.read(3) + 1
                    bits.read(17)
                    bits.read(3 + 5 + 32 + 1 + 1 + 32 + 14 + 8)
                    profile_flags = [(bits.read(1), bits.read(1)) for _ in range(max_sub_layers - 1)]
                    if max_sub_layers > 1:
                        bits.read((8 - (max_sub_layers - 1)) * 2)
                    for profile_present, level_present in profile_flags:
                        if profile_present:
                            bits.read(88)
                        if level_present:
                            bits.read(8)
                    first_ordering_layer = 0 if bits.read(1) else max_sub_layers - 1
                    for _ in range(first_ordering_layer, max_sub_layers):
                        bits.unsigned_golomb()
                        bits.unsigned_golomb()
                        bits.unsigned_golomb()
                    max_layer_id = bits.read(6)
                    layer_sets = bits.unsigned_golomb()
                    for _ in range(layer_sets):
                        bits.read(max_layer_id + 1)
                    if bits.read(1):
                        units_in_tick, time_scale = bits.read(32), bits.read(32)
                        return time_scale / units_in_tick if units_in_tick else None

                if codec_name == 'h264' and nal and (nal[0] & 0x1F) == 7:
                    bits = _BitReader(nal[1:].replace(b'\x00\x00\x03', b'\x00\x00'))
                    profile_idc = bits.read(8)
                    bits.read(16)
                    bits.unsigned_golomb()
                    if profile_idc in {44, 83, 86, 100, 110, 118, 122, 128, 134, 135, 138, 139, 244}:
                        chroma_format_idc = bits.unsigned_golomb()
                        if chroma_format_idc == 3:
                            bits.read(1)
                        bits.unsigned_golomb()
                        bits.unsigned_golomb()
                        bits.read(1)
                        if bits.read(1):
                            for scaling_list in range(8 if chroma_format_idc != 3 else 12):
                                if not bits.read(1):
                                    continue
                                last_scale = next_scale = 8
                                for _ in range(16 if scaling_list < 6 else 64):
                                    if next_scale:
                                        next_scale = (last_scale + bits.signed_golomb() + 256) % 256
                                    last_scale = next_scale or last_scale
                    bits.unsigned_golomb()
                    pic_order_count_type = bits.unsigned_golomb()
                    if pic_order_count_type == 0:
                        bits.unsigned_golomb()
                    elif pic_order_count_type == 1:
                        bits.read(1)
                        bits.signed_golomb()
                        bits.signed_golomb()
                        for _ in range(bits.unsigned_golomb()):
                            bits.signed_golomb()
                    bits.unsigned_golomb()
                    bits.read(1)
                    bits.unsigned_golomb()
                    bits.unsigned_golomb()
                    if not bits.read(1):
                        bits.read(1)
                    bits.read(1)
                    if bits.read(1):
                        for _ in range(4):
                            bits.unsigned_golomb()
                    if not bits.read(1):
                        continue
                    if bits.read(1) and bits.read(8) == 255:
                        bits.read(32)
                    if bits.read(1):
                        bits.read(1)
                    if bits.read(1):
                        bits.read(4)
                        if bits.read(1):
                            bits.read(24)
                    if bits.read(1):
                        bits.unsigned_golomb()
                        bits.unsigned_golomb()
                    if bits.read(1):
                        units_in_tick, time_scale = bits.read(32), bits.read(32)
                        return time_scale / (2.0 * units_in_tick) if units_in_tick else None
            except (IndexError, ValueError):
                pass
            if next_start_code < 0:
                return None

    def read_frame_rate_from_m2ts(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_bytes: Optional[int] = 128 * 1024 * 1024,
        use_ffprobe_fallback: bool = False,
        debug: bool = False,
    ) -> Optional[float]:
        self._ensure_cache_valid()
        cache_key = (m2ts, max_bytes, bool(use_ffprobe_fallback))
        if not debug and cache_key in self._fps_cache:
            return self._fps_cache[cache_key]

        frame_rate = None
        try:
            video_tracks = [track for track in self.get_tracks_info(m2ts=m2ts) if track.get('codec_type') == 'video']
            if video_tracks:
                video_pid = int(video_tracks[0]['pid'])
                codec_name = str(video_tracks[0].get('codec_name') or '')
                elementary_stream = bytearray()
                with open(self.filename, 'rb') as stream:
                    for packet in M2TS._iter_transport_packets(stream, m2ts=m2ts, max_bytes=max_bytes):
                        payload, pid, payload_unit_start = M2TS._ts_payload(packet)
                        if payload is None or pid != video_pid:
                            continue
                        if payload_unit_start:
                            pes = M2TS._pes_payload_after_pointer(payload)
                            if len(pes) < 9 or pes[:3] != b'\x00\x00\x01':
                                continue
                            header_end = 9 + pes[8]
                            if header_end <= len(pes):
                                elementary_stream.extend(pes[header_end:])
                        else:
                            elementary_stream.extend(payload)
                        if len(elementary_stream) >= 2 * 1024 * 1024:
                            break
                frame_rate = M2TS._frame_rate_from_parameter_sets(bytes(elementary_stream), codec_name)
                if debug:
                    sp_debug_log(translate_text(
                        'M2TS native frame rate: path={path!r} PID=0x{pid} codec={codec!r} fps={fps}'
                    ).format(path=self.filename, pid=f'{video_pid:04x}', codec=codec_name, fps=frame_rate))
        except (OSError, TypeError, ValueError):
            frame_rate = None

        if frame_rate is None and use_ffprobe_fallback:
            executable = FFPROBE_PATH if FFPROBE_PATH else (shutil.which('ffprobe') or 'ffprobe')
            command = [
                executable, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                'stream=avg_frame_rate,r_frame_rate', '-of', 'default=nokey=1:noprint_wrappers=1', self.filename,
            ]
            try:
                output = run_command(
                    command, text=True, stderr=subprocess.DEVNULL, timeout=8, capture_output=True, check=True
                ).stdout
                for value in (line.strip() for line in str(output or '').splitlines() if line.strip()):
                    numerator, separator, denominator = value.partition('/')
                    parsed = float(numerator) / float(denominator) if separator and float(denominator) else float(value)
                    if parsed > 0:
                        frame_rate = parsed
                        break
            except (OSError, ValueError, subprocess.SubprocessError):
                frame_rate = None
            if debug:
                sp_debug_log(translate_text('M2TS ffprobe frame rate: path={path!r} fps={fps}').format(
                    path=self.filename, fps=frame_rate
                ))

        self._fps_cache[cache_key] = frame_rate
        return frame_rate

    def get_total_frames(self) -> int:
        self._ensure_cache_valid()
        if self._total_frames_cache is not None:
            return self._total_frames_cache
        # Accuracy-first path: use full FPS parsing.
        fps = self.read_frame_rate_from_m2ts(use_ffprobe_fallback=True)
        if not fps or fps <= 0.0:
            self._total_frames_cache = -1
            return -1

        # Blu-ray clip duration follows the transport PCR clock used by tsMuxer; get_duration falls back to PTS.
        dur90 = self.get_duration()
        if dur90 <= 0:
            self._total_frames_cache = -1
            return -1
        dur_sec = float(dur90) / 90000.0
        frame_sec = 1.0 / float(fps)
        frames = int(round(dur_sec / frame_sec))
        self._total_frames_cache = frames if frames > 0 else -1
        return self._total_frames_cache

    def count_video_frames_up_to(
        self,
        limit: int,
        *,
        m2ts: Optional[bool] = None,
        video_pid: Optional[int] = None,
        codec_name: Optional[str] = None,
    ) -> int:
        """Count compressed video access units, stopping as soon as ``limit`` is reached.

        AVC and HEVC use the same first-slice boundaries as tsMuxer. MPEG-1/2
        and VC-1 use their picture/frame start codes. The bounded scan is used
        to reject normal video before the SP still-image check starts a decoder.
        ``-1`` means that the video codec or stream could not be identified.
        """
        if limit <= 0:
            raise ValueError('Frame count limit must be positive')

        try:
            if video_pid is None or not codec_name:
                video_track = next(
                    (track for track in self.get_tracks_info(m2ts=m2ts) if track.get('codec_type') == 'video'),
                    None,
                )
                if video_track is None:
                    return -1
                video_pid = int(video_track['pid'])
                codec_name = str(video_track.get('codec_name') or '')
            else:
                video_pid = int(video_pid)
                codec_name = str(codec_name)
        except (KeyError, TypeError, ValueError):
            return -1

        codec = codec_name.lower()
        if codec not in {'h264', 'mvc', 'hevc', 'mpeg1video', 'mpeg2video', 'vc1'}:
            return -1

        frame_count = 0
        elementary_stream = bytearray()
        start_code = b'\x00\x00\x01'
        pending_nal_start: Optional[int] = None
        required_nal_bytes = 16 if codec in {'h264', 'mvc'} else 3 if codec == 'hevc' else 1

        def _count_nal_unit(nal: bytes) -> None:
            nonlocal frame_count
            if not nal:
                return
            if codec == 'hevc':
                nal_type = (nal[0] >> 1) & 0x3F
                if nal_type <= 31 and len(nal) >= 3 and nal[2] & 0x80:
                    frame_count += 1
                return
            if codec in {'h264', 'mvc'}:
                if (nal[0] & 0x1F) not in {1, 2, 5} or len(nal) < 2:
                    return
                try:
                    bits = _BitReader(nal[1:].replace(b'\x00\x00\x03', b'\x00\x00'))
                    if bits.unsigned_golomb() == 0:
                        frame_count += 1
                except ValueError:
                    return
                return
            if codec in {'mpeg1video', 'mpeg2video'} and nal[0] == 0x00:
                frame_count += 1
            elif codec == 'vc1' and nal[0] == 0x0D:
                frame_count += 1

        def _scan_nal_units(*, final: bool = False) -> None:
            nonlocal pending_nal_start
            while frame_count < limit:
                if pending_nal_start is None:
                    pending_nal_start = elementary_stream.find(start_code)
                if pending_nal_start < 0:
                    if final:
                        elementary_stream.clear()
                    elif len(elementary_stream) >= len(start_code):
                        del elementary_stream[:-(len(start_code) - 1)]
                    pending_nal_start = None
                    return

                nal_start = pending_nal_start + len(start_code)
                next_start = elementary_stream.find(start_code, nal_start)
                nal_end = next_start if next_start >= 0 else len(elementary_stream)
                if nal_end - nal_start < required_nal_bytes and next_start < 0 and not final:
                    if pending_nal_start:
                        del elementary_stream[:pending_nal_start]
                        pending_nal_start = 0
                    return

                _count_nal_unit(bytes(elementary_stream[nal_start:min(nal_end, nal_start + required_nal_bytes)]))
                if next_start >= 0:
                    del elementary_stream[:next_start]
                    pending_nal_start = 0
                    continue

                if len(elementary_stream) >= len(start_code):
                    del elementary_stream[:-(len(start_code) - 1)]
                pending_nal_start = None
                return

        try:
            with open(self.filename, 'rb') as stream:
                for packet in M2TS._iter_transport_packets(stream, m2ts=m2ts):
                    payload, pid, payload_unit_start = M2TS._ts_payload(packet)
                    if payload is None or pid != video_pid:
                        continue
                    if payload_unit_start:
                        pes = M2TS._pes_payload_after_pointer(payload)
                        if len(pes) < 9 or pes[:3] != start_code:
                            continue
                        header_end = 9 + pes[8]
                        if header_end > len(pes):
                            continue
                        elementary_stream.extend(pes[header_end:])
                    else:
                        elementary_stream.extend(payload)
                    _scan_nal_units()
                    if frame_count >= limit:
                        return frame_count
            _scan_nal_units(final=True)
            return frame_count
        except OSError:
            return -1

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

    _PSI_ASSEMBLY_MAX = 4096

    @staticmethod
    def _psi_collector() -> dict[str, object]:
        return {"buf": bytearray(), "expect_ptr": True}

    @staticmethod
    def _psi_feed(col: dict[str, object], payload: bytes, pusi: bool, max_buf: int) -> None:
        """
        Append TS payload bytes for one PAT/PMT PID, matching tsMuxer: new PUSI starts a payload unit
        (clear buffer); continuation packets append until a full PSI section is assembled.
        """
        buf: bytearray = col["buf"]  # type: ignore[assignment]
        if pusi:
            buf.clear()
            col["expect_ptr"] = True
            buf.extend(payload)
        else:
            if len(buf) == 0:
                return
            if len(buf) + len(payload) > max_buf:
                buf.clear()
                col["expect_ptr"] = True
                return
            buf.extend(payload)

    @staticmethod
    def _psi_apply_section(
        sec: bytes,
        stream_pid: int,
        tracks_by_pid: dict[int, dict[str, object]],
        pmt_pids: dict[int, int],
        pmt_pid_set: set[int],
        parsed_pmts: set[int],
    ) -> None:
        if len(sec) < 12:
            return
        table_id = sec[0]
        section_total = len(sec)
        body_end = section_total - 4
        if body_end < 8:
            return

        if table_id == 0x00 and stream_pid == 0x0000:
            i = 8
            while i + 4 <= body_end:
                program_number = (sec[i] << 8) | sec[i + 1]
                pmt_pid = ((sec[i + 2] & 0x1F) << 8) | sec[i + 3]
                if program_number != 0:
                    pmt_pids[program_number] = pmt_pid
                    pmt_pid_set.add(pmt_pid)
                i += 4
            return

        if table_id == 0x02 and stream_pid in pmt_pid_set:
            if stream_pid in parsed_pmts:
                return
            parsed_pmts.add(stream_pid)
            program_number = (sec[3] << 8) | sec[4]
            if body_end < 12:
                return
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
                        lang = lang_bytes.decode("ascii", errors="ignore").strip() or None

                        break
                    j = end

                tracks_by_pid[es_pid] = {
                    "pid": es_pid,
                    "program_number": program_number,
                    "pmt_pid": stream_pid,
                    "is_pcr_pid": es_pid == pcr_pid,
                    "stream_type": M2TS._stream_type_text(stream_type),
                    "codec_type": codec_type,
                    "codec_name": codec_name,
                    "language_from_pmt_descriptor": lang,
                }
                i += 5 + es_info_len

    @staticmethod
    def _psi_drain(
        col: dict[str, object],
        stream_pid: int,
        tracks_by_pid: dict[int, dict[str, object]],
        pmt_pids: dict[int, int],
        pmt_pid_set: set[int],
        parsed_pmts: set[int],
    ) -> None:
        """Extract every complete PSI section from the front of the assembly buffer (ISO 13818-1)."""
        buf: bytearray = col["buf"]  # type: ignore[assignment]
        max_ptr = M2TS._TS_PACKET - 4
        while True:
            if len(buf) < 3:
                return
            if col["expect_ptr"]:  # type: ignore[operator]
                ptr = buf[0]
                if ptr == 0xFF:
                    buf.clear()
                    col["expect_ptr"] = True
                    return
                if ptr > max_ptr:
                    buf.clear()
                    col["expect_ptr"] = True
                    return
                if len(buf) < 1 + ptr + 3:
                    return
                off = 1 + ptr
                section_len = ((buf[off + 1] & 0x0F) << 8) | buf[off + 2]
                section_total = 3 + section_len
                if section_total < 12:
                    buf.clear()
                    col["expect_ptr"] = True
                    return
                if len(buf) < off + section_total:
                    return
                sec = bytes(memoryview(buf)[off : off + section_total])
                del buf[: off + section_total]
                col["expect_ptr"] = len(buf) == 0
                M2TS._psi_apply_section(sec, stream_pid, tracks_by_pid, pmt_pids, pmt_pid_set, parsed_pmts)
                continue

            section_len = ((buf[1] & 0x0F) << 8) | buf[2]
            section_total = 3 + section_len
            if section_total < 12:
                buf.clear()
                col["expect_ptr"] = True
                return
            if len(buf) < section_total:
                return
            sec = bytes(memoryview(buf)[:section_total])
            del buf[:section_total]
            col["expect_ptr"] = len(buf) == 0
            M2TS._psi_apply_section(sec, stream_pid, tracks_by_pid, pmt_pids, pmt_pid_set, parsed_pmts)

    def get_tracks_info(
        self,
        *,
        m2ts: Optional[bool] = None,
        max_scan_bytes: int = 8 * 1024 * 1024,
    ) -> list[dict[str, object]]:
        """
        Parse PAT/PMT and return elementary stream track metadata list.
        Each item includes at least pid/codec_type/codec_name.

        PAT/PMT sections may span multiple TS packets (common on UHD / long PMT); assembly matches
        tsMuxer (``TSDemuxer::getTrackList`` + ``TS_program_map_section::isFullBuff`` semantics).
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
        psi_cols: dict[int, dict[str, object]] = {0: M2TS._psi_collector()}
        max_psi = M2TS._PSI_ASSEMBLY_MAX

        with open(self.filename, 'rb') as stream:
            layout = self._choose_transport_layout_cached(stream, m2ts)
            for packet in M2TS._iter_transport_packets(stream, max_bytes=max_scan_bytes, layout=layout):
                payload, pid, pusi = M2TS._ts_payload(packet)
                if payload is None or not payload:
                    continue
                if pid != 0x0000 and pid not in pmt_pid_set:
                    continue

                col = psi_cols.setdefault(pid, M2TS._psi_collector())
                M2TS._psi_feed(col, payload, pusi, max_psi)
                M2TS._psi_drain(col, pid, tracks_by_pid, pmt_pids, pmt_pid_set, parsed_pmts)
                for new_pmt in list(pmt_pid_set):
                    psi_cols.setdefault(new_pmt, M2TS._psi_collector())

                if pmt_pids and len(parsed_pmts) >= len(set(pmt_pids.values())):
                    break

        tracks = [tracks_by_pid[k] for k in sorted(tracks_by_pid)]
        self._tracks_info_cache[cache_key] = [dict(item) for item in tracks]
        return tracks


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
            elif ctype in ("subtitle", "subtitles"):
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

        def u16(buf: bytes, off: int) -> int:
            return (buf[off] << 8) | buf[off + 1]

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
                        duration = (body[p] << 16) | (body[p + 1] << 8) | body[p + 2]
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

        igs_pids = {int(track['pid']) for track in self.get_tracks_info(m2ts=m2ts) if track.get('codec_name') == 'igs'}
        if debug:
            print(translate_text(
                '[M2TS.extract_igs_menu_png] detected IGS PIDs: {pids}'
            ).format(pids=[hex(pid) for pid in sorted(igs_pids)]), file=sys.stderr)
        if not igs_pids:
            return out_files

        with open(self.filename, 'rb') as stream:
            segment_buffers: dict[int, bytearray] = {pid: bytearray() for pid in igs_pids}
            # Per-PID state follows the igstools model while PSI/PID discovery stays shared with track parsing.
            palettes_by_pid: dict[int, list[dict[int, tuple[int, int, int, int]]]] = {pid: [] for pid in igs_pids}
            pictures_by_pid: dict[int, dict[int, dict[str, object]]] = {pid: {} for pid in igs_pids}
            pic_pending: dict[int, dict[int, dict[str, object]]] = {pid: {} for pid in igs_pids}
            menu_model_by_pid: dict[int, dict[str, object]] = {}

            for packet in M2TS._iter_transport_packets(stream, m2ts=m2ts, max_bytes=max_bytes):
                payload, pid, pusi = M2TS._ts_payload(packet)
                if payload is None or pid not in igs_pids:
                    continue
                if pusi:
                    pes = M2TS._pes_payload_after_pointer(payload)
                    if len(pes) >= 9 and pes[0:3] == b"\x00\x00\x01":
                        hdr_len = 9 + pes[8]
                        es = pes[hdr_len:] if hdr_len <= len(pes) else b""
                    else:
                        es = payload
                else:
                    es = payload
                if not es:
                    continue

                sb = segment_buffers[pid]
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
                        # Empty or placeholder states can occur anywhere in an IGS menu.
                        is_fully_black = True
                        for pixel_offset in range(0, len(canvas), 4):
                            if canvas[pixel_offset] or canvas[pixel_offset + 1] or canvas[pixel_offset + 2]:
                                is_fully_black = False
                                break
                        if is_fully_black:
                            continue
                        name = f"igs_pid{pid:04x}_page{page_id:03d}_{state1}_{state2}.png"
                        out_path = os.path.join(output_dir, name)
                        M2TS._write_rgba_png(out_path, width, height, bytes(canvas))
                        out_files.append(out_path)
                        if debug:
                            print(translate_text(
                                '[M2TS.extract_igs_menu_png] write {name} ({width}x{height})'
                            ).format(name=name, width=width, height=height), file=sys.stderr)

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
