"""Tests for explicit GUI-worker-service configuration transfer."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from src.runtime.gui_runtime_classes import encode_worker as encode_worker_module
from src.runtime.gui_runtime_classes import merge_worker as merge_worker_module
from src.runtime.gui_runtime_classes import remux_worker as remux_worker_module


class _FakeService:
    instances: list["_FakeService"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.init_args = args
        self.init_kwargs = kwargs
        self.remux_call = None
        self.encode_call = None
        self.merge_call = None
        self.completion_called = False
        type(self).instances.append(self)

    def episodes_remux(self, *args, **kwargs) -> None:
        self.configuration_was_preassigned = hasattr(self, "configuration")
        self.remux_call = (args, kwargs)

    def episodes_encode(self, *args, **kwargs) -> None:
        self.configuration_was_preassigned = hasattr(self, "configuration")
        self.encode_call = (args, kwargs)

    def merge_subtitles(self, *args, **kwargs) -> None:
        self.merge_call = (args, kwargs)

    def completion(self) -> None:
        self.completion_called = True


class WorkerConfigurationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeService.instances.clear()

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
        worker = encode_worker_module.EncodeWorker(
            "disc",
            [""],
            True,
            "output",
            configuration,
            [],
            threading.Event(),
            ["episode.vpy"],
            [],
            [],
            ["Episode.mkv"],
            ["eng"],
            "bundle",
            "bundle",
            "--crf 18",
            "external",
        )

        with patch.object(encode_worker_module, "BluraySubtitle", _FakeService):
            worker.run()

        service = _FakeService.instances[0]
        self.assertFalse(service.configuration_was_preassigned)
        self.assertIs(service.encode_call[1]["configuration"], configuration)

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
