"""Short UI animations on desktop backends that support them."""

from collections.abc import Callable

from PyQt6 import sip
from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QPropertyAnimation, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QWidget

from .desktop_appearance import desktop_appearance
from .x11_window import x11_compositing_active


def enable_combo_animation() -> None:
    if QApplication.isEffectEnabled(Qt.UIEffect.UI_General):
        QApplication.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, True)


class _WindowFade(QPropertyAnimation):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window, b"windowOpacity", window)
        self._window = window
        self.opacity = window.windowOpacity()
        self.close_action: Callable[[], object] | None = None
        self.finished.connect(self._finish)
        window.installEventFilter(self)

    def start_opening(self) -> None:
        self.cancel()
        self.opacity = self._window.windowOpacity()
        self.setDuration(200)
        self.setStartValue(self.opacity * 0.25)
        self.setEndValue(self.opacity)
        self.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.start()

    def start_closing(self, close: Callable[[], object]) -> None:
        current = self._window.windowOpacity()
        if self.state() == QAbstractAnimation.State.Stopped:
            self.opacity = current
        self.stop()
        self.close_action = close
        self.setDuration(160)
        self.setStartValue(current)
        self.setEndValue(0.0)
        self.setEasingCurve(QEasingCurve.Type.InQuad)
        self.start()

    def cancel(self) -> None:
        self.close_action = None
        self.stop()
        self._window.setWindowOpacity(self.opacity)

    def _finish(self) -> None:
        close, self.close_action = self.close_action, None
        if close is not None:
            window = self._window
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


def supports_window_opacity() -> bool:
    platform = QApplication.platformName()
    return platform == "windows" or (platform == "xcb" and x11_compositing_active())


def _supports_window_fade(window: QWidget) -> bool:
    app = QApplication.instance()
    if (
        app.isSavingSession()
        or window.windowType() not in (Qt.WindowType.Window, Qt.WindowType.Dialog)
        or window.isMinimized()
        or window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        or not supports_window_opacity()
    ):
        return False
    hints = app.styleHints()
    accessibility = hints.accessibility() if hasattr(hints, "accessibility") else None
    if accessibility is not None and hasattr(accessibility, "motionPreference"):
        if accessibility.motionPreference() == Qt.MotionPreference.ReducedMotion:
            return False
    elif app.platformName() == "windows" and not app.isEffectEnabled(Qt.UIEffect.UI_General):
        return False
    # Qt's generic Unix UI-effects flag can be off on a composited desktop.
    appearance = desktop_appearance()
    return appearance is None or not appearance.reduced_motion()


def animate_window_open(window: QWidget) -> None:
    if _supports_window_fade(window):
        (_window_fade(window) or _WindowFade(window)).start_opening()


def animate_window_close(window: QWidget, close: Callable[[], object]) -> bool:
    fade = _window_fade(window)
    if fade is not None and fade.close_action is not None:
        return True
    # A replayed close reaches this point at the end of the fade, at zero opacity.
    if not window.isVisible() or window.windowOpacity() <= 0.0 or not _supports_window_fade(window):
        return False
    (fade or _WindowFade(window)).start_closing(close)
    return True


def window_is_fading_out(window: QWidget) -> bool:
    fade = _window_fade(window)
    return fade is not None and fade.close_action is not None


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


class DialogFade:
    def done(self, result: int) -> None:
        complete = super().done
        if not animate_window_close(self, lambda: complete(result)):
            complete(result)


class AnimatedDialog(DialogFade, QDialog):
    """Finish the dialog after the fade while preserving its result."""


class AnimatedMessageBox(DialogFade, QMessageBox):
    def closeEvent(self, event) -> None:
        # QMessageBox computes the result of a title-bar close in its close handler.
        if animate_window_close(self, self.close):
            event.ignore()
        else:
            super().closeEvent(event)
