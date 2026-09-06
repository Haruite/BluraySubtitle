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
from src.core.media_language import normalize_track_language
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


@dataclass(frozen=True)
class _ExtractedAudioRun:
    """One decoded interval on a logical audio track's Matroska timeline."""

    timeline_start_seconds: float
    timeline_duration_seconds: Optional[float]
    wave64_path: str


_AUDIO_GAP_SIDECAR_SUFFIX = '.audio-gaps.json'


def audio_gap_sidecar_path(media_path: str) -> str:
    """Return the sidecar owned by one Matroska output."""
    return os.path.abspath(os.path.normpath(media_path)) + _AUDIO_GAP_SIDECAR_SUFFIX


def _complement_audio_gaps(
        gaps: tuple[tuple[float, float], ...],
        timeline_duration: float,
) -> tuple[tuple[float, float], ...]:
    runs: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in gaps:
        start = max(cursor, min(float(start), timeline_duration))
        end = max(start, min(float(end), timeline_duration))
        if start > cursor + 0.0005:
            runs.append((cursor, start - cursor))
        cursor = end
    if timeline_duration > cursor + 0.0005:
        runs.append((cursor, timeline_duration - cursor))
    return tuple(runs)


def load_audio_gap_sidecar(
        media_path: str,
        tracks: list[dict[str, object]],
) -> Optional[dict[int, tuple[tuple[float, float], ...]]]:
    """Load a valid sidecar, including an empty marker for continuous audio."""
    sidecar = audio_gap_sidecar_path(media_path)
    if not os.path.isfile(sidecar):
        return None
    try:
        with open(sidecar, 'r', encoding='utf-8') as stream:
            payload = json.load(stream)
        if int(payload.get('version') or 0) != 1:
            return None
        if int(payload.get('media_size') or -1) != os.path.getsize(media_path):
            return None
        rows = payload.get('tracks')
        if not isinstance(rows, list):
            return None
        timeline_duration = float(payload['timeline_duration_seconds'])
        if (
                not math.isfinite(timeline_duration)
                or timeline_duration < 0
                or (rows and timeline_duration <= 0)
        ):
            return None
        track_by_id = {int(track['id']): track for track in tracks if 'id' in track}
        result: dict[int, tuple[tuple[float, float], ...]] = {}
        for row in rows:
            track_id = int(row['track_id'])
            track = track_by_id.get(track_id)
            if track is None or track.get('type') != 'audio':
                return None
            properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
            expected_uid = str(row.get('track_uid') or '').strip()
            actual_uid = str(properties.get('uid') or '').strip()
            if expected_uid and actual_uid and expected_uid != actual_uid:
                return None
            gaps = tuple(
                (float(gap[0]), float(gap[1]))
                for gap in row.get('gaps') or []
                if isinstance(gap, list) and len(gap) == 2
            )
            if not gaps:
                continue
            previous_end = -1.0
            for start, end in gaps:
                if (
                        not math.isfinite(start) or not math.isfinite(end)
                        or start < 0 or end <= start
                        or start + 0.0005 < previous_end
                        or end > timeline_duration + 0.002
                ):
                    return None
                previous_end = end
            runs = _complement_audio_gaps(gaps, timeline_duration)
            if runs:
                result[track_id] = runs
        return result
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def write_audio_gap_sidecar(
        media_path: str,
        timeline_by_track: dict[int, tuple[tuple[float, float], ...]],
        timeline_duration_seconds: float,
        tracks: Optional[list[dict[str, object]]] = None,
) -> None:
    """Atomically persist detected gaps or an empty continuous-audio marker."""
    sidecar = audio_gap_sidecar_path(media_path)
    duration = float(timeline_duration_seconds)
    track_by_id = {
        int(track['id']): track for track in (tracks or []) if 'id' in track
    }
    rows: list[dict[str, object]] = []
    for track_id in sorted(timeline_by_track):
        runs = sorted(timeline_by_track[track_id])
        cursor = 0.0
        gaps: list[list[float]] = []
        for start, run_duration in runs:
            start = max(0.0, float(start))
            end = min(duration, start + max(0.0, float(run_duration)))
            if start > cursor + 0.0005:
                gaps.append([round(cursor, 6), round(start, 6)])
            cursor = max(cursor, end)
        if duration > cursor + 0.0005:
            gaps.append([round(cursor, 6), round(duration, 6)])
        if not gaps:
            continue
        track = track_by_id.get(int(track_id)) or {}
        properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
        rows.append({
            'track_id': int(track_id),
            'track_uid': str(properties.get('uid') or ''),
            'gaps': gaps,
        })
    payload = {
        'version': 1,
        'media_size': os.path.getsize(media_path),
        'timeline_duration_seconds': round(duration, 6),
        'tracks': rows,
    }
    temporary = sidecar + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, sidecar)
    finally:
        if os.path.isfile(temporary):
            os.remove(temporary)


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
    """Return whether channel-based conversion would discard object metadata."""
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


