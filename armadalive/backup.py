"""One file with ArmadaLive's settings, rules and tile order, to keep or to move to another device."""
import json, os, sys
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import __version__

CONFIG_DIR = os.path.expanduser("~/.config/armadalive")
FILE = os.path.expanduser("~/ArmadaLive-backup.json")
NAMES = ("ui.json", "game_rules.json", "tiles.json", "battery.json")   # nothing else is ever read or written


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

    def __init__(self):
        super().__init__()
        self._message = ""

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(path=FILE, exists=os.path.exists(FILE), message=self._message)

    def _say(self, text):
        self._message = text
        self.changed.emit()

    @Slot()
    def save(self):
        try:
            with open(FILE, "w") as f:
                json.dump(collect(), f, indent=1)
            self._say("saved")
        except OSError as e:
            self._say(str(e))

    @Slot()
    def restore(self):
        try:
            with open(FILE) as f:
                apply(json.load(f))
        except (OSError, ValueError) as e:
            self._say(str(e))
            return
        self._say("restored")
        QTimer.singleShot(800, lambda: os.execv(sys.executable, sys.orig_argv))   # start over so every part reads its file again
