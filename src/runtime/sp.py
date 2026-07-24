"""Plain-data contracts for Blu-ray bonus SP processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


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


__all__ = ['SpEntry', 'SpJob']
