"""Shared lightweight fakes for GUI worker launch tests."""

from __future__ import annotations


class Signal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class FakeThread:
    def __init__(self, _parent) -> None:
        self.started = Signal()
        self.was_started = False

    def start(self) -> None:
        self.was_started = True


class RequestWorkerCapture:
    last_request = None
    signal_names = ('progress', 'label', 'finished', 'canceled', 'failed')

    def __init__(self, request, _cancel_event) -> None:
        type(self).last_request = request
        for signal_name in type(self).signal_names:
            setattr(self, signal_name, Signal())

    def moveToThread(self, thread) -> None:
        self.thread = thread

    def run(self) -> None:
        pass
