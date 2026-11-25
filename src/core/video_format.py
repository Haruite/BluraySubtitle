"""Chroma sampling and planar YUV formats used by video encoders."""

CHROMA_FORMATS = ('yuv420', 'yuv422', 'yuv444')


def cpu_chroma_formats(encoder: str) -> tuple[str, ...]:
    return ('yuv420',) if encoder == 'svtav1' else CHROMA_FORMATS


def planar_yuv_format(chroma_format: str, bit_depth: str) -> str:
    suffix = '' if bit_depth == '8' else f'{bit_depth}le'
    return f'{chroma_format}p{suffix}'


def yuv_format_matches(pixel_format: str | None, chroma_format: str, bit_depth: str) -> bool:
    expected = planar_yuv_format(chroma_format, bit_depth)
    if bit_depth == '8' and pixel_format == expected.replace('yuv', 'yuvj', 1):
        return True
    if pixel_format and pixel_format.endswith('be'):
        pixel_format = pixel_format[:-2] + 'le'
    return pixel_format in (expected, expected.replace('yuv', 'yuva', 1))
