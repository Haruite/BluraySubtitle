from ..core import InfoDict, unpack_bytes, pack_bytes


class SubPath(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 4)
        self["raw"] = data[4:4 + self["Length"]]
        return self

    def calculate_display_size(self):
        return len(self.get("raw", b""))

    def to_bytes(self):
        return pack_bytes(self["Length"], 4) + self.get("raw", b"")


__all__ = ["SubPath"]
