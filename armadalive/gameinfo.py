"""What ES-DE knows about a game (its gamelist entry: description, genre, developer, year, rating) and its pictures, for the game info page."""
import glob, http.client, json, os, re, tempfile, threading, time, urllib.request
from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot

from . import nowplaying, steamlib
from .poller import Poller

STEAM_INFO = os.path.expanduser("~/.cache/armadalive/steam-info")   # what Steam's store says about a game, kept for a month
STEAM_MAX_AGE = 30 * 86400
STEAM_RETRY = 30
STEAM_API = "https://store.steampowered.com/api/appdetails?appids=%s&l=%s"
_titles = {}   # gamelist path -> (indexed entries, normalized titles)


def _pictures(system, base, kind):
    folder = glob.escape(f"{nowplaying.MEDIA}/{system}/{kind}/")
    paths = glob.glob(folder + glob.escape(base) + ".*") or glob.glob(folder + glob.escape(os.path.basename(base)) + ".*")
    return [QUrl.fromLocalFile(p).toString() for p in sorted(paths)]


def _empty_fields():
    return dict(name="", desc="", genre="", developer="", year="", rating=0, players="", cover="", shots=[])


def read(system, path):
    """{name, desc, genre, developer, year, rating (0..5, or 0), players, cover, shots} for a ROM; fields ES-DE has no entry for stay empty."""
    out = _empty_fields()
    if not re.fullmatch(r"[\w.-]+", system) or system in (".", "..") or not path:
        return out
    folder = nowplaying._rom_folder(system)
    entries, basenames = nowplaying._gamelist(system, folder)
    relative = nowplaying._gamelist_path(system, path, folder, basenames)
    base = os.path.splitext(relative or os.path.basename(path))[0]
    g = entries.get(relative)
    if g is not None:
        text = lambda tag: (g.findtext(tag) or "").strip()
        try:
            rating = round(float(text("rating") or 0) * 5, 1)
        except ValueError:
            rating = 0
        out.update(name=text("name"), desc=text("desc"), genre=text("genre"), developer=text("developer"), players=text("players"),
                   year=text("releasedate")[:4], rating=rating)
    covers = _pictures(system, base, "covers") or _pictures(system, base, "3dboxes")
    out["cover"] = covers[0] if covers else ""
    out["shots"] = _pictures(system, base, "screenshots")[:3] + _pictures(system, base, "titlescreens")[:1]
    return out


def _plain(text):
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def find(title):
    """(system, relative ROM path) of the ES-DE game with this name, or ("", "") - for a game that runs as a Steam shortcut and so has no ROM path of its own."""
    want = _plain(title)
    if want:
        root, definitions = nowplaying._rom_configuration()
        for f in sorted(glob.glob(glob.escape(nowplaying.GAMELISTS) + "/*/gamelist.xml")):
            system = os.path.basename(os.path.dirname(f))
            folder = nowplaying._system_folder(system, root, definitions.get(system))
            entries, _ = nowplaying._gamelist(system, folder)
            indexed = _titles.get(f)
            if indexed is None or indexed[0] is not entries:
                names = {}
                for path, game in entries.items():
                    names.setdefault(_plain(game.findtext("name") or ""), path)
                indexed = _titles[f] = entries, names
            if path := indexed[1].get(want):
                return system, path
    return "", ""


def _read_local(request):
    if request is None:
        return None
    system, path, title = request
    if title:
        system, path = find(title)
    return request, read(system, path)


def _steam_fetch(appid, lang):
    """Steam's store entry for an app as the raw `data` dict, or None (offline, unknown app, not a game)."""
    try:
        req = urllib.request.Request(STEAM_API % (appid, lang), headers={"User-Agent": "ArmadaLive"})
        deadline = time.monotonic() + 8
        limit = 2 * 1024 * 1024
        payload = bytearray()
        with urllib.request.urlopen(req, timeout=8) as response:
            while len(payload) <= limit and time.monotonic() < deadline:
                chunk = response.read1(min(65536, limit + 1 - len(payload)))
                if not chunk:
                    entry = json.loads(payload).get(str(appid)) or {}
                    return entry.get("data") if entry.get("success") else None
                payload.extend(chunk)
        return None
    except (OSError, http.client.HTTPException, ValueError, AttributeError):
        return None


def _steam_fields(data):
    year = re.search(r"\d{4}", (data.get("release_date") or {}).get("date", ""))
    score = (data.get("metacritic") or {}).get("score", 0)
    return dict(name=data.get("name", ""), desc=data.get("short_description", ""), genre=", ".join(g["description"] for g in data.get("genres", [])[:2]),
                developer=", ".join(data.get("developers", [])[:2]), year=year.group(0) if year else "", rating=round(score / 20, 1),
                shots=[s["path_thumbnail"] for s in data.get("screenshots", [])[:3] if s.get("path_thumbnail")])


