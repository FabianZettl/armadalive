"""Low-battery warnings and an optional charge limit (the kernel's charge_control_end_threshold, written by the root helper)."""
import json, os
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import privileged

BATTERY = "/sys/class/power_supply/battery"
LIMIT_FILE = BATTERY + "/charge_control_end_threshold"
CONFIG = os.path.expanduser("~/.config/armadalive/battery.json")
DEFAULTS = dict(warn=20, limit=100)   # warn: percent, 0 = off


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

    def __init__(self):
        super().__init__()
        try:
            with open(CONFIG) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self._s = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}} if isinstance(saved, dict) else dict(DEFAULTS)
        self._done, self.error = set(), ""
        self.supported = os.path.exists(LIMIT_FILE)
        # the kernel forgets the limit on reboot, so it is applied again at start
        if self.supported and self._s["limit"] < 100 and privileged.available():
            self.error = privileged.run("charge-limit", self._s["limit"])
        timer = QTimer(self)
        timer.timeout.connect(lambda: self.check(int(_read(BATTERY + "/capacity", "100")), _read(BATTERY + "/status")))
        timer.start(30000)

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(self._s, supported=self.supported, error=self.error)

    def _save(self):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump(self._s, f)
        self.changed.emit()

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
        self.error = privileged.run("charge-limit", percent) if privileged.available() else "root helper missing"
        if not self.error:
            self._s["limit"] = percent
        self._save()
