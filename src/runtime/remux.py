"""Plain-data contracts for the Blu-ray Remux workflow."""

from __future__ import annotations

from dataclasses import dataclass

from src.runtime.audio_conversion import AudioEncodingSettings
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
    language_code: str = 'en'
    movie_mode: bool = False
    mux_dolby_vision: bool = True
    convert_lossless_audio_to_flac: bool = True
    clean_audio_tracks: bool = True
    audio_encoding: AudioEncodingSettings = AudioEncodingSettings()
    # ``main::`` and MPLS-backed ``sp::`` values are MPEG PIDs grouped by type.
    # MKV and no-MPLS single-M2TS SP keys retain source-local track IDs.
    track_selection_config: dict[str, dict[str, list[str]]] | None = None
    track_language_config: dict[str, dict[str, str]] | None = None
    ensure_tools: bool = False


@dataclass(frozen=True)
class RemuxMainJob:
    """One selected main playlist, its PID selection, command, and planned outputs."""

    configuration_keys: tuple[int, ...]
    configurations: tuple[dict[str, int | str], ...]
    bdmv_index: int
    command: str
    m2ts_file: str
    volume: str
    primary_output: str
    mpls_path: str
    # Main-job values are decimal PID strings retained for command placeholders and logs.
    audio_tracks: tuple[str, ...]
    subtitle_tracks: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    final_outputs: tuple[str, ...]
    m2ts_file_details: tuple[str, ...] = ()
    track_language_overrides: tuple[tuple[str, str], ...] = ()
    # Canonical main-track contract: (``video`` | ``audio`` | ``subtitles``, MPEG PID).
    # Tuple order follows MPLS identify only; GUI row order has no runtime meaning.
    track_pids: tuple[tuple[str, int], ...] = ()


__all__ = ['RemuxMainJob', 'RemuxRequest']