def _steam_entry(appid):
    """Store fields and freshness. Expired fields remain usable during refresh."""
    try:
        with open(os.path.join(STEAM_INFO, f"{appid}.json"), encoding="utf-8") as f:
            fresh = time.time() - os.fstat(f.fileno()).st_mtime < STEAM_MAX_AGE
            return _steam_fields(json.load(f)), fresh
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        return {}, False


def _steam_display(appid):
    out = dict(name="", desc="", genre="", developer="", year="", rating=0, players="", cover="", shots=[])
    steam = steamlib.STEAM or os.path.expanduser("~/.local/share/Steam")
    art = sorted(glob.glob(glob.escape(os.path.join(steam, "appcache", "librarycache", appid))
                           + "/**/library_600x900*.jpg", recursive=True))
    out["cover"] = QUrl.fromLocalFile(art[0]).toString() if art else ""
    return out


def steam_read(appid, fetch=None, wait=False):
    """Return local cover and cached Steam store fields, even if the entry has expired."""
    fields, _ = _steam_entry(appid)
    return dict(_steam_display(appid), **fields)


def _save_steam_entry(appid, data):
    os.makedirs(STEAM_INFO, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=STEAM_INFO, delete=False) as f:
            tmp = f.name
            json.dump(data, f)
        os.replace(tmp, os.path.join(STEAM_INFO, f"{appid}.json"))
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


class GameInfo(QObject):
    """For the info page: game metadata and play history."""

    updated = Signal()
    _fetched = Signal(str, bool)

    def __init__(self, history):
        super().__init__()
        self._history = history
        self._active = self._pending = None
        self._steam_request = None
        self._retry = {}
        self._fetched.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self._local_fields = None
        request = self._local_request = [None]
        self._local = Poller(self, lambda: _read_local(request[0]), self._local_ready, 2000, now=False)

    def _request_local(self, request):
        if request != self._local_request[0]:
            self._local_request[0] = request
            self._local_fields = None
            self._local.refresh()

    def _local_ready(self, result):
        request, fields = result
        if request == self._local_request[0] and self._local_fields != fields:
            self._local_fields = fields
            self.updated.emit()

    @Slot()
    def suspend(self):
        self._request_local(None)
        self._steam_request = self._pending = None

    def _steam(self, appid):
        fields, fresh = _steam_entry(appid)
        now = time.monotonic()
        self._retry = {key: until for key, until in self._retry.items() if now < until}
        self._pending = None if fresh or appid == self._active or appid in self._retry else appid
        self._start()
        return dict(_steam_display(appid), **fields)

    def _start(self):
        if self._active is not None or self._pending is None:
            return
        appid, self._pending = self._pending, None
        self._active = appid
        lang = "german" if os.environ.get("LANG", "").startswith("de") else "english"
        threading.Thread(target=self._fetch, args=(appid, lang), daemon=True).start()

    def _fetch(self, appid, lang):
        success = False
        try:
            data = _steam_fetch(appid, lang)
            if data:
                _steam_fields(data)  # keep an existing cache entry if the refresh is malformed
                _save_steam_entry(appid, data)
                success = True
        except (OSError, ValueError, AttributeError, TypeError, KeyError):
            pass
        finally:
            self._fetched.emit(appid, success)

    @Slot(str, bool)
    def _complete(self, appid, success):
        self._active = None
        if not success:
            self._retry[appid] = time.monotonic() + STEAM_RETRY
        if success and appid == self._steam_request:
            self.updated.emit()
        self._start()

    @Slot(str, str, str, str, result="QVariant")
    def of(self, system, path, key, title=""):
        steam = re.fullmatch(r"steam/(\d+)", key or "")
        if steam and int(steam.group(1)) < 2 ** 31:   # a game of Steam itself: Steam knows its data
            self._request_local(None)
            self._steam_request = steam.group(1)
            out = self._steam(self._steam_request)
        else:
            self._steam_request = self._pending = None
            if (not path or system == "steam") and title:   # started through a Steam shortcut: find the game in ES-DE by its name
                request = "", "", title
            else:
                request = (system, path, "") if system and path else None
            self._request_local(request)
            out = dict(self._local_fields or _empty_fields(), loading=request is not None and self._local_fields is None)
        out.update(self._history.info(key) if key else dict(total=0, plays=0, last=0, favorite=False))
        return out
