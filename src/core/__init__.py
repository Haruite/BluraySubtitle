"""Core runtime/configuration layer (migration stage)."""

from .version import APP_TITLE
from .version import APP_VERSION
from .settings import BDMV_LABELS
from .settings import DIY_BDMV_LABELS
from .settings import CURRENT_UI_LANGUAGE
from .settings import DEFAULT_APPROX_EPISODE_DURATION_SECONDS
from .settings import ENCODE_LABELS
from .settings import ENCODE_REMUX_LABELS
from .settings import ENCODE_REMUX_SP_LABELS
from .settings import ENCODE_SP_LABELS
from .settings import DIY_SP_LABELS
from .settings import MKV_LABELS
from .settings import MPLS_INFO_LABELS
from .settings import MPLS_INFO_TRACKS_LABELS
from .settings import REMUX_LABELS
from .settings import DIY_REMUX_LABELS
from .settings import SUBTITLE_LABELS
from .settings import get_mkvtoolnix_ui_language
from .settings import mkvtoolnix_ui_language_arg

__all__ = [
    "BDMV_LABELS",
    "DIY_BDMV_LABELS",
    "SUBTITLE_LABELS",
    "MKV_LABELS",
    "MPLS_INFO_LABELS",
    "MPLS_INFO_TRACKS_LABELS",
    "REMUX_LABELS",
    "DIY_REMUX_LABELS",
    "ENCODE_LABELS",
    "ENCODE_SP_LABELS",
    "DIY_SP_LABELS",
    "ENCODE_REMUX_LABELS",
    "ENCODE_REMUX_SP_LABELS",
    "DEFAULT_APPROX_EPISODE_DURATION_SECONDS",
    "CURRENT_UI_LANGUAGE",
    "APP_TITLE",
    "APP_VERSION",
    "get_mkvtoolnix_ui_language",
    "mkvtoolnix_ui_language_arg",
]

