"""Capture application and child-process output for the session log."""

import codecs
from collections import deque
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from io import TextIOWrapper
from itertools import islice
import os
from pathlib import Path
import sys
import tempfile
from threading import Lock, Thread

from src.core.app_config import UiPreferences

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _set_std_handle = _kernel32.SetStdHandle
    _set_std_handle.argtypes = (wintypes.DWORD, wintypes.HANDLE)
    _set_std_handle.restype = wintypes.BOOL
    _attach_console = _kernel32.AttachConsole
    _attach_console.argtypes = (wintypes.DWORD,)
    _attach_console.restype = wintypes.BOOL
    _get_console_mode = _kernel32.GetConsoleMode
    _get_console_mode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _get_console_mode.restype = wintypes.BOOL
    _standard_handles = (-10, -11, -12)


def _terminal_accepts_ansi(descriptor: int) -> bool:
    if not os.isatty(descriptor):
        return False
    if sys.platform != "win32":
        return os.environ.get("TERM") != "dumb"
    mode = wintypes.DWORD()
    return bool(
        _get_console_mode(msvcrt.get_osfhandle(descriptor), ctypes.byref(mode))
        and mode.value & 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    )


def _replace_standard_descriptor(source: int, target: int) -> None:
    os.dup2(source, target)
    if sys.platform == "win32":
        # Native child processes inherit Win32 handles independently of the CRT descriptors.
        if not _set_std_handle(_standard_handles[target], msvcrt.get_osfhandle(target)):
            raise ctypes.WinError(ctypes.get_last_error())


def prepare_windows_stdio(*, foreground: bool) -> None:
    """Supply standard streams for a windowed executable and its workers."""
    if sys.platform != "win32":
        return
    # Attach only when requested. A windowed executable never allocates a console.
    use_console = foreground and (sys.stdout is None or sys.stderr is None)
    if use_console:
        _attach_console(-1)
    for descriptor, name in enumerate(("stdin", "stdout", "stderr")):
        if getattr(sys, name) is not None:
            continue
        reading = descriptor == 0
        flags = os.O_RDONLY if reading else os.O_WRONLY
        try:
            os.fstat(descriptor)
        except OSError:
            device = ("CONIN$" if reading else "CONOUT$") if use_console else os.devnull
            try:
                replacement = os.open(device, flags)
            except OSError:
                replacement = os.open(os.devnull, flags)
            try:
                _replace_standard_descriptor(replacement, descriptor)
            finally:
                if replacement != descriptor:
                    os.close(replacement)
        stream = open(descriptor, "r" if reading else "w", encoding="utf-8", errors="backslashreplace",
                      buffering=-1 if reading else 1, closefd=False)
        setattr(sys, name, stream)
        setattr(sys, f"__{name}__", stream)


@dataclass(frozen=True, slots=True)
class LogFragment:
    text: str
    timestamp: str
    starts_line: bool


