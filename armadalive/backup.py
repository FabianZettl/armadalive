"""One file with ArmadaLive's settings, rules, tile order, app grid with folders and play history, to keep or to move to another device."""
import base64, json, logging, os, secrets, stat, sys, time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import __version__, battery, gamerules, persistence, tiles, ui
from .history import _valid_history

CONFIG_DIR = os.path.expanduser("~/.config/armadalive")
FILE = os.path.expanduser("~/ArmadaLive-backup.json")
JOURNAL = ".restore-undo.json"
RESTART_TOKEN = "ARMADALIVE_RESTORE_TOKEN"
WRITE_TIMEOUT = 3.0
log = logging.getLogger(__name__)


def _validate_apps(saved):
    if not isinstance(saved, dict) or not isinstance(saved.get("slots"), list):
        raise ValueError("slots must be a list of app names")
    folders = saved.get("folders", {})
    if not isinstance(folders, dict):
        raise ValueError("folders must be an object")
    for key, folder in folders.items():
        if (not isinstance(folder, dict) or not isinstance(folder.get("items", []), list)):
            raise ValueError(f"invalid folder {key!r}")
    try:
        int(saved.get("next", len(folders) + 1))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("next must be a folder number") from error
    return True


VALIDATORS = {
    "ui.json": ui.validate_settings,
    "game_rules.json": gamerules.validate_settings,
    "tiles.json": tiles.validate_settings,
    "battery.json": battery.validate_settings,
    "apps.json": _validate_apps,
    "history.json": _valid_history,
}


class RestoreRecoveryError(OSError):
    """An unfinished restore must be recovered before configuration is loaded."""


def _portable_data(name, data):
    if name == "game_rules.json" and "base" in data:
        return {key: value for key, value in data.items() if key != "base"}
    return data


def collect():
    files = {}
    for name, validate in VALIDATORS.items():
        path = os.path.join(CONFIG_DIR, name)
        try:
            with open(path) as stream:
                data = json.load(stream)
            if not validate(data):
                raise ValueError("invalid configuration data")
            files[name] = _portable_data(name, data)
        except (OSError, ValueError, TypeError, RecursionError) as error:
            if isinstance(error, FileNotFoundError) and not os.path.lexists(path):
                continue
            raise ValueError(f"Could not read {name}: {error}") from error
    return dict(armadalive=__version__, files=files)


def _targets():
    return {name: os.path.realpath(os.path.join(CONFIG_DIR, name)) for name in VALIDATORS}


def _journal_path():
    return os.path.join(os.path.realpath(CONFIG_DIR), JOURNAL)


def _read_target(path):
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(f"{path} is not a regular file")
        with open(path, "rb") as stream:
            return stream.read(), stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
    except FileNotFoundError:
        return None, None


def _restore_target(path, original, mode):
    if original is None:
        if os.path.isdir(os.path.dirname(path)):
            persistence.remove(path)
    elif _read_target(path) != (original, mode):
        persistence.write_bytes(path, original, mode=mode)
    else:
        # A previous recovery might have replaced the file before its directory
        # sync failed. Ensure the original is durable before clearing the journal.
        with open(path, "rb") as stream:
            os.fsync(stream.fileno())
        persistence._sync_directory(os.path.dirname(path))


def _journal_entries(records, path):
    targets = _targets()
    if not isinstance(records, dict) or not records:
        raise ValueError("invalid restore journal")
    entries = []
    for name, record in records.items():
        if (name not in targets or not isinstance(record, list) or len(record) != 3
                or record[0] != targets[name] or record[0] == path
                or list(targets.values()).count(record[0]) != 1):
            raise ValueError(f"{name}: restore target has changed")
        target, data, mode = record
        if data is None and mode is None:
            entries.append((target, None, None))
        elif isinstance(data, str) and type(mode) is int and 0 <= mode <= 0o7777:
            entries.append((target, base64.b64decode(data, validate=True), mode))
        else:
            raise ValueError(f"{name}: invalid original contents in restore journal")
    return entries


def recover_restore(*, startup=False):
    """Restore pre-import bytes after an interrupted transaction, before any backend loads."""
    path = _journal_path()
    token = os.environ.pop(RESTART_TOKEN, None) if startup else None
    try:
        if os.path.islink(path):
            raise ValueError("restore journal is a symbolic link")
        payload, _ = _read_target(path)
        if payload is None:
            return
        journal = json.loads(payload)
        if not isinstance(journal, dict) or not isinstance(journal.get("token"), str):
            raise ValueError("invalid restore journal")
        entries = _journal_entries(journal.get("records"), path)
        if token and token == journal["token"]:
            persistence.remove(path)
            return
        failures = []
        for target, original, mode in reversed(entries):
            try:
                _restore_target(target, original, mode)
            except OSError as error:
                failures.append(f"{target}: {error}")
        if failures:
            raise OSError(", ".join(failures))
        persistence.remove(path)
    except (OSError, ValueError, RecursionError) as error:
        raise RestoreRecoveryError(f"Could not recover the interrupted backup restore ({path}): {error}") from error


def apply(data):
    """Validate all included files, then restore them as one recoverable operation."""
    return len(_restore(data).get("records", {}))


