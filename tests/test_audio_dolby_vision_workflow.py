"""Focused contracts for audio conversion and Dolby Vision processing."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.audio_conversion import (
    AudioMuxFailure,
    _ExtractedAudioRun,
    _extract_selected_audio_tracks,
    _mux_converted_audio_runs,
    _selected_audio_after_cleanup,
    convert_audio_stream,
    converted_audio_runs_are_acceptable,
    audio_gap_sidecar_path,
    load_audio_gap_sidecar,
    mux_with_audio_conversion,
    write_audio_gap_sidecar,
)
from src.runtime.dolby_vision import (
    DolbyVisionEncodePlan,
    edit_dolby_vision_rpu_for_crop,
    inject_dolby_vision_rpu,
    mux_dolby_vision_layers,
    verify_dolby_vision_rpu,
)
from src.runtime.video_crop import VideoCropPlan


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
        track_match = re.search(r'track-(\d+)', Path(extracted_path).stem)
        if not track_match:
            continue
        track_id = int(track_match.group(1))
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
        bit_depth_patcher = patch(
            'src.runtime.audio_conversion.get_effective_bit_depth',
            side_effect=lambda _path, fallback_depth: fallback_depth,
        )
        self.bit_depth_probe = bit_depth_patcher.start()
        self.addCleanup(bit_depth_patcher.stop)

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
                            ('', 60.0),
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
            self.assertTrue(any('track-1-run-000.flac' in argument for argument in mux_command))
            self.assertFalse(any('track-2-run-000.flac' in argument for argument in mux_command))

    def test_silent_and_duplicate_audio_are_removed_without_reordering_kept_tracks(self) -> None:
        tracks = [
            _track(1, 'audio', 'A_AC3', language='eng'),
            _track(2, 'audio', 'A_AC3', language='eng'),
            _track(3, 'audio', 'A_AC3', language='jpn'),
            _track(4, 'audio', 'A_AC3', language='eng'),
            _track(5, 'audio', 'A_AC3', language='eng', channels=6),
            _track(6, 'audio', 'A_AC3', language='eng'),
        ]
        self.audio_analysis.side_effect = [
            (-20.0, 'same-pcm'), (-20.0, 'same-pcm'), (-20.0, 'same-pcm'),
            (float('-inf'), 'silence'), (-20.0, 'same-pcm'), (-60.0, 'quiet-pcm'),
        ]
        extracted = {track['id']: (
            _ExtractedAudioRun(0.0, 60.0, f"{track['id']}.w64"),
        ) for track in tracks}
        kept = _selected_audio_after_cleanup(
            'ffmpeg', 'source.mkv', tracks, (1, 2, 3, 4, 5, 6), {}, extracted,
        )
        self.assertEqual(kept, [1, 3, 5, 6])

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
                succeeded = convert_audio_stream(
                    str(input_wave), '0:0', str(output_flac), target_codec='flac'
                )

            self.assertFalse(succeeded)
            self.assertEqual(
                [command[0] for command in commands],
                ['ffmpeg', 'flac', 'ffmpeg'],
            )
            self.assertFalse(output_flac.exists())

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
    def test_audio_gap_sidecar_round_trip_and_continuous_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / 'source.mkv'
            source.write_bytes(b'matroska')
            tracks = [
                _track(1, 'audio', 'A_TRUEHD'),
                _track(2, 'audio', 'A_AC3'),
            ]
            tracks[0]['properties']['uid'] = 101
            tracks[1]['properties']['uid'] = 102

            write_audio_gap_sidecar(
                str(source),
                {1: ((0.0, 4.0), (6.0, 4.0)), 2: ((0.0, 10.0),)},
                10.0,
                tracks,
            )

            sidecar = Path(audio_gap_sidecar_path(str(source)))
            self.assertTrue(sidecar.is_file())
            payload = json.loads(sidecar.read_text(encoding='utf-8'))
            self.assertEqual(payload['tracks'], [
                {'track_id': 1, 'track_uid': '101', 'gaps': [[4.0, 6.0]]},
            ])
            self.assertEqual(
                load_audio_gap_sidecar(str(source), tracks),
                {1: ((0.0, 4.0), (6.0, 4.0))},
            )

            write_audio_gap_sidecar(
                str(source), {1: ((0.0, 10.0),)}, 10.0, tracks
            )
            self.assertTrue(sidecar.is_file())
            payload = json.loads(sidecar.read_text(encoding='utf-8'))
            self.assertEqual(payload['tracks'], [])
            self.assertEqual(load_audio_gap_sidecar(str(source), tracks), {})
            sidecar.unlink()
            self.assertIsNone(load_audio_gap_sidecar(str(source), tracks))

    def test_duration_fallback_uses_largest_run_loss_instead_of_sum(self) -> None:
        extracted_runs = (
            _ExtractedAudioRun(0.0, 10.0, 'run-0.w64'),
            _ExtractedAudioRun(12.0, 10.0, 'run-1.w64'),
        )
        with patch(
                'src.runtime.audio_conversion.probe_audio_stream',
                side_effect=[
                    ('', 9.4),
                    ('', 9.4),
                ],
        ):
            accepted = converted_audio_runs_are_acceptable(
                'ffprobe',
                extracted_runs,
                ('run-0.opus', 'run-1.opus'),
                1,
                'source.mkv',
                1.0,
            )

        self.assertTrue(accepted)

    def test_duration_fallback_includes_loss_during_source_decode(self) -> None:
        extracted_runs = (
            _ExtractedAudioRun(0.0, None, 'run-0.w64'),
        )
        with patch(
                'src.runtime.audio_conversion.probe_audio_stream',
                return_value=('', 7.5),
        ) as probe:
            accepted = converted_audio_runs_are_acceptable(
                'ffprobe',
                extracted_runs,
                ('run-0.flac',),
                1,
                'source.mkv',
                1.0,
                10.0,
            )

        self.assertFalse(accepted)
        probe.assert_called_once_with('ffprobe', 'run-0.flac')

    def test_sparse_converted_runs_restore_leading_and_middle_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            converted_paths = (root / 'run-0.opus', root / 'run-1.opus')
            for path in converted_paths:
                path.write_bytes(b'opus')
            output = root / 'timeline.mka'
            extracted_runs = (
                _ExtractedAudioRun(3.0, 10.0, 'run-0.w64'),
                _ExtractedAudioRun(15.0, 8.0, 'run-1.w64'),
            )

            def mux_runs(command, **_kwargs):
                Path(command[command.index('-o') + 1]).write_bytes(b'mka')
                return SimpleNamespace(returncode=0)

            with (
                    patch(
                        'src.runtime.audio_conversion.mkvtoolnix_ui_language_arg',
                        return_value='',
                    ),
                    patch(
                        'src.runtime.audio_conversion.run_command',
                        side_effect=mux_runs,
                    ) as run,
                    patch(
                        'src.runtime.audio_conversion._probe_audio_packet_end',
                        side_effect=(9.9, 8.0),
                    ),
            ):
                replacement, initial_delay_ms = _mux_converted_audio_runs(
                    'mkvmerge',
                    'ffprobe',
                    1,
                    extracted_runs,
                    tuple(str(path) for path in converted_paths),
                    str(output),
                )

            command = run.call_args_list[-1].args[0]
            self.assertEqual(replacement, str(output))
            self.assertEqual(initial_delay_ms, 3000)
            self.assertEqual(
                command[command.index('--append-to') + 1],
                '1:0:0:0',
            )
            self.assertIn('0:2100', command)

    def test_duplicate_fingerprint_includes_sparse_gap_positions(self) -> None:
        audio_tracks = [
            _track(1, 'audio', 'A_AC3', language='eng'),
            _track(2, 'audio', 'A_AC3', language='eng'),
        ]
        extracted = {
            1: (
                _ExtractedAudioRun(0.0, 10.0, '1-0.w64'),
                _ExtractedAudioRun(12.0, 8.0, '1-1.w64'),
            ),
            2: (
                _ExtractedAudioRun(0.0, 10.0, '2-0.w64'),
                _ExtractedAudioRun(13.0, 8.0, '2-1.w64'),
            ),
        }
        with patch(
                'src.runtime.audio_conversion._analyze_audio_track',
                return_value=(-20.0, 'same-pcm'),
        ):
            kept = _selected_audio_after_cleanup(
                'ffmpeg',
                'source.mkv',
                audio_tracks,
                (1, 2),
                {},
                extracted,
            )

        self.assertEqual(kept, [1, 2])

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

            self.assertEqual(set(extracted_audio), {1})
            self.assertFalse((root / 'track-2.w64').exists())


class DolbyVisionTests(unittest.TestCase):
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
            self.assertEqual(output_rpu.read_bytes(), b'edited')


if __name__ == '__main__':
    unittest.main()
