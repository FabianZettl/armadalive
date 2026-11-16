"""Gamescope frame rate from its stats pipe and focus and display settings from X properties."""
import collections, math, os, select, subprocess, threading, time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from .poller import Poller

PIPE = f"/run/user/{os.getuid()}/gamescope-stats/stats.pipe"
ENV = dict(os.environ, DISPLAY=os.environ.get("ARMADALIVE_GAMESCOPE_DISPLAY", ":0"))


DISPLAY_PROPERTIES = ("GAMESCOPE_FPS_LIMIT", "GAMESCOPE_DISPLAY_REFRESH_RATE_FEEDBACK", "GAMESCOPE_DYNAMIC_REFRESH")


def _xprops(*names):
    try:
        reply = subprocess.run(["xprop", "-root", *names], env=ENV, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if reply.returncode:
        return None
    props = {}
    out = reply.stdout
    for line in out.splitlines():
        name, _, value = line.partition("=")
        value = value.strip().split(",")[0]
        if value.isdecimal():
            props[name.partition("(")[0].strip()] = int(value)
    return props


def _xprop(name):
    props = _xprops(name)
    return None if props is None else props.get(name, 0)


def _read_fps(samples, stopped):
    """Keep only the latest reading. Reopen the pipe if Gamescope restarts."""
    while not stopped.is_set():
        try:
            with os.fdopen(os.open(PIPE, os.O_RDONLY | os.O_NONBLOCK), "rb", buffering=0) as pipe:
                pending = b""
                while not stopped.is_set():
                    if not select.select([pipe], [], [], 1)[0]:
                        continue
                    chunk = pipe.read(4096)
                    if chunk is None:
                        continue
                    if not chunk:
                        samples.append((0.0, 0.0))
                        break
                    pending += chunk
                    *lines, pending = pending.split(b"\n")
                    if len(pending) >= 4096:
                        pending = b""
                    for line in lines:
                        key, _, value = line.strip().partition(b"=")
                        if key == b"fps":
                            try:
                                fps = float(value)
                                if math.isfinite(fps):
                                    samples.append((fps, time.monotonic()))
                            except ValueError:
                                pass
        except OSError:
            pass
        stopped.wait(1)


def _read_display():
    props = _xprops(*DISPLAY_PROPERTIES)
    return None if props is None else tuple(props.get(name, 0) for name in DISPLAY_PROPERTIES)


class Gamescope(QObject):
    changed = Signal()
    focusChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self._focus, self._limit, self._refresh, self._hz = "", 0, 0, 0
        self._samples = collections.deque([(0.0, 0.0)], maxlen=1)
        self._published_fps = 0
        stopped = threading.Event()
        self.destroyed.connect(stopped.set)
        threading.Thread(target=_read_fps, args=(self._samples, stopped), daemon=True).start()
        self._focus_poller = Poller(self, lambda: _xprop("GAMESCOPE_FOCUSED_APP"), self._apply_focus, 1000)
        self._display_poller = Poller(self, _read_display, self._apply_display, 3000, idle_ms=15000)
        # Pipe samples and their expiry remain visible even when X queries fail.
        timer = QTimer(self)
        timer.timeout.connect(self._publish_fps)
        timer.start(1000)

    def set_active(self, active):
        self._display_poller.set_active(active)

    @Property("QVariant", notify=changed)
    def state(self):
        fps, seen = self._samples[-1]
        # The pipe publishes about every five seconds.
        fps = round(fps) if time.monotonic() - seen <= 12 else 0
        return dict(fps=fps, focus=self._focus, limit=self._limit, refresh=self._refresh, hz=self._hz)

    @Slot()
    def _publish_fps(self):
        if self.state["fps"] != self._published_fps:
            self._publish()

    def _publish(self):
        self._published_fps = self.state["fps"]
        self.changed.emit()

    def _apply_focus(self, app):
        focus = str(app) if app else ""
        if focus != self._focus:
            self._focus = focus
            self.focusChanged.emit(focus)
            self._publish()

    def _apply_display(self, display):
        self._limit, self._refresh, self._hz = display
        self._publish()

    @Slot(int)
    def setFpsLimit(self, fps):
        # the screen mode: the display's refresh rate while a game runs (dynamic refresh) and the frame limit that goes with it
        for atom in ("GAMESCOPE_DYNAMIC_REFRESH", "GAMESCOPE_FPS_LIMIT"):
            subprocess.Popen(["xprop", "-root", "-f", atom, "32c", "-set", atom, str(int(fps))],
                             env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._limit = self._hz = int(fps)
        self.changed.emit()
