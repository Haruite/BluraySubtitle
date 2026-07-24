"""Focused contracts for the unified Blu-ray Encode workflow."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.runtime.encode import EncodeRequest, EncodeRow, EncodeSettings, validate_encode_request
from src.runtime.services import BluraySubtitle as _BluraySubtitle
from src.runtime.services_split.encode_and_audio_tasks import EncodeAudioTasksMixin
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin
from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI as _BluraySubtitleGUI
from src.runtime.gui_runtime_split import actions_and_file_dialogs as encode_gui_module
from src.runtime.gui_runtime_split.actions_and_file_dialogs import ActionsAndDialogsMixin


class _Signal:
    def connect(self, _callback) -> None:
        pass


class _EncodeWorkerCapture:
    last_request = None

    def __init__(self, request, _cancel_event) -> None:
        type(self).last_request = request
        self.progress = _Signal()
        self.label = _Signal()
        self.finished = _Signal()
        self.canceled = _Signal()
        self.failed = _Signal()

    def moveToThread(self, _thread) -> None:
        pass

    def run(self) -> None:
        pass


class _ThreadCapture:
    def __init__(self, _owner) -> None:
        self.started = _Signal()

    def start(self) -> None:
        pass


def _settings() -> EncodeSettings:
    return EncodeSettings(
        vspipe_mode='bundle',
        encoder_mode='bundle',
        encoder_parameters='--crf 18',
        subtitle_mode='external',
        encoder='x265',
        bit_depth='10',
        use_getnative=False,
        default_lossless_audio_codec='flac',
    )


class _RowEncodeService(RemuxEpisodeWorkflowsMixin):
    def __init__(self, create_outputs: bool = True) -> None:
        self.create_outputs = create_outputs
        self.encode_calls: list[tuple[str, str]] = []
        self.progress_messages: list[str] = []

    def t(self, text: str) -> str:
        return text

    def _progress(self, value=None, text=None) -> None:
        if text:
            self.progress_messages.append(text)

    def encode_task(self, output_file, _dst_folder, _index, _vpy_path, *_args, source_file=None, **_kwargs):
        self.encode_calls.append((source_file, output_file))
        if self.create_outputs:
            Path(output_file).write_bytes(b'encoded')


class _BdmvEncodeService(_RowEncodeService):
    def __init__(self) -> None:
        super().__init__()
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


class _PipelineService(EncodeAudioTasksMixin):
    use_getnative = False
    sub_files = []

    def t(self, text: str) -> str:
        return text

    def _progress(self, value=None, text=None) -> None:
        pass

    def _log_getnative(self, _message: str) -> None:
        pass

    def _cleanup_getnative_artifacts(self) -> None:
        pass

    def process_audio_to_flac(self, *_args, **_kwargs):
        raise AssertionError('Audio processing must not start after an encoder failure')


class EncodeWorkflowTests(unittest.TestCase):
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
            errors: list[str] = []
            owner = SimpleNamespace(
                output_folder_path=SimpleNamespace(text=lambda: str(output_base)),
                bdmv_folder_path=SimpleNamespace(text=lambda: str(source_folder)),
                _encode_input_mode='bdmv',
                vspipe_mode_combo=SimpleNamespace(currentText=lambda: 'System'),
                x265_mode_combo=SimpleNamespace(currentText=lambda: 'System'),
                sub_pack_hard_radio=SimpleNamespace(isChecked=lambda: False),
                sub_pack_soft_radio=SimpleNamespace(isChecked=lambda: False),
                use_getnative_checkbox=SimpleNamespace(isChecked=lambda: True),
                trim_copyright_tail_checkbox=SimpleNamespace(isChecked=lambda: False),
                mux_dolby_vision_checkbox=SimpleNamespace(isChecked=lambda: False),
                table2=SimpleNamespace(rowCount=lambda: 1, item=lambda _row, _column: None),
                table3=SimpleNamespace(rowCount=lambda: 0),
                ensure_default_vpy_file=lambda: None,
                _current_encode_tool_and_depth=lambda: ('x265', '10'),
                _effective_encode_params=lambda: '--crf 18',
                _current_encode_lossless_audio_codec=lambda: 'opus',
                get_selected_mpls_no_ext=lambda: [(str(source_folder), str(playlist_base))],
                _configuration_for_service_run=lambda: configuration,
                _get_episode_output_names_from_table2=lambda: ['Visible Episode'],
                _get_episode_subtitle_languages_from_table2=lambda: ['jpn'],
                get_vpy_path_from_row=lambda _row: str(vpy_path),
                get_default_vpy_path=lambda: str(vpy_path),
                _is_movie_mode=lambda: False,
                get_selected_function_id=lambda: 4,
                _track_selection_config={'main': {'audio': ['1']}},
                _track_language_config={'main': {'1': 'jpn'}},
                _track_lossless_audio_config={'main': {'1': 'opus'}},
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
            self.assertEqual(request.settings.default_lossless_audio_codec, 'opus')
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
                with self.assertRaisesRegex(RuntimeError, 'Encode output is missing'):
                    service._encode_mkv_rows(
                        missing_request,
                        [missing_row],
                        [],
                        threading.Event(),
                    )

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
            self.assertEqual(service.stage_request.episode_output_names, ('Episode.mkv',))
            resolved_main = service.resolved_rows[1][0]
            self.assertEqual(resolved_main.output_path, str(output_folder / 'Episode.mkv'))
            self.assertTrue(resolved_main.source_path.endswith(os.path.join('Disc', 'Episode.mkv')))
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
            with (
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.MediaInfoTrackMappingMixin.mkvinfo_dolby_vision_track_id',
                        return_value=None,
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
                        return_value=7,
                    )
            ):
                with self.assertRaisesRegex(RuntimeError, 'exit code 7'):
                    service.encode_task(
                        str(output_path),
                        str(root),
                        1,
                        str(vpy_path),
                        'bundle',
                        'bundle',
                        '--crf 18',
                        'external',
                        source_file=str(source_path),
                    )
            self.assertFalse(output_path.exists())


if __name__ == '__main__':
    unittest.main()
