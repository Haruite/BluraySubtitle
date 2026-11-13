"""Application bootstrap for migrated src runtime."""

import sys

from PyQt6.QtCore import QStandardPaths, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QStyle

from src.core.version import APP_TITLE, current_commit
from src.core.i18n import translate_text
from src.exports.utils import print_terminal_line

from .application_log import ApplicationLog
from .desktop_integration import application_icon_path, desktop_entry_id
from .gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from .gui_runtime_classes.widget_animations import enable_combo_animation
from .instance_activation import InstanceActivation

if sys.platform == "win32":
    import ctypes

    _set_taskbar_app_id = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
    _set_taskbar_app_id.argtypes = (ctypes.c_wchar_p,)
    _set_taskbar_app_id.restype = ctypes.c_long


def run_src_entry(application_log: ApplicationLog | None = None) -> None:
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        # Keep source launches out of python.exe's taskbar group.
        _set_taskbar_app_id("Haruite.BluraySubtitle")
    desktop_id = desktop_entry_id() if sys.platform.startswith("linux") else ""
    if desktop_id:
        desktop_entry = QStandardPaths.locate(
            QStandardPaths.StandardLocation.ApplicationsLocation, f"{desktop_id}.desktop",
        )
        if desktop_entry:
            # Qt registers an installed entry before the GUI reads appearance settings.
            QApplication.setDesktopFileName(desktop_id)
    app = QApplication.instance() or QApplication(sys.argv)
    instance = None
    try:
        instance = InstanceActivation(app)
        if not instance.claim():
            return
    except TimeoutError as error:
        QMessageBox.warning(None, APP_TITLE, str(error))
        return
    except OSError as error:
        instance = None
        print_terminal_line(
            translate_text("Could not start local instance detection. {error}").format(error=error),
            translate=False,
        )
    if desktop_id and not desktop_entry:
        # Let Qt's queued portal check skip registration before assigning the window ID.
        app.processEvents()
        app.setDesktopFileName(desktop_id)
    # Capture Git metadata before the GUI starts handling events.
    current_commit()
    enable_combo_animation()
    app.setWindowIcon(QIcon(str(application_icon_path())))
    window = BluraySubtitleGUI(application_log)
    if instance is not None:
        instance.activation_requested.connect(window._restore_from_tray)
        app.aboutToQuit.connect(instance.release)
    window.show()
    try:
        # Re-apply current UI font once after show so all widgets are ready.
        QTimer.singleShot(0, lambda: window._on_font_size_changed() if hasattr(window, '_on_font_size_changed') else None)
    except Exception:
        pass
    try:
        def fit_window_to_available_screen():
            if bool(getattr(window, '_window_geometry_restored', False)):
                return
            screen = window.screen() or app.primaryScreen()
            if not screen:
                return
            avail = screen.availableGeometry()
            fg = window.frameGeometry()
            # Native frame margins may not be available on the first event-loop turn.
            style = window.style()
            border = style.pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth) * 2
            chrome_h = max(fg.height() - window.height(),
                           style.pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight) + border)
            chrome_w = max(fg.width() - window.width(), border)

            # Keep previous small-screen fitting behavior.
            if avail.height() <= 1200:
                target_w = max(200, min(window.width(), max(200, avail.width() - chrome_w)))
                target_h = max(200, avail.height() - chrome_h)
                window.resize(target_w, target_h)

            frame_w = window.width() + chrome_w
            frame_h = window.height() + chrome_h
            x = avail.left() + max(0, (avail.width() - frame_w) // 2)
            y = avail.top() + max(0, (avail.height() - frame_h) // 2)
            window.move(x, y)

        QTimer.singleShot(0, fit_window_to_available_screen)
    except Exception:
        pass
    sys.exit(app.exec())


def main() -> None:
    run_src_entry()

