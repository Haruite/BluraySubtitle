"""Focused contracts for SP planning, execution, and track-aligned repair."""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from dataclasses import replace
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


def _main_job(
        root: Path,
        destination: Path,
        *,
        detail: str = '',
        output_name: str = 'EP01.mkv',
) -> RemuxMainJob:
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
        final_outputs=(str(destination / output_name),),
        m2ts_file_details=(detail,),
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


def _selected_pid_slots_for_test(path, selected_tracks):
    return [
        {
            'type': track_type,
            'pid': int(pid),
            '_mpls_source_path': os.path.normpath(path),
            '_mpls_bucket': track_type,
            '_mpls_slot_index': slot_index,
        }
        for config_name, track_type in (
            ('video', 'video'), ('audio', 'audio'), ('subtitle', 'subtitles')
        )
        for slot_index, pid in enumerate(selected_tracks.get(config_name) or [])
    ]


def _language_map_for_test(_path, _slots, configured=None, **_kwargs):
    return dict(configured or {})


def _logical_slots_for_selection_test(_path, selected_slots, **_kwargs):
    rows = []
    for track_type, pid in selected_slots:
        codec_type = 'subtitle' if track_type == 'subtitles' else track_type
        occurrence = {
            'pid': int(pid),
            'codec_type': codec_type,
            'codec_name': 'hevc' if track_type == 'video' else 'ac3',
            'stream_type': 0x24 if track_type == 'video' else 0x81,
        }
        rows.append({
            'pid': int(pid),
            'language': 'und',
            '_logical_type': track_type,
            '_logical_pid': int(pid),
            '_mpls_slot_key': (track_type, int(pid)),
            '_mpls_occurrences': (dict(occurrence), dict(occurrence)),
            '_mpls_append_compatible': True,
        })
    return rows, []


def _plan_sp_jobs(
        root: Path,
        destination: Path,
        entries: tuple[SpEntry, ...],
        main_jobs: list[RemuxMainJob],
        *,
        movie_mode: bool = False,
) -> list[SpJob]:
    fake_service_class = SimpleNamespace(
        _probe_m2ts_for_remux_source=lambda _path: (
            str(root / 'BDMV' / 'STREAM' / '00002.m2ts'),
            {},
        ),
        _selected_pid_slots_for_mpls=_selected_pid_slots_for_test,
        _mpls_default_language_map=_language_map_for_test,
    )
    service = _PlanningService()
    service.movie_mode = movie_mode
    track_selection = {
        entry.track_key: {'audio': ['1'], 'subtitle': []}
        for entry in entries
    }
    with patch.object(remux_module, '_svc_cls', return_value=fake_service_class):
        return service._prepare_sp_jobs(
            entries, str(destination), main_jobs, track_selection, {},
        )


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
                ),
                _selected_pid_slots_for_mpls=_selected_pid_slots_for_test,
                _mpls_default_language_map=_language_map_for_test,
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
                ),
                _selected_pid_slots_for_mpls=_selected_pid_slots_for_test,
                _mpls_default_language_map=_language_map_for_test,
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
                ),
                _selected_pid_slots_for_mpls=_selected_pid_slots_for_test,
                _mpls_default_language_map=_language_map_for_test,
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
            detail = '00002.m2ts(00:00:00.000-00:24:00.000)'
            entry = _entry(
                root,
                output_name='Custom Episode.mkv',
                m2ts_file_detail=detail,
            )
            main_job = _main_job(
                root,
                destination,
                detail=detail,
                output_name='Custom Episode.mkv',
            )
            jobs = _plan_sp_jobs(root, destination, (entry,), [main_job])
            self.assertEqual(jobs[0].output_path, main_job.final_outputs[0])
            self.assertEqual(jobs[0].episode_main_mpls_path, main_job.mpls_path)

    def test_same_m2ts_with_different_window_remains_independent_sp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / 'Disc'
            _disc(root)
            destination = Path(temporary_directory) / 'Output'
            entry = _entry(
                root,
                m2ts_file_detail='00002.m2ts(00:00:10.000-00:24:00.000)',
            )
            main_job = _main_job(
                root,
                destination,
                detail='00002.m2ts(00:00:00.000-00:24:00.000)',
            )
            jobs = _plan_sp_jobs(root, destination, (entry,), [main_job])

            self.assertEqual(jobs[0].output_path, str(destination / 'SPs' / 'Visible Name.mkv'))
            self.assertEqual(jobs[0].episode_main_mpls_path, '')

    def test_duplicate_episode_detail_is_not_an_attachment_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / 'Disc'
            _disc(root)
            destination = Path(temporary_directory) / 'Output'
            detail = '00002.m2ts(00:00:00.000-00:24:00.000)'
            entry = _entry(root, m2ts_file_detail=detail)
            single_job = _main_job(root, destination, detail=detail)
            main_job = replace(
                single_job,
                expected_outputs=(
                    str(destination / 'temporary-001.mkv'),
                    str(destination / 'temporary-002.mkv'),
                ),
                final_outputs=(
                    str(destination / 'EP01.mkv'),
                    str(destination / 'EP02.mkv'),
                ),
                m2ts_file_details=(detail, detail),
            )
            jobs = _plan_sp_jobs(root, destination, (entry,), [main_job])

            self.assertEqual(jobs[0].episode_main_mpls_path, '')

    def test_movie_mode_never_links_an_exact_sp_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / 'Disc'
            _disc(root)
            destination = Path(temporary_directory) / 'Output'
            detail = '00002.m2ts(00:00:00.000-00:24:00.000)'
            entry = _entry(root, m2ts_file_detail=detail)
            main_job = _main_job(root, destination, detail=detail)
            jobs = _plan_sp_jobs(
                root, destination, (entry,), [main_job], movie_mode=True,
            )

            self.assertEqual(jobs[0].episode_main_mpls_path, '')


