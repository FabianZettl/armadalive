"""Crash-safe replacement of small local state files."""
import json
import os
import stat
import tempfile


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _prepare_directory(path):
    os.makedirs(path, exist_ok=True)
    # An existing entry may come from an interrupted write or another writer.
    while path != (parent := os.path.dirname(path)):
        _sync_directory(parent)
        path = parent


def _replace(path, content, mode=None):
    directory = os.path.dirname(path)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".armadalive-", delete=False) as file:
        tmp = file.name
        try:
            file.write(content)
            file.flush()
            if mode is not None:
                os.fchmod(file.fileno(), mode)
            os.fsync(file.fileno())
            os.replace(tmp, path)
            _sync_directory(directory)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


def write_bytes(path, content, *, mode=None):
    """Durably replace a file with already serialized bytes."""
    path = os.path.abspath(path)
    _prepare_directory(os.path.dirname(path))
    _replace(path, content, mode=mode)


def encode_json(data, *, indent=None, allow_nan=False):
    return json.dumps(data, indent=indent, allow_nan=allow_nan).encode()


def write_json(path, data, *, validate=None, indent=None, follow_symlinks=False,
               require_writable=False, allow_nan=False):
    """Replace a JSON file. With a validator, keep its prior valid contents as .bak.

    With require_writable, check write access to an existing target without
    truncating or creating it. With allow_nan, retain legacy nonfinite values.
    """
    path = os.path.realpath(path) if follow_symlinks else os.path.abspath(path)
    content = encode_json(data, indent=indent, allow_nan=allow_nan)
    if require_writable:
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
        except FileNotFoundError:
            pass
    mode = None
    if follow_symlinks:
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except FileNotFoundError:
            pass
    _prepare_directory(os.path.dirname(path))
    if validate is not None:
        try:
            with open(path, "rb") as file:
                previous = file.read()
            if not validate(json.loads(previous)):
                previous = None
        except (FileNotFoundError, ValueError, RecursionError):
            previous = None
        backup = path + ".bak"
        if previous is not None:
            _replace(backup, previous)
        elif not os.path.exists(backup):
            _replace(backup, content)
    _replace(path, content, mode=mode)


def read_json(path, validate, default):
    """Use the last valid backup when the primary is unreadable or malformed."""
    for candidate in (os.fspath(path), os.fspath(path) + ".bak"):
        try:
            with open(candidate, "rb") as file:
                data = json.load(file)
            if validate(data):
                return data
        except (OSError, ValueError, RecursionError):
            continue
    return default


def remove(path):
    """Remove a committed state file and persist that directory update."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    _sync_directory(os.path.dirname(os.path.abspath(path)))