def _restore(data, *, await_restart=False):
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise ValueError("not an ArmadaLive backup")
    prepared = {}
    for name, validate in VALIDATORS.items():
        if name in files:
            try:
                if not validate(files[name]):
                    raise ValueError("invalid configuration data")
                prepared[name] = persistence.encode_json(_portable_data(name, files[name]), allow_nan=name in ("ui.json", "battery.json", "game_rules.json"))
            except (ValueError, TypeError, RecursionError) as error:
                raise ValueError(f"{name}: {error}") from error

    recover_restore()
    if not prepared:
        return {}
    path = _journal_path()
    targets = _targets()
    records = {}
    for name in prepared:
        target = targets[name]
        if target == path or list(targets.values()).count(target) != 1:
            raise ValueError(f"{name}: backup files cannot share a restore target")
        previous, mode = _read_target(target)
        if previous is not None:
            os.close(os.open(target, os.O_WRONLY | os.O_NONBLOCK))
        records[name] = [target, None if previous is None else base64.b64encode(previous).decode(), mode]
        if name == "game_rules.json" and previous is not None:
            # A device that has yet to migrate its old recovery values must
            # retain them even when a backup supplies different rules.
            legacy = _local_legacy_base(previous)
            if not legacy:
                legacy = persistence.read_json(target, gamerules.validate_settings, {}).get("base", {})
            if legacy:
                prepared[name] = persistence.encode_json({**json.loads(prepared[name]), "base": legacy}, allow_nan=True)

    journal = dict(token=secrets.token_hex(24), records=records)
    try:
        # Keep the original contents durable until all replacements are durable.
        persistence.write_json(path, journal)
    except OSError:
        recover_restore()
        raise
    try:
        for name, content in prepared.items():
            target, _, mode = records[name]
            persistence.write_bytes(target, content, mode=mode)
        if not await_restart:
            persistence.remove(path)
    except OSError:
        _rollback_restore(journal)
        raise
    return journal


def _rollback_restore(journal):
    # The direct apply API may fail syncing journal removal after replacement.
    # Recreate its evidence before attempting rollback in that case.
    if not os.path.lexists(_journal_path()):
        try:
            persistence.write_json(_journal_path(), journal)
        except OSError as error:
            raise RestoreRecoveryError(f"Could not preserve restore journal: {error}") from error
    recover_restore()


def _local_legacy_base(content):
    try:
        saved = json.loads(content)
        base = saved.get("base", {}) if isinstance(saved, dict) else {}
        if isinstance(base, dict) and all(value is None or isinstance(value, str) for value in base.values()):
            return base
    except (ValueError, RecursionError):
        pass
    return {}


def _export(path):
    content = persistence.encode_json(collect(), indent=1, allow_nan=True)
    target = os.path.realpath(path)
    previous, mode = _read_target(target)
    if previous is not None:
        os.close(os.open(target, os.O_WRONLY | os.O_NONBLOCK))
    try:
        persistence.write_bytes(target, content, mode=mode)
    except OSError:
        _restore_target(target, previous, mode)
        raise


class Backup(QObject):
    changed = Signal()

    def __init__(self, writers=()):
        """Coordinate background writers that share Backup's owner thread."""
        super().__init__()
        self._writers = tuple(writers)
        self._paused = []
        self._message = self._operation = ""
        self._destination_touched = self._restart_required = False
        self._restart_undo = None
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
            try:
                recover_restore()
            except RestoreRecoveryError as error:
                self._fail(error)
                return
            self._restart_required = self._destination_touched = False
            self._restart_undo = None
            self._resume_writers()
            self._start("restore")
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
                _export(FILE)
                self._resume_writers()
                self._operation = ""
                self._say("saved")
            else:
                with open(FILE) as f:
                    self._restart_undo = _restore(json.load(f), await_restart=True)
                self._destination_touched = bool(self._restart_undo)
                self._say("restored")
                QTimer.singleShot(800, self._restart)  # Reload every backend from disk.
        except (OSError, ValueError, RecursionError) as error:
            self._fail(error)

    def _resume_writers(self):
        for writer in self._paused:
            writer.resumeWrites()
        self._paused.clear()

    def _fail(self, error):
        self._drain.stop()
        if isinstance(error, RestoreRecoveryError) or os.path.lexists(_journal_path()):
            # Recovery evidence remains; old live writers must not touch it.
            self._restart_required = True
        else:
            self._destination_touched = self._restart_required = False
            self._restart_undo = None
            self._resume_writers()
        self._operation = ""
        self._say(str(error) or type(error).__name__)

    def _restart(self):
        try:
            if self._restart_undo:
                # Exec inherits this token. A new unrelated process rolls back;
                # only this successfully exec'd process commits the restore.
                os.environ[RESTART_TOKEN] = self._restart_undo["token"]
            os.execv(sys.executable, sys.orig_argv)
        except OSError as error:
            os.environ.pop(RESTART_TOKEN, None)
            try:
                recover_restore()
            except RestoreRecoveryError as rollback_error:
                self._fail(RestoreRecoveryError(f"{error}. {rollback_error}"))
                return
            self._fail(error)

    @Slot()
    def flushWriters(self):
        """Drain registered writers within one shutdown budget."""
        deadline = time.monotonic() + WRITE_TIMEOUT
        self._drain.stop()
        if self._destination_touched or self._restart_required:
            return  # These writers drained before restore and must stay frozen.
        # Leaving during export must still save edits accepted after its cutoff.
        self._resume_writers()
        for writer in self._writers:
            try:
                writer.flush(timeout=max(0.0, deadline - time.monotonic()))
            except (OSError, ValueError) as error:
                log.error("%s configuration remains unsaved at shutdown: %s", type(writer).__name__, error)
