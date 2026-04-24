from ..core import InfoDict, unpack_bytes, pack_bytes
from .play_item import PlayItem
from .sub_path import SubPath


class PlayList(InfoDict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setdefault("PlayItems", [])
        self.setdefault("SubPaths", [])

    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 4)
        self["reserved1"] = unpack_bytes(data, 4, 2)
        self["NumberOfPlayItems"] = unpack_bytes(data, 6, 2)
        self["NumberOfSubPaths"] = unpack_bytes(data, 8, 2)
        read_index = 10
        for _ in range(self["NumberOfPlayItems"]):
            item_length = unpack_bytes(data, read_index, 2)
            self["PlayItems"].append(PlayItem.from_bytes(data[read_index: read_index + item_length + 2]))
            read_index += item_length + 2
        for _ in range(self["NumberOfSubPaths"]):
            item_length = unpack_bytes(data, read_index, 4)
            self["SubPaths"].append(SubPath.from_bytes(data[read_index: read_index + item_length + 4]))
            read_index += item_length + 4
        return self

    def calculate_display_size(self):
        real_length = 10
        for i in self["PlayItems"]:
            real_length += i.calculate_display_size() + 2
        for i in self["SubPaths"]:
            real_length += i.calculate_display_size() + 4
        return real_length - 4

    def update_counts(self):
        self["NumberOfPlayItems"] = len(self["PlayItems"])
        self["NumberOfSubPaths"] = len(self["SubPaths"])

    def to_bytes(self):
        data = b""
        data += pack_bytes(self["Length"], 4)
        data += pack_bytes(self["reserved1"], 2)
        data += pack_bytes(self["NumberOfPlayItems"], 2)
        data += pack_bytes(self["NumberOfSubPaths"], 2)
        for i in self["PlayItems"]:
            data += i.to_bytes()
        for i in self["SubPaths"]:
            data += i.to_bytes()
        return data


__all__ = ["PlayList"]
