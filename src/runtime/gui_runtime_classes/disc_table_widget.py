"""Disc selection and row moves that retain embedded playlist editors."""

import os
from html import escape

from PyQt6.QtCore import QEvent, QPersistentModelIndex, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QAbstractItemView, QLabel, QPlainTextEdit, QTableWidgetItem, QToolTip, QWidget,
)

from src.core.i18n import translate_text
from .custom_table_widget import CustomTableWidget, TableCellDelegate


class _DiscNameDelegate(TableCellDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = os.path.basename(option.text) or option.text


class DiscCommandEdit(QPlainTextEdit):
    def __init__(self, command: str, label: str, parent: QWidget):
        super().__init__(command, parent)
        self.setObjectName('discCommandEdit')
        self.setAccessibleName(label)
        tooltip = 'Click to edit the mux command.'
        self.setProperty('toolTipSource', tooltip)
        self.setToolTip(translate_text(tooltip))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._generated_command = command

    def update_generated_command(self, command: str, *, reset: bool = False) -> None:
        current = self.toPlainText()
        if reset or not current.strip() or current == self._generated_command:
            self._generated_command = command
            if command != current:
                self.setPlainText(command)


class DiscTableWidget(CustomTableWidget):
    discsChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, self._disc_moved)
        self._checked_paths: dict[str, bool] = {}
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setItemDelegateForColumn(0, _DiscNameDelegate(self))
        self._header_press_position: QPoint | None = None
        self._header_press_row = -1
        self._dragged_disc = QPersistentModelIndex()
        self._row_drag_preview: QLabel | None = None
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        header = self.verticalHeader()
        header.sectionPressed.connect(self._on_disc_header_pressed)
        self._disc_header_viewport = header.viewport()
        self._disc_header_viewport.installEventFilter(self)
        self.horizontalHeader().setSectionsClickable(False)
        self.itemChanged.connect(self._disc_checked)

    def currentChanged(self, current, previous):
        cell = self.indexWidget(current)
        if (
            self.hasAutoScroll() and cell is not None and cell.hasFocus()
            and self.viewport().rect().intersects(self.visualRect(current))
        ):
            # An embedded control can take focus while its row is only partly visible.
            self.setAutoScroll(False)
            try:
                super().currentChanged(current, previous)
            finally:
                self.setAutoScroll(True)
            return
        super().currentChanged(current, previous)

    def _on_disc_header_pressed(self, row: int) -> None:
        # Qt emits sectionPressed on the row body and handles its resize grip separately.
        self._header_press_row = row if self.item(row, 0) is not None else -1

    def _filter_disc_header_event(self, event) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonPress:
            self._header_press_row = -1
            self._header_press_position = None
            if event.button() == Qt.MouseButton.LeftButton:
                self._header_press_position = event.position().toPoint()
        elif event_type == QEvent.Type.MouseButtonRelease:
            self._header_press_position = None
        elif event_type == QEvent.Type.MouseMove:
            origin = self._header_press_position
            if (
                origin is not None
                and self._header_press_row >= 0
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - origin).manhattanLength() >= QApplication.startDragDistance()
            ):
                self._header_press_position = None
                self._start_row_drag(self._header_press_row)
                return True
        return False

    def eventFilter(self, watched, event):
        preview = getattr(self, '_row_drag_preview', None)
        if preview is not None and self._filter_row_drag(preview, watched, event):
            return True
        if watched is getattr(self, '_disc_header_viewport', None) and self._filter_disc_header_event(event):
            return True
        return super().eventFilter(watched, event)

    def _start_row_drag(self, row: int) -> None:
        if not 0 <= row < self.rowCount() or not QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            return

        # This reorder stays in the table. Native XWayland drags can show a
        # compositor rejection cursor even when Qt accepts the move.
        pixmap = self._disc_drag_preview(row)
        preview = QLabel(self.window())
        preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        preview.setPixmap(pixmap)
        preview.resize(pixmap.deviceIndependentSize().toSize())

        self._dragged_disc = QPersistentModelIndex(self.model().index(row, 0))
        self._row_drag_preview = preview
        # Qt's implicit mouse grab continues sending the drag to the pressed widget.
        QApplication.instance().installEventFilter(self)
        QApplication.setOverrideCursor(Qt.CursorShape.ForbiddenCursor)
        self._update_row_drag(preview, QCursor.pos())
        preview.show()
        preview.raise_()

    def _row_drop_target(self, position: QPoint) -> int | None:
        viewport = self.viewport()
        header = self._disc_header_viewport
        window = self.window()
        hovered = window.childAt(window.mapFromGlobal(position))
        if hovered is None or not (
            hovered in (viewport, header) or viewport.isAncestorOf(hovered) or header.isAncestorOf(hovered)
        ):
            return None
        source = self._dragged_disc.row()
        target = self._insertion_row_at(viewport.mapFromGlobal(position).y())
        return target if source >= 0 and target not in (source, source + 1) else None

    def _update_row_drag(self, preview: QLabel, position: QPoint) -> None:
        preview.move(preview.parentWidget().mapFromGlobal(position))
        target = self._row_drop_target(position)
        if target is None:
            self._drop_indicator.hide()
            QApplication.changeOverrideCursor(Qt.CursorShape.ForbiddenCursor)
        else:
            self._show_drop_indicator(target)
            QApplication.changeOverrideCursor(Qt.CursorShape.ClosedHandCursor)

    def _finish_row_drag(self, preview: QLabel) -> None:
        self._row_drag_preview = None
        self._dragged_disc = QPersistentModelIndex()
        QApplication.instance().removeEventFilter(self)
        QApplication.restoreOverrideCursor()
        self._drop_indicator.hide()
        preview.hide()
        preview.deleteLater()

    def _filter_row_drag(self, preview: QLabel, watched, event) -> bool:
        event_type = event.type()
        if event_type == QEvent.Type.MouseMove:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._update_row_drag(preview, event.globalPosition().toPoint())
                return True
            self._finish_row_drag(preview)
        elif event_type == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            source = self._dragged_disc.row()
            target = self._row_drop_target(event.globalPosition().toPoint())
            self._finish_row_drag(preview)
            if target is not None and self._move_row(source, target):
                self._disc_moved()
        elif event_type in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress) and event.key() == Qt.Key.Key_Escape:
            if event_type == QEvent.Type.KeyPress:
                self._finish_row_drag(preview)
            event.accept()
            return True
        elif (
            (event_type == QEvent.Type.Hide and watched is self)
            or (event_type == QEvent.Type.WindowDeactivate and watched is self.window())
        ):
            self._finish_row_drag(preview)
        return False

    def _disc_drag_preview(self, row: int) -> QPixmap:
        item = self.item(row, 0)
        path = item.text() if item is not None else ''
        name = os.path.basename(path) or path
        margin = 8
        pointer_gap = 12
        width = 240
        dpr = self.devicePixelRatioF()
        playlist = self.cellWidget(row, 2)
        thumbnail = QPixmap()
        if playlist is not None:
            crop = QRect(0, 0, min(playlist.width(), 480), min(playlist.height(), 160))
            thumbnail = playlist.grab(crop).scaled(
                round((width - 2 * margin) * dpr), round(76 * dpr),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
            thumbnail.setDevicePixelRatio(dpr)

        metrics = self.fontMetrics()
        title_height = metrics.height() + 2 * margin
        height = title_height
        if not thumbnail.isNull():
            height += round(thumbnail.deviceIndependentSize().height()) + margin
        pixmap = QPixmap(round((width + pointer_gap) * dpr), round((height + pointer_gap) * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        # The preview needs a solid surface even when the table's stylesheet is transparent.
        palette = QApplication.palette()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(palette.color(QPalette.ColorRole.Accent))
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(pointer_gap, pointer_gap, width - 1, height - 1, 5, 5)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.setFont(self.font())
        text_rect = QRect(pointer_gap + margin, pointer_gap, width - 2 * margin, title_height)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, metrics.elidedText(
            name, Qt.TextElideMode.ElideMiddle, text_rect.width(),
        ))
        if not thumbnail.isNull():
            painter.drawPixmap(QPoint(pointer_gap + margin, pointer_gap + title_height), thumbnail)
        painter.end()
        return pixmap

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
        row = self.currentRow()
        item = self.item(row, 0)
        path = item.text() if item is not None else ''
        self.discsChanged.emit()
        if path and self.isVisible():
            message = translate_text('Moved {disc} to row {row}.').format(
                disc=os.path.basename(path) or path, row=row + 1,
            )
            QToolTip.showText(QCursor.pos(), f'<qt>{escape(message)}</qt>', self, msecShowTime=3000)
