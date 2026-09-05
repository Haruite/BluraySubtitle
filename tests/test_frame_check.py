"""PSNR thresholds, suspicious ranges, and incomplete frame comparisons."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.frame_check import run_full_frame_check


class FrameCheckTests(unittest.TestCase):
    def test_frame_counts_and_per_plane_thresholds_determine_the_result(self) -> None:
        cases = (
            ('identical', [(float('inf'),) * 3] * 2, 2, (30, 30), 'pass', []),
            ('luma', [(45, 45, 45), (28, 45, 45), (29, 45, 45)],
             3, (30, 30), 'suspect', [(1, 2)]),
            ('chroma', [(45, 29, 45), (45, 45, 45), (45, 45, 29)],
             3, (30, 30), 'suspect', [(0, 0), (2, 2)]),
            ('custom threshold', [(28, 39, 45)], 1, (25, 38), 'pass', []),
            ('missing frame', [(45, 45, 45)], 2, (30, 30), 'fail', []),
        )
        for name, planes, expected_frames, thresholds, status, ranges in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                vpy_path = root / 'encode.vpy'
                encoded_path = root / 'Episode.mkv'
                vpy_path.write_text('clip.set_output()\n', encoding='utf-8')
                encoded_path.write_bytes(b'encoded')

                def write_stats(*args, **kwargs):
                    Path(args[5]).write_text(''.join(
                        f'n:{index} psnr_avg:{y} psnr_y:{y} psnr_u:{u} psnr_v:{v}\n'
                        for index, (y, u, v) in enumerate(planes, 1)
                    ), encoding='utf-8')
                    return SimpleNamespace(
                        vspipe_exit_code=0, ffmpeg_exit_code=0, vspipe_log='', ffmpeg_log='',
                    )

                with (
                    patch('src.runtime.frame_check._probe_encoded_video', return_value={
                        'packet_count': expected_frames, 'frame_rate': '24/1', 'fps': 24.0,
                        'width': 1920, 'height': 1080, 'pixel_format': 'yuv420p10le',
                    }),
                    patch('src.runtime.frame_check._run_full_frame_check_process', side_effect=write_stats),
                ):
                    result = run_full_frame_check(
                        vspipe_executable='vspipe', vpy_path=str(vpy_path), vspipe_environment={},
                        ffmpeg_executable='ffmpeg', ffprobe_executable='ffprobe',
                        encoded_path=str(encoded_path), expected_reference_frames=expected_frames,
                        luma_psnr_threshold_db=thresholds[0], chroma_psnr_threshold_db=thresholds[1],
                    )

                self.assertEqual(result.status, status)
                self.assertEqual(result.compared_frames, len(planes))
                report = json.loads(Path(result.report_path).read_text(encoding='utf-8'))
                self.assertEqual(
                    [(item['start_frame'], item['end_frame']) for item in report['suspicious_ranges']],
                    ranges,
                )
                self.assertEqual(
                    report['summary']['frame_count_matches'], len(planes) == expected_frames,
                )


if __name__ == '__main__':
    unittest.main()
