from typing import Optional, Callable

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtGui import QDrag, QDragMoveEvent, QDropEvent, QPaintEvent, QPainter, QColor
from PyQt6.QtWidgets import QAbstractItemView, QTableWidget, QWidget


class CustomTableWidget(QTableWidget):
    def __init__(self, parent: Optional[QWidget]=None, on_drop: Optional[Callable]=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(self.selectionMode().MultiSelection)
        self.target_row = -1
        self._drag_source_row = -1
        self.on_drop = on_drop

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasFormat('application/x-qabstractitemmodeldatalist'):
            row = self.rowAt(int(event.position().y()))
            if row != self.target_row:
                self.target_row = row
                self.viewport().update()
            event.acceptProposedAction()

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        self._drag_source_row = self.currentRow()
        if self._drag_source_row < 0:
            return
        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData(self.selectedIndexes()))
        try:
            # The drop handler moves model rows; default drag cleanup would
            # otherwise clear the items that now belong to the moved row.
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._drag_source_row = -1
            self.target_row = -1
            self.viewport().update()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is not self:
            event.ignore()
            return
        source = self._drag_source_row if self._drag_source_row >= 0 else self.currentRow()
        target = self.rowAt(int(event.position().y()))
        if target < 0:
            target = self.rowCount()
        elif event.position().y() > self.rowViewportPosition(target) + self.rowHeight(target) / 2:
            target += 1
        if source < 0 or target in (source, source + 1):
            event.ignore()
            return
        # Model moves preserve item data, persistent indexes and cell widgets.
        if not self.model().moveRows(QModelIndex(), source, 1, QModelIndex(), target):
            event.ignore()
            return
        self.setCurrentCell(target - 1 if source < target else target, 0)
        self.horizontalHeader().setSortIndicatorShown(False)
        self.target_row = -1
        self.viewport().update()
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if self.on_drop is not None:
            self.on_drop()

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        if self.target_row >= 0:
            rect1 = self.visualRect(self.indexFromItem(self.item(self.target_row, 0)))
            rect2 = self.visualRect(self.indexFromItem(self.item(self.target_row, self.columnCount() - 1)))
            painter = QPainter(self.viewport())
            painter.setPen(QColor(10, 240, 10))
            painter.drawLine(rect1.topLeft().x(), rect1.topLeft().y(), rect2.bottomRight().x(), rect2.topLeft().y())
