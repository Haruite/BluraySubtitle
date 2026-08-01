"""Application settings and persistent window-state integration."""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import QByteArray
from PyQt6.QtWidgets import QComboBox, QDialog, QMessageBox

from src.core.app_config import UiPreferences, WindowPreferences, save_app_config
from src.runtime.audio_conversion import AudioEncodingSettings
from src.runtime.gui_runtime_classes.settings_dialog import SettingsDialog
from .gui_base import BluraySubtitleGuiBase


class SettingsStateMixin(BluraySubtitleGuiBase):
    def _captured_audio_encoding_settings(self) -> AudioEncodingSettings:
        audio = self._app_config.audio
        return AudioEncodingSettings(
            flac_compression_level=audio.flac_compression_level,
            ffmpeg_flac_compression_level=audio.ffmpeg_flac_compression_level,
            fdkaac_bitrate_kbps=audio.fdkaac_bitrate_kbps,
            opus_bitrate_kbps=audio.opus_bitrate_kbps,
        )

    def _apply_saved_encode_defaults(self) -> None:
        encode = self._app_config.encode
        tool_text = {
            "x264": "x264",
            "x265": "x265",
            "svtav1": "SvtAv1",
        }[encode.encoder]
        self.encode_tool_combo.setCurrentText(tool_text)
        self._refill_encode_bit_depth_combo(tool_text)
        depth_index = self.encode_bit_depth_combo.findData(encode.bit_depth)
        if depth_index >= 0:
            self.encode_bit_depth_combo.setCurrentIndex(depth_index)
        preset_index = self.x265_preset_combo.findData(encode.preset)
        self.x265_preset_combo.blockSignals(True)
        try:
            self.x265_preset_combo.setCurrentIndex(
                preset_index if preset_index >= 0 else 0
            )
        finally:
            self.x265_preset_combo.blockSignals(False)
        self._encode_setting_updating = True
        try:
            self.x265_params_edit.setPlainText(encode.preset_parameters)
        finally:
            self._encode_setting_updating = False
        self._set_combo_value(
            self.encode_lossless_audio_combo,
            encode.lossless_audio_codec,
        )
        self.use_getnative_checkbox.setChecked(encode.use_getnative)
        self.output_comparison_checkbox.setChecked(
            encode.output_comparison_images
        )
        subtitle_radio = {
            "external": self.sub_pack_external_radio,
            "softsub": self.sub_pack_soft_radio,
            "hardsub": self.sub_pack_hard_radio,
        }[encode.subtitle_mode]
        subtitle_radio.setChecked(True)
        self.remux_flac_checkbox.setChecked(
            self._app_config.remux.convert_lossless_audio_to_flac
        )

    def _remember_output_folder_for_function(self, function_id: int) -> None:
        if function_id not in (3, 4, 5):
            return
        edit = getattr(self, "output_folder_path", None)
        values = getattr(self, "_output_folder_values", None)
        if edit is not None and isinstance(values, dict):
            values[function_id] = edit.text().strip()

    def _restore_output_folder_for_function(self, function_id: int) -> None:
        if function_id not in (3, 4, 5):
            return
        edit = getattr(self, "output_folder_path", None)
        values = getattr(self, "_output_folder_values", None)
        if edit is not None and isinstance(values, dict):
            edit.setText(str(values.get(function_id) or ""))

    def _window_geometry_text(self) -> str:
        return bytes(self.saveGeometry().toBase64()).decode("ascii")

    def _restore_window_geometry(self) -> bool:
        geometry = str(getattr(self._app_config.window, "geometry", "") or "")
        if not geometry:
            self._window_geometry_restored = False
            return False
        encoded = QByteArray.fromBase64(geometry.encode("ascii"))
        if encoded.isEmpty() or not self.restoreGeometry(encoded):
            raise ValueError("Stored window geometry could not be restored")
        self._window_geometry_restored = True
        return True

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _apply_saved_ui_preferences(self) -> None:
        ui = self._app_config.ui
        for combo, value in (
            (self.language_combo, ui.language),
            (self.theme_combo, ui.theme),
        ):
            combo.blockSignals(True)
            try:
                self._set_combo_value(combo, value)
            finally:
                combo.blockSignals(False)
        self.font_size_combo.blockSignals(True)
        try:
            index = self.font_size_combo.findData(ui.font_size)
            self.font_size_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.font_size_combo.blockSignals(False)
        self.opacity_slider.blockSignals(True)
        try:
            self.opacity_slider.setValue(ui.opacity)
        finally:
            self.opacity_slider.blockSignals(False)
        self._on_opacity_changed(ui.opacity)
        self._apply_ui_font_size(ui.font_size)
        self._apply_theme(ui.theme)
        self._apply_language(ui.language)

    def _show_app_config_error(self, action: str, error: Exception | str) -> None:
        template = (
            "Could not load application settings: {error}"
            if action == "load"
            else "Could not save application settings: {error}"
        )
        QMessageBox.warning(
            self,
            self.t("Settings"),
            self.t(template).format(error=self.t(str(error))),
        )

    def _show_settings_dialog(self) -> None:
        dialog = SettingsDialog(self._app_config, self.t, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = replace(
            dialog.selected_config(),
            window=WindowPreferences(geometry=self._window_geometry_text()),
        )
        try:
            save_app_config(selected, self._app_config_path)
        except Exception as error:
            self._show_app_config_error("save", error)
            return
        self._app_config = selected
        self._app_config_load_failed = False
        self._output_folder_values[3] = selected.paths.remux_output
        self._output_folder_values[4] = selected.paths.encode_output
        self._auto_output_folders[3] = ""
        self._auto_output_folders[4] = ""
        function_id = self.get_selected_function_id()
        if function_id in (3, 4):
            self._restore_output_folder_for_function(function_id)
        self._apply_saved_ui_preferences()

    def _save_application_state(self) -> None:
        if getattr(self, "_app_config_load_failed", False):
            return
        language = str(self.language_combo.currentData() or "en")
        theme = str(self.theme_combo.currentData() or "light")
        font_size = int(getattr(self, "_ui_font_point_size", 10) or 10)
        opacity = int(self.opacity_slider.value())
        updated = replace(
            self._app_config,
            window=WindowPreferences(geometry=self._window_geometry_text()),
            ui=UiPreferences(
                language=language,
                theme=theme,
                font_size=max(6, min(14, font_size)),
                opacity=max(60, min(100, opacity)),
            ),
        )
        save_app_config(updated, self._app_config_path)
        self._app_config = updated


__all__ = ["SettingsStateMixin"]
