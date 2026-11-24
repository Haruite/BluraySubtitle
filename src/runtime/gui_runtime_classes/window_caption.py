"""Prepare the title bar used by application windows on each desktop."""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from .x11_window import x11_supports_system_move_resize


def prepare_window_caption(window: QWidget) -> None:
    flags = window.windowFlags()
    if (window.windowType() not in (Qt.WindowType.Window, Qt.WindowType.Dialog)
            or not flags & Qt.WindowType.WindowTitleHint or flags & Qt.WindowType.FramelessWindowHint):
        return
    platform = QApplication.platformName()
    if platform == "cocoa":
        window._app_caption_enabled = True
    elif ((platform.startswith("wayland") and sys.platform.startswith(("linux", "freebsd")))
          or (platform == "xcb" and sys.platform.startswith("freebsd") and x11_supports_system_move_resize())):
        from .client_window_frame import ClientWindowFrame

        # Set the flag before Qt creates the surface and negotiates native decorations.
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        window._client_window_frame = ClientWindowFrame(window)


def refresh_window_caption(window: QWidget) -> None:
    if getattr(window, "_app_caption_enabled", False) and window.windowHandle() is not None:
        from .macos_appearance import set_window_title_font

        set_window_title_font(window)
