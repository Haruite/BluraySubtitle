"""Paint a centered, aspect-ratio-preserving image behind a window's controls."""

import os

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QImage, QImageReader, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from src.core.i18n import translate_text
from src.exports.utils import print_terminal_line


def background_panel_colors(dark: bool) -> tuple[str, str]:
    if dark:
        return "rgba(31,31,31,195)", "rgba(31,31,31,175)"
    return "rgba(255,255,255,185)", "rgba(255,255,255,150)"


def _blur_background(image: QImage, strength: int) -> QImage:
    from PIL import Image, ImageFilter

    # Blur a bounded source raster once, so resizing can keep using the Qt cover renderer.
    if max(image.width(), image.height()) > 1600:
        image = image.scaled(
            1600, 1600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
    pixel_format = QImage.Format.Format_RGBA8888_Premultiplied
    raster = image.convertToFormat(pixel_format)
    if raster.isNull():
        return image
    pixels = raster.constBits()
    pixels.setsize(raster.sizeInBytes())
    width, height = raster.width(), raster.height()
    # Premultiplication keeps RGB values in fully transparent pixels out of the blur.
    source = Image.frombuffer("RGBA", (width, height), memoryview(pixels), "raw", "RGBA", raster.bytesPerLine(), 1)
    radius = strength * min(width, height) / 720
    blurred = source.filter(ImageFilter.GaussianBlur(radius))
    result = QImage(blurred.tobytes(), width, height, width * 4, pixel_format).copy()
    result.setColorSpace(raster.colorSpace())
    return result


class WindowBackground:
    def __init__(self) -> None:
        self._path = ""
        self._source = QImage()
        self._image = QImage()
        self._pixmap = QPixmap()
        self._opacity = 0.0
        self._blur = 0

    @property
    def active(self) -> bool:
        return self._opacity > 0 and not self._image.isNull()

    def set_image(self, path: str, opacity: int, blur: int = 0) -> None:
        self._opacity = opacity / 100
        reload_source = path != self._path or (bool(path) and self._source.isNull())
        if not reload_source and blur == self._blur:
            return
        if reload_source:
            self._path = path
            self._source = QImage()
            self._image = QImage()
            if path:
                reader = QImageReader(os.path.expanduser(path))
                reader.setAutoTransform(True)
                self._source = reader.read()
                if self._source.isNull():
                    message = translate_text("Could not read background image {path}. {error}")
                    print_terminal_line(message.format(path=path, error=reader.errorString()), translate=False)
        self._blur = blur
        self._image = self._source
        if blur and not self._source.isNull():
            filtered = _blur_background(self._source, blur)
            if not filtered.isNull():
                self._image = filtered
        self._pixmap = QPixmap()

    def paint(self, window: QWidget) -> None:
        if not self.active or window.size().isEmpty():
            return
        ratio = window.devicePixelRatioF()
        size = window.size() * ratio
        # Reuse the scaled image when log output or scrolling causes a repaint.
        if self._pixmap.size() != size or self._pixmap.devicePixelRatio() != ratio:
            pixmap = QPixmap(size)
            if pixmap.isNull():
                return
            pixmap.fill(Qt.GlobalColor.transparent)
            scale = max(size.width() / self._image.width(), size.height() / self._image.height())
            width = size.width() / scale
            height = size.height() / scale
            source = QRectF(
                (self._image.width() - width) / 2, (self._image.height() - height) / 2,
                width, height,
            )
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(pixmap.rect()), self._image, source)
            painter.end()
            pixmap.setDevicePixelRatio(ratio)
            self._pixmap = pixmap

        painter = QPainter(window)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()
