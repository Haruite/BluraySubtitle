"""Cocoa window appearance and desktop preferences for both supported Qt versions."""

from ctypes import CDLL, CFUNCTYPE, Structure, c_bool, c_char_p, c_double, c_long, c_void_p
from functools import cache

from PyQt6.QtCore import QEvent, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontInfo
from PyQt6.QtWidgets import QApplication, QWidget


_appkit = CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
_objc = CDLL("/usr/lib/libobjc.A.dylib")
_objc.objc_getClass.argtypes = [c_char_p]
_objc.objc_getClass.restype = c_void_p
_objc.sel_registerName.argtypes = [c_char_p]
_objc.sel_registerName.restype = c_void_p
_selector = cache(_objc.sel_registerName)
_object = CFUNCTYPE(c_void_p, c_void_p, c_void_p)(("objc_msgSend", _objc))
_object_with_arg = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_void_p)(("objc_msgSend", _objc))
_set_object = CFUNCTYPE(None, c_void_p, c_void_p, c_void_p)(("objc_msgSend", _objc))
_component = CFUNCTYPE(c_double, c_void_p, c_void_p)(("objc_msgSend", _objc))
_flag = CFUNCTYPE(c_bool, c_void_p, c_void_p)(("objc_msgSend", _objc))


class _Size(Structure):
    _fields_ = [("width", c_double), ("height", c_double)]


class _Point(Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


_fitting_size = CFUNCTYPE(_Size, c_void_p, c_void_p)(("objc_msgSend", _objc))
_set_size = CFUNCTYPE(None, c_void_p, c_void_p, _Size)(("objc_msgSend", _objc))
_set_origin = CFUNCTYPE(None, c_void_p, c_void_p, _Point)(("objc_msgSend", _objc))
_object_at = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_long)(("objc_msgSend", _objc))
_void = CFUNCTYPE(None, c_void_p, c_void_p)(("objc_msgSend", _objc))
_number = CFUNCTYPE(c_long, c_void_p, c_void_p)(("objc_msgSend", _objc))
_set_number = CFUNCTYPE(None, c_void_p, c_void_p, c_long)(("objc_msgSend", _objc))
_string = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_char_p)(("objc_msgSend", _objc))
_named_font = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_void_p, c_double)(("objc_msgSend", _objc))
_system_font = CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_double)(("objc_msgSend", _objc))


def set_window_title_font(window: QWidget) -> None:
    view = int(window.effectiveWinId() or 0)
    native = _object(view, _selector(b"window")) if view else None
    if not native:
        return
    # Keep NSWindow's title and traffic lights for accessibility and window management.
    # Only the visible text is supplied by our native titlebar accessory.
    controllers = _object(native, _selector(b"titlebarAccessoryViewControllers"))
    title_tag = 0x4253544C
    label = None
    for index in range(_number(controllers, _selector(b"count"))):
        controller = _object_at(controllers, _selector(b"objectAtIndex:"), index)
        container = _object(controller, _selector(b"view"))
        label = _object_at(container, _selector(b"viewWithTag:"), title_tag)
        if label:
            break
    ns_string = _objc.objc_getClass(b"NSString")
    text = _string(ns_string, _selector(b"stringWithUTF8String:"), window.windowTitle().encode("utf-8"))
    if label is None:
        label = _object_with_arg(_objc.objc_getClass(b"NSTextField"), _selector(b"labelWithString:"), text)
        _set_number(label, _selector(b"setTag:"), title_tag)
        controller = _object(_objc.objc_getClass(b"NSTitlebarAccessoryViewController"), _selector(b"new"))
        _set_number(controller, _selector(b"setLayoutAttribute:"), 1)  # NSLayoutAttributeLeft
        container = _object(_objc.objc_getClass(b"NSView"), _selector(b"new"))
        _set_number(container, _selector(b"setAutoresizingMask:"), 16)  # NSViewHeightSizable
        _set_number(label, _selector(b"setAutoresizingMask:"), 8 | 32)  # Flexible vertical margins
        _set_object(container, _selector(b"addSubview:"), label)
        _set_object(controller, _selector(b"setView:"), container)
        _void(container, _selector(b"release"))
        _set_object(native, _selector(b"addTitlebarAccessoryViewController:"), controller)
        _void(controller, _selector(b"release"))
    _set_number(native, _selector(b"setTitleVisibility:"), 1)  # NSWindowTitleHidden
    info = QFontInfo(window.font())
    family = _string(ns_string, _selector(b"stringWithUTF8String:"), info.family().encode("utf-8"))
    fonts = _objc.objc_getClass(b"NSFont")
    size = info.pointSizeF()
    font = _named_font(fonts, _selector(b"fontWithName:size:"), family, size) or _system_font(fonts, _selector(b"systemFontOfSize:"), size)
    _set_object(label, _selector(b"setStringValue:"), text)
    _set_object(label, _selector(b"setFont:"), font)
    _void(label, _selector(b"sizeToFit"))
    # AppKit places a leading accessory at the top of the title bar. Give the
    # accessory the native frame height and center the text field inside it.
    text_size = _fitting_size(label, _selector(b"fittingSize"))
    height = max(text_size.height, window.windowHandle().frameMargins().top())
    _set_size(container, _selector(b"setFrameSize:"), _Size(text_size.width, height))
    _set_origin(label, _selector(b"setFrameOrigin:"), _Point(0, (height - text_size.height) / 2))


def set_window_appearance(window: QWidget, dark: bool) -> None:
    # On Cocoa a widget's WId is an NSView. The NSWindow owns its native title bar.
    view = int(window.effectiveWinId() or 0)
    native = _object(view, _selector(b"window")) if view else None
    if native:
        name = c_void_p.in_dll(_appkit, "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua")
        appearance = _object_with_arg(_objc.objc_getClass(b"NSAppearance"), _selector(b"appearanceNamed:"), name)
        _set_object(native, _selector(b"setAppearance:"), appearance)


class MacAppearance(QObject):
    accent_changed = pyqtSignal()

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._accent = self._read_accent()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh)
        app.installEventFilter(self)
        app.applicationStateChanged.connect(lambda _state: self._timer.start(0))

    @staticmethod
    def _read_accent() -> QColor:
        color = _object(_objc.objc_getClass(b"NSColor"), _selector(b"controlAccentColor"))
        space = _object(_objc.objc_getClass(b"NSColorSpace"), _selector(b"sRGBColorSpace"))
        rgb = _object_with_arg(color, _selector(b"colorUsingColorSpace:"), space)
        if not rgb:
            return QColor()
        return QColor.fromRgbF(*(_component(rgb, _selector(name)) for name in
                                 (b"redComponent", b"greenComponent", b"blueComponent")))

    def _refresh(self) -> None:
        current = self._read_accent()
        if current != self._accent:
            self._accent = current
            self.accent_changed.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self._timer.start(0)
        return False

    def accent(self) -> QColor:
        return self._accent

    def reduced_motion(self) -> bool:
        workspace = _object(_objc.objc_getClass(b"NSWorkspace"), _selector(b"sharedWorkspace"))
        return _flag(workspace, _selector(b"accessibilityDisplayShouldReduceMotion"))
