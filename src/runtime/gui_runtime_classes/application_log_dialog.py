"""Modeless viewer for the application's console output."""

import re
import sys
from array import array
from bisect import bisect_left

from PyQt6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor, QFont, QGuiApplication, QIcon, QKeySequence, QPaintEvent, QPainter, QShortcut, QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)

from src.core.app_config import UiPreferences, application_support_directory
from src.core.i18n import translate_text
from src.runtime.application_log import ApplicationLog

from .widget_animations import AnimatedDialog
from .window_background import WindowBackground, background_panel_colors
from .x11_window import apply_x11_title_bar_theme

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _dwm_set_window_attribute = ctypes.WinDLL("dwmapi").DwmSetWindowAttribute
    _dwm_set_window_attribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    _dwm_set_window_attribute.restype = ctypes.c_long
    _DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    _DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19


_CONTROL = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[^\[\]\x1b])|[\r\b]")
_PARTIAL_CONTROL = re.compile(r"\x1b(?:\[[0-?]*[ -/]*|\][^\x07\x1b]*\x1b?)?\Z")
_SUPPLEMENTARY_CHARACTER = re.compile(r"[\U00010000-\U0010ffff]")
_ANSI_COLORS = (
    "#171717", "#bb3232", "#278344", "#977218", "#3261cb", "#a042a6", "#218282", "#bcbcbc",
    "#737373", "#ff6060", "#56bd65", "#d6a338", "#6892ff", "#d86bd3", "#44b7bc", "#f3f3f3",
)
_SEARCH_BUTTON_STYLE = (
    "QToolButton{background:transparent;border:1px solid transparent;border-radius:4px;padding:1px 3px;}"
    "QToolButton:hover,QToolButton:focus{border-color:palette(highlight);}"
    "QToolButton:checked{background:palette(highlight);color:palette(highlighted-text);}"
)
_SEARCH_BUTTON_INSET = 2


def _indexed_color(index: int) -> QColor:
    if 0 <= index < 16:
        return QColor(_ANSI_COLORS[index])
    if 16 <= index < 232:
        red, rest = divmod(index - 16, 36)
        green, blue = divmod(rest, 6)
        levels = (0, 95, 135, 175, 215, 255)
        return QColor(levels[red], levels[green], levels[blue])
    if 232 <= index < 256:
        level = 8 + (index - 232) * 10
        return QColor(level, level, level)
    return QColor()


class _MatchCountLabel(QLabel):
    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance("00000/00000") + 6, metrics.height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event: QPaintEvent) -> None:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        rect = self.contentsRect()
        if text_width <= rect.width():
            super().paintEvent(event)
            return
        # Fit unusually large counts without taking width from the search field.
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.translate(rect.x(), rect.y())
        painter.scale(rect.width() / text_width, 1)
        painter.drawText(QRect(0, 0, text_width, rect.height()), self.alignment(), self.text())
        painter.end()


