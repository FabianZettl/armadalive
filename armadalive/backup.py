"""One file with ArmadaLive's settings, rules, tile order, app grid with folders and play history, to keep or to move to another device."""
import json, os, sys
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import __version__

CONFIG_DIR = os.path.expanduser("~/.config/armadalive")
FILE = os.path.expanduser("~/ArmadaLive-backup.json")
NAMES = ("ui.json", "game_rules.json", "tiles.json", "battery.json", "apps.json", "history.json")   # nothing else is ever read or written


def collect():
    files = {}
    for name in NAMES:
        try:
            with open(os.path.join(CONFIG_DIR, name)) as f:
                files[name] = json.load(f)
        except (OSError, ValueError):
            pass
    return dict(armadalive=__version__, files=files)


def apply(data):
    """Writes the known files from a backup; returns how many. Anything else in the file is ignored."""
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise ValueError("not an ArmadaLive backup")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    done = 0
    for name in NAMES:
        if isinstance(files.get(name), (dict, list)):
            with open(os.path.join(CONFIG_DIR, name), "w") as f:
                json.dump(files[name], f)
            done += 1
    return done


class Backup(QObject):
    changed = Signal()

    def __init__(self, writers=()):
        super().__init__()
        self._message = ""
        self._writers = tuple(writers)
        self._paused = []
        self._operation = ""
        self._drain = QTimer(self)
        self._drain.setInterval(20)
        self._drain.timeout.connect(self._check_writers)

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(path=FILE, exists=os.path.exists(FILE), message=self._message, busy=bool(self._operation))

    def _say(self, text):
        self._message = text
        self.changed.emit()

    @Slot()
    def save(self):
        self._start("save")

    @Slot()
    def restore(self):
        self._start("restore")

    def _start(self, operation):
        if self._operation:
            return
        self._operation = operation
        try:
            # These methods run on the writers' owner thread. Later edits remain
            # deferred while their already-accepted snapshots finish writing.
            for writer in self._writers:
                self._paused.append(writer)
                writer.pauseWrites()
        except (OSError, ValueError) as error:
            self._finish(error)
            return
        self._say("")
        self._drain.start()
        self._check_writers()

    @Slot()
    def _check_writers(self):
        try:
            if any(writer.writesPending() for writer in self._paused):
                return
        except (OSError, ValueError) as error:
            self._finish(error)
            return
        self._drain.stop()
        # Keep the existing file operations on the owner thread so synchronous
        # settings writers cannot interleave with collection or restoration.
        try:
            if self._operation == "save":
                with open(FILE, "w") as stream:
                    json.dump(collect(), stream, indent=1)
            else:
                with open(FILE) as stream:
                    apply(json.load(stream))
        except (OSError, ValueError) as error:
            self._finish(error)
        else:
            self._finish(None)

    def _finish(self, error):
        self._drain.stop()
        if error is None and self._operation == "restore":
            self._say("restored")
            QTimer.singleShot(800, self._restart)
            return
        self._operation = ""
        for writer in self._paused:
            writer.resumeWrites()
        self._paused.clear()
        self._say((str(error) or type(error).__name__) if error is not None else "saved")

    def _restart(self):
        try:
            os.execv(sys.executable, sys.orig_argv)
        except OSError as error:
            self._finish(error)
