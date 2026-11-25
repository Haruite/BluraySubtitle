"""Focused tests for automatic discovery of the actual per-row Encode source."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.core.tool_paths import default_tool_paths, using_tool_paths
from src.runtime.encode_source import (
    ActualEncodeSource,
    extract_hdr10plus_metadata,
    hdr_to_sdr_source,
    inject_hdr10plus_metadata,
    probe_vapoursynth_frame_count,
    probe_vapoursynth_output_metadata,
    source_has_hdr10plus,
    verify_hdr10plus_metadata,
    verify_sdr_encode,
)


class EncodeSourceProbeTests(unittest.TestCase):
    def test_sdr_conversion_selects_the_dolby_vision_base_signal(self) -> None:
        cases = ((7, 6, 16, False), (8, 1, 16, False), (8, 4, 18, False), (8, 2, 1, False), (5, 0, 2, True))
        for input_mode in ('bdmv', 'remux'):
            for profile, compatibility, transfer, reshape in cases:
                with self.subTest(input_mode=input_mode, profile=profile, compatibility=compatibility):
                    source = ActualEncodeSource('source.mkv', 0, 'hevc', {'side_data_list': [{
                        'side_data_type': 'DOVI configuration record',
                        'dv_profile': profile,
                        'dv_bl_signal_compatibility_id': compatibility,
                    }]})
                    plan = hdr_to_sdr_source(source, input_mode=input_mode)
                    self.assertEqual(plan.transfer, transfer)
                    self.assertEqual(plan.needs_dolby_vision_rpu, reshape and input_mode == 'remux')

    def test_sdr_output_rejects_hdr_metadata_even_with_sdr_color_tags(self) -> None:
        source = ActualEncodeSource('encoded.hevc', 0, 'hevc', {
            'color_transfer': 'bt709',
            'side_data_list': [{'side_data_type': 'HDR Dynamic Metadata SMPTE2094-40 (HDR10+)'}],
        })
        with self.assertRaisesRegex(RuntimeError, 'wrote HDR signaling'):
            verify_sdr_encode(source, expect_bt709=True)

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
                    'width': 3840,
                    'height': 2160,
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
                        'size': [1920, 800],
                        'resize_input_size': [3840, 1600],
                    }),
                    encoding='utf-8',
                )
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            with patch('src.runtime.encode_source.run_vspipe', side_effect=run_probe):
                result, color_changed, timeline, _source_frames = probe_vapoursynth_output_metadata(
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
            self.assertEqual(result.geometry.source_size, (3840, 2160))
            self.assertEqual(result.geometry.resize_input_size, (3840, 1600))
            self.assertEqual(result.geometry.output_size, (1920, 800))

    def test_frame_count_comes_from_output_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vpy_path = str(Path(directory) / "test.vpy")
            for output in (
                "Width: 1920\nFrames: 23\n",
                "Output Index: 1\nFrames: 100\n\nOutput Index: 0\nFrames: 23\n",
            ):
                with (
                    self.subTest(output=output),
                    patch("src.runtime.encode_source.run_vspipe", return_value=SimpleNamespace(
                        returncode=0, stdout=output, stderr="",
                    )),
                ):
                    self.assertEqual(probe_vapoursynth_frame_count(vpy_path, "vspipe", {}), 23)

    def test_hdr10plus_requires_matching_frames_without_relying_on_nominal_fps(self) -> None:
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
            tool = root / 'hdr_tool'
            tool.touch(mode=0o755)
            with (
                    using_tool_paths({**default_tool_paths(), 'HDR10PLUS_TOOL_PATH': str(tool)}),
                    patch('src.runtime.encode_source.run_command', side_effect=run_extract),
            ):
                self.assertEqual(
                    extract_hdr10plus_metadata(
                        source,
                        str(metadata_path),
                        (3, 30, 1),
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


if __name__ == '__main__':
    unittest.main()