def converted_audio_runs_are_acceptable(
        ffprobe: str,
        extracted_runs: tuple[_ExtractedAudioRun, ...],
        converted_paths: tuple[str, ...],
        track: object,
        source_path: str,
        fallback_threshold_seconds: float,
        source_duration_seconds: Optional[float] = None,
) -> bool:
    """Validate every encoded run and use the largest shortening for fallback."""
    if len(extracted_runs) != len(converted_paths) or not extracted_runs:
        raise ValueError(
            translate_text('Audio conversion failed for track {track}: {path}').format(
                track=track,
                path=source_path,
            )
        )
    duration_losses: list[float] = []
    for extracted_run, converted_path in zip(extracted_runs, converted_paths):
        expected_duration = extracted_run.timeline_duration_seconds
        if expected_duration is None:
            if source_duration_seconds is not None and len(extracted_runs) == 1:
                source_duration = float(source_duration_seconds)
            else:
                _profile, source_duration = probe_audio_stream(
                    ffprobe, extracted_run.wave64_path
                )
        else:
            source_duration = float(expected_duration)
        _profile, converted_duration = probe_audio_stream(ffprobe, converted_path)
        duration_losses.append(max(0.0, round(source_duration - converted_duration, 6)))
    duration_loss = max(duration_losses, default=0.0)
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
        audio_timeline_by_track: Optional[
            dict[int, tuple[tuple[float, float], ...]]
        ] = None,
        ffprobe: str = '',
        expected_duration_by_track: Optional[dict[int, float]] = None,
        detect_timeline_gaps: bool = False,
) -> dict[int, tuple[_ExtractedAudioRun, ...]]:
    """Decode all selected intervals together, then retry failed logical tracks."""
    if not selected_audio:
        return {}
    if not ffmpeg:
        raise FileNotFoundError(translate_text('ffmpeg executable does not exist'))
    if wave64_bit_depth not in (24, 32):
        raise ValueError(f'Unsupported Wave64 bit depth: {wave64_bit_depth}')

    normalized_timeline_by_track: dict[int, tuple[tuple[float, float], ...]] = {}
    for raw_track_id, raw_runs in (audio_timeline_by_track or {}).items():
        track_id = int(raw_track_id)
        normalized_runs: list[tuple[float, float]] = []
        previous_end = -1.0
        for raw_start, raw_duration in raw_runs:
            start = float(raw_start)
            duration = float(raw_duration)
            if (
                    not math.isfinite(start)
                    or not math.isfinite(duration)
                    or start < 0
                    or duration <= 0
                    or start + 0.0005 < previous_end
            ):
                raise ValueError(
                    translate_text(
                        'Invalid audio timeline for track {track}: {path}'
                    ).format(track=track_id, path=source_path)
                )
            normalized_runs.append((start, duration))
            previous_end = start + duration
        if normalized_runs:
            normalized_timeline_by_track[track_id] = tuple(normalized_runs)

    extracted_audio_by_track: dict[int, tuple[_ExtractedAudioRun, ...]] = {}
    for track_id in selected_audio:
        if track_id not in audio_index_by_track:
            raise ValueError(
                translate_text('Selected audio track is missing from: {path}').format(
                    path=source_path
                )
            )
        timeline_runs = normalized_timeline_by_track.get(track_id)
        if timeline_runs:
            extracted_audio_by_track[track_id] = tuple(
                _ExtractedAudioRun(
                    timeline_start_seconds=start,
                    timeline_duration_seconds=duration,
                    wave64_path=os.path.join(
                        work_folder,
                        f'track-{track_id}-run-{run_index:03d}.w64',
                    ),
                )
                for run_index, (start, duration) in enumerate(timeline_runs)
            )
        else:
            extracted_audio_by_track[track_id] = (
                _ExtractedAudioRun(
                    timeline_start_seconds=0.0,
                    timeline_duration_seconds=None,
                    wave64_path=os.path.join(work_folder, f'track-{track_id}.w64'),
                ),
            )

    def extraction_command(track_ids: tuple[int, ...]) -> list[str]:
        command = [ffmpeg, '-y']
        uses_copyts = any(
                run.timeline_duration_seconds is not None
                for track_id in track_ids
                for run in extracted_audio_by_track[track_id]
        ) or detect_timeline_gaps
        if uses_copyts:
            command.append('-copyts')
        command.extend(['-i', source_path])
        for track_id in track_ids:
            for run in extracted_audio_by_track[track_id]:
                command.extend(['-map', f'0:a:{audio_index_by_track[track_id]}'])
                if run.timeline_duration_seconds is not None:
                    command.extend([
                        '-af',
                        (
                            f'atrim=start={run.timeline_start_seconds:.9f}:'
                            f'duration={run.timeline_duration_seconds:.9f},'
                            'asetpts=N/SR/TB'
                        ),
                    ])
                elif detect_timeline_gaps:
                    command.extend([
                        '-af',
                        f'ashowinfo@track_{track_id},asetpts=N/SR/TB',
                    ])
                elif uses_copyts:
                    # ``-copyts`` is input-global. Reset the timestamps for a
                    # continuous output that shares this batch with sparse
                    # outputs, otherwise Wave64 can contain almost no PCM even
                    # though FFmpeg exits successfully.
                    command.extend(['-af', 'asetpts=N/SR/TB'])
                command.extend([
                    '-c:a',
                    f'pcm_s{wave64_bit_depth}le',
                    '-f',
                    'w64',
                    run.wave64_path,
                ])
        return command

    frame_pattern = re.compile(
        r'ashowinfo@track_(?P<track>\d+).*?\bn:(?P<n>\d+)\s+'
        r'pts:(?P<pts>-?\d+)\s+pts_time:(?P<time>-?\d+(?:\.\d+)?)'
        r'.*?\brate:(?P<rate>\d+)\s+nb_samples:(?P<samples>\d+)',
        flags=re.IGNORECASE,
    )

    def detected_runs_from_log(
            log_path: str,
            track_ids: tuple[int, ...],
    ) -> dict[int, tuple[tuple[float, float, int, int, int], ...]]:
        if not detect_timeline_gaps:
            return {}
        frames: dict[int, list[tuple[float, int, int]]] = {
            track_id: [] for track_id in track_ids
        }
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as stream:
            for line in stream:
                match = frame_pattern.search(line)
                if not match:
                    continue
                track_id = int(match.group('track'))
                if track_id not in frames:
                    continue
                frames[track_id].append((
                    float(match.group('time')),
                    int(match.group('samples')),
                    int(match.group('rate')),
                ))
        detected: dict[int, tuple[tuple[float, float, int, int, int], ...]] = {}
        for track_id, track_frames in frames.items():
            if not track_frames:
                raise RuntimeError(
                    translate_text('Could not detect audio timeline: {path}').format(
                        path=source_path
                    )
                )
            rate = track_frames[0][2]
            if rate <= 0 or any(frame_rate != rate for _, _, frame_rate in track_frames):
                raise RuntimeError(
                    translate_text('Could not detect audio timeline: {path}').format(
                        path=source_path
                    )
                )
            run_start = track_frames[0][0]
            run_pcm_start = 0
            run_samples = 0
            pcm_cursor = 0
            previous_end = run_start
            runs: list[tuple[float, float, int, int, int]] = []
            # Matroska normally stores timestamps on a 1 ms scale. Decoded audio frames
            # can therefore alternate between slightly early and late boundaries, with
            # an apparent positive jump a little above 1 ms even though PCM is continuous.
            tolerance = max(0.0021, 2.0 / rate)
            for frame_start, sample_count, _frame_rate in track_frames:
                if sample_count <= 0:
                    continue
                delta = frame_start - previous_end
                if delta > tolerance and run_samples:
                    runs.append((
                        run_start,
                        run_samples / rate,
                        run_pcm_start,
                        run_samples,
                        rate,
                    ))
                    run_start = frame_start
                    run_pcm_start = pcm_cursor
                    run_samples = 0
                elif delta < -max(0.05, tolerance * 4):
                    raise RuntimeError(
                        translate_text('Could not detect audio timeline: {path}').format(
                            path=source_path
                        )
                    )
                run_samples += sample_count
                pcm_cursor += sample_count
                previous_end = max(previous_end, frame_start + sample_count / rate)
            if run_samples:
                runs.append((
                    run_start,
                    run_samples / rate,
                    run_pcm_start,
                    run_samples,
                    rate,
                ))
            detected[track_id] = tuple(runs)
        return detected

    def materialize_detected_runs(
            track_id: int,
            detected_runs: tuple[tuple[float, float, int, int, int], ...],
    ) -> tuple[_ExtractedAudioRun, ...]:
        if not detected_runs:
            raise RuntimeError(
                translate_text('Could not detect audio timeline: {path}').format(path=source_path)
            )
        has_gap = detected_runs[0][0] > 0.0011 or len(detected_runs) > 1
        if not has_gap:
            start, duration, _pcm_start, _sample_count, _rate = detected_runs[0]
            return (
                _ExtractedAudioRun(
                    start,
                    duration,
                    extracted_audio_by_track[track_id][0].wave64_path,
                ),
            )
        original_path = extracted_audio_by_track[track_id][0].wave64_path
        command = [ffmpeg, '-y', '-i', original_path]
        result_runs: list[_ExtractedAudioRun] = []
        for run_index, (start, duration, pcm_start, sample_count, _rate) in enumerate(
                detected_runs):
            run_path = os.path.join(
                work_folder, f'track-{track_id}-run-{run_index:03d}.w64'
            )
            command.extend([
                '-map', '0:a:0',
                '-af', (
                    f'atrim=start_sample={pcm_start}:end_sample={pcm_start + sample_count},'
                    'asetpts=N/SR/TB'
                ),
                '-c:a', f'pcm_s{wave64_bit_depth}le', '-f', 'w64', run_path,
            ])
            result_runs.append(_ExtractedAudioRun(start, duration, run_path))
        split_result = run_command(
            command,
            log_template='Audio extraction command: {command}',
        )
        if split_result.returncode != 0 or not all(
                os.path.isfile(run.wave64_path) and os.path.getsize(run.wave64_path) > 0
                for run in result_runs):
            raise RuntimeError(
                translate_text('Audio extraction failed for track {track}: {path}').format(
                    track=track_id, path=source_path,
                )
            )
        os.remove(original_path)
        return tuple(result_runs)

    def run_extraction(
            track_ids: tuple[int, ...],
            log_name: str,
    ) -> tuple[object, dict[int, tuple[tuple[float, float, int, int, int], ...]]]:
        log_path = os.path.join(work_folder, log_name)
        if not detect_timeline_gaps:
            return run_command(
                extraction_command(track_ids),
                log_template='Audio extraction command: {command}',
            ), {}
        with open(log_path, 'w', encoding='utf-8', errors='ignore') as log_stream:
            result = run_command(
                extraction_command(track_ids),
                stdout=subprocess.DEVNULL,
                stderr=log_stream,
                log_template='Audio extraction command: {command}',
            )
        detected = detected_runs_from_log(log_path, track_ids) if result.returncode == 0 else {}
        os.remove(log_path)
        return result, detected

    def track_outputs_exist(track_id: int) -> bool:
        for run in extracted_audio_by_track[track_id]:
            if not (
                    os.path.isfile(run.wave64_path)
                    and os.path.getsize(run.wave64_path) > 0
            ):
                return False
            if not ffprobe:
                continue
            try:
                actual_duration = probe_audio_stream(ffprobe, run.wave64_path)[1]
            except (OSError, RuntimeError, ValueError):
                return False
            expected_duration = run.timeline_duration_seconds
            if expected_duration is None:
                expected_duration = (expected_duration_by_track or {}).get(track_id)
            if (
                    expected_duration is not None
                    and expected_duration > 1.0
                    and actual_duration + 1.0 < expected_duration * 0.5
            ):
                return False
        return True

    extract_command = extraction_command(selected_audio)

    batch_error: Exception | None = None
    try:
        extract_result, detected_by_track = run_extraction(
            selected_audio, 'audio-timeline-batch.log'
        )
        batch_succeeded = extract_result.returncode == 0 and all(
            track_outputs_exist(track_id) for track_id in selected_audio
        )
        if batch_succeeded:
            if detect_timeline_gaps:
                for track_id in selected_audio:
                    extracted_audio_by_track[track_id] = materialize_detected_runs(
                        track_id, detected_by_track[track_id]
                    )
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
    for extracted_runs in extracted_audio_by_track.values():
        for extracted_run in extracted_runs:
            if os.path.isfile(extracted_run.wave64_path):
                os.remove(extracted_run.wave64_path)

    recovered_audio_by_track: dict[int, tuple[_ExtractedAudioRun, ...]] = {}
    for track_id, extracted_runs in extracted_audio_by_track.items():
        track_error: Exception | None = None
        try:
            track_result, detected_by_track = run_extraction(
                (track_id,), f'audio-timeline-track-{track_id}.log'
            )
            if track_result.returncode == 0 and track_outputs_exist(track_id):
                if detect_timeline_gaps:
                    extracted_runs = materialize_detected_runs(
                        track_id, detected_by_track[track_id]
                    )
                recovered_audio_by_track[track_id] = extracted_runs
                continue
            track_error = RuntimeError(
                translate_text('Audio extraction failed for track {track}: {path}').format(
                    track=track_id,
                    path=source_path,
                )
            )
        except (OSError, RuntimeError, ValueError) as error:
            track_error = error
        for extracted_run in extracted_runs:
            if os.path.isfile(extracted_run.wave64_path):
                os.remove(extracted_run.wave64_path)
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
        effective_bit_depth: int,
        audio_encoding: AudioEncodingSettings,
) -> bool:
    """Encode one Wave64 interval at the logical track's effective depth."""
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


