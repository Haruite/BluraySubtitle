"""Apply the interface font to native Cocoa window titles."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget


def prepare_window_caption(window: QWidget) -> None:
    if QApplication.platformName() != "cocoa":
        return
    flags = window.windowFlags()
    if (window.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog)
            and flags & Qt.WindowType.WindowTitleHint and not flags & Qt.WindowType.FramelessWindowHint):
        window._app_caption_enabled = True


def refresh_window_caption(window: QWidget) -> None:
    if getattr(window, "_app_caption_enabled", False) and window.windowHandle() is not None:
        from .macos_appearance import set_window_title_font

        set_window_title_font(window)
