"""What ES-DE knows about a game (its gamelist entry: description, genre, developer, year, rating) and its pictures, for the game info page."""
import glob, http.client, json, os, re, time, urllib.request
from collections import OrderedDict
from PySide6.QtCore import QObject, QUrl, Signal, Slot

from . import nowplaying, persistence, steamlib
from .poller import Poller

STEAM_INFO = os.path.expanduser("~/.cache/armadalive/steam-info")   # what Steam's store says about a game, kept for a month
STEAM_MAX_AGE = 30 * 86400
STEAM_RETRY = 30
STEAM_RESPONSE_LIMIT = 2 * 1024 * 1024
STEAM_CACHE_LIMIT = 3 * STEAM_RESPONSE_LIMIT
STEAM_API = "https://store.steampowered.com/api/appdetails?appids=%s&l=%s"


def _empty_fields():
    return dict(name="", desc="", genre="", developer="", year="", rating=0, players="", cover="", shots=[])


def _pictures(system, base, kind):
    return [QUrl.fromLocalFile(p).toString() for p in sorted(glob.glob(f"{glob.escape(nowplaying.MEDIA)}/{glob.escape(system)}/{kind}/{glob.escape(base)}.*"))]


def read(system, path):
    """{name, desc, genre, developer, year, rating (0..5, or 0), players, cover, shots} for a ROM; fields ES-DE has no entry for stay empty."""
    out = _empty_fields()
    if not nowplaying._valid_system(system) or not path:
        return out
    base = os.path.splitext(os.path.basename(path))[0]
    g = nowplaying._gamelist_entries(system).get(os.path.basename(path))
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
    """(system, file name) of the ES-DE game with this name, or ("", "") - for a game that runs as a Steam shortcut and so has no ROM path of its own."""
    want = _plain(title)
    if want:
        for f in sorted(glob.glob(glob.escape(nowplaying.GAMELISTS) + "/*/gamelist.xml")):
            system = os.path.basename(os.path.dirname(f))
            for name, g in nowplaying._gamelist_entries(system).items():
                if _plain(g.findtext("name") or "") == want:
                    return system, name
    return "", ""


def _steam_fetch(appid, lang):
    """Steam's store entry for an app as the raw `data` dict, or None (offline, unknown app, not a game)."""
    try:
        req = urllib.request.Request(STEAM_API % (appid, lang), headers={"User-Agent": "ArmadaLive"})
        deadline = time.monotonic() + 8
        limit = STEAM_RESPONSE_LIMIT
        payload = bytearray()
        with urllib.request.urlopen(req, timeout=8) as response:
            while len(payload) <= limit and time.monotonic() < deadline:
                chunk = response.read1(min(65536, limit + 1 - len(payload)))
                if not chunk:
                    entry = json.loads(payload).get(str(appid)) or {}
                    return entry.get("data") if entry.get("success") else None
                payload.extend(chunk)
    except (OSError, http.client.HTTPException, ValueError, AttributeError):
        pass
    return None


def _steam_fields(data):
    year = re.search(r"\d{4}", (data.get("release_date") or {}).get("date", ""))
    score = (data.get("metacritic") or {}).get("score", 0)
    return dict(name=data.get("name", ""), desc=data.get("short_description", ""), genre=", ".join(g["description"] for g in data.get("genres", [])[:2]),
                developer=", ".join(data.get("developers", [])[:2]), year=year.group(0) if year else "", rating=round(score / 20, 1),
                shots=[s["path_thumbnail"] for s in data.get("screenshots", [])[:3] if s.get("path_thumbnail")])


def _steam_entry(appid):
    """Store fields and freshness. Keep expired fields usable during refresh."""
    try:
        with open(os.path.join(STEAM_INFO, f"{appid}.json"), "rb") as file:
            fresh = time.time() - os.fstat(file.fileno()).st_mtime < STEAM_MAX_AGE
            data = file.read(STEAM_CACHE_LIMIT + 1)
        if len(data) <= STEAM_CACHE_LIMIT:
            return _steam_fields(json.loads(data)), fresh
    except (OSError, ValueError, AttributeError, TypeError, KeyError, RecursionError):
        pass
    return {}, False


