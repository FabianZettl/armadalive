"""Sees every touch, click and key press on the window, whatever item takes it, so the "dim after 10 s" timer starts again for all of them.

A PointHandler in QML only hears the touches that are delivered to its own item; a list or grid that takes a drag, or a button that takes a tap, can keep them
from it, and the screen then dimmed in the middle of use."""
import time
from PySide6.QtCore import QEvent, QObject, Signal, Slot

BEGIN = {QEvent.Type.TouchBegin, QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.TabletPress}
END = {QEvent.Type.TouchEnd, QEvent.Type.TouchCancel, QEvent.Type.MouseButtonRelease, QEvent.Type.KeyRelease, QEvent.Type.TabletRelease}
MOVE = {QEvent.Type.TouchUpdate, QEvent.Type.MouseMove, QEvent.Type.Wheel, QEvent.Type.TabletMove}
EVERY = 0.25    # seconds: moves are reported at most this often, a touch going down or up always


class Activity(QObject):
    seen = Signal()

    def __init__(self):
        super().__init__()
        self._last, self._window = 0.0, None

    @Slot(QObject)
    def watch(self, window):
        if window is not None and window is not self._window:
            self._window = window      # kept: the filter lives as long as this object
            window.installEventFilter(self)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in BEGIN or kind in END:
            self._last = time.monotonic()
            self.seen.emit()
        elif kind in MOVE and time.monotonic() - self._last >= EVERY:
            self._last = time.monotonic()
            self.seen.emit()
        return False
