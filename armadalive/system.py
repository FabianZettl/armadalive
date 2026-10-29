"""Live device stats and power controls for the AYN Thor on Armada OS."""
import collections, glob, json, os, subprocess
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface

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


class SystemMonitor(QObject):
    changed = Signal()

    def __init__(self, fps=None):
        super().__init__()
        self._fps = fps or (lambda: 0)
        self._hist = {k: collections.deque(maxlen=120) for k in ("fps", "cpu", "temp", "watts", "battery")}
        self._amps = collections.deque(maxlen=20)
        self._power = QDBusInterface("org.armada.Power", "/org/armada/Power", "org.armada.Power1",
                                     QDBusConnection.systemBus())
        self._cpu = _cpu_times()
        self._stats = {}
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)
        self._tick()

    @Property("QVariant", notify=changed)
    def stats(self):
        return self._stats

    @Property("QVariant", notify=changed)
    def history(self):
        """The last two minutes, one sample per second, for each series."""
        return {k: list(v) for k, v in self._hist.items()}

    def _prop(self, name, default=None):
        v = self._power.property(name) if self._power.isValid() else None
        return default if v is None else v

    def _tick(self):
        idle, total = _cpu_times()
        d_idle, d_total = idle - self._cpu[0], total - self._cpu[1]
        self._cpu = (idle, total)
        used, total_gb = _ram()
        amps, volts = int(_read(BATTERY + "/current_now", "0")), int(_read(BATTERY + "/voltage_now", "0"))
        self._amps.append(abs(amps))
        avg = sum(self._amps) / len(self._amps)  # current jumps around: judge the time left on the last 20 seconds
        now, full = int(_read(BATTERY + "/charge_now", "0")), int(_read(BATTERY + "/charge_full", "0"))
        charging = _read(BATTERY + "/status") == "Charging"
        left = (full - now) if charging else now
        eta = round(60 * left / avg) if avg > 50000 and full else -1   # minutes; -1 when unknown
        self._stats = dict(
            cpu=round(100 * (1 - d_idle / d_total)) if d_total else 0,
            ramUsed=round(used, 1), ramTotal=round(total_gb, 1),
            cpuGhz=round(_cpu_ghz()[0], 2), cpuMaxGhz=round(_cpu_ghz()[1], 2),
            gpuMhz=int(_read(GPU_DEVFREQ, "0")) // 1000000,
            temp=self._prop("Temperature", 0), fanRpm=self._prop("FanRpm", 0), fanPwm=self._prop("FanPwm", 0),
            profile=self._prop("Profile", ""), profiles=list(self._prop("AvailableProfiles", [])),
            gpuLevel=self._prop("GpuPerformanceLevel", "auto"),
            gpuMin=self._prop("ManualGpuClockMin", 220), gpuMax=self._prop("ManualGpuClockMax", 680),
            gpuManual=self._prop("ManualGpuClock", 680),
            battery=int(_read(BATTERY + "/capacity", "0")), charging=_read(BATTERY + "/status") == "Charging",
            watts=round(abs(amps * volts) / 1e12, 1), led=self._led(), eta=eta)
        for key, value in (("fps", self._fps()), ("cpu", self._stats["cpu"]), ("temp", self._stats["temp"]),
                           ("watts", self._stats["watts"]), ("battery", self._stats["battery"])):
            self._hist[key].append(value)
        self.changed.emit()

    @staticmethod
    def _led():
        try:
            return bool(json.load(open("/etc/armada/rgb.json")).get("enabled"))
        except (OSError, ValueError):
            return False

    @staticmethod
    def _power_cli(*args):
        subprocess.Popen(["armada-power", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @Slot(str)
    def setProfile(self, name):
        self._power_cli("profile", name)

    @Slot()
    def setGpuAuto(self):
        self._power_cli("gpu-auto")

    @Slot(int)
    def setGpuManual(self, mhz):
        self._power_cli("gpu-manual", str(int(mhz)))
