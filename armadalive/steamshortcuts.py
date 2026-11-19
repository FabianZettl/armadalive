"""Prepare ES-DE launch commands and artwork for Steam shortcuts."""
import base64, glob, json, logging, os, re, shlex, struct, threading, time, weakref
from typing import Callable, NamedTuple
from PySide6.QtCore import Property, QBuffer, QIODevice, QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QImage
from shiboken6 import isValid

from .nowplaying import ES, MEDIA
from .steamlib import _vdf_map
from .steamui import eval_js

LOG = ES + "/logs/es_log.txt"
SHORTCUTS = os.path.expanduser("~/.local/share/Steam/userdata/*/config/shortcuts.vdf")
WRAP = "/usr/libexec/armada/armada-game-launch"   # Armada's own game wrapper, as on the other emulator shortcuts
MARK = "Expanded emulator launch command:"
PREPARE_TIMEOUT_MS = 5000
SHORTCUT_READY_MS = 1500
RECENT_SHORTCUT_SECONDS = 5
MAX_RECENT_SHORTCUTS = 32
log = logging.getLogger(__name__)
ADD_JS = """((a) => (async () => {
  const A = SteamClient.Apps;
  const id = await A.AddShortcut(a.name, a.exe, a.start, a.launch);
  if (!Number.isInteger(id) || id === 0) return null;
  await A.SetShortcutName(id, a.name); await A.SetShortcutExe(id, a.exe);
  await A.SetShortcutStartDir(id, a.start); await A.SetShortcutLaunchOptions(id, a.launch);
  for (const [type, data, ext] of a.art) await A.SetCustomArtworkForApp(id, data, ext, type);
  return id;
})())(%s)"""


def launch_command(log, path):
    """The newest launch command in ES-DE's log that starts this ROM, split into words; None if there is none."""
    lines = log.splitlines()
    for i in range(len(lines) - 1, 0, -1):
        if lines[i - 1].endswith(MARK):
            try:
                words = shlex.split(lines[i].partition("Info:")[2])
            except ValueError:
                continue
            if path in words:
                return words
    return None


def shortcut_launches():
    """The launch options of every shortcut Steam knows (its binary shortcuts file is only searched, not parsed)."""
    found = []
    for f in glob.glob(SHORTCUTS):
        try:
            with open(f, "rb") as stream:
                data = stream.read()
        except OSError:
            continue
        found += [x.decode(errors="replace") for x in re.findall(rb"\x01LaunchOptions\x00([^\x00]*)\x00", data)]
    return found


def options_for(words):
    return f"{WRAP} %command% {shlex.join(words[1:])}"


def known_appid(words):
    """The AppId of the shortcut that already runs these words (found by its launch options), else None."""
    tail = shlex.join(words[1:])
    for f in glob.glob(SHORTCUTS):
        try:
            with open(f, "rb") as stream:
                entries = _vdf_map(stream.read())[0].get("shortcuts", {})
        except (OSError, ValueError, struct.error):
            continue
        for e in entries.values():
            if str(e.get("LaunchOptions", "")).endswith(tail) and _valid_appid(e.get("appid")):
                return e["appid"]
    return None


def _valid_appid(value):
    return type(value) is int and -(1 << 31) <= value <= 0xFFFFFFFF and value != 0


def _encode(image, width, height, fmt):
    if image.width() > width or image.height() > height:
        image = image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if image.save(buf, fmt, 88):
        return base64.b64encode(bytes(buf.data())).decode()
    return None


def artwork(system, path):
    """[type, base64, extension] for what ES-DE has: 0 portrait cover, 1 hero, 2 logo, 3 wide image (Steam's asset types)."""
    base = glob.escape(os.path.splitext(os.path.basename(path))[0])
    first = lambda kind: next(iter(sorted(glob.glob(f"{glob.escape(MEDIA)}/{glob.escape(system)}/{kind}/{base}.*"))), "")
    art = []
    for kind, outputs in (
        ("covers", ((0, 600, 900, "JPG", "jpg"),)),
        ("fanart", ((1, 1920, 1080, "JPG", "jpg"), (3, 920, 430, "JPG", "jpg"))),
        ("marquees", ((2, 1024, 512, "PNG", "png"),)),
    ):
        f = first(kind) or (first("screenshots") if kind == "fanart" else "")
        if not f:
            continue
        image = QImage(f)
        if image.isNull():
            continue
        for steam_type, width, height, fmt, ext in outputs:
            if data := _encode(image, width, height, fmt):
                art.append([steam_type, data, ext])
    return art


