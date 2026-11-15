"""In-app update: look up the newest GitHub release, download it and run its installer outside the running service."""
import fcntl, hashlib, json, os, re, shutil, socket, subprocess, tarfile, threading, time, urllib.request, uuid
from http.client import HTTPException

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from . import REPO, __version__, persistence

REPO_ID = os.environ.get("ARMADALIVE_REPO", REPO)
SHARE = os.path.expanduser("~/.local/share/armadalive")
CACHE = os.path.expanduser("~/.cache/armadalive/update")


def _version(tag):
    return tuple(int(x) for x in re.findall(r"\d+", tag)[:3])


ASSET, CHECKSUM = "armadalive.tar.gz", "armadalive.tar.gz.sha256"
CHECKSUM_LIMIT = 4096
INSTALL_TIMEOUT = 30 * 60

# Run independently of ArmadaLive's service. The exit record is visible to
# the restarted application, and the installer keeps its diagnostics in the journal.
RUN_INSTALLER = r'''work=$1
root=$2
lock=$3
finish() {
    status=$?
    printf '%s\n' "$status" > "$work.result.part" &&
        mv -f -- "$work.result.part" "$work.result"
    rm -rf -- "$work"
    exit "$status"
}
trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
# The launcher's start job returns while it still owns this lock. Hold it
# across the actual installation once that process releases it.
exec 9>>"$lock"
flock 9 || exit 1
(cd "$root" && ./install.sh)
'''


def notify_ready():
    """Acknowledge startup after the root window loads and the event loop starts."""
    address = os.environ.get("NOTIFY_SOCKET")
    if address:
        if address.startswith("@"):
            address = "\0" + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as ready:
            ready.sendto(b"READY=1", address)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _get(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"ArmadaLive/{__version__}"}), timeout=timeout)


def _release_info(release):
    if not isinstance(release, dict):
        raise ValueError("Invalid release metadata")
    tag = release.get("tag_name")
    assets = release.get("assets", [])
    if not isinstance(tag, str) or not _version(tag) or not isinstance(assets, list):
        raise ValueError("Invalid release metadata")
    downloads = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("Invalid release asset")
        name, url = asset.get("name"), asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str) or not url:
            raise ValueError("Invalid release asset")
        downloads[name] = url
    return tag, downloads


def _valid_record(record):
    if not isinstance(record, dict):
        return False
    name = record.get("attempt")
    return (isinstance(name, str) and re.fullmatch(r"install-[a-z0-9_]+", name)
            and isinstance(record.get("latest"), str)
            and isinstance(record.get("deadline"), (int, float))
            and isinstance(record.get("error", ""), str)
            and record.get("phase", "started") in ("downloading", "started"))


