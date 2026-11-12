"""Route a second launch from the same directory to the existing window."""

import os
import sys
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep

from PyQt6.QtCore import QLockFile, QObject, QStandardPaths, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from src.core.app_config import application_location_id
from src.core.i18n import translate_text

if sys.platform == "win32":
    import ctypes

    _allow_foreground = ctypes.WinDLL("user32").AllowSetForegroundWindow
    _allow_foreground.argtypes = (ctypes.c_uint32,)
    _allow_foreground.restype = ctypes.c_int


class InstanceActivation(QObject):
    activation_requested = pyqtSignal()

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        runtime = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
        if not runtime:
            runtime = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
        directory = Path(runtime).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        session = sha256(os.fsencode(os.path.normcase(str(directory)))).hexdigest()[:8]
        self._name = f"bs-{application_location_id()}-{session}"
        self._lock = QLockFile(str(directory / f"{self._name}.lock"))
        self._lock.setStaleLockTime(0)
        self._server = QLocalServer(self)
        # The name includes the user's runtime directory. Windows uses its default pipe ACL.
        if sys.platform != "win32":
            self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._activate)

    def claim(self) -> bool:
        deadline = monotonic() + 3
        while True:
            if self._lock.tryLock(0):
                # Only the lock owner can remove a socket left by an earlier process.
                QLocalServer.removeServer(self._name)
                if self._server.listen(self._name):
                    return True
                self._lock.unlock()
                raise OSError(self._server.errorString())
            if self._lock.error() != QLockFile.LockError.LockFailedError:
                raise OSError(self._lock.error().name)
            if sys.platform == "win32":
                locked, pid, _, _ = self._lock.getLockInfo()
                if locked and pid > 0:
                    _allow_foreground(pid)
            socket = QLocalSocket()
            socket.connectToServer(self._name)
            if socket.state() == QLocalSocket.LocalSocketState.ConnectedState or socket.waitForConnected(200):
                socket.disconnectFromServer()
                return False
            if monotonic() >= deadline:
                raise TimeoutError(translate_text("Could not activate the running program."))
            sleep(0.05)

    def release(self) -> None:
        self._server.close()
        self._lock.unlock()

    def _activate(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.disconnectFromServer()
            socket.deleteLater()
            self.activation_requested.emit()
