from ..core import InfoDict, unpack_bytes, pack_bytes


class UOMaskTable(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["raw"] = unpack_bytes(data, 0, 8)
        return self

    def to_bytes(self):
        return pack_bytes(self["raw"], 8)


__all__ = ["UOMaskTable"]
