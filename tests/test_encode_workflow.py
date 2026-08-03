"""Focused contracts for the unified Blu-ray Encode workflow."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.audio_conversion import AudioEncodingSettings
from src.runtime.dolby_vision import DolbyVisionEncodePlan
from src.runtime.encode import EncodeRequest, EncodeRow, EncodeSettings, validate_encode_request
from src.runtime.encode_results import (
    EncodeBatchResult,
    EncodeRowResult,
    EncodeTaskFailure,
)
from src.runtime.encode_source import ActualEncodeSource
from src.runtime import TaskCancelled
from src.runtime.video_crop import VideoCropPlan
from src.runtime.services import BluraySubtitle as _BluraySubtitle
from src.runtime.services_split.encode_and_audio_tasks import (
    EncodeAudioTasksMixin,
    _plan_automatic_encoder_metadata,
    _write_vpy_video_source_a,
)
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin
from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI as _BluraySubtitleGUI
from src.runtime.gui_runtime_split import actions_and_file_dialogs as encode_gui_module
from src.runtime.gui_runtime_split.actions_and_file_dialogs import ActionsAndDialogsMixin
from tests._gui_worker_fakes import FakeThread as _ThreadCapture
from tests._gui_worker_fakes import RequestWorkerCapture


class _EncodeWorkerCapture(RequestWorkerCapture):
    signal_names = RequestWorkerCapture.signal_names + (
        'finished_with_warnings',
        'finished_with_errors',
    )


def _settings(
        *,
        output_comparison_images: bool = False,
        auto_crop_black_borders: bool = False,
) -> EncodeSettings:
    return EncodeSettings(
        vspipe_mode='bundle',
        encoder_mode='bundle',
        encoder_parameters='--crf 18',
        subtitle_mode='external',
        encoder='x265',
        bit_depth='10',
        use_getnative=False,
        default_lossless_audio_codec='flac',
        auto_crop_black_borders=auto_crop_black_borders,
        output_comparison_images=output_comparison_images,
    )


def _actual_source(
        path: str,
        codec_name: str = 'hevc',
        stream_metadata: dict | None = None,
) -> ActualEncodeSource:
    normalized_path = os.path.abspath(os.path.normpath(path))
    stream = {'index': 0, 'codec_name': codec_name}
    stream.update(stream_metadata or {})
    return ActualEncodeSource(
        normalized_path,
        0,
        codec_name,
        stream,
    )


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
        self.resolved_rows = None

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
        self.resolved_rows = (request, main_rows, sp_rows, cancel_event)
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
    def test_vpy_source_patch_changes_only_the_top_level_source_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            vpy_path = Path(temporary_directory) / 'encode.vpy'
            vpy_path.write_text(
                'a = r"old.mkv"\n'
                'def helper():\n'
                '    a = 8\n'
                '    return a\n',
                encoding='utf-8',
            )

            self.assertTrue(_write_vpy_video_source_a(str(vpy_path), r'E:\video.mkv'))

            content = vpy_path.read_text(encoding='utf-8')
            self.assertIn('a = r"E:\\video.mkv"', content)
            self.assertIn('    a = 8', content)

    def test_preflight_rejects_invalid_vpy_processing_strengths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'source'
            output_folder = root / 'output'
            source_folder.mkdir()
            output_folder.mkdir()
            source_path = source_folder / 'source.mkv'
            vpy_path = root / 'encode.vpy'
            source_path.write_bytes(b'mkv')
            vpy_path.write_text('a = r""\n', encoding='utf-8')

            for name, value in (
                    ('vpy_denoise_strength', float('nan')),
                    ('vpy_dehalo_strength', 1.1),
                    ('vpy_dering_strength', True),
                    ('vpy_deband_strength', -0.1),
                    ('vpy_antialiasing_strength', 1.1),
            ):
                request = EncodeRequest(
                    input_mode='remux',
                    source_root=str(source_folder),
                    output_folder=str(output_folder),
                    staging_folder='',
                    main_rows=(EncodeRow(
                        str(source_path),
                        str(output_folder / f'{name}.mkv'),
                        str(vpy_path),
                    ),),
                    sp_rows=(),
                    settings=replace(_settings(), **{name: value}),
                )
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, name):
                        validate_encode_request(request)

    def setUp(self) -> None:
        vpy_probe = patch(
            'src.runtime.services_split.encode_and_audio_tasks.probe_vapoursynth_output_metadata',
            side_effect=lambda source, *_args: (source, False, (1, 24, 1)),
        )
        self.vpy_probe = vpy_probe.start()
        self.addCleanup(vpy_probe.stop)

    def test_gui_captures_bdmv_rows_in_one_request_without_hidden_checkbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'Disc'
            output_base = root / 'Output'
            playlist_base = source_folder / 'BDMV' / 'PLAYLIST' / '00001'
            playlist_base.parent.mkdir(parents=True)
            output_base.mkdir()
            playlist_base.with_suffix('.mpls').write_bytes(b'mpls')
            vpy_path = root / 'encode.vpy'
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            configuration = {
                0: {
                    'folder': str(source_folder),
                    'selected_mpls': str(playlist_base),
                    'bdmv_index': 1,
                    'start_at_chapter': 1,
                }
            }
            track_key = f'main::{playlist_base.with_suffix(".mpls")}'
            errors: list[str] = []
            audio_encoding = AudioEncodingSettings(
                flac_compression_level=6,
                ffmpeg_flac_compression_level=10,
                fdkaac_bitrate_kbps=320,
                opus_bitrate_kbps=192,
            )
            owner = SimpleNamespace(
                output_folder_path=SimpleNamespace(text=lambda: str(output_base)),
                bdmv_folder_path=SimpleNamespace(text=lambda: str(source_folder)),
                _encode_input_mode='bdmv',
                _sp_scan_in_progress=True,
                vspipe_mode_combo=SimpleNamespace(currentText=lambda: 'System'),
                x265_mode_combo=SimpleNamespace(currentText=lambda: 'System'),
                sub_pack_hard_radio=SimpleNamespace(isChecked=lambda: False),
                sub_pack_soft_radio=SimpleNamespace(isChecked=lambda: False),
                use_getnative_checkbox=SimpleNamespace(isChecked=lambda: True),
                auto_crop_black_borders_checkbox=SimpleNamespace(
                    isChecked=lambda: True
                ),
                output_comparison_checkbox=SimpleNamespace(isChecked=lambda: True),
                vpy_denoise_strength_spin=SimpleNamespace(value=lambda: 0.7),
                vpy_dehalo_strength_spin=SimpleNamespace(value=lambda: 0.2),
                vpy_dering_strength_spin=SimpleNamespace(value=lambda: 0.3),
                vpy_deband_strength_spin=SimpleNamespace(value=lambda: 0.4),
                vpy_antialiasing_strength_spin=SimpleNamespace(value=lambda: 0.5),
                trim_copyright_tail_checkbox=SimpleNamespace(isChecked=lambda: False),
                mux_dolby_vision_checkbox=SimpleNamespace(isChecked=lambda: False),
                table2=SimpleNamespace(rowCount=lambda: 1, item=lambda _row, _column: None),
                table3=SimpleNamespace(rowCount=lambda: 0),
                ensure_default_vpy_file=lambda: None,
                _current_encode_tool_and_depth=lambda: ('x265', '10'),
                _effective_encode_params=lambda: '--crf 18',
                _current_encode_lossless_audio_codec=lambda: 'opus',
                _captured_audio_encoding_settings=lambda: audio_encoding,
                get_selected_mpls_no_ext=lambda: [(str(source_folder), str(playlist_base))],
                _configuration_for_service_run=lambda: configuration,
                _get_episode_output_names_from_table2=lambda: ['Visible Episode'],
                _get_episode_subtitle_languages_from_table2=lambda: ['jpn'],
                get_vpy_path_from_row=lambda _row: str(vpy_path),
                get_default_vpy_path=lambda: str(vpy_path),
                _is_movie_mode=lambda: False,
                get_selected_function_id=lambda: 4,
                _track_selection_config={track_key: {'audio': ['1'], 'subtitle': ['2']}},
                _track_language_config={track_key: {'1': 'jpn'}},
                _track_lossless_audio_config={track_key: {'1': 'opus'}},
                t=lambda text: text,
                exe_button=SimpleNamespace(text=lambda: 'Start'),
                _update_exe_button_progress=lambda *_args: None,
                _on_exe_button_progress_value=lambda _value: None,
                _on_exe_button_progress_text=lambda _text: None,
                _show_error_dialog=errors.append,
            )

            with patch.object(encode_gui_module, 'QThread', _ThreadCapture), patch.object(
                    encode_gui_module, 'EncodeWorker', _EncodeWorkerCapture), patch.object(
                    encode_gui_module,
                    'validate_encode_request',
                    side_effect=lambda request, check_tools: validate_encode_request(request, False),
            ):
                ActionsAndDialogsMixin.encode_bluray(owner)

            self.assertEqual(errors, [])
            request = _EncodeWorkerCapture.last_request
            self.assertEqual(request.input_mode, 'bdmv')
            self.assertEqual(request.main_rows[0].output_path, str(output_base / 'Disc' / 'Visible Episode.mkv'))
            self.assertEqual(request.main_rows[0].subtitle_language, 'jpn')
            self.assertEqual(request.main_rows[0].vpy_path, str(vpy_path))
            self.assertEqual(request.main_rows[0].audio_tracks, ('1',))
            self.assertEqual(request.main_rows[0].subtitle_tracks, ('2',))
            self.assertEqual(request.main_rows[0].audio_codec_choices, ('opus',))
            self.assertEqual(request.main_rows[0].track_language_overrides, (('1', 'jpn'),))
            self.assertEqual(request.settings.default_lossless_audio_codec, 'opus')
            self.assertTrue(request.settings.auto_crop_black_borders)
            self.assertTrue(request.settings.output_comparison_images)
            self.assertEqual(request.settings.vpy_denoise_strength, 0.7)
            self.assertEqual(request.settings.vpy_dehalo_strength, 0.2)
            self.assertEqual(request.settings.vpy_dering_strength, 0.3)
            self.assertEqual(request.settings.vpy_deband_strength, 0.4)
            self.assertEqual(request.settings.vpy_antialiasing_strength, 0.5)
            self.assertEqual(request.settings.audio_encoding, audio_encoding)
            self.assertFalse(request.mux_dolby_vision)
            self.assertFalse(hasattr(owner, 'checkbox1'))

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
            source_folder = root / 'source'
            output_folder = root / 'output'
            source_folder.mkdir()
            output_folder.mkdir()
            source_path = source_folder / 'source.mkv'
            second_source_path = source_folder / 'second.mkv'
            vpy_path = root / 'encode.vpy'
            source_path.write_bytes(b'mkv')
            second_source_path.write_bytes(b'mkv')
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            output_path = output_folder / 'Episode.mkv'
            second_output_path = output_folder / 'Episode 2.mkv'
            row = EncodeRow(str(source_path), str(output_path), str(vpy_path))
            second_row = EncodeRow(
                str(second_source_path),
                str(second_output_path),
                str(vpy_path),
            )
            request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=(row, second_row),
                sp_rows=(),
                settings=_settings(),
            )

            output_path.write_bytes(b'existing')
            service = _RowEncodeService()
            with patch(
                    'src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths',
                    return_value=None) as dovi_preflight:
                service._encode_mkv_rows(request, [row, second_row], [], threading.Event())
            self.assertEqual(output_path.read_bytes(), b'existing')
            self.assertEqual(second_output_path.read_bytes(), b'encoded')
            self.assertEqual(
                service.encode_calls,
                [(str(second_source_path), str(second_output_path))],
            )
            dovi_preflight.assert_called_once_with(
                [str(second_source_path)],
                request.settings.encoder,
                request.settings.bit_depth,
            )
            self.assertIn(
                f'Skipping existing output: {output_path}',
                service.progress_messages,
            )

            output_path.write_bytes(b'')
            service = _RowEncodeService()
            with patch(
                    'src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths',
                    return_value=None):
                with self.assertRaisesRegex(FileExistsError, 'Existing resumable output is invalid'):
                    service._encode_mkv_rows(request, [row, second_row], [], threading.Event())
            self.assertEqual(service.encode_calls, [])

            bdmv_request = EncodeRequest(
                input_mode='bdmv',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=(row,),
                sp_rows=(),
                settings=_settings(),
            )
            service = _RowEncodeService()
            with patch(
                    'src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths',
                    return_value=None):
                with self.assertRaisesRegex(FileExistsError, 'Output file already exists'):
                    service._encode_mkv_rows(bdmv_request, [row], [], threading.Event())
            self.assertEqual(service.encode_calls, [])

            missing_output_path = output_folder / 'Missing.mkv'
            missing_row = EncodeRow(
                str(second_source_path),
                str(missing_output_path),
                str(vpy_path),
            )
            missing_request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=(missing_row,),
                sp_rows=(),
                settings=_settings(),
            )
            service = _RowEncodeService(create_outputs=False)
            with patch(
                    'src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths',
                    return_value=None):
                result = service._encode_mkv_rows(
                    missing_request,
                    [missing_row],
                    [],
                    threading.Event(),
                )
            self.assertEqual(result.rows[0].status, 'failed')
            self.assertIn('Encode output is missing', result.rows[0].message)

    def test_remux_resume_skips_existing_subtitles_and_companion_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'source'
            output_folder = root / 'output'
            source_folder.mkdir()
            output_folder.mkdir()
            source_path = source_folder / 'source.mkv'
            companion_source = source_folder / 'notes.nfo'
            subtitle_source = root / 'subtitle.ass'
            vpy_path = root / 'encode.vpy'
            source_path.write_bytes(b'mkv')
            companion_source.write_bytes(b'new companion')
            subtitle_source.write_bytes(b'new subtitle')
            vpy_path.write_text('a = r""\n', encoding='utf-8')

            output_path = output_folder / 'Episode.mkv'
            subtitle_destination = output_folder / 'Episode.ass'
            companion_destination = output_folder / 'notes.nfo'
            output_path.write_bytes(b'existing encode')
            subtitle_destination.write_bytes(b'existing subtitle')
            companion_destination.write_bytes(b'existing companion')
            row = EncodeRow(
                str(source_path),
                str(output_path),
                str(vpy_path),
                subtitle_path=str(subtitle_source),
            )
            request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=(row,),
                sp_rows=(),
                settings=_settings(),
            )

            service = _RowEncodeService()
            with patch(
                    'src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths',
                    return_value=None):
                service._encode_mkv_rows(
                    request,
                    [row],
                    [],
                    threading.Event(),
                    companion_root=str(source_folder),
                )

            self.assertEqual(service.encode_calls, [])
            self.assertEqual(output_path.read_bytes(), b'existing encode')
            self.assertEqual(subtitle_destination.read_bytes(), b'existing subtitle')
            self.assertEqual(companion_destination.read_bytes(), b'existing companion')
            self.assertIn(
                f'Skipping existing output: {output_path}',
                service.progress_messages,
            )
            self.assertIn(
                f'Skipping existing output: {subtitle_destination}',
                service.progress_messages,
            )
            self.assertIn(
                f'Skipping existing output: {companion_destination}',
                service.progress_messages,
            )

    def test_comparison_images_use_the_same_frame_number_under_actual_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'source'
            output_folder = root / 'output' / 'Disc'
            source_folder.mkdir()
            output_folder.mkdir(parents=True)
            source_path = source_folder / 'source.mkv'
            output_path = output_folder / '第一集.mkv'
            vpy_path = root / 'encode.vpy'
            source_path.write_bytes(b'source')
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            row = EncodeRow(
                str(source_path),
                str(output_path),
                str(vpy_path),
            )
            request = EncodeRequest(
                input_mode='remux',
                source_root=str(source_folder),
                output_folder=str(output_folder),
                staging_folder='',
                main_rows=(row,),
                sp_rows=(),
                settings=_settings(output_comparison_images=True),
            )
            ffmpeg_commands: list[list[str]] = []

            def fake_ffmpeg(command, **_kwargs):
                ffmpeg_commands.append(list(command))
                Path(command[-1]).write_bytes(b'png')
                return SimpleNamespace(returncode=0, stdout='', stderr='')

            service = _RowEncodeService()
            with (
                patch(
                    'src.runtime.services_split.encode_and_audio_tasks.encode_dovi_preflight_mkv_paths',
                    return_value=None,
                ),
                patch.object(
                    service,
                    '_video_frame_count_static',
                    return_value=120,
                ),
                patch(
                    'src.runtime.services_split.remux_and_episode_workflows.run_command',
                    side_effect=fake_ffmpeg,
                ),
            ):
                result = service._encode_mkv_rows(
                    request,
                    [row],
                    [],
                    threading.Event(),
                )

            self.assertEqual(result.rows[0].status, 'completed')
            self.assertEqual(len(ffmpeg_commands), 2)
            self.assertEqual(
                [command[command.index('-i') + 1] for command in ffmpeg_commands],
                [str(source_path), str(output_path)],
            )
            self.assertEqual(
                [command[command.index('-vf') + 1] for command in ffmpeg_commands],
                ['select=eq(n\\,60)', 'select=eq(n\\,60)'],
            )
            self.assertTrue(all('-ss' not in command for command in ffmpeg_commands))
            comparison_files = sorted(
                path.name for path in (output_folder / 'Compare').glob('*.png')
            )
            self.assertEqual(
                comparison_files,
                [
                    '001-第一集-f000060-encoded.png',
                    '001-第一集-f000060-source.png',
                ],
            )

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

    def test_bdmv_encode_uses_exact_rows_and_never_completes_source_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_folder = root / 'Disc'
            source_folder.mkdir()
            output_folder = root / 'output' / 'Disc'
            staging_folder = root / 'output' / '_encode_remux_stage'
            configuration = {'bdmv_index': 1, 'selected_mpls': '00001', 'start_at_chapter': 1}
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
                    configuration=configuration,
                ),),
                sp_rows=(),
                settings=_settings(),
                selected_mpls=((str(source_folder), '00001'),),
            )
            service = _BdmvEncodeService()
            service.episodes_encode(request, threading.Event())

            self.assertFalse(service.checked)
            self.assertFalse(service.stage_request.complete_bluray_folder)
            self.assertTrue(service.stage_request.mux_dolby_vision)
            self.assertFalse(service.stage_request.convert_lossless_audio_to_flac)
            self.assertFalse(service.stage_request.clean_audio_tracks)
            self.assertEqual(service.stage_request.episode_output_names, ('Episode.mkv',))
            resolved_main = service.resolved_rows[1][0]
            self.assertEqual(resolved_main.output_path, str(output_folder / 'Episode.mkv'))
            self.assertTrue(resolved_main.source_path.endswith(os.path.join('Disc', 'Episode.mkv')))
            self.assertFalse(staging_folder.exists())

    def test_bdmv_svt_stage_omits_dolby_vision_metadata_with_a_warning(self) -> None:
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
                settings=replace(_settings(), encoder='svtav1'),
                selected_mpls=((str(source_folder), '00001'),),
            )
            service = _BdmvEncodeService()
            service.episodes_encode(request, threading.Event())

            self.assertFalse(service.stage_request.mux_dolby_vision)
            self.assertTrue(any(
                'Dolby Vision metadata will not be retained for SVT-AV1 output' in message
                for message in service.progress_messages
            ))

    def test_bdmv_staging_is_retained_when_an_encode_row_fails(self) -> None:
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
            self.assertTrue((staging_folder / 'Disc' / 'Episode.mkv').is_file())
            self.assertTrue(any(
                'Blu-ray staging files were retained' in message
                for message in service.encode_warnings
            ))

    def test_remux_svt_encode_omits_dolby_vision_injection_with_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / 'source.mkv'
            output_path = root / 'output.mkv'
            vpy_path = root / 'encode.vpy'
            source_path.write_bytes(b'mkv')
            vpy_path.write_text(
                'a = r""\n'
                'denoise_strength=6e-1  # keep\n'
                'dehalo_strength = 0.25\n'
                'dering_strength = 0.25\n'
                'deband_strength = 1.0\n'
                'antialiasing_strength = 1.0\n'
                'def helper():\n'
                '    denoise_strength = 9\n'
                'res = core.fmtc.bitdepth(src8, bits=10)\n',
                encoding='utf-8',
            )
            service = _PipelineService()

            def encode_video(_vspipe, _vpy, encoder_command, _environment):
                self.assertEqual(encoder_command[encoder_command.index('--preset') + 1], '6')
                content = Path(_vpy).read_text(encoding='utf-8')
                self.assertIn('denoise_strength=0  # keep', content)
                self.assertIn('dehalo_strength = 0.4', content)
                self.assertIn('dering_strength = 0.5', content)
                self.assertIn('deband_strength = 0.6', content)
                self.assertIn('antialiasing_strength = 0.7', content)
                self.assertIn('    denoise_strength = 9', content)
                Path(encoder_command[encoder_command.index('-b') + 1]).write_bytes(b'av1')
                return 0

            with (
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id',
                        return_value=0,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.probe_actual_encode_source',
                        side_effect=_actual_source,
                    ) as source_probe,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.prepare_dolby_vision_encode'
                    ) as prepare_dolby_vision,
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
                        return_value='SvtAv1EncApp',
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks._run_vspipe_piped_encode',
                        side_effect=encode_video,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.mux_with_audio_conversion'
                    ) as final_mux,
            ):
                service.encode_task(
                    str(output_path),
                    str(vpy_path),
                    'bundle',
                    'bundle',
                    '--preset 6',
                    'external',
                    encoder='svtav1',
                    bit_depth='10',
                    selected_audio_tracks=(),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=(),
                    track_language_overrides=(),
                    subtitle_path='',
                    subtitle_language='',
                    source_file=str(source_path),
                    vpy_denoise_strength=0.0,
                    vpy_dehalo_strength=0.4,
                    vpy_dering_strength=0.5,
                    vpy_deband_strength=0.6,
                    vpy_antialiasing_strength=0.7,
                )

            prepare_dolby_vision.assert_not_called()
            source_probe.assert_called_once_with(str(source_path))
            final_mux.assert_called_once()
            self.assertTrue(any(
                'Dolby Vision metadata will not be retained for SVT-AV1 output' in message
                for message in service.progress_messages
            ))

    def test_custom_x265_without_dynamic_options_uses_post_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / 'source.mkv'
            output_path = root / 'output.mkv'
            vpy_path = root / 'encode.vpy'
            work_folder = root / 'dovi-work'
            base_layer = work_folder / 'base-layer.hevc'
            rpu_path = work_folder / 'rpu.bin'
            source_path.write_bytes(b'mkv')
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            work_folder.mkdir()
            base_layer.write_bytes(b'hevc')
            rpu_path.write_bytes(b'rpu')
            plan = DolbyVisionEncodePlan(
                str(base_layer),
                str(rpu_path),
                str(work_folder),
            )
            crop_plan = VideoCropPlan(
                1920,
                1080,
                7200.0,
                24,
                (),
                top=140,
                bottom=140,
            )
            service = _PipelineService()

            def encode_video(_vspipe, _vpy, encoder_command, environment):
                self.assertEqual(
                    environment['BLURAYSUB_VPY_SOURCE'],
                    os.path.normpath(str(base_layer)),
                )
                self.assertEqual(
                    environment['BLURAYSUB_PLUGIN_PATH'],
                    '/custom/vapoursynth/plugins',
                )
                self.assertEqual(
                    encoder_command[
                        encoder_command.index('--colorprim'):
                        encoder_command.index('--colorprim') + 2
                    ],
                    ['--colorprim', 'bt2020'],
                )
                self.assertEqual(
                    encoder_command[
                        encoder_command.index('--transfer'):
                        encoder_command.index('--transfer') + 2
                    ],
                    ['--transfer', 'smpte2084'],
                )
                self.assertNotIn('--dhdr10-info', encoder_command)
                self.assertNotIn('--dolby-vision-profile', encoder_command)
                self.assertNotIn('--dolby-vision-rpu', encoder_command)
                Path(encoder_command[encoder_command.index('-o') + 1]).write_bytes(b'hevc')
                return 0

            def probe_source(path):
                return _actual_source(
                    path,
                    stream_metadata={
                        'color_range': 'tv',
                        'color_primaries': 'bt2020',
                        'color_transfer': 'smpte2084',
                        'color_space': 'bt2020nc',
                        'avg_frame_rate': '24/1',
                        'side_data_list': [
                            {
                                'side_data_type': 'Mastering display metadata',
                                'green_x': '13250/50000',
                                'green_y': '34500/50000',
                                'blue_x': '7500/50000',
                                'blue_y': '3000/50000',
                                'red_x': '34000/50000',
                                'red_y': '16000/50000',
                                'white_point_x': '15635/50000',
                                'white_point_y': '16450/50000',
                                'max_luminance': '10000000/10000',
                                'min_luminance': '50/10000',
                            },
                            {
                                'side_data_type':
                                    'HDR Dynamic Metadata SMPTE2094-40 (HDR10+)',
                            },
                        ],
                    },
                )

            def extract_hdr10plus(_source, path, _timeline):
                Path(path).write_text('{"SceneInfo": [{}]}', encoding='utf-8')
                return path

            with (
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id',
                        return_value=0,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.prepare_dolby_vision_encode',
                        return_value=plan,
                    ) as prepare_dolby_vision,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.detect_black_borders',
                        return_value=crop_plan,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.probe_actual_encode_source',
                        side_effect=probe_source,
                    ) as source_probe,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.extract_hdr10plus_metadata',
                        side_effect=extract_hdr10plus,
                    ) as hdr10plus_extract,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.inject_hdr10plus_metadata',
                    ) as hdr10plus_inject,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.verify_hdr10plus_metadata',
                    ) as hdr10plus_verify,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.verify_final_video_metadata',
                        side_effect=RuntimeError('final static metadata mismatch'),
                    ) as final_video_verify,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.verify_dolby_vision_rpu'
                    ) as dolby_vision_verify,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.inject_dolby_vision_rpu'
                    ) as dolby_vision_inject,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks._write_vpy_video_source_a',
                        return_value=True,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.write_vapoursynth_crop',
                    ) as write_crop,
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.get_vspipe_context',
                        return_value=('vspipe', {}),
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.PLUGIN_PATH',
                        '/custom/vapoursynth/plugins',
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.resolve_encoder_executable_path',
                        return_value='x265',
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.probe_x265_dynamic_metadata_options',
                        return_value=frozenset(),
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks._run_vspipe_piped_encode',
                        side_effect=encode_video,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.mux_with_audio_conversion'
                    ) as final_mux,
            ):
                service.encode_task(
                    str(output_path),
                    str(vpy_path),
                    'bundle',
                    'bundle',
                    '--crf 18 --vbv-maxrate 30000 --vbv-bufsize 30000',
                    'external',
                    encoder='x265',
                    bit_depth='10',
                    selected_audio_tracks=(),
                    selected_subtitle_tracks=(),
                    audio_codec_choices=(),
                    track_language_overrides=(),
                    source_file=str(source_path),
                    auto_crop_black_borders=True,
                )

            prepare_dolby_vision.assert_called_once_with(
                str(source_path),
                0,
                str(root),
                crop_plan,
            )
            write_crop.assert_called_once_with(str(vpy_path), crop_plan)
            source_probe.assert_called_once_with(str(base_layer))
            self.assertEqual(self.vpy_probe.call_args.args[0].path, str(base_layer))
            hdr10plus_extract.assert_called_once()
            hdr10plus_inject.assert_called_once()
            hdr10plus_verify.assert_called_once()
            final_video_verify.assert_called_once()
            self.assertEqual(dolby_vision_verify.call_count, 3)
            dolby_vision_inject.assert_called_once()
            final_mux.assert_called_once()
            self.assertFalse(work_folder.exists())
            self.assertEqual(list(root.glob('*.hdr10plus.json')), [])
            self.assertEqual(len(list(root.glob('output.hdr-metadata-error*.txt'))), 1)
            self.assertTrue(any(
                'Final HDR metadata verification failed' in message
                for message in service.encode_warnings
            ))
            self.assertTrue(any(
                'Actual encode source: base-layer.hevc' in message
                for message in service.progress_messages
            ))

    def test_native_x265_uses_the_preprocessed_dolby_vision_rpu_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / 'base-layer.hevc'
            vpy_path = root / 'encode.vpy'
            processed_rpu = root / 'rpu.bin'
            source_path.write_bytes(b'hevc')
            vpy_path.write_text('res = src8\n', encoding='utf-8')
            processed_rpu.write_bytes(b'processed-rpu')
            service = _PipelineService()

            with (
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.'
                        'probe_actual_encode_source',
                        return_value=_actual_source(str(source_path)),
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.'
                        'probe_x265_dynamic_metadata_options',
                        return_value=frozenset({
                            '--dolby-vision-profile',
                            '--dolby-vision-rpu',
                        }),
                    ),
            ):
                result = _plan_automatic_encoder_metadata(
                    service,
                    str(root / 'output.mkv'),
                    str(source_path),
                    str(vpy_path),
                    'vspipe',
                    {},
                    'x265',
                    'x265',
                    '10',
                    '--vbv-maxrate 30000 --vbv-bufsize 30000 '
                    '--master-display G(13250,34500)',
                    str(root / 'hdr10plus.json'),
                    str(processed_rpu),
                )

            automatic_arguments = result[1]
            self.assertTrue(result[4])
            self.assertEqual(
                automatic_arguments[
                    automatic_arguments.index('--dolby-vision-rpu') + 1
                ],
                str(processed_rpu),
            )

    def test_source_probe_failure_writes_report_and_encoding_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / 'source.mkv'
            output_path = root / 'output.mkv'
            vpy_path = root / 'encode.vpy'
            source_path.write_bytes(b'mkv')
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            service = _PipelineService()

            def encode_video(_vspipe, _vpy, encoder_command, _environment):
                Path(encoder_command[encoder_command.index('-o') + 1]).write_bytes(b'hevc')
                return 0

            with (
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id',
                        return_value=None,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.probe_actual_encode_source',
                        side_effect=RuntimeError('ffprobe failed'),
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
                        side_effect=encode_video,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.mux_with_audio_conversion'
                    ) as final_mux,
            ):
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
                    source_file=str(source_path),
                )

            final_mux.assert_called_once()
            reports = list(root.glob('output.hdr-metadata-error*.txt'))
            self.assertEqual(len(reports), 1)
            self.assertIn('ffprobe failed', reports[0].read_text(encoding='utf-8'))
            self.assertEqual(len(service.encode_warnings), 1)
            self.assertIn('encoding will continue', service.encode_warnings[0])

    def test_metadata_parameter_failure_writes_report_and_encoding_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / 'source.mkv'
            output_path = root / 'output.mkv'
            vpy_path = root / 'encode.vpy'
            source_path.write_bytes(b'mkv')
            vpy_path.write_text('a = r""\n', encoding='utf-8')
            service = _PipelineService()

            def encode_video(_vspipe, _vpy, encoder_command, _environment):
                self.assertNotIn('--colorprim', encoder_command)
                Path(encoder_command[encoder_command.index('-o') + 1]).write_bytes(b'hevc')
                return 0

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
                        'src.runtime.services_split.encode_and_audio_tasks.build_automatic_encoder_metadata_arguments',
                        side_effect=RuntimeError('metadata planning failed'),
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
                        side_effect=encode_video,
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.mux_with_audio_conversion'
                    ) as final_mux,
            ):
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
                    source_file=str(source_path),
                )

            final_mux.assert_called_once()
            reports = list(root.glob('output.hdr-metadata-error*.txt'))
            self.assertEqual(len(reports), 1)
            report_text = reports[0].read_text(encoding='utf-8')
            self.assertIn('Automatic encoder metadata parameter generation', report_text)
            self.assertIn('metadata planning failed', report_text)
            self.assertEqual(len(service.encode_warnings), 1)
            self.assertIn(
                'Automatic encoder metadata parameter generation failed',
                service.encode_warnings[0],
            )

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
