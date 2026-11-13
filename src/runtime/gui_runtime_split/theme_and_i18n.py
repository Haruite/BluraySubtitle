"""Target module for theme/language methods of `BluraySubtitleGUI`."""
from PyQt6.QtCore import QLibraryInfo, QRectF, Qt, QTranslator
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QApplication, QLabel, QTabBar, QWidget, QPlainTextEdit, QTextEdit, QLineEdit, QGroupBox, \
    QComboBox, QProxyStyle, QStyle, QTableWidget

from src.core import APP_TITLE
import src.core.settings as core_settings
from src.core.i18n import translate_text
from src.runtime.gui_runtime_classes.custom_table_widget import editable_table_border_color
from src.runtime.gui_runtime_classes.desktop_appearance import desktop_appearance
from src.runtime.gui_runtime_classes.disc_table_widget import DiscCommandEdit
from src.runtime.gui_runtime_classes.widget_animations import set_window_opacity, supports_window_opacity
from src.runtime.gui_runtime_classes.x11_window import apply_x11_title_bar_theme
from .gui_base import BluraySubtitleGuiBase


_SCROLL_BAR_GEOMETRY = (
    "QScrollBar{background:transparent;border:none;}"
    "QScrollBar:horizontal{height:7px;margin:0 1px;}"
    "QScrollBar:vertical{width:7px;margin:1px 0;}"
    "QScrollBar::handle{border-radius:2px;}"
    "QScrollBar::handle:horizontal{min-width:24px;margin:1px 0;}"
    "QScrollBar::handle:vertical{min-height:24px;margin:0 1px;}"
    "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}"
    "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
    "QScrollBar::add-line,QScrollBar::sub-line,QScrollBar::add-page,QScrollBar::sub-page{background:transparent;}"
)
_COLORFUL_ACCENT = '#7c3aed'
_COLORFUL_ACCENT_HOVER = '#6d28d9'
_DARK_ACCENT = '#3a5fcd'
_DARK_FOCUS = '#5b7fff'
_COLORFUL_GRADIENT = 'qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #fff7d9,stop:0.55 #fffefa,stop:1 #f4f9ff)'
_LOG_THEME_ACCENTS = {'light': '#356dcc', 'dark': _DARK_ACCENT, 'colorful': _COLORFUL_ACCENT}
_COLORFUL_FUNCTION_COLORS = {1: '#0ea5e9', 2: '#14b8a6', 3: '#f59e0b', 4: '#ef4444', 5: '#8b5cf6'}
_COLORFUL_TABLE_COLORS = (
    (('table1', 'playlistTable', 'chapterTable', 'timingTable', 'subtitleEditorTable'),
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


def _accent_text_color(color: QColor) -> QColor:
    rgb = (value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
           for value in color.getRgbF()[:3])
    luminance = sum(channel * weight for channel, weight in zip(rgb, (0.2126, 0.7152, 0.0722)))
    return QColor('#141618' if luminance > 0.20 else '#ffffff')


def execution_button_stylesheet(palette: QPalette, mode: str, progress: float | None = None) -> str:
    dark = mode == 'dark'
    accent = palette.color(QPalette.ColorRole.Accent)
    surface = '#22252b' if dark else '#ffffff'
    text = '#e6e6e6' if dark else '#20262e'
    edge = _blend_color(surface, accent, 0.55 if dark else 0.32)
    focus = _DARK_FOCUS if dark else accent.name()
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


def _table_control_colors(selectors: tuple[str, ...], surface: str, edge: str, accent: QColor,
                          focus: str, dark: bool) -> str:
    controls = tuple(
        f'{table} {control}'
        for table in selectors
        for control in (
            'QWidget#vpyPathCell QLineEdit:enabled',
            'QPushButton:enabled',
            'QToolButton[checkable="false"]:enabled',
            'QToolButton#mainPlaylistToggle:enabled:!checked',
        )
    )
    if 'QTableWidget#table2' in selectors:
        controls += ('QTableWidget#table2 QComboBox[chapterRange="true"]:enabled',)
    if 'QTableWidget#trackTable' in selectors:
        controls += ('QTableWidget#trackTable QComboBox:enabled',)
    fill = _blend_color(surface, accent, 0.15 if dark else 0.11)
    hover = _blend_color(surface, accent, 0.24 if dark else 0.20)
    border = _blend_color(edge, accent, 0.27 if dark else 0.19)
    style = (
        f'{",".join(controls)}{{background:{fill};border-color:{border};}}'
        f'{",".join(f"{control}:hover" for control in controls)}{{background:{hover};}}'
        f'{",".join(f"{control}:focus" for control in controls)}{{border-bottom-color:{focus};}}'
    )
    value_tables = tuple(
        table for table in selectors if table in ('QTableWidget#table2', 'QTableWidget#table3', 'QTableWidget#trackTable')
    )
    if value_tables:
        editors = tuple(f'{table} QLineEdit[tableValueEditor="true"]' for table in value_tables)
        style += (
            f'{",".join(value_tables)}{{qproperty-editableCellBorderColor:{border};}}'
            f'{",".join(editors)}{{border-color:{border};}}'
            f'{",".join(f"{editor}:focus" for editor in editors)}{{border-bottom-color:{focus};}}'
        )
    return style


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
    focus = _DARK_FOCUS if dark else accent.name()
    title_color = _COLORFUL_ACCENT if colorful else text
    pane = 'rgba(255,255,255,145)' if colorful else surface
    editor = 'rgba(255,255,255,178)' if colorful else surface
    tinted_editor_background = '#2c3542' if dark else '#f4f8ff'
    tinted_editor_disabled_background = '#2a3039' if dark else '#f7f9fc'
    section_background = {'light': '#f1f6fc', 'dark': '#242830', 'colorful': 'rgba(246,250,255,205)'}[mode]
    tool_result_background = {'light': table_colors[1], 'dark': table_colors[0], 'colorful': '#f3efff'}[mode]
    checked, checked_hover, checked_edge = (
        ('#ffedd5', '#fed7aa', '#fb923c') if colorful else
        (_DARK_ACCENT, '#4970df', focus) if dark else (accent.name(), hover, focus)
    )
    checked_disabled = _blend_color(surface, QColor(checked_edge), 0.35)
    section = 'QGroupBox[workspaceSection="true"]'
    subtitle_box = 'QGroupBox[subtitlePathBox="true"]'
    encode_box = 'QGroupBox#encodeBox'
    command_edit = 'QPlainTextEdit#discCommandEdit'
    encode_params = f'{encode_box} > QPlainTextEdit'
    tab_bar = 'QTabBar#functionTabbar,QDialog QTabBar'
    tab = 'QTabBar#functionTabbar::tab,QDialog QTabBar::tab'
    toggle = 'QTableWidget QToolButton[checkable="true"]'
    control_accent = QColor({'light': '#78a7d6', 'dark': '#66788b', 'colorful': _COLORFUL_ACCENT}[mode])
    field_fill, field_edge = ('#2a2a2a', '#3d3d3d') if dark else ('#f8f9fb', '#dce0e6')
    combo_fill, combo_hover = ('#30353c', '#353b44') if dark else ('#edf4fc', '#e5effa')
    control_edge = editable_table_border_color(dark)
    tab_edge = _blend_color(control_edge, QColor(focus), 0.32)
    scroll_handle = {'light': '#8b929a', 'dark': '#6e727a', 'colorful': '#a78bfa'}[mode]
    scroll_hover = {'light': '#656d77', 'dark': '#989ca4', 'colorful': _COLORFUL_ACCENT}[mode]
    styles = [
        f'{_SCROLL_BAR_GEOMETRY}'
        f'QScrollBar::handle{{background:{scroll_handle};}}'
        f'QScrollBar::handle:hover,QScrollBar::handle:pressed{{background:{scroll_hover};}}'
        'OpacitySlider{background:transparent;}'
        'OpacitySlider::groove:horizontal{height:4px;background:transparent;}'
        'OpacitySlider::handle:horizontal{width:16px;margin:-6px 0;background:transparent;}'
        'StyledComboBox{combobox-popup:0;combobox-list-mousetracking:1;}'
        'QDialogButtonBox{dialogbuttonbox-buttons-have-icons:0;}'
        f'StyledComboBox QAbstractItemView{{background:{surface};color:{text};border:1px solid {control_edge};'
        f'outline:0;selection-background-color:{selection};selection-color:{text};}}'
        'StyledComboBox QAbstractItemView::item{padding:3px 8px 3px 11px;}'
        f'StyledComboBox QAbstractItemView::item:selected{{background:{selection};color:{text};}}',
        f'QWidget#startupUpdateNotice{{background:{table_selection};border:1px solid {focus};border-radius:6px;}}'
        f'QWidget#startupUpdateNotice QLabel{{background:transparent;color:{text};font-weight:600;}}'
        f'SelectionTableWidget{{qproperty-editableCellBorderColor:{control_edge};}}'
        f'QComboBox:enabled,QPushButton:enabled,QToolButton:enabled{{border:1px solid {control_edge};}}'
        'QComboBox:enabled:focus,QPushButton:enabled:focus,QToolButton:enabled:focus'
        f'{{border-bottom-color:{focus};}}'
        'StyledComboBox::drop-down{width:20px;border:0;background:transparent;}'
        # Reserve the second button's width in the edit field on older Qt versions.
        'StyledSpinBox,StyledDoubleSpinBox{border-radius:5px;padding:2px 25px 2px 0;}'
        'StyledSpinBox[layoutDirection="RightToLeft"],StyledDoubleSpinBox[layoutDirection="RightToLeft"]'
        '{padding-left:25px;padding-right:0;}'
        'StyledSpinBox::up-button,StyledSpinBox::down-button,'
        'StyledDoubleSpinBox::up-button,StyledDoubleSpinBox::down-button'
        '{subcontrol-origin:padding;subcontrol-position:center right;position:absolute;'
        'top:0;bottom:0;width:24px;border:0;background:transparent;}'
        'StyledSpinBox::up-button,StyledDoubleSpinBox::up-button{right:24px;}'
        'StyledSpinBox::down-button,StyledDoubleSpinBox::down-button{right:0;}'
        'QLineEdit:enabled:!read-only,QAbstractSpinBox:enabled:!read-only'
        f'{{border-color:{control_edge};}}'
        'QLineEdit:enabled:focus:!read-only,QAbstractSpinBox:enabled:focus:!read-only'
        f'{{border-bottom-color:{focus};}}',
        _table_stylesheet(('QTableWidget',), *table_colors, table_selection, text),
        f'{section},{subtitle_box},QDialog QGroupBox{{border:1px solid {edge};border-radius:8px;}}'
        f'{section},QDialog QGroupBox{{margin-top:9px;}}'
        f'{subtitle_box}{{margin-top:0;}}'
        f'{section},{subtitle_box},{subtitle_box} > QLineEdit{{background:{section_background};}}'
        f'{section} > QLabel,QWidget#spSelectionRow{{background:transparent;}}'
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
        f'{command_edit}:enabled{{border-color:{control_edge};}}'
        f'{command_edit}:disabled,{encode_params}:disabled'
        f'{{background:{tinted_editor_disabled_background};color:{muted_text};}}'
        f'QDialog QPlainTextEdit{{background:{editor};}}'
        f'QPlainTextEdit#externalToolsEditor{{background:{tinted_editor_background};}}'
        f'QPlainTextEdit#externalToolsDetectionView{{background:{tool_result_background};}}'
        f'{command_edit}:focus,{encode_params}:focus:!read-only,QDialog QPlainTextEdit:focus:!read-only'
        f'{{border-bottom-color:{focus};}}'
        f'QDialog QTabWidget::pane{{background:{pane};border:1px solid {edge};border-radius:6px;}}'
        'QDialog QScrollArea{background:transparent;border:0;}'
        f'{tab_bar}{{qproperty-drawBase:false;background:{pane};border:1px solid {tab_edge};border-radius:5px;}}'
        f'{tab}{{background:transparent;color:{text};border:0;border-bottom:2px solid transparent;'
        'padding:7px 10px;margin:2px 0;}'
        'QTabBar#functionTabbar::tab:first,QDialog QTabBar::tab:first{margin-left:2px;}'
        'QTabBar#functionTabbar::tab:last,QDialog QTabBar::tab:last{margin-right:2px;}'
        'QTabBar#functionTabbar::tab:hover:!selected,QDialog QTabBar::tab:hover:!selected'
        f'{{background:{tab_hover};}}'
        'QTabBar#functionTabbar::tab:selected,QDialog QTabBar::tab:selected'
        f'{{background:{tab_selected};border-bottom-color:{focus};}}'
        f'QDialog QPushButton{{background:{surface};color:{text};border:1px solid {edge};border-radius:6px;padding:5px 12px;}}'
        f'QDialog QPushButton:hover,QDialog QPushButton:pressed{{background:{selection};border-color:{focus};}}'
        f'QDialog QPushButton:default,QDialog QPushButton:focus{{border-color:{focus};}}'
        f'QDialog QPushButton:disabled{{background:{alternate};color:{muted_text};border-color:{edge};}}',
        'QTableWidget QWidget#vpyPathCell{background:transparent;}'
        'QTableWidget QComboBox,QTableWidget QLineEdit,QTableWidget QPushButton'
        f'{{border:1px solid transparent;border-radius:4px;color:{text};}}'
        'QTableWidget QComboBox{padding:2px 6px;margin:1px 2px;}'
        f'QTableWidget QComboBox:enabled{{background:{combo_fill};}}'
        f'QTableWidget QComboBox:enabled:hover{{background:{combo_hover};}}'
        f'QTableWidget QLineEdit{{background:{field_fill};border-color:{field_edge};padding:1px 4px;}}'
        f'QTableWidget QLineEdit:enabled:focus{{border-bottom-color:{focus};}}'
        'QTableWidget QPushButton{padding:2px 7px;}'
        'QTableWidget QToolButton[checkable="false"]{margin:1px 2px;}'
        'QTableWidget QComboBox:disabled,QTableWidget QLineEdit:disabled'
        f'{{background:{field_fill};border-color:{field_edge};color:{muted_text};}}'
        'StyledComboBox QLineEdit,StyledComboBox QLineEdit:disabled,'
        'QAbstractSpinBox QLineEdit,QAbstractSpinBox QLineEdit:disabled'
        '{background:transparent;border:0;padding:0;}'
        'QTableWidget QPushButton:disabled'
        f'{{background:transparent;border-color:transparent;color:{muted_text};}}',
        _table_control_colors(('QTableWidget',), table_colors[0], table_colors[3], control_accent, focus, dark),
        execution_button_stylesheet(palette, mode),
    ]
    if mode == 'light':
        styles.insert(0, (
            f'QComboBox,QPushButton,QToolButton{{border:1px solid {field_edge};border-radius:5px;}}'
            'QComboBox{padding:3px 6px;}'
            'QPushButton,QToolButton{padding:4px 9px;}'
            f'QLineEdit,QAbstractSpinBox{{background:#fcfcfd;border:1px solid {field_edge};border-radius:5px;}}'
            'QLineEdit{padding:2px 4px;}'
            'QComboBox:disabled,QPushButton:disabled,QToolButton:disabled,QLineEdit:disabled,QAbstractSpinBox:disabled'
            f'{{background:{field_fill};color:{muted_text};}}'
            f'QPushButton:enabled:hover,QToolButton:enabled:hover{{background:{selection};}}'
            f'QPushButton:enabled:pressed,QToolButton:enabled:pressed{{background:{tint};}}'
        ))
    if colorful:
        for names, base, stripe, heading, border, scrollbar, scrollbar_hover in _COLORFUL_TABLE_COLORS:
            selectors = tuple(f'QTableWidget#{name}' for name in names)
            highlight = _blend_color(base, QColor(scrollbar_hover), 0.16)
            styles.append(_table_stylesheet(selectors, base, stripe, heading, border, highlight, text))
            styles.append(_table_control_colors(selectors, base, border, QColor(scrollbar), focus, dark))
            handles = tuple(f'{selector} QScrollBar::handle' for selector in selectors)
            styles.append(f'{",".join(handles)}{{background:{scrollbar};}}')
            styles.append(f'{",".join(f"{handle}:hover" for handle in handles)}{{background:{scrollbar_hover};}}')
        playlist_colors = ('#fbfdff', '#edf5ff', '#eef5ff', '#b9d0ed')
        playlist_selection = _blend_color(playlist_colors[0], QColor('#2563eb'), 0.16)
    else:
        base, stripe, _, border = table_colors
        playlist_colors = (base, stripe, '#404956' if dark else '#edf3fa', border)
        playlist_selection = table_selection
    styles.append(_table_stylesheet(('QTableWidget#playlistTable',), *playlist_colors, playlist_selection, text))
    if dark:
        styles.append(
            f'{encode_box} QCheckBox,{encode_box} QRadioButton{{background:{section_background};}}'
        )
    return ''.join(styles)


def _log_window_stylesheet(mode: str) -> str:
    dark = mode == 'dark'
    colorful = mode == 'colorful'
    background = _COLORFUL_GRADIENT if colorful else ('#1f1f1f' if dark else '#f8f8f8')
    field = '#2a2a2a' if dark else '#ffffff'
    editor = _COLORFUL_GRADIENT if colorful else field
    text, muted, edge = ('#e6e6e6', '#9aa0b3', '#3a3a3a') if dark else ('#1f2330', '#666b75', '#dce0e6')
    accent = _LOG_THEME_ACCENTS[mode]
    focus = _DARK_FOCUS if dark else accent
    hover = _blend_color(field, QColor(accent), 0.22 if dark else 0.12)
    scroll_handle = '#a78bfa' if colorful else ('#626262' if dark else '#a7aeb8')
    return (
        f'QWidget{{background:transparent;color:{text};}}'
        f'QWidget:disabled{{color:{muted};}}'
        f'QDialog{{background:{background};}}'
        f'QLineEdit,QPlainTextEdit{{border:1px solid {edge};border-radius:5px;padding:3px;'
        f'selection-background-color:{accent};selection-color:#ffffff;}}'
        f'QLineEdit{{background:{field};placeholder-text-color:{muted};}}'
        f'QLineEdit:focus{{border-bottom-color:{focus};}}'
        f'QPlainTextEdit{{background:{editor};}}'
        f'QPushButton{{background:{field};border:1px solid {edge};border-radius:6px;padding:5px 12px;}}'
        f'QPushButton:hover:enabled,QPushButton:pressed:enabled{{background:{hover};border-color:{focus};}}'
        f'QPushButton:focus{{border-color:{focus};}}'
        f'QMenu{{background:{field};border:1px solid {edge};}}'
        f'QMenu::item:selected{{background:{accent};color:#ffffff;}}'
        f'QScrollBar::handle{{background:{scroll_handle};}}'
        f'QScrollBar::handle:hover{{background:{focus};}}'
    )


class _ThemeStyle(QProxyStyle):
    def __init__(self, base_style: str, mode: str):
        super().__init__(base_style)
        self._mode = mode

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (
            QStyle.PixelMetric.PM_IndicatorWidth, QStyle.PixelMetric.PM_IndicatorHeight,
            QStyle.PixelMetric.PM_ExclusiveIndicatorWidth, QStyle.PixelMetric.PM_ExclusiveIndicatorHeight,
        ):
            return 16
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        checkbox = element == QStyle.PrimitiveElement.PE_IndicatorCheckBox
        radio = element == QStyle.PrimitiveElement.PE_IndicatorRadioButton
        window = widget.window() if (checkbox or radio) and widget is not None else None
        log_mode = window.property('logWindowTheme') if window is not None else None
        window_background = getattr(window, '_window_background', None)
        over_image = window_background is not None and window_background.active
        table_checkbox = (
            element == QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck and isinstance(widget, QTableWidget)
        )
        if not (radio or checkbox or table_checkbox):
            super().drawPrimitive(element, option, painter, widget)
            return

        flags = QStyle.StateFlag
        enabled = bool(option.state & flags.State_Enabled)
        partial = bool(option.state & flags.State_NoChange)
        marked = partial or bool(option.state & flags.State_On)
        hovered = bool(option.state & flags.State_MouseOver)
        palette = QApplication.palette()
        dark = (log_mode or self._mode) == 'dark'
        if log_mode is None:
            accent = palette.color(QPalette.ColorRole.Accent)
            base = palette.color(QPalette.ColorRole.Base)
        else:
            accent = QColor(_LOG_THEME_ACCENTS[log_mode])
            base = QColor('#2a2a2a' if dark else '#ffffff')
        if dark and checkbox and log_mode is None:
            accent = QColor('#525861')
        if hovered:
            accent = accent.darker(112)
        # The native indicator can inherit a transparent fill from the window stylesheet.
        outline = '#757983' if dark else '#9399a4'
        if over_image or radio:
            base.setAlpha(255)
            accent.setAlpha(255)
            outline = '#a6abba' if dark else '#626d80'
        if enabled:
            border = accent if marked or hovered else QColor(outline)
            background = accent if marked else base
            mark = _accent_text_color(accent)
        else:
            border = QColor('#555a64' if dark else '#b8bdc8')
            background = QColor('#34373e' if dark else '#e5e7ef')
            mark = QColor('#a6abba' if dark else '#626d88')

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(option.rect.topLeft())
        painter.scale(option.rect.width() / 16, option.rect.height() / 16)
        if radio:
            painter.setPen(QPen(border, 1.5))
            painter.setBrush(base if enabled else background)
            painter.drawEllipse(QRectF(1, 1, 14, 14))
            if marked:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent if enabled else mark)
                painter.drawEllipse(QRectF(4, 4, 8, 8))
        else:
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
    _qt_translator: QTranslator | None = None

    def _window_opacity_supported(self) -> bool:
        return supports_window_opacity()

    def _apply_window_opacity(self, window: QWidget | None = None):
        if not self._window_opacity_supported():
            return
        # QWidget stores opacity as a byte before the native window is created.
        opacity = round(self.opacity_slider.value() * 255 / 100) / 255
        targets = (self, self._log_dialog) if window is None else (window,)
        for target in targets:
            if target is not None:
                set_window_opacity(target, opacity)

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
            label.setText(self.t('UI font size'))
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
        preferences = self._app_config.ui.fonts

        def choose_font(family: str, default: QFont) -> QFont:
            font = QFont(default)
            if family:
                font.setFamilies([family, *default.families()])
            font.setPointSize(size)
            return font

        interface_font = choose_font(preferences.interface, self._default_ui_font)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._content_fonts = {
            'interface': interface_font,
            'table': choose_font(preferences.table, interface_font),
            'log': choose_font(preferences.log, interface_font),
            'editor': choose_font(preferences.editor, interface_font),
            'external_tools': choose_font(preferences.editor, interface_font if preferences.editor else fixed_font),
        }
        app.setFont(interface_font)
        self.setFont(interface_font)
        for widget in self.findChildren(QWidget):
            self._apply_widget_font(widget)
        if self._log_dialog is not None:
            self._log_dialog.setFont(interface_font)
            for widget in self._log_dialog.findChildren(QWidget):
                self._apply_widget_font(widget)
        self._refresh_language_dependent_sizes()
        self.update()

    def _apply_widget_font(self, widget: QWidget) -> None:
        if isinstance(widget, QTableWidget):
            font = self._content_fonts['table']
            widget.setFont(font)
            widget.horizontalHeader().setFont(font)
            widget.verticalHeader().setFont(font)
            return
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
            role = {
                'applicationLogOutput': 'log',
                'externalToolsEditor': 'external_tools',
            }.get(widget.objectName(), 'editor')
        else:
            parent = widget.parentWidget()
            if parent is not None and not widget.isWindow():
                widget.setFont(parent.font())
                return
            role = 'interface'
        widget.setFont(self._content_fonts[role])

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
        base_style = 'Fusion' if dark or app.platformName() in ('xcb', 'wayland') else self._default_style_name
        app.setStyle(_ThemeStyle(base_style, self._theme_mode))
        if dark:
            # Fusion consistently paints the custom dark palette across platforms.
            palette = QPalette(QColor('#2a2a2a'))
            for role, color in (
                (QPalette.ColorRole.Window, '#1f1f1f'),
                (QPalette.ColorRole.Base, '#202020'),
                (QPalette.ColorRole.AlternateBase, '#242424'),
                (QPalette.ColorRole.Highlight, _DARK_ACCENT),
                (QPalette.ColorRole.Accent, _DARK_FOCUS),
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
                appearance = desktop_appearance()
                if appearance is not None:
                    accent = appearance.accent()
                    if accent.isValid():
                        for role in (QPalette.ColorRole.Accent, QPalette.ColorRole.Highlight):
                            palette.setColor(role, accent)
                        palette.setColor(QPalette.ColorRole.HighlightedText, _accent_text_color(accent))
            app.setPalette(palette)
        shared_style = _shared_stylesheet(app.palette(), self._theme_mode)
        if self.exe_button.styleSheet():
            self._update_exe_button_progress()
        theme_style = ""
        if colorful:
            theme_style = (
                "QWidget{background:transparent;color:#1f2330;}"
                f"QWidget#mainWindow,QDialog{{background:{_COLORFUL_GRADIENT};}}"
                f"QPlainTextEdit#applicationLogOutput{{background:{_COLORFUL_GRADIENT};}}"
                "QWidget:disabled{color:#8b92a8;}"
                "QLineEdit,QPlainTextEdit,QTextEdit,QAbstractSpinBox{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:4px;}"
                "QTextBrowser#thirdPartyNoticesBrowser{background:transparent;}"
                "QLineEdit:disabled,QPlainTextEdit:disabled,QTextEdit:disabled,QAbstractSpinBox:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QComboBox{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:4px;padding:2px 6px;}"
                "QPlainTextEdit:focus:!read-only,QTextEdit:focus:!read-only,"
                f"QComboBox:editable:focus{{border-bottom-color:{_COLORFUL_ACCENT};}}"
                "QComboBox:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                f"QComboBox QAbstractItemView{{background:#ffffff;color:#1f2330;selection-background-color:{_COLORFUL_ACCENT};selection-color:#ffffff;}}"
                "QGroupBox{background:rgba(255,255,255,190);border:1px solid rgba(214,217,230,220);border-radius:8px;margin-top:10px;}"
                f"QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 6px;color:{_COLORFUL_ACCENT};}}"
                "QRadioButton{color:#1f2330;}"
                "QRadioButton:disabled{color:#8b92a8;}"
                "QCheckBox{color:#1f2330;}"
                "QCheckBox:disabled{color:#8b92a8;}"
                "QPushButton,QToolButton{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:8px;padding:4px 10px;}"
                f"QPushButton:enabled:hover,QToolButton:enabled:hover{{border-color:{_COLORFUL_ACCENT};}}"
                "QPushButton:pressed,QToolButton:pressed{background:#eee8f8;}"
                "QPushButton:disabled,QToolButton:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QMenu{background:#ffffff;color:#1f2330;border:1px solid #d6d9e6;}"
                f"QMenu::item:selected{{background:{_COLORFUL_ACCENT};color:#ffffff;}}"
                "QProgressBar{background:#ffffff;border:1px solid #d6d9e6;border-radius:6px;text-align:center;color:#1f2330;}"
                f"QProgressBar::chunk{{background:{_COLORFUL_ACCENT};border-radius:6px;}}"
                "QToolTip{background:#f6f0ff;color:#302347;border:1px solid #c9b4ec;}"
            )
        elif dark:
            theme_style = (
                "QWidget{background:#1f1f1f;color:#e6e6e6;}"
                "QLineEdit,QPlainTextEdit,QTextEdit,QAbstractSpinBox{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
                "QComboBox{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:2px 6px;}"
                "QComboBox:disabled,QAbstractSpinBox:disabled{background:#242424;color:#9aa0b3;border-color:#343434;}"
                "QPlainTextEdit:focus:!read-only,QTextEdit:focus:!read-only,"
                f"QComboBox:editable:focus{{border-bottom-color:{_DARK_FOCUS};}}"
                "QComboBox QAbstractItemView{background:#2a2a2a;color:#e6e6e6;selection-background-color:#343d54;}"
                "QRadioButton{color:#e6e6e6;}"
                "QRadioButton:disabled{color:#9aa0b3;}"
                "QPushButton,QToolButton{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:4px 8px;}"
                "QPushButton:hover,QToolButton:hover{background:#333333;}"
                "QPushButton:pressed,QToolButton:pressed{background:#3a3a3a;}"
                "QGroupBox{border:1px solid #3a3a3a;margin-top:10px;}"
                "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
                "QMenu{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
                f"QMenu::item:selected{{background:{_DARK_ACCENT};}}"
                "QProgressBar{background:#2a2a2a;border:1px solid #3a3a3a;text-align:center;color:#e6e6e6;}"
                f"QProgressBar::chunk{{background:{_DARK_ACCENT};}}"
                "QToolTip{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
            )
        app.setStyleSheet(theme_style + shared_style)
        self._refresh_background_panels()
        # Install the global tab padding first so the layout measures the styled height.
        self._refresh_function_tabbar_theme()
        self._apply_log_dialog_theme()
        for window in app.topLevelWidgets():
            if window is not self._log_dialog and window.isVisible():
                apply_x11_title_bar_theme(window, self._theme_mode == 'dark')

    def _apply_log_dialog_theme(self) -> None:
        if self._log_dialog is None:
            return
        mode = self._app_config.ui.log_theme
        fixed_mode = None if mode == 'follow' else mode
        self._log_dialog.setProperty('logWindowTheme', fixed_mode)
        self._log_dialog.set_theme(fixed_mode or self._theme_mode, _log_window_stylesheet(fixed_mode) if fixed_mode else '')

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
            if tooltip := widget.property('toolTipSource'):
                widget.setToolTip(self.t(tooltip))
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
                if default_label := widget.property('fontDefaultLabel'):
                    widget.setItemText(0, self.t(default_label))
                    continue
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
            if code == 'zh' and self._qt_translator is None:
                translator = QTranslator(self)
                translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
                if translator.load('qtbase_zh_CN', translations):
                    QApplication.installTranslator(translator)
                    self._qt_translator = translator
                else:
                    translator.deleteLater()
            elif code == 'en' and self._qt_translator is not None:
                QApplication.removeTranslator(self._qt_translator)
                self._qt_translator.deleteLater()
                self._qt_translator = None
            self.setWindowTitle(APP_TITLE)
            self._translate_widget_texts()
            self._tray_show_action.setText(self.t('Show main window'))
            self._tray_exit_action.setText(self.t('Exit'))
            if self._log_dialog is not None:
                self._log_dialog.retranslate()
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
