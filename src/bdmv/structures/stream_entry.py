from ..core import InfoDict, unpack_bytes, pack_bytes


class StreamEntry(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 1)
        if self["Length"] == 0:
            return self
        self["StreamType"] = unpack_bytes(data, 1, 1)
        if self["StreamType"] == 1:
            self["RefToStreamPID"] = unpack_bytes(data, 2, 2)
        elif self["StreamType"] == 2:
            self["RefToSubPathID"] = unpack_bytes(data, 2, 1)
            self["RefToSubClipID"] = unpack_bytes(data, 3, 1)
            self["RefToStreamPID"] = unpack_bytes(data, 4, 2)
        elif self["StreamType"] in [3, 4]:
            self["RefToSubPathID"] = unpack_bytes(data, 2, 1)
            self["RefToStreamPID"] = unpack_bytes(data, 3, 2)
        return self

    def calculate_display_size(self):
        return 9 if self["Length"] != 0 else 0

    def to_bytes(self):
        data = b""
        data += pack_bytes(self["Length"], 1)
        if self["Length"] == 0:
            return data
        data += pack_bytes(self["StreamType"], 1)
        if self["StreamType"] == 1:
            data += pack_bytes(self["RefToStreamPID"], 2) + b"\x00\x00\x00\x00\x00\x00"
        elif self["StreamType"] == 2:
            data += pack_bytes(self["RefToSubPathID"], 1)
            data += pack_bytes(self["RefToSubClipID"], 1)
            data += pack_bytes(self["RefToStreamPID"], 2) + b"\x00\x00\x00\x00"
        elif self["StreamType"] in [3, 4]:
            data += pack_bytes(self["RefToSubPathID"], 1)
            data += pack_bytes(self["RefToStreamPID"], 2) + b"\x00\x00\x00\x00\x00"
        return data


__all__ = ["StreamEntry"]
