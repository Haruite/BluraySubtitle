"""CPU encoder commands for the VapourSynth stdin and temporary video workflow."""

from __future__ import annotations

import ctypes
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from src.core.i18n import translate_text
from src.core.tool_paths import ENCODER_PATH_NAMES, require_tool_path, tool_path
from src.core.video_format import cpu_chroma_formats, yuv_format_matches
from src.exports.utils import run_command


_OUTPUT_CODECS = {'x264': 'h264', 'x265': 'hevc', 'svtav1': 'av1'}
_OUTPUT_EXTENSIONS = {'x264': '.h264', 'x265': '.hevc', 'svtav1': '.ivf'}
_ENCODER_PROGRAMS = {'x264': 'x264', 'x265': 'x265', 'svtav1': 'SvtAv1EncApp'}
_ENCODER_PATH_MARKERS = {f'{{{name}}}': name for name in ENCODER_PATH_NAMES.values()}
_METADATA_ARGUMENT = '{metadata}'
_PARAMETERS_ARGUMENT = '{params}'


def split_encoder_command(text: str) -> tuple[str, ...]:
    if '\0' in text:
        raise ValueError(translate_text('The command contains a null character.'))
    if not text.strip():
        return ()
    if sys.platform != 'win32':
        return tuple(shlex.split(text))

    # Match the Windows quoting used by subprocess.list2cmdline, including backslashes.
    parser = ctypes.windll.shell32.CommandLineToArgvW
    parser.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int))
    parser.restype = ctypes.POINTER(ctypes.c_wchar_p)
    release = ctypes.windll.kernel32.LocalFree
    release.argtypes = (ctypes.c_void_p,)
    release.restype = ctypes.c_void_p
    argc = ctypes.c_int()
    argv = parser(text.replace('\r', ' ').replace('\n', ' ').strip(), ctypes.byref(argc))
    if not argv:
        raise ValueError(translate_text('Windows could not parse the command.'))
    try:
        return tuple(argv[:argc.value])
    finally:
        release(argv)


def format_encoder_command(arguments: Sequence[str]) -> str:
    return subprocess.list2cmdline(arguments) if sys.platform == 'win32' else shlex.join(arguments)


def _parse_encoder_parameters(parameters: str) -> list[str]:
    # A dummy program keeps Windows' special argv[0] parsing away from the option string.
    return list(split_encoder_command('encoder ' + parameters)[1:])


def _normalize_x264_profile(extra: list[str], bit_depth: str, chroma_format: str) -> None:
    if bit_depth not in ('8', '10'):
        return
    is_420 = chroma_format == 'yuv420'
    profile = (
        ('high10' if bit_depth == '10' else 'high') if is_420
        else 'high' + chroma_format[3:]
    )
    profile_found = False
    for index, argument in enumerate(extra):
        if argument == '--profile' and index + 1 < len(extra):
            profile_found = True
            if not is_420 or extra[index + 1] in ('high', 'high10'):
                extra[index + 1] = profile
        elif argument.startswith('--profile='):
            profile_found = True
            if not is_420 or argument.partition('=')[2] in ('high', 'high10'):
                extra[index] = f'--profile={profile}'
    if not profile_found and (bit_depth == '10' or not is_420):
        extra[:0] = ['--profile', profile]


def _normalize_builtin_parameters(extra: list[str], encoder: str, bit_depth: str, chroma_format: str) -> None:
    if encoder == 'x264':
        _normalize_x264_profile(extra, bit_depth, chroma_format)
    elif encoder == 'svtav1' and bit_depth == '12' and not any(
            argument.lower().partition('=')[0] in ('--profile', '-profile') for argument in extra
    ):
        extra[:0] = ['--profile', '2']


def _matches_builtin_encoder(executable: str, encoder: str) -> bool:
    if Path(executable).stem.casefold() == _ENCODER_PROGRAMS[encoder].casefold():
        return True
    try:
        configured = tool_path(ENCODER_PATH_NAMES[encoder])
    except KeyError:
        return False
    return os.path.normcase(executable) == os.path.normcase(configured)


@dataclass(frozen=True)
class CpuEncodeCommand:
    arguments: tuple[str, ...]
    encoder: str

    @property
    def output_extension(self) -> str:
        return _OUTPUT_EXTENSIONS[self.encoder]

    @property
    def uses_metadata(self) -> bool:
        return _METADATA_ARGUMENT in self.arguments

    def uses_builtin_encoder(self) -> bool:
        return _matches_builtin_encoder(self.arguments[0], self.encoder)

    def materialize(self, output: str, metadata: Sequence[str]) -> list[str]:
        marker = '{output' + self.output_extension + '}'
        command = [self.arguments[0]]
        for argument in self.arguments[1:]:
            if argument == _METADATA_ARGUMENT:
                command.extend(metadata)
            elif argument == marker or argument.endswith('=' + marker):
                command.append(argument[:-len(marker)] + output)
            else:
                command.append(argument)
        return command

    def verify_output(self, path: str, bit_depth: str, chroma_format: str = 'yuv420') -> None:
        """Check the video stream and container before using it as track zero."""
        result = run_command(
            [tool_path('FFPROBE_PATH'), '-v', 'error', '-show_entries',
             'format=format_name:stream=codec_type,codec_name,pix_fmt', '-of', 'json', path],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, check=True,
        )
        payload = json.loads(result.stdout)
        streams = payload.get('streams') or ()
        stream = streams[0] if len(streams) == 1 else {}
        codec = _OUTPUT_CODECS[self.encoder]
        if (
                stream.get('codec_type') != 'video' or stream.get('codec_name') != codec
                or payload.get('format', {}).get('format_name') != self.output_extension[1:]
                or not yuv_format_matches(stream.get('pix_fmt'), chroma_format, bit_depth)
        ):
            raise RuntimeError(translate_text(
                'The encoder command must output one {codec} video at {depth}-bit {chroma} in {format} format. Check {path}.'
            ).format(codec=codec, depth=bit_depth, chroma=chroma_format, format=self.output_extension[1:], path=path))


