from ..core import InfoDict, unpack_bytes, pack_bytes
from .multi_clip_entry import MultiClipEntry
from .stn_table import STNTable
from .uo_mask_table import UOMaskTable


class PlayItem(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 2)
        self["ClipInformationFileName"] = data[2:7].decode("utf-8")
        self["ClipCodecIdentifier"] = data[7:11].decode("utf-8")
        flags = unpack_bytes(data, 11, 2)
        self["reserved1"], flags = divmod(flags, 2 ** 5)
        self["IsMultiAngle"], self["ConnectionCondition"] = divmod(flags, 2 ** 4)
        self["RefToSTCID"] = unpack_bytes(data, 13, 1)
        self["INTime"] = unpack_bytes(data, 14, 4)
        self["OUTTime"] = unpack_bytes(data, 18, 4)
        self["UOMaskTable"] = UOMaskTable.from_bytes(data[22:30])
        flags = unpack_bytes(data, 30, 1)
        self["PlayItemRandomAccessFlag"], self["reserved2"] = divmod(flags, 2 ** 7)
        self["StillMode"] = unpack_bytes(data, 31, 1)
        if self["StillMode"] == 1:
            self["StillTime"] = unpack_bytes(data, 32, 2)
        else:
            self["reserved3"] = unpack_bytes(data, 32, 2)
        read_index = 34
        self["Angles"] = []
        if self["IsMultiAngle"]:
            self["NumberOfAngles"] = unpack_bytes(data, 34, 1)
            flags = unpack_bytes(data, 35, 1)
            self["reserved4"] = flags // 2 ** 2
            flags %= 2 ** 2
            self["IsDifferentAudios"] = flags // 2
            self["IsSeamlessAngleChange"] = flags % 2
            read_index += 2
            for _ in range(self["NumberOfAngles"] - 1):
                self["Angles"].append(MultiClipEntry.from_bytes(data[read_index: read_index + 10]))
                read_index += 10
        self["STNTable"] = STNTable.from_bytes(data[read_index:])
        return self

    def calculate_display_size(self):
        real_length = 34
        if self["IsMultiAngle"]:
            real_length += 2 + len(self["Angles"]) * 10
        real_length += self["STNTable"].calculate_display_size() + 2
        return real_length - 2

    def update_counts(self):
        if self["IsMultiAngle"]:
            self["NumberOfAngles"] = len(self["Angles"]) + 1

    def to_bytes(self):
        flags = (self["reserved1"] << 5) + (self["IsMultiAngle"] << 4) + self["ConnectionCondition"]
        data = b""
        data += pack_bytes(self["Length"], 2)
        data += self["ClipInformationFileName"].encode("utf-8")
        data += self["ClipCodecIdentifier"].encode("utf-8")
        data += pack_bytes(flags, 2)
        data += pack_bytes(self["RefToSTCID"], 1)
        data += pack_bytes(self["INTime"], 4)
        data += pack_bytes(self["OUTTime"], 4)
        data += self["UOMaskTable"].to_bytes()
        data += pack_bytes((self["PlayItemRandomAccessFlag"] << 7) + self["reserved2"], 1)
        data += pack_bytes(self["StillMode"], 1)
        data += pack_bytes(self["StillTime"], 2) if self["StillMode"] == 1 else pack_bytes(self["reserved3"], 2)
        if self["IsMultiAngle"]:
            data += pack_bytes(self["NumberOfAngles"], 1)
            data += pack_bytes((self["reserved4"] << 2) + (self["IsDifferentAudios"] << 1) + self["IsSeamlessAngleChange"], 1)
            for i in self["Angles"]:
                data += i.to_bytes()
        data += self["STNTable"].to_bytes()
        return data


__all__ = ["PlayItem"]
