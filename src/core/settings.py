"""Shared configuration constants (stage-1 extracted from legacy file)."""

import os
import shutil
import sys
from pathlib import Path


def is_docker() -> bool:
    path = "/proc/self/cgroup"
    return os.path.exists("/.dockerenv") or (os.path.isfile(path) and any("docker" in line for line in open(path)))


_BUNDLE_ROOT = (
    os.path.abspath(str(sys._MEIPASS))
    if (
        sys.platform == "win32"
        and bool(getattr(sys, "frozen", False))
        and hasattr(sys, "_MEIPASS")
    )
    else ""
)


def editable_settings_path() -> Path:
    """Return the source settings file edited by the settings dialog."""
    if _BUNDLE_ROOT:
        return Path(sys.executable).resolve().parent / "src" / "core" / "settings.py"
    return Path(__file__).resolve()


def ensure_editable_settings_file() -> Path:
    """Create the external settings source used by frozen builds when needed."""
    target = editable_settings_path()
    if not _BUNDLE_ROOT or target.is_file():
        return target
    bundled_source = Path(_BUNDLE_ROOT) / "src" / "core" / "settings.py"
    if not bundled_source.is_file():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_source, target)
    except OSError:
        pass
    return target


def _bundled_path(relative_path: str, system_path: str) -> str:
    """Use a packaged tool in frozen builds and the configured system path otherwise."""
    return os.path.join(_BUNDLE_ROOT, relative_path) if _BUNDLE_ROOT else system_path


FLAC_PATH = _bundled_path("flac.exe", r"C:\Software\flac.exe")
FFMPEG_PATH = _bundled_path("ffmpeg.exe", r"C:\Software\ffmpeg.exe")
FFPROBE_PATH = _bundled_path("ffprobe.exe", r"C:\Software\ffprobe.exe")
# These paths remain system defaults because the GUI can explicitly select
# bundled or system VapourSynth and encoder executables.
X265_PATH = r"C:\Software\x265.exe"
X264_PATH = r"C:\Software\x264.exe"
SVT_AV1_PATH = r'C:\Software\SvtAv1EncApp.exe'
FDK_AAC_PATH = _bundled_path("fdkaac.exe", r"C:\Software\fdkaac.exe")
DOVI_TOOL_PATH = _bundled_path("dovi_tool.exe", r"C:\Software\dovi_tool.exe")
HDR10PLUS_TOOL_PATH = _bundled_path(
    "hdr10plus_tool.exe",
    r"C:\Software\hdr10plus_tool.exe",
)
TRUEHDD_PATH = _bundled_path("truehdd.exe", r"C:\Software\truehdd.exe")
VSEDIT_PATH = _bundled_path(
    os.path.join("vs_pkg", "vsedit.exe"),
    r"C:\Software\vapoursynth\vsedit.exe",
)
VSPIPE_PATH = r"C:\Software\vapoursynth\vspipe.exe"
PLUGIN_PATH = ""
LIBASS_PATH = _bundled_path("libass-9.dll", r"C:\Software\libass-9.dll")
TS_MUXER_PATH = _bundled_path("tsMuxeR.exe", r"C:\Software\tsMuxeR.exe")
MKV_INFO_PATH = _bundled_path(
    "mkvinfo.exe",
    r"C:\Program Files\MKVToolNix\mkvinfo.exe",
)
MKV_MERGE_PATH = _bundled_path(
    "mkvmerge.exe",
    r"C:\Program Files\MKVToolNix\mkvmerge.exe",
)
MKV_PROP_EDIT_PATH = _bundled_path(
    "mkvpropedit.exe",
    r"C:\Program Files\MKVToolNix\mkvpropedit.exe",
)
MKV_EXTRACT_PATH = _bundled_path(
    "mkvextract.exe",
    r"C:\Program Files\MKVToolNix\mkvextract.exe",
)

if sys.platform != "win32":
    FLAC_PATH = "/usr/bin/flac"
    FFMPEG_PATH = "/usr/bin/ffmpeg"
    FFPROBE_PATH = "/usr/bin/ffprobe"
    X265_PATH = "/usr/bin/x265"
    X264_PATH = "/usr/bin/x264"
    SVT_AV1_PATH = "/usr/bin/SvtAv1EncApp"
    FDK_AAC_PATH = "/usr/local/bin/fdkaac"
    DOVI_TOOL_PATH = "/usr/bin/dovi_tool"
    HDR10PLUS_TOOL_PATH = "/usr/bin/hdr10plus_tool"
    TRUEHDD_PATH = '/usr/bin/truehdd'
    PLUGIN_PATH = os.path.expanduser("~/plugins")
    VSEDIT_PATH = "/usr/bin/vsedit"
    VSPIPE_PATH = "/usr/local/bin/vspipe"
    LIBASS_PATH = ''
    TSMUXER_PATH = '/usr/bin/tsMuxeR'
    if is_docker():
        PLUGIN_PATH = "/app/plugins"
    MKV_INFO_PATH = '/usr/bin/mkvinfo'
    MKV_MERGE_PATH = '/usr/bin/mkvmerge'
    MKV_PROP_EDIT_PATH = '/usr/bin/mkvpropedit'
    MKV_EXTRACT_PATH = '/usr/bin/mkvextract'


BDMV_LABELS = ["path", "size", "info", "remux_cmd"]
DIY_BDMV_LABELS = ["path", "size", "info"]
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


def _resolve_mkvtoolnix_path(default_path: str, binary_name: str) -> str:
    if os.path.exists(default_path):
        return default_path
    resolved = shutil.which(binary_name)
    return resolved or ""


def find_mkvtoolnix() -> None:
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


def _load_editable_settings() -> None:
    """Apply the external settings source before frozen imports capture constants."""
    if not _BUNDLE_ROOT or globals().get("_EDITABLE_SETTINGS_LOADING", False):
        return
    source_path = ensure_editable_settings_file()
    if not source_path.is_file():
        return
    source = source_path.read_text(encoding="utf-8")
    globals()["_EDITABLE_SETTINGS_LOADING"] = True
    try:
        exec(compile(source, str(source_path), "exec"), globals())
    finally:
        globals().pop("_EDITABLE_SETTINGS_LOADING", None)


_load_editable_settings()
