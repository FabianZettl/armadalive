"""Quick settings: radios, volume and the brightness of both screens."""
import glob, json, os, re, subprocess, threading
from . import privileged
from .poller import Poller
from PySide6.QtCore import Property, QObject, Signal, Slot

# DSI-1 (1080x1240) is the bottom panel, DSI-2 (1080x1920) the top one; the backlight names follow the DSI order
BACKLIGHTS = dict(bottom=os.environ.get("ARMADALIVE_BOTTOM_BACKLIGHT", "ae94000.dsi.0"),
                  top=os.environ.get("ARMADALIVE_TOP_BACKLIGHT", "ae96000.dsi.0"))
SINK = "@DEFAULT_AUDIO_SINK@"
# Frame generation of Eglantine, Eden and TotK (MAKO): the launchers skip it while this file exists, see mako-thor/env.sh
FRAMEGEN_OFF = os.environ.get("ARMADALIVE_FRAMEGEN_OFF", os.path.expanduser("~/.config/mako-thor/off"))
MIN_PERCENT = 3  # never black out a screen: the bottom one is the one these sliders live on


def _out(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _rfkill(kind):
    """True when the radio of this type is on, False when it is blocked, None when the kernel lists none."""
    for node in glob.glob("/sys/class/rfkill/rfkill*"):
        try:
            if open(node + "/type").read().strip() == kind:
                return open(node + "/soft").read().strip() == "0" and open(node + "/hard").read().strip() == "0"
        except OSError:
            pass
    return None


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
        self._ts = dict(state="missing", ip="")
        self._s = dict(tailscale=self._ts, brightness={}, volume=0)
        self._poller = Poller(self, self._read, self._apply, 2000, idle_ms=15000)
        self._vpn_poller = Poller(self, self._read_vpn, self._apply_vpn, 6000, idle_ms=30000)

    def set_active(self, active):
        self._poller.set_active(active)
        self._vpn_poller.set_active(active)

    @staticmethod
    def _read_vpn():
        text = _out("tailscale", "status", "--json")
        return None if text is None else tailscale_state(text)

    def _apply_vpn(self, status):
        self._ts = status
        self._apply(self._s)

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    @staticmethod
    def _read():
        state = {}
        wifi, bluetooth = _rfkill("wlan"), _rfkill("bluetooth")
        if wifi is None and (text := _out("nmcli", "radio", "wifi")) is not None:
            wifi = {"enabled": True, "disabled": False}.get(text.strip())
        if bluetooth is None and (text := _out("rfkill", "list", "bluetooth")) is not None:
            if "Soft blocked:" in text:
                bluetooth = "Soft blocked: no" in text and "Hard blocked: yes" not in text
        if wifi is not None:
            state["wifi"] = wifi
        if bluetooth is not None:
            state["bluetooth"] = bluetooth
        if wifi is False:
            state["wifips"] = False
        elif wifi is True and (text := _out("iw", "dev", Controls._wlan(), "get", "power_save")) is not None:
            if match := re.search(r"power save: (on|off)", text.lower()):
                state["wifips"] = match[1] == "on"
        if (text := _out("wpctl", "get-volume", SINK)) is not None:
            if vol := re.search(r"Volume:\s*(\d+(?:\.\d+)?)", text):
                state.update(volume=min(1.0, float(vol[1])), muted="[MUTED]" in text)
        bright = {}
        for name, dev in BACKLIGHTS.items():
            base = f"/sys/class/backlight/{dev}"
            top = _read(base + "/max_brightness", None)
            value = _read(base + "/brightness", None)
            if top and value is not None:
                bright[name] = round(100 * value / top)
        return dict(state, framegen=not os.path.exists(FRAMEGEN_OFF), brightness=bright)

    def _apply(self, state):
        brightness = dict(self._s["brightness"], **state.get("brightness", {}))
        state = {**self._s, **state, "tailscale": self._ts, "brightness": brightness}
        state["airplane"] = state.get("wifi") is False and state.get("bluetooth") is False
        if state != self._s:
            self._s = state
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
            self._vpn_poller.refresh()
        threading.Thread(target=run, daemon=True).start()

    @Slot()
    def toggleWifiSaver(self):
        # shortcut: the kernel drops this setting when Wi-Fi reconnects, so it is a per-session switch
        if privileged.available():
            def run(mode="off" if self._s.get("wifips") else "on"):
                privileged.run("wifi-powersave", mode)   # sudo: not on the UI thread
                self._poller.kick()
            threading.Thread(target=run, daemon=True).start()

    @Slot()
    def toggleFrameGen(self):
        # shortcut: only games started afterwards see it; a running game keeps the setting it started with
        try:
            if os.path.exists(FRAMEGEN_OFF):
                os.remove(FRAMEGEN_OFF)
            else:
                os.makedirs(os.path.dirname(FRAMEGEN_OFF), exist_ok=True)
                open(FRAMEGEN_OFF, "w").close()
        except OSError:
            return
        self._poller.kick()

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
