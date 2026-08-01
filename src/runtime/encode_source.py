"""Actual media-source discovery and non-blocking HDR automation reports."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Sequence

from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import run_command


_X265_DYNAMIC_METADATA_OPTIONS = (
    '--dhdr10-info',
    '--dolby-vision-profile',
    '--dolby-vision-rpu',
)
_X265_OPTION_CACHE: dict[tuple[str, int, int], frozenset[str]] = {}


@dataclass(frozen=True)
class ActualEncodeSource:
    """The video stream in the media file actually loaded by VapourSynth."""

    path: str
    stream_index: int
    codec_name: str
    stream: dict[str, object] = field(repr=False, compare=False)


@dataclass(frozen=True)
class SourceColorMetadata:
    """Normalized color and static HDR metadata from one FFprobe video stream."""

    color_range: str | None
    color_primaries: str | None
    color_transfer: str | None
    color_matrix: str | None
    chroma_location: str | None
    mastering_display_x26x: str | None
    mastering_display_svt: str | None
    content_light_level: str | None


class VapourSynthOutputMetadataMismatch(RuntimeError):
    """The sampled output frames cannot share one set of encoder metadata."""


_X26X_COLOR_PRIMARIES = frozenset({
    'bt709',
    'bt470m',
    'bt470bg',
    'smpte170m',
    'smpte240m',
    'film',
    'bt2020',
    'smpte428',
    'smpte431',
    'smpte432',
})
_X26X_COLOR_TRANSFERS = frozenset({
    'bt709',
    'bt470m',
    'bt470bg',
    'smpte170m',
    'smpte240m',
    'linear',
    'log100',
    'log316',
    'iec61966-2-4',
    'bt1361e',
    'iec61966-2-1',
    'bt2020-10',
    'bt2020-12',
    'smpte2084',
    'smpte428',
    'arib-std-b67',
})
_X26X_COLOR_MATRICES = frozenset({
    'gbr',
    'bt709',
    'fcc',
    'bt470bg',
    'smpte170m',
    'smpte240m',
    'ycgco',
    'bt2020nc',
    'bt2020c',
    'smpte2085',
    'chroma-derived-nc',
    'chroma-derived-c',
    'ictcp',
})
_SVT_COLOR_PRIMARIES = {
    'bt709': '1',
    'bt470m': '4',
    'bt470bg': '5',
    'smpte170m': '6',
    'smpte240m': '7',
    'film': '8',
    'bt2020': '9',
    'smpte428': '10',
    'smpte431': '11',
    'smpte432': '12',
    'ebu3213': '22',
    'jedec-p22': '22',
}
_SVT_COLOR_TRANSFERS = {
    'bt709': '1',
    'bt470m': '4',
    'bt470bg': '5',
    'smpte170m': '6',
    'smpte240m': '7',
    'linear': '8',
    'log100': '9',
    'log316': '10',
    'iec61966-2-4': '11',
    'bt1361e': '12',
    'iec61966-2-1': '13',
    'bt2020-10': '14',
    'bt2020-12': '15',
    'smpte2084': '16',
    'smpte428': '17',
    'arib-std-b67': '18',
}
_SVT_COLOR_MATRICES = {
    'gbr': '0',
    'rgb': '0',
    'bt709': '1',
    'fcc': '4',
    'bt470bg': '5',
    'smpte170m': '6',
    'smpte240m': '7',
    'ycgco': '8',
    'bt2020nc': '9',
    'bt2020c': '10',
    'smpte2085': '11',
    'chroma-derived-nc': '12',
    'chroma-derived-c': '13',
    'ictcp': '14',
}
_X26X_CHROMA_LOCATIONS = {
    'left': '0',
    'center': '1',
    'topleft': '2',
    'top-left': '2',
    'top': '3',
    'bottomleft': '4',
    'bottom-left': '4',
    'bottom': '5',
}
_SVT_CHROMA_LOCATIONS = {
    'left': 'left',
    'vertical': 'left',
    'topleft': 'topleft',
    'top-left': 'topleft',
    'colocated': 'topleft',
}
_VS_COLOR_PRIMARIES = {
    int(value): name
    for name, value in reversed(tuple(_SVT_COLOR_PRIMARIES.items()))
}
_VS_COLOR_TRANSFERS = {
    int(value): name
    for name, value in reversed(tuple(_SVT_COLOR_TRANSFERS.items()))
}
_VS_COLOR_MATRICES = {
    int(value): name
    for name, value in reversed(tuple(_SVT_COLOR_MATRICES.items()))
}
_VS_OUTPUT_PROBE_SCRIPT = """import json
import os
import runpy
import sys
import vapoursynth as vs

