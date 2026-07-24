"""Focused contracts for SP planning, execution, and track-aligned repair."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.remux import RemuxMainJob
from src.runtime.services import BluraySubtitle as _BluraySubtitle
from src.runtime.sp import SpEntry, SpJob
from src.runtime.services_split.media_info_and_track_mapping import MediaInfoTrackMappingMixin
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin
from src.runtime.services_split.subtitle_and_chapter_pipeline import SubtitleChapterPipelineMixin
from src.runtime.services_split import media_info_and_track_mapping as track_module
from src.runtime.services_split import remux_and_episode_workflows as remux_module
from src.runtime.services_split import subtitle_and_chapter_pipeline as sp_module


def _disc(root: Path) -> tuple[Path, Path]:
    playlist = root / 'BDMV' / 'PLAYLIST'
    stream = root / 'BDMV' / 'STREAM'
    playlist.mkdir(parents=True)
    stream.mkdir(parents=True)
    (playlist / '00001.mpls').write_bytes(b'mpls')
    (playlist / '00002.mpls').write_bytes(b'mpls')
    (stream / '00001.m2ts').write_bytes(b'm2ts')
    (stream / '00002.m2ts').write_bytes(b'm2ts')
    return playlist, stream


def _entry(root: Path, **changes) -> SpEntry:
    values = {
        'bdmv_index': 1,
        'bdmv_root': str(root),
        'mpls_file': '00002.mpls',
        'm2ts_files': ('00002.m2ts',),
        'm2ts_file_detail': '',
        'm2ts_type': 'video',
        'output_name': 'SPs/Visible Name.mkv',
        'selected': True,
    }
    values.update(changes)
    return SpEntry(**values)


def _main_job(root: Path, destination: Path) -> RemuxMainJob:
    playlist = root / 'BDMV' / 'PLAYLIST' / '00001.mpls'
    return RemuxMainJob(
        configuration_keys=(0,),
        configurations=({'bdmv_index': 1, 'selected_mpls': str(playlist.with_suffix(''))},),
        bdmv_index=1,
        command='mkvmerge -o temporary.mkv 00001.mpls',
        m2ts_file=str(root / 'BDMV' / 'STREAM' / '00001.m2ts'),
        volume='001',
        primary_output=str(destination / 'temporary.mkv'),
        mpls_path=str(playlist),
        audio_tracks=('1',),
        subtitle_tracks=(),
        expected_outputs=(str(destination / 'temporary.mkv'),),
        final_outputs=(str(destination / 'EP01.mkv'),),
    )


class _PlanningService(RemuxEpisodeWorkflowsMixin):
    def _select_tracks_for_source(self, *_args, **_kwargs):
        return ['1'], ['2']


class _SpExecutionService(SubtitleChapterPipelineMixin):
    def t(self, text: str) -> str:
        return text

    @staticmethod
    def _mkvmerge_das_flag_strings_for_m2ts(*_args, **_kwargs):
        return '0', '', ''


class SpPlanningTests(unittest.TestCase):
    def test_selected_rows_keep_exact_output_tracks_and_languages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / 'Disc'
            _disc(root)
            destination = Path(temporary_directory) / 'Output'
            selected = _entry(root)
            ignored = _entry(root, selected=False, output_name='SPs/Ignored.mkv')
            empty_output = _entry(root, output_name='')
            fake_service_class = SimpleNamespace(
                _probe_m2ts_for_remux_source=lambda _path: (
                    str(root / 'BDMV' / 'STREAM' / '00002.m2ts'),
                    {},
                )
            )
            with patch.object(remux_module, '_svc_cls', return_value=fake_service_class):
                jobs = _PlanningService()._prepare_sp_jobs(
                    (selected, ignored, empty_output),
                    str(destination),
                    [_main_job(root, destination)],
                    {selected.track_key: {'audio': ['4'], 'subtitle': ['7']}},
                    {selected.track_key: {'4': 'jpn', '7': 'eng'}},
                )

            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].output_path, str(destination / 'SPs' / 'Visible Name.mkv'))
            self.assertEqual(jobs[0].audio_tracks, ('4',))
            self.assertEqual(jobs[0].subtitle_tracks, ('7',))
            self.assertEqual(dict(jobs[0].track_language_overrides), {'4': 'jpn', '7': 'eng'})

    def test_missing_captured_track_selection_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / 'Disc'
            _disc(root)
            destination = Path(temporary_directory) / 'Output'
            entry = _entry(root)
            fake_service_class = SimpleNamespace(
                _probe_m2ts_for_remux_source=lambda _path: (
                    str(root / 'BDMV' / 'STREAM' / '00002.m2ts'),
                    {},
                )
            )
            with patch.object(remux_module, '_svc_cls', return_value=fake_service_class):
                with self.assertRaisesRegex(ValueError, 'no captured track selection'):
                    _PlanningService()._prepare_sp_jobs(
                        (entry,), str(destination), [_main_job(root, destination)], {}, {}
                    )
            self.assertFalse(destination.exists())

    def test_existing_sp_output_is_rejected_during_planning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / 'Disc'
            _disc(root)
            destination = Path(temporary_directory) / 'Output'
            existing = destination / 'SPs' / 'Visible Name.mkv'
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b'existing')
            entry = _entry(root)
            fake_service_class = SimpleNamespace(
                _probe_m2ts_for_remux_source=lambda _path: (
                    str(root / 'BDMV' / 'STREAM' / '00002.m2ts'),
                    {},
                )
            )
            with patch.object(remux_module, '_svc_cls', return_value=fake_service_class):
                with self.assertRaisesRegex(FileExistsError, 'already exists'):
                    _PlanningService()._prepare_sp_jobs(
                        (entry,),
                        str(destination),
                        [_main_job(root, destination)],
                        {entry.track_key: {'audio': [], 'subtitle': []}},
                        {},
                    )
            self.assertEqual(existing.read_bytes(), b'existing')

    def test_episode_linked_sp_targets_the_planned_main_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / 'Disc'
            _disc(root)
            destination = Path(temporary_directory) / 'Output'
            entry = _entry(root, output_name='EP01.mkv')
            main_job = _main_job(root, destination)
            fake_service_class = SimpleNamespace(
                _probe_m2ts_for_remux_source=lambda _path: (
                    str(root / 'BDMV' / 'STREAM' / '00002.m2ts'),
                    {},
                )
            )
            with patch.object(remux_module, '_svc_cls', return_value=fake_service_class):
                jobs = _PlanningService()._prepare_sp_jobs(
                    (entry,),
                    str(destination),
                    [main_job],
                    {entry.track_key: {'audio': ['1'], 'subtitle': []}},
                    {},
                )
            self.assertEqual(jobs[0].output_path, main_job.final_outputs[0])
            self.assertEqual(jobs[0].episode_main_mpls_path, main_job.mpls_path)


class SpExecutionTests(unittest.TestCase):
    def test_video_only_sp_disables_unselected_audio_and_subtitles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / '00001.m2ts'
            source.write_bytes(b'm2ts')
            output = root / 'SPs' / 'Video.mkv'
            entry = _entry(root, mpls_file='', m2ts_files=('00001.m2ts',), output_name='SPs/Video.mkv')
            job = SpJob(
                entry_index=1,
                entry=entry,
                source_path=str(source),
                first_m2ts_path=str(source),
                output_path=str(output),
                main_mpls_path='',
                episode_main_mpls_path='',
                audio_tracks=(),
                subtitle_tracks=(),
                track_language_overrides=(),
            )
            commands = []

            def run(command, **_kwargs):
                commands.append(command)
                output_index = command.index('-o') + 1
                Path(command[output_index]).write_bytes(b'mkv')
                return SimpleNamespace(returncode=0)

            service = _SpExecutionService()
            with patch.object(sp_module, 'find_mkvtoolnix'), patch.object(
                    sp_module, 'MKV_MERGE_PATH', 'mkvmerge'), patch.object(
                    sp_module.subprocess, 'run', side_effect=run):
                created = service._build_sp_outputs([job])

            self.assertEqual(created, [(1, str(output))])
            self.assertIn('-A', commands[0])
            self.assertIn('-S', commands[0])

    def test_audio_container_disables_video_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / '00001.m2ts'
            source.write_bytes(b'm2ts')
            output = root / 'SPs' / 'Audio.mka'
            entry = _entry(root, mpls_file='', m2ts_files=('00001.m2ts',), output_name='SPs/Audio.mka')
            job = SpJob(
                entry_index=1,
                entry=entry,
                source_path=str(source),
                first_m2ts_path=str(source),
                output_path=str(output),
                main_mpls_path='',
                episode_main_mpls_path='',
                audio_tracks=('1',),
                subtitle_tracks=(),
                track_language_overrides=(),
            )
            commands = []

            def run(command, **_kwargs):
                commands.append(command)
                output_index = command.index('-o') + 1
                Path(command[output_index]).write_bytes(b'mka')
                return SimpleNamespace(returncode=0)

            fake_service_class = SimpleNamespace(
                _mkvmerge_das_flag_strings_for_m2ts=lambda *_args, **_kwargs: ('0', '1', ''),
            )
            with patch.object(sp_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    sp_module, 'find_mkvtoolnix'), patch.object(
                    sp_module, 'MKV_MERGE_PATH', 'mkvmerge'), patch.object(
                    sp_module.subprocess, 'run', side_effect=run):
                created = _SpExecutionService()._build_sp_outputs([job])

            self.assertEqual(created, [(1, str(output))])
            self.assertIn('-D', commands[0])
            self.assertIn('-a', commands[0])
            self.assertNotIn('-d', commands[0])
    def test_episode_linked_mux_disables_unselected_sp_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            playlist = root / 'BDMV' / 'PLAYLIST'
            stream = root / 'BDMV' / 'STREAM'
            playlist.mkdir(parents=True)
            stream.mkdir(parents=True)
            episode = root / 'EP01.mkv'
            main_mpls = playlist / '00001.mpls'
            sp_mpls = playlist / '00002.mpls'
            first_m2ts = stream / '00001.m2ts'
            for path in (episode, main_mpls, sp_mpls, first_m2ts):
                path.write_bytes(b'source')

            episode_identify = {
                'tracks': [
                    {'id': 0, 'type': 'video', 'properties': {}},
                    {'id': 1, 'type': 'audio', 'properties': {}},
                ]
            }
            sp_identify = {
                'tracks': [
                    {'id': 0, 'type': 'video', 'properties': {'stream_id': 0x1011}},
                    {'id': 1, 'type': 'audio', 'properties': {'stream_id': 0x1101}},
                    {'id': 2, 'type': 'subtitles', 'properties': {'stream_id': 0x1200}},
                ]
            }
            fake_service_class = SimpleNamespace(
                _int_from_mkvmerge_prop=lambda value: int(value) if value is not None else None,
                _mkvmerge_identify_json=lambda path: (
                    sp_identify if os.path.normpath(path) == os.path.normpath(str(sp_mpls))
                    else episode_identify
                ),
            )
            commands = []

            def run(command, **_kwargs):
                commands.append(command)
                if command[0] == 'mkvmerge':
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                    return SimpleNamespace(returncode=0)
                return SimpleNamespace(returncode=1)

            service = _SpExecutionService()
            service._compute_mkv_id_to_m2ts_pid_for_main_mpls = lambda _path: {
                0: 0x1011,
                1: 0x1100,
            }
            with patch.object(sp_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    sp_module, 'Chapter', return_value=SimpleNamespace()), patch.object(
                    sp_module, 'get_index_to_m2ts_and_offset', return_value=({1: '00001.m2ts'}, {})), patch.object(
                    sp_module, 'MKV_MERGE_PATH', 'mkvmerge'), patch.object(
                    sp_module, 'MKV_EXTRACT_PATH', 'mkvextract'), patch.object(
                    sp_module, 'mkvtoolnix_ui_language_arg', return_value=''), patch.object(
                    sp_module.subprocess, 'run', side_effect=run):
                result = service._mux_episode_linked_sp_mkvmerge(
                    episode_mkv=str(episode),
                    sp_mpls_path=str(sp_mpls),
                    episode_main_mpls=str(main_mpls),
                    cmd_audio_sp=[],
                    cmd_sub_sp=[],
                    language_by_sp_track_id={},
                    cancel_event=None,
                )

            self.assertTrue(result)
            mux_command = next(command for command in commands if command[0] == 'mkvmerge')
            sp_options = mux_command[mux_command.index(str(episode)) + 1:mux_command.index(str(sp_mpls))]
            self.assertIn('-D', sp_options)
            self.assertIn('-A', sp_options)
            self.assertIn('-S', sp_options)
            self.assertEqual(episode.read_bytes(), b'muxed')
    def test_selected_sp_command_failure_is_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / '00001.m2ts'
            source.write_bytes(b'm2ts')
            output = root / 'SPs' / 'Audio.ac3'
            entry = _entry(root, mpls_file='', m2ts_files=('00001.m2ts',), output_name='SPs/Audio.ac3')
            job = SpJob(
                entry_index=1,
                entry=entry,
                source_path=str(source),
                first_m2ts_path=str(source),
                output_path=str(output),
                main_mpls_path='',
                episode_main_mpls_path='',
                audio_tracks=('1',),
                subtitle_tracks=(),
                track_language_overrides=(),
            )
            with patch.object(
                    sp_module.subprocess, 'run', return_value=SimpleNamespace(returncode=2)):
                with self.assertRaisesRegex(RuntimeError, 'SP processing failed in row 1'):
                    _SpExecutionService()._build_sp_outputs([job])
            self.assertFalse(output.exists())


class TrackAlignmentTests(unittest.TestCase):
    def test_single_clip_uses_the_shared_track_aligned_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            playlist = root / 'BDMV' / 'PLAYLIST'
            stream = root / 'BDMV' / 'STREAM'
            playlist.mkdir(parents=True)
            stream.mkdir(parents=True)
            mpls = playlist / '00001.mpls'
            m2ts = stream / '00001.m2ts'
            output = root / 'Output.mkv'
            mpls.write_bytes(b'mpls')
            m2ts.write_bytes(b'm2ts')
            calls = []

            def remux_clip(*args, **_kwargs):
                calls.append(args[0])
                Path(args[4]).write_bytes(b'part')
                return True

            owner = SimpleNamespace(
                _dovi_mux_plan=None,
                _set_dovi_mux_plan_for_mpls=lambda _path: None,
                _remux_aligned_clip=remux_clip,
            )
            fake_service_class = SimpleNamespace(
                _detect_sp_looping_mpls=lambda _path: None,
                _ordered_track_slots_for_remux=lambda *_args, **_kwargs: [
                    {'type': 'video', 'pid': 0x1011}
                ],
                _m2ts_clip_time_window_sec=lambda *_args: (False, 0.0, 1.0),
            )
            chapter = SimpleNamespace(
                in_out_time=[('00001', 0, 45000)],
                pid_to_lang={},
                get_pid_to_language=lambda: None,
            )
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter), patch.object(
                    track_module, 'find_mkvtoolnix'), patch.object(
                    track_module, 'MKV_MERGE_PATH', 'mkvmerge'), patch.object(
                    track_module, 'mkvtoolnix_ui_language_arg', return_value=''):
                result = MediaInfoTrackMappingMixin._try_remux_mpls_track_aligned(
                    owner, str(mpls), str(output), [], [], ''
                )

            self.assertTrue(result)
            self.assertEqual(calls, [str(m2ts)])
            self.assertEqual(output.read_bytes(), b'part')
    def test_missing_audio_uses_silence_only_after_recovery_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mpls = root / '00001.mpls'
            m2ts = root / '00001.m2ts'
            output = root / 'part.mkv'
            work = root / 'work'
            mpls.write_bytes(b'mpls')
            m2ts.write_bytes(b'm2ts')
            work.mkdir()
            silence_calls = []

            def run_command(_command):
                output.write_bytes(b'video')
                return 0

            def append_silence(
                    _exe, _ui, _base_mkv, current_pids, audio_slots, _first_m2ts,
                    _duration, _work_dir, _tag, _languages, silence_output):
                silence_calls.append((list(current_pids), list(audio_slots)))
                Path(silence_output).write_bytes(b'video+silence')
                return [0x1011, 0x1100]

            owner = SimpleNamespace(
                _dovi_mux_plan=None,
                mux_dolby_vision=True,
                _run_single_command=run_command,
                _remux_fallback_append_silence_pid_order=append_silence,
            )
            fake_service_class = SimpleNamespace(
                detect_dovi_mux_pair=lambda *_args: None,
                _clip_ref_slots_for_m2ts=lambda slots, *_args: list(slots),
                _mkvmerge_identify_json=lambda _path: {},
                _mkvmerge_tid_for_pid=lambda _path, pid, _type: 0 if pid == 0x1011 else None,
                _mkvmerge_select_flags_from_mapped=lambda _ids, _ident: ('0', '', ''),
                _slot_pids_in_order=lambda slots: [int(slot['pid']) for slot in slots],
                _ref_slot_pid_set=lambda slots: {int(slot['pid']) for slot in slots},
                _run_tsmuxer_probe=lambda _path: '',
                _parse_tsmuxer_probe_output=lambda _text: [],
                _tsmuxer_mpeg_pid=lambda _track: None,
            )
            chapter = SimpleNamespace(
                pid_to_lang={},
                get_pid_to_language=lambda: None,
            )
            reference_slots = [
                {'type': 'video', 'pid': 0x1011},
                {'type': 'audio', 'pid': 0x1100},
            ]
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter):
                result = MediaInfoTrackMappingMixin._remux_aligned_clip(
                    owner,
                    str(m2ts),
                    str(mpls),
                    str(m2ts),
                    reference_slots,
                    str(output),
                    '',
                    1.0,
                    str(work),
                    'part',
                    'mkvmerge',
                    '',
                )

            self.assertTrue(result)
            self.assertEqual(len(silence_calls), 1)
            self.assertEqual(silence_calls[0][0], [0x1011])
            self.assertEqual(silence_calls[0][1][0]['pid'], 0x1100)
            self.assertEqual(output.read_bytes(), b'video+silence')

    def test_missing_non_audio_track_aborts_when_tsmuxer_cannot_supply_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mpls = root / '00001.mpls'
            m2ts = root / '00001.m2ts'
            output = root / 'part.mkv'
            work = root / 'work'
            mpls.write_bytes(b'mpls')
            m2ts.write_bytes(b'm2ts')
            work.mkdir()

            def run_command(_command):
                output.write_bytes(b'video')
                return 0

            owner = SimpleNamespace(
                _dovi_mux_plan=None,
                mux_dolby_vision=True,
                _run_single_command=run_command,
            )
            fake_service_class = SimpleNamespace(
                detect_dovi_mux_pair=lambda *_args: None,
                _clip_ref_slots_for_m2ts=lambda slots, *_args: list(slots),
                _mkvmerge_identify_json=lambda _path: {},
                _mkvmerge_tid_for_pid=lambda _path, pid, _type: 0 if pid == 0x1011 else None,
                _mkvmerge_select_flags_from_mapped=lambda _ids, _ident: ('0', '', ''),
                _slot_pids_in_order=lambda slots: [int(slot['pid']) for slot in slots],
                _ref_slot_pid_set=lambda slots: {int(slot['pid']) for slot in slots},
                _run_tsmuxer_probe=lambda _path: '',
                _parse_tsmuxer_probe_output=lambda _text: [],
                _tsmuxer_mpeg_pid=lambda _track: None,
            )
            chapter = SimpleNamespace(pid_to_lang={}, get_pid_to_language=lambda: None)
            reference_slots = [
                {'type': 'video', 'pid': 0x1011},
                {'type': 'subtitles', 'pid': 0x1200},
            ]
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter):
                result = MediaInfoTrackMappingMixin._remux_aligned_clip(
                    owner, str(m2ts), str(mpls), str(m2ts), reference_slots,
                    str(output), '', 1.0, str(work), 'part', 'mkvmerge', '',
                )

            self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
