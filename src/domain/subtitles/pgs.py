import _io
import struct


class PGS:
    def __init__(self, path):
        self.raw = b""
        self.packets = []
        with open(path, 'rb') as f:
            self.raw = f.read()
        self._parse_packets()
        self.max_end = self._compute_max_end()

    def _parse_packets(self):
        self.packets = []
        i = 0
        total = len(self.raw)
        while i + 13 <= total:
            if self.raw[i:i + 2] != b'PG':
                break
            pts, dts, seg_type, seg_size = struct.unpack('>IIBH', self.raw[i + 2:i + 13])
            payload_start = i + 13
            payload_end = payload_start + seg_size
            if payload_end > total:
                break
            payload = self.raw[payload_start:payload_end]
            self.packets.append({
                "pts": pts,
                "dts": dts,
                "seg_type": seg_type,
                "payload": payload,
            })
            i = payload_end

    def _build_packet_bytes(self, packet):
        return (
            b'PG'
            + struct.pack('>IIBH', packet["pts"], packet["dts"], packet["seg_type"], len(packet["payload"]))
            + packet["payload"]
        )

    def _compute_max_end(self):
        end_set = set(self.iter_timestamp())
        if not end_set:
            return 0
        max_end = max(end_set)
        end_set.remove(max_end)
        if not end_set:
            return max_end
        max_end_1 = max(end_set)
        if max_end_1 < max_end - 300:
            return max_end_1
        return max_end

    def iter_timestamp(self):
        for packet in self.packets:
            presentation_timestamp = packet["pts"] / 90000
            if presentation_timestamp < 18000:
                yield presentation_timestamp

    def dump_file(self, fp: _io.BufferedWriter):
        for packet in self.packets:
            fp.write(self._build_packet_bytes(packet))

    def append_pgs(self, other: 'PGS', shift_time: float):
        if not hasattr(other, 'packets') or not other.packets:
            return self
        shift_pts = int(round(shift_time * 90000))
        for packet in other.packets:
            self.packets.append({
                "pts": (packet["pts"] + shift_pts) & 0xFFFFFFFF,
                "dts": (packet["dts"] + shift_pts) & 0xFFFFFFFF,
                "seg_type": packet["seg_type"],
                "payload": packet["payload"],
            })
        self.max_end = self._compute_max_end()
        return self

    def cut_pgs(self, start_time: float, end_time: float):
        start_pts = int(round(start_time * 90000))
        end_pts = int(round(end_time * 90000))
        cut_packets = []
        for packet in self.packets:
            if packet["pts"] < start_pts or packet["pts"] > end_pts:
                continue
            cut_packets.append({
                "pts": (packet["pts"] - start_pts) & 0xFFFFFFFF,
                "dts": (packet["dts"] - start_pts) & 0xFFFFFFFF,
                "seg_type": packet["seg_type"],
                "payload": packet["payload"],
            })
        self.packets = cut_packets
        self.max_end = self._compute_max_end()
        return self


__all__ = ["PGS"]
