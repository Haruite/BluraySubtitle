"""Read desktop appearance settings missing from the Qt palette."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QObject, QProcess, QProcessEnvironment, QSettings, QStandardPaths, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget

from .x11_window import apply_x11_title_bar_theme

if sys.platform == "darwin":
    from .macos_appearance import MacAppearance, set_window_appearance

QDBusConnection = None
_LEGACY_WINDOWS = sys.platform == "win32" and sys.getwindowsversion().platform_version[0] < 10
if _LEGACY_WINDOWS:
    import ctypes
    from ctypes import wintypes

    from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer

    _dwm = ctypes.WinDLL("dwmapi")
    _dwm_composition_enabled = _dwm.DwmIsCompositionEnabled
    _dwm_composition_enabled.argtypes = (ctypes.POINTER(wintypes.BOOL),)
    _dwm_composition_enabled.restype = ctypes.c_long
    _dwm_colorization = _dwm.DwmGetColorizationColor
    _dwm_colorization.argtypes = (ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BOOL))
    _dwm_colorization.restype = ctypes.c_long
    _system_color = ctypes.WinDLL("user32").GetSysColor
    _system_color.argtypes = (ctypes.c_int,)
    _system_color.restype = wintypes.DWORD
    _COLOR_HIGHLIGHT = 13
    _COLOR_MESSAGES = {
        0x0015,  # WM_SYSCOLORCHANGE
        0x031A,  # WM_THEMECHANGED
        0x031E,  # WM_DWMCOMPOSITIONCHANGED
        0x0320,  # WM_DWMCOLORIZATIONCOLORCHANGED
    }

    class _WindowsColorEvents(QAbstractNativeEventFilter):
        def __init__(self, refresh) -> None:
            super().__init__()
            self._refresh = refresh

        def nativeEventFilter(self, event_type, message):
            if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                if wintypes.MSG.from_address(int(message)).message in _COLOR_MESSAGES:
                    QTimer.singleShot(0, self._refresh)
            return False, 0

    class _WindowsAppearance(QObject):
        accent_changed = pyqtSignal()

        def __init__(self, app: QApplication) -> None:
            super().__init__(app)
            self._accent = self._read_accent()
            self._events = _WindowsColorEvents(self._refresh)
            app.installNativeEventFilter(self._events)

        @staticmethod
        def _read_accent() -> QColor:
            color = wintypes.DWORD()
            opaque = wintypes.BOOL()
            enabled = wintypes.BOOL()
            if (_dwm_composition_enabled(ctypes.byref(enabled)) == 0 and enabled.value
                    and _dwm_colorization(ctypes.byref(color), ctypes.byref(opaque)) == 0 and color.value):
                # The frame's transparency is independent of the accent used by opaque controls.
                return QColor.fromRgb(color.value)
            colorref = _system_color(_COLOR_HIGHLIGHT)
            return QColor(colorref & 0xFF, colorref >> 8 & 0xFF, colorref >> 16 & 0xFF)

        def _refresh(self) -> None:
            accent = self._read_accent()
            if accent != self._accent:
                self._accent = accent
                self.accent_changed.emit()

        def accent(self) -> QColor:
            return self._accent

        def reduced_motion(self) -> bool:
            return False

if os.name == "posix":
    try:
        from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusVariant
    except (ImportError, OSError):
        QDBusVariant = object
else:
    QDBusVariant = object


_PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_INTERFACE = "org.freedesktop.portal.Settings"
_APPEARANCE = "org.freedesktop.appearance"


def _portal_setting(bus, namespace: str, key: str):
    if bus is None or not bus.isConnected():
        return None
    request = QDBusMessage.createMethodCall(_PORTAL_SERVICE, _PORTAL_PATH, _PORTAL_INTERFACE, "Read")
    request.setArguments([namespace, key])
    reply = bus.call(request, timeout=300)
    if reply.type() == QDBusMessage.MessageType.ReplyMessage and (values := reply.arguments()):
        return values[0]
    return None


def _accent_color(value) -> QColor:
    if isinstance(value, (list, tuple)) and len(value) == 3 and all(
            isinstance(n, (int, float)) and 0 <= n <= 1 for n in value):
        return QColor.fromRgbF(*value)
    return QColor()


class _DesktopAppearance(QObject):
    accent_changed = pyqtSignal()

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        session = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("XDG_SESSION_DESKTOP")
                   or os.environ.get("DESKTOP_SESSION", ""))
        desktops = set(session.lower().split(":"))
        self._kde = "kde" in desktops
        self._lxqt = "lxqt" in desktops
        self._gtk_desktop = bool(desktops & {"xfce", "mate", "x-cinnamon", "cinnamon", "budgie", "pantheon"})
        self._config = None
        if self._kde or self._lxqt:
            directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation))
            name = "kdeglobals" if self._kde else "lxqt/lxqt.conf"
            self._config = QSettings(str(directory / name), QSettings.Format.IniFormat, self)
            self._config_watch = QFileSystemWatcher(self)
            self._config_watch.fileChanged.connect(self._reload_palette)
            self._config_watch.directoryChanged.connect(self._reload_palette)
            self._reload_palette()

        bus = QDBusConnection.sessionBus() if QDBusConnection else None
        self._portal_accent = _accent_color(_portal_setting(bus, _APPEARANCE, "accent-color"))
        self._portal_motion = _portal_setting(bus, _APPEARANCE, "reduced-motion")
        self._gtk_color = QColor()
        self._gtk_motion = False
        if bus is not None:
            bus.connect(_PORTAL_SERVICE, _PORTAL_PATH, _PORTAL_INTERFACE, "SettingChanged", self._setting_changed)
        if not (self._kde or self._lxqt) and (self._gtk_desktop or not self._portal_accent.isValid()):
            from src.exports.utils import system_tool_environment

            env = system_tool_environment()
            program = sys.executable if not getattr(sys, "frozen", False) else shutil.which("python3", path=env.get("PATH"))
            if program:
                self._probe = QProcess(self)
                environment = QProcessEnvironment()
                for key, value in env.items():
                    environment.insert(key, value)
                self._probe.setProcessEnvironment(environment)
                self._probe.readyReadStandardOutput.connect(self._read_gtk)
                app.aboutToQuit.connect(self._stop_gtk)
                script = Path(__file__).resolve().parents[1] / "gtk_appearance_probe.py"
                self._probe.start(program, ["-I", "-B", str(script), "gnome" if "gnome" in desktops else "gtk3"])

    def _stop_gtk(self) -> None:
        self._probe.closeWriteChannel()
        if self._probe.state() != QProcess.ProcessState.NotRunning and not self._probe.waitForFinished(300):
            self._probe.terminate()
            self._probe.waitForFinished(300)

    def _read_gtk(self) -> None:
        while self._probe.canReadLine():
            color, self._gtk_motion = json.loads(bytes(self._probe.readLine()))
            self._gtk_color = _accent_color(color)
            self.accent_changed.emit()

    def _reload_palette(self, _path="") -> None:
        config = Path(self._config.fileName())
        # Watch the containing directory as well: desktop settings are commonly replaced atomically.
        for path in (config.parent.parent if self._lxqt else config.parent, config.parent, config):
            if path.exists() and str(path) not in self._config_watch.files() + self._config_watch.directories():
                self._config_watch.addPath(str(path))
        self._config.sync()
        self.accent_changed.emit()

    def accent(self) -> QColor:
        if self._config is not None:
            if self._kde:
                value = self._config.value("AccentColor")
                color = self._kde_color(value)
                if color.isValid():
                    return color
            elif self._config.value("palette_override", True, type=bool):
                color = QColor(self._config.value("Palette/highlight_color", ""))
                if color.isValid():
                    return color
        if self._gtk_desktop and self._gtk_color.isValid():
            return self._gtk_color
        if self._portal_accent.isValid():
            return self._portal_accent
        if self._kde:
            return self._kde_color(self._config.value("Colors:Selection/BackgroundNormal"))
        return self._gtk_color

    @staticmethod
    def _kde_color(value) -> QColor:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, (tuple, list)) and len(value) >= 3:
            try:
                channels = [int(v) for v in value[:3]]
            except (TypeError, ValueError):
                return QColor()
            if all(0 <= v <= 255 for v in channels):
                return QColor(*channels)
        return QColor()

    def reduced_motion(self) -> bool:
        if self._portal_motion is not None:
            return self._portal_motion == 1
        if self._kde:
            try:
                return float(self._config.value("KDE/AnimationDurationFactor", 1)) == 0
            except (ValueError, TypeError):
                return False
        return self._gtk_motion

    @pyqtSlot(str, str, QDBusVariant)
    def _setting_changed(self, namespace: str, key: str, value) -> None:
        if namespace == _APPEARANCE and key == "accent-color":
            self._portal_accent = _accent_color(value.variant())
            if self._config is not None:
                self._config.sync()
            self.accent_changed.emit()
        elif namespace == _APPEARANCE and key == "reduced-motion":
            self._portal_motion = value.variant()


def apply_title_bar_theme(window: QWidget, dark: bool) -> None:
    if QApplication.platformName() == "cocoa":
        if (window.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog)
                and window.windowHandle() is not None and not window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)):
            set_window_appearance(window, dark)
    else:
        apply_x11_title_bar_theme(window, dark)


def desktop_appearance() -> _DesktopAppearance | _WindowsAppearance | MacAppearance | None:
    app = QApplication.instance()
    platform = app.platformName() if app is not None else ""
    if platform == "cocoa":
        return app.findChild(MacAppearance) or MacAppearance(app)
    if _LEGACY_WINDOWS and platform == "windows":
        return app.findChild(_WindowsAppearance) or _WindowsAppearance(app)
    if platform == "xcb" or platform.startswith("wayland"):
        return app.findChild(_DesktopAppearance) or _DesktopAppearance(app)
    return None
