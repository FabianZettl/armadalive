"""Bring the ArmadaLive window to the front of the bottom Plasma session, whatever is on top of it."""
import glob, json, os, stat, subprocess, threading
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

TITLE = "ArmadaLive"
_bus = None


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
    return None


def _call(addr, *args):
    return subprocess.run(["busctl", f"--address={addr}", "--json=short", "call", "org.kde.KWin", "/WindowsRunner",
                           "org.kde.krunner1", *args], capture_output=True, text=True, timeout=5)


def activate_window():
    """KWin's own windows runner activates the window, so focus-stealing prevention never gets a say."""
    global _bus
    for attempt in range(2):
        _bus = _bus or _find_bus()
        if not _bus:
            return False
        try:
            r = _call(_bus, "Match", "s", TITLE)
            if r.returncode == 0:
                for m in json.loads(r.stdout)["data"][0]:
                    if m[1] == TITLE:
                        return _call(_bus, "Run", "ss", m[0], "").returncode == 0
                return False  # window not mapped (yet)
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError):
            pass
        _bus = None  # the session may have restarted: look again once
    return False


def _kb(*args):
    bus = _bus or _find_bus()
    if not bus:
        return ""
    try:
        return subprocess.run(["busctl", f"--address={bus}", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


KB = ["org.kde.KWin", "/VirtualKeyboard", "org.kde.kwin.VirtualKeyboard"]


def keyboard_visible():
    return _kb("get-property", *KB, "visible") == "b true"


def keyboard_show():
    if not keyboard_visible():     # forceActivate toggles, so only when it is not up
        _kb("call", *KB, "forceActivate")


def keyboard_hide():
    _kb("set-property", *KB, "active", "b", "false")


class Shell(QObject):
    keyboardChanged = Signal()

    def __init__(self):
        super().__init__()
        self._pinned = False
        timer = QTimer(self)    # Plasma hides its keyboard when focus moves on; while pinned it is put back
        timer.timeout.connect(lambda: self._pinned and threading.Thread(target=keyboard_show, daemon=True).start())
        timer.start(800)

    @Property(bool, notify=keyboardChanged)
    def keyboardPinned(self):
        return self._pinned

    @Slot()
    def keyboard(self):
        """Shows the on-screen keyboard and keeps it up until this is called again."""
        self._pinned = not self._pinned
        self.keyboardChanged.emit()
        threading.Thread(target=keyboard_show if self._pinned else keyboard_hide, daemon=True).start()

    @Slot()
    def activate(self):
        # the window has just been shown; give KWin a moment to list it
        QTimer.singleShot(250, lambda: threading.Thread(target=activate_window, daemon=True).start())
