"""A small task manager for the bottom screen: the windows the bottom Plasma session has open, with their memory, to bring forward, close or kill.

KWin has no list a plain D-Bus call can read, so a short KWin script (loaded through KWin's own /Scripting interface, as kdotool does) calls
back with the windows; this app owns that receiving service on the bottom session's private bus."""
import json, os, signal, subprocess, threading, time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtDBus import QDBusConnection

from . import shell
from .closer import parents, tree

SERVICE, PATH = "org.armadalive.Tasks", "/Tasks"
SCRIPT_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "armadalive")
LIST_JS = """(function () {
  var out = [], ws = workspace.windowList();
  for (var i = 0; i < ws.length; i++) { var w = ws[i];
    out.push({ id: String(w.internalId), title: w.caption, app: w.resourceClass, pid: w.pid, normal: w.normalWindow, skip: w.skipTaskbar, min: w.minimized });
  }
  callDBus("%s", "%s", "%s", "report", JSON.stringify(out));
})();
""" % (SERVICE, PATH, SERVICE)
ACT_JS = """(function () {
  var ws = workspace.windowList(), first = null;
  for (var i = 0; i < ws.length; i++) { var w = ws[i];
    if (w.pid !== %s || !w.normalWindow || w.skipTaskbar) continue;
    if (%s === "close") w.closeWindow(); else if (!first) first = w;
  }
  if (first) { first.minimized = false; workspace.activeWindow = first; }
})();
"""


def parse(text, own_pid):
    """The programs worth listing from the script's JSON, one per process: real application windows, never this app's own and never Plasma's panels.
    A program with several windows (a browser) is one entry with the title of its first window."""
    try:
        found = json.loads(text)
    except ValueError:
        return []
    out = {}
    for w in found if isinstance(found, list) else []:
        if not (isinstance(w, dict) and w.get("normal") and not w.get("skip")) or w.get("pid") in (own_pid, 0, None) or w.get("app") == "armadalive":
            continue
        pid = int(w["pid"])
        if pid in out:
            out[pid]["windows"] += 1
            out[pid]["minimized"] = out[pid]["minimized"] and bool(w.get("min"))
        else:
            out[pid] = dict(id=str(pid), title=(w.get("title") or w.get("app") or "?").strip(), app=w.get("app", ""), pid=pid, windows=1, minimized=bool(w.get("min")))
    return list(out.values())


def memory_mb(pid, table):
    """What the program and everything it started holds in RAM (a browser spreads over many processes)."""
    pages = 0
    for p in tree(pid, table):
        try:
            with open(f"/proc/{p}/statm") as f:
                pages += int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            pass
    return round(pages * os.sysconf("SC_PAGE_SIZE") / 1048576)


def kill_tree(pid, grace=3.0, table=None):
    """Ask the program (and its children) to end, and kill what is still there after `grace` seconds."""
    pids = tree(pid, table or parents())
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(os.path.exists(f"/proc/{p}") for p in pids):
        time.sleep(0.2)
    for p in pids:
        if os.path.exists(f"/proc/{p}"):
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass


class _Receiver(QObject):
    """The only thing exported on the bottom bus: the window list the KWin script reports."""
    got = Signal(str)

    @Slot(str)
    def report(self, text):
        self.got.emit(text)


class Tasks(QObject):
    changed = Signal()
    switched = Signal()    # a window was brought forward: ArmadaLive steps back so it shows

    def __init__(self):
        super().__init__()
        self._items, self._ok, self._conn, self._rx, self._busy = [], False, None, _Receiver(self), False
        self._rx.got.connect(self._update)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(items=self._items, ok=self._ok)

    @Slot(bool)
    def setActive(self, on):
        """Only while the page is open the list is refreshed."""
        if on:
            self.refresh()
            self._timer.start(2500)
        else:
            self._timer.stop()

    def _connect(self):
        if self._conn is not None:
            return self._conn.isConnected()
        bus = shell._find_bus()
        if not bus:
            return False
        conn = QDBusConnection.connectToBus(bus, "armadalive-bottom")
        if conn.isConnected() and conn.registerService(SERVICE) and conn.registerObject(PATH, SERVICE, self._rx, QDBusConnection.ExportAllSlots):
            self._conn, self._bus = conn, bus
            return True
        return False

    def _run_script(self, source, name):
        """Loads a one-shot script into the bottom session's KWin, runs it and unloads it (on a worker thread)."""
        os.makedirs(SCRIPT_DIR, exist_ok=True)
        path = os.path.join(SCRIPT_DIR, f"{name}.js")
        with open(path, "w") as f:
            f.write(source)

        def call(*args):
            return subprocess.run(["busctl", f"--address={self._bus}", "call", "org.kde.KWin", *args], capture_output=True, text=True, timeout=5)
        try:
            loaded = call("/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", path, f"armadalive-{name}")
            sid = loaded.stdout.split()[-1] if loaded.returncode == 0 and loaded.stdout.split() else ""
            if sid.lstrip("-").isdigit() and int(sid) >= 0:
                call(f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")
            call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", f"armadalive-{name}")
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _in_background(self, source, name):
        if not self._connect():
            if self._ok:
                self._ok = False
                self.changed.emit()
            return
        threading.Thread(target=self._run_script, args=(source, name), daemon=True).start()

    @Slot()
    def refresh(self):
        self._in_background(LIST_JS, "list")

    def _update(self, text):
        table = parents()
        items = parse(text, os.getpid())
        for it in items:
            it["mb"] = memory_mb(it["pid"], table)
        items.sort(key=lambda i: (i["title"].lower(), i["pid"]))
        if items != self._items or not self._ok:
            self._items, self._ok = items, True
            self.changed.emit()

    @Slot(str)
    def close(self, wid):
        """Asks the window to close, as its own close button does."""
        if wid in {i["id"] for i in self._items}:
            self._in_background(ACT_JS % (int(wid), json.dumps("close")), "act")
            QTimer.singleShot(1200, self.refresh)

    @Slot(str)
    def activate(self, wid):
        if wid in {i["id"] for i in self._items}:
            self._in_background(ACT_JS % (int(wid), json.dumps("activate")), "act")
            self.switched.emit()

    @Slot(str)
    def kill(self, wid):
        """For a program that does not close: end it and everything it started (SIGTERM, then SIGKILL after three seconds)."""
        for it in self._items:
            if it["id"] == wid:
                threading.Thread(target=kill_tree, args=(it["pid"],), daemon=True).start()
                QTimer.singleShot(4500, self.refresh)
