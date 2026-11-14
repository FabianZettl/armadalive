"""Collect slow snapshots on reusable workers and publish them on the owner's thread."""
import logging
import weakref
from types import MethodType

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Qt, Signal, Slot

log = logging.getLogger(__name__)


class Poller(QObject):
    """Allow one queued or running read per poller. Timer ticks during reads are dropped."""

    _done = Signal(int, object, object)
    _kick_requested = Signal()
    _refresh_requested = Signal()
    failed = Signal(object)

    def __init__(self, parent, work, apply, ms, now=True, idle_ms=None):
        super().__init__(parent)
        self._work = work
        self._apply = weakref.WeakMethod(apply) if isinstance(apply, MethodType) else lambda: apply
        self._busy = self._pending = False
        self._generation = 0
        self._active = True
        self._ms, self._idle_ms = ms, idle_ms
        queued = Qt.ConnectionType.QueuedConnection
        self._done.connect(self._deliver, queued)
        self._kick_requested.connect(self.kick, queued)
        self._refresh_requested.connect(self.refresh, queued)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.kick)
        self._timer.start(ms)
        if now:
            self.kick()

    @Slot()
    def kick(self):
        if QThread.currentThread() != self.thread():
            self._kick_requested.emit()
            return
        if self._busy:
            return
        self._busy = True
        generation, work, ref = self._generation, self._work, weakref.ref(self)
        QThreadPool.globalInstance().start(QRunnable.create(lambda: Poller._run(work, ref, generation)))

    @Slot()
    def refresh(self):
        """Replace an in-flight snapshot with a new read, coalescing repeated refreshes."""
        if QThread.currentThread() != self.thread():
            self._refresh_requested.emit()
            return
        self._generation += 1
        self._pending = self._busy
        self.kick()

    def set_active(self, active):
        if self._idle_ms is None or self._active == active:
            return
        self._active = active
        self._timer.start(self._ms if active else self._idle_ms)
        if active:
            self.refresh()

    @staticmethod
    def _run(work, ref, generation):
        result = error = None
        try:
            result = work()
        except Exception as exc:
            error = exc
        if (poller := ref()) is not None:
            try:
                poller._done.emit(generation, result, error)
            except RuntimeError:
                pass  # the owner was deleted before the read completed

    @Slot(int, object, object)
    def _deliver(self, generation, result, error):
        try:
            if generation == self._generation:
                if error is not None:
                    log.debug("Polling failed", exc_info=(type(error), error, error.__traceback__))
                    self.failed.emit(error)
                elif result is not None and (apply := self._apply()) is not None:
                    apply(result)
        finally:
            self._busy = False
            if self._pending:
                self._pending = False
                self.kick()
