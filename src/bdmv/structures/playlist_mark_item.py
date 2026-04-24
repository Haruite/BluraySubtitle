from ..core import InfoDict, unpack_bytes, pack_bytes


class PlayListMarkItem(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["reserved1"] = unpack_bytes(data, 0, 1)
        self["MarkType"] = unpack_bytes(data, 1, 1)
        self["RefToPlayItemID"] = unpack_bytes(data, 2, 2)
        self["MarkTimeStamp"] = unpack_bytes(data, 4, 4)
        self["EntryESPID"] = unpack_bytes(data, 8, 2)
        self["Duration"] = unpack_bytes(data, 10, 4)
        return self

    def to_bytes(self):
        return (
            pack_bytes(self["reserved1"], 1)
            + pack_bytes(self["MarkType"], 1)
            + pack_bytes(self["RefToPlayItemID"], 2)
            + pack_bytes(self["MarkTimeStamp"], 4)
            + pack_bytes(self["EntryESPID"], 2)
            + pack_bytes(self["Duration"], 4)
        )


__all__ = ["PlayListMarkItem"]
