"""The two one-time setup steps that need root (root helper, AYN button), run from the app after the user types their password."""
import os, subprocess, threading
from PySide6.QtCore import Property, QObject, Qt, Signal, Slot

from . import privileged
from .poller import Poller

SHARE = os.path.expanduser("~/.local/share/armadalive")
SUDO = os.environ.get("ARMADALIVE_SUDO", "sudo")  # tests point this at a stand-in
AYN_MAP = "/etc/inputplumber/capability_maps.d/ayn_type2.yaml"
SCRIPTS = {"helper": "install-helper.sh", "ayn": "ayn-button.sh"}


def helper_state():
    """ok, outdated (installed, but this version ships a different one) or missing."""
    if not privileged.available():
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
        self._status = dict(helper="missing", ayn=False)
        self._s = dict(self._status, busy="", message="")
        self.finished.connect(self._done, Qt.ConnectionType.QueuedConnection)
        self._poller = Poller(self, self._read, self._apply, 3000, idle_ms=15000)

    def set_active(self, active):
        self._poller.set_active(active)

    @staticmethod
    def _read():
        return dict(helper=helper_state(), ayn=ayn_done())

    def _apply(self, status):
        self._status = status
        self._publish()

    def _publish(self):
        state = dict(self._status, busy=self._busy, message=self._message)
        if state != self._s:
            self._s = state
            self.changed.emit()

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    @Slot()
    def refresh(self):
        self._poller.refresh()

    @Slot(str, str)
    def run(self, action, password):
        if self._busy or action not in SCRIPTS:
            return
        self._busy, self._message = action, ""
        self._publish()
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
        self._publish()
        if action == "helper":
            privileged.invalidate()
        self.refresh()
