"""Bring the ArmadaLive window to the front of the bottom Plasma session, whatever is on top of it."""
import glob, json, os, stat, subprocess, threading, time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

TITLE = "ArmadaLive"
_bus = None
_probe_after = 0.0
_bus_lock = threading.Lock()
_discovery_lock = threading.Lock()


def _find_bus():
    # the bottom session runs under dbus-run-session: a private bus socket in /tmp, named differently each boot
    for path in glob.glob("/tmp/dbus-*"):
        try:
            st = os.stat(path)
        except OSError:
            continue
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
            continue
        addr = f"unix:path={path}"
        try:
            names = subprocess.run(["busctl", f"--address={addr}", "list"], capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        if "kwin_wayland" in names:
            return addr
    # Desktop mode: there is one Plasma session, and its KWin is on the ordinary session bus
    session = f"unix:path={os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'}/bus"
    try:
        if "org.kde.KWin" in subprocess.run(["busctl", f"--address={session}", "list"], capture_output=True, text=True, timeout=3).stdout:
            return session
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _call(addr, *args):
    return subprocess.run(["busctl", f"--address={addr}", "--json=short", "call", "org.kde.KWin", "/WindowsRunner",
                           "org.kde.krunner1", *args], capture_output=True, text=True, timeout=5)


def _cached_bus():
    with _bus_lock:
        return _bus


def session_bus():
    """Discover on a worker and share the result across session operations."""
    global _bus, _probe_after
    with _discovery_lock:
        with _bus_lock:
            if time.monotonic() < _probe_after:
                return _bus
        found = _find_bus()
        with _bus_lock:
            _bus = found
            _probe_after = time.monotonic() + (10 if found else 2)
            return _bus


def invalidate_bus(addr):
    global _bus, _probe_after
    with _bus_lock:
        if _bus == addr:
            _bus, _probe_after = None, 0.0


def activate_window():
    """KWin's own windows runner activates the window, so focus-stealing prevention never gets a say."""
    for _ in range(2):
        addr = session_bus()
        if not addr:
            return False
        try:
            r = _call(addr, "Match", "s", TITLE)
            if r.returncode == 0:
                for match in json.loads(r.stdout)["data"][0]:
                    if match[1] == TITLE:
                        if _call(addr, "Run", "ss", match[0], "").returncode == 0:
                            return True
                        break
                else:
                    return False  # window not mapped yet
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError):
            pass
        invalidate_bus(addr)
    return False


def _kb(*args):
    bus = session_bus()
    if not bus:
        return ""
    try:
        result = subprocess.run(["busctl", f"--address={bus}", *args], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    invalidate_bus(bus)
    return ""


KB = ["org.kde.KWin", "/VirtualKeyboard", "org.kde.kwin.VirtualKeyboard"]


def keyboard_visible():
    return _kb("get-property", *KB, "visible") == "b true"


def keyboard_show(is_current=lambda: True):
    # forceActivate toggles. Only use it after confirming the keyboard is hidden.
    if _kb("get-property", *KB, "visible") == "b false" and is_current():
        _kb("call", *KB, "forceActivate")


def keyboard_hide():
    _kb("set-property", *KB, "active", "b", "false")


class Shell(QObject):
    keyboardChanged = Signal()

    def __init__(self):
        super().__init__()
        self._pinned = False
        self._desired = False
        self._generation = 0
        self._lock = threading.Lock()
        self._busy = self._reconcile = self._raise_window = self._probe = False
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(800)
        self._activation = QTimer(self)
        self._activation.setSingleShot(True)
        self._activation.setInterval(250)
        self._activation.timeout.connect(lambda: self._queue(activate=True))
        QTimer.singleShot(0, self._tick)

    def _tick(self):
        with _bus_lock:
            probe = time.monotonic() >= _probe_after
        self._queue(reconcile=self._pinned, probe=probe)

    def _queue(self, reconcile=False, activate=False, probe=False):
        with self._lock:
            self._reconcile |= reconcile
            self._raise_window |= activate
            self._probe |= probe
            if self._busy or not (self._reconcile or self._raise_window or self._probe):
                return
            self._busy = True
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        while True:
            with self._lock:
                reconcile, activate, probe = self._reconcile, self._raise_window, self._probe
                self._reconcile = self._raise_window = self._probe = False
                if not (reconcile or activate or probe):
                    self._busy = False
                    return
                desired, generation = self._desired, self._generation

            if reconcile:
                if desired:
                    keyboard_show(lambda: self._current(generation))
                elif self._current(generation):
                    keyboard_hide()
            if activate:
                activate_window()
            elif probe:
                session_bus()

    def _current(self, generation):
        with self._lock:
            return self._generation == generation

    def _sync_keyboard(self, desired):
        with self._lock:
            if desired != self._desired:
                self._desired = desired
                self._generation += 1
        self._queue(reconcile=True)

    @Property(bool, notify=keyboardChanged)
    def keyboardPinned(self):
        return self._pinned

    @Slot()
    def keyboard(self):
        """Shows the on-screen keyboard and keeps it up until this is called again."""
        self._pinned = not self._pinned
        self._sync_keyboard(self._pinned)
        self.keyboardChanged.emit()

    @Slot(bool)
    def textFocus(self, on):
        """Reconcile text focus with the keyboard tile's pinned state."""
        if on or not self._pinned:
            self._sync_keyboard(on)

    @Slot(result=bool)
    def hasKwin(self):
        """Use the last worker discovery so controller input never waits for busctl."""
        return _cached_bus() is not None

    @Slot()
    def activate(self):
        # The window has just been shown; give KWin time to list it.
        self._activation.start()
