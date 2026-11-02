"""Run a slow read (a subprocess, a bus call) on a worker thread so the UI thread never waits for it."""
import threading
from PySide6.QtCore import QObject, QTimer, Signal


class Poller(QObject):
    """Every `ms`, work() runs on a worker thread and apply(result) on the UI thread. One run at a time: a slow
    read skips ticks instead of piling up. A work() that returns None changes nothing. now=False: the caller has
    already read once, synchronously, so the first run waits for the first tick."""
    _done = Signal(object)

    def __init__(self, parent, work, apply, ms, now=True):
        super().__init__(parent)
        self._work, self._busy = work, False
        self._done.connect(apply)   # emitted from the worker: queued onto the UI thread
        timer = QTimer(self)
        timer.timeout.connect(self.kick)
        timer.start(ms)
        if now:
            self.kick()

    def kick(self):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            result = self._work()
        except Exception:   # a failed read must not end the polling
            result = None
        self._busy = False
        if result is not None:
            try:
                self._done.emit(result)
            except RuntimeError:   # the owner was deleted while the read ran (shutdown)
                pass
