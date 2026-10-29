"""Quick settings: radios, volume and the brightness of both screens."""
import json, os, re, subprocess, threading
from . import privileged
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

# DSI-1 (1080x1240) is the bottom panel, DSI-2 (1080x1920) the top one; the backlight names follow the DSI order
BACKLIGHTS = dict(bottom=os.environ.get("ARMADALIVE_BOTTOM_BACKLIGHT", "ae94000.dsi.0"),
                  top=os.environ.get("ARMADALIVE_TOP_BACKLIGHT", "ae96000.dsi.0"))
SINK = "@DEFAULT_AUDIO_SINK@"
MIN_PERCENT = 3  # never black out a screen: the bottom one is the one these sliders live on


def _out(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _run(*cmd):
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _read(path, default=0):
    try:
        return int(open(path).read())
    except (OSError, ValueError):
        return default


def tailscale_state(text):
    """{state: on | off | login | missing, ip} from `tailscale status --json`; "missing" when there is no daemon to ask."""
    try:
        d = json.loads(text)
    except ValueError:
        return dict(state="missing", ip="")
    state = {"Running": "on", "NeedsLogin": "login", "NeedsMachineAuth": "login"}.get(d.get("BackendState"), "off")
    return dict(state=state, ip=((d.get("Self") or {}).get("TailscaleIPs") or [""])[0])


def tailscale_retry(stderr):
    """`tailscale up` refuses to run when earlier flags (such as --operator) are not repeated, and prints the command that would work.
    Returns those flags, only if they look like plain flags."""
    for line in stderr.splitlines():
        words = line.split()
        if words[:2] == ["tailscale", "up"] and all(re.fullmatch(r"--[a-z-]+(=[\w.,:/@-]+)?", w) for w in words[2:]):
            return words[2:]
    return None


class Controls(QObject):
    changed = Signal()
    notice = Signal(str, str)   # a short message code for the popup (see Main.qml), and a detail

    def __init__(self):
        super().__init__()
        self._s, self._n, self._ts = {}, 0, dict(state="missing", ip="")
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(2000)
        self._tick()

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    def _tick(self):
        wifi = _out("nmcli", "radio", "wifi").strip() == "enabled"
        bluetooth = "Soft blocked: no" in _out("rfkill", "list", "bluetooth")  # this rfkill has no JSON output
        vol = re.search(r"([\d.]+)", _out("wpctl", "get-volume", SINK))
        bright = {}
        for name, dev in BACKLIGHTS.items():
            base = f"/sys/class/backlight/{dev}"
            top = _read(base + "/max_brightness", 1)
            bright[name] = round(100 * _read(base + "/brightness") / top)
        saver = "power save: on" in _out("iw", "dev", self._wlan(), "get", "power_save").lower() if wifi else False
        if self._n % 3 == 0:    # a status call is the most expensive thing here, and the VPN changes rarely
            self._ts = tailscale_state(_out("tailscale", "status", "--json"))
        self._n += 1
        self._s = dict(wifi=wifi, wifips=saver, tailscale=self._ts, bluetooth=bluetooth, airplane=not wifi and not bluetooth,
                       volume=min(1.0, float(vol.group(1))) if vol else 0.0, muted="[MUTED]" in _out("wpctl", "get-volume", SINK),
                       brightness=bright)
        self.changed.emit()

    @staticmethod
    def _wlan():
        return next((d for d in os.listdir("/sys/class/net") if os.path.isdir(f"/sys/class/net/{d}/phy80211")), "wlan0")

    @Slot()
    def toggleTailscale(self):
        state = self._ts["state"]
        if state in ("missing", "login"):
            self.notice.emit("tsmissing" if state == "missing" else "tslogin", "")
            return
        up = state != "on"

        def run():
            r = subprocess.run(["tailscale", "up" if up else "down"], capture_output=True, text=True, timeout=25)
            if r.returncode and up and (flags := tailscale_retry(r.stderr)) is not None:
                r = subprocess.run(["tailscale", "up", *flags], capture_output=True, text=True, timeout=25)
            text = (r.stderr + r.stdout).lower()
            self.notice.emit(("tsdenied" if "denied" in text or "sudo" in text else "tsfail") if r.returncode else ("tson" if up else "tsoff"), "")
            self._ts = tailscale_state(_out("tailscale", "status", "--json"))
        threading.Thread(target=run, daemon=True).start()

    @Slot()
    def toggleWifiSaver(self):
        # shortcut: the kernel drops this setting when Wi-Fi reconnects, so it is a per-session switch
        if privileged.available():
            privileged.run("wifi-powersave", "off" if self._s.get("wifips") else "on")
            self._tick()

    @Slot()
    def toggleWifi(self):
        _run("nmcli", "radio", "wifi", "off" if self._s.get("wifi") else "on")

    @Slot()
    def toggleBluetooth(self):
        _run("rfkill", "block" if self._s.get("bluetooth") else "unblock", "bluetooth")

    @Slot()
    def toggleAirplane(self):
        on = not self._s.get("airplane")
        _run("nmcli", "radio", "wifi", "off" if on else "on")
        _run("rfkill", "block" if on else "unblock", "bluetooth")

    @Slot()
    def toggleMute(self):
        _run("wpctl", "set-mute", SINK, "toggle")

    @Slot(float)
    def setVolume(self, fraction):
        _run("wpctl", "set-volume", SINK, f"{max(0.0, min(1.0, fraction)):.2f}")

    @Slot(str, int)
    def setBrightness(self, which, percent):
        dev = BACKLIGHTS.get(which)
        if not dev:
            return
        top = _read(f"/sys/class/backlight/{dev}/max_brightness", 0)
        value = round(max(MIN_PERCENT, min(100, percent)) / 100 * top)
        _run("busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
             "org.freedesktop.login1.Session", "SetBrightness", "ssu", "backlight", dev, str(value))

    @Slot()
    def screenshot(self):
        pictures = os.path.expanduser("~/Pictures")
        os.makedirs(pictures, exist_ok=True)
        _run("spectacle", "-b", "-n", "-f", "-o", f"{pictures}/armadalive-{os.getpid()}-{int(__import__('time').time())}.png")
