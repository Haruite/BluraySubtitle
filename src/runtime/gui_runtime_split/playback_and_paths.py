"""Target module for playback/path helper methods of `BluraySubtitleGUI`."""
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl
from PyQt6.QtWidgets import QToolButton

from src.core import ENCODE_SP_LABELS
from src.core.tool_paths import tool_path
from src.exports.utils import print_terminal_line, run_command
from src.runtime.desktop_integration import supports_desktop_entries
from src.runtime.mpv_menu import mpv_language_options
from src.runtime.gui_runtime_classes.widget_animations import AnimatedInputDialog, AnimatedMessageBox
from .gui_base import BluraySubtitleGuiBase


class PlaybackPathsMixin(BluraySubtitleGuiBase):
    def _normalize_path_input(self, text: str) -> str:
        s = str(text or '').strip()
        if sys.platform == 'win32' and len(s) >= 2 and s[0] == s[-1] == '"':
            s = s[1:-1]
        if not s:
            return ''
        if s.startswith('file://'):
            s = QUrl(s).toLocalFile() or s
        return os.path.normpath(os.path.expanduser(s))

    def _split_m2ts_files(self, text: str) -> list[str]:
        if not text:
            return []
        parts = re.split(r'[,\n;]+', str(text))
        return [p.strip() for p in parts if p and p.strip()]

    def _get_stream_dir_for_bdmv_index(self, bdmv_index: int) -> str:
        root = self._get_disc_root_for_bdmv_index(bdmv_index)
        if not root:
            return ''
        return os.path.normpath(os.path.join(root, 'BDMV', 'STREAM'))

    def _get_playlist_dir_for_bdmv_index(self, bdmv_index: int) -> str:
        root = self._get_disc_root_for_bdmv_index(bdmv_index)
        if not root:
            return ''
        return os.path.normpath(os.path.join(root, 'BDMV', 'PLAYLIST'))

    def _get_disc_root_for_bdmv_index(self, bdmv_index: int) -> str:
        try:
            idx = int(bdmv_index)
        except Exception:
            idx = -1
        if not hasattr(self, 'table1') or not self.table1:
            return ''
        row_count = self.table1.rowCount()
        if row_count <= 0:
            return ''
        candidates: list[int] = []
        if idx > 0:
            candidates.extend([idx - 1, idx])
        else:
            candidates.append(0)
        candidates.extend([0, row_count - 1])
        seen: set[int] = set()
        for r in candidates:
            if r in seen:
                continue
            seen.add(r)
            if r < 0 or r >= row_count:
                continue
            try:
                root_item = self.table1.item(r, 0)
                root = root_item.text().strip() if root_item else ''
            except Exception:
                root = ''
            if not root:
                continue
            if root in (getattr(self, '_bdmv_inventory', None) or {}):
                return root
            bdmv_dir = os.path.join(root, 'BDMV')
            playlist_dir = os.path.join(bdmv_dir, 'PLAYLIST')
            stream_dir = os.path.join(bdmv_dir, 'STREAM')
            if os.path.isdir(playlist_dir) and os.path.isdir(stream_dir):
                return os.path.normpath(root)
            if os.path.isdir(bdmv_dir):
                return os.path.normpath(root)
        return ''

    def _select_video_path(self, bdmv_index: int, m2ts_files: list[str]) -> str:
        if not m2ts_files:
            return ''
        stream_dir = self._get_stream_dir_for_bdmv_index(bdmv_index)
        if not stream_dir:
            return ''

        if len(m2ts_files) == 1:
            return os.path.normpath(os.path.join(stream_dir, m2ts_files[0]))

        item, ok = AnimatedInputDialog.getItem(
            self,
            self.t("Select M2TS File"),
            self.t("Multiple M2TS files detected, choose one for preview:"),
            m2ts_files,
        )
        if not ok or not item:
            return ''
        return os.path.normpath(os.path.join(stream_dir, str(item)))

    def _play_mpls_path(self, mpls_path: str):
        btn = QToolButton()
        btn.setText(self.t('play'))
        btn.setProperty('action', 'play')
        self.on_button_play(mpls_path, btn)

    def _mpv_playback_executable(self, mime_type: str) -> str:
        executable = tool_path("MPV_PATH")
        if self._app_config.tools.get("MPV_PATH") or sys.platform == "win32":
            return executable
        if not executable or not supports_desktop_entries():
            return ""
        try:
            association = run_command(
                ["xdg-mime", "query", "default", mime_type], capture_output=True, check=True, timeout=2,
            ).stdout.strip()
            if not association and mime_type == "x-content/video-bluray":
                association = run_command(
                    ["xdg-mime", "query", "default", "video/mp4"], capture_output=True, check=True, timeout=2,
                ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
        return executable if b"mpv" in association else ""

    def _start_mpv_playback(self, executable: str, arguments: list[str], source_path: str) -> None:
        options = []
        menu_directory = None
        environment = QProcessEnvironment.systemEnvironment()
        ubuntu_bundle = getattr(sys, "frozen", False) and sys.platform.startswith("linux")
        if sys.platform.startswith("linux"):
            if ubuntu_bundle:
                if environment.contains("LD_LIBRARY_PATH_ORIG"):
                    environment.insert("LD_LIBRARY_PATH", environment.value("LD_LIBRARY_PATH_ORIG"))
                else:
                    environment.remove("LD_LIBRARY_PATH")
                for name in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH"):
                    environment.remove(name)
            if environment.value("DISPLAY"):
                try:
                    extensions = run_command(
                        ["xdpyinfo", "-queryExtensions"], capture_output=True, timeout=2,
                    )
                    dri3 = extensions.returncode == 0 and b"DRI3  (opcode:" in extensions.stdout
                except (OSError, subprocess.SubprocessError):
                    dri3 = any(os.access(node, os.R_OK | os.W_OK) for node in Path("/dev/dri").glob("renderD*"))
                if not dri3:
                    # Remote X servers may require a software-rendered EGL context.
                    options.extend((
                        "--vo=gpu-next,x11", "--gpu-api=opengl", "--gpu-context=x11egl", "--gpu-sw=yes",
                        "--icc-profile-auto=no", "--msg-level=vo/gpu-next=error,vo/gpu-next/opengl=error,ffmpeg/video=error",
                        "--profile=sw-fast", "--hwdec=no", "--framedrop=vo", "--osc=yes",
                    ))
                    if not environment.contains("LIBGL_ALWAYS_SOFTWARE"):
                        environment.insert("LIBGL_ALWAYS_SOFTWARE", "1")
        plugin_path = tool_path("PLUGIN_PATH")
        environment.insert("BLURAYSUB_PLUGIN_PATH", plugin_path)
        if plugin_path:
            environment.insert("VAPOURSYNTH_EXTRA_PLUGIN_PATH", plugin_path)
        config = tool_path("MPV_CONFIG_PATH")
        if config:
            if ubuntu_bundle:
                options.append(f"--config-dir={config}")
                environment.insert("BLURAYSUB_MPV_CONFIG_PATH", config)
            if ubuntu_bundle or self._app_config.tools.get("MPV_CONFIG_PATH"):
                environment.insert("MPV_HOME", config)
        if config and (supports_desktop_entries() or self._app_config.tools.get("MPV_CONFIG_PATH")):
            menu_options, menu_directory = mpv_language_options(self._language_code, Path(config))
            options.extend(menu_options)

        process = QProcess(self)
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        process.setStandardInputFile(QProcess.nullDevice())
        if menu_directory is not None:
            process.destroyed.connect(lambda *_: menu_directory.cleanup())

        def start_failed(error: QProcess.ProcessError) -> None:
            if error != QProcess.ProcessError.FailedToStart:
                return
            details = process.errorString()
            process.deleteLater()
            message = self.t("Could not start playback for {path}. {error}").format(path=source_path, error=details)
            print_terminal_line(message, translate=False)
            if not getattr(self, "_close_pending", False):
                AnimatedMessageBox.warning(self, self.t("Open File Failed"), message)

        def finished(code: int, status: QProcess.ExitStatus) -> None:
            if code or status != QProcess.ExitStatus.NormalExit:
                message = self.t("Playback for {path} failed with exit code {code}.").format(path=source_path, code=code)
                print_terminal_line(message, translate=False)
            process.deleteLater()

        process.errorOccurred.connect(start_failed)
        process.finished.connect(finished)
        process.start(executable, [*options, *arguments])

    def _play_m2ts_path(self, m2ts_path: str):
        if not m2ts_path or not os.path.exists(m2ts_path):
            AnimatedMessageBox.information(self, " ", self.t('M2TS file not found:\n{m2ts_path}').format(m2ts_path=m2ts_path))
            return
        if executable := self._mpv_playback_executable("video/mp2t"):
            self._start_mpv_playback(executable, [m2ts_path], m2ts_path)
        else:
            self.open_file_path(m2ts_path)

    def on_play_table2_disc_row(self, row_index: int, bdmv_col: int, m2ts_col: int):
        try:
            bdmv_item = self.table2.item(row_index, bdmv_col)
            try:
                bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
            except Exception:
                bdmv_index = 0
            if self._is_movie_mode() and bdmv_item:
                sm = str(bdmv_item.data(Qt.ItemDataRole.UserRole) or '').strip()
                if sm:
                    mpls_path = sm if sm.lower().endswith('.mpls') else sm + '.mpls'
                    mpls_path = os.path.normpath(mpls_path)
                    if os.path.isfile(mpls_path):
                        self._play_mpls_path(mpls_path)
                        return
                    AnimatedMessageBox.information(self, " ", self.t('MPLS file not found:\n{mpls_path}').format(mpls_path=mpls_path))
                    return
            m2ts_item = self.table2.item(row_index, m2ts_col)
            m2ts_files = self._split_m2ts_files(m2ts_item.text() if m2ts_item else '')
            video_path = self._select_video_path(bdmv_index, m2ts_files)
            if video_path:
                self._play_m2ts_path(video_path)
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def on_play_sp_table_row(self, row_index: int, bdmv_col: int, mpls_col: int, m2ts_col: int):
        try:
            bdmv_item = self.table3.item(row_index, bdmv_col)
            try:
                bdmv_index = int(bdmv_item.text().strip()) if bdmv_item and bdmv_item.text().strip() else 0
            except Exception:
                bdmv_index = 0
            mpls_item = self.table3.item(row_index, mpls_col)
            mpls_file = (mpls_item.text().strip() if mpls_item and mpls_item.text() else '')
            if mpls_file:
                playlist_dir = self._get_playlist_dir_for_bdmv_index(bdmv_index)
                if not playlist_dir:
                    AnimatedMessageBox.information(self, " ",
                                            self.t('Matching Blu-ray directory not found (bdmv_index={bdmv_index}), cannot locate MPLS file').format(bdmv_index=bdmv_index))
                    return
                mpls_path = os.path.normpath(os.path.join(playlist_dir, mpls_file))
                if os.path.exists(mpls_path):
                    self._play_mpls_path(mpls_path)
                    return
                AnimatedMessageBox.information(self, " ", self.t('MPLS file not found:\n{mpls_path}').format(mpls_path=mpls_path))
                return
            m2ts_item = self.table3.item(row_index, m2ts_col)
            m2ts_files = self._split_m2ts_files(m2ts_item.text() if m2ts_item else '')
            video_path = self._select_video_path(bdmv_index, m2ts_files)
            if video_path:
                self._play_m2ts_path(video_path)
        except Exception:
            self._show_error_dialog(traceback.format_exc())

    def _on_play_sp_table_row_clicked(self):
        try:
            sender = self.sender()
            if sender is None or not hasattr(self, 'table3') or not self.table3:
                return
            row_index = self.table3.indexAt(sender.pos()).row()
            if row_index < 0:
                return
            bdmv_col = ENCODE_SP_LABELS.index('bdmv_index')
            mpls_col = ENCODE_SP_LABELS.index('mpls_file')
            m2ts_col = ENCODE_SP_LABELS.index('m2ts_file')
            self.on_play_sp_table_row(row_index, bdmv_col, mpls_col, m2ts_col)
        except Exception:
            self._show_error_dialog(traceback.format_exc())
