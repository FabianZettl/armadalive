"""Power profiles, fan curves and RGB: read as the user, written through the root helper."""
import configparser, json, os, time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import device, privileged

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


class Settings(QObject):
    changed = Signal()
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self._helper = privileged.available()
        self._data = {}
        self._dev = device.info()
        try:
            self._spec = json.load(open(PRESETS))
        except (OSError, ValueError):
            self._spec = {}
        # changes not yet confirmed: (kind, name, key) -> the value to go back to; kept on disk so a closed app cannot leave them behind
        self._undo, self._left, self._since, self._boot_revert = {}, 0, 0.0, False
        try:
            self._undo = {(k, n, key): v for k, n, key, v in json.load(open(PENDING))}
            self._boot_revert = bool(self._undo)
        except (OSError, ValueError, TypeError):
            pass
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

    @Slot()
    def refresh(self):
        self._helper = privileged.available()
        try:
            power = read_power()
        except (configparser.Error, OSError, ValueError, KeyError):
            power = {}
        self._data = dict(power, helper=self._helper, rgb=read_rgb(), device=self._dev,
                          presets=resolve_presets(self._spec, self._dev, power.get("gpuSteps", []), power.get("governors", []), power.get("curves", [])))
        self.changed.emit()

    def _do(self, *args):
        err = privileged.run(*args)
        self.message.emit(err)
        self.refresh()

    # --- changes that can make the device hot or unstable are taken back unless confirmed, like a new screen resolution
    @Property("QVariant", notify=changed)
    def pending(self):
        return dict(active=bool(self._undo) and self._left > 0, seconds=self._left, total=CONFIRM_S)

    def _previous(self, profile, key):
        prof = next((p for p in self._data.get("profiles", []) if p["id"] == profile), None)
        return None if prof is None else prof.get(FIELDS[key])

    def _arm(self, remembered):
        """remembered: [((kind, name, key), old value)]; the oldest value of each setting is the one to go back to."""
        now = time.monotonic()
        if not self._undo:
            self._since = now
        for k, v in remembered:
            self._undo.setdefault(k, v)
        self._left = max(1, min(CONFIRM_S, int(self._since + MAX_S - now)))
        os.makedirs(os.path.dirname(PENDING), exist_ok=True)
        with open(PENDING, "w") as f:
            json.dump([[*k, v] for k, v in self._undo.items()], f)
        self.changed.emit()

    def _apply_profile(self, profile, pairs):
        before = [((("profile", profile, k)), self._previous(profile, k)) for k, v in pairs]
        err = privileged.run("profile", profile, *[f"{k}={v}" for k, v in pairs])
        self.message.emit(err)
        if not err:
            self._arm([(k, old) for (k, old), (_, new) in zip(before, pairs) if old is not None and str(old) != str(new)])
        self.refresh()

    @Slot(str, str, str)
    def setProfileOption(self, profile, key, value):
        self._apply_profile(profile, [(key, value)])

    @Slot(str, str)
    def applyPreset(self, profile, preset):
        pre = next((p for p in self._data.get("presets", []) if p["id"] == preset), None)
        if pre:
            self._apply_profile(profile, [tuple(i.split("=", 1)) for i in pre["items"]])

    @Slot(str, str)
    def saveFanCurve(self, name, points):
        old = next((c for c in self._data.get("curves", []) if c["id"] == name), None)
        err = privileged.run("fan-curve", name, points)
        self.message.emit(err)
        if not err and old:
            self._arm([(("curve", name, ""), ",".join(f"{t}:{p}" for t, p in sorted(old["points"], reverse=True)))])
        self.refresh()

    @Slot()
    def confirm(self):
        self._forget()

    def _forget(self):
        self._undo, self._left, self._boot_revert = {}, 0, False
        try:
            os.remove(PENDING)
        except OSError:
            pass
        self.changed.emit()

    @Slot()
    def revert(self):
        undo = dict(self._undo)
        self._forget()
        by_profile, errors = {}, []
        for (kind, name, key), old in undo.items():
            if kind == "profile":
                by_profile.setdefault(name, []).append(f"{key}={old}")
            else:
                errors.append(privileged.run("fan-curve", name, old))
        for name, items in by_profile.items():
            errors.append(privileged.run("profile", name, *items))
        self.message.emit(next((e for e in errors if e), ""))
        self.refresh()

    def _tick(self):
        if self._boot_revert and privileged.available():
            self.revert()          # the app was closed before the change was confirmed
        elif self._left > 0:
            self._left -= 1
            self.changed.emit()
            if self._left == 0:
                self.revert()

    @Slot()
    def dropCaches(self):
        self._do("drop-caches")

    @Slot(bool, str, int)
    def setRgb(self, enabled, color, brightness):
        rgb = read_rgb()
        self._do("rgb", "true" if enabled else "false", color, brightness, rgb.get("saturation", 100),
                 "true" if rgb.get("linkBrightness") else "false", rgb.get("maxBrightness", 50))
