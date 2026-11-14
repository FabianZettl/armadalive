"""What ES-DE knows about a game (its gamelist entry: description, genre, developer, year, rating) and its pictures, for the game info page."""
import glob, http.client, json, os, re, tempfile, threading, time, urllib.request
import xml.etree.ElementTree as ET
from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot

from . import nowplaying, steamlib

_cache = {}   # gamelist path -> (mtime, {relative ROM path: entry})
STEAM_INFO = os.path.expanduser("~/.cache/armadalive/steam-info")   # what Steam's store says about a game, kept for a month
STEAM_MAX_AGE = 30 * 86400
STEAM_RETRY = 30
STEAM_API = "https://store.steampowered.com/api/appdetails?appids=%s&l=%s"


def _entries(system):
    f = f"{nowplaying.GAMELISTS}/{system}/gamelist.xml"
    try:
        mtime = os.stat(f).st_mtime_ns
        if _cache.get(f, (None,))[0] != mtime:
            _cache[f] = (mtime, {nowplaying.rom_relative(system, g.findtext("path") or ""): g
                                 for g in ET.parse(f).getroot().iter("game")})
        return _cache[f][1]
    except (OSError, ET.ParseError):
        return {}


def _pictures(system, base, kind):
    folder = glob.escape(f"{nowplaying.MEDIA}/{system}/{kind}/")
    paths = glob.glob(folder + glob.escape(base) + ".*") or glob.glob(folder + glob.escape(os.path.basename(base)) + ".*")
    return [QUrl.fromLocalFile(p).toString() for p in sorted(paths)]


def read(system, path):
    """{name, desc, genre, developer, year, rating (0..5, or 0), players, cover, shots} for a ROM; fields ES-DE has no entry for stay empty."""
    out = dict(name="", desc="", genre="", developer="", year="", rating=0, players="", cover="", shots=[])
    if not re.fullmatch(r"[\w.-]+", system) or system in (".", "..") or not path:
        return out
    relative = nowplaying.rom_relative(system, path)
    base = os.path.splitext(relative)[0]
    g = _entries(system).get(relative)
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
        for f in sorted(glob.glob(f"{nowplaying.GAMELISTS}/*/gamelist.xml")):
            system = os.path.basename(os.path.dirname(f))
            for name, g in _entries(system).items():
                if _plain(g.findtext("name") or "") == want:
                    return system, name
    return "", ""


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
        self._retry = {}
        self._fetched.connect(self._complete, Qt.ConnectionType.QueuedConnection)

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
        if success:
            self.updated.emit()
        self._start()

    @Slot(str, str, str, str, result="QVariant")
    def of(self, system, path, key, title=""):
        steam = re.fullmatch(r"steam/(\d+)", key or "")
        if steam and int(steam.group(1)) < 2 ** 31:   # a game of Steam itself: Steam knows its data
            out = self._steam(steam.group(1))
        else:
            self._pending = None
            if (not path or system == "steam") and title:   # started through a Steam shortcut: find the game in ES-DE by its name
                system, path = find(title)
            out = read(system, path)
        out.update(self._history.info(key) if key else dict(total=0, plays=0, last=0, favorite=False))
        return out
