"""A delayed scan dialog whose lifetime is owned by the scan."""

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .widget_animations import AnimatedDialog


class ScanProgressDialog(AnimatedDialog):
    cancel_requested = pyqtSignal()

    def __init__(self, parent: QWidget, text: str, cancel_text: str = "", *, show_delay_ms: int | None = 300) -> None:
        super().__init__(parent)
        self.setWindowTitle(text)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, bool(cancel_text))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        layout = QVBoxLayout(self)
        self._label = QLabel(text, self)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        self.bar = QProgressBar(self)
        self.bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar.setRange(0, 0)
        layout.addWidget(self.bar)
        self._cancel_button = QPushButton(cancel_text, self)
        self._cancel_button.setVisible(bool(cancel_text))
        self._cancel_button.clicked.connect(self.reject)
        layout.addWidget(self._cancel_button, alignment=Qt.AlignmentFlag.AlignRight)

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self.show)
        self._finishing = False
        if show_delay_ms is not None:
            self._show_timer.start(show_delay_ms)

    def setLabelText(self, text: str) -> None:
        self._label.setText(text)

    def set_cancel_enabled(self, enabled: bool) -> None:
        self._cancel_button.setEnabled(enabled)

    def reject(self) -> None:
        if self._finishing:
            super().reject()
        elif self._cancel_button.isVisible() and self._cancel_button.isEnabled():
            self.set_cancel_enabled(False)
            self.cancel_requested.emit()

    def finish(self) -> None:
        if self._finishing:
            return
        self._finishing = True
        self._show_timer.stop()
        self.set_cancel_enabled(False)
        self.accept()
