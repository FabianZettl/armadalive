"""Power profiles, fan curves and RGB: read as the user, written through the root helper."""
import configparser, json, os
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import privileged

FACTORY, OVERRIDE = "/usr/share/armada/power-profiles.conf", "/etc/armada/power-profiles.conf"
PROFILES = ("eco", "balanced", "performance")
GPU_FREQS = "/sys/class/devfreq/3d00000.gpu/available_frequencies"
GOVERNORS = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors"
UNDERCLOCK = ("none", "small", "medium", "large")


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
        self.refresh()
        timer = QTimer(self)
        timer.timeout.connect(self.refresh)
        timer.start(5000)  # the helper may be installed while the app runs

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
        self._data = dict(power, helper=self._helper, rgb=read_rgb())
        self.changed.emit()

    def _do(self, *args):
        err = privileged.run(*args)
        self.message.emit(err)
        self.refresh()

    @Slot(str, str, str)
    def setProfileOption(self, profile, key, value):
        self._do("profile", profile, f"{key}={value}")

    @Slot(str, str)
    def saveFanCurve(self, name, points):
        self._do("fan-curve", name, points)

    @Slot()
    def dropCaches(self):
        self._do("drop-caches")

    @Slot(bool, str, int)
    def setRgb(self, enabled, color, brightness):
        rgb = read_rgb()
        self._do("rgb", "true" if enabled else "false", color, brightness, rgb.get("saturation", 100),
                 "true" if rgb.get("linkBrightness") else "false", rgb.get("maxBrightness", 50))