def _steam_cover(appid):
    steam = steamlib.STEAM or os.path.expanduser("~/.local/share/Steam")
    cache = os.path.join(steam, "appcache", "librarycache", appid)
    art = min((os.path.join(folder, file)
               for folder, _, files in os.walk(cache) for file in files
               if file.startswith("library_600x900") and file.endswith(".jpg")), default="")
    return QUrl.fromLocalFile(art).toString() if art else ""


def _cached_steam(appid):
    fields, fresh = _steam_entry(appid)
    return dict(_empty_fields(), **fields, cover=_steam_cover(appid)), fresh


def steam_read(appid, fetch=None, wait=False):
    """Return local cover and cached Steam store fields, including expired entries."""
    return _cached_steam(appid)[0]


def _read_metadata(request):
    if request is None:
        return None
    kind, *args = request
    if kind == "steam":
        fields, fresh = _cached_steam(args[0])
        return request, fields, not fresh
    system, path = find(args[0]) if kind == "shortcut" else args
    return request, read(system, path), False


def _refresh_store(appid, retries):
    if appid is None or time.monotonic() < retries.get(appid, 0):
        return None
    lang = "german" if os.environ.get("LANG", "").startswith("de") else "english"
    try:
        data = _steam_fetch(appid, lang)
        if data:
            _steam_fields(data)  # Preserve cached fields if the refresh is malformed.
            persistence.write_json(os.path.join(STEAM_INFO, f"{appid}.json"), data)
            retries.pop(appid, None)
            return appid
    except (OSError, ValueError, AttributeError, TypeError, KeyError, RecursionError):
        pass
    retries[appid] = time.monotonic() + STEAM_RETRY
    retries.move_to_end(appid)
    if len(retries) > 128:
        retries.popitem(last=False)
    return None


class GameInfo(QObject):
    """Game metadata and play history for the information page."""

    updated = Signal()

    def __init__(self, history):
        super().__init__()
        self._history = history
        self._fields = None
        request = self._request = [None]
        store = self._store_request = [None]
        retries = OrderedDict()  # Only the single-flight store worker reads or writes this.
        self._local = Poller(self, lambda: _read_metadata(request[0]), self._local_ready, 2000, now=False)
        self._store = Poller(self, lambda: _refresh_store(store[0], retries), self._store_ready, 30000, now=False)

    def _set_request(self, request):
        if request == self._request[0]:
            return
        self._request[0] = request
        self._store_request[0] = None
        self._fields = None
        self._local.refresh()

    def _local_ready(self, result):
        request, fields, stale = result
        if request != self._request[0]:
            return
        previous = self._store_request[0]
        self._store_request[0] = request[1] if stale else None
        if self._fields != fields:
            self._fields = fields
            self.updated.emit()
        if self._store_request[0] is not None:
            if self._store_request[0] == previous:
                self._store.kick()
            else:
                self._store.refresh()

    def _store_ready(self, appid):
        if self._request[0] == ("steam", appid):
            self._store_request[0] = None
            self._local.refresh()

    @Slot()
    def suspend(self):
        self._set_request(None)

    @Slot(str, str, str, str, result="QVariant")
    def of(self, system, path, key, title=""):
        steam = re.fullmatch(r"steam/(\d+)", key or "")
        if steam and int(steam.group(1)) < 2 ** 31:
            request = ("steam", steam.group(1))
        elif (not path or system == "steam") and title:
            request = ("shortcut", title)
        else:
            request = ("local", system, path) if system and path else None
        self._set_request(request)
        out = dict(self._fields or _empty_fields(), loading=request is not None and self._fields is None)
        out.update(self._history.info(key) if key else dict(total=0, plays=0, last=0, favorite=False))
        return out
