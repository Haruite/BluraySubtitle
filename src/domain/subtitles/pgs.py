import struct


_HEADER = struct.Struct('>2sIIBH')
_CLOCKS = struct.Struct('>II')
_CLOCK_RATE = 90000
_CLOCK_MASK = 0xFFFFFFFF
_MAX_PTS = 18000 * _CLOCK_RATE


def _packet_headers(block):
    offset = 0
    while offset + _HEADER.size <= len(block):
        magic, pts, dts, _, payload_size = _HEADER.unpack_from(block, offset)
        end = offset + _HEADER.size + payload_size
        if magic != b'PG' or end > len(block):
            break
        yield offset, end, pts, dts
        offset = end


class _EndTimestamps:
    __slots__ = ('latest', 'previous')

    def __init__(self):
        self.latest = self.previous = -1

    def add(self, pts):
        if not 0 <= pts < _MAX_PTS:
            return
        if pts > self.latest:
            self.previous, self.latest = self.latest, pts
        elif self.previous < pts < self.latest:
            self.previous = pts

    def duration(self):
        latest = max(self.latest, 0) / _CLOCK_RATE
        previous = self.previous / _CLOCK_RATE
        if self.previous >= 0 and previous < latest - 300:
            return previous
        return latest


def _scan(block):
    times = _EndTimestamps()
    end = 0
    for _, end, pts, _ in _packet_headers(block):
        times.add(pts)
    return end, times


class PGS:
    def __init__(self, path):
        with open(path, 'rb') as stream:
            block = stream.read()
        end, self._times = _scan(block)
        # Published blocks are never mutated, so clones share their image data.
        self._blocks = (block[:end],) if end else ()

    @staticmethod
    def read_duration(path):
        with open(path, 'rb') as stream:
            _, times = _scan(stream.read())
        return times.duration()

    @property
    def max_end(self):
        return self._times.duration()

    def _shifted(self, offset):
        offset &= _CLOCK_MASK
        if not offset:
            return self._blocks, self._times
        blocks = []
        times = _EndTimestamps()
        for block in self._blocks:
            patch = bytearray(block)
            for start, _, pts, dts in _packet_headers(block):
                pts = (pts + offset) & _CLOCK_MASK
                _CLOCKS.pack_into(patch, start + 2, pts, (dts + offset) & _CLOCK_MASK)
                times.add(pts)
            blocks.append(patch)
        return tuple(blocks), times

    def shift(self, seconds):
        self._blocks, self._times = self._shifted(round(seconds * _CLOCK_RATE))

    def append_pgs(self, other: 'PGS', shift_time: float):
        blocks, times = other._shifted(round(shift_time * _CLOCK_RATE))
        combined = _EndTimestamps()
        for pts in (self._times.latest, self._times.previous, times.latest, times.previous):
            combined.add(pts)
        self._blocks += blocks
        self._times = combined
        return self

    def cut_pgs(self, start_time: float, end_time: float):
        start_pts = round(start_time * _CLOCK_RATE)
        end_pts = round(end_time * _CLOCK_RATE)
        times = _EndTimestamps()
        blocks = []
        for block in self._blocks:
            source = memoryview(block)
            cut = bytearray()
            for start, end, pts, dts in _packet_headers(block):
                if not start_pts <= pts <= end_pts:
                    continue
                offset = len(cut)
                cut.extend(source[start:end])
                pts = (pts - start_pts) & _CLOCK_MASK
                _CLOCKS.pack_into(cut, offset + 2, pts, (dts - start_pts) & _CLOCK_MASK)
                times.add(pts)
            if cut:
                blocks.append(cut)
        self._blocks = tuple(blocks)
        self._times = times
        return self

    def dump_file(self, fp):
        for block in self._blocks:
            fp.write(block)


__all__ = ["PGS"]
