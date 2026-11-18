"""What is playing on the main screen's session (music, video, browser: anything that speaks MPRIS), with play/pause and skip."""
import json, os, subprocess, time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from .poller import Poller

# ArmadaLive lives on the bottom session's private bus; the games and players run on the user's normal one
BUS = f"unix:path=/run/user/{os.getuid()}/bus"
PREFIX = "org.mpris.MediaPlayer2."
PLAYER = ["/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player"]


def _bus(*args, timeout=2):
    try:
        r = subprocess.run(["busctl", f"--address={BUS}", "--json=short", *args], capture_output=True, text=True, timeout=timeout)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def pick(players):
    """The player that is playing, else one that is paused, else none."""
    for wanted in ("Playing", "Paused"):
        for p in players:
            if p["status"] == wanted:
                return p
    return None


def describe(name, status, metadata):
    meta = metadata or {}
    value = lambda k: (meta.get(k) or {}).get("data")
    artist = value("xesam:artist")
    return dict(name=name, status=status, title=value("xesam:title") or "",
                artist=", ".join(artist) if isinstance(artist, list) else (artist or ""))


class Media(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._s = dict(active=False)
        self._poller = Poller(self, self._read, self._apply, 3000, idle_ms=15000)   # busctl runs here: not on the UI thread

    def set_active(self, active):
        self._poller.set_active(active)

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    @staticmethod
    def _read():
        deadline = time.monotonic() + 4

        def query(*args):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            return _bus(*args, timeout=min(2, remaining))

        listed = query("list")
        if not isinstance(listed, list):
            return None
        paused, failed = [], False
        for entry in listed:
            if time.monotonic() >= deadline:
                return None
            name = entry.get("name", "")
            if not name.startswith(PREFIX):
                continue
            reply = query("get-property", name, *PLAYER, "PlaybackStatus")
            if not isinstance(reply, dict) or "data" not in reply:
                failed = True
                continue
            status = reply["data"]
            if status == "Playing":
                if found := Media._describe(query, name, status):
                    return found
                failed = True
            elif status == "Paused":
                paused.append(name)
        for name in paused:
            if time.monotonic() >= deadline:
                return None
            if found := Media._describe(query, name, "Paused"):
                return found
            failed = True
        return None if failed else dict(active=False)

    @staticmethod
    def _describe(query, name, status):
        reply = query("get-property", name, *PLAYER, "Metadata")
        if not isinstance(reply, dict) or not isinstance(reply.get("data"), dict):
            return None
        return dict(describe(name, status, reply["data"]), active=True)

    def _apply(self, new):
        if new != self._s:
            self._s = new
            self.changed.emit()

    def _send(self, method):
        if self._s.get("active"):
            subprocess.Popen(["busctl", f"--address={BUS}", "call", self._s["name"], *PLAYER, method],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            QTimer.singleShot(400, self._poller.refresh)

    @Slot()
    def playPause(self):
        self._send("PlayPause")

    @Slot()
    def next(self):
        self._send("Next")

    @Slot()
    def previous(self):
        self._send("Previous")
