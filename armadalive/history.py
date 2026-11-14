"""What was played and for how long: every session of a game (start, length), the totals, and the lists built from them ("recently played", a week of play).

It follows NowPlaying: a game that runs starts a session, anything else ends it. Steam's own play times and ES-DE's `lastplayed` are read once, so the lists are
not empty on the first day. Kept in ~/.config/armadalive/history.json; sessions older than a year are dropped."""
import glob, logging, math, os, re, time
import xml.etree.ElementTree as ET
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from PySide6.QtCore import Property, QCoreApplication, QObject, QTimer, Signal, Slot

from . import persistence

LOG = logging.getLogger(__name__)
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


def _number(value):
    return isinstance(value, int) or isinstance(value, float) and math.isfinite(value)


def _valid_history(saved):
    if not isinstance(saved, dict):
        return False
    games, sessions = saved.get("games", {}), saved.get("sessions", [])
    baseline = saved.get("steam_baseline", {})
    return (isinstance(games, dict) and isinstance(sessions, list)
            and isinstance(baseline, dict)
            and all(isinstance(v, (list, tuple)) and len(v) == 2
                    and all(_number(n) and n >= 0 for n in v) for v in baseline.values())
            and all(isinstance(rec, dict) and all(_number(rec.get(field, 0))
                    for field in ("total", "plays", "last")) for rec in games.values())
            and all(isinstance(s, list) and len(s) == 3 and isinstance(s[0], str)
                    and _number(s[1]) and 0 <= s[1] < 253402214400
                    and _number(s[2]) for s in sessions))


def _steam_baseline(totals):
    # Legacy unfinished imports have no checkpoint. Their overlap with Steam
    # is unknown, so retain the larger known total instead of adding both.
    try:
        steam = _read_steam()
    except (OSError, ValueError) as exc:
        LOG.warning("Could not read Steam play history: %s", exc)
        steam = {}
    return {appid: (last, max(0, seconds - totals.get(f"steam/{appid}", 0)))
            for appid, (last, seconds) in steam.items()}


def _import_history(steam_titles, gamelists, imported, baseline):
    steam = {} if imported else baseline.result()
    titles = steam_titles() if steam_titles is not None else {}
    return titles, steam, [] if imported else _read_esde(gamelists)