def _encode_wave64_to_codec(
        ffmpeg: str,
        flac_encoder: str,
        wave64_path: str,
        output_path: str,
        target_codec: str,
        channel_count: int,
        wave64_bit_depth: int,
        effective_bit_depth: int,
        audio_encoding: AudioEncodingSettings,
) -> bool:
    """Encode one decoded interval with the selected logical-track codec."""
    if target_codec == 'flac':
        return _encode_wave64_to_flac(
            ffmpeg,
            flac_encoder,
            wave64_path,
            output_path,
            wave64_bit_depth,
            effective_bit_depth,
            audio_encoding,
        )
    if target_codec == 'opus':
        command = [
            ffmpeg,
            '-y',
            '-i',
            wave64_path,
            '-map',
            '0:a:0',
            '-c:a',
            'libopus',
        ]
        if channel_count > 2:
            command.extend(['-mapping_family', '1'])
        bitrate = (
            f'{audio_encoding.opus_bitrate_kbps}k'
            if audio_encoding.opus_bitrate_kbps
            else ('128k' if channel_count <= 2 else '256k')
        )
        command.extend(['-b:a', bitrate, output_path])
        try:
            return run_command(
                command,
                log_template='Audio command: {command}',
            ).returncode == 0 and (
                os.path.isfile(output_path) and os.path.getsize(output_path) > 0
            )
        except OSError:
            return False

    fdkaac = (
        str(core_settings.FDK_AAC_PATH or '').strip()
        or shutil.which('fdkaac')
        or shutil.which('fdkaac.exe')
        or ''
    )
    if not fdkaac:
        return False
    rate_control = (
        ['-b', str(audio_encoding.fdkaac_bitrate_kbps * 1000)]
        if audio_encoding.fdkaac_bitrate_kbps
        else ['-m', '5']
    )
    return encode_fdkaac_from_ffmpeg(
        ffmpeg,
        fdkaac,
        wave64_path,
        '0:a:0',
        output_path,
        rate_control,
    )


