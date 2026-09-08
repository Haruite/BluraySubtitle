"""Disc selection and row moves that retain embedded playlist editors."""

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QDropEvent
from PyQt6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem, QWidget


class DiscTableWidget(QTableWidget):
    discsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._checked_paths: dict[str, bool] = {}
        self._drag_source_row = -1
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.horizontalHeader().sectionClicked.connect(self._sort_discs)
        self.itemChanged.connect(self._disc_checked)

    def _sort_discs(self, column: int) -> None:
        header = self.horizontalHeader()
        order = Qt.SortOrder.AscendingOrder
        if self._sort_column == column and self._sort_order == Qt.SortOrder.AscendingOrder:
            order = Qt.SortOrder.DescendingOrder
        self._sort_column = column
        self._sort_order = order
        # Sort only on an explicit header click; later checkbox edits must not
        # undo a manual row move or relocate partially populated rows.
        self.sortItems(column, order)
        header.setSortIndicator(column, order)
        header.setSortIndicatorShown(True)
        self.discsChanged.emit()

    def sync_selection(self) -> None:
        self._checked_paths = {}
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is None:
                continue
            checked = item.checkState() == Qt.CheckState.Checked
            self._checked_paths[item.text()] = checked
            for column in range(1, self.columnCount()):
                widget = self.cellWidget(row, column)
                if widget is not None:
                    widget.setEnabled(checked)

    def _disc_checked(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        checked = item.checkState() == Qt.CheckState.Checked
        if self._checked_paths.get(item.text()) == checked:
            return
        self.sync_selection()
        self.discsChanged.emit()

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        self._drag_source_row = self.currentRow()
        if self._drag_source_row < 0:
            return
        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData(self.selectedIndexes()))
        try:
            # dropEvent moves the existing model rows. QAbstractItemView's
            # default drag cleanup would otherwise remove the moved source.
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._drag_source_row = -1

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
        # Model row moves carry persistent indexes and cell widgets together.
        # Taking items and removing the source row would delete its editors.
        if not self.model().moveRows(QModelIndex(), source, 1, QModelIndex(), target):
            event.ignore()
            return
        self.setCurrentCell(target - 1 if source < target else target, 0)
        self.horizontalHeader().setSortIndicatorShown(False)
        self._sort_column = -1
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.discsChanged.emit()
