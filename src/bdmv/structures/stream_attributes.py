from ..core import InfoDict, unpack_bytes, pack_bytes


class StreamAttributes(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 1)
        if self["Length"] == 0:
            return self
        self["StreamCodingType"] = unpack_bytes(data, 1, 1)
        if self["StreamCodingType"] in [0x01, 0x02, 0x1B, 0xEA]:
            tmp = unpack_bytes(data, 2, 1)
            self["VideoFormat"], self["FrameRate"] = divmod(tmp, 2 ** 4)
        elif self["StreamCodingType"] == 0x24:
            tmp = unpack_bytes(data, 2, 1)
            self["VideoFormat"], self["FrameRate"] = divmod(tmp, 2 ** 4)
            tmp = unpack_bytes(data, 3, 1)
            self["DynamicRangeType"], self["ColorSpace"] = divmod(tmp, 2 ** 4)
            tmp = unpack_bytes(data, 4, 1)
            self["CRFlag"] = tmp >> 7 & 1
            self["HDRPlusFlag"] = tmp >> 6 & 1
        elif self["StreamCodingType"] in [0x03, 0x04, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0xA1, 0xA2]:
            tmp = unpack_bytes(data, 2, 1)
            self["AudioFormat"], self["SampleRate"] = divmod(tmp, 2 ** 4)
            self["LanguageCode"] = data[3:6].decode("utf-8")
        elif self["StreamCodingType"] in [0x90, 0x91]:
            self["LanguageCode"] = data[2:5].decode("utf-8")
        elif self["StreamCodingType"] in [0x92]:
            self["CharacterCode"] = unpack_bytes(data, 2, 1)
            self["LanguageCode"] = data[3:6].decode("utf-8")
        return self

    def calculate_display_size(self):
        return 5 if self["Length"] != 0 else 0

    def to_bytes(self):
        data = b""
        data += pack_bytes(self["Length"], 1)
        if self["Length"] == 0:
            return data
        data += pack_bytes(self["StreamCodingType"], 1)
        if self["StreamCodingType"] in [0x01, 0x02, 0x1B, 0xEA]:
            data += pack_bytes((self["VideoFormat"] << 4) + self["FrameRate"], 1) + b"\x00\x00\x00"
        elif self["StreamCodingType"] == 0x24:
            data += pack_bytes((self["VideoFormat"] << 4) + self["FrameRate"], 1)
            data += pack_bytes((self["DynamicRangeType"] << 4) + self["ColorSpace"], 1)
            data += pack_bytes((self["CRFlag"] << 7) + (self["HDRPlusFlag"] << 6), 1) + b"\x00"
        elif self["StreamCodingType"] in [0x03, 0x04, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0xA1, 0xA2]:
            data += pack_bytes((self["AudioFormat"] << 4) + self["SampleRate"], 1)
            data += self["LanguageCode"].encode("utf-8")
        elif self["StreamCodingType"] in [0x90, 0x91]:
            data += self["LanguageCode"].encode("utf-8") + b"\x00"
        elif self["StreamCodingType"] in [0x92]:
            data += pack_bytes(self["CharacterCode"], 1) + self["LanguageCode"].encode("utf-8")
        return data


__all__ = ["StreamAttributes"]