def _read_log(cached):
    try:
        st = os.stat(LOG)
        if (st.st_mtime_ns, st.st_size) != cached[1:]:
            with open(LOG, "rb") as stream:
                stream.seek(max(0, st.st_size - 2_000_000))  # the newest part is enough
                return stream.read(2_000_000).decode(errors="replace"), st.st_mtime_ns, st.st_size
    except OSError:
        return "", 0, 0
    return cached


def _shortcut_exists(words):
    tail = shlex.join(words[1:])
    return any(lo.endswith(tail) for lo in shortcut_launches())


def _recent_appid(recent, options):
    entry = recent.get(options)
    return entry[0] if entry is not None and time.monotonic() < entry[1] else None


class _Prepared(NamedTuple):
    notice: str = ""
    appid: int | None = None
    script: str = ""
    options: str = ""


def _prepare(action, title, system, path, words, recent):
    if not words:
        return _Prepared(notice="unknown" if action == "add" else "launchUnavailable")
    options = options_for(words)
    appid = _recent_appid(recent, options)
    if action == "add":
        if appid is not None or _shortcut_exists(words):
            return _Prepared(notice="exists")
    else:
        if appid is None:
            appid = known_appid(words)
        if appid is not None:
            return _Prepared(appid=appid)
    payload = dict(name=title, exe=f'"{words[0]}"', start=os.path.dirname(words[0]) + "/",
                   launch=options, art=artwork(system, path))
    return _Prepared(script=ADD_JS % json.dumps(payload), options=options)


class _Request(NamedTuple):
    action: str
    title: str
    is_current: Callable[[], bool]
    deadline: float


