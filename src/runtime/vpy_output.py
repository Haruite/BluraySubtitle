"""Apply the selected encoder format after the VPy processing graph."""

import re


_FORMAT_BEGIN = '# Begin BluraySubtitle output format'
_FORMAT_END = '# End BluraySubtitle output format'
_FORMAT_BLOCK = re.compile(rf'(?ms)^{_FORMAT_BEGIN}\r?\n.*?^{_FORMAT_END}\r?\n?')


def remove_vpy_output_format(script: str) -> str:
    return _FORMAT_BLOCK.sub('', script)


def vpy_with_output_format(script: str, bit_depth: str, chroma_format: str) -> str:
    """Convert output 0 while preserving the processing graph and other outputs."""
    target = f'{chroma_format.upper()}P{bit_depth}'
    script = remove_vpy_output_format(script)
    return script.rstrip('\r\n') + f'''

{_FORMAT_BEGIN}
def _bluraysub_apply_output_format():
    import vapoursynth as vs

    output = vs.get_output(0)
    clip = getattr(output, 'clip', output)
    # Leave RGB debug output available in the script editor.
    if clip.format is not None and clip.format.color_family == vs.YUV and clip.format.id != vs.{target}:
        clip.resize.Spline36(format=vs.{target}, dither_type='error_diffusion').set_output(0)

_bluraysub_apply_output_format()
{_FORMAT_END}
'''
