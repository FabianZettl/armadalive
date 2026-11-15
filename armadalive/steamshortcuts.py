"""Prepare ES-DE launch commands and artwork for Steam shortcuts."""
import base64, glob, json, logging, os, re, shlex, struct, threading, time
from math import ceil
from typing import Callable, NamedTuple
from PySide6.QtCore import Property, QBuffer, QIODevice, QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QImage

from .nowplaying import ES, MEDIA
from .steamlib import _vdf_map
from .steamui import eval_js

LOG = ES + "/logs/es_log.txt"
SHORTCUTS = os.path.expanduser("~/.local/share/Steam/userdata/*/config/shortcuts.vdf")
WRAP = "/usr/libexec/armada/armada-game-launch"   # Armada's own game wrapper, as on the other emulator shortcuts
MARK = "Expanded emulator launch command:"
PREPARE_TIMEOUT_MS = 5000
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
            with open(LOG, errors="replace") as stream:
                stream.seek(max(0, st.st_size - 2_000_000))  # the newest part is enough
                return stream.read(), st.st_mtime_ns, st.st_size
    except OSError:
        return "", 0, 0
    return cached


def _shortcut_exists(words):
    tail = shlex.join(words[1:])
    return any(lo.endswith(tail) for lo in shortcut_launches())


class _Prepared(NamedTuple):
    notice: str = ""
    appid: int | None = None
    script: str = ""
    options: str = ""


def _prepare(action, title, system, path, words, recent):
    if not words:
        return _Prepared(notice="unknown" if action == "add" else "launchUnavailable")
    options = options_for(words)
    recent_options, recent_id, expires = recent
    appid = recent_id if options == recent_options and time.monotonic() < expires else None
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
    deadline: float = 0.0
    esde_game: tuple[str, str] | None = None


class _RuleWait(NamedTuple):
    request: _Request
    dispatch: Callable[[], None]
    deadline: float


