"""Focused tests for automatic encoder color and static HDR parameters."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.runtime.encode_source import (
    ActualEncodeSource,
    build_automatic_encoder_metadata_arguments,
    parse_source_color_metadata,
    verify_final_video_metadata,
)


def _hdr_source() -> ActualEncodeSource:
    stream = {
        'index': 0,
        'codec_name': 'hevc',
        'color_range': 'tv',
        'color_primaries': 'bt2020',
        'color_transfer': 'smpte2084',
        'color_space': 'bt2020nc',
        'chroma_location': 'topleft',
        'side_data_list': [
            {
                'side_data_type': 'Mastering display metadata',
                'green_x': '13250/50000',
                'green_y': '34500/50000',
                'blue_x': '7500/50000',
                'blue_y': '3000/50000',
                'red_x': '34000/50000',
                'red_y': '16000/50000',
                'white_point_x': '15635/50000',
                'white_point_y': '16450/50000',
                'max_luminance': '10000000/10000',
                'min_luminance': '50/10000',
            },
            {
                'side_data_type': 'Content light level metadata',
                'max_content': 1000,
                'max_average': 400,
            },
        ],
    }
    return ActualEncodeSource(
        path=os.path.abspath('source.mkv'),
        stream_index=0,
        codec_name='hevc',
        stream=stream,
    )


class EncoderMetadataParameterTests(unittest.TestCase):
    def test_static_hdr_metadata_uses_encoder_specific_units(self) -> None:
        metadata = parse_source_color_metadata(_hdr_source())

        self.assertEqual(
            metadata.mastering_display_x26x,
            'G(13250,34500)B(7500,3000)R(34000,16000)'
            'WP(15635,16450)L(10000000,50)',
        )
        self.assertEqual(
            metadata.mastering_display_svt,
            'G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)'
            'WP(0.3127,0.329)L(1000,0.005)',
        )
        self.assertEqual(metadata.content_light_level, '1000,400')

    def test_x265_receives_supported_color_and_static_hdr_options(self) -> None:
        arguments = build_automatic_encoder_metadata_arguments(
            _hdr_source(),
            'x265',
            (),
        )

        self.assertEqual(arguments, (
            '--range', 'limited',
            '--colorprim', 'bt2020',
            '--transfer', 'smpte2084',
            '--colormatrix', 'bt2020nc',
            '--chromaloc', '2',
            '--master-display',
            'G(13250,34500)B(7500,3000)R(34000,16000)'
            'WP(15635,16450)L(10000000,50)',
            '--max-cll', '1000,400',
        ))
        self.assertNotIn('--hdr10-opt', arguments)
        expected_metadata = parse_source_color_metadata(_hdr_source())
        with patch(
                'src.runtime.encode_source.probe_actual_encode_source',
                return_value=_hdr_source(),
        ):
            verify_final_video_metadata(
                'output.mkv',
                expected_metadata,
                arguments,
            )
        mismatched_output = _hdr_source()
        mismatched_output.stream['color_primaries'] = 'bt709'
        with patch(
                'src.runtime.encode_source.probe_actual_encode_source',
                return_value=mismatched_output,
        ):
            with self.assertRaisesRegex(RuntimeError, 'color_primaries'):
                verify_final_video_metadata(
                    'output.mkv',
                    expected_metadata,
                    arguments,
                )

    def test_x264_uses_its_current_official_static_hdr_option_names(self) -> None:
        arguments = build_automatic_encoder_metadata_arguments(
            _hdr_source(),
            'x264',
            (),
        )

        self.assertEqual(arguments, (
            '--range', 'tv',
            '--colorprim', 'bt2020',
            '--transfer', 'smpte2084',
            '--colormatrix', 'bt2020nc',
            '--chromaloc', '2',
            '--mastering-display',
            'G(13250,34500)B(7500,3000)R(34000,16000)'
            'WP(15635,16450)L(10000000,50)',
            '--cll', '1000,400',
        ))

    def test_svt_av1_uses_h273_values_and_physical_mastering_units(self) -> None:
        arguments = build_automatic_encoder_metadata_arguments(
            _hdr_source(),
            'svtav1',
            (),
        )

        self.assertEqual(arguments, (
            '--color-range', '0',
            '--color-primaries', '9',
            '--transfer-characteristics', '16',
            '--matrix-coefficients', '9',
            '--chroma-sample-position', 'topleft',
            '--mastering-display',
            'G(0.265,0.69)B(0.15,0.06)R(0.68,0.32)'
            'WP(0.3127,0.329)L(1000,0.005)',
            '--content-light', '1000,400',
        ))

    def test_manual_options_remain_authoritative(self) -> None:
        arguments = build_automatic_encoder_metadata_arguments(
            _hdr_source(),
            'x265',
            (
                '--range=full',
                '--colorprim',
                'bt709',
                '--master-display',
                'manual',
            ),
        )

        self.assertNotIn('--range', arguments)
        self.assertNotIn('--colorprim', arguments)
        self.assertNotIn('--master-display', arguments)
        self.assertIn('--transfer', arguments)
        self.assertIn('--max-cll', arguments)
        self.assertEqual(
            build_automatic_encoder_metadata_arguments(
                _hdr_source(),
                'x265',
                ('--video-signal-type-preset', 'BT2100_PQ_YCC'),
            ),
            (),
        )

    def test_invalid_or_unsupported_metadata_is_skipped(self) -> None:
        source = ActualEncodeSource(
            path=os.path.abspath('source.mkv'),
            stream_index=0,
            codec_name='hevc',
            stream={
                'color_range': 'unknown',
                'color_primaries': 'unsupported',
                'color_transfer': 'smpte2084',
                'color_space': 'unknown',
                'chroma_location': 'center',
                'side_data_list': [{
                    'side_data_type': 'Mastering display metadata',
                    'green_x': 'invalid',
                }],
            },
        )

        self.assertEqual(
            build_automatic_encoder_metadata_arguments(source, 'svtav1', ()),
            ('--transfer-characteristics', '16'),
        )


if __name__ == '__main__':
    unittest.main()
