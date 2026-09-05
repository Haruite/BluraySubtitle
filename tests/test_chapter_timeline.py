"""Episode tail trimming must preserve content and respect clip boundaries."""

import unittest
from types import SimpleNamespace

from src.bdmv.chapter import episode_tail_trim_plan


def _chapter(*ranges):
    # Fixture times are seconds; MPLS and CLPI use a 45 kHz clock.
    return SimpleNamespace(_play_item_file_ranges_cache=tuple(
        (name, start * 45000, end * 45000, 0, file_end * 45000 if file_end is not None else None)
        for name, start, end, file_end in ranges
    ))


class ChapterTimelineTests(unittest.TestCase):
    def test_trim_window_removes_only_complete_trailing_play_items(self) -> None:
        chapter = _chapter(('00001', 10, 100, 100), ('00002', 20, 40, 40), ('00003', 50, 60, 60))
        for window, expected in (
            (30, (90, ('00002.m2ts', '00003.m2ts'))),
            (29.9, (110, ('00003.m2ts',))),
            (9.9, (120, ())),
        ):
            with self.subTest(window=window):
                self.assertEqual(episode_tail_trim_plan(chapter, 0, 120, window), expected)

    def test_partial_or_unverified_file_end_is_preserved(self) -> None:
        for episode_end, file_end in ((115, 60), (120, 70), (120, None)):
            with self.subTest(episode_end=episode_end, file_end=file_end):
                chapter = _chapter(('00001', 0, 100, 100), ('00002', 40, 60, file_end))
                self.assertEqual(episode_tail_trim_plan(chapter, 0, episode_end), (episode_end, ()))

    def test_trim_never_empties_an_episode_or_removes_a_still_used_clip(self) -> None:
        chapter = _chapter(
            ('00001', 0, 100, 100), ('00002', 0, 10, 20),
            ('00001', 40, 50, 100), ('00002', 10, 20, 20),
        )
        for start, expected in (
            (0, (100, ('00002.m2ts',))),
            (110, (120, ('00002.m2ts',))),
            (120, (130, ())),
        ):
            with self.subTest(episode_start=start):
                self.assertEqual(episode_tail_trim_plan(chapter, start, 130), expected)


if __name__ == '__main__':
    unittest.main()
