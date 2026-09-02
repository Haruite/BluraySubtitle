"""Automatic audio cleanup, lossless conversion, and verified Matroska muxing."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

from src.core import find_mkvtoolnix, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import (
    get_effective_bit_depth,
    mkv_codec_id_is_dts_family,
    run_command,
)
from src.runtime import TaskCancelled


@dataclass(frozen=True)
class AudioEncodingSettings:
    """Audio encoder values captured from application settings at task launch."""

    flac_compression_level: int = 8
    ffmpeg_flac_compression_level: int = 8
    fdkaac_bitrate_kbps: int = 0
    opus_bitrate_kbps: int = 0
    duration_loss_fallback_threshold_seconds: float = 1.0

    def __post_init__(self) -> None:
        if not 0 <= self.flac_compression_level <= 8:
            raise ValueError("FLAC compression level must be from 0 to 8")
        if not 0 <= self.ffmpeg_flac_compression_level <= 12:
            raise ValueError("FFmpeg FLAC compression level must be from 0 to 12")
        if not 0 <= self.fdkaac_bitrate_kbps <= 1024:
            raise ValueError("FDK-AAC bitrate must be from 0 to 1024 kbps")
        if not 0 <= self.opus_bitrate_kbps <= 1024:
            raise ValueError("Opus bitrate must be from 0 to 1024 kbps")
        if (
                isinstance(self.duration_loss_fallback_threshold_seconds, bool)
                or not isinstance(
                    self.duration_loss_fallback_threshold_seconds,
                    (int, float),
                )
                or not 0.1 <= float(
                    self.duration_loss_fallback_threshold_seconds
                ) <= 60.0
        ):
            raise ValueError(
                "Audio duration-loss fallback threshold must be from 0.1 to 60 seconds"
            )


class AudioMuxFailure(RuntimeError):
    """Final-mux failure whose non-empty task artifacts remain recoverable."""

    def __init__(self, message: str, artifact_paths: tuple[str, ...]) -> None:
        super().__init__(message)
        self.stage = 'Final Matroska mux'
        self.artifact_paths = artifact_paths


def _identify_tracks(media_path: str) -> list[dict[str, object]]:
    find_mkvtoolnix()
    mkvmerge = str(core_settings.MKV_MERGE_PATH or '').strip() or shutil.which('mkvmerge') or ''
    if not mkvmerge:
        raise FileNotFoundError(translate_text('mkvmerge not found'))
    result = run_command(
        [mkvmerge, '-J', media_path],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore',
    )
    if result.returncode != 0:
        raise RuntimeError(
            translate_text('Could not identify media tracks: {path}').format(path=media_path)
        )
    try:
        tracks = json.loads(result.stdout or '{}').get('tracks') or []
    except Exception as error:
        raise RuntimeError(
            translate_text('Could not identify media tracks: {path}').format(path=media_path)
        ) from error
    return [track for track in tracks if isinstance(track, dict)]


def is_lossless_audio_codec(
        codec_id: object,
        codec_name: object,
        profile: object = '',
) -> bool:
    """Return whether a codec is a supported lossless source."""
    normalized_codec_id = str(codec_id or '').strip().upper()
    normalized_codec_name = str(codec_name or '').strip().lower()
    description = f'{normalized_codec_name} {str(profile or "").strip().lower()}'
    dts_hd_ma = (
        mkv_codec_id_is_dts_family(normalized_codec_id)
        or normalized_codec_name.startswith('dts')
    ) and (
        'dts-hd master audio' in description
        or 'dts-hd ma' in description
        or normalized_codec_name == 'dts_hd_ma'
        or normalized_codec_name.startswith('dts_hd_ma_')
    )
    return bool(
        normalized_codec_id in (
            'A_PCM/INT/LIT',
            'A_PCM/INT/BIG',
            'A_TRUEHD',
            'A_MLP',
            'A_FLAC',
        )
        or normalized_codec_name.startswith('pcm')
        or normalized_codec_name in ('lpcm', 'truehd', 'mlp', 'flac')
        or 'truehd' in normalized_codec_name
        or dts_hd_ma
    )


def _is_lossless_audio_track(
        track: dict[str, object],
        profile: object = '',
) -> bool:
    properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
    return is_lossless_audio_codec(
        properties.get('codec_id'),
        track.get('codec'),
        profile,
    )


def is_immersive_audio_codec(
        codec_name: object,
        profile: object = '',
        track_name: object = '',
) -> bool:
    """Return whether decoded FLAC would discard immersive object metadata."""
    description = ' '.join((
        str(codec_name or ''),
        str(profile or ''),
        str(track_name or ''),
    )).strip().lower()
    return bool(
        'atmos' in description
        or 'dts:x' in description
        or 'dts-x' in description
        or 'dts_hd_ma_x' in description
    )


def _is_immersive_audio_track(
        track: dict[str, object],
        profile: object = '',
) -> bool:
    properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
    return is_immersive_audio_codec(
        track.get('codec'),
        profile,
        properties.get('track_name'),
    )


def probe_audio_streams(
        ffprobe: str,
        media_path: str,
) -> list[tuple[str, float]]:
    """Return every audio stream profile and duration in one probe."""
    result = run_command(
        [
            ffprobe,
            '-v',
            'error',
            '-select_streams',
            'a',
            '-show_entries',
            'stream=profile,duration:format=duration',
            '-of',
            'json',
            media_path,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore',
    )
    try:
        payload = json.loads(result.stdout or '{}')
        streams = payload.get('streams') or []
    except (TypeError, json.JSONDecodeError, AttributeError):
        streams = []
        payload = {}
    try:
        raw_format_duration = (payload.get('format') or {}).get('duration')
        format_duration = float(raw_format_duration)
        if not math.isfinite(format_duration) or format_duration <= 0:
            format_duration = 0.0
    except (TypeError, ValueError, AttributeError):
        format_duration = 0.0
    if result.returncode != 0 or not isinstance(streams, list):
        raise RuntimeError(
            translate_text('Could not probe audio duration: {path}').format(path=media_path)
        )

    audio_streams: list[tuple[str, float]] = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        profile = str(stream.get('profile') or '')
        raw_duration = stream.get('duration')
        try:
            duration = float(raw_duration)
        except (TypeError, ValueError):
            duration = format_duration
        if not math.isfinite(duration) or duration <= 0:
            duration = format_duration
        audio_streams.append((profile, duration))
    if not audio_streams:
        raise RuntimeError(
            translate_text('Could not probe audio duration: {path}').format(path=media_path)
        )
    return audio_streams


def probe_audio_stream(
        ffprobe: str,
        media_path: str,
        stream_selector: str = 'a:0',
) -> tuple[str, float]:
    """Return the selected audio profile and duration in seconds."""
    result = run_command(
        [
            ffprobe,
            '-v',
            'error',
            '-select_streams',
            stream_selector,
            '-show_entries',
            'stream=profile,duration:format=duration',
            '-of',
            'json',
            media_path,
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore',
    )
    try:
        payload = json.loads(result.stdout or '{}')
        streams = payload.get('streams') or []
        stream = streams[0] if streams and isinstance(streams[0], dict) else {}
        profile = str(stream.get('profile') or '')
        raw_duration = stream.get('duration')
        if raw_duration in (None, '', 'N/A'):
            raw_duration = (payload.get('format') or {}).get('duration')
        duration = float(raw_duration)
    except (TypeError, ValueError, json.JSONDecodeError, AttributeError, IndexError):
        duration = 0.0
        profile = ''
    if result.returncode != 0 or not math.isfinite(duration) or duration <= 0:
        raise RuntimeError(
            translate_text('Could not probe audio duration: {path}').format(path=media_path)
        )
    return profile, duration


def converted_flac_duration_is_acceptable(
        ffprobe: str,
        source_duration: float,
        converted_path: str,
        track: object,
        source_path: str,
        fallback_threshold_seconds: float,
) -> bool:
    """Report meaningful duration loss and return whether the FLAC may replace its source."""
    _profile, converted_duration = probe_audio_stream(ffprobe, converted_path)
    duration_loss = round(source_duration - converted_duration, 6)
    threshold = float(fallback_threshold_seconds)
    if duration_loss > threshold:
        print(
            translate_text(
                'Converted audio track {track} is {loss:.3f} seconds shorter than the source, exceeding the {threshold:.3f}-second fallback threshold; keeping the original: {path}'
            ).format(
                track=track,
                loss=duration_loss,
                threshold=threshold,
                path=source_path,
            ),
            flush=True,
        )
        return False
    if duration_loss > 0.1:
        print(
            translate_text(
                'Converted audio track {track} is {loss:.3f} seconds shorter than the source: {path}'
            ).format(track=track, loss=duration_loss, path=source_path),
            flush=True,
        )
    return True


def encode_fdkaac_from_ffmpeg(
        ffmpeg: str,
        fdkaac: str,
        input_media: str,
        stream_selector: str,
        output_path: str,
        rate_control: list[str],
) -> bool:
    """Decode PCM through a pipe and encode it with fdkaac without a WAV file."""
    decode_command = [
        ffmpeg,
        '-y',
        '-i',
        input_media,
        '-map',
        stream_selector,
        '-c:a',
        'pcm_s24le',
        '-f',
        'wav',
        '-',
    ]
    encode_command = [
        fdkaac,
        *rate_control,
        '-I',
        '-o',
        output_path,
        '-',
    ]
    decoder = run_command(
        decode_command,
        wait=False,
        stdout=subprocess.PIPE,
        log_template='Audio command: {command}',
    )
    try:
        encoder = run_command(
            encode_command,
            wait=False,
            stdin=decoder.stdout,
            log_template='Audio command: {command}',
        )
    except Exception:
        decoder.terminate()
        decoder.wait()
        raise
    if decoder.stdout is not None:
        decoder.stdout.close()
    encoder_return_code = encoder.wait()
    decoder_return_code = decoder.wait()
    return bool(
        decoder_return_code == 0
        and encoder_return_code == 0
        and os.path.isfile(output_path)
        and os.path.getsize(output_path) > 0
    )


def validate_audio_cleanup_tools() -> None:
    """Require the decoder used by automatic audio cleanup."""
    find_mkvtoolnix()
    ffmpeg = str(core_settings.FFMPEG_PATH or '').strip() or shutil.which('ffmpeg') or ''
    if not ffmpeg or not (os.path.isfile(ffmpeg) or shutil.which(ffmpeg)):
        raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))


def _extract_selected_audio_tracks(
        ffmpeg: str,
        source_path: str,
        work_folder: str,
        audio_index_by_track: dict[int, int],
        selected_audio: tuple[int, ...],
        wave64_bit_depth: int = 32,
) -> dict[int, str]:
    """Decode selected tracks together, then retry failed batches one track at a time."""
    if not selected_audio:
        return {}
    if not ffmpeg:
        raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
    if wave64_bit_depth not in (24, 32):
        raise ValueError(f'Unsupported Wave64 bit depth: {wave64_bit_depth}')

    extracted_audio_by_track: dict[int, str] = {}
    extract_command = [ffmpeg, '-y', '-i', source_path]
    for track_id in selected_audio:
        if track_id not in audio_index_by_track:
            raise ValueError(
                translate_text('Selected audio track is missing from: {path}').format(
                    path=source_path
                )
            )
        extracted_audio = os.path.join(work_folder, f'track-{track_id}.w64')
        extracted_audio_by_track[track_id] = extracted_audio
        extract_command.extend([
            '-map',
            f'0:a:{audio_index_by_track[track_id]}',
            '-c:a',
            f'pcm_s{wave64_bit_depth}le',
            '-f',
            'w64',
            extracted_audio,
        ])

    batch_error: Exception | None = None
    try:
        extract_result = run_command(
            extract_command,
            log_template='Audio extraction command: {command}',
        )
        batch_succeeded = extract_result.returncode == 0 and all(
            os.path.isfile(extracted_audio) and os.path.getsize(extracted_audio) > 0
            for extracted_audio in extracted_audio_by_track.values()
        )
        if batch_succeeded:
            return extracted_audio_by_track
        batch_error = RuntimeError(
            translate_text('Audio extraction failed for track {track}: {path}').format(
                track=','.join(str(track_id) for track_id in selected_audio),
                path=source_path,
            )
        )
    except (OSError, RuntimeError, ValueError) as error:
        batch_error = error

    print(
        translate_text(
            'Batch audio extraction failed; retrying each track: {path} ({error})'
        ).format(path=source_path, error=batch_error),
        flush=True,
    )
    for extracted_audio in extracted_audio_by_track.values():
        if os.path.isfile(extracted_audio):
            os.remove(extracted_audio)

    recovered_audio_by_track: dict[int, str] = {}
    for track_id, extracted_audio in extracted_audio_by_track.items():
        track_error: Exception | None = None
        try:
            track_result = run_command(
                [
                    ffmpeg,
                    '-y',
                    '-i',
                    source_path,
                    '-map',
                    f'0:a:{audio_index_by_track[track_id]}',
                    '-c:a',
                    f'pcm_s{wave64_bit_depth}le',
                    '-f',
                    'w64',
                    extracted_audio,
                ],
                log_template='Audio extraction command: {command}',
            )
            if track_result.returncode == 0 and (
                    os.path.isfile(extracted_audio)
                    and os.path.getsize(extracted_audio) > 0
            ):
                recovered_audio_by_track[track_id] = extracted_audio
                continue
            track_error = RuntimeError(
                translate_text('Audio extraction failed for track {track}: {path}').format(
                    track=track_id,
                    path=source_path,
                )
            )
        except (OSError, RuntimeError, ValueError) as error:
            track_error = error
        if os.path.isfile(extracted_audio):
            os.remove(extracted_audio)
        print(
            translate_text(
                'Audio extraction failed for track {track}; keeping the original: {path} ({error})'
            ).format(track=track_id, path=source_path, error=track_error),
            flush=True,
        )
    return recovered_audio_by_track


def _flac_encoder_path() -> str:
    configured_flac = str(core_settings.FLAC_PATH or '').strip()
    if configured_flac and (
            os.path.isfile(configured_flac) or shutil.which(configured_flac)
    ):
        return configured_flac
    return shutil.which('flac') or shutil.which('flac.exe') or ''


def _encode_wave64_to_flac(
        ffmpeg: str,
        flac_encoder: str,
        wave64_path: str,
        output_path: str,
        wave64_bit_depth: int,
        audio_encoding: AudioEncodingSettings,
) -> bool:
    """Encode one Wave64 file at its detected effective integer depth."""
    try:
        effective_bit_depth = get_effective_bit_depth(
            wave64_path,
            wave64_bit_depth,
        )
    except (OSError, RuntimeError, ValueError):
        effective_bit_depth = wave64_bit_depth
    if effective_bit_depth <= 16:
        effective_bit_depth = 16
    elif effective_bit_depth <= 24:
        effective_bit_depth = 24
    else:
        effective_bit_depth = 32

    # A direct FLAC input keeps the configured reference-encoder path when the
    # Wave64 container already has the desired nominal depth. When down-packing
    # zero padding, FFmpeg writes the intended 16- or 24-bit FLAC directly.
    if flac_encoder and effective_bit_depth == wave64_bit_depth:
        try:
            flac_succeeded = run_command([
                flac_encoder,
                f'-{audio_encoding.flac_compression_level}',
                '-j',
                str(os.cpu_count() or 1),
                '-f',
                '-o',
                output_path,
                wave64_path,
            ], log_template='Audio command: {command}').returncode == 0 and (
                os.path.isfile(output_path) and os.path.getsize(output_path) > 0
            )
        except OSError:
            flac_succeeded = False
        if flac_succeeded:
            return True
        if os.path.isfile(output_path):
            os.remove(output_path)

    # This FFmpeg build writes s32 FLAC as 24-bit. A genuinely effective
    # 32-bit stream therefore requires the reference FLAC encoder.
    if effective_bit_depth == 32:
        return False
    conversion_command = [
        ffmpeg,
        '-y',
        '-i',
        wave64_path,
        '-map',
        '0:a:0',
        '-c:a',
        'flac',
    ]
    if effective_bit_depth == 16:
        conversion_command.extend(['-sample_fmt', 's16'])
    else:
        conversion_command.extend([
            '-sample_fmt',
            's32',
            '-bits_per_raw_sample',
            '24',
        ])
    conversion_command.extend([
        '-compression_level',
        str(audio_encoding.ffmpeg_flac_compression_level),
        output_path,
    ])
    try:
        return run_command(
            conversion_command,
            log_template='Audio command: {command}',
        ).returncode == 0 and (
            os.path.isfile(output_path) and os.path.getsize(output_path) > 0
        )
    except OSError:
        return False


def convert_audio_stream_to_flac(
        input_media: str,
        stream_selector: str,
        output_path: str,
        *,
        wave64_bit_depth: int = 24,
        audio_encoding: AudioEncodingSettings = AudioEncodingSettings(),
) -> bool:
    """Convert one selected stream to FLAC through the shared Wave64 path."""
    if not input_media or not os.path.isfile(input_media) or not output_path:
        return False
    if wave64_bit_depth not in (24, 32):
        raise ValueError(f'Unsupported Wave64 bit depth: {wave64_bit_depth}')
    ffmpeg = str(core_settings.FFMPEG_PATH or '').strip() or shutil.which('ffmpeg') or ''
    ffprobe = str(core_settings.FFPROBE_PATH or '').strip() or shutil.which('ffprobe') or ''
    if not ffmpeg or not ffprobe:
        return False
    normalized_selector = str(stream_selector or 'a:0').strip()
    ffmpeg_selector = (
        normalized_selector
        if normalized_selector.startswith('0:')
        else f'0:{normalized_selector}'
    )
    ffprobe_selector = (
        normalized_selector[2:]
        if normalized_selector.startswith('0:')
        else normalized_selector
    )
    normalized_output = os.path.abspath(os.path.normpath(output_path))
    output_parent = os.path.dirname(normalized_output)
    os.makedirs(output_parent, exist_ok=True)
    work_folder = tempfile.mkdtemp(prefix='_audio_convert_', dir=output_parent)
    wave64_path = os.path.join(work_folder, 'track.w64')
    try:
        _profile, source_duration = probe_audio_stream(
            ffprobe,
            input_media,
            ffprobe_selector,
        )
        decode_result = run_command(
            [
                ffmpeg,
                '-y',
                '-i',
                input_media,
                '-map',
                ffmpeg_selector,
                '-c:a',
                f'pcm_s{wave64_bit_depth}le',
                '-f',
                'w64',
                wave64_path,
            ],
            log_template='Audio extraction command: {command}',
        )
        if decode_result.returncode != 0 or not (
                os.path.isfile(wave64_path) and os.path.getsize(wave64_path) > 0
        ):
            return False
        if not _encode_wave64_to_flac(
                ffmpeg,
                _flac_encoder_path(),
                wave64_path,
                normalized_output,
                wave64_bit_depth,
                audio_encoding,
        ):
            if os.path.isfile(normalized_output):
                os.remove(normalized_output)
            return False
        if not converted_flac_duration_is_acceptable(
                ffprobe,
                source_duration,
                normalized_output,
                ffprobe_selector,
                input_media,
                audio_encoding.duration_loss_fallback_threshold_seconds,
        ):
            os.remove(normalized_output)
            return False
        return True
    except TaskCancelled:
        raise
    except (OSError, RuntimeError, ValueError):
        if os.path.isfile(normalized_output):
            os.remove(normalized_output)
        return False
    finally:
        shutil.rmtree(work_folder, ignore_errors=True)


def _analyze_audio_track(
        ffmpeg: str,
        extracted_audio: str,
        source_path: str,
        track_id: int,
) -> tuple[float, str]:
    """Analyze one previously extracted audio track."""
    result = run_command(
        [
            ffmpeg, '-hide_banner', '-nostats', '-i', extracted_audio,
            '-map', '0:a:0', '-af', 'volumedetect',
            '-ar', '8000', '-c:a', 'pcm_s16le', '-f', 'hash', '-hash', 'sha256', '-',
        ],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore',
        log_template='Audio analysis command: {command}',
    )
    output = f'{result.stdout or ""}\n{result.stderr or ""}'
    volume_match = re.search(
        r'max_volume:\s*(-?inf|[-+]?\d+(?:\.\d+)?)\s*dB',
        output,
        flags=re.IGNORECASE,
    )
    fingerprint_match = re.search(r'\bSHA256=([0-9a-f]+)\b', output, flags=re.IGNORECASE)
    if result.returncode != 0 or not volume_match or not fingerprint_match:
        raise RuntimeError(
            translate_text('Audio analysis failed for track {track}: {path}').format(
                track=track_id,
                path=source_path,
            )
        )
    return float(volume_match.group(1)), fingerprint_match.group(1).lower()


def _selected_audio_after_cleanup(
        ffmpeg: str,
        source_path: str,
        audio_tracks: list[dict[str, object]],
        selected_audio: tuple[int, ...],
        language_by_track: dict[int, str],
        extracted_audio_by_track: dict[int, str],
) -> list[int]:
    """Remove silent and exact duplicate selections while retaining source order."""
    kept_audio: list[int] = []
    fingerprints: dict[tuple[str, int, str], list[tuple[int, str]]] = {}
    for track in audio_tracks:
        track_id = int(track['id'])
        if track_id not in selected_audio:
            continue
        if track_id not in extracted_audio_by_track:
            kept_audio.append(track_id)
            continue
        properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
        codec_id = str(properties.get('codec_id') or '').strip().upper()
        codec_name = str(track.get('codec') or '').strip().lower()
        maximum_volume, fingerprint = _analyze_audio_track(
            ffmpeg,
            extracted_audio_by_track[track_id],
            source_path,
            track_id,
        )
        if maximum_volume < -60.0:
            print(
                translate_text(
                    'Silent audio track {track} was removed ({level:.1f} dB): {path}'
                ).format(track=track_id, level=maximum_volume, path=source_path),
                flush=True,
            )
            continue
        try:
            channel_count = int(properties.get('audio_channels') or 0)
        except (TypeError, ValueError):
            channel_count = 0
        language = language_by_track.get(track_id) or str(properties.get('language') or 'und')
        normalized_language = language.strip().lower().replace('_', '-').split('-', 1)[0]
        if normalized_language in ('chi', 'cmn', 'yue', 'nan', 'zh'):
            normalized_language = 'zho'
        elif not normalized_language:
            normalized_language = 'und'
        if codec_id in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG'):
            codec_family = 'pcm'
        elif codec_id in ('A_TRUEHD', 'A_MLP'):
            codec_family = 'truehd'
        elif mkv_codec_id_is_dts_family(codec_id):
            codec_family = 'dts'
        else:
            codec_family = codec_id or codec_name
        fingerprint_key = (codec_family, channel_count, fingerprint)
        duplicate_track_id = next(
            (
                kept_track_id
                for kept_track_id, kept_language in fingerprints.get(fingerprint_key, ())
                if (
                    normalized_language == 'und'
                    or kept_language == 'und'
                    or normalized_language == kept_language
                )
            ),
            None,
        )
        if duplicate_track_id is not None:
            print(
                translate_text(
                    'Duplicate audio track {track} was removed; keeping track {kept}: {path}'
                ).format(track=track_id, kept=duplicate_track_id, path=source_path),
                flush=True,
            )
            continue
        fingerprints.setdefault(fingerprint_key, []).append((track_id, normalized_language))
        kept_audio.append(track_id)
    return kept_audio


def validate_audio_conversion_tools(
        source_file: str,
        selected_audio_tracks: Optional[tuple[str, ...]],
        audio_codec_choices: tuple[str, ...],
        *,
        convert_all_lossless_to_flac: bool = False,
        convert_immersive_audio_to_flac: bool = False,
) -> None:
    """Check tools required by automatic cleanup and requested conversions."""
    cleanup_only = (
        selected_audio_tracks is None
        and not audio_codec_choices
        and not convert_all_lossless_to_flac
    )
    if selected_audio_tracks == () and not convert_all_lossless_to_flac:
        return
    tracks = _identify_tracks(source_file)
    if convert_all_lossless_to_flac or selected_audio_tracks is None:
        selected_audio_tracks = tuple(
            str(track['id']) for track in tracks if track.get('type') == 'audio'
        )
    if convert_all_lossless_to_flac:
        audio_codec_choices = ('flac',) * len(selected_audio_tracks)
    if not selected_audio_tracks:
        return
    if not cleanup_only and len(selected_audio_tracks) != len(audio_codec_choices):
        raise ValueError(
            translate_text('Audio codec choices do not match selected tracks: {path}').format(
                path=source_file
            )
        )
    audio_by_id = {
        int(track['id']): track
        for track in tracks
        if track.get('type') == 'audio' and 'id' in track
    }
    for raw_track_id in selected_audio_tracks:
        if int(raw_track_id) not in audio_by_id:
            raise ValueError(
                translate_text('Selected audio track is missing from: {path}').format(
                    path=source_file
                )
            )
    validate_audio_cleanup_tools()
    if cleanup_only:
        return
    requires_fdkaac = False
    requires_duration_probe = False
    for raw_track_id, raw_target_codec in zip(selected_audio_tracks, audio_codec_choices):
        track_id = int(raw_track_id)
        track = audio_by_id.get(track_id)
        target_codec = str(raw_target_codec).strip().lower()
        if target_codec not in ('flac', 'aac', 'opus'):
            raise ValueError(
                translate_text('Unsupported lossless audio codec: {codec}').format(
                    codec=target_codec
                )
            )
        properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
        codec_id = str(properties.get('codec_id') or '').strip().upper()
        conversion_candidate = (
            _is_lossless_audio_track(track)
            or mkv_codec_id_is_dts_family(codec_id)
        )
        if not conversion_candidate or (
                codec_id == 'A_FLAC' and target_codec == 'flac'
        ):
            continue
        if (
                _is_immersive_audio_track(track)
                and not convert_immersive_audio_to_flac
        ):
            continue
        requires_duration_probe = True
        if target_codec == 'aac':
            requires_fdkaac = True
    if requires_duration_probe:
        ffprobe = (
            str(core_settings.FFPROBE_PATH or '').strip()
            or shutil.which('ffprobe')
            or ''
        )
        if not ffprobe or not (os.path.isfile(ffprobe) or shutil.which(ffprobe)):
            raise FileNotFoundError(translate_text('ffprobe executable does not exist'))
    if requires_fdkaac:
        fdkaac = (
            str(core_settings.FDK_AAC_PATH or '').strip()
            or shutil.which('fdkaac')
            or shutil.which('fdkaac.exe')
            or ''
        )
        if not fdkaac or not (os.path.isfile(fdkaac) or shutil.which(fdkaac)):
            raise FileNotFoundError(translate_text('fdkaac executable does not exist'))


def mux_with_audio_conversion(
        source_file: str,
        output_file: str,
        *,
        selected_audio_tracks: Optional[tuple[str, ...]],
        selected_subtitle_tracks: Optional[tuple[str, ...]],
        audio_codec_choices: tuple[str, ...],
        convert_all_lossless_to_flac: bool = False,
        convert_immersive_audio_to_flac: bool = False,
        clean_audio_tracks: bool = True,
        track_language_overrides: tuple[tuple[str, str], ...] = (),
        encoded_video_file: str = '',
        subtitle_file: str = '',
        subtitle_language: str = '',
        audio_encoding: AudioEncodingSettings = AudioEncodingSettings(),
        wave64_bit_depth: int = 32,
        preserve_failure_artifacts: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
) -> None:
    """Optionally clean audio, convert requested lossless tracks, and mux atomically."""
    def report_progress(message_source: str, **values: object) -> None:
        if progress_callback is not None:
            progress_callback(translate_text(message_source).format(**values))

    source_path = os.path.abspath(os.path.normpath(source_file))
    output_path = os.path.abspath(os.path.normpath(output_file))
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)
    if wave64_bit_depth not in (24, 32):
        raise ValueError(f'Unsupported Wave64 bit depth: {wave64_bit_depth}')
    same_path = os.path.normcase(source_path) == os.path.normcase(output_path)
    if os.path.exists(output_path) and not same_path:
        raise FileExistsError(
            translate_text('Output file already exists: {path}').format(path=output_path)
        )

    report_progress('Inspecting media tracks')
    tracks = _identify_tracks(source_path)
    track_by_id = {int(track['id']): track for track in tracks if 'id' in track}
    source_audio = [int(track['id']) for track in tracks if track.get('type') == 'audio']
    source_subtitles = [int(track['id']) for track in tracks if track.get('type') == 'subtitles']
    cleanup_only = (
        selected_audio_tracks is None
        and not audio_codec_choices
        and not convert_all_lossless_to_flac
    )
    if convert_all_lossless_to_flac:
        selected_audio = tuple(source_audio)
        audio_codec_choices = ('flac',) * len(selected_audio)
    elif selected_audio_tracks is None:
        selected_audio = tuple(source_audio)
    else:
        selected_audio = tuple(int(track_id) for track_id in selected_audio_tracks)
    if selected_subtitle_tracks is None:
        selected_subtitles = tuple(source_subtitles)
    else:
        selected_subtitles = tuple(int(track_id) for track_id in selected_subtitle_tracks)
    if any(track_id not in source_audio for track_id in selected_audio):
        raise ValueError(
            translate_text('Selected audio track is missing from: {path}').format(path=source_path)
        )
    if any(track_id not in source_subtitles for track_id in selected_subtitles):
        raise ValueError(
            translate_text('Selected subtitle track is missing from: {path}').format(path=source_path)
        )
    if not cleanup_only and len(selected_audio) != len(audio_codec_choices):
        raise ValueError(
            translate_text('Audio codec choices do not match selected tracks: {path}').format(
                path=source_path
            )
        )
    codec_by_track = dict(zip(selected_audio, audio_codec_choices))
    language_by_track = {
        int(track_id): str(language).strip()
        for track_id, language in track_language_overrides
        if str(language).strip()
    }

    output_parent = os.path.dirname(output_path)
    os.makedirs(output_parent, exist_ok=True)
    work_folder = tempfile.mkdtemp(prefix='_audio_convert_', dir=output_parent)
    output_extension = os.path.splitext(output_path)[1] or '.mkv'
    temporary_output = os.path.join(work_folder, f'result{output_extension}')
    replacement_by_track: dict[int, tuple[str, str]] = {}
    keep_work_folder = False
    try:
        find_mkvtoolnix()
        ffmpeg = str(core_settings.FFMPEG_PATH or '').strip() or shutil.which('ffmpeg') or ''
        ffprobe = str(core_settings.FFPROBE_PATH or '').strip() or shutil.which('ffprobe') or ''
        flac_encoder = _flac_encoder_path()

        audio_tracks = [track for track in tracks if track.get('type') == 'audio']
        audio_index_by_track = {
            int(track['id']): audio_index
            for audio_index, track in enumerate(audio_tracks)
        }
        unsupported_codec = next(
            (
                str(codec).strip().lower()
                for codec in codec_by_track.values()
                if str(codec).strip().lower() not in ('flac', 'aac', 'opus')
            ),
            '',
        )
        if unsupported_codec:
            raise ValueError(
                translate_text('Unsupported lossless audio codec: {codec}').format(
                    codec=unsupported_codec
                )
            )

        potential_conversion_tracks: list[int] = []
        for track in audio_tracks:
            track_id = int(track['id'])
            if track_id not in selected_audio:
                continue
            target_codec = str(codec_by_track.get(track_id) or '').strip().lower()
            if not target_codec:
                continue
            properties = track.get('properties') \
                if isinstance(track.get('properties'), dict) else {}
            codec_id = str(properties.get('codec_id') or '').strip().upper()
            if codec_id == 'A_FLAC' and target_codec == 'flac':
                continue
            if (
                    _is_lossless_audio_track(track)
                    or mkv_codec_id_is_dts_family(codec_id)
            ):
                potential_conversion_tracks.append(track_id)

        audio_probe_by_track: dict[int, tuple[str, float]] = {}
        if potential_conversion_tracks:
            try:
                if not ffprobe:
                    raise FileNotFoundError(
                        translate_text('ffprobe executable does not exist')
                    )
                source_audio_probes = probe_audio_streams(ffprobe, source_path)
                if len(source_audio_probes) < len(audio_tracks):
                    raise RuntimeError(
                        translate_text('Could not probe audio duration: {path}').format(
                            path=source_path
                        )
                    )
                audio_probe_by_track = {
                    int(track['id']): source_audio_probes[audio_index]
                    for audio_index, track in enumerate(audio_tracks)
                }
            except (OSError, RuntimeError, ValueError) as error:
                print(
                    translate_text(
                        'Audio probing failed; skipping audio conversion: {path} ({error})'
                    ).format(path=source_path, error=error),
                    flush=True,
                )

        conversion_tracks: set[int] = set()
        for track in audio_tracks:
            track_id = int(track['id'])
            if track_id not in potential_conversion_tracks:
                continue
            profile, source_duration = audio_probe_by_track.get(track_id, ('', 0.0))
            if source_duration <= 0:
                print(
                    translate_text(
                        'Audio conversion failed for track {track}; keeping the original: {path} ({error})'
                    ).format(
                        track=track_id,
                        path=source_path,
                        error=translate_text(
                            'Could not probe audio duration: {path}'
                        ).format(path=source_path),
                    ),
                    flush=True,
                )
                continue
            if not _is_lossless_audio_track(track, profile):
                continue
            if (
                    _is_immersive_audio_track(track, profile)
                    and not convert_immersive_audio_to_flac
            ):
                continue
            conversion_tracks.add(track_id)

        extracted_track_ids = tuple(
            int(track['id'])
            for track in audio_tracks
            if int(track['id']) in selected_audio and (
                clean_audio_tracks or int(track['id']) in conversion_tracks
            )
        )
        extracted_audio_by_track: dict[int, str] = {}
        if extracted_track_ids:
            if not ffmpeg:
                raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
            report_progress('Decoding selected audio tracks to Wave64')
            extracted_audio_by_track = _extract_selected_audio_tracks(
                ffmpeg,
                source_path,
                work_folder,
                audio_index_by_track,
                extracted_track_ids,
                wave64_bit_depth,
            )
        conversion_tracks.intersection_update(extracted_audio_by_track)

        if clean_audio_tracks:
            report_progress('Analyzing silent and duplicate audio')
            kept_audio = _selected_audio_after_cleanup(
                ffmpeg,
                source_path,
                audio_tracks,
                selected_audio,
                language_by_track,
                extracted_audio_by_track,
            )
        else:
            kept_audio = list(selected_audio)
        for track in audio_tracks:
            track_id = int(track['id'])
            if track_id not in kept_audio or track_id not in conversion_tracks:
                continue
            target_codec = str(codec_by_track.get(track_id) or '').strip().lower()
            properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
            conversion_input = extracted_audio_by_track[track_id]
            converted_audio = ''
            try:
                _profile, source_duration = audio_probe_by_track[track_id]
                report_progress(
                    'Converting audio track {track} to {codec}',
                    track=track_id,
                    codec=target_codec.upper(),
                )

                if target_codec == 'flac':
                    converted_audio = os.path.join(work_folder, f'track-{track_id}.flac')
                    if not _encode_wave64_to_flac(
                            ffmpeg,
                            flac_encoder,
                            conversion_input,
                            converted_audio,
                            wave64_bit_depth,
                            audio_encoding,
                    ):
                        raise RuntimeError(
                            translate_text(
                                'Audio conversion failed for track {track}: {path}'
                            ).format(track=track_id, path=source_path)
                        )
                    conversion_command = None
                elif target_codec == 'opus':
                    converted_audio = os.path.join(work_folder, f'track-{track_id}.opus')
                    try:
                        channels = int(properties.get('audio_channels') or 2)
                    except (TypeError, ValueError):
                        channels = 2
                    conversion_command = [
                        ffmpeg,
                        '-y',
                        '-i',
                        conversion_input,
                        '-map',
                        '0:a:0',
                        '-c:a',
                        'libopus',
                    ]
                    if channels > 2:
                        conversion_command.extend(['-mapping_family', '1'])
                    opus_bitrate = (
                        f'{audio_encoding.opus_bitrate_kbps}k'
                        if audio_encoding.opus_bitrate_kbps
                        else ('128k' if channels <= 2 else '256k')
                    )
                    conversion_command.extend(['-b:a', opus_bitrate, converted_audio])
                else:
                    fdkaac = (
                        str(core_settings.FDK_AAC_PATH or '').strip()
                        or shutil.which('fdkaac')
                        or shutil.which('fdkaac.exe')
                        or ''
                    )
                    if not fdkaac:
                        raise FileNotFoundError(
                            translate_text('fdkaac executable does not exist')
                        )
                    converted_audio = os.path.join(work_folder, f'track-{track_id}.m4a')
                    fdkaac_rate_control = (
                        ['-b', str(audio_encoding.fdkaac_bitrate_kbps * 1000)]
                        if audio_encoding.fdkaac_bitrate_kbps
                        else ['-m', '5']
                    )
                    if not encode_fdkaac_from_ffmpeg(
                            ffmpeg,
                            fdkaac,
                            conversion_input,
                            '0:a:0',
                            converted_audio,
                            fdkaac_rate_control,
                    ):
                        raise RuntimeError(
                            translate_text(
                                'Audio conversion failed for track {track}: {path}'
                            ).format(track=track_id, path=source_path)
                        )
                    conversion_command = None

                if conversion_command is not None and (
                        run_command(
                            conversion_command,
                            log_template='Audio command: {command}',
                        ).returncode != 0
                        or not (
                            os.path.isfile(converted_audio)
                            and os.path.getsize(converted_audio) > 0
                        )
                ):
                    raise RuntimeError(
                        translate_text(
                            'Audio conversion failed for track {track}: {path}'
                        ).format(track=track_id, path=source_path)
                    )
                if target_codec == 'flac' and not converted_flac_duration_is_acceptable(
                        ffprobe,
                        source_duration,
                        converted_audio,
                        track_id,
                        source_path,
                        audio_encoding.duration_loss_fallback_threshold_seconds,
                ):
                    os.remove(converted_audio)
                    continue
                replacement_by_track[track_id] = (converted_audio, target_codec)
            except TaskCancelled:
                raise
            except (OSError, RuntimeError, ValueError) as error:
                if converted_audio and os.path.isfile(converted_audio):
                    os.remove(converted_audio)
                print(
                    translate_text(
                        'Audio conversion failed for track {track}; keeping the original: {path} ({error})'
                    ).format(track=track_id, path=source_path, error=error),
                    flush=True,
                )
                continue

        if (
                same_path
                and not replacement_by_track
                and len(kept_audio) == len(selected_audio)
                and not language_by_track
                and not subtitle_file
        ):
            return
        mkvmerge = str(core_settings.MKV_MERGE_PATH or '').strip() or shutil.which('mkvmerge') or ''
        if not mkvmerge:
            raise FileNotFoundError(translate_text('mkvmerge not found'))
        input_arguments: list[str] = []
        if encoded_video_file:
            input_arguments.append('-D')
        source_audio_to_keep = [
            track_id for track_id in kept_audio if track_id not in replacement_by_track
        ]
        input_arguments.extend(
            ['-a', ','.join(str(track_id) for track_id in source_audio_to_keep)]
            if source_audio_to_keep else ['-A']
        )
        input_arguments.extend(
            ['-s', ','.join(str(track_id) for track_id in selected_subtitles)]
            if selected_subtitles else ['-S']
        )
        for track_id, language in language_by_track.items():
            if track_id in track_by_id:
                input_arguments.extend(['--language', f'{track_id}:{language}'])
        input_arguments.append(source_path)

        next_input_index = 1
        replacement_input: dict[int, int] = {}
        for track in tracks:
            track_id = int(track['id'])
            replacement = replacement_by_track.get(track_id)
            if not replacement:
                continue
            replacement_path, _target_codec = replacement
            properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
            language = language_by_track.get(track_id) or str(properties.get('language') or 'und')
            input_arguments.extend(['--language', f'0:{language}'])
            track_name = str(properties.get('track_name') or '')
            if track_name:
                input_arguments.extend(['--track-name', f'0:{track_name}'])
            input_arguments.extend([
                '--default-track-flag',
                f'0:{"yes" if properties.get("default_track") else "no"}',
                '--forced-display-flag',
                f'0:{"yes" if properties.get("forced_track") else "no"}',
            ])
            try:
                delay_ms = int(round(int(properties.get('minimum_timestamp') or 0) / 1_000_000))
            except Exception:
                delay_ms = 0
            if delay_ms:
                input_arguments.extend(['--sync', f'0:{delay_ms}'])
            input_arguments.append(replacement_path)
            replacement_input[track_id] = next_input_index
            next_input_index += 1

        encoded_video_input = -1
        first_video_track = next(
            (track for track in tracks if track.get('type') == 'video'),
            None,
        )
        if encoded_video_file:
            encoded_path = os.path.abspath(os.path.normpath(encoded_video_file))
            if not os.path.isfile(encoded_path):
                raise FileNotFoundError(encoded_path)
            encoded_video_input = next_input_index
            next_input_index += 1
            if first_video_track:
                video_id = int(first_video_track['id'])
                video_properties = first_video_track.get('properties') \
                    if isinstance(first_video_track.get('properties'), dict) else {}
                video_language = language_by_track.get(video_id) or str(video_properties.get('language') or 'und')
                input_arguments.extend(['--language', f'0:{video_language}'])
                video_name = str(video_properties.get('track_name') or '')
                if video_name:
                    input_arguments.extend(['--track-name', f'0:{video_name}'])
                input_arguments.extend([
                    '--default-track-flag',
                    f'0:{"yes" if video_properties.get("default_track") else "no"}',
                    '--forced-display-flag',
                    f'0:{"yes" if video_properties.get("forced_track") else "no"}',
                ])
                try:
                    video_delay_ms = int(round(
                        int(video_properties.get('minimum_timestamp') or 0)
                        / 1_000_000
                    ))
                except (TypeError, ValueError):
                    video_delay_ms = 0
                if video_delay_ms:
                    input_arguments.extend(['--sync', f'0:{video_delay_ms}'])
            input_arguments.append(encoded_path)

        external_subtitle_input = -1
        if subtitle_file:
            external_subtitle_path = os.path.abspath(os.path.normpath(subtitle_file))
            if not os.path.isfile(external_subtitle_path):
                raise FileNotFoundError(external_subtitle_path)
            external_subtitle_input = next_input_index
            input_arguments.extend(['--language', f'0:{subtitle_language or "und"}', external_subtitle_path])

        track_order: list[str] = []
        expected_languages: list[str | None] = []
        encoded_video_added = False
        for track in tracks:
            track_id = int(track['id'])
            track_type = str(track.get('type') or '')
            if track_type == 'video':
                if encoded_video_file:
                    if encoded_video_added:
                        continue
                    track_order.append(f'{encoded_video_input}:0')
                    expected_languages.append(language_by_track.get(track_id))
                    encoded_video_added = True
                else:
                    track_order.append(f'0:{track_id}')
                    expected_languages.append(language_by_track.get(track_id))
            elif track_type == 'audio':
                if track_id not in kept_audio:
                    continue
                if track_id in replacement_input:
                    track_order.append(f'{replacement_input[track_id]}:0')
                else:
                    track_order.append(f'0:{track_id}')
                expected_languages.append(language_by_track.get(track_id))
            elif track_type == 'subtitles':
                if track_id not in selected_subtitles:
                    continue
                track_order.append(f'0:{track_id}')
                expected_languages.append(language_by_track.get(track_id))
            else:
                track_order.append(f'0:{track_id}')
                expected_languages.append(language_by_track.get(track_id))
        if external_subtitle_input >= 0:
            track_order.append(f'{external_subtitle_input}:0')
            expected_languages.append(subtitle_language or 'und')
        if not track_order:
            raise ValueError(
                translate_text('No tracks are selected for output: {path}').format(path=source_path)
            )

        mux_command = [mkvmerge]
        ui_language = mkvtoolnix_ui_language_arg().strip()
        if ui_language:
            mux_command.extend(ui_language.split())
        mux_command.extend([
            '--track-order',
            ','.join(track_order),
            '-o',
            temporary_output,
        ])
        mux_command.extend(input_arguments)
        report_progress('Muxing final Matroska output')
        mux_result = run_command(mux_command, log_template='Mux command: {command}')

        if mux_result.returncode not in (0, 1) or not (
                os.path.isfile(temporary_output) and os.path.getsize(temporary_output) > 0
        ):
            raise RuntimeError(
                translate_text('mkvmerge failed for: {path}').format(path=output_path)
            )

        output_tracks = _identify_tracks(temporary_output)
        if len(output_tracks) != len(track_order):
            raise RuntimeError(
                translate_text('Final track verification failed: {path}').format(path=output_path)
            )
        output_audio = [track for track in output_tracks if track.get('type') == 'audio']
        if len(output_audio) != len(kept_audio):
            raise RuntimeError(
                translate_text('Final audio track verification failed: {path}').format(path=output_path)
            )

        def normalized_language(language: object) -> str:
            normalized = str(language or 'und').strip().lower().replace('_', '-')
            primary = normalized.split('-', 1)[0]
            return 'zho' if primary in ('chi', 'cmn', 'yue', 'zh') else primary

        for output_track, expected_language in zip(output_tracks, expected_languages):
            if not expected_language:
                continue
            output_properties = output_track.get('properties') \
                if isinstance(output_track.get('properties'), dict) else {}
            actual_languages = {
                normalized_language(output_properties.get(property_name))
                for property_name in ('language', 'language_ietf')
                if output_properties.get(property_name)
            }
            if normalized_language(expected_language) not in actual_languages:
                raise RuntimeError(
                    translate_text('Final track language verification failed: {path}').format(
                        path=output_path
                    )
                )
        os.replace(temporary_output, output_path)
    except TaskCancelled:
        raise
    except Exception as error:
        if preserve_failure_artifacts:
            artifact_paths = tuple(
                os.path.join(current_folder, filename)
                for current_folder, _directories, filenames in os.walk(work_folder)
                for filename in filenames
                if (
                    os.path.isfile(os.path.join(current_folder, filename))
                    and os.path.getsize(os.path.join(current_folder, filename)) > 0
                )
            )
            if artifact_paths:
                keep_work_folder = True
                raise AudioMuxFailure(str(error), artifact_paths) from error
        raise
    finally:
        if not keep_work_folder:
            shutil.rmtree(work_folder, ignore_errors=True)


__all__ = [
    'AudioEncodingSettings',
    'AudioMuxFailure',
    'convert_audio_stream_to_flac',
    'converted_flac_duration_is_acceptable',
    'encode_fdkaac_from_ffmpeg',
    'is_immersive_audio_codec',
    'is_lossless_audio_codec',
    'mux_with_audio_conversion',
    'probe_audio_stream',
    'probe_audio_streams',
    'validate_audio_cleanup_tools',
    'validate_audio_conversion_tools',
]
