"""Source clock preservation and the README prefix-test boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.runtime.video_timeline import VideoTimeline


class VideoTimelineTests(unittest.TestCase):
    def test_prefix_preserves_start_offset_frame_intervals_and_end_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.txt'
            source.write_text(
                '# timestamp format v2\n125\n166.708333\n208.416666\n229.25\n250.083333\n',
                encoding='utf-8',
            )
            timeline = VideoTimeline.read(str(source))
            self.assertEqual(timeline.timestamps_ns, (
                125_000_000, 166_708_333, 208_416_666, 229_250_000, 250_083_333,
            ))
            for count in (1, 3, 4):
                with self.subTest(frames=count):
                    path = root / f'prefix-{count}.txt'
                    prefix = timeline.write_prefix(str(path), count)
                    self.assertEqual(prefix.timestamps_ns, timeline.timestamps_ns[:count + 1])
                    self.assertEqual(VideoTimeline.read(str(path)), prefix)
                    with self.assertRaises(FileExistsError):
                        timeline.write_prefix(str(path), count)
            for count in (0, 5):
                with self.subTest(frames=count), self.assertRaises(ValueError):
                    timeline.write_prefix(str(root / 'invalid.txt'), count)
            self.assertFalse((root / 'invalid.txt').exists())

    def test_incomplete_or_non_increasing_timestamps_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timestamps.txt'
            for contents in ('0\n', '0\n0\n', '42\n0\n', '0\nNaN\n'):
                with self.subTest(contents=contents):
                    path.write_text(contents, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        VideoTimeline.read(str(path))


if __name__ == '__main__':
    unittest.main()