def _probe_audio_packet_end(ffprobe: str, media_path: str) -> float:
    """Return the greatest non-negative audio packet end timestamp."""
    result = run_command(
        [
            ffprobe,
            '-v',
            'error',
            '-select_streams',
            'a:0',
            '-show_entries',
            'packet=pts_time,duration_time',
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
        packet_ends = [
            float(packet.get('pts_time')) + float(packet.get('duration_time') or 0)
            for packet in payload.get('packets') or []
            if isinstance(packet, dict) and packet.get('pts_time') not in (None, 'N/A')
        ]
        packet_end = max(packet_ends)
    except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
        packet_end = 0.0
    if result.returncode != 0 or not math.isfinite(packet_end) or packet_end <= 0:
        raise RuntimeError(
            translate_text('Could not probe audio duration: {path}').format(
                path=media_path
            )
        )
    return packet_end


def _mux_converted_audio_runs(
        mkvmerge: str,
        ffprobe: str,
        track_id: int,
        extracted_runs: tuple[_ExtractedAudioRun, ...],
        converted_paths: tuple[str, ...],
        output_path: str,
) -> tuple[str, Optional[int]]:
    """Append encoded runs once, preserving authored gaps without silence."""
    explicit_timeline = all(
        run.timeline_duration_seconds is not None for run in extracted_runs
    )
    if not explicit_timeline:
        return converted_paths[0], None
    initial_delay_ms = int(round(extracted_runs[0].timeline_start_seconds * 1000.0))
    if len(extracted_runs) == 1:
        return converted_paths[0], initial_delay_ms

    wrapped_paths: list[str] = []
    wrapped_packet_ends: list[float] = []
    output_root, _output_extension = os.path.splitext(output_path)
    for run_index, converted_path in enumerate(converted_paths):
        wrapped_path = f'{output_root}-run-{run_index:03d}.mka'
        wrap_result = run_command(
            [
                mkvmerge,
                '-o',
                wrapped_path,
                '-D',
                '-a',
                '0',
                '-S',
                converted_path,
            ],
            log_template='Audio timeline mux command: {command}',
        )
        if wrap_result.returncode not in (0, 1) or not (
                os.path.isfile(wrapped_path) and os.path.getsize(wrapped_path) > 0
        ):
            raise RuntimeError(
                translate_text(
                    'Audio timeline mux failed for track {track}'
                ).format(track=track_id)
            )
        wrapped_paths.append(wrapped_path)
        wrapped_packet_ends.append(_probe_audio_packet_end(ffprobe, wrapped_path))

    append_mappings = [
        f'{run_index}:0:{run_index - 1}:0'
        for run_index in range(1, len(extracted_runs))
    ]
    command = [mkvmerge]
    ui_language = mkvtoolnix_ui_language_arg().strip()
    if ui_language:
        command.extend(ui_language.split())
    command.extend([
        '--append-mode',
        'track',
        '--append-to',
        ','.join(append_mappings),
        '--track-order',
        '0:0',
        '-o',
        output_path,
    ])
    for run_index, (run, wrapped_path) in enumerate(
            zip(extracted_runs, wrapped_paths)):
        if run_index:
            command.append('+')
            previous_run = extracted_runs[run_index - 1]
            offset_seconds = (
                run.timeline_start_seconds
                - previous_run.timeline_start_seconds
                - wrapped_packet_ends[run_index - 1]
            )
            offset_ms = int(round(offset_seconds * 1000.0))
            if offset_ms:
                command.extend(['--sync', f'0:{offset_ms}'])
        command.extend(['-D', '-a', '0', '-S', wrapped_path])
    result = run_command(command, log_template='Audio timeline mux command: {command}')
    if result.returncode not in (0, 1) or not (
            os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    ):
        raise RuntimeError(
            translate_text('Audio timeline mux failed for track {track}').format(
                track=track_id
            )
        )
    return output_path, initial_delay_ms


def _encode_sparse_flac_timeline(
        ffmpeg: str,
        ffprobe: str,
        extracted_runs: tuple[_ExtractedAudioRun, ...],
        output_path: str,
        effective_bit_depth: int,
        audio_encoding: AudioEncodingSettings,
) -> tuple[str, int]:
    """Encode all sparse PCM runs with one FLAC stream and retained timestamps."""
    if len(extracted_runs) < 2 or not all(
            run.timeline_duration_seconds is not None for run in extracted_runs
    ):
        raise ValueError(
            translate_text('Sparse FLAC encoding requires multiple explicit runs')
        )
    if effective_bit_depth > 24:
        raise RuntimeError(
            translate_text(
                'Sparse 32-bit FLAC timelines are not supported by FFmpeg'
            )
        )

    source_durations = [
        probe_audio_stream(ffprobe, run.wave64_path)[1]
        for run in extracted_runs
    ]
    concat_inputs = ''.join(f'[{index}:a]' for index in range(len(extracted_runs)))
    cumulative_source = 0.0
    previous_offset = 0.0
    timestamp_terms: list[str] = []
    first_start = extracted_runs[0].timeline_start_seconds
    for run_index in range(1, len(extracted_runs)):
        cumulative_source += source_durations[run_index - 1]
        desired_start = extracted_runs[run_index].timeline_start_seconds - first_start
        desired_offset = desired_start - cumulative_source
        step_offset = desired_offset - previous_offset
        if abs(step_offset) > 0.0000005:
            timestamp_terms.append(
                f'if(gte(T\\,{cumulative_source:.9f})\\,{step_offset:.9f}/TB\\,0)'
            )
        previous_offset = desired_offset
    timestamp_expression = 'PTS-STARTPTS'
    if timestamp_terms:
        timestamp_expression += '+' + '+'.join(timestamp_terms)
    filter_graph = (
        f'{concat_inputs}concat=n={len(extracted_runs)}:v=0:a=1,'
        f'asetpts={timestamp_expression}[audio]'
    )
    command = [ffmpeg, '-y']
    for extracted_run in extracted_runs:
        command.extend(['-i', extracted_run.wave64_path])
    command.extend([
        '-filter_complex',
        filter_graph,
        '-map',
        '[audio]',
        '-c:a',
        'flac',
        '-frame_size',
        '256',
    ])
    if effective_bit_depth <= 16:
        command.extend(['-sample_fmt', 's16'])
    else:
        command.extend(['-sample_fmt', 's32', '-bits_per_raw_sample', '24'])
    command.extend([
        '-compression_level',
        str(audio_encoding.ffmpeg_flac_compression_level),
        output_path,
    ])
    result = run_command(command, log_template='Audio command: {command}')
    if result.returncode != 0 or not (
            os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    ):
        raise RuntimeError(translate_text('Sparse FLAC timeline encoding failed'))
    return output_path, int(round(first_start * 1000.0))


def _validate_sparse_audio_timeline(
        ffmpeg: str,
        ffprobe: str,
        track_id: int,
        extracted_runs: tuple[_ExtractedAudioRun, ...],
        converted_path: str,
        work_folder: str,
        wave64_bit_depth: int,
        source_path: str,
        fallback_threshold_seconds: float,
) -> bool:
    """Decode authored windows once and validate the largest per-run loss."""
    if len(extracted_runs) < 2:
        raise ValueError(
            translate_text('Sparse timeline validation requires multiple runs')
        )
    first_start = extracted_runs[0].timeline_start_seconds
    validation_paths = tuple(
        os.path.join(
            work_folder,
            f'track-{track_id}-validated-run-{run_index:03d}.w64',
        )
        for run_index in range(len(extracted_runs))
    )
    command = [ffmpeg, '-y', '-copyts', '-i', converted_path]
    pcm_codec = 'pcm_s24le' if wave64_bit_depth == 24 else 'pcm_s32le'
    for extracted_run, validation_path in zip(extracted_runs, validation_paths):
        relative_start = extracted_run.timeline_start_seconds - first_start
        duration = float(extracted_run.timeline_duration_seconds or 0.0)
        command.extend([
            '-map',
            '0:a:0',
            '-af',
            (
                f'atrim=start={relative_start:.9f}:duration={duration:.9f},'
                'asetpts=N/SR/TB'
            ),
            '-c:a',
            pcm_codec,
            '-f',
            'w64',
            validation_path,
        ])
    result = run_command(command, log_template='Audio extraction command: {command}')
    if result.returncode != 0 or not all(
            os.path.isfile(path) and os.path.getsize(path) > 0
            for path in validation_paths
    ):
        raise RuntimeError(
            translate_text('Audio conversion failed for track {track}: {path}').format(
                track=track_id,
                path=source_path,
            )
        )
    return converted_audio_runs_are_acceptable(
        ffprobe,
        extracted_runs,
        validation_paths,
        track_id,
        source_path,
        fallback_threshold_seconds,
    )


def convert_audio_stream(
        input_media: str,
        stream_selector: str,
        output_path: str,
        *,
        target_codec: str,
        channel_count: int = 2,
        wave64_bit_depth: int = 24,
        audio_encoding: AudioEncodingSettings = AudioEncodingSettings(),
) -> bool:
    """Convert one selected stream through the shared Wave64 path."""
    if not input_media or not os.path.isfile(input_media) or not output_path:
        return False
    normalized_codec = str(target_codec or '').strip().lower()
    if normalized_codec not in ('flac', 'aac', 'opus'):
        raise ValueError(
            translate_text('Unsupported lossless audio codec: {codec}').format(
                codec=target_codec
            )
        )
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
        _source_profile, source_duration = probe_audio_stream(
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
        effective_bit_depth = (
            get_effective_bit_depth(wave64_path, wave64_bit_depth)
            if normalized_codec == 'flac' else wave64_bit_depth
        )
        if not _encode_wave64_to_codec(
                ffmpeg,
                _flac_encoder_path(),
                wave64_path,
                normalized_output,
                normalized_codec,
                max(1, int(channel_count)),
                wave64_bit_depth,
                effective_bit_depth,
                audio_encoding,
        ):
            if os.path.isfile(normalized_output):
                os.remove(normalized_output)
            return False
        duration_ok = converted_audio_runs_are_acceptable(
            ffprobe,
            (_ExtractedAudioRun(0.0, None, wave64_path),),
            (normalized_output,),
            ffprobe_selector,
            input_media,
            audio_encoding.duration_loss_fallback_threshold_seconds,
            source_duration,
        )
        if not duration_ok:
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
        extracted_audio_by_track: dict[int, tuple[_ExtractedAudioRun, ...]],
) -> list[int]:
    """Remove silent and timeline-identical duplicates in source order."""
    kept_audio: list[int] = []
    fingerprints: dict[
        tuple[str, int, tuple[tuple[float, float, str], ...]],
        list[tuple[int, str]],
    ] = {}
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
        extracted_runs = extracted_audio_by_track[track_id]
        try:
            analyses = [
                _analyze_audio_track(
                    ffmpeg,
                    extracted_run.wave64_path,
                    source_path,
                    track_id,
                )
                for extracted_run in extracted_runs
            ]
        except (OSError, RuntimeError, ValueError) as error:
            extracted_audio_by_track.pop(track_id, None)
            kept_audio.append(track_id)
            print(
                translate_text(
                    'Audio extraction failed for track {track}; keeping the original: {path} ({error})'
                ).format(track=track_id, path=source_path, error=error),
                flush=True,
            )
            continue
        maximum_volume = max(result[0] for result in analyses)
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
        normalized_language = normalize_track_language(language)
        if codec_id in ('A_PCM/INT/LIT', 'A_PCM/INT/BIG'):
            codec_family = 'pcm'
        elif codec_id in ('A_TRUEHD', 'A_MLP'):
            codec_family = 'truehd'
        elif mkv_codec_id_is_dts_family(codec_id):
            codec_family = 'dts'
        else:
            codec_family = codec_id or codec_name
        timeline_fingerprint = tuple(
            (
                round(extracted_run.timeline_start_seconds, 6),
                round(float(extracted_run.timeline_duration_seconds or 0.0), 6),
                fingerprint,
            )
            for extracted_run, (_maximum_volume, fingerprint) in zip(
                extracted_runs, analyses
            )
        )
        fingerprint_key = (codec_family, channel_count, timeline_fingerprint)
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
        audio_timeline_by_track: Optional[
            dict[int, tuple[tuple[float, float], ...]]
        ] = None,
        audio_timeline_duration_seconds: Optional[float] = None,
        detect_audio_gaps: bool = False,
        write_audio_gaps: bool = False,
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
    explicit_audio_timeline = dict(audio_timeline_by_track or {})
    sidecar_timeline_loaded = False
    if detect_audio_gaps and not explicit_audio_timeline:
        sidecar_timeline = load_audio_gap_sidecar(source_path, tracks)
        if sidecar_timeline is not None:
            explicit_audio_timeline = sidecar_timeline
            sidecar_timeline_loaded = True
    detect_source_audio_gaps = bool(
        detect_audio_gaps
        and not explicit_audio_timeline
        and not sidecar_timeline_loaded
    )
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
    replacement_by_track: dict[int, tuple[str, str, Optional[int]]] = {}
    keep_work_folder = False
    try:
        find_mkvtoolnix()
        ffmpeg = str(core_settings.FFMPEG_PATH or '').strip() or shutil.which('ffmpeg') or ''
        ffprobe = str(core_settings.FFPROBE_PATH or '').strip() or shutil.which('ffprobe') or ''
        mkvmerge = str(core_settings.MKV_MERGE_PATH or '').strip() or shutil.which('mkvmerge') or ''
        if not mkvmerge:
            raise FileNotFoundError(translate_text('mkvmerge not found'))
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
        extracted_audio_by_track: dict[int, tuple[_ExtractedAudioRun, ...]] = {}
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
                explicit_audio_timeline,
                ffprobe,
                {
                    track_id: duration
                    for track_id, (_profile, duration) in audio_probe_by_track.items()
                },
                detect_timeline_gaps=detect_source_audio_gaps,
            )
            if detect_source_audio_gaps:
                for track_id, extracted_runs in extracted_audio_by_track.items():
                    if all(
                            run.timeline_duration_seconds is not None
                            for run in extracted_runs
                    ):
                        explicit_audio_timeline[track_id] = tuple(
                            (
                                run.timeline_start_seconds,
                                float(run.timeline_duration_seconds),
                            )
                            for run in extracted_runs
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
            conversion_tracks.intersection_update(extracted_audio_by_track)
        else:
            kept_audio = list(selected_audio)
        for track in audio_tracks:
            track_id = int(track['id'])
            if track_id not in kept_audio or track_id not in conversion_tracks:
                continue
            target_codec = str(codec_by_track.get(track_id) or '').strip().lower()
            properties = track.get('properties') if isinstance(track.get('properties'), dict) else {}
            extracted_runs = extracted_audio_by_track[track_id]
            converted_paths: list[str] = []
            timeline_output = ''
            try:
                report_progress(
                    'Converting audio track {track} to {codec}',
                    track=track_id,
                    codec=target_codec.upper(),
                )
                try:
                    channel_count = int(properties.get('audio_channels') or 2)
                except (TypeError, ValueError):
                    channel_count = 2
                effective_bit_depth = wave64_bit_depth
                if target_codec == 'flac':
                    detected_depths = [
                        get_effective_bit_depth(
                            extracted_run.wave64_path,
                            wave64_bit_depth,
                        )
                        for extracted_run in extracted_runs
                    ]
                    effective_bit_depth = max(detected_depths)
                    if effective_bit_depth <= 16:
                        effective_bit_depth = 16
                    elif effective_bit_depth <= 24:
                        effective_bit_depth = 24
                    else:
                        effective_bit_depth = 32

                sparse_timeline = len(extracted_runs) > 1 and all(
                    run.timeline_duration_seconds is not None
                    for run in extracted_runs
                )
                timeline_output = os.path.join(
                    work_folder, f'track-{track_id}-timeline.mka'
                )
                if sparse_timeline and target_codec == 'flac':
                    replacement_path, initial_delay_ms = (
                        _encode_sparse_flac_timeline(
                            ffmpeg,
                            ffprobe,
                            extracted_runs,
                            timeline_output,
                            effective_bit_depth,
                            audio_encoding,
                        )
                    )
                else:
                    extension = {
                        'flac': '.flac',
                        'aac': '.m4a',
                        'opus': '.opus',
                    }[target_codec]
                    for run_index, extracted_run in enumerate(extracted_runs):
                        converted_path = os.path.join(
                            work_folder,
                            f'track-{track_id}-run-{run_index:03d}{extension}',
                        )
                        converted_paths.append(converted_path)
                        if not _encode_wave64_to_codec(
                                ffmpeg,
                                flac_encoder,
                                extracted_run.wave64_path,
                                converted_path,
                                target_codec,
                                channel_count,
                                wave64_bit_depth,
                                effective_bit_depth,
                                audio_encoding,
                        ):
                            raise RuntimeError(
                                translate_text(
                                    'Audio conversion failed for track {track}: {path}'
                                ).format(track=track_id, path=source_path)
                            )

                    if sparse_timeline:
                        replacement_path, initial_delay_ms = (
                            _mux_converted_audio_runs(
                                mkvmerge,
                                ffprobe,
                                track_id,
                                extracted_runs,
                                tuple(converted_paths),
                                timeline_output,
                            )
                        )
                    else:
                        duration_ok = (
                            converted_audio_runs_are_acceptable(
                                ffprobe,
                                extracted_runs,
                                tuple(converted_paths),
                                track_id,
                                source_path,
                                audio_encoding.duration_loss_fallback_threshold_seconds,
                                audio_probe_by_track[track_id][1],
                            )
                        )
                        if not duration_ok:
                            for converted_path in converted_paths:
                                if os.path.isfile(converted_path):
                                    os.remove(converted_path)
                            continue
                        replacement_path, initial_delay_ms = (
                            _mux_converted_audio_runs(
                                mkvmerge,
                                ffprobe,
                                track_id,
                                extracted_runs,
                                tuple(converted_paths),
                                timeline_output,
                            )
                        )

                if sparse_timeline and not _validate_sparse_audio_timeline(
                        ffmpeg,
                        ffprobe,
                        track_id,
                        extracted_runs,
                        replacement_path,
                        work_folder,
                        wave64_bit_depth,
                        source_path,
                        audio_encoding.duration_loss_fallback_threshold_seconds,
                ):
                    continue
                replacement_by_track[track_id] = (
                    replacement_path,
                    target_codec,
                    initial_delay_ms,
                )
            except TaskCancelled:
                raise
            except (OSError, RuntimeError, ValueError) as error:
                for converted_path in converted_paths:
                    if os.path.isfile(converted_path):
                        os.remove(converted_path)
                if timeline_output and os.path.isfile(timeline_output):
                    os.remove(timeline_output)
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
            if write_audio_gaps:
                duration = float(audio_timeline_duration_seconds or 0.0)
                if duration <= 0:
                    duration = max(
                        (
                            start + run_duration
                            for runs in explicit_audio_timeline.values()
                            for start, run_duration in runs
                        ),
                        default=0.0,
                    )
                write_audio_gap_sidecar(
                    output_path,
                    explicit_audio_timeline,
                    duration,
                    tracks,
                )
            return
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
            replacement_path, _target_codec, timeline_delay_ms = replacement
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
            if timeline_delay_ms is None:
                try:
                    delay_ms = int(round(
                        int(properties.get('minimum_timestamp') or 0) / 1_000_000
                    ))
                except Exception:
                    delay_ms = 0
            else:
                delay_ms = timeline_delay_ms
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
        output_audio_id_by_source: dict[int, int] = {}
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
                output_audio_id_by_source[track_id] = len(track_order)
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

        for output_track, expected_language in zip(output_tracks, expected_languages):
            if not expected_language:
                continue
            output_properties = output_track.get('properties') \
                if isinstance(output_track.get('properties'), dict) else {}
            actual_languages = {
                normalize_track_language(output_properties.get(property_name))
                for property_name in ('language', 'language_ietf')
                if output_properties.get(property_name)
            }
            if normalize_track_language(expected_language) not in actual_languages:
                raise RuntimeError(
                    translate_text('Final track language verification failed: {path}').format(
                        path=output_path
                    )
                )
        if write_audio_gaps:
            source_timeline_by_output_track: dict[
                int, tuple[tuple[float, float], ...]
            ] = {}
            for track_id, output_track_id in output_audio_id_by_source.items():
                if track_id in explicit_audio_timeline:
                    source_timeline_by_output_track[output_track_id] = tuple(
                        explicit_audio_timeline[track_id]
                    )
            duration = float(audio_timeline_duration_seconds or 0.0)
            if duration <= 0:
                duration = max(
                    (
                        start + run_duration
                        for runs in source_timeline_by_output_track.values()
                        for start, run_duration in runs
                    ),
                    default=0.0,
                )
            write_audio_gap_sidecar(
                temporary_output,
                source_timeline_by_output_track,
                duration,
                output_tracks,
            )
        os.replace(temporary_output, output_path)
        if write_audio_gaps:
            try:
                os.replace(audio_gap_sidecar_path(temporary_output), audio_gap_sidecar_path(output_path))
            except OSError:
                # Keep this task's media under its temporary name if metadata publication fails.
                os.replace(output_path, temporary_output)
                raise
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
    'convert_audio_stream',
    'converted_audio_runs_are_acceptable',
    'encode_fdkaac_from_ffmpeg',
    'audio_gap_sidecar_path',
    'is_immersive_audio_codec',
    'is_lossless_audio_codec',
    'mux_with_audio_conversion',
    'load_audio_gap_sidecar',
    'probe_audio_stream',
    'probe_audio_streams',
    'validate_audio_cleanup_tools',
    'validate_audio_conversion_tools',
    'write_audio_gap_sidecar',
]
