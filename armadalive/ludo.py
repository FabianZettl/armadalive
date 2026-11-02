"""What the Ludo plugin (Decky, RomM) is doing before a game starts, read from its log, so the bottom screen can show it."""
import glob, os, re
from PySide6.QtCore import Property, QObject, QTimer, Signal

LOGS = os.environ.get("ARMADALIVE_LUDO_LOGS", os.path.expanduser("~/homebrew/logs/ludo"))
GIVE_UP_MS = 45000   # the log may never say "done" (another emulator, a crash): the banner goes by itself

# shortcut: these are Ludo's log lines as of v1.0.0-beta.27; a different wording only means no banner
SESSION = re.compile(r"Save-sync session \((.*)\)")
PRELAUNCH = re.compile(r"Pre-launch sync for (.+)\.\.\.$")
PRELAUNCH_DONE = re.compile(r"Pre-launch sync complete for (.+)$")


class LudoSync(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._s, self._session, self._file, self._pos = dict(phase="", title=""), False, "", 0
        self._gone = QTimer(self)
        self._gone.setSingleShot(True)
        self._gone.timeout.connect(lambda: self._set("", ""))
        timer = QTimer(self)
        timer.timeout.connect(self.poll)
        timer.start(500)

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    def _set(self, phase, title):
        new = dict(phase=phase, title=title)
        if new != self._s:
            self._s = new
            self.changed.emit()
        self._gone.start(GIVE_UP_MS) if phase else self._gone.stop()

    def feed(self, line):
        """phase: check (is a newer save on the server?) | sync | start | upload (after a game closed) | "" """
        if m := SESSION.search(line):
            self._session = True
            if "closed" in m.group(1):
                self._set("upload", "")
        elif "session sync" in line and "s (dirs" in line:
            self._session = False
            if self._s["phase"] == "upload":
                self._set("", "")
        elif "inventory: save-file walk" in line and not self._session and not self._s["phase"]:
            self._set("check", "")   # the walk of the check before a start has no session line of its own
        elif m := PRELAUNCH.search(line):
            self._set("sync", m.group(1))
        elif m := PRELAUNCH_DONE.search(line):
            self._set("start", m.group(1))
        elif "RetroArch content loaded" in line or "RetroArch launched" in line:
            self._set("", "")

    def poll(self):
        files = glob.glob(f"{glob.escape(LOGS)}/*.log")
        if not files:
            return
        newest = max(files, key=os.path.getmtime)
        try:
            size = os.path.getsize(newest)
            if newest != self._file:   # a new log (Decky restarted): start at its end, never replay old lines
                self._file, self._pos = newest, size
                return
            if size < self._pos:
                self._pos = 0
            if size == self._pos:
                return
            with open(newest, errors="replace") as f:
                f.seek(self._pos)
                data = f.read(1_000_000)
                self._pos = f.tell()
        except OSError:
            return
        for line in data.splitlines():
            self.feed(line)
