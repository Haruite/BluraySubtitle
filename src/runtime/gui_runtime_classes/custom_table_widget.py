from html import escape
from typing import Optional, Callable

from PyQt6.QtCore import (
    QEvent, QItemSelectionModel, QModelIndex, QPersistentModelIndex, QRect, QRectF, Qt, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QContextMenuEvent, QDrag, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent,
    QPainter, QPainterPath, QPalette, QPen,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QLineEdit, QMenu, QStyle, QStyledItemDelegate,
    QStyleOptionComboBox, QStyleOptionViewItem, QStylePainter, QTableWidget, QTableWidgetItem, QToolTip, QWidget,
)

from src.core.i18n import translate_text


READ_ONLY_HINT_ROLE = Qt.ItemDataRole.UserRole + 6


def editable_table_border_color(dark: bool) -> str:
    return '#4e5c6d' if dark else '#acc6df'


def draw_vertical_chevron(
        painter: QPainter, rect: QRect, palette: QPalette, *, enabled: bool, points_up: bool = False,
) -> None:
    if rect.isEmpty():
        return
    center = QRectF(rect).center()
    half_width = min(3.5, (rect.width() - 1) / 2)
    direction = -1 if points_up else 1
    end_y = center.y() - 1.5 * direction
    chevron = QPainterPath()
    chevron.moveTo(center.x() - half_width, end_y)
    chevron.lineTo(center.x(), center.y() + 1.75 * direction)
    chevron.lineTo(center.x() + half_width, end_y)

    color = palette.color(QPalette.ColorRole.ButtonText)
    color.setAlpha(185 if enabled else 115)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.15, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(chevron)
    painter.restore()


def _can_edit_cell_text(view: QWidget | None, index: QModelIndex) -> bool:
    editable = Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsEnabled
    return (
        (index.flags() & editable) == editable
        and isinstance(view, QTableWidget)
        and view.itemFromIndex(index) is not None
        and view.indexWidget(index) is None
        and bool(view.editTriggers() & QAbstractItemView.EditTrigger.DoubleClicked)
    )


def _is_table_value_column(view: QWidget | None, index: QModelIndex) -> bool:
    columns = view.property('columnKeys') if view is not None else None
    column = index.column()
    return bool(columns and 0 <= column < len(columns) and columns[column] in ('output_name', 'language'))


class StyledComboBox(QComboBox):
    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        control = QStyle.ComplexControl.CC_ComboBox
        arrow_control = QStyle.SubControl.SC_ComboBoxArrow
        arrow_rect = self.style().subControlRect(control, option, arrow_control, self)
        # Keep Qt's hit area for the dropdown and draw the chevron without its native button panel.
        option.subControls &= ~arrow_control
        painter = QStylePainter(self)
        painter.drawComplexControl(control, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)
        draw_vertical_chevron(painter, arrow_rect, option.palette, enabled=self.isEnabled())


class TableCellDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        table = option.widget
        if table is None or table.objectName() not in ('table2', 'table3'):
            return
        columns = table.property('columnKeys') or []
        column = index.column()
        if 0 <= column < len(columns) and columns[column] == 'bdmv_index':
            option.displayAlignment = Qt.AlignmentFlag.AlignCenter

    def paint(self, painter, option, index):
        view = option.widget
        if isinstance(view, QTableWidget) and option.state & QStyle.StateFlag.State_HasFocus:
            widget = view.indexWidget(index)
            if isinstance(widget, QComboBox) and not widget.isEnabled():
                option = QStyleOptionViewItem(option)
                option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)
        if not _can_edit_cell_text(view, index):
            return
        color = view.property('editableCellBorderColor') if _is_table_value_column(view, index) else None
        if color is None or not color.isValid():
            dark = QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
            color = QColor(editable_table_border_color(dark))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(option.rect).adjusted(1.5, 2.5, -1.5, -2.5), 4, 4)
        painter.restore()

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit) and _is_table_value_column(option.widget, index):
            editor.setProperty('tableValueEditor', True)
        return editor

    def helpEvent(self, event, view, option, index):
        if event.type() != QEvent.Type.ToolTip or not index.isValid():
            return super().helpEvent(event, view, option, index)
        widget = view.indexWidget(index)
        if widget is not None:
            if tooltip := widget.toolTip():
                QToolTip.showText(event.globalPos(), tooltip, view)
                return True
            return super().helpEvent(event, view, option, index)
        tooltip = index.data(Qt.ItemDataRole.ToolTipRole)
        can_edit = _can_edit_cell_text(view, index)
        if tooltip and not can_edit:
            return super().helpEvent(event, view, option, index)
        text = tooltip or index.data(Qt.ItemDataRole.DisplayRole) or ''
        lines = [escape(str(text)).replace('\n', '<br>')] if text else []
        if can_edit:
            lines.append(escape(translate_text('Double-click to edit.')))
        if not lines:
            return super().helpEvent(event, view, option, index)
        QToolTip.showText(event.globalPos(), '<qt>' + '<br>'.join(lines) + '</qt>', view)
        return True


class SelectionTableWidget(QTableWidget):
    cellMenuCreated = pyqtSignal(QMenu, QModelIndex)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._pending_read_only_tip: QPersistentModelIndex | None = None
        self._editable_cell_border_color = QColor()
        self.setAlternatingRowColors(True)
        self.setItemDelegate(TableCellDelegate(self))

    @pyqtProperty(QColor)
    def editableCellBorderColor(self) -> QColor:
        return self._editable_cell_border_color

    @editableCellBorderColor.setter
    def editableCellBorderColor(self, color: QColor) -> None:
        self._editable_cell_border_color = color

    def setItem(self, row: int, column: int, item: QTableWidgetItem | None, *, editable: bool = False) -> None:
        if item is not None and not editable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        super().setItem(row, column, item)

    def edit(self, index, trigger=QAbstractItemView.EditTrigger.AllEditTriggers, event=None):
        item = self.itemFromIndex(index)
        if item is None:
            return False
        if super().edit(index, trigger, event):
            return True
        triggers = QAbstractItemView.EditTrigger
        if not item.flags() & Qt.ItemFlag.ItemIsEditable and trigger in (
            triggers.DoubleClicked, triggers.EditKeyPressed, triggers.AnyKeyPressed, triggers.AllEditTriggers,
        ):
            if trigger == triggers.DoubleClicked and event is not None:
                # Qt dismisses visible tooltips on mouse release.
                self._pending_read_only_tip = QPersistentModelIndex(index)
            else:
                self._show_read_only_tip(index)
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pending_read_only_tip = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        pending = self._pending_read_only_tip
        self._pending_read_only_tip = None
        super().mouseReleaseEvent(event)
        if pending is not None and pending.isValid() and event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if pending == index and not index.flags() & Qt.ItemFlag.ItemIsEditable:
                self._show_read_only_tip(index)

    def _show_read_only_tip(self, index: QModelIndex) -> None:
        rect = self.visualRect(index)
        viewport = self.viewport()
        message = index.data(READ_ONLY_HINT_ROLE) or 'Read-only cell. You can copy its value.'
        QToolTip.showText(
            viewport.mapToGlobal(rect.center()), translate_text(message),
            viewport, rect, msecShowTime=5000,
        )

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        index = self.currentIndex() if event.reason() == QContextMenuEvent.Reason.Keyboard else self.indexAt(event.pos())
        item = self.itemFromIndex(index)
        if item is None or self.indexWidget(index) is not None:
            super().contextMenuEvent(event)
            return
        menu = QMenu(self)
        text = item.text()
        copy_action = menu.addAction(translate_text('Copy'))
        self.cellMenuCreated.emit(menu, index)
        if menu.exec(event.globalPos()) == copy_action:
            QApplication.clipboard().setText(text)
        menu.deleteLater()
        event.accept()

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
        return True
