"""What was played and for how long: every session of a game (start, length), the totals, and the lists built from them ("recently played", a week of play).

It follows NowPlaying: a game that runs starts a session, anything else ends it. Steam's own play times and ES-DE's `lastplayed` are read once, so the lists are
not empty on the first day. Kept in ~/.config/armadalive/history.json; sessions older than a year are dropped."""
import glob, json, os, re, time
from datetime import datetime, timedelta
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import nowplaying as esde
from .poller import Poller


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
    """Canonical game identity and play counts from ES-DE's dated gamelist entries."""
    root, definitions = esde._rom_configuration()
    out = []
    for f in glob.glob(glob.escape(gamelists) + "/*/gamelist.xml"):
        system = os.path.basename(os.path.dirname(f))
        folder = esde._system_folder(system, root, definitions.get(system))
        entries, _ = esde._gamelist(system, folder, gamelists)
        for relative, game in entries.items():
            stamp = game.findtext("lastplayed") or ""
            if not stamp:
                continue
            try:
                when = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S").timestamp()
                plays = int(game.findtext("playcount") or 0)
            except ValueError:
                continue
            title = game.findtext("name") or os.path.splitext(os.path.basename(relative))[0]
            out.append((esde.rom_key(system, relative), title, system, os.path.join(folder, relative), when, plays))
    return out


class History(QObject):
    changed = Signal()

    def __init__(self, nowplaying, path=None, steam_titles=None, gamelists=None):
        super().__init__()
        self._path = path or CONFIG
        self._np = nowplaying
        self._games, self._sessions, self._open = {}, [], None      # _open: [key, start epoch, seconds counted so far, monotonic of the last count]
        self._steam_titles = steam_titles or (lambda: {})
        self._legacy_scan = None
        self._file_version = self._version()
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
        legacy_keys = tuple(key for key in self._games if esde.legacy_key_parts(key))
        if legacy_keys:
            source = gamelists or esde.GAMELISTS
            self._legacy_scan = Poller(self, lambda: esde.resolve_legacy_keys(legacy_keys, source), self._legacy_ready, 2000)

    # --- reading what the other programs know ---
    def _import(self, gamelists):
        titles = self._steam_titles()
        for appid, (last, seconds) in _read_steam().items():
            key = f"steam/{appid}"
            if f"steam:{appid}" in titles:      # installed games and shortcuts only: the account has hundreds of owned ones
                self._games[key] = dict(title=titles[f"steam:{appid}"], system="steam", path="", total=seconds, plays=1, last=last)
        for key, title, system, path, when, plays in _read_esde(gamelists or esde.GAMELISTS):
            rec = self._games.setdefault(key, dict(title=title, system=system, path=path, total=0, plays=0))
            rec["last"], rec["plays"] = max(rec.get("last", 0), when), max(rec.get("plays", 0), plays)

    def _version(self):
        try:
            info = os.stat(self._path)
            return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size
        except OSError:
            return None

    def _legacy_ready(self, aliases):
        scan, self._legacy_scan = self._legacy_scan, None
        scan.deleteLater()
        self._use_legacy_proof(aliases)

    def _use_legacy_proof(self, aliases):
        # A backup restore can replace history while this proof is pending.
        # Leave the restored data in place for the new application instance.
        if self._file_version == self._version() and self._migrate_legacy(aliases):
            self._save()
            self.changed.emit()

    def _migrate_legacy(self, aliases):
        migrated = {}
        for legacy, (key, path) in aliases.items():
            old = self._games.get(legacy)
            if old is None:
                continue
            old_path = old.get("path")
            system, _, relative = key.removeprefix("esde:").partition("/")
            folder = path[:-len(relative)].rstrip("/") or "/"
            if old_path and (not isinstance(old_path, str) or esde.rom_relative(system, old_path, folder) != relative):
                continue  # a previous location disagrees with the only candidate still present
            current = self._games.get(key, {})
            self._games[key] = dict(old, **current)
            self._games[key].update(system=system, path=path, total=old.get("total", 0) + current.get("total", 0),
                                    plays=old.get("plays", 0) + current.get("plays", 0),
                                    last=max(old.get("last", 0), current.get("last", 0)))
            del self._games[legacy]
            migrated[legacy] = key
        if migrated:
            for session in self._sessions:
                session[0] = migrated.get(session[0], session[0])
            if self._open is not None:
                self._open[0] = migrated.get(self._open[0], self._open[0])
        return bool(migrated)

    def _save(self, imported=True):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(dict(imported=imported, games=self._games, sessions=self._sessions), f)
        self._file_version = self._version()

    # --- tracking ---
    def _seen(self):
        s = self._np.state
        if s.get("legacyKey") in self._games and s.get("romPath"):
            self._use_legacy_proof({s["legacyKey"]: (s["key"], s["romPath"])})
        if s.get("kind") == "game" and s.get("playing") and s.get("key") and s.get("system") != "":
            if self._open is None or self._open[0] != s["key"]:
                self._end()
                self._begin(s)
            elif not s.get("metadataPending"):
                rec = self._games[s["key"]]
                fields = {field: value for field, value in self._game_details(s).items() if value}
                if any(rec.get(field) != value for field, value in fields.items()) and self._file_version == self._version():
                    rec.update(fields)
                    self._save()
                    self.changed.emit()
        else:
            self._end()

    def _begin(self, s):
        rec = self._games.setdefault(s["key"], dict(total=0, plays=0))
        details = self._game_details(s)
        if s.get("metadataPending"):
            # Keep already known metadata until the authoritative result arrives.
            details = {field: value for field, value in details.items() if not rec.get(field)}
        rec.update(details, last=time.time())
        rec["plays"] = rec.get("plays", 0) + 1
        self._sessions.append([s["key"], int(time.time()), 0])
        self._open = [s["key"], int(time.time()), 0, time.monotonic()]
        self._save()
        self.changed.emit()

    @staticmethod
    def _game_details(s):
        return dict(title=s.get("title") or s["key"], system=s.get("system", ""), path=s.get("romPath") or s.get("path", ""),
                    art=s.get("fanart") or s.get("logo") or "")

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
        items = [(k, self._launch_record(k, r)) for k, r in self._games.items() if r.get("last")]
        return sorted(items, key=lambda kr: kr[1]["last"], reverse=True)[:limit]

    def title_of(self, key):
        """The name of a game key such as "steam/1145360" or "snes/Chrono Trigger", or "" if nobody knows it."""
        t = (self._games.get(key) or {}).get("title")
        if t and t != key:
            return t
        if key.startswith("steam/"):
            return self._steam_titles().get("steam:" + key[6:], "")
        if key.startswith("esde:"):
            return os.path.splitext(os.path.basename(key))[0]
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
        return [(k, self._launch_record(k, r)) for k, r in self._games.items() if r.get("favorite")]

    @staticmethod
    def _launch_record(key, record):
        # Legacy records might contain the last sibling played, not the game
        # that earned the favorite or accumulated the earlier play time.
        return dict(record, path="") if esde.legacy_key_parts(key) else record

    @Slot(str, str, str, str)
    def toggleFavorite(self, key, title, system, path):
        """Heart or un-heart a game; a game never played gets a record without a play time or a last-played date."""
        if not key:
            return
        if self._np.state.get("key") == key:
            path = self._np.state.get("romPath") or path
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
