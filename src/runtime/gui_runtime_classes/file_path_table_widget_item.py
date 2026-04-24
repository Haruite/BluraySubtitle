import os

from PyQt6.QtWidgets import QTableWidgetItem


class FilePathTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            left = os.path.basename(self.text()).lower() if self.text() else ''
            right = os.path.basename(other.text()).lower() if other.text() else ''
            return left < right
        return super().__lt__(other)
