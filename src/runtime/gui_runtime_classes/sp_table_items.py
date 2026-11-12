"""Table items for SP selection and output naming."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidgetItem

from src.core.i18n import translate_text


class SpSelectionItem(QTableWidgetItem):
    def __init__(self, selected: bool, reason: str, *, disc_root: str):
        super().__init__()
        self.disc_root = os.path.normcase(os.path.normpath(disc_root)) if disc_root else ''
        self.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self.set_default(selected, reason)

    def set_default(self, selected: bool, reason: str) -> None:
        self.default_selected = selected and bool(self.flags() & Qt.ItemFlag.ItemIsEnabled)
        self.default_reason = reason
        if self.data(Qt.ItemDataRole.UserRole) != 'user':
            self.apply_selection(None)

    def apply_selection(self, selected: bool | None) -> None:
        self.setData(Qt.ItemDataRole.UserRole, 'auto' if selected is None else 'user')
        checked = self.default_selected if selected is None else selected
        checked = checked and bool(self.flags() & Qt.ItemFlag.ItemIsEnabled)
        self.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def data(self, role: int):
        if role == Qt.ItemDataRole.ToolTipRole:
            if not self.flags() & Qt.ItemFlag.ItemIsEnabled:
                status = translate_text('Unavailable for selection')
            elif self.default_selected:
                status = translate_text('Checked by default')
            else:
                status = translate_text('Unchecked by default')
            return f'{status}\n{translate_text(self.default_reason)}'
        return super().data(role)


class SpOutputNameItem(QTableWidgetItem):
    def setData(self, role: int, value: object) -> None:
        # Qt commits cell edits with EditRole. Generated names use setText/DisplayRole.
        if role == Qt.ItemDataRole.EditRole:
            super().setData(Qt.ItemDataRole.UserRole, value)
        super().setData(role, value)
