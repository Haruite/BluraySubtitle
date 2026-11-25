"""Application settings and persistent window-state integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from PyQt6.QtCore import QByteArray, QThread, QTimer
from PyQt6.QtWidgets import QApplication, QComboBox, QDialog, QWidget

from src.core.app_config import AppConfig, UiPreferences, WindowPreferences, save_app_config
from src.core.tool_paths import active_tool_paths
from src.runtime.audio_conversion import AudioEncodingSettings
from src.runtime.gui_runtime_classes.settings_dialog import SettingsDialog
from src.runtime.program_update import UpdatePackage, start_program_update
from src.runtime.gui_runtime_classes.widget_animations import AnimatedMessageBox
from .gui_base import BluraySubtitleGuiBase


class SettingsStateMixin(BluraySubtitleGuiBase):
    def _captured_audio_encoding_settings(self) -> AudioEncodingSettings:
        audio = self._app_config.audio
        return AudioEncodingSettings(
            flac_compression_level=audio.flac_compression_level,
            ffmpeg_flac_compression_level=audio.ffmpeg_flac_compression_level,
            fdkaac_bitrate_kbps=audio.fdkaac_bitrate_kbps,
            opus_bitrate_kbps=audio.opus_bitrate_kbps,
            duration_loss_fallback_threshold_seconds=(
                audio.duration_loss_fallback_threshold_seconds
            ),
        )

    def _apply_saved_encode_devices(self) -> None:
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
            self.x265_params_edit.setPlainText(
                encode.cpu_parameters if encode.cpu_parameters is not None
                else self._encode_preset_params.get(encode.preset, "")
            )
        finally:
            self._encode_setting_updating = False
        self.encode_device_controls.restore(encode)
        self._refresh_cpu_encode_command()

    def _apply_saved_encode_defaults(self) -> None:
        self._apply_saved_encode_devices()
        encode = self._app_config.encode
        self._set_combo_value(
            self.encode_lossless_audio_combo,
            encode.lossless_audio_codec,
        )
        self.use_getnative_checkbox.setChecked(encode.use_getnative)
        self.auto_crop_black_borders_checkbox.setChecked(
            encode.auto_crop_black_borders
        )
        self.output_comparison_checkbox.setChecked(
            encode.output_comparison_images
        )
        self.frame_check_checkbox.setChecked(
            encode.check_corrupted_frames
        )
        self.vpy_denoise_strength_spin.setValue(encode.vpy_denoise_strength)
        self.vpy_dehalo_strength_spin.setValue(encode.vpy_dehalo_strength)
        self.vpy_dering_strength_spin.setValue(encode.vpy_dering_strength)
        self.vpy_deband_strength_spin.setValue(encode.vpy_deband_strength)
        self.vpy_antialiasing_strength_spin.setValue(
            encode.vpy_antialiasing_strength
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
        self.encode_device_controls.refresh(
            self._resolved_tool_paths.get("FFMPEG_PATH", ""),
            self._resolved_tool_paths.get("FFPROBE_PATH", ""),
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

    def _window_geometry_text(self, window: QWidget | None = None) -> str:
        target = self if window is None else window
        return bytes(target.saveGeometry().toBase64()).decode("ascii")

    @staticmethod
    def _restore_saved_window_geometry(window: QWidget, geometry: str) -> bool:
        encoded = QByteArray.fromBase64(geometry.encode("ascii"))
        # Qt may reject saved geometry after the screen layout or scale changes.
        return not encoded.isEmpty() and window.restoreGeometry(encoded)

    def _restore_window_geometry(self) -> bool:
        self._window_geometry_restored = self._restore_saved_window_geometry(
            self, self._app_config.window.geometry,
        )
        return self._window_geometry_restored

    def _current_window_preferences(self) -> WindowPreferences:
        log_geometry = self._app_config.window.log_geometry
        if self._log_dialog is not None:
            log_geometry = self._window_geometry_text(self._log_dialog)
        return WindowPreferences(geometry=self._window_geometry_text(), log_geometry=log_geometry)

    def _save_log_window_geometry(self) -> None:
        if self._close_pending or self._app_config_load_failed or self._log_dialog is None:
            return
        geometry = self._window_geometry_text(self._log_dialog)
        if geometry == self._app_config.window.log_geometry:
            return
        updated = replace(
            self._app_config,
            window=replace(self._app_config.window, log_geometry=geometry),
        )
        try:
            save_app_config(updated, self._app_config_path, preserve_tools=True)
        except Exception as error:
            self._show_app_config_error("save", error)
        else:
            self._app_config = updated

    @staticmethod
    def _set_combo_value(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _apply_saved_ui_preferences(self, previous: UiPreferences | None = None) -> None:
        ui = self._app_config.ui
        self._tray_icon.setVisible(ui.close_to_tray)
        if self._application_log is not None:
            self._application_log.set_line_limit(ui.log_line_limit)
            if self._log_dialog is not None:
                self._log_dialog.set_line_limit(ui.log_line_limit)
            self._application_log.set_log_directory(
                self._app_config_path.parent / "logs" if ui.save_log_to_file else None,
            )
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
        if previous is None or ui.font_size != previous.font_size or ui.fonts != previous.fonts:
            self._apply_ui_font_size(ui.font_size)
        if previous is None or ui.theme != previous.theme:
            self._apply_theme(ui.theme)
        elif ui.log_theme != previous.log_theme:
            self._apply_log_dialog_theme()
        if previous is None or ui.opacity != previous.opacity:
            self._apply_window_opacity()
        if previous is None or ui.language != previous.language:
            self._apply_language(ui.language)
        self.set_background_image(ui.main_background_path, ui.main_background_opacity, ui.main_background_blur)
        if self._log_dialog is not None:
            self._log_dialog.set_background_image(ui.log_background_path, ui.log_background_opacity, ui.log_background_blur)
        self._startup_update_notice.set_check_enabled(ui.check_updates_on_startup)

    def _show_app_config_error(self, action: str, error: Exception | str) -> None:
        template = (
            "Could not load application settings: {error}"
            if action == "load"
            else "Could not save application settings: {error}"
        )
        AnimatedMessageBox.warning(
            self,
            self.t("Settings"),
            self.t(template).format(error=self.t(str(error))),
        )

    def _start_program_update(self, package: UpdatePackage) -> None:
        if any(thread.isRunning() for thread in self.findChildren(QThread)):
            raise RuntimeError(self.t("Finish or cancel the running task before updating."))
        start_program_update(package)
        QTimer.singleShot(0, self._exit_application)

    def _confirm_ui_scale_restart(self, dialog: SettingsDialog) -> bool:
        title = self.t("UI scale")
        if (getattr(self, "_current_cancel_event", None) is not None or self._bdmv_load_pending
                or any(thread.isRunning() for thread in self.findChildren(QThread))):
            AnimatedMessageBox.information(
                dialog, title, self.t("A task is running. The new UI scale will take effect on the next launch."),
            )
            return False
        prompt = AnimatedMessageBox(
            AnimatedMessageBox.Icon.Question, title,
            self.t("Restart the app now to apply the new UI scale? Restarting closes the currently open content."),
            parent=dialog,
        )
        restart = prompt.addButton(self.t("Restart now"), AnimatedMessageBox.ButtonRole.AcceptRole)
        later = prompt.addButton(self.t("Later"), AnimatedMessageBox.ButtonRole.RejectRole)
        prompt.setDefaultButton(later)
        prompt.exec()
        confirmed = prompt.clickedButton() == restart
        prompt.deleteLater()
        return confirmed

    def _show_settings_dialog(self) -> None:
        restart_requested = False

        def apply_config(config: AppConfig, resolved_tools: Mapping[str, str]) -> bool:
            nonlocal restart_requested
            previous = self._app_config
            previous_ui = self._current_ui_preferences()
            selected = replace(config, window=self._current_window_preferences())
            try:
                save_app_config(
                    selected, self._app_config_path,
                    preserve_tools=not self._app_config_load_failed and selected.tools == previous.tools,
                )
            except Exception as error:
                self._show_app_config_error("save", error)
                return False
            self._app_config = selected
            self._app_config_load_failed = False
            tools_changed = self._resolved_tool_paths != resolved_tools
            self._resolved_tool_paths = resolved_tools
            active_tool_paths.set(resolved_tools)
            current_preset = self.x265_preset_combo.currentData()
            refresh_cpu_parameters = (
                selected.encode.custom_presets != previous.encode.custom_presets
                and self.x265_params_edit.toPlainText() == self._encode_preset_params.get(current_preset)
            )
            if selected.encode != previous.encode:
                self._reload_encode_preset_parameters()
            if selected.encode != previous.encode or tools_changed:
                self._refresh_encode_tool_dependent_ui(refresh_cpu_parameters)
            if any(getattr(selected.encode, name) != getattr(previous.encode, name) for name in (
                "encoder", "bit_depth", "preset", "chroma_format", "cpu_enabled", "cpu_parameters",
            )):
                self._apply_saved_encode_devices()
            elif selected.encode.gpu_devices != previous.encode.gpu_devices:
                self.encode_device_controls.restore(selected.encode)
            elif selected.encode.gpu_enabled != previous.encode.gpu_enabled:
                self.encode_device_controls.set_gpu_enabled(selected.encode.gpu_enabled)
            ffmpeg, ffprobe = resolved_tools.get("FFMPEG_PATH", ""), resolved_tools.get("FFPROBE_PATH", "")
            detected = dialog.detected_gpu_devices(ffmpeg, ffprobe)
            if detected is not None or tools_changed or selected.encode.gpu_enabled != previous.encode.gpu_enabled:
                self.encode_device_controls.refresh(ffmpeg, ffprobe, detected=detected)
            for function_id, old_path, new_path in (
                (3, previous.paths.remux_output, selected.paths.remux_output),
                (4, previous.paths.encode_output, selected.paths.encode_output),
            ):
                if new_path != old_path:
                    self._output_folder_values[function_id] = new_path
                    self._auto_output_folders[function_id] = ""
                    if self.get_selected_function_id() == function_id:
                        self._restore_output_folder_for_function(function_id)
            if tools_changed and self.get_selected_function_id() == 3:
                self._refresh_table1_remux_cmds()
            self._apply_saved_ui_preferences(previous_ui)
            self._apply_window_opacity(dialog)
            if selected.ui.scale_percent != previous.ui.scale_percent:
                active_scale = QApplication.instance().property("uiScalePercent") or 0
                if selected.ui.scale_percent != active_scale and self._confirm_ui_scale_restart(dialog):
                    restart_requested = True
                    QTimer.singleShot(0, lambda: dialog.done(QDialog.DialogCode.Accepted))
            return True

        dialog = SettingsDialog(
            replace(self._app_config, ui=self._current_ui_preferences()),
            self.t,
            self,
            config_path=self._app_config_path,
            resolved_tools=self._resolved_tool_paths,
            apply_config=apply_config,
            start_update=self._start_program_update,
        )
        dialog.encode_device_controls.set_devices(self.encode_device_controls.devices)
        self.encode_device_controls.devices_changed.connect(dialog.encode_device_controls.set_devices)
        self._apply_window_opacity(dialog)
        dialog.exec()
        dialog.deleteLater()
        if restart_requested:
            self._restart_for_ui_scale = True
            self._exit_application()

    def _current_ui_preferences(self) -> UiPreferences:
        font_size = int(getattr(self, "_ui_font_point_size", 10) or 10)
        return replace(
            self._app_config.ui,
            language=str(self.language_combo.currentData() or "en"),
            theme=str(self.theme_combo.currentData() or "light"),
            font_size=max(6, min(14, font_size)),
            opacity=self.opacity_slider.value(),
        )

    def _save_application_state(self) -> None:
        if getattr(self, "_app_config_load_failed", False):
            return
        updated = replace(
            self._app_config,
            window=self._current_window_preferences(),
            ui=self._current_ui_preferences(),
        )
        save_app_config(updated, self._app_config_path, preserve_tools=True)
        self._app_config = updated


__all__ = ["SettingsStateMixin"]
