"""Subtitle domain scaffold (class-per-file migration layout).

Migration note:
- Keep runtime behavior via legacy bridge aliases for now.
- Manually copy implementations from `BluraySubtitle.py` into each file later.
"""

from .ass_model import Ass
from .event_model import Event
from .pgs import PGS
from .srt import SRT
from .style_model import Style
from .subtitle import Subtitle
from .timecode import parse_hhmmss_ms_to_seconds
from .worker import parse_subtitle_worker
from ...bdmv.chapter import Chapter

__all__ = [
    "Chapter",
    "Style",
    "Event",
    "Ass",
    "SRT",
    "PGS",
    "parse_hhmmss_ms_to_seconds",
    "Subtitle",
    "parse_subtitle_worker",
]