class History(QObject):
    changed = Signal()

    def __init__(self, nowplaying, path=None, steam_titles=None, gamelists=None):
        super().__init__()
        self._path = path or CONFIG
        self._np = nowplaying
        self._games, self._sessions, self._open = {}, [], None      # _open: [key, start epoch, seconds counted so far, monotonic of the last count]
        self._titles = {}
        saved = persistence.read_json(self._path, _valid_history, {})
        self._games, self._sessions = saved.get("games", {}), saved.get("sessions", [])
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-save")
        self._write_job = self._pending_save = None
        self._dirty = False
        self._waiting_baseline = False
        self._writes_paused = self._deferred_save = False
        self._write_timer = QTimer(self)
        self._write_timer.setInterval(30)
        self._write_timer.timeout.connect(self._finish_save)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown)
        self._imported = bool(saved.get("imported"))
        self._tracking_ready = self._imported
        cut = time.time() - KEEP_DAYS * 86400
        self._sessions = [s for s in self._sessions if isinstance(s, list) and len(s) == 3 and s[1] >= cut]
        if not self._imported or steam_titles is not None:
            from .nowplaying import GAMELISTS
            worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-import")
            self._baseline_job = Future()
            if self._imported or "steam_baseline" in saved:
                self._baseline_job.set_result(saved.get("steam_baseline", {}))
            else:
                totals = {key: rec.get("total", 0) for key, rec in self._games.items()}
                self._baseline_job = worker.submit(_steam_baseline, totals)
            self._import_job = worker.submit(_import_history, steam_titles, gamelists or GAMELISTS,
                                             self._imported, self._baseline_job)
            worker.shutdown(wait=False)
            self._import_timer = QTimer(self)
            self._import_timer.timeout.connect(self._finish_import)
            self._import_timer.start(30)
        nowplaying.changed.connect(self._seen)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(30000)       # a session in progress is written now and then: a crash or a power cut loses at most half a minute
        self._seen()

    # --- reading what the other programs know ---
    @Slot()
    def _finish_import(self):
        if not self._tracking_ready:
            self._seen()
        if self._waiting_baseline and self._baseline_job.done():
            self._save()
        if not self._import_job.done():
            return
        self._import_timer.stop()
        try:
            self._titles, steam, esde = self._import_job.result()
        except Exception as exc:
            LOG.warning("Could not import play history: %s", exc)
            return
        if not self._imported:
            for appid, (last, seconds) in steam.items():
                title = self._titles.get(f"steam:{appid}")
                if title:  # Installed games and shortcuts only.
                    rec = self._games.setdefault(f"steam/{appid}", dict(title=title, system="steam", path=""))
                    rec["total"] = rec.get("total", 0) + seconds
                    rec["plays"] = rec.get("plays", 0) + 1
                    rec["last"] = max(rec.get("last", 0), last)
            for system, name, when, plays in esde:
                title = os.path.splitext(name)[0]
                rec = self._games.setdefault(f"{system}/{title}", dict(title=title, system=system, path="", total=0, plays=0))
                rec["last"], rec["plays"] = max(rec.get("last", 0), when), max(rec.get("plays", 0), plays)
            self._imported = True
            self._save()
        self.changed.emit()

    def _save(self):
        if self._writes_paused:
            self._deferred_save = True
            return
        self._queue_save()

    def _queue_save(self):
        if not self._imported and not self._baseline_job.done():
            # Never persist live totals without the baseline needed to merge
            # them after an abrupt restart, even while the source read is slow.
            self._waiting_baseline = True
            return
        self._waiting_baseline = False
        self._deferred_save = False
        # The worker exclusively owns its detached snapshot. Keep only the newest
        # unsent snapshot while a durable write is in progress.
        self._pending_save = dict(imported=self._imported, games=deepcopy(self._games),
                                  sessions=deepcopy(self._sessions))
        if not self._imported:
            self._pending_save["steam_baseline"] = self._baseline_job.result()
        if self._write_job is None:
            self._start_save()

    def _start_save(self):
        snapshot, self._pending_save = self._pending_save, None
        self._write_job = self._writer.submit(persistence.write_json, self._path, snapshot,
                                             validate=_valid_history)
        self._write_timer.start()

    @Slot()
    def _finish_save(self):
        if self._write_job is None or not self._write_job.done():
            return
        self._write_timer.stop()
        job, self._write_job = self._write_job, None
        try:
            job.result()
        except Exception as exc:
            self._dirty = True
            LOG.warning("Could not save play history: %s", exc)
        else:
            self._dirty = False
        if self._pending_save is not None:
            self._start_save()

    @Slot()
    def flush(self):
        """Drain pending writes on shutdown, with one retry for an unsaved latest state."""
        if self._waiting_baseline and not self._writes_paused:
            self._baseline_job.result()
            self._save()
        self._drain_saves()
        if self._dirty and not self._writes_paused:
            self._save()
            self._drain_saves()

    def pauseWrites(self):
        """Freeze a backup snapshot; later edits wait for resume or restart."""
        self._count()
        self._save()
        self._writes_paused = True

    def writesPending(self):
        if self._waiting_baseline:
            if not self._baseline_job.done():
                return True
            self._queue_save()
        self._finish_save()
        if self._write_job is not None:
            return True
        if self._dirty:
            raise OSError("Could not save play history before backup")
        return False

    def resumeWrites(self):
        self._writes_paused = False
        if self._deferred_save or self._dirty:
            self._save()

    @Slot()
    def _shutdown(self):
        self.flush()
        self._writer.shutdown()

    def _drain_saves(self):
        while self._write_job is not None:
            # The owner thread handles each result, even after the event loop stops.
            try:
                self._write_job.result()
            except Exception:
                pass
            self._finish_save()

    # --- tracking ---
    def _seen(self):
        if not self._tracking_ready:
            # Steam may update cumulative time during a slow source read. Start
            # local counting after that read, without waiting for title scans.
            if not self._baseline_job.done():
                return
            self._tracking_ready = True
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
        counted = self._open is not None and self._count()
        if counted or self._dirty:
            self._save()
        if counted:
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
            return self._titles.get("steam:" + key[6:], "")
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
