"""Serialize bounded device commands, retaining the latest pending value per channel."""
import logging
import subprocess
import weakref

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot

log = logging.getLogger(__name__)


def run(*args, **kwargs):
    return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=5, check=True, **kwargs)


class Commands(QObject):
    settled = Signal(str)
    completed = Signal(str, object, bool)
    _done = Signal(str, bool)

    def __init__(self, parent):
        super().__init__(parent)
        self._running = {}
        self._pending = {}
        self._done.connect(self._advance, Qt.ConnectionType.QueuedConnection)

    def target(self, channel, fallback):
        return self._pending.get(channel, self._running.get(channel, (None, fallback)))[1]

    def submit(self, channel, command, target=None):
        if channel in self._running:
            self._pending[channel] = command, target
        else:
            self._start(channel, command, target)

    def _start(self, channel, command, target):
        self._running[channel] = command, target
        owner = weakref.ref(self)

        def execute():
            succeeded = False
            try:
                command()
                succeeded = True
            except Exception:
                log.debug("Device command failed", exc_info=True)
            finally:
                if (commands := owner()) is not None:
                    try:
                        commands._done.emit(channel, succeeded)
                    except RuntimeError:
                        pass

        QThreadPool.globalInstance().start(QRunnable.create(execute))

    @Slot(str, bool)
    def _advance(self, channel, succeeded):
        _, target = self._running.pop(channel)
        if channel in self._pending:
            self._start(channel, *self._pending.pop(channel))
        self.completed.emit(channel, target, succeeded)
        if channel not in self._running:
            self.settled.emit(channel)
