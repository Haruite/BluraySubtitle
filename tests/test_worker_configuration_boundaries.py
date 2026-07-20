"""Tests for explicit GUI-worker-service configuration transfer."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from src.runtime.gui_runtime_classes import encode_worker as encode_worker_module
from src.runtime.gui_runtime_classes import remux_worker as remux_worker_module


class _FakeService:
    instances: list["_FakeService"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.init_args = args
        self.init_kwargs = kwargs
        self.remux_call = None
        self.encode_call = None
        type(self).instances.append(self)

    def episodes_remux(self, *args, **kwargs) -> None:
        self.configuration_was_preassigned = hasattr(self, "configuration")
        self.remux_call = (args, kwargs)

    def episodes_encode(self, *args, **kwargs) -> None:
        self.configuration_was_preassigned = hasattr(self, "configuration")
        self.encode_call = (args, kwargs)


class WorkerConfigurationBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeService.instances.clear()

    def test_remux_worker_passes_only_its_explicit_configuration(self) -> None:
        configuration = {0: {"selected_mpls": "00001", "start_at_chapter": 1}}
        worker = remux_worker_module.RemuxWorker(
            "disc",
            [""],
            True,
            "output",
            configuration,
            [],
            threading.Event(),
            [],
            ["Episode.mkv"],
            ["eng"],
        )

        with patch.object(remux_worker_module, "BluraySubtitle", _FakeService):
            worker.run()

        service = _FakeService.instances[0]
        self.assertFalse(service.configuration_was_preassigned)
        self.assertIs(service.remux_call[1]["configuration"], configuration)

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


if __name__ == "__main__":
    unittest.main()
