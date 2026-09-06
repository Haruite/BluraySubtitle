"""Workflow tests for subtitle merging and output safety."""

from __future__ import annotations

import datetime
import os
import struct
import tempfile
import threading
import unittest
from contextlib import chdir
from pathlib import Path
from types import SimpleNamespace

from src.domain import Subtitle
from src.runtime.services import BluraySubtitle  # Import the composed service before its split mixins.
from src.runtime.services_split.subtitle_and_chapter_pipeline import SubtitleChapterPipelineMixin


class MergeSubtitleWorkflowTests(unittest.TestCase):
    @staticmethod
    def _write_srt(path: Path, text: str) -> None:
        path.write_text(
            f'1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n',
            encoding='utf-8-sig',
        )

    @staticmethod
    def _write_sup(path: Path, pts: int = 90000) -> None:
        path.write_bytes(b'PG' + struct.pack('>IIBH', pts, pts, 0x16, 1) + b'\x00')

    @staticmethod
    def _service(subtitle_files: list[str], configuration: dict[int, dict[str, int | str]]):
        service = SimpleNamespace(
            sub_files=subtitle_files,
            _subtitle_cache={},
            configuration={},
            _progress=lambda *args, **kwargs: None,
            generate_configuration_from_selected_mpls=lambda *args, **kwargs: configuration,
        )

        def preload(paths: list[str], cancel_event=None) -> None:
            service._subtitle_cache.update({path: Subtitle(path) for path in paths})

        service._preload_subtitles = preload
        return service

    def test_subtitle_duration_keeps_a_distant_final_event(self) -> None:
        subtitle = Subtitle.from_parsed(SimpleNamespace(events=[
            SimpleNamespace(End=datetime.timedelta(seconds=20)),
            SimpleNamespace(End=datetime.timedelta(seconds=600)),
        ]))
        self.assertEqual(subtitle.max_end_time(), 600.0)

    def test_completion_preserves_unowned_files_in_the_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory, chdir(temporary_directory):
            paths = [Path(name) for name in ('chapter.txt', 'mkvinfo.txt', 'info.json', '.meta')]
            for path in paths:
                path.write_bytes(b'existing user data')
            service = SimpleNamespace(checked=False)
            SubtitleChapterPipelineMixin.completion(service)
            self.assertEqual([path.read_bytes() for path in paths], [b'existing user data'] * len(paths))

    def test_sup_subtitles_are_merged_and_dumped_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_path = root / 'first.sup'
            second_path = root / 'second.sup'
            self._write_sup(first_path)
            self._write_sup(second_path, 180000)

            merged = Subtitle(str(first_path))
            merged.append_subtitle(Subtitle(str(second_path)), 10.0)
            folder_base = str(root / 'Disc.en')
            playlist_base = str(root / '00001.en')
            merged.dump(folder_base, playlist_base)

            output = (root / 'Disc.en.sup').read_bytes()
            expected = b''.join(
                b'PG' + struct.pack('>IIBH', pts, pts, 0x16, 1) + b'\x00'
                for pts in (90_000, 1_080_000)
            )
            self.assertEqual(output, expected)
            self.assertEqual((root / '00001.en.sup').read_bytes(), expected)
            with self.assertRaises(FileExistsError):
                merged.dump(folder_base, playlist_base)

    def test_series_merge_writes_one_output_pair_after_mapping_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_path = root / 'episode1.srt'
            second_path = root / 'episode2.srt'
            self._write_srt(first_path, 'First')
            self._write_srt(second_path, 'Second')
            playlist_directory = root / 'Disc' / 'BDMV' / 'PLAYLIST'
            playlist_directory.mkdir(parents=True)
            folder_base = str(root / 'Disc')
            playlist_base = str(playlist_directory / '00001')
            configuration = {
                0: {'folder': folder_base, 'selected_mpls': playlist_base, 'bdmv_index': 1, 'offset': '0'},
                1: {'folder': folder_base, 'selected_mpls': playlist_base, 'bdmv_index': 1, 'offset': '00:00:10'},
            }
            service = self._service([str(first_path), str(second_path)], configuration)

            output_paths = SubtitleChapterPipelineMixin.merge_subtitles(
                service,
                [(folder_base, playlist_base)],
                subtitle_suffix='.en',
                cancel_event=threading.Event(),
            )

            self.assertEqual(
                output_paths,
                [folder_base + '.en.srt', playlist_base + '.en.srt'],
            )
            output_text = Path(output_paths[0]).read_text(encoding='utf-8-sig')
            self.assertEqual(output_text.strip(), (
                '1\n00:00:00,000 --> 00:00:01,000\nFirst\n\n'
                '2\n00:00:10,000 --> 00:00:11,000\nSecond'
            ))

    def test_iso_merge_writes_only_beside_the_image_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image = root / 'Disc.ISO'
            image.write_bytes(b'original image')
            subtitle = root / 'episode.srt'
            self._write_srt(subtitle, 'Episode')
            playlists = root / 'private' / 'BDMV' / 'PLAYLIST'
            playlists.mkdir(parents=True)
            playlist_base = str(playlists / '00001')
            configuration = {
                0: {'folder': str(image), 'selected_mpls': playlist_base, 'bdmv_index': 1, 'offset': '00:00:10'},
            }
            service = self._service([str(subtitle)], configuration)
            outputs = SubtitleChapterPipelineMixin.merge_subtitles(
                service, [(str(image), playlist_base)], subtitle_suffix='.en',
            )
            self.assertEqual(outputs, [str(root / 'Disc.en.srt')])
            self.assertEqual(Path(outputs[0]).read_text(encoding='utf-8-sig').strip(),
                             '1\n00:00:10,000 --> 00:00:11,000\nEpisode')
            self.assertEqual(list(playlists.iterdir()), [])
            self.assertEqual(image.read_bytes(), b'original image')
            with self.assertRaises(FileExistsError):
                SubtitleChapterPipelineMixin.merge_subtitles(
                    service, [(str(image), playlist_base)], subtitle_suffix='.en',
                )

    def test_existing_output_aborts_before_any_new_output_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            subtitle_path = root / 'episode.srt'
            self._write_srt(subtitle_path, 'Episode')
            playlist_directory = root / 'Disc' / 'BDMV' / 'PLAYLIST'
            playlist_directory.mkdir(parents=True)
            folder_base = str(root / 'Disc')
            playlist_base = str(playlist_directory / '00001')
            existing_output = Path(folder_base + '.srt')
            existing_output.write_text('existing', encoding='utf-8')
            configuration = {
                0: {'folder': folder_base, 'selected_mpls': playlist_base, 'bdmv_index': 1, 'offset': '0'},
            }
            service = self._service([str(subtitle_path)], configuration)

            with self.assertRaises(FileExistsError):
                SubtitleChapterPipelineMixin.merge_subtitles(
                    service,
                    [(folder_base, playlist_base)],
                    cancel_event=threading.Event(),
                )

            self.assertEqual(existing_output.read_text(encoding='utf-8'), 'existing')
            self.assertFalse(Path(playlist_base + '.srt').exists())

    def test_mixed_formats_and_incomplete_mapping_are_explicit_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            srt_path = root / 'episode.srt'
            sup_path = root / 'episode.sup'
            self._write_srt(srt_path, 'Episode')
            self._write_sup(sup_path)
            folder_base = str(root / 'Disc')
            playlist_base = str(root / '00001')
            one_row = {
                0: {'folder': folder_base, 'selected_mpls': playlist_base, 'bdmv_index': 1, 'offset': '0'},
            }
            incomplete_service = self._service([str(srt_path), str(sup_path)], one_row)

            with self.assertRaises(ValueError):
                SubtitleChapterPipelineMixin.merge_subtitles(
                    incomplete_service,
                    [(folder_base, playlist_base)],
                )

            two_rows = {
                **one_row,
                1: {'folder': folder_base, 'selected_mpls': playlist_base, 'bdmv_index': 1, 'offset': '00:00:10'},
            }
            mixed_service = self._service([str(srt_path), str(sup_path)], two_rows)
            with self.assertRaises(ValueError):
                SubtitleChapterPipelineMixin.merge_subtitles(
                    mixed_service,
                    [(folder_base, playlist_base)],
                )

            self.assertFalse(os.path.exists(folder_base + '.srt'))
            self.assertFalse(os.path.exists(folder_base + '.sup'))


if __name__ == '__main__':
    unittest.main()
