"""Focused contracts for the unified Blu-ray Encode workflow."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.runtime.encode import EncodeRequest, EncodeRow, EncodeSettings, validate_encode_request
from src.runtime.encode_results import (
    EncodeBatchResult,
    EncodeRowResult,
    EncodeTaskFailure,
)
from src.runtime.encode_source import ActualEncodeSource
from src.runtime import TaskCancelled
from src.runtime.services_split.encode_and_audio_tasks import EncodeAudioTasksMixin
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin


def _settings() -> EncodeSettings:
    return EncodeSettings(
        vspipe_mode='bundle', encoder_mode='bundle', encoder_parameters='--crf 18',
        subtitle_mode='external', encoder='x265', bit_depth='10',
        use_getnative=False, default_lossless_audio_codec='flac', output_comparison_images=False,
    )


def _actual_source(path: str) -> ActualEncodeSource:
    return ActualEncodeSource(os.path.abspath(path), 0, 'hevc', {'index': 0, 'codec_name': 'hevc'})


class _RowEncodeService(RemuxEpisodeWorkflowsMixin):
    def __init__(
            self,
            create_outputs: bool = True,
            failing_outputs: tuple[str, ...] = (),
            cancel_outputs: tuple[str, ...] = (),
    ) -> None:
        self.create_outputs = create_outputs
        self.failing_outputs = set(failing_outputs)
        self.cancel_outputs = set(cancel_outputs)
        self.encode_calls: list[tuple[str, str]] = []
        self.progress_messages: list[str] = []

    def t(self, text: str) -> str:
        return text

    def _progress(self, value=None, text=None) -> None:
        if text:
            self.progress_messages.append(text)

    def encode_task(self, output_file, _vpy_path, *_args, source_file=None, **_kwargs):
        self.encode_calls.append((source_file, output_file))
        if output_file in self.cancel_outputs:
            raise TaskCancelled()
        if output_file in self.failing_outputs:
            artifact_path = output_file + '.partial.test.hevc'
            Path(artifact_path).write_bytes(b'partial')
            raise EncodeTaskFailure(
                'Video encoding',
                'simulated encoder failure',
                (artifact_path,),
            )
        if self.create_outputs:
            Path(output_file).write_bytes(b'encoded')


class _BdmvEncodeService(_RowEncodeService):
    def __init__(self, batch_result: EncodeBatchResult = EncodeBatchResult(())) -> None:
        super().__init__()
        self.batch_result = batch_result
        self.stage_request = None

    def _prepare_remux_main_jobs(self, request):
        self.stage_request = request
        self.configuration = request.configuration
        return os.path.join(request.output_folder, 'Disc'), []

    def _build_main_episode_mkvs(self, *_args, **_kwargs):
        return []

    def _post_remux_finalize_episodes(self, _jobs, _cancel_event):
        staged_output = os.path.join(self.stage_request.output_folder, 'Disc', 'Episode.mkv')
        Path(staged_output).write_bytes(b'remux')
        return [staged_output]

    def _build_sp_outputs(self, *_args, **_kwargs):
        return []

    def _encode_mkv_rows(self, request, main_rows, sp_rows, cancel_event, **_kwargs):
        self.encode_warnings = []
        return self.batch_result


class _PipelineService(EncodeAudioTasksMixin):
    use_getnative = False
    sub_files = []

    def __init__(self) -> None:
        self.progress_messages: list[str] = []

    def t(self, text: str) -> str:
        return text

    def _progress(self, value=None, text=None) -> None:
        if text:
            self.progress_messages.append(text)

    def _cleanup_getnative_artifacts(self) -> None:
        pass


class EncodeWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        vpy_probe = patch(
            'src.runtime.services_split.encode_and_audio_tasks.probe_vapoursynth_output_metadata',
            side_effect=lambda source, *_args: (source, False, (1, 24, 1)),
        )
        self.vpy_probe = vpy_probe.start()
        self.addCleanup(vpy_probe.stop)

    def test_sp_copy_failure_retains_partial_data_and_never_deletes_a_collision(self) -> None:
        for collision in (False, True):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                source_folder = root / 'images'
                source_folder.mkdir()
                output_folder = root / 'output'
                output_path = output_folder / 'images'
                row = EncodeRow(str(source_folder), str(output_path), '')
                request = EncodeRequest(
                    input_mode='remux', source_root=str(root), output_folder=str(output_folder),
                    staging_folder='', main_rows=(), sp_rows=(row,), settings=_settings(),
                )

                def copy_images(_source, temporary, **_kwargs):
                    Path(temporary, 'frame.png').write_bytes(b'partial image')
                    if collision:
                        output_path.mkdir()
                        (output_path / 'existing.png').write_bytes(b'existing image')
                    else:
                        raise OSError('simulated copy failure')

                service = _RowEncodeService()
                with patch('src.runtime.services_split.remux_and_episode_workflows.shutil.copytree', side_effect=copy_images):
                    if collision:
                        with self.assertRaises(FileExistsError):
                            service._encode_mkv_rows(request, [], [row], threading.Event())
                        self.assertEqual((output_path / 'existing.png').read_bytes(), b'existing image')
                    else:
                        result = service._encode_mkv_rows(request, [], [row], threading.Event())
                        self.assertEqual(result.rows[0].status, 'failed_with_artifacts')
                        artifact = Path(result.rows[0].artifact_paths[0])
                        self.assertNotEqual(artifact, output_path)
                        self.assertEqual((artifact / 'frame.png').read_bytes(), b'partial image')
                        self.assertFalse(output_path.exists())

    def test_preflight_rejects_duplicates_and_only_allows_existing_remux_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'source'
            output_folder = root / 'output'
            source_folder.mkdir()
            output_folder.mkdir()
            source_a = source_folder / 'a.mkv'
            source_b = source_folder / 'b.mkv'
            vpy_path = root / 'encode.vpy'
            source_a.write_bytes(b'a')
            source_b.write_bytes(b'b')
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            output_path = output_folder / 'Episode.mkv'
            request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=(
                    EncodeRow(str(source_a), str(output_path), str(vpy_path)),
                    EncodeRow(str(source_b), str(output_path), str(vpy_path)),
                ),
                sp_rows=(),
                settings=_settings(),
            )
            with self.assertRaisesRegex(ValueError, 'Duplicate output path'):
                validate_encode_request(request)

            output_path.write_bytes(b'existing')
            existing_request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=(EncodeRow(str(source_a), str(output_path), str(vpy_path)),),
                sp_rows=(),
                settings=_settings(),
            )
            validate_encode_request(existing_request)

            output_path.unlink()
            output_path.mkdir()
            with self.assertRaisesRegex(FileExistsError, 'Existing resumable output is invalid'):
                validate_encode_request(existing_request)
            output_path.rmdir()
            output_path.write_bytes(b'')
            with self.assertRaisesRegex(FileExistsError, 'Existing resumable output is invalid'):
                validate_encode_request(existing_request)

            disc_folder = root / 'Disc'
            playlist_folder = disc_folder / 'BDMV' / 'PLAYLIST'
            playlist_folder.mkdir(parents=True)
            (playlist_folder / '00001.mpls').write_bytes(b'mpls')
            bdmv_request = EncodeRequest(
                input_mode='bdmv',
                source_root=str(disc_folder),
                output_folder=str(output_folder),
                staging_folder=str(root / 'stage'),
                main_rows=(EncodeRow(
                    source_path='',
                    output_path=str(output_path),
                    vpy_path=str(vpy_path),
                    configuration_key=0,
                    configuration={
                        'folder': str(disc_folder),
                        'selected_mpls': '00001',
                    },
                ),),
                sp_rows=(),
                settings=_settings(),
                selected_mpls=((str(disc_folder), '00001'),),
            )
            with self.assertRaisesRegex(FileExistsError, 'Output file already exists'):
                validate_encode_request(bdmv_request)

    def test_preflight_rejects_output_inside_source_and_missing_vpy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'source'
            source_folder.mkdir()
            source_path = source_folder / 'source.mkv'
            source_path.write_bytes(b'mkv')
            inside_output = source_folder / 'encoded'
            request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(inside_output),
                staging_folder='',
                main_rows=(EncodeRow(
                    str(source_path),
                    str(inside_output / 'Episode.mkv'),
                    str(root / 'missing.vpy'),
                ),),
                sp_rows=(),
                settings=_settings(),
            )
            with self.assertRaisesRegex(ValueError, 'cannot be inside the source folder'):
                validate_encode_request(request)

            outside_output = root / 'encoded'
            request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(outside_output),
                staging_folder='',
                main_rows=(EncodeRow(
                    str(source_path),
                    str(outside_output / 'Episode.mkv'),
                    str(root / 'missing.vpy'),
                ),),
                sp_rows=(),
                settings=_settings(),
            )
            with self.assertRaisesRegex(FileNotFoundError, 'VPy file does not exist'):
                validate_encode_request(request)

    def test_shared_row_executor_resumes_remux_but_keeps_bdmv_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder, output_folder = root / 'source', root / 'output'
            source_folder.mkdir()
            output_folder.mkdir()
            vpy_path = root / 'encode.vpy'
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            rows = []
            for name in ('First.mkv', 'Second.mkv'):
                source = source_folder / name
                source.write_bytes(b'source')
                rows.append(EncodeRow(str(source), str(output_folder / name), str(vpy_path)))
            request = EncodeRequest(
                input_mode='remux', source_root=str(source_folder), output_folder=str(output_folder),
                staging_folder='', main_rows=tuple(rows), sp_rows=(), settings=_settings(),
            )
            existing = Path(rows[0].output_path)
            existing.write_bytes(b'existing')
            with patch('src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths', return_value=None):
                service = _RowEncodeService()
                service._encode_mkv_rows(request, rows, [], threading.Event())
                self.assertEqual(existing.read_bytes(), b'existing')
                self.assertEqual(Path(rows[1].output_path).read_bytes(), b'encoded')
                self.assertEqual(service.encode_calls, [(rows[1].source_path, rows[1].output_path)])

                for mode, payload in (('remux', b''), ('bdmv', b'existing')):
                    with self.subTest(mode=mode):
                        existing.write_bytes(payload)
                        service = _RowEncodeService()
                        with self.assertRaises(FileExistsError):
                            service._encode_mkv_rows(
                                replace(request, input_mode=mode), rows, [], threading.Event(),
                            )
                        self.assertEqual(service.encode_calls, [])
                        self.assertEqual(existing.read_bytes(), payload)

                missing_row = replace(rows[1], output_path=str(output_folder / 'Missing.mkv'))
                service = _RowEncodeService(create_outputs=False)
                result = service._encode_mkv_rows(
                    replace(request, main_rows=(missing_row,)), [missing_row], [], threading.Event(),
                )
                self.assertEqual(result.rows[0].status, 'failed')
                self.assertFalse(Path(missing_row.output_path).exists())

    def test_row_failure_retains_artifacts_and_continues_later_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'source'
            output_folder = root / 'output'
            source_folder.mkdir()
            output_folder.mkdir()
            first_source = source_folder / 'first.mkv'
            second_source = source_folder / 'second.mkv'
            vpy_path = root / 'encode.vpy'
            first_source.write_bytes(b'first')
            second_source.write_bytes(b'second')
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            first_output = output_folder / 'First.mkv'
            second_output = output_folder / 'Second.mkv'
            rows = (
                EncodeRow(str(first_source), str(first_output), str(vpy_path)),
                EncodeRow(str(second_source), str(second_output), str(vpy_path)),
            )
            request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=rows,
                sp_rows=(),
                settings=_settings(),
            )
            service = _RowEncodeService(
                failing_outputs=(str(first_output),),
            )

            with patch(
                    'src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths',
                    return_value=None):
                result = service._encode_mkv_rows(
                    request,
                    list(rows),
                    [],
                    threading.Event(),
                )

            self.assertEqual(
                [row.status for row in result.rows],
                ['failed_with_artifacts', 'completed'],
            )
            self.assertEqual(len(service.encode_calls), 2)
            self.assertTrue(second_output.is_file())
            self.assertTrue(Path(result.rows[0].artifact_paths[0]).is_file())
            self.assertTrue(Path(result.rows[0].report_path).is_file())
            report_text = Path(result.rows[0].report_path).read_text(encoding='utf-8')
            self.assertIn('simulated encoder failure', report_text)
            self.assertIn(result.rows[0].artifact_paths[0], report_text)

    def test_cancellation_stops_later_rows_without_converting_it_to_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'source'
            output_folder = root / 'output'
            source_folder.mkdir()
            output_folder.mkdir()
            first_source = source_folder / 'first.mkv'
            second_source = source_folder / 'second.mkv'
            vpy_path = root / 'encode.vpy'
            first_source.write_bytes(b'first')
            second_source.write_bytes(b'second')
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            first_output = output_folder / 'First.mkv'
            rows = (
                EncodeRow(str(first_source), str(first_output), str(vpy_path)),
                EncodeRow(
                    str(second_source),
                    str(output_folder / 'Second.mkv'),
                    str(vpy_path),
                ),
            )
            request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=rows,
                sp_rows=(),
                settings=_settings(),
            )
            service = _RowEncodeService(
                cancel_outputs=(str(first_output),),
            )

            with patch(
                    'src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths',
                    return_value=None):
                with self.assertRaises(TaskCancelled):
                    service._encode_mkv_rows(
                        request,
                        list(rows),
                        [],
                        threading.Event(),
                    )

            self.assertEqual(
                service.encode_calls,
                [(str(first_source), str(first_output))],
            )
            self.assertEqual(list(output_folder.glob('*.encode-error*.txt')), [])

    def test_bdmv_staging_is_removed_when_an_encode_row_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'Disc'
            source_folder.mkdir()
            output_folder = root / 'output' / 'Disc'
            staging_folder = root / 'output' / '_encode_remux_stage'
            request = EncodeRequest(
                input_mode='bdmv',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder=str(staging_folder),
                main_rows=(EncodeRow(
                    source_path='',
                    output_path=str(output_folder / 'Episode.mkv'),
                    vpy_path=str(root / 'encode.vpy'),
                    configuration_key=0,
                    configuration={
                        'bdmv_index': 1,
                        'selected_mpls': '00001',
                        'start_at_chapter': 1,
                    },
                ),),
                sp_rows=(),
                settings=_settings(),
                selected_mpls=((str(source_folder), '00001'),),
            )
            failed_result = EncodeBatchResult((EncodeRowResult(
                row_type='Main row',
                source_path='',
                output_path=str(output_folder / 'Episode.mkv'),
                status='failed',
            ),))
            service = _BdmvEncodeService(failed_result)

            result = service.episodes_encode(request, threading.Event())

            self.assertIs(result, failed_result)
            self.assertFalse(staging_folder.exists())

    def test_encoder_failure_stops_before_audio_or_mux(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / 'source.mkv'
            output_path = root / 'output.mkv'
            vpy_path = root / 'encode.vpy'
            source_path.write_bytes(b'mkv')
            vpy_path.write_text('a = r""\nres = core.fmtc.bitdepth(src8, bits=10)\n', encoding='utf-8')
            service = _PipelineService()

            def fail_encode(_vspipe, _vpy, encoder_command, _environment):
                Path(encoder_command[encoder_command.index('-o') + 1]).write_bytes(
                    b'partial-hevc'
                )
                return 7

            with (
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id',
                        return_value=None,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.probe_actual_encode_source',
                        side_effect=_actual_source,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks._write_vpy_video_source_a',
                        return_value=True,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.get_vspipe_context',
                        return_value=('vspipe', {}),
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.resolve_encoder_executable_path',
                        return_value='x265',
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks._run_vspipe_piped_encode',
                        side_effect=fail_encode,
                    )
            ):
                with self.assertRaisesRegex(EncodeTaskFailure, 'exit code 7') as failure:
                    service.encode_task(
                        str(output_path),
                        str(vpy_path),
                        'bundle',
                        'bundle',
                        '--crf 18',
                        'external',
                        encoder='x265',
                        bit_depth='10',
                        selected_audio_tracks=(),
                        selected_subtitle_tracks=(),
                        audio_codec_choices=(),
                        track_language_overrides=(),
                        subtitle_path='',
                        subtitle_language='',
                        source_file=str(source_path),
                    )
            self.assertFalse(output_path.exists())
            self.assertEqual(len(failure.exception.artifact_paths), 1)
            artifact_path = Path(failure.exception.artifact_paths[0])
            self.assertTrue(artifact_path.name.startswith('output.partial.'))
            self.assertEqual(artifact_path.suffix, '.hevc')
            self.assertEqual(artifact_path.read_bytes(), b'partial-hevc')

if __name__ == '__main__':
    unittest.main()
