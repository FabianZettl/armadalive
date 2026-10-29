"""In-app update: look up the newest GitHub release, download it and run its installer outside the running service."""
import hashlib, json, os, re, shutil, subprocess, tarfile, threading, urllib.request
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from . import REPO, __version__

REPO_ID = os.environ.get("ARMADALIVE_REPO", REPO)
SHARE = os.path.expanduser("~/.local/share/armadalive")
CACHE = os.path.expanduser("~/.cache/armadalive/update")


def _version(tag):
    return tuple(int(x) for x in re.findall(r"\d+", tag)[:3])


ASSET, CHECKSUM = "armadalive.tar.gz", "armadalive.tar.gz.sha256"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _get(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"ArmadaLive/{__version__}"}), timeout=timeout)


class Updater(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._s = dict(version=__version__, repo=REPO_ID, repoUrl=f"https://github.com/{REPO_ID}" if REPO_ID else "",
                       status="norepo" if not REPO_ID else "idle", latest="", message="", tarball="", sha="")

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(self._s, scripts=f"{SHARE}/scripts")

    def _set(self, **kw):
        self._s.update(kw)
        self.changed.emit()

    @Slot()
    def openRepo(self):
        if self._s["repoUrl"]:
            QDesktopServices.openUrl(QUrl(self._s["repoUrl"]))

    @Slot()
    def check(self):
        if not REPO_ID or self._s["status"] in ("checking", "installing"):
            return
        self._set(status="checking", message="")
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            release = json.load(_get(f"https://api.github.com/repos/{REPO_ID}/releases/latest"))
            tag = release["tag_name"]
        except (OSError, ValueError, KeyError) as e:
            return self._set(status="error", message=str(e))
        assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
        if _version(tag) > _version(__version__):
            if ASSET in assets and CHECKSUM in assets:
                self._set(status="available", latest=tag, tarball=assets[ASSET], sha=assets[CHECKSUM], message="")
            else:  # nothing to verify the download against: do not run it
                self._set(status="error", latest=tag, message="Release has no checksum file; update by hand from GitHub")
        else:
            self._set(status="uptodate", latest=tag, message="")

    @Slot()
    def install(self):
        if self._s["status"] != "available":
            return
        self._set(status="installing", message="")
        threading.Thread(target=self._install, daemon=True).start()

    def _install(self):
        try:
            tag = re.sub(r"[^\w.-]", "_", self._s["latest"])
            dest = f"{CACHE}/{tag}"
            shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(dest)
            archive = f"{dest}.tar.gz"
            with _get(self._s["tarball"], 60) as r, open(archive, "wb") as f:
                shutil.copyfileobj(r, f)
            want = _get(self._s["sha"]).read().decode().split()[0].lower()
            if sha256(archive) != want:
                os.remove(archive)
                raise RuntimeError("checksum mismatch, download discarded")
            with tarfile.open(archive) as t:
                t.extractall(dest, filter="data")  # refuses absolute paths, links out of the tree and device files
            (root,) = [d for d in os.listdir(dest) if os.path.isdir(f"{dest}/{d}")]
            script = f"{dest}/{root}/install.sh"
            if not os.path.isfile(script):
                raise RuntimeError("release has no install.sh")
            # a separate unit: the installer restarts armadalive, which would take a child process down with it
            subprocess.run(["systemd-run", "--user", "--collect", "--quiet", "--unit=armadalive-update", "sh", "-c",
                            'cd "$1" && ./install.sh', "sh", f"{dest}/{root}"], check=True)
            self._set(status="installed")
        except (OSError, ValueError, RuntimeError, tarfile.TarError, subprocess.CalledProcessError) as e:
            self._set(status="error", message=str(e))
