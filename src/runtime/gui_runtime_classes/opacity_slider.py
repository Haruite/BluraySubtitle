"""Draw the opacity slider with the same geometry on each desktop."""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen
from PyQt6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class OpacitySlider(QSlider):
    def paintEvent(self, event) -> None:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self,
        )
        center = QRectF(handle).center()
        center.setY(self.height() / 2)
        track = QRectF(handle.width() / 2, center.y() - 1.5, self.width() - handle.width(), 3)
        fill = QRectF(track)
        if option.upsideDown:
            fill.setLeft(center.x())
        else:
            fill.setRight(center.x())
        palette = option.palette
        base = palette.color(QPalette.ColorRole.Base)
        neutral = QColor("#626870" if base.lightness() < 128 else "#a2a7ae")
        accent = palette.color(QPalette.ColorRole.Accent) if self.isEnabled() else neutral

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(neutral)
        painter.drawRoundedRect(track, 1.5, 1.5)
        painter.setBrush(accent)
        painter.drawRoundedRect(fill, 1.5, 1.5)
        painter.setPen(QPen(accent if self.hasFocus() or self.underMouse() else neutral, 1))
        painter.setBrush(base)
        painter.drawEllipse(center, 7, 7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawEllipse(center, 3, 3)
