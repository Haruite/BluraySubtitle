"""Focused tests for the explicit Blu-ray Remux request and output plan."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.runtime.remux import RemuxMainJob, RemuxRequest
from src.runtime.services import BluraySubtitle  # Import the composed service before its split mixins.
from src.runtime.services_split import remux_and_episode_workflows as remux_service_module
from src.runtime.services_split import media_info_and_track_mapping as track_mapping_module
from src.runtime.services_split.media_info_and_track_mapping import MediaInfoTrackMappingMixin
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin


class RemuxWorkflowTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
