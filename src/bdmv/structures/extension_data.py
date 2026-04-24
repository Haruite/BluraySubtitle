from ..core import InfoDict, unpack_bytes, pack_bytes


class ExtensionData(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 4)
        self["Data"] = data[4:4 + self["Length"]] if self["Length"] else b""
        return self

    def calculate_display_size(self):
        return len(self.get("Data", b""))

    def to_bytes(self, **kwargs):
        self.check_constraints()
        return pack_bytes(self["Length"], 4) + self.get("Data", b"")


__all__ = ["ExtensionData"]
