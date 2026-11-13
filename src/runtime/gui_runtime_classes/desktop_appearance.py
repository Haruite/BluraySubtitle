"""Read appearance settings missing from the Qt palette on Linux desktops."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QObject, QSettings, QStandardPaths, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

if sys.platform.startswith("linux"):
    from PyQt6.QtDBus import QDBusConnection, QDBusMessage, QDBusVariant

    _PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
    _PORTAL_PATH = "/org/freedesktop/portal/desktop"
    _PORTAL_INTERFACE = "org.freedesktop.portal.Settings"
    _APPEARANCE = "org.freedesktop.appearance"
    _GNOME_INTERFACE = "org.gnome.desktop.interface"
    _GTK_SELECTION_COLOR = re.compile(r"@define-color\s+theme_selected_bg_color\s+(#[0-9a-fA-F]{6})\s*;")

    def _portal_setting(bus: QDBusConnection, namespace: str, key: str) -> object:
        request = QDBusMessage.createMethodCall(_PORTAL_SERVICE, _PORTAL_PATH, _PORTAL_INTERFACE, "Read")
        request.setArguments([namespace, key])
        reply = bus.call(request, timeout=300)
        if reply.type() == QDBusMessage.MessageType.ReplyMessage and (values := reply.arguments()):
            return values[0]
        return None

    def _accent_color(value: object) -> QColor:
        if isinstance(value, (list, tuple)) and len(value) == 3 and all(
                isinstance(channel, (int, float)) and 0 <= channel <= 1 for channel in value
        ):
            return QColor.fromRgbF(*value)
        return QColor()

    class _DesktopAppearance(QObject):
        accent_changed = pyqtSignal()

        def __init__(self, app: QApplication) -> None:
            super().__init__(app)
            desktops = os.environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
            self._kde_config = None
            if "kde" in desktops:
                path = QStandardPaths.locate(QStandardPaths.StandardLocation.GenericConfigLocation, "kdeglobals")
                if path:
                    self._kde_config = QSettings(path, QSettings.Format.IniFormat, self)
                    self._kde_watcher = QFileSystemWatcher([path], self)
                    self._kde_watcher.fileChanged.connect(self._kde_settings_changed)

            bus = QDBusConnection.sessionBus()
            self._accent = _accent_color(_portal_setting(bus, _APPEARANCE, "accent-color"))
            self._portal_motion = _portal_setting(bus, _APPEARANCE, "reduced-motion")
            self._gnome_motion = False
            self._gnome = "gnome" in desktops
            self._gtk_accent = QColor()
            if self._gnome:
                if not self._accent.isValid():
                    self._set_yaru_accent(_portal_setting(bus, _GNOME_INTERFACE, "gtk-theme"))
                if self._portal_motion is None:
                    self._gnome_motion = _portal_setting(bus, _GNOME_INTERFACE, "enable-animations") is False
            bus.connect(_PORTAL_SERVICE, _PORTAL_PATH, _PORTAL_INTERFACE, "SettingChanged", self._setting_changed)

        def accent(self) -> QColor:
            # QSettings exposes KDE's [General] group at the root.
            accent = self._kde_color("AccentColor")
            if not accent.isValid():
                accent = self._accent
            if not accent.isValid():
                accent = self._kde_color("Colors:Selection/BackgroundNormal")
            return accent if accent.isValid() else self._gtk_accent

        def _set_yaru_accent(self, theme: object) -> None:
            self._gtk_accent = QColor()
            if not isinstance(theme, str) or not re.fullmatch(r"Yaru(?:-[\w-]+)?", theme):
                return
            # Older Ubuntu desktops expose the Yaru variant through GTK's theme name.
            path = QStandardPaths.locate(
                QStandardPaths.StandardLocation.GenericDataLocation, f"themes/{theme}/gtk-3.0/gtk.css",
            )
            if not path:
                return
            try:
                stylesheet = Path(path).read_text(encoding="utf-8")
                # Ubuntu's packaged Yaru CSS imports the stylesheet from gtk.gresource.
                resource_path = f"/com/ubuntu/themes/{theme}/3.0/gtk.css"
                if f"resource://{resource_path}" in stylesheet:
                    stylesheet = subprocess.run(
                        ["gresource", "extract", str(Path(path).with_name("gtk.gresource")), resource_path],
                        capture_output=True, check=True, timeout=1, encoding="utf-8",
                    ).stdout
            except (OSError, UnicodeError, subprocess.SubprocessError):
                return
            if match := _GTK_SELECTION_COLOR.search(stylesheet):
                self._gtk_accent = QColor(match[1])

        def _kde_color(self, key: str) -> QColor:
            if self._kde_config is not None:
                channels = self._kde_config.value(key)
                if isinstance(channels, list) and len(channels) >= 3:
                    try:
                        rgb = [int(channel) for channel in channels[:3]]
                    except (ValueError, TypeError):
                        return QColor()
                    if all(0 <= channel <= 255 for channel in rgb):
                        return QColor(*rgb)
            return QColor()

        def _kde_settings_changed(self, path: str) -> None:
            # Plasma can replace kdeglobals while writing its settings.
            if not self._kde_watcher.files():
                self._kde_watcher.addPath(path)
            self._kde_config.sync()
            self.accent_changed.emit()

        def reduced_motion(self) -> bool:
            if self._portal_motion is not None:
                return self._portal_motion == 1
            if self._kde_config is None:
                return self._gnome_motion
            try:
                return float(self._kde_config.value("KDE/AnimationDurationFactor", 1)) == 0
            except (ValueError, TypeError):
                return False

        @pyqtSlot(str, str, QDBusVariant)
        def _setting_changed(self, namespace: str, key: str, value: QDBusVariant) -> None:
            if namespace == _APPEARANCE and key == "accent-color":
                self._accent = _accent_color(value.variant())
                if self._kde_config is not None:
                    self._kde_config.sync()
                elif self._gnome and not self._accent.isValid():
                    bus = QDBusConnection.sessionBus()
                    self._set_yaru_accent(_portal_setting(bus, _GNOME_INTERFACE, "gtk-theme"))
                self.accent_changed.emit()
            elif namespace == _APPEARANCE and key == "reduced-motion":
                self._portal_motion = value.variant()
            elif self._gnome and namespace == _GNOME_INTERFACE and key == "enable-animations":
                self._gnome_motion = value.variant() is False
            elif self._gnome and namespace == _GNOME_INTERFACE and key == "gtk-theme" and not self._accent.isValid():
                self._set_yaru_accent(value.variant())
                self.accent_changed.emit()


def desktop_appearance() -> _DesktopAppearance | None:
    app = QApplication.instance()
    platform = app.platformName() if app is not None else ""
    if sys.platform.startswith("linux") and (platform == "xcb" or platform.startswith("wayland")):
        return app.findChild(_DesktopAppearance) or _DesktopAppearance(app)
    return None
