"""Workflow tests for ordered chapter matching and safe MKV writes."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.services import BluraySubtitle  # Import the composed service before its split mixins.
from src.runtime.services_split import subtitle_and_chapter_pipeline as chapter_service_module
from src.runtime.services_split.subtitle_and_chapter_pipeline import SubtitleChapterPipelineMixin


class _FakeChapter:
    in_out_time = [('00001', 0, 900000)]
    mark_info = {0: [0, 225000, 450000, 675000]}


class _FakeMkv:
    durations: dict[str, float] = {}
    writes: list[tuple[str, bool, str | None, str]] = []

    def __init__(self, path: str) -> None:
        self.path = path

    def get_duration(self) -> float:
        return self.durations[self.path]

    def add_chapter(self, edit_original: bool, chapter_path: str, output_path: str | None = None) -> None:
        chapter_text = Path(chapter_path).read_text(encoding='utf-8-sig')
        self.writes.append((self.path, edit_original, output_path, chapter_text))


class AddChaptersWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeMkv.durations = {}
        _FakeMkv.writes = []

    def test_service_matches_ordered_mkvs_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_mkv = str(root / 'group-release-b.mkv')
            second_mkv = str(root / 'group-release-a.mkv')
            targets = [
                (first_mkv, str(root / 'output' / 'group-release-b.mkv')),
                (second_mkv, str(root / 'output' / 'group-release-a.mkv')),
            ]
            _FakeMkv.durations = {first_mkv: 10.0, second_mkv: 10.0}
            service = SimpleNamespace(_progress=lambda *args, **kwargs: None)

            with patch.object(chapter_service_module, 'Chapter', return_value=_FakeChapter()), patch.object(
                    chapter_service_module, 'MKV', _FakeMkv):
                SubtitleChapterPipelineMixin.add_chapters_to_mkv(
                    service,
                    targets,
                    [str(root / '00001')],
                    False,
                    cancel_event=threading.Event(),
                )

            self.assertEqual([write[0] for write in _FakeMkv.writes], [first_mkv, second_mkv])
            self.assertEqual([write[2] for write in _FakeMkv.writes], [target[1] for target in targets])
            self.assertIn('CHAPTER02=00:00:05.000', _FakeMkv.writes[0][3])
            self.assertIn('CHAPTER02=00:00:05.000', _FakeMkv.writes[1][3])

    def test_unmatched_mkvs_fail_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            targets = []
            for index in range(3):
                source_path = str(root / f'{index}.mkv')
                targets.append((source_path, str(root / 'output' / f'{index}.mkv')))
                _FakeMkv.durations[source_path] = 999.0
            service = SimpleNamespace(_progress=lambda *args, **kwargs: None)

            with patch.object(chapter_service_module, 'Chapter', return_value=_FakeChapter()), patch.object(
                    chapter_service_module, 'MKV', _FakeMkv):
                with self.assertRaisesRegex(ValueError, 'Could not map all MKV files'):
                    SubtitleChapterPipelineMixin.add_chapters_to_mkv(
                        service,
                        targets,
                        [str(root / '00001')],
                        False,
                    )

            self.assertEqual(_FakeMkv.writes, [])

    def test_multiple_playlists_continue_in_order_without_filename_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_mkv = str(root / 'release-episode-a.mkv')
            second_mkv = str(root / 'release-episode-b.mkv')
            targets = [
                (first_mkv, str(root / 'output' / 'release-episode-a.mkv')),
                (second_mkv, str(root / 'output' / 'release-episode-b.mkv')),
            ]
            _FakeMkv.durations = {first_mkv: 999.0, second_mkv: 999.0}
            service = SimpleNamespace(_progress=lambda *args, **kwargs: None)

            with patch.object(chapter_service_module, 'Chapter', return_value=_FakeChapter()), patch.object(
                    chapter_service_module, 'MKV', _FakeMkv):
                SubtitleChapterPipelineMixin.add_chapters_to_mkv(
                    service,
                    targets,
                    [str(root / '00001'), str(root / '00002')],
                    False,
                )

            self.assertEqual([write[0] for write in _FakeMkv.writes], [first_mkv, second_mkv])


if __name__ == '__main__':
    unittest.main()
