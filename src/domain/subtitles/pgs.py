from struct import unpack


class PGS:
    def __init__(self, path):
        self.formats: dict[int, str] = {1: '>B', 2: '>H', 4: '>I', 8: '>Q'}
        with open(path, 'rb') as self.bytes:
            end_set = set(self.iter_timestamp())
            max_end = max(end_set)
            end_set.remove(max_end)
            max_end_1 = max(end_set)
            if max_end_1 < max_end - 300:
                self.max_end = max_end_1
            else:
                self.max_end = max_end

    def iter_timestamp(self):
        while True:
            if self.bytes.read(2) != b'PG':
                break
            presentation_timestamp = self._unpack_byte(4) / 90000
            self.bytes.read(5)
            segment_size = self._unpack_byte(2)
            self.bytes.read(segment_size)
            if presentation_timestamp < 18000:
                yield presentation_timestamp

    def _unpack_byte(self, n: int):
        return unpack(self.formats[n], self.bytes.read(n))[0]


__all__ = ["PGS"]
