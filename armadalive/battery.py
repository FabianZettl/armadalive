"""Low-battery warnings and an optional charge limit (the kernel's charge_control_end_threshold, written by the root helper)."""
import json, os, threading, weakref
from PySide6.QtCore import Property, QObject, QTimer, Qt, Signal, Slot
from . import privileged

BATTERY = "/sys/class/power_supply/battery"
LIMIT_FILE = BATTERY + "/charge_control_end_threshold"
CONFIG = os.path.expanduser("~/.config/armadalive/battery.json")
DEFAULTS = dict(warn=20, limit=100, refused=False)   # warn: percent, 0 = off


def _read(path, default=""):
    try:
        return open(path).read().strip()
    except OSError:
        return default


def levels(warn):
    """A warning at the chosen level and a last one at 10 %."""
    return [l for l in sorted({warn, 10}, reverse=True) if warn and l <= warn]


class Battery(QObject):
    changed = Signal()
    alert = Signal(str)
    _limit_done = Signal(int, bool, str)

    def __init__(self):
        super().__init__()
        try:
            with open(CONFIG) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self._s = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}} if isinstance(saved, dict) else dict(DEFAULTS)
        self._done, self.error = set(), ""   # _s["refused"]: the battery's firmware rejected a limit (the Thor's does)
        self.supported = os.path.exists(LIMIT_FILE)
        self._limit_busy, self._next_limit = False, None
        self._limit_done.connect(self._finish_limit, Qt.ConnectionType.QueuedConnection)
        # The kernel forgets the limit on reboot.
        if self.supported and not self._s["refused"] and self._s["limit"] < 100:
            self._start_limit(self._s["limit"], startup=True)
        timer = QTimer(self)
        timer.timeout.connect(self._check_battery)
        timer.start(30000)

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(self._s, supported=self.supported and not self._s["refused"], error=self.error)

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump(self._s, f)
        self.changed.emit()

    @Slot()
    def _check_battery(self):
        self.check(int(_read(BATTERY + "/capacity", "100")), _read(BATTERY + "/status"))

    def check(self, capacity, status):
        """Tells once per level; the levels re-arm when the device charges or the charge climbs well above the warning."""
        if status != "Discharging" or capacity > self._s["warn"] + 3:
            self._done.clear()
            return
        for level in levels(self._s["warn"]):
            if capacity <= level and level not in self._done:
                self._done.add(level)
                self._done.update(l for l in levels(self._s["warn"]) if l > level)
                self.alert.emit(f"{capacity}")
                return

    @Slot(int)
    def setWarn(self, percent):
        self._s["warn"] = max(0, min(50, int(percent)))
        self._done.clear()
        self._save()

    @Slot(int)
    def setLimit(self, percent):
        percent = max(50, min(100, int(percent)))
        if self._limit_busy:
            self._next_limit = percent
        else:
            self._start_limit(percent)

    def _start_limit(self, percent, startup=False):
        self._limit_busy = True
        owner = weakref.ref(self)

        def run():
            error = privileged.run("charge-limit", percent) if privileged.available() else "root helper missing"
            if not error and not startup and _read(LIMIT_FILE) not in (str(percent), ""):
                error = "the battery did not keep the limit"
            if (battery := owner()) is not None:
                try:
                    battery._limit_done.emit(percent, startup, error)
                except RuntimeError:
                    pass  # the application exited while the helper was running

        threading.Thread(target=run, daemon=True).start()

    @Slot(int, bool, str)
    def _finish_limit(self, percent, startup, error):
        try:
            if startup:
                if error and error != "root helper missing":
                    self._s["refused"], self._s["limit"] = True, 100
                    self._save()
            else:
                self.error = error
                if self.error and percent < 100 and self.error != "root helper missing":
                    self._s["refused"], self.error = True, ""
                elif not self.error:
                    self._s["limit"] = percent
                self._save()
        except OSError as exc:
            self.error = f"Could not save battery settings: {exc}"
            self.changed.emit()
        finally:
            self._limit_busy = False
            pending, self._next_limit = self._next_limit, None
            if pending is not None:
                self._start_limit(pending)
