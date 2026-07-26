"""Automatic audio cleanup, lossless conversion, and verified Matroska muxing."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from typing import Optional

from src.core import find_mkvtoolnix, mkvtoolnix_ui_language_arg
from src.core import settings as core_settings
from src.core.i18n import translate_text
from src.exports.utils import mkv_codec_id_is_dts_family, run_command


@dataclass(frozen=True)
class AudioEncodingSettings:
    """Audio encoder values captured from application settings at task launch."""

    flac_compression_level: int = 8
    ffmpeg_flac_compression_level: int = 8
    fdkaac_bitrate_kbps: int = 0
    opus_bitrate_kbps: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.flac_compression_level <= 8:
            raise ValueError("FLAC compression level must be from 0 to 8")
        if not 0 <= self.ffmpeg_flac_compression_level <= 12:
            raise ValueError("FFmpeg FLAC compression level must be from 0 to 12")
        if not 0 <= self.fdkaac_bitrate_kbps <= 1024:
            raise ValueError("FDK-AAC bitrate must be from 0 to 1024 kbps")
        if not 0 <= self.opus_bitrate_kbps <= 1024:
            raise ValueError("Opus bitrate must be from 0 to 1024 kbps")


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


def _is_lossless_audio_track(track: dict[str, object]) -> bool:
    properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
    codec_id = str(properties.get('codec_id') or '').strip().upper()
    codec_name = str(track.get('codec') or '').strip().lower()
    return bool(
        codec_id in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG', 'A_TRUEHD', 'A_MLP', 'A_FLAC')
        or mkv_codec_id_is_dts_family(codec_id)
        or codec_name.startswith('pcm')
        or 'truehd' in codec_name
        or 'dts-hd' in codec_name
        or codec_name == 'flac'
    )


def _truehdd_path() -> str:
    """Return a usable truehdd executable or an empty string."""
    configured_path = str(core_settings.TRUEHDD_PATH or '').strip()
    if configured_path and (
            os.path.isfile(configured_path) or shutil.which(configured_path)
    ):
        return configured_path
    return shutil.which('truehdd') or shutil.which('truehdd.exe') or ''


def validate_audio_cleanup_tools() -> None:
    """Require the extractor and decoder used by automatic audio cleanup."""
    find_mkvtoolnix()
    ffmpeg = str(core_settings.FFMPEG_PATH or '').strip() or shutil.which('ffmpeg') or ''
    if not ffmpeg or not (os.path.isfile(ffmpeg) or shutil.which(ffmpeg)):
        raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
    mkvextract = str(core_settings.MKV_EXTRACT_PATH or '').strip() or shutil.which('mkvextract') or ''
    if not mkvextract or not (os.path.isfile(mkvextract) or shutil.which(mkvextract)):
        raise FileNotFoundError(translate_text('mkvextract not found'))


def _extract_selected_audio_tracks(
        mkvextract: str,
        source_path: str,
        work_folder: str,
        audio_tracks: list[dict[str, object]],
        selected_audio: tuple[int, ...],
) -> dict[int, str]:
    """Extract every selected audio track in one source-container pass."""
    if not selected_audio:
        return {}
    if not mkvextract:
        raise FileNotFoundError(translate_text('mkvextract not found'))

    extracted_audio_by_track: dict[int, str] = {}
    extract_command = [mkvextract]
    ui_language = mkvtoolnix_ui_language_arg().strip()
    if ui_language:
        extract_command.extend(ui_language.split())
    extract_command.extend(['tracks', source_path])
    extension_by_codec = {
        'A_PCM/INT/LIT': '.wav',
        'A_PCM/INT/BIG': '.wav',
        'A_TRUEHD': '.thd',
        'A_MLP': '.thd',
        'A_FLAC': '.flac',
        'A_AC3': '.ac3',
        'A_EAC3': '.eac3',
        'A_AAC': '.aac',
        'A_MPEG/L3': '.mp3',
        'A_MPEG/L2': '.mp2',
        'A_OPUS': '.opus',
        'A_VORBIS': '.ogg',
    }
    for track in audio_tracks:
        track_id = int(track['id'])
        if track_id not in selected_audio:
            continue
        properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
        codec_id = str(properties.get('codec_id') or '').strip().upper()
        extension = (
            '.dts'
            if mkv_codec_id_is_dts_family(codec_id)
            else extension_by_codec.get(codec_id, '.audio')
        )
        extracted_audio = os.path.join(work_folder, f'track-{track_id}{extension}')
        extracted_audio_by_track[track_id] = extracted_audio
        extract_command.append(f'{track_id}:{extracted_audio}')

    extract_result = run_command(
        extract_command,
        log_template='Audio extraction command: {command}',
    )
    for track_id, extracted_audio in extracted_audio_by_track.items():
        if extract_result.returncode not in (0, 1) or not (
                os.path.isfile(extracted_audio) and os.path.getsize(extracted_audio) > 0
        ):
            raise RuntimeError(
                translate_text('Audio extraction failed for track {track}: {path}').format(
                    track=track_id,
                    path=source_path,
                )
            )
    return extracted_audio_by_track


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
        codec_name = str(track.get('codec') or '').strip().lower()
        if not _is_lossless_audio_track(track) or (
                codec_id == 'A_FLAC' and target_codec == 'flac'
        ):
            continue
        if (
                codec_id in ('A_TRUEHD', 'A_MLP')
                and 'atmos' in codec_name
                and not _truehdd_path()
        ):
            continue
        if target_codec == 'aac':
            requires_fdkaac = True
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
        track_language_overrides: tuple[tuple[str, str], ...] = (),
        encoded_video_file: str = '',
        subtitle_file: str = '',
        subtitle_language: str = '',
        audio_encoding: AudioEncodingSettings = AudioEncodingSettings(),
) -> None:
    """Clean selected audio, convert requested lossless tracks, and mux atomically."""
    source_path = os.path.abspath(os.path.normpath(source_file))
    output_path = os.path.abspath(os.path.normpath(output_file))
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)
    same_path = os.path.normcase(source_path) == os.path.normcase(output_path)
    if os.path.exists(output_path) and not same_path:
        raise FileExistsError(
            translate_text('Output file already exists: {path}').format(path=output_path)
        )

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
    expected_audio_codecs: list[str | None] = []
    try:
        find_mkvtoolnix()
        mkvextract = str(core_settings.MKV_EXTRACT_PATH or '').strip() or shutil.which('mkvextract') or ''
        ffmpeg = str(core_settings.FFMPEG_PATH or '').strip() or shutil.which('ffmpeg') or ''
        configured_flac = str(core_settings.FLAC_PATH or '').strip()
        flac_encoder = (
            configured_flac
            if configured_flac and (os.path.isfile(configured_flac) or shutil.which(configured_flac))
            else shutil.which('flac') or shutil.which('flac.exe') or ''
        )

        if selected_audio and not ffmpeg:
            raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
        audio_tracks = [track for track in tracks if track.get('type') == 'audio']
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
        # The source MKV can be hundreds of gigabytes. Extract selected audio in
        # one mkvextract invocation, then reuse the elementary streams for both
        # cleanup analysis and conversion instead of reopening the MKV per track.
        extracted_audio_by_track = _extract_selected_audio_tracks(
            mkvextract,
            source_path,
            work_folder,
            audio_tracks,
            selected_audio,
        )
        kept_audio = _selected_audio_after_cleanup(
            ffmpeg,
            source_path,
            audio_tracks,
            selected_audio,
            language_by_track,
            extracted_audio_by_track,
        )
        for track in audio_tracks:
            track_id = int(track['id'])
            if track_id not in kept_audio:
                continue
            target_codec = str(codec_by_track.get(track_id) or '').strip().lower()
            expected_audio_codecs.append(None)
            properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
            codec_id = str(properties.get('codec_id') or '').strip().upper()
            codec_name = str(track.get('codec') or '').strip().lower()
            if not target_codec or not _is_lossless_audio_track(track):
                continue
            if codec_id == 'A_FLAC' and target_codec == 'flac':
                expected_audio_codecs[-1] = target_codec
                continue
            truehd_atmos = codec_id in ('A_TRUEHD', 'A_MLP') and 'atmos' in codec_name
            truehdd = _truehdd_path() if truehd_atmos else ''
            if truehd_atmos and not truehdd:
                print(
                    translate_text(
                        'TrueHD Atmos track {track} will be kept because truehdd is unavailable or failed'
                    ).format(track=track_id),
                    flush=True,
                )
                continue
            extracted_audio = extracted_audio_by_track[track_id]
            conversion_input = extracted_audio
            if truehd_atmos:
                decoded_base = os.path.join(work_folder, f'track-{track_id}-decoded')
                decode_command = [
                    truehdd,
                    '--progress',
                    'decode',
                    '--format',
                    'w64',
                    '--presentation',
                    '2',
                    '--output-path',
                    decoded_base,
                    extracted_audio,
                ]
                decoded_wave = decoded_base + '.wav'
                try:
                    decode_succeeded = run_command(decode_command, log_template='Audio command: {command}').returncode == 0
                except OSError:
                    decode_succeeded = False
                if decode_succeeded and (
                        os.path.isfile(decoded_wave) and os.path.getsize(decoded_wave) > 0
                ):
                    conversion_input = decoded_wave
                else:
                    print(
                        translate_text(
                            'TrueHD Atmos track {track} will be kept because truehdd is unavailable or failed'
                        ).format(track=track_id),
                        flush=True,
                    )
                    continue

            if target_codec == 'flac':
                converted_audio = os.path.join(work_folder, f'track-{track_id}.flac')
                flac_input = conversion_input
                # Compressed lossless streams must be decoded before the standalone FLAC encoder can read them.
                if flac_encoder and os.path.splitext(flac_input)[1].lower() not in ('.wav', '.w64'):
                    if not ffmpeg:
                        raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
                    flac_input = os.path.join(work_folder, f'track-{track_id}-decoded.wav')
                    decode_command = [
                        ffmpeg, '-y', '-i', conversion_input,
                        '-map', '0:a:0', '-c:a', 'pcm_s24le', flac_input,
                    ]
                    if run_command(decode_command, log_template='Audio command: {command}').returncode != 0 or not (
                            os.path.isfile(flac_input) and os.path.getsize(flac_input) > 0
                    ):
                        raise RuntimeError(
                            translate_text('Audio decode failed for track {track}: {path}').format(
                                track=track_id, path=source_path,
                            )
                        )
                flac_succeeded = False
                if flac_encoder:
                    try:
                        flac_succeeded = run_command([
                            flac_encoder,
                            f'-{audio_encoding.flac_compression_level}',
                            '-j',
                            str(os.cpu_count() or 1),
                            '-f',
                            '-o', converted_audio, flac_input,
                        ], log_template='Audio command: {command}').returncode == 0 and (
                            os.path.isfile(converted_audio) and os.path.getsize(converted_audio) > 0
                        )
                    except OSError:
                        flac_succeeded = False
                conversion_command = None
                if not flac_succeeded:
                    # Reuse the decoded wave when the standalone FLAC encode fails.
                    if os.path.isfile(converted_audio):
                        os.remove(converted_audio)
                    if not ffmpeg:
                        raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
                    conversion_command = [
                        ffmpeg, '-y', '-i', flac_input, '-map', '0:a:0', '-c:a', 'flac',
                        '-compression_level',
                        str(audio_encoding.ffmpeg_flac_compression_level),
                        converted_audio,
                    ]
            elif target_codec == 'opus':
                if not ffmpeg:
                    raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
                converted_audio = os.path.join(work_folder, f'track-{track_id}.opus')
                try:
                    channels = int(properties.get('audio_channels') or 2)
                except Exception:
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
                if not ffmpeg:
                    raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
                fdkaac = str(core_settings.FDK_AAC_PATH or '').strip() or shutil.which('fdkaac') or shutil.which('fdkaac.exe') or ''
                if not fdkaac:
                    raise FileNotFoundError(translate_text('fdkaac executable does not exist'))
                wave_path = os.path.join(work_folder, f'track-{track_id}.wav')
                wave_command = [
                    ffmpeg,
                    '-y',
                    '-i',
                    conversion_input,
                    '-map',
                    '0:a:0',
                    '-c:a',
                    'pcm_s24le',
                    wave_path,
                ]
                if run_command(wave_command, log_template='Audio command: {command}').returncode != 0 or not os.path.isfile(wave_path):
                    raise RuntimeError(
                        translate_text('Audio decode failed for track {track}: {path}').format(
                            track=track_id,
                            path=source_path,
                        )
                    )
                converted_audio = os.path.join(work_folder, f'track-{track_id}.m4a')
                fdkaac_rate_control = (
                    ['-b', str(audio_encoding.fdkaac_bitrate_kbps * 1000)]
                    if audio_encoding.fdkaac_bitrate_kbps
                    else ['-m', '5']
                )
                conversion_command = [
                    fdkaac,
                    *fdkaac_rate_control,
                    '-o',
                    converted_audio,
                    wave_path,
                ]

            if conversion_command is not None and (
                    run_command(conversion_command, log_template='Audio command: {command}').returncode != 0
                    or not (os.path.isfile(converted_audio) and os.path.getsize(converted_audio) > 0)
            ):
                raise RuntimeError(
                    translate_text('Audio conversion failed for track {track}: {path}').format(
                        track=track_id,
                        path=source_path,
                    )
                )
            # DTS is already a compact lossless source in this workflow. Replacing
            # it with a larger FLAC defeats the conversion's size-saving purpose,
            # so keep the original container track. PCM and TrueHD/MLP retain a
            # successfully encoded FLAC even when it is larger, matching the
            # established behavior for those formats.
            if (
                    target_codec == 'flac'
                    and mkv_codec_id_is_dts_family(codec_id)
                    and os.path.getsize(converted_audio) > os.path.getsize(extracted_audio)
            ):
                print(
                    translate_text(
                        'FLAC is larger than the DTS source; keeping the original track: {path}'
                    ).format(path=extracted_audio),
                    flush=True,
                )
                os.remove(converted_audio)
                continue
            replacement_by_track[track_id] = (converted_audio, target_codec)
            expected_audio_codecs[-1] = target_codec

        if (
                same_path
                and not replacement_by_track
                and len(kept_audio) == len(selected_audio)
                and not language_by_track
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
        expected_codec_ids = {
            'flac': 'A_FLAC',
            'opus': 'A_OPUS',
            'aac': 'A_AAC',
        }
        for output_track, expected_codec in zip(output_audio, expected_audio_codecs):
            if not expected_codec:
                continue
            output_properties = output_track.get('properties') \
                if isinstance(output_track.get('properties'), dict) else {}
            output_codec_id = str(output_properties.get('codec_id') or '').upper()
            wanted_codec_id = expected_codec_ids[expected_codec]
            if not (
                    output_codec_id == wanted_codec_id
                    or (wanted_codec_id == 'A_AAC' and output_codec_id.startswith('A_AAC'))
            ):
                raise RuntimeError(
                    translate_text('Final audio codec verification failed: {path}').format(
                        path=output_path
                    )
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
            if normalized_language(output_properties.get('language')) != normalized_language(expected_language):
                raise RuntimeError(
                    translate_text('Final track language verification failed: {path}').format(
                        path=output_path
                    )
                )
        os.replace(temporary_output, output_path)
    finally:
        shutil.rmtree(work_folder, ignore_errors=True)


__all__ = [
    'AudioEncodingSettings',
    'mux_with_audio_conversion',
    'validate_audio_cleanup_tools',
    'validate_audio_conversion_tools',
]
