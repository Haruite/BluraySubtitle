"""Focused contracts for the unified Blu-ray Encode workflow."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.core.tool_paths import default_tool_paths, tool_path, using_tool_paths
from src.exports.utils import terminate_process_trees
from src.runtime import dolby_vision
from src.runtime.encode import EncodeRequest, EncodeRow, EncodeSettings, validate_encode_request
from src.runtime.encode_command import format_encoder_command
from src.runtime.encode_results import (
    EncodeBatchResult,
    EncodeRowResult,
    EncodeTaskFailure,
)
from src.runtime.encode_source import ActualEncodeSource
from src.runtime import hardware_encode
from src.runtime.hardware_encode import GpuEncodeDevice, VideoEncodeChoice, hardware_encode_command
from src.runtime.video_timeline import VideoTimeline
from src.runtime import TaskCancelled
from src.runtime.services_split.encode_and_audio_tasks import EncodeAudioTasksMixin
from src.runtime.services_split.remux_and_episode_workflows import RemuxEpisodeWorkflowsMixin


def _settings() -> EncodeSettings:
    return EncodeSettings(
        encoder_parameters='--crf 18',
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
    def test_cpu_command_uses_its_visible_executable_and_output_instead_of_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / 'source'
            source_dir.mkdir()
            source = source_dir / 'input.mkv'
            source.touch()
            vpy = root / 'encode.vpy'
            vpy.touch()
            output = root / 'output' / 'episode.mkv'
            request = EncodeRequest(
                'remux', str(source_dir), str(output.parent), '',
                (EncodeRow(str(source), str(output), str(vpy)),), (), _settings(),
            )
            tool_paths = dict.fromkeys(
                ('VSPIPE_PATH', 'FFPROBE_PATH', 'MKV_MERGE_PATH', 'MKV_EXTRACT_PATH'), sys.executable,
            )
            tool_paths.update(PLUGIN_PATH='', X265_PATH=str(root / 'missing-x265'))
            report = str(root / 'stats with spaces.txt')
            text = format_encoder_command((sys.executable, '--stats', report, '--output={output.ivf}', '-'))
            with using_tool_paths(tool_paths):
                prepared = validate_encode_request(
                    replace(request, settings=replace(request.settings, cpu_command=text)), check_tools=True,
                )
                with self.assertRaisesRegex(ValueError, 'output placeholder'):
                    validate_encode_request(
                        replace(request, settings=replace(request.settings, cpu_command=sys.executable)),
                        check_tools=True,
                    )
            command = prepared.settings.cpu_command
            self.assertIsNotNone(command)
            temporary = str(root / 'temporary video.ivf')
            self.assertEqual(command.materialize(temporary, ('--crf', '38')), [
                os.path.abspath(sys.executable), '--stats', report, f'--output={temporary}', '-',
            ])
            self.assertEqual(command.output_extension, '.ivf')
            self.assertFalse(output.parent.exists())

    def test_windows_arm64_discovery_matches_vulkan_to_nvidia_without_trials(self) -> None:
        nvenc = GpuEncodeDevice('nvidia', 'NVIDIA', 'nvenc', 'd3d11va', '0', hardware_id='luid:01')
        qsv = GpuEncodeDevice('intel', 'Intel', 'qsv', 'd3d11va', '1', hardware_id='luid:02')
        listed = b' V..... hevc_nvenc\n V..... h264_nvenc\n V..... hevc_mf\n V..... hevc_qsv\n V..... ffv1_vulkan\n'

        def run(args, **kwargs):
            if args[1:] == ['nvenc', '0']:
                output = b'hevc 8\nvvc 10\n'
            elif args[1:] == ['--list-vulkan']:
                output = (b'8086\t00000000000000000000000000000002\tluid:02\t8,10\tIntel\n'
                          b'10de\t00000000000000000000000000000001\tluid:01\t10,12\tNVIDIA\n')
            elif '-encoders' in args:
                output = listed
            elif '-h' in args:
                output = b''
            else:
                self.fail(f'Unexpected GPU probe command: {args}')
            return subprocess.CompletedProcess(args, 0, output, b'')

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bluraysub-gpu-capabilities.exe').touch()
            with (
                patch.object(hardware_encode, 'sys', SimpleNamespace(platform='win32')),
                patch.object(hardware_encode, '_windows_arm64', return_value=True),
                patch.object(hardware_encode, '_windows_adapters', return_value=[nvenc, qsv]),
                patch.object(hardware_encode, 'run_command', side_effect=run),
            ):
                devices = hardware_encode.discover_gpu_encoders(str(root / 'ffmpeg.exe'), str(root / 'ffprobe.exe'))

        device, = devices
        self.assertEqual((device.key, device.formats), ('nvidia', (('hevc', '8'), ('ffv1', '10'), ('ffv1', '12'))))
        presets = hardware_encode.gpu_presets(device, 'ffv1', '12')
        self.assertEqual(set(presets), {'Fast', 'Balanced'})
        choice = VideoEncodeChoice('ffv1', '12', presets['Balanced'], device)
        command = hardware_encode_command('ffmpeg', choice, ['-i', 'pipe:0'], ['-f', 'matroska', 'output.mkv'])
        self.assertEqual(command[command.index('-init_hw_device') + 1], 'vulkan=encode:00000000-0000-0000-0000-000000000001')
        self.assertEqual(command[command.index('-c:v') + 1], 'ffv1_vulkan')

    def test_chroma_probe_keeps_only_formats_produced_by_the_selected_gpu_mode(self) -> None:
        device = GpuEncodeDevice('nvidia', 'NVIDIA', 'nvenc', 'd3d11va', '2', cuda_adapter='1')
        choice = VideoEncodeChoice('hevc', '10', '-preset p7 -cq 20', device)

        def run(args, **kwargs):
            if args[0] == 'ffprobe':
                pixels = kwargs['input'].decode()
                result = {'streams': [{'codec_name': 'hevc', 'pix_fmt': pixels, 'nb_read_frames': '4'}]}
                return subprocess.CompletedProcess(args, 0, json.dumps(result).encode(), b'')
            self.assertEqual(args[args.index('-c:v') + 1], 'hevc_nvenc')
            self.assertEqual(args[args.index('-preset') + 1], 'p7')
            self.assertEqual(args[args.index('-cq') + 1], '20')
            pixel_format = args[args.index('-vf') + 1].split(',')[0]
            if pixel_format == 'format=p010le':
                self.assertIn('d3d11va=adapter:2', args)
            else:
                self.assertEqual(args[args.index('-gpu') + 1], '1')
            # The driver silently falls back to 4:2:0 for the 4:4:4 trial.
            decoded = b'yuv422p10le' if pixel_format == 'format=p210le' else b'yuv420p10le'
            return subprocess.CompletedProcess(args, 0, decoded, b'')

        with patch.object(hardware_encode, 'run_command', side_effect=run):
            formats = hardware_encode.probe_gpu_chroma_formats('ffmpeg', 'ffprobe', choice, threading.Event())
        self.assertEqual(formats, ('yuv420', 'yuv422'))

    def test_prores_hardware_command_selects_12_bit_4444(self) -> None:
        device = GpuEncodeDevice('macos', 'VideoToolbox', 'videotoolbox')
        choice = VideoEncodeChoice('prores', '12', '-profile:v xq', device)
        command = hardware_encode_command(
            'ffmpeg', choice, ['-i', 'pipe:0'], ['-f', 'matroska', 'output.mkv'],
            metadata_args=('--chromaloc', '2'),
        )
        self.assertEqual(command[command.index('-c:v') + 1], 'prores_videotoolbox')
        self.assertEqual(command[command.index('-vf') + 1], 'format=ayuv64le')
        self.assertEqual(command[command.index('-profile:v') + 1], 'xq')
        self.assertNotIn('-bsf:v', command)

    def setUp(self) -> None:
        vpy_probe = patch(
            'src.runtime.services_split.encode_and_audio_tasks.probe_vapoursynth_output_metadata',
            side_effect=lambda source, *_args: (source, False, (1, 24, 1), 1),
        )
        self.vpy_probe = vpy_probe.start()
        self.addCleanup(vpy_probe.stop)

    def test_dolby_vision_profile_7_uses_a_container_for_base_layer_decoding(self) -> None:
        def run_tool(command, **_kwargs):
            if command[0] == 'MKV_EXTRACT_PATH':
                destination = command[-1].split(':', 1)[1]
            else:
                destination = command[command.index('-o') + 1]
            Path(destination).write_bytes(b'output')
            return subprocess.CompletedProcess(command, 0)

        with (
                tempfile.TemporaryDirectory() as temporary_directory,
                patch.object(dolby_vision, 'require_tool_path', side_effect=lambda name: name),
                patch.object(dolby_vision, 'run_command', side_effect=run_tool) as run_command,
                patch.object(dolby_vision, 'inspect_dolby_vision', return_value=(7, 'FEL')),
        ):
            source = Path(temporary_directory, 'source.mkv')
            source.write_bytes(b'source')
            plan = dolby_vision.prepare_dolby_vision_encode(
                str(source), 0, temporary_directory, default_duration_ns=41708333,
            )
            mux_command, = [call.args[0] for call in run_command.call_args_list if call.args[0][0] == 'MKV_MERGE_PATH']
            self.assertEqual(Path(plan.base_layer_path).suffix, '.mkv')
            self.assertTrue(Path(plan.base_layer_path).is_file())
            self.assertEqual(mux_command[mux_command.index('-o') + 1], plan.base_layer_path)
            self.assertEqual(mux_command[mux_command.index('--default-duration') + 1], '0:41708333ns')
            self.assertTrue(plan.fel_residual_discarded)

    def test_hardware_hevc_signals_the_vpy_chroma_location_in_the_bitstream(self) -> None:
        device = GpuEncodeDevice('gpu0', 'GPU', 'nvenc')
        command = hardware_encode_command(
            'ffmpeg', VideoEncodeChoice('hevc', '10', '', device),
            ['-i', 'pipe:0'], ['-f', 'hevc', 'output.hevc'],
            metadata_args=('--chromaloc', '2'),
        )
        self.assertEqual(command[command.index('-bsf:v') + 1], 'hevc_metadata=chroma_sample_loc_type=2')

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

    def test_rows_on_distinct_devices_run_concurrently_with_their_captured_parameters(self) -> None:
        ready = threading.Barrier(3, timeout=3)
        seen = {}

        class ConcurrentService(_RowEncodeService):
            def encode_task(self, output_file, vpy_path, parameters, _subtitle_mode, **options):
                seen[output_file] = (
                    parameters, options['encoder'], options['bit_depth'],
                    options['hardware_device'], tool_path('FFMPEG_PATH'),
                )
                script = Path(vpy_path)
                if script == original_script or script.parent != original_script.parent:
                    raise AssertionError(f'Unexpected row script: {script}')
                script.write_text(parameters, encoding='utf-8')
                ready.wait()
                if script.read_text(encoding='utf-8') != parameters:
                    raise AssertionError('Another device modified this row script')
                Path(output_file).write_bytes(b'encoded')

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = root / 'source'
            sources.mkdir()
            output = root / 'output'
            original_script = root / 'shared.vpy'
            original_script.write_text('original', encoding='utf-8')
            paths = [sources / f'{name}.mkv' for name in ('main', 'sp1', 'sp2')]
            for path in paths:
                path.write_bytes(b'source')
            device = GpuEncodeDevice('adapter1', 'GPU', 'nvenc', formats=(('hevc', '10'),))
            other_device = replace(device, key='adapter2')
            main, sp, other_sp = (
                EncodeRow(str(path), str(output / path.name), str(original_script))
                for path in paths
            )
            sp = replace(sp, video_encode=VideoEncodeChoice('hevc', '10', '-preset p5 -cq 22', device))
            other_sp = replace(other_sp, video_encode=VideoEncodeChoice('hevc', '10', '-preset p3', other_device))
            request = EncodeRequest('remux', str(sources), str(output), '', (main,), (sp, other_sp), _settings())

            with using_tool_paths(default_tool_paths() | {'FFMPEG_PATH': 'captured-ffmpeg'}):
                result = ConcurrentService().episodes_encode(request, threading.Event())

            self.assertEqual([row.status for row in result.rows], ['completed'] * 3)
            self.assertEqual([row.output_path for row in result.rows], [main.output_path, sp.output_path, other_sp.output_path])
            self.assertEqual(seen[main.output_path], ('--crf 18', 'x265', '10', None, 'captured-ffmpeg'))
            self.assertEqual(seen[sp.output_path], ('-preset p5 -cq 22', 'hevc', '10', device, 'captured-ffmpeg'))
            self.assertEqual(seen[other_sp.output_path], ('-preset p3', 'hevc', '10', other_device, 'captured-ffmpeg'))
            self.assertEqual(original_script.read_text(encoding='utf-8'), 'original')
            self.assertEqual(list(root.glob('.encode-*.vpy')), [])

    @unittest.skipUnless(os.name == 'posix', 'Requires POSIX process groups')
    def test_cancellation_closes_the_output_of_a_wrapped_encoder(self) -> None:
        encoder = (
            "import signal, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "print('ready', flush=True)\n"
            "time.sleep(5)"
        )
        launcher = (
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-c', sys.argv[1]])\n"
            "time.sleep(5)"
        )
        with subprocess.Popen([sys.executable, '-c', launcher, encoder],
                              start_new_session=True, stdout=subprocess.PIPE) as process:
            self.assertTrue(select.select([process.stdout], [], [], 3)[0])
            self.assertEqual(process.stdout.readline(), b'ready\n')
            terminate_process_trees((process,), grace=0.1)
            # A surviving encoder keeps its inherited output open.
            self.assertTrue(select.select([process.stdout], [], [], 1)[0])
            self.assertEqual(process.stdout.read(1), b'')

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

            def fail_encode(vspipe, _vpy, encoder_command, _environment):
                self.assertEqual(vspipe, str(root / 'my-vspipe'))
                self.assertEqual(encoder_command[0], str(root / 'my-x265'))
                Path(encoder_command[encoder_command.index('-o') + 1]).write_bytes(
                    b'partial-hevc'
                )
                return 7

            def extract_timeline(_source, _track_id, path, _cancel, **_options):
                timeline = VideoTimeline((125_000_000, 166_708_333))
                return timeline.write_prefix(path, 1)

            with (
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.MediaInfoTrackMappingMixin._mkvmerge_identify_json',
                        return_value={'tracks': [{'id': 0, 'type': 'video'}]},
                    ),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks.extract_video_timeline',
                        side_effect=extract_timeline,
                    ),
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
                    using_tool_paths({
                        **default_tool_paths(), 'VSPIPE_PATH': str(root / 'my-vspipe'),
                        'X265_PATH': str(root / 'my-x265'), 'PLUGIN_PATH': str(root),
                    }),
                    patch(
                        'src.runtime.services_split.encode_and_audio_tasks._run_vspipe_piped_encode',
                        side_effect=fail_encode,
                    )
            ):
                with self.assertRaisesRegex(EncodeTaskFailure, 'exit code 7') as failure:
                    service.encode_task(
                        str(output_path),
                        str(vpy_path),
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
            self.assertEqual(len(failure.exception.artifact_paths), 2)
            artifact_path = Path(failure.exception.artifact_paths[0])
            self.assertTrue(artifact_path.name.startswith('output.partial.'))
            self.assertEqual(artifact_path.suffix, '.hevc')
            self.assertEqual(artifact_path.read_bytes(), b'partial-hevc')
            for timestamp_path in failure.exception.artifact_paths[1:]:
                self.assertEqual(
                    VideoTimeline.read(timestamp_path).timestamps_ns,
                    (125_000_000, 166_708_333),
                )

if __name__ == '__main__':
    unittest.main()
