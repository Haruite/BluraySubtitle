from ..core import InfoDict, unpack_bytes, pack_bytes
from .app_info_playlist import AppInfoPlayList
from .extension_data import ExtensionData
from .playlist import PlayList
from .playlist_mark import PlayListMark


class MPLSHeader(InfoDict):
    @classmethod
    def from_bytes(cls, data, strict=True, **kwargs):
        self = cls()
        self["TypeIndicator"] = data[0:4].decode("utf-8")
        self["VersionNumber"] = data[4:8].decode("utf-8")
        self["PlayListStartAddress"] = unpack_bytes(data, 8, 4)
        self["PlayListMarkStartAddress"] = unpack_bytes(data, 12, 4)
        self["ExtensionDataStartAddress"] = unpack_bytes(data, 16, 4)
        self["reserved1"] = data[20:40]
        appinfo_display_size = unpack_bytes(data, 40, 4)
        playlist_display_size = unpack_bytes(data, self["PlayListStartAddress"], 4)
        playlist_mark_display_size = unpack_bytes(data, self["PlayListMarkStartAddress"], 4)
        self["AppInfoPlayList"] = AppInfoPlayList.from_bytes(data[40: 40 + appinfo_display_size + 4])
        self["PlayList"] = PlayList.from_bytes(
            data[self["PlayListStartAddress"]: self["PlayListStartAddress"] + playlist_display_size + 4]
        )
        self["PlayListMark"] = PlayListMark.from_bytes(
            data[self["PlayListMarkStartAddress"]: self["PlayListMarkStartAddress"] + playlist_mark_display_size + 4]
        )
        if self["ExtensionDataStartAddress"]:
            ext_size = unpack_bytes(data, self["ExtensionDataStartAddress"], 4)
            self["ExtensionData"] = ExtensionData.from_bytes(
                data[self["ExtensionDataStartAddress"]: self["ExtensionDataStartAddress"] + ext_size + 4]
            )
        return self

    def update_addresses(self, offset=0):
        playlist_display_size = self["PlayList"].calculate_display_size()
        playlist_mark_display_size = self["PlayListMark"].calculate_display_size()
        self["PlayListMarkStartAddress"] = self["PlayListStartAddress"] + playlist_display_size + 4
        if self["ExtensionDataStartAddress"]:
            self["ExtensionDataStartAddress"] = self["PlayListMarkStartAddress"] + playlist_mark_display_size + 4

    def to_bytes(self):
        data = b""
        data += self["TypeIndicator"].encode("utf-8")
        data += self["VersionNumber"].encode("utf-8")
        data += pack_bytes(self["PlayListStartAddress"], 4)
        data += pack_bytes(self["PlayListMarkStartAddress"], 4)
        data += pack_bytes(self["ExtensionDataStartAddress"], 4)
        data += self["reserved1"]
        data += self["AppInfoPlayList"].to_bytes()
        data += self["PlayList"].to_bytes()
        data += self["PlayListMark"].to_bytes()
        if self["ExtensionDataStartAddress"]:
            data += self["ExtensionData"].to_bytes()
        return data


__all__ = ["MPLSHeader"]
