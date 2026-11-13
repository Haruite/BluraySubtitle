"""File and folder selection for the desktop and container."""

import os
import sys

from PyQt6.QtCore import QEvent, QSize, QStandardPaths, QStorageInfo, Qt, QUrl
from PyQt6.QtGui import QFileSystemModel, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QLabel, QLineEdit, QListView, QMessageBox, QSplitter, QToolButton, QWidget,
)

from src.core.i18n import translate_text

from .widget_animations import DialogFade, set_window_opacity, supports_window_opacity, window_opacity


class _LinuxFileDialog(DialogFade, QFileDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setOption(QFileDialog.Option.DontUseNativeDialog)
        if supports_window_opacity():
            set_window_opacity(self, window_opacity(parent.window()))
        self.resize(800, 520)

        places = self.sidebarUrls()
        for location in (
            QStandardPaths.StandardLocation.DesktopLocation,
            QStandardPaths.StandardLocation.DocumentsLocation,
            QStandardPaths.StandardLocation.DownloadLocation,
        ):
            path = QStandardPaths.writableLocation(location)
            if os.path.isdir(path):
                places.append(QUrl.fromLocalFile(path))
        for volume in sorted(QStorageInfo.mountedVolumes(), key=lambda mounted: mounted.rootPath().casefold()):
            path = volume.rootPath()
            if (
                volume.isReady() and path not in ("/", "/boot", "/boot/efi")
                and volume.fileSystemType() not in (b"tmpfs", b"devtmpfs", b"squashfs")
                and not any(part.startswith(".") for part in path.split("/"))
            ):
                places.append(QUrl.fromLocalFile(path))
        self.setSidebarUrls(list(dict.fromkeys(places)))
        sidebar = self.findChild(QListView, "sidebar")
        sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar.setMinimumWidth(190)
        self.findChild(QSplitter).setSizes([190, 600])

        icons = self.findChild(QListView, "listView")
        icons.setViewMode(QListView.ViewMode.IconMode)
        icons.setMovement(QListView.Movement.Static)
        icons.setDragEnabled(False)
        icons.setAcceptDrops(False)
        icons.setResizeMode(QListView.ResizeMode.Adjust)
        icons.setIconSize(QSize(48, 48))
        icons.setGridSize(QSize(120, 88))
        icons.setWordWrap(True)
        icons.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        icon_button = self.findChild(QToolButton, "listModeButton")
        icon_button.setIcon(QIcon())
        icon_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

        # Keep Qt's file model, history, and view actions behind the editable location field.
        location = self.findChild(QComboBox, "lookInCombo")
        self._address = QLineEdit(self)
        self._address.setAccessibleName(translate_text("Folder path"))
        self._address.setClearButtonEnabled(True)
        self.layout().replaceWidget(location, self._address)
        self.findChild(QLabel, "lookInLabel").setBuddy(self._address)
        location.hide()
        model = self.findChild(QFileSystemModel)
        model.rootPathChanged.connect(self._address.setText)
        self._address.setText(model.rootPath())
        self._address.installEventFilter(self)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self._focus_address)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        icon_button = self.findChild(QToolButton, "listModeButton")
        label = translate_text("Large icons")
        icon_button.setText(label)
        icon_button.setToolTip(label)
        icon_button.setAccessibleName(label)
        icon_button.setFixedWidth(icon_button.sizeHint().width())

    def _focus_address(self) -> None:
        self._address.setFocus()
        self._address.selectAll()

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is getattr(self, "_address", None)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self._open_address()
            return True
        return super().eventFilter(watched, event)

    def _open_address(self) -> None:
        text = self._address.text().strip()
        if not text:
            return
        path = os.path.normpath(os.path.join(self.directory().absolutePath(), os.path.expanduser(text)))
        if os.path.isdir(path):
            folder, filename = path, ""
        elif (is_file := os.path.isfile(path)) and self.fileMode() == QFileDialog.FileMode.ExistingFile:
            folder, filename = os.path.split(path)
        else:
            message = (
                translate_text("Select a folder: {path}") if is_file
                else translate_text("Path does not exist: {path}")
            )
            QMessageBox.warning(
                self, self.windowTitle(), message.format(path=path),
            )
            self._focus_address()
            return
        self.setDirectory(folder)
        self._address.setText(self.directory().absolutePath())
        name_edit = self.findChild(QLineEdit, "fileNameEdit")
        name_edit.setText(filename)
        if filename:
            name_edit.setFocus()


def choose_path(parent: QWidget, title: str, start: str = "", *, directory: bool = True, name_filter: str = "") -> str:
    start = os.path.expanduser(start)
    if not sys.platform.startswith("linux"):
        if directory:
            return QFileDialog.getExistingDirectory(parent, title, start)
        return QFileDialog.getOpenFileName(parent, title, start, name_filter)[0]

    dialog = _LinuxFileDialog(parent)
    dialog.setWindowTitle(title)
    if directory:
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly)
        for name in ("fileTypeLabel", "fileTypeCombo"):
            dialog.findChild(QWidget, name).hide()
    else:
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilter(name_filter or translate_text("All files (*)"))
        dialog.setLabelText(QFileDialog.DialogLabel.FileName, translate_text("File name:"))
        dialog.setLabelText(QFileDialog.DialogLabel.FileType, translate_text("File type:"))
    dialog.setLabelText(QFileDialog.DialogLabel.LookIn, translate_text("Location:"))
    action = translate_text("Select") if directory else translate_text("Open")
    dialog.setLabelText(QFileDialog.DialogLabel.Accept, action)
    dialog.setLabelText(QFileDialog.DialogLabel.Reject, translate_text("Cancel"))
    if start:
        start = os.path.abspath(start)
        if os.path.isdir(start):
            dialog.setDirectory(start)
        elif not directory:
            folder, name = os.path.split(start)
            if os.path.isdir(folder):
                dialog.setDirectory(folder)
                if os.path.isfile(start):
                    dialog.selectFile(name)
    try:
        if dialog.exec() == QDialog.DialogCode.Accepted and (paths := dialog.selectedFiles()):
            return paths[0]
        return ""
    finally:
        dialog.deleteLater()
