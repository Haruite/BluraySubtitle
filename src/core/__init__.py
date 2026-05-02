"""Core runtime/configuration layer (migration stage)."""

from .settings import APP_TITLE
from .settings import BDMV_LABELS
from .settings import DIY_BDMV_LABELS
from .settings import CONFIGURATION
from .settings import CURRENT_UI_LANGUAGE
from .settings import DEFAULT_APPROX_EPISODE_DURATION_SECONDS
from .settings import ENCODE_LABELS
from .settings import ENCODE_REMUX_LABELS
from .settings import ENCODE_REMUX_SP_LABELS
from .settings import ENCODE_SP_LABELS
from .settings import DIY_SP_LABELS
from .settings import FDK_AAC_PATH
from .settings import FFMPEG_PATH
from .settings import FFPROBE_PATH
from .settings import FLAC_PATH
from .settings import FLAC_THREADS
from .settings import find_mkvtoolinx
from .settings import MKV_EXTRACT_PATH
from .settings import MKV_INFO_PATH
from .settings import MKV_LABELS
from .settings import MKV_MERGE_PATH
from .settings import MKV_PROP_EDIT_PATH
from .settings import REMUX_LABELS
from .settings import DIY_REMUX_LABELS
from .settings import SUBTITLE_LABELS
from .settings import VSEDIT_PATH
from .settings import X265_PATH
from .settings import get_mkvtoolnix_ui_language
from .settings import is_docker
from .settings import mkvtoolnix_ui_language_arg

__all__ = [
    "is_docker",
    "FLAC_PATH",
    "FLAC_THREADS",
    "find_mkvtoolinx",
    "FDK_AAC_PATH",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "X265_PATH",
    "VSEDIT_PATH",
    "MKV_INFO_PATH",
    "MKV_MERGE_PATH",
    "MKV_PROP_EDIT_PATH",
    "MKV_EXTRACT_PATH",
    "BDMV_LABELS",
    "DIY_BDMV_LABELS",
    "SUBTITLE_LABELS",
    "MKV_LABELS",
    "REMUX_LABELS",
    "DIY_REMUX_LABELS",
    "ENCODE_LABELS",
    "ENCODE_SP_LABELS",
    "DIY_SP_LABELS",
    "ENCODE_REMUX_LABELS",
    "ENCODE_REMUX_SP_LABELS",
    "CONFIGURATION",
    "DEFAULT_APPROX_EPISODE_DURATION_SECONDS",
    "CURRENT_UI_LANGUAGE",
    "APP_TITLE",
    "get_mkvtoolnix_ui_language",
    "mkvtoolnix_ui_language_arg",
]

