"""Focused tests for automatic discovery of the actual per-row Encode source."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.encode_source import (
    ActualEncodeSource,
    extract_hdr10plus_metadata,
    inject_hdr10plus_metadata,
    probe_actual_encode_source,
    probe_vapoursynth_output_metadata,
    source_has_hdr10plus,
    verify_hdr10plus_metadata,
    write_hdr_metadata_error_report,
)


class EncodeSourceProbeTests(unittest.TestCase):
    def test_probe_selects_first_video_stream_and_keeps_the_stream_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / 'source.mkv'
            source_path.write_bytes(b'mkv')
            stream = {
                'index': 3,
                'codec_name': 'hevc',
                'color_primaries': 'bt2020',
                'side_data_list': [{'side_data_type': 'Mastering display metadata'}],
            }
            frame_side_data = {
                'side_data_type': 'Content light level metadata',
                'max_content': 1000,
                'max_average': 400,
            }
            result = SimpleNamespace(
                returncode=0,
                stdout=json.dumps({
                    'streams': [stream],
                    'frames': [{'side_data_list': [frame_side_data]}],
                }),
                stderr='',
            )

            with (
                    patch('src.runtime.encode_source.core_settings.FFPROBE_PATH', ''),
                    patch('src.runtime.encode_source.run_command', return_value=result) as run_probe,
            ):
                source = probe_actual_encode_source(str(source_path))

            self.assertTrue(os.path.samefile(source.path, source_path))
            self.assertEqual(source.stream_index, 3)
            self.assertEqual(source.codec_name, 'hevc')
            self.assertEqual(
                source.stream['side_data_list'],
                stream['side_data_list'] + [frame_side_data],
            )
            command = run_probe.call_args.args[0]
            self.assertEqual(command[0], 'ffprobe')
            self.assertEqual(command[command.index('-select_streams') + 1], 'v:0')
            self.assertEqual(command[command.index('-read_intervals') + 1], '%+#1')
            self.assertIn('-show_frames', command)
            self.assertEqual(command[-1], source.path)
            self.assertEqual(run_probe.call_args.kwargs['timeout'], 120)

    def test_probe_uses_the_explicit_configured_ffprobe_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / 'source.mkv'
            source_path.write_bytes(b'mkv')
            result = SimpleNamespace(
                returncode=0,
                stdout='{"streams": [{"index": 0, "codec_name": "hevc"}]}',
                stderr='',
            )
            with (
                    patch(
                        'src.runtime.encode_source.core_settings.FFPROBE_PATH',
                        r'X:\configured\ffprobe.exe',
                    ),
                    patch('src.runtime.encode_source.run_command', return_value=result) as run_probe,
            ):
                probe_actual_encode_source(str(source_path))

            self.assertEqual(
                run_probe.call_args.args[0][0],
                r'X:\configured\ffprobe.exe',
            )

    def test_probe_reports_ffprobe_failure_and_missing_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / 'source.mkv'
            source_path.write_bytes(b'mkv')
            with patch(
                    'src.runtime.encode_source.run_command',
                    return_value=SimpleNamespace(returncode=2, stdout='', stderr='bad input'),
            ):
                with self.assertRaisesRegex(RuntimeError, 'bad input'):
                    probe_actual_encode_source(str(source_path))

            with patch(
                    'src.runtime.encode_source.run_command',
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout='{"streams": []}',
                        stderr='',
                    ),
            ):
                with self.assertRaisesRegex(RuntimeError, 'did not return a video stream'):
                    probe_actual_encode_source(str(source_path))

    def test_vapoursynth_output_properties_override_source_color_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vpy_path = root / 'encode.vpy'
            vpy_path.write_text('clip.set_output()\n', encoding='utf-8')
            source = ActualEncodeSource(
                str(root / 'source.mkv'),
                0,
                'hevc',
                {
                    'color_range': 'tv',
                    'color_primaries': 'bt2020',
                    'color_transfer': 'smpte2084',
                    'color_space': 'bt2020nc',
                    'chroma_location': 'topleft',
                    'side_data_list': [
                        {'side_data_type': 'Mastering display metadata'},
                        {'side_data_type': 'Content light level metadata'},
                    ],
                },
            )
            properties = {
                '_ColorRange': 0,
                '_Primaries': 1,
                '_Transfer': 1,
                '_Matrix': 1,
            }

            def run_probe(command, **kwargs):
                Path(kwargs['env']['BLURAYSUB_VPY_PROBE_RESULT']).write_text(
                    json.dumps({
                        'timeline': [3, 24_000, 1_001],
                        'samples': [properties, properties, properties],
                    }),
                    encoding='utf-8',
                )
                wrapper = Path(command[-1]).read_text(encoding='utf-8')
                self.assertIn('clip.num_frames // 2', wrapper)
                self.assertIn('clip.num_frames - 1', wrapper)
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            with patch('src.runtime.encode_source.run_command', side_effect=run_probe):
                result, color_changed, timeline = probe_vapoursynth_output_metadata(
                    source,
                    str(vpy_path),
                    'vspipe',
                    {},
                )

            self.assertEqual(result.stream['color_range'], 'pc')
            self.assertEqual(result.stream['color_primaries'], 'bt709')
            self.assertEqual(result.stream['color_transfer'], 'bt709')
            self.assertEqual(result.stream['color_space'], 'bt709')
            self.assertEqual(result.stream['chroma_location'], 'topleft')
            self.assertEqual(result.stream['side_data_list'], [])
            self.assertTrue(color_changed)
            self.assertEqual(timeline, (3, 24_000, 1_001))

    def test_hdr10plus_extraction_requires_the_same_vpy_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = ActualEncodeSource(
                str(root / 'source.mkv'),
                0,
                'hevc',
                {
                    'avg_frame_rate': '24000/1001',
                    'side_data_list': [{
                        'side_data_type': 'HDR Dynamic Metadata SMPTE2094-40 (HDR10+)',
                    }],
                },
            )

            def run_extract(command, **_kwargs):
                if command[1:3] == ['--verify', 'extract']:
                    self.assertIn(
                        command[3],
                        (
                            str(root / 'encoded.hevc'),
                            str(root / 'encoded.hevc.hdr10plus.hevc'),
                        ),
                    )
                    return SimpleNamespace(returncode=0, stdout='', stderr='')
                if command[1] == 'inject':
                    self.assertEqual(
                        command[command.index('-i') + 1],
                        str(root / 'encoded.hevc'),
                    )
                    self.assertEqual(
                        command[command.index('-j') + 1],
                        str(root / 'metadata.json'),
                    )
                    Path(command[command.index('-o') + 1]).write_bytes(b'injected')
                    return SimpleNamespace(returncode=0, stdout='', stderr='')
                self.assertEqual(command[1:3], ['extract', source.path])
                self.assertNotIn('--skip-validation', command)
                self.assertNotIn('--skip-reorder', command)
                Path(command[command.index('-o') + 1]).write_text(
                    json.dumps({'SceneInfo': [{}, {}, {}]}),
                    encoding='utf-8',
                )
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            self.assertTrue(source_has_hdr10plus(source))
            metadata_path = root / 'metadata.json'
            encoded_path = root / 'encoded.hevc'
            encoded_path.write_bytes(b'encoded')
            with (
                    patch(
                        'src.runtime.encode_source.core_settings.HDR10PLUS_TOOL_PATH',
                        'hdr10plus_tool',
                    ),
                    patch('src.runtime.encode_source.run_command', side_effect=run_extract),
            ):
                self.assertEqual(
                    extract_hdr10plus_metadata(
                        source,
                        str(metadata_path),
                        (3, 24_000, 1_001),
                    ),
                    str(metadata_path),
                )
                verify_hdr10plus_metadata(str(encoded_path))
                inject_hdr10plus_metadata(str(encoded_path), str(metadata_path))
                with self.assertRaisesRegex(RuntimeError, 'VapourSynth output'):
                    extract_hdr10plus_metadata(
                        source,
                        str(metadata_path),
                        (2, 24_000, 1_001),
                    )
            self.assertTrue(metadata_path.is_file())
            self.assertEqual(encoded_path.read_bytes(), b'injected')
            self.assertFalse((root / 'encoded.hevc.hdr10plus.hevc').exists())

    def test_error_report_uses_a_new_file_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_path = root / 'Episode.mkv'
            first_report = root / 'Episode.hdr-metadata-error.txt'
            first_report.write_text('existing', encoding='utf-8')

            report_path = Path(write_hdr_metadata_error_report(
                str(output_path),
                str(root / 'source.mkv'),
                'Actual encode source detection',
                RuntimeError('probe failed'),
            ))

            self.assertEqual(report_path.name, 'Episode.hdr-metadata-error.2.txt')
            self.assertEqual(first_report.read_text(encoding='utf-8'), 'existing')
            report_bytes = report_path.read_bytes()
            self.assertIn(b'probe failed', report_bytes)
            self.assertNotIn(b'\n', report_bytes.replace(b'\r\n', b''))


if __name__ == '__main__':
    unittest.main()
