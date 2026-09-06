"""Application bootstrap for migrated src runtime."""

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QStyle

from .gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI


def run_src_entry() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = BluraySubtitleGUI()
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

