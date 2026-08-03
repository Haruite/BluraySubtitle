"""Focused tests for full-frame PSNR report generation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.frame_check import frame_check_report_path, run_full_frame_check


class FrameCheckTests(unittest.TestCase):
    def test_full_check_reports_ranges_and_frame_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vpy_path = root / "encode.vpy"
            encoded_path = root / "Episode.mkv"
            vpy_path.write_text("clip.set_output()\n", encoding="utf-8")
            encoded_path.write_bytes(b"encoded")

            def write_stats(*args, **kwargs):
                Path(args[5]).write_text(
                    "n:1 mse_avg:0.00 psnr_avg:inf psnr_y:inf psnr_u:inf psnr_v:inf\n"
                    "n:2 mse_avg:1.00 psnr_avg:31.00 psnr_y:28.00 psnr_u:45.00 psnr_v:45.00\n"
                    "n:3 mse_avg:1.00 psnr_avg:30.00 psnr_y:29.00 psnr_u:39.00 psnr_v:45.00\n",
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    vspipe_exit_code=0,
                    ffmpeg_exit_code=0,
                    vspipe_log="Frames: 4/4",
                    ffmpeg_log="",
                )

            with (
                    patch(
                        "src.runtime.frame_check._probe_encoded_video",
                        return_value={
                            "packet_count": 4,
                            "frame_rate": "24/1",
                            "fps": 24.0,
                            "width": 1920,
                            "height": 1080,
                            "pixel_format": "yuv420p10le",
                        },
                    ),
                    patch(
                        "src.runtime.frame_check._run_full_frame_check_process",
                        side_effect=write_stats,
                    ),
            ):
                result = run_full_frame_check(
                    vspipe_executable="vspipe",
                    vpy_path=str(vpy_path),
                    vspipe_environment={},
                    ffmpeg_executable="ffmpeg",
                    ffprobe_executable="ffprobe",
                    encoded_path=str(encoded_path),
                    expected_reference_frames=4,
                )

            self.assertEqual(result.status, "fail")
            self.assertEqual(result.compared_frames, 3)
            self.assertEqual(result.suspicious_frames, 2)
            report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
            self.assertFalse(report["summary"]["frame_count_matches"])
            self.assertEqual(report["summary"]["metrics"]["y"]["infinite_frames"], 1)
            self.assertEqual(report["suspicious_ranges"][0]["start_frame"], 1)
            self.assertEqual(report["suspicious_ranges"][0]["end_frame"], 2)
            self.assertNotIn("Infinity", Path(result.report_path).read_text(encoding="utf-8"))

    def test_identical_frames_pass_and_report_path_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vpy_path = root / "encode.vpy"
            encoded_path = root / "Episode.mkv"
            vpy_path.write_text("clip.set_output()\n", encoding="utf-8")
            encoded_path.write_bytes(b"encoded")

            def write_stats(*args, **kwargs):
                Path(args[5]).write_text(
                    "n:1 mse_avg:0.00 psnr_avg:inf psnr_y:inf psnr_u:inf psnr_v:inf\n"
                    "n:2 mse_avg:0.00 psnr_avg:inf psnr_y:inf psnr_u:inf psnr_v:inf\n",
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    vspipe_exit_code=0,
                    ffmpeg_exit_code=0,
                    vspipe_log="Frames: 2/2",
                    ffmpeg_log="",
                )

            with (
                    patch(
                        "src.runtime.frame_check._probe_encoded_video",
                        return_value={
                            "packet_count": 2,
                            "frame_rate": "24000/1001",
                            "fps": 24000 / 1001,
                            "width": 1920,
                            "height": 1080,
                            "pixel_format": "yuv420p10le",
                        },
                    ),
                    patch(
                        "src.runtime.frame_check._run_full_frame_check_process",
                        side_effect=write_stats,
                    ),
            ):
                result = run_full_frame_check(
                    vspipe_executable="vspipe",
                    vpy_path=str(vpy_path),
                    vspipe_environment={},
                    ffmpeg_executable="ffmpeg",
                    ffprobe_executable="ffprobe",
                    encoded_path=str(encoded_path),
                    expected_reference_frames=2,
                )

            self.assertEqual(result.status, "pass")
            self.assertEqual(
                result.report_path,
                frame_check_report_path(str(encoded_path)),
            )
            report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["metrics"]["average"]["mean_db"], "inf")
            self.assertEqual(report["suspicious_ranges"], [])

    def test_configured_psnr_threshold_changes_suspicion_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            vpy_path = root / "encode.vpy"
            encoded_path = root / "Episode.mkv"
            vpy_path.write_text("clip.set_output()\n", encoding="utf-8")
            encoded_path.write_bytes(b"encoded")

            def write_stats(*args, **kwargs):
                Path(args[5]).write_text(
                    "n:1 mse_avg:1.00 psnr_avg:30.00 psnr_y:28.00 psnr_u:39.00 psnr_v:45.00\n",
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    vspipe_exit_code=0,
                    ffmpeg_exit_code=0,
                    vspipe_log="Frames: 1/1",
                    ffmpeg_log="",
                )

            with (
                    patch(
                        "src.runtime.frame_check._probe_encoded_video",
                        return_value={
                            "packet_count": 1,
                            "frame_rate": "24/1",
                            "fps": 24.0,
                            "width": 1920,
                            "height": 1080,
                            "pixel_format": "yuv420p10le",
                        },
                    ),
                    patch(
                        "src.runtime.frame_check._run_full_frame_check_process",
                        side_effect=write_stats,
                    ),
            ):
                result = run_full_frame_check(
                    vspipe_executable="vspipe",
                    vpy_path=str(vpy_path),
                    vspipe_environment={},
                    ffmpeg_executable="ffmpeg",
                    ffprobe_executable="ffprobe",
                    encoded_path=str(encoded_path),
                    expected_reference_frames=1,
                    luma_psnr_threshold_db=25.0,
                    chroma_psnr_threshold_db=38.0,
                )

            self.assertEqual(result.status, "pass")
            report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
            self.assertEqual(report["thresholds_db"], {"y": 25.0, "u": 38.0, "v": 38.0})


if __name__ == "__main__":
    unittest.main()
