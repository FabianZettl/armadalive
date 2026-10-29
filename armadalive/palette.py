"""Picks an accent colour from a picture, so the theme "Follow game" can take the colours of what the top screen shows."""
from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QColor, QImage
from PySide6.QtCore import Qt


def accent_of(image):
    """The colour that stands out most: pixels weighted by saturation x brightness, then lifted so text on it stays readable.
    Returns RRGGBB, or "" for a picture without colour."""
    small = image.scaled(24, 24, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB32)
    total = r = g = b = 0.0
    for y in range(24):
        for x in range(24):
            c = QColor(small.pixel(x, y))
            w = (c.hsvSaturationF() * c.valueF()) ** 2
            total, r, g, b = total + w, r + w * c.redF(), g + w * c.greenF(), b + w * c.blueF()
    if total < 0.5:
        return ""
    c = QColor.fromRgbF(r / total, g / total, b / total)
    c = QColor.fromHsvF(max(c.hueF(), 0.0), max(c.saturationF(), 0.55), max(c.valueF(), 0.8))
    return c.name()[1:]


class Palette(QObject):
    def __init__(self):
        super().__init__()
        self._cache = {}

    @Slot(str, result=str)
    def dominant(self, url):
        if not url:
            return ""
        if url not in self._cache:
            image = QImage(QUrl(url).toLocalFile())
            self._cache[url] = "" if image.isNull() else accent_of(image)
        return self._cache[url]
