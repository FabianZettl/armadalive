"""What ES-DE knows about a game (its gamelist entry: description, genre, developer, year, rating) and its pictures, for the game info page."""
import glob, json, os, re, threading, time, urllib.request
import xml.etree.ElementTree as ET
from PySide6.QtCore import QObject, QUrl, Signal, Slot

from . import nowplaying

_cache = {}   # system -> (mtime, {file name: entry})
STEAM_INFO = os.path.expanduser("~/.cache/armadalive/steam-info")   # what Steam's store says about a game, kept for a month
STEAM_API = "https://store.steampowered.com/api/appdetails?appids=%s&l=%s"


def _entries(system):
    f = f"{nowplaying.GAMELISTS}/{system}/gamelist.xml"
    try:
        mtime = os.stat(f).st_mtime
        if _cache.get(system, (0,))[0] != mtime:
            _cache[system] = (mtime, {os.path.basename(g.findtext("path") or ""): g for g in ET.parse(f).getroot().iter("game")})
        return _cache[system][1]
    except (OSError, ET.ParseError):
        return {}


def _pictures(system, base, kind):
    return [QUrl.fromLocalFile(p).toString() for p in sorted(glob.glob(f"{glob.escape(nowplaying.MEDIA)}/{glob.escape(system)}/{kind}/{glob.escape(base)}.*"))]


def read(system, path):
    """{name, desc, genre, developer, year, rating (0..5, or 0), players, cover, shots} for a ROM; fields ES-DE has no entry for stay empty."""
    out = dict(name="", desc="", genre="", developer="", year="", rating=0, players="", cover="", shots=[])
    if not system or not path:
        return out
    base = os.path.splitext(os.path.basename(path))[0]
    g = _entries(system).get(os.path.basename(path))
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
        with urllib.request.urlopen(req, timeout=8) as r:
            entry = json.load(r).get(str(appid)) or {}
        return entry.get("data") if entry.get("success") else None
    except (OSError, ValueError, AttributeError):
        return None


def _steam_fields(data):
    year = re.search(r"\d{4}", (data.get("release_date") or {}).get("date", ""))
    score = (data.get("metacritic") or {}).get("score", 0)
    return dict(name=data.get("name", ""), desc=data.get("short_description", ""), genre=", ".join(g["description"] for g in data.get("genres", [])[:2]),
                developer=", ".join(data.get("developers", [])[:2]), year=year.group(0) if year else "", rating=round(score / 20, 1),
                shots=[s["path_thumbnail"] for s in data.get("screenshots", [])[:3] if s.get("path_thumbnail")])


def steam_read(appid, fetch=None, wait=False):
    """Description, genre, developer, year, rating, screenshots and the local cover of a Steam game. The store entry is cached on disk;
    without one the fields stay empty until it has been fetched (in the background unless `wait`)."""
    out = dict(name="", desc="", genre="", developer="", year="", rating=0, players="", cover="", shots=[])
    art = glob.glob(glob.escape(os.path.expanduser(f"~/.local/share/Steam/appcache/librarycache/{appid}")) + "/**/library_600x900*.jpg", recursive=True) \
        or glob.glob(glob.escape(os.path.expanduser(f"~/.local/share/Steam/appcache/librarycache/{appid}")) + "/library_600x900*.jpg")
    out["cover"] = QUrl.fromLocalFile(art[0]).toString() if art else ""
    path = f"{STEAM_INFO}/{appid}.json"
    try:
        if time.time() - os.stat(path).st_mtime < 30 * 86400:
            return dict(out, **_steam_fields(json.load(open(path))))
    except (OSError, ValueError):
        pass
    return out


class GameInfo(QObject):
    """For the info page: what ES-DE knows about a game, with the play history's numbers for it."""

    updated = Signal()     # a Steam game's store entry arrived

    def __init__(self, history):
        super().__init__()
        self._history = history
        self._asked = set()

    def _steam(self, appid):
        out = steam_read(appid)
        if not out["desc"] and appid not in self._asked:   # not cached yet: ask Steam once per run, in the background
            self._asked.add(appid)
            lang = "german" if os.environ.get("LANG", "").startswith("de") else "english"
            threading.Thread(target=self._fetch, args=(appid, lang), daemon=True).start()
        return out

    def _fetch(self, appid, lang):
        data = _steam_fetch(appid, lang)
        if data:
            os.makedirs(STEAM_INFO, exist_ok=True)
            with open(f"{STEAM_INFO}/{appid}.json", "w") as f:
                json.dump(data, f)
            self.updated.emit()

    @Slot(str, str, str, str, result="QVariant")
    def of(self, system, path, key, title=""):
        steam = re.fullmatch(r"steam/(\d+)", key or "")
        if steam and int(steam.group(1)) < 2 ** 31:   # a game of Steam itself: Steam knows its data
            out = self._steam(steam.group(1))
        else:
            if (not path or system == "steam") and title:   # started through a Steam shortcut: find the game in ES-DE by its name
                system, path = find(title)
            out = read(system, path)
        out.update(self._history.info(key) if key else dict(total=0, plays=0, last=0, favorite=False))
        return out
