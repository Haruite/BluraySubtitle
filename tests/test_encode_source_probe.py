"""Focused tests for automatic discovery of the actual per-row Encode source."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.encode_source import (
    ActualEncodeSource,
    extract_hdr10plus_metadata,
    inject_hdr10plus_metadata,
    probe_vapoursynth_output_metadata,
    source_has_hdr10plus,
    verify_hdr10plus_metadata,
)


class EncodeSourceProbeTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
