"""Shared video device controls for Encode and its application defaults."""

from __future__ import annotations

import threading
from contextvars import copy_context
from PyQt6.QtCore import QObject, QSignalBlocker, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from src.core.app_config import EncodePreferences, GpuEncodePreferences
from src.core.encode_presets import UserGpuEncodePreset
from src.core.i18n import translate_text
from src.runtime import TaskCancelled
from src.runtime.hardware_encode import (
    GPU_CODECS, GpuEncodeDevice, VideoEncodeChoice,
    cpu_device_name, discover_gpu_encoders, gpu_detection_supported, gpu_device_label, gpu_presets,
)
from .custom_table_widget import StyledComboBox
from .encode_preset_editor import EncodePresetEditor


_PRESET_PARAMETERS_ROLE = Qt.ItemDataRole.UserRole + 1


class GpuProbeThread(QThread):
    found = pyqtSignal(object)
    detail = pyqtSignal(str)

    def __init__(self, ffmpeg: str, ffprobe: str, parent: QObject, *, diagnostics: bool = False):
        super().__init__(parent)
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.cancel = threading.Event()
        self.diagnostics = diagnostics
        self._context = copy_context()

    def run(self) -> None:
        try:
            devices = self._context.run(
                discover_gpu_encoders, self.ffmpeg, self.ffprobe, self.cancel,
                report=self.detail.emit if self.diagnostics else None,
            )
        except TaskCancelled:
            return
        except Exception as error:
            message = self._context.run(translate_text, 'Probe failed: {error}').format(error=error)
            if self.diagnostics:
                self.detail.emit(message)
            else:
                print(message, flush=True)
            devices = ()
        if not self.cancel.is_set():
            self.found.emit(devices)


class _DeviceBox(QGroupBox):
    def __init__(self, name: str, codec_label: str, translate, parent: QWidget, *, manage_presets: bool):
        super().__init__(parent)
        self.setObjectName('encodeDeviceBox')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(7)
        self.checkbox = QCheckBox(name, self)
        self.checkbox.setProperty('encodeDeviceName', True)
        layout.addWidget(self.checkbox, alignment=Qt.AlignmentFlag.AlignLeft)

        self.options = QWidget(self)
        layout.addWidget(self.options)
        options = QVBoxLayout(self.options)
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(7)

        selectors = QHBoxLayout()
        selectors.setSpacing(18)

        def add_selector(label: str) -> tuple[QWidget, StyledComboBox]:
            field = QWidget(self.options)
            pair = QHBoxLayout(field)
            pair.setContentsMargins(0, 0, 0, 0)
            pair.setSpacing(6)
            combo = StyledComboBox(field)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            combo.setMinimumWidth(84)
            caption = QLabel(translate(label), field)
            caption.setBuddy(combo)
            pair.addWidget(caption)
            pair.addWidget(combo)
            selectors.addWidget(field)
            return field, combo

        self.codec_field, self.codec = add_selector(codec_label)
        self.bit_depth_field, self.bit_depth = add_selector('Output bit depth:')
        _, self.preset = add_selector('Preset parameters')
        self.preset.setMaximumWidth(240)
        selectors.addStretch()
        options.addLayout(selectors)

        self.preset_editor: EncodePresetEditor | None = None
        self.parameters: QPlainTextEdit | None = None
        if manage_presets:
            self.preset_editor = EncodePresetEditor(self.preset, translate, self.options)
            options.addWidget(self.preset_editor)
            return

        parameters = QHBoxLayout()
        parameters.setSpacing(6)
        label = QLabel(translate('Encoder parameters'), self.options)
        self.parameters = QPlainTextEdit(self.options)
        self.parameters.setObjectName('encodeParametersEdit')
        self.parameters.setAccessibleName(label.text())
        tooltip = 'Click to edit the encoder parameters.'
        self.parameters.setProperty('toolTipSource', tooltip)
        self.parameters.setToolTip(translate(tooltip))
        self.parameters.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.parameters.setFixedHeight(60)
        label.setBuddy(self.parameters)
        parameters.addWidget(label)
        parameters.addWidget(self.parameters, 1)
        options.addLayout(parameters)

    def parameter_text(self) -> str:
        if self.preset_editor is not None:
            return self.preset_editor.parameters
        return self.parameters.toPlainText()

    def set_parameter_override(self, value: str) -> None:
        if self.preset_editor is not None:
            self.preset_editor.set_parameter_override(value)
        else:
            self.parameters.setPlainText(value)


