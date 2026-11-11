"""Target module for theme/language methods of `BluraySubtitleGUI`."""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QApplication, QLabel, QTabBar, QWidget, QPlainTextEdit, QLineEdit, QGroupBox, \
    QAbstractItemView, QComboBox, QTableWidget, QProxyStyle, QStyle

from src.core import APP_TITLE
import src.core.settings as core_settings
from src.core.i18n import translate_text
from src.runtime.gui_runtime_classes.disc_table_widget import DiscCommandEdit
from .gui_base import BluraySubtitleGuiBase


_SCROLL_CONTROL_GEOMETRY = (
    "QSlider{background:transparent;}"
    "QSlider::groove:horizontal{height:3px;border-radius:2px;}"
    "QSlider::sub-page:horizontal,QSlider::add-page:horizontal{border-radius:2px;}"
    "QSlider::handle:horizontal{width:14px;margin:-7px 0;border:1px solid transparent;border-radius:7px;}"
    "QScrollBar{background:transparent;border:none;}"
    "QScrollBar:horizontal{height:6px;margin:0 6px;}"
    "QScrollBar:vertical{width:6px;margin:6px 0;}"
    "QScrollBar::handle{border-radius:2px;}"
    "QScrollBar::handle:horizontal{min-width:24px;margin:1px 0;}"
    "QScrollBar::handle:vertical{min-height:24px;margin:0 1px;}"
    "QScrollBar::handle:hover,QScrollBar::handle:pressed{margin:0;}"
    "QScrollBar::add-line:horizontal{width:6px;subcontrol-position:right;subcontrol-origin:margin;}"
    "QScrollBar::sub-line:horizontal{width:6px;subcontrol-position:left;subcontrol-origin:margin;}"
    "QScrollBar::add-line:vertical{height:6px;subcontrol-position:bottom;subcontrol-origin:margin;}"
    "QScrollBar::sub-line:vertical{height:6px;subcontrol-position:top;subcontrol-origin:margin;}"
    "QScrollBar::add-line,QScrollBar::sub-line,QScrollBar::add-page,QScrollBar::sub-page{background:transparent;}"
)
_COLORFUL_ACCENT = '#7c3aed'
_COLORFUL_ACCENT_HOVER = '#6d28d9'
_COLORFUL_GRADIENT = 'qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #fff7d9,stop:0.55 #fffefa,stop:1 #f4f9ff)'
_COLORFUL_FUNCTION_COLORS = {1: '#0ea5e9', 2: '#14b8a6', 3: '#f59e0b', 4: '#ef4444', 5: '#8b5cf6'}
_COLORFUL_TABLE_COLORS = (
    (('table1', 'chapterTable', 'timingTable'),
     '#f1f7ff', '#e6f0ff', '#e4edfc', '#cdddf1', '#60a5fa', '#2563eb'),
    (('table2', 'trackTable'), '#f0fff6', '#e3f8eb', '#e4f3ea', '#cfe4d8', '#34d399', '#059669'),
    (('table3', 'attachmentTable'), '#fff8ee', '#fff0df', '#fceede', '#ead8c3', '#fb923c', '#ea580c'),
)


def _blend_color(background: str, foreground: QColor, amount: float) -> str:
    base = QColor(background)
    channels = [
        round(start + (end - start) * amount)
        for start, end in zip(base.getRgb()[:3], foreground.getRgb()[:3])
    ]
    return QColor(*channels).name()


def execution_button_stylesheet(palette: QPalette, mode: str, progress: float | None = None) -> str:
    dark = mode == 'dark'
    accent = palette.color(QPalette.ColorRole.Accent)
    surface = '#22252b' if dark else '#ffffff'
    text = '#e6e6e6' if dark else '#20262e'
    edge = _blend_color(surface, accent, 0.55 if dark else 0.32)
    focus = '#5b7fff' if dark else accent.name()
    button = 'QPushButton#primaryAction'
    if progress is None:
        background = _blend_color(surface, accent, 0.28 if dark else 0.16)
        hover = _blend_color(surface, accent, 0.36 if dark else 0.22)
        pressed = _blend_color(surface, accent, 0.44 if dark else 0.28)
        muted = '#a9acb6' if dark else '#666b75'
        states = (
            f'{button}:hover{{background:{hover};}}'
            f'{button}:pressed{{background:{pressed};}}'
            f'{button}:disabled{{background:{surface};color:{muted};}}'
        )
    else:
        filled = _blend_color(surface, accent, 0.54 if dark else 0.34)
        pending = _blend_color(surface, accent, 0.18 if dark else 0.09)
        if 0 < progress < 1:
            background = (
                f'qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {filled},stop:{progress:.3f} {filled},'
                f'stop:{min(1.0, progress + 0.001):.3f} {pending},stop:1 {pending})'
            )
        else:
            background = filled if progress >= 1 else pending
        states = f'{button}:disabled{{background:{background};color:{text};}}'
    return (
        f'{button}{{background:{background};color:{text};border:1px solid {edge};'
        'border-radius:7px;padding:7px 18px;font-weight:600;}'
        f'{button}:focus{{border-color:{focus};}}'
        f'{states}'
    )


