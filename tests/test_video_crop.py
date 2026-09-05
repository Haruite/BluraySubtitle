"""Focused contracts for automatic video black-border detection."""

from __future__ import annotations

import tempfile
import unittest
from itertools import cycle
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.runtime.video_crop import VideoCropPlan, detect_black_borders, write_vapoursynth_crop


class VideoCropTests(unittest.TestCase):
    def test_detection_preserves_the_union_of_active_rectangles(self) -> None:
        cases = (
            (('crop=1920:800:0:140', 'crop=1920:804:0:138'), (0, 0, 138, 138), True),
            (('crop=1920:1080:0:0',), (0, 0, 0, 0), False),
        )
        for rectangles, margins, variable in cases:
            with self.subTest(rectangles=rectangles), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / 'movie.mkv'
                source.write_bytes(b'video')
                samples = cycle(rectangles)

                def run_command(command, **_kwargs):
                    if command[0] == 'ffprobe':
                        return SimpleNamespace(returncode=0, stderr='', stdout=(
                            '{"streams":[{"width":1920,"height":1080}],"format":{"duration":"60"}}'
                        ))
                    return SimpleNamespace(returncode=0, stdout='', stderr=next(samples))

                with (
                    patch('src.runtime.video_crop.core_settings.FFPROBE_PATH', 'ffprobe'),
                    patch('src.runtime.video_crop.core_settings.FFMPEG_PATH', 'ffmpeg'),
                    patch('src.runtime.video_crop.run_command', side_effect=run_command),
                ):
                    plan = detect_black_borders(str(source))
                self.assertEqual((plan.left, plan.right, plan.top, plan.bottom), margins)
                self.assertEqual(plan.variable_borders, variable)
                self.assertEqual(plan.has_crop, any(margins))

    def test_vapoursynth_crop_is_replaced_once_and_can_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'encode.vpy'
            original = 'src8 = source_clip\nres = src8\n'
            script.write_text(original, encoding='utf-8')
            first = VideoCropPlan(1920, 1080, 60, 4, (), top=140, bottom=140)
            second = VideoCropPlan(1920, 1080, 60, 4, (), left=2, right=2, top=138, bottom=138)
            write_vapoursynth_crop(str(script), first)
            write_vapoursynth_crop(str(script), second)

            crop = Mock(return_value=object())
            namespace = {'source_clip': SimpleNamespace(std=SimpleNamespace(Crop=crop))}
            exec(compile(script.read_text(encoding='utf-8'), str(script), 'exec'), namespace)
            crop.assert_called_once_with(left=2, right=2, top=138, bottom=138)
            self.assertIs(namespace['res'], crop.return_value)

            write_vapoursynth_crop(str(script), None)
            self.assertEqual(script.read_text(encoding='utf-8'), original)

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
