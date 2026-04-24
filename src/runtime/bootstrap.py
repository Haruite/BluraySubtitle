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
        def fit_window_to_available_screen():
            screen = window.screen() or app.primaryScreen()
            if not screen:
                return
            avail = screen.availableGeometry()
            if avail.height() > 1200:
                return
            fg = window.frameGeometry()
            chrome_h = max(0, fg.height() - window.height())
            chrome_w = max(0, fg.width() - window.width())
            target_w = max(200, min(window.width(), max(200, avail.width() - chrome_w)))
            target_h = max(200, avail.height() - chrome_h)
            window.resize(target_w, target_h)

            fg2 = window.frameGeometry()
            x = min(max(fg2.x(), avail.left()), avail.right() - fg2.width() + 1)
            y = avail.top()
            window.move(x, y)

            fg3 = window.frameGeometry()
            if fg3.bottom() > avail.bottom():
                window.move(x, avail.bottom() - fg3.height() + 1)

        QTimer.singleShot(0, fit_window_to_available_screen)
    except Exception:
        pass
    sys.exit(app.exec())


def main() -> None:
    run_src_entry()