def _table_stylesheet(selectors: tuple[str, ...], surface: str, alternate: str, header: str, edge: str,
                      selection: str, text: str) -> str:
    tables = ','.join(selectors)
    selected_items = ','.join(f'{selector}::item:selected' for selector in selectors)
    header_views = ','.join(f'{selector} QHeaderView' for selector in selectors)
    headers = ','.join(f'{selector} QHeaderView::section' for selector in selectors)
    corners = ','.join(f'{selector} QTableCornerButton::section' for selector in selectors)
    return (
        f'{tables}{{background:{surface};alternate-background-color:{alternate};gridline-color:{edge};'
        f'border:1px solid {edge};border-radius:5px;selection-background-color:{selection};selection-color:{text};}}'
        f'{selected_items}{{background:{selection};color:{text};}}'
        f'{header_views}{{background:{header};}}'
        f'{headers}{{background:{header};color:{text};border:0;border-bottom:1px solid {edge};padding:4px;}}'
        f'{corners}{{background:{header};border:0;}}'
    )


def _shared_stylesheet(palette: QPalette, mode: str) -> str:
    dark = mode == 'dark'
    colorful = mode == 'colorful'
    accent = palette.color(QPalette.ColorRole.Accent)
    text = {'dark': '#e6e6e6', 'colorful': '#1f2330'}.get(mode, palette.color(QPalette.ColorRole.WindowText).name())
    muted_text = '#a9acb6' if dark else '#666b75'
    surface, alternate, header, edge = (
        ('#222326', '#26282c', '#2c2e33', '#383b42') if dark else
        ('#ffffff', '#f7f8fa', '#f0f1f4', '#dce0e6')
    )
    table_colors = {
        'light': ('#f8fbfd', '#edf3f8', '#e2ebf4', '#bfcdda'),
        'dark': ('#292d34', '#2e333b', '#343b46', '#444d5b'),
    }.get(mode, (surface, alternate, header, edge))
    table_selection = _blend_color(table_colors[0], accent, 0.26 if dark else 0.14)
    hover = accent.lighter(112).name()
    tint = f'rgba({accent.red()},{accent.green()},{accent.blue()},{45 if dark else 22})'
    tab_hover = f'rgba({accent.red()},{accent.green()},{accent.blue()},{23 if dark else 12})'
    tab_selected = f'rgba({accent.red()},{accent.green()},{accent.blue()},{70 if dark else 39})'
    selection = _blend_color(surface, accent, 0.26 if dark else 0.14)
    focus = '#5b7fff' if dark else accent.name()
    title_color = _COLORFUL_ACCENT if colorful else text
    pane = 'rgba(255,255,255,145)' if colorful else surface
    editor = 'rgba(255,255,255,178)' if colorful else surface
    tinted_editor_background = '#2c3542' if dark else '#f4f8ff'
    tinted_editor_disabled_background = '#2a3039' if dark else '#f7f9fc'
    section_background = {'light': '#f1f6fc', 'dark': '#242830', 'colorful': 'rgba(246,250,255,205)'}[mode]
    tool_result_background = {'light': table_colors[1], 'dark': table_colors[0], 'colorful': '#f3efff'}[mode]
    checked, checked_hover, checked_edge = (
        ('#ffedd5', '#fed7aa', '#fb923c') if colorful else (accent.name(), hover, focus)
    )
    checked_disabled = _blend_color(surface, QColor(checked_edge), 0.35)
    section = 'QGroupBox[workspaceSection="true"]'
    encode_box = 'QGroupBox#encodeBox'
    command_edit = 'QPlainTextEdit#discCommandEdit'
    encode_params = f'{encode_box} > QPlainTextEdit'
    tab = 'QTabBar#functionTabbar::tab,QDialog QTabBar::tab'
    toggle = 'QTableWidget QToolButton[checkable="true"]'
    styles = [
        _table_stylesheet(('QTableWidget',), *table_colors, table_selection, text),
        f'{section},QDialog QGroupBox{{border:1px solid {edge};border-radius:8px;margin-top:9px;}}'
        f'{section}{{background:{section_background};}}'
        f'{section} > QLabel{{background:transparent;}}'
        f'{encode_box} > .QWidget,{encode_box} QLabel{{background:transparent;}}'
        f'{section}::title,QDialog QGroupBox::title{{subcontrol-origin:margin;left:10px;padding:0 5px;'
        f'color:{title_color};font-weight:600;}}'
        'QGroupBox[sourcePathBox="true"]{margin:0;border:0;background:transparent;}'
        f'QTableWidget QToolButton{{background:transparent;color:{text};'
        'border:1px solid transparent;border-radius:4px;padding:2px 5px;}'
        f'QTableWidget QToolButton:hover,QTableWidget QToolButton:focus{{background:{tint};border-color:{edge};}}'
        f'QTableWidget QToolButton:disabled{{background:transparent;color:{muted_text};}}'
        f'{toggle}{{background:{surface};border:1px solid {edge};margin:2px 3px;}}'
        f'{toggle}:hover,{toggle}:focus{{border-color:{focus};}}'
        f'{toggle}:checked{{background:{checked};border-color:{checked_edge};}}'
        f'{toggle}:checked:hover{{background:{checked_hover};}}'
        f'{toggle}:disabled{{background:{alternate};border-color:{edge};}}'
        f'{toggle}:checked:disabled{{background:{checked_disabled};}}'
        f'{command_edit},{encode_params},QDialog QPlainTextEdit{{color:{text};'
        f'border:1px solid {edge};border-radius:5px;padding:3px;}}'
        f'{command_edit},{encode_params}{{background:{tinted_editor_background};border-color:{table_colors[3]};}}'
        f'{command_edit}:disabled,{encode_params}:disabled'
        f'{{background:{tinted_editor_disabled_background};color:{muted_text};}}'
        f'QDialog QPlainTextEdit{{background:{editor};}}'
        f'QPlainTextEdit#externalToolsEditor{{background:{tinted_editor_background};}}'
        f'QPlainTextEdit#externalToolsDetectionView{{background:{tool_result_background};}}'
        f'{command_edit}:focus,{encode_params}:focus:!read-only,QDialog QPlainTextEdit:focus:!read-only'
        f'{{border-bottom-color:{focus};}}'
        f'QDialog QTabWidget::pane{{background:{pane};border:1px solid {edge};border-radius:6px;}}'
        'QDialog QScrollArea{background:transparent;border:0;}'
        f'{tab}{{background:transparent;color:{text};border:0;border-bottom:2px solid {edge};padding:7px 10px;}}'
        'QTabBar#functionTabbar::tab:hover:!selected,QDialog QTabBar::tab:hover:!selected'
        f'{{background:{tab_hover};}}'
        'QTabBar#functionTabbar::tab:selected,QDialog QTabBar::tab:selected'
        f'{{background:{tab_selected};border-bottom-color:{focus};}}'
        f'QDialog QPushButton{{background:{surface};color:{text};border:1px solid {edge};border-radius:6px;padding:5px 12px;}}'
        f'QDialog QPushButton:hover,QDialog QPushButton:pressed{{background:{selection};border-color:{focus};}}'
        f'QDialog QPushButton:default,QDialog QPushButton:focus{{border-color:{focus};}}'
        f'QDialog QPushButton:disabled{{background:{alternate};color:{muted_text};border-color:{edge};}}',
        execution_button_stylesheet(palette, mode),
    ]
    if colorful:
        for names, base, stripe, heading, border, scrollbar, scrollbar_hover in _COLORFUL_TABLE_COLORS:
            selectors = tuple(f'QTableWidget#{name}' for name in names)
            highlight = _blend_color(base, QColor(scrollbar_hover), 0.16)
            styles.append(_table_stylesheet(selectors, base, stripe, heading, border, highlight, text))
            handles = tuple(f'{selector} QScrollBar::handle' for selector in selectors)
            styles.append(f'{",".join(handles)}{{background:{scrollbar};}}')
            styles.append(f'{",".join(f"{handle}:hover" for handle in handles)}{{background:{scrollbar_hover};}}')
        playlist_colors = ('#fbfdff', '#edf5ff', '#d9e9fc', '#b9d0ed')
        playlist_selection = _blend_color(playlist_colors[0], QColor('#2563eb'), 0.16)
        styles.append(_table_stylesheet(('QTableWidget#playlistTable',), *playlist_colors, playlist_selection, text))
    elif dark:
        styles.append(f'{encode_box} QCheckBox,{encode_box} QRadioButton{{background:{section_background};}}')
    return ''.join(styles)