class EncodeDeviceControls(QWidget):
    selection_changed = pyqtSignal()
    devices_changed = pyqtSignal(object)

    def __init__(self, translate, parent: QWidget, *, manage_presets: bool = False):
        super().__init__(parent)
        self.t = translate
        self._manage_presets = manage_presets
        self.devices: tuple[GpuEncodeDevice, ...] = ()
        self._saved: dict[str, GpuEncodePreferences] = {}
        self._controls: dict[str, _DeviceBox] = {}
        self._probe = None
        self._probe_paths = None
        self._cpu_enabled = True
        self._gpu_enabled = False
        self._diy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.cpu_box = _DeviceBox(cpu_device_name(), 'Encoder tool:', self.t, self, manage_presets=manage_presets)
        self.cpu_checkbox = self.cpu_box.checkbox
        self.cpu_checkbox.setChecked(True)
        layout.addWidget(self.cpu_box)
        self.gpu_controls = QWidget(self)
        self._gpu_layout = QVBoxLayout(self.gpu_controls)
        self._gpu_layout.setContentsMargins(0, 0, 0, 0)
        self._gpu_layout.setSpacing(8)
        layout.addWidget(self.gpu_controls)
        self.cpu_checkbox.toggled.connect(self._cpu_toggled)
        self._update_selection()

    def refresh(self, ffmpeg: str, ffprobe: str, *, detected: tuple[GpuEncodeDevice, ...] | None = None) -> None:
        if not self._gpu_enabled:
            return
        paths = (ffmpeg, ffprobe)
        if self._probe_paths == paths and detected is None:
            return
        self._probe_paths = paths
        self.cancel_probe()
        self._probe = None
        self.set_devices(detected or ())
        if detected is not None or not all(paths):
            return
        thread = GpuProbeThread(*paths, self)
        self._probe = thread

        def publish(devices):
            if self._probe is thread:
                self.set_devices(devices)

        def finished():
            if self._probe is thread:
                self._probe = None
            thread.deleteLater()

        thread.found.connect(publish)
        thread.finished.connect(finished)
        thread.start()

    def cancel_probe(self) -> None:
        if self._probe is not None:
            self._probe.cancel.set()

    def restore(self, preferences: EncodePreferences) -> None:
        self._cpu_enabled = preferences.cpu_enabled
        self._saved = {entry.device: entry for entry in preferences.gpu_devices}
        self._set_gpu_enabled(preferences.gpu_enabled)
        self._build_gpu_controls()

    def _set_gpu_enabled(self, enabled: bool) -> None:
        self._gpu_enabled = enabled and gpu_detection_supported()
        if not self._gpu_enabled and self._probe is not None:
            self.cancel_probe()
            self._probe = None
            self._probe_paths = None

    @property
    def gpu_enabled(self) -> bool:
        return self._gpu_enabled and not self._diy

    def set_gpu_enabled(self, enabled: bool) -> None:
        self._set_gpu_enabled(enabled)
        self._update_selection()

    def set_devices(self, devices: tuple[GpuEncodeDevice, ...]) -> None:
        if devices != self.devices:
            self._saved = {entry.device: entry for entry in self.gpu_preferences()}
            self.devices = devices
            self._build_gpu_controls()
            self.devices_changed.emit(devices)

    def _build_gpu_controls(self) -> None:
        while self._gpu_layout.count():
            widget = self._gpu_layout.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self._controls.clear()
        for device in self.devices:
            saved = self._saved.get(device.key, GpuEncodePreferences(device.key))
            controls = _DeviceBox(self.device_label(device), 'Video codec', self.t, self.gpu_controls,
                                  manage_presets=self._manage_presets)
            controls.checkbox.setChecked(saved.enabled)
            if controls.preset_editor is not None:
                controls.preset_editor.custom_presets = list(saved.custom_presets)
            self._controls[device.key] = controls
            for candidate in dict.fromkeys(codec for codec, _ in device.formats):
                controls.codec.addItem(GPU_CODECS[candidate], candidate)
            controls.codec.setCurrentIndex(max(0, controls.codec.findData(saved.codec)))
            self._gpu_layout.addWidget(controls)
            self._set_gpu_depths(device, saved.bit_depth, saved.preset)
            if (saved.parameters is not None and (saved.preset != 'Default' or saved.parameters.strip())
                    and saved.codec == controls.codec.currentData()
                    and saved.bit_depth == controls.bit_depth.currentData()):
                controls.set_parameter_override(saved.parameters)
            controls.checkbox.toggled.connect(self._gpu_toggled)
            controls.codec.currentIndexChanged.connect(
                lambda _, item=device: self._set_gpu_depths(item),
            )
            controls.bit_depth.currentIndexChanged.connect(
                lambda _, item=device: self._set_gpu_presets(item),
            )
            if controls.preset_editor is None:
                controls.preset.currentIndexChanged.connect(
                    lambda _, box=controls: self._apply_gpu_preset(box),
                )
        with QSignalBlocker(self.cpu_checkbox):
            self.cpu_checkbox.setChecked(self._cpu_enabled)
        self._update_selection()

    def device_label(self, device: GpuEncodeDevice) -> str:
        caption = gpu_device_label(device)
        matching = [candidate for candidate in self.devices
                    if (candidate.name, candidate.backend) == (device.name, device.backend)]
        return f'{caption} #{matching.index(device) + 1}' if len(matching) > 1 else caption

    def _set_gpu_depths(self, device: GpuEncodeDevice, depth: str = '', preset: str = '') -> None:
        controls = self._controls[device.key]
        codec = controls.codec.currentData()
        previous = depth or controls.bit_depth.currentData() or '10'
        with QSignalBlocker(controls.bit_depth):
            controls.bit_depth.clear()
            for candidate, value in device.formats:
                if candidate == codec:
                    controls.bit_depth.addItem(self.t(f'{value}-bit'), value)
            controls.bit_depth.setCurrentIndex(max(0, controls.bit_depth.findData(previous)))
        self._set_gpu_presets(device, preset)

    def _set_gpu_presets(self, device: GpuEncodeDevice, preset: str = '') -> None:
        controls = self._controls[device.key]
        codec, depth = controls.codec.currentData(), controls.bit_depth.currentData()
        built_in = gpu_presets(device, codec, depth)
        if controls.preset_editor is not None:
            controls.preset_editor.set_mode(codec, built_in, bit_depth=depth, selected=preset or None)
            return

        saved = self._saved.get(device.key, GpuEncodePreferences(device.key))
        reserved = {name.casefold() for name in built_in}
        custom = {
            item.name: item.parameters for item in saved.custom_presets
            if item.scope == (codec, depth) and item.name.casefold() not in reserved
        }
        previous = preset or controls.preset.currentData()
        if previous not in built_in and previous not in custom:
            previous = 'Balanced'
        with QSignalBlocker(controls.preset):
            controls.preset.clear()
            for name, parameters in (built_in | custom).items():
                controls.preset.addItem(self.t(name) if name in built_in else name, name)
                controls.preset.setItemData(controls.preset.count() - 1, parameters, _PRESET_PARAMETERS_ROLE)
            controls.preset.setProperty('encodePresetBuiltinCount', len(built_in))
            controls.preset.setCurrentIndex(max(0, controls.preset.findData(previous)))
        self._apply_gpu_preset(controls)

    @staticmethod
    def _apply_gpu_preset(controls: _DeviceBox) -> None:
        controls.parameters.setPlainText(controls.preset.currentData(_PRESET_PARAMETERS_ROLE) or '')

    def _cpu_toggled(self, enabled: bool) -> None:
        self._cpu_enabled = enabled
        self._update_selection()

    def _gpu_toggled(self) -> None:
        if not any(controls.checkbox.isChecked() for controls in self._controls.values()):
            self._cpu_enabled = True
        self._update_selection()

    def _update_selection(self) -> None:
        self.gpu_controls.setHidden(not self.gpu_enabled)
        any_gpu = False
        for controls in self._controls.values():
            enabled = self.gpu_enabled and controls.checkbox.isChecked()
            controls.options.setVisible(enabled)
            any_gpu = any_gpu or enabled
        self.cpu_checkbox.setEnabled(any_gpu)
        with QSignalBlocker(self.cpu_checkbox):
            self.cpu_checkbox.setChecked(self._cpu_enabled or not any_gpu)
        self.cpu_box.options.setVisible(self.cpu_checkbox.isChecked() or self.cpu_checkbox.isHidden())
        self.selection_changed.emit()

    def enabled_devices(self) -> list[tuple[str, str]]:
        devices = [(device.key, self.device_label(device)) for device in self.devices
                   if self.gpu_enabled and self._controls[device.key].checkbox.isChecked()]
        if self.cpu_checkbox.isChecked():
            devices.insert(0, ('cpu', self.cpu_checkbox.text()))
        return devices

    def gpu_choices(self) -> dict[str, VideoEncodeChoice]:
        choices = {}
        if not self.gpu_enabled:
            return choices
        for device in self.devices:
            controls = self._controls[device.key]
            if controls.checkbox.isChecked():
                choices[device.key] = VideoEncodeChoice(
                    controls.codec.currentData(), controls.bit_depth.currentData(),
                    controls.parameter_text().strip(), device,
                )
        return choices

    def gpu_preferences(self) -> tuple[GpuEncodePreferences, ...]:
        preferences = dict(self._saved)
        for device in self.devices:
            controls = self._controls[device.key]
            editor = controls.preset_editor
            if editor is None:
                preset = controls.preset.currentData()
                parameters = controls.parameter_text().strip()
                saved = preferences.get(device.key)
                custom_presets = saved.custom_presets if saved is not None else ()
            else:
                preset = editor.selected_name
                parameters = editor.parameter_override
                custom_presets = tuple(item for item in editor.custom_presets if isinstance(item, UserGpuEncodePreset))
            preferences[device.key] = GpuEncodePreferences(
                device.key, controls.checkbox.isChecked(), controls.codec.currentData(),
                controls.bit_depth.currentData(), preset, parameters, custom_presets,
            )
        return tuple(preferences.values())

    def cpu_preference(self) -> bool:
        return self._cpu_enabled

    def set_diy_mode(self, diy: bool) -> None:
        self._diy = diy
        self.cpu_checkbox.setHidden(diy)
        self.cpu_box.codec_field.setHidden(diy)
        self.cpu_box.bit_depth_field.setHidden(diy)
        self._update_selection()
