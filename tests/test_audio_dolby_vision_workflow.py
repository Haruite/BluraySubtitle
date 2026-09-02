"""Focused contracts for audio conversion and Dolby Vision processing."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.audio_conversion import (
    AudioEncodingSettings,
    AudioMuxFailure,
    _analyze_audio_track,
    _extract_selected_audio_tracks,
    convert_audio_stream_to_flac,
    mux_with_audio_conversion,
    validate_audio_cleanup_tools,
    validate_audio_conversion_tools,
)
from src.runtime.dolby_vision import (
    DolbyVisionEncodePlan,
    edit_dolby_vision_rpu_for_crop,
    inject_dolby_vision_rpu,
    mux_dolby_vision_layers,
    prepare_dolby_vision_encode,
    verify_dolby_vision_rpu,
)
from src.runtime.video_crop import VideoCropPlan
from src.runtime.services_split.encode_and_audio_tasks import (
    encode_dovi_preflight_mkv_paths,
    encode_dovi_preservation_supported,
)


def _track(
        track_id: int,
        track_type: str,
        codec_id: str,
        *,
        codec: str = '',
        language: str = 'und',
        channels: int = 2,
) -> dict[str, object]:
    track = {
        'id': track_id,
        'type': track_type,
        'codec': codec,
        'properties': {
            'codec_id': codec_id,
            'language': language,
            'default_track': False,
            'forced_track': False,
        },
    }
    if track_type == 'audio':
        track['properties']['audio_channels'] = channels
    return track


def _is_wave64_extraction(command: list[str]) -> bool:
    return bool(
        'w64' in command
        and any(str(argument).endswith('.w64') for argument in command)
    )


def _write_extracted_tracks(command: list[str], payload=b'audio') -> None:
    for index, argument in enumerate(command[:-1]):
        if argument != 'w64':
            continue
        extracted_path = command[index + 1]
        track_id = int(Path(extracted_path).stem.rsplit('-', 1)[-1])
        Path(extracted_path).write_bytes(
            payload(track_id) if callable(payload) else payload
        )


class AudioConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        analysis_patcher = patch(
            'src.runtime.audio_conversion._analyze_audio_track',
            side_effect=lambda _ffmpeg, _extracted, _source, track_id: (
                -20.0,
                f'track-{track_id}',
            ),
        )
        self.audio_analysis = analysis_patcher.start()
        self.addCleanup(analysis_patcher.stop)
        duration_patcher = patch(
            'src.runtime.audio_conversion.probe_audio_stream',
            return_value=('', 60.0),
        )
        batch_duration_patcher = patch(
            'src.runtime.audio_conversion.probe_audio_streams',
            return_value=[('', 60.0)] * 16,
        )
        self.audio_duration_probe = duration_patcher.start()
        self.batch_audio_duration_probe = batch_duration_patcher.start()
        self.addCleanup(duration_patcher.stop)
        self.addCleanup(batch_duration_patcher.stop)

    def test_lossy_audio_is_preserved_with_exact_tracks_and_languages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AC3', language='eng'),
                _track(2, 'audio', 'A_TRUEHD', codec='TrueHD Atmos', language='eng'),
                _track(3, 'subtitles', 'S_HDMV/PGS', language='eng'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AC3', language='jpn'),
                _track(2, 'subtitles', 'S_HDMV/PGS', language='zho'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command)
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=('3',),
                    audio_codec_choices=('opus',),
                    track_language_overrides=(('1', 'jpn'), ('3', 'zho')),
                )

            self.assertEqual(output.read_bytes(), b'muxed')
            self.assertEqual(len(commands), 2)
            mux_command = commands[-1]
            self.assertEqual(mux_command[mux_command.index('-a') + 1], '1')
            self.assertEqual(mux_command[mux_command.index('-s') + 1], '3')
            self.assertIn('0:0,0:1,0:3', mux_command)
            self.assertIn('1:jpn', mux_command)
            self.assertIn('3:zho', mux_command)

    def test_lossless_audio_is_converted_and_reinserted_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_audio = _track(1, 'audio', 'A_TRUEHD', codec='TrueHD', language='eng')
            source_audio['properties']['track_name'] = 'Main audio'
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                source_audio,
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_FLAC', codec='FLAC', language='jpn'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command, b'wave')
                elif command[0] == 'flac':
                    Path(command[command.index('-o') + 1]).write_bytes(b'larger-flac-output')
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', 'flac'),
                    patch('src.runtime.audio_conversion.os.cpu_count', return_value=6),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac',),
                    track_language_overrides=(('1', 'jpn'),),
                )

            self.assertEqual(output.read_bytes(), b'muxed')
            flac_command = next(command for command in commands if command[0] == 'flac')
            self.assertEqual(flac_command[flac_command.index('-j') + 1], '6')
            decode_command = next(command for command in commands if command[0] == 'ffmpeg')
            self.assertEqual(decode_command[decode_command.index('-c:a') + 1], 'pcm_s32le')
            self.assertNotIn('-hide_banner', decode_command)
            self.assertNotIn('-loglevel', decode_command)
            mux_command = commands[-1]
            self.assertIn('-A', mux_command)
            self.assertIn('0:0,1:0', mux_command)
            self.assertIn('0:jpn', mux_command)
            self.assertIn('0:Main audio', mux_command)

    def test_effective_16bit_wave64_is_encoded_as_16bit_flac(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_PCM/INT/LIT', codec='PCM'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_FLAC', codec='FLAC'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command)
                elif command[0] == 'ffmpeg':
                    Path(command[-1]).write_bytes(b'flac')
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch(
                        'src.runtime.audio_conversion._identify_tracks',
                        side_effect=[source_tracks, output_tracks],
                    ),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', 'flac'),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch(
                        'src.runtime.audio_conversion.get_effective_bit_depth',
                        return_value=16,
                    ) as detect_depth,
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac',),
                    wave64_bit_depth=24,
                )

            detect_depth.assert_called_once()
            flac_command = next(
                command
                for command in commands
                if command[0] == 'ffmpeg' and 'flac' in command
            )
            self.assertEqual(
                flac_command[flac_command.index('-sample_fmt') + 1],
                's16',
            )
            self.assertFalse(any(command[0] == 'flac' for command in commands))
            self.assertEqual(output.read_bytes(), b'muxed')

    def test_remux_mode_converts_only_lossless_audio_to_flac_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / 'source.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AC3', codec='AC-3', language='eng'),
                _track(2, 'audio', 'A_TRUEHD', codec='TrueHD', language='jpn'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AC3', codec='AC-3', language='eng'),
                _track(2, 'audio', 'A_FLAC', codec='FLAC', language='jpn'),
            ]
            commands = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command, b'wave')
                elif command[0] == 'flac':
                    Path(command[command.index('-o') + 1]).write_bytes(b'flac')
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', 'flac'),
                    patch('src.runtime.audio_conversion.os.cpu_count', return_value=6),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(source),
                    selected_audio_tracks=None,
                    selected_subtitle_tracks=None,
                    audio_codec_choices=(),
                    convert_all_lossless_to_flac=True,
                )

            self.assertEqual(source.read_bytes(), b'muxed')
            self.assertEqual(sum(_is_wave64_extraction(command) for command in commands), 1)
            mux_command = commands[-1]
            self.assertEqual(mux_command[mux_command.index('-a') + 1], '1')
            self.assertIn('0:0,0:1,1:0', mux_command)

    def test_in_place_remux_adds_selected_subtitle_when_audio_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            subtitle = root / 'episode.ass'
            source.write_bytes(b'source')
            subtitle.write_text('subtitle', encoding='utf-8')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AC3', codec='AC-3', language='eng'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AC3', codec='AC-3', language='eng'),
                _track(2, 'subtitles', 'S_TEXT/ASS', language='jpn'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command)
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(source),
                    selected_audio_tracks=None,
                    selected_subtitle_tracks=None,
                    audio_codec_choices=(),
                    clean_audio_tracks=False,
                    subtitle_file=str(subtitle),
                    subtitle_language='jpn',
                )

            self.assertEqual(source.read_bytes(), b'muxed')
            self.assertEqual([command[0] for command in commands], ['mkvmerge'])
            mux_command = commands[-1]
            self.assertIn(str(subtitle), mux_command)
            self.assertIn('0:jpn', mux_command)
            self.assertEqual(
                mux_command[mux_command.index('--track-order') + 1],
                '0:0,0:1,1:0',
            )

    def test_remux_dts_keeps_larger_flac_but_falls_back_on_duration_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_DTS', codec='DTS-HD Master Audio', language='eng'),
                _track(2, 'audio', 'A_DTS', codec='DTS-HD Master Audio', language='jpn'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_FLAC', codec='FLAC', language='eng'),
                _track(2, 'audio', 'A_DTS', codec='DTS-HD Master Audio', language='jpn'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(
                        command,
                        lambda track_id: b'dts-a' if track_id == 1 else b'dts',
                    )
                elif command[0] == 'flac':
                    converted = Path(command[command.index('-o') + 1])
                    converted.write_bytes(b'flac!' if 'track-1' in converted.name else b'larger-flac-output')
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', 'flac'),
                    patch('src.runtime.audio_conversion.os.cpu_count', return_value=4),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
                    patch(
                        'src.runtime.audio_conversion.probe_audio_streams',
                        return_value=[
                            ('DTS-HD MA', 60.0),
                            ('DTS-HD MA', 60.0),
                        ],
                    ),
                    patch(
                        'src.runtime.audio_conversion.probe_audio_stream',
                        side_effect=[
                            ('', 60.0),
                            ('', 58.9),
                        ],
                    ),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(source),
                    selected_audio_tracks=None,
                    selected_subtitle_tracks=(),
                    audio_codec_choices=(),
                    convert_all_lossless_to_flac=True,
                )

            self.assertEqual(source.read_bytes(), b'muxed')
            mux_command = commands[-1]
            self.assertEqual(mux_command[mux_command.index('-a') + 1], '2')
            self.assertEqual(
                mux_command[mux_command.index('--track-order') + 1],
                '0:0,1:0,0:2',
            )
            self.assertTrue(any('track-1.flac' in argument for argument in mux_command))
            self.assertFalse(any('track-2.flac' in argument for argument in mux_command))

    def test_silent_and_duplicate_audio_are_removed_without_reordering_kept_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AC3', codec='AC-3', language='eng'),
                _track(2, 'audio', 'A_AC3', codec='AC-3', language='eng'),
                _track(3, 'audio', 'A_AC3', codec='AC-3', language='jpn'),
                _track(4, 'audio', 'A_AC3', codec='AC-3', language='eng'),
                _track(5, 'audio', 'A_AC3', codec='AC-3', language='eng', channels=6),
                _track(6, 'audio', 'A_AC3', codec='AC-3', language='eng'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AC3', codec='AC-3', language='eng'),
                _track(2, 'audio', 'A_AC3', codec='AC-3', language='jpn'),
                _track(3, 'audio', 'A_AC3', codec='AC-3', language='eng', channels=6),
                _track(4, 'audio', 'A_AC3', codec='AC-3', language='eng'),
            ]
            self.audio_analysis.side_effect = [
                (-20.0, 'same-audio'),
                (-20.0, 'same-audio'),
                (-20.0, 'same-audio'),
                (float('-inf'), 'silence'),
                (-20.0, 'same-audio'),
                (-60.0, 'threshold-audio'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command)
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1', '2', '3', '4', '5', '6'),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac', 'flac', 'flac', 'flac', 'flac', 'flac'),
                )

            self.assertEqual(output.read_bytes(), b'muxed')
            mux_command = commands[-1]
            self.assertEqual(mux_command[mux_command.index('-a') + 1], '1,3,5,6')
            self.assertEqual(
                mux_command[mux_command.index('--track-order') + 1],
                '0:0,0:1,0:3,0:5,0:6',
            )

    def test_flac_encoder_failure_falls_back_to_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_PCM/INT/LIT', codec='PCM', language='jpn'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_FLAC', codec='FLAC', language='jpn'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command, b'wave')
                    return SimpleNamespace(returncode=0)
                if command[0] == 'flac':
                    Path(command[command.index('-o') + 1]).write_bytes(b'partial')
                    return SimpleNamespace(returncode=2)
                if command[0] == 'ffmpeg':
                    Path(command[-1]).write_bytes(b'ffmpeg-flac')
                    return SimpleNamespace(returncode=0)
                Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', 'flac'),
                    patch('src.runtime.audio_conversion.os.cpu_count', return_value=4),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac',),
                    audio_encoding=AudioEncodingSettings(
                        flac_compression_level=5,
                        ffmpeg_flac_compression_level=11,
                    ),
                    wave64_bit_depth=24,
                )

            self.assertEqual(output.read_bytes(), b'muxed')
            self.assertEqual(
                [command[0] for command in commands],
                ['ffmpeg', 'flac', 'ffmpeg', 'mkvmerge'],
            )
            self.assertEqual(commands[0][commands[0].index('-f') + 1], 'w64')
            self.assertIn('-5', commands[1])
            self.assertEqual(commands[1][commands[1].index('-j') + 1], '4')
            self.assertEqual(commands[2][commands[2].index('-c:a') + 1], 'flac')
            self.assertEqual(
                commands[2][commands[2].index('-compression_level') + 1],
                '11',
            )
            self.assertNotIn('-hide_banner', commands[2])
            self.assertNotIn('-loglevel', commands[2])

    def test_sp_flac_ffmpeg_fallback_uses_configured_levels_and_visible_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_wave = root / 'input.wav'
            output_flac = root / 'output.flac'
            input_wave.write_bytes(b'wave')
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if 'w64' in command:
                    Path(command[-1]).write_bytes(b'wave')
                elif command[0] == 'ffmpeg' and command[command.index('-c:a') + 1] == 'flac':
                    output_flac.write_bytes(b'flac')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', 'flac'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FFPROBE_PATH', 'ffprobe'),
                    patch(
                        'src.runtime.audio_conversion.os.cpu_count',
                        return_value=8,
                    ),
                    patch('src.runtime.audio_conversion.get_effective_bit_depth', return_value=24),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                succeeded = convert_audio_stream_to_flac(
                    str(input_wave),
                    '0:0',
                    str(output_flac),
                    audio_encoding=AudioEncodingSettings(
                        flac_compression_level=4,
                        ffmpeg_flac_compression_level=12,
                    ),
                )

            self.assertTrue(succeeded)
            self.assertEqual(len(commands), 3)
            self.assertEqual(commands[0][commands[0].index('-c:a') + 1], 'pcm_s24le')
            self.assertEqual(commands[1][0], 'flac')
            self.assertIn('-4', commands[1])
            self.assertEqual(commands[1][commands[1].index('-j') + 1], '8')
            self.assertEqual(commands[2][commands[2].index('-compression_level') + 1], '12')
            self.assertNotIn('-hide_banner', commands[2])
            self.assertNotIn('-loglevel', commands[2])

    def test_explicit_fdkaac_and_opus_bitrates_are_used(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_TRUEHD', codec='TrueHD', language='eng'),
                _track(2, 'audio', 'A_PCM/INT/LIT', codec='PCM', language='jpn'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_AAC', codec='AAC', language='eng'),
                _track(2, 'audio', 'A_OPUS', codec='Opus', language='jpn'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command)
                elif command[0] == 'ffmpeg':
                    Path(command[-1]).write_bytes(b'audio')
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            def encode_aac(
                    _ffmpeg,
                    _fdkaac,
                    _input_media,
                    _stream_selector,
                    output_path,
                    _rate_control,
            ):
                Path(output_path).write_bytes(b'aac')
                return True

            with (
                    patch(
                        'src.runtime.audio_conversion._identify_tracks',
                        side_effect=[source_tracks, output_tracks],
                    ),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch(
                        'src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH',
                        'mkvextract',
                    ),
                    patch(
                        'src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH',
                        'mkvmerge',
                    ),
                    patch(
                        'src.runtime.audio_conversion.core_settings.FFMPEG_PATH',
                        'ffmpeg',
                    ),
                    patch(
                        'src.runtime.audio_conversion.core_settings.FDK_AAC_PATH',
                        'fdkaac',
                    ),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
                    patch(
                        'src.runtime.audio_conversion.encode_fdkaac_from_ffmpeg',
                        side_effect=encode_aac,
                    ) as fdkaac_encoder,
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1', '2'),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('aac', 'opus'),
                    audio_encoding=AudioEncodingSettings(
                        fdkaac_bitrate_kbps=320,
                        opus_bitrate_kbps=192,
                    ),
                )

            opus_command = next(
                command
                for command in commands
                if command[0] == 'ffmpeg' and 'libopus' in command
            )
            self.assertEqual(
                fdkaac_encoder.call_args.args[-1],
                ['-b', '320000'],
            )
            self.assertEqual(
                opus_command[opus_command.index('-b:a') + 1],
                '192k',
            )
            self.assertEqual(output.read_bytes(), b'muxed')

    def test_sp_flac_rejects_partial_outputs_from_failed_encoders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_wave = root / 'input.wav'
            output_flac = root / 'output.flac'
            input_wave.write_bytes(b'wave')
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if 'w64' in command:
                    Path(command[-1]).write_bytes(b'wave')
                    return SimpleNamespace(returncode=0)
                output_flac.write_bytes(b'partial')
                return SimpleNamespace(returncode=2)

            with (
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', 'flac'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FFPROBE_PATH', 'ffprobe'),
                    patch('src.runtime.audio_conversion.get_effective_bit_depth', return_value=24),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                succeeded = convert_audio_stream_to_flac(
                    str(input_wave), '0:0', str(output_flac)
                )

            self.assertFalse(succeeded)
            self.assertEqual(
                [command[0] for command in commands],
                ['ffmpeg', 'flac', 'ffmpeg'],
            )
            self.assertFalse(output_flac.exists())

    def test_truehd_atmos_is_preserved_when_immersive_conversion_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_TRUEHD', codec='TrueHD Atmos', language='eng'),
            ]
            commands: list[list[str]] = []

            def run_mux(command, **_kwargs):
                commands.append(list(command))
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(list(command))
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, source_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_mux),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac',),
                    convert_immersive_audio_to_flac=False,
                )

            self.assertEqual(len(commands), 2)
            self.assertEqual(output.read_bytes(), b'muxed')
            self.assertEqual(commands[-1][commands[-1].index('-a') + 1], '1')

    def test_truehd_atmos_opt_in_uses_ffmpeg_and_wave64(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_TRUEHD', codec='TrueHD Atmos', language='eng'),
            ]
            output_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_FLAC', codec='FLAC', language='eng'),
            ]
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command, b'wave64')
                elif command[0] == 'flac':
                    Path(command[command.index('-o') + 1]).write_bytes(b'flac')
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', 'flac'),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac',),
                    convert_immersive_audio_to_flac=True,
                )

            self.assertEqual(output.read_bytes(), b'muxed')
            decode_command = next(command for command in commands if command[0] == 'ffmpeg')
            self.assertEqual(decode_command[decode_command.index('-f') + 1], 'w64')
            self.assertTrue(decode_command[-1].endswith('.w64'))

    def test_lossless_conversion_failure_keeps_the_original_track(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_TRUEHD', codec='TrueHD', language='eng'),
            ]

            def run_command(command, **_kwargs):
                command = list(command)
                if _is_wave64_extraction(command):
                    _write_extracted_tracks(command, b'wave64')
                    return SimpleNamespace(returncode=0)
                if command[0] == 'ffmpeg':
                    return SimpleNamespace(returncode=5)
                Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch(
                        'src.runtime.audio_conversion._identify_tracks',
                        side_effect=[source_tracks, source_tracks],
                    ),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac',),
                )

            self.assertEqual(output.read_bytes(), b'muxed')
            self.assertEqual(list(root.glob('_audio_convert_*')), [])

    def test_preflight_does_not_require_conversion_tools_for_lossy_audio(self) -> None:
        tracks = [_track(1, 'audio', 'A_AC3', language='eng')]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            ffmpeg = root / 'ffmpeg.exe'
            mkvextract = root / 'mkvextract.exe'
            ffmpeg.write_bytes(b'tool')
            mkvextract.write_bytes(b'tool')
            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', str(mkvextract)),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.FDK_AAC_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                validate_audio_conversion_tools('source.mkv', ('1',), ('aac',))

    def test_preflight_skips_immersive_conversion_tools_when_disabled(self) -> None:
        tracks = [_track(1, 'audio', 'A_TRUEHD', codec='TrueHD Atmos')]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            ffmpeg = root / 'ffmpeg.exe'
            mkvextract = root / 'mkvextract.exe'
            ffmpeg.write_bytes(b'tool')
            mkvextract.write_bytes(b'tool')
            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', str(mkvextract)),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.FDK_AAC_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                validate_audio_conversion_tools(
                    'source.mkv',
                    ('1',),
                    ('aac',),
                    convert_immersive_audio_to_flac=False,
                )

    def test_preflight_accepts_standalone_flac_with_cleanup_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            flac = root / 'flac.exe'
            mkvextract = root / 'mkvextract.exe'
            ffmpeg = root / 'ffmpeg.exe'
            ffprobe = root / 'ffprobe.exe'
            flac.write_bytes(b'tool')
            mkvextract.write_bytes(b'tool')
            ffmpeg.write_bytes(b'tool')
            ffprobe.write_bytes(b'tool')
            tracks = [_track(1, 'audio', 'A_PCM/INT/LIT', codec='PCM')]
            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', str(mkvextract)),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.FFPROBE_PATH', str(ffprobe)),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', str(flac)),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                validate_audio_conversion_tools('source.mkv', ('1',), ('flac',))

    def test_preflight_reports_a_missing_tool_for_an_actual_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            ffmpeg = root / 'ffmpeg.exe'
            mkvextract = root / 'mkvextract.exe'
            ffprobe = root / 'ffprobe.exe'
            ffmpeg.write_bytes(b'tool')
            mkvextract.write_bytes(b'tool')
            ffprobe.write_bytes(b'tool')
            tracks = [_track(1, 'audio', 'A_TRUEHD', codec='TrueHD')]
            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', str(mkvextract)),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.FFPROBE_PATH', str(ffprobe)),
                    patch('src.runtime.audio_conversion.core_settings.FDK_AAC_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                with self.assertRaisesRegex(FileNotFoundError, 'fdkaac'):
                    validate_audio_conversion_tools('source.mkv', ('1',), ('aac',))

    def test_encode_mux_failure_retains_nonempty_partial_container(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            encoded_video = root / 'encoded.hevc'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            encoded_video.write_bytes(b'hevc')
            source_tracks = [_track(0, 'video', 'V_MPEGH/ISO/HEVC')]

            def run_mux(command, **_kwargs):
                Path(command[command.index('-o') + 1]).write_bytes(b'partial-mkv')
                return SimpleNamespace(returncode=0)

            with (
                    patch(
                        'src.runtime.audio_conversion._identify_tracks',
                        side_effect=[source_tracks, RuntimeError('verification failed')],
                    ),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_mux),
            ):
                with self.assertRaisesRegex(
                        AudioMuxFailure,
                        'verification failed',
                ) as failure:
                    mux_with_audio_conversion(
                        str(source),
                        str(output),
                        selected_audio_tracks=(),
                        selected_subtitle_tracks=(),
                        audio_codec_choices=(),
                        encoded_video_file=str(encoded_video),
                        preserve_failure_artifacts=True,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(len(failure.exception.artifact_paths), 1)
            partial_output = Path(failure.exception.artifact_paths[0])
            self.assertEqual(partial_output.read_bytes(), b'partial-mkv')
            self.assertTrue(partial_output.parent.name.startswith('_audio_convert_'))


class AudioAnalysisTests(unittest.TestCase):
    def test_selected_audio_is_extracted_in_one_source_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            source.write_bytes(b'mkv')
            def extract_tracks(command, **_kwargs):
                _write_extracted_tracks(list(command))
                return SimpleNamespace(returncode=0)

            with patch(
                    'src.runtime.audio_conversion.run_command',
                    side_effect=extract_tracks,
            ) as run:
                extracted_audio = _extract_selected_audio_tracks(
                    'ffmpeg',
                    str(source),
                    str(root),
                    {1: 0, 2: 1, 3: 2},
                    (1, 3),
                    24,
                )

            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertEqual(command[:4], ['ffmpeg', '-y', '-i', str(source)])
            self.assertEqual(command.count('-map'), 2)
            self.assertEqual(command.count('w64'), 2)
            self.assertEqual(command.count('pcm_s24le'), 2)
            self.assertEqual(Path(extracted_audio[1]).suffix, '.w64')
            self.assertEqual(Path(extracted_audio[3]).suffix, '.w64')
            self.assertNotIn(2, extracted_audio)

    def test_failed_batch_extraction_retries_each_track_and_skips_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            source.write_bytes(b'mkv')
            commands: list[list[str]] = []

            def extract_tracks(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if command.count('-map') > 1:
                    _write_extracted_tracks(command, b'partial')
                    return SimpleNamespace(returncode=1)
                if command[command.index('-map') + 1] == '0:a:0':
                    _write_extracted_tracks(command)
                    return SimpleNamespace(returncode=0)
                return SimpleNamespace(returncode=1)

            with patch(
                    'src.runtime.audio_conversion.run_command',
                    side_effect=extract_tracks,
            ) as run:
                extracted_audio = _extract_selected_audio_tracks(
                    'ffmpeg',
                    str(source),
                    str(root),
                    {1: 0, 2: 1},
                    (1, 2),
                    24,
                )

            self.assertEqual(run.call_count, 3)
            self.assertEqual(set(extracted_audio), {1})
            self.assertFalse((root / 'track-2.w64').exists())
            self.assertTrue(all('pcm_s24le' in command for command in commands))

    def test_ffmpeg_analysis_reads_maximum_volume_and_decoded_fingerprint(self) -> None:
        result = SimpleNamespace(
            returncode=0,
            stdout='SHA256=0123456789abcdef\n',
            stderr='[Parsed_volumedetect] max_volume: -18.5 dB\n',
        )
        with patch('src.runtime.audio_conversion.run_command', return_value=result) as run:
            maximum_volume, fingerprint = _analyze_audio_track(
                'ffmpeg',
                'track-7.w64',
                'source.mkv',
                7,
            )

        self.assertEqual(maximum_volume, -18.5)
        self.assertEqual(fingerprint, '0123456789abcdef')
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('-i') + 1], 'track-7.w64')
        self.assertEqual(command[command.index('-map') + 1], '0:a:0')

    def test_cleanup_preflight_reports_missing_ffmpeg(self) -> None:
        with (
                patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', ''),
                patch('src.runtime.audio_conversion.shutil.which', return_value=''),
        ):
            with self.assertRaisesRegex(FileNotFoundError, 'ffmpeg'):
                validate_audio_cleanup_tools()

    def test_cleanup_preflight_does_not_require_mkvextract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            ffmpeg = Path(temporary_directory) / 'ffmpeg.exe'
            ffmpeg.write_bytes(b'tool')
            with (
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                validate_audio_cleanup_tools()


class DolbyVisionTests(unittest.TestCase):
    def test_preservation_support_is_limited_to_x265_hevc_at_ten_bit_or_deeper(self) -> None:
        self.assertTrue(encode_dovi_preservation_supported('x265', '10'))
        self.assertTrue(encode_dovi_preservation_supported('x265', '12'))
        self.assertFalse(encode_dovi_preservation_supported('x265', '8'))
        self.assertFalse(encode_dovi_preservation_supported('x264', '10'))
        self.assertFalse(encode_dovi_preservation_supported('svtav1', '10'))

    def test_preflight_allows_svt_av1_without_dolby_vision_preservation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / 'source.mkv'
            source.write_bytes(b'source')
            with patch(
                    'src.runtime.services_split.encode_and_audio_tasks.MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id',
                    return_value=0,
            ):
                error = encode_dovi_preflight_mkv_paths([str(source)], 'svtav1', '10')
            self.assertIsNone(error)

    def test_layer_mux_replaces_only_the_base_layer_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            base_layer = root / 'base.hevc'
            enhancement_layer = root / 'enhancement.hevc'
            base_layer.write_bytes(b'base')
            enhancement_layer.write_bytes(b'enhancement')
            commands: list[list[str]] = []

            def run_dovi(command, **_kwargs):
                commands.append(list(command))
                if 'mux' in command:
                    Path(command[command.index('-o') + 1]).write_bytes(b'combined')
                    return SimpleNamespace(returncode=0)
                if 'extract-rpu' in command:
                    Path(command[command.index('-o') + 1]).write_bytes(b'rpu')
                    return SimpleNamespace(returncode=0)
                return SimpleNamespace(
                    returncode=0,
                    stdout='Frames: 259\nProfile: 8\n',
                    stderr='',
                )

            with (
                    patch('src.runtime.dolby_vision.dolby_vision_tool_path', return_value='dovi_tool'),
                    patch('src.runtime.dolby_vision.run_command', side_effect=run_dovi),
            ):
                mux_dolby_vision_layers(str(base_layer), str(enhancement_layer))
                verify_dolby_vision_rpu(str(base_layer), 259, 8)
                with self.assertRaisesRegex(RuntimeError, 'profile'):
                    verify_dolby_vision_rpu(str(base_layer), 259, 7)

            self.assertEqual(base_layer.read_bytes(), b'combined')
            self.assertEqual(commands[0][1:4], ['-m', '2', 'mux'])
            self.assertIn('--discard', commands[0])
            self.assertIn('extract-rpu', commands[1])
            self.assertEqual(commands[2][1:3], ['info', '-s'])
            self.assertEqual(list(root.glob('*.dovi-temp.hevc')), [])

    def test_failed_rpu_injection_retains_nonempty_partial_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            encoded_stream = root / 'encoded.hevc'
            rpu_path = root / 'rpu.bin'
            encoded_stream.write_bytes(b'encoded')
            rpu_path.write_bytes(b'rpu')
            plan = DolbyVisionEncodePlan(
                str(encoded_stream),
                str(rpu_path),
                str(root),
            )

            def fail_injection(command, **_kwargs):
                Path(command[command.index('-o') + 1]).write_bytes(b'partial')
                return SimpleNamespace(returncode=1)

            with (
                    patch('src.runtime.dolby_vision.dolby_vision_tool_path', return_value='dovi_tool'),
                    patch('src.runtime.dolby_vision.run_command', side_effect=fail_injection),
            ):
                with self.assertRaisesRegex(RuntimeError, 'injected HEVC output'):
                    inject_dolby_vision_rpu(str(encoded_stream), plan)

            self.assertEqual(encoded_stream.read_bytes(), b'encoded')
            self.assertEqual(
                Path(str(encoded_stream) + '.dovi.hevc').read_bytes(),
                b'partial',
            )

    def test_crop_edit_subtracts_physical_margins_from_every_l5_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_rpu = root / 'source-rpu.bin'
            output_rpu = root / 'cropped-rpu.bin'
            source_rpu.write_bytes(b'rpu')
            commands: list[list[str]] = []
            captured_editor_config: dict = {}

            def run_tool(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if 'export' in command:
                    level5_path = Path(
                        command[command.index('-d') + 1].split('=', 1)[1]
                    )
                    level5_path.write_text(json.dumps({
                        'active_area': {
                            'presets': [
                                {
                                    'id': 0,
                                    'left': 20,
                                    'right': 24,
                                    'top': 140,
                                    'bottom': 142,
                                },
                                {
                                    'id': 1,
                                    'left': 0,
                                    'right': 0,
                                    'top': 200,
                                    'bottom': 200,
                                },
                            ],
                            'edits': {'all': 0, '100-199': 1},
                        },
                    }), encoding='utf-8')
                    return SimpleNamespace(returncode=0, stdout='', stderr='')
                if 'editor' in command:
                    editor_path = Path(command[command.index('-j') + 1])
                    captured_editor_config.update(json.loads(
                        editor_path.read_text(encoding='utf-8')
                    ))
                    Path(command[command.index('-o') + 1]).write_bytes(b'edited')
                    return SimpleNamespace(returncode=0, stdout='', stderr='')
                return SimpleNamespace(
                    returncode=0,
                    stdout='Frames: 1000\nProfile: 8\n',
                    stderr='',
                )

            crop_plan = VideoCropPlan(
                1920,
                1080,
                7200.0,
                24,
                (),
                left=10,
                right=12,
                top=100,
                bottom=100,
            )
            with (
                    patch(
                        'src.runtime.dolby_vision.dolby_vision_tool_path',
                        return_value='dovi_tool',
                    ),
                    patch(
                        'src.runtime.dolby_vision.run_command',
                        side_effect=run_tool,
                    ),
            ):
                edit_dolby_vision_rpu_for_crop(
                    str(source_rpu),
                    str(output_rpu),
                    crop_plan,
                    str(root),
                )

            active_area = captured_editor_config['active_area']
            self.assertEqual(active_area['edits'], {'all': 0, '100-199': 1})
            self.assertEqual(active_area['presets'][0], {
                'id': 0,
                'left': 10,
                'right': 12,
                'top': 40,
                'bottom': 42,
            })
            self.assertEqual(active_area['presets'][1], {
                'id': 1,
                'left': 0,
                'right': 0,
                'top': 100,
                'bottom': 100,
            })
            self.assertEqual(commands[0][1:3], ['export', '-i'])
            self.assertIn('editor', commands[1])
            self.assertEqual(commands[2][1:3], ['info', '-s'])
            self.assertEqual(output_rpu.read_bytes(), b'edited')

    def test_preparation_uses_profile_81_mode_and_task_owned_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            source.write_bytes(b'source')
            dovi_commands: list[list[str]] = []

            def run_tool(command, **_kwargs):
                if 'tracks' in command:
                    Path(command[-1].split(':', 1)[1]).write_bytes(b'hevc')
                else:
                    dovi_commands.append(list(command))
                    if 'demux' in command:
                        Path(command[command.index('-b') + 1]).write_bytes(b'base')
                    else:
                        Path(command[command.index('-o') + 1]).write_bytes(b'rpu')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.dolby_vision.dolby_vision_tool_path', return_value='dovi_tool'),
                    patch('src.runtime.dolby_vision.find_mkvtoolnix'),
                    patch('src.runtime.dolby_vision.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.dolby_vision.run_command', side_effect=run_tool),
            ):
                first_plan = prepare_dolby_vision_encode(str(source), 0, str(root))
                second_plan = prepare_dolby_vision_encode(str(source), 0, str(root))

            self.assertNotEqual(first_plan.work_folder, second_plan.work_folder)
            self.assertEqual(dovi_commands[0][1:4], ['-m', '2', 'demux'])
            self.assertEqual(dovi_commands[1][1:4], ['-m', '2', 'extract-rpu'])
            first_plan.cleanup()
            second_plan.cleanup()
            self.assertFalse(os.path.exists(first_plan.work_folder))
            self.assertFalse(os.path.exists(second_plan.work_folder))


if __name__ == '__main__':
    unittest.main()
