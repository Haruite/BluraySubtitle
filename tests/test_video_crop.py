"""Focused contracts for automatic video black-border detection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.video_crop import (
    VideoCropPlan,
    adaptive_crop_sample_count,
    detect_black_borders,
    stratified_crop_timestamps,
    write_vapoursynth_crop,
)


class VideoCropTests(unittest.TestCase):
    def test_sample_count_scales_with_duration_and_is_bounded(self) -> None:
        self.assertEqual(adaptive_crop_sample_count(60), 4)
        self.assertEqual(adaptive_crop_sample_count(600), 4)
        self.assertEqual(adaptive_crop_sample_count(900), 6)
        self.assertEqual(adaptive_crop_sample_count(1800), 12)
        self.assertEqual(adaptive_crop_sample_count(3600), 24)
        self.assertEqual(adaptive_crop_sample_count(7200), 24)

    def test_stratified_timestamps_are_reproducible_and_cover_all_buckets(self) -> None:
        duration = 1800.0
        sample_count = 12
        first = stratified_crop_timestamps(duration, sample_count, 'movie')
        second = stratified_crop_timestamps(duration, sample_count, 'movie')

        self.assertEqual(first, second)
        self.assertNotEqual(
            first,
            stratified_crop_timestamps(duration, sample_count, 'another movie'),
        )
        edge_guard = 5.0
        bucket_width = (duration - edge_guard * 2) / sample_count
        for index, timestamp in enumerate(first):
            self.assertGreaterEqual(timestamp, edge_guard + bucket_width * index)
            self.assertLess(timestamp, edge_guard + bucket_width * (index + 1))

    def test_detection_uses_fast_time_seeks_and_unions_active_rectangles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / 'movie.mkv'
            source.write_bytes(b'video')
            commands: list[list[str]] = []

            def run_command(command, **_kwargs):
                command = list(command)
                commands.append(command)
                if command[0] == 'ffprobe':
                    return SimpleNamespace(
                        returncode=0,
                        stdout=(
                            '{"streams":[{"width":1920,"height":1080}],'
                            '"format":{"duration":"1800.0"}}'
                        ),
                        stderr='',
                    )
                sample_index = len(commands) - 2
                crop = (
                    'crop=1920:804:0:138'
                    if sample_index == 5
                    else 'crop=1920:800:0:140'
                )
                return SimpleNamespace(
                    returncode=0,
                    stdout='',
                    stderr=f'[Parsed_cropdetect_0] {crop}\n',
                )

            with (
                    patch(
                        'src.runtime.video_crop.core_settings.FFPROBE_PATH',
                        'ffprobe',
                    ),
                    patch(
                        'src.runtime.video_crop.core_settings.FFMPEG_PATH',
                        'ffmpeg',
                    ),
                    patch(
                        'src.runtime.video_crop.run_command',
                        side_effect=run_command,
                    ),
            ):
                plan = detect_black_borders(str(source))

            self.assertEqual(plan.sample_count, 12)
            self.assertEqual((plan.left, plan.right, plan.top, plan.bottom), (0, 0, 138, 138))
            self.assertEqual((plan.output_width, plan.output_height), (1920, 804))
            self.assertTrue(plan.variable_borders)
            ffmpeg_commands = commands[1:]
            self.assertEqual(len(ffmpeg_commands), 12)
            for command in ffmpeg_commands:
                self.assertLess(command.index('-ss'), command.index('-i'))
                self.assertEqual(command[command.index('-frames:v') + 1], '3')
                self.assertEqual(command[-2:], ['null', '-'])

    def test_full_frame_detection_returns_a_no_crop_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / 'short.mkv'
            source.write_bytes(b'video')

            def run_command(command, **_kwargs):
                if list(command)[0] == 'ffprobe':
                    return SimpleNamespace(
                        returncode=0,
                        stdout=(
                            '{"streams":[{"width":1280,"height":720}],'
                            '"format":{"duration":"60"}}'
                        ),
                        stderr='',
                    )
                return SimpleNamespace(
                    returncode=0,
                    stdout='',
                    stderr='crop=1280:720:0:0',
                )

            with (
                    patch(
                        'src.runtime.video_crop.core_settings.FFPROBE_PATH',
                        'ffprobe',
                    ),
                    patch(
                        'src.runtime.video_crop.core_settings.FFMPEG_PATH',
                        'ffmpeg',
                    ),
                    patch(
                        'src.runtime.video_crop.run_command',
                        side_effect=run_command,
                    ),
            ):
                plan = detect_black_borders(str(source))

            self.assertEqual(plan.sample_count, 4)
            self.assertFalse(plan.has_crop)

    def test_vapoursynth_crop_is_inserted_replaced_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            script = Path(temporary_directory) / 'encode.vpy'
            script.write_text(
                'src8 = core.lsmas.LWLibavSource(a)\n'
                'src16 = core.fmtc.bitdepth(src8, bits=16)\n'
                'res = core.fmtc.bitdepth(src16, bits=10)\n'
                'res.set_output()\n',
                encoding='utf-8',
            )
            first = VideoCropPlan(
                1920,
                1080,
                7200.0,
                24,
                (),
                top=140,
                bottom=140,
            )
            second = VideoCropPlan(
                1920,
                1080,
                7200.0,
                24,
                (),
                left=2,
                right=2,
                top=138,
                bottom=138,
            )

            write_vapoursynth_crop(str(script), first)
            write_vapoursynth_crop(str(script), second)
            edited = script.read_text(encoding='utf-8')

            self.assertEqual(edited.count('automatic black-border crop: start'), 1)
            self.assertIn(
                'src8 = src8.std.Crop(left=2, right=2, top=138, bottom=138)',
                edited,
            )
            self.assertLess(edited.index('.std.Crop('), edited.index('src16 ='))

            write_vapoursynth_crop(str(script), None)
            cleaned = script.read_text(encoding='utf-8')
            self.assertNotIn('automatic black-border crop', cleaned)
            self.assertNotIn('.std.Crop(', cleaned)
            raw = script.read_bytes()
            self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))

    def test_vapoursynth_crop_rejects_a_script_without_safe_clip_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            script = Path(temporary_directory) / 'custom.vpy'
            script.write_text('clip = make_video()\nclip.set_output()\n', encoding='utf-8')
            plan = VideoCropPlan(1920, 1080, 60.0, 4, (), top=100, bottom=100)

            with self.assertRaisesRegex(RuntimeError, 'safe VPy crop insertion point'):
                write_vapoursynth_crop(str(script), plan)

    def test_vapoursynth_crop_rejects_unpaired_managed_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            script = Path(temporary_directory) / 'broken.vpy'
            original = (
                'src8 = make_video()\n'
                '# BluraySubtitle automatic black-border crop: end\n'
                'res = src8\n'
            )
            script.write_text(original, encoding='utf-8')

            with self.assertRaisesRegex(RuntimeError, 'crop block is incomplete'):
                write_vapoursynth_crop(str(script), None)

            self.assertEqual(script.read_text(encoding='utf-8'), original)

    def test_vapoursynth_crop_rejects_an_existing_manual_crop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            script = Path(temporary_directory) / 'manual-crop.vpy'
            script.write_text(
                'src8 = make_video()\n'
                'src8 = src8.std.Crop(top=20, bottom=20)\n'
                'res = src8\n'
                'res.set_output()\n',
                encoding='utf-8',
            )
            plan = VideoCropPlan(1920, 1080, 60.0, 4, (), top=100, bottom=100)

            with self.assertRaisesRegex(RuntimeError, 'already contains a manual crop'):
                write_vapoursynth_crop(str(script), plan)


if __name__ == '__main__':
    unittest.main()