def default_cpu_encode_command(
        encoder: str, bit_depth: str, parameters: str | None, *,
        chroma_format: str = 'yuv420', use_path_placeholder: bool = False,
) -> CpuEncodeCommand:
    """Build the default command, using a placeholder when parameters are deferred."""
    if chroma_format not in cpu_chroma_formats(encoder):
        raise ValueError(translate_text('Unsupported chroma sampling: {chroma}').format(chroma=chroma_format))
    path_name = ENCODER_PATH_NAMES[encoder]
    executable = f'{{{path_name}}}' if use_path_placeholder else tool_path(path_name) or _ENCODER_PROGRAMS[encoder]
    if parameters is None:
        extra = [_PARAMETERS_ARGUMENT]
    else:
        extra = _parse_encoder_parameters(parameters)
        _normalize_builtin_parameters(extra, encoder, bit_depth, chroma_format)
    output = '{output' + _OUTPUT_EXTENSIONS[encoder] + '}'
    if encoder == 'x264':
        arguments = [
            '--demuxer', 'y4m', '-', *extra, _METADATA_ARGUMENT, '--output-depth', bit_depth,
            '--output-csp', 'i' + chroma_format[3:], '-o', output,
        ]
    elif encoder == 'x265':
        arguments = [*extra, _METADATA_ARGUMENT, '--y4m', '-', '--input-depth', bit_depth,
                     '--output-depth', bit_depth, '-o', output]
    else:
        # Keep the portable assembly setting used by the Windows preset workflow.
        windows_options = ['--asm', 'c'] if sys.platform == 'win32' else []
        arguments = [*windows_options, '-i', 'stdin', '--input-depth', bit_depth, *extra,
                     _METADATA_ARGUMENT, '-b', output]
    return CpuEncodeCommand((executable, *arguments), encoder)


def capture_cpu_encode_command(
        text: str, parameters: str = '', *, bit_depth: str = '10', chroma_format: str = 'yuv420',
) -> CpuEncodeCommand:
    """Resolve the visible executable and expand the captured parameters to arguments."""
    try:
        arguments = list(split_encoder_command(text))
    except ValueError as error:
        raise ValueError(translate_text('Invalid encoder command. {error}').format(error=error)) from error
    if not arguments or not arguments[0]:
        raise ValueError(translate_text('Enter an encoder command.'))
    parameter_count = arguments[1:].count(_PARAMETERS_ARGUMENT)
    if parameter_count > 1:
        raise ValueError(translate_text('The encoder command can contain only one {params} placeholder.'))
    if parameter_count:
        parameter_start = arguments.index(_PARAMETERS_ARGUMENT, 1)
        try:
            extra = _parse_encoder_parameters(parameters)
        except ValueError as error:
            raise ValueError(translate_text('Invalid encoder parameters. {error}').format(error=error)) from error
        parameter_end = parameter_start + len(extra)
        arguments[parameter_start:parameter_start + 1] = extra
    markers = {'{output' + suffix + '}': encoder for encoder, suffix in _OUTPUT_EXTENSIONS.items()}
    encoders = [
        markers[value] for argument in arguments[1:] if (value := argument.rsplit('=', 1)[-1]) in markers
    ]
    if len(encoders) != 1:
        raise ValueError(translate_text(
            'Use exactly one of {output.h264}, {output.hevc}, or {output.ivf} as the output placeholder.'
        ))
    metadata_count = arguments[1:].count(_METADATA_ARGUMENT)
    if metadata_count > 1:
        raise ValueError(translate_text('The encoder command can contain only one {metadata} placeholder.'))
    program = arguments[0]
    if path_name := _ENCODER_PATH_MARKERS.get(program):
        executable = require_tool_path(path_name)
    else:
        executable = shutil.which(os.path.expanduser(program))
        if not executable:
            raise FileNotFoundError(translate_text('Cannot use the encoder executable at {path}.').format(path=program))
    arguments[0] = os.path.abspath(executable)
    encoder = encoders[0]
    builtin = (parameter_count == 1 or metadata_count == 1) and _matches_builtin_encoder(arguments[0], encoder)
    if metadata_count and not builtin:
        raise ValueError(translate_text('The {metadata} placeholder requires the matching built-in encoder.'))
    if parameter_count and builtin:
        _normalize_builtin_parameters(extra, encoder, bit_depth, chroma_format)
        arguments[parameter_start:parameter_end] = extra
    return CpuEncodeCommand(tuple(arguments), encoder)
