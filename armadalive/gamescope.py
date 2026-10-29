"""Gamescope on the main screen: FPS and focused app from its stats pipe, FPS limit and refresh rate from X properties."""
import os, subprocess, threading, time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

PIPE = f"/run/user/{os.getuid()}/gamescope-stats/stats.pipe"
ENV = dict(os.environ, DISPLAY=os.environ.get("ARMADALIVE_GAMESCOPE_DISPLAY", ":0"))


def _xprop(name):
    try:
        out = subprocess.run(["xprop", "-root", name], env=ENV, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return 0
    value = out.partition("=")[2].strip().split(",")[0]
    return int(value) if value.isdigit() else 0


class Gamescope(QObject):
    changed = Signal()
    focusChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self._fps, self._seen, self._focus, self._limit, self._refresh, self._n = 0.0, 0.0, "", 0, 0, 0
        threading.Thread(target=self._read, daemon=True).start()
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)
        self._tick()

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(fps=round(self._fps), focus=self._focus, limit=self._limit, refresh=self._refresh)

    def _read(self):
        # blocks until gamescope writes "fps=<n>" lines (the pipe is shared: every reader takes lines away from the others)
        while True:
            try:
                with open(PIPE) as pipe:
                    for line in pipe:
                        key, _, value = line.strip().partition("=")
                        if key == "fps":
                            try:
                                self._fps, self._seen = float(value), time.monotonic()
                            except ValueError:
                                pass
            except OSError:
                pass
            time.sleep(2)

    def _tick(self):
        if time.monotonic() - self._seen > 3:
            self._fps = 0.0  # a static screen produces no frames
        app = _xprop("GAMESCOPE_FOCUSED_APP")
        focus = str(app) if app else ""
        if focus != self._focus:
            self._focus = focus
            self.focusChanged.emit(focus)
        if self._n % 3 == 0:  # X properties change rarely
            self._limit, self._refresh = _xprop("GAMESCOPE_FPS_LIMIT"), _xprop("GAMESCOPE_DISPLAY_REFRESH_RATE_FEEDBACK")
        self._n += 1
        self.changed.emit()

    @Slot(int)
    def setFpsLimit(self, fps):
        subprocess.Popen(["xprop", "-root", "-f", "GAMESCOPE_FPS_LIMIT", "32c", "-set", "GAMESCOPE_FPS_LIMIT", str(int(fps))],
                         env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._limit = int(fps)
        self.changed.emit()
