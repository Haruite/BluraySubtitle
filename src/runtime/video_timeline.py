"""Preserve source presentation timestamps through frame-preserving Encode."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Event

from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import run_command
from src.runtime import TaskCancelled


VPY_HARDSUB_CALL = (
    'res = core.assrender.TextSub(res, file=sub_file, '
    'vfr=os.environ.get("BLURAYSUB_VPY_TIMECODES"))'
)
VPY_LEGACY_HARDSUB_CALL = 'res = core.assrender.TextSub(res, file=sub_file)'


@dataclass(frozen=True)
class VideoTimeline:
    """Absolute frame starts followed by one end timestamp, in nanoseconds."""

    timestamps_ns: tuple[int, ...]

    @classmethod
    def read(cls, path: str) -> VideoTimeline:
        try:
            with open(path, encoding='utf-8-sig') as stream:
                timestamps = tuple(
                    int(Decimal(line.strip()) * 1_000_000)
                    for line in stream
                    if line.strip() and not line.lstrip().startswith('#')
                )
            # mkvextract appends the end of the last frame to timestamps_v2.
            if len(timestamps) < 2 or any(
                    end <= start for start, end in zip(timestamps, timestamps[1:])
            ):
                raise ValueError('Missing or non-increasing video timestamps')
        except (OSError, ValueError, OverflowError, InvalidOperation) as error:
            raise ValueError(translate_text(
                'Invalid video timestamps: {path}'
            ).format(path=path)) from error
        return cls(timestamps)

    def write_prefix(self, path: str, frame_count: int) -> VideoTimeline:
        """Keep the first N frames and their end; do not rebase the source clock."""
        if not 0 < frame_count < len(self.timestamps_ns):
            raise ValueError(translate_text(
                'Video timestamps cover {source_frames} frames, but VPy outputs {output_frames}'
            ).format(
                source_frames=len(self.timestamps_ns) - 1,
                output_frames=frame_count,
            ))
        prefix = VideoTimeline(self.timestamps_ns[:frame_count + 1])
        with open(path, 'x', encoding='utf-8', newline='\r\n') as stream:
            stream.write('# timecode format v2\n')
            for timestamp in prefix.timestamps_ns:
                stream.write(f'{Decimal(timestamp) / 1_000_000:f}\n')
        return prefix


def extract_video_timeline(
        source_path: str,
        track_id: int,
        timestamps_path: str,
        cancel_event: Event | None = None,
) -> VideoTimeline:
    """Read the container timeline once without decoding the source video."""
    if os.path.exists(timestamps_path):
        raise FileExistsError(timestamps_path)
    if cancel_event is not None and cancel_event.is_set():
        raise TaskCancelled()
    command = [
        str(core_settings.MKV_EXTRACT_PATH or 'mkvextract'),
        source_path, 'timestamps_v2', f'{track_id}:{timestamps_path}',
    ]
    process_options = {}
    if os.name == 'nt':
        process_options['creationflags'] = subprocess.CREATE_NO_WINDOW
    process = run_command(
        command, wait=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', **process_options,
    )
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise TaskCancelled()
            try:
                output, _ = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                continue
        # MKVToolNix exit code 1 is a completed operation with warnings.
        if process.returncode not in (0, 1):
            raise RuntimeError(translate_text(
                'Video timestamp extraction failed: {path}. {error}'
            ).format(path=source_path, error=output.strip()))
        if process.returncode == 1:
            print(output, flush=True)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    timeline = VideoTimeline.read(timestamps_path)
    # assrender accepts the original timecode header, not mkvextract's newer spelling.
    with open(timestamps_path, 'r+', encoding='utf-8', newline='') as stream:
        contents = stream.read().replace('# timestamp format v2', '# timecode format v2', 1)
        stream.seek(0)
        stream.write(contents)
        stream.truncate()
    return timeline
