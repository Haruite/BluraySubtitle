"""Focused contracts for persistent application settings."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel

import src.core.settings as core_settings
from src.core.app_config import (
    AppConfig,
    AudioPreferences,
    EncodePreferences,
    PathPreferences,
    RemuxPreferences,
    StartupPreferences,
    UiPreferences,
    UserEncodePreset,
    WindowPreferences,
    app_config_from_mapping,
    app_config_path,
    application_directory,
    default_app_config,
    default_config_path,
    load_app_config,
    save_app_config,
)
from src.core.i18n import translate_text
from src.core.version import APP_TITLE, APP_VERSION, is_newer_release, release_version
from src.runtime.gui_runtime_classes.bluray_subtitle_gui_entry import BluraySubtitleGUI
from src.runtime.gui_runtime_classes.settings_dialog import (
    GITHUB_RELEASES_URL,
    SettingsDialog,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class AppConfigTests(unittest.TestCase):
    def test_release_version_comparison_uses_numeric_tag_only(self) -> None:
        self.assertEqual(APP_VERSION, "4.5")
        self.assertEqual(APP_TITLE, f"BluraySubtitle v{APP_VERSION}")
        self.assertEqual(
            release_version({
                "tag_name": "v4.1.0",
                "body": "This field must not affect update checks.",
            }),
            "4.1.0",
        )
        self.assertTrue(is_newer_release("4.1", "4.0.9"))
        self.assertFalse(is_newer_release("4.0.0", "4.0"))
        with self.assertRaisesRegex(ValueError, "Invalid release version"):
            release_version({"tag_name": "release-tomorrow"})

    def test_default_template_is_valid(self) -> None:
        raw = json.loads(
            (REPOSITORY_ROOT / "config.default.json").read_text(encoding="utf-8")
        )
        config = app_config_from_mapping(raw)
        self.assertEqual(config, default_app_config())
        self.assertFalse(config.encode.check_corrupted_frames)
        self.assertEqual(config.encode.frame_check_luma_psnr_threshold_db, 30.0)
        self.assertEqual(config.encode.frame_check_chroma_psnr_threshold_db, 30.0)
        self.assertEqual(config.encode.vpy_deband_strength, 0.5)
        self.assertEqual(config.encode.vpy_antialiasing_strength, 0.5)

    def test_missing_config_is_created_from_packaged_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "config.json"
            template = root / "config.default.json"
            expected = replace(
                default_app_config(),
                ui=UiPreferences(language="zh", theme="dark", font_size=12, opacity=88),
                paths=PathPreferences(remux_output="R:/Remux", encode_output="E:/Encode"),
            )
            save_app_config(expected, template)

            loaded = load_app_config(target, template)

            self.assertEqual(loaded, expected)
            self.assertEqual(load_app_config(target, template), expected)
            raw = target.read_bytes()
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_invalid_existing_config_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"
            target.write_bytes(b"{broken")

            with self.assertRaisesRegex(ValueError, "Invalid JSON"):
                load_app_config(target)

            self.assertEqual(target.read_bytes(), b"{broken")

    def test_configuration_values_are_validated(self) -> None:
        raw = json.loads(json.dumps({
            "schema_version": 1,
            "window": {},
            "ui": {"font_size": 20},
            "startup": {},
            "paths": {},
        }))
        with self.assertRaisesRegex(ValueError, "font_size"):
            app_config_from_mapping(raw)

    def test_legacy_config_without_advanced_sections_uses_defaults(self) -> None:
        config = app_config_from_mapping({
            "schema_version": 1,
            "window": {},
            "ui": {},
            "startup": {},
            "paths": {},
        })

        self.assertEqual(config.audio, AudioPreferences())
        self.assertEqual(config.remux, RemuxPreferences())
        self.assertEqual(config.encode, EncodePreferences())

    def test_advanced_configuration_values_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "ffmpeg_flac_compression_level"):
            app_config_from_mapping({
                "schema_version": 1,
                "audio": {"ffmpeg_flac_compression_level": 13},
            })
        with self.assertRaisesRegex(ValueError, "bit depth"):
            app_config_from_mapping({
                "schema_version": 1,
                "encode": {"encoder": "x264", "bit_depth": "12"},
            })
        with self.assertRaisesRegex(ValueError, "use_getnative"):
            app_config_from_mapping({
                "schema_version": 1,
                "encode": {"use_getnative": "yes"},
            })
        with self.assertRaisesRegex(ValueError, "output_comparison_images"):
            app_config_from_mapping({
                "schema_version": 1,
                "encode": {"output_comparison_images": "yes"},
            })
        with self.assertRaisesRegex(ValueError, "check_corrupted_frames"):
            app_config_from_mapping({
                "schema_version": 1,
                "encode": {"check_corrupted_frames": "yes"},
            })
        with self.assertRaisesRegex(ValueError, "auto_crop_black_borders"):
            app_config_from_mapping({
                "schema_version": 1,
                "encode": {"auto_crop_black_borders": "yes"},
            })
        for name, value in (
                ("frame_check_luma_psnr_threshold_db", 100.1),
                ("frame_check_chroma_psnr_threshold_db", -0.1),
                ("vpy_denoise_strength", 3.1),
                ("vpy_dehalo_strength", -0.1),
                ("vpy_dering_strength", "medium"),
                ("vpy_deband_strength", 1.1),
                ("vpy_antialiasing_strength", True),
        ):
            with self.assertRaisesRegex(ValueError, name):
                app_config_from_mapping({
                    "schema_version": 1,
                    "encode": {name: value},
                })
        with self.assertRaisesRegex(ValueError, "built-in preset"):
            app_config_from_mapping({
                "schema_version": 1,
                "encode": {
                    "custom_presets": [{
                        "encoder": "x265",
                        "name": "Balanced",
                        "parameters": "--crf 17",
                    }],
                },
            })

    def test_legacy_edited_parameters_migrate_to_a_user_preset(self) -> None:
        config = app_config_from_mapping({
            "schema_version": 1,
            "encode": {
                "encoder": "x265",
                "preset": "Balanced",
                "preset_parameters": "--preset slow --crf 17",
            },
        })

        self.assertEqual(config.encode.preset, "Balanced Custom")
        self.assertEqual(config.encode.custom_presets, (
            UserEncodePreset(
                encoder="x265",
                name="Balanced Custom",
                parameters="--preset slow --crf 17",
            ),
        ))

    def test_saved_config_contains_only_user_defined_encode_presets(self) -> None:
        config = replace(
            default_app_config(),
            encode=replace(
                default_app_config().encode,
                preset="Cinema",
                custom_presets=(UserEncodePreset(
                    encoder="x265",
                    name="Cinema",
                    parameters="--preset slow --crf 17",
                ),),
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"

            save_app_config(config, target)
            raw = json.loads(target.read_text(encoding="utf-8"))

        self.assertNotIn("preset_parameters", raw["encode"])
        self.assertEqual(raw["encode"]["custom_presets"], [{
            "encoder": "x265",
            "name": "Cinema",
            "parameters": "--preset slow --crf 17",
        }])

    def test_frozen_paths_separate_writable_config_from_packaged_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable = root / "BluraySubtitle_windows_x64.exe"
            bundle_root = root / "_internal"
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(executable)),
                patch.object(sys, "_MEIPASS", str(bundle_root), create=True),
            ):
                self.assertEqual(application_directory(), executable.parent)
                self.assertEqual(app_config_path(), executable.parent / "config.json")
                self.assertEqual(
                    default_config_path(),
                    bundle_root / "config.default.json",
                )

    def test_frozen_settings_source_is_seeded_and_loaded_as_an_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bundle_root = root / "_internal"
            bundled_source = bundle_root / "src" / "core" / "settings.py"
            bundled_source.parent.mkdir(parents=True)
            bundled_source.write_text('FLAC_PATH = "bundled"\n', encoding="utf-8")
            executable = root / "BluraySubtitle_windows_x64.exe"
            original_flac_path = core_settings.FLAC_PATH
            try:
                with (
                    patch.object(core_settings, "_BUNDLE_ROOT", str(bundle_root)),
                    patch.object(sys, "executable", str(executable)),
                ):
                    editable = core_settings.ensure_editable_settings_file()
                    self.assertEqual(
                        editable,
                        root / "src" / "core" / "settings.py",
                    )
                    self.assertEqual(
                        editable.read_text(encoding="utf-8"),
                        'FLAC_PATH = "bundled"\n',
                    )
                    editable.write_text(
                        'FLAC_PATH = "override"\n',
                        encoding="utf-8",
                    )
                    core_settings._load_editable_settings()
                    self.assertEqual(core_settings.FLAC_PATH, "override")
            finally:
                core_settings.FLAC_PATH = original_flac_path


class SettingsGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_edits_general_path_and_advanced_defaults(self) -> None:
        config = replace(
            default_app_config(),
            encode=replace(
                default_app_config().encode,
                frame_check_luma_psnr_threshold_db=27.5,
                frame_check_chroma_psnr_threshold_db=38.5,
            ),
        )
        dialog = SettingsDialog(config, lambda text: text)
        self.assertEqual(
            dialog.language_combo.itemText(dialog.language_combo.findData("zh")),
            translate_text("Simplified Chinese", "zh"),
        )
        dialog.function_page_combo.setCurrentIndex(
            dialog.function_page_combo.findData("bluray_encode")
        )
        dialog.episode_mode_combo.setCurrentIndex(
            dialog.episode_mode_combo.findData("movie")
        )
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("zh"))
        dialog.theme_combo.setCurrentIndex(dialog.theme_combo.findData("dark"))
        dialog.font_size_spin.setValue(12)
        dialog.opacity_spin.setValue(85)
        dialog.remux_output_edit.setText("R:/Remux")
        dialog.encode_output_edit.setText("E:/Encode")
        dialog.flac_compression_spin.setValue(6)
        dialog.ffmpeg_flac_compression_spin.setValue(11)
        dialog.fdkaac_bitrate_spin.setValue(320)
        dialog.opus_bitrate_spin.setValue(192)
        dialog.default_encoder_combo.setCurrentIndex(
            dialog.default_encoder_combo.findData("x264")
        )
        dialog.default_bit_depth_combo.setCurrentIndex(
            dialog.default_bit_depth_combo.findData("10")
        )
        dialog.default_preset_combo.setCurrentIndex(
            dialog.default_preset_combo.findData("High Quality")
        )
        dialog._add_custom_encode_preset()
        dialog._edit_custom_preset_name("Archival")
        dialog._edit_custom_preset_parameters("--preset slow --crf 17")
        dialog.default_preset_combo.setCurrentIndex(
            dialog.default_preset_combo.findData("Archival")
        )
        dialog.default_lossless_audio_combo.setCurrentIndex(
            dialog.default_lossless_audio_combo.findData("opus")
        )
        dialog.default_subtitle_mode_combo.setCurrentIndex(
            dialog.default_subtitle_mode_combo.findData("softsub")
        )
        dialog.default_getnative_checkbox.setChecked(False)
        dialog.default_auto_crop_checkbox.setChecked(True)
        dialog.default_output_comparison_checkbox.setChecked(False)
        dialog.default_frame_check_checkbox.setChecked(True)
        self.assertEqual(dialog.frame_check_luma_psnr_threshold_spin.value(), 27.5)
        self.assertEqual(dialog.frame_check_chroma_psnr_threshold_spin.value(), 38.5)
        dialog.frame_check_luma_psnr_threshold_spin.setValue(29.5)
        dialog.frame_check_chroma_psnr_threshold_spin.setValue(41.5)
        dialog.default_vpy_denoise_strength_spin.setValue(0.8)
        dialog.default_vpy_dehalo_strength_spin.setValue(0.3)
        dialog.default_vpy_dering_strength_spin.setValue(0.4)
        dialog.default_vpy_deband_strength_spin.setValue(0.5)
        dialog.default_vpy_antialiasing_strength_spin.setValue(0.6)
        dialog.remux_flac_default_checkbox.setChecked(False)

        selected = dialog.selected_config()

        self.assertEqual(
            selected.startup,
            StartupPreferences(function_page="bluray_encode", episode_mode="movie"),
        )
        self.assertEqual(
            selected.ui,
            UiPreferences(language="zh", theme="dark", font_size=12, opacity=85),
        )
        self.assertEqual(
            selected.paths,
            PathPreferences(remux_output="R:/Remux", encode_output="E:/Encode"),
        )
        self.assertEqual(
            selected.audio,
            AudioPreferences(
                flac_compression_level=6,
                ffmpeg_flac_compression_level=11,
                fdkaac_bitrate_kbps=320,
                opus_bitrate_kbps=192,
            ),
        )
        self.assertEqual(
            selected.remux,
            RemuxPreferences(convert_lossless_audio_to_flac=False),
        )
        self.assertEqual(
            selected.encode,
            EncodePreferences(
                encoder="x264",
                bit_depth="10",
                preset="Archival",
                custom_presets=(UserEncodePreset(
                    encoder="x264",
                    name="Archival",
                    parameters="--preset slow --crf 17",
                ),),
                lossless_audio_codec="opus",
                subtitle_mode="softsub",
                use_getnative=False,
                auto_crop_black_borders=True,
                output_comparison_images=False,
                check_corrupted_frames=True,
                frame_check_luma_psnr_threshold_db=29.5,
                frame_check_chroma_psnr_threshold_db=41.5,
                vpy_denoise_strength=0.8,
                vpy_dehalo_strength=0.3,
                vpy_dering_strength=0.4,
                vpy_deband_strength=0.5,
                vpy_antialiasing_strength=0.6,
            ),
        )
        labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("src/core/settings.py", labels)
        self.assertIn(
            "Higher FFmpeg FLAC compression levels can significantly increase Remux time.",
            labels,
        )
        self.assertIn("FDK-AAC 128–256 kbps; Opus 64–128 kbps", labels)
        self.assertIn("Frame check luma PSNR threshold", labels)
        self.assertIn("Frame check chroma PSNR threshold", labels)
        self.assertIn(f"Current version: {APP_VERSION}", labels)
        dialog.buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).click()
        self.assertEqual(dialog.frame_check_luma_psnr_threshold_spin.value(), 30.0)
        self.assertEqual(dialog.frame_check_chroma_psnr_threshold_spin.value(), 30.0)
        dialog.close()

    def test_custom_encode_preset_editor_filters_and_protects_built_ins(self) -> None:
        config = replace(
            default_app_config(),
            encode=replace(
                default_app_config().encode,
                custom_presets=(
                    UserEncodePreset("x264", "Legacy", "--crf 19"),
                    UserEncodePreset("x265", "Cinema", "--crf 17"),
                ),
            ),
        )
        dialog = SettingsDialog(config, lambda text: text)

        visible = [
            dialog.custom_preset_combo.itemText(index)
            for index in range(dialog.custom_preset_combo.count())
        ]
        self.assertIn("Cinema", visible)
        self.assertNotIn("Legacy", visible)
        self.assertTrue(dialog.custom_preset_name_edit.isReadOnly())
        self.assertTrue(dialog.custom_preset_parameters_edit.isReadOnly())
        self.assertFalse(dialog.delete_custom_preset_button.isEnabled())

        custom_index = next(
            index
            for index in range(dialog.custom_preset_combo.count())
            if dialog.custom_preset_combo.itemData(index) == ("custom", 1)
        )
        dialog.custom_preset_combo.setCurrentIndex(custom_index)
        self.assertFalse(dialog.custom_preset_name_edit.isReadOnly())
        self.assertFalse(dialog.custom_preset_parameters_edit.isReadOnly())
        self.assertTrue(dialog.delete_custom_preset_button.isEnabled())

        dialog.default_encoder_combo.setCurrentIndex(
            dialog.default_encoder_combo.findData("x264")
        )
        visible = [
            dialog.custom_preset_combo.itemText(index)
            for index in range(dialog.custom_preset_combo.count())
        ]
        self.assertIn("Legacy", visible)
        self.assertNotIn("Cinema", visible)
        dialog.close()

    def test_builtin_preset_name_uses_the_dialog_language(self) -> None:
        dialog = SettingsDialog(
            default_app_config(),
            lambda text: translate_text(text, "zh"),
        )
        high_quality_index = next(
            index
            for index in range(dialog.custom_preset_combo.count())
            if dialog.custom_preset_combo.itemData(index)
            == ("built_in", "High Quality")
        )

        dialog.custom_preset_combo.setCurrentIndex(high_quality_index)

        self.assertEqual(
            dialog.custom_preset_combo.currentText(),
            translate_text("High Quality", "zh"),
        )
        self.assertEqual(
            dialog.custom_preset_name_edit.text(),
            translate_text("High Quality", "zh"),
        )
        dialog.close()

    def test_update_available_message_links_release_and_migration_reminder(
            self
    ) -> None:
        dialog = SettingsDialog(default_app_config(), lambda text: text)

        message = dialog._update_available_message("4.1")

        self.assertIn(GITHUB_RELEASES_URL, message)
        self.assertIn("Version 4.1 is available.", message)
        self.assertIn(
            "copy config.json from the current program directory to the new "
            "program directory",
            message,
        )
        dialog.close()

    def test_update_check_starts_only_when_requested(self) -> None:
        class FinishedSignal:
            def __init__(self) -> None:
                self.callback = None

            def connect(self, callback) -> None:
                self.callback = callback

        class Reply:
            def __init__(self) -> None:
                self.finished = FinishedSignal()

        class NetworkManager:
            def __init__(self) -> None:
                self.request = None
                self.reply = Reply()

            def get(self, request):
                self.request = request
                return self.reply

        dialog = SettingsDialog(default_app_config(), lambda text: text)
        manager = NetworkManager()
        dialog._update_network_manager = manager

        self.assertIsNone(manager.request)
        dialog._check_for_updates()

        self.assertEqual(
            manager.request.url().toString(),
            "https://api.github.com/repos/Haruite/BluraySubtitle/releases/latest",
        )
        self.assertEqual(
            bytes(manager.request.rawHeader(b"Accept")),
            b"application/vnd.github+json",
        )
        self.assertEqual(manager.request.transferTimeout(), 15_000)
        self.assertFalse(dialog.check_updates_button.isEnabled())
        self.assertIsNotNone(manager.reply.finished.callback)
        dialog._update_reply = None
        dialog.close()

    def test_external_tools_editor_saves_valid_python_with_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "settings.py"
            target.write_text('FFMPEG_PATH = "old"\n', encoding="utf-8")
            dialog = SettingsDialog(
                default_app_config(),
                lambda text: text,
                settings_source_path=target,
            )
            self.assertIn('FFMPEG_PATH = "old"', dialog.external_tools_editor.toPlainText())
            dialog.external_tools_editor.setPlainText('FFMPEG_PATH = "new"\n')

            dialog.accept()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            raw = target.read_bytes()
            self.assertIn(b'FFMPEG_PATH = "new"', raw)
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_external_tools_editor_rejects_invalid_python(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "settings.py"
            original = b'FFMPEG_PATH = "old"\r\n'
            target.write_bytes(original)
            dialog = SettingsDialog(
                default_app_config(),
                lambda text: text,
                settings_source_path=target,
            )
            dialog.external_tools_editor.setPlainText("if")

            with patch(
                    "src.runtime.gui_runtime_classes.settings_dialog.QMessageBox.warning"
            ) as warning:
                dialog.accept()

            self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
            self.assertEqual(target.read_bytes(), original)
            warning.assert_called_once()
            dialog.close()

    def test_external_tools_path_detection_reports_platform_setup_script(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "settings.py"
            missing_tool = root / "ffmpeg.exe"
            hdr10plus_tool = root / "hdr10plus_tool.exe"
            dovi_tool = root / "dovi_tool.exe"
            target.write_text('FFMPEG_PATH = "ffmpeg.exe"\n', encoding="utf-8")
            with (
                patch(
                    "src.runtime.gui_runtime_classes.settings_dialog."
                    "EXTERNAL_TOOL_PATH_NAMES",
                    ("FFMPEG_PATH",),
                ),
                patch.object(core_settings, "FFMPEG_PATH", str(missing_tool)),
                patch.object(
                    core_settings,
                    "HDR10PLUS_TOOL_PATH",
                    str(hdr10plus_tool),
                ),
                patch.object(core_settings, "DOVI_TOOL_PATH", str(dovi_tool)),
                patch(
                    "src.runtime.gui_runtime_classes.settings_dialog."
                    "probe_x265_dynamic_metadata_options",
                    return_value=frozenset({
                        "--dhdr10-info",
                        "--dolby-vision-profile",
                        "--dolby-vision-rpu",
                    }),
                ) as x265_probe,
                patch.object(sys, "platform", "win32"),
            ):
                dialog = SettingsDialog(
                    default_app_config(),
                    lambda text: text,
                    settings_source_path=target,
                )
                self.assertIn(
                    str(missing_tool),
                    dialog.external_tools_detection_view.toPlainText(),
                )
                self.assertIn(
                    "setup_windows_environment.ps1",
                    dialog.external_tools_detection_view.toPlainText(),
                )
                self.assertIn(
                    str(hdr10plus_tool),
                    dialog.external_tools_detection_view.toPlainText(),
                )
                self.assertIn(
                    str(dovi_tool),
                    dialog.external_tools_detection_view.toPlainText(),
                )

                missing_tool.write_bytes(b"tool")
                x265_probe.return_value = frozenset()
                dialog._refresh_external_tool_detection()

                self.assertEqual(
                    dialog.external_tools_detection_view.toPlainText(),
                    "All configured tool paths in settings.py were found.",
                )
                dialog.close()

    def test_startup_defaults_and_page_specific_output_paths_are_applied(self) -> None:
        config = AppConfig(
            window=WindowPreferences(),
            ui=UiPreferences(language="en", theme="light", font_size=10, opacity=94),
            startup=StartupPreferences(
                function_page="bluray_encode",
                episode_mode="movie",
            ),
            paths=PathPreferences(
                remux_output=r"R:\Remux",
                encode_output=r"E:\Encode",
            ),
            remux=RemuxPreferences(
                convert_lossless_audio_to_flac=False,
            ),
            encode=EncodePreferences(
                encoder="x264",
                bit_depth="10",
                preset="Archival",
                custom_presets=(UserEncodePreset(
                    encoder="x264",
                    name="Archival",
                    parameters="--preset slow --crf 17",
                ),),
                lossless_audio_codec="opus",
                subtitle_mode="softsub",
                use_getnative=False,
                auto_crop_black_borders=True,
                output_comparison_images=False,
                check_corrupted_frames=True,
                vpy_denoise_strength=0.8,
                vpy_dehalo_strength=0.3,
                vpy_dering_strength=0.4,
                vpy_deband_strength=0.5,
                vpy_antialiasing_strength=0.6,
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"
            with (
                patch(
                    "src.runtime.gui_runtime_split.lifecycle_and_bootstrap.app_config_path",
                    return_value=target,
                ),
                patch(
                    "src.runtime.gui_runtime_split.lifecycle_and_bootstrap.load_app_config",
                    return_value=config,
                ),
            ):
                window = BluraySubtitleGUI()

            self.assertEqual(window.get_selected_function_id(), 4)
            self.assertTrue(window.movie_mode_radio.isChecked())
            self.assertEqual(window.output_folder_path.text(), r"E:\Encode")
            self.assertEqual(window.encode_tool_combo.currentText(), "x264")
            self.assertEqual(window.encode_bit_depth_combo.currentData(), "10")
            self.assertEqual(window.x265_preset_combo.currentData(), "Archival")
            self.assertEqual(
                window.x265_params_edit.toPlainText(),
                "--preset slow --crf 17",
            )
            self.assertEqual(window.x265_preset_combo.findData("Custom"), -1)
            window.x265_params_edit.setPlainText("--preset slow --crf 16")
            self.assertEqual(window.x265_preset_combo.currentData(), "Archival")
            window.encode_tool_combo.setCurrentText("x265")
            self.assertEqual(window.x265_preset_combo.findData("Archival"), -1)
            window.encode_tool_combo.setCurrentText("x264")
            self.assertGreaterEqual(
                window.x265_preset_combo.findData("Archival"),
                0,
            )
            self.assertEqual(window.encode_lossless_audio_combo.currentData(), "opus")
            self.assertTrue(window.sub_pack_soft_radio.isChecked())
            self.assertFalse(window.use_getnative_checkbox.isChecked())
            self.assertTrue(window.auto_crop_black_borders_checkbox.isChecked())
            self.assertFalse(window.output_comparison_checkbox.isChecked())
            self.assertTrue(window.frame_check_checkbox.isChecked())
            self.assertFalse(hasattr(window, "frame_check_luma_psnr_threshold_spin"))
            self.assertFalse(hasattr(window, "frame_check_chroma_psnr_threshold_spin"))
            options_layout = window.encode_options_row.layout()
            self.assertLess(
                options_layout.indexOf(window.output_comparison_checkbox),
                options_layout.indexOf(window.frame_check_checkbox),
            )
            self.assertEqual(window.vpy_denoise_strength_spin.value(), 0.8)
            self.assertEqual(window.vpy_dehalo_strength_spin.value(), 0.3)
            self.assertEqual(window.vpy_dering_strength_spin.value(), 0.4)
            self.assertEqual(window.vpy_deband_strength_spin.value(), 0.5)
            self.assertEqual(window.vpy_antialiasing_strength_spin.value(), 0.6)
            self.assertFalse(window.remux_flac_checkbox.isChecked())
            self.assertIs(
                window.lossless_audio_compression_label.parentWidget(),
                window.vspipe_mode_combo.parentWidget(),
            )
            self.assertIs(
                window.use_getnative_checkbox.parentWidget(),
                window.output_comparison_checkbox.parentWidget(),
            )
            options_layout = window.use_getnative_checkbox.parentWidget().layout()
            self.assertLess(
                options_layout.indexOf(window.use_getnative_checkbox),
                options_layout.indexOf(window.output_comparison_checkbox),
            )
            self.assertIsNot(
                window.use_getnative_checkbox.parentWidget(),
                window.encode_lossless_audio_combo.parentWidget(),
            )
            encode_layout = window.encode_options_row.parentWidget().layout()
            self.assertLess(
                encode_layout.indexOf(window.encode_options_row),
                encode_layout.indexOf(window.vpy_processing_row),
            )
            self.assertLess(
                encode_layout.indexOf(window.vpy_processing_row),
                encode_layout.indexOf(window.x265_params_edit),
            )

            window.output_folder_path.setText(r"E:\Session")
            window.function_tabbar.setCurrentIndex(0)
            self.assertEqual(window.get_selected_function_id(), 3)
            self.assertEqual(window.output_folder_path.text(), r"R:\Remux")

            window.output_folder_path.setText(r"R:\Session")
            window.function_tabbar.setCurrentIndex(1)
            self.assertEqual(window.output_folder_path.text(), r"E:\Session")
            window.function_tabbar.setCurrentIndex(0)
            self.assertEqual(window.output_folder_path.text(), r"R:\Session")

            window.close()
            saved = load_app_config(target)
            self.assertEqual(saved.paths, config.paths)
            self.assertTrue(saved.window.geometry)

    def test_unrestorable_geometry_is_reported_without_overwriting_config(self) -> None:
        config = replace(
            default_app_config(),
            window=WindowPreferences(geometry="AA=="),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            target = Path(temporary_directory) / "config.json"
            save_app_config(config, target)
            original = target.read_bytes()
            with (
                patch(
                    "src.runtime.gui_runtime_split.lifecycle_and_bootstrap.app_config_path",
                    return_value=target,
                ),
                patch(
                    "src.runtime.gui_runtime_split.lifecycle_and_bootstrap.load_app_config",
                    return_value=config,
                ),
                patch(
                    "src.runtime.gui_runtime_split.lifecycle_and_bootstrap.QTimer.singleShot",
                    return_value=None,
                ),
            ):
                window = BluraySubtitleGUI()

            self.assertTrue(window._app_config_load_failed)
            window.close()
            self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
