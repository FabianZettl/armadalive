"""The two one-time setup steps that need root (root helper, AYN button), run from the app after the user types their password."""
import os, subprocess, threading
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import privileged

SHARE = os.path.expanduser("~/.local/share/armadalive")
SUDO = os.environ.get("ARMADALIVE_SUDO", "sudo")  # tests point this at a stand-in
AYN_MAP = "/etc/inputplumber/capability_maps.d/ayn_type2.yaml"
SCRIPTS = {"helper": "install-helper.sh", "ayn": "ayn-button.sh"}


def helper_state():
    """ok, outdated (installed, but this version ships a different one) or missing."""
    if not privileged.available(refresh=True):
        return "missing"
    try:
        same = open(privileged.HELPER, "rb").read() == open(f"{SHARE}/scripts/armadalive-helper", "rb").read()
    except OSError:
        return "ok"
    return "ok" if same else "outdated"


def ayn_done():
    try:
        return "dbus: ui_quick2" in open(AYN_MAP).read()
    except OSError:
        return False


class Admin(QObject):
    changed = Signal()
    finished = Signal(str, str)   # action, message ("" on success)

    def __init__(self):
        super().__init__()
        self._busy, self._message = "", ""
        self._s = {}
        self.finished.connect(self._done)
        timer = QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(3000)  # the user may run the scripts in a terminal as well: keep looking
        self.refresh()

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    @Slot()
    def refresh(self):
        self._s = dict(helper=helper_state(), ayn=ayn_done(), busy=self._busy, message=self._message)
        self.changed.emit()

    @Slot(str, str)
    def run(self, action, password):
        if self._busy or action not in SCRIPTS:
            return
        self._busy, self._message = action, ""
        self.refresh()
        threading.Thread(target=self._run, args=(action, password), daemon=True).start()

    def _run(self, action, password):
        try:
            # the password goes to sudo on stdin only: never on a command line, never written anywhere
            r = subprocess.run([SUDO, "-S", "-p", "", f"{SHARE}/scripts/{SCRIPTS[action]}"], input=password + "\n",
                               capture_output=True, text=True, timeout=90)
            err = r.stderr.strip().splitlines()
            wrong = any("incorrect password" in l or "try again" in l.lower() for l in err)
            msg = "" if r.returncode == 0 else ("wrong password" if wrong else (err[-1] if err else f"failed ({r.returncode})"))
        except (OSError, subprocess.TimeoutExpired) as e:
            msg = str(e)
        self.finished.emit(action, msg)

    def _done(self, action, msg):
        self._busy, self._message = "", msg
        self.refresh()
