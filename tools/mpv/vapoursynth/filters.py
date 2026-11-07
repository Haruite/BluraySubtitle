"""VapourSynth presets for mpv's streaming input node."""

from fractions import Fraction
from functools import lru_cache
from math import isfinite
from os import fsdecode
from pathlib import Path

import vapoursynth as vs


def load_plugin(filename, namespace):
    core = vs.core
    if not hasattr(core, namespace):
        config = Path(__file__).with_name("plugins-dir")
        plugin_dir = Path(fsdecode(config.read_bytes())) if config.is_file() else Path.home() / "plugins"
        core.std.LoadPlugin(str(plugin_dir / filename))
    return getattr(core, namespace)


def with_nominal_fps(clip, nominal_fps):
    if not isfinite(nominal_fps) or nominal_fps <= 0:
        raise vs.Error("Frame interpolation requires a known source frame rate")
    fps = Fraction(nominal_fps).limit_denominator(100_000)
    return clip.std.AssumeFPS(fpsnum=fps.numerator, fpsden=fps.denominator)


def interpolation_multiplier(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        factor = Fraction(value or "2")
    except (ValueError, ZeroDivisionError) as error:
        raise vs.Error("Invalid interpolation multiplier") from error
    if not 1 < factor <= 10 or factor.denominator > 100:
        raise vs.Error("The interpolation multiplier must be above 1 and at most 10, with a denominator of at most 100")
    return factor


def preserve_timing(output, reference):
    return output.std.CopyFrameProps(reference, props=["_DurationNum", "_DurationDen", "_MP_IMAGE"])


def finish_interpolation(output, source, factor, *, rgb=False):
    numerator, denominator = factor.numerator, factor.denominator
    if denominator == 1:
        reference = vs.core.std.Interleave([source] * numerator)
    else:
        offsets = [n * denominator // numerator for n in range(numerator)]
        reference = source.std.SelectEvery(denominator, offsets, modify_duration=False)

    if rgb:
        converted = from_rgb(output, reference)
        # Keep the original pixels at times where the two frame grids coincide.
        output = converted.std.FrameEval(
            lambda n: reference if n % numerator == 0 else converted, clip_src=[reference, converted],
        )
    if denominator == 1:
        return preserve_timing(output, reference)

    end_offsets = [((n + 1) * denominator - 1) // numerator for n in range(numerator)]
    end_reference = source.std.SelectEvery(denominator, end_offsets, modify_duration=False)

    def set_timing(n, f):
        result, start, end = f
        # An output interval may span two source frames with different durations.
        start_ticks = min(denominator, numerator - n * denominator % numerator)
        end_ticks = denominator - start_ticks
        duration = Fraction(start.props["_DurationNum"] * start_ticks, start.props["_DurationDen"])
        if end_ticks:
            duration += Fraction(end.props["_DurationNum"] * end_ticks, end.props["_DurationDen"])
        duration /= numerator
        if max(duration.numerator, duration.denominator) > 2_147_483_647:
            duration = duration.limit_denominator(1_000_000)
        result = result.copy()
        result.props["_DurationNum"] = duration.numerator
        result.props["_DurationDen"] = duration.denominator
        if "_MP_IMAGE" in start.props:
            result.props["_MP_IMAGE"] = start.props["_MP_IMAGE"]
        return result

    return output.std.ModifyFrame([output, reference, end_reference], set_timing)


def color_settings(clip, frame):
    props = frame.props
    # mpv supplies the FFmpeg matrix code in _ColorSpace, while VS sources use _Matrix.
    matrix = props.get("_Matrix", props.get("_ColorSpace", 2))
    if matrix in (0, 2):
        matrix = 6 if clip.height <= 576 else 1
    return matrix, props.get("_ColorRange", 1), props.get("_ChromaLocation", 0)


def to_rgb(clip):
    rgb_format = vs.PresetFormat.RGBS

    @lru_cache(maxsize=16)
    def convert(matrix, levels, chroma):
        return clip.resize.Bicubic(
            format=rgb_format, matrix_in=matrix, range_in=levels, chromaloc_in=chroma, range=0,
        )

    template = clip.std.BlankClip(format=rgb_format)
    return template.std.FrameEval(
        lambda n, f: convert(*color_settings(clip, f)), prop_src=clip, clip_src=clip,
    )


def from_rgb(clip, source):
    output_format = source.format.id

    @lru_cache(maxsize=16)
    def convert(matrix, levels, chroma):
        return clip.resize.Bicubic(
            format=output_format, matrix=matrix, range=levels, chromaloc=chroma,
        )

    template = clip.std.BlankClip(format=output_format)
    return template.std.FrameEval(
        lambda n, f: convert(*color_settings(source, f)), prop_src=source, clip_src=[clip, source],
    )


def mvtools(clip, nominal_fps, multiplier=""):
    plugin = load_plugin("mvtools.so", "mv")
    factor = interpolation_multiplier(multiplier)
    timed = with_nominal_fps(clip, nominal_fps)
    # MVTools reads its first two frames while building the graph, before mpv supplies input.
    # A whole multiplier cycle of padding keeps the source and output grids aligned.
    padding = max(2, factor.denominator)
    padded = timed.std.BlankClip(length=padding) + timed
    super_clip = plugin.Super(padded, pel=2)
    backward = plugin.Analyse(super_clip, isb=True, blksize=16, overlap=8)
    forward = plugin.Analyse(super_clip, isb=False, blksize=16, overlap=8)
    fps = timed.fps * factor
    output = plugin.FlowFPS(
        padded, super_clip, backward, forward, num=fps.numerator, den=fps.denominator, blend=False,
    )
    trim = padding * factor.numerator // factor.denominator
    return finish_interpolation(output[trim:], clip, factor)


def rife(clip, nominal_fps, multiplier=""):
    plugin = load_plugin("librife_linux_x86-64.so", "rife")
    factor = interpolation_multiplier(multiplier)
    timed = with_nominal_fps(clip, nominal_fps)
    scene_detected = vs.core.misc.SCDetect(timed, threshold=0.1)
    output = plugin.RIFE(
        to_rgb(scene_detected), model=23, factor_num=factor.numerator,
        factor_den=factor.denominator, gpu_thread=2, sc=True,
    )
    return finish_interpolation(output, clip, factor, rgb=True)


def ccd(clip):
    plugin = load_plugin("libccd.so", "ccd")
    output = plugin.CCD(to_rgb(clip), threshold=4.0)
    return preserve_timing(from_rgb(output, clip), clip)


def bm3d(clip):
    plugin = load_plugin("bm3d.so", "bm3d")
    # Filter luma at the original bit depth and keep the subsampled chroma planes.
    return plugin.Basic(clip, profile="fast", sigma=[3.0, 0.0, 0.0])
