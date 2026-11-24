"""Draw a theme-aware window frame and delegate window operations to the compositor."""

from PyQt6.QtCore import QEvent, QLineF, QMargins, QObject, QPoint, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap, QRegion
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QWidget

from src.core.i18n import translate_text


_EDGE = Qt.Edge
_RESIZE_CURSORS = {
    _EDGE.LeftEdge: Qt.CursorShape.SizeHorCursor,
    _EDGE.RightEdge: Qt.CursorShape.SizeHorCursor,
    _EDGE.TopEdge: Qt.CursorShape.SizeVerCursor,
    _EDGE.BottomEdge: Qt.CursorShape.SizeVerCursor,
    _EDGE.TopEdge | _EDGE.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
    _EDGE.BottomEdge | _EDGE.RightEdge: Qt.CursorShape.SizeFDiagCursor,
    _EDGE.TopEdge | _EDGE.RightEdge: Qt.CursorShape.SizeBDiagCursor,
    _EDGE.BottomEdge | _EDGE.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
}


def _control_icon(symbol: str, color: QColor) -> QIcon:
    pixmap = QPixmap(26, 26)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.25))
    if symbol == "minimize":
        painter.drawLine(QLineF(2.5, 9.5, 10.5, 9.5))
    elif symbol == "maximize":
        painter.drawRect(QRectF(2.5, 2.5, 8, 8))
    elif symbol == "restore":
        painter.drawRect(QRectF(2.5, 4.5, 6, 6))
        painter.drawLines([QLineF(4.5, 2.5, 10.5, 2.5), QLineF(10.5, 2.5, 10.5, 8.5)])
    else:
        painter.drawLines([QLineF(3, 3, 10, 10), QLineF(10, 3, 3, 10)])
    painter.end()
    return QIcon(pixmap)


class _WindowTitle(QLabel):
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class ClientWindowFrame(QWidget):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._original_margins = window.contentsMargins()
        self._drag_origin = None
        self._dark = None
        self.setObjectName("clientWindowFrame")
        self.setMouseTracking(True)

        self._row = QHBoxLayout(self)
        self._row.setSpacing(0)
        self._row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._title = _WindowTitle(window.windowTitle(), self)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._row.addWidget(self._title, 1)
        self._minimize = QToolButton(self)
        self._maximize = QToolButton(self)
        self._close = QToolButton(self)
        self._buttons = (self._minimize, self._maximize, self._close)
        for button, handler in zip(self._buttons, (window.showMinimized, self._toggle_maximized, window.close)):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setIconSize(QSize(13, 13))
            button.clicked.connect(handler)
            self._row.addWidget(button)

        window.windowTitleChanged.connect(self._title.setText)
        self.set_dark(False)
        self._fit_window()
        window.installEventFilter(self)

    def set_dark(self, dark: bool) -> None:
        if self._dark == dark:
            return
        self._dark = dark
        title, text, edge, hover = ("#2b2e33", "#f1f3f5", "#444950", "#454a52") if dark else (
            "#edf0f3", "#24292f", "#c8cfd6", "#dce2e7"
        )
        self._surface = QColor(title)
        self._border = QColor(edge)
        self._foreground = QColor(text)
        self.setStyleSheet(
            f"QWidget#clientWindowFrame QLabel{{background:transparent;color:{text};font-weight:600;}}"
            f"QWidget#clientWindowFrame QToolButton{{background:transparent;color:{text};border:0;padding:0;}}"
            f"QWidget#clientWindowFrame QToolButton:hover{{background:{hover};}}"
        )
        self._update_buttons()
        self.update()

    def _update_buttons(self) -> None:
        flags = self._window.windowFlags()
        maximized = self._window.isMaximized()
        window_type = Qt.WindowType
        for button, hint, symbol, name in (
            (self._minimize, window_type.WindowMinimizeButtonHint, "minimize", "Minimize window"),
            (self._maximize, window_type.WindowMaximizeButtonHint, "restore" if maximized else "maximize",
             "Restore window" if maximized else "Maximize window"),
            (self._close, window_type.WindowCloseButtonHint, "close", "Close"),
        ):
            label = translate_text(name)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setIcon(_control_icon(symbol, self._foreground))
            button.setVisible(bool(flags & hint))

    def _fit_window(self) -> None:
        window = self._window
        fullscreen = window.isFullScreen()
        self._inset = 0 if window.isMaximized() or fullscreen else 5
        inset = self._inset
        row_height = max(29, self._title.fontMetrics().height() + 9)
        self._title_height = 0 if fullscreen else row_height + inset
        self._title.setFixedHeight(row_height)
        for button in self._buttons:
            button.setFixedSize(row_height + 3, row_height)
        self._row.setContentsMargins(inset + 8, inset, inset, 0)
        window.setContentsMargins(self._original_margins + QMargins(inset, self._title_height, inset, inset))
        self.setGeometry(window.rect())
        # Leave the client area available to the window's existing widgets.
        client = self.rect().adjusted(inset, self._title_height, -inset, -inset)
        self.setMask(QRegion(self.rect()).subtracted(QRegion(client)))
        self.setVisible(not fullscreen)
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.FontChange, QEvent.Type.WindowStateChange):
            self._fit_window()
        if kind in (QEvent.Type.Show, QEvent.Type.WindowStateChange, QEvent.Type.LanguageChange, QEvent.Type.StyleChange):
            self._update_buttons()
        return False

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._surface)
        painter.setPen(self._border)
        if self._inset:
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.drawLine(0, self._title_height - 1, self.width(), self._title_height - 1)

    def _edges_at(self, point: QPoint) -> Qt.Edge:
        edges = _EDGE(0)
        if self._inset and self._window.minimumWidth() < self._window.maximumWidth():
            if point.x() < self._inset:
                edges |= _EDGE.LeftEdge
            elif point.x() >= self.width() - self._inset:
                edges |= _EDGE.RightEdge
        if self._inset and self._window.minimumHeight() < self._window.maximumHeight():
            if point.y() < self._inset:
                edges |= _EDGE.TopEdge
            elif point.y() >= self.height() - self._inset:
                edges |= _EDGE.BottomEdge
        return edges

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self._window.windowHandle().startSystemResize(edges)
            elif event.position().y() < self._title_height:
                self._drag_origin = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        edges = self._edges_at(event.position().toPoint())
        self.setCursor(_RESIZE_CURSORS.get(edges, Qt.CursorShape.ArrowCursor))
        if (self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.globalPosition().toPoint() - self._drag_origin).manhattanLength() >= QApplication.startDragDistance()):
            self._drag_origin = None
            self._window.windowHandle().startSystemMove()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_origin = None

    def mouseDoubleClickEvent(self, event) -> None:
        self._drag_origin = None
        if (event.button() == Qt.MouseButton.LeftButton and self._maximize.isVisible()
                and not self._edges_at(event.position().toPoint())):
            self._toggle_maximized()

    def _toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        for button in self._buttons:
            if button.isVisible():
                menu.addAction(button.icon(), button.toolTip(), button.click)
        if not menu.isEmpty():
            menu.exec(event.globalPos())
        menu.deleteLater()
