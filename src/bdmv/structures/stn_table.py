from ..core import InfoDict, unpack_bytes, pack_bytes
from .stream_entry import StreamEntry
from .stream_attributes import StreamAttributes


class STNTable(InfoDict):
    stream_names = [
        "PrimaryVideoStreamEntries",
        "PrimaryAudioStreamEntries",
        "PrimaryPGStreamEntries",
        "PrimaryIGStreamEntries",
        "SecondaryAudioStreamEntries",
        "SecondaryVideoStreamEntries",
        "SecondaryPGStreamEntries",
        "DVStreamEntries",
    ]

    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 2)
        if self["Length"] == 0:
            return self
        self["reserved1"] = unpack_bytes(data, 2, 2)
        read_index = 4
        for name in self.stream_names:
            self[f"NumberOf{name}"] = unpack_bytes(data, read_index, 1)
            read_index += 1
        self["reserved2"] = unpack_bytes(data, 12, 4)
        read_index = 16
        for name in self.stream_names:
            self[name] = []
            for _ in range(self[f"NumberOf{name}"]):
                info_pair = InfoDict()
                stream_entry_length = unpack_bytes(data, read_index, 1)
                info_pair["StreamEntry"] = StreamEntry.from_bytes(data[read_index: read_index + stream_entry_length + 1])
                read_index += stream_entry_length + 1
                stream_attr_length = unpack_bytes(data, read_index, 1)
                info_pair["StreamAttributes"] = StreamAttributes.from_bytes(data[read_index: read_index + stream_attr_length + 1])
                read_index += stream_attr_length + 1
                self[name].append(info_pair)
        return self

    def calculate_display_size(self):
        if self["Length"] == 0:
            return 0
        real_length = 16
        for name in self.stream_names:
            for i in self[name]:
                real_length += i["StreamEntry"].calculate_display_size() + 1 + i["StreamAttributes"].calculate_display_size() + 1
        return real_length - 2

    def update_counts(self):
        if self["Length"] != 0:
            for name in self.stream_names:
                self[f"NumberOf{name}"] = len(self[name])

    def to_bytes(self):
        data = b""
        data += pack_bytes(self["Length"], 2)
        if self["Length"] == 0:
            return data
        data += pack_bytes(self["reserved1"], 2)
        for name in self.stream_names:
            data += pack_bytes(self[f"NumberOf{name}"], 1)
        data += pack_bytes(self["reserved2"], 4)
        for name in self.stream_names:
            for i in self[name]:
                data += i["StreamEntry"].to_bytes()
                data += i["StreamAttributes"].to_bytes()
        return data


__all__ = ["STNTable"]
