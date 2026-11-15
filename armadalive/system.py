"""Live device stats and power controls for the AYN Thor on Armada OS."""
import collections, glob, json, subprocess
from functools import partial
from PySide6.QtCore import Property, QObject, Signal, Slot
from .poller import Poller
from .commands import Commands, run

GPU_DEVFREQ = "/sys/class/devfreq/3d00000.gpu/cur_freq"
BATTERY = "/sys/class/power_supply/battery"


def _read(path, default=""):
    try:
        return open(path).read().strip()
    except OSError:
        return default


def _cpu_times():
    f = open("/proc/stat").readline().split()[1:]
    vals = [int(x) for x in f]
    return vals[3] + vals[4], sum(vals)  # idle+iowait, total


def _cpu_ghz():
    """(highest current, highest possible) clock over all CPU clusters, in GHz."""
    cur = [int(_read(f, "0")) for f in glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq")]
    top = [int(_read(f, "0")) for f in glob.glob("/sys/devices/system/cpu/cpufreq/policy*/cpuinfo_max_freq")]
    return max(cur or [0]) / 1e6, max(top or [1]) / 1e6


def _ram():
    m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
    return (m["MemTotal"] - m["MemAvailable"]) / 1048576, m["MemTotal"] / 1048576


POWER = {
    "temp": ("Temperature", 0), "fanRpm": ("FanRpm", 0), "fanPwm": ("FanPwm", 0),
    "profile": ("Profile", ""), "profiles": ("AvailableProfiles", ()),
    "gpuLevel": ("GpuPerformanceLevel", "auto"), "gpuMin": ("ManualGpuClockMin", 220),
    "gpuMax": ("ManualGpuClockMax", 680), "gpuManual": ("ManualGpuClock", 680),
}


def _power_state():
    """Get the power properties in one bounded D-Bus request via the system bus client."""
    try:
        result = subprocess.run(
            ["busctl", "--system", "--json=short", "call", "org.armada.Power", "/org/armada/Power",
             "org.freedesktop.DBus.Properties", "GetAll", "s", "org.armada.Power1"],
            capture_output=True, text=True, timeout=1)
        if result.returncode:
            return None
        data = json.loads(result.stdout)["data"][0]
        return {key: value["data"] for key, value in data.items()}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, AttributeError, TypeError):
        return None


def _essential():
    return (
        _cpu_times(),
        int(_read(BATTERY + "/current_now", "0")),
        int(_read(BATTERY + "/voltage_now", "0")),
        int(_read(BATTERY + "/charge_now", "0")),
        int(_read(BATTERY + "/charge_full", "0")),
        _read(BATTERY + "/status") == "Charging",
        int(_read(BATTERY + "/capacity", "0")),
    )


class SystemMonitor(QObject):
    changed = Signal()
    profileFinished = Signal(object, bool)

    def __init__(self, fps=None):
        super().__init__()
        self._fps = fps or (lambda: 0)
        self._hist = {k: collections.deque(maxlen=120) for k in ("fps", "cpu", "temp", "watts", "battery")}
        self._amps = collections.deque(maxlen=20)
        self._cpu = None
        self._profile_request = 0
        self._commands = Commands(self)
        self._commands.completed.connect(self._command_completed)
        self._commands.settled.connect(self._refresh_power)
        power = {key: default for key, (_, default) in POWER.items()}
        self._stats = dict(power, profiles=[], cpu=0, ramUsed=0, ramTotal=0, cpuGhz=0, cpuMaxGhz=0,
                           gpuMhz=0, battery=0, charging=False, watts=0, led=False, eta=-1)
        self._power_poller = Poller(self, _power_state, self._apply_power, 1000)
        self._essential_poller = Poller(self, _essential, self._apply_essential, 1000)
        self._detail_poller = Poller(self, self._read_detail, self._apply_detail, 1000, idle_ms=15000)

    def set_active(self, active):
        self._detail_poller.set_active(active)

    @Property("QVariant", notify=changed)
    def stats(self):
        return self._stats

    @Property("QVariant", notify=changed)
    def history(self):
        """The last two minutes, one sample per second, for each series."""
        return {k: list(v) for k, v in self._hist.items()}

    def _apply_power(self, power):
        stats = {key: power.get(name, default) for key, (name, default) in POWER.items()}
        stats["profiles"] = list(stats["profiles"])
        self._stats = dict(self._stats, **stats)
        self.changed.emit()

    def _apply_essential(self, sample):
        (idle, total), amps, volts, now, full, charging, battery = sample
        d_idle, d_total = (idle - self._cpu[0], total - self._cpu[1]) if self._cpu else (0, 0)
        self._cpu = (idle, total)
        self._amps.append(abs(amps))
        avg = sum(self._amps) / len(self._amps)  # current jumps around: judge the time left on the last 20 seconds
        left = (full - now) if charging else now
        eta = round(60 * left / avg) if avg > 50000 and full else -1   # minutes; -1 when unknown
        self._stats = dict(
            self._stats, cpu=round(100 * (1 - d_idle / d_total)) if d_total else 0,
            battery=battery, charging=charging, watts=round(abs(amps * volts) / 1e12, 1), eta=eta)
        for key, value in (("fps", self._fps()), ("cpu", self._stats["cpu"]), ("temp", self._stats["temp"]),
                           ("watts", self._stats["watts"]), ("battery", self._stats["battery"])):
            self._hist[key].append(value)
        self.changed.emit()

    @staticmethod
    def _read_detail():
        used, total = _ram()
        cur, top = _cpu_ghz()
        return dict(ramUsed=round(used, 1), ramTotal=round(total, 1), cpuGhz=round(cur, 2), cpuMaxGhz=round(top, 2),
                    gpuMhz=int(_read(GPU_DEVFREQ, "0")) // 1000000, led=SystemMonitor._led())

    def _apply_detail(self, detail):
        self._stats = dict(self._stats, **detail)
        self.changed.emit()

    @staticmethod
    def _led():
        try:
            return bool(json.load(open("/etc/armada/rgb.json")).get("enabled"))
        except (OSError, ValueError):
            return False

    @Slot(str)
    def _refresh_power(self, _):
        self._power_poller.refresh()

    @Slot(str, object, bool)
    def _command_completed(self, channel, request, succeeded):
        if channel == "profile" and request == self._profile_request:
            self.profileFinished.emit(request, succeeded)

    def _power_cli(self, channel, *args, target=None):
        self._commands.submit(channel, partial(run, "armada-power", *args), target)

    @Slot(str)
    def setProfile(self, name):
        self._profile_request += 1
        request = self._profile_request
        self._power_cli("profile", "profile", name, target=request)
        return request

    @Slot()
    def setGpuAuto(self):
        self._power_cli("gpu", "gpu-auto")

    @Slot(int)
    def setGpuManual(self, mhz):
        self._power_cli("gpu", "gpu-manual", str(int(mhz)))