class ApplicationLog:
    """Retain recent output and optionally write it to a per-session file."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._file_lock = Lock()
        self._history: deque[LogFragment] = deque()
        self._history_size = 0
        self._history_lines = 0
        self._line_limit = UiPreferences.log_line_limit
        self._starts_line = True
        self._line_time = ""
        self._position = 0
        self._file_position = 0
        self._file = None
        self._file_path: Path | None = None
        self._file_error: OSError | None = None

    @contextmanager
    def capture(self, *, foreground: bool):
        # A shared pipe preserves the ordering of stdout and stderr when detached.
        channels = ((1,), (2,)) if foreground else ((1, 2),)
        originals: dict[int, int] = {}
        readers: list[Thread] = []
        original_streams = (sys.stdout, sys.stderr)
        output_streams = []
        try:
            for descriptor, stream in enumerate(original_streams, start=1):
                if stream is not None:
                    stream.flush()
                originals[descriptor] = os.dup(descriptor)
            for targets in channels:
                read_fd, write_fd = os.pipe()
                try:
                    for target in targets:
                        _replace_standard_descriptor(write_fd, target)
                    mirror = open(os.dup(originals[targets[0]]), "wb") if foreground else None
                    reader = Thread(target=self._drain, args=(read_fd, mirror), daemon=True)
                    reader.start()
                    readers.append(reader)
                except BaseException:
                    os.close(read_fd)
                    raise
                finally:
                    os.close(write_fd)
            for descriptor in originals:
                stream = TextIOWrapper(
                    open(descriptor, "wb", buffering=0, closefd=False),
                    encoding="utf-8", errors="backslashreplace", write_through=True,
                )
                stream.accepts_ansi_color = not foreground or _terminal_accepts_ansi(originals[descriptor])
                output_streams.append(stream)
            sys.stdout = sys.__stdout__ = output_streams[0]
            sys.stderr = sys.__stderr__ = output_streams[1]
            yield
        finally:
            for stream in output_streams:
                with suppress(OSError):
                    stream.close()
            for descriptor, original in originals.items():
                try:
                    _replace_standard_descriptor(original, descriptor)
                finally:
                    os.close(original)
            if output_streams:
                # Reopen the streams so Windows console IO uses the restored native handles.
                for descriptor, original in enumerate(original_streams, start=1):
                    stream = open(
                        descriptor, "w", buffering=1, encoding=getattr(original, "encoding", None),
                        errors=getattr(original, "errors", None), closefd=False,
                    )
                    if descriptor == 1:
                        sys.stdout = sys.__stdout__ = stream
                    else:
                        sys.stderr = sys.__stderr__ = stream
            for reader in readers:
                # A separately launched tool may still hold a copy of a pipe writer.
                reader.join(timeout=0.5)
            self.set_log_directory(None)

    def _drain(self, descriptor: int, mirror) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        windows_console = mirror is not None and sys.platform == "win32" and mirror.isatty()
        try:
            with os.fdopen(descriptor, "rb", buffering=0) as source:
                while chunk := source.read(8192):
                    text = decoder.decode(chunk)
                    self._append(text)
                    if mirror is not None:
                        try:
                            # A console write needs complete UTF-8 characters across pipe reads.
                            mirror.write(text.encode("utf-8") if windows_console else chunk)
                            mirror.flush()
                        except OSError:
                            with suppress(OSError):
                                mirror.close()
                            mirror = None
                self._append(decoder.decode(b"", final=True))
        finally:
            if mirror is not None:
                with suppress(OSError):
                    mirror.close()

    def _append(self, text: str) -> None:
        if not text:
            return
        timestamp = datetime.now().astimezone().isoformat(sep=" ", timespec="milliseconds")
        lines = text.split("\n")
        parts = [line + "\n" for line in lines[:-1]]
        if lines[-1]:
            parts.append(lines[-1])
        with self._file_lock:
            with self._lock:
                fragments = []
                for part in parts:
                    if self._starts_line:
                        self._line_time = timestamp
                        self._history_lines += 1
                    fragments.append(LogFragment(part, self._line_time, self._starts_line))
                    self._starts_line = part.endswith("\n")
                self._history.extend(fragments)
                self._history_size += len(text)
                self._position += len(fragments)
                self._trim_history()
            self._write_file(fragments)

    def set_line_limit(self, limit: int) -> None:
        with self._lock:
            self._line_limit = limit
            self._trim_history()

    def _trim_history(self) -> None:
        # The character and fragment bounds also cover progress output without a newline.
        while (
            self._history_lines > self._line_limit
            or self._history_size > 16_000_000
            or len(self._history) > self._line_limit * 2 + 8192
        ):
            fragment = self._history.popleft()
            self._history_size -= len(fragment.text)
            self._history_lines -= fragment.text.endswith("\n")

    def read_since(self, position: int) -> tuple[int, bool, list[LogFragment]]:
        with self._lock:
            first = self._position - len(self._history)
            start = max(first, position)
            chunks = []
            size = 0
            for chunk in islice(self._history, start - first, None):
                chunks.append(chunk)
                size += len(chunk.text)
                if size >= 65536:
                    break
            return start + len(chunks), position < first, chunks

    def set_log_directory(self, directory: Path | None) -> None:
        with self._file_lock:
            if directory is None:
                self._close_file()
                return
            if self._file is not None:
                return
            try:
                directory.mkdir(parents=True, exist_ok=True)
                if self._file_path is None:
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    self._file = tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", newline="", dir=directory,
                        prefix=f"BluraySubtitle-{stamp}-", suffix=".log", delete=False,
                    )
                    self._file_path = Path(self._file.name)
                else:
                    self._file = self._file_path.open("a", encoding="utf-8", newline="")
                with self._lock:
                    first = self._position - len(self._history)
                    buffered = list(islice(self._history, max(0, self._file_position - first), None))
                self._write_file(buffered)
            except OSError as error:
                self._record_file_error(error)
                self._close_file()

    def _write_file(self, fragments: list[LogFragment]) -> None:
        if self._file is not None:
            try:
                self._file.write("".join(
                    f"[{part.timestamp}] {part.text}" if part.starts_line else part.text for part in fragments
                ))
                self._file.flush()
            except OSError as error:
                self._record_file_error(error)
                self._close_file()
                self._file_path = None
            else:
                self._file_position = self._position

    def _close_file(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError as error:
                self._record_file_error(error)
            finally:
                self._file = None

    def _record_file_error(self, error: OSError) -> None:
        with self._lock:
            self._file_error = self._file_error or error

    def take_file_error(self) -> OSError | None:
        with self._lock:
            error = self._file_error
            self._file_error = None
            return error
