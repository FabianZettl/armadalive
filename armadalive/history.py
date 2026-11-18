"""What was played and for how long: every session of a game (start, length), the totals, and the lists built from them ("recently played", a week of play).

It follows NowPlaying: a game that runs starts a session, anything else ends it. Steam's own play times and ES-DE's `lastplayed` are read once, so the lists are
not empty on the first day. Kept in ~/.config/armadalive/history.json; sessions older than a year are dropped."""
import glob, logging, os, re, threading, time
import xml.etree.ElementTree as ET
from concurrent.futures import Future, wait
from copy import deepcopy
from datetime import datetime, timedelta
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import persistence

LOG = logging.getLogger(__name__)
CONFIG = os.path.expanduser("~/.config/armadalive/history.json")
MIN_SESSION = 10          # seconds: a game that was started by mistake and closed again is not a play
KEEP_DAYS = 400
STEAM = os.path.expanduser("~/.local/share/Steam")


def _read_steam():
    """{appid: (lastplayed epoch, seconds)} from Steam's localconfig.vdf (its app blocks are flat key-value lists)."""
    out = {}
    userdata = os.path.join(STEAM, "userdata")
    try:
        accounts = os.listdir(userdata)
    except FileNotFoundError:
        return out
    except OSError as error:
        LOG.warning("Could not list Steam accounts in %s: %s", userdata, error)
        return out
    for account in accounts:
        if account.startswith("."):
            continue
        config = os.path.join(userdata, account, "config", "localconfig.vdf")
        try:
            with open(config, errors="replace") as fh:
                text = fh.read()
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as error:
            LOG.warning("Could not read Steam play history at %s: %s", config, error)
            continue
        for appid, body in re.findall(r'"([0-9]+)"\s*\{([^{}]*)\}', text):
            last = re.search(r'"LastPlayed"\s*"([^"]*)"', body)
            mins = re.search(r'"Playtime"\s*"([^"]*)"', body)
            if last is None:
                continue
            stamp, minutes = last[1], mins[1] if mins is not None else "0"
            if not all(value.isascii() and value.isdecimal() for value in (stamp, minutes)):
                continue
            try:
                when, seconds = int(stamp), int(minutes) * 60
            except ValueError:
                continue
            if 0 < when and _number(when) and _number(seconds):
                out[appid] = (when, seconds)
    return out


def _read_esde(gamelists):
    """[(system, file name, lastplayed epoch, playcount)] for every game ES-DE has a `lastplayed` for."""
    out = []
    for f in glob.glob(os.path.join(gamelists, "*", "gamelist.xml")):
        system = os.path.basename(os.path.dirname(f))
        try:
            games = ET.parse(f).getroot().iter("game")
        except (OSError, ET.ParseError, ValueError):
            continue
        for g in games:
            stamp = g.findtext("lastplayed")
            if not stamp:
                continue
            try:
                when = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S").timestamp()
                plays = int(g.findtext("playcount") or 0)
            except (OSError, OverflowError, ValueError):
                continue
            if _number(when) and _number(plays) and plays >= 0:
                out.append((system, os.path.basename(g.findtext("path") or ""), when, plays))
    return out


def _number(value):
    return type(value) in (int, float) and -(2**63) <= value < 2**63


def _valid_game(record):
    return (isinstance(record, dict)
            and all(_number(record.get(field, 0)) for field in ("total", "plays", "last"))
            and all(isinstance(record.get(field, ""), str) for field in ("title", "system", "path", "art"))
            and isinstance(record.get("favorite", False), bool))


def _valid_baseline(baseline):
    return (isinstance(baseline, dict)
            and all(isinstance(appid, str) and appid.isascii() and appid.isdecimal()
                    and isinstance(entry, (tuple, list)) and len(entry) == 2
                    and all(_number(value) and value >= 0 for value in entry)
                    for appid, entry in baseline.items()))


def _valid_history(saved):
    if not isinstance(saved, dict):
        return False
    games, sessions = saved.get("games", {}), saved.get("sessions", [])
    return (isinstance(saved.get("imported", False), bool)
            and _valid_baseline(saved.get("steam_baseline", {}))
            and isinstance(games, dict) and all(_valid_game(record) for record in games.values())
            and isinstance(sessions, list)
            and all(isinstance(row, list) and len(row) == 3 and isinstance(row[0], str)
                    and _number(row[1]) and 0 <= row[1] < 253402214400
                    and _number(row[2]) for row in sessions))


def _steam_baseline(totals):
    steam = _read_steam()
    if not _valid_baseline(steam):
        raise ValueError("invalid Steam play times")
    # An unfinished legacy history has no snapshot. Its overlap with Steam is
    # unknown, so import only the portion above the already recorded total.
    return {appid: (last, max(0, seconds - max(0, totals.get(f"steam/{appid}", 0))))
            for appid, (last, seconds) in steam.items()}