class SteamShortcuts(QObject):
    changed = Signal()
    notice = Signal(str, str)   # completion code and either the title or a blocking rule error
    _prepared = Signal(object, object)

    def __init__(self, nowplaying=None, parent=None, *, prepare_esde_launch=None):
        super().__init__(parent)
        self._np = nowplaying
        self._prepare_esde_launch = prepare_esde_launch
        self._waiting_rule = None
        self._s = dict(possible=False, exists=False)
        self._request = self._preparing = None
        self._log = ("", 0, 0)
        self._recent = ("", None, 0)
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
        options, _, expires = self._recent
        exists = bool(words and ((options_for(words) == options and time.monotonic() < expires)
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
        self._start("launch", title, system, path, lambda: command(system, path), current)

    def launch_steam(self, gameid, title, current):
        if self.state["busy"]:
            return
        request = _Request("launch", title, current)
        self._request = request
        self.changed.emit()
        self._run_game(request, gameid)

    def _start(self, action, title, system, path, resolve, current):
        if self.state["busy"]:
            return
        request = _Request(action, title, current, time.monotonic() + PREPARE_TIMEOUT_MS / 1000,
                           (system, path) if action == "launch" else None)
        self._request = self._preparing = request
        recent = self._recent
        self.changed.emit()

        def prepare():
            try:
                result = _prepare(action, title, system, path, resolve(), recent)
            except Exception:
                log.exception("Could not prepare Steam %s for %s", action, path)
                result = _Prepared(notice="prepareFailed")
            self._prepared.emit(request, result)

        # One request across both entry points. New taps cannot enqueue work.
        self._preparation_timer.start(PREPARE_TIMEOUT_MS)
        threading.Thread(target=prepare, daemon=True).start()

    def _prepare_timeout(self):
        if self._preparing is not None:
            # Leave the slot occupied until the filesystem call returns.
            self._finish(self._preparing, "prepareFailed")
        elif self._waiting_rule is not None:
            self._finish(self._waiting_rule.request, "prepareFailed")

    @Slot(object, object)
    def _accept_preparation(self, request, result):
        if self._preparing is not request:
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

    def _rule_result(self, request):
        try:
            system, path = request.esde_game
            return self._prepare_esde_launch(system, path, request.title)
        except Exception:
            log.exception("Could not prepare game rules for %s", request.title)
            return "Could not prepare game rules"

    def _wait_for_rule(self, request, dispatch, deadline):
        remaining = deadline - time.monotonic()
        if not self._can_dispatch(request):
            self._finish(request, "")
        elif remaining <= 0:
            self._finish(request, "prepareFailed")
        else:
            self._waiting_rule = _RuleWait(request, dispatch, deadline)
            self._preparation_timer.start(ceil(remaining * 1000))

    @Slot()
    def resume_esde_launch(self):
        pending, self._waiting_rule = self._waiting_rule, None
        if pending is None:
            return
        request = pending.request
        if not self._can_dispatch(request):
            self._finish(request, "")
        elif time.monotonic() >= pending.deadline:
            self._finish(request, "prepareFailed")
        else:
            problem = self._rule_result(request)
            if problem is None:
                self._wait_for_rule(*pending)
            elif problem:
                self._finish(request, "launchBlocked", problem)
            elif time.monotonic() >= pending.deadline:
                self._finish(request, "prepareFailed")
            elif self._can_dispatch(request):
                self._preparation_timer.stop()
                pending.dispatch()
            else:
                self._finish(request, "")

    def _evaluate(self, request, script, done, deadline):
        if self._prepare_esde_launch is None or request.esde_game is None:
            eval_js(script, done, valid=lambda: self._can_dispatch(request))
            return

        def dispatch():
            problem = ""

            def valid():
                nonlocal problem
                if not self._can_dispatch(request):
                    return False
                # Rule state can change while Steam discovers and connects its socket.
                problem = self._rule_result(request)
                return problem == "" and self._can_dispatch(request)

            def finished(value):
                if not self._can_dispatch(request):
                    self._finish(request, "")
                elif problem is None:
                    self._wait_for_rule(request, dispatch, deadline)
                elif problem:
                    self._finish(request, "launchBlocked", problem)
                else:
                    done(value)

            eval_js(script, finished, valid=valid)

        self._wait_for_rule(request, dispatch, deadline)
        self.resume_esde_launch()

    def _added(self, request, options, value):
        if self._request is not request:
            return
        if not _valid_appid(value):
            self._finish(request, "unreachable" if request.action == "add" else "launchFailed")
            return
        # Steam updates its shortcuts file later. Cover that gap for both entry points.
        self._recent = (options, value, time.monotonic() + 5)
        if not request.is_current():
            self._finish(request, "")
        elif request.action == "add":
            self._s = dict(possible=True, exists=True)
            self._finish(request, "created")
        else:
            # A newly added shortcut needs a moment before Steam can dispatch it.
            QTimer.singleShot(1500, self, lambda: self._run(request, value, after_create=True))
        if self._np is not None:
            self._refresh_timer.start(2000)

    def _can_dispatch(self, request):
        return self._request is request and request.is_current()

    def _run(self, request, appid, *, after_create=False):
        gameid = ((appid & 0xFFFFFFFF) << 32) | 0x02000000
        deadline = time.monotonic() + PREPARE_TIMEOUT_MS / 1000 if after_create else request.deadline
        self._run_game(request, gameid, deadline)

    def _run_game(self, request, gameid, deadline=0.0):
        if not self._can_dispatch(request):
            self._finish(request, "")
            return
        script = f'(async () => (await SteamClient.Apps.RunGame("{gameid}", "", -1, 100)) !== false)()'
        self._evaluate(request, script,
                       lambda value: self._finish(request, "launchRequested" if value is True else "launchFailed"),
                       deadline)

    def _finish(self, request, code, detail=None):
        if self._request is not request:
            return
        self._preparation_timer.stop()
        self._request = self._waiting_rule = None
        self.changed.emit()
        if code and request.is_current():
            self.notice.emit(code, request.title if detail is None else detail)
