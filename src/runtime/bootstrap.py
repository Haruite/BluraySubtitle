"""Application bootstrap for migrated src runtime."""

import os
import sys
from contextlib import suppress
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QStyle

from src.core.version import APP_TITLE, current_commit
from src.core.app_config import macos_application_bundle
from src.core.i18n import translate_text
from src.exports.utils import print_terminal_line

from .application_log import ApplicationLog
from .desktop_integration import application_icon_path, desktop_entry_id, supports_desktop_entries
from .gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from .gui_runtime_classes.widget_animations import AnimatedMessageBox, enable_combo_animation
from .gui_runtime_classes.x11_window import set_x11_window_identity
from .instance_activation import InstanceActivation

def _macos_menu_bar(window: BluraySubtitleGUI):
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import QMenuBar

    # A parentless Cocoa menu bar also remains available when the window is hidden.
    bar = QMenuBar()
    menu = bar.addMenu(window.t("Window"))
    for title, role, callback in (
        ("Third-party notices", QAction.MenuRole.AboutRole, window._open_third_party_notices_dialog),
        ("Settings", QAction.MenuRole.PreferencesRole, window._show_settings_dialog),
        ("Exit", QAction.MenuRole.QuitRole, window._exit_application),
    ):
        action = QAction(window.t(title), menu)
        action.setMenuRole(role)
        action.triggered.connect(callback)
        menu.addAction(action)
    show = menu.addAction(window.t("Show main window"), window._restore_from_tray)

    def translate_menu():
        menu.setTitle(window.t("Window"))
        show.setText(window.t("Show main window"))

    window.language_combo.currentIndexChanged.connect(translate_menu)
    return bar


def run_src_entry(application_log: ApplicationLog | None = None) -> None:
    frozen = getattr(sys, "frozen", False)
    if sys.platform == "win32" and not frozen:
        import ctypes

        # Keep source launches out of python.exe's taskbar group.
        with suppress(AttributeError, OSError):
            set_taskbar_app_id = ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID
            set_taskbar_app_id.argtypes = (ctypes.c_wchar_p,)
            set_taskbar_app_id.restype = ctypes.c_long
            set_taskbar_app_id("Haruite.BluraySubtitle")
    desktop_id = desktop_entry_id() if supports_desktop_entries() else ""
    desktop_entry = desktop_id and QStandardPaths.locate(
        QStandardPaths.StandardLocation.ApplicationsLocation, f"{desktop_id}.desktop",
    )
    if desktop_entry:
        QApplication.setDesktopFileName(desktop_id)
    app = QApplication.instance() or QApplication(sys.argv)
    if not desktop_id and supports_desktop_entries():
        desktop_id = desktop_entry_id()
    ready_file = update_error = ""
    update_guard = None
    if (frozen and sys.platform.startswith("linux")) or getattr(sys, "_bluray_freebsd_runtime", None):
        from .portable_update import update_in_progress as update_guard
    elif macos_application_bundle():
        from .macos_update import update_in_progress as update_guard
    if update_guard:
        ready_file = os.environ.pop("BLURAY_SUBTITLE_UPDATE_READY", "")
        update_error = os.environ.pop("BLURAY_SUBTITLE_UPDATE_ERROR", "")
        if not (ready_file or update_error) and update_guard():
            QMessageBox.warning(None, APP_TITLE, translate_text("An update is already running for this installation."))
            return
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
    if app.platformName() == "cocoa":
        app.setApplicationDisplayName("BluraySubtitle")
        window._macos_menu = _macos_menu_bar(window)
    if instance is not None:
        instance.activation_requested.connect(window._restore_from_tray)
        app.aboutToQuit.connect(instance.release)
    if desktop_id:
        set_x11_window_identity(window, desktop_id)
    window.show()
    if sys.platform == "darwin":
        gui_ready = os.environ.pop("BLURAY_SUBTITLE_GUI_READY", "")
        ready_file = ready_file or gui_ready
        # Cocoa delivers a forced activation for Dock and Finder reopens, including
        # when the red close button has previously hidden the window in the menu bar.
        def restore_hidden_window(state):
            if state == Qt.ApplicationState.ApplicationActive and not window.isVisible() and not window._close_pending:
                window._restore_from_tray()

        app.applicationStateChanged.connect(restore_hidden_window)
    if ready_file:
        QTimer.singleShot(0, lambda: Path(ready_file).touch())
    if update_error:
        QTimer.singleShot(0, lambda: AnimatedMessageBox.warning(
            window, translate_text("Check for updates"), update_error,
        ))
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

