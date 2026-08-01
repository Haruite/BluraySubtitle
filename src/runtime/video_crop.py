"""Automatic black-border detection and VapourSynth crop writing."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import random
import re
from dataclasses import dataclass

from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import run_command


_CROP_RE = re.compile(r'\bcrop=(\d+):(\d+):(\d+):(\d+)\b')
_VPY_CROP_START = '# BluraySubtitle automatic black-border crop: start'
_VPY_CROP_END = '# BluraySubtitle automatic black-border crop: end'


@dataclass(frozen=True)
class VideoCropPlan:
    """One fixed conservative crop derived from sampled source frames."""

    source_width: int
    source_height: int
    duration_seconds: float
    sample_count: int
    sampled_timestamps: tuple[float, ...]
    left: int = 0
    right: int = 0
    top: int = 0
    bottom: int = 0
    variable_borders: bool = False

    @property
    def output_width(self) -> int:
        return self.source_width - self.left - self.right

    @property
    def output_height(self) -> int:
        return self.source_height - self.top - self.bottom

    @property
    def has_crop(self) -> bool:
        return any((self.left, self.right, self.top, self.bottom))


def adaptive_crop_sample_count(duration_seconds: float) -> int:
    """Use one sample per 150 seconds, bounded to 4-24 samples."""
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError('Video duration must be positive')
    return max(4, min(24, math.ceil(duration_seconds / 150.0)))


def stratified_crop_timestamps(
        duration_seconds: float,
        sample_count: int,
        seed: str,
) -> tuple[float, ...]:
    """Choose one reproducible pseudo-random timestamp from each time bucket."""
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError('Video duration must be positive')
    if sample_count <= 0:
        raise ValueError('Sample count must be positive')
    edge_guard = min(5.0, duration_seconds * 0.02)
    usable_duration = duration_seconds - edge_guard * 2.0
    if usable_duration <= 0:
        edge_guard = 0.0
        usable_duration = duration_seconds
    random_source = random.Random(
        int.from_bytes(hashlib.sha256(seed.encode('utf-8')).digest()[:8], 'big')
    )
    bucket_width = usable_duration / sample_count
    return tuple(
        min(
            duration_seconds,
            edge_guard + bucket_width * (index + random_source.uniform(0.15, 0.85)),
        )
        for index in range(sample_count)
    )


def _probe_video_geometry_and_duration(video_path: str) -> tuple[int, int, float]:
    ffprobe_path = str(core_settings.FFPROBE_PATH or 'ffprobe').strip()
    result = run_command(
        [
            ffprobe_path,
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=width,height,duration:format=duration',
            '-of',
            'json',
            video_path,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or '').strip()
        raise RuntimeError(detail or translate_text(
            'Could not probe video dimensions and duration: {path}'
        ).format(path=video_path))
    try:
        payload = json.loads(result.stdout or '{}')
        stream = (payload.get('streams') or [])[0]
        width = int(stream['width'])
        height = int(stream['height'])
        duration = float(stream.get('duration') or payload['format']['duration'])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(
            translate_text('Could not probe video dimensions and duration: {path}').format(
                path=video_path
            )
        ) from error
    if width <= 0 or height <= 0 or not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(
            translate_text('Could not probe video dimensions and duration: {path}').format(
                path=video_path
            )
        )
    return width, height, duration


def _valid_crop_rectangles(
        text: str,
        source_width: int,
        source_height: int,
) -> list[tuple[int, int, int, int]]:
    rectangles: list[tuple[int, int, int, int]] = []
    for match in _CROP_RE.finditer(text):
        width, height, x, y = (int(value) for value in match.groups())
        if (
                width < source_width // 2
                or height < source_height // 2
                or x < 0
                or y < 0
                or x + width > source_width
                or y + height > source_height
        ):
            continue
        rectangles.append((x, y, x + width, y + height))
    return rectangles


def detect_black_borders(video_path: str) -> VideoCropPlan:
    """Detect a fixed crop from stratified time seeks without writing images."""
    source_path = os.path.abspath(os.path.normpath(video_path))
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)
    source_width, source_height, duration = _probe_video_geometry_and_duration(
        source_path
    )
    sample_count = adaptive_crop_sample_count(duration)
    timestamps = stratified_crop_timestamps(
        duration,
        sample_count,
        f'{os.path.normcase(source_path)}|{duration:.6f}',
    )
    ffmpeg_path = str(core_settings.FFMPEG_PATH or 'ffmpeg').strip()
    rectangles: list[tuple[int, int, int, int]] = []
    for timestamp in timestamps:
        result = run_command(
            [
                ffmpeg_path,
                '-hide_banner',
                '-loglevel',
                'info',
                '-nostdin',
                '-ss',
                f'{timestamp:.6f}',
                '-i',
                source_path,
                '-map',
                '0:v:0',
                '-an',
                '-sn',
                '-dn',
                '-frames:v',
                '3',
                '-vf',
                'cropdetect=limit=0.094:round=2:reset=1',
                '-f',
                'null',
                '-',
            ],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or '').strip()
            raise RuntimeError(detail or translate_text(
                'Automatic black-border analysis failed: {path}'
            ).format(path=source_path))
        rectangles.extend(_valid_crop_rectangles(
            f'{result.stdout or ""}\n{result.stderr or ""}',
            source_width,
            source_height,
        ))
    if not rectangles:
        raise RuntimeError(
            translate_text('Automatic black-border analysis returned no valid frames: {path}').format(
                path=source_path
            )
        )

    # The union of all active rectangles cannot remove pixels used by any sample.
    active_left = min(rectangle[0] for rectangle in rectangles)
    active_top = min(rectangle[1] for rectangle in rectangles)
    active_right = max(rectangle[2] for rectangle in rectangles)
    active_bottom = max(rectangle[3] for rectangle in rectangles)
    left = active_left - active_left % 2
    top = active_top - active_top % 2
    right = source_width - active_right
    right -= right % 2
    bottom = source_height - active_bottom
    bottom -= bottom % 2
    if source_width - left - right <= 0 or source_height - top - bottom <= 0:
        raise RuntimeError(
            translate_text('Automatic black-border analysis returned an invalid crop: {path}').format(
                path=source_path
            )
        )
    return VideoCropPlan(
        source_width=source_width,
        source_height=source_height,
        duration_seconds=duration,
        sample_count=sample_count,
        sampled_timestamps=timestamps,
        left=left,
        right=right,
        top=top,
        bottom=bottom,
        variable_borders=len(set(rectangles)) > 1,
    )


def write_vapoursynth_crop(
        vpy_path: str,
        crop_plan: VideoCropPlan | None,
) -> None:
    """Replace the task-owned managed crop block in a VapourSynth script."""
    script_path = os.path.abspath(os.path.normpath(vpy_path))
    with open(script_path, 'r', encoding='utf-8') as stream:
        lines = stream.readlines()

    cleaned_lines: list[str] = []
    inside_managed_block = False
    managed_block_found = False
    for line in lines:
        marker = line.strip()
        if marker == _VPY_CROP_START:
            if inside_managed_block:
                raise RuntimeError(
                    translate_text('VPy automatic crop block is incomplete: {path}').format(
                        path=script_path
                    )
                )
            inside_managed_block = True
            managed_block_found = True
            continue
        if marker == _VPY_CROP_END:
            if not inside_managed_block:
                raise RuntimeError(
                    translate_text('VPy automatic crop block is incomplete: {path}').format(
                        path=script_path
                    )
                )
            inside_managed_block = False
            continue
        if not inside_managed_block:
            cleaned_lines.append(line)
    if inside_managed_block:
        raise RuntimeError(
            translate_text('VPy automatic crop block is incomplete: {path}').format(
                path=script_path
            )
        )

    if crop_plan is not None and crop_plan.has_crop:
        insertion_index = None
        clip_name = 'src8'
        try:
            syntax_tree = ast.parse(''.join(cleaned_lines), filename=script_path)
        except SyntaxError as error:
            raise RuntimeError(
                translate_text('Could not find a safe VPy crop insertion point: {path}').format(
                    path=script_path
                )
            ) from error
        if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ('Crop', 'CropAbs')
                for node in ast.walk(syntax_tree)
        ):
            raise RuntimeError(
                translate_text(
                    'The VPy already contains a manual crop; automatic cropping '
                    'cannot also be applied: {path}'
                ).format(path=script_path)
            )
        for node in syntax_tree.body:
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if value is not None and any(
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id == 'src8'
                    for child in ast.walk(value)
            ):
                insertion_index = node.lineno - 1
                break
        if insertion_index is None:
            clip_name = 'res'
            for node in syntax_tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else [node.target]
                    )
                    target_is_res = any(
                        isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Store)
                        and child.id == 'res'
                        for target in targets
                        for child in ast.walk(target)
                    )
                    value_uses_res = any(
                        isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Load)
                        and child.id == 'res'
                        for child in ast.walk(node.value)
                    )
                    if target_is_res and value_uses_res:
                        insertion_index = node.lineno - 1
                        break
                if (
                        isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr in ('set_output', 'SetOutput')
                        and any(
                            isinstance(child, ast.Name) and child.id == 'res'
                            for child in ast.walk(node.value.func.value)
                        )
                ):
                    insertion_index = node.lineno - 1
                    break
        if insertion_index is None:
            raise RuntimeError(
                translate_text('Could not find a safe VPy crop insertion point: {path}').format(
                    path=script_path
                )
            )
        crop_lines = [
            _VPY_CROP_START + '\n',
            (
                f'{clip_name} = {clip_name}.std.Crop('
                f'left={crop_plan.left}, right={crop_plan.right}, '
                f'top={crop_plan.top}, bottom={crop_plan.bottom})\n'
            ),
            _VPY_CROP_END + '\n',
        ]
        cleaned_lines[insertion_index:insertion_index] = crop_lines

    if managed_block_found or (crop_plan is not None and crop_plan.has_crop):
        with open(script_path, 'w', encoding='utf-8', newline='') as stream:
            stream.write(''.join(cleaned_lines).replace('\r\n', '\n').replace('\n', '\r\n'))


__all__ = [
    'VideoCropPlan',
    'adaptive_crop_sample_count',
    'detect_black_borders',
    'stratified_crop_timestamps',
    'write_vapoursynth_crop',
]
