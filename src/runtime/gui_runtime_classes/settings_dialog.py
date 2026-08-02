"""Application settings dialog."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QDoubleSpinBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import src.core.settings as core_settings
from src.core.app_config import (
    AppConfig,
    AudioPreferences,
    EncodePreferences,
    PathPreferences,
    RemuxPreferences,
    StartupPreferences,
    UiPreferences,
    default_app_config,
)
from src.core.encode_presets import (
    ENCODE_PRESET_NAMES,
    UserEncodePreset,
    encode_presets_for_encoder,
)
from src.core.i18n import translate_text
from src.core.version import APP_VERSION, is_newer_release, release_version
from src.runtime.encode_source import probe_x265_dynamic_metadata_options


GITHUB_LATEST_RELEASE_API = (
    "https://api.github.com/repos/Haruite/BluraySubtitle/releases/latest"
)
GITHUB_RELEASES_URL = "https://github.com/Haruite/BluraySubtitle/releases/latest"
EXTERNAL_TOOL_PATH_NAMES = (
    "FLAC_PATH",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "X265_PATH",
    "X264_PATH",
    "SVT_AV1_PATH",
    "FDK_AAC_PATH",
    "TRUEHDD_PATH",
    "VSEDIT_PATH",
    "VSPIPE_PATH",
    "TS_MUXER_PATH",
    "MKV_INFO_PATH",
    "MKV_MERGE_PATH",
    "MKV_PROP_EDIT_PATH",
    "MKV_EXTRACT_PATH",
)


class SettingsDialog(QDialog):
    def __init__(
            self,
            config: AppConfig,
            translate: Callable[[str], str],
            parent: QWidget | None = None,
            settings_source_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.t = translate
        self._custom_encode_presets = list(config.encode.custom_presets)
        self._preset_editor_updating = False
        self._settings_source_path = (
            Path(settings_source_path)
            if settings_source_path is not None
            else core_settings.ensure_editable_settings_file()
        )
        self._settings_source_text: str | None = None
        self._update_network_manager = QNetworkAccessManager(self)
        self._update_reply: QNetworkReply | None = None
        self.setWindowTitle(self.t("Settings"))
        self.setMinimumWidth(680)
        self.setMinimumHeight(520)

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._build_general_tab(), self.t("General"))
        tabs.addTab(self._build_paths_tab(), self.t("Paths"))
        tabs.addTab(self._build_advanced_tab(), self.t("Advanced"))
        tabs.addTab(self._build_external_tools_tab(), self.t("External tools"))
        layout.addWidget(tabs)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(self.t("Save"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.t("Cancel"))
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText(
            self.t("Restore defaults")
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            lambda _=None: self._set_controls(default_app_config())
        )
        layout.addWidget(self.buttons)
        self._set_controls(config)

    def _build_general_tab(self) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)

        self.function_page_combo = QComboBox(tab)
        for text, value in (
            ("Blu-ray Remux", "bluray_remux"),
            ("Blu-ray Encode", "bluray_encode"),
            ("Blu-ray DIY", "bluray_diy"),
            ("Merge Subtitles", "merge_subtitles"),
            ("Add Chapters To MKV", "add_chapters"),
        ):
            self.function_page_combo.addItem(self.t(text), value)
        form.addRow(self.t("Startup function page"), self.function_page_combo)

        self.episode_mode_combo = QComboBox(tab)
        self.episode_mode_combo.addItem(self.t("Series mode"), "series")
        self.episode_mode_combo.addItem(self.t("Movie mode"), "movie")
        form.addRow(self.t("Default episode mode"), self.episode_mode_combo)

        self.language_combo = QComboBox(tab)
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem(
            translate_text("Simplified Chinese", "zh"),
            "zh",
        )
        form.addRow(self.t("UI language"), self.language_combo)

        self.theme_combo = QComboBox(tab)
        self.theme_combo.addItem(self.t("Light"), "light")
        self.theme_combo.addItem(self.t("Dark"), "dark")
        self.theme_combo.addItem(self.t("Colorful"), "colorful")
        form.addRow(self.t("Theme"), self.theme_combo)

        self.font_size_spin = QSpinBox(tab)
        self.font_size_spin.setRange(6, 14)
        form.addRow(self.t("UI font size"), self.font_size_spin)

        self.opacity_spin = QSpinBox(tab)
        self.opacity_spin.setRange(60, 100)
        self.opacity_spin.setSuffix("%")
        form.addRow(self.t("Window opacity"), self.opacity_spin)

        update_row = QWidget(tab)
        update_layout = QHBoxLayout(update_row)
        update_layout.setContentsMargins(0, 0, 0, 0)
        self.current_version_label = QLabel(
            self.t("Current version: {version}").format(version=APP_VERSION),
            update_row,
        )
        self.check_updates_button = QPushButton(
            self.t("Check for updates"),
            update_row,
        )
        self.check_updates_button.clicked.connect(
            lambda _=None: self._check_for_updates()
        )
        update_layout.addWidget(self.current_version_label)
        update_layout.addStretch(1)
        update_layout.addWidget(self.check_updates_button)
        form.addRow(self.t("Application updates"), update_row)
        return tab

    def _check_for_updates(self) -> None:
        if self._update_reply is not None:
            return
        self.check_updates_button.setEnabled(False)
        self.check_updates_button.setText(self.t("Checking for updates..."))
        request = QNetworkRequest(QUrl(GITHUB_LATEST_RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(
            b"User-Agent",
            f"BluraySubtitle/{APP_VERSION}".encode("ascii"),
        )
        request.setTransferTimeout(15_000)
        self._update_reply = self._update_network_manager.get(request)
        self._update_reply.finished.connect(self._finish_update_check)

    def _finish_update_check(self) -> None:
        reply = self._update_reply
        if reply is None:
            return
        self._update_reply = None
        self.check_updates_button.setEnabled(True)
        self.check_updates_button.setText(self.t("Check for updates"))
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                QMessageBox.warning(
                    self,
                    self.t("Check for updates"),
                    self.t("Could not check for updates: {error}").format(
                        error=reply.errorString()
                    ),
                )
                return
            try:
                payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                self._process_latest_release(payload)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                QMessageBox.warning(
                    self,
                    self.t("Check for updates"),
                    self.t("GitHub did not return a valid release version."),
                )
        finally:
            reply.deleteLater()

    def _process_latest_release(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("GitHub release response must be an object")
        latest_version = release_version(payload)
        if is_newer_release(latest_version):
            self._show_update_available(latest_version)
            return
        QMessageBox.information(
            self,
            self.t("Check for updates"),
            self.t("You are using the latest version ({version}).").format(
                version=APP_VERSION
            ),
        )

    def _update_available_message(self, latest_version: str) -> str:
        return (
            "<p>"
            + self.t("Version {version} is available.").format(
                version=latest_version
            )
            + "</p>"
            + f'<p><a href="{GITHUB_RELEASES_URL}">'
            + self.t("Open GitHub Releases")
            + "</a></p><p><b>"
            + self.t(
                "Before running the new version, copy config.json from the "
                "current program directory to the new program directory."
            )
            + "</b></p>"
        )

    def _show_update_available(self, latest_version: str) -> None:
        message_box = QMessageBox(self)
        message_box.setWindowTitle(self.t("Update available"))
        message_box.setIcon(QMessageBox.Icon.Information)
        message_box.setTextFormat(Qt.TextFormat.RichText)
        message_box.setText(self._update_available_message(latest_version))
        message_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        for label in message_box.findChildren(QLabel):
            label.setOpenExternalLinks(True)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextBrowserInteraction
            )
        message_box.exec()

    def _path_row(self, parent: QWidget) -> tuple[QWidget, QLineEdit]:
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(row)
        select_button = QPushButton(self.t("Select"), row)

        def select_folder() -> None:
            start = edit.text().strip()
            if not os.path.isdir(start):
                start = ""
            folder = QFileDialog.getExistingDirectory(self, self.t("Select folder"), start)
            if folder:
                edit.setText(os.path.normpath(folder))

        select_button.clicked.connect(lambda _=None: select_folder())
        layout.addWidget(edit, 1)
        layout.addWidget(select_button)
        return row, edit

    def _build_paths_tab(self) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        remux_row, self.remux_output_edit = self._path_row(tab)
        encode_row, self.encode_output_edit = self._path_row(tab)
        form.addRow(self.t("Remux default output folder"), remux_row)
        form.addRow(self.t("Encode default output folder"), encode_row)
        return tab

    def _build_advanced_tab(self) -> QWidget:
        tab = QWidget(self)
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(tab)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        layout = QVBoxLayout(content)

        audio_group = QGroupBox(self.t("Audio encoding"), tab)
        audio_form = QFormLayout(audio_group)
        self.flac_compression_spin = QSpinBox(audio_group)
        self.flac_compression_spin.setRange(0, 8)
        audio_form.addRow(
            self.t("FLAC compression level"),
            self.flac_compression_spin,
        )
        self.ffmpeg_flac_compression_spin = QSpinBox(audio_group)
        self.ffmpeg_flac_compression_spin.setRange(0, 12)
        audio_form.addRow(
            self.t("FFmpeg FLAC compression level"),
            self.ffmpeg_flac_compression_spin,
        )
        ffmpeg_level_hint = QLabel(
            self.t(
                "Higher FFmpeg FLAC compression levels can significantly "
                "increase Remux time."
            ),
            audio_group,
        )
        ffmpeg_level_hint.setWordWrap(True)
        audio_form.addRow(ffmpeg_level_hint)
        self.fdkaac_bitrate_spin = QSpinBox(audio_group)
        self.fdkaac_bitrate_spin.setRange(0, 1024)
        self.fdkaac_bitrate_spin.setSpecialValueText(self.t("Auto"))
        self.fdkaac_bitrate_spin.setSuffix(" kbps")
        audio_form.addRow(
            self.t("FDK-AAC bitrate"),
            self.fdkaac_bitrate_spin,
        )
        self.opus_bitrate_spin = QSpinBox(audio_group)
        self.opus_bitrate_spin.setRange(0, 1024)
        self.opus_bitrate_spin.setSpecialValueText(self.t("Auto"))
        self.opus_bitrate_spin.setSuffix(" kbps")
        audio_form.addRow(
            self.t("Opus bitrate"),
            self.opus_bitrate_spin,
        )
        bitrate_hint = QLabel(
            self.t(
                "Auto keeps FDK-AAC VBR mode 5 and Opus 128/256 kbps "
                "selection based on channel count. Suggested for stereo music: "
                "FDK-AAC 128–256 kbps; Opus 64–128 kbps. For multichannel audio "
                "or mixed channel layouts, use Auto or a higher value."
            ),
            audio_group,
        )
        bitrate_hint.setWordWrap(True)
        audio_form.addRow(bitrate_hint)
        self.remux_flac_default_checkbox = QCheckBox(
            self.t("Convert lossless audio to FLAC by default"),
            audio_group,
        )
        audio_form.addRow(self.remux_flac_default_checkbox)
        layout.addWidget(audio_group)

        encode_group = QGroupBox(self.t("Default encode settings"), tab)
        encode_form = QFormLayout(encode_group)
        self.default_encoder_combo = QComboBox(encode_group)
        self.default_encoder_combo.addItem("x264", "x264")
        self.default_encoder_combo.addItem("x265", "x265")
        self.default_encoder_combo.addItem("SVT-AV1", "svtav1")
        encode_form.addRow(
            self.t("Default encoder"),
            self.default_encoder_combo,
        )
        self.default_bit_depth_combo = QComboBox(encode_group)
        encode_form.addRow(
            self.t("Default bit depth"),
            self.default_bit_depth_combo,
        )
        self.default_preset_combo = QComboBox(encode_group)
        encode_form.addRow(
            self.t("Default preset"),
            self.default_preset_combo,
        )

        preset_editor_row = QWidget(encode_group)
        preset_editor_layout = QHBoxLayout(preset_editor_row)
        preset_editor_layout.setContentsMargins(0, 0, 0, 0)
        preset_editor_layout.setSpacing(4)
        self.custom_preset_combo = QComboBox(preset_editor_row)
        self.add_custom_preset_button = QPushButton(
            self.t("Add"),
            preset_editor_row,
        )
        self.delete_custom_preset_button = QPushButton(
            self.t("Delete"),
            preset_editor_row,
        )
        preset_editor_layout.addWidget(self.custom_preset_combo, 1)
        preset_editor_layout.addWidget(self.add_custom_preset_button)
        preset_editor_layout.addWidget(self.delete_custom_preset_button)
        encode_form.addRow(
            self.t("Custom encode presets"),
            preset_editor_row,
        )
        self.custom_preset_name_edit = QLineEdit(encode_group)
        encode_form.addRow(
            self.t("Preset name"),
            self.custom_preset_name_edit,
        )
        self.custom_preset_parameters_edit = QLineEdit(encode_group)
        encode_form.addRow(
            self.t("Custom encode preset parameters"),
            self.custom_preset_parameters_edit,
        )
        self.default_lossless_audio_combo = QComboBox(encode_group)
        self.default_lossless_audio_combo.addItem("FLAC", "flac")
        self.default_lossless_audio_combo.addItem("AAC", "aac")
        self.default_lossless_audio_combo.addItem("Opus", "opus")
        encode_form.addRow(
            self.t("Default lossless audio target"),
            self.default_lossless_audio_combo,
        )
        self.default_subtitle_mode_combo = QComboBox(encode_group)
        self.default_subtitle_mode_combo.addItem(self.t("External"), "external")
        self.default_subtitle_mode_combo.addItem(self.t("Softsub"), "softsub")
        self.default_subtitle_mode_combo.addItem(self.t("Hardsub"), "hardsub")
        encode_form.addRow(
            self.t("Default subtitle packaging"),
            self.default_subtitle_mode_combo,
        )
        self.default_getnative_checkbox = QCheckBox(
            self.t("Enable getnative by default"),
            encode_group,
        )
        encode_form.addRow(self.default_getnative_checkbox)
        self.default_auto_crop_checkbox = QCheckBox(
            self.t("Automatically crop detected black borders by default"),
            encode_group,
        )
        self.default_auto_crop_checkbox.setToolTip(self.t(
            "Automatic black-border detection can be wrong; verify the encoded picture."
        ))
        encode_form.addRow(self.default_auto_crop_checkbox)
        self.default_output_comparison_checkbox = QCheckBox(
            self.t("Output comparison images by default"),
            encode_group,
        )
        encode_form.addRow(self.default_output_comparison_checkbox)

        def create_vpy_strength_spin(maximum: float, tooltip: str) -> QDoubleSpinBox:
            spin = QDoubleSpinBox(encode_group)
            spin.setRange(0.0, maximum)
            spin.setDecimals(2)
            spin.setSingleStep(0.1)
            spin.setKeyboardTracking(False)
            spin.setToolTip(self.t(tooltip))
            return spin

        self.default_vpy_denoise_strength_spin = create_vpy_strength_spin(
            3.0,
            "Default VPy denoise strength; 0 disables it. Lower values preserve more grain and texture.",
        )
        encode_form.addRow(
            self.t("Default VPy denoise strength"),
            self.default_vpy_denoise_strength_spin,
        )
        self.default_vpy_dehalo_strength_spin = create_vpy_strength_spin(
            1.0,
            "Default VPy dehalo starts disabled. For visible sharpening halos, start around 0.15-0.25.",
        )
        encode_form.addRow(
            self.t("Default VPy dehalo strength"),
            self.default_vpy_dehalo_strength_spin,
        )
        self.default_vpy_dering_strength_spin = create_vpy_strength_spin(
            1.0,
            "Default VPy dering starts disabled. For visible ringing, start around 0.15-0.25.",
        )
        encode_form.addRow(
            self.t("Default VPy dering strength"),
            self.default_vpy_dering_strength_spin,
        )
        self.default_vpy_deband_strength_spin = create_vpy_strength_spin(
            1.0,
            "Default VPy deband blend; 0 disables it, 0.5 is the moderate default, and 1 applies the full adaptively masked result.",
        )
        encode_form.addRow(
            self.t("Default VPy deband strength"),
            self.default_vpy_deband_strength_spin,
        )
        self.default_vpy_antialiasing_strength_spin = create_vpy_strength_spin(
            1.0,
            "Default VPy anti-aliasing blend; 0 disables it, 0.5 is the moderate default, and 1 applies the full limited EEDI2 result.",
        )
        encode_form.addRow(
            self.t("Default VPy anti-aliasing strength"),
            self.default_vpy_antialiasing_strength_spin,
        )
        self.default_encoder_combo.currentIndexChanged.connect(
            lambda _=None: self._refresh_advanced_encode_options(True)
        )
        self.default_preset_combo.currentIndexChanged.connect(
            lambda _=None: self._select_default_preset_in_editor()
        )
        self.custom_preset_combo.currentIndexChanged.connect(
            lambda _=None: self._load_custom_preset_editor()
        )
        self.add_custom_preset_button.clicked.connect(
            lambda _=None: self._add_custom_encode_preset()
        )
        self.delete_custom_preset_button.clicked.connect(
            lambda _=None: self._delete_custom_encode_preset()
        )
        self.custom_preset_name_edit.textEdited.connect(
            self._edit_custom_preset_name
        )
        self.custom_preset_parameters_edit.textEdited.connect(
            self._edit_custom_preset_parameters
        )
        layout.addWidget(encode_group)
        layout.addStretch(1)
        scroll.setWidget(content)
        tab_layout.addWidget(scroll)
        return tab

    def _refresh_advanced_encode_options(self, refresh_presets: bool) -> None:
        encoder = str(self.default_encoder_combo.currentData() or "x265")
        previous_depth = str(self.default_bit_depth_combo.currentData() or "10")
        depths = ("8", "10") if encoder == "x264" else ("8", "10", "12")
        self.default_bit_depth_combo.blockSignals(True)
        try:
            self.default_bit_depth_combo.clear()
            for depth in depths:
                self.default_bit_depth_combo.addItem(
                    self.t({
                        "8": "8-bit",
                        "10": "10-bit",
                        "12": "12-bit",
                    }[depth]),
                    depth,
                )
            index = self.default_bit_depth_combo.findData(previous_depth)
            if index < 0:
                index = self.default_bit_depth_combo.findData("10")
            self.default_bit_depth_combo.setCurrentIndex(max(0, index))
        finally:
            self.default_bit_depth_combo.blockSignals(False)
        if refresh_presets:
            self._refill_custom_preset_controls(
                str(self.default_preset_combo.currentData() or "Balanced")
            )

    def _refill_custom_preset_controls(
            self,
            preferred_default: str,
            preferred_editor: tuple[str, object] | None = None,
    ) -> None:
        encoder = str(self.default_encoder_combo.currentData() or "x265")
        presets = encode_presets_for_encoder(
            encoder,
            self._custom_encode_presets,
        )
        self._preset_editor_updating = True
        self.default_preset_combo.blockSignals(True)
        self.custom_preset_combo.blockSignals(True)
        try:
            self.default_preset_combo.clear()
            for name in presets:
                self.default_preset_combo.addItem(
                    self.t(name) if name in ENCODE_PRESET_NAMES else name,
                    name,
                )
            default_index = self.default_preset_combo.findData(preferred_default)
            if default_index < 0:
                default_index = self.default_preset_combo.findData("Balanced")
            self.default_preset_combo.setCurrentIndex(max(0, default_index))

            self.custom_preset_combo.clear()
            for name in ENCODE_PRESET_NAMES:
                self.custom_preset_combo.addItem(
                    self.t(name),
                    ("built_in", name),
                )
            for index, preset in enumerate(self._custom_encode_presets):
                if preset.encoder == encoder:
                    self.custom_preset_combo.addItem(
                        preset.name,
                        ("custom", index),
                    )
            editor_index = -1
            if preferred_editor is not None:
                for index in range(self.custom_preset_combo.count()):
                    if self.custom_preset_combo.itemData(index) == preferred_editor:
                        editor_index = index
                        break
            if editor_index < 0:
                selected_name = str(
                    self.default_preset_combo.currentData() or "Balanced"
                )
                for index in range(self.custom_preset_combo.count()):
                    kind, value = self.custom_preset_combo.itemData(index)
                    candidate = (
                        str(value)
                        if kind == "built_in"
                        else self._custom_encode_presets[int(value)].name
                    )
                    if candidate == selected_name:
                        editor_index = index
                        break
            self.custom_preset_combo.setCurrentIndex(max(0, editor_index))
        finally:
            self.custom_preset_combo.blockSignals(False)
            self.default_preset_combo.blockSignals(False)
            self._preset_editor_updating = False
        self._load_custom_preset_editor()

    def _select_default_preset_in_editor(self) -> None:
        if self._preset_editor_updating:
            return
        selected_name = str(self.default_preset_combo.currentData() or "")
        for index in range(self.custom_preset_combo.count()):
            kind, value = self.custom_preset_combo.itemData(index)
            candidate = (
                str(value)
                if kind == "built_in"
                else self._custom_encode_presets[int(value)].name
            )
            if candidate == selected_name:
                self.custom_preset_combo.setCurrentIndex(index)
                return

    def _load_custom_preset_editor(self) -> None:
        if self._preset_editor_updating:
            return
        data = self.custom_preset_combo.currentData()
        if not isinstance(data, tuple) or len(data) != 2:
            return
        kind, value = data
        editable = kind == "custom"
        if editable:
            preset = self._custom_encode_presets[int(value)]
            name = preset.name
            parameters = preset.parameters
        else:
            name = self.t(str(value))
            parameters = encode_presets_for_encoder(
                str(self.default_encoder_combo.currentData() or "x265")
            )[str(value)]
        self._preset_editor_updating = True
        try:
            self.custom_preset_name_edit.setText(name)
            self.custom_preset_parameters_edit.setText(parameters)
            self.custom_preset_name_edit.setReadOnly(not editable)
            self.custom_preset_parameters_edit.setReadOnly(not editable)
            self.delete_custom_preset_button.setEnabled(editable)
        finally:
            self._preset_editor_updating = False

    def _edit_custom_preset_name(self, name: str) -> None:
        if self._preset_editor_updating:
            return
        data = self.custom_preset_combo.currentData()
        if not isinstance(data, tuple) or data[0] != "custom":
            return
        index = int(data[1])
        previous = self._custom_encode_presets[index]
        self._custom_encode_presets[index] = replace(previous, name=name)
        self.custom_preset_combo.setItemText(
            self.custom_preset_combo.currentIndex(),
            name,
        )
        for combo_index in range(self.default_preset_combo.count()):
            if self.default_preset_combo.itemData(combo_index) == previous.name:
                self.default_preset_combo.setItemText(combo_index, name)
                self.default_preset_combo.setItemData(combo_index, name)
                break

    def _edit_custom_preset_parameters(self, parameters: str) -> None:
        if self._preset_editor_updating:
            return
        data = self.custom_preset_combo.currentData()
        if not isinstance(data, tuple) or data[0] != "custom":
            return
        index = int(data[1])
        self._custom_encode_presets[index] = replace(
            self._custom_encode_presets[index],
            parameters=parameters,
        )

    def _add_custom_encode_preset(self) -> None:
        encoder = str(self.default_encoder_combo.currentData() or "x265")
        base_name = self.t("New Preset")
        used_names = {
            name.casefold()
            for name in ENCODE_PRESET_NAMES
        } | {
            preset.name.casefold()
            for preset in self._custom_encode_presets
            if preset.encoder == encoder
        }
        name = base_name
        suffix = 2
        while name.casefold() in used_names:
            name = f"{base_name} {suffix}"
            suffix += 1
        self._custom_encode_presets.append(UserEncodePreset(
            encoder=encoder,
            name=name,
            parameters=self.custom_preset_parameters_edit.text().strip(),
        ))
        self._refill_custom_preset_controls(
            str(self.default_preset_combo.currentData() or "Balanced"),
            ("custom", len(self._custom_encode_presets) - 1),
        )
        self.custom_preset_name_edit.setFocus()
        self.custom_preset_name_edit.selectAll()

    def _delete_custom_encode_preset(self) -> None:
        data = self.custom_preset_combo.currentData()
        if not isinstance(data, tuple) or data[0] != "custom":
            return
        deleted = self._custom_encode_presets.pop(int(data[1]))
        preferred_default = str(
            self.default_preset_combo.currentData() or "Balanced"
        )
        if preferred_default == deleted.name:
            preferred_default = "Balanced"
        self._refill_custom_preset_controls(preferred_default)

    def _custom_preset_validation_error(
            self,
    ) -> tuple[str, dict[str, str]] | None:
        names_by_encoder: dict[str, set[str]] = {
            "x264": set(),
            "x265": set(),
            "svtav1": set(),
        }
        built_in_names = {name.casefold() for name in ENCODE_PRESET_NAMES}
        for preset in self._custom_encode_presets:
            name = preset.name.strip()
            if not name:
                return "Custom encode preset name cannot be empty.", {}
            normalized_name = name.casefold()
            if normalized_name in built_in_names:
                return (
                    "Custom encode preset name conflicts with a built-in preset: {name}",
                    {"name": name},
                )
            if normalized_name in names_by_encoder[preset.encoder]:
                return (
                    "Duplicate custom encode preset for {encoder}: {name}",
                    {"encoder": preset.encoder, "name": name},
                )
            names_by_encoder[preset.encoder].add(normalized_name)
        return None

    def _normalized_custom_encode_presets(self) -> tuple[UserEncodePreset, ...]:
        error = self._custom_preset_validation_error()
        if error is not None:
            template, values = error
            raise ValueError(template.format(**values))
        return tuple(
            replace(
                preset,
                name=preset.name.strip(),
                parameters=preset.parameters.strip(),
            )
            for preset in self._custom_encode_presets
        )

    def _build_external_tools_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        message = QLabel(
            self.t(
                "Edit src/core/settings.py below. Changes take effect after restarting "
                "the application."
            ),
            tab,
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        self.external_tools_path_label = QLabel(
            self.t("Settings file: {path}").format(path=str(self._settings_source_path)),
            tab,
        )
        self.external_tools_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.external_tools_path_label.setWordWrap(True)
        layout.addWidget(self.external_tools_path_label)

        self.external_tools_editor = QPlainTextEdit(tab)
        self.external_tools_editor.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.external_tools_editor.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        layout.addWidget(self.external_tools_editor, 1)

        self.external_tools_status_label = QLabel("", tab)
        self.external_tools_status_label.setWordWrap(True)
        layout.addWidget(self.external_tools_status_label)

        self.external_tools_detection_view = QPlainTextEdit(tab)
        self.external_tools_detection_view.setReadOnly(True)
        self.external_tools_detection_view.setFixedHeight(48)
        self.external_tools_detection_view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        layout.addWidget(self.external_tools_detection_view)

        button_row = QWidget(tab)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        reload_button = QPushButton(self.t("Reload file"), tab)
        reload_button.clicked.connect(
            lambda _=None: self._load_external_tools_source(show_error=True)
        )
        check_paths_button = QPushButton(self.t("Check tool paths"), tab)
        check_paths_button.clicked.connect(
            lambda _=None: self._refresh_external_tool_detection()
        )
        button_layout.addWidget(reload_button)
        button_layout.addWidget(check_paths_button)
        button_layout.addStretch(1)
        layout.addWidget(button_row)
        self._load_external_tools_source(show_error=False)
        self._refresh_external_tool_detection()
        return tab

    def _refresh_external_tool_detection(self) -> None:
        missing: list[tuple[str, str]] = []
        tool_path_names = list(EXTERNAL_TOOL_PATH_NAMES)
        x265_options = probe_x265_dynamic_metadata_options(
            str(core_settings.X265_PATH or "")
        )
        for name, required_options in (
                ("HDR10PLUS_TOOL_PATH", {"--dhdr10-info"}),
                ("DOVI_TOOL_PATH", {
                    "--dolby-vision-profile",
                    "--dolby-vision-rpu",
                }),
        ):
            if required_options.issubset(x265_options):
                tool_path_names.append(name)
        for name in tool_path_names:
            raw_path = str(getattr(core_settings, name, "") or "").strip()
            expanded_path = os.path.expandvars(os.path.expanduser(raw_path))
            if not expanded_path or not (
                    os.path.isfile(expanded_path) or shutil.which(expanded_path)
            ):
                missing.append((
                    name,
                    raw_path or self.t("not configured"),
                ))
        if not missing:
            self.external_tools_detection_view.setFixedHeight(48)
            self.external_tools_detection_view.setStyleSheet("color: #2e9d50;")
            self.external_tools_detection_view.setPlainText(
                self.t("All configured tool paths in settings.py were found.")
            )
            return
        setup_script = (
            "setup_windows_environment.ps1"
            if sys.platform == "win32"
            else "setup_linux_environment.sh"
        )
        missing_lines = "\n".join(
            f"- {name}: {path}" for name, path in missing
        )
        self.external_tools_detection_view.setFixedHeight(120)
        self.external_tools_detection_view.setStyleSheet("color: #d9534f;")
        self.external_tools_detection_view.setPlainText(
            self.t("Missing tools configured in settings.py:")
            + "\n"
            + missing_lines
            + "\n"
            + self.t(
                "Run {script} from the repository root, then restart the "
                "application and check the paths again."
            ).format(script=setup_script)
        )

    def _load_external_tools_source(self, show_error: bool) -> None:
        try:
            text = self._settings_source_path.read_text(encoding="utf-8")
        except Exception as error:
            self._settings_source_text = None
            self.external_tools_editor.clear()
            self.external_tools_editor.setReadOnly(True)
            message = self.t(
                "Could not load external tool settings: {error}"
            ).format(error=str(error))
            self.external_tools_status_label.setText(message)
            if show_error:
                QMessageBox.warning(self, self.t("Settings"), message)
            return
        self._settings_source_text = text
        self.external_tools_editor.setReadOnly(False)
        self.external_tools_editor.setPlainText(text)
        self.external_tools_status_label.clear()

    def _save_external_tools_source(self) -> bool:
        if self._settings_source_text is None:
            return True
        text = self.external_tools_editor.toPlainText()
        if text == self._settings_source_text:
            return True
        try:
            compile(text, str(self._settings_source_path), "exec")
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            normalized = normalized.replace("\n", "\r\n")
            if normalized and not normalized.endswith("\r\n"):
                normalized += "\r\n"
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self._settings_source_path.name}.",
                suffix=".tmp",
                dir=self._settings_source_path.parent,
            )
            try:
                with os.fdopen(
                        descriptor,
                        "w",
                        encoding="utf-8",
                        newline="",
                ) as stream:
                    stream.write(normalized)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, self._settings_source_path)
            except Exception:
                try:
                    os.remove(temporary_name)
                except OSError:
                    pass
                raise
        except Exception as error:
            QMessageBox.warning(
                self,
                self.t("Settings"),
                self.t("Could not save external tool settings: {error}").format(
                    error=str(error)
                ),
            )
            return False
        self._settings_source_text = normalized
        return True

    def accept(self) -> None:
        validation_error = self._custom_preset_validation_error()
        if validation_error is not None:
            template, values = validation_error
            QMessageBox.warning(
                self,
                self.t("Settings"),
                self.t(template).format(**values),
            )
            return
        if self._save_external_tools_source():
            super().accept()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_controls(self, config: AppConfig) -> None:
        self._custom_encode_presets = list(config.encode.custom_presets)
        self._set_combo_data(self.function_page_combo, config.startup.function_page)
        self._set_combo_data(self.episode_mode_combo, config.startup.episode_mode)
        self._set_combo_data(self.language_combo, config.ui.language)
        self._set_combo_data(self.theme_combo, config.ui.theme)
        self.font_size_spin.setValue(config.ui.font_size)
        self.opacity_spin.setValue(config.ui.opacity)
        self.remux_output_edit.setText(config.paths.remux_output)
        self.encode_output_edit.setText(config.paths.encode_output)
        self.flac_compression_spin.setValue(config.audio.flac_compression_level)
        self.ffmpeg_flac_compression_spin.setValue(
            config.audio.ffmpeg_flac_compression_level
        )
        self.fdkaac_bitrate_spin.setValue(config.audio.fdkaac_bitrate_kbps)
        self.opus_bitrate_spin.setValue(config.audio.opus_bitrate_kbps)
        self.remux_flac_default_checkbox.setChecked(
            config.remux.convert_lossless_audio_to_flac
        )
        self.default_encoder_combo.blockSignals(True)
        try:
            self._set_combo_data(
                self.default_encoder_combo,
                config.encode.encoder,
            )
        finally:
            self.default_encoder_combo.blockSignals(False)
        self._refresh_advanced_encode_options(False)
        self._set_combo_data(
            self.default_bit_depth_combo,
            config.encode.bit_depth,
        )
        self._refill_custom_preset_controls(config.encode.preset)
        self._set_combo_data(
            self.default_lossless_audio_combo,
            config.encode.lossless_audio_codec,
        )
        self._set_combo_data(
            self.default_subtitle_mode_combo,
            config.encode.subtitle_mode,
        )
        self.default_getnative_checkbox.setChecked(config.encode.use_getnative)
        self.default_auto_crop_checkbox.setChecked(
            config.encode.auto_crop_black_borders
        )
        self.default_output_comparison_checkbox.setChecked(
            config.encode.output_comparison_images
        )
        self.default_vpy_denoise_strength_spin.setValue(
            config.encode.vpy_denoise_strength
        )
        self.default_vpy_dehalo_strength_spin.setValue(
            config.encode.vpy_dehalo_strength
        )
        self.default_vpy_dering_strength_spin.setValue(
            config.encode.vpy_dering_strength
        )
        self.default_vpy_deband_strength_spin.setValue(
            config.encode.vpy_deband_strength
        )
        self.default_vpy_antialiasing_strength_spin.setValue(
            config.encode.vpy_antialiasing_strength
        )

    def selected_config(self) -> AppConfig:
        return replace(
            self._config,
            ui=UiPreferences(
                language=str(self.language_combo.currentData()),
                theme=str(self.theme_combo.currentData()),
                font_size=self.font_size_spin.value(),
                opacity=self.opacity_spin.value(),
            ),
            startup=StartupPreferences(
                function_page=str(self.function_page_combo.currentData()),
                episode_mode=str(self.episode_mode_combo.currentData()),
            ),
            paths=PathPreferences(
                remux_output=self.remux_output_edit.text().strip(),
                encode_output=self.encode_output_edit.text().strip(),
            ),
            audio=AudioPreferences(
                flac_compression_level=self.flac_compression_spin.value(),
                ffmpeg_flac_compression_level=(
                    self.ffmpeg_flac_compression_spin.value()
                ),
                fdkaac_bitrate_kbps=self.fdkaac_bitrate_spin.value(),
                opus_bitrate_kbps=self.opus_bitrate_spin.value(),
            ),
            remux=RemuxPreferences(
                convert_lossless_audio_to_flac=(
                    self.remux_flac_default_checkbox.isChecked()
                ),
            ),
            encode=EncodePreferences(
                encoder=str(self.default_encoder_combo.currentData()),
                bit_depth=str(self.default_bit_depth_combo.currentData()),
                preset=str(self.default_preset_combo.currentData()),
                custom_presets=self._normalized_custom_encode_presets(),
                lossless_audio_codec=str(
                    self.default_lossless_audio_combo.currentData()
                ),
                subtitle_mode=str(
                    self.default_subtitle_mode_combo.currentData()
                ),
                use_getnative=self.default_getnative_checkbox.isChecked(),
                auto_crop_black_borders=(
                    self.default_auto_crop_checkbox.isChecked()
                ),
                output_comparison_images=(
                    self.default_output_comparison_checkbox.isChecked()
                ),
                vpy_denoise_strength=(
                    self.default_vpy_denoise_strength_spin.value()
                ),
                vpy_dehalo_strength=(
                    self.default_vpy_dehalo_strength_spin.value()
                ),
                vpy_dering_strength=(
                    self.default_vpy_dering_strength_spin.value()
                ),
                vpy_deband_strength=(
                    self.default_vpy_deband_strength_spin.value()
                ),
                vpy_antialiasing_strength=(
                    self.default_vpy_antialiasing_strength_spin.value()
                ),
            ),
        )


__all__ = ["SettingsDialog"]
