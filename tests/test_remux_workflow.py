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

from src.runtime.audio_conversion import AudioEncodingSettings
from src.runtime.remux import RemuxMainJob, RemuxRequest
from src.runtime.services import BluraySubtitle  # Import the composed service before its split mixins.
from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI  # noqa: F401
from src.runtime.gui_runtime_split import remux_and_episode_layout as remux_gui_module
from src.runtime.gui_runtime_split.remux_and_episode_layout import RemuxEpisodeLayoutMixin
from src.runtime.services_split import lifecycle_and_configuration as lifecycle_module
from src.runtime.services_split import remux_and_episode_workflows as remux_service_module
from src.runtime.services_split import media_info_and_track_mapping as track_mapping_module
from src.runtime.services_split.lifecycle_and_configuration import LifecycleConfigurationMixin
from src.runtime.services_split.media_info_and_track_mapping import MediaInfoTrackMappingMixin
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin
from tests._gui_worker_fakes import FakeThread as _FakeThread
from tests._gui_worker_fakes import RequestWorkerCapture


class _FakeWorker(RequestWorkerCapture):
    signal_names = (
        'progress', 'label', 'finished', 'finished_with_warnings', 'canceled', 'failed',
    )


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
            audio_encoding = AudioEncodingSettings(
                flac_compression_level=5,
                ffmpeg_flac_compression_level=11,
                fdkaac_bitrate_kbps=256,
                opus_bitrate_kbps=160,
            )
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
                remux_flac_checkbox=SimpleNamespace(isChecked=lambda: True),
                _app_config=SimpleNamespace(
                    remux=SimpleNamespace(
                        convert_immersive_audio_to_flac=True,
                        allow_partial_missing_non_video_tracks=True,
                    ),
                ),
                _sp_scan_in_progress=True,
                _current_encode_lossless_audio_codec=lambda: 'opus',
                _captured_audio_encoding_settings=lambda: audio_encoding,
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
            self.assertTrue(request.convert_lossless_audio_to_flac)
            self.assertTrue(request.convert_immersive_audio_to_flac)
            self.assertTrue(request.allow_partial_missing_non_video_tracks)
            self.assertTrue(request.clean_audio_tracks)
            self.assertTrue(request.movie_mode)
            self.assertEqual(request.audio_encoding, audio_encoding)
            self.assertFalse(hasattr(request, 'default_lossless_audio_codec'))
            self.assertIsNot(request.configuration, configuration)

    def test_remux_flac_conversion_runs_after_main_and_sp_outputs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            main_output = root / 'Episode.mkv'
            sp_output = root / 'SP.mka'
            subtitle = root / 'Episode.ass'
            subtitle.write_text('subtitle', encoding='utf-8')
            request = replace(
                self._request(root, {0: {}}, [], ['Episode.mkv']),
                subtitle_files=(str(subtitle),),
                episode_subtitle_languages=('jpn',),
                convert_lossless_audio_to_flac=True,
                convert_immersive_audio_to_flac=True,
            )
            owner = SimpleNamespace(
                _prepare_remux_main_jobs=lambda _request: (str(root), []),
                _prepare_sp_jobs=lambda *_args: [],
                _build_main_episode_mkvs=lambda *_args, **_kwargs: [],
                _post_remux_finalize_episodes=lambda *_args: [str(main_output)],
                _build_sp_outputs=lambda *_args, **_kwargs: [
                    (1, str(main_output)),
                    (2, str(sp_output)),
                ],
                _progress=lambda *_args, **_kwargs: None,
                completion=Mock(),
                t=lambda text: text,
            )

            with patch.object(
                    remux_service_module,
                    'validate_audio_cleanup_tools',
            ), patch.object(
                    remux_service_module,
                    'validate_audio_conversion_tools',
            ) as validate_tools, patch.object(
                    remux_service_module,
                    'mux_with_audio_conversion',
            ) as convert_audio:
                RemuxEpisodeWorkflowsMixin.episodes_remux(owner, request)

            self.assertEqual(
                [call.args[0] for call in convert_audio.call_args_list],
                [str(main_output), str(sp_output)],
            )
            self.assertEqual(convert_audio.call_args_list[0].kwargs['subtitle_file'], str(subtitle))
            self.assertEqual(convert_audio.call_args_list[0].kwargs['subtitle_language'], 'jpn')
            self.assertEqual(convert_audio.call_args_list[1].kwargs['subtitle_file'], '')
            self.assertEqual(convert_audio.call_args_list[1].kwargs['subtitle_language'], '')
            self.assertEqual(validate_tools.call_count, 2)
            for call in validate_tools.call_args_list:
                self.assertTrue(call.kwargs['convert_all_lossless_to_flac'])
                self.assertTrue(call.kwargs['convert_immersive_audio_to_flac'])
            for call in convert_audio.call_args_list:
                self.assertTrue(call.kwargs['convert_immersive_audio_to_flac'])
                self.assertEqual(call.kwargs['wave64_bit_depth'], 24)
            owner.completion.assert_called_once_with()

    def test_remux_flac_disabled_still_runs_automatic_audio_cleanup(self) -> None:
        request = replace(
            self._request(Path('root'), {0: {}}, [], ['Episode.mkv']),
            convert_lossless_audio_to_flac=False,
        )
        owner = SimpleNamespace(
            _prepare_remux_main_jobs=lambda _request: ('output', []),
            _prepare_sp_jobs=lambda *_args: [],
            _build_main_episode_mkvs=lambda *_args, **_kwargs: [],
            _post_remux_finalize_episodes=lambda *_args: ['Episode.mkv'],
            _build_sp_outputs=lambda *_args, **_kwargs: [],
            _progress=lambda *_args, **_kwargs: None,
            completion=Mock(),
            t=lambda text: text,
        )

        with patch.object(
                remux_service_module,
                'validate_audio_cleanup_tools',
        ) as validate_cleanup, patch.object(
                remux_service_module,
                'validate_audio_conversion_tools',
        ) as validate_tools, patch.object(
                remux_service_module,
                'mux_with_audio_conversion',
        ) as convert_audio:
            RemuxEpisodeWorkflowsMixin.episodes_remux(owner, request)

        validate_cleanup.assert_called_once_with()
        validate_tools.assert_called_once_with(
            'Episode.mkv',
            None,
            (),
            convert_all_lossless_to_flac=False,
            convert_immersive_audio_to_flac=False,
        )
        convert_audio.assert_called_once_with(
            'Episode.mkv',
            'Episode.mkv',
            selected_audio_tracks=None,
            selected_subtitle_tracks=None,
            audio_codec_choices=(),
            convert_all_lossless_to_flac=False,
            convert_immersive_audio_to_flac=False,
            clean_audio_tracks=True,
            subtitle_file='',
            subtitle_language='',
            audio_encoding=request.audio_encoding,
            wave64_bit_depth=24,
            audio_timeline_by_track={},
            audio_timeline_duration_seconds=None,
            write_audio_gaps=True,
        )
        owner.completion.assert_called_once_with()

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

    def test_gui_command_preview_keeps_nested_disc_root_before_configuration_exists(self) -> None:
        top_folder = os.path.normpath(r'E:\BDMV\[BDMV] Series')
        disc_root = os.path.join(top_folder, 'Disc 1', 'BD_VIDEO')
        mpls_path = os.path.join(disc_root, 'BDMV', 'PLAYLIST', '00003.mpls')
        expected_command = f'mkvmerge "{mpls_path}"'
        service = SimpleNamespace(
            _make_main_mpls_remux_cmd=Mock(return_value=(
                expected_command,
                os.path.join(disc_root, 'BDMV', 'STREAM', '00003.m2ts'),
                '001',
                os.path.normpath(r'E:\Output\Series.mkv'),
                mpls_path,
                [],
                [],
            )),
        )
        owner = SimpleNamespace(
            _last_configuration_34={},
            _remux_dst_folder_for_cmd_template=lambda _root: os.path.normpath(r'E:\Output'),
            _is_movie_mode=lambda: True,
            _track_selection_config={},
            bdmv_folder_path=SimpleNamespace(text=lambda: top_folder),
        )

        with patch.object(remux_gui_module, 'find_mkvtoolnix'), patch.object(
                remux_gui_module, 'BluraySubtitle', return_value=service):
            command = RemuxEpisodeLayoutMixin._build_main_remux_cmd_template(
                owner,
                mpls_path,
                1,
                disc_root,
            )

        preview_configuration = service._make_main_mpls_remux_cmd.call_args.args[0][0]
        self.assertEqual(command, expected_command)
        self.assertEqual(preview_configuration['folder'], disc_root)
        self.assertEqual(
            MediaInfoTrackMappingMixin._resolve_mpls_path_from_conf(
                preview_configuration,
                top_folder,
            ),
            mpls_path,
        )

    def test_dolby_vision_command_preview_probe_is_silent(self) -> None:
        detected_plan = {
            'bl_pid': 0x1011,
            'el_pid': 0x1015,
            'active': True,
            'mux_enabled': True,
        }
        service_class = SimpleNamespace(
            _probe_m2ts_for_remux_source=lambda _path: ('00000.m2ts', '00000.mpls'),
            detect_dovi_mux_pair=lambda *_args: detected_plan,
        )
        owner = SimpleNamespace(mux_dolby_vision=True, _dovi_mux_plan=None, t=lambda text: text)

        with patch.object(track_mapping_module, '_svc_cls', return_value=service_class), patch(
                'builtins.print') as print_mock:
            MediaInfoTrackMappingMixin._set_dovi_mux_plan_for_mpls(owner, '00000.mpls')
            print_mock.assert_not_called()
            MediaInfoTrackMappingMixin._set_dovi_mux_plan_for_mpls(
                owner, '00000.mpls', report_detected_pair=True
            )

        self.assertIs(owner._dovi_mux_plan, detected_plan)
        print_mock.assert_called_once_with(
            'MPLS Dolby Vision pair BL=0x1011 EL=0x1015; mux enabled: True'
        )

    def test_main_command_preview_uses_track_placeholders_without_identify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mpls_path = root / 'Disc' / 'BDMV' / 'PLAYLIST' / '00001.mpls'
            mpls_path.parent.mkdir(parents=True)
            mpls_path.write_bytes(b'mpls')
            service = object.__new__(BluraySubtitle)
            service.bdmv_path = str(root / 'Disc')
            service.movie_mode = True
            service.track_selection_config = {
                f'main::{os.path.normpath(str(mpls_path))}': {
                    'video': ['4113'],
                    'audio': ['4352'],
                    'subtitle': ['4768'],
                },
            }
            service._resolve_disc_output_name = lambda _stem: 'Movie'
            configuration = [{
                'selected_mpls': str(mpls_path),
                'main_remux_cmd': (
                    'mkvmerge -d 9 --audio-tracks=8 -S -o "{output_file}" '
                    '"{mpls_path}"'
                ),
            }]
            chapter = SimpleNamespace(in_out_time=[('00001', 0, 45000)])

            with patch.object(remux_service_module, 'Chapter', return_value=chapter), patch.object(
                    remux_service_module, 'find_mkvtoolnix'), patch.object(
                    MediaInfoTrackMappingMixin, '_mkvmerge_identify_json',
                    side_effect=AssertionError('identify must not run while building the preview')):
                command, *_rest = service._make_main_mpls_remux_cmd(
                    configuration,
                    str(root / 'Output'),
                    1,
                    1,
                )

            self.assertIn('{video_opts} {audio_opts} {sub_opts}', command)
            self.assertNotIn('-d 9', command)
            self.assertNotIn('--audio-tracks=8', command)
            self.assertNotIn(' -S ', command)

    def test_disc_title_language_comes_from_mpls_without_first_m2ts_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / 'Disc'
            mpls_path = root / 'BDMV' / 'PLAYLIST' / '00001.mpls'
            meta_folder = root / 'BDMV' / 'META' / 'DL'
            mpls_path.parent.mkdir(parents=True)
            meta_folder.mkdir(parents=True)
            mpls_path.write_bytes(b'mpls')
            xml_template = '<discinfo xmlns="urn:BDA:bdmv;discinfo"><name>{}</name></discinfo>'
            (meta_folder / 'bdmt_jpn.xml').write_text(
                xml_template.format('Japanese title'), encoding='utf-8'
            )
            (meta_folder / 'bdmt_eng.xml').write_text(
                xml_template.format('English title'), encoding='utf-8'
            )
            parser = SimpleNamespace(get_tracks_info=lambda: [
                {'codec_type': 'audio', 'language': 'jpn'},
            ])

            with patch.object(lifecycle_module, 'MPLS', return_value=parser):
                title = LifecycleConfigurationMixin.resolve_disc_output_title(
                    str(root), '00001'
                )

            self.assertEqual(title, 'Japanese title')

    def test_main_track_placeholders_resolve_from_selected_pids(self) -> None:
        identification = {'tracks': [
            {'id': 0, 'type': 'video', 'properties': {'stream_id': 0x1011}},
            {'id': 2, 'type': 'audio', 'properties': {'stream_id': 0x1100}},
            {'id': 7, 'type': 'subtitles', 'properties': {'stream_id': 0x12A2}},
        ]}
        command = 'mkvmerge {video_opts} {audio_opts} {sub_opts} -o output.mkv input.mpls'

        with patch.object(track_mapping_module, '_svc_cls', return_value=MediaInfoTrackMappingMixin):
            resolved = MediaInfoTrackMappingMixin._resolve_main_remux_track_placeholders(
                command,
                [('video', 0x1011), ('audio', 0x1100), ('subtitles', 0x12A2)],
                identification,
            )

        self.assertEqual(
            resolved,
            'mkvmerge -d 0 -a 2 -s 7 -o output.mkv input.mpls',
        )

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
                track_selection_config={
                    f'main::{os.path.normpath(str(first))}': {'audio': ['1']},
                },
                track_language_config={
                    f'main::{os.path.normpath(str(first))}': {'1': 'jpn'},
                },
            )

            track_row = {
                'index': '1', 'pid': 1, 'codec_type': 'audio', 'language': 'eng',
                '_mpls_source_path': os.path.normpath(str(first)),
                '_mpls_bucket': 'PrimaryAudioStreamEntries', '_mpls_slot_index': 0,
                '_mpls_append_compatible': True,
            }
            with patch.object(BluraySubtitle, '_mpls_track_streams', return_value=[track_row]), patch.object(
                    remux_service_module, 'find_mkvtoolnix'), patch.object(
                    remux_service_module.core_settings, 'MKV_PROP_EDIT_PATH', str(first)):
                _destination, jobs = RemuxEpisodeWorkflowsMixin._prepare_remux_main_jobs(
                    self._planning_owner(root), request
                )

            self.assertEqual([Path(job.mpls_path).name for job in jobs], ['00001.mpls', '00002.mpls'])
            self.assertEqual([job.configuration_keys for job in jobs], [(0,), (1,)])
            self.assertEqual([Path(job.final_outputs[0]).name for job in jobs], ['First.mkv', 'Second.mkv'])
            self.assertEqual(
                jobs[0].track_language_overrides,
                (('mpls-slot::00001.mpls::PrimaryAudioStreamEntries::0', 'jpn'),),
            )
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
                track_selection_config={
                    f'main::{os.path.normpath(str(playlist))}': {'audio': ['1']},
                },
                track_language_config={
                    f'main::{os.path.normpath(str(playlist))}': {'1': 'jpn'},
                },
            )

            track_row = {
                'index': '1', 'pid': 1, 'codec_type': 'audio', 'language': 'eng',
                '_mpls_source_path': os.path.normpath(str(playlist)),
                '_mpls_bucket': 'PrimaryAudioStreamEntries', '_mpls_slot_index': 0,
                '_mpls_append_compatible': True,
            }
            with patch.object(BluraySubtitle, '_mpls_track_streams', return_value=[track_row]), patch.object(
                    remux_service_module, 'find_mkvtoolnix'), patch.object(
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

    def test_missing_selected_subtitle_fails_during_planning(self) -> None:
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
                }
            }
            missing_subtitle = root / 'missing.ass'
            request = replace(
                self._request(
                    root,
                    configuration,
                    [(str(root / 'Disc'), str(playlist.with_suffix('')))],
                    ['Episode.mkv'],
                ),
                subtitle_files=(str(missing_subtitle),),
            )

            with self.assertRaisesRegex(FileNotFoundError, 'Subtitle file does not exist'):
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
                track_pids=(('video', 0x1011),),
            )
            owner = SimpleNamespace(
                track_selection_config={},
                _validate_mpls_tracks_for_execution=lambda _path, slots, **_kwargs: list(slots),
                t=lambda text: text,
                _progress=lambda *args, **kwargs: None,
                _set_dovi_mux_plan_for_mpls=Mock(),
                _mkvmerge_identify_covers_remux_slots=lambda *args, **kwargs: True,
                _run_shell_command_detailed=lambda command: (2, [2]),
                _try_remux_mpls_split_outputs_track_aligned=lambda *args, **kwargs: False,
                _try_remux_mpls_track_aligned=lambda *args, **kwargs: False,
            )
            fake_service_class = SimpleNamespace(
                _mkvmerge_identify_json=lambda _path: {'tracks': []},
                _mkvmerge_pid_id_map=lambda *_args: {('video', 0x1011): 0},
                _resolve_main_remux_track_placeholders=lambda command, *_args: command,
            )

            with patch.object(remux_service_module, '_svc_cls', return_value=fake_service_class):
                with self.assertRaisesRegex(RuntimeError, 'Main remux failed'):
                    RemuxEpisodeWorkflowsMixin._build_main_episode_mkvs(owner, [job])

            owner._set_dovi_mux_plan_for_mpls.assert_called_once_with(
                str(mpls_path), report_detected_pair=True
            )
            self.assertFalse(expected_output.exists())

    def test_mpls_pid_change_uses_logical_slot_and_stn_gap_enters_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            playlist_dir = root / 'BDMV' / 'PLAYLIST'
            stream_dir = root / 'BDMV' / 'STREAM'
            playlist_dir.mkdir(parents=True)
            stream_dir.mkdir(parents=True)
            mpls_path = playlist_dir / '00002.mpls'
            first_m2ts = stream_dir / '00002.m2ts'
            second_m2ts = stream_dir / '00003.m2ts'
            for path in (mpls_path, first_m2ts, second_m2ts):
                path.write_bytes(b'media')
            mpls_identification = {'tracks': [
                {'id': 0, 'type': 'video', 'properties': {'stream_id': 0x1011}},
                {'id': 1, 'type': 'audio', 'properties': {'stream_id': 0x1100}},
            ]}
            chapter = SimpleNamespace(in_out_time=[
                ('00002', 0, 45000),
                ('00003', 0, 45000),
            ])
            owner = SimpleNamespace(_dovi_mux_plan=None)
            logical_rows = [
                {
                    'pid': 0x1011,
                    '_logical_type': 'video',
                    '_logical_pid': 0x1011,
                    '_mpls_occurrences': (
                        {'pid': 0x1011, 'codec_type': 'video'},
                        {'pid': 0x1011, 'codec_type': 'video'},
                    ),
                },
                {
                    'pid': 0x1100,
                    '_logical_type': 'audio',
                    '_logical_pid': 0x1100,
                    '_mpls_occurrences': (
                        {'pid': 0x1100, 'codec_type': 'audio'},
                        {'pid': 0x1101, 'codec_type': 'audio'},
                    ),
                },
            ]

            def identify(path):
                if os.path.normpath(path) == os.path.normpath(mpls_path):
                    return mpls_identification
                audio_pid = 0x1100 if os.path.normpath(path) == os.path.normpath(first_m2ts) else 0x1101
                return {'tracks': [
                    {'id': 0, 'type': 'video', 'properties': {'stream_id': 0x1011}},
                    {'id': 1, 'type': 'audio', 'properties': {'stream_id': audio_pid}},
                ]}

            with patch.object(track_mapping_module, '_svc_cls', return_value=MediaInfoTrackMappingMixin), patch.object(
                    track_mapping_module, 'Chapter', return_value=chapter), patch.object(
                    MediaInfoTrackMappingMixin, '_mpls_logical_slots_for_selection',
                    return_value=(logical_rows, [])), patch.object(
                    MediaInfoTrackMappingMixin, '_mkvmerge_identify_json', side_effect=identify):
                result = MediaInfoTrackMappingMixin._mkvmerge_identify_covers_mpls_pid_slots(
                    owner,
                    str(mpls_path),
                    [('video', 0x1011), ('audio', 0x1100)],
                )

                self.assertTrue(result)
                logical_rows[1]['_mpls_occurrences'] = (
                    {'pid': 0x1100, 'codec_type': 'audio'}, None,
                )
                result_with_gap = MediaInfoTrackMappingMixin._mkvmerge_identify_covers_mpls_pid_slots(
                    owner,
                    str(mpls_path),
                    [('video', 0x1011), ('audio', 0x1100)],
                )

            self.assertFalse(result_with_gap)

    def test_alternate_mpls_track_uses_direct_input_when_identify_exposes_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            playlist_dir = root / 'BDMV' / 'PLAYLIST'
            stream_dir = root / 'BDMV' / 'STREAM'
            playlist_dir.mkdir(parents=True)
            stream_dir.mkdir(parents=True)
            main_mpls = playlist_dir / '00001.mpls'
            alternate_mpls = playlist_dir / '00002.mpls'
            m2ts = stream_dir / '00001.m2ts'
            for path in (main_mpls, alternate_mpls, m2ts):
                path.write_bytes(b'media')

            identification = {'tracks': [
                {'id': 0, 'type': 'video', 'properties': {'stream_id': 0x1011}},
                {'id': 1, 'type': 'audio', 'properties': {'stream_id': 0x1100}},
                {'id': 2, 'type': 'audio', 'properties': {'stream_id': 0x1101}},
            ]}
            logical_rows = [
                {
                    '_logical_type': 'video',
                    '_logical_pid': 0x1011,
                    '_mpls_source_path': str(main_mpls),
                    '_mpls_occurrences': (
                        {'pid': 0x1011, 'codec_type': 'video'},
                    ),
                },
                {
                    '_logical_type': 'audio',
                    '_logical_pid': 0x1100,
                    '_mpls_source_path': str(main_mpls),
                    '_mpls_occurrences': (
                        {'pid': 0x1100, 'codec_type': 'audio'},
                    ),
                },
                {
                    '_logical_type': 'audio',
                    '_logical_pid': 0x1101,
                    '_mpls_source_path': str(alternate_mpls),
                    '_mpls_occurrences': (
                        {'pid': 0x1101, 'codec_type': 'audio'},
                    ),
                },
            ]
            owner = SimpleNamespace(_dovi_mux_plan=None)
            chapter = SimpleNamespace(in_out_time=[('00001', 0, 45000)])

            with patch.object(
                    track_mapping_module, '_svc_cls', return_value=MediaInfoTrackMappingMixin
            ), patch.object(
                    track_mapping_module, 'Chapter', return_value=chapter
            ), patch.object(
                    MediaInfoTrackMappingMixin,
                    '_mpls_logical_slots_for_selection',
                    return_value=(logical_rows, []),
            ), patch.object(
                    MediaInfoTrackMappingMixin,
                    '_mkvmerge_identify_json',
                    return_value=identification,
            ):
                result = MediaInfoTrackMappingMixin._mkvmerge_identify_covers_mpls_pid_slots(
                    owner,
                    str(main_mpls),
                    [('video', 0x1011), ('audio', 0x1100), ('audio', 0x1101)],
                    identification=identification,
                    alternate_mpls_paths=(str(alternate_mpls),),
                )

            self.assertTrue(result)

    def test_empty_output_track_is_reported_from_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / 'Episode.mkv'
            output.write_bytes(b'media')
            slots = [
                {'type': 'video', 'pid': 0x1011, 'index': '0'},
                {'type': 'audio', 'pid': 0x1100, 'index': '1'},
                {'type': 'subtitles', 'pid': 0x1200, 'index': '4'},
            ]
            identification = {'tracks': [
                {'id': 0, 'type': 'video', 'properties': {'uid': 10}},
                {'id': 1, 'type': 'audio', 'properties': {'uid': 11}},
                {'id': 2, 'type': 'subtitles', 'properties': {'uid': 12}},
            ]}
            tags = '''<?xml version="1.0"?>
<Tags>
  <Tag><Targets><TrackUID>10</TrackUID></Targets><Simple><Name>NUMBER_OF_FRAMES</Name><String>100</String></Simple><Simple><Name>NUMBER_OF_BYTES</Name><String>1000</String></Simple></Tag>
  <Tag><Targets><TrackUID>11</TrackUID></Targets><Simple><Name>NUMBER_OF_FRAMES</Name><String>100</String></Simple><Simple><Name>NUMBER_OF_BYTES</Name><String>1000</String></Simple></Tag>
  <Tag><Targets><TrackUID>12</TrackUID></Targets><Simple><Name>NUMBER_OF_FRAMES</Name><String>0</String></Simple><Simple><Name>NUMBER_OF_BYTES</Name><String>0</String></Simple></Tag>
</Tags>'''

            with patch.object(track_mapping_module, '_svc_cls', return_value=MediaInfoTrackMappingMixin), patch.object(
                    track_mapping_module, 'find_mkvtoolnix'), patch.object(
                    track_mapping_module, 'run_command', return_value=SimpleNamespace(
                        returncode=0, stdout=tags, stderr=''
                    )), patch.object(
                    MediaInfoTrackMappingMixin, '_mkvmerge_identify_json',
                    return_value=identification):
                warnings = MediaInfoTrackMappingMixin._remux_output_track_warnings(
                    str(output),
                    None,
                    [(str(slot['type']), int(slot['pid'])) for slot in slots],
                )

            self.assertEqual(len(warnings), 1)
            self.assertIn('track ID 2', warnings[0])

    def test_track_validation_failure_is_collected_without_failing_remux(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mpls_path = root / '00001.mpls'
            expected_output = root / 'expected.mkv'
            mpls_path.write_bytes(b'mpls')
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
                track_pids=(('video', 0x1011),),
            )

            def primary(_command):
                expected_output.write_bytes(b'mkv')
                return 0, [0]

            owner = SimpleNamespace(
                track_selection_config={},
                remux_warnings=[],
                _validate_mpls_tracks_for_execution=lambda _path, slots, **_kwargs: list(slots),
                t=lambda text: text,
                _progress=lambda *args, **kwargs: None,
                _set_dovi_mux_plan_for_mpls=lambda _path, **_kwargs: None,
                _dovi_mux_plan=None,
                _mkvmerge_identify_covers_remux_slots=lambda *args, **kwargs: True,
                _run_shell_command_detailed=primary,
                _try_remux_mpls_split_outputs_track_aligned=lambda *args, **kwargs: False,
                _try_remux_mpls_track_aligned=lambda *args, **kwargs: False,
                _remux_output_track_warnings=Mock(side_effect=RuntimeError('probe failed')),
            )
            fake_service_class = SimpleNamespace(
                _mkvmerge_identify_json=lambda _path: {'tracks': []},
                _mkvmerge_pid_id_map=lambda *_args: {('video', 0x1011): 0},
                _resolve_main_remux_track_placeholders=lambda command, *_args: command,
            )

            with patch.object(remux_service_module, '_svc_cls', return_value=fake_service_class):
                result = RemuxEpisodeWorkflowsMixin._build_main_episode_mkvs(owner, [job])

            self.assertEqual(result, [str(expected_output)])
            self.assertEqual(len(owner.remux_warnings), 1)
            self.assertIn('probe failed', owner.remux_warnings[0])

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
                track_pids=(('video', 0x1011), ('audio', 0x1100)),
            )
            language_calls = []

            def fallback(*_args, **_kwargs) -> bool:
                expected_output.write_bytes(b'mkv')
                return True

            fake_service_class = SimpleNamespace(
                _mkvmerge_identify_json=lambda _path: {'tracks': []},
                _mkvmerge_pid_id_map=lambda *_args: {
                    ('video', 0x1011): 0,
                    ('audio', 0x1100): 1,
                },
                _resolve_main_remux_track_placeholders=lambda command, *_args: command,
                _fix_output_track_languages_with_mkvpropedit=(
                    lambda *args, **_kwargs: language_calls.append(args)
                ),
            )
            owner = SimpleNamespace(
                track_selection_config={},
                _validate_mpls_tracks_for_execution=lambda _path, slots, **_kwargs: list(slots),
                t=lambda text: text,
                _progress=lambda *args, **kwargs: None,
                _set_dovi_mux_plan_for_mpls=lambda _path, **_kwargs: None,
                _dovi_mux_plan=None,
                _mkvmerge_identify_covers_remux_slots=lambda *args, **kwargs: True,
                _run_shell_command_detailed=lambda command: (2, [2]),
                _try_remux_mpls_split_outputs_track_aligned=lambda *args, **kwargs: False,
                _try_remux_mpls_track_aligned=fallback,
                _remux_output_track_warnings=lambda *args, **kwargs: [],
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
                {
                    'id': 3,
                    'type': 'subtitles',
                    'properties': {'language': 'chi', 'language_ietf': 'zh'},
                },
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
                    {'0': 'eng', '1': 'jpn', '2': 'eng', '3': 'zho'},
                )

            command = run.call_args.args[0]
            self.assertEqual(command[:4], [str(executable), '--ui-language', 'en', str(output_path)])
            self.assertIn(['--edit', 'track:1', '--set', 'language=eng'], [
                command[index:index + 4] for index in range(len(command) - 3)
            ])
            self.assertIn(['--edit', 'track:2', '--set', 'language=jpn'], [
                command[index:index + 4] for index in range(len(command) - 3)
            ])
            self.assertIn(['--edit', 'track:4', '--set', 'language=zho'], [
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
