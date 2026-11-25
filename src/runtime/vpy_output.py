"""Apply the selected dimensions and encoder format after the VPy processing graph."""

import re
from dataclasses import dataclass

from src.core.i18n import translate_text
from src.core.video_format import OutputResolution
from src.runtime.hdr_to_sdr import HdrToSdrSource, vpy_hdr_to_sdr
from src.runtime.video_timeline import VPY_HARDSUB_CALL


_FORMAT_BEGIN = '# Begin BluraySubtitle output format'
_FORMAT_END = '# End BluraySubtitle output format'
_FORMAT_BLOCK = re.compile(rf'(?ms)^{_FORMAT_BEGIN}\r?\n.*?^{_FORMAT_END}\r?\n?')
_DEFERRED_SUBTITLE = '# BluraySubtitle deferred hardsub: '
_MANAGED_SUBTITLE = re.compile(
    rf'(?m)^{re.escape(VPY_HARDSUB_CALL)}(?=[ \t]*(?:#[^\r\n]*)?\r?\nres\.set_output\((?:0)?\))',
)


@dataclass(frozen=True)
class VpyOutputGeometry:
    source_size: tuple[int, int] | None
    resize_input_size: tuple[int, int] | None
    output_size: tuple[int, int]

    @property
    def was_resized(self) -> bool:
        return self.resize_input_size is not None and self.resize_input_size != self.output_size

    def follows_source_geometry(self, source_after_crop: tuple[int, int] | None) -> bool:
        return source_after_crop is not None and self.resize_input_size == source_after_crop


def remove_vpy_output_format(script: str) -> str:
    script = _FORMAT_BLOCK.sub('', script)
    return re.sub(rf'(?m)^{re.escape(_DEFERRED_SUBTITLE)}(?={re.escape(VPY_HARDSUB_CALL)})', '', script)


def vpy_with_output_format(
        script: str, bit_depth: str, chroma_format: str, resolution: OutputResolution = OutputResolution(),
        *, hdr_to_sdr: HdrToSdrSource | None = None,
) -> str:
    """Convert output 0 while preserving the processing graph and other outputs."""
    target = f'{chroma_format.upper()}P{bit_depth}'
    script = remove_vpy_output_format(script)
    resize = subtitle = ''
    tone_map = vpy_hdr_to_sdr(hdr_to_sdr) if hdr_to_sdr is not None else ''
    apply_tone_map = '    clip = _bluraysub_hdr_to_sdr(clip, vs)\n' if tone_map else ''
    if resolution.enabled:
        horizontal_alignment = 1 if chroma_format == 'yuv444' else 2
        vertical_alignment = 2 if chroma_format == 'yuv420' else 1
        resize = f'''
    from fractions import Fraction

    global _bluraysub_resize_input_size
    _bluraysub_resize_input_size = (clip.width, clip.height)
    if clip.format is None or not all(_bluraysub_resize_input_size):
        raise ValueError({translate_text('Output resolution requires a constant-size VapourSynth clip.')!r})

    # Work in display coordinates so anamorphic sources retain their aspect ratio.
    align_w, align_h = ({horizontal_alignment}, {vertical_alignment}) if clip.format.color_family == vs.YUV else (1, 1)
    if ({resolution.allow_upscale!r} or clip.width > {resolution.width} or clip.height > {resolution.height}
            or clip.width % align_w or clip.height % align_h):
        props = clip.get_frame(0).props
        sar_num, sar_den = props.get('_SARNum', 1), props.get('_SARDen', 1)
        sar = Fraction(sar_num, sar_den) if sar_num > 0 and sar_den > 0 else Fraction(1)
        ratio = Fraction(clip.width, clip.height) * sar
        fitted_height = min(Fraction({resolution.height}), Fraction({resolution.width}) / ratio)
        if not {resolution.allow_upscale!r}:
            fitted_height = min(fitted_height, Fraction(clip.height), Fraction(clip.width) / ratio)
        width = int(fitted_height * ratio) // align_w * align_w
        height = int(fitted_height) // align_h * align_h
        if width <= 0 or height <= 0:
            raise ValueError({translate_text('Output resolution is too small for the video aspect ratio and chroma sampling.')!r})
        target_format = vs.{target} if clip.format.color_family == vs.YUV else clip.format.id
        clip = clip.resize.Spline36(width, height, format=target_format, dither_type='error_diffusion')
        clip = clip.std.SetFrameProps(_SARNum=1, _SARDen=1)
'''
    if resolution.enabled or (hdr_to_sdr is not None and hdr_to_sdr.is_hdr):
        if match := _MANAGED_SUBTITLE.search(script):
            script = script[:match.start()] + _DEFERRED_SUBTITLE + script[match.start():]
            subtitle = f'''
    import os

    {VPY_HARDSUB_CALL.replace('res', 'clip')}
'''
    return script.rstrip('\r\n') + f'''

{_FORMAT_BEGIN}
{tone_map}def _bluraysub_apply_output_format():
    import vapoursynth as vs

    output = vs.get_output(0)
    clip = getattr(output, 'clip', output)
{apply_tone_map}{resize}    # Keep RGB debug output in its original color format.
    if clip.format is not None and clip.format.color_family == vs.YUV and clip.format.id != vs.{target}:
        clip = clip.resize.Spline36(format=vs.{target}, dither_type='error_diffusion')
{subtitle}    if clip is not getattr(output, 'clip', output):
        clip.set_output(0)

_bluraysub_apply_output_format()
{_FORMAT_END}
'''
