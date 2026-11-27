"""Short UI animations on desktop backends that support them."""

from collections.abc import Callable

from PyQt6 import sip
from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, Qt, QVariantAnimation
from PyQt6.QtGui import QPainter, QWindow
from PyQt6.QtWidgets import QApplication, QDialog, QGraphicsOpacityEffect, QInputDialog, QMessageBox, QWidget

from .desktop_appearance import desktop_appearance
from .x11_window import x11_compositing_active
from .window_caption import prepare_window_surface


def enable_combo_animation() -> None:
    if QApplication.isEffectEnabled(Qt.UIEffect.UI_General):
        QApplication.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, True)


class _WindowOpacityEffect(QGraphicsOpacityEffect):
    def draw(self, painter: QPainter) -> None:
        # Qt can retain opaque child regions in the backing store between repaints.
        # Clear the damaged pixels before compositing the complete window over them.
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.boundingRect(), Qt.GlobalColor.transparent)
        painter.restore()
        super().draw(painter)


class _WindowFade(QVariantAnimation):
    _opening_fraction = 0.25

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._effect: QGraphicsOpacityEffect | None = None
        if _has_translucent_client(window):
            self._effect = _WindowOpacityEffect(window)
            self._effect.setOpacity(1.0)
            window.setGraphicsEffect(self._effect)
        self.opacity = self.current_opacity()
        self.close_action: Callable[[], object] | None = None
        self._waiting_for_expose: QWindow | None = None
        self.finished.connect(self._finish)
        window.installEventFilter(self)

    def prepare_opening(self, handle: QWindow) -> None:
        if self.is_active():
            self.cancel()
        else:
            self.opacity = self.current_opacity()
        # Set the first frame before mapping, then wait for the window system to expose it.
        self._waiting_for_expose = handle
        handle.installEventFilter(self)
        self._set_opacity(self.opacity * self._opening_fraction)

    def _start_opening(self) -> None:
        self._stop_waiting_for_expose()
        self.setDuration(200)
        self.setStartValue(self.opacity * self._opening_fraction)
        self.setEndValue(self.opacity)
        self.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.start()

    def _stop_waiting_for_expose(self) -> None:
        handle, self._waiting_for_expose = self._waiting_for_expose, None
        if handle is not None and not sip.isdeleted(handle):
            handle.removeEventFilter(self)

    def is_active(self) -> bool:
        return self._waiting_for_expose is not None or self.state() == QAbstractAnimation.State.Running

    def current_opacity(self) -> float:
        if self._effect is not None:
            return self._effect.opacity()
        return self._window.windowOpacity()

    def _set_opacity(self, opacity: float) -> None:
        if self._effect is None:
            self._window.setWindowOpacity(opacity)
        else:
            self._effect.setOpacity(opacity)

    def updateCurrentValue(self, value: float) -> None:
        if self.state() == QAbstractAnimation.State.Running:
            self._set_opacity(value)

    def start_closing(self, close: Callable[[], object]) -> None:
        current = self.current_opacity()
        if not self.is_active():
            self.opacity = current
        self._stop_waiting_for_expose()
        self.stop()
        self.close_action = close
        self.setDuration(160)
        self.setStartValue(current)
        self.setEndValue(0.0)
        self.setEasingCurve(QEasingCurve.Type.InQuad)
        self.start()

    def cancel(self) -> None:
        self.close_action = None
        self._stop_waiting_for_expose()
        self.stop()
        self._set_opacity(self.opacity)

    def set_resting_opacity(self, opacity: float) -> None:
        if self.opacity == opacity and self.is_active():
            return
        self.opacity = opacity
        if self.close_action is not None:
            return
        if self._waiting_for_expose is not None:
            self._set_opacity(opacity * self._opening_fraction)
        else:
            self.stop()
            self._set_opacity(opacity)

    def _finish(self) -> None:
        close, self.close_action = self.close_action, None
        if close is not None:
            window = self._window
            close()
            if not sip.isdeleted(window) and not self.is_active():
                self._set_opacity(self.opacity)

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.Expose and watched is self._waiting_for_expose
            and watched.isExposed()
        ):
            self._start_opening()
        elif (
            event.type() == QEvent.Type.Hide and watched is self._window
            and self.close_action is None and self.is_active()
        ):
            self.cancel()
        return False


def _window_fade(window: QWidget) -> _WindowFade | None:
    return window.findChild(_WindowFade, options=Qt.FindChildOption.FindDirectChildrenOnly)


