"""A non-modal notice for a newer server package discovered on startup."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from src.core.i18n import translate_text
from src.core.version import current_commit, parse_commit_record
from src.runtime.update_check import SERVER_PACKAGE_METADATA_URL, request_update_info, update_network_manager
from src.runtime.windows_update import WindowsUpdatePackage, server_windows_package, windows_update_executable
from .widget_animations import AnimatedMessageBox


class StartupUpdateNotice(QWidget):
    def __init__(self, install_update: Callable[[WindowsUpdatePackage], None], parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("startupUpdateNotice")
        self._install_update = install_update
        self._network_manager = update_network_manager(self)
        self._check_enabled = False
        self._reply: QNetworkReply | None = None
        self._package: WindowsUpdatePackage | None = None
        label = QLabel(translate_text("A newer server package is available."), self)
        label.setWordWrap(True)
        self._update_button = QPushButton(translate_text("Update now"), self)
        self._update_button.clicked.connect(self._update)
        self._update_button.hide()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.addWidget(label, 1)
        layout.addWidget(self._update_button)
        self.hide()

    def set_check_enabled(self, enabled: bool) -> None:
        if enabled == self._check_enabled:
            return
        self._check_enabled = enabled
        if enabled:
            QTimer.singleShot(0, self._begin_check)
        else:
            self.hide()
            self._package = None
            self._update_button.hide()
            if self._reply is not None:
                reply, self._reply = self._reply, None
                reply.abort()
                reply.deleteLater()

    def _begin_check(self) -> None:
        if self._check_enabled and self._reply is None:
            reply = request_update_info(self._network_manager, SERVER_PACKAGE_METADATA_URL, b"text/plain")
            self._reply = reply
            reply.finished.connect(lambda: self._finish_check(reply))

    def _finish_check(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        self._reply = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return
            record = bytes(reply.readAll()).decode("utf-8")
            server_commit = parse_commit_record(record)
        except ValueError:
            return
        finally:
            reply.deleteLater()
        installed = current_commit()
        if installed is None or installed.commit_hash == server_commit.commit_hash:
            return
        if server_commit.committed_at > installed.committed_at:
            self._package = server_windows_package(record) if windows_update_executable() is not None else None
            self._update_button.setVisible(self._package is not None)
            self.show()

    def _update(self) -> None:
        if self._package is None:
            return
        self._update_button.setEnabled(False)
        try:
            self._install_update(self._package)
        except (OSError, RuntimeError, ValueError) as error:
            self._update_button.setEnabled(True)
            AnimatedMessageBox.warning(
                self,
                translate_text("Check for updates"),
                translate_text("Could not start the update. {error}").format(error=error),
            )
