"""Tests for explicit GUI-worker-service configuration transfer."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from src.runtime.gui_runtime_classes import encode_worker as encode_worker_module
from src.runtime.gui_runtime_classes import merge_worker as merge_worker_module
from src.runtime.gui_runtime_classes import remux_worker as remux_worker_module
from src.runtime.encode import EncodeRequest, EncodeRow, EncodeSettings
from src.runtime.encode_results import EncodeBatchResult, EncodeRowResult


class _FakeService:
    instances: list["_FakeService"] = []
    warning_message: str | None = None
    encode_result: EncodeBatchResult | None = None

    def __init__(self, *args, **kwargs) -> None:
        self.init_args = args
        self.init_kwargs = kwargs
        self.remux_call = None
        self.encode_call = None
        self.merge_call = None
        self.completion_called = False
        self.encode_warnings = (
            [type(self).warning_message]
            if type(self).warning_message is not None
            else []
        )
        type(self).instances.append(self)

    def episodes_remux(self, *args, **kwargs) -> None:
        self.configuration_was_preassigned = hasattr(self, "configuration")
        self.remux_call = (args, kwargs)

    def episodes_encode(self, *args, **kwargs) -> EncodeBatchResult:
        self.configuration_was_preassigned = hasattr(self, "configuration")
        self.encode_call = (args, kwargs)
        return type(self).encode_result or EncodeBatchResult(())

    def merge_subtitles(self, *args, **kwargs) -> None:
        self.merge_call = (args, kwargs)

    def completion(self) -> None:
        self.completion_called = True


class WorkerConfigurationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeService.instances.clear()
        _FakeService.warning_message = None
        _FakeService.encode_result = None

    @staticmethod
    def _encode_request(configuration: dict) -> EncodeRequest:
        return EncodeRequest(
            input_mode='bdmv',
            source_root='disc',
            output_folder='output/disc',
            staging_folder='output/_encode_remux_stage',
            main_rows=(EncodeRow(
                source_path='',
                output_path='output/disc/Episode.mkv',
                vpy_path='episode.vpy',
                configuration_key=0,
                configuration=configuration[0],
            ),),
            sp_rows=(),
            settings=EncodeSettings(
                vspipe_mode='bundle',
                encoder_mode='bundle',
                encoder_parameters='--crf 18',
                subtitle_mode='external',
                encoder='x265',
                bit_depth='10',
                use_getnative=True,
                default_lossless_audio_codec='flac',
            ),
        )

    def test_remux_worker_passes_only_its_explicit_configuration(self) -> None:
        configuration = {0: {"selected_mpls": "00001", "start_at_chapter": 1}}
        request = remux_worker_module.RemuxRequest(
            bdmv_path='disc',
            subtitle_files=('',),
            complete_bluray_folder=True,
            output_folder='output',
            configuration=configuration,
            selected_mpls=(),
            sp_entries=(),
            episode_output_names=('Episode.mkv',),
            episode_subtitle_languages=('eng',),
        )
        worker = remux_worker_module.RemuxWorker(request, threading.Event())

        with patch.object(remux_worker_module, "BluraySubtitle", _FakeService):
            worker.run()

        service = _FakeService.instances[0]
        self.assertEqual(service.init_args[:3], ('disc', [''], True))
        self.assertFalse(service.configuration_was_preassigned)
        self.assertIs(service.remux_call[0][0], request)
        self.assertIs(service.remux_call[0][0].configuration, configuration)

    def test_encode_worker_passes_only_its_explicit_configuration(self) -> None:
        configuration = {0: {"selected_mpls": "00001", "start_at_chapter": 1}}
        request = self._encode_request(configuration)
        worker = encode_worker_module.EncodeWorker(request, threading.Event())

        with patch.object(encode_worker_module, "BluraySubtitle", _FakeService):
            worker.run()

        service = _FakeService.instances[0]
        self.assertFalse(service.configuration_was_preassigned)
        self.assertEqual(service.init_args[:3], ('disc', [''], False))
        self.assertIs(service.encode_call[0][0], request)
        self.assertIs(service.encode_call[0][0].main_rows[0].configuration, configuration[0])

    def test_encode_worker_reports_warnings_after_success(self) -> None:
        configuration = {0: {"selected_mpls": "00001", "start_at_chapter": 1}}
        worker = encode_worker_module.EncodeWorker(
            self._encode_request(configuration),
            threading.Event(),
        )
        finished = []
        warnings = []
        worker.finished.connect(lambda: finished.append(True))
        worker.finished_with_warnings.connect(warnings.append)
        _FakeService.warning_message = 'source probe warning'

        with patch.object(encode_worker_module, "BluraySubtitle", _FakeService):
            worker.run()

        self.assertEqual(finished, [])
        self.assertEqual(warnings, ['source probe warning'])

    def test_encode_worker_reports_row_errors_without_emitting_global_failure(self) -> None:
        configuration = {0: {"selected_mpls": "00001", "start_at_chapter": 1}}
        worker = encode_worker_module.EncodeWorker(
            self._encode_request(configuration),
            threading.Event(),
        )
        row_errors = []
        failures = []
        finished = []
        worker.finished_with_errors.connect(row_errors.append)
        worker.failed.connect(failures.append)
        worker.finished.connect(lambda: finished.append(True))
        _FakeService.warning_message = 'row failed and later rows continued'
        _FakeService.encode_result = EncodeBatchResult((EncodeRowResult(
            row_type='Main row',
            source_path='source.mkv',
            output_path='Episode.mkv',
            status='failed_with_artifacts',
            report_path='Episode.encode-error.txt',
            artifact_paths=('Episode.partial.hevc',),
        ),))

        with patch.object(encode_worker_module, "BluraySubtitle", _FakeService):
            worker.run()

        self.assertEqual(failures, [])
        self.assertEqual(finished, [])
        self.assertEqual(len(row_errors), 1)
        self.assertIn('Failed rows: 1', row_errors[0])
        self.assertIn('Episode.encode-error.txt', row_errors[0])
        self.assertIn('Episode.partial.hevc', row_errors[0])

    def test_merge_worker_passes_one_complete_request_and_applies_completion(self) -> None:
        request = merge_worker_module.MergeSubtitleRequest(
            bdmv_path='disc',
            subtitle_files=('movie.sup',),
            complete_bluray_folder=True,
            selected_mpls=(('disc', 'disc/BDMV/PLAYLIST/00001'),),
            subtitle_suffix='.zh-Hans',
            movie_tasks=(('movie.sup', 'disc', 'disc/BDMV/PLAYLIST/00001'),),
        )
        worker = merge_worker_module.MergeWorker(request, threading.Event())

        with patch.object(merge_worker_module, 'BluraySubtitle', _FakeService):
            worker.run()

        service = _FakeService.instances[0]
        self.assertEqual(service.init_args[:3], ('disc', ['movie.sup'], True))
        self.assertTrue(service.init_kwargs['movie_mode'])
        self.assertEqual(service.merge_call[0][0], list(request.selected_mpls))
        self.assertEqual(service.merge_call[1]['movie_tasks'], list(request.movie_tasks))
        self.assertEqual(service.merge_call[1]['subtitle_suffix'], '.zh-Hans')
        self.assertTrue(service.completion_called)


if __name__ == "__main__":
    unittest.main()
