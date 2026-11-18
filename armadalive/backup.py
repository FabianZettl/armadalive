"""One file with ArmadaLive's settings, rules, tile order, app grid with folders and play history, to keep or to move to another device."""
import json, logging, os, sys, time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import __version__

CONFIG_DIR = os.path.expanduser("~/.config/armadalive")
FILE = os.path.expanduser("~/ArmadaLive-backup.json")
NAMES = ("ui.json", "game_rules.json", "tiles.json", "battery.json", "apps.json", "history.json")   # nothing else is ever read or written
WRITE_TIMEOUT = 3.0
log = logging.getLogger(__name__)


def collect():
    files = {}
    for name in NAMES:
        path = os.path.join(CONFIG_DIR, name)
        try:
            with open(path) as f:
                files[name] = json.load(f)
        except (OSError, ValueError, RecursionError) as error:
            if isinstance(error, FileNotFoundError) and not os.path.lexists(path):
                continue
            raise ValueError(f"Could not read {name}: {error}") from error
    return dict(armadalive=__version__, files=files)


def apply(data, *, destination_opened=None):
    """Write known files and report each destination once it is open for writing."""
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise ValueError("not an ArmadaLive backup")
    os.makedirs(CONFIG_DIR, exist_ok=True)
    done = 0
    for name in NAMES:
        if isinstance(files.get(name), (dict, list)):
            with open(os.path.join(CONFIG_DIR, name), "w") as f:
                if destination_opened is not None:
                    destination_opened()
                json.dump(files[name], f)
            done += 1
    return done


class Backup(QObject):
    changed = Signal()

    def __init__(self, writers=()):
        """Coordinate background writers that share Backup's owner thread."""
        super().__init__()
        self._writers = tuple(writers)
        self._paused = []
        self._message = self._operation = ""
        self._destination_touched = self._restart_required = False
        self._deadline = 0.0
        self._drain = QTimer(self)
        self._drain.setInterval(20)
        self._drain.timeout.connect(self._check_writers)

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(path=FILE, exists=os.path.exists(FILE), message=self._message,
                    busy=bool(self._operation), restartRequired=self._restart_required)

    def _say(self, text):
        self._message = text
        self.changed.emit()

    @Slot()
    def save(self):
        if not self._restart_required:
            self._start("save")

    @Slot()
    def restore(self):
        if self._operation:
            return
        if self._restart_required:
            self._operation = "restore"
            self._restart()
        else:
            self._start("restore")

    def _start(self, operation):
        if self._operation:
            return
        self._operation = operation
        self._deadline = time.monotonic() + WRITE_TIMEOUT
        try:
            for writer in self._writers:
                self._paused.append(writer)
                writer.pauseWrites(restoring=operation == "restore")
        except (OSError, ValueError) as error:
            self._fail(error)
            return
        self._say("")
        self._drain.start()
        self._check_writers()

    def _check_writers(self):
        try:
            # Check every writer so one stalled writer cannot hide another's error.
            pending = [writer.writesPending() for writer in self._paused]
            if any(pending):
                if time.monotonic() >= self._deadline:
                    raise TimeoutError("Timed out waiting for configuration writes")
                return
            self._drain.stop()
            if self._operation == "save":
                data = collect()
                with open(FILE, "w") as f:
                    json.dump(data, f, indent=1)
                self._resume_writers()
                self._operation = ""
                self._say("saved")
            else:
                with open(FILE) as f:
                    apply(json.load(f), destination_opened=self._mark_destination_touched)
                self._say("restored")
                QTimer.singleShot(800, self._restart)  # Reload every backend from disk.
        except (OSError, ValueError, RecursionError) as error:
            self._fail(error)

    def _mark_destination_touched(self):
        self._destination_touched = True

    def _resume_writers(self):
        for writer in self._paused:
            writer.resumeWrites()
        self._paused.clear()

    def _fail(self, error):
        self._drain.stop()
        if self._destination_touched:
            # A restored file may no longer match the old process's in-memory state.
            self._restart_required = True
        else:
            self._resume_writers()
        self._operation = ""
        self._say(str(error) or type(error).__name__)

    def _restart(self):
        try:
            os.execv(sys.executable, sys.orig_argv)
        except OSError as error:
            self._fail(error)

    @Slot()
    def flushWriters(self):
        """Drain registered writers within one shutdown budget."""
        deadline = time.monotonic() + WRITE_TIMEOUT
        self._drain.stop()
        if self._destination_touched:
            return  # These writers drained before restore and must stay frozen.
        # Leaving during export must still save edits accepted after its cutoff.
        self._resume_writers()
        for writer in self._writers:
            try:
                writer.flush(timeout=max(0.0, deadline - time.monotonic()))
            except (OSError, ValueError) as error:
                log.error("%s configuration remains unsaved at shutdown: %s", type(writer).__name__, error)
