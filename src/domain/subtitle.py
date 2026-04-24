"""Compatibility facade for subtitle domain.

Prefer importing from `src.domain.subtitles` package.
"""

from ..bdmv.chapter import Chapter
from .subtitles import Ass
from .subtitles import Event
from .subtitles import PGS
from .subtitles import SRT
from .subtitles import Style
from .subtitles import Subtitle
from .subtitles import parse_hhmmss_ms_to_seconds
from .subtitles import parse_subtitle_worker

_parse_hhmmss_ms_to_seconds = parse_hhmmss_ms_to_seconds
_parse_subtitle_worker = parse_subtitle_worker

__all__ = [
    "Chapter",
    "Style",
    "Event",
    "Ass",
    "SRT",
    "PGS",
    "_parse_hhmmss_ms_to_seconds",
    "Subtitle",
    "_parse_subtitle_worker",
]

