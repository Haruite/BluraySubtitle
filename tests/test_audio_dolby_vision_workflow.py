"""Focused contracts for audio conversion and Dolby Vision processing."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.services import BluraySubtitle as _BluraySubtitle
from src.runtime.audio_conversion import (
    _analyze_audio_track,
    _extract_selected_audio_tracks,
    mux_with_audio_conversion,
    validate_audio_cleanup_tools,
    validate_audio_conversion_tools,
)
from src.runtime.dolby_vision import (
    mux_dolby_vision_layers,
    prepare_dolby_vision_encode,
)
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


def _write_extracted_tracks(command: list[str], payload=b'audio') -> None:
    for track_specification in command[command.index('tracks') + 2:]:
        track_id, extracted_path = track_specification.split(':', 1)
        Path(extracted_path).write_bytes(payload(int(track_id)) if callable(payload) else payload)


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
                if 'tracks' in command:
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
                if command[0] == 'ffmpeg':
                    Path(command[-1]).write_bytes(b'wave')
                elif command[0] == 'flac':
                    Path(command[command.index('-o') + 1]).write_bytes(b'larger-flac-output')
                elif 'tracks' in command:
                    _write_extracted_tracks(command, b'truehd')
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
                    patch('src.runtime.audio_conversion.core_settings.FLAC_THREADS', 6),
                    patch('src.runtime.audio_conversion.core_settings.TRUEHDD_PATH', ''),
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
            self.assertEqual(decode_command[decode_command.index('-c:a') + 1], 'pcm_s24le')
            self.assertNotIn('-hide_banner', decode_command)
            self.assertNotIn('-loglevel', decode_command)
            mux_command = commands[-1]
            self.assertIn('-A', mux_command)
            self.assertIn('0:0,1:0', mux_command)
            self.assertIn('0:jpn', mux_command)
            self.assertIn('0:Main audio', mux_command)

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
                if command[0] == 'ffmpeg':
                    Path(command[-1]).write_bytes(b'wave')
                elif command[0] == 'flac':
                    Path(command[command.index('-o') + 1]).write_bytes(b'flac')
                elif 'tracks' in command:
                    _write_extracted_tracks(command, b'truehd')
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
                    patch('src.runtime.audio_conversion.core_settings.FLAC_THREADS', 6),
                    patch('src.runtime.audio_conversion.core_settings.TRUEHDD_PATH', ''),
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
            self.assertEqual(sum('tracks' in command for command in commands), 1)
            mux_command = commands[-1]
            self.assertEqual(mux_command[mux_command.index('-a') + 1], '1')
            self.assertIn('0:0,0:1,1:0', mux_command)

    def test_remux_dts_uses_flac_only_when_the_converted_track_is_not_larger(self) -> None:
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
                if 'tracks' in command:
                    _write_extracted_tracks(
                        command,
                        lambda track_id: b'dts-a' if track_id == 1 else b'dts',
                    )
                elif command[0] == 'ffmpeg':
                    Path(command[-1]).write_bytes(b'wave')
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
                    patch('src.runtime.audio_conversion.core_settings.FLAC_THREADS', 4),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
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
                if 'tracks' in command:
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
                if 'tracks' in command:
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
                    patch('src.runtime.audio_conversion.core_settings.FLAC_THREADS', 4),
                    patch('src.runtime.audio_conversion.shutil.which', return_value='flac'),
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
            self.assertEqual([command[0] for command in commands], ['mkvextract', 'flac', 'ffmpeg', 'mkvmerge'])
            self.assertEqual(commands[1][commands[1].index('-j') + 1], '4')
            self.assertEqual(commands[2][commands[2].index('-c:a') + 1], 'flac')
            self.assertEqual(commands[2][commands[2].index('-compression_level') + 1], '8')
            self.assertNotIn('-hide_banner', commands[2])
            self.assertNotIn('-loglevel', commands[2])

    def test_sp_flac_ffmpeg_fallback_uses_level_8_and_visible_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_wave = root / 'input.wav'
            output_flac = root / 'output.flac'
            input_wave.write_bytes(b'wave')
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if command[0] == 'ffmpeg' and command[command.index('-c:a') + 1] == 'flac':
                    output_flac.write_bytes(b'flac')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.services_split.media_info_and_track_mapping.FLAC_PATH', 'flac'),
                    patch('src.runtime.services_split.media_info_and_track_mapping.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.services_split.media_info_and_track_mapping.get_effective_bit_depth', return_value=24),
                    patch('src.runtime.services_split.media_info_and_track_mapping.run_command', side_effect=run_command),
                    patch.object(_BluraySubtitle, '_is_silent_audio_file', return_value=(False, -20.0)),
            ):
                succeeded = _BluraySubtitle._compress_audio_stream_to_flac(
                    str(input_wave), '0', str(output_flac)
                )

            self.assertTrue(succeeded)
            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0][0], 'flac')
            self.assertEqual(commands[1][commands[1].index('-compression_level') + 1], '8')
            self.assertNotIn('-hide_banner', commands[1])
            self.assertNotIn('-loglevel', commands[1])

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
                output_flac.write_bytes(b'partial')
                return SimpleNamespace(returncode=2)

            with (
                    patch('src.runtime.services_split.media_info_and_track_mapping.FLAC_PATH', 'flac'),
                    patch('src.runtime.services_split.media_info_and_track_mapping.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.services_split.media_info_and_track_mapping.get_effective_bit_depth', return_value=24),
                    patch('src.runtime.services_split.media_info_and_track_mapping.run_command', side_effect=run_command),
                    patch.object(_BluraySubtitle, '_is_silent_audio_file', return_value=(False, -20.0)),
            ):
                succeeded = _BluraySubtitle._compress_audio_stream_to_flac(
                    str(input_wave), '0', str(output_flac)
                )

            self.assertFalse(succeeded)
            self.assertEqual([command[0] for command in commands], ['flac', 'ffmpeg'])
            self.assertFalse(output_flac.exists())

    def test_truehd_atmos_is_preserved_when_truehdd_is_unavailable(self) -> None:
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
                if 'tracks' in command:
                    _write_extracted_tracks(list(command))
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, source_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion._truehdd_path', return_value=''),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_mux),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac',),
                )

            self.assertEqual(len(commands), 2)
            self.assertEqual(output.read_bytes(), b'muxed')
            self.assertEqual(commands[-1][commands[-1].index('-a') + 1], '1')

    def test_truehd_atmos_is_preserved_when_truehdd_decode_fails(self) -> None:
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

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if command[0] == 'truehdd':
                    return SimpleNamespace(returncode=3)
                if 'tracks' in command:
                    _write_extracted_tracks(command, b'truehd')
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, source_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion._truehdd_path', return_value='truehdd'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=run_command),
            ):
                mux_with_audio_conversion(
                    str(source),
                    str(output),
                    selected_audio_tracks=('1',),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=('flac',),
                )

            self.assertEqual(sum(command[0] == 'truehdd' for command in commands), 1)
            self.assertEqual(output.read_bytes(), b'muxed')
            self.assertEqual(commands[-1][commands[-1].index('-a') + 1], '1')

    def test_lossless_conversion_failure_is_explicit_and_leaves_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            output = root / 'output.mkv'
            source.write_bytes(b'source')
            source_tracks = [
                _track(0, 'video', 'V_MPEGH/ISO/HEVC'),
                _track(1, 'audio', 'A_TRUEHD', codec='TrueHD', language='eng'),
            ]

            def extract_track(command, **_kwargs):
                if 'tracks' not in command:
                    return SimpleNamespace(returncode=5)
                _write_extracted_tracks(list(command), b'truehd')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=source_tracks),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', ''),
                    patch('src.runtime.audio_conversion.core_settings.TRUEHDD_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
                    patch('src.runtime.audio_conversion.run_command', side_effect=extract_track),
            ):
                with self.assertRaisesRegex(RuntimeError, 'Audio conversion failed'):
                    mux_with_audio_conversion(
                        str(source),
                        str(output),
                        selected_audio_tracks=('1',),
                        selected_subtitle_tracks=(),
                        audio_codec_choices=('flac',),
                    )

            self.assertFalse(output.exists())
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

    def test_preflight_does_not_require_conversion_tools_when_atmos_is_preserved(self) -> None:
        tracks = [_track(1, 'audio', 'A_TRUEHD', codec='TrueHD Atmos')]
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            ffmpeg = root / 'ffmpeg.exe'
            mkvextract = root / 'mkvextract.exe'
            ffmpeg.write_bytes(b'tool')
            mkvextract.write_bytes(b'tool')
            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                    patch('src.runtime.audio_conversion._truehdd_path', return_value=''),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', str(mkvextract)),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.FDK_AAC_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                validate_audio_conversion_tools('source.mkv', ('1',), ('aac',))

    def test_preflight_accepts_standalone_flac_with_cleanup_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            flac = root / 'flac.exe'
            mkvextract = root / 'mkvextract.exe'
            ffmpeg = root / 'ffmpeg.exe'
            flac.write_bytes(b'tool')
            mkvextract.write_bytes(b'tool')
            ffmpeg.write_bytes(b'tool')
            tracks = [_track(1, 'audio', 'A_PCM/INT/LIT', codec='PCM')]
            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', str(mkvextract)),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.FLAC_PATH', str(flac)),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                validate_audio_conversion_tools('source.mkv', ('1',), ('flac',))

    def test_preflight_reports_a_missing_tool_for_an_actual_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            ffmpeg = root / 'ffmpeg.exe'
            mkvextract = root / 'mkvextract.exe'
            ffmpeg.write_bytes(b'tool')
            mkvextract.write_bytes(b'tool')
            tracks = [_track(1, 'audio', 'A_TRUEHD', codec='TrueHD')]
            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', str(mkvextract)),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.FDK_AAC_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                with self.assertRaisesRegex(FileNotFoundError, 'fdkaac'):
                    validate_audio_conversion_tools('source.mkv', ('1',), ('aac',))


class AudioAnalysisTests(unittest.TestCase):
    def test_selected_audio_is_extracted_in_one_source_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / 'source.mkv'
            source.write_bytes(b'mkv')
            audio_tracks = [
                _track(1, 'audio', 'A_AC3'),
                _track(2, 'audio', 'A_FLAC'),
                _track(3, 'audio', 'A_DTS'),
            ]

            def extract_tracks(command, **_kwargs):
                _write_extracted_tracks(list(command))
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion.mkvtoolnix_ui_language_arg', return_value='--ui-language en'),
                    patch('src.runtime.audio_conversion.run_command', side_effect=extract_tracks) as run,
            ):
                extracted_audio = _extract_selected_audio_tracks(
                    'mkvextract',
                    str(source),
                    str(root),
                    audio_tracks,
                    (1, 3),
                )

            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ['mkvextract', '--ui-language', 'en'])
            self.assertEqual(command[3:5], ['tracks', str(source)])
            self.assertEqual(len(command[5:]), 2)
            self.assertEqual(Path(extracted_audio[1]).suffix, '.ac3')
            self.assertEqual(Path(extracted_audio[3]).suffix, '.dts')
            self.assertNotIn(2, extracted_audio)

    def test_ffmpeg_analysis_reads_maximum_volume_and_decoded_fingerprint(self) -> None:
        result = SimpleNamespace(
            returncode=0,
            stdout='SHA256=0123456789abcdef\n',
            stderr='[Parsed_volumedetect] max_volume: -18.5 dB\n',
        )
        with patch('src.runtime.audio_conversion.run_command', return_value=result) as run:
            maximum_volume, fingerprint = _analyze_audio_track(
                'ffmpeg',
                'track-7.dts',
                'source.mkv',
                7,
            )

        self.assertEqual(maximum_volume, -18.5)
        self.assertEqual(fingerprint, '0123456789abcdef')
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('-i') + 1], 'track-7.dts')
        self.assertEqual(command[command.index('-map') + 1], '0:a:0')

    def test_cleanup_preflight_reports_missing_ffmpeg(self) -> None:
        with (
                patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', ''),
                patch('src.runtime.audio_conversion.shutil.which', return_value=''),
        ):
            with self.assertRaisesRegex(FileNotFoundError, 'ffmpeg'):
                validate_audio_cleanup_tools()

    def test_cleanup_preflight_reports_missing_mkvextract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            ffmpeg = Path(temporary_directory) / 'ffmpeg.exe'
            ffmpeg.write_bytes(b'tool')
            with (
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                with self.assertRaisesRegex(FileNotFoundError, 'mkvextract'):
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
                Path(command[command.index('-o') + 1]).write_bytes(b'combined')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.dolby_vision.dolby_vision_tool_path', return_value='dovi_tool'),
                    patch('src.runtime.dolby_vision.run_command', side_effect=run_dovi),
            ):
                mux_dolby_vision_layers(str(base_layer), str(enhancement_layer))

            self.assertEqual(base_layer.read_bytes(), b'combined')
            self.assertEqual(commands[0][1:4], ['-m', '2', 'mux'])
            self.assertIn('--discard', commands[0])
            self.assertEqual(list(root.glob('*.dovi-temp.hevc')), [])
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
