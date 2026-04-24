import os
from typing import Optional

from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QGroupBox, QWidget


class CustomBox(QGroupBox):  # Drag-and-drop folder input helper for boxed rows.
    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.box_title = title

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e: QDropEvent):
        if not e.mimeData().hasUrls():
            return
        url = e.mimeData().urls()[0]
        if not url.isLocalFile():
            return
        dropped_path = os.path.normpath(url.toLocalFile())

        w: Optional[QWidget] = self
        while w and not hasattr(w, 'bdmv_folder_path'):
            w = w.parentWidget()
        if not w:
            w = self.window()
        if not w:
            return

        if self.box_title == '原盘' and hasattr(w, 'bdmv_folder_path'):
            w.bdmv_folder_path.setText(dropped_path)
        if self.box_title == '字幕' and hasattr(w, 'subtitle_folder_path'):
            w.subtitle_folder_path.setText(dropped_path)
        if self.box_title == 'Remux' and hasattr(w, 'remux_folder_path'):
            w.remux_folder_path.setText(dropped_path)
