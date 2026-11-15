"""Start + Select held for two seconds closes the program in front (emulator, ES-DE, Steam game; never Steam itself), with a countdown on the bottom screen."""
import os, signal, time
from collections import defaultdict
from PySide6.QtCore import Property, QObject, QTimer, Signal
from .nowplaying import esde_running, running_game

HOLD = 2.0


def process_table():
    table = {}
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                fields = process_stat(pid)
                table[int(pid)] = (int(fields[1]), int(fields[19]))
            except (OSError, ValueError, IndexError):
                pass
    return table


def parents():
    return {pid: parent for pid, (parent, _) in process_table().items()}


def process_stat(pid):
    # The command name may contain spaces and brackets.
    with open(f"/proc/{pid}/stat") as stat:
        return stat.read().rpartition(")")[2].split()


def children(table):
    index = defaultdict(list)
    for pid, parent in table.items():
        index[parent].append(pid)
    return index


def tree(root, table):
    """Root and everything below it."""
    return descendants(root, children(table))


def descendants(root, index):
    found, seen, todo = [], {root}, [root]
    while todo:
        pid = todo.pop()
        found.append(pid)
        for child in index.get(pid, ()):
            if child not in seen:
                seen.add(child)
                todo.append(child)
    return found


def process_start(pid):
    """Linux /proc start time, in clock ticks since boot."""
    try:
        return int(process_stat(pid)[19])
    except (OSError, ValueError, IndexError):
        return None


def process_identities(pids):
    return {pid: process_start(pid) for pid in pids}


def same_process(pid, start):
    return start is not None and process_start(pid) == start


def signal_processes(identities, sig):
    for pid, start in identities.items():
        if same_process(pid, start):
            try:
                os.kill(pid, sig)
            except OSError:
                pass


def steam_pids(appid):
    """Steam starts a game as `reaper SteamLaunch AppId=<id> -- ...`; that process and its children are the game."""
    table, pids = parents(), []
    index = children(table)
    for pid in table:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as cmdline:
                args = cmdline.read().split(b"\0")
        except OSError:
            continue
        if b"SteamLaunch" in args and f"AppId={appid}".encode() in args:
            pids += descendants(pid, index)
    return pids


def terminate(pids, identities=None):
    if identities is None:
        identities = process_identities(pids)
    signal_processes(identities, signal.SIGTERM)
    QTimer.singleShot(3000, lambda: signal_processes(identities, signal.SIGKILL))


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
                self._identities = process_identities(self._target[0])
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
        terminate(self._target[0], self._identities)
        self._set(phase="closed", progress=1.0)
        QTimer.singleShot(1500, lambda: self._set(phase=""))
