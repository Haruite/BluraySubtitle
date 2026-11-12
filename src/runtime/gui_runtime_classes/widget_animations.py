"""Short UI animations on desktop backends that support them."""

from collections.abc import Callable

from PyQt6 import sip
from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QPropertyAnimation, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget


def enable_combo_animation() -> None:
    if QApplication.isEffectEnabled(Qt.UIEffect.UI_General):
        QApplication.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, True)


class _WindowFade(QPropertyAnimation):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window, b"windowOpacity", window)
        self._window = window
        self.opacity = window.windowOpacity()
        self.close_action: Callable[[], object] | None = None
        self._was_enabled = window.isEnabled()
        self.finished.connect(self._finish)
        window.installEventFilter(self)

    def start_opening(self) -> None:
        self.cancel()
        self.opacity = self._window.windowOpacity()
        self.setDuration(160)
        self.setStartValue(self.opacity * 0.30)
        self.setEndValue(self.opacity)
        self.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.start()

    def start_closing(self, close: Callable[[], object]) -> None:
        current = self._window.windowOpacity()
        if self.state() == QAbstractAnimation.State.Stopped:
            self.opacity = current
        self.stop()
        self.close_action = close
        self._was_enabled = self._window.isEnabled()
        self._window.setEnabled(False)
        self.setDuration(120)
        self.setStartValue(current)
        self.setEndValue(0.0)
        self.setEasingCurve(QEasingCurve.Type.InQuad)
        self.start()

    def cancel(self) -> None:
        close, self.close_action = self.close_action, None
        self.stop()
        if close is not None:
            self._window.setEnabled(self._was_enabled)
        self._window.setWindowOpacity(self.opacity)

    def _finish(self) -> None:
        close, self.close_action = self.close_action, None
        if close is not None:
            window = self._window
            window.setEnabled(self._was_enabled)
            close()
            if not sip.isdeleted(window) and self.state() == QAbstractAnimation.State.Stopped:
                window.setWindowOpacity(self.opacity)

    def eventFilter(self, watched, event) -> bool:
        if (event.type() == QEvent.Type.Hide and self.close_action is None
                and self.state() == QAbstractAnimation.State.Running):
            self.cancel()
        return False


def _window_fade(window: QWidget) -> _WindowFade | None:
    return window.findChild(_WindowFade, options=Qt.FindChildOption.FindDirectChildrenOnly)


def _supports_window_fade(window: QWidget) -> bool:
    return (
        QApplication.platformName() in ("windows", "xcb")
        and QApplication.isEffectEnabled(Qt.UIEffect.UI_General)
        and not QApplication.instance().isSavingSession()
        and window.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog)
        and not window.isMinimized()
        and not window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    )


def animate_window_open(window: QWidget) -> None:
    if _supports_window_fade(window):
        (_window_fade(window) or _WindowFade(window)).start_opening()


def animate_window_close(window: QWidget, close: Callable[[], object]) -> bool:
    if not _supports_window_fade(window) or not window.isVisible():
        return False
    fade = _window_fade(window)
    if fade is not None and fade.close_action is not None:
        return True
    # A replayed close reaches this point at the end of the fade, at zero opacity.
    if window.windowOpacity() <= 0.0:
        return False
    (fade or _WindowFade(window)).start_closing(close)
    return True


def cancel_window_close(window: QWidget) -> None:
    fade = _window_fade(window)
    if fade is not None and fade.close_action is not None:
        fade.cancel()


def set_window_opacity(window: QWidget, opacity: float) -> None:
    fade = _window_fade(window)
    if fade is not None:
        fade.opacity = opacity
        if fade.close_action is not None:
            return
        fade.stop()
    window.setWindowOpacity(opacity)


def window_opacity(window: QWidget) -> float:
    fade = _window_fade(window)
    if fade is not None and fade.state() == QAbstractAnimation.State.Running:
        return fade.opacity
    return window.windowOpacity()


class _DialogFade:
    def done(self, result: int) -> None:
        complete = super().done
        if not animate_window_close(self, lambda: complete(result)):
            complete(result)


class AnimatedDialog(_DialogFade, QDialog):
    """Finish the dialog after the fade while preserving its result."""


class AnimatedMessageBox(_DialogFade, QMessageBox):
    def closeEvent(self, event) -> None:
        # QMessageBox computes the result of a title-bar close in its close handler.
        if animate_window_close(self, self.close):
            event.ignore()
        else:
            super().closeEvent(event)
