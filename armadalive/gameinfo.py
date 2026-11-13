"""What ES-DE knows about a game (its gamelist entry: description, genre, developer, year, rating) and its pictures, for the game info page."""
import glob, os
import xml.etree.ElementTree as ET
from PySide6.QtCore import QObject, QUrl, Slot

from . import nowplaying

_cache = {}   # system -> (mtime, {file name: entry})


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


class GameInfo(QObject):
    """For the info page: what ES-DE knows about a game, with the play history's numbers for it."""

    def __init__(self, history):
        super().__init__()
        self._history = history

    @Slot(str, str, str, result="QVariant")
    def of(self, system, path, key):
        out = read(system, path)
        out.update(self._history.info(key) if key else dict(total=0, plays=0, last=0, favorite=False))
        return out