def _write_history(path, snapshot):
    if not _valid_history(snapshot):
        raise ValueError("invalid play history snapshot")
    persistence.write_json(path, snapshot, validate=_valid_history,
                           follow_symlinks=True, require_writable=True)


def _background(task, *args, **kwargs):
    result = Future()

    def run():
        try:
            result.set_result(task(*args, **kwargs))
        except Exception as error:
            result.set_exception(error)

    # Discovery or storage may stay blocked even when the process has to exit.
    threading.Thread(target=run, daemon=True).start()
    return result


class History(QObject):
    changed = Signal()

    def __init__(self, nowplaying, path=None, steam_titles=None, gamelists=None):
        super().__init__()
        self._path = path or CONFIG
        self._np = nowplaying
        self._open = None  # [key, start epoch, seconds counted, last monotonic count]
        self._titles = {}
        saved = persistence.read_json(os.path.realpath(self._path), _valid_history, {})
        self._games = saved.get("games", {})
        cutoff = time.time() - KEEP_DAYS * 86400
        self._sessions = [row for row in saved.get("sessions", []) if row[1] >= cutoff]
        self._imported = saved.get("imported", False)
        self._write_job = self._pending_save = self._failed_save = self._write_error = None
        self._waiting_baseline = None
        self._writes_paused = self._deferred_save = False
        self._write_timer = QTimer(self, interval=30)
        self._write_timer.timeout.connect(self._finish_save)
        self._baseline_job = Future()
        if self._imported or "steam_baseline" in saved:
            self._baseline_job.set_result(saved.get("steam_baseline", {}))
        if not self._imported or steam_titles is not None:
            from .nowplaying import GAMELISTS
            self._start_import(steam_titles, gamelists or GAMELISTS)

        nowplaying.changed.connect(self._seen)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(30000)  # Regular checkpoints for the open session.
        self._seen()

    # --- reading what the other programs know ---
    def _start_import(self, steam_titles, gamelists):
        imported, baseline = self._imported, self._baseline_job
        totals = {key: record.get("total", 0) for key, record in self._games.items()}

        def load_sources():
            if not baseline.done():
                try:
                    baseline.set_result(_steam_baseline(totals))
                except Exception as error:
                    baseline.set_exception(error)
            steam = baseline.result()
            titles = steam_titles() if steam_titles is not None else {}
            return titles, steam, [] if imported else _read_esde(gamelists)

        self._import_job = _background(load_sources)
        self._import_timer = QTimer(self, interval=30)
        self._import_timer.timeout.connect(self._finish_import)
        self._import_timer.start()

    @Slot()
    def _finish_import(self):
        if not self._imported and self._baseline_job.done():
            if self._baseline_job.exception() is None:
                self._seen()
            self._queue_waiting_baseline()
        if not self._import_job.done():
            return
        self._import_timer.stop()
        try:
            self._titles, steam, esde = self._import_job.result()
        except Exception as error:
            source = "play history baseline" if self._baseline_job.exception() is not None else "play history"
            LOG.warning("Could not import %s: %s", source, error)
            return
        if not self._imported:
            for appid, (last, seconds) in steam.items():
                title = self._titles.get(f"steam:{appid}")
                if not title:  # Only installed games and shortcuts are imported.
                    continue
                key = f"steam/{appid}"
                record = self._games.setdefault(key, dict(system="steam", path=""))
                if record.get("title") in (None, "", key):
                    record["title"] = title
                record["total"] = record.get("total", 0) + seconds
                record["plays"] = record.get("plays", 0) + 1
                record["last"] = max(record.get("last", 0), last)
            for system, name, when, plays in esde:
                title = os.path.splitext(name)[0]
                record = self._games.setdefault(f"{system}/{title}", dict(title=title, system=system, path="", total=0, plays=0))
                record["last"] = max(record.get("last", 0), when)
                record["plays"] = max(record.get("plays", 0), plays)
            self._imported = True
            self._save()
        self.changed.emit()

    # --- accepting, writing and draining snapshots ---
    def _save(self):
        if self._writes_paused:
            self._deferred_save = True
            return
        snapshot = dict(imported=self._imported, games=deepcopy(self._games),
                        sessions=deepcopy(self._sessions))
        if self._imported:
            self._queue_snapshot(snapshot)
        else:
            self._waiting_baseline = snapshot
            if self._baseline_job.done():
                self._queue_waiting_baseline()

    def _queue_waiting_baseline(self):
        if self._waiting_baseline is None:
            return
        snapshot, self._waiting_baseline = self._waiting_baseline, None
        # Save local edits after an unexpected baseline failure and retry Steam import next launch.
        if self._baseline_job.exception() is None:
            snapshot["steam_baseline"] = self._baseline_job.result()
        self._queue_snapshot(snapshot)

    def _queue_snapshot(self, snapshot):
        self._failed_save = self._write_error = None
        if self._write_job is not None:
            self._pending_save = snapshot
        else:
            self._start_save(snapshot)

    def _start_save(self, snapshot, *, retry=True):
        self._writing, self._retry_write = snapshot, retry
        self._write_job = _background(_write_history, self._path, snapshot)
        self._write_timer.start()

    @Slot()
    def _finish_save(self):
        if self._write_job is None or not self._write_job.done():
            return
        error = self._write_job.exception()
        snapshot, self._writing = self._writing, None
        self._write_job = None
        if error is not None:
            LOG.warning("Could not save play history to %s: %s", self._path, error)
        if self._pending_save is not None:
            pending, self._pending_save = self._pending_save, None
            self._start_save(pending)
        elif error is not None and self._retry_write:
            self._start_save(snapshot, retry=False)
        else:
            self._write_timer.stop()
            if error is not None:
                self._failed_save = snapshot
                self._write_error = OSError(str(error))
                self._write_error.__cause__ = error

    def _retry_failed_save(self):
        if self._failed_save is not None:
            snapshot, self._failed_save = self._failed_save, None
            self._write_error = None
            self._start_save(snapshot, retry=False)

    def pauseWrites(self, *, restoring=False):
        """Freeze the backup cutoff while accepted snapshots drain."""
        self._count()
        # Materialize the cutoff even if startup recovered it from a .bak file.
        self._save()
        self._writes_paused = True

    def writesPending(self):
        if self._waiting_baseline is not None:
            if not self._baseline_job.done():
                return True
            self._queue_waiting_baseline()
        self._finish_save()
        if self._write_error is not None:
            raise self._write_error
        return self._write_job is not None

    def resumeWrites(self):
        self._writes_paused = False
        if self._deferred_save:
            self._deferred_save = False
            self._save()

    def flush(self, timeout=3.0):
        """Drain snapshots accepted before the freeze within one wait budget."""
        deadline = time.monotonic() + timeout
        if timeout > 0:
            self._retry_failed_save()
        if self._waiting_baseline is not None:
            _, pending = wait((self._baseline_job,), timeout=max(0, deadline - time.monotonic()))
            if pending:
                raise TimeoutError("Timed out preparing play history baseline")
            self._queue_waiting_baseline()
        while self._write_job is not None:
            _, pending = wait((self._write_job,), timeout=max(0, deadline - time.monotonic()))
            if pending:
                raise TimeoutError("Timed out saving play history")
            self._finish_save()
        if self._write_error is not None:
            raise self._write_error

    # --- tracking ---
    def _seen(self):
        s = self._np.state
        if s.get("kind") == "game" and s.get("playing") and s.get("key") and s.get("system") != "":
            if self._open is None or self._open[0] != s["key"]:
                self._end()
                self._begin(s)
            elif not s.get("metadataPending"):
                # The already-open session can receive title and artwork after its start.
                rec = self._games[s["key"]]
                fields = {field: value for field, value in self._presentation(s).items() if value}
                if any(rec.get(field) != value for field, value in fields.items()):
                    rec.update(fields)
                    self._save()
                    self.changed.emit()
        else:
            self._end()

    def _begin(self, s):
        # A Steam play that ends before this read may already be included in
        # Steam's cumulative time. Begin counting after the baseline is known.
        if s["key"].startswith("steam/") and (
            not self._baseline_job.done() or self._baseline_job.exception() is not None
        ):
            return
        rec = self._games.setdefault(s["key"], dict(total=0, plays=0))
        fields = self._presentation(s)
        if s.get("metadataPending"):
            fields = {field: value for field, value in fields.items() if not rec.get(field)}
        rec.update(fields, system=s.get("system", ""), path=s.get("path", ""), last=time.time())
        rec["plays"] = rec.get("plays", 0) + 1
        self._sessions.append([s["key"], int(time.time()), 0])
        self._open = [s["key"], int(time.time()), 0, time.monotonic()]
        self._save()
        self.changed.emit()

    @staticmethod
    def _presentation(state):
        return dict(title=state.get("title") or state["key"], art=state.get("fanart") or state.get("logo") or "")

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
        if self._count():
            self._save()
            self.changed.emit()
        elif not self._writes_paused:
            self._retry_failed_save()

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
        total = (self._games.get(key) or {}).get("total", 0)
        if self._open is not None and self._open[0] == key:
            total += int(time.monotonic() - self._open[3])
        return total

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
