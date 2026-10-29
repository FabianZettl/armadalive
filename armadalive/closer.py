"""Start + Select held for two seconds closes the program in front (emulator, ES-DE, Steam game; never Steam itself), with a countdown on the bottom screen."""
import os, signal, time
from PySide6.QtCore import Property, QObject, QTimer, Signal
from .nowplaying import esde_running, running_game

HOLD = 2.0


def parents():
    table = {}
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:   # the command name may hold spaces and brackets: the fields start after its closing bracket
                table[int(pid)] = int(open(f"/proc/{pid}/stat").read().rpartition(")")[2].split()[1])
            except (OSError, ValueError, IndexError):
                pass
    return table


def tree(root, table):
    """root and everything below it."""
    found, todo = [], [root]
    while todo:
        pid = todo.pop()
        found.append(pid)
        todo += [p for p, parent in table.items() if parent == pid and p not in found]
    return found


def steam_pids(appid):
    """Steam starts a game as `reaper SteamLaunch AppId=<id> -- ...`; that process and its children are the game."""
    table, pids = parents(), []
    for pid in table:
        try:
            args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        if b"SteamLaunch" in args and f"AppId={appid}".encode() in args:
            pids += tree(pid, table)
    return pids


def terminate(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    def force():   # whatever ignored the polite request
        for pid in pids:
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    QTimer.singleShot(3000, force)


class Closer(QObject):
    changed = Signal()
    begun = Signal()   # a countdown started: the window comes to the front so it can be seen

    def __init__(self, pad, gamescope, nowplaying, ui):
        super().__init__()
        self._gs, self._np, self._ui = gamescope, nowplaying, ui
        self._s, self._target, self._since = dict(phase="", title="", progress=0.0), None, 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(50)
        self._tick.timeout.connect(self._step)
        pad.combo.connect(self._combo)

    @Property("QVariant", notify=changed)
    def state(self):
        return self._s

    def target(self):
        """(pids, title) of what is in front: a running emulator, else whatever Steam started (a game, or ES-DE as a shortcut).
        Steam's own UI (focus 769) is never a target."""
        title = self._np.state.get("title", "")
        game = running_game()
        if game:
            return [game["pid"]], title or game["name"]
        app = self._gs.state.get("focus", "")
        if app.isdigit() and int(app) > 0 and app != "769":
            pids = steam_pids(app)
            if pids:
                shortcut = int(app) >= 2**31   # a non-Steam shortcut: ES-DE, whose own title is just the game it shows
                return pids, "ES-DE" if shortcut and esde_running() else title
        return None

    def _set(self, **kw):
        self._s = {**self._s, **kw}
        self.changed.emit()

    def _combo(self, on):
        if on and self._s["phase"] == "" and self._ui.state.get("close", True):
            self._target = self.target()
            if self._target:
                self._since = time.monotonic()
                self._set(phase="holding", title=self._target[1], progress=0.0)
                self._tick.start()
                self.begun.emit()
        elif not on and self._s["phase"] == "holding":
            self._tick.stop()
            self._set(phase="")

    def _step(self):
        progress = (time.monotonic() - self._since) / HOLD
        if progress < 1:
            self._set(progress=progress)
            return
        self._tick.stop()
        terminate(self._target[0])
        self._set(phase="closed", progress=1.0)
        QTimer.singleShot(1500, lambda: self._set(phase=""))
