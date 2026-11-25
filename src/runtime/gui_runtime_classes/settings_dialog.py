"""Application settings dialog."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
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
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QDoubleSpinBox,
    QStyle,
    QTabWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

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
    encode_presets_for_encoder,
)
from src.core.i18n import translate_text
from src.core.tool_paths import (
    ENCODER_PATH_NAMES, MKVTOOLNIX_TOOLS, TOOL_DIRECTORY_NAMES, TOOL_PATH_NAMES,
    bundle_directory, resolve_tool_paths, tool_path_exists, using_tool_paths,
)
from src.core.version import (
    APP_VERSION,
    CommitInfo,
    current_commit,
    is_newer_release,
    parse_commit_record,
    release_version,
)
from src.runtime.desktop_integration import create_launch_shortcut, supports_desktop_entries
from src.runtime.encode_source import probe_svt_av1_bit_depths
from src.runtime.hardware_encode import GpuEncodeDevice, gpu_detection_supported, gpu_presets, hardware_encoder_parameters
from src.runtime.update_check import request_update_info, update_network_manager
from src.runtime.program_update import (
    DIRECT_UPDATE_REQUIREMENT,
    GITHUB_LATEST_RELEASE_API,
    SERVER_PACKAGE_LABEL,
    SERVER_PACKAGE_METADATA_URL,
    UpdatePackage,
    github_update_package,
    server_update_package,
    update_executable,
)

from .custom_table_widget import SelectionTableWidget, StyledComboBox
from .encode_devices import EncodeDeviceControls, GpuProbeThread
from .encode_preset_editor import validate_custom_preset_names
from .file_dialog import choose_path
from .spin_box import StyledDoubleSpinBox, StyledSpinBox
from .widget_animations import (
    AnimatedDialog, AnimatedMessageBox, supports_window_opacity, window_is_fading_out, window_opacity,
)


class SettingsDialog(AnimatedDialog):
    def __init__(
            self,
            config: AppConfig,
            translate: Callable[[str], str],
            parent: QWidget | None = None,
            *,
            config_path: Path,
            resolved_tools: Mapping[str, str],
            apply_config: Callable[[AppConfig, Mapping[str, str]], bool] | None = None,
            start_update: Callable[[UpdatePackage], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._apply_config = apply_config
        self._start_update = start_update
        self.t = translate
        self._config_path = config_path
        self._configured_tools = config.tools
        self._resolved_tools = resolved_tools
        self._current_commit = current_commit()
        self._update_network_manager = update_network_manager(self)
        self._update_replies: tuple[QNetworkReply, ...] | None = None
        self._gpu_diagnostic_thread: GpuProbeThread | None = None
        self._gpu_detection_result: tuple[tuple[str, str], tuple[GpuEncodeDevice, ...]] | None = None
        self.finished.connect(self._cancel_update_check)
        self.finished.connect(self._cancel_gpu_diagnostic)
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
        self._add_settings_buttons(layout)
        self._set_controls(config)

    def _add_settings_buttons(self, layout: QVBoxLayout) -> None:
        save = QPushButton(self.t("Save"), self)
        apply = QPushButton(self.t("Apply"), self)
        cancel = QPushButton(self.t("Cancel"), self)
        restore = QPushButton(self.t("Restore defaults"), self)
        save.clicked.connect(self.accept)
        apply.clicked.connect(self._apply_settings)
        cancel.clicked.connect(self.reject)
        restore.clicked.connect(lambda _=None: self._set_controls(default_app_config()))
        if sys.platform == "win32":
            row = QHBoxLayout()
            row.addWidget(restore)
            row.addStretch()
            for button in (save, apply, cancel):
                row.addWidget(button)
            save.setDefault(True)
            layout.addLayout(row)
        else:
            box = QDialogButtonBox(self)
            box.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)
            box.addButton(apply, QDialogButtonBox.ButtonRole.ApplyRole)
            box.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
            box.addButton(restore, QDialogButtonBox.ButtonRole.ResetRole)
            layout.addWidget(box)

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
        self.keep_sp_checkbox = QCheckBox(self.t("Keep SP (bonus features) during Remux"), tab)
        self.keep_sp_checkbox.setToolTip(self.t(
            "Turn this off to load discs with the SP table unchecked in Blu-ray Remux and Blu-ray Encode."
        ))
        form.addRow(self.keep_sp_checkbox)

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
            help_text = self.t("Window opacity requires macOS, Windows or a composited X11 session.")
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
        self.startup_update_checkbox.setVisible(bool(SERVER_PACKAGE_METADATA_URL))
        update_layout.addWidget(self.check_updates_button, alignment=Qt.AlignmentFlag.AlignLeft)
        form.addRow(self.t("Application updates"), update_row)

        if sys.platform in ("win32", "darwin") or supports_desktop_entries():
            shortcuts = QWidget(tab)
            shortcut_layout = QHBoxLayout(shortcuts)
            shortcut_layout.setContentsMargins(0, 0, 0, 0)
            desktop_button = QPushButton(self.t("Add desktop shortcut"), shortcuts)
            menu_button = QPushButton(self.t("Add to Applications" if sys.platform == "darwin" else "Add to application menu"), shortcuts)
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
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            message = self.t("Could not create the shortcut. {error}").format(error=error)
        else:
            template = "Available in Applications at {path}." if menu and sys.platform == "darwin" else "Shortcut created at {path}."
            message = self.t(template).format(path=path)
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
            combo = StyledComboBox(tab, compact_popup=True)
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
        replies = [request_update_info(manager, GITHUB_LATEST_RELEASE_API, b"application/vnd.github+json")]
        if SERVER_PACKAGE_METADATA_URL:
            replies.append(request_update_info(manager, SERVER_PACKAGE_METADATA_URL, b"text/plain"))
        self._update_replies = tuple(replies)
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
        release_reply, *package_replies = replies
        release_result = self._read_update_reply(
            release_reply,
            self._release_update_result,
            "GitHub did not return a valid release version.",
        )
        package_result = None
        if package_replies:
            package_result = self._read_update_reply(
                package_replies[0],
                self._server_package_update_result,
                "The server did not return valid package commit information.",
            )
        self._show_update_results(release_result, package_result)

    def _read_update_reply(
            self,
            reply: QNetworkReply,
            render: Callable[[str], tuple[str, UpdatePackage | None]],
            invalid_reply_message: str,
    ) -> tuple[str, UpdatePackage | None]:
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

    def _release_update_result(self, response: str) -> tuple[str, UpdatePackage | None]:
        payload = json.loads(response)
        if not isinstance(payload, dict):
            raise ValueError("GitHub release response must be an object")
        latest_version = release_version(payload)
        if not is_newer_release(latest_version):
            status = self.t("Latest Release version is {version}. Your version is up to date.")
            return escape(status.format(version=latest_version)), None
        status = escape(self.t("Version {version} is available.").format(version=latest_version))
        package = github_update_package(payload)
        if package is None and SERVER_PACKAGE_METADATA_URL:
            status += "<br>" + escape(self.t("The update source did not provide a verified package for this platform."))
        return status, package

    def _server_package_update_result(self, response: str) -> tuple[str, UpdatePackage | None]:
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
        package = server_update_package(response) if offer_package else None
        if offer_package and package is None:
            lines.append(escape(self.t("The update source did not provide a verified package for this platform.")))
        return "<br>".join(lines), package

    def _show_update_results(
            self,
            release_result: tuple[str, UpdatePackage | None],
            package_result: tuple[str, UpdatePackage | None] | None,
    ) -> None:
        release_text, github_package = release_result
        current_build = "<br>".join(escape(line) for line in self._current_build_summary().splitlines())
        sections = [
            (self.t("Current build"), current_build),
            (self.t("GitHub Release"), release_text),
        ]
        server_package = None
        if package_result is not None:
            server_text, server_package = package_result
            sections.append((self.t(SERVER_PACKAGE_LABEL), server_text))
        message = "".join(f"<p><b>{escape(title)}</b><br>{body}</p>" for title, body in sections)
        start_update = self._start_update
        can_update = start_update is not None and update_executable() is not None
        if github_package is not None or server_package is not None:
            reminder = (
                self.t("The program will close and reopen automatically after the update.") if can_update
                else self.t(DIRECT_UPDATE_REQUIREMENT)
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

        device_group = QGroupBox(self.t("Video encoding devices"), tab)
        layout.addWidget(device_group)
        self.encode_device_controls = EncodeDeviceControls(self.t, device_group, manage_presets=True)
        device_layout = QVBoxLayout(device_group)
        self.gpu_enable_checkbox = QCheckBox(self.t("Enable GPU encoding"), device_group)
        self.gpu_enable_checkbox.setVisible(gpu_detection_supported())
        self.gpu_enable_checkbox.toggled.connect(self._gpu_encoding_toggled)
        device_layout.addWidget(self.gpu_enable_checkbox)
        device_layout.addWidget(self.encode_device_controls)
        if gpu_detection_supported():
            controls = QHBoxLayout()
            self.gpu_detection_button = QPushButton(self.t("Detect GPUs"), device_group)
            self.gpu_detection_button.setAutoDefault(False)
            self.gpu_detection_button.clicked.connect(self._detect_gpus)
            controls.addWidget(self.gpu_detection_button)
            self.gpu_report_copy_button = QPushButton(self.t("Copy report"), device_group)
            self.gpu_report_copy_button.setAutoDefault(False)
            self.gpu_report_copy_button.hide()
            self.gpu_report_copy_button.clicked.connect(self._copy_gpu_report)
            controls.addWidget(self.gpu_report_copy_button)
            controls.addStretch()
            device_layout.addLayout(controls)
            self.gpu_detection_report = QPlainTextEdit(device_group)
            self.gpu_detection_report.setAccessibleName(self.t("GPU detection report"))
            self.gpu_detection_report.setReadOnly(True)
            self.gpu_detection_report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self.gpu_detection_report.setMinimumHeight(170)
            self.gpu_detection_report.hide()
            device_layout.addWidget(self.gpu_detection_report)
        cpu_box = self.encode_device_controls.cpu_box
        self.default_encoder_combo = cpu_box.codec
        self.default_encoder_combo.addItem("x264", "x264")
        self.default_encoder_combo.addItem("x265", "x265")
        self.default_encoder_combo.addItem("SVT-AV1", "svtav1")
        self.default_bit_depth_combo = cpu_box.bit_depth
        self._cpu_preset_editor = cpu_box.preset_editor
        encode_group = QGroupBox(self.t("Default encode settings"), tab)
        encode_form = QFormLayout(encode_group)
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
            executable = self._resolved_tools[ENCODER_PATH_NAMES[encoder]]
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
            self._cpu_preset_editor.set_mode(encoder, encode_presets_for_encoder(encoder))

    def _build_external_tools_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        description = QLabel(
            self.t("Relative paths are based on the directory containing {path}.").format(path=self._config_path)
            + "\n" + self.t("Leave a tool path empty for automatic discovery."),
            tab,
        )
        description.setWordWrap(True)
        description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(description)

        table = SelectionTableWidget(tab)
        table.setRowCount(len(TOOL_PATH_NAMES))
        table.setColumnCount(3)
        self.external_tools_table = table
        table.setHorizontalHeaderLabels([
            self.t("Tool name"), self.t("Configured path"), self.t("Resolved path"),
        ])
        table.verticalHeader().hide()
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._tool_path_edits: dict[str, QLineEdit] = {}
        for row, name in enumerate(TOOL_PATH_NAMES):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 2, QTableWidgetItem())
            cell = QWidget(table)
            cell.setObjectName("toolPathCell")
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(3, 2, 3, 2)
            cell_layout.setSpacing(3)
            edit = QLineEdit(cell)
            edit.setToolTip(self.t("Edit the path directly or use Browse."))
            edit.editingFinished.connect(lambda name=name: self._tool_path_edited(name))
            self._tool_path_edits[name] = edit
            button = QPushButton(self.t("Browse"), cell)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, name=name: self._browse_tool_path(name))
            cell_layout.addWidget(edit, 1)
            cell_layout.addWidget(button)
            table.setCellWidget(row, 1, cell)
        layout.addWidget(table, 1)

        self.external_tools_status_label = QLabel(tab)
        self.external_tools_status_label.setWordWrap(True)
        layout.addWidget(self.external_tools_status_label)
        check = QPushButton(self.t("Check tool paths"), tab)
        check.clicked.connect(lambda: self._refresh_external_tool_detection(force=True))
        layout.addWidget(check, alignment=Qt.AlignmentFlag.AlignLeft)
        return tab

    def _browse_tool_path(self, name: str) -> None:
        path = choose_path(
            self, self.t("Select tool path"), self._resolved_tools[name] or str(self._config_path.parent),
            directory=name in TOOL_DIRECTORY_NAMES,
        )
        if path:
            self._tool_path_edits[name].setText(path)
            self._tool_path_edited(name)

    def _refresh_external_tool_detection(self, *, force: bool = False) -> bool:
        table = self.external_tools_table
        configured = {name: edit.text() for name, edit in self._tool_path_edits.items()}
        try:
            if force or configured != self._configured_tools:
                self._resolved_tools = resolve_tool_paths(configured, self._config_path.parent)
                self._configured_tools = configured
        except ValueError as error:
            self.external_tools_status_label.setText(str(error))
            return False
        missing = []
        optional = {"MPV_CONFIG_PATH", "MPV_PATH", "LIBASS_PATH"}
        if sys.platform == "win32" or bundle_directory() is None:
            optional.add("PLUGIN_PATH")
        for row, name in enumerate(self._tool_path_edits):
            path = self._resolved_tools[name]
            item = table.item(row, 2)
            item.setText(path)
            item.setToolTip(path)
            checked_tools = MKVTOOLNIX_TOOLS if name == "MKVTOOLNIX_PATH" else (name,)
            if (name not in optional or configured[name]) and not all(
                    tool_path_exists(tool, self._resolved_tools[tool]) for tool in checked_tools
            ):
                missing.append(name)
        self.external_tools_status_label.setText(
            self.t("The following tools could not be found or used: {tools}").format(tools=", ".join(missing))
            if missing else self.t("All configured tool paths were found.")
        )
        return True

    def _tool_path_edited(self, name: str) -> None:
        if self._refresh_external_tool_detection() and name == "SVT_AV1_PATH":
            self._refresh_advanced_encode_options(refresh_presets=False)

    def _gpu_encoding_toggled(self, enabled: bool) -> None:
        self.encode_device_controls.set_gpu_enabled(enabled)
        if not self.encode_device_controls.gpu_enabled:
            thread = self._gpu_diagnostic_thread
            if thread is not None and not thread.diagnostics:
                thread.cancel.set()
        elif not self.encode_device_controls.devices:
            self._start_gpu_detection(diagnostics=False)

    def _detect_gpus(self) -> None:
        self._start_gpu_detection(diagnostics=True)

    def _start_gpu_detection(self, *, diagnostics: bool) -> None:
        if self._gpu_diagnostic_thread is not None:
            return
        report = self.gpu_detection_report
        if diagnostics:
            report.clear()
            report.show()
            self.gpu_report_copy_button.show()
        if not self._refresh_external_tool_detection(force=True):
            if diagnostics:
                report.setPlainText(self.external_tools_status_label.text())
            return
        self.gpu_detection_button.setEnabled(False)
        self.gpu_detection_button.setText(self.t("Detecting GPUs..."))
        # The parent window keeps the thread alive during cancellation if Settings closes.
        with using_tool_paths(self._resolved_tools):
            thread = GpuProbeThread(
                self._resolved_tools["FFMPEG_PATH"], self._resolved_tools["FFPROBE_PATH"],
                self.parentWidget() or QApplication.instance(), diagnostics=diagnostics,
            )
        self._gpu_diagnostic_thread = thread
        thread.detail.connect(report.appendPlainText)
        thread.found.connect(self._accept_gpu_detection)
        thread.finished.connect(self._finish_gpu_diagnostic)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _accept_gpu_detection(self, devices: tuple[GpuEncodeDevice, ...]) -> None:
        thread = self._gpu_diagnostic_thread
        if thread is not None and not thread.cancel.is_set():
            self._gpu_detection_result = ((thread.ffmpeg, thread.ffprobe), devices)
            self.encode_device_controls.set_devices(devices)

    def detected_gpu_devices(self, ffmpeg: str, ffprobe: str) -> tuple[GpuEncodeDevice, ...] | None:
        if self._gpu_detection_result and self._gpu_detection_result[0] == (ffmpeg, ffprobe):
            return self._gpu_detection_result[1]
        return None

    def _finish_gpu_diagnostic(self) -> None:
        thread = self._gpu_diagnostic_thread
        self._gpu_diagnostic_thread = None
        self.gpu_detection_button.setText(self.t("Detect GPUs"))
        self.gpu_detection_button.setEnabled(True)
        if (thread is not None and thread.cancel.is_set() and self.isVisible()
                and self.encode_device_controls.gpu_enabled and not self.encode_device_controls.devices):
            self._start_gpu_detection(diagnostics=False)

    def _cancel_gpu_diagnostic(self) -> None:
        if self._gpu_diagnostic_thread is not None:
            self._gpu_diagnostic_thread.cancel.set()

    def _copy_gpu_report(self) -> None:
        QApplication.clipboard().setText(self.gpu_detection_report.toPlainText())

    def accept(self) -> None:
        if not window_is_fading_out(self) and self._apply_settings():
            super().accept()

    def _apply_settings(self) -> bool:
        try:
            validate_custom_preset_names(
                self._cpu_preset_editor.custom_presets, lambda _: ENCODE_PRESET_NAMES, self.t,
            )
            parameters = {choice.parameters for choice in self.encode_device_controls.gpu_choices().values()}
            devices = {device.key: device for device in self.encode_device_controls.devices}
            for saved in self.encode_device_controls.gpu_preferences():
                device = devices.get(saved.device)
                validate_custom_preset_names(
                    saved.custom_presets,
                    lambda scope: gpu_presets(device, *scope, verified_only=False) if device is not None else (),
                    self.t,
                )
                parameters.update(preset.parameters.strip() for preset in saved.custom_presets)
            for value in parameters:
                hardware_encoder_parameters(value)
        except ValueError as error:
            AnimatedMessageBox.warning(self, self.t("Settings"), str(error))
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
        if not self._refresh_external_tool_detection():
            AnimatedMessageBox.warning(self, self.t("Settings"), self.external_tools_status_label.text())
            return False
        selected = self.selected_config()
        if self._apply_config is not None and not self._apply_config(selected, self._resolved_tools):
            return False
        self._config = selected
        self.setWindowTitle(self.t("Settings"))
        return True

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_controls(self, config: AppConfig) -> None:
        for name, edit in self._tool_path_edits.items():
            edit.setText(config.tools[name])
        self._refresh_external_tool_detection()
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
        self.keep_sp_checkbox.setChecked(config.remux.keep_sp_by_default)
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
        self._cpu_preset_editor.custom_presets = list(config.encode.custom_presets)
        self._cpu_preset_editor.set_mode(
            config.encode.encoder, encode_presets_for_encoder(config.encode.encoder),
            selected=config.encode.preset,
        )
        if config.encode.cpu_parameters is not None:
            self._cpu_preset_editor.set_parameter_override(config.encode.cpu_parameters)
        self.gpu_enable_checkbox.blockSignals(True)
        self.gpu_enable_checkbox.setChecked(config.encode.gpu_enabled)
        self.gpu_enable_checkbox.blockSignals(False)
        self.encode_device_controls.restore(config.encode)
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
        cpu_editor = self._cpu_preset_editor
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
            tools=self._configured_tools.copy(),
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
                keep_sp_by_default=self.keep_sp_checkbox.isChecked(),
            ),
            encode=EncodePreferences(
                encoder=str(self.default_encoder_combo.currentData()),
                bit_depth=str(self.default_bit_depth_combo.currentData()),
                preset=cpu_editor.selected_name.strip(),
                custom_presets=tuple(
                    replace(preset, name=preset.name.strip(), parameters=preset.parameters.strip())
                    for preset in cpu_editor.custom_presets
                ),
                cpu_enabled=self.encode_device_controls.cpu_preference(),
                cpu_parameters=cpu_editor.parameter_override,
                gpu_enabled=self.gpu_enable_checkbox.isChecked(),
                gpu_devices=tuple(
                    replace(
                        device,
                        preset=device.preset.strip(),
                        custom_presets=tuple(
                            replace(preset, name=preset.name.strip(), parameters=preset.parameters.strip())
                            for preset in device.custom_presets
                        ),
                    )
                    for device in self.encode_device_controls.gpu_preferences()
                ),
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
