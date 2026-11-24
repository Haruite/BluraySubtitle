"""Native X11 window hints that Qt Widgets does not expose."""

import atexit
import os
from ctypes import CDLL, POINTER, byref, c_char_p, c_int, c_long, c_ulong, c_void_p, cast
from ctypes.util import find_library
from functools import cache

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtWidgets import QApplication, QWidget


@cache
def _x11_connection() -> tuple[CDLL, int] | None:
    try:
        x11 = CDLL(find_library("X11") or "libX11.so.6")
    except OSError:
        return None
    for name, arguments, result in (
        ("XOpenDisplay", (c_char_p,), c_void_p),
        ("XCloseDisplay", (c_void_p,), c_int),
        ("XDefaultScreen", (c_void_p,), c_int),
        ("XDefaultRootWindow", (c_void_p,), c_ulong),
        ("XSync", (c_void_p, c_int), c_int),
        ("XInternAtom", (c_void_p, c_char_p, c_int), c_ulong),
        ("XGetSelectionOwner", (c_void_p, c_ulong), c_ulong),
        ("XGetWindowProperty", (c_void_p, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong,
                                POINTER(c_ulong), POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong),
                                POINTER(c_void_p)), c_int),
        ("XFree", (c_void_p,), c_int),
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


@cache
def x11_supports_system_move_resize() -> bool:
    connection = _x11_connection()
    if connection is None:
        return False
    x11, display = connection
    supported = x11.XInternAtom(display, b"_NET_SUPPORTED", True)
    moveresize = x11.XInternAtom(display, b"_NET_WM_MOVERESIZE", True)
    if not supported or not moveresize:
        return False
    atom = x11.XInternAtom(display, b"ATOM", True)
    actual_type, size, length, remaining, data = c_ulong(), c_int(), c_ulong(), c_ulong(), c_void_p()
    result = x11.XGetWindowProperty(display, x11.XDefaultRootWindow(display), supported, 0, 1024, False, atom,
                                    byref(actual_type), byref(size), byref(length), byref(remaining), byref(data))
    try:
        return (result == 0 and actual_type.value == atom and size.value == 32 and bool(data)
                and moveresize in cast(data, POINTER(c_ulong))[:length.value])
    finally:
        if data:
            x11.XFree(data)


def set_x11_window_identity(window: QWidget, desktop_id: str, desktop_file: str = "") -> None:
    if QApplication.platformName() != "xcb" or window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen):
        return
    connection = _x11_connection()
    if connection is None:
        return

    # Set the per-window identity before Qt maps it so the task manager uses the correct launcher and icon.
    window_id = int(window.winId())
    x11, display = connection
    for name, type_name, value in (
        (b"WM_CLASS", b"STRING", (desktop_id + "\0" + desktop_id + "\0").encode()),
        (b"_GTK_APPLICATION_ID", b"UTF8_STRING", desktop_id.encode()),
        (b"_KDE_NET_WM_DESKTOP_FILE", b"UTF8_STRING", (desktop_file or desktop_id).encode()),
    ):
        atom = x11.XInternAtom(display, name, False)
        property_type = x11.XInternAtom(display, type_name, False)
        x11.XChangeProperty(display, window_id, atom, property_type, 8, 0, value, len(value))
    x11.XSync(display, False)


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
