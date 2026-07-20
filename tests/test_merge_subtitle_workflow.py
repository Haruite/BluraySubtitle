"""Workflow tests for subtitle merging and output safety."""

from __future__ import annotations

import os
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import Qt

from src.domain import Subtitle
from src.runtime.services import BluraySubtitle  # Import the composed service before its split mixins.
from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from src.runtime.gui_runtime_split import actions_and_file_dialogs as actions_module
from src.runtime.gui_runtime_split.actions_and_file_dialogs import ActionsAndDialogsMixin
from src.runtime.services_split.subtitle_and_chapter_pipeline import SubtitleChapterPipelineMixin


class _Signal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class _FakeThread:
    def __init__(self, parent) -> None:
        self.started = _Signal()
        self.was_started = False

    def start(self) -> None:
        self.was_started = True


class _FakeWorker:
    last_request = None

    def __init__(self, request, cancel_event) -> None:
        type(self).last_request = request
        self.progress = _Signal()
        self.label = _Signal()
        self.finished = _Signal()
        self.canceled = _Signal()
        self.failed = _Signal()

    def moveToThread(self, thread) -> None:
        self.thread = thread

    def run(self) -> None:
        pass


class _SubtitleTable:
    def __init__(self, subtitle_path: str) -> None:
        self.subtitle_path = subtitle_path

    def rowCount(self) -> int:
        return 1

    def item(self, row: int, column: int):
        if row != 0:
            return None
        if column == 0:
            return SimpleNamespace(checkState=lambda: Qt.CheckState.Checked)
        if column == 1:
            return SimpleNamespace(text=lambda: self.subtitle_path)
        return None


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

            self.assertEqual(merged.output_extension(), '.sup')
            self.assertEqual((root / 'Disc.en.sup').read_bytes().count(b'PG'), 2)
            self.assertEqual((root / '00001.en.sup').read_bytes().count(b'PG'), 2)
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
            self.assertIn('First', output_text)
            self.assertIn('Second', output_text)

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

    def test_gui_launch_reads_current_checkbox_state_into_one_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            subtitle_path = root / 'episode.srt'
            self._write_srt(subtitle_path, 'Episode')
            playlist_base = root / 'Disc' / 'BDMV' / 'PLAYLIST' / '00001'
            playlist_base.parent.mkdir(parents=True)
            playlist_base.with_suffix('.mpls').write_bytes(b'mpls')
            owner = SimpleNamespace(
                table2=_SubtitleTable(str(subtitle_path)),
                sub_check_state=[0],
                get_selected_mpls_no_ext=lambda: [(str(root / 'Disc'), str(playlist_base))],
                _is_movie_mode=lambda: False,
                _get_subtitle_suffix=lambda: '.en',
                bdmv_folder_path=SimpleNamespace(text=lambda: str(root)),
                checkbox1=SimpleNamespace(isChecked=lambda: True),
                exe_button=SimpleNamespace(text=lambda: 'Generate Subtitles'),
                _update_exe_button_progress=lambda *args, **kwargs: None,
                _on_exe_button_progress_value=lambda value: None,
                _on_exe_button_progress_text=lambda text: None,
                _show_error_dialog=lambda message: self.fail(message),
                _show_bottom_message=lambda *args, **kwargs: None,
                altered=True,
            )

            with patch.object(actions_module, 'QThread', _FakeThread), patch.object(
                    actions_module, 'MergeWorker', _FakeWorker):
                started = ActionsAndDialogsMixin.generate_subtitle(owner)

            self.assertTrue(started)
            request = _FakeWorker.last_request
            self.assertEqual(request.subtitle_files, (str(subtitle_path),))
            self.assertEqual(request.subtitle_suffix, '.en')
            self.assertTrue(request.complete_bluray_folder)


if __name__ == '__main__':
    unittest.main()
