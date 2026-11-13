"""Native X11 window hints that Qt Widgets does not expose."""

import atexit
import os
from ctypes import CDLL, c_char_p, c_int, c_ulong, c_void_p
from functools import cache

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtWidgets import QApplication, QWidget


@cache
def _x11_connection() -> tuple[CDLL, int] | None:
    try:
        x11 = CDLL("libX11.so.6")
    except OSError:
        return None
    for name, arguments, result in (
        ("XOpenDisplay", (c_char_p,), c_void_p),
        ("XCloseDisplay", (c_void_p,), c_int),
        ("XDefaultScreen", (c_void_p,), c_int),
        ("XInternAtom", (c_void_p, c_char_p, c_int), c_ulong),
        ("XGetSelectionOwner", (c_void_p, c_ulong), c_ulong),
        ("XChangeProperty", (c_void_p, c_ulong, c_ulong, c_ulong, c_int, c_int, c_char_p, c_int), c_int),
        ("XFlush", (c_void_p,), c_int),
    ):
        function = getattr(x11, name)
        function.argtypes = arguments
        function.restype = result
    display = x11.XOpenDisplay(None)
    if not display:
        return None
    atexit.register(x11.XCloseDisplay, display)
    return x11, display


def x11_compositing_active() -> bool:
    connection = _x11_connection()
    if connection is None:
        return False
    x11, display = connection
    screen = x11.XDefaultScreen(display)
    selection = x11.XInternAtom(display, f"_NET_WM_CM_S{screen}".encode(), True)
    return bool(selection and x11.XGetSelectionOwner(display, selection))


def apply_x11_title_bar_theme(window: QWidget, dark: bool) -> None:
    if (
        QApplication.platformName() != "xcb"
        or window.windowType() not in (Qt.WindowType.Window, Qt.WindowType.Dialog)
        or window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        or window.windowHandle() is None
    ):
        return
    window_id = int(window.effectiveWinId() or 0)
    if not window_id:
        return
    connection = _x11_connection()
    if connection is None:
        return
    x11, display = connection
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    if "kde" in desktops:
        scheme = "BreezeDark.colors" if dark else "BreezeLight.colors"
        path = QStandardPaths.locate(QStandardPaths.StandardLocation.GenericDataLocation, f"color-schemes/{scheme}")
        if not path:
            return
        atom = x11.XInternAtom(display, b"_KDE_NET_WM_COLOR_SCHEME", False)
        string_type = x11.XInternAtom(display, b"STRING", False)
        value = os.fsencode(path)
    else:
        atom = x11.XInternAtom(display, b"_GTK_THEME_VARIANT", False)
        string_type = x11.XInternAtom(display, b"UTF8_STRING", False)
        value = b"dark" if dark else b"light"
    x11.XChangeProperty(display, window_id, atom, string_type, 8, 0, value, len(value))
    x11.XFlush(display)
