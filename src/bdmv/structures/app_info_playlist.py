from ..core import InfoDict, unpack_bytes, pack_bytes
from .uo_mask_table import UOMaskTable


class AppInfoPlayList(InfoDict):
    @classmethod
    def from_bytes(cls, data, **kwargs):
        self = cls()
        self["Length"] = unpack_bytes(data, 0, 4)
        self["reserved1"] = unpack_bytes(data, 4, 1)
        self["PlaybackType"] = unpack_bytes(data, 5, 1)
        self["reserved2"] = unpack_bytes(data, 6, 2)
        self["UOMaskTable"] = UOMaskTable.from_bytes(data[8:16])
        flags = unpack_bytes(data, 16, 2)
        self["RandomAccessFlag"] = flags >> 15 & 1
        self["AudioMixFlag"] = flags >> 14 & 1
        self["LosslessBypassFlag"] = flags >> 13 & 1
        self["MVCBaseViewRFlag"] = flags >> 12 & 1
        self["SDRConversionNotificationFlag"] = flags >> 11 & 1
        self["reserved3"] = flags % 2 ** 11
        return self

    def calculate_display_size(self):
        return 14

    def to_bytes(self):
        flags = (
            (self["RandomAccessFlag"] << 15)
            + (self["AudioMixFlag"] << 14)
            + (self["LosslessBypassFlag"] << 13)
            + (self["MVCBaseViewRFlag"] << 12)
            + (self["SDRConversionNotificationFlag"] << 11)
            + self["reserved3"]
        )
        data = b""
        data += pack_bytes(self["Length"], 4)
        data += pack_bytes(self["reserved1"], 1)
        data += pack_bytes(self["PlaybackType"], 1)
        data += pack_bytes(self["reserved2"], 2)
        data += self["UOMaskTable"].to_bytes()
        data += pack_bytes(flags, 2)
        return data


__all__ = ["AppInfoPlayList"]
