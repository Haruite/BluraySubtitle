from typing import Optional, Callable

from PyQt6.QtGui import QDragMoveEvent, QDropEvent, QPaintEvent, QPainter, QColor
from PyQt6.QtWidgets import QTableWidget, QWidget


class CustomTableWidget(QTableWidget):
    def __init__(self, parent: Optional[QWidget]=None, on_drop: Optional[Callable]=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setSelectionMode(self.selectionMode().MultiSelection)
        self.target_row = -1
        self.on_drop = on_drop

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasFormat('application/x-qabstractitemmodeldatalist'):
            row = self.rowAt(int(event.position().y()))
            if row != self.target_row:
                self.target_row = row
                self.viewport().update()
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        if event.source() is self and event.mimeData().hasFormat('application/x-qabstractitemmodeldatalist'):
            drag_row = self.currentRow()
            drop_row = self.rowAt(int(event.position().y()))
            if drop_row < 0:
                drop_row = self.rowCount()
            if drag_row != drop_row:
                items = [self.takeItem(drag_row, col) for col in range(self.columnCount())]
                self.insertRow(drop_row)
                [self.setItem(drop_row, col, item) for col, item in enumerate(items) if item]
                self.removeRow(drag_row if drag_row < drop_row else drag_row + 1)
                self.target_row = -1
                self.viewport().update()
                event.acceptProposedAction()
            event.accept()
            self.on_drop()
        else:
            super().dropEvent(event)

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        if self.target_row >= 0:
            rect1 = self.visualRect(self.indexFromItem(self.item(self.target_row, 0)))
            rect2 = self.visualRect(self.indexFromItem(self.item(self.target_row, self.columnCount() - 1)))
            painter = QPainter(self.viewport())
            painter.setPen(QColor(10, 240, 10))
            painter.drawLine(rect1.topLeft().x(), rect1.topLeft().y(), rect2.bottomRight().x(), rect2.topLeft().y())
