"""Power profiles, fan curves and RGB: read as the user, written through the root helper."""
import configparser, json, math, os, time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import device, persistence, privileged

FACTORY, OVERRIDE = "/usr/share/armada/power-profiles.conf", "/etc/armada/power-profiles.conf"
PROFILES = ("eco", "balanced", "performance")
GPU_FREQS = "/sys/class/devfreq/3d00000.gpu/available_frequencies"
GOVERNORS = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors"
UNDERCLOCK = ("none", "small", "medium", "large")
PRESETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")
PENDING = os.path.expanduser("~/.config/armadalive/tuning_pending.json")
CONFIRM_S, MAX_S = 15, 60     # seconds to confirm a change; the most a chain of changes may stay unconfirmed
# helper option -> the field read_power() reports it under
FIELDS = {"cpu_governor": "governor", "cpu_underclock": "underclock", "fan_curve": "fanCurve", "gpu_max_mhz": "gpuMax", "gpu_min_mhz": "gpuMin"}


def _words(path):
    try:
        return open(path).read().split()
    except OSError:
        return []


def _at_most(steps, target):
    ok = [s for s in steps if s <= target]
    return max(ok) if ok else min(steps)


def read_power():
    p = configparser.ConfigParser()
    p.optionxform = str
    p.read([f for f in (FACTORY, OVERRIDE) if os.path.exists(f)])
    steps = sorted(int(f) // 1000000 for f in _words(GPU_FREQS))
    stock = steps[-1] if steps else 0
    profiles = []
    for name in PROFILES:
        s = f"profile.{name}"
        if not p.has_section(s):
            continue
        # a profile gives the GPU limits either in MHz or as a ratio of the top step
        gpu = lambda key, ratio: int(p.get(s, key)) if p.has_option(s, key) else (_at_most(steps, int(stock * float(p.get(s, ratio)))) if steps else 0)
        under = p.get(s, "cpu_underclock", fallback="none").lower()
        profiles.append(dict(id=name, label=p.get(s, "label", fallback=name.title()), governor=p.get(s, "cpu_governor"),
                             underclock=under if under in UNDERCLOCK else "none", fanCurve=p.get(s, "fan_curve"),
                             gpuMax=gpu("gpu_max_mhz", "gpu_max"), gpuMin=gpu("gpu_min_mhz", "gpu_min")))
    curves = []
    for s in p.sections():
        if s.startswith("fan_curve."):
            pts = sorted([int(a), int(b)] for a, b in (x.split(":") for x in p.get(s, "curve").split(",")))
            curves.append(dict(id=s.split(".", 1)[1], label=p.get(s, "label", fallback=s.split(".", 1)[1].title()), points=pts))
    return dict(profiles=profiles, curves=curves, governors=_words(GOVERNORS), underclocks=list(UNDERCLOCK), gpuSteps=steps)


def resolve_presets(spec, dev, steps, governors, curves):
    """The presets a device can really do: GPU limits snap to a real step, governors and fan curves that do not exist are left out.
    A model's own entry in spec["models"] (keyed "ayn,thor" or "ayn,thor:pro") replaces a preset of the same id."""
    own = {**spec.get("models", {}).get(dev.get("id", ""), {}), **spec.get("models", {}).get(f"{dev.get('id', '')}:{dev.get('tier', '')}", {})}
    out = []
    for pre in spec.get("presets", []):
        pre = {**pre, **own.get(pre["id"], {})}
        items = []
        if pre.get("cpu_governor") in governors:
            items.append(f"cpu_governor={pre['cpu_governor']}")
        if pre.get("cpu_underclock") in UNDERCLOCK:
            items.append(f"cpu_underclock={pre['cpu_underclock']}")
        if "gpu_max" in pre and steps:
            items.append(f"gpu_max_mhz={_at_most(steps, int(steps[-1] * pre['gpu_max']))}")
        if pre.get("fan_curve") in {c["id"] for c in curves}:
            items.append(f"fan_curve={pre['fan_curve']}")
        if items:
            out.append(dict(id=pre["id"], label=pre["label"], hint=pre.get("hint", ""), items=items))
    return out


def read_rgb():
    try:
        return json.load(open("/etc/armada/rgb.json"))
    except (OSError, ValueError):
        return {}


def _read_state(spec, dev):
    try:
        power = read_power()
    except (configparser.Error, OSError, ValueError, KeyError):
        power = {}
    try:
        helper = privileged.available()
    except OSError:
        helper = False
    return dict(power, helper=helper, rgb=read_rgb(), device=dev,
                presets=resolve_presets(spec, dev, power.get("gpuSteps", []),
                                        power.get("governors", []), power.get("curves", [])))


def _journal(path):
    try:
        with open(path, encoding="utf-8") as file:
            entries = json.load(file)
    except FileNotFoundError:
        return {}
    if not isinstance(entries, list):
        raise ValueError("Invalid tuning recovery file")
    undo = {}
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 4:
            raise ValueError("Invalid tuning recovery entry")
        kind, name, key, value = entry
        if (not all(isinstance(item, str) for item in (kind, name, key))
                or not isinstance(value, (int, str))
                or not ((kind == "profile" and name in PROFILES and key in FIELDS)
                        or (kind == "curve" and name and not key))):
            raise ValueError("Invalid tuning recovery entry")
        undo[kind, name, key] = value
    return undo


def _write_journal(path, undo):
    persistence.write_json(path, [[*key, value] for key, value in undo.items()])


def _apply(path, undo, args):
    """Record each original value before entering the helper."""
    operation, name, *items = args
    try:
        power = read_power()
        if operation == "profile":
            previous = next((p for p in power.get("profiles", []) if p["id"] == name), {})
            values = [item.split("=", 1) for item in items]
            remembered = {(operation, name, key): previous.get(FIELDS[key])
                          for key, value in values if str(previous.get(FIELDS[key])) != value}
        else:
            old = next((c["points"] for c in power.get("curves", []) if c["id"] == name), None)
            value = ",".join(f"{t}:{p}" for t, p in sorted(old, reverse=True)) if old else None
            remembered = {} if value == items[0] else {("curve", name, ""): value}
        if any(value is None for value in remembered.values()):
            raise ValueError("Could not read the previous tuning setting")
        updated = {**remembered, **undo}
        if updated != undo:
            _write_journal(path, updated)
    except (configparser.Error, OSError, ValueError, KeyError) as exc:
        return undo, str(exc), False
    if not remembered:
        return updated, "", False
    try:
        return updated, privileged.run(*args), True
    except Exception as exc:
        # The helper may have changed state before reporting an error.
        return updated, str(exc), True


def _keep(path, undo):
    try:
        persistence.remove(path)
    except OSError as exc:
        error = str(exc) or "Could not remove the tuning recovery journal."
        # An unlink may have succeeded before the directory sync failed.
        if not os.path.lexists(path):
            try:
                _write_journal(path, undo)
            except (OSError, ValueError) as write_error:
                return (f"{error}\nCould not save the tuning recovery journal ({write_error}). "
                        "Retry restore before closing ArmadaLive.")
        return error
    return ""


def _restore(path, undo):
    """Keep the complete journal until every helper call succeeds."""
    by_profile, commands = {}, []
    for (kind, name, key), old in undo.items():
        if kind == "profile":
            by_profile.setdefault(name, []).append(f"{key}={old}")
        else:
            commands.append(("fan-curve", name, old))
    commands.extend(("profile", name, *items) for name, items in by_profile.items())
    errors = []
    for args in commands:
        try:
            err = privileged.run(*args)
        except Exception as exc:
            err = str(exc)
        if err:
            errors.append(err)
    if errors:
        return errors[0]
    persistence.remove(path)
    return ""


class Settings(QObject):
    changed = Signal()
    pendingChanged = Signal()
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self._data = {}
        self._dev = device.info()
        try:
            with open(PRESETS, encoding="utf-8") as file:
                self._spec = json.load(file)
        except (OSError, ValueError):
            self._spec = {}
        self._path = PENDING
        self._undo, self._since, self._deadline = {}, None, None
        self._journal_error = ""
        try:
            self._undo = _journal(self._path)
        except (OSError, ValueError) as exc:
            self._journal_error = str(exc)
        self._recovery = bool(self._undo)
        self._restore_requested = self._recovery
        self._queue = deque()
        self._refresh_requested = False
        self._future = None
        self._operation = ""
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tuning")
        self._results = QTimer(self)
        self._results.timeout.connect(self._poll_result)
        self._results.setInterval(15)
        self.refresh()
        timer = QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(5000)  # the helper may be installed while the app runs
        clock = QTimer(self)
        clock.timeout.connect(self._tick)
        clock.start(1000)

    @Property("QVariant", notify=changed)
    def data(self):
        return self._data

    @Property("QVariant", notify=pendingChanged)
    def pending(self):
        seconds = max(0, math.ceil(self._deadline - time.monotonic())) if self._deadline is not None else 0
        return dict(active=bool(self._undo), seconds=seconds, total=CONFIRM_S,
                    busy=(self._operation not in ("", "refresh") or bool(self._queue)
                          or self._restore_requested and bool(self._data.get("helper"))),
                    recovery=self._recovery)

    @Slot()
    def refresh(self):
        if self._operation != "refresh":
            self._refresh_requested = True
            self._dispatch()

    def _submit(self, name, fn, *args):
        self._operation = name
        self._future = self._executor.submit(fn, *args)
        self._results.start()
        self.pendingChanged.emit()

    def _dispatch(self):
        if self._future is not None:
            return
        if self._expired():
            self._request_recovery()
        if self._restore_requested and self._data.get("helper"):
            self._restore_requested = False
            self._submit("restore", _restore, self._path, dict(self._undo))
            return
        if self._queue:
            kind, args = self._queue.popleft()
            if kind == "apply":
                self._submit(kind, _apply, self._path, dict(self._undo), args)
            elif kind == "keep":
                self._submit(kind, _keep, self._path, dict(self._undo))
            else:
                self._submit(kind, privileged.run, *args)
        elif self._refresh_requested:
            self._refresh_requested = False
            self._submit("refresh", _read_state, self._spec, self._dev)

    @Slot()
    def _poll_result(self):
        if not self._future.done():
            return
        self._results.stop()
        operation, future = self._operation, self._future
        self._operation, self._future = "", None
        error = ""
        try:
            result = future.result()
        except Exception as exc:
            error = str(exc)
        else:
            if operation == "refresh":
                self._data = result
                self.changed.emit()
            elif operation == "apply":
                undo, error, entered = result
                new_chain = not self._undo and undo
                self._undo = undo
                now = time.monotonic()
                if new_chain:
                    self._since = now
                if entered and undo:
                    if error or self._recovery or self._expired():
                        self._request_recovery()
                    else:
                        self._deadline = min(now + CONFIRM_S, self._since + MAX_S)
            elif operation in ("restore", "keep"):
                error = result
                if not error:
                    self._undo, self._since, self._deadline = {}, None, None
                    self._recovery = False
            else:
                error = result
        if operation in ("restore", "keep") and error:
            self._recovery = True
            self._deadline = None
        if operation in ("apply", "direct", "restore"):
            self._refresh_requested = True
        if error or operation != "refresh":
            self.message.emit(error or "")
        self._dispatch()
        self.pendingChanged.emit()

    def _enqueue(self, kind, args=()):
        if len(self._queue) >= 16:
            self.message.emit("Too many tuning requests. Try again when the current change finishes.")
            return
        self._queue.append((kind, args))
        self._dispatch()
        self.pendingChanged.emit()

    def _tune(self, *args):
        self._tick()
        if self._journal_error:
            self.message.emit(self._journal_error)
        elif not self._recovery:
            self._enqueue("apply", args)

    @Slot(str, str, str)
    def setProfileOption(self, profile, key, value):
        if profile in PROFILES and key in FIELDS:
            self._tune("profile", profile, f"{key}={value}")

    @Slot(str, str)
    def applyPreset(self, profile, preset):
        pre = next((p for p in self._data.get("presets", []) if p["id"] == preset), None)
        if pre and profile in PROFILES:
            self._tune("profile", profile, *pre["items"])

    @Slot(str, str)
    def saveFanCurve(self, name, points):
        self._tune("fan-curve", name, points)

    @Slot()
    def confirm(self):
        if self._expired():
            self.revert()
        elif self._undo and not self._recovery and not self.pending["busy"]:
            # Accept Keep now even if an in-flight refresh delays journal removal.
            self._deadline = None
            self._enqueue("keep")

    def _request_recovery(self):
        self._deadline = None
        self._recovery = self._restore_requested = True
        self._queue = deque(entry for entry in self._queue if entry[0] == "direct")

    @Slot()
    def revert(self):
        if self._undo and self._operation not in ("restore", "keep"):
            self._request_recovery()
            self._refresh_requested = True
            self._dispatch()
            self.pendingChanged.emit()

    def _expired(self):
        return self._deadline is not None and time.monotonic() >= self._deadline

    def _tick(self):
        if self._deadline is not None and self._operation != "keep":
            if self._expired():
                self.revert()
            else:
                self.pendingChanged.emit()

    @Slot()
    def dropCaches(self):
        self._enqueue("direct", ("drop-caches",))

    @Slot(bool, str, int)
    def setRgb(self, enabled, color, brightness):
        rgb = self._data.get("rgb", {})
        self._enqueue("direct", ("rgb", "true" if enabled else "false", color, brightness, rgb.get("saturation", 100),
                                 "true" if rgb.get("linkBrightness") else "false", rgb.get("maxBrightness", 50)))
