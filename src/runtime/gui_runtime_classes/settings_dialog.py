"""Application settings dialog."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontDatabase, QImageReader, QShowEvent
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QDialogButtonBox,
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
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import src.core.settings as core_settings
from src.core.app_config import (
    MAX_BACKGROUND_BLUR,
    MAX_LOG_LINE_LIMIT,
    AppConfig,
    AudioPreferences,
    EncodePreferences,
    FontPreferences,
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
from src.core.version import (
    APP_VERSION,
    CommitInfo,
    current_commit,
    is_newer_release,
    parse_commit_record,
    release_version,
)
from src.exports.utils import resolve_encoder_executable_path
from src.runtime.desktop_integration import create_launch_shortcut
from src.runtime.encode_source import (
    probe_svt_av1_bit_depths,
    probe_x265_dynamic_metadata_options,
)
from src.runtime.update_check import SERVER_PACKAGE_METADATA_URL, request_update_info, update_network_manager
from src.runtime.windows_update import (
    GITHUB_LATEST_RELEASE_API,
    WindowsUpdatePackage,
    github_windows_package,
    server_windows_package,
    windows_update_executable,
)

from .custom_table_widget import StyledComboBox
from .file_dialog import choose_path
from .spin_box import StyledDoubleSpinBox, StyledSpinBox
from .widget_animations import (
    AnimatedDialog, AnimatedMessageBox, supports_window_opacity, window_is_fading_out, window_opacity,
)


EXTERNAL_TOOL_PATH_NAMES = (
    "SEVEN_ZIP_PATH",
    "FLAC_PATH",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "X265_PATH",
    "X264_PATH",
    "SVT_AV1_PATH",
    "FDK_AAC_PATH",
    "VSEDIT_PATH",
    "VSPIPE_PATH",
    "TS_MUXER_PATH",
    "MKV_INFO_PATH",
    "MKV_MERGE_PATH",
    "MKV_PROP_EDIT_PATH",
    "MKV_EXTRACT_PATH",
)


class SettingsDialog(AnimatedDialog):
    def __init__(
            self,
            config: AppConfig,
            translate: Callable[[str], str],
            parent: QWidget | None = None,
            settings_source_path: Path | None = None,
            encoder_mode: str = "system",
            *,
            apply_config: Callable[[AppConfig], bool] | None = None,
            start_update: Callable[[WindowsUpdatePackage], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._apply_config = apply_config
        self._start_update = start_update
        self._encoder_mode = encoder_mode
        self.t = translate
        self._custom_encode_presets = list(config.encode.custom_presets)
        self._preset_editor_updating = False
        self._settings_source_path = (
            Path(settings_source_path)
            if settings_source_path is not None
            else core_settings.ensure_editable_settings_file()
        )
        self._settings_source_text: str | None = None
        self._current_commit = current_commit()
        self._update_network_manager = update_network_manager(self)
        self._update_replies: tuple[QNetworkReply, QNetworkReply] | None = None
        self.finished.connect(self._cancel_update_check)
        self.setWindowTitle(self.t("Settings"))
        self.setMinimumWidth(680)
        self._initial_size_set = False

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        self._general_scroll = self._build_general_tab()
        tabs.addTab(self._general_scroll, self.t("General"))
        tabs.addTab(self._build_fonts_tab(), self.t("Fonts"))
        tabs.addTab(self._build_paths_tab(), self.t("Paths"))
        tabs.addTab(self._build_advanced_tab(), self.t("Advanced"))
        tabs.addTab(self._build_tools_tab(), self.t("Tools"))
        tabs.addTab(self._build_external_tools_tab(), self.t("External tools"))
        layout.addWidget(tabs)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(self.t("Save"))
        apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply_button.setText(self.t("Apply"))
        apply_button.clicked.connect(self._apply_settings)
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

    def showEvent(self, event: QShowEvent) -> None:
        first_show = not event.spontaneous() and not self._initial_size_set
        if first_show:
            self._initial_size_set = True
            self._fit_general_tab_height()
        super().showEvent(event)
        if first_show and not QApplication.platformName().startswith("wayland"):
            screen = self.screen()
            if screen is None:
                return
            available = screen.availableGeometry()
            frame = self.frameGeometry()
            top = max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
            if top != frame.top():
                self.move(frame.left(), top)

    def _fit_general_tab_height(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        scroll = self._general_scroll
        viewport = scroll.maximumViewportSize()
        general = scroll.widget()
        content_height = general.heightForWidth(viewport.width())
        if content_height < 0:
            content_height = general.sizeHint().height()
        controls_height = self.height() - viewport.height()
        style = self.style()
        # The window manager may supply the frame margins only after mapping.
        frame_height = max(
            self.frameGeometry().height() - self.height(),
            style.pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight, widget=self)
            + 2 * style.pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth, widget=self),
        )
        available_height = screen.availableGeometry().height() - frame_height
        self.resize(self.width(), min(content_height + controls_height, available_height))

    def _build_general_tab(self) -> QScrollArea:
        tab = QWidget(self)
        form = QFormLayout(tab)

        self.function_page_combo = StyledComboBox(tab)
        for text, value in (
            ("Blu-ray Remux", "bluray_remux"),
            ("Blu-ray Encode", "bluray_encode"),
            ("Blu-ray DIY", "bluray_diy"),
            ("Merge Subtitles", "merge_subtitles"),
            ("Add Chapters To MKV", "add_chapters"),
        ):
            self.function_page_combo.addItem(self.t(text), value)
        form.addRow(self.t("Startup function page"), self.function_page_combo)

        self.episode_mode_combo = StyledComboBox(tab)
        self.episode_mode_combo.addItem(self.t("Series mode"), "series")
        self.episode_mode_combo.addItem(self.t("Movie mode"), "movie")
        form.addRow(self.t("Default episode mode"), self.episode_mode_combo)

        self.language_combo = StyledComboBox(tab)
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem(
            translate_text("Simplified Chinese", "zh"),
            "zh",
        )
        form.addRow(self.t("UI language"), self.language_combo)

        self.theme_combo = StyledComboBox(tab)
        self.theme_combo.addItem(self.t("Light"), "light")
        self.theme_combo.addItem(self.t("Dark"), "dark")
        self.theme_combo.addItem(self.t("Colorful"), "colorful")
        form.addRow(self.t("Theme"), self.theme_combo)

        self.opacity_spin = StyledSpinBox(tab)
        self.opacity_spin.setRange(60, 100)
        self.opacity_spin.setSuffix("%")
        opacity_label = QLabel(self.t("Window opacity"), tab)
        opacity_label.setBuddy(self.opacity_spin)
        form.addRow(opacity_label, self.opacity_spin)
        if not supports_window_opacity():
            self.opacity_spin.setEnabled(False)
            help_text = self.t("Window opacity requires Windows or a composited X11 session.")
            self.opacity_spin.setToolTip(help_text)
            opacity_label.setToolTip(help_text)

        self.main_background_opacity_spin = StyledSpinBox(tab)
        self.main_background_opacity_spin.setRange(0, 100)
        self.main_background_opacity_spin.setSuffix("%")
        form.addRow(self.t("Main background image opacity"), self.main_background_opacity_spin)
        self.main_background_blur_spin = StyledSpinBox(tab)
        self.main_background_blur_spin.setRange(0, MAX_BACKGROUND_BLUR)
        form.addRow(self.t("Main background image blur strength"), self.main_background_blur_spin)

        self.log_background_opacity_spin = StyledSpinBox(tab)
        self.log_background_opacity_spin.setRange(0, 100)
        self.log_background_opacity_spin.setSuffix("%")
        form.addRow(self.t("Log background image opacity"), self.log_background_opacity_spin)
        self.log_background_blur_spin = StyledSpinBox(tab)
        self.log_background_blur_spin.setRange(0, MAX_BACKGROUND_BLUR)
        form.addRow(self.t("Log background image blur strength"), self.log_background_blur_spin)
        blur_hint = QLabel(self.t("Blur strength ranges from 0 to 40. Set it to 0 to keep the background image sharp."), tab)
        blur_hint.setWordWrap(True)
        form.addRow(blur_hint)

        self.close_to_tray_checkbox = QCheckBox(
            self.t("Minimize to the system tray when closing the main window"), tab,
        )
        form.addRow(self.close_to_tray_checkbox)
        self.save_log_checkbox = QCheckBox(self.t("Save log to file"), tab)
        form.addRow(self.save_log_checkbox)
        self.log_line_limit_spin = StyledSpinBox(tab)
        self.log_line_limit_spin.setRange(1, MAX_LOG_LINE_LIMIT)
        form.addRow(self.t("Log line limit"), self.log_line_limit_spin)
        self.log_theme_combo = StyledComboBox(tab)
        self.log_theme_combo.addItem(self.t("Follow main window"), "follow")
        for index in range(self.theme_combo.count()):
            self.log_theme_combo.addItem(self.theme_combo.itemText(index), self.theme_combo.itemData(index))
        form.addRow(self.t("Log window theme"), self.log_theme_combo)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(tab)
        tab.setAutoFillBackground(False)
        return scroll

    def _build_tools_tab(self) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        update_row = QWidget(tab)
        update_layout = QVBoxLayout(update_row)
        update_layout.setContentsMargins(0, 0, 0, 0)
        self.current_version_label = QLabel(self._current_build_summary(), update_row)
        self.current_version_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.startup_update_checkbox = QCheckBox(self.t("Check for updates at startup"), update_row)
        self.check_updates_button = QPushButton(
            self.t("Check for updates"),
            update_row,
        )
        self.check_updates_button.clicked.connect(
            lambda _=None: self._check_for_updates()
        )
        update_layout.addWidget(self.current_version_label)
        update_layout.addWidget(self.startup_update_checkbox)
        update_layout.addWidget(self.check_updates_button, alignment=Qt.AlignmentFlag.AlignLeft)
        form.addRow(self.t("Application updates"), update_row)

        shortcuts = QWidget(tab)
        shortcut_layout = QHBoxLayout(shortcuts)
        shortcut_layout.setContentsMargins(0, 0, 0, 0)
        desktop_button = QPushButton(self.t("Add desktop shortcut"), shortcuts)
        menu_button = QPushButton(self.t("Add to application menu"), shortcuts)
        desktop_button.clicked.connect(lambda _=False: self._add_launch_shortcut(menu=False))
        menu_button.clicked.connect(lambda _=False: self._add_launch_shortcut(menu=True))
        shortcut_layout.addWidget(desktop_button)
        shortcut_layout.addWidget(menu_button)
        shortcut_layout.addStretch()
        form.addRow(self.t("Launch shortcuts"), shortcuts)
        self._shortcut_status = QLabel(tab)
        self._shortcut_status.setTextFormat(Qt.TextFormat.PlainText)
        self._shortcut_status.setWordWrap(True)
        self._shortcut_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._shortcut_status.hide()
        form.addRow(self._shortcut_status)
        return tab

    def _add_launch_shortcut(self, *, menu: bool) -> None:
        try:
            path = create_launch_shortcut(menu=menu)
        except (OSError, RuntimeError, ValueError) as error:
            message = self.t("Could not create the shortcut. {error}").format(error=error)
        else:
            message = self.t("Shortcut created at {path}.").format(path=path)
        self._shortcut_status.setText(message)
        self._shortcut_status.show()

    def _build_fonts_tab(self) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        self.font_size_spin = StyledSpinBox(tab)
        self.font_size_spin.setRange(6, 14)
        form.addRow(self.t("UI font size"), self.font_size_spin)

        families = sorted(QFontDatabase.families(), key=str.casefold)
        self.font_family_combos: dict[str, QComboBox] = {}
        for role, label, default_label in (
            ("interface", "Interface font", "System default font"),
            ("table", "Table font", "Follow interface font"),
            ("log", "Log output font", "Follow interface font"),
            ("editor", "Text editor font", "Default editor font"),
        ):
            combo = StyledComboBox(tab)
            combo.setProperty("fontDefaultLabel", default_label)
            combo.addItem(self.t(default_label), "")
            for family in families:
                combo.addItem(family, family)
            self.font_family_combos[role] = combo
            form.addRow(self.t(label), combo)
        return tab

    def _commit_lines(self, commit: CommitInfo | None) -> tuple[str, str]:
        if commit is None:
            commit_hash = commit_time = self.t("unknown")
        else:
            commit_hash = commit.commit_hash
            commit_time = commit.committed_at.isoformat(sep=" ", timespec="seconds")
        return (
            self.t("Commit hash: {hash}").format(hash=commit_hash),
            self.t("Commit time: {time}").format(time=commit_time),
        )

    def _current_build_summary(self) -> str:
        return "\n".join((
            self.t("Current version: {version}").format(version=APP_VERSION),
            *self._commit_lines(self._current_commit),
        ))

    def _set_update_check_busy(self, busy: bool) -> None:
        self.check_updates_button.setEnabled(not busy)
        text = "Checking for updates..." if busy else "Check for updates"
        self.check_updates_button.setText(self.t(text))

    def _check_for_updates(self) -> None:
        if self._update_replies is not None:
            return
        self._set_update_check_busy(True)
        manager = self._update_network_manager
        self._update_replies = (
            request_update_info(manager, GITHUB_LATEST_RELEASE_API, b"application/vnd.github+json"),
            request_update_info(manager, SERVER_PACKAGE_METADATA_URL, b"text/plain"),
        )
        for reply in self._update_replies:
            reply.finished.connect(self._finish_update_check)

    def _cancel_update_check(self) -> None:
        replies = self._update_replies
        if replies is None:
            return
        self._update_replies = None
        for reply in replies:
            reply.abort()
            reply.deleteLater()
        self._set_update_check_busy(False)

    def _finish_update_check(self) -> None:
        replies = self._update_replies
        if replies is None or not all(reply.isFinished() for reply in replies):
            return
        self._update_replies = None
        self._set_update_check_busy(False)
        release_reply, package_reply = replies
        release_result = self._read_update_reply(
            release_reply,
            self._release_update_result,
            "GitHub did not return a valid release version.",
        )
        package_result = self._read_update_reply(
            package_reply,
            self._server_package_update_result,
            "The server did not return valid package commit information.",
        )
        self._show_update_results(release_result, package_result)

    def _read_update_reply(
            self,
            reply: QNetworkReply,
            render: Callable[[str], tuple[str, WindowsUpdatePackage | None]],
            invalid_reply_message: str,
    ) -> tuple[str, WindowsUpdatePackage | None]:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                message = self.t("Could not check for updates: {error}").format(
                    error=reply.errorString()
                )
                return escape(message), None
            return render(bytes(reply.readAll()).decode("utf-8"))
        except ValueError:
            return escape(self.t(invalid_reply_message)), None
        finally:
            reply.deleteLater()

    def _release_update_result(self, response: str) -> tuple[str, WindowsUpdatePackage | None]:
        payload = json.loads(response)
        if not isinstance(payload, dict):
            raise ValueError("GitHub release response must be an object")
        latest_version = release_version(payload)
        if not is_newer_release(latest_version):
            status = self.t("Latest Release version is {version}. Your version is up to date.")
            return escape(status.format(version=latest_version)), None
        status = escape(self.t("Version {version} is available.").format(version=latest_version))
        package = github_windows_package(payload)
        if package is None:
            status += "<br>" + escape(self.t("The update source did not provide a verified Windows package."))
        return status, package

    def _server_package_update_result(self, response: str) -> tuple[str, WindowsUpdatePackage | None]:
        server_commit = parse_commit_record(response)
        installed_commit = self._current_commit
        offer_package = True
        if installed_commit is None:
            status = self.t("Your current commit is unknown. A server package is available.")
        elif server_commit.commit_hash == installed_commit.commit_hash:
            status = self.t("The server package matches your current commit.")
            offer_package = False
        elif server_commit.committed_at > installed_commit.committed_at:
            status = self.t("A newer server package is available.")
        elif server_commit.committed_at < installed_commit.committed_at:
            status = self.t("The server package is from an older commit.")
            offer_package = False
        else:
            status = self.t("The server package has a different commit with the same commit time.")
        lines = [escape(line) for line in (*self._commit_lines(server_commit), status)]
        package = server_windows_package(response) if offer_package else None
        if offer_package and package is None:
            lines.append(escape(self.t("The update source did not provide a verified Windows package.")))
        return "<br>".join(lines), package

    def _show_update_results(
            self,
            release_result: tuple[str, WindowsUpdatePackage | None],
            package_result: tuple[str, WindowsUpdatePackage | None],
    ) -> None:
        release_text, github_package = release_result
        server_text, server_package = package_result
        current_build = "<br>".join(escape(line) for line in self._current_build_summary().splitlines())
        sections = (
            (self.t("Current build"), current_build),
            (self.t("GitHub Release"), release_text),
            (self.t("Server Windows x64 package"), server_text),
        )
        message = "".join(f"<p><b>{escape(title)}</b><br>{body}</p>" for title, body in sections)
        start_update = self._start_update
        can_update = start_update is not None and windows_update_executable() is not None
        if github_package is not None or server_package is not None:
            reminder = (
                self.t("The program will close and reopen automatically after the update.") if can_update
                else self.t("Direct updates require the packaged Windows program and its bundled 7-Zip.")
            )
            message += f"<p>{escape(reminder)}</p>"
        message_box = AnimatedMessageBox(self)
        message_box.setOption(QMessageBox.Option.DontUseNativeDialog)
        opacity = window_opacity(self)
        if opacity < 1.0:
            message_box.setWindowOpacity(opacity)
        message_box.setWindowTitle(self.t("Check for updates"))
        message_box.setIcon(QMessageBox.Icon.Information)
        message_box.setTextFormat(Qt.TextFormat.RichText)
        message_box.setText(message)
        message_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        message_box.setDefaultButton(QMessageBox.StandardButton.Ok)
        updates = {}
        if can_update:
            for label, package in (
                ("Update from GitHub", github_package),
                ("Update from server", server_package),
            ):
                if package is not None:
                    button = message_box.addButton(self.t(label), QMessageBox.ButtonRole.ActionRole)
                    updates[button] = package
        for label in message_box.findChildren(QLabel):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message_box.exec()
        selected = updates.get(message_box.clickedButton())
        if selected is None or start_update is None:
            return
        try:
            start_update(selected)
        except (OSError, RuntimeError, ValueError) as error:
            AnimatedMessageBox.warning(self, self.t("Check for updates"), self.t("Could not start the update. {error}").format(error=error))
        else:
            self.reject()

    def _path_row(self, parent: QWidget, *, image: bool = False) -> tuple[QWidget, QLineEdit]:
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(row)
        edit.setClearButtonEnabled(image)
        select_button = QPushButton(self.t("Select"), row)

        def select_path() -> None:
            start = edit.text().strip()
            if image:
                patterns = " ".join(
                    f"*.{bytes(extension).decode('ascii')}" for extension in QImageReader.supportedImageFormats()
                )
                path = choose_path(
                    self, self.t("Select background image"), start,
                    directory=False, name_filter=f'{self.t("Image files")} ({patterns})',
                )
            else:
                path = choose_path(self, self.t("Select folder"), start)
            if path:
                edit.setText(os.path.normpath(path))

        select_button.clicked.connect(select_path)
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

        main_background_row, self.main_background_edit = self._path_row(tab, image=True)
        form.addRow(self.t("Main window background image"), main_background_row)
        log_background_row, self.log_background_edit = self._path_row(tab, image=True)
        form.addRow(self.t("Log window background image"), log_background_row)
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
        self.flac_compression_spin = StyledSpinBox(audio_group)
        self.flac_compression_spin.setRange(0, 8)
        audio_form.addRow(
            self.t("FLAC compression level"),
            self.flac_compression_spin,
        )
        self.ffmpeg_flac_compression_spin = StyledSpinBox(audio_group)
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
        self.fdkaac_bitrate_spin = StyledSpinBox(audio_group)
        self.fdkaac_bitrate_spin.setRange(0, 1024)
        self.fdkaac_bitrate_spin.setSpecialValueText(self.t("Auto"))
        self.fdkaac_bitrate_spin.setSuffix(" kbps")
        audio_form.addRow(
            self.t("FDK-AAC bitrate"),
            self.fdkaac_bitrate_spin,
        )
        self.opus_bitrate_spin = StyledSpinBox(audio_group)
        self.opus_bitrate_spin.setRange(0, 1024)
        self.opus_bitrate_spin.setSpecialValueText(self.t("Auto"))
        self.opus_bitrate_spin.setSuffix(" kbps")
        audio_form.addRow(
            self.t("Opus bitrate"),
            self.opus_bitrate_spin,
        )
        self.audio_duration_loss_threshold_spin = StyledDoubleSpinBox(audio_group)
        self.audio_duration_loss_threshold_spin.setRange(0.1, 60.0)
        self.audio_duration_loss_threshold_spin.setDecimals(1)
        self.audio_duration_loss_threshold_spin.setSingleStep(0.1)
        self.audio_duration_loss_threshold_spin.setSuffix(self.t(" seconds"))
        audio_form.addRow(
            self.t("Audio duration-loss fallback threshold"),
            self.audio_duration_loss_threshold_spin,
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
        self.remux_immersive_flac_checkbox = QCheckBox(
            self.t("Convert DTS:X and TrueHD Atmos to FLAC during Remux"),
            audio_group,
        )
        audio_form.addRow(self.remux_immersive_flac_checkbox)
        immersive_audio_hint = QLabel(
            self.t(
                "Converting DTS:X or TrueHD Atmos to FLAC permanently removes "
                "immersive object metadata and keeps only decoded channels."
            ),
            audio_group,
        )
        immersive_audio_hint.setWordWrap(True)
        audio_form.addRow(immersive_audio_hint)
        self.save_audio_gaps_checkbox = QCheckBox(
            self.t("Save .audio-gaps.json during Remux"),
            audio_group,
        )
        audio_form.addRow(self.save_audio_gaps_checkbox)
        audio_gaps_hint = QLabel(
            self.t(
                "Enable this if you plan to encode the Remux output later so Encode "
                "can reuse the audio gap information."
            ),
            audio_group,
        )
        audio_gaps_hint.setWordWrap(True)
        audio_form.addRow(audio_gaps_hint)
        self.allow_partial_missing_non_video_tracks_checkbox = QCheckBox(
            self.t("Allow partially missing non-video tracks"),
            audio_group,
        )
        self.allow_partial_missing_non_video_tracks_checkbox.setToolTip(
            self.t(
                "If a selected audio or subtitle track is missing from only some "
                "M2TS clips and tsMuxer cannot recover it, preserve those clips as "
                "timeline gaps. A completely missing selected track or any missing "
                "video track still stops the task."
            )
        )
        audio_form.addRow(self.allow_partial_missing_non_video_tracks_checkbox)
        layout.addWidget(audio_group)

        encode_group = QGroupBox(self.t("Default encode settings"), tab)
        encode_form = QFormLayout(encode_group)
        self.default_encoder_combo = StyledComboBox(encode_group)
        self.default_encoder_combo.addItem("x264", "x264")
        self.default_encoder_combo.addItem("x265", "x265")
        self.default_encoder_combo.addItem("SVT-AV1", "svtav1")
        encode_form.addRow(
            self.t("Default encoder"),
            self.default_encoder_combo,
        )
        self.default_bit_depth_combo = StyledComboBox(encode_group)
        encode_form.addRow(
            self.t("Default bit depth"),
            self.default_bit_depth_combo,
        )
        self.default_preset_combo = StyledComboBox(encode_group)
        encode_form.addRow(
            self.t("Default preset"),
            self.default_preset_combo,
        )

        preset_editor_row = QWidget(encode_group)
        preset_editor_layout = QHBoxLayout(preset_editor_row)
        preset_editor_layout.setContentsMargins(0, 0, 0, 0)
        preset_editor_layout.setSpacing(4)
        self.custom_preset_combo = StyledComboBox(preset_editor_row)
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
        self.default_lossless_audio_combo = StyledComboBox(encode_group)
        self.default_lossless_audio_combo.addItem("FLAC", "flac")
        self.default_lossless_audio_combo.addItem("AAC", "aac")
        self.default_lossless_audio_combo.addItem("Opus", "opus")
        encode_form.addRow(
            self.t("Default lossless audio target"),
            self.default_lossless_audio_combo,
        )
        self.default_subtitle_mode_combo = StyledComboBox(encode_group)
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
        self.default_frame_check_checkbox = QCheckBox(
            self.t("Check corrupted frames by default"),
            encode_group,
        )
        self.default_frame_check_checkbox.setToolTip(self.t(
            "After encoding, rerun the VPy and check the output frame by frame; "
            "this significantly increases processing time."
        ))
        encode_form.addRow(self.default_frame_check_checkbox)

        def create_frame_check_threshold_spin(tooltip: str) -> QDoubleSpinBox:
            spin = StyledDoubleSpinBox(encode_group)
            spin.setRange(0.0, 100.0)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setSuffix(" dB")
            spin.setKeyboardTracking(False)
            spin.setToolTip(self.t(tooltip))
            return spin

        self.frame_check_luma_psnr_threshold_spin = (
            create_frame_check_threshold_spin(
                "Frames below this luma PSNR threshold are suspicious; "
                "raising it increases sensitivity."
            )
        )
        encode_form.addRow(
            self.t("Frame check luma PSNR threshold"),
            self.frame_check_luma_psnr_threshold_spin,
        )
        self.frame_check_chroma_psnr_threshold_spin = (
            create_frame_check_threshold_spin(
                "Frames below this chroma PSNR threshold on U or V are suspicious; "
                "raising it increases sensitivity."
            )
        )
        encode_form.addRow(
            self.t("Frame check chroma PSNR threshold"),
            self.frame_check_chroma_psnr_threshold_spin,
        )

        def create_vpy_strength_spin(maximum: float, tooltip: str) -> QDoubleSpinBox:
            spin = StyledDoubleSpinBox(encode_group)
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
        supports_12_bit = encoder == "x265"
        if encoder == "svtav1":
            executable = resolve_encoder_executable_path(encoder, self._encoder_mode)
            supports_12_bit = "12" in probe_svt_av1_bit_depths(executable)
        depths = ("8", "10", "12") if supports_12_bit else ("8", "10")
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
            self.custom_preset_parameters_edit.setCursorPosition(0)
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
        self.external_tools_editor.setObjectName("externalToolsEditor")
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
        self.external_tools_detection_view.setObjectName("externalToolsDetectionView")
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
        encoder_path_names = {"X264_PATH", "X265_PATH", "SVT_AV1_PATH"}
        show_bundled_encoder_hint = (
            sys.platform == "win32"
            and bool(getattr(sys, "frozen", False))
            and any(name in encoder_path_names for name, _ in missing)
        )
        hints: list[str] = []
        if show_bundled_encoder_hint:
            hints.append(self.t(
                "Only the bundled source can be selected for x264/x265/svtav1 encoders."
            ))
        if not show_bundled_encoder_hint or any(name not in encoder_path_names for name, _ in missing):
            hints.append(self.t(
                "Run {script} from the repository root, then restart the "
                "application and check the paths again."
            ).format(script=setup_script))
        self.external_tools_detection_view.setFixedHeight(120)
        self.external_tools_detection_view.setStyleSheet("color: #d9534f;")
        self.external_tools_detection_view.setPlainText(
            self.t("Missing tools configured in settings.py:")
            + "\n"
            + missing_lines
            + "\n"
            + "\n".join(hints)
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
                AnimatedMessageBox.warning(self, self.t("Settings"), message)
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
            AnimatedMessageBox.warning(
                self,
                self.t("Settings"),
                self.t("Could not save external tool settings: {error}").format(
                    error=str(error)
                ),
            )
            return False
        self._settings_source_text = text
        return True

    def accept(self) -> None:
        if not window_is_fading_out(self) and self._apply_settings():
            super().accept()

    def _apply_settings(self) -> bool:
        validation_error = self._custom_preset_validation_error()
        if validation_error is not None:
            template, values = validation_error
            AnimatedMessageBox.warning(
                self,
                self.t("Settings"),
                self.t(template).format(**values),
            )
            return False
        for edit, saved_path in (
            (self.main_background_edit, self._config.ui.main_background_path),
            (self.log_background_edit, self._config.ui.log_background_path),
        ):
            path = edit.text().strip()
            if not path or path == saved_path:
                continue
            path = os.path.abspath(os.path.expanduser(path))
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            if reader.read().isNull():
                AnimatedMessageBox.warning(
                    self,
                    self.t("Settings"),
                    self.t("Could not read background image {path}. {error}").format(
                        path=path, error=reader.errorString(),
                    ),
                )
                edit.setFocus()
                return False
            edit.setText(path)
        selected = self.selected_config()
        if not self._save_external_tools_source():
            return False
        if self._apply_config is not None and not self._apply_config(selected):
            return False
        self._config = selected
        self.setWindowTitle(self.t("Settings"))
        return True

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
        for role, combo in self.font_family_combos.items():
            family = getattr(config.ui.fonts, role)
            if family and combo.findData(family) < 0:
                combo.addItem(family, family)
            self._set_combo_data(combo, family)
        self.opacity_spin.setValue(config.ui.opacity)
        self.close_to_tray_checkbox.setChecked(config.ui.close_to_tray)
        self.startup_update_checkbox.setChecked(config.ui.check_updates_on_startup)
        self.save_log_checkbox.setChecked(config.ui.save_log_to_file)
        self.log_line_limit_spin.setValue(config.ui.log_line_limit)
        self._set_combo_data(self.log_theme_combo, config.ui.log_theme)
        self.remux_output_edit.setText(config.paths.remux_output)
        self.encode_output_edit.setText(config.paths.encode_output)
        self.main_background_edit.setText(config.ui.main_background_path)
        self.main_background_opacity_spin.setValue(config.ui.main_background_opacity)
        self.main_background_blur_spin.setValue(config.ui.main_background_blur)
        self.log_background_edit.setText(config.ui.log_background_path)
        self.log_background_opacity_spin.setValue(config.ui.log_background_opacity)
        self.log_background_blur_spin.setValue(config.ui.log_background_blur)
        self.flac_compression_spin.setValue(config.audio.flac_compression_level)
        self.ffmpeg_flac_compression_spin.setValue(
            config.audio.ffmpeg_flac_compression_level
        )
        self.fdkaac_bitrate_spin.setValue(config.audio.fdkaac_bitrate_kbps)
        self.opus_bitrate_spin.setValue(config.audio.opus_bitrate_kbps)
        self.audio_duration_loss_threshold_spin.setValue(
            config.audio.duration_loss_fallback_threshold_seconds
        )
        self.remux_flac_default_checkbox.setChecked(
            config.remux.convert_lossless_audio_to_flac
        )
        self.remux_immersive_flac_checkbox.setChecked(
            config.remux.convert_immersive_audio_to_flac
        )
        self.allow_partial_missing_non_video_tracks_checkbox.setChecked(
            config.remux.allow_partial_missing_non_video_tracks
        )
        self.save_audio_gaps_checkbox.setChecked(config.remux.save_audio_gaps)
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
        self.default_frame_check_checkbox.setChecked(
            config.encode.check_corrupted_frames
        )
        self.frame_check_luma_psnr_threshold_spin.setValue(
            config.encode.frame_check_luma_psnr_threshold_db
        )
        self.frame_check_chroma_psnr_threshold_spin.setValue(
            config.encode.frame_check_chroma_psnr_threshold_db
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
                save_log_to_file=self.save_log_checkbox.isChecked(),
                log_line_limit=self.log_line_limit_spin.value(),
                log_theme=str(self.log_theme_combo.currentData()),
                close_to_tray=self.close_to_tray_checkbox.isChecked(),
                check_updates_on_startup=self.startup_update_checkbox.isChecked(),
                main_background_path=self.main_background_edit.text().strip(),
                main_background_opacity=self.main_background_opacity_spin.value(),
                main_background_blur=self.main_background_blur_spin.value(),
                log_background_path=self.log_background_edit.text().strip(),
                log_background_opacity=self.log_background_opacity_spin.value(),
                log_background_blur=self.log_background_blur_spin.value(),
                fonts=FontPreferences(**{
                    role: str(combo.currentData() or "") for role, combo in self.font_family_combos.items()
                }),
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
                duration_loss_fallback_threshold_seconds=(
                    self.audio_duration_loss_threshold_spin.value()
                ),
            ),
            remux=RemuxPreferences(
                convert_lossless_audio_to_flac=(
                    self.remux_flac_default_checkbox.isChecked()
                ),
                convert_immersive_audio_to_flac=(
                    self.remux_immersive_flac_checkbox.isChecked()
                ),
                allow_partial_missing_non_video_tracks=(
                    self.allow_partial_missing_non_video_tracks_checkbox.isChecked()
                ),
                save_audio_gaps=self.save_audio_gaps_checkbox.isChecked(),
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
                check_corrupted_frames=(
                    self.default_frame_check_checkbox.isChecked()
                ),
                frame_check_luma_psnr_threshold_db=(
                    self.frame_check_luma_psnr_threshold_spin.value()
                ),
                frame_check_chroma_psnr_threshold_db=(
                    self.frame_check_chroma_psnr_threshold_spin.value()
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
