"""What was played and for how long: every session of a game (start, length), the totals, and the lists built from them ("recently played", a week of play).

It follows NowPlaying: a game that runs starts a session, anything else ends it. Steam's own play times and ES-DE's `lastplayed` are read once, so the lists are
not empty on the first day. Kept in ~/.config/armadalive/history.json; sessions older than a year are dropped."""
import glob, json, os, re, time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

CONFIG = os.path.expanduser("~/.config/armadalive/history.json")
MIN_SESSION = 10          # seconds: a game that was started by mistake and closed again is not a play
KEEP_DAYS = 400
STEAM = os.path.expanduser("~/.local/share/Steam")


def _read_steam():
    """{appid: (lastplayed epoch, seconds)} from Steam's localconfig.vdf (its app blocks are flat key-value lists)."""
    out = {}
    for f in glob.glob(os.path.join(STEAM, "userdata", "*", "config", "localconfig.vdf")):
        try:
            with open(f, errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for appid, body in re.findall(r'"(\d+)"\s*\{([^{}]*)\}', text):
            last, mins = re.search(r'"LastPlayed"\s*"(\d+)"', body), re.search(r'"Playtime"\s*"(\d+)"', body)
            if last and int(last.group(1)) > 0:
                out[appid] = (int(last.group(1)), int(mins.group(1)) * 60 if mins else 0)
    return out


def _read_esde(gamelists):
    """[(system, file name, lastplayed epoch, playcount)] for every game ES-DE has a `lastplayed` for."""
    out = []
    for f in glob.glob(os.path.join(gamelists, "*", "gamelist.xml")):
        system = os.path.basename(os.path.dirname(f))
        try:
            for g in ET.parse(f).getroot().iter("game"):
                stamp = g.findtext("lastplayed") or ""
                if stamp:
                    when = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S").timestamp()
                    out.append((system, os.path.basename(g.findtext("path") or ""), when, int(g.findtext("playcount") or 0)))
        except (OSError, ET.ParseError, ValueError):
            continue
    return out


class History(QObject):
    changed = Signal()

    def __init__(self, nowplaying, path=None, steam_titles=None, gamelists=None):
        super().__init__()
        self._path = path or CONFIG
        self._np = nowplaying
        self._games, self._sessions, self._open = {}, [], None      # _open: [key, start epoch, seconds counted so far, monotonic of the last count]
        self._steam_titles = steam_titles or (lambda: {})
        try:
            with open(self._path) as f:
                saved = json.load(f)
            self._games, self._sessions = dict(saved.get("games", {})), list(saved.get("sessions", []))
            imported = bool(saved.get("imported"))
        except (OSError, ValueError, AttributeError):
            imported = False
        cut = time.time() - KEEP_DAYS * 86400
        self._sessions = [s for s in self._sessions if isinstance(s, list) and len(s) == 3 and s[1] >= cut]
        if not imported:
            self._import(gamelists)
            self._save(imported=True)
        nowplaying.changed.connect(self._seen)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(30000)       # a session in progress is written now and then: a crash or a power cut loses at most half a minute
        self._seen()

    # --- reading what the other programs know ---
    def _import(self, gamelists):
        titles = self._steam_titles()
        for appid, (last, seconds) in _read_steam().items():
            key = f"steam/{appid}"
            if f"steam:{appid}" in titles:      # installed games and shortcuts only: the account has hundreds of owned ones
                self._games[key] = dict(title=titles[f"steam:{appid}"], system="steam", path="", total=seconds, plays=1, last=last)
        from .nowplaying import GAMELISTS
        for system, name, when, plays in _read_esde(gamelists or GAMELISTS):
            key = f"{system}/{os.path.splitext(name)[0]}"
            rec = self._games.setdefault(key, dict(title=os.path.splitext(name)[0], system=system, path="", total=0, plays=0))
            rec["last"], rec["plays"] = max(rec.get("last", 0), when), max(rec.get("plays", 0), plays)

    def _save(self, imported=True):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(dict(imported=imported, games=self._games, sessions=self._sessions), f)

    # --- tracking ---
    def _seen(self):
        s = self._np.state
        if s.get("kind") == "game" and s.get("playing") and s.get("key") and s.get("system") != "":
            if self._open is None or self._open[0] != s["key"]:
                self._end()
                self._begin(s)
        else:
            self._end()

    def _begin(self, s):
        rec = self._games.setdefault(s["key"], dict(total=0, plays=0))
        rec.update(title=s.get("title") or s["key"], system=s.get("system", ""), path=s.get("path", ""), art=s.get("fanart") or s.get("logo") or "", last=time.time())
        rec["plays"] = rec.get("plays", 0) + 1
        self._sessions.append([s["key"], int(time.time()), 0])
        self._open = [s["key"], int(time.time()), 0, time.monotonic()]
        self._save()
        self.changed.emit()

    def _count(self):
        """Adds what has passed since the last count to the open session and the game's total."""
        if self._open is None:
            return 0
        now = time.monotonic()
        add = int(now - self._open[3])
        self._open[2] += add
        self._open[3] += add
        self._sessions[-1][2] = self._open[2]
        self._games[self._open[0]]["total"] = self._games[self._open[0]].get("total", 0) + add
        self._games[self._open[0]]["last"] = time.time()
        return add

    def _tick(self):
        if self._open is not None and self._count():
            self._save()
            self.changed.emit()

    def _end(self):
        if self._open is None:
            return
        self._count()
        key, secs = self._open[0], self._open[2]
        if secs < MIN_SESSION:            # not a real play: take it back
            self._sessions.pop()
            rec = self._games[key]
            rec["total"] = max(0, rec.get("total", 0) - secs)
            rec["plays"] = max(0, rec.get("plays", 1) - 1)
        self._open = None
        self._save()
        self.changed.emit()

    # --- what the pages ask for ---
    @Property("QVariant", notify=changed)
    def games(self):
        return self._games

    def recent(self, limit=12):
        """[(key, record)], the most recently played first."""
        items = [(k, r) for k, r in self._games.items() if r.get("last")]
        return sorted(items, key=lambda kr: kr[1]["last"], reverse=True)[:limit]

    def title_of(self, key):
        """The name of a game key such as "steam/1145360" or "snes/Chrono Trigger", or "" if nobody knows it."""
        t = (self._games.get(key) or {}).get("title")
        if t and t != key:
            return t
        if key.startswith("steam/"):
            return self._steam_titles().get("steam:" + key[6:], "")
        return key.split("/", 1)[1] if "/" in key else ""

    def total_for(self, key):
        """Seconds played of one game, counting the session in progress."""
        if self._open is not None and self._open[0] == key:
            self._count()
        return (self._games.get(key) or {}).get("total", 0)

    def info(self, key):
        r = self._games.get(key) or {}
        return dict(total=r.get("total", 0), plays=r.get("plays", 0), last=r.get("last", 0), favorite=bool(r.get("favorite")))

    def favorites(self):
        """[(key, record)] of the games marked as favorite."""
        return [(k, r) for k, r in self._games.items() if r.get("favorite")]

    @Slot(str, str, str, str)
    def toggleFavorite(self, key, title, system, path):
        """Heart or un-heart a game; a game never played gets a record without a play time or a last-played date."""
        if not key:
            return
        rec = self._games.setdefault(key, dict(title=title or key, system=system, path=path, total=0, plays=0))
        rec["favorite"] = not rec.get("favorite")
        self._save()
        self.changed.emit()

    @Slot(int, result="QVariant")
    def week(self, days=7):
        """[{day: "Mon", date: "2026-11-12", seconds}] for the last `days` days, today last."""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        out = {(today - timedelta(days=i)).strftime("%Y-%m-%d"): 0 for i in range(days)}
        for key, start, secs in self._sessions:
            day = datetime.fromtimestamp(start).strftime("%Y-%m-%d")
            if day in out:
                out[day] += secs
        return [dict(day=datetime.strptime(d, "%Y-%m-%d").strftime("%a"), date=d, seconds=s) for d, s in sorted(out.items())]

    @Slot(int, int, result="QVariant")
    def top(self, days=7, limit=5):
        """[{key, title, seconds}] the most played games of the last `days` days."""
        since = time.time() - days * 86400
        sums = {}
        for key, start, secs in self._sessions:
            if start >= since:
                sums[key] = sums.get(key, 0) + secs
        ranked = sorted(sums.items(), key=lambda ks: ks[1], reverse=True)[:limit]
        return [dict(key=k, title=self.title_of(k) or k, seconds=s) for k, s in ranked]

    @Slot(int, result=int)
    def totalSeconds(self, days=7):
        since = time.time() - days * 86400
        return sum(secs for _, start, secs in self._sessions if start >= since)
