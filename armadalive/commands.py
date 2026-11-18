"""Bounded device writes: one worker and one latest pending request per declared channel."""
from dataclasses import dataclass, replace
import logging
import subprocess
import weakref

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot

log = logging.getLogger(__name__)


def run(*args, **kwargs):
    return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=5, check=True, **kwargs)


def _failure_reason(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return f"timed out after {error.timeout} seconds"
    if isinstance(error, subprocess.CalledProcessError):
        if error.returncode < 0:
            return f"terminated by signal {-error.returncode}"
        return f"exit status {error.returncode}"
    reason = str(error)
    summary = " ".join(reason[:160].split()) or type(error).__name__
    return summary + ("…" if len(reason) > 160 else "")


@dataclass(frozen=True)
class Result:
    succeeded: bool
    target: object = None
    error: str = ""
    current: bool = True


class Commands(QObject):
    completed = Signal(str, object, object)  # channel, request id, Result; delivered on owner
    _done = Signal(str, object)

    def __init__(self, parent, channels):
        super().__init__(parent)
        self._channels = frozenset(channels)
        self._running, self._pending, self._acknowledged = {}, {}, {}
        self._request = 0
        self._done.connect(self._advance, Qt.ConnectionType.QueuedConnection)

    def target(self, channel, fallback):
        """Latest intent for relative toggles, distinct from a consumer's observed state."""
        request = self._pending.get(channel, self._running.get(channel))
        return request[2] if request else self._acknowledged.get(channel, fallback)

    def observed(self, channel):
        """A fresh observation supersedes the acknowledged intent once writes settle."""
        if channel not in self._running:
            self._acknowledged.pop(channel, None)

    def submit(self, channel, command, target=None):
        if channel not in self._channels:
            raise ValueError(f"Unknown command channel: {channel}")
        self._request += 1
        request = self._request, command, target
        if channel in self._running:
            self._pending[channel] = request
        else:
            self._start(channel, request)
        return self._request

    def cancel_pending(self, channel, request):
        """Discard a matching request waiting behind a dispatched command."""
        pending = self._pending.get(channel)
        if pending is not None and pending[0] == request:
            del self._pending[channel]
            return True
        return False

    def _start(self, channel, request):
        self._running[channel] = request
        _, command, target = request
        owner = weakref.ref(self)

        def execute():
            try:
                command()
                result = Result(True, target)
            except Exception as error:
                reason = _failure_reason(error)
                log.warning("Device command %s failed: %s", channel, reason)
                result = Result(False, target, reason)
            if (commands := owner()) is not None:
                try:
                    commands._done.emit(channel, result)
                except RuntimeError:
                    pass  # owner was deleted while its command was running

        QThreadPool.globalInstance().start(QRunnable.create(execute))

    @Slot(str, object)
    def _advance(self, channel, result):
        request, _, _ = self._running.pop(channel)
        pending = self._pending.pop(channel, None)
        result = replace(result, current=pending is None)
        if pending is not None:
            self._start(channel, pending)
        elif result.succeeded:
            self._acknowledged[channel] = result.target
        else:
            self._acknowledged.pop(channel, None)
        self.completed.emit(channel, request, result)
