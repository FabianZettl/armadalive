"""What is playing on the main screen's session (music, video, browser: anything that speaks MPRIS), with play/pause and skip."""
import json, os, subprocess
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

# ArmadaLive lives on the bottom session's private bus; the games and players run on the user's normal one
BUS = f"unix:path=/run/user/{os.getuid()}/bus"
PREFIX = "org.mpris.MediaPlayer2."
PLAYER = ["/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player"]


def _bus(*args):
    try:
        r = subprocess.run(["busctl", f"--address={BUS}", "--json=short", *args], capture_output=True, text=True, timeout=2)
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
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(3000)
        self._tick()

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    def _tick(self):
        listed = _bus("list") or []
        players = []
        for entry in listed:
            name = entry.get("name", "")
            if name.startswith(PREFIX):
                status = (_bus("get-property", name, *PLAYER, "PlaybackStatus") or {}).get("data", "")
                meta = (_bus("get-property", name, *PLAYER, "Metadata") or {}).get("data")
                players.append(describe(name, status, meta))
        found = pick(players)
        new = dict(found, active=True) if found else dict(active=False)
        if new != self._s:
            self._s = new
            self.changed.emit()

    def _send(self, method):
        if self._s.get("active"):
            subprocess.Popen(["busctl", f"--address={BUS}", "call", self._s["name"], *PLAYER, method],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            QTimer.singleShot(400, self._tick)

    @Slot()
    def playPause(self):
        self._send("PlayPause")

    @Slot()
    def next(self):
        self._send("Next")

    @Slot()
    def previous(self):
        self._send("Previous")
