from ..core import InfoDict, unpack_bytes, pack_bytes
from .playlist_mark_item import PlayListMarkItem


class PlayListMark(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 4)
        self["NumberOfPlayListMarks"] = unpack_bytes(data, 4, 2)
        self["PlayListMarks"] = []
        for i in range(self["NumberOfPlayListMarks"]):
            self["PlayListMarks"].append(PlayListMarkItem.from_bytes(data[6 + 14 * i: 6 + 14 * (i + 1)]))
        return self

    def calculate_display_size(self):
        return self["NumberOfPlayListMarks"] * 14 + 2

    def update_counts(self):
        self["NumberOfPlayListMarks"] = len(self["PlayListMarks"])

    def to_bytes(self):
        data = b""
        data += pack_bytes(self["Length"], 4)
        data += pack_bytes(self["NumberOfPlayListMarks"], 2)
        for i in self["PlayListMarks"]:
            data += i.to_bytes()
        return data


__all__ = ["PlayListMark"]
