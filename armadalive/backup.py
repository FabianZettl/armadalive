"""One file with ArmadaLive's settings, rules, tile order, app grid with folders and play history, to keep or to move to another device."""
import base64, json, os, stat, sys
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from . import __version__, battery, gamerules, persistence, tiles, ui
from .history import _valid_history

CONFIG_DIR = os.path.expanduser("~/.config/armadalive")
FILE = os.path.expanduser("~/ArmadaLive-backup.json")
JOURNAL = ".restore-undo.json"


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _validate_apps(saved):
    if not isinstance(saved, dict) or not _strings(saved.get("slots")):
        raise ValueError("slots must be a list of app names")
    folders = saved.get("folders", {})
    if not isinstance(folders, dict):
        raise ValueError("folders must be an object")
    for key, folder in folders.items():
        if (not isinstance(folder, dict) or not isinstance(folder.get("name", ""), str)
                or not _strings(folder.get("items", []))):
            raise ValueError(f"invalid folder {key!r}")
    counter = saved.get("next", len(folders) + 1)
    if type(counter) is not int or counter < 1 or str(counter) in folders:
        raise ValueError("next must be an unused positive folder number")
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
    recover_restore()
    files = {}
    for name, validate in VALIDATORS.items():
        data = persistence.read_json(os.path.join(CONFIG_DIR, name), validate, None)
        if data is not None:
            files[name] = _portable_data(name, data)
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


def recover_restore():
    """Restore pre-import bytes after an interrupted transaction, before any backend loads."""
    path = _journal_path()
    try:
        if os.path.islink(path):
            raise ValueError("restore journal is a symbolic link")
        payload, _ = _read_target(path)
        if payload is None:
            return
        entries = _journal_entries(json.loads(payload), path)
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
    return len(_restore(data))


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
                prepared[name] = persistence.encode_json(_portable_data(name, files[name]))
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
        records[name] = [target, None if previous is None else base64.b64encode(previous).decode(), mode]
        if name == "game_rules.json" and previous is not None:
            # A device that has yet to migrate its old recovery values must
            # retain them even when a backup supplies different rules.
            legacy = _local_legacy_base(previous)
            if legacy:
                prepared[name] = persistence.encode_json({**json.loads(prepared[name]), "base": legacy})

    try:
        # Keep the original contents durable until all replacements are durable.
        persistence.write_json(path, records)
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
        _rollback_restore(records)
        raise
    return records


def _rollback_restore(records):
    path = _journal_path()
    # Exec can fail after we unlink the journal. Recommit the prior bytes
    # before rolling back so a second restart can finish recovery.
    if records and not os.path.lexists(path):
        try:
            persistence.write_json(path, records)
        except OSError as error:
            raise RestoreRecoveryError(f"Could not recommit the restore journal ({path}): {error}") from error
    recover_restore()


def _local_legacy_base(content):
    try:
        saved = json.loads(content)
        if gamerules.validate_settings(saved):
            return saved.get("base", {})
    except (ValueError, RecursionError):
        pass
    return {}


def _export(path):
    content = persistence.encode_json(collect(), indent=1)
    target = os.path.realpath(path)
    previous, mode = _read_target(target)
    try:
        persistence.write_bytes(target, content, mode=mode)
    except OSError:
        _restore_target(target, previous, mode)
        raise


class Backup(QObject):
    changed = Signal()

    def __init__(self, writers=()):
        super().__init__()
        self._message = ""
        self._writers = tuple(writers)
        self._paused = []
        self._operation = ""
        self._restart_undo = None
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
                if writer not in self._paused:
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
            if self._restart_undo is not None:
                _rollback_restore(self._restart_undo)
                self._restart_undo = None
            if self._operation == "save":
                _export(FILE)
            else:
                with open(FILE) as stream:
                    self._restart_undo = _restore(json.load(stream), await_restart=True)
        except (OSError, ValueError, RecursionError) as error:
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
        if not isinstance(error, RestoreRecoveryError) and not os.path.lexists(_journal_path()):
            for writer in self._paused:
                writer.resumeWrites()
            self._paused.clear()
        self._say((str(error) or type(error).__name__) if error is not None else "saved")

    def _restart(self):
        try:
            if self._restart_undo:
                persistence.remove(_journal_path())
            os.execv(sys.executable, sys.orig_argv)
        except OSError as error:
            try:
                _rollback_restore(self._restart_undo)
            except RestoreRecoveryError as rollback_error:
                self._finish(RestoreRecoveryError(f"{error}. {rollback_error}"))
                return
            self._restart_undo = None
            self._finish(error)
