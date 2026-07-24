"""Focused tests for the explicit Blu-ray Remux request and output plan."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.runtime.remux import RemuxMainJob, RemuxRequest
from src.runtime.services import BluraySubtitle  # Import the composed service before its split mixins.
from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI  # noqa: F401
from src.runtime.gui_runtime_split import remux_and_episode_layout as remux_gui_module
from src.runtime.gui_runtime_split.remux_and_episode_layout import RemuxEpisodeLayoutMixin
from src.runtime.services_split import remux_and_episode_workflows as remux_service_module
from src.runtime.services_split import media_info_and_track_mapping as track_mapping_module
from src.runtime.services_split.media_info_and_track_mapping import MediaInfoTrackMappingMixin
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin


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


class _FakeChapter:
    in_out_time = []


class _FakeMkv:
    writes: list[tuple[str, bool, str]] = []

    def __init__(self, path: str) -> None:
        self.path = path

    def add_chapter(self, edit_original: bool, chapter_path: str) -> None:
        self.writes.append((self.path, edit_original, chapter_path))


class RemuxWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeWorker.last_request = None
        _FakeMkv.writes = []

    @staticmethod
    def _request(
            root: Path,
            configuration: dict[int, dict[str, int | str]],
            selected_mpls: list[tuple[str, str]],
            output_names: list[str],
    ) -> RemuxRequest:
        return RemuxRequest(
            bdmv_path=str(root / 'Disc'),
            subtitle_files=tuple('' for _ in configuration),
            complete_bluray_folder=False,
            output_folder=str(root / 'Output'),
            configuration=configuration,
            selected_mpls=tuple(selected_mpls),
            sp_entries=(),
            episode_output_names=tuple(output_names),
            episode_subtitle_languages=tuple('eng' for _ in configuration),
        )

    @staticmethod
    def _planning_owner(root: Path):
        owner = SimpleNamespace(configuration=None)

        def make_command(confs, dst_folder, bdmv_index, disc_count, ensure_disc_out_dir=False):
            mpls_path = BluraySubtitle._resolve_mpls_path_from_conf(confs[0], str(root / 'Disc'))
            stem = Path(mpls_path).stem
            output_path = os.path.join(dst_folder, f'{stem}.mkv')
            command = f'mkvmerge -o "{output_path}" "{mpls_path}"'
            return command, '', f'{bdmv_index:03d}', output_path, mpls_path, [], []

        owner._make_main_mpls_remux_cmd = make_command
        return owner

    def test_gui_captures_current_remux_controls_in_one_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_folder = root / 'Output'
            output_folder.mkdir()
            playlist_base = root / 'Disc' / 'BDMV' / 'PLAYLIST' / '00001'
            playlist_base.parent.mkdir(parents=True)
            playlist_base.with_suffix('.mpls').write_bytes(b'mpls')
            configuration = {
                0: {
                    'folder': str(root / 'Disc'),
                    'selected_mpls': str(playlist_base),
                    'bdmv_index': 1,
                    'start_at_chapter': 1,
                    'end_at_chapter': 2,
                    'main_remux_cmd': 'visible command',
                }
            }
            errors = []
            table2 = SimpleNamespace(
                rowCount=lambda: 1,
                item=lambda row, column: SimpleNamespace(text=lambda: 'episode.ass') if column == 0 else None,
            )
            table3 = SimpleNamespace(rowCount=lambda: 0)
            owner = SimpleNamespace(
                output_folder_path=SimpleNamespace(text=lambda: str(output_folder)),
                bdmv_folder_path=SimpleNamespace(text=lambda: str(root / 'Disc')),
                checkbox1=SimpleNamespace(isChecked=lambda: False),
                table2=table2,
                table3=table3,
                get_selected_mpls_no_ext=lambda: [(str(root / 'Disc'), str(playlist_base))],
                _configuration_for_service_run=lambda: configuration,
                _get_episode_output_names_from_table2=lambda: ['Visible Name.mkv'],
                _get_episode_subtitle_languages_from_table2=lambda: ['jpn'],
                _table3_get_sp_entry_for_row=lambda row: {},
                _is_movie_mode=lambda: True,
                get_selected_function_id=lambda: 3,
                trim_copyright_tail_checkbox=SimpleNamespace(isChecked=lambda: True),
                mux_dolby_vision_checkbox=SimpleNamespace(isChecked=lambda: False),
                _current_encode_lossless_audio_codec=lambda: 'opus',
                _track_selection_config={'main': {'audio': ['1']}},
                _track_language_config={'main': {'1': 'jpn'}},
                _track_lossless_audio_config={'main': {'1': 'opus'}},
                t=lambda text: text,
                exe_button=SimpleNamespace(text=lambda: 'Start Remux'),
                _update_exe_button_progress=lambda *args, **kwargs: None,
                _on_exe_button_progress_value=lambda value: None,
                _on_exe_button_progress_text=lambda text: None,
                _reset_exe_button=lambda: None,
                _show_bottom_message=lambda *args, **kwargs: None,
                _show_error_dialog=errors.append,
                _remux_thread=None,
                _remux_worker=None,
            )

            with patch.object(remux_gui_module, 'QThread', _FakeThread), patch.object(
                    remux_gui_module, 'RemuxWorker', _FakeWorker), patch.object(
                    remux_gui_module, 'find_mkvtoolnix'):
                started = RemuxEpisodeLayoutMixin.remux_episodes(owner)

            self.assertTrue(started)
            self.assertEqual(errors, [])
            request = _FakeWorker.last_request
            self.assertEqual(request.episode_output_names, ('Visible Name.mkv',))
            self.assertEqual(request.episode_subtitle_languages, ('jpn',))
            self.assertFalse(request.complete_bluray_folder)
            self.assertFalse(request.mux_dolby_vision)
            self.assertTrue(request.movie_mode)
            self.assertEqual(request.default_lossless_audio_codec, 'opus')
            self.assertIsNot(request.configuration, configuration)

    def test_gui_command_preview_keeps_the_complete_generated_command(self) -> None:
        mpls_path = os.path.normpath(r'E:\Disc\BDMV\PLAYLIST\00000.mpls')
        output_folder = os.path.normpath(r'E:\Output')
        expected_command = (
            '"mkvmerge" -a 1,2 -s 3 -o '
            '"E:\\Output\\Disc\\Main.mkv" '
            '"E:\\Disc\\BDMV\\PLAYLIST\\00000.mpls"'
        )
        service = SimpleNamespace(
            _make_main_mpls_remux_cmd=Mock(return_value=(
                expected_command,
                r'E:\Disc\BDMV\STREAM\00000.m2ts',
                '001',
                r'E:\Output\Disc\Main.mkv',
                mpls_path,
                ['1', '2'],
                ['3'],
            )),
        )
        owner = SimpleNamespace(
            _last_configuration_34={
                0: {
                    'selected_mpls': os.path.splitext(mpls_path)[0],
                    'bdmv_index': 1,
                    'chapter_index': 1,
                },
            },
            _remux_dst_folder_for_cmd_template=lambda root: output_folder,
            _is_movie_mode=lambda: True,
            _track_selection_config={},
            bdmv_folder_path=SimpleNamespace(text=lambda: r'E:\Disc'),
        )

        with patch.object(remux_gui_module, 'find_mkvtoolnix'), patch.object(
                remux_gui_module, 'BluraySubtitle', return_value=service):
            command = RemuxEpisodeLayoutMixin._build_main_remux_cmd_template(
                owner,
                mpls_path,
                1,
                r'E:\Disc',
            )

        self.assertEqual(command, expected_command)
        service._make_main_mpls_remux_cmd.assert_called_once()

    def test_gui_command_preview_failure_does_not_create_an_incomplete_command(self) -> None:
        mpls_path = os.path.normpath(r'E:\Disc\BDMV\PLAYLIST\00000.mpls')
        service = SimpleNamespace(
            _make_main_mpls_remux_cmd=Mock(side_effect=RuntimeError('generation failed')),
        )
        owner = SimpleNamespace(
            _last_configuration_34={},
            _remux_dst_folder_for_cmd_template=lambda root: os.path.normpath(r'E:\Output'),
            _is_movie_mode=lambda: True,
            _track_selection_config={},
            bdmv_folder_path=SimpleNamespace(text=lambda: r'E:\Disc'),
        )

        with patch.object(remux_gui_module, 'find_mkvtoolnix'), patch.object(
                remux_gui_module, 'BluraySubtitle', return_value=service), patch.object(
                remux_gui_module, 'print_exc_terminal'):
            command = RemuxEpisodeLayoutMixin._build_main_remux_cmd_template(
                owner,
                mpls_path,
                1,
                r'E:\Disc',
            )

        self.assertEqual(command, '')

    def test_same_disc_main_playlists_each_get_one_job_in_selected_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'Output').mkdir()
            playlist_directory = root / 'Disc' / 'BDMV' / 'PLAYLIST'
            playlist_directory.mkdir(parents=True)
            first = playlist_directory / '00001.mpls'
            second = playlist_directory / '00002.mpls'
            first.write_bytes(b'mpls')
            second.write_bytes(b'mpls')
            configuration = {
                0: {'folder': str(root / 'Disc'), 'selected_mpls': str(first.with_suffix('')), 'bdmv_index': 1},
                1: {'folder': str(root / 'Disc'), 'selected_mpls': str(second.with_suffix('')), 'bdmv_index': 1},
            }
            request = self._request(
                root,
                configuration,
                [(str(root / 'Disc'), str(first.with_suffix(''))),
                 (str(root / 'Disc'), str(second.with_suffix('')))],
                ['First.mkv', 'Second.mkv'],
            )
            request = replace(
                request,
                track_language_config={
                    f'main::{os.path.normpath(str(first))}': {'1': 'jpn'},
                },
            )

            with patch.object(remux_service_module, 'find_mkvtoolnix'), patch.object(
                    remux_service_module.core_settings, 'MKV_PROP_EDIT_PATH', str(first)):
                _destination, jobs = RemuxEpisodeWorkflowsMixin._prepare_remux_main_jobs(
                    self._planning_owner(root), request
                )

            self.assertEqual([Path(job.mpls_path).name for job in jobs], ['00001.mpls', '00002.mpls'])
            self.assertEqual([job.configuration_keys for job in jobs], [(0,), (1,)])
            self.assertEqual([Path(job.final_outputs[0]).name for job in jobs], ['First.mkv', 'Second.mkv'])
            self.assertEqual(jobs[0].track_language_overrides, (('1', 'jpn'),))
            self.assertEqual(jobs[1].track_language_overrides, ())

    def test_language_correction_requires_mkvpropedit_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'Output').mkdir()
            playlist_directory = root / 'Disc' / 'BDMV' / 'PLAYLIST'
            playlist_directory.mkdir(parents=True)
            playlist = playlist_directory / '00001.mpls'
            playlist.write_bytes(b'mpls')
            configuration = {
                0: {
                    'folder': str(root / 'Disc'),
                    'selected_mpls': str(playlist.with_suffix('')),
                    'bdmv_index': 1,
                },
            }
            request = replace(
                self._request(
                    root,
                    configuration,
                    [(str(root / 'Disc'), str(playlist.with_suffix('')))],
                    ['Episode.mkv'],
                ),
                track_language_config={
                    f'main::{os.path.normpath(str(playlist))}': {'1': 'jpn'},
                },
            )

            with patch.object(remux_service_module, 'find_mkvtoolnix'), patch.object(
                    remux_service_module.core_settings, 'MKV_PROP_EDIT_PATH', ''), patch.object(
                    remux_service_module.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, 'mkvpropedit not found'):
                    RemuxEpisodeWorkflowsMixin._prepare_remux_main_jobs(
                        self._planning_owner(root), request
                    )

            self.assertFalse((root / 'Output' / 'Disc').exists())

    def test_existing_or_duplicate_outputs_abort_during_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'Output').mkdir()
            playlist_directory = root / 'Disc' / 'BDMV' / 'PLAYLIST'
            playlist_directory.mkdir(parents=True)
            first = playlist_directory / '00001.mpls'
            second = playlist_directory / '00002.mpls'
            first.write_bytes(b'mpls')
            second.write_bytes(b'mpls')
            configuration = {
                0: {'folder': str(root / 'Disc'), 'selected_mpls': str(first.with_suffix('')), 'bdmv_index': 1},
                1: {'folder': str(root / 'Disc'), 'selected_mpls': str(second.with_suffix('')), 'bdmv_index': 1},
            }
            selected = [
                (str(root / 'Disc'), str(first.with_suffix(''))),
                (str(root / 'Disc'), str(second.with_suffix(''))),
            ]
            duplicate_request = self._request(root, configuration, selected, ['Same.mkv', 'Same.mkv'])
            with self.assertRaisesRegex(ValueError, 'Duplicate output path'):
                RemuxEpisodeWorkflowsMixin._prepare_remux_main_jobs(
                    self._planning_owner(root), duplicate_request
                )

            existing_path = root / 'Output' / 'Disc' / '00001.mkv'
            existing_path.parent.mkdir(parents=True)
            existing_path.write_bytes(b'existing')
            existing_request = self._request(root, configuration, selected, ['First.mkv', 'Second.mkv'])
            with self.assertRaisesRegex(FileExistsError, 'Output file already exists'):
                RemuxEpisodeWorkflowsMixin._prepare_remux_main_jobs(
                    self._planning_owner(root), existing_request
                )
            self.assertEqual(existing_path.read_bytes(), b'existing')

    def test_invalid_chapter_range_fails_before_output_directory_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'Output').mkdir()
            playlist_directory = root / 'Disc' / 'BDMV' / 'PLAYLIST'
            playlist_directory.mkdir(parents=True)
            playlist = playlist_directory / '00001.mpls'
            playlist.write_bytes(b'mpls')
            configuration = {
                0: {
                    'folder': str(root / 'Disc'),
                    'selected_mpls': str(playlist.with_suffix('')),
                    'bdmv_index': 1,
                    'start_at_chapter': 4,
                    'end_at_chapter': 4,
                }
            }
            request = self._request(
                root,
                configuration,
                [(str(root / 'Disc'), str(playlist.with_suffix('')))],
                ['Episode.mkv'],
            )

            with self.assertRaisesRegex(ValueError, 'End chapter must be greater'):
                RemuxEpisodeWorkflowsMixin._prepare_remux_main_jobs(
                    self._planning_owner(root), request
                )

            self.assertFalse((root / 'Output' / 'Disc').exists())

    def test_failed_main_command_is_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mpls_path = root / '00001.mpls'
            mpls_path.write_bytes(b'mpls')
            expected_output = root / 'expected.mkv'
            job = RemuxMainJob(
                configuration_keys=(0,),
                configurations=({'selected_mpls': str(mpls_path.with_suffix('')), 'bdmv_index': 1},),
                bdmv_index=1,
                command='mkvmerge -o expected.mkv 00001.mpls',
                m2ts_file='',
                volume='001',
                primary_output=str(expected_output),
                mpls_path=str(mpls_path),
                audio_tracks=(),
                subtitle_tracks=(),
                expected_outputs=(str(expected_output),),
                final_outputs=(str(root / 'Final.mkv'),),
            )
            owner = SimpleNamespace(
                track_selection_config={},
                t=lambda text: text,
                _progress=lambda *args, **kwargs: None,
                _set_dovi_mux_plan_for_mpls=lambda path: None,
                _mkvmerge_identify_covers_remux_slots=lambda *args: True,
                _run_shell_command_detailed=lambda command: (2, [2]),
                _try_remux_mpls_split_outputs_track_aligned=lambda *args, **kwargs: False,
                _try_remux_mpls_track_aligned=lambda *args, **kwargs: False,
            )

            with patch.object(remux_service_module, 'Chapter', return_value=_FakeChapter()):
                with self.assertRaisesRegex(RuntimeError, 'Main remux failed'):
                    RemuxEpisodeWorkflowsMixin._build_main_episode_mkvs(owner, [job])

            self.assertFalse(expected_output.exists())

    def test_fallback_output_receives_the_captured_track_languages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mpls_path = root / '00001.mpls'
            mpls_path.write_bytes(b'mpls')
            m2ts_path = root / '00001.m2ts'
            m2ts_path.write_bytes(b'm2ts')
            expected_output = root / 'expected.mkv'
            job = RemuxMainJob(
                configuration_keys=(0,),
                configurations=({'selected_mpls': str(mpls_path.with_suffix('')), 'bdmv_index': 1},),
                bdmv_index=1,
                command='mkvmerge -o expected.mkv 00001.mpls',
                m2ts_file=str(m2ts_path),
                volume='001',
                primary_output=str(expected_output),
                mpls_path=str(mpls_path),
                audio_tracks=('1',),
                subtitle_tracks=(),
                expected_outputs=(str(expected_output),),
                final_outputs=(str(root / 'Final.mkv'),),
                track_language_overrides=(('1', 'jpn'),),
            )
            language_calls = []

            def fallback(*_args, **_kwargs) -> bool:
                expected_output.write_bytes(b'mkv')
                return True

            fake_service_class = SimpleNamespace(
                _fallback_track_lists=lambda command, audio, subtitle: (audio, subtitle),
                _fix_output_track_languages_with_mkvpropedit=lambda *args: language_calls.append(args),
            )
            owner = SimpleNamespace(
                track_selection_config={},
                t=lambda text: text,
                _progress=lambda *args, **kwargs: None,
                _set_dovi_mux_plan_for_mpls=lambda path: None,
                _dovi_mux_plan=None,
                _mkvmerge_identify_covers_remux_slots=lambda *args: True,
                _run_shell_command_detailed=lambda command: (2, [2]),
                _try_remux_mpls_split_outputs_track_aligned=lambda *args, **kwargs: False,
                _try_remux_mpls_track_aligned=fallback,
            )

            chapter = SimpleNamespace(in_out_time=[('00001', 0, 45000)])
            with patch.object(remux_service_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    remux_service_module, 'Chapter', return_value=chapter):
                result = RemuxEpisodeWorkflowsMixin._build_main_episode_mkvs(owner, [job])

            self.assertEqual(result, [str(expected_output)])
            self.assertEqual(len(language_calls), 1)
            self.assertEqual(language_calls[0][0], str(expected_output))
            self.assertEqual(language_calls[0][4], {'1': 'jpn'})

    def test_track_language_overrides_are_written_with_mkvpropedit_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            m2ts_path = root / '00001.m2ts'
            output_path = root / 'Episode.mkv'
            executable = root / 'mkvpropedit.exe'
            m2ts_path.write_bytes(b'm2ts')
            output_path.write_bytes(b'mkv')
            executable.write_bytes(b'exe')
            source_streams = [
                {'index': '0', 'codec_type': 'video', 'pid': 0x1011},
                {'index': '1', 'codec_type': 'audio', 'pid': 0x1100},
                {'index': '2', 'codec_type': 'audio', 'pid': 0x1101},
                {'index': '3', 'codec_type': 'subtitle', 'pid': 0x1200},
            ]
            before_tracks = [
                {'id': 0, 'type': 'video', 'properties': {'language': 'und'}},
                {'id': 1, 'type': 'audio', 'properties': {'language': 'eng'}},
                {'id': 2, 'type': 'audio', 'properties': {'language': 'eng'}},
                {'id': 3, 'type': 'subtitles', 'properties': {'language': 'eng'}},
            ]
            after_tracks = [
                {'id': 0, 'type': 'video', 'properties': {'language': 'eng'}},
                {'id': 1, 'type': 'audio', 'properties': {'language': 'jpn'}},
                {'id': 2, 'type': 'audio', 'properties': {'language': 'eng'}},
                {'id': 3, 'type': 'subtitles', 'properties': {'language': 'chi'}},
            ]
            identify = Mock(side_effect=[
                {'tracks': before_tracks},
                {'tracks': after_tracks},
            ])
            fake_service_class = SimpleNamespace(
                _m2ts_track_streams=lambda path: source_streams,
                _stream_service_id=lambda stream: int(stream['pid']),
                _mkvmerge_identify_json=identify,
            )
            run = Mock(return_value=SimpleNamespace(returncode=0, stdout='', stderr=''))

            with patch.object(track_mapping_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_mapping_module, 'find_mkvtoolnix'), patch.object(
                    track_mapping_module, 'get_mkvtoolnix_ui_language', return_value='en'), patch.object(
                    track_mapping_module.core_settings, 'MKV_PROP_EDIT_PATH', str(executable)), patch.object(
                    track_mapping_module.subprocess, 'run', run):
                MediaInfoTrackMappingMixin._fix_output_track_languages_with_mkvpropedit(
                    str(output_path),
                    str(m2ts_path),
                    ['1', '2'],
                    ['3'],
                    {'0': 'eng', '1': 'jpn', '2': 'eng', '3': 'chi'},
                )

            command = run.call_args.args[0]
            self.assertEqual(command[:4], [str(executable), '--ui-language', 'en', str(output_path)])
            self.assertIn(['--edit', 'track:1', '--set', 'language=eng'], [
                command[index:index + 4] for index in range(len(command) - 3)
            ])
            self.assertIn(['--edit', 'track:2', '--set', 'language=jpn'], [
                command[index:index + 4] for index in range(len(command) - 3)
            ])
            self.assertIn(['--edit', 'track:4', '--set', 'language=chi'], [
                command[index:index + 4] for index in range(len(command) - 3)
            ])
            self.assertEqual(identify.call_count, 2)

    def test_finalization_uses_exact_planned_name_and_task_local_chapter_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            expected_output = root / 'temporary.mkv'
            final_output = root / 'Visible Name.mkv'
            expected_output.write_bytes(b'mkv')
            mpls_path = root / '00001.mpls'
            mpls_path.write_bytes(b'mpls')
            job = RemuxMainJob(
                configuration_keys=(0,),
                configurations=({'selected_mpls': str(mpls_path.with_suffix('')), 'bdmv_index': 1},),
                bdmv_index=1,
                command='mkvmerge -o temporary.mkv 00001.mpls',
                m2ts_file='',
                volume='001',
                primary_output=str(expected_output),
                mpls_path=str(mpls_path),
                audio_tracks=(),
                subtitle_tracks=(),
                expected_outputs=(str(expected_output),),
                final_outputs=(str(final_output),),
            )

            def write_chapter(_mpls, _start, _end, chapter_path) -> None:
                Path(chapter_path).write_text(
                    'CHAPTER01=00:00:00.000\nCHAPTER01NAME=Chapter 01\n',
                    encoding='utf-8-sig',
                )

            owner = SimpleNamespace(configuration={0: dict(job.configurations[0])},
                                    _write_remux_segment_chapter_txt=write_chapter)
            fake_service_class = SimpleNamespace(
                _remux_parsed_chapter_bounds_for_theory_count=lambda *args: None,
                _series_episode_segments_bounds=lambda *args: [(1, 2)],
            )
            with patch.object(remux_service_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    remux_service_module, 'Chapter', return_value=_FakeChapter()), patch.object(
                    remux_service_module, 'MKV', _FakeMkv):
                result = RemuxEpisodeWorkflowsMixin._post_remux_finalize_episodes(owner, [job], None)

            self.assertEqual(result, [str(final_output)])
            self.assertTrue(final_output.is_file())
            self.assertFalse(expected_output.exists())
            self.assertEqual(len(_FakeMkv.writes), 1)
            self.assertTrue(_FakeMkv.writes[0][1])
            self.assertFalse(os.path.exists(_FakeMkv.writes[0][2]))


if __name__ == '__main__':
    unittest.main()