class SpExecutionTests(unittest.TestCase):
    def test_multiple_episode_sp_rows_deduplicate_physical_track_relations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            playlist = root / 'BDMV' / 'PLAYLIST'
            playlist.mkdir(parents=True)
            episode = root / 'EP01.mkv'
            main_mpls = playlist / '00001.mpls'
            sp_paths = [playlist / f'0000{index}.mpls' for index in range(2, 5)]
            for path in (episode, main_mpls, *sp_paths):
                path.write_bytes(b'source')

            main_tracks = [
                {'id': 0, 'type': 'video', 'properties': {}},
                {'id': 1, 'type': 'audio', 'properties': {}},
            ]
            episode_identify_calls = 0
            sp_tracks = {
                str(sp_paths[0]): [
                    {'id': 1, 'type': 'audio', 'properties': {'stream_id': 0x1103}},
                    {'id': 2, 'type': 'audio', 'properties': {'stream_id': 0x1101}},
                ],
                str(sp_paths[1]): [
                    {'id': 1, 'type': 'audio', 'properties': {'stream_id': 0x1101}},
                    {'id': 2, 'type': 'audio', 'properties': {'stream_id': 0x1102}},
                ],
                str(sp_paths[2]): [
                    {'id': 1, 'type': 'audio', 'properties': {'stream_id': 0x1102}},
                ],
            }

            def identify(path):
                nonlocal episode_identify_calls
                normalized = os.path.normpath(path)
                if normalized == os.path.normpath(str(episode)):
                    episode_identify_calls += 1
                    track_count = 2 if episode_identify_calls == 1 else 4 + (
                        1 if episode_identify_calls >= 3 else 0
                    )
                    tracks = [dict(track) for track in main_tracks]
                    tracks.extend(
                        {'id': track_id, 'type': 'audio', 'properties': {}}
                        for track_id in range(2, track_count)
                    )
                    return {'tracks': tracks}
                return {'tracks': sp_tracks.get(normalized, [])}

            fake_service_class = SimpleNamespace(
                _int_from_mkvmerge_prop=lambda value: int(value) if value is not None else None,
                _mkvmerge_identify_json=identify,
            )
            commands: list[list[str]] = []

            def run(command, **_kwargs):
                commands.append(list(command))
                if command[0] == 'mkvmerge':
                    Path(command[command.index('-o') + 1]).write_bytes(b'muxed')
                    return SimpleNamespace(returncode=0)
                return SimpleNamespace(returncode=1)

            service = _SpExecutionService()
            service._compute_mkv_id_to_mpls_track_signature_for_main_mpls = lambda _path: {
                0: (('main.m2ts', 0x1011),),
                1: (('main.m2ts', 0x1100),),
            }
            source_signatures = (
                {
                    1: (('episode.m2ts', 0x1103),),
                    2: (('episode.m2ts', 0x1101),),
                },
                {
                    1: (('episode.m2ts', 0x1101),),
                    2: (('episode.m2ts', 0x1102),),
                },
                {1: (('episode.m2ts', 0x1102),)},
            )
            with patch.object(sp_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    sp_module, 'MKV_MERGE_PATH', 'mkvmerge'), patch.object(
                    sp_module, 'mkvtoolnix_ui_language_arg', return_value=''), patch.object(
                    sp_module, 'run_command', side_effect=run):
                for sp_path, selected_ids, signatures in zip(
                        sp_paths, (['1', '2'], ['1', '2'], ['1']), source_signatures):
                    self.assertTrue(service._mux_episode_linked_sp_mkvmerge(
                        episode_mkv=str(episode),
                        sp_mpls_path=str(sp_path),
                        episode_main_mpls=str(main_mpls),
                        selected_sp_audio_track_ids=selected_ids,
                        selected_sp_subtitle_track_ids=[],
                        language_by_sp_track_id={},
                        cancel_event=None,
                        source_signature_by_track_id=signatures,
                    ))

            mux_commands = [command for command in commands if command[0] == 'mkvmerge']
            self.assertEqual(len(mux_commands), 2)
            self.assertEqual(
                mux_commands[0][mux_commands[0].index('--track-order') + 1],
                '0:0,0:1,1:1,1:2',
            )
            self.assertEqual(
                mux_commands[1][mux_commands[1].index('--track-order') + 1],
                '0:0,0:1,0:2,0:3,1:2',
            )
            self.assertEqual(
                service._episode_sp_mux_last_after_mux_signatures[
                    os.path.normcase(os.path.abspath(episode))
                ],
                {
                    0: (('main.m2ts', 0x1011),),
                    1: (('main.m2ts', 0x1100),),
                    2: (('episode.m2ts', 0x1103),),
                    3: (('episode.m2ts', 0x1101),),
                    4: (('episode.m2ts', 0x1102),),
                },
            )

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
            service._compute_mkv_id_to_mpls_track_signature_for_main_mpls = lambda _path: {
                0: (('main.m2ts', 0x1011),),
                1: (('main.m2ts', 0x1100),),
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
                    selected_sp_audio_track_ids=[],
                    selected_sp_subtitle_track_ids=[],
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

    def test_selected_episode_sp_track_without_physical_mapping_fails(self) -> None:
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

            sp_identification = {
                'tracks': [
                    {'id': 1, 'type': 'audio', 'properties': {'number': 0x1101}},
                ]
            }
            fake_service_class = SimpleNamespace(
                _int_from_mkvmerge_prop=lambda value: int(value) if value is not None else None,
                _mkvmerge_identify_json=lambda path: (
                    sp_identification
                    if os.path.normpath(path) == os.path.normpath(str(sp_mpls))
                    else {'tracks': []}
                ),
            )
            with patch.object(sp_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    sp_module, 'Chapter', return_value=SimpleNamespace()), patch.object(
                    sp_module, 'get_index_to_m2ts_and_offset', return_value=({1: '00001.m2ts'}, {})):
                with self.assertRaisesRegex(RuntimeError, 'M2TS/PID mapping'):
                    _SpExecutionService()._mux_episode_linked_sp_mkvmerge(
                        episode_mkv=str(episode),
                        sp_mpls_path=str(sp_mpls),
                        episode_main_mpls=str(main_mpls),
                        selected_sp_audio_track_ids=['1'],
                        selected_sp_subtitle_track_ids=[],
                        language_by_sp_track_id={},
                        cancel_event=None,
                    )

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
    def test_full_match_selection_deduplicates_shared_physical_relations(self) -> None:
        main_mpls = os.path.normpath(r'C:\disc\BDMV\PLAYLIST\00001.mpls')
        alternate_mpls = os.path.normpath(r'C:\disc\BDMV\PLAYLIST\00002.mpls')

        def row(path, track_type, pid, bucket):
            return {
                'pid': pid,
                'codec_type': track_type,
                '_mpls_source_path': path,
                '_mpls_bucket': bucket,
                '_mpls_slot_index': 0,
                '_mpls_m2ts_pid_pairs': (('00001', pid),),
                '_mpls_append_compatible': True,
            }

        streams_by_path = {
            main_mpls: [
                row(main_mpls, 'video', 0x1011, 'PrimaryVideoStreamEntries'),
                row(main_mpls, 'audio', 0x1100, 'PrimaryAudioStreamEntries'),
            ],
            alternate_mpls: [
                row(alternate_mpls, 'video', 0x1011, 'PrimaryVideoStreamEntries'),
                row(alternate_mpls, 'audio', 0x1101, 'PrimaryAudioStreamEntries'),
            ],
        }
        fake_service_class = SimpleNamespace(
            _mpls_track_streams=lambda path: streams_by_path[os.path.normpath(path)],
            _mpls_track_selection_key=MediaInfoTrackMappingMixin._mpls_track_selection_key,
            _mpls_track_mapping_signature=MediaInfoTrackMappingMixin._mpls_track_mapping_signature,
        )
        configuration = {
            'video': [],
            'audio': [
                'mpls-slot::00001.mpls::PrimaryAudioStreamEntries::0',
                'mpls-slot::00002.mpls::PrimaryAudioStreamEntries::0',
            ],
            'subtitle': [],
        }

        with patch.object(track_module, '_svc_cls', return_value=fake_service_class):
            selected = MediaInfoTrackMappingMixin._selected_pid_slots_for_mpls(
                main_mpls,
                configuration,
                alternate_mpls_paths=(alternate_mpls,),
            )

        self.assertEqual(
            [(slot['type'], slot['pid']) for slot in selected],
            [('video', 0x1011), ('audio', 0x1100), ('audio', 0x1101)],
        )
        self.assertEqual(
            os.path.normpath(selected[-1]['_mpls_source_path']),
            alternate_mpls,
        )

    def test_execution_check_allows_stn_gap_and_rejects_missing_declared_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            playlist = root / 'BDMV' / 'PLAYLIST'
            stream = root / 'BDMV' / 'STREAM'
            playlist.mkdir(parents=True)
            stream.mkdir(parents=True)
            mpls = playlist / '00001.mpls'
            mpls.write_bytes(b'mpls')
            for clip in ('00001', '00002', '00003'):
                (stream / f'{clip}.m2ts').write_bytes(b'm2ts')
            video_occurrence = {
                'pid': 0x1011, 'codec_type': 'video',
                'codec_name': 'hevc', 'stream_type': 0x24,
            }
            audio_first = {
                'pid': 0x1100, 'codec_type': 'audio',
                'codec_name': 'truehd', 'stream_type': 0x83,
            }
            audio_last = dict(audio_first, pid=0x1101)
            logical_rows = [
                {
                    'pid': 0x1011,
                    '_logical_type': 'video',
                    '_logical_pid': 0x1011,
                    '_mpls_occurrences': tuple(dict(video_occurrence) for _ in range(3)),
                    '_mpls_append_compatible': True,
                },
                {
                    'pid': 0x1100,
                    '_logical_type': 'audio',
                    '_logical_pid': 0x1100,
                    '_mpls_occurrences': (audio_first, None, audio_last),
                    '_mpls_append_compatible': True,
                },
            ]

            def streams_for(path):
                rows = [{
                    'pid': 0x1011, 'codec_type': 'video',
                    'codec_name': 'hevc', 'stream_type_id': 0x24,
                }]
                if not str(path).endswith('00002.m2ts'):
                    rows.append({
                        'pid': 0x1101 if str(path).endswith('00003.m2ts') else 0x1100,
                        'codec_type': 'audio',
                        'codec_name': 'truehd', 'stream_type_id': 0x83,
                    })
                return rows

            fake_service_class = SimpleNamespace(
                _mpls_logical_slots_for_selection=lambda *_args, **_kwargs: (logical_rows, []),
                _m2ts_track_streams=streams_for,
                _stream_service_id=lambda row: int(row['pid']),
            )
            owner = SimpleNamespace()
            chapter = SimpleNamespace(in_out_time=[
                ('00001', 0, 45000), ('00002', 0, 45000), ('00003', 0, 45000),
            ])
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter):
                retained = MediaInfoTrackMappingMixin._validate_mpls_tracks_for_execution(
                    owner,
                    str(mpls),
                    [('video', 0x1011), ('audio', 0x1100)],
                )

            self.assertEqual(retained, [('video', 0x1011), ('audio', 0x1100)])

            def streams_with_missing_declared_pid(path):
                rows = streams_for(path)
                if str(path).endswith('00003.m2ts'):
                    return [row for row in rows if row['codec_type'] != 'audio']
                return rows

            owner = SimpleNamespace()
            fake_service_class._m2ts_track_streams = streams_with_missing_declared_pid
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter):
                with self.assertRaisesRegex(RuntimeError, '00003.m2ts'):
                    MediaInfoTrackMappingMixin._validate_mpls_tracks_for_execution(
                        owner,
                        str(mpls),
                        [('video', 0x1011), ('audio', 0x1100)],
                    )

            owner.allow_partial_missing_non_video_tracks = True
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter):
                retained_with_partial_missing = (
                    MediaInfoTrackMappingMixin._validate_mpls_tracks_for_execution(
                        owner,
                        str(mpls),
                        [('video', 0x1011), ('audio', 0x1100)],
                    )
                )
            self.assertEqual(
                retained_with_partial_missing,
                [('video', 0x1011), ('audio', 0x1100)],
            )

    def test_sparse_logical_track_concat_uses_one_chained_append_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            parts = [root / f'part-{index}.mkv' for index in range(3)]
            for part in parts:
                part.write_bytes(b'part')
            output = root / 'output.mkv'
            video = {
                'type': 'video', 'pid': 0x1011,
                '_logical_type': 'video', '_logical_pid': 0x1011,
                '_mpls_slot_key': ('PrimaryVideoStreamEntries', 0),
            }
            audio = {
                'type': 'audio', 'pid': 0x1100,
                '_logical_type': 'audio', '_logical_pid': 0x1100,
                '_mpls_slot_key': ('PrimaryAudioStreamEntries', 0),
            }
            descriptors = [
                {'path': str(parts[0]), 'duration': 1.0, 'slots': [video, audio]},
                {'path': str(parts[1]), 'duration': 1.0, 'slots': [video]},
                {'path': str(parts[2]), 'duration': 1.0, 'slots': [video, audio]},
            ]
            commands = []

            def run(command):
                commands.append(command)
                output.write_bytes(b'joined')
                return SimpleNamespace(returncode=0)

            owner = SimpleNamespace()
            with patch.object(track_module, 'run_command', side_effect=run):
                result = MediaInfoTrackMappingMixin._concat_mpls_logical_parts(
                    owner,
                    descriptors,
                    [video, audio],
                    str(output),
                    '',
                    'mkvmerge',
                    '',
                )

            self.assertTrue(result)
            self.assertEqual(len(commands), 1)
            command = commands[0]
            self.assertEqual(command[command.index('--append-mode') + 1], 'track')
            self.assertEqual(
                command[command.index('--append-to') + 1],
                '1:0:0:0,2:0:1:0,2:1:0:1',
            )
            self.assertIn('1:1000', command)
            self.assertEqual(
                owner._remux_fallback_audio_timelines[
                    os.path.normcase(os.path.abspath(output))
                ],
                {1: ((0.0, 1.0), (2.0, 1.0))},
            )

            all_audio_missing = [
                {'path': str(part), 'duration': 1.0, 'slots': [video]}
                for part in parts
            ]
            missing_track_result = MediaInfoTrackMappingMixin._concat_mpls_logical_parts(
                owner,
                all_audio_missing,
                [video, audio],
                str(root / 'missing-audio.mkv'),
                '',
                'mkvmerge',
                '',
            )
            self.assertFalse(missing_track_result)
            self.assertEqual(len(commands), 1)

    def test_dolby_vision_only_sp_retains_one_combined_video_slot(self) -> None:
        base_layer_pid = 0x1011
        enhancement_layer_pid = 0x1015
        streams = [
            {'index': 0, 'codec_type': 'video', 'pid': base_layer_pid},
            {'index': 1, 'codec_type': 'video', 'pid': enhancement_layer_pid},
        ]
        fake_service_class = SimpleNamespace(
            _m2ts_track_streams=lambda _path: streams,
            _stream_service_id=lambda stream: stream.get('pid'),
            _filter_video_pids_for_dovi_plan=lambda *_args: [],
        )
        dolby_vision_plan = {
            'active': True,
            'mux_enabled': True,
            'bl_pid': base_layer_pid,
            'el_pid': enhancement_layer_pid,
        }

        with patch.object(track_module, '_svc_cls', return_value=fake_service_class):
            selected_slots = MediaInfoTrackMappingMixin._ordered_track_slots_for_remux(
                '00304.m2ts',
                [],
                [],
                dovi_plan=dolby_vision_plan,
            )

        self.assertEqual(selected_slots, [
            {'type': 'video', 'pid': base_layer_pid, 'index': '0'},
        ])

    def test_multi_clip_fallback_cleans_each_tsmuxer_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            playlist = root / 'BDMV' / 'PLAYLIST'
            stream = root / 'BDMV' / 'STREAM'
            playlist.mkdir(parents=True)
            stream.mkdir(parents=True)
            mpls = playlist / '00001.mpls'
            first_m2ts = stream / '00001.m2ts'
            second_m2ts = stream / '00002.m2ts'
            output = root / 'Output.mkv'
            mpls.write_bytes(b'mpls')
            first_m2ts.write_bytes(b'm2ts')
            second_m2ts.write_bytes(b'm2ts')
            calls = []
            concat_commands = []
            split_arguments = []
            temporary_directories = []

            def remux_clip(*args, **_kwargs):
                calls.append(args[0])
                split_arguments.append(args[4])
                work_folder = Path(args[6])
                part_tag = args[7]
                for suffix in ('tsmux_out', 'audrec_tsmux_out'):
                    temporary_directory = work_folder / f'{part_tag}_{suffix}'
                    temporary_directory.mkdir()
                    (temporary_directory / 'temporary.bin').write_bytes(b'temporary')
                    temporary_directories.append(temporary_directory)
                Path(args[3]).write_bytes(b'part')
                return True

            def run_concat(command):
                concat_commands.append(command)
                Path(command[command.index('-o') + 1]).write_bytes(b'joined')
                return SimpleNamespace(returncode=0)

            owner = SimpleNamespace(
                _dovi_mux_plan=None,
                _set_dovi_mux_plan_for_mpls=lambda _path: None,
                _remux_aligned_clip=remux_clip,
            )
            owner._concat_mpls_logical_parts = lambda *args: (
                MediaInfoTrackMappingMixin._concat_mpls_logical_parts(owner, *args)
            )
            fake_service_class = SimpleNamespace(
                _detect_sp_looping_mpls=lambda _path: None,
                _filter_pid_slots_for_dovi_plan=lambda slots, _plan: list(slots),
                _mpls_logical_slots_for_selection=_logical_slots_for_selection_test,
                _mpls_clip_slots=MediaInfoTrackMappingMixin._mpls_clip_slots,
                _m2ts_clip_time_window_sec=lambda *_args: (True, 0.0, 1.0),
            )
            chapter = SimpleNamespace(
                in_out_time=[('00001', 0, 45000), ('00002', 0, 45000)],
            )
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter), patch.object(
                    track_module, 'find_mkvtoolnix'), patch.object(
                    track_module, 'MKV_MERGE_PATH', 'mkvmerge'), patch.object(
                    track_module, 'mkvtoolnix_ui_language_arg', return_value=''), patch.object(
                    track_module, 'run_command', side_effect=run_concat):
                result = MediaInfoTrackMappingMixin._try_remux_mpls_track_aligned(
                    owner,
                    str(mpls),
                    str(output),
                    '',
                    selected_pid_slots=[('video', 0x1011)],
                )

            self.assertTrue(result)
            self.assertEqual(calls, [str(first_m2ts), str(second_m2ts)])
            self.assertEqual(
                split_arguments,
                ['--split parts:00:00:00.000-00:00:01.000'] * 2,
            )
            self.assertEqual(concat_commands[0][1:3], ['--append-mode', 'track'])
            self.assertIn('--append-to', concat_commands[0])
            self.assertEqual(output.read_bytes(), b'joined')
            self.assertTrue(temporary_directories)
            self.assertTrue(all(not path.exists() for path in temporary_directories))

    def test_multi_output_fallback_uses_track_append_and_normalized_zero_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            playlist = root / 'BDMV' / 'PLAYLIST'
            stream = root / 'BDMV' / 'STREAM'
            playlist.mkdir(parents=True)
            stream.mkdir(parents=True)
            mpls = playlist / '00001.mpls'
            first_m2ts = stream / '00001.m2ts'
            second_m2ts = stream / '00002.m2ts'
            output = root / 'Output.mkv'
            expected_outputs = [root / 'Output-001.mkv', root / 'Output-002.mkv']
            for path in (mpls, first_m2ts, second_m2ts):
                path.write_bytes(b'source')
            split_arguments = []
            concat_commands = []

            def remux_clip(*args, **_kwargs):
                split_arguments.append(args[4])
                Path(args[3]).write_bytes(b'part')
                return True

            def run_concat(command):
                concat_commands.append(command)
                Path(command[command.index('-o') + 1]).write_bytes(b'joined')
                return SimpleNamespace(returncode=0)

            owner = SimpleNamespace(
                movie_mode=False,
                _dovi_mux_plan=None,
                _set_dovi_mux_plan_for_mpls=lambda _path: None,
                _remux_aligned_clip=remux_clip,
                _progress=lambda **_kwargs: None,
                _run_single_command=run_concat,
            )
            owner._concat_mpls_logical_parts = lambda *args: (
                MediaInfoTrackMappingMixin._concat_mpls_logical_parts(owner, *args)
            )
            fake_service_class = SimpleNamespace(
                _series_episode_segments_bounds=lambda *_args: [(1, 2), (1, 2)],
                _expected_mkvmerge_split_output_paths=lambda *_args: [
                    str(path) for path in expected_outputs
                ],
                _filter_pid_slots_for_dovi_plan=lambda slots, _plan: list(slots),
                _mpls_logical_slots_for_selection=_logical_slots_for_selection_test,
                _mpls_clip_slots=MediaInfoTrackMappingMixin._mpls_clip_slots,
                _m2ts_clip_time_window_sec=lambda *_args: (True, 0.0, 1.0),
            )
            chapter = SimpleNamespace(
                in_out_time=[('00001', 0, 45000), ('00002', 0, 45000)],
                mark_info={'00001': [object()]},
                get_total_time=lambda: 2.0,
            )
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter), patch.object(
                    track_module, 'find_mkvtoolnix'), patch.object(
                    track_module, 'MKV_MERGE_PATH', 'mkvmerge'), patch.object(
                    track_module, 'mkvtoolnix_ui_language_arg', return_value=''), patch.object(
                    track_module, 'get_index_to_m2ts_and_offset', return_value=({}, {1: 0.0})), patch.object(
                    track_module, 'run_command', side_effect=run_concat):
                result = MediaInfoTrackMappingMixin._try_remux_mpls_split_outputs_track_aligned(
                    owner,
                    str(mpls),
                    str(output),
                    [{}, {}],
                    '',
                    selected_pid_slots=[('video', 0x1011)],
                )

            self.assertTrue(result)
            self.assertEqual(
                split_arguments,
                ['--split parts:00:00:00.000-00:00:01.000'] * 4,
            )
            self.assertEqual(len(concat_commands), 2)
            self.assertTrue(all('--append-mode' in command for command in concat_commands))
            self.assertTrue(all(command[command.index('--append-mode') + 1] == 'track' for command in concat_commands))
            self.assertTrue(all(path.read_bytes() == b'joined' for path in expected_outputs))

    def test_dolby_vision_only_clip_can_mux_without_a_base_mkv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            mpls = root / '01478.mpls'
            m2ts = root / '00304.m2ts'
            output = root / 'part_000.mkv'
            base_layer = root / 'base.hevc'
            enhancement_layer = root / 'enhancement.hevc'
            for path in (mpls, m2ts, base_layer, enhancement_layer):
                path.write_bytes(b'source')
            base_layer_pid = 0x1011
            enhancement_layer_pid = 0x1015
            selected_orders = []

            def merge_without_base(
                    _mkvmerge, _ui_language, base_mkv, base_pids, demuxed_paths,
                    _languages, merged_output, **kwargs):
                self.assertIsNone(base_mkv)
                self.assertEqual(base_pids, [])
                self.assertEqual(demuxed_paths, {base_layer_pid: str(base_layer)})
                selected_orders.append(kwargs['selected_pid_order'])
                Path(merged_output).write_bytes(b'dolby vision')
                return True

            owner = SimpleNamespace(
                _dovi_mux_plan={
                    'active': True,
                    'mux_enabled': True,
                    'bl_pid': base_layer_pid,
                    'el_pid': enhancement_layer_pid,
                },
                mux_dolby_vision=True,
                _remux_fallback_run_tsmuxer_demux_subset=lambda *_args, **_kwargs: {
                    base_layer_pid: str(base_layer),
                    enhancement_layer_pid: str(enhancement_layer),
                },
                _remux_fallback_merge_demux_with_base=merge_without_base,
            )
            fake_service_class = SimpleNamespace(
                _mkvmerge_identify_json=lambda _path: {'tracks': []},
                _slot_pids_in_order=lambda slots: [int(slot['pid']) for slot in slots],
                _run_tsmuxer_probe=lambda _path: 'probe',
                _parse_tsmuxer_probe_output=lambda _output: [
                    {'pid': base_layer_pid},
                    {'pid': enhancement_layer_pid},
                ],
                _tsmuxer_mpeg_pid=lambda track: track['pid'],
                _remux_fallback_promote_merge_to_part_out=lambda part, merged: (
                    os.replace(merged, part) is None
                ),
            )
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'mux_dolby_vision_layers'):
                result = MediaInfoTrackMappingMixin._remux_aligned_clip(
                    owner,
                    str(m2ts),
                    str(mpls),
                    [{'type': 'video', 'pid': base_layer_pid, 'index': '0'}],
                    str(output),
                    '',
                    1.0,
                    str(root),
                    'part_000',
                    'mkvmerge',
                    '',
                )

            self.assertTrue(result)
            self.assertEqual(output.read_bytes(), b'dolby vision')
            self.assertEqual(selected_orders, [[base_layer_pid]])

    def test_recovered_tracks_follow_gui_selected_pid_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            base_mkv = root / 'base.mkv'
            recovered_audio = root / 'recovered.ac3'
            output = root / 'merged.mkv'
            base_mkv.write_bytes(b'base')
            recovered_audio.write_bytes(b'audio')
            commands = []

            def run_command(command):
                commands.append(command)
                output.write_bytes(b'merged')
                return 0

            owner = SimpleNamespace(_run_single_command=run_command)
            fake_service_class = SimpleNamespace(
                _norm_lang_mkv=lambda language: language,
                _tsmuxer_demux_audio_use_track0_after_identify=lambda *_args: False,
            )
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class):
                result = MediaInfoTrackMappingMixin._remux_fallback_merge_demux_with_base(
                    owner,
                    'mkvmerge',
                    '',
                    str(base_mkv),
                    [0x1200, 0x1011],
                    {0x1100: str(recovered_audio)},
                    {},
                    str(output),
                    base_track_by_pid={0x1200: 0, 0x1011: 1},
                    selected_pid_order=[0x1200, 0x1011, 0x1100],
                )

            self.assertTrue(result)
            self.assertIn('--track-order 0:0,0:1,1:0', commands[0])

    def test_aligned_fallback_does_not_substitute_a_similarly_named_intermediate(self) -> None:
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

            def remux_clip(*args, **_kwargs):
                Path(args[3]).with_name('part_000_intermediate.mkv').write_bytes(b'wrong part')
                return True

            owner = SimpleNamespace(
                _dovi_mux_plan=None,
                _set_dovi_mux_plan_for_mpls=lambda _path: None,
                _remux_aligned_clip=remux_clip,
            )
            fake_service_class = SimpleNamespace(
                _detect_sp_looping_mpls=lambda _path: None,
                _filter_pid_slots_for_dovi_plan=lambda slots, _plan: list(slots),
                _mpls_logical_slots_for_selection=_logical_slots_for_selection_test,
                _mpls_clip_slots=MediaInfoTrackMappingMixin._mpls_clip_slots,
                _m2ts_clip_time_window_sec=lambda *_args: (False, 0.0, 1.0),
            )
            chapter = SimpleNamespace(in_out_time=[('00001', 0, 45000)])
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class), patch.object(
                    track_module, 'Chapter', return_value=chapter), patch.object(
                    track_module, 'find_mkvtoolnix'), patch.object(
                    track_module, 'MKV_MERGE_PATH', 'mkvmerge'), patch.object(
                    track_module, 'mkvtoolnix_ui_language_arg', return_value=''):
                result = MediaInfoTrackMappingMixin._try_remux_mpls_track_aligned(
                    owner,
                    str(mpls),
                    str(output),
                    '',
                    selected_pid_slots=[('video', 0x1011)],
                )

            self.assertFalse(result)
            self.assertFalse(output.exists())

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
                _mkvmerge_identify_json=lambda _path: {},
                _m2ts_track_streams=lambda _path: [
                    {'pid': 0x1011, 'codec_type': 'video'}
                ],
                _stream_service_id=lambda row: int(row['pid']),
                _mkvmerge_tid_for_pid=lambda _path, pid, _type: 0 if pid == 0x1011 else None,
                _mkvmerge_select_flags_from_mapped=lambda _ids, _ident: ('0', '', ''),
                _slot_pids_in_order=lambda slots: [int(slot['pid']) for slot in slots],
                _ref_slot_pid_set=lambda slots: {int(slot['pid']) for slot in slots},
                _run_tsmuxer_probe=lambda _path: '',
                _parse_tsmuxer_probe_output=lambda _text: [],
                _tsmuxer_mpeg_pid=lambda _track: None,
            )
            reference_slots = [
                {'type': 'video', 'pid': 0x1011},
                {'type': 'subtitles', 'pid': 0x1200},
            ]
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class):
                result = MediaInfoTrackMappingMixin._remux_aligned_clip(
                    owner, str(m2ts), str(mpls), reference_slots,
                    str(output), '', 1.0, str(work), 'part', 'mkvmerge', '',
                )

            self.assertFalse(result)

            owner.allow_partial_missing_non_video_tracks = True
            with patch.object(track_module, '_svc_cls', return_value=fake_service_class):
                allowed_result = MediaInfoTrackMappingMixin._remux_aligned_clip(
                    owner, str(m2ts), str(mpls), reference_slots,
                    str(output), '', 1.0, str(work), 'part', 'mkvmerge', '',
                )

            self.assertTrue(allowed_result)
            self.assertEqual(reference_slots, [
                {'type': 'video', 'pid': 0x1011},
            ])


if __name__ == '__main__':
    unittest.main()
