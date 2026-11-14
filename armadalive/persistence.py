"""Crash-safe replacement of small local state files."""
import json
import os
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


def _replace(path, content):
    directory = os.path.dirname(path)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".armadalive-", delete=False) as file:
        tmp = file.name
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
            os.replace(tmp, path)
            _sync_directory(directory)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


def write_json(path, data, *, validate=None):
    """Replace a JSON file. With a validator, keep its prior valid contents as .bak."""
    path = os.path.abspath(path)
    content = json.dumps(data, allow_nan=False).encode()
    _prepare_directory(os.path.dirname(path))
    if validate is not None:
        try:
            with open(path, "rb") as file:
                previous = file.read()
            if not validate(json.loads(previous)):
                previous = None
        except (FileNotFoundError, ValueError):
            previous = None
        backup = path + ".bak"
        if previous is not None:
            _replace(backup, previous)
        elif not os.path.exists(backup):
            _replace(backup, content)
    _replace(path, content)


def read_json(path, validate, default):
    """Use the last valid backup when the primary is unreadable or malformed."""
    for candidate in (os.fspath(path), os.fspath(path) + ".bak"):
        try:
            with open(candidate, "rb") as file:
                data = json.load(file)
            if validate(data):
                return data
        except (OSError, ValueError):
            continue
    return default


def remove(path):
    """Remove a committed state file and persist that directory update."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    _sync_directory(os.path.dirname(os.path.abspath(path)))
