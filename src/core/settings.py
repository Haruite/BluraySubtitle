"""Shared configuration constants (stage-1 extracted from legacy file)."""

import os
import shutil
import sys


def is_docker() -> bool:
    path = "/proc/self/cgroup"
    return os.path.exists("/.dockerenv") or (os.path.isfile(path) and any("docker" in line for line in open(path)))


FLAC_PATH = r"C:\Downloads\flac-1.5.0-win\Win64\flac.exe"
FLAC_THREADS = 20
FFMPEG_PATH = r"C:\Downloads\ffmpeg-8.1-essentials_build\bin\ffmpeg.exe"
FFPROBE_PATH = r"C:\Downloads\ffmpeg-8.1-essentials_build\bin\ffprobe.exe"
X265_PATH = r"C:\Software\x265.exe"
VSEDIT_PATH = r"C:\Software\vapoursynth\vsedit.exe"
PLUGIN_PATH = ""
LIBASS_PATH = r"C:\Downloads\libass.dll"

if sys.platform != "win32":
    FLAC_PATH = "/usr/bin/flac"
    FFMPEG_PATH = "/usr/bin/ffmpeg"
    FFPROBE_PATH = "/usr/bin/ffprobe"
    X265_PATH = "/usr/bin/x265"
    PLUGIN_PATH = os.path.expanduser("~/plugins")
    VSEDIT_PATH = "/usr/bin/vsedit"
    LIBASS_PATH = ''
    if is_docker():
        PLUGIN_PATH = "/app/plugins"


MKV_INFO_PATH = ""
MKV_MERGE_PATH = ""
MKV_PROP_EDIT_PATH = ""
MKV_EXTRACT_PATH = ""
BDMV_LABELS = ["path", "size", "info", "remux_cmd"]
SUBTITLE_LABELS = ["select", "path", "sub_duration", "ep_duration", "bdmv_index", "chapter_index", "offset", "warning"]
MKV_LABELS = ["path", "duration"]
REMUX_LABELS = ["sub_path", "language", "ep_duration", "bdmv_index", "start_at_chapter", "end_at_chapter", "m2ts_file", "output_name", "play"]
ENCODE_LABELS = ["sub_path", "language", "ep_duration", "bdmv_index", "start_at_chapter", "end_at_chapter", "m2ts_file", "output_name", "vpy_path", "edit_vpy", "preview_script", "play"]
ENCODE_SP_LABELS = ["select", "bdmv_index", "mpls_file", "m2ts_file", "m2ts_type", "duration", "output_name", "tracks", "vpy_path", "edit_vpy", "preview_script", "play"]
ENCODE_REMUX_LABELS = ["sub_path", "language", "ep_duration", "output_name", "vpy_path", "edit_vpy", "preview_script", "play", "edit_tracks", "edit_chapters", "edit_attachments"]
ENCODE_REMUX_SP_LABELS = ["duration", "output_name", "vpy_path", "edit_vpy", "preview_script", "play", "edit_tracks", "edit_chapters", "edit_attachments"]
CONFIGURATION = {}
DEFAULT_APPROX_EPISODE_DURATION_SECONDS = 24 * 60
CURRENT_UI_LANGUAGE = "en"
APP_TITLE = "BluraySubtitle v3.4"


def get_mkvtoolnix_ui_language() -> str:
    if CURRENT_UI_LANGUAGE == "zh":
        return "zh_CN"
    return "en" if sys.platform == "win32" else "en_US"


def mkvtoolnix_ui_language_arg() -> str:
    return f"--ui-language {get_mkvtoolnix_ui_language()}"


def _resolve_mkvtoolnix_path(default_path: str, binary_name: str) -> str:
    if os.path.exists(default_path):
        return default_path
    resolved = shutil.which(binary_name)
    return resolved or ""


def find_mkvtoolinx() -> None:
    """Resolve mkvtoolnix executable paths into global settings."""
    global MKV_INFO_PATH
    global MKV_MERGE_PATH
    global MKV_PROP_EDIT_PATH
    global MKV_EXTRACT_PATH

    if not MKV_INFO_PATH:
        default_mkv_info_path = r"C:\Program Files\MKVToolNix\mkvinfo.exe" if sys.platform == "win32" else "/usr/bin/mkvinfo"
        MKV_INFO_PATH = _resolve_mkvtoolnix_path(default_mkv_info_path, "mkvinfo")

    if not MKV_MERGE_PATH:
        default_mkv_merge_path = r"C:\Program Files\MKVToolNix\mkvmerge.exe" if sys.platform == "win32" else "/usr/bin/mkvmerge"
        MKV_MERGE_PATH = _resolve_mkvtoolnix_path(default_mkv_merge_path, "mkvmerge")

    if not MKV_PROP_EDIT_PATH:
        default_mkv_prop_edit_path = r"C:\Program Files\MKVToolNix\mkvpropedit.exe" if sys.platform == "win32" else "/usr/bin/mkvpropedit"
        MKV_PROP_EDIT_PATH = _resolve_mkvtoolnix_path(default_mkv_prop_edit_path, "mkvpropedit")

    if not MKV_EXTRACT_PATH:
        default_mkv_extract_path = r"C:\Program Files\MKVToolNix\mkvextract.exe" if sys.platform == "win32" else "/usr/bin/mkvextract"
        MKV_EXTRACT_PATH = _resolve_mkvtoolnix_path(default_mkv_extract_path, "mkvextract")

