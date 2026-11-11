"""The execution button wraps progress labels within the available width."""

from math import ceil

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QPalette, QTextLayout, QTextOption
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QStyle, QStyleOptionButton, QStylePainter, QWidget


class ExecutionButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumHeight(42)

    def _label_layout(self, width: int) -> tuple[QTextLayout, float]:
        layout = QTextLayout(self.text().replace('\n', '\u2028'), self.font())
        text_option = QTextOption()
        text_option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(text_option)
        height = 0.0
        layout.beginLayout()
        while (line := layout.createLine()).isValid():
            line.setLineWidth(max(1, width))
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        return layout, height

    def heightForWidth(self, width: int) -> int:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.rect = QRect(0, 0, width, self.minimumHeight())
        contents = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        _, height = self._label_layout(contents.width())
        return max(self.minimumHeight(), ceil(height) + option.rect.height() - contents.height())

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        contents = self.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, self)
        option.text = ''
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        painter.setPen(option.palette.color(QPalette.ColorRole.ButtonText))
        layout, height = self._label_layout(contents.width())
        layout.draw(painter, QPointF(contents.left(), contents.top() + (contents.height() - height) / 2))