class Updater(QObject):
    changed = Signal()
    _worker_changed = Signal(dict)
    _installer_started = Signal()

    def __init__(self):
        super().__init__()
        self._s = dict(version=__version__, repo=REPO_ID, repoUrl=f"https://github.com/{REPO_ID}" if REPO_ID else "",
                       status="norepo" if not REPO_ID else "idle", latest="", message="", tarball="", sha="")
        self._worker_changed.connect(self._apply_worker_state)
        self._installer_started.connect(self._poll_completion)
        self._cache = os.path.abspath(CACHE)
        self._status_path = os.path.join(self._cache, "installation.json")
        self._lock_path = os.path.join(self._cache, "attempt.lock")
        self._completion = QTimer(self)
        self._completion.setInterval(1000)
        self._completion.timeout.connect(self._poll_completion)
        self._poll_completion()

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(self._s, scripts=f"{SHARE}/scripts")

    def _set(self, **kw):
        self._s.update(kw)
        self.changed.emit()

    @Slot(dict)
    def _apply_worker_state(self, state):
        self._set(**state)

    def _read_record(self):
        return persistence.read_json(self._status_path, _valid_record, {})

    def _wait(self, status, latest):
        if (self._s["status"], self._s["latest"]) != (status, latest):
            self._set(status=status, latest=latest, message="")
        if not self._completion.isActive():
            self._completion.start()

    @Slot()
    def _poll_completion(self):
        record = self._read_record()
        if not record:
            if self._completion.isActive():
                self._completion.stop()
                self._set(status="error", message="Could not read the update attempt.")
            return

        if record.get("phase") == "downloading" and not record.get("error"):
            try:
                with open(self._lock_path, "a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # The download might have advanced between the read and the lock.
                    record = self._read_record()
            except BlockingIOError:
                self._wait("installing", record["latest"])
                return
            except OSError as e:
                record = dict(record, error=str(e))
            if record.get("phase") == "downloading" and not record.get("error"):
                record["error"] = "The update download was interrupted."

        latest = record.get("latest", "")
        message = record.get("error", "")
        status = "error"
        if not message:
            try:
                result_path = os.path.join(self._cache, record["attempt"] + ".result")
                with open(result_path, encoding="ascii") as result:
                    code = int(result.read(32))
            except FileNotFoundError:
                if time.time() < record["deadline"]:
                    self._wait("started", latest)
                    return
                message = "The installer did not report a result. Check the armadalive-update journal."
            except (KeyError, OSError, ValueError):
                message = "Could not read the installer result. Check the armadalive-update journal."
            else:
                if code == 0:
                    status = "installed"
                else:
                    message = f"Installation failed (exit status {code}). Check the armadalive-update journal."
        self._completion.stop()
        self._set(status=status, latest=latest, message=message)

    @Slot()
    def openRepo(self):
        if self._s["repoUrl"]:
            QDesktopServices.openUrl(QUrl(self._s["repoUrl"]))

    @Slot()
    def check(self):
        if not REPO_ID or self._s["status"] in ("checking", "installing", "started"):
            return
        self._set(status="checking", message="")
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            with _get(f"https://api.github.com/repos/{REPO_ID}/releases/latest") as response:
                tag, assets = _release_info(json.load(response))
            newer = _version(tag) > _version(__version__)
        except (OSError, ValueError, HTTPException) as e:
            return self._worker_changed.emit(dict(status="error", message=str(e)))
        if newer:
            if ASSET in assets and CHECKSUM in assets:
                self._worker_changed.emit(dict(status="available", latest=tag, tarball=assets[ASSET], sha=assets[CHECKSUM], message=""))
            else:  # nothing to verify the download against: do not run it
                self._worker_changed.emit(dict(status="error", latest=tag, message="Release has no checksum file; update by hand from GitHub"))
        else:
            self._worker_changed.emit(dict(status="uptodate", latest=tag, message=""))

    @Slot()
    def install(self):
        if self._s["status"] != "available":
            return
        self._set(status="installing", message="")
        threading.Thread(target=self._install, daemon=True).start()

    def _install(self):
        try:
            os.makedirs(self._cache, mode=0o700, exist_ok=True)
            with open(self._lock_path, "a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self._worker_changed.emit(dict(status="error", message="An update is already running."))
                    return
                self._install_locked()
        except OSError as e:
            self._worker_changed.emit(dict(status="error", message=str(e)))

    def _install_locked(self):
        previous = self._read_record()
        if previous:
            old_work = os.path.join(self._cache, previous["attempt"])
            if (not previous.get("error") and previous.get("phase", "started") == "started"
                    and time.time() < previous["deadline"] and not os.path.exists(old_work + ".result")):
                self._installer_started.emit()
                return

        name = f"install-{uuid.uuid4().hex}"
        work = os.path.join(self._cache, name)
        record = dict(attempt=name, latest=self._s["latest"], phase="downloading", deadline=0)
        persistence.write_json(self._status_path, record)
        try:
            if previous:
                shutil.rmtree(old_work, ignore_errors=True)
                for suffix in (".result", ".result.part"):
                    try:
                        os.unlink(old_work + suffix)
                    except FileNotFoundError:
                        pass
            os.mkdir(work, mode=0o700)
            archive = os.path.join(work, "release.tar.gz")
            with _get(self._s["tarball"], 60) as response, open(archive, "wb") as output:
                shutil.copyfileobj(response, output)
            with _get(self._s["sha"]) as response:
                checksum = response.read(CHECKSUM_LIMIT + 1)
            tokens = checksum.split(maxsplit=1)
            if len(checksum) > CHECKSUM_LIMIT or not tokens or not re.fullmatch(b"[0-9a-fA-F]{64}", tokens[0]):
                raise ValueError("Release checksum is missing or malformed")
            if sha256(archive) != tokens[0].decode("ascii").lower():
                raise ValueError("checksum mismatch, download discarded")

            dest = os.path.join(work, "release")
            with tarfile.open(archive) as t:
                t.extractall(dest, filter="data")  # refuses absolute paths, links out of the tree and device files
            with os.scandir(dest) as entries:
                (root,) = [entry.path for entry in entries if entry.is_dir(follow_symlinks=False)]
            if not os.path.isfile(os.path.join(root, "install.sh")):
                raise RuntimeError("release has no install.sh")

            record.update(phase="started", deadline=time.time() + INSTALL_TIMEOUT + 60)
            persistence.write_json(self._status_path, record)
            subprocess.run(["systemd-run", "--user", "--collect", "--quiet", "--unit=armadalive-update",
                            f"--property=RuntimeMaxSec={INSTALL_TIMEOUT}s",
                            "sh", "-c", RUN_INSTALLER, "sh", work, root, self._lock_path], check=True)
        except (OSError, ValueError, RuntimeError, HTTPException, tarfile.TarError, subprocess.CalledProcessError) as e:
            message = str(e) or type(e).__name__
            shutil.rmtree(work, ignore_errors=True)
            try:
                persistence.write_json(self._status_path, dict(record, error=message))
            except OSError:
                pass
            self._worker_changed.emit(dict(status="error", message=message))
        else:
            self._installer_started.emit()
