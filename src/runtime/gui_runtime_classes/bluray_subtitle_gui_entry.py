"""New external GUI entry class.

All external imports should use this module instead of the legacy
`bluray_subtitle_gui.py` directly. The legacy file is kept for debugging.
"""

from ..gui_runtime_split.lifecycle_and_bootstrap import LifecycleBootstrapMixin
from ..gui_runtime_split.configuration_and_modes import ConfigurationModesMixin
from ..gui_runtime_split.output_and_tracks import OutputTracksMixin
from ..gui_runtime_split.playback_and_paths import PlaybackPathsMixin
from ..gui_runtime_split.remux_and_episode_layout import RemuxEpisodeLayoutMixin
from ..gui_runtime_split.scan_and_worker_hooks import ScanWorkerHooksMixin
from ..gui_runtime_split.actions_and_file_dialogs import ActionsAndDialogsMixin
from ..gui_runtime_split.sp_chapter_segment_logic import SpChapterSegmentLogicMixin
from ..gui_runtime_split.table_layout_and_headers import TableLayoutHeadersMixin
from ..gui_runtime_split.theme_and_i18n import ThemeI18nMixin
from ..gui_runtime_split.track_and_attachment_editing import TrackAttachmentEditingMixin
from ..gui_runtime_split.vpy_edit_and_preview import VpyEditPreviewMixin
from ..gui_runtime_split.gui_base import BluraySubtitleGuiBase


class BluraySubtitleGUI(
    LifecycleBootstrapMixin,
    ConfigurationModesMixin,
    ThemeI18nMixin,
    TableLayoutHeadersMixin,
    VpyEditPreviewMixin,
    PlaybackPathsMixin,
    RemuxEpisodeLayoutMixin,
    OutputTracksMixin,
    TrackAttachmentEditingMixin,
    SpChapterSegmentLogicMixin,
    ActionsAndDialogsMixin,
    ScanWorkerHooksMixin,
    BluraySubtitleGuiBase,
):
    """Split GUI class composed from all migration mixins."""

    def __getattribute__(self, name: str):
        """Hide base stub methods when no parent provides implementation."""
        value = super().__getattribute__(name)
        if callable(value):
            func = getattr(value, "__func__", value)
            if getattr(func, "__gui_base_stub__", False):
                raise AttributeError(f"{type(self).__name__!s} has no implemented method: {name!s}")
        return value


