"""Output dimensions and planar YUV formats used by video encoders."""

from dataclasses import dataclass

from src.core.i18n import translate_text

CHROMA_FORMATS = ('yuv420', 'yuv422', 'yuv444')
RESOLUTION_PRESETS = (
    ('2160p', 3840, 2160), ('1440p', 2560, 1440), ('1080p', 1920, 1080), ('720p', 1280, 720),
)


@dataclass(frozen=True)
class OutputResolution:
    """A bounding box in pixels, or zero dimensions to keep the VPy output."""

    width: int = 0
    height: int = 0
    allow_upscale: bool = False

    def __post_init__(self) -> None:
        if (
                type(self.width) is not int or type(self.height) is not int
                or (self.width, self.height) != (0, 0) and min(self.width, self.height) < 2
                or type(self.allow_upscale) is not bool
        ):
            raise ValueError(translate_text('Invalid output resolution.'))

    @property
    def enabled(self) -> bool:
        return self.width != 0


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
