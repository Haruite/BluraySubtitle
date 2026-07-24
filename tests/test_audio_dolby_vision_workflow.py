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
    mux_with_audio_conversion,
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
) -> dict[str, object]:
    return {
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


class AudioConversionTests(unittest.TestCase):
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
                commands.append(list(command))
                destination = Path(command[command.index('-o') + 1])
                destination.write_bytes(b'muxed')
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
            self.assertEqual(len(commands), 1)
            mux_command = commands[0]
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
                    Path(command[-1]).write_bytes(b'flac')
                elif 'tracks' in command:
                    Path(command[-1].split(':', 1)[1]).write_bytes(b'truehd')
                else:
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', side_effect=[source_tracks, output_tracks]),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_MERGE_PATH', 'mkvmerge'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.audio_conversion.core_settings.TRUEHDD_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
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
            mux_command = commands[-1]
            self.assertIn('-A', mux_command)
            self.assertIn('0:0,1:0', mux_command)
            self.assertIn('0:jpn', mux_command)
            self.assertIn('0:Main audio', mux_command)
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

            self.assertEqual(len(commands), 1)
            self.assertEqual(output.read_bytes(), b'muxed')
            self.assertEqual(commands[0][commands[0].index('-a') + 1], '1')

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
                    Path(command[-1].split(':', 1)[1]).write_bytes(b'truehd')
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
                extracted_path = Path(command[-1].split(':', 1)[1])
                extracted_path.write_bytes(b'truehd')
                return SimpleNamespace(returncode=0)

            with (
                    patch('src.runtime.audio_conversion._identify_tracks', return_value=source_tracks),
                    patch('src.runtime.audio_conversion.find_mkvtoolnix'),
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', 'mkvextract'),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', 'ffmpeg'),
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
        with (
                patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', ''),
                patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', ''),
                patch('src.runtime.audio_conversion.core_settings.FDK_AAC_PATH', ''),
                patch('src.runtime.audio_conversion.shutil.which', return_value=''),
        ):
            validate_audio_conversion_tools('source.mkv', ('1',), ('aac',))

    def test_preflight_does_not_require_conversion_tools_when_atmos_is_preserved(self) -> None:
        tracks = [_track(1, 'audio', 'A_TRUEHD', codec='TrueHD Atmos')]
        with (
                patch('src.runtime.audio_conversion._identify_tracks', return_value=tracks),
                patch('src.runtime.audio_conversion._truehdd_path', return_value=''),
                patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', ''),
                patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', ''),
                patch('src.runtime.audio_conversion.core_settings.FDK_AAC_PATH', ''),
                patch('src.runtime.audio_conversion.shutil.which', return_value=''),
        ):
            validate_audio_conversion_tools('source.mkv', ('1',), ('aac',))

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
                    patch('src.runtime.audio_conversion.core_settings.MKV_EXTRACT_PATH', str(mkvextract)),
                    patch('src.runtime.audio_conversion.core_settings.FFMPEG_PATH', str(ffmpeg)),
                    patch('src.runtime.audio_conversion.core_settings.FDK_AAC_PATH', ''),
                    patch('src.runtime.audio_conversion.shutil.which', return_value=''),
            ):
                with self.assertRaisesRegex(FileNotFoundError, 'fdkaac'):
                    validate_audio_conversion_tools('source.mkv', ('1',), ('aac',))

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
