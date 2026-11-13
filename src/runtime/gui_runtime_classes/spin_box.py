"""Numeric inputs with chevrons drawn on the field background."""

from typing import Any

from PyQt6.QtGui import QPaintEvent
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QDoubleSpinBox, QSpinBox, QStyle, QStyleOptionSpinBox, QStylePainter, QWidget,
)

from .custom_table_widget import draw_vertical_chevron


def _paint_spin_box(spin_box: QAbstractSpinBox) -> None:
    option = QStyleOptionSpinBox()
    spin_box.initStyleOption(option)
    control = QStyle.ComplexControl.CC_SpinBox
    painter = QStylePainter(spin_box)
    if option.buttonSymbols != QAbstractSpinBox.ButtonSymbols.UpDownArrows:
        painter.drawComplexControl(control, option)
        return

    up = QStyle.SubControl.SC_SpinBoxUp
    down = QStyle.SubControl.SC_SpinBoxDown
    style = spin_box.style()
    up_rect = style.subControlRect(control, option, up, spin_box)
    down_rect = style.subControlRect(control, option, down, spin_box)
    # Mask the step panels for painting while retaining Qt's native hit areas.
    option.subControls &= ~(up | down)
    painter.drawComplexControl(control, option)

    enabled = spin_box.isEnabled()
    steps = QAbstractSpinBox.StepEnabledFlag
    draw_vertical_chevron(
        painter, up_rect, option.palette,
        enabled=enabled and bool(option.stepEnabled & steps.StepUpEnabled), points_up=True,
    )
    draw_vertical_chevron(
        painter, down_rect, option.palette,
        enabled=enabled and bool(option.stepEnabled & steps.StepDownEnabled),
    )


class StyledSpinBox(QSpinBox):
    def __init__(self, parent: QWidget | None = None, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self.lineEdit().setTextMargins(4, 0, 4, 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        _paint_spin_box(self)


class StyledDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self.lineEdit().setTextMargins(4, 0, 4, 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        _paint_spin_box(self)
