"""Build the shared VapourSynth color conversion for SDR output."""

from dataclasses import dataclass

from src.core.i18n import translate_text


@dataclass(frozen=True)
class HdrToSdrSource:
    """Source color hints for VPy graphs that omit frame properties."""

    transfer: int = 2
    primaries: int = 9
    matrix: int = 9
    peak_nits: float = 1000.0
    needs_dolby_vision_rpu: bool = False
    full_range: bool = False

    @property
    def is_hdr(self) -> bool:
        return self.transfer in (16, 18) or self.needs_dolby_vision_rpu


def vpy_hdr_to_sdr(source: HdrToSdrSource) -> str:
    """Render a self-contained filter so VSPipe and VSEdit use the same graph."""
    format_error = translate_text('HDR to SDR conversion requires a constant-format video clip.')
    dolby_mapping = ''
    if source.needs_dolby_vision_rpu:
        dolby_error = translate_text(
            'This Dolby Vision source requires a decoder that exposes RPU data and a '
            'Vulkan-enabled vs-placebo filter for SDR conversion.'
        )
        dolby_mapping = f'''
    if transfer in (2, 16, 18) or props.get('_Matrix') == 15:
        if tone_map is None or not props.get('DolbyVisionRPU') or clip.format is None or clip.format.color_family != vs.YUV:
            raise ValueError({dolby_error!r})
        working = clip.std.SetFrameProps(_ColorRange=0).resize.Point(format=vs.YUV420P16, range_s='full')
        mapped = tone_map(working, src_csp=3, dst_csp=0, src_max={source.peak_nits!r}, dst_max=100.0, use_dovi=True)
        return finish_sdr(mapped)
'''
    return f'''
def _bluraysub_hdr_to_sdr(clip, vs):
    def finish_sdr(mapped):
        # Tonemap changes samples and can copy the input color properties.
        mapped = mapped.std.SetFrameProps(_Primaries=1, _Transfer=1, _Matrix=1).resize.Point(range_s='limited')
        return mapped.std.RemoveFrameProps(props=[
            'DolbyVisionRPU', 'HDR10Plus', 'MasteringDisplay*', 'ContentLightLevel*', 'PLSceneMax', 'PLSceneAvg',
        ])

    core = vs.core
    props = clip.get_frame(0).props
    transfer = props.get('_Transfer', 2)
    if transfer == 2 or (transfer == 14 and {source.transfer} == 18):
        transfer = {source.transfer}
    tone_map = getattr(getattr(core, 'placebo', None), 'Tonemap', None)
{dolby_mapping}    if transfer not in (16, 18):
        return clip
    if clip.format is None:
        raise ValueError({format_error!r})

    primaries = props.get('_Primaries', 2)
    if primaries == 2:
        primaries = {source.primaries}
    matrix = props.get('_Matrix', 2)
    if matrix == 2:
        matrix = {source.matrix}

    full_range = (
        props['_Range'] == 1 if '_Range' in props else props.get('_ColorRange', {int(not source.full_range)}) == 0
    )
    input_range = 'full' if full_range else 'limited'
    if tone_map is not None and clip.format.color_family == vs.YUV and (primaries, matrix) == (9, 9):
        clip = clip.std.SetFrameProps(_ColorRange=int(not full_range)).std.RemoveFrameProps(props=['DolbyVisionRPU'])
        working_format = clip.format.replace(bits_per_sample=16, sample_type=vs.INTEGER).id
        working = clip.resize.Point(format=working_format, range_s=input_range)
        clip = tone_map(working, src_csp=2 if transfer == 18 else 1, dst_csp=0,
                        src_max={source.peak_nits!r}, dst_max=100.0, use_dovi=False)
    else:
        # CPU fallback uses extended Reinhard with the source peak as its white point.
        rgb = clip.std.SetFrameProps(_Transfer=transfer).resize.Bicubic(
            format=vs.RGBS, matrix_in=matrix if clip.format.color_family == vs.YUV else 0,
            primaries_in=primaries, range_in_s=input_range, primaries=1, transfer=8,
            nominal_luminance=100.0,
        )
        channels = [core.std.ShufflePlanes(rgb, plane, vs.GRAY) for plane in range(3)]
        maximum = core.std.Expr(channels, 'x y max z max 0 max')
        white_squared = ({source.peak_nits!r} / 100.0) ** 2
        gain = maximum.std.Expr(f'1 x {{white_squared}} / + 1 x + /')
        channels = [core.std.Expr([channel, gain], 'x y * 0 max 1 min') for channel in channels]
        rgb = core.std.ShufflePlanes(channels, [0, 0, 0], vs.RGB)
        clip = rgb.resize.Bicubic(format=vs.YUV444P16, matrix=1, primaries=1, transfer=1, range_s='limited')

    return finish_sdr(clip)
'''
