"""Picks an accent colour from a picture, so the theme "Follow game" can take the colours of what the top screen shows."""
from collections import OrderedDict

from PySide6.QtCore import QObject, Property, QRunnable, QSize, QThreadPool, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QImage, QImageReader


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


def _read_accent(url):
    path = QUrl(url).toLocalFile()
    if not path:
        return ""
    reader = QImageReader(path)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > 96:
        reader.setScaledSize(size.scaled(QSize(96, 96), Qt.AspectRatioMode.KeepAspectRatio).expandedTo(QSize(1, 1)))
    image = reader.read()
    return "" if image.isNull() else accent_of(image)


class _AccentJob(QRunnable):
    def __init__(self, generation, url, complete):
        super().__init__()
        self.generation, self.url, self.complete = generation, url, complete

    def run(self):
        try:
            color = _read_accent(self.url)
        except Exception:
            color = ""
        self.complete.emit(self.generation, self.url, color)


class Palette(QObject):
    changed = Signal()
    _completed = Signal(int, str, str)

    def __init__(self):
        super().__init__()
        self._cache = OrderedDict()
        self._color = self._url = ""
        self._active = False
        self._generation = 0
        self._running = False
        self._completed.connect(self._finish, Qt.ConnectionType.QueuedConnection)

    @Property(str, notify=changed)
    def color(self):
        return self._color

    def _publish(self, color):
        if color != self._color:
            self._color = color
            self.changed.emit()

    @Slot(str, bool)
    def request(self, url, active):
        if (url, active) == (self._url, self._active):
            return
        self._url, self._active = url, active
        self._generation += 1
        self._update()

    def _update(self):
        if not self._active:
            return
        if not self._url:
            self._publish("")
        elif self._url in self._cache:
            self._cache.move_to_end(self._url)
            self._publish(self._cache[self._url])
        elif not self._running:
            self._running = True
            # While this job runs, request() only remembers the latest desired URL.
            QThreadPool.globalInstance().start(_AccentJob(self._generation, self._url, self._completed))

    @Slot(int, str, str)
    def _finish(self, generation, url, color):
        self._running = False
        if color:
            self._cache[url] = color
            self._cache.move_to_end(url)
            if len(self._cache) > 128:
                self._cache.popitem(last=False)
        if generation == self._generation:
            self._publish(color)
        else:
            self._update()
