"""Application bootstrap for migrated src runtime."""

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

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
            screen = window.screen() or app.primaryScreen()
            if not screen:
                return
            avail = screen.availableGeometry()
            fg = window.frameGeometry()
            chrome_h = max(0, fg.height() - window.height())
            chrome_w = max(0, fg.width() - window.width())

            # Keep previous small-screen fitting behavior.
            if avail.height() <= 1200:
                target_w = max(200, min(window.width(), max(200, avail.width() - chrome_w)))
                target_h = max(200, avail.height() - chrome_h)
                window.resize(target_w, target_h)

            fg2 = window.frameGeometry()
            centered_x = avail.left() + max(0, (avail.width() - fg2.width()) // 2)
            centered_y = avail.top() + max(0, (avail.height() - fg2.height()) // 2)
            x = min(max(centered_x, avail.left()), avail.right() - fg2.width() + 1)
            y = min(max(centered_y, avail.top()), avail.bottom() - fg2.height() + 1)
            window.move(x, y)

        QTimer.singleShot(0, fit_window_to_available_screen)
    except Exception:
        pass
    sys.exit(app.exec())


def main() -> None:
    run_src_entry()