class _ThemeStyle(QProxyStyle):
    def __init__(self, base_style: str, mode: str):
        super().__init__(base_style)
        self._mode = mode

    def drawControl(self, element, option, painter, widget=None):
        super().drawControl(element, option, painter, widget)
        if self._mode != 'dark' or not option.state & QStyle.StateFlag.State_Enabled:
            return
        # The popup selection follows hover. Mark the combo box's current value.
        if element == QStyle.ControlElement.CE_MenuItem and isinstance(widget, QComboBox):
            current_item = option.checked
        elif element == QStyle.ControlElement.CE_ItemViewItem and isinstance(widget, QAbstractItemView):
            combo = widget.window().parentWidget()
            index = option.index
            current_item = isinstance(combo, QComboBox) and index.isValid() and index.row() == combo.currentIndex()
        else:
            return
        if current_item:
            inset = option.rect.height() // 5
            marker = option.rect.adjusted(1, inset, 0, -inset)
            marker.setWidth(2)
            painter.fillRect(marker, QColor('#5b7fff'))

    def drawPrimitive(self, element, option, painter, widget=None):
        themed_checkbox = (
            element == QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck and isinstance(widget, QTableWidget)
        ) or (
            element == QStyle.PrimitiveElement.PE_IndicatorCheckBox and self._mode == 'colorful'
        )
        if not themed_checkbox:
            super().drawPrimitive(element, option, painter, widget)
            return

        flags = QStyle.StateFlag
        enabled = bool(option.state & flags.State_Enabled)
        partial = bool(option.state & flags.State_NoChange)
        marked = partial or bool(option.state & flags.State_On)
        hovered = bool(option.state & flags.State_MouseOver)
        palette = QApplication.palette()
        accent = palette.color(QPalette.ColorRole.Accent)
        if hovered:
            accent = accent.darker(112)
        dark = self._mode == 'dark'
        if enabled:
            border = accent if marked or hovered else QColor('#757983' if dark else '#9399a4')
            background = accent if marked else palette.color(QPalette.ColorRole.Base)
            mark = palette.color(QPalette.ColorRole.HighlightedText)
        else:
            border = QColor('#555a64' if dark else '#b8bdc8')
            background = QColor('#34373e' if dark else '#e5e7ef')
            mark = QColor('#a6abba' if dark else '#626d88')

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(option.rect.topLeft())
        painter.scale(option.rect.width() / 16, option.rect.height() / 16)
        painter.setPen(border)
        painter.setBrush(background)
        painter.drawRoundedRect(QRectF(0.5, 0.5, 15, 15), 3, 3)
        if marked:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(mark, 1.8, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            if partial:
                painter.drawLine(4, 8, 12, 8)
            else:
                check = QPainterPath()
                check.moveTo(4, 8)
                check.lineTo(7, 11)
                check.lineTo(12, 5)
                painter.drawPath(check)
        painter.restore()


class ThemeI18nMixin(BluraySubtitleGuiBase):
    def _window_opacity_supported(self) -> bool:
        app = QApplication.instance()
        if not app:
            return False
        platform_name = (app.platformName() or '').lower()
        # Wayland backend does not support per-window opacity in Qt.
        return 'wayland' not in platform_name

    def _apply_window_opacity(self, window: QWidget | None = None):
        if not self._window_opacity_supported():
            return
        # QWidget stores opacity as a byte before the native window is created.
        opacity = round(self.opacity_slider.value() * 255 / 100) / 255
        try:
            (self if window is None else window).setWindowOpacity(opacity)
        except Exception:
            pass

    def t(self, text: str) -> str:
        return translate_text(str(text), getattr(self, '_language_code', None) or core_settings.CURRENT_UI_LANGUAGE)

    def _refresh_language_combo(self):
        if not hasattr(self, 'language_label') or not hasattr(self, 'language_combo'):
            return
        current_code = self.language_combo.currentData() or 'en'
        self.language_label.setText(self.t('Language'))
        self.language_combo.blockSignals(True)
        self.language_combo.setItemText(0, 'English')
        self.language_combo.setItemText(1, translate_text('Simplified Chinese', 'zh'))
        idx = 0 if current_code == 'en' else 1
        self.language_combo.setCurrentIndex(idx)
        self.language_combo.blockSignals(False)

    def _refresh_theme_combo(self):
        if not hasattr(self, 'theme_label') or not hasattr(self, 'theme_combo'):
            return
        current_mode = self.theme_combo.currentData() or getattr(self, '_theme_mode', 'light')
        self.theme_label.setText(self.t('Mode'))
        self.theme_combo.blockSignals(True)
        try:
            self.theme_combo.clear()
            self.theme_combo.addItem(self.t('Light'), 'light')
            self.theme_combo.addItem(self.t('Dark'), 'dark')
            self.theme_combo.addItem(self.t('Colorful'), 'colorful')
            if str(current_mode) == 'dark':
                idx = 1
            elif str(current_mode) == 'colorful':
                idx = 2
            else:
                idx = 0
            self.theme_combo.setCurrentIndex(idx)
        finally:
            self.theme_combo.blockSignals(False)

    def _refresh_font_size_combo(self):
        label = getattr(self, 'font_size_label', None)
        combo = getattr(self, 'font_size_combo', None)
        if isinstance(label, QLabel):
            label.setText(self.t('UI Font'))
        if not isinstance(combo, QComboBox):
            return
        current_size = int(getattr(self, '_ui_font_point_size', 10) or 10)
        combo.blockSignals(True)
        try:
            idx = combo.findData(current_size)
            combo.setCurrentIndex(idx if idx >= 0 else 1)
        finally:
            combo.blockSignals(False)

    def _apply_ui_font_size(self, point_size: int):
        app = QApplication.instance()
        if not app:
            return
        size = max(6, min(24, int(point_size)))
        self._ui_font_point_size = size
        f = app.font()
        if not isinstance(f, QFont):
            return
        f.setPointSize(size)
        app.setFont(f)
        # Apply to the current window tree immediately so existing widgets refresh.
        self.setFont(f)
        for widget in self.findChildren(QWidget):
            try:
                widget.setFont(f)
            except Exception:
                pass
        self._refresh_language_dependent_sizes()
        self.update()

    def _on_font_size_changed(self):
        combo = getattr(self, 'font_size_combo', None)
        if not isinstance(combo, QComboBox):
            return
        data = combo.currentData()
        try:
            text_value = (combo.currentText() or '').strip()
            size = int(data if data is not None else text_value)
        except Exception:
            size = 10
        self._apply_ui_font_size(size)

    def _apply_theme(self, mode: str):
        m = str(mode or 'light')
        if m == 'dark':
            self._theme_mode = 'dark'
        elif m == 'colorful':
            self._theme_mode = 'colorful'
        else:
            self._theme_mode = 'light'
        app = QApplication.instance()
        if not app:
            return
        dark = self._theme_mode == 'dark'
        colorful = self._theme_mode == 'colorful'
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
        app.setStyle(_ThemeStyle('Fusion' if dark else self._default_style_name, self._theme_mode))
        if dark:
            # Fusion consistently paints the custom dark palette across platforms.
            palette = QPalette(QColor('#2a2a2a'))
            for role, color in (
                (QPalette.ColorRole.Window, '#1f1f1f'),
                (QPalette.ColorRole.Base, '#202020'),
                (QPalette.ColorRole.AlternateBase, '#242424'),
                (QPalette.ColorRole.Highlight, '#3a5fcd'),
                (QPalette.ColorRole.Accent, '#3a5fcd'),
                (QPalette.ColorRole.HighlightedText, '#ffffff'),
                (QPalette.ColorRole.Link, '#8daaff'),
                (QPalette.ColorRole.LinkVisited, '#c4b5fd'),
            ):
                palette.setColor(role, QColor(color))
            for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
                palette.setColor(QPalette.ColorGroup.Disabled, role, QColor('#9aa0b3'))
            app.setPalette(palette)
        else:
            app.setPalette(QPalette())
            # Some platform themes keep supplying a dark palette after the light request.
            if app.palette().color(QPalette.ColorRole.Window).lightness() < 128:
                app.setStyle(_ThemeStyle('Fusion', self._theme_mode))
                app.setPalette(app.style().standardPalette())
            palette = app.palette()
            if colorful:
                for role in (QPalette.ColorRole.Accent, QPalette.ColorRole.Highlight, QPalette.ColorRole.Link):
                    palette.setColor(role, QColor(_COLORFUL_ACCENT))
                palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#ffffff'))
                palette.setColor(QPalette.ColorRole.LinkVisited, QColor(_COLORFUL_ACCENT_HOVER))
            else:
                palette.setColor(QPalette.ColorRole.Window, QColor('#f8f8f8'))
            app.setPalette(palette)
        self._apply_window_opacity()
        shared_style = _shared_stylesheet(app.palette(), self._theme_mode)
        self._refresh_function_tabbar_theme()
        if self.exe_button.styleSheet():
            self._update_exe_button_progress()
        if self._theme_mode == 'light':
            app.setStyleSheet(shared_style)
            return
        if colorful:
            app.setStyleSheet(
                "QWidget{background:transparent;color:#1f2330;}"
                f"QWidget#mainWindow,QDialog{{background:{_COLORFUL_GRADIENT};}}"
                "QWidget:disabled{color:#8b92a8;}"
                "QLineEdit,QPlainTextEdit,QTextEdit,QAbstractSpinBox{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:4px;}"
                "QTextBrowser#thirdPartyNoticesBrowser{background:transparent;}"
                "QLineEdit:disabled,QPlainTextEdit:disabled,QTextEdit:disabled,QAbstractSpinBox:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QComboBox{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:4px;padding:2px 6px;}"
                "QLineEdit:focus:!read-only,QPlainTextEdit:focus:!read-only,QTextEdit:focus:!read-only,"
                f"QAbstractSpinBox:focus:!read-only,QComboBox:editable:focus{{border-bottom-color:{_COLORFUL_ACCENT};}}"
                "QComboBox:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                f"QComboBox QAbstractItemView{{background:#ffffff;color:#1f2330;selection-background-color:{_COLORFUL_ACCENT};selection-color:#ffffff;}}"
                "QGroupBox{background:rgba(255,255,255,190);border:1px solid rgba(214,217,230,220);border-radius:8px;margin-top:10px;}"
                f"QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 6px;color:{_COLORFUL_ACCENT};}}"
                "QRadioButton{color:#1f2330;}"
                "QRadioButton:disabled{color:#8b92a8;}"
                f"QRadioButton::indicator{{width:14px;height:14px;border-radius:7px;border:2px solid {_COLORFUL_ACCENT};background:rgba(255,255,255,220);}}"
                f"QRadioButton::indicator:checked{{background:{_COLORFUL_ACCENT};border-color:{_COLORFUL_ACCENT_HOVER};}}"
                f"QRadioButton::indicator:checked:hover{{background:{_COLORFUL_ACCENT_HOVER};}}"
                f"QRadioButton::indicator:unchecked:hover{{border-color:{_COLORFUL_ACCENT_HOVER};}}"
                "QRadioButton::indicator:disabled{border:2px solid #c7cbe0;background:rgba(243,244,248,220);}"
                "QRadioButton::indicator:checked:disabled{border:2px solid #c7cbe0;background:rgba(199,203,224,220);}"
                "QCheckBox{color:#1f2330;}"
                "QCheckBox:disabled{color:#8b92a8;}"
                f"{_SCROLL_CONTROL_GEOMETRY}"
                "QSlider::groove:horizontal,QSlider::add-page:horizontal{background:rgba(214,217,230,180);}"
                f"QSlider::sub-page:horizontal{{background:{_COLORFUL_ACCENT};}}"
                f"QSlider::handle:horizontal{{background:#ffffff;border-color:{_COLORFUL_ACCENT};}}"
                f"QSlider::handle:horizontal:hover{{border-color:{_COLORFUL_ACCENT_HOVER};}}"
                "QPushButton,QToolButton{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:8px;padding:4px 10px;}"
                f"QPushButton:hover,QToolButton:hover{{border:1px solid {_COLORFUL_ACCENT};}}"
                "QPushButton:pressed,QToolButton:pressed{background:#eee8f8;}"
                "QPushButton:disabled,QToolButton:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QScrollBar::handle{background:#a78bfa;}"
                f"QScrollBar::handle:hover{{background:{_COLORFUL_ACCENT};}}"
                "QMenu{background:#ffffff;color:#1f2330;border:1px solid #d6d9e6;}"
                f"QMenu::item:selected{{background:{_COLORFUL_ACCENT};color:#ffffff;}}"
                "QProgressBar{background:#ffffff;border:1px solid #d6d9e6;border-radius:6px;text-align:center;color:#1f2330;}"
                f"QProgressBar::chunk{{background:{_COLORFUL_ACCENT};border-radius:6px;}}"
                f"QToolTip{{background:#1f2330;color:#ffffff;border:1px solid {_COLORFUL_ACCENT};}}"
                f"{shared_style}"
            )
            return
        app.setStyleSheet(
            "QWidget{background:#1f1f1f;color:#e6e6e6;}"
            "QLineEdit,QPlainTextEdit,QTextEdit,QAbstractSpinBox{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
            "QComboBox{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:2px 6px;}"
            "QComboBox:disabled,QAbstractSpinBox:disabled{background:#242424;color:#9aa0b3;border-color:#343434;}"
            "QLineEdit:focus:!read-only,QPlainTextEdit:focus:!read-only,QTextEdit:focus:!read-only,"
            "QAbstractSpinBox:focus:!read-only,QComboBox:editable:focus{border-bottom-color:#5b7fff;}"
            "QComboBox QAbstractItemView{background:#2a2a2a;color:#e6e6e6;selection-background-color:#343d54;}"
            "QRadioButton{color:#e6e6e6;}"
            "QRadioButton::indicator{width:14px;height:14px;border-radius:7px;border:2px solid #5b7fff;background:#2a2a2a;}"
            "QRadioButton::indicator:checked{background:#3a5fcd;border:2px solid #5b7fff;}"
            "QRadioButton::indicator:checked:hover{background:#4a6fe0;}"
            "QRadioButton::indicator:unchecked:hover{border:2px solid #7a93ff;}"
            "QRadioButton:disabled{color:#9aa0b3;}"
            "QRadioButton::indicator:disabled{border:2px solid #555a6b;background:#252525;}"
            "QRadioButton::indicator:checked:disabled{border:2px solid #555a6b;background:#555a6b;}"
            "QPushButton,QToolButton{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:4px 8px;}"
            "QPushButton:hover,QToolButton:hover{background:#333333;}"
            "QPushButton:pressed,QToolButton:pressed{background:#3a3a3a;}"
            "QGroupBox{border:1px solid #3a3a3a;margin-top:10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
            f"{_SCROLL_CONTROL_GEOMETRY}"
            "QSlider::groove:horizontal,QSlider::add-page:horizontal{background:#454545;}"
            "QSlider::sub-page:horizontal{background:#5b7fff;}"
            "QSlider::handle:horizontal{background:#2a2a2a;border-color:#5b7fff;}"
            "QSlider::handle:horizontal:hover{border-color:#8daaff;}"
            "QScrollBar::handle{background:#626262;}"
            "QScrollBar::handle:hover{background:#7a7a7a;}"
            "QMenu{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
            "QMenu::item:selected{background:#3a5fcd;}"
            "QProgressBar{background:#2a2a2a;border:1px solid #3a3a3a;text-align:center;color:#e6e6e6;}"
            "QProgressBar::chunk{background:#3a5fcd;}"
            "QToolTip{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
            f"{shared_style}"
        )

    def _refresh_function_tabbar_theme(self) -> None:
        style = ''
        if self._theme_mode == 'colorful':
            color = _COLORFUL_FUNCTION_COLORS.get(self.get_selected_function_id(), _COLORFUL_ACCENT)
            background = _blend_color('#fffdf3', QColor(color), 0.18)
            style = f'QTabBar#functionTabbar::tab:selected{{background:{background};border-bottom-color:{color};}}'
        self.function_tabbar.setStyleSheet(style)

    def _on_theme_changed(self):
        mode = self.theme_combo.currentData() if hasattr(self, 'theme_combo') else 'light'
        self._apply_theme(str(mode))
        self._refresh_language_dependent_sizes()

    def _translate_widget_texts(self):
        for widget in self.findChildren(QWidget):
            if isinstance(widget, DiscCommandEdit):
                widget.setAccessibleName(self.t('remux cmd'))
            if widget.objectName() == 'mainPlaylistToggle':
                name = self.t('main')
                widget.setToolTip(name)
                widget.setAccessibleName(name)
            if widget is getattr(self, 'language_combo', None):
                continue
            if widget is getattr(self, 'theme_combo', None):
                continue
            if widget is getattr(self, 'font_size_combo', None):
                continue
            if widget is getattr(self, 'subtitle_suffix_combo', None):
                continue
            if isinstance(widget, (QLineEdit, QPlainTextEdit)):
                continue
            if isinstance(widget, QGroupBox):
                title_getter = getattr(widget, 'title', None)
                title_text = title_getter() if callable(title_getter) else ''
                if title_text:
                    widget.setTitle(self.t(title_text))
            if isinstance(widget, QTabBar):
                if widget is self.function_tabbar:
                    widget.setAccessibleName(self.t('Function'))
                widget.blockSignals(True)
                try:
                    for i in range(widget.count()):
                        widget.setTabText(i, self.t(widget.tabText(i)))
                finally:
                    widget.blockSignals(False)
            if isinstance(widget, QComboBox):
                if widget in (
                    getattr(self, 'encode_tool_combo', None),
                    getattr(self, 'encode_bit_depth_combo', None),
                    getattr(self, 'x265_preset_combo', None),
                ):
                    continue
                widget.blockSignals(True)
                try:
                    for i in range(widget.count()):
                        widget.setItemText(i, self.t(widget.itemText(i)))
                finally:
                    widget.blockSignals(False)
            if hasattr(widget, 'text') and hasattr(widget, 'setText'):
                try:
                    txt = widget.text()
                    if isinstance(txt, str) and txt:
                        widget.setText(self.t(txt))
                except Exception:
                    pass

    def _apply_language(self, language_code: str):
        code = 'zh' if language_code == 'zh' else 'en'
        self._language_code = code
        core_settings.CURRENT_UI_LANGUAGE = code
        self._language_updating = True
        try:
            self.setWindowTitle(APP_TITLE)
            self._translate_widget_texts()
            self._refresh_subtitle_suffix_options()
            self._refresh_language_combo()
            self._refresh_theme_combo()
            self._refresh_font_size_combo()
            self._refresh_all_table_headers()
            self._refresh_language_dependent_sizes()
            self.on_select_function(force=True, keep_inputs=True, keep_state=True)
            self._refresh_language_dependent_sizes()
            self._refresh_language_column_defaults()
            try:
                if getattr(self, 'encode_tool_combo', None) is not None and callable(
                    getattr(self, '_refill_encode_bit_depth_combo', None)
                ):
                    self._refill_encode_bit_depth_combo(self.encode_tool_combo.currentText())
            except Exception:
                pass
            try:
                self._refresh_encode_tool_dependent_ui(False)
            except Exception:
                pass
        finally:
            self._language_updating = False

    def _refresh_subtitle_suffix_options(self):
        combo = getattr(self, 'subtitle_suffix_combo', None)
        if not isinstance(combo, QComboBox):
            return
        current = (combo.currentText() or '').strip()
        combo.blockSignals(True)
        try:
            combo.clear()
            _lang = getattr(self, '_language_code', None) or core_settings.CURRENT_UI_LANGUAGE
            if _lang == 'zh':
                items = ["", ".zh-Hans", ".zh-Hant", ".chs", ".cht", ".sc", ".tc", ".big5", ".gb"]
            else:
                items = ["", ".en", ".eng", ".en_US", ".jpn", ".jp", ".kor"]
            combo.addItems(items)
            combo.setCurrentText(current if current != '' else '')
        finally:
            combo.blockSignals(False)

    def _get_subtitle_suffix(self) -> str:
        combo = getattr(self, 'subtitle_suffix_combo', None)
        if isinstance(combo, QComboBox):
            return (combo.currentText() or '').strip()
        return ''

    def _on_language_changed(self):
        code = self.language_combo.currentData() or 'en'
        self._apply_language(str(code))

    def _localized_headers_for_keys(self, keys: list[str]) -> list[str]:
        header_text = {
            'disc_volume': 'Disc volume',
            'm2ts_file_detail': 'm2ts detail',
            'warning': 'Prompt',
            'language': 'Language',
            'lang': 'Language',
            'logical_track': 'Logical track',
            'pid': 'PID',
            'track_status': 'Status',
            'select': 'Select',
            'convert': 'convert',
            'extract': 'extract',
            'edit_chapters': 'edit chapters',
            'edit_attachments': 'Edit Attachment',
            'filename': 'filename',
            'mime_type': 'mime_type',
            'uid': 'UID',
            'track_uid': 'UID',
            'codec_id': 'Codec ID',
            'id': 'ID',
            'preview_script': 'preview',
            'edit_tracks': 'edit tracks',
            'chapters': 'Chapters',
            'm2ts_timing': 'M2TS timing',
            'play': 'play',
        }
        return [self.t(header_text.get(key, key.replace('_', ' '))) for key in keys]

    def _refresh_language_dependent_sizes(self):
        table1 = getattr(self, 'table1', None)
        tables = [getattr(self, name, None) for name in ('table2', 'table3')]
        if table1 is not None:
            tables.extend(
                table1.cellWidget(row, 2) for row in range(table1.rowCount())
                if isinstance(table1.cellWidget(row, 2), QTableWidget)
            )
        for table in tables:
            if table is not None:
                self._resize_table_columns_for_language(table)
                self._scroll_table_to_primary_column(table)
        if table1 is not None:
            table1.horizontalHeader().setFixedHeight(table1.fontMetrics().height() + 10)
            self._resize_table_columns_for_language(table1)
            self._scroll_table_to_primary_column(table1)
        self._resize_encode_tool_combos()
        duration = getattr(self, 'approx_episode_minutes_combo', None)
        if duration is not None:
            self._adjust_combo_width_to_contents(duration, padding=54, min_width=120, max_width=220)
        params = getattr(self, 'x265_params_edit', None)
        if params is not None:
            params.setFixedHeight(max(96, params.fontMetrics().lineSpacing() * 3 + 16))
