"""A font-aware caption for Qt windows whose desktop frame has no per-window font."""

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QSizePolicy, QStyle, QToolButton, QWidget

from src.core.i18n import translate_text


def prepare_window_caption(window: QWidget) -> None:
    flags = window.windowFlags()
    if (window.windowType() not in (Qt.WindowType.Window, Qt.WindowType.Dialog)
            or not flags & Qt.WindowType.WindowTitleHint or flags & Qt.WindowType.FramelessWindowHint):
        return
    window._app_caption_enabled = True
    if QApplication.platformName() != "cocoa":
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        window.setMouseTracking(True)


def refresh_window_caption(window: QWidget) -> None:
    if not getattr(window, "_app_caption_enabled", False):
        return
    if QApplication.platformName() == "cocoa":
        from .macos_appearance import set_window_title_font

        if window.windowHandle() is not None:
            set_window_title_font(window)
        return
    layout = QWidget.layout(window)
    if layout is None:
        return
    bar = layout.menuBar()
    if bar is None:
        bar = _Caption(window)
        layout.setMenuBar(bar)
    if isinstance(bar, _Caption):
        bar.refresh()


class _Caption(QWidget):
    def __init__(self, window: QWidget):
        super().__init__(window)
        self._owner = window
        self._drag_start = None
        self.setMouseTracking(True)
        self.setObjectName("applicationCaption")
        self._label = QLabel(window.windowTitle(), self)
        self._label.setObjectName("captionTitle")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        window.windowTitleChanged.connect(self._label.setText)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 3, 2)
        layout.setSpacing(2)
        layout.addWidget(self._label, 1)
        self._buttons = {}
        for hint, title, callback in (
                (Qt.WindowType.WindowMinimizeButtonHint, "Minimize", window.showMinimized),
                (Qt.WindowType.WindowMaximizeButtonHint, "Maximize", self._toggle_maximized),
                (Qt.WindowType.WindowCloseButtonHint, "Close", window.close)):
            if window.windowFlags() & hint:
                button = QToolButton(self)
                button.setAutoRaise(True)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.clicked.connect(callback)
                layout.addWidget(button)
                self._buttons[title] = button
        window.installEventFilter(self)

    def refresh(self) -> None:
        self.setVisible(not self._owner.isFullScreen())
        self._label.setFont(self._owner.font())
        for name, button in self._buttons.items():
            restoring = name == "Maximize" and self._owner.isMaximized()
            title = translate_text("Restore window" if restoring else name)
            icon = {"Minimize": QStyle.StandardPixmap.SP_TitleBarMinButton,
                    "Maximize": QStyle.StandardPixmap.SP_TitleBarNormalButton if restoring else QStyle.StandardPixmap.SP_TitleBarMaxButton,
                    "Close": QStyle.StandardPixmap.SP_TitleBarCloseButton}[name]
            button.setIcon(self.style().standardIcon(icon))
            button.setToolTip(title)
            button.setAccessibleName(title)

    def _toggle_maximized(self) -> None:
        if self._owner.isMaximized():
            self._owner.showNormal()
        else:
            self._owner.showMaximized()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_start
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._drag_start = None
                handle = self._owner.windowHandle()
                if handle is not None and handle.startSystemMove():
                    event.accept()
                    return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and "Maximize" in self._buttons:
            self._toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        for name, button in self._buttons.items():
            menu.addAction(button.icon(), button.toolTip(), button.click)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.WindowStateChange, QEvent.Type.LanguageChange):
            self.refresh()
        return False


_RESIZE_CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.TopEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.BottomEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.TopEdge | Qt.Edge.RightEdge: Qt.CursorShape.SizeBDiagCursor,
    Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: Qt.CursorShape.SizeBDiagCursor,
}


def caption_resize_event(widget: QWidget, event) -> bool:
    window = widget.window()
    if (not getattr(window, "_app_caption_enabled", False) or not window.windowFlags() & Qt.WindowType.FramelessWindowHint
            or window.isMaximized() or window.isFullScreen() or window.windowHandle() is None):
        return False
    pos = window.mapFromGlobal(event.globalPosition().toPoint())
    if not window.rect().contains(pos):
        return False
    edges = Qt.Edge(0)
    if window.minimumWidth() < window.maximumWidth():
        if pos.x() < 5:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= window.width() - 5:
            edges |= Qt.Edge.RightEdge
    if window.minimumHeight() < window.maximumHeight():
        if pos.y() < 5:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= window.height() - 5:
            edges |= Qt.Edge.BottomEdge
    if event.type() == QEvent.Type.MouseButtonPress:
        return bool(edges and window.windowHandle().startSystemResize(edges))
    # Set the cursor on the frame only. Editors and other children own their cursors.
    if widget is window or isinstance(widget, _Caption):
        if edges:
            widget.setCursor(_RESIZE_CURSORS[edges])
        elif widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor):
            widget.unsetCursor()
    return False
