"""Preserve source presentation timestamps through frame-preserving Encode."""

from __future__ import annotations

import heapq
import os
import queue
import re
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Event, Thread

from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import run_command
from src.runtime import TaskCancelled


VPY_HARDSUB_CALL = (
    'res = core.assrender.TextSub('
    'res[:int(os.environ.get("BLURAYSUB_VPY_FRAMES", res.num_frames))], '
    'file=sub_file, vfr=os.environ.get("BLURAYSUB_VPY_TIMECODES"))'
)
VPY_LEGACY_HARDSUB_CALLS = (
    'res = core.assrender.TextSub(res, file=sub_file)',
    'res = core.assrender.TextSub(res, file=sub_file, '
    'vfr=os.environ.get("BLURAYSUB_VPY_TIMECODES"))',
)
VPY_HARDSUB_PATTERN = (
    r'^(\s*)(#\s*)?('
    + '|'.join(re.escape(call) for call in (VPY_HARDSUB_CALL, *VPY_LEGACY_HARDSUB_CALLS))
    + r'|res\s*=\s*core\.assrender\.TextSub\(\s*res\s*,\s*file\s*=\s*sub_file\s*\))'
    r'(\s*(#.*)?)$'
)


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


def _extract_prefix_timeline(
        source_path: str,
        timestamps_path: str,
        frame_count: int,
        cancel_event: Event | None,
) -> VideoTimeline:
    """Read packets through the prefix boundary without decoding video frames."""
    command = [
        str(core_settings.FFPROBE_PATH or 'ffprobe'),
        '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'packet=pts_time,dts_time',
        '-of', 'compact=p=0:nk=0', source_path,
    ]
    lines: queue.Queue[str | None] = queue.Queue(maxsize=32)
    stop_reader = Event()
    # Keep the earliest N+1 presentation times while packets arrive in decode order.
    timestamps: list[int] = []
    boundary_reached = False
    stopped_at_boundary = False
    process_options = {}
    if os.name == 'nt':
        process_options['creationflags'] = subprocess.CREATE_NO_WINDOW
    with tempfile.TemporaryFile(mode='w+b') as errors:
        process = run_command(
            command, wait=False, stdout=subprocess.PIPE, stderr=errors,
            text=True, encoding='utf-8', errors='replace', **process_options,
        )

        def read_output() -> None:
            def enqueue(line: str | None) -> None:
                while not stop_reader.is_set():
                    try:
                        lines.put(line, timeout=0.1)
                        return
                    except queue.Full:
                        continue

            try:
                for line in process.stdout:
                    enqueue(line)
                    if stop_reader.is_set():
                        break
            finally:
                enqueue(None)

        reader = Thread(target=read_output, daemon=True)
        reader.start()
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise TaskCancelled()
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    process.wait()
                    break
                fields = dict(
                    item.split('=', 1) for item in line.strip().split('|')
                    if '=' in item
                )
                if 'pts_time' not in fields:
                    continue
                timestamp = int(Decimal(fields['pts_time']) * 1_000_000_000)
                heapq.heappush(timestamps, -timestamp)
                if len(timestamps) > frame_count + 1:
                    heapq.heappop(timestamps)
                dts = fields.get('dts_time', 'N/A')
                # Later packets cannot present before this decode timestamp.
                # Merely taking N+1 packets would miss reordered B frames.
                if (
                        len(timestamps) == frame_count + 1 and dts != 'N/A'
                        and int(Decimal(dts) * 1_000_000_000) >= -timestamps[0]
                ):
                    boundary_reached = True
                    break
        finally:
            stop_reader.set()
            if process.poll() is None:
                stopped_at_boundary = boundary_reached
                process.kill()
            process.wait()
            reader.join()
            process.stdout.close()
        errors.seek(0)
        error_text = errors.read().decode('utf-8', errors='replace').strip()
        if process.returncode != 0 and not stopped_at_boundary:
            raise RuntimeError(translate_text(
                'Video timestamp extraction failed: {path}. {error}'
            ).format(path=source_path, error=error_text))
    ordered = tuple(sorted(-value for value in timestamps))
    if len(ordered) != frame_count + 1 or any(
            end <= start for start, end in zip(ordered, ordered[1:])
    ):
        raise ValueError(translate_text(
            'Invalid video timestamps: {path}'
        ).format(path=source_path))
    return VideoTimeline(ordered).write_prefix(timestamps_path, frame_count)


def extract_video_timeline(
        source_path: str,
        track_id: int,
        timestamps_path: str,
        cancel_event: Event | None = None,
        *,
        frame_count: int | None = None,
        source_frame_count: int | None = None,
) -> VideoTimeline:
    """Read the container timeline once without decoding the source video."""
    if os.path.exists(timestamps_path):
        raise FileExistsError(timestamps_path)
    if cancel_event is not None and cancel_event.is_set():
        raise TaskCancelled()
    if (
            frame_count is not None and source_frame_count is not None
            and frame_count < source_frame_count
    ):
        return _extract_prefix_timeline(
            source_path, timestamps_path, frame_count, cancel_event,
        )
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
    if frame_count is not None:
        if not 0 < frame_count < len(timeline.timestamps_ns):
            raise ValueError(translate_text(
                'Video timestamps cover {source_frames} frames, but VPy outputs {output_frames}'
            ).format(
                source_frames=len(timeline.timestamps_ns) - 1,
                output_frames=frame_count,
            ))
        if frame_count < len(timeline.timestamps_ns) - 1:
            # Custom scripts without the source output still support prefix trims.
            timeline = VideoTimeline(timeline.timestamps_ns[:frame_count + 1])
            with open(timestamps_path, 'w', encoding='utf-8', newline='\r\n') as stream:
                stream.write('# timecode format v2\n')
                for timestamp in timeline.timestamps_ns:
                    stream.write(f'{Decimal(timestamp) / 1_000_000:f}\n')
            return timeline
    # assrender needs the original header. Preserve its byte length so the rest
    # of the timestamp file needs neither a second read nor a rewrite.
    with open(timestamps_path, 'r+b') as stream:
        header = stream.readline()
        normalized = header.replace(b'timestamp format v2', b'timecode format v2 ')
        if normalized != header:
            stream.seek(0)
            stream.write(normalized)
    return timeline
