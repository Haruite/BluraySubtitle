"""Resolution controls shared by the Encode panel and its row override dialog."""

from collections.abc import Callable
from contextvars import copy_context
from fractions import Fraction
from math import ceil, floor
from threading import Event

from PyQt6.QtCore import QSignalBlocker, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

from src.core.video_format import OutputResolution, RESOLUTION_PRESETS
from src.runtime import TaskCancelled
from src.runtime.encode_source import probe_video_geometry
from .custom_table_widget import StyledComboBox
from .spin_box import StyledSpinBox


_MAX_CUSTOM_DIMENSION = 32768


class _ResolutionModeCombo(StyledComboBox):
    def showPopup(self) -> None:
        view = self.view()
        view.ensurePolished()
        view.setMinimumWidth(
            view.sizeHintForColumn(self.modelColumn()) + 2 * view.frameWidth()
            + view.verticalScrollBar().sizeHint().width()
        )
        super().showPopup()


class _SourceGeometryProbe(QThread):
    def __init__(self, path: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.path = path
        self.geometry: tuple[int, int, Fraction] | None = None
        self.error = ''
        self._context = copy_context()
        self._cancel = Event()

    def requestInterruption(self) -> None:
        self._cancel.set()
        super().requestInterruption()

    def run(self) -> None:
        try:
            self.geometry = self._context.run(probe_video_geometry, self.path, cancel_event=self._cancel, timeout=30)
        except TaskCancelled:
            return
        except Exception as error:
            self.error = f'{self.path}\n{error}'


class OutputResolutionControls(QWidget):
    ready_changed = pyqtSignal(bool)

    def __init__(
            self, translate: Callable[[str], str], parent: QWidget, *,
            source_for_custom: Callable[[], str], allow_inherit: bool = False,
    ) -> None:
        super().__init__(parent)
        self._translate = translate
        self._source_for_custom = source_for_custom
        self._source_path = ''
        self._geometry: tuple[int, int, Fraction] | None = None
        self._probe: _SourceGeometryProbe | None = None
        self._probe_error = ''
        self._custom_issue = ''
        self._width_was_edited = True
        self._source_timer = QTimer(self, singleShot=True, interval=100)
        self._source_timer.timeout.connect(self._refresh_source)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(translate('Output resolution'), self)
        self.mode = _ResolutionModeCombo(self)
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        label.setBuddy(self.mode)
        self.mode.setAccessibleName(label.text())
        if allow_inherit:
            self.mode.addItem(translate('Follow batch setting'), 'inherit')
        self.mode.addItem(translate('Original resolution'), 'keep')
        for name, width, height in RESOLUTION_PRESETS:
            self.mode.addItem(f'{name} ({width} × {height})', name)
        self.mode.addItem(translate('Custom resolution'), 'custom')
        layout.addWidget(label)
        layout.addWidget(self.mode)

        self.custom = QWidget(self)
        dimensions = QHBoxLayout(self.custom)
        dimensions.setContentsMargins(0, 0, 0, 0)
        dimensions.setSpacing(4)
        self.width_spin = StyledSpinBox(self.custom)
        self.height_spin = StyledSpinBox(self.custom)
        for control, name, default in (
            (self.width_spin, 'Maximum width', 1920), (self.height_spin, 'Maximum height', 1080),
        ):
            control.setRange(2, _MAX_CUSTOM_DIMENSION)
            control.setValue(default)
            control.setKeyboardTracking(False)
            control.setAccessibleName(translate(name))
            control.setToolTip(translate(name))
        dimensions.addWidget(self.width_spin)
        dimensions.addWidget(QLabel('×', self.custom))
        dimensions.addWidget(self.height_spin)
        layout.addWidget(self.custom)

        self.upscale = QCheckBox(translate('Allow upscaling'), self)
        layout.addWidget(self.upscale)
        layout.addStretch(1)
        hint = 'Fit the picture within the selected width and height while keeping its aspect ratio.'
        self.mode.setProperty('toolTipSource', hint)
        self.mode.setToolTip(translate(hint))
        self.mode.currentIndexChanged.connect(self._on_mode_changed)
        self.width_spin.valueChanged.connect(lambda: self._dimension_edited(True))
        self.height_spin.valueChanged.connect(lambda: self._dimension_edited(False))
        self.upscale.toggled.connect(self._update_fields)
        self._update_fields()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.schedule_source_refresh()

    def hideEvent(self, event) -> None:
        self._source_timer.stop()
        self._cancel_probe()
        super().hideEvent(event)

    def schedule_source_refresh(self) -> None:
        if self.mode.currentData() == 'custom' and self.isVisible():
            self._source_timer.start()

    def _cancel_probe(self) -> None:
        if self._probe is not None:
            self._probe.requestInterruption()
            self._probe = None

    def _on_mode_changed(self) -> None:
        if self.mode.currentData() == 'custom':
            self._refresh_source()
        else:
            self._source_timer.stop()
            self._cancel_probe()
            self._probe_error = ''
        self._update_fields()

    def _refresh_source(self) -> None:
        if self.mode.currentData() != 'custom' or not self.isVisible():
            return
        path = self._source_for_custom()
        if path == self._source_path and (not path or self._geometry or self._probe or self._probe_error):
            return
        self._cancel_probe()
        self._source_path = path
        self._geometry = None
        self._probe_error = ''
        if path:
            # Keep the probe alive while a per-row dialog closes and cancels it.
            window = self.window()
            probe = _SourceGeometryProbe(path, window.parentWidget() or window)
            self._probe = probe
            probe.finished.connect(self._on_probe_finished)
            probe.finished.connect(probe.deleteLater)
            probe.start()
        self._update_fields()

    def _on_probe_finished(self) -> None:
        probe = self.sender()
        if probe is not self._probe:
            return
        self._probe = None
        self._geometry = probe.geometry
        self._probe_error = probe.error
        self._update_fields()

    def _dimension_edited(self, width: bool) -> None:
        self._width_was_edited = width
        self._update_fields()

    def _fit_custom_dimensions(self) -> bool:
        source_width, source_height, aspect_ratio = self._geometry
        width_limit, height_limit = (_MAX_CUSTOM_DIMENSION, _MAX_CUSTOM_DIMENSION) if self.upscale.isChecked() else (
            source_width, source_height,
        )
        if self._width_was_edited:
            primary, secondary = self.width_spin, self.height_spin
            primary_limit, secondary_limit = width_limit, height_limit
        else:
            primary, secondary = self.height_spin, self.width_spin
            primary_limit, secondary_limit = height_limit, width_limit
            aspect_ratio = 1 / aspect_ratio
        # Constrain the edited axis as well when its matching dimension would exceed the source.
        minimum = max(2, ceil(2 * aspect_ratio))
        maximum = min(primary_limit, floor(secondary_limit * aspect_ratio))
        if maximum < minimum:
            return False
        value = min(max(primary.value(), minimum), maximum)
        with QSignalBlocker(self.width_spin), QSignalBlocker(self.height_spin):
            self.width_spin.setMaximum(width_limit)
            self.height_spin.setMaximum(height_limit)
            primary.setValue(value)
            secondary.setValue(round(value / aspect_ratio))
        return True

    def _update_fields(self) -> None:
        mode = self.mode.currentData()
        self.custom.setVisible(mode == 'custom')
        self.upscale.setVisible(mode not in ('keep', 'inherit'))
        issue = ''
        if mode == 'custom':
            if self._geometry is not None:
                if not self._fit_custom_dimensions():
                    issue = self._translate('Output resolution is too small for the video aspect ratio and chroma sampling.')
            elif self._probe_error:
                issue = self._translate('Could not read source resolution: {error}').format(error=self._probe_error)
            elif self._source_path:
                issue = self._translate('Reading source resolution…')
            else:
                issue = self._translate('Load a video source to set a custom resolution.')
        self._custom_issue = issue
        self.custom.setEnabled(not issue)
        self.custom.setToolTip(issue)
        self.mode.setToolTip(issue or self._translate(self.mode.property('toolTipSource')))
        self.ready_changed.emit(not issue)

    def selected_resolution(self) -> OutputResolution | None:
        mode = self.mode.currentData()
        if mode == 'inherit':
            return None
        if mode == 'keep':
            return OutputResolution()
        if mode == 'custom':
            self._refresh_source()
            if self._custom_issue:
                raise ValueError(self._custom_issue)
            return OutputResolution(self.width_spin.value(), self.height_spin.value(), self.upscale.isChecked())
        width, height = next((width, height) for name, width, height in RESOLUTION_PRESETS if name == mode)
        return OutputResolution(width, height, self.upscale.isChecked())

    def set_resolution(self, resolution: OutputResolution | None) -> None:
        mode = 'inherit'
        if resolution is not None:
            if resolution.enabled:
                mode = next((
                    name for name, width, height in RESOLUTION_PRESETS
                    if (width, height) == (resolution.width, resolution.height)
                ), 'custom')
            else:
                mode = 'keep'
        with QSignalBlocker(self.width_spin), QSignalBlocker(self.height_spin), QSignalBlocker(self.upscale):
            self.upscale.setChecked(bool(resolution and resolution.allow_upscale))
            if resolution is not None and resolution.enabled:
                self.width_spin.setMaximum(max(resolution.width, self.width_spin.maximum()))
                self.height_spin.setMaximum(max(resolution.height, self.height_spin.maximum()))
                self.width_spin.setValue(resolution.width)
                self.height_spin.setValue(resolution.height)
                self._width_was_edited = True
        with QSignalBlocker(self.mode):
            self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        self._on_mode_changed()
