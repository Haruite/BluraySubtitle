from typing import Optional, Callable

from PyQt6.QtCore import QEvent, QItemSelectionModel, QModelIndex, Qt
from PyQt6.QtGui import QDrag, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QPalette
from PyQt6.QtWidgets import QAbstractItemView, QTableWidget, QWidget


class SelectionTableWidget(QTableWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)

    def selectionCommand(self, index, event=None):
        if event is None and self.indexWidget(index) is not None:
            # An embedded control has its own focus state.
            return QItemSelectionModel.SelectionFlag.Clear
        if (
            event is not None
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            if not index.isValid():
                return QItemSelectionModel.SelectionFlag.Clear
            selection_model = self.selectionModel()
            selection = selection_model.selection()
            if (
                index == self.currentIndex() and selection_model.isSelected(index)
                and len(selection) == 1 and selection[0].height() == 1
                and (selection[0].width() == 1 or self.selectionBehavior() == self.SelectionBehavior.SelectRows)
            ):
                # Qt defers selection on an already selected item until release, so it can still be dragged.
                return QItemSelectionModel.SelectionFlag.Clear
        return super().selectionCommand(index, event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if event.reason() == Qt.FocusReason.MouseFocusReason:
            self.clearSelection()


class CustomTableWidget(SelectionTableWidget):
    def __init__(self, parent: Optional[QWidget]=None, on_drop: Optional[Callable]=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDropIndicatorShown(False)
        # Keep the insertion line visible over embedded cell widgets.
        self._drop_indicator = QWidget(self.viewport())
        self._drop_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_indicator.hide()
        self._drag_source_row = -1
        self.on_drop = on_drop

    def _insertion_row_at(self, y: int) -> int:
        row = self.rowAt(y)
        if row < 0:
            return self.rowCount()
        if y > self.rowViewportPosition(row) + self.rowHeight(row) / 2:
            return row + 1
        return row

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.source() is not self or self._drag_source_row < 0:
            event.ignore()
            return
        target = self._insertion_row_at(int(event.position().y()))
        if target in (self._drag_source_row, self._drag_source_row + 1):
            self._drop_indicator.hide()
            event.ignore()
            return
        if target == self.rowCount():
            last = target - 1
            y = self.rowViewportPosition(last) + self.rowHeight(last)
        else:
            y = self.rowViewportPosition(target)
        viewport = self.viewport()
        top = max(0, min(y - 1, viewport.height() - 3))
        self._drop_indicator.setGeometry(0, top, viewport.width(), 3)
        self._drop_indicator.raise_()
        self._drop_indicator.show()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._drop_indicator.hide()
        super().dragLeaveEvent(event)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        self._start_row_drag(self.currentRow())

    def _make_row_drag(self, row: int) -> QDrag:
        drag = QDrag(self)
        model = self.model()
        drag.setMimeData(model.mimeData([model.index(row, column) for column in range(self.columnCount())]))
        return drag

    def _start_row_drag(self, row: int) -> None:
        if not 0 <= row < self.rowCount():
            return
        self._drag_source_row = row
        try:
            drag = self._make_row_drag(row)
            color = self.palette().color(QPalette.ColorRole.Accent).name()
            self._drop_indicator.setStyleSheet(f'background-color: {color};')
            # The drop handler moves model rows; default drag cleanup would
            # otherwise clear the items that now belong to the moved row.
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._drag_source_row = -1
            self._drop_indicator.hide()

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_indicator.hide()
        if event.source() is not self:
            event.ignore()
            return
        source = self._drag_source_row if self._drag_source_row >= 0 else self.currentRow()
        target = self._insertion_row_at(int(event.position().y()))
        if not self._move_row(source, target):
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        if self.on_drop is not None:
            self.on_drop()

    def _move_row(self, source: int, target: int) -> bool:
        if source < 0 or target in (source, source + 1):
            return False
        # Model moves preserve item data, persistent indexes and cell widgets.
        if not self.model().moveRows(QModelIndex(), source, 1, QModelIndex(), target):
            return False
        scrollbar = self.horizontalScrollBar()
        offset = scrollbar.value()
        self.setCurrentCell(target - 1 if source < target else target, 0)
        scrollbar.setValue(offset)
        self.horizontalHeader().setSortIndicatorShown(False)
        return True
