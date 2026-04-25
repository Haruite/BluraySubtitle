"""New composed entry for split `BluraySubtitle` service."""

import threading

from ..services_split.lifecycle_and_configuration import LifecycleConfigurationMixin
from ..services_split.subtitle_and_chapter_pipeline import SubtitleChapterPipelineMixin
from ..services_split.media_info_and_track_mapping import MediaInfoTrackMappingMixin
from ..services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin
from ..services_split.encode_and_audio_tasks import EncodeAudioTasksMixin
from ..services_split.misc_workflows import MiscWorkflowsMixin
from ..services_split.service_base import BluraySubtitleServiceBase


class BluraySubtitle(
    LifecycleConfigurationMixin,
    SubtitleChapterPipelineMixin,
    MediaInfoTrackMappingMixin,
    RemuxEpisodeWorkflowsMixin,
    EncodeAudioTasksMixin,
    MiscWorkflowsMixin,
    BluraySubtitleServiceBase,
):
    """Split service class composed from generated mixins."""
    _m2ts_track_info_cache_lock = threading.RLock()
    _m2ts_track_info_cache: dict[str, tuple[tuple[int, int], list[dict[str, object]]]] = {}
    _m2ts_duration_cache_lock = threading.RLock()
    _m2ts_duration_cache: dict[str, tuple[tuple[int, int], int]] = {}
    _m2ts_frame_count_cache_lock = threading.RLock()
    _m2ts_frame_count_cache: dict[str, tuple[tuple[int, int], int]] = {}

    def __getattribute__(self, name: str):
        value = super().__getattribute__(name)
        if callable(value):
            func = getattr(value, "__func__", value)
            if getattr(func, "__service_base_stub__", False):
                raise AttributeError(f"{type(self).__name__} has no implemented method: {name}")
        return value
