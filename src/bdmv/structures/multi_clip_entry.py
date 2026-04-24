from ..core import InfoDict, unpack_bytes, pack_bytes


class MultiClipEntry(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["ClipInformationFileName"] = data[0:5].decode("utf-8")
        self["ClipCodecIdentifier"] = data[5:9].decode("utf-8")
        self["RefToSTCID"] = unpack_bytes(data, 9, 1)
        return self

    def to_bytes(self):
        return self["ClipInformationFileName"].encode("utf-8") + self["ClipCodecIdentifier"].encode("utf-8") + pack_bytes(self["RefToSTCID"], 1)


__all__ = ["MultiClipEntry"]