def supports_window_opacity() -> bool:
    platform = QApplication.platformName()
    return platform in ("windows", "cocoa") or platform.startswith("wayland") or (
        platform == "xcb" and x11_compositing_active()
    )


def _has_translucent_client(window: QWidget) -> bool:
    if not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
        return False
    platform = QApplication.platformName()
    handle = window.windowHandle()
    if platform.startswith("wayland"):
        # Qt 6.6's raster popups report an unspecified format even with an ARGB buffer.
        return handle is None or handle.requestedFormat().hasAlpha()
    return platform == "xcb" and (handle is None or handle.format().hasAlpha())


def _supports_window_fade(window: QWidget) -> bool:
    app = QApplication.instance()
    if (
        app.isSavingSession()
        or window.windowType() not in (Qt.WindowType.Window, Qt.WindowType.Dialog)
        or window.isMinimized()
        or window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    ):
        return False
    platform = app.platformName()
    opacity_supported = (
        _has_translucent_client(window) if platform.startswith("wayland") else supports_window_opacity()
    )
    if not opacity_supported:
        return False
    hints = app.styleHints()
    accessibility = hints.accessibility() if hasattr(hints, "accessibility") else None
    if accessibility is not None and hasattr(accessibility, "motionPreference"):
        if accessibility.motionPreference() == Qt.MotionPreference.ReducedMotion:
            return False
    elif platform == "windows" and not app.isEffectEnabled(Qt.UIEffect.UI_General):
        return False
    # Qt's generic Unix UI-effects flag can be off on a composited desktop.
    appearance = desktop_appearance()
    return appearance is None or not appearance.reduced_motion()


def animate_window_open(window: QWidget) -> None:
    handle = window.windowHandle()
    if handle is not None and _supports_window_fade(window):
        (_window_fade(window) or _WindowFade(window)).prepare_opening(handle)


def animate_window_close(window: QWidget, close: Callable[[], object]) -> bool:
    fade = _window_fade(window)
    if fade is not None and fade.close_action is not None:
        return True
    # A replayed close reaches this point at the end of the fade, at zero opacity.
    handle = window.windowHandle()
    if (
        not window.isVisible() or handle is None or not handle.isExposed()
        or not _supports_window_fade(window)
    ):
        return False
    fade = fade or _WindowFade(window)
    if fade.current_opacity() <= 0.0:
        return False
    fade.start_closing(close)
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
    if fade is None and opacity < 1.0 and _has_translucent_client(window):
        fade = _WindowFade(window)
    if fade is not None:
        fade.set_resting_opacity(opacity)
    elif opacity != window.windowOpacity():
        window.setWindowOpacity(opacity)


def window_opacity(window: QWidget) -> float:
    fade = _window_fade(window)
    return fade.opacity if fade is not None else window.windowOpacity()


class DialogFade:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        prepare_window_surface(self)

    def done(self, result: int) -> None:
        complete = super().done
        if not animate_window_close(self, lambda: complete(result)):
            complete(result)


class AnimatedDialog(DialogFade, QDialog):
    """Finish the dialog after the fade while preserving its result."""


class AnimatedMessageBox(DialogFade, QMessageBox):
    @classmethod
    def information(cls, parent: QWidget, title: str, text: str) -> QMessageBox.StandardButton:
        return cls._show_message(parent, cls.Icon.Information, title, text)

    @classmethod
    def warning(cls, parent: QWidget, title: str, text: str) -> QMessageBox.StandardButton:
        return cls._show_message(parent, cls.Icon.Warning, title, text)

    @classmethod
    def _show_message(cls, parent: QWidget, icon: QMessageBox.Icon, title: str,
                      text: str) -> QMessageBox.StandardButton:
        dialog = cls(icon, title, text, cls.StandardButton.Ok, parent)
        dialog.setDefaultButton(cls.StandardButton.Ok)
        dialog.exec()
        return dialog.standardButton(dialog.clickedButton())

    def closeEvent(self, event) -> None:
        # QMessageBox computes the result of a title-bar close in its close handler.
        if animate_window_close(self, self.close):
            event.ignore()
        else:
            super().closeEvent(event)


class AnimatedInputDialog(DialogFade, QInputDialog):
    @classmethod
    def getItem(cls, parent: QWidget, title: str, label: str, items: list[str]) -> tuple[str, bool]:
        dialog = cls(parent)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems(items)
        dialog.setComboBoxEditable(False)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            return dialog.textValue(), True
        return (items[0] if items else ''), False
