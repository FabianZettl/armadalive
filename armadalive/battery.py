"""Low-battery warnings and an optional charge limit (the kernel's charge_control_end_threshold, written by the root helper)."""
import os, time
from PySide6.QtCore import QCoreApplication, QEvent, Property, QObject, QTimer, Signal, Slot
from . import persistence, privileged
from .commands import Commands

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


def validate_settings(saved):
    # The ordinary reader accepts object members and normalizes unusable values.
    # Backup must preserve those compatible values, including optional fields.
    return isinstance(saved, dict)


class Battery(persistence.OwnerWriter, QObject):
    changed = Signal()
    alert = Signal(str)

    def __init__(self):
        super().__init__()
        saved = persistence.read_json(CONFIG, validate_settings, {})
        self._s = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
        for key in ("warn", "limit"):
            if not isinstance(self._s[key], (int, float)):
                self._s[key] = DEFAULTS[key]
        self._done, self.error = set(), ""   # _s["refused"]: the battery's firmware rejected a limit (the Thor's does)
        self.supported = os.path.exists(LIMIT_FILE)
        self._limit_verified = False
        self._write_error = None
        self._commands = Commands(self, ("charge-limit",))
        self._commands.completed.connect(self._finish_limit)
        # The kernel forgets the limit on reboot. Probing and restoring it run off the owner.
        if self.supported and not self._s["refused"] and self._s["limit"] < 100:
            self._start_limit(self._s["limit"], startup=True)
        timer = QTimer(self)
        timer.timeout.connect(lambda: self.check(int(_read(BATTERY + "/capacity", "100")), _read(BATTERY + "/status")))
        timer.start(30000)

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(self._s, supported=self.supported and not self._s["refused"], error=self.error)

    def _save(self):
        persistence.write_json(CONFIG, self._s, follow_symlinks=True, require_writable=True, allow_nan=True)
        self._write_error = None
        self.changed.emit()

    def pauseWrites(self, *, restoring=False):
        super().pauseWrites(restoring=restoring)
        if self._write_error is not None:
            self._save()

    def writesPending(self):
        if self._write_error is not None:
            raise self._write_error
        return self._commands.pending("charge-limit")

    def flush(self, timeout=3.0):
        deadline = time.monotonic() + timeout
        while self.writesPending():
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for battery settings")
            # Deliver the command acknowledgements without letting unrelated
            # owner timers accept new edits after their writers have drained.
            QCoreApplication.sendPostedEvents(self._commands, QEvent.Type.MetaCall)
            time.sleep(0.001)

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
        if self._writes_paused:
            return
        self._s["warn"] = max(0, min(50, int(percent)))
        self._done.clear()
        self._save()

    @Slot(int)
    def setLimit(self, percent):
        if self._writes_paused:
            return
        self._start_limit(max(50, min(100, int(percent))))

    def _start_limit(self, percent, startup=False):
        def apply():
            if not privileged.available():
                raise RuntimeError("root helper missing")
            if error := privileged.run("charge-limit", percent):
                raise RuntimeError(error)
            if _read(LIMIT_FILE) not in (str(percent), ""):
                raise RuntimeError("the battery did not keep the limit")

        self._commands.submit("charge-limit", apply, (percent, startup))

    @Slot(str, object, object)
    def _finish_limit(self, channel, request, result):
        if not (result.current or result.succeeded):
            return
        percent, startup = result.target
        if result.current:
            self.error = result.error
        if result.succeeded:
            # The helper applied this limit even if a newer request is waiting.
            self._s["limit"] = percent
            if percent < 100:
                self._limit_verified = True
                self._s["refused"] = False
        elif percent < 100 and not self._limit_verified and self.error != "root helper missing":
            self._s["refused"], self.error = True, ""
            if startup:
                self._s["limit"] = 100
        try:
            self._save()
        except OSError as exc:
            self._write_error = exc
            if result.current:
                self.error = f"Could not save battery settings: {exc}"
            self.changed.emit()
