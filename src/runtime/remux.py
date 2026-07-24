"""Plain-data contracts for the Blu-ray Remux workflow."""

from __future__ import annotations

from dataclasses import dataclass

from src.runtime.sp import SpEntry


@dataclass(frozen=True)
class RemuxRequest:
    """Complete GUI snapshot consumed by one Remux worker."""

    bdmv_path: str
    subtitle_files: tuple[str, ...]
    complete_bluray_folder: bool
    output_folder: str
    configuration: dict[int, dict[str, int | str]]
    selected_mpls: tuple[tuple[str, str], ...]
    sp_entries: tuple[SpEntry, ...]
    episode_output_names: tuple[str, ...]
    episode_subtitle_languages: tuple[str, ...]
    movie_mode: bool = False
    episode_trim_copyright_tail: bool = False
    mux_dolby_vision: bool = True
    track_selection_config: dict[str, dict[str, list[str]]] | None = None
    track_language_config: dict[str, dict[str, str]] | None = None
    track_lossless_audio_config: dict[str, dict[str, str]] | None = None
    default_lossless_audio_codec: str = 'flac'
    ensure_tools: bool = False


@dataclass(frozen=True)
class RemuxMainJob:
    """One selected main playlist, its one command, and all planned outputs."""

    configuration_keys: tuple[int, ...]
    configurations: tuple[dict[str, int | str], ...]
    bdmv_index: int
    command: str
    m2ts_file: str
    volume: str
    primary_output: str
    mpls_path: str
    audio_tracks: tuple[str, ...]
    subtitle_tracks: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    final_outputs: tuple[str, ...]
    track_language_overrides: tuple[tuple[str, str], ...] = ()


__all__ = ['RemuxMainJob', 'RemuxRequest']
