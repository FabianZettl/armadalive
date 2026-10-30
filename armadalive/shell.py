"""Bring the ArmadaLive window to the front of the bottom Plasma session, whatever is on top of it."""
import glob, json, os, stat, subprocess, threading
from PySide6.QtCore import QObject, QTimer, Slot

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


def toggle_keyboard():
    """KWin's virtual keyboard of the bottom session, opened or closed whether or not the focused app asked for it."""
    bus = _bus or _find_bus()
    if bus:
        subprocess.run(["busctl", f"--address={bus}", "call", "org.kde.KWin", "/VirtualKeyboard", "org.kde.kwin.VirtualKeyboard",
                        "forceActivate"], capture_output=True, timeout=5)


class Shell(QObject):
    @Slot()
    def keyboard(self):
        threading.Thread(target=toggle_keyboard, daemon=True).start()

    @Slot()
    def activate(self):
        # the window has just been shown; give KWin a moment to list it
        QTimer.singleShot(250, lambda: threading.Thread(target=activate_window, daemon=True).start())
