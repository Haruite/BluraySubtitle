"""Disc selection and row moves that retain embedded playlist editors."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QTableWidgetItem, QWidget

from .custom_table_widget import CustomTableWidget


class DiscTableWidget(CustomTableWidget):
    discsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, self._disc_moved)
        self._checked_paths: dict[str, bool] = {}
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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

    def _disc_moved(self) -> None:
        self._sort_column = -1
        self.discsChanged.emit()
