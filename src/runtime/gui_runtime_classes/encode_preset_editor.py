"""Settings controls for previewing and editing named video encoder presets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace

from PyQt6.QtCore import QSignalBlocker
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QWidget

from src.core.encode_presets import UserEncodePreset, UserGpuEncodePreset

from .custom_table_widget import StyledComboBox


class EncodePresetEditor(QWidget):
    def __init__(self, preset_combo: StyledComboBox, translate, parent: QWidget):
        super().__init__(parent)
        self.t = translate
        self.custom_presets: list[UserEncodePreset] = []
        self._scope: tuple[str, str | None] = ("", None)
        self._built_in: Mapping[str, str] = {}
        self._parameter_override: str | None = None
        self._preset_combo = preset_combo

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.preview = QLineEdit(self)
        self.preview.setReadOnly(True)
        form.addRow(self.t("Parameter preview"), self.preview)

        preset_row = QWidget(self)
        layout = QHBoxLayout(preset_row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._editor_combo = StyledComboBox(preset_row)
        add_button = QPushButton(self.t("Add"), preset_row)
        self._delete_button = QPushButton(self.t("Delete"), preset_row)
        for button in (add_button, self._delete_button):
            button.setAutoDefault(False)
        layout.addWidget(self._editor_combo, 1)
        layout.addWidget(add_button)
        layout.addWidget(self._delete_button)
        form.addRow(self.t("Custom encode presets"), preset_row)
        self._name_edit = QLineEdit(self)
        self._parameters_edit = QLineEdit(self)
        form.addRow(self.t("Preset name"), self._name_edit)
        form.addRow(self.t("Custom encode preset parameters"), self._parameters_edit)

        self._preset_combo.currentIndexChanged.connect(self._select_preset)
        self._editor_combo.currentIndexChanged.connect(self._load_editor)
        add_button.clicked.connect(self._add_preset)
        self._delete_button.clicked.connect(self._delete_preset)
        self._name_edit.textEdited.connect(self._rename_preset)
        self._parameters_edit.textEdited.connect(self._edit_parameters)

    def set_mode(
            self,
            encoder: str,
            built_in: Mapping[str, str],
            *,
            bit_depth: str | None = None,
            selected: str | None = None,
    ) -> None:
        name = self.selected_name if selected is None else selected
        self._scope = (encoder, bit_depth)
        self._built_in = built_in
        self._parameter_override = None
        self._refill(name)

    def set_parameter_override(self, value: str) -> None:
        parameters = self._preset(self._preset_combo.currentData())[1]
        self._parameter_override = value if value.strip() != parameters.strip() else None
        self._refresh_preview()

    def _preset(self, key: str | int | None) -> tuple[str, str]:
        if isinstance(key, int):
            preset = self.custom_presets[key]
            return preset.name, preset.parameters
        name = key or ""
        return name, self._built_in.get(name, "")

    @property
    def selected_name(self) -> str:
        return self._preset(self._preset_combo.currentData())[0]

    @property
    def parameters(self) -> str:
        if self._parameter_override is not None:
            return self._parameter_override
        return self._preset(self._preset_combo.currentData())[1]

    @property
    def parameter_override(self) -> str | None:
        parameters = self.parameters.strip()
        if parameters != self._preset(self._preset_combo.currentData())[1].strip():
            return parameters
        return None

    def _refill(self, name: str, *, editing: int | None = None) -> None:
        # Both combos share the same order. Custom entries use their list index
        # so that names can be edited before validation, including duplicates.
        rows = [(self.t(name), name) for name in self._built_in]
        rows.extend((preset.name, index) for index, preset in enumerate(self.custom_presets)
                    if preset.scope == self._scope)
        with QSignalBlocker(self._preset_combo), QSignalBlocker(self._editor_combo):
            for combo in (self._preset_combo, self._editor_combo):
                combo.clear()
                for caption, key in rows:
                    combo.addItem(caption, key)
                combo.setProperty("encodePresetBuiltinCount", len(self._built_in))
            index = next((row for row, (_, key) in enumerate(rows) if self._preset(key)[0] == name), -1)
            if index < 0:
                index = max(0, self._preset_combo.findData("Balanced"))
            self._preset_combo.setCurrentIndex(index)
            self._editor_combo.setCurrentIndex(index if editing is None else self._editor_combo.findData(editing))
        self._refresh_preview()
        self._load_editor()

    def _refresh_preview(self) -> None:
        self.preview.setText(self.parameters)
        self.preview.setCursorPosition(0)

    def _select_preset(self, index: int) -> None:
        self._parameter_override = None
        self._refresh_preview()
        self._editor_combo.setCurrentIndex(index)

    def _load_editor(self) -> None:
        key = self._editor_combo.currentData()
        name, parameters = self._preset(key)
        editable = isinstance(key, int)
        self._name_edit.setText(name if editable else self.t(name))
        self._parameters_edit.setText(parameters)
        self._parameters_edit.setCursorPosition(0)
        self._name_edit.setReadOnly(not editable)
        self._parameters_edit.setReadOnly(not editable)
        self._delete_button.setEnabled(editable)

    def _rename_preset(self, name: str) -> None:
        key = self._editor_combo.currentData()
        if isinstance(key, int):
            self.custom_presets[key] = replace(self.custom_presets[key], name=name)
            index = self._editor_combo.currentIndex()
            self._editor_combo.setItemText(index, name)
            self._preset_combo.setItemText(index, name)

    def _edit_parameters(self, parameters: str) -> None:
        key = self._editor_combo.currentData()
        if isinstance(key, int):
            self.custom_presets[key] = replace(self.custom_presets[key], parameters=parameters)
            if key == self._preset_combo.currentData():
                self._refresh_preview()

    def _add_preset(self) -> None:
        base = self.t("New Preset")
        used = {name.casefold() for name in self._built_in}
        used.update(preset.name.strip().casefold() for preset in self.custom_presets if preset.scope == self._scope)
        name = base
        suffix = 2
        while name.casefold() in used:
            name = f"{base} {suffix}"
            suffix += 1
        encoder, depth = self._scope
        parameters = self._parameters_edit.text().strip()
        preset = (UserEncodePreset(encoder, name, parameters) if depth is None
                  else UserGpuEncodePreset(encoder, name, parameters, depth))
        self.custom_presets.append(preset)
        self._refill(self.selected_name, editing=len(self.custom_presets) - 1)
        self._name_edit.setFocus()
        self._name_edit.selectAll()

    def _delete_preset(self) -> None:
        key = self._editor_combo.currentData()
        if not isinstance(key, int):
            return
        name = self.selected_name
        if key == self._preset_combo.currentData():
            name = "Balanced"
            self._parameter_override = None
        self.custom_presets.pop(key)
        self._refill(name)


def validate_custom_preset_names(
        presets: Iterable[UserEncodePreset],
        built_in_names: Callable[[tuple[str, str | None]], Iterable[str]],
        translate: Callable[[str], str],
) -> None:
    names_by_scope: dict[tuple[str, str | None], set[str]] = {}
    for preset in presets:
        name = preset.name.strip()
        if not name:
            raise ValueError(translate("Custom encode preset name cannot be empty."))
        normalized = name.casefold()
        if any(normalized == built_in.casefold() for built_in in built_in_names(preset.scope)):
            raise ValueError(translate("Custom encode preset name conflicts with a built-in preset: {name}").format(
                name=name,
            ))
        names = names_by_scope.setdefault(preset.scope, set())
        if normalized in names:
            raise ValueError(translate("Duplicate custom encode preset for {encoder}: {name}").format(
                encoder=preset.encoder, name=name,
            ))
        names.add(normalized)
