"""Target module for lifecycle/bootstrap methods of `BluraySubtitleGUI`."""

if __name__ == "__main__" and __package__ is None:
    import sys

    sys.stderr.write(
        "This file is a mixin, not an entry point. From the repository root run:\n"
        "  python -m src.main\n"
    )
    raise SystemExit(1)

import os
import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QCoreApplication
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget, QHBoxLayout, QLabel, QComboBox, QSlider, QGroupBox, \
    QLineEdit, QTabBar, QRadioButton, QButtonGroup, QPushButton, QCheckBox, QTableWidget, QSizePolicy, QSplitter, \
    QProgressDialog, QProgressBar, QFileDialog

from src.core import APP_TITLE, BDMV_LABELS, SUBTITLE_LABELS, ENCODE_SP_LABELS
from src.exports.utils import print_exc_terminal, force_remove_file
from src.runtime.gui_runtime_classes.custom_box import CustomBox
from src.runtime.gui_runtime_classes.custom_table_widget import CustomTableWidget
from .gui_base import BluraySubtitleGuiBase


class LifecycleBootstrapMixin(BluraySubtitleGuiBase):
    def __init__(self):
        super().__init__()
        self.setObjectName('mainWindow')
        self.altered = False
        self._sp_index_by_bdmv: dict[int, int] = {}
        self._chapter_checkbox_states: dict[str, list[bool]] = {}  # Save chapter checkbox states
        self._last_config_inputs: dict[str, object] = {}
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(APP_TITLE)
        self.setMinimumWidth(860)
        self.setMinimumHeight(820)
        self.resize(1000, 1000)
        self._geometry = self.saveGeometry()
        self._language_code = 'en'
        global CURRENT_UI_LANGUAGE
        CURRENT_UI_LANGUAGE = 'en'

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.delete_default_vpy_file)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(6)

        language_row = QWidget(self)
        language_layout = QHBoxLayout()
        language_layout.setContentsMargins(8, 0, 8, 0)
        language_layout.setSpacing(6)
        language_row.setLayout(language_layout)
        self.language_label = QLabel('Language', language_row)
        self.language_combo = QComboBox(language_row)
        self.language_combo.addItem('English', 'en')
        self.language_combo.addItem('简体中文', 'zh')
        self.language_combo.setCurrentIndex(0)
        self.language_combo.currentIndexChanged.connect(lambda _=None: self._on_language_changed())
        language_layout.addWidget(self.language_label)
        language_layout.addWidget(self.language_combo)
        language_layout.addSpacing(12)
        self.theme_label = QLabel('Mode', language_row)
        self.theme_combo = QComboBox(language_row)
        self.theme_combo.addItem('Light', 'light')
        self.theme_combo.addItem('Dark', 'dark')
        self.theme_combo.addItem('Colorful', 'colorful')
        self.theme_combo.setCurrentIndex(0)
        self.theme_combo.currentIndexChanged.connect(lambda _=None: self._on_theme_changed())
        language_layout.addWidget(self.theme_label)
        language_layout.addWidget(self.theme_combo)
        language_layout.addSpacing(12)
        self.font_size_label = QLabel('UI Font', language_row)
        self.font_size_combo = QComboBox(language_row)
        self.font_size_combo.addItem('6', 6)
        self.font_size_combo.addItem('7', 7)
        self.font_size_combo.addItem('8', 8)
        self.font_size_combo.addItem('9', 9)
        self.font_size_combo.addItem('10', 10)
        self.font_size_combo.addItem('11', 11)
        self.font_size_combo.addItem('12', 12)
        self.font_size_combo.addItem('13', 13)
        self.font_size_combo.addItem('14', 14)
        self.font_size_combo.setCurrentIndex(1)
        self.font_size_combo.currentIndexChanged.connect(lambda _=None: self._on_font_size_changed())
        self._apply_ui_font_size(10)
        language_layout.addWidget(self.font_size_label)
        language_layout.addWidget(self.font_size_combo)
        language_layout.addSpacing(12)
        self.opacity_label = QLabel('Opacity', language_row)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, language_row)
        self.opacity_slider.setRange(60, 100)
        self.opacity_slider.setValue(int(getattr(self, '_colorful_opacity', 0.94) * 100))
        self.opacity_slider.setFixedWidth(140)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.opacity_slider.sliderReleased.connect(
            lambda: self.opacity_slider.setValue(
                100 if self.opacity_slider.value() >= 99 else self.opacity_slider.value())
        )
        language_layout.addWidget(self.opacity_label)
        language_layout.addWidget(self.opacity_slider)
        language_layout.addStretch(1)
        self.layout.addWidget(language_row)

        function_button = QGroupBox(self.t('Function'), self)
        self.function_button = function_button
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(8, 10, 8, 6)
        h_layout.setSpacing(12)
        function_button.setLayout(h_layout)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)

        self.function_tabbar = QTabBar(function_button)
        self.function_tabbar.setObjectName('functionTabbar')
        self.function_tabbar.setExpanding(True)
        self.function_tabbar.setMovable(False)
        self.function_tabbar.setDocumentMode(True)
        self.function_tabbar.addTab(self.t("Blu-ray Remux"))
        self.function_tabbar.addTab(self.t("Blu-ray Encode"))
        self.function_tabbar.addTab(self.t("Blu-ray DIY"))
        self.function_tabbar.addTab(self.t("Merge Subtitles"))
        self.function_tabbar.addTab(self.t("Add Chapters To MKV"))
        self.function_tabbar.setCurrentIndex(0)
        self._function_id_order = [3, 4, 5, 1, 2]
        self._selected_function_id = 3
        self.function_tabbar.currentChanged.connect(lambda _=None: self.on_select_function())
        h_layout.addWidget(self.function_tabbar)
        self.layout.addWidget(function_button)

        self.diy_mode_row = QWidget(self)
        self.diy_mode_row.setProperty("noMargin", True)
        diy_mode_layout = QHBoxLayout()
        diy_mode_layout.setContentsMargins(8, 0, 8, 0)
        diy_mode_layout.setSpacing(6)
        self.diy_mode_row.setLayout(diy_mode_layout)
        self.diy_mode_label = QLabel("Select:", self.diy_mode_row)
        self.diy_simple_radio = QRadioButton("Simple DIY", self.diy_mode_row)
        self.diy_advanced_radio = QRadioButton("Advanced DIY", self.diy_mode_row)
        self.diy_simple_radio.setChecked(True)
        diy_mode_layout.addWidget(self.diy_mode_label)
        diy_mode_layout.addWidget(self.diy_simple_radio)
        diy_mode_layout.addWidget(self.diy_advanced_radio)
        diy_mode_layout.addStretch(1)
        diy_mode_group = QButtonGroup(self.diy_mode_row)
        diy_mode_group.addButton(self.diy_simple_radio)
        diy_mode_group.addButton(self.diy_advanced_radio)
        self._diy_mode_group = diy_mode_group
        self.diy_simple_radio.toggled.connect(lambda _=None: self.on_select_function(force=True, keep_inputs=True, keep_state=True))
        self.diy_advanced_radio.toggled.connect(lambda _=None: self.on_select_function(force=True, keep_inputs=True, keep_state=True))
        self.diy_mode_row.setVisible(self.get_selected_function_id() == 5)
        self.layout.addWidget(self.diy_mode_row)

        mode_row = QWidget(self)
        mode_row.setProperty("noMargin", True)
        mode_layout = QHBoxLayout()
        mode_layout.setContentsMargins(8, 0, 8, 0)
        mode_layout.setSpacing(6)
        mode_row.setLayout(mode_layout)

        self.series_mode_radio = QRadioButton("Series mode", mode_row)
        self.movie_mode_radio = QRadioButton("Movie mode", mode_row)
        self.series_mode_radio.setChecked(True)

        mode_layout.addWidget(self.series_mode_radio)

        self.episode_length_container = QWidget(mode_row)
        episode_length_layout = QHBoxLayout()
        episode_length_layout.setContentsMargins(0, 0, 0, 0)
        episode_length_layout.setSpacing(4)
        self.episode_length_container.setLayout(episode_length_layout)
        episode_length_layout.addWidget(QLabel("（", self.episode_length_container))
        episode_length_layout.addWidget(QLabel("Approx. episode length (minutes):", self.episode_length_container))
        self.approx_episode_minutes_combo = QComboBox(self.episode_length_container)
        self.approx_episode_minutes_combo.setEditable(True)
        self.approx_episode_minutes_combo.addItems(["3", "24", "50"])
        self.approx_episode_minutes_combo.setCurrentText("24")
        self.approx_episode_minutes_combo.setMinimumWidth(120)
        self._adjust_combo_width_to_contents(self.approx_episode_minutes_combo, padding=54, min_width=120,
                                             max_width=220)
        episode_length_layout.addWidget(self.approx_episode_minutes_combo)
        episode_length_layout.addWidget(QLabel("）", self.episode_length_container))
        mode_layout.addWidget(self.episode_length_container)

        mode_layout.addSpacing(8)
        mode_layout.addWidget(self.movie_mode_radio)
        mode_layout.addStretch(1)

        mode_group = QButtonGroup(mode_row)
        mode_group.addButton(self.series_mode_radio)
        mode_group.addButton(self.movie_mode_radio)
        self._mode_group = mode_group

        def update_episode_length_enabled_state():
            enabled = self.series_mode_radio.isChecked()
            self.approx_episode_minutes_combo.setEnabled(enabled)
            self._apply_episode_mode_to_table2()
            if self.get_selected_function_id() in (3, 4, 5):
                try:
                    self._refresh_table1_remux_cmds()
                except Exception:
                    pass

        self.series_mode_radio.toggled.connect(update_episode_length_enabled_state)
        self.movie_mode_radio.toggled.connect(update_episode_length_enabled_state)
        update_episode_length_enabled_state()

        self.episode_mode_row = mode_row
        self.episode_mode_row.setVisible(self.get_selected_function_id() in (1, 3, 4, 5))
        self.approx_episode_minutes_combo.currentTextChanged.connect(
            lambda _=None: self._rebuild_configuration_for_function_34())
        self.layout.addWidget(self.episode_mode_row)

        bdmv = QGroupBox()
        bdmv.setProperty("noTitle", True)
        bdmv_top = QVBoxLayout()
        bdmv_top.setContentsMargins(8, 2, 8, 6)
        bdmv_top.setSpacing(4)
        bdmv.setLayout(bdmv_top)

        self.bdmv_path_row = QWidget(self)
        bdmv_path_outer = QHBoxLayout(self.bdmv_path_row)
        bdmv_path_outer.setContentsMargins(0, 0, 0, 0)
        bdmv_path_outer.setSpacing(4)
        self.bdmv_path_label = QLabel('Select the BDMV folder', self)
        bdmv_path_outer.addWidget(self.bdmv_path_label)

        bluray_path_box = CustomBox('Blu-ray', self)
        bluray_path_box.setProperty("noMargin", True)
        self.bluray_path_box = bluray_path_box
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(4)
        bluray_path_box.setLayout(h_layout)
        self.bdmv_folder_path = QLineEdit()
        self.bdmv_folder_path.setMinimumWidth(200)
        self.bdmv_folder_path.setAcceptDrops(False)
        button1 = QPushButton('Select')
        button1.clicked.connect(self.select_bdmv_folder)
        button1_open = QPushButton('Open')
        button1_open.clicked.connect(lambda _=None: self.open_folder_path(self.bdmv_folder_path.text()))
        h_layout.addWidget(self.bdmv_folder_path)
        h_layout.addWidget(button1)
        h_layout.addWidget(button1_open)
        bdmv_path_outer.addWidget(bluray_path_box, 1)
        self.layout.addWidget(self.bdmv_path_row)

        remux_path_box = CustomBox('Remux', self)
        remux_path_box.setProperty("noMargin", True)
        remux_layout = QHBoxLayout()
        remux_layout.setContentsMargins(0, 0, 0, 0)
        remux_layout.setSpacing(4)
        remux_path_box.setLayout(remux_layout)
        self.remux_folder_path = QLineEdit()
        self.remux_folder_path.setMinimumWidth(200)
        self.remux_folder_path.setAcceptDrops(False)
        self.remux_folder_path.textChanged.connect(
            lambda _=None: QTimer.singleShot(150, self._populate_encode_from_remux_folder))
        remux_btn = QPushButton('Select')
        remux_btn.clicked.connect(self.select_remux_folder)
        remux_btn_open = QPushButton('Open')
        remux_btn_open.clicked.connect(lambda _=None: self.open_folder_path(self.remux_folder_path.text()))
        remux_layout.addWidget(self.remux_folder_path)
        remux_layout.addWidget(remux_btn)
        remux_layout.addWidget(remux_btn_open)
        self.remux_path_box = remux_path_box
        self.remux_path_box.setVisible(False)
        bdmv_path_outer.addWidget(remux_path_box, 1)

        label1_container = QWidget(self)
        self.label1_container = label1_container
        label1_layout = QVBoxLayout()
        label1_layout.setContentsMargins(0, 0, 0, 0)
        label1_layout.setSpacing(0)
        label1_container.setLayout(label1_layout)
        self.label1 = QLabel('Select folder', self)
        self.label1.setText(self.t('Select folder'))

        encode_source_row = QWidget(self)
        encode_source_layout = QHBoxLayout()
        encode_source_layout.setContentsMargins(0, 0, 0, 0)
        encode_source_layout.setSpacing(8)
        encode_source_row.setLayout(encode_source_layout)
        encode_source_layout.addWidget(self.label1)
        self.encode_source_bdmv_radio = QRadioButton('Blu-ray', encode_source_row)
        self.encode_source_remux_radio = QRadioButton('Remux', encode_source_row)
        self.encode_source_bdmv_radio.setChecked(True)
        encode_source_layout.addWidget(self.encode_source_bdmv_radio)
        encode_source_layout.addWidget(self.encode_source_remux_radio)
        encode_source_layout.addStretch(1)
        self.encode_source_row = encode_source_row
        self.encode_source_row.setVisible(self.get_selected_function_id() == 4)
        self._encode_input_mode = 'bdmv'

        def on_encode_source_changed():
            self._encode_input_mode = 'remux' if self.encode_source_remux_radio.isChecked() else 'bdmv'
            try:
                self._apply_encode_input_mode_ui()
            except Exception:
                print_exc_terminal()

        self.encode_source_bdmv_radio.toggled.connect(on_encode_source_changed)
        self.encode_source_remux_radio.toggled.connect(on_encode_source_changed)
        label1_layout.addWidget(bdmv)

        bdmv_body = QWidget(bdmv)
        v_layout = QVBoxLayout(bdmv_body)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(4)

        select_all_tracks_row = QWidget(self)
        select_all_tracks_layout = QHBoxLayout()
        select_all_tracks_layout.setContentsMargins(0, 0, 0, 0)
        select_all_tracks_layout.setSpacing(8)
        select_all_tracks_row.setLayout(select_all_tracks_layout)
        self.select_all_tracks_checkbox = QCheckBox(self.t('Select all tracks'), select_all_tracks_row)
        self.select_all_tracks_checkbox.setChecked(False)
        self.select_all_tracks_checkbox.toggled.connect(self._on_select_all_tracks_toggled)
        select_all_tracks_layout.addWidget(self.select_all_tracks_checkbox)
        select_all_tracks_layout.addStretch(1)
        self.select_all_tracks_row = select_all_tracks_row
        self.layout.addWidget(select_all_tracks_row)

        self.table1 = QTableWidget()
        self.table1.setObjectName('table1')
        self.table1.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table1.setColumnCount(len(BDMV_LABELS))
        self._set_table_headers(self.table1, BDMV_LABELS)
        self.table1.setSortingEnabled(True)
        self.table1.horizontalHeader().setSortIndicatorShown(True)
        self.bdmv_folder_path.textChanged.connect(self.on_bdmv_folder_path_change)
        v_layout.addWidget(self.table1)
        v_layout.setStretch(v_layout.indexOf(self.table1), 1)
        bdmv_top.addWidget(bdmv_body, 1)
        try:
            idx = self.layout.indexOf(self.episode_mode_row)
            if idx >= 0:
                self.layout.insertWidget(idx, self.encode_source_row)
            else:
                self.layout.insertWidget(1, self.encode_source_row)
        except Exception:
            self.layout.insertWidget(1, self.encode_source_row)

        subtitle = QGroupBox()
        subtitle.setProperty("noTitle", True)
        subtitle_inner_layout = QVBoxLayout()
        subtitle_inner_layout.setContentsMargins(8, 2, 8, 6)
        subtitle_inner_layout.setSpacing(4)
        subtitle.setLayout(subtitle_inner_layout)

        label2_container = QWidget(self)
        self.label2_container = label2_container
        self._label2_outer_layout = QVBoxLayout()
        self._label2_outer_layout.setContentsMargins(0, 0, 0, 0)
        self._label2_outer_layout.setSpacing(0)
        label2_container.setLayout(self._label2_outer_layout)

        self.subtitle_hint_row = QWidget(label2_container)
        subtitle_hint_outer = QHBoxLayout(self.subtitle_hint_row)
        subtitle_hint_outer.setContentsMargins(8, 2, 8, 0)
        subtitle_hint_outer.setSpacing(4)
        self.subtitle_formats_hint_label = QLabel(self.t('Supports ass/ssa/srt/sup formats            '), self.subtitle_hint_row)
        subtitle_hint_outer.addWidget(self.subtitle_formats_hint_label)
        self.subtitle_convert_checkbox = QCheckBox(self.t('Convert srt -> ass -> sup'), self.subtitle_hint_row)
        self.subtitle_convert_checkbox.setChecked(False)
        subtitle_hint_outer.addWidget(self.subtitle_convert_checkbox)
        self.subtitle_bluray_compat_checkbox = QCheckBox(self.t('Blu-ray compatible'), self.subtitle_hint_row)
        self.subtitle_bluray_compat_checkbox.setChecked(False)
        self.subtitle_bluray_compat_checkbox.toggled.connect(lambda _=None: self._save_simple_diy_subtitle_config())
        subtitle_hint_outer.addWidget(self.subtitle_bluray_compat_checkbox)
        subtitle_hint_outer.addStretch(1)

        self.subtitle_label_row = QWidget(label2_container)
        subtitle_label_outer = QHBoxLayout(self.subtitle_label_row)
        subtitle_label_outer.setContentsMargins(8, 2, 8, 0)
        subtitle_label_outer.setSpacing(4)
        self.label2 = QLabel('Select the subtitle folder', self)
        subtitle_label_outer.addWidget(self.label2)
        subtitle_label_outer.addStretch(1)

        self.subtitle_path_row = QWidget(label2_container)
        subtitle_path_outer = QHBoxLayout(self.subtitle_path_row)
        subtitle_path_outer.setContentsMargins(8, 2, 8, 2)
        subtitle_path_outer.setSpacing(4)

        subtitle_path_box = CustomBox('Subtitles', self)
        subtitle_path_box.setProperty("noMargin", True)
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(4)
        subtitle_path_box.setLayout(h_layout)
        self.subtitle_folder_path = QLineEdit()
        self.subtitle_folder_path.setMinimumWidth(200)
        self.subtitle_folder_path.setAcceptDrops(False)
        button2 = QPushButton('Select')
        button2.clicked.connect(self.select_subtitle_folder)
        button2_open = QPushButton('Open')
        button2_open.clicked.connect(lambda _=None: self.open_folder_path(self.subtitle_folder_path.text()))
        h_layout.addWidget(self.subtitle_folder_path)
        h_layout.addWidget(button2)
        h_layout.addWidget(button2_open)
        self.subtitle_path_box = subtitle_path_box
        subtitle_path_outer.addWidget(subtitle_path_box, 1)
        self.simple_diy_sub_lang_label = QLabel(self.t('Language'), self.subtitle_path_row)
        self.simple_diy_sub_lang_label.setVisible(False)
        subtitle_path_outer.addWidget(self.simple_diy_sub_lang_label)
        self.simple_diy_sub_lang_combo = QComboBox(self.subtitle_path_row)
        self.simple_diy_sub_lang_combo.addItems(['und', 'chi', 'eng', 'jpn'])
        self.simple_diy_sub_lang_combo.setEditable(True)
        self.simple_diy_sub_lang_combo.setCurrentText('eng')
        self.simple_diy_sub_lang_combo.setVisible(False)
        self.simple_diy_sub_lang_combo.currentIndexChanged.connect(
            lambda _=None: self._save_simple_diy_subtitle_config()
        )
        subtitle_path_outer.addWidget(self.simple_diy_sub_lang_combo)
        self.simple_diy_remove_sub_row_btn = QPushButton('-', self.subtitle_path_row)
        self.simple_diy_remove_sub_row_btn.setFixedWidth(28)
        self.simple_diy_remove_sub_row_btn.setVisible(False)
        subtitle_path_outer.addWidget(self.simple_diy_remove_sub_row_btn)
        self.simple_diy_add_sub_row_btn = QPushButton('+', self.subtitle_path_row)
        self.simple_diy_add_sub_row_btn.setFixedWidth(28)
        self.simple_diy_add_sub_row_btn.setVisible(False)
        subtitle_path_outer.addWidget(self.simple_diy_add_sub_row_btn)
        self.subtitle_formats_hint_label.setVisible(False)
        self.subtitle_convert_checkbox.setVisible(False)
        self.subtitle_hint_row.setVisible(False)

        self.simple_diy_extra_sub_rows = QWidget(label2_container)
        self.simple_diy_extra_sub_rows_layout = QVBoxLayout(self.simple_diy_extra_sub_rows)
        self.simple_diy_extra_sub_rows_layout.setContentsMargins(8, 0, 8, 0)
        self.simple_diy_extra_sub_rows_layout.setSpacing(4)
        self.simple_diy_extra_sub_rows.setVisible(False)
        self._simple_diy_sub_rows: list[dict[str, object]] = []

        def _default_diy_sub_lang() -> str:
            return 'chi' if getattr(self, '_language_code', 'en') == 'zh' else 'eng'

        def _refresh_simple_diy_sub_row_buttons():
            rows = [None] + list(self._simple_diy_sub_rows)
            last_idx = len(rows) - 1
            for i, row_info in enumerate(rows):
                if i == 0:
                    add_btn = self.simple_diy_add_sub_row_btn
                    del_btn = self.simple_diy_remove_sub_row_btn
                else:
                    add_btn = row_info.get('add_btn')
                    del_btn = row_info.get('del_btn')
                if add_btn:
                    add_btn.setVisible(i == last_idx)
                if del_btn:
                    del_btn.setVisible(i == last_idx and len(rows) > 1)

        def _add_simple_diy_sub_row():
            row = QWidget(self.simple_diy_extra_sub_rows)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            box = CustomBox('Subtitle', row)
            box.setProperty("noMargin", True)
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            box.setLayout(h)
            edit = QLineEdit()
            edit.setMinimumWidth(200)
            btn_sel = QPushButton('Select')
            btn_open = QPushButton('Open')
            def _pick_folder(target_edit: QLineEdit):
                picked = QFileDialog.getExistingDirectory(self, self.t('Select folder'))
                if picked:
                    target_edit.setText(os.path.normpath(picked))
            btn_sel.clicked.connect(lambda _=None, e=edit: _pick_folder(e))
            btn_open.clicked.connect(lambda _=None, e=edit: self.open_folder_path(e.text()))
            h.addWidget(edit)
            h.addWidget(btn_sel)
            h.addWidget(btn_open)
            lang_label = QLabel(self.t('Language'), row)
            lang = QComboBox(row)
            lang.addItems(['und', 'chi', 'eng', 'jpn'])
            lang.setEditable(True)
            lang.setCurrentText(_default_diy_sub_lang())
            lang.currentIndexChanged.connect(lambda _=None: self._save_simple_diy_subtitle_config())
            btn_del = QPushButton('-', row)
            btn_del.setFixedWidth(28)
            btn_add = QPushButton('+', row)
            btn_add.setFixedWidth(28)
            btn_add.clicked.connect(_add_simple_diy_sub_row)
            def _remove_this_row():
                try:
                    self.simple_diy_extra_sub_rows_layout.removeWidget(row)
                except Exception:
                    pass
                row.setParent(None)
                row.deleteLater()
                self._simple_diy_sub_rows = [x for x in self._simple_diy_sub_rows if x.get('row') is not row]
                _refresh_simple_diy_sub_row_buttons()
                self._save_simple_diy_subtitle_config()
            btn_del.clicked.connect(_remove_this_row)
            row_layout.addWidget(box, 1)
            row_layout.addWidget(lang_label)
            row_layout.addWidget(lang)
            row_layout.addWidget(btn_del)
            row_layout.addWidget(btn_add)
            self.simple_diy_extra_sub_rows_layout.addWidget(row)
            self._simple_diy_sub_rows.append({
                'row': row,
                'edit': edit,
                'lang': lang,
                'lang_label': lang_label,
                'add_btn': btn_add,
                'del_btn': btn_del,
            })
            edit.textChanged.connect(lambda _=None: self._save_simple_diy_subtitle_config())
            _refresh_simple_diy_sub_row_buttons()
            self._save_simple_diy_subtitle_config()

        self.simple_diy_add_sub_row_btn.clicked.connect(_add_simple_diy_sub_row)
        self.simple_diy_remove_sub_row_btn.clicked.connect(
            lambda _=None: (
                self._simple_diy_sub_rows and
                self._simple_diy_sub_rows[-1].get('del_btn') and
                self._simple_diy_sub_rows[-1]['del_btn'].click()
            )
        )
        self.subtitle_folder_path.textChanged.connect(lambda _=None: self._save_simple_diy_subtitle_config())
        self.simple_diy_sub_lang_combo.setCurrentText(_default_diy_sub_lang())
        _refresh_simple_diy_sub_row_buttons()

        self.track_scope_row = QWidget(label2_container)
        track_scope_outer = QHBoxLayout(self.track_scope_row)
        track_scope_outer.setContentsMargins(8, 0, 8, 2)
        track_scope_outer.setSpacing(4)
        self.track_scope_label = QLabel(self.t('Track edit scope：'), self.track_scope_row)
        self.track_scope_main_radio = QRadioButton(self.t('Main mpls'), self.track_scope_row)
        self.track_scope_all_radio = QRadioButton(self.t('All'), self.track_scope_row)
        self.track_scope_all_radio.setChecked(True)
        self.track_scope_main_radio.toggled.connect(
            lambda _=None: self.on_bdmv_folder_path_change() if self.get_selected_function_id() == 5 else None
        )
        self.track_scope_all_radio.toggled.connect(
            lambda _=None: self.on_bdmv_folder_path_change() if self.get_selected_function_id() == 5 else None
        )
        track_scope_outer.addWidget(self.track_scope_label)
        track_scope_outer.addWidget(self.track_scope_main_radio)
        track_scope_outer.addWidget(self.track_scope_all_radio)
        track_scope_outer.addStretch(1)
        self.track_scope_row.setVisible(False)

        self.table2 = CustomTableWidget(self, self.on_subtitle_drop)
        self.table2.setObjectName('table2')
        self.table2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._set_compact_table(self.table2, row_height=22, header_height=22)
        self.table2.setColumnCount(len(SUBTITLE_LABELS))
        self._set_table_headers(self.table2, SUBTITLE_LABELS)
        self._set_table2_subtitle_column_order()
        self.table2.setSortingEnabled(True)
        self.table2.horizontalHeader().setSortIndicatorShown(True)
        self.table2.horizontalHeader().sortIndicatorChanged.connect(self.on_subtitle_table_sorted)
        self.subtitle_folder_path.textChanged.connect(self.on_subtitle_folder_path_change)
        self._subtitle_scan_debounce = QTimer(self)
        self._subtitle_scan_debounce.setSingleShot(True)
        self._subtitle_scan_debounce.setInterval(250)
        self._subtitle_scan_debounce.timeout.connect(self._start_subtitle_folder_scan)
        self._pending_subtitle_folder = ''
        self._chapter_combo_debounce = QTimer(self)
        self._chapter_combo_debounce.setSingleShot(True)
        self._chapter_combo_debounce.setInterval(120)
        self._chapter_combo_debounce.timeout.connect(self._run_chapter_combo_update)
        self._pending_chapter_combo_index = -1
        self.table3 = QTableWidget(self)
        self.table3.setObjectName('table3')
        self.table3.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._set_compact_table(self.table3, row_height=22, header_height=22)
        self.table3.setColumnCount(len(ENCODE_SP_LABELS))
        self._set_table_headers(self.table3, ENCODE_SP_LABELS)
        self.table3.setSortingEnabled(True)
        self.table3.horizontalHeader().setSortIndicatorShown(True)
        self._updating_sp_table = False
        self.table3.itemChanged.connect(self._on_table3_item_changed)
        self.table3.setVisible(False)
        self.subtitle_tables_splitter = QSplitter(Qt.Orientation.Vertical, subtitle)
        self.subtitle_tables_splitter.setObjectName('subtitleTablesSplitter')
        self.subtitle_tables_splitter.setChildrenCollapsible(False)
        self.subtitle_tables_splitter.addWidget(self.table2)
        self.subtitle_tables_splitter.addWidget(self.table3)
        self.subtitle_tables_splitter.setStretchFactor(0, 1)
        self.subtitle_tables_splitter.setStretchFactor(1, 1)
        self.subtitle_tables_splitter.setSizes([360, 360])
        subtitle_inner_layout.addWidget(self.subtitle_tables_splitter)
        subtitle_inner_layout.setStretch(
            subtitle_inner_layout.indexOf(self.subtitle_tables_splitter), 1)

        self._subtitle_tables_host = subtitle
        self._label2_outer_layout.addWidget(subtitle)

        label1_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        label2_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        bdmv.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tables_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.tables_splitter = tables_splitter
        tables_splitter.setObjectName('tablesSplitter')
        tables_splitter.setChildrenCollapsible(False)
        tables_splitter.addWidget(label1_container)
        tables_splitter.addWidget(label2_container)
        tables_splitter.setStretchFactor(0, 1)
        tables_splitter.setStretchFactor(1, 1)
        tables_splitter.setSizes([480, 480])
        self.layout.addWidget(tables_splitter)
        self.layout.setStretch(self.layout.indexOf(tables_splitter), 1)

        self.encode_box = QGroupBox('Encode', self)
        self.encode_box.setProperty("tightGroup", True)
        self.encode_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.encode_box.setVisible(False)
        self.init_encode_box()
        self.layout.addWidget(self.encode_box)

        self.checkbox1 = QCheckBox("Complete Blu-ray Folder")
        self.checkbox1.setChecked(True)
        merge_options_row = QWidget(self)
        merge_options_row.setProperty("noMargin", True)
        merge_options_layout = QHBoxLayout()
        merge_options_layout.setContentsMargins(8, 0, 8, 0)
        merge_options_layout.setSpacing(6)
        merge_options_row.setLayout(merge_options_layout)
        merge_options_layout.addWidget(self.checkbox1)
        merge_options_layout.addSpacing(12)

        self.subtitle_suffix_label = QLabel("Add suffix", merge_options_row)
        merge_options_layout.addWidget(self.subtitle_suffix_label)
        self.subtitle_suffix_combo = QComboBox(merge_options_row)
        self.subtitle_suffix_combo.setEditable(True)
        self.subtitle_suffix_combo.setMinimumWidth(160)
        merge_options_layout.addWidget(self.subtitle_suffix_combo)
        merge_options_layout.addStretch(1)
        self.merge_options_row = merge_options_row
        self.merge_options_row.setVisible(self.get_selected_function_id() == 1)
        self._refresh_subtitle_suffix_options()
        self.layout.addWidget(self.merge_options_row)
        output_path_row = QWidget(self)
        output_path_row.setProperty("noMargin", True)
        output_path_layout = QHBoxLayout()
        output_path_layout.setContentsMargins(8, 0, 8, 0)
        output_path_layout.setSpacing(4)
        output_path_row.setLayout(output_path_layout)
        output_path_layout.addWidget(QLabel("Output Folder", self))
        self.output_folder_path = QLineEdit()
        self.output_folder_path.setMinimumWidth(200)
        self.output_folder_path.setAcceptDrops(False)
        self._auto_output_folder = ''
        self.output_folder_path.textEdited.connect(lambda _: setattr(self, '_output_folder_user_edited', True))
        self._remux_cmd_refresh_timer = QTimer(self)
        self._remux_cmd_refresh_timer.setSingleShot(True)
        self._remux_cmd_refresh_timer.setInterval(300)
        self._remux_cmd_refresh_timer.timeout.connect(
            lambda: self._refresh_table1_remux_cmds() if self.get_selected_function_id() in (3, 4, 5) else None)
        self.output_folder_path.textChanged.connect(lambda _=None: self._remux_cmd_refresh_timer.start())
        button_output = QPushButton("Select")
        button_output.clicked.connect(self.select_output_folder)
        button_output_open = QPushButton("Open")
        button_output_open.clicked.connect(lambda _=None: self.open_folder_path(self.output_folder_path.text()))
        output_path_layout.addWidget(self.output_folder_path)
        output_path_layout.addWidget(button_output)
        output_path_layout.addWidget(button_output_open)
        self.output_folder_row = output_path_row
        self.output_folder_row.setVisible(self.get_selected_function_id() in (3, 4, 5))
        self.layout.addWidget(self.output_folder_row)
        self.exe_button = QPushButton("Generate Subtitles")
        self.exe_button.clicked.connect(self.main)
        self.exe_button.setMinimumHeight(38)
        self.layout.addWidget(self.exe_button)
        self.bottom_message_label = QLabel('', self)
        self.bottom_message_label.setStyleSheet('color: #007BFF;')
        self.bottom_message_label.setVisible(False)
        self.layout.addWidget(self.bottom_message_label)

        self.setLayout(self.layout)
        self._track_selection_config: dict[str, dict[str, list[str]]] = {}
        self._track_convert_config: dict[str, dict[str, str]] = {}
        self._track_language_config: dict[str, dict[str, str]] = {}
        self._reposition_subtitle_path_box()
        self._apply_language('en')
        self._apply_theme(getattr(self, '_theme_mode', 'light'))

    def _reposition_subtitle_path_box(self):
        outer = getattr(self, '_label2_outer_layout', None)
        hint_row = getattr(self, 'subtitle_hint_row', None)
        label_row = getattr(self, 'subtitle_label_row', None)
        row = getattr(self, 'subtitle_path_row', None)
        extra_rows = getattr(self, 'simple_diy_extra_sub_rows', None)
        scope_row = getattr(self, 'track_scope_row', None)
        host = getattr(self, '_subtitle_tables_host', None)
        if outer is None or row is None or host is None:
            return
        if hint_row is not None and outer.indexOf(hint_row) >= 0:
            outer.removeWidget(hint_row)
        if label_row is not None and outer.indexOf(label_row) >= 0:
            outer.removeWidget(label_row)
        if outer.indexOf(row) >= 0:
            outer.removeWidget(row)
        if extra_rows is not None and outer.indexOf(extra_rows) >= 0:
            outer.removeWidget(extra_rows)
        if scope_row is not None and outer.indexOf(scope_row) >= 0:
            outer.removeWidget(scope_row)
        idx_host = outer.indexOf(host)
        if idx_host < 0:
            if hint_row is not None:
                outer.insertWidget(0, hint_row)
            insert_base = 1 if hint_row is not None else 0
            if label_row is not None:
                outer.insertWidget(insert_base, label_row)
                insert_base += 1
            outer.insertWidget(insert_base, row)
            if extra_rows is not None:
                outer.insertWidget(insert_base + 1, extra_rows)
            if scope_row is not None:
                outer.insertWidget(insert_base + (2 if extra_rows is not None else 1), scope_row)
            return
        if self.get_selected_function_id() in (3, 4, 5):
            if hint_row is not None:
                outer.insertWidget(idx_host + 1, hint_row)
                if label_row is not None:
                    outer.insertWidget(idx_host + 2, label_row)
                outer.insertWidget(idx_host + (3 if label_row is not None else 2), row)
                if extra_rows is not None:
                    outer.insertWidget(idx_host + (4 if label_row is not None else 3), extra_rows)
                if scope_row is not None:
                    offset = (5 if (label_row is not None and extra_rows is not None)
                              else 4 if (label_row is not None or extra_rows is not None) else 3)
                    outer.insertWidget(idx_host + offset, scope_row)
            else:
                if label_row is not None:
                    outer.insertWidget(idx_host + 1, label_row)
                outer.insertWidget(idx_host + (2 if label_row is not None else 1), row)
                if extra_rows is not None:
                    outer.insertWidget(idx_host + (3 if label_row is not None else 2), extra_rows)
                if scope_row is not None:
                    offset = (4 if (label_row is not None and extra_rows is not None)
                              else 3 if (label_row is not None or extra_rows is not None) else 2)
                    outer.insertWidget(idx_host + offset, scope_row)
        else:
            if hint_row is not None:
                outer.insertWidget(idx_host, hint_row)
                if label_row is not None:
                    outer.insertWidget(idx_host + 1, label_row)
                outer.insertWidget(idx_host + (2 if label_row is not None else 1), row)
                if extra_rows is not None:
                    outer.insertWidget(idx_host + (3 if label_row is not None else 2), extra_rows)
                if scope_row is not None:
                    offset = (4 if (label_row is not None and extra_rows is not None)
                              else 3 if (label_row is not None or extra_rows is not None) else 2)
                    outer.insertWidget(idx_host + offset, scope_row)
            else:
                if label_row is not None:
                    outer.insertWidget(idx_host, label_row)
                outer.insertWidget(idx_host + (1 if label_row is not None else 0), row)
                if extra_rows is not None:
                    outer.insertWidget(idx_host + (2 if label_row is not None else 1), extra_rows)
                if scope_row is not None:
                    offset = (3 if (label_row is not None and extra_rows is not None)
                              else 2 if (label_row is not None or extra_rows is not None) else 1)
                    outer.insertWidget(idx_host + offset, scope_row)

    def _save_simple_diy_subtitle_config(self):
        try:
            if self.get_selected_function_id() != 5:
                return
            if not (getattr(self, 'diy_simple_radio', None) and self.diy_simple_radio.isChecked()):
                return
            rows = []
            main_path = (self.subtitle_folder_path.text() or '').strip()
            main_lang = (self.simple_diy_sub_lang_combo.currentText() or 'und').strip() if getattr(
                self, 'simple_diy_sub_lang_combo', None) else 'und'
            bluray_compat = bool(
                getattr(self, 'subtitle_bluray_compat_checkbox', None)
                and self.subtitle_bluray_compat_checkbox.isChecked()
            )
            if main_path or main_lang:
                rows.append({
                    'path': main_path,
                    'language': main_lang or 'und',
                    'bluray_compatible': bluray_compat,
                })
            for row_info in getattr(self, '_simple_diy_sub_rows', []):
                edit = row_info.get('edit')
                combo = row_info.get('lang')
                p = (edit.text() or '').strip() if edit else ''
                l = (combo.currentText() or 'und').strip() if combo else 'und'
                if p or l:
                    rows.append({
                        'path': p,
                        'language': l or 'und',
                        'bluray_compatible': bluray_compat,
                    })
            self._simple_diy_subtitle_config = rows
        except Exception:
            pass

    def closeEvent(self, event):
        self.delete_default_vpy_file()
        try:
            if os.path.exists('info.json'):
                force_remove_file('info.json')
        except Exception:
            pass
        event.accept()
        print('[BluraySubtitle] window close accepted', flush=True)
        return

    def _cleanup_info_json_if_needed(self):
        try:
            if os.path.exists('info.json'):
                force_remove_file('info.json')
        except Exception:
            pass

    def _begin_delayed_busy(self, label_text: str, minimum_delay_sec: float = 2.0) -> dict[str, object]:
        return {
            'start': time.time(),
            'delay': float(minimum_delay_sec),
            'text': str(label_text or ''),
            'dialog': None,
        }

    def _tick_delayed_busy(self, state: Optional[dict[str, object]], text: Optional[str] = None):
        if not isinstance(state, dict):
            return
        if text:
            state['text'] = str(text)
        dlg = state.get('dialog')
        if dlg is None and (time.time() - float(state.get('start') or 0.0)) >= float(state.get('delay') or 2.0):
            dlg = QProgressDialog(str(state.get('text') or self.t('Loading...')), '', 0, 0, self)
            dlg.setCancelButton(None)
            # Non-modal: show progress hint without freezing the whole UI.
            dlg.setWindowModality(Qt.WindowModality.NonModal)
            dlg.setMinimumWidth(420)
            bar = QProgressBar(dlg)
            bar.setRange(0, 0)
            bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dlg.setBar(bar)
            dlg.setMinimumDuration(0)
            dlg.setAutoClose(False)
            dlg.setAutoReset(False)
            dlg.show()
            state['dialog'] = dlg
        elif dlg is not None and text:
            try:
                dlg.setLabelText(str(state.get('text') or ''))
            except Exception:
                pass
        try:
            QCoreApplication.processEvents()
        except Exception:
            pass

    def _end_delayed_busy(self, state: Optional[dict[str, object]]):
        if not isinstance(state, dict):
            return
        dlg = state.get('dialog')
        if dlg is not None:
            try:
                dlg.close()
                dlg.deleteLater()
            except Exception:
                pass