class SteamShortcuts(QObject):
    """Owner-thread coordinator shared by every Steam launch and add action.

    One filesystem preparation may be active; busy taps are dropped, never queued.
    A timed-out worker keeps its slot until it returns, then its result is discarded.
    """
    changed = Signal()
    notice = Signal(str, str)   # completion code and the game title
    _prepared = Signal(object)

    def __init__(self, nowplaying=None, parent=None):
        super().__init__(parent)
        self._np = nowplaying
        self._s = dict(possible=False, exists=False)
        self._request = self._preparing = None
        self._log = ("", 0, 0)
        self._recent = {}
        self._game, self._game_generation = None, 0
        self._prepared.connect(self._accept_preparation, Qt.QueuedConnection)
        self._preparation_timer = QTimer(self)
        self._preparation_timer.setSingleShot(True)
        self._preparation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._preparation_timer.timeout.connect(self._prepare_timeout)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        if nowplaying is not None:
            nowplaying.changed.connect(self.refresh)
            timer = QTimer(self)
            timer.timeout.connect(self.refresh)
            timer.start(15000)   # shortcuts may also come and go outside the app
            self.refresh()

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(self._s, busy=self._request is not None or self._preparing is not None)

    def _game_key(self):
        state = self._np.state
        return state.get("kind"), state.get("system"), state.get("path")

    def refresh(self):
        if self._np is None:
            return
        game = self._game_key()
        if game != self._game:
            self._game, self._game_generation = game, self._game_generation + 1
        kind, system, path = game
        words = None
        if kind == "game" and path and system not in (None, "", "steam"):
            self._log = _read_log(self._log)
            words = launch_command(self._log[0], path)
        exists = bool(words and (_recent_appid(self._recent, options_for(words)) is not None
                                 or _shortcut_exists(words)))
        new = dict(possible=bool(words), exists=exists)
        if new != self._s:
            self._s = new
            self.changed.emit()

    @Slot()
    def add(self):
        if self.state["busy"] or self._np is None:
            return
        kind, system, path = self._game_key()
        title = self._np.state.get("title") or os.path.basename(path or "")
        if kind != "game" or not path or system in (None, "", "steam"):
            self.notice.emit("unknown", title)
            return
        generation, cached = self._game_generation, self._log
        self._start("add", title, system, path, lambda: launch_command(_read_log(cached)[0], path),
                    lambda: generation == self._game_generation and self._game_key() == (kind, system, path))

    def launch(self, title, system, path, command, current):
        """Resolve command(system, path) on a worker; check current() on the owner thread."""
        self._start("launch", title, system, path, lambda: command(system, path), current)

    def launch_steam(self, gameid, title, current):
        if self.state["busy"]:
            return
        request = _Request("launch", title, current, time.monotonic() + PREPARE_TIMEOUT_MS / 1000)
        self._request = request
        self.changed.emit()
        self._run_game(request, gameid, request.deadline)

    def _start(self, action, title, system, path, resolve, current):
        if self.state["busy"]:
            return
        request = _Request(action, title, current, time.monotonic() + PREPARE_TIMEOUT_MS / 1000)
        self._request = self._preparing = request
        recent = self._recent.copy()
        owner = weakref.ref(self)
        self.changed.emit()

        def prepare():
            try:
                result = _prepare(action, title, system, path, resolve(), recent)
            except Exception:
                log.exception("Could not prepare Steam %s for %s", action, path)
                result = _Prepared(notice="prepareFailed")
            if (coordinator := owner()) is not None:
                try:
                    coordinator._prepared.emit(result)
                except RuntimeError:
                    pass  # The coordinator was deleted while preparation was running.

        # One request across add, native Steam and emulated launches. Taps never queue.
        self._preparation_timer.start(PREPARE_TIMEOUT_MS)
        threading.Thread(target=prepare, daemon=True).start()

    def _prepare_timeout(self):
        if self._preparing is not None:
            # Leave the slot occupied until the filesystem call returns.
            self._finish(self._preparing, "prepareFailed")

    @Slot(object)
    def _accept_preparation(self, result):
        request = self._preparing  # Only one worker can hold this slot, even after timeout.
        if request is None:
            return
        self._preparation_timer.stop()
        self._preparing = None
        if self._request is not request:
            self.changed.emit()
            return
        if time.monotonic() >= request.deadline:
            self._finish(request, "prepareFailed")
        elif not request.is_current() or result.notice:
            self._finish(request, result.notice)
        elif result.appid is not None:
            self._run(request, result.appid)
        else:
            self._evaluate(request, result.script, lambda value: self._added(request, result.options, value),
                           request.deadline)

    def _evaluate(self, request, script, done, deadline):
        # Check before discovery and again immediately before the socket sends.
        # Deliver confirmed results even after invalidation so _added can cache an
        # already-created shortcut; _finish suppresses obsolete notices.
        def valid():
            return isValid(self) and self._can_dispatch(request)

        def complete(value):
            if isValid(self):
                done(value)

        if time.monotonic() < deadline and valid():
            eval_js(script, complete, deadline=deadline, valid=valid)
        else:
            complete(None)

    def _added(self, request, options, value):
        if self._request is not request:
            return
        if not _valid_appid(value):
            self._finish(request, "unreachable" if request.action == "add" else "launchFailed")
            return
        # Steam updates its shortcuts file later. Cover that gap for both entry points.
        now = time.monotonic()
        self._recent = {key: entry for key, entry in self._recent.items() if entry[1] > now}
        self._recent[options] = value, now + RECENT_SHORTCUT_SECONDS
        if len(self._recent) > MAX_RECENT_SHORTCUTS:
            del self._recent[next(iter(self._recent))]
        if not request.is_current():
            self._finish(request, "")
        elif request.action == "add":
            self._s = dict(possible=True, exists=True)
            self._finish(request, "created")
        else:
            # A newly added shortcut needs a moment before Steam can dispatch it.
            deadline = time.monotonic() + (SHORTCUT_READY_MS + PREPARE_TIMEOUT_MS) / 1000
            QTimer.singleShot(SHORTCUT_READY_MS, self, lambda: self._run(request, value, deadline=deadline))
        if self._np is not None:
            self._refresh_timer.start(2000)

    def _can_dispatch(self, request):
        return self._request is request and request.is_current()

    def _run(self, request, appid, *, deadline=None):
        gameid = ((appid & 0xFFFFFFFF) << 32) | 0x02000000
        self._run_game(request, gameid, request.deadline if deadline is None else deadline)

    def _run_game(self, request, gameid, deadline):
        if not self._can_dispatch(request):
            self._finish(request, "")
            return
        script = f'(async () => (await SteamClient.Apps.RunGame("{gameid}", "", -1, 100)) !== false)()'
        self._evaluate(request, script,
                       lambda value: self._finish(request, "launchRequested" if value is True else "launchFailed"),
                       deadline)

    def _finish(self, request, code):
        if self._request is not request:
            return
        self._preparation_timer.stop()
        self._request = None
        self.changed.emit()
        if code and request.is_current():
            self.notice.emit(code, request.title)