source_path = os.environ['BLURAYSUB_VPY_PROBE_SCRIPT']
sys.path.insert(0, os.path.dirname(source_path))
runpy.run_path(source_path, run_name='__vapoursynth__')
output = vs.get_output(0)
clip = getattr(output, 'clip', output)
indices = sorted({0, clip.num_frames // 2, clip.num_frames - 1})
names = ('_ColorRange', '_Range', '_Primaries', '_Transfer', '_Matrix', '_ChromaLocation')
samples = []
for index in indices:
    frame = clip.get_frame(index)
    sample = {name: int(frame.props[name]) for name in names if name in frame.props}
    if '_ColorRange' not in sample and '_Range' in sample:
        sample['_ColorRange'] = sample.pop('_Range')
    samples.append(sample)
with open(os.environ['BLURAYSUB_VPY_PROBE_RESULT'], 'w', encoding='utf-8') as output:
    json.dump({
        'timeline': [clip.num_frames, clip.fps_num, clip.fps_den],
        'samples': samples,
    }, output)
"""


def _metadata_fraction(value: object) -> Fraction | None:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def _scaled_metadata_value(
        value: object,
        scale: int,
        already_scaled_threshold: int,
        maximum: int,
) -> tuple[int, Fraction] | None:
    parsed = _metadata_fraction(value)
    if parsed is None or parsed < 0:
        return None
    if parsed <= already_scaled_threshold:
        physical = parsed
        scaled_fraction = parsed * scale
    else:
        scaled_fraction = parsed
        physical = parsed / scale
    scaled = (
        scaled_fraction.numerator * 2 + scaled_fraction.denominator
    ) // (2 * scaled_fraction.denominator)
    if scaled < 0 or scaled > maximum:
        return None
    return scaled, physical


def _format_fraction(value: Fraction) -> str:
    with localcontext() as context:
        context.prec = 24
        text = format(
            Decimal(value.numerator) / Decimal(value.denominator),
            'f',
        )
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _mastering_display_values(
        side_data: dict[str, object],
) -> tuple[str, str] | None:
    chromaticity_fields = (
        'green_x',
        'green_y',
        'blue_x',
        'blue_y',
        'red_x',
        'red_y',
        'white_point_x',
        'white_point_y',
    )
    chromaticities = [
        _scaled_metadata_value(side_data.get(name), 50_000, 1, 50_000)
        for name in chromaticity_fields
    ]
    max_luminance = _scaled_metadata_value(
        side_data.get('max_luminance'),
        10_000,
        10_000,
        0xFFFFFFFF,
    )
    min_luminance = _scaled_metadata_value(
        side_data.get('min_luminance'),
        10_000,
        10_000,
        0xFFFFFFFF,
    )
    if any(value is None for value in chromaticities):
        return None
    if max_luminance is None or min_luminance is None:
        return None
    if min_luminance[1] > max_luminance[1]:
        return None

    values = [value for value in chromaticities if value is not None]
    scaled = [value[0] for value in values]
    physical = [value[1] for value in values]
    x26x_value = (
        f'G({scaled[0]},{scaled[1]})'
        f'B({scaled[2]},{scaled[3]})'
        f'R({scaled[4]},{scaled[5]})'
        f'WP({scaled[6]},{scaled[7]})'
        f'L({max_luminance[0]},{min_luminance[0]})'
    )
    svt_value = (
        f'G({_format_fraction(physical[0])},{_format_fraction(physical[1])})'
        f'B({_format_fraction(physical[2])},{_format_fraction(physical[3])})'
        f'R({_format_fraction(physical[4])},{_format_fraction(physical[5])})'
        f'WP({_format_fraction(physical[6])},{_format_fraction(physical[7])})'
        f'L({_format_fraction(max_luminance[1])},{_format_fraction(min_luminance[1])})'
    )
    return x26x_value, svt_value


def _content_light_level_value(side_data: dict[str, object]) -> str | None:
    max_content = _scaled_metadata_value(
        side_data.get('max_content'),
        1,
        65_535,
        65_535,
    )
    max_average = _scaled_metadata_value(
        side_data.get('max_average'),
        1,
        65_535,
        65_535,
    )
    if max_content is None or max_average is None:
        return None
    return f'{max_content[0]},{max_average[0]}'


def _normalized_metadata_text(value: object) -> str | None:
    normalized = str(value or '').strip().lower()
    if normalized in ('', 'unknown', 'unspecified', 'reserved', 'undef', 'n/a'):
        return None
    return normalized


def parse_source_color_metadata(source: ActualEncodeSource) -> SourceColorMetadata:
    """Normalize color fields and static HDR side data from an actual source."""
    mastering_display_x26x = None
    mastering_display_svt = None
    content_light_level = None
    side_data_list = source.stream.get('side_data_list')
    if isinstance(side_data_list, list):
        for side_data in side_data_list:
            if not isinstance(side_data, dict):
                continue
            side_data_type = str(side_data.get('side_data_type') or '').lower()
            if (
                    mastering_display_x26x is None
                    and 'mastering display metadata' in side_data_type
            ):
                mastering_values = _mastering_display_values(side_data)
                if mastering_values is not None:
                    mastering_display_x26x, mastering_display_svt = mastering_values
            if (
                    content_light_level is None
                    and 'content light level metadata' in side_data_type
            ):
                content_light_level = _content_light_level_value(side_data)

    return SourceColorMetadata(
        color_range=_normalized_metadata_text(source.stream.get('color_range')),
        color_primaries=_normalized_metadata_text(
            source.stream.get('color_primaries')
        ),
        color_transfer=_normalized_metadata_text(
            source.stream.get('color_transfer')
        ),
        color_matrix=_normalized_metadata_text(source.stream.get('color_space')),
        chroma_location=_normalized_metadata_text(
            source.stream.get('chroma_location')
        ),
        mastering_display_x26x=mastering_display_x26x,
        mastering_display_svt=mastering_display_svt,
        content_light_level=content_light_level,
    )


def arguments_contain_option(
        arguments: Sequence[str],
        *option_names: str,
) -> bool:
    normalized_names = tuple(name.lower() for name in option_names)
    for argument in arguments:
        normalized = str(argument or '').strip().lower()
        if any(
                normalized == name
                or normalized.startswith(f'{name}=')
                or normalized.startswith(f'{name} ')
                for name in normalized_names
        ):
            return True
    return False


def build_automatic_encoder_metadata_arguments(
        source: ActualEncodeSource,
        encoder: str,
        manual_arguments: Sequence[str],
) -> tuple[str, ...]:
    """Build supported metadata arguments without overriding manual options."""
    normalized_encoder = str(encoder or '').strip().lower()
    if (
            normalized_encoder == 'x265'
            and arguments_contain_option(
                manual_arguments,
                '--video-signal-type-preset',
            )
    ):
        return ()

    metadata = parse_source_color_metadata(source)
    arguments: list[str] = []

    def add_option(
            option_name: str,
            value: str | None,
            *conflicting_names: str,
    ) -> None:
        if value is None or arguments_contain_option(
                manual_arguments,
                option_name,
                *conflicting_names,
        ):
            return
        arguments.extend((option_name, value))

    if normalized_encoder in ('x264', 'x265'):
        range_values = (
            {'tv': 'tv', 'limited': 'tv', 'pc': 'pc', 'full': 'pc'}
            if normalized_encoder == 'x264'
            else {
                'tv': 'limited',
                'limited': 'limited',
                'pc': 'full',
                'full': 'full',
            }
        )
        add_option(
            '--range',
            range_values.get(metadata.color_range or ''),
            *(('--fullrange',) if normalized_encoder == 'x264' else ()),
        )
        add_option(
            '--colorprim',
            metadata.color_primaries
            if metadata.color_primaries in _X26X_COLOR_PRIMARIES
            else None,
        )
        add_option(
            '--transfer',
            metadata.color_transfer
            if metadata.color_transfer in _X26X_COLOR_TRANSFERS
            else None,
        )
        add_option(
            '--colormatrix',
            metadata.color_matrix
            if metadata.color_matrix in _X26X_COLOR_MATRICES
            else None,
        )
        add_option(
            '--chromaloc',
            _X26X_CHROMA_LOCATIONS.get(metadata.chroma_location or ''),
        )
        if normalized_encoder == 'x264':
            add_option(
                '--mastering-display',
                metadata.mastering_display_x26x,
            )
            add_option('--cll', metadata.content_light_level)
        else:
            add_option('--master-display', metadata.mastering_display_x26x)
            add_option('--max-cll', metadata.content_light_level)
        return tuple(arguments)

    if normalized_encoder == 'svtav1':
        add_option(
            '--color-range',
            {
                'tv': '0',
                'limited': '0',
                'pc': '1',
                'full': '1',
            }.get(metadata.color_range or ''),
        )
        add_option(
            '--color-primaries',
            _SVT_COLOR_PRIMARIES.get(metadata.color_primaries or ''),
        )
        add_option(
            '--transfer-characteristics',
            _SVT_COLOR_TRANSFERS.get(metadata.color_transfer or ''),
        )
        add_option(
            '--matrix-coefficients',
            _SVT_COLOR_MATRICES.get(metadata.color_matrix or ''),
        )
        add_option(
            '--chroma-sample-position',
            _SVT_CHROMA_LOCATIONS.get(metadata.chroma_location or ''),
        )
        add_option('--mastering-display', metadata.mastering_display_svt)
        add_option('--content-light', metadata.content_light_level)
    return tuple(arguments)


def probe_actual_encode_source(source_path: str) -> ActualEncodeSource:
    """Probe the first video stream from the resolved per-row Encode source."""
    normalized_path = os.path.abspath(os.path.normpath(str(source_path or '').strip()))
    if not os.path.isfile(normalized_path):
        raise FileNotFoundError(
            translate_text('Actual encode source does not exist: {path}').format(
                path=normalized_path
            )
        )

    executable = str(core_settings.FFPROBE_PATH or '').strip() or 'ffprobe'
    result = run_command(
        [
            executable,
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-read_intervals',
            '%+#1',
            '-show_streams',
            '-show_frames',
            '-of',
            'json',
            normalized_path,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=120,
    )
    if result.returncode != 0:
        error = str(result.stderr or '').strip()
        raise RuntimeError(
            error
            or translate_text('FFprobe exited with code {code}').format(
                code=result.returncode
            )
        )

    try:
        document = json.loads(result.stdout or '{}')
    except json.JSONDecodeError as error:
        raise RuntimeError(
            translate_text('FFprobe returned invalid JSON: {error}').format(
                error=error
            )
        ) from error
    streams = document.get('streams') if isinstance(document, dict) else None
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        raise RuntimeError(translate_text('FFprobe did not return a video stream'))
    stream = dict(streams[0])
    stream_side_data = stream.get('side_data_list')
    merged_side_data = (
        list(stream_side_data)
        if isinstance(stream_side_data, list)
        else []
    )
    frames = document.get('frames')
    if isinstance(frames, list) and frames and isinstance(frames[0], dict):
        frame_side_data = frames[0].get('side_data_list')
        if isinstance(frame_side_data, list):
            for side_data in frame_side_data:
                if side_data not in merged_side_data:
                    merged_side_data.append(side_data)
    if merged_side_data:
        stream['side_data_list'] = merged_side_data
    try:
        stream_index = int(stream.get('index', 0))
    except (TypeError, ValueError):
        stream_index = 0
    codec_name = str(stream.get('codec_name') or 'unknown').strip().lower()
    return ActualEncodeSource(
        path=normalized_path,
        stream_index=stream_index,
        codec_name=codec_name,
        stream=stream,
    )


def probe_vapoursynth_output_metadata(
        source: ActualEncodeSource,
        vpy_path: str,
        vspipe_executable: str,
        environment: dict[str, str],
) -> tuple[ActualEncodeSource, bool, tuple[int, int, int]]:
    """Overlay stable final-output frame properties on the source snapshot."""
    script_path = os.path.abspath(os.path.normpath(vpy_path))
    with tempfile.TemporaryDirectory(
            prefix='_vpy_probe_',
    ) as work_folder:
        wrapper_path = os.path.join(work_folder, 'probe.vpy')
        result_path = os.path.join(work_folder, 'result.json')
        with open(wrapper_path, 'w', encoding='utf-8', newline='\n') as wrapper:
            wrapper.write(_VS_OUTPUT_PROBE_SCRIPT)
        probe_environment = dict(environment)
        probe_environment['BLURAYSUB_VPY_PROBE_SCRIPT'] = script_path
        probe_environment['BLURAYSUB_VPY_PROBE_RESULT'] = result_path
        result = run_command(
            [vspipe_executable, '--preserve-cwd', '--info', wrapper_path],
            cwd=os.path.dirname(script_path),
            env=probe_environment,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                str(result.stderr or '').strip()
                or translate_text('VapourSynth output probe exited with code {code}').format(
                    code=result.returncode
                )
            )
        try:
            with open(result_path, 'r', encoding='utf-8') as probe_result:
                document = json.load(probe_result)
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                translate_text('VapourSynth output probe returned invalid data: {error}').format(
                    error=error
                )
            ) from error

    samples = document.get('samples') if isinstance(document, dict) else None
    timeline = document.get('timeline') if isinstance(document, dict) else None
    if (
            not isinstance(samples, list)
            or not samples
            or not all(isinstance(sample, dict) for sample in samples)
            or not isinstance(timeline, list)
            or len(timeline) != 3
    ):
        raise RuntimeError(translate_text('VapourSynth output probe returned no frame properties'))
    try:
        output_timeline = tuple(int(value) for value in timeline)
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            translate_text('VapourSynth output probe returned invalid data: {error}').format(
                error=error
            )
        ) from error
    if any(value <= 0 for value in output_timeline):
        raise RuntimeError(translate_text('VapourSynth output probe returned no frame properties'))
    properties = dict(samples[0])
    if any(sample != properties for sample in samples[1:]):
        raise VapourSynthOutputMetadataMismatch(
            translate_text('VapourSynth output frame properties are inconsistent')
        )

    mappings = (
        ('_ColorRange', 'color_range', {0: 'pc', 1: 'tv'}),
        ('_Primaries', 'color_primaries', _VS_COLOR_PRIMARIES),
        ('_Transfer', 'color_transfer', _VS_COLOR_TRANSFERS),
        ('_Matrix', 'color_space', _VS_COLOR_MATRICES),
        ('_ChromaLocation', 'chroma_location', {
            0: 'left', 1: 'center', 2: 'topleft',
            3: 'top', 4: 'bottomleft', 5: 'bottom',
        }),
    )
    stream = dict(source.stream)
    updates = {
        field: values.get(int(properties[prop]))
        for prop, field, values in mappings
        if prop in properties
    }
    color_changed = any(
        field in updates
        and _normalized_metadata_text(stream.get(field)) is not None
        and updates[field] != _normalized_metadata_text(stream.get(field))
        for field in ('color_primaries', 'color_transfer')
    )
    stream.update(updates)
    side_data = stream.get('side_data_list')
    if color_changed and isinstance(side_data, list):
        stream['side_data_list'] = [
            item for item in side_data
            if not isinstance(item, dict) or not any(
                name in str(item.get('side_data_type') or '').lower()
                for name in ('mastering display metadata', 'content light level metadata')
            )
        ]
    return (
        ActualEncodeSource(
            source.path,
            source.stream_index,
            source.codec_name,
            stream,
        ),
        color_changed,
        output_timeline,
    )


def source_has_hdr10plus(source: ActualEncodeSource) -> bool:
    """Return whether FFprobe exposed ST 2094-40 metadata on the source."""
    side_data = source.stream.get('side_data_list')
    if not isinstance(side_data, list):
        return False
    for item in side_data:
        if not isinstance(item, dict):
            continue
        name = str(item.get('side_data_type') or '').lower()
        if 'hdr10+' in name or 'smpte2094-40' in name.replace(' ', ''):
            return True
    return False


def probe_x265_dynamic_metadata_options(executable: str) -> frozenset[str]:
    """Return dynamic-metadata options advertised by this exact x265 binary."""
    executable_path = shutil.which(executable) or executable
    executable_path = os.path.abspath(os.path.normpath(executable_path))
    try:
        identity = os.stat(executable_path)
    except OSError:
        return frozenset()
    cache_key = (
        os.path.normcase(executable_path),
        identity.st_size,
        identity.st_mtime_ns,
    )
    cached = _X265_OPTION_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        result = run_command(
            [executable_path, '--help'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        options = frozenset()
    else:
        help_text = f'{result.stdout or ""}\n{result.stderr or ""}'
        options = frozenset(
            option for option in _X265_DYNAMIC_METADATA_OPTIONS
            if option in help_text
        )
    _X265_OPTION_CACHE[cache_key] = options
    return options


def extract_hdr10plus_metadata(
        source: ActualEncodeSource,
        output_path: str,
        vpy_timeline: tuple[int, int, int] | None,
) -> str:
    """Extract validated HDR10+ JSON and require an unchanged VPy timeline."""
    executable = str(core_settings.HDR10PLUS_TOOL_PATH or '').strip()
    if not executable:
        executable = 'hdr10plus_tool'
    metadata_path = os.path.abspath(os.path.normpath(output_path))
    result = run_command(
        [executable, 'extract', source.path, '-o', metadata_path],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=7200,
    )
    if (
            result.returncode != 0
            or not os.path.isfile(metadata_path)
            or os.path.getsize(metadata_path) == 0
    ):
        message = (
            str(result.stderr or '').strip()
            or translate_text('hdr10plus_tool exited with code {code}').format(
                code=result.returncode
            )
        )
        if os.path.isfile(metadata_path) and os.path.getsize(metadata_path) > 0:
            message = f'{message}; ' + translate_text(
                'HDR10+ metadata was retained: {path}'
            ).format(path=metadata_path)
        elif os.path.isfile(metadata_path):
            os.remove(metadata_path)
        raise RuntimeError(message)
    try:
        with open(metadata_path, 'r', encoding='utf-8') as metadata_file:
            document = json.load(metadata_file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            translate_text(
                'hdr10plus_tool returned invalid JSON at {path}: {error}'
            ).format(
                path=metadata_path,
                error=error,
            )
        ) from error
    scene_info = document.get('SceneInfo') if isinstance(document, dict) else None
    if not isinstance(scene_info, list) or not scene_info:
        raise RuntimeError(
            translate_text('HDR10+ JSON contains no frame metadata: {path}').format(
                path=metadata_path
            )
        )

    source_rate = _metadata_fraction(
        source.stream.get('avg_frame_rate')
        or source.stream.get('r_frame_rate')
    )
    if vpy_timeline is None or source_rate is None or source_rate <= 0:
        raise RuntimeError(
            translate_text('HDR10+ timeline could not be verified; metadata was retained: {path}').format(
                path=metadata_path
            )
        )
    output_frames, output_fps_num, output_fps_den = vpy_timeline
    output_rate = Fraction(output_fps_num, output_fps_den)
    if len(scene_info) != output_frames or source_rate != output_rate:
        raise RuntimeError(
            translate_text(
                'HDR10+ timeline does not match the VapourSynth output; '
                'metadata was retained: {path}'
            ).format(path=metadata_path)
        )
    return metadata_path


def verify_hdr10plus_metadata(encoded_path: str) -> None:
    """Require the encoded HEVC stream to contain HDR10+ metadata."""
    executable = str(core_settings.HDR10PLUS_TOOL_PATH or '').strip()
    if not executable:
        executable = 'hdr10plus_tool'
    result = run_command(
        [executable, '--verify', 'extract', encoded_path],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=7200,
    )
    if result.returncode != 0:
        detail = str(result.stderr or result.stdout or '').strip()
        raise RuntimeError(
            detail or translate_text(
                'hdr10plus_tool did not find HDR10+ metadata in the encoded output'
            )
        )


def verify_final_video_metadata(
        output_path: str,
        expected_metadata: SourceColorMetadata | None,
        automatic_arguments: Sequence[str],
) -> None:
    """Verify only the final video metadata fields added automatically."""
    if expected_metadata is None:
        return
    checks = (
        ('color_range', ('--range', '--color-range')),
        ('color_primaries', ('--colorprim', '--color-primaries')),
        ('color_transfer', ('--transfer', '--transfer-characteristics')),
        ('color_matrix', ('--colormatrix', '--matrix-coefficients')),
        ('chroma_location', ('--chromaloc', '--chroma-sample-position')),
        ('mastering_display_x26x', ('--master-display', '--mastering-display')),
        ('content_light_level', ('--max-cll', '--cll', '--content-light')),
    )
    checked_fields = tuple(
        field_name for field_name, option_names in checks
        if arguments_contain_option(automatic_arguments, *option_names)
    )
    if not checked_fields:
        return
    actual_metadata = parse_source_color_metadata(probe_actual_encode_source(output_path))
    aliases = {
        'tv': 'limited',
        'pc': 'full',
        'top-left': 'topleft',
        'bottom-left': 'bottomleft',
        'vertical': 'left',
        'colocated': 'topleft',
    }
    for field_name in checked_fields:
        expected = getattr(expected_metadata, field_name)
        actual = getattr(actual_metadata, field_name)
        expected = aliases.get(str(expected or '').lower(), expected)
        actual = aliases.get(str(actual or '').lower(), actual)
        if actual != expected:
            raise RuntimeError(
                translate_text(
                    'Final video metadata mismatch for {field}: expected '
                    '{expected}, got {actual} ({path})'
                ).format(
                    field=field_name,
                    expected=expected or translate_text('unknown'),
                    actual=actual or translate_text('unknown'),
                    path=os.path.abspath(os.path.normpath(output_path)),
                )
            )


def inject_hdr10plus_metadata(encoded_path: str, metadata_path: str) -> None:
    """Inject and verify HDR10+ metadata before atomically replacing the HEVC stream."""
    executable = str(core_settings.HDR10PLUS_TOOL_PATH or '').strip()
    if not executable:
        executable = 'hdr10plus_tool'
    encoded_path = os.path.abspath(os.path.normpath(encoded_path))
    metadata_path = os.path.abspath(os.path.normpath(metadata_path))
    temporary_output = encoded_path + '.hdr10plus.hevc'
    if os.path.exists(temporary_output):
        raise FileExistsError(
            translate_text('Output file already exists: {path}').format(
                path=temporary_output
            )
        )
    result = run_command(
        [
            executable,
            'inject',
            '-i',
            encoded_path,
            '-j',
            metadata_path,
            '-o',
            temporary_output,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=7200,
    )
    if (
            result.returncode != 0
            or not os.path.isfile(temporary_output)
            or os.path.getsize(temporary_output) == 0
    ):
        if os.path.isfile(temporary_output) and os.path.getsize(temporary_output) == 0:
            os.remove(temporary_output)
        detail = str(result.stderr or result.stdout or '').strip()
        raise RuntimeError(
            detail or translate_text(
                'hdr10plus_tool did not create the injected HEVC output: {path}'
            ).format(path=encoded_path)
        )
    verify_hdr10plus_metadata(temporary_output)
    os.replace(temporary_output, encoded_path)


def write_hdr_metadata_error_report(
        output_file: str,
        source_path: str,
        stage: str,
        error: BaseException,
) -> str:
    """Create a row-owned error report without replacing an existing file."""
    output_path = os.path.abspath(os.path.normpath(output_file))
    output_folder = os.path.dirname(output_path)
    os.makedirs(output_folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(output_path))[0]
    report_base = os.path.join(output_folder, f'{stem}.hdr-metadata-error')

    lines = (
        translate_text('HDR metadata automation failed; encoding continued.'),
        translate_text('Stage: {stage}').format(stage=stage),
        translate_text('Source: {path}').format(path=os.path.abspath(os.path.normpath(source_path))),
        translate_text('Error: {error}').format(error=str(error)),
    )
    suffix = 1
    while True:
        report_path = (
            f'{report_base}.txt'
            if suffix == 1
            else f'{report_base}.{suffix}.txt'
        )
        try:
            with open(report_path, 'x', encoding='utf-8', newline='') as report:
                report.write('\r\n'.join(lines) + '\r\n')
        except FileExistsError:
            suffix += 1
            continue
        return report_path


__all__ = [
    'ActualEncodeSource',
    'SourceColorMetadata',
    'VapourSynthOutputMetadataMismatch',
    'arguments_contain_option',
    'build_automatic_encoder_metadata_arguments',
    'extract_hdr10plus_metadata',
    'inject_hdr10plus_metadata',
    'parse_source_color_metadata',
    'probe_actual_encode_source',
    'probe_x265_dynamic_metadata_options',
    'probe_vapoursynth_output_metadata',
    'source_has_hdr10plus',
    'verify_final_video_metadata',
    'verify_hdr10plus_metadata',
    'write_hdr_metadata_error_report',
]
