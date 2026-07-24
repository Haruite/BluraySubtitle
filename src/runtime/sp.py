"""Plain-data contracts for Blu-ray bonus SP processing."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Mapping

from src.exports.utils import parse_time_to_seconds

_M2TS_DETAIL_SEGMENT_RE = re.compile(r'^(.+?)\(([^)]+)-([^)]+)\)\s*$')


def media_track_key(kind: str, path: str) -> str:
    """Build the shared key for a main-playlist or MKV track configuration."""
    return f'{kind}::{os.path.normpath(path)}'


def parse_m2ts_file_detail_segments(detail: str) -> list[tuple[str, float, float]]:
    """Parse clip/time ranges displayed by the SP and episode tables."""
    segments: list[tuple[str, float, float]] = []
    for part in str(detail or '').strip().split(','):
        piece = part.strip()
        if not piece:
            continue
        match = _M2TS_DETAIL_SEGMENT_RE.match(piece)
        if not match:
            return []
        segments.append((
            match.group(1).strip(),
            parse_time_to_seconds(match.group(2)),
            parse_time_to_seconds(match.group(3)),
        ))
    return segments


def filter_m2ts_file_detail_by_basenames(detail: str, basenames: list[str]) -> str:
    """Keep only clip ranges whose basename is selected."""
    wanted = {
        os.path.basename(str(basename or '')).strip().lower()
        for basename in basenames if str(basename or '').strip()
    }
    if not wanted:
        return str(detail or '').strip()
    return ','.join(
        piece for part in str(detail or '').split(',')
        if (piece := part.strip()) and piece.split('(', 1)[0].strip().lower() in wanted
    )


def m2ts_file_detail_segments_contained_in(
        sp_detail: str, episode_detail: str, *, eps: float = 0.05) -> bool:
    """Return whether every SP clip range is contained in an episode clip range."""
    sp_segments = parse_m2ts_file_detail_segments(sp_detail)
    episode_segments = parse_m2ts_file_detail_segments(episode_detail)
    if not sp_segments or not episode_segments:
        return False
    for name, start, end in sp_segments:
        if end <= start + eps:
            continue
        if not any(
                episode_name == name and start + eps >= episode_start and end <= episode_end + eps
                for episode_name, episode_start, episode_end in episode_segments):
            return False
    return True


@dataclass(frozen=True)
class SpEntry:
    """One visible SP row captured at task launch."""

    bdmv_index: int
    bdmv_root: str
    mpls_file: str
    m2ts_files: tuple[str, ...]
    m2ts_file_detail: str
    m2ts_type: str
    output_name: str
    selected: bool

    @classmethod
    def from_mapping(cls, entry: Mapping[str, object]) -> 'SpEntry':
        """Normalize one GUI or batch SP row without changing its meaning."""
        try:
            bdmv_index = int(entry.get('bdmv_index') or 0)
        except (TypeError, ValueError):
            bdmv_index = 0
        raw_m2ts = str(entry.get('m2ts_file') or '')
        return cls(
            bdmv_index=bdmv_index,
            bdmv_root=str(entry.get('bdmv_root') or '').strip(),
            mpls_file=str(entry.get('mpls_file') or '').strip(),
            m2ts_files=tuple(
                filename.strip()
                for filename in raw_m2ts.split(',')
                if filename.strip()
            ),
            m2ts_file_detail=str(entry.get('m2ts_file_detail') or '').strip(),
            m2ts_type=str(entry.get('m2ts_type') or '').strip(),
            output_name=str(entry.get('output_name') or '').strip(),
            selected=bool(entry.get('selected', True)),
        )

    @property
    def track_key(self) -> str:
        """Key used by captured track-selection and language settings."""
        if self.mpls_file:
            return f'sp::{self.bdmv_index}::mpls::{self.mpls_file}'
        first_m2ts = self.m2ts_files[0] if self.m2ts_files else ''
        return f'sp::{self.bdmv_index}::m2ts::{first_m2ts}'


@dataclass(frozen=True)
class SpJob:
    """One selected SP row with resolved source, tracks, and exact output."""

    entry_index: int
    entry: SpEntry
    source_path: str
    first_m2ts_path: str
    output_path: str
    main_mpls_path: str
    episode_main_mpls_path: str
    audio_tracks: tuple[str, ...]
    subtitle_tracks: tuple[str, ...]
    track_language_overrides: tuple[tuple[str, str], ...]


__all__ = [
    'SpEntry', 'SpJob', 'media_track_key',
    'parse_m2ts_file_detail_segments', 'm2ts_file_detail_segments_contained_in',
    'filter_m2ts_file_detail_by_basenames',
]
