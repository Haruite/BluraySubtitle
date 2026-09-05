"""Clip range parsing and containment used by SP matching."""

from __future__ import annotations

import unittest

from src.runtime.sp import m2ts_file_detail_segments_contained_in, parse_m2ts_file_detail_segments


class M2tsDetailTests(unittest.TestCase):
    detail = (
        "00001.m2ts(00:00:01.500-00:02:03.250),"
        "00002.m2ts(00:00:00.000-00:00:01.250)"
    )

    def test_clip_ranges_preserve_millisecond_offsets(self) -> None:
        expected = [
            ("00001.m2ts", 1.5, 123.25),
            ("00002.m2ts", 0.0, 1.25),
        ]
        self.assertEqual(parse_m2ts_file_detail_segments(self.detail), expected)
        self.assertEqual(parse_m2ts_file_detail_segments("invalid"), [])

    def test_containment_requires_the_same_clip_and_enclosed_range(self) -> None:
        episode = "00001.m2ts(00:00:01.000-00:02:04.000)"
        contained = "00001.m2ts(00:00:01.500-00:02:03.250)"
        outside = "00001.m2ts(00:00:00.000-00:02:03.250)"
        wrong_clip = "00002.m2ts(00:00:01.500-00:02:03.250)"

        self.assertTrue(m2ts_file_detail_segments_contained_in(contained, episode))
        self.assertFalse(m2ts_file_detail_segments_contained_in(outside, episode))
        self.assertFalse(m2ts_file_detail_segments_contained_in(wrong_clip, episode))
        self.assertFalse(m2ts_file_detail_segments_contained_in("", episode))


if __name__ == "__main__":
    unittest.main()
