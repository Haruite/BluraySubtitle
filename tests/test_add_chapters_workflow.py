"""Workflow tests for ordered chapter matching and safe MKV writes."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.domain.media.mkv_container import MKV
from src.runtime.gui_runtime_classes import chapter_worker as chapter_worker_module
from src.runtime.gui_runtime_split import actions_and_file_dialogs as actions_module
from src.runtime.gui_runtime_split.actions_and_file_dialogs import ActionsAndDialogsMixin
from src.runtime.gui_runtime_split.remux_and_episode_layout import RemuxEpisodeLayoutMixin
from src.runtime.services import BluraySubtitle  # Import the composed service before its split mixins.
from src.runtime.services_split import subtitle_and_chapter_pipeline as chapter_service_module
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


class _FakeChapterWorker:
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


class _WorkerService:
    instance = None

    def __init__(self, *args, **kwargs) -> None:
        self.init_args = args
        self.add_call = None
        self.completion_called = False
        type(self).instance = self

    def add_chapters_to_mkv(self, *args, **kwargs) -> None:
        self.add_call = (args, kwargs)

    def completion(self) -> None:
        self.completion_called = True


class AddChaptersWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeChapterWorker.last_request = None
        _FakeMkv.durations = {}
        _FakeMkv.writes = []

    @staticmethod
    def _gui_owner(root: Path, mkv_paths: list[str], edit_original: bool, errors: list[str]):
        playlist_base = root / 'Disc' / 'BDMV' / 'PLAYLIST' / '00001'
        playlist_base.parent.mkdir(parents=True, exist_ok=True)
        playlist_base.with_suffix('.mpls').write_bytes(b'mpls')
        return SimpleNamespace(
            get_selected_mpls_no_ext=lambda: [(str(root / 'Disc'), str(playlist_base))],
            get_mkv_files_in_table_order=lambda: list(mkv_paths),
            t=lambda text: text,
            checkbox1=SimpleNamespace(isChecked=lambda: edit_original),
            bdmv_folder_path=SimpleNamespace(text=lambda: str(root)),
            exe_button=SimpleNamespace(text=lambda: 'Add Chapters'),
            _update_exe_button_progress=lambda *args, **kwargs: None,
            _on_exe_button_progress_value=lambda value: None,
            _on_exe_button_progress_text=lambda text: None,
            _reset_exe_button=lambda: None,
            _show_bottom_message=lambda *args, **kwargs: None,
            _show_error_dialog=errors.append,
            _chapter_thread=None,
            _chapter_worker=None,
        )

    def test_gui_builds_one_request_from_current_order_and_output_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_mkv = root / '02.mkv'
            second_mkv = root / '01.mkv'
            first_mkv.write_bytes(b'mkv')
            second_mkv.write_bytes(b'mkv')
            tool_path = root / 'mkvmerge.exe'
            tool_path.write_bytes(b'tool')
            errors = []
            owner = self._gui_owner(
                root,
                [str(first_mkv), str(second_mkv)],
                edit_original=False,
                errors=errors,
            )

            with patch.object(actions_module, 'QThread', _FakeThread), patch.object(
                    actions_module, 'ChapterWorker', _FakeChapterWorker), patch.object(
                    actions_module, 'find_mkvtoolnix'), patch.object(
                    actions_module.core_settings, 'MKV_MERGE_PATH', str(tool_path)):
                started = ActionsAndDialogsMixin.add_chapters(owner)

            self.assertTrue(started)
            self.assertEqual(errors, [])
            request = _FakeChapterWorker.last_request
            self.assertEqual(
                request.mkv_targets,
                (
                    (str(first_mkv), str(root / 'output' / first_mkv.name)),
                    (str(second_mkv), str(root / 'output' / second_mkv.name)),
                ),
            )
            self.assertFalse(request.edit_original)

    def test_gui_rejects_existing_output_before_starting_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mkv_path = root / 'episode.mkv'
            mkv_path.write_bytes(b'mkv')
            output_path = root / 'output' / mkv_path.name
            output_path.parent.mkdir()
            output_path.write_bytes(b'existing')
            tool_path = root / 'mkvmerge.exe'
            tool_path.write_bytes(b'tool')
            errors = []
            owner = self._gui_owner(root, [str(mkv_path)], False, errors)

            with patch.object(actions_module, 'ChapterWorker', _FakeChapterWorker), patch.object(
                    actions_module, 'find_mkvtoolnix'), patch.object(
                    actions_module.core_settings, 'MKV_MERGE_PATH', str(tool_path)):
                started = ActionsAndDialogsMixin.add_chapters(owner)

            self.assertFalse(started)
            self.assertEqual(errors, [f'Output file already exists: {output_path}'])
            self.assertIsNone(_FakeChapterWorker.last_request)
            self.assertEqual(output_path.read_bytes(), b'existing')

    def test_gui_direct_edit_request_targets_the_original_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mkv_path = root / 'episode.mkv'
            mkv_path.write_bytes(b'mkv')
            tool_path = root / 'mkvpropedit.exe'
            tool_path.write_bytes(b'tool')
            errors = []
            owner = self._gui_owner(root, [str(mkv_path)], True, errors)

            with patch.object(actions_module, 'QThread', _FakeThread), patch.object(
                    actions_module, 'ChapterWorker', _FakeChapterWorker), patch.object(
                    actions_module, 'find_mkvtoolnix'), patch.object(
                    actions_module.core_settings, 'MKV_PROP_EDIT_PATH', str(tool_path)):
                started = ActionsAndDialogsMixin.add_chapters(owner)

            self.assertTrue(started)
            request = _FakeChapterWorker.last_request
            self.assertTrue(request.edit_original)
            self.assertEqual(request.mkv_targets, ((str(mkv_path), str(mkv_path)),))

    def test_table_helper_returns_the_current_visible_order(self) -> None:
        paths = ['02.mkv', '01.mkv']
        table = SimpleNamespace(
            rowCount=lambda: len(paths),
            item=lambda row, column: SimpleNamespace(text=lambda: paths[row]) if column == 0 else None,
        )
        owner = SimpleNamespace(table2=table, get_selected_function_id=lambda: 2)

        result = RemuxEpisodeLayoutMixin.get_mkv_files_in_table_order(owner)

        self.assertEqual(result, paths)

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

    def test_worker_passes_only_the_immutable_request_and_does_not_complete_bdmv(self) -> None:
        request = chapter_worker_module.AddChaptersRequest(
            bdmv_path='disc-root',
            mkv_targets=(('episode.mkv', 'output/episode.mkv'),),
            selected_mpls=('disc-root/BDMV/PLAYLIST/00001',),
            edit_original=False,
        )
        worker = chapter_worker_module.ChapterWorker(request, threading.Event())

        with patch.object(chapter_worker_module, 'BluraySubtitle', _WorkerService):
            worker.run()

        service = _WorkerService.instance
        self.assertEqual(service.init_args[:3], ('disc-root', ['episode.mkv'], False))
        self.assertEqual(service.add_call[0][:3], (
            list(request.mkv_targets),
            list(request.selected_mpls),
            False,
        ))
        self.assertFalse(service.completion_called)

    def test_trivial_chapter_still_creates_new_output_without_chapter_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / 'episode.mkv'
            source_path.write_bytes(b'mkv')
            chapter_path = root / 'chapter.txt'
            chapter_path.write_text(
                'CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 01',
                encoding='utf-8-sig',
            )
            output_path = root / 'output' / source_path.name
            tool_path = root / 'mkvmerge.exe'
            tool_path.write_bytes(b'tool')

            with patch('src.domain.media.mkv_container.core_settings.MKV_MERGE_PATH', str(tool_path)), patch(
                    'src.domain.media.mkv_container.subprocess.run',
                    return_value=SimpleNamespace(returncode=0),
            ) as run_command:
                mkv = MKV.__new__(MKV)
                mkv.path = str(source_path)
                mkv.add_chapter(False, str(chapter_path), str(output_path))

            command = run_command.call_args.args[0]
            self.assertNotIn('--chapters', command)
            self.assertEqual(command[-3:], ['-o', str(output_path), str(source_path)])
            self.assertTrue(output_path.parent.is_dir())


if __name__ == '__main__':
    unittest.main()