class ApplicationLogDialog(AnimatedDialog):
    def __init__(self, application_log: ApplicationLog) -> None:
        # An owned dialog stays above its owner in the window manager.
        super().__init__()
        self._window_background = WindowBackground()
        self._background_mode = "light"
        self._dark_title_bar: bool | None = None
        self._title_bar_timer = QTimer(self)
        self._title_bar_timer.setSingleShot(True)
        self._title_bar_timer.timeout.connect(self._apply_dark_title_bar)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        icon_path = application_support_directory() / "resource" / "log-window.svg"
        self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(820, 480)
        self._toolbar = QWidget(self)
        self._toolbar.setObjectName("logToolbar")
        self.search_input = QLineEdit(self._toolbar)
        self.search_input.setMinimumWidth(100)
        self.ignore_case = QToolButton(self.search_input)
        self.ignore_case.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.ignore_case.setText(translate_text("Cc"))
        self.ignore_case.setCheckable(True)
        self.ignore_case.setChecked(True)
        self.previous_button = QToolButton(self._toolbar)
        self.previous_button.setArrowType(Qt.ArrowType.UpArrow)
        self.next_button = QToolButton(self._toolbar)
        self.next_button.setArrowType(Qt.ArrowType.DownArrow)
        for button in (self.ignore_case, self.previous_button, self.next_button):
            button.setStyleSheet(_SEARCH_BUTTON_STYLE)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        case_layout = QHBoxLayout(self.search_input)
        inset = _SEARCH_BUTTON_INSET
        case_layout.setContentsMargins(0, inset, inset, inset)
        case_layout.addStretch()
        case_layout.addWidget(self.ignore_case, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.ignore_case.installEventFilter(self)
        self.search_input.setTextMargins(0, 0, self.ignore_case.sizeHint().width() + 2 * inset, 0)

        self.search_status = _MatchCountLabel(self._toolbar)
        self.search_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.search_status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.wrap_lines = QCheckBox(self._toolbar)
        self.auto_scroll = QCheckBox(self._toolbar)
        self.auto_scroll.setChecked(True)
        toolbar = QHBoxLayout(self._toolbar)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(self.search_input, 1)
        toolbar.addWidget(self.search_status)
        toolbar.addWidget(self.previous_button)
        toolbar.addWidget(self.next_button)
        toolbar.addWidget(self.wrap_lines)
        toolbar.addWidget(self.auto_scroll)
        self.output = QPlainTextEdit(self)
        self.output.setObjectName("applicationLogOutput")
        self.output.setReadOnly(True)
        self.set_line_limit(UiPreferences.log_line_limit)
        layout = QVBoxLayout(self)
        layout.addWidget(self._toolbar)
        layout.addWidget(self.output)
        self._search_offsets: tuple[array, list[int]] | None = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._find)
        self.output.textChanged.connect(self._schedule_search_refresh)
        self.search_input.textChanged.connect(self._restart_search)
        self.search_input.returnPressed.connect(lambda: self._find(1))
        self.ignore_case.toggled.connect(self._restart_search)
        self.previous_button.clicked.connect(lambda _=False: self._find(-1))
        self.next_button.clicked.connect(lambda _=False: self._find(1))
        self.wrap_lines.toggled.connect(self._set_line_wrap)
        self.wrap_lines.setChecked(True)
        self.auto_scroll.toggled.connect(self._scroll_to_end)
        QShortcut(QKeySequence.StandardKey.Find, self).activated.connect(self.search_input.setFocus)
        self.retranslate()
        self._application_log = application_log
        self._position = 0
        self._cursor = QTextCursor(self.output.document())
        self._format = QTextCharFormat()
        self._partial_control = ""
        self._prefix_length = 0
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._refresh)

    def set_dark_title_bar(self, dark: bool) -> None:
        if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
            return
        self._dark_title_bar = dark
        self._title_bar_timer.start(0)

    def _apply_dark_title_bar(self) -> None:
        dark = getattr(self, "_dark_title_bar", None)
        hwnd = int(self.effectiveWinId() or 0)
        if dark is None or not hwnd:
            return
        value = wintypes.BOOL(dark)
        for attribute in (_DWMWA_USE_IMMERSIVE_DARK_MODE, _DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1):
            if _dwm_set_window_attribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) >= 0:
                break

    def event(self, event: QEvent) -> bool:
        handled = super().event(event)
        if event.type() == QEvent.Type.WinIdChange:
            self._apply_dark_title_bar()
        elif event.type() == QEvent.Type.ApplicationPaletteChange:
            if getattr(self, "_dark_title_bar", None) is not None:
                # Apply the dialog's choice after Qt updates the application-wide palette.
                self._title_bar_timer.start(0)
        return handled

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.ignore_case and event.type() == QEvent.Type.Resize:
            self.search_input.setTextMargins(0, 0, event.size().width() + 2 * _SEARCH_BUTTON_INSET, 0)
        return super().eventFilter(watched, event)

    def retranslate(self) -> None:
        self.setWindowTitle(translate_text("View Log"))
        self.search_input.setPlaceholderText(translate_text("Find in log"))
        for button, label in (
            (self.ignore_case, "Ignore case"),
            (self.previous_button, "Previous match"),
            (self.next_button, "Next match"),
        ):
            text = translate_text(label)
            button.setToolTip(text)
            button.setAccessibleName(text)
        self.wrap_lines.setText(translate_text("Wrap lines"))
        self.auto_scroll.setText(translate_text("Auto-scroll to end"))
        if self.search_status.text() == "0/0":
            self.search_status.setToolTip(translate_text("No matches"))

    def set_line_limit(self, limit: int) -> None:
        self.output.setMaximumBlockCount(limit)

    def set_theme(self, mode: str, stylesheet: str) -> None:
        self._background_mode = mode
        if stylesheet != self.styleSheet():
            self.setStyleSheet(stylesheet)
        self._refresh_background_panels()
        dark = mode == "dark"
        self.set_dark_title_bar(dark)
        apply_x11_title_bar_theme(self, dark)

    def set_background_image(self, path: str, opacity: int, blur: int = 0) -> None:
        self._window_background.set_image(path, opacity, blur)
        self._refresh_background_panels()
        self.update()

    def _refresh_background_panels(self) -> None:
        toolbar_style = output_style = ''
        active = self._window_background.active
        if active:
            toolbar, panel = background_panel_colors(self._background_mode == "dark")
            toolbar_style = (
                f'QWidget#logToolbar{{background:{toolbar};border-radius:6px;}}'
                'QLabel,QCheckBox{background:transparent;}'
            )
            output_style = (
                f'QPlainTextEdit{{background:{panel};}}'
                'QPlainTextEdit > .QWidget{background:transparent;}'
            )
        inset = 4 if active else 0
        self._toolbar.layout().setContentsMargins(inset, inset, inset, inset)
        for widget, stylesheet in ((self._toolbar, toolbar_style), (self.output, output_style)):
            if stylesheet != widget.styleSheet():
                widget.setStyleSheet(stylesheet)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        self._window_background.paint(self)

    def _set_line_wrap(self, enabled: bool) -> None:
        modes = QPlainTextEdit.LineWrapMode
        self.output.setLineWrapMode(modes.WidgetWidth if enabled else modes.NoWrap)
        self._scroll_to_end(self.auto_scroll.isChecked())

    def _restart_search(self) -> None:
        self._search_offsets = None
        self._find(0)

    def _schedule_search_refresh(self) -> None:
        self._search_offsets = None
        if self.search_input.text() and not self._search_timer.isActive():
            self._search_timer.start()

    def _find(self, step: int | None = None) -> None:
        self._search_timer.stop()
        query = self.search_input.text()
        if query and self._search_offsets is None:
            text = self.output.toPlainText()
            flags = re.IGNORECASE if self.ignore_case.isChecked() else 0
            pattern = re.compile(re.escape(query), flags)
            starts = array("I", (match.start() for match in pattern.finditer(text)))
            supplementary = []
            if starts and not text.isascii():
                supplementary = [match.start() for match in _SUPPLEMENTARY_CHARACTER.finditer(text)]
            self._search_offsets = starts, supplementary

        starts, supplementary = self._search_offsets or ((), ())
        cursor = self.output.textCursor()
        self.search_status.setToolTip(translate_text("No matches") if query and not starts else "")
        if not starts:
            self.search_status.setText("0/0" if query else "")
            if step == 0 and cursor.hasSelection():
                cursor.clearSelection()
                self.output.setTextCursor(cursor)
            return

        # QTextCursor counts UTF-16 units while Python match offsets count code points.
        def qt_offset(position: int) -> int:
            return position + bisect_left(supplementary, position)

        if step is None:
            start = cursor.selectionStart()
            index = bisect_left(starts, start, key=qt_offset)
            is_match = (
                index < len(starts)
                and qt_offset(starts[index]) == start
                and qt_offset(starts[index] + len(query)) == cursor.selectionEnd()
            )
            self.search_status.setText(f"{index + 1 if is_match else 0}/{len(starts)}")
            return

        index = 0
        if step < 0:
            index = (bisect_left(starts, cursor.selectionStart(), key=qt_offset) - 1) % len(starts)
        elif step > 0:
            index = bisect_left(starts, cursor.selectionEnd(), key=qt_offset) % len(starts)
        start = starts[index]
        cursor.setPosition(qt_offset(start))
        cursor.setPosition(qt_offset(start + len(query)), QTextCursor.MoveMode.KeepAnchor)
        cursor.setKeepPositionOnInsert(True)
        self.auto_scroll.setChecked(False)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()
        self.search_status.setText(f"{index + 1}/{len(starts)}")

    def _scroll_to_end(self, enabled: bool) -> None:
        if enabled:
            scrollbar = self.output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _refresh(self) -> None:
        self._position, truncated, fragments = self._application_log.read_since(self._position)
        if truncated:
            self.output.clear()
            self._cursor = QTextCursor(self.output.document())
            self._format = QTextCharFormat()
            self._partial_control = ""
            self._prefix_length = 0
        if not fragments:
            return
        scrollbar = self.output.verticalScrollBar()
        previous_scroll = scrollbar.value()
        self._cursor.beginEditBlock()
        try:
            for part in fragments:
                if part.starts_line or not self._prefix_length:
                    if self._prefix_length:
                        self._cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                        self._cursor.insertBlock()
                    self._partial_control = ""
                    prefix = f"[{part.timestamp}] "
                    self._cursor.insertText(prefix, QTextCharFormat())
                    self._prefix_length = len(prefix)
                self._render(part.text.removesuffix("\n"))
        finally:
            self._cursor.endEditBlock()
        if self.auto_scroll.isChecked():
            self._scroll_to_end(True)
        elif not truncated:
            scrollbar.setValue(previous_scroll)

    def _render(self, text: str) -> None:
        data = self._partial_control + text
        # Output can end midway through an escape sequence at any pipe read boundary.
        partial = _PARTIAL_CONTROL.search(data, max(0, len(data) - 4096))
        self._partial_control = partial.group() if partial else ""
        if partial:
            data = data[:partial.start()]
        start = 0
        move = QTextCursor.MoveOperation
        for match in _CONTROL.finditer(data):
            self._overwrite(data[start:match.start()])
            token = match.group()
            if token == "\r":
                self._cursor.setPosition(self._cursor.block().position() + self._prefix_length)
            elif token == "\b" and self._cursor.positionInBlock() > self._prefix_length:
                self._cursor.movePosition(move.PreviousCharacter)
            elif token.startswith("\x1b["):
                parameters, command = token[2:-1], token[-1]
                if command == "m":
                    self._set_format(parameters)
                elif command == "K":
                    if parameters == "2":
                        self._cursor.setPosition(self._cursor.block().position() + self._prefix_length)
                    if parameters in ("", "0", "2"):
                        self._cursor.movePosition(move.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                        self._cursor.removeSelectedText()
            start = match.end()
        self._overwrite(data[start:])

    def _overwrite(self, text: str) -> None:
        if text:
            self._cursor.movePosition(
                QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor, len(text),
            )
            self._cursor.insertText(text, self._format)

    def _set_format(self, parameters: str) -> None:
        if len(parameters) > 128 or re.fullmatch(r"[0-9;]*", parameters) is None:
            return
        codes = iter(int(part or "0") for part in parameters.split(";"))
        for code in codes:
            if code == 0:
                self._format = QTextCharFormat()
            elif code in (1, 22):
                weight = QFont.Weight.Bold if code == 1 else QFont.Weight.Normal
                self._format.setFontWeight(weight.value)
            elif code == 39:
                self._format.clearForeground()
            elif code == 49:
                self._format.clearBackground()
            elif 30 <= code <= 37 or 90 <= code <= 97:
                self._format.setForeground(_indexed_color(code - (30 if code < 90 else 82)))
            elif 40 <= code <= 47 or 100 <= code <= 107:
                self._format.setBackground(_indexed_color(code - (40 if code < 100 else 92)))
            elif 310 <= code <= 315:
                # Older Windows FFmpeg builds prefix bright Win32 color indices with 3.
                windows_index = code - 300
                ansi_index = (windows_index & 0b1010) | ((windows_index & 4) >> 2) | ((windows_index & 1) << 2)
                self._format.setForeground(_indexed_color(ansi_index))
            elif code in (38, 48):
                mode = next(codes, 0)
                color = QColor()
                if mode == 5:
                    color = _indexed_color(next(codes, -1))
                elif mode == 2:
                    rgb = [next(codes, -1) for _ in range(3)]
                    if all(0 <= value <= 255 for value in rgb):
                        color = QColor(*rgb)
                if color.isValid():
                    if code == 38:
                        self._format.setForeground(color)
                    else:
                        self._format.setBackground(color)
