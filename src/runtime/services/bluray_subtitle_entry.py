"""New composed entry for split `BluraySubtitle` service."""

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

    def __getattribute__(self, name: str):
        value = super().__getattribute__(name)
        if callable(value):
            func = getattr(value, "__func__", value)
            if getattr(func, "__service_base_stub__", False):
                raise AttributeError(f"{type(self).__name__} has no implemented method: {name}")
        return value
