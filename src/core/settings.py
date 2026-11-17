"""Shared table definitions and tool paths for setup and packaging."""

import os
import sys


_BUNDLE_ROOT = (
    os.path.abspath(str(sys._MEIPASS))
    if (
        (sys.platform == "win32" or sys.platform.startswith("linux"))
        and bool(getattr(sys, "frozen", False))
        and hasattr(sys, "_MEIPASS")
    )
    else ""
)


def _bundled_path(relative_path: str, system_path: str) -> str:
    """Use a packaged tool in frozen builds and the configured system path otherwise."""
    return os.path.join(_BUNDLE_ROOT, relative_path) if _BUNDLE_ROOT else system_path


SEVEN_ZIP_PATH = _bundled_path("7z.exe", r"C:\Program Files\7-Zip\7z.exe")
FLAC_PATH = _bundled_path("flac.exe", r"C:\Software\flac.exe")
FFMPEG_PATH = _bundled_path("ffmpeg.exe", r"C:\Software\ffmpeg.exe")
FFPROBE_PATH = _bundled_path("ffprobe.exe", r"C:\Software\ffprobe.exe")
X265_PATH = r"C:\Software\x265.exe"
X264_PATH = r"C:\Software\x264.exe"
SVT_AV1_PATH = r'C:\Software\SvtAv1EncApp.exe'
FDK_AAC_PATH = _bundled_path("fdkaac.exe", r"C:\Software\fdkaac.exe")
DOVI_TOOL_PATH = _bundled_path("dovi_tool.exe", r"C:\Software\dovi_tool.exe")
HDR10PLUS_TOOL_PATH = _bundled_path(
    "hdr10plus_tool.exe",
    r"C:\Software\hdr10plus_tool.exe",
)
VSEDIT_PATH = _bundled_path(
    "vsedit/vsedit.exe",
    r"C:\Software\vapoursynth\vsedit\vsedit.exe",
)
VSPIPE_PATH = r"C:\Software\vapoursynth\vspipe.exe"
PLUGIN_PATH = ""
LIBASS_PATH = _bundled_path("libass-9.dll", r"C:\Software\libass-9.dll")
TS_MUXER_PATH = _bundled_path("tsMuxeR.exe", r"C:\Software\tsMuxeR.exe")
MKVTOOLNIX_PATH = _bundled_path("mkvtoolnix", r"C:\Software\mkvtoolnix")

MPV_PATH = ""
MPV_CONFIG_PATH = ""

if sys.platform != "win32":
    SEVEN_ZIP_PATH = _bundled_path("linux/bin/7zz", "/usr/local/bin/7zz")
    FLAC_PATH = _bundled_path("linux/bin/flac", "/usr/bin/flac")
    FFMPEG_PATH = _bundled_path("linux/bin/ffmpeg", "/usr/bin/ffmpeg")
    FFPROBE_PATH = _bundled_path("linux/bin/ffprobe", "/usr/bin/ffprobe")
    X265_PATH = "/usr/bin/x265"
    X264_PATH = "/usr/bin/x264"
    SVT_AV1_PATH = "/usr/bin/SvtAv1EncApp"
    FDK_AAC_PATH = _bundled_path("linux/bin/fdkaac", "/usr/local/bin/fdkaac")
    DOVI_TOOL_PATH = _bundled_path("linux/bin/dovi_tool", "/usr/bin/dovi_tool")
    HDR10PLUS_TOOL_PATH = _bundled_path("linux/bin/hdr10plus_tool", "/usr/bin/hdr10plus_tool")
    PLUGIN_PATH = _bundled_path("linux/plugins", os.path.expanduser("~/plugins"))
    VSEDIT_PATH = _bundled_path("linux/bin/vsedit", "/usr/local/bin/vsedit")
    VSPIPE_PATH = "/usr/local/bin/vspipe"
    LIBASS_PATH = _bundled_path("libass.so.9", "")
    TS_MUXER_PATH = _bundled_path("linux/bin/tsMuxeR", "/usr/bin/tsMuxeR")
    MKVTOOLNIX_PATH = _bundled_path("linux/bin", "/usr/bin")
    MPV_PATH = _bundled_path("linux/bin/mpv", "")
    MPV_CONFIG_PATH = _bundled_path("mpv", "")


BDMV_LABELS = ["path", "size", "info", "remux_cmd"]
DIY_BDMV_LABELS = ["path", "size", "info"]
MPLS_INFO_LABELS = ["mpls_file", "duration", "chapters", "m2ts_timing", "main", "play"]
MPLS_INFO_TRACKS_LABELS = MPLS_INFO_LABELS + ["tracks"]
SUBTITLE_LABELS = ["select", "path", "sub_duration", "ep_duration", "bdmv_index", "chapter_index", "offset", "warning"]
MKV_LABELS = ["path", "duration"]
REMUX_LABELS = ["sub_path", "language", "ep_duration", "bdmv_index", "start_at_chapter", "end_at_chapter", "m2ts_file", "m2ts_file_detail", "output_name", "play"]
DIY_REMUX_LABELS = ["sub_path", "language", "ep_duration", "bdmv_index", "start_at_chapter", "end_at_chapter", "m2ts_file", "m2ts_file_detail", "play"]
ENCODE_LABELS = ["sub_path", "language", "ep_duration", "bdmv_index", "start_at_chapter", "end_at_chapter", "m2ts_file", "m2ts_file_detail", "output_name", "vpy_path", "edit_vpy", "preview_script", "play"]
ENCODE_SP_LABELS = ["select", "bdmv_index", "mpls_file", "m2ts_file", "m2ts_file_detail", "m2ts_type", "duration", "output_name", "tracks", "vpy_path", "edit_vpy", "preview_script", "play"]
DIY_SP_LABELS = ["select", "bdmv_index", "mpls_file", "m2ts_file", "m2ts_file_detail", "m2ts_type", "duration", "tracks", "vpy_path", "edit_vpy", "preview_script", "play"]
ENCODE_REMUX_LABELS = ["sub_path", "language", "ep_duration", "output_name", "vpy_path", "edit_vpy", "preview_script", "play", "edit_tracks", "edit_chapters", "edit_attachments"]
ENCODE_REMUX_SP_LABELS = ["duration", "output_name", "vpy_path", "edit_vpy", "preview_script", "play", "edit_tracks", "edit_chapters", "edit_attachments"]
DEFAULT_APPROX_EPISODE_DURATION_SECONDS = 24 * 60
CURRENT_UI_LANGUAGE = "en"


def get_mkvtoolnix_ui_language() -> str:
    if CURRENT_UI_LANGUAGE == "zh":
        return "zh_CN"
    return "en" if sys.platform == "win32" else "en_US"


def mkvtoolnix_ui_language_arg() -> str:
    return f"--ui-language {get_mkvtoolnix_ui_language()}"
