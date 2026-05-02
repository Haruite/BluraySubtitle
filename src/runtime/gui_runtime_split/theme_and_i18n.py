"""Target module for theme/language methods of `BluraySubtitleGUI`."""
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel, QSlider, QTabBar, QWidget, QPlainTextEdit, QLineEdit, QGroupBox, \
    QComboBox, QTableWidget

from src.core import APP_TITLE, CURRENT_UI_LANGUAGE
from src.core.i18n import translate_text
from .gui_base import BluraySubtitleGuiBase


class ThemeI18nMixin(BluraySubtitleGuiBase):
    def _window_opacity_supported(self) -> bool:
        app = QApplication.instance()
        if not app:
            return False
        platform_name = (app.platformName() or '').lower()
        # Wayland backend does not support per-window opacity in Qt.
        return 'wayland' not in platform_name

    def _set_window_opacity_if_supported(self, opacity: float):
        if not self._window_opacity_supported():
            return
        try:
            self.setWindowOpacity(opacity)
        except Exception:
            pass

    def t(self, text: str) -> str:
        return translate_text(str(text), getattr(self, '_language_code', CURRENT_UI_LANGUAGE))

    def _refresh_language_combo(self):
        if not hasattr(self, 'language_label') or not hasattr(self, 'language_combo'):
            return
        current_code = self.language_combo.currentData() or 'en'
        self.language_label.setText(self.t('Language'))
        self.language_combo.blockSignals(True)
        self.language_combo.setItemText(0, 'English')
        self.language_combo.setItemText(1, '简体中文')
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
        self._refresh_opacity_controls()

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
        size = max(8, min(24, int(point_size)))
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

    def _refresh_opacity_controls(self):
        label = getattr(self, 'opacity_label', None)
        slider = getattr(self, 'opacity_slider', None)
        visible = (
            getattr(self, '_theme_mode', 'light') == 'colorful'
            and self._window_opacity_supported()
        )
        if isinstance(label, QLabel):
            label.setText(self.t('Opacity'))
            label.setVisible(visible)
        if isinstance(slider, QSlider):
            slider.setVisible(visible)

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
        if self._theme_mode == 'light':
            self._set_window_opacity_if_supported(1.0)
            app.setStyleSheet(
                "QTabBar::tab:selected{background:#e6e6e6;color:#000000;border:1px solid #c8c8c8;}"
            )
            self._refresh_function_tabbar_theme()
            self._refresh_opacity_controls()
            return
        if self._theme_mode == 'colorful':
            opacity = float(getattr(self, '_colorful_opacity', 0.94) or 0.94)
            opacity = min(1.0, max(0.6, opacity))
            self._colorful_opacity = opacity
            self._set_window_opacity_if_supported(opacity)
            app.setStyleSheet(
                "QWidget{background:transparent;color:#1f2330;}"
                "QWidget#mainWindow{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #fff3c4,stop:0.55 #fffdf3,stop:1 #eef6ff);}"
                "QDialog{background:rgba(255,255,255,235);border:1px solid rgba(214,217,230,220);}"
                "QWidget:disabled{color:#8b92a8;}"
                "QLineEdit,QPlainTextEdit,QTextEdit{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:4px;}"
                "QLineEdit:disabled,QPlainTextEdit:disabled,QTextEdit:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QComboBox{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:4px;padding:2px 6px;}"
                "QComboBox:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QComboBox QAbstractItemView{background:#ffffff;color:#1f2330;selection-background-color:#7c3aed;selection-color:#ffffff;}"
                "QGroupBox{background:rgba(255,255,255,190);border:1px solid rgba(214,217,230,220);border-radius:8px;margin-top:10px;}"
                "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 6px;color:#7c3aed;}"
                "QRadioButton{color:#1f2330;}"
                "QRadioButton:disabled{color:#8b92a8;}"
                "QRadioButton::indicator{width:14px;height:14px;border-radius:7px;border:2px solid #7c3aed;background:rgba(255,255,255,220);}"
                "QRadioButton::indicator:checked{background:#7c3aed;border:2px solid #6d28d9;}"
                "QRadioButton::indicator:checked:hover{background:#6d28d9;}"
                "QRadioButton::indicator:unchecked:hover{border:2px solid #6d28d9;}"
                "QRadioButton::indicator:disabled{border:2px solid #c7cbe0;background:rgba(243,244,248,220);}"
                "QRadioButton::indicator:checked:disabled{border:2px solid #c7cbe0;background:rgba(199,203,224,220);}"
                "QCheckBox{color:#1f2330;}"
                "QCheckBox:disabled{color:#8b92a8;}"
                "QCheckBox::indicator{width:14px;height:14px;border-radius:3px;border:1px solid #7c3aed;background:#ffffff;}"
                "QCheckBox::indicator:checked{border:1px solid #6d28d9;background:#7c3aed;}"
                "QCheckBox::indicator:checked:hover{background:#6d28d9;}"
                "QCheckBox::indicator:disabled{border:1px solid #b8bfd6;background:#e5e7ef;}"
                "QSlider{background:transparent;}"
                "QSlider::groove:horizontal{height:6px;background:rgba(214,217,230,180);border-radius:3px;margin:0px;}"
                "QSlider::sub-page:horizontal{background:#7c3aed;border-radius:3px;}"
                "QSlider::add-page:horizontal{background:rgba(214,217,230,120);border-radius:3px;}"
                "QSlider::handle:horizontal{background:#ffffff;border:1px solid rgba(124,58,237,180);width:14px;margin:-6px 0px;border-radius:7px;}"
                "QSlider::handle:horizontal:hover{border:1px solid #6d28d9;}"
                "QTableWidget{gridline-color:#e2e4f0;background:rgba(255,255,255,210);alternate-background-color:rgba(246,244,255,210);selection-background-color:#34d399;selection-color:#0b1220;border-radius:6px;}"
                "QTableView::indicator{width:14px;height:14px;border-radius:3px;}"
                "QTableView::indicator:unchecked{border:1px solid #7c3aed;background:#ffffff;}"
                "QTableView::indicator:checked{border:1px solid #6d28d9;background:#7c3aed;}"
                "QTableView::indicator:disabled{border:1px solid #b8bfd6;background:#e5e7ef;}"
                "QTableWidget#table1{background:rgba(234,243,255,220);alternate-background-color:rgba(214,233,255,220);}"
                "QTableWidget#table2{background:rgba(240,255,246,220);alternate-background-color:rgba(220,250,232,220);}"
                "QTableWidget#table3{background:rgba(255,248,236,220);alternate-background-color:rgba(255,235,213,220);}"
                "QHeaderView::section{background:rgba(240,243,255,235);color:#1f2330;border:1px solid rgba(214,217,230,220);padding:4px;}"
                "QTableCornerButton::section{background:rgba(240,243,255,235);border:1px solid rgba(214,217,230,220);}"
                "QPushButton,QToolButton{background:rgba(255,255,255,220);color:#1f2330;border:1px solid rgba(214,217,230,220);border-radius:8px;padding:4px 10px;}"
                "QPushButton:hover,QToolButton:hover{border:1px solid #7c3aed;}"
                "QPushButton:pressed,QToolButton:pressed{background:#f2e9ff;}"
                "QToolButton:checked{background:#ffedd5;border:1px solid #fb923c;color:#7c2d12;}"
                "QToolButton:checked:hover{background:#fed7aa;}"
                "QPushButton:disabled,QToolButton:disabled{background:#f3f4f8;color:#8b92a8;border:1px solid #dde0ea;}"
                "QScrollBar:horizontal{background:#fbfbff;height:12px;margin:0px 14px 0px 14px;border:1px solid #d6d9e6;border-radius:5px;}"
                "QScrollBar::handle:horizontal{background:#a78bfa;min-width:24px;border-radius:4px;}"
                "QScrollBar::handle:horizontal:hover{background:#7c3aed;}"
                "QScrollBar::add-line:horizontal{background:#f0f3ff;width:14px;subcontrol-position:right;subcontrol-origin:margin;border:1px solid #d6d9e6;}"
                "QScrollBar::sub-line:horizontal{background:#f0f3ff;width:14px;subcontrol-position:left;subcontrol-origin:margin;border:1px solid #d6d9e6;}"
                "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:none;}"
                "QScrollBar:vertical{background:#fbfbff;width:12px;margin:14px 0px 14px 0px;border:1px solid #d6d9e6;border-radius:5px;}"
                "QScrollBar::handle:vertical{background:#a78bfa;min-height:24px;border-radius:4px;}"
                "QScrollBar::handle:vertical:hover{background:#7c3aed;}"
                "QScrollBar::add-line:vertical{background:#f0f3ff;height:14px;subcontrol-position:bottom;subcontrol-origin:margin;border:1px solid #d6d9e6;}"
                "QScrollBar::sub-line:vertical{background:#f0f3ff;height:14px;subcontrol-position:top;subcontrol-origin:margin;border:1px solid #d6d9e6;}"
                "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}"
                "QTableWidget#table1 QScrollBar::handle:horizontal{background:#60a5fa;}"
                "QTableWidget#table1 QScrollBar::handle:horizontal:hover{background:#2563eb;}"
                "QTableWidget#table1 QScrollBar::handle:vertical{background:#60a5fa;}"
                "QTableWidget#table1 QScrollBar::handle:vertical:hover{background:#2563eb;}"
                "QTableWidget#table2 QScrollBar::handle:horizontal{background:#34d399;}"
                "QTableWidget#table2 QScrollBar::handle:horizontal:hover{background:#059669;}"
                "QTableWidget#table2 QScrollBar::handle:vertical{background:#34d399;}"
                "QTableWidget#table2 QScrollBar::handle:vertical:hover{background:#059669;}"
                "QTableWidget#table3 QScrollBar::handle:horizontal{background:#fb923c;}"
                "QTableWidget#table3 QScrollBar::handle:horizontal:hover{background:#ea580c;}"
                "QTableWidget#table3 QScrollBar::handle:vertical{background:#fb923c;}"
                "QTableWidget#table3 QScrollBar::handle:vertical:hover{background:#ea580c;}"
                "QMenu{background:#ffffff;color:#1f2330;border:1px solid #d6d9e6;}"
                "QMenu::item:selected{background:#7c3aed;color:#ffffff;}"
                "QProgressBar{background:#ffffff;border:1px solid #d6d9e6;border-radius:6px;text-align:center;color:#1f2330;}"
                "QProgressBar::chunk{background:#34d399;border-radius:6px;}"
                "QTabBar::tab{background:#f0f3ff;color:#1f2330;border:1px solid #d6d9e6;border-bottom:none;padding:6px 10px;border-top-left-radius:6px;border-top-right-radius:6px;}"
                "QTabBar::tab:selected{background:#7c3aed;color:#ffffff;border:1px solid #6d28d9;border-bottom:none;}"
                "QToolTip{background:#1f2330;color:#ffffff;border:1px solid #7c3aed;}"
            )
            self._refresh_function_tabbar_theme()
            self._refresh_opacity_controls()
            return
        self._set_window_opacity_if_supported(1.0)
        app.setStyleSheet(
            "QWidget{background:#1f1f1f;color:#e6e6e6;}"
            "QLineEdit,QPlainTextEdit,QTextEdit{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
            "QComboBox{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:2px 6px;}"
            "QComboBox QAbstractItemView{background:#2a2a2a;color:#e6e6e6;selection-background-color:#3a5fcd;}"
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
            "QToolButton:checked{background:#3a5fcd;border:1px solid #5b7fff;color:#ffffff;}"
            "QToolButton:checked:hover{background:#4a6fe0;}"
            "QGroupBox{border:1px solid #3a3a3a;margin-top:10px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
            "QTableWidget{gridline-color:#3a3a3a;background:#202020;alternate-background-color:#242424;}"
            "QHeaderView::section{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;padding:4px;}"
            "QTableCornerButton::section{background:#2a2a2a;border:1px solid #3a3a3a;}"
            "QScrollBar:horizontal{background:#1f1f1f;height:12px;margin:0px 14px 0px 14px;border:1px solid #2b2b2b;}"
            "QScrollBar::handle:horizontal{background:#555555;min-width:24px;border-radius:4px;}"
            "QScrollBar::handle:horizontal:hover{background:#666666;}"
            "QScrollBar::add-line:horizontal{background:#2a2a2a;width:14px;subcontrol-position:right;subcontrol-origin:margin;border:1px solid #3a3a3a;}"
            "QScrollBar::sub-line:horizontal{background:#2a2a2a;width:14px;subcontrol-position:left;subcontrol-origin:margin;border:1px solid #3a3a3a;}"
            "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:none;}"
            "QScrollBar:vertical{background:#1f1f1f;width:12px;margin:14px 0px 14px 0px;border:1px solid #2b2b2b;}"
            "QScrollBar::handle:vertical{background:#555555;min-height:24px;border-radius:4px;}"
            "QScrollBar::handle:vertical:hover{background:#666666;}"
            "QScrollBar::add-line:vertical{background:#2a2a2a;height:14px;subcontrol-position:bottom;subcontrol-origin:margin;border:1px solid #3a3a3a;}"
            "QScrollBar::sub-line:vertical{background:#2a2a2a;height:14px;subcontrol-position:top;subcontrol-origin:margin;border:1px solid #3a3a3a;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}"
            "QMenu{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
            "QMenu::item:selected{background:#3a5fcd;}"
            "QProgressBar{background:#2a2a2a;border:1px solid #3a3a3a;text-align:center;color:#e6e6e6;}"
            "QProgressBar::chunk{background:#3a5fcd;}"
            "QToolTip{background:#2a2a2a;color:#e6e6e6;border:1px solid #3a3a3a;}"
        )
        self._refresh_function_tabbar_theme()
        self._refresh_opacity_controls()

    def _on_opacity_changed(self, value: int):
        try:
            v = int(value)
        except Exception:
            v = 96
        opacity = min(100, max(60, v)) / 100.0
        self._colorful_opacity = opacity
        if getattr(self, '_theme_mode', 'light') == 'colorful':
            self._set_window_opacity_if_supported(opacity)

    def _refresh_function_tabbar_theme(self):
        tabbar = getattr(self, 'function_tabbar', None)
        if not isinstance(tabbar, QTabBar):
            return
        mode = getattr(self, '_theme_mode', 'light')
        if mode == 'colorful':
            fid = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 1
            accent = {
                1: ('#0ea5e9', '#0284c7'),
                2: ('#14b8a6', '#0f766e'),
                3: ('#f59e0b', '#b45309'),
                4: ('#ef4444', '#b91c1c'),
                5: ('#8b5cf6', '#6d28d9'),
            }.get(int(fid), ('#7c3aed', '#6d28d9'))
            tabbar.setStyleSheet(
                "QTabBar::tab{background:#f0f3ff;color:#1f2330;border:1px solid #d6d9e6;border-bottom:none;"
                "padding:6px 10px;border-top-left-radius:6px;border-top-right-radius:6px;}"
                "QTabBar::tab:hover{background:#e6ecff;}"
                f"QTabBar::tab:selected{{background:{accent[0]};color:#ffffff;border:1px solid {accent[1]};"
                "border-bottom:none;font-weight:700;}"
            )
            return
        if mode == 'dark':
            tabbar.setStyleSheet(
                "QTabBar::tab{background:#2a2a2a;color:#cbd1e4;border:1px solid #3a3a3a;border-bottom:none;"
                "padding:6px 10px;border-top-left-radius:6px;border-top-right-radius:6px;}"
                "QTabBar::tab:hover{background:#32323a;color:#e6e6e6;}"
                "QTabBar::tab:selected{background:#3a5fcd;color:#ffffff;border:1px solid #5b7fff;"
                "border-bottom:none;font-weight:700;}"
            )
            return
        tabbar.setStyleSheet(
            "QTabBar::tab{background:#f5f6fb;color:#3a3f52;border:1px solid #d0d5e4;border-bottom:none;"
            "padding:6px 10px;border-top-left-radius:6px;border-top-right-radius:6px;}"
            "QTabBar::tab:hover{background:#eceffa;}"
            "QTabBar::tab:selected{background:#2563eb;color:#ffffff;border:1px solid #1d4ed8;"
            "border-bottom:none;font-weight:700;}"
        )

    def _on_theme_changed(self):
        mode = self.theme_combo.currentData() if hasattr(self, 'theme_combo') else 'light'
        self._apply_theme(str(mode))

    def _translate_widget_texts(self):
        for widget in self.findChildren(QWidget):
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
        global CURRENT_UI_LANGUAGE
        code = 'zh' if language_code == 'zh' else 'en'
        self._language_code = code
        CURRENT_UI_LANGUAGE = code
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
            if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) == 'zh':
                items = ["", ".zh-Hans", ".zh-Hant", ".chs", ".cht", ".sc", ".tc", ".big5", ".gb"]
            else:
                items = ["", "en", "eng", "en_US", "jpn", "jp", "kor"]
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
        if getattr(self, '_language_code', CURRENT_UI_LANGUAGE) != 'zh':
            en = {
                'edit_tracks': 'tracks',
                'extract': 'extract',
                'edit_chapters': 'chapters',
                'edit_attachments': 'attachments',
                'remux_cmd': 'remux cmd',
            }
            return [en.get(k, k) for k in keys]
        zh = {
            'path': '路径',
            'size': '大小',
            'info': '信息',
            'remux_cmd': '混流命令',
            'select': '选择',
            'sub_duration': '字幕时长',
            'warning': '提示',
            'tracks': '轨道',
            'bdmv_index': '原盘序号',
            'chapter_index': '章节序号',
            'start_at_chapter': '起始章节',
            'end_at_chapter': '结束章节',
            'offset': '偏移',
            'duration': '时长',
            'sub_path': '字幕路径',
            'ep_duration': '单集时长',
            'm2ts_file': 'm2ts 文件',
            'm2ts_type': 'm2ts 类型',
            'language': '语言',
            'sub_language': '字幕语言',
            'lang': '语言',
            'track_number': '轨道号',
            'track_uid': 'UID',
            'track_type': '类型',
            'codec_id': 'Codec ID',
            'convert': '转换',
            'channels': '声道',
            'bit_depth': '位深',
            'sampling_frequency': '采样率',
            'pixel_width': '宽度',
            'pixel_height': '高度',
            'default_duration': '默认时长',
            'extract': '提取',
            'edit_chapters': '编辑章节',
            'edit_attachments': '编辑附件',
            'filename': '文件名',
            'mime_type': 'MIME 类型',
            'uid': 'UID',
            'file_size': '文件大小',
            'id': 'ID',
            'output_name': '输出文件名',
            'vpy_path': 'vpy 路径',
            'edit_vpy': '编辑 vpy',
            'preview_script': '预览',
            'edit_tracks': '编辑轨道',
            'mpls_file': 'mpls 文件',
            'chapters': '章节',
            'main': '主播放列表',
            'play': '播放',
            'file': '文件',
            'index': '序号',
            'start': '开始',
            'end': '结束',
            'text': '内容',
        }
        return [zh.get(k, str(k).replace('_', ' ')) for k in keys]

    def _refresh_language_dependent_sizes(self):
        lang = getattr(self, '_language_code', CURRENT_UI_LANGUAGE)
        try:
            if hasattr(self, 'table1') and self.table1:
                function_id = self.get_selected_function_id() if hasattr(self, 'get_selected_function_id') else 0
                if function_id in (3, 4, 5):
                    self.table1.setColumnWidth(2, 620 if lang == 'zh' else 560)
                else:
                    self.table1.setColumnWidth(2, 420 if lang == 'zh' else 370)
                for r in range(self.table1.rowCount()):
                    info_table = self.table1.cellWidget(r, 2)
                    if isinstance(info_table, QTableWidget):
                        info_table.resizeColumnsToContents()
        except Exception:
            pass

        try:
            if hasattr(self, 'x265_preset_combo') and self.x265_preset_combo:
                self._adjust_combo_width_to_contents(self.x265_preset_combo)
        except Exception:
            pass

        try:
            if hasattr(self, 'approx_episode_minutes_combo') and self.approx_episode_minutes_combo:
                self._adjust_combo_width_to_contents(self.approx_episode_minutes_combo, padding=54, min_width=120,
                                                     max_width=220)
        except Exception:
            pass

        try:
            if hasattr(self, 'table2') and self.table2:
                self._resize_table_columns_for_language(self.table2)
        except Exception:
            pass

        try:
            if hasattr(self, 'table3') and self.table3:
                self._resize_table_columns_for_language(self.table3)
        except Exception:
            pass

        try:
            if hasattr(self, 'table1') and self.table1:
                for r in range(self.table1.rowCount()):
                    info_table = self.table1.cellWidget(r, 2)
                    if isinstance(info_table, QTableWidget):
                        self._resize_table_columns_for_language(info_table)
        except Exception:
            pass
