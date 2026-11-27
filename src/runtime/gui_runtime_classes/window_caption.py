"""Prepare application window surfaces and their desktop title bars."""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from .x11_window import x11_compositing_active, x11_wm_supports


def prepare_window_surface(window: QWidget) -> None:
    app = QApplication.instance()
    platform = app.platformName()
    # Weston composites XWayland surfaces but ignores the X11 whole-window opacity hint.
    client_opacity = platform.startswith("wayland") or (
        platform == "xcb" and not x11_wm_supports(b"_NET_WM_WINDOW_OPACITY") and x11_compositing_active()
    )
    if client_opacity:
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        window.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        window.setAutoFillBackground(True)

    flags = window.windowFlags()
    if (window.windowType() not in (Qt.WindowType.Window, Qt.WindowType.Dialog)
            or not flags & Qt.WindowType.WindowTitleHint or flags & Qt.WindowType.FramelessWindowHint):
        return
    custom_scale = app.property("uiScalePercent") not in (None, 0, 100)
    if platform == "cocoa":
        window._app_caption_enabled = True
    elif sys.platform.startswith(("linux", "freebsd")) and (platform.startswith("wayland") or (
        platform == "xcb" and (client_opacity or custom_scale or sys.platform.startswith("freebsd"))
        and x11_wm_supports(b"_NET_WM_MOVERESIZE")
    )):
        from .client_window_frame import ClientWindowFrame

        # Set the flag before Qt creates the surface and negotiates native decorations.
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        window._client_window_frame = ClientWindowFrame(window)


def refresh_window_caption(window: QWidget) -> None:
    if getattr(window, "_app_caption_enabled", False) and window.windowHandle() is not None:
        from .macos_appearance import set_window_title_font

        set_window_title_font(window)
