"""A small task manager for the bottom screen: the windows the bottom Plasma session has open, with their memory, to bring forward, close or kill.

KWin has no list a plain D-Bus call can read, so a short KWin script (loaded through KWin's own /Scripting interface, as kdotool does) calls
back with the windows; this app owns that receiving service on the bottom session's private bus."""
import json, os, signal, subprocess, tempfile, threading, time, uuid
from collections import deque
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtDBus import QDBusConnection

from . import shell
from .closer import children, descendants, parents, process_identities, process_table, same_process, signal_processes

SERVICE, PATH = "org.armadalive.Tasks", "/Tasks"
SCRIPT_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "armadalive")
LIST_JS = """(function () {
  var out = [], ws = workspace.windowList();
  for (var i = 0; i < ws.length; i++) { var w = ws[i];
    out.push({ id: String(w.internalId), title: w.caption, app: w.resourceClass, pid: w.pid, normal: w.normalWindow, skip: w.skipTaskbar, min: w.minimized });
  }
  callDBus("%s", "%s", "%s", "report", TOKEN + JSON.stringify(out));
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
        pid = w["pid"]
        if type(pid) is not int or pid < 1:
            continue
        if pid in out:
            out[pid]["windows"] += 1
            out[pid]["minimized"] = out[pid]["minimized"] and bool(w.get("min"))
        else:
            out[pid] = dict(id=str(pid), title=(w.get("title") or w.get("app") or "?").strip(), app=w.get("app", ""), pid=pid, windows=1, minimized=bool(w.get("min")))
    return list(out.values())


def memory_mb(pid, table):
    """What the program and everything it started holds in RAM."""
    return _memory_mb(pid, children(table))


def _memory_mb(pid, index):
    pages = 0
    for process in descendants(pid, index):
        try:
            with open(f"/proc/{process}/statm") as statm:
                pages += int(statm.read().split()[1])
        except (OSError, ValueError, IndexError):
            pass
    return round(pages * os.sysconf("SC_PAGE_SIZE") / 1048576)


def kill_tree(pid, grace=3.0, table=None, expected_start=None):
    """Send signals only to the processes that were selected for termination."""
    if table is None:
        processes = process_table()
        index = children({process: parent for process, (parent, _) in processes.items()})
        identities = {process: processes[process][1] for process in descendants(pid, index) if process in processes}
    else:
        identities = process_identities(descendants(pid, children(table)))
    if expected_start is not None and identities.get(pid) != expected_start:
        return
    if identities.get(pid) is None:
        return

    signal_processes(identities, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(same_process(p, start) for p, start in identities.items()):
        time.sleep(0.2)
    signal_processes(identities, signal.SIGKILL)


def _collect(text):
    processes = process_table()
    index = children({pid: parent for pid, (parent, _) in processes.items()})
    items = parse(text, os.getpid())
    for item in items:
        item["mb"] = _memory_mb(item["pid"], index)
    items.sort(key=lambda item: (item["title"].lower(), item["pid"]))
    starts = {item["id"]: processes[item["pid"]][1] for item in items if item["pid"] in processes}
    return items, starts


class _Receiver(QObject):
    """The only thing exported on the bottom bus: the window list the KWin script reports."""
    got = Signal(str)

    @Slot(str)
    def report(self, text):
        self.got.emit(text)


class Tasks(QObject):
    changed = Signal()
    switched = Signal()    # a window was brought forward: ArmadaLive steps back so it shows
    _finished = Signal(str, object)

    def __init__(self):
        super().__init__()
        self._items, self._starts, self._ok = [], {}, False
        self._conn, self._bus, self._conn_name = None, None, None
        self._pending_cleanup = None
        self._cleanup_after = 0.0
        self._cleanup_delay = 1.0
        self._rx = _Receiver(self)
        self._rx.got.connect(self._report)
        self._finished.connect(self._complete)
        self._active, self._epoch = False, 0
        self._refresh_pending = False
        self._actions = deque()
        self._job, self._report_text = None, None
        self._phase = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._report_timeout = QTimer(self)
        self._report_timeout.setSingleShot(True)
        self._report_timeout.setInterval(1500)
        self._report_timeout.timeout.connect(self._list_failed)
        self._close_refresh = QTimer(self)
        self._close_refresh.setSingleShot(True)
        self._close_refresh.setInterval(1200)
        self._close_refresh.timeout.connect(self._refresh_if_active)

    @Property("QVariant", notify=changed)
    def state(self):
        return dict(items=self._items, ok=self._ok)

    @Slot(bool)
    def setActive(self, on):
        """Only while the page is open the list is refreshed."""
        if on == self._active:
            return
        self._active = on
        self._epoch += 1
        if on:
            self.refresh()
            self._timer.start(2500)
        else:
            self._timer.stop()
            self._close_refresh.stop()
            self._refresh_pending = False
            if self._phase == "report":
                self._end_job()

    def _refresh_if_active(self):
        if self._active:
            self.refresh()

    def _disconnect(self):
        name = self._conn_name
        self._conn, self._bus, self._conn_name = None, None, None
        if name is not None:
            QDBusConnection.disconnectFromBus(name)

    def _connect(self, bus):
        # Only the serialized script worker accesses the connection. Qt delivers
        # exported calls to the receiver on its owner thread.
        if self._conn is not None and self._bus == bus and self._conn.isConnected():
            return True
        self._disconnect()
        name = f"armadalive-bottom-{uuid.uuid4().hex}"
        conn = QDBusConnection.connectToBus(bus, name)
        if conn.isConnected() and conn.registerObject(PATH, SERVICE, self._rx, QDBusConnection.ExportAllSlots) and conn.registerService(SERVICE):
            self._conn, self._bus, self._conn_name = conn, bus, name
            return True
        QDBusConnection.disconnectFromBus(name)
        return False

    def _script_call(self, bus, *args):
        return subprocess.run(["busctl", f"--address={bus}", "call", "org.kde.KWin", *args],
                              capture_output=True, text=True, timeout=5)

    def _unload_script(self, bus, name):
        try:
            result = self._script_call(bus, "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", name)
            if result.returncode != 0:
                return False
            reply = result.stdout.strip()
            if reply == "b true":
                return True
            if reply == "b false":
                # A previous timed-out unload may already have succeeded.
                result = self._script_call(bus, "/Scripting", "org.kde.kwin.Scripting", "isScriptLoaded", "s", name)
                return result.returncode == 0 and result.stdout.strip() == "b false"
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False

    def _bus_gone(self, bus):
        # A dead private bus can leave its socket file behind. Only definitive
        # connection errors prove absence; timeouts and access errors do not.
        name = f"armadalive-cleanup-{uuid.uuid4().hex}"
        conn = QDBusConnection.connectToBus(bus, name)
        try:
            return not conn.isConnected() and conn.lastError().name() in (
                "org.freedesktop.DBus.Error.NoServer",
                "org.freedesktop.DBus.Error.FileNotFound",
            )
        finally:
            QDBusConnection.disconnectFromBus(name)

    def _retry_cleanup(self, bus):
        if self._pending_cleanup is None:
            return True
        previous_bus, script_name = self._pending_cleanup
        if time.monotonic() < self._cleanup_after:
            return False
        if self._unload_script(previous_bus, script_name) or (previous_bus != bus and self._bus_gone(previous_bus)):
            self._pending_cleanup = None
        else:
            self._cleanup_delay = min(30.0, self._cleanup_delay * 2)
            self._cleanup_after = time.monotonic() + self._cleanup_delay
            return False
        self._cleanup_delay = 1.0
        self._cleanup_after = 0.0
        return True

    def _run_script(self, source, name):
        """Return whether execution and cleanup succeeded, independently."""
        bus = self._bus
        if not self._retry_cleanup(bus):
            return False, False

        path = None
        ran, cleaned = False, True
        try:
            os.makedirs(SCRIPT_DIR, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", dir=SCRIPT_DIR, prefix=f"{name}-", suffix=".js", delete=False) as script:
                path = script.name
                script.write(source)
            script_name = f"armadalive-{os.path.basename(path)}"
            try:
                loaded = self._script_call(bus, "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", path, script_name)
                fields = loaded.stdout.split()
                if loaded.returncode == 0 and fields and fields[-1].isdigit():
                    sid = fields[-1]
                    ran = self._script_call(bus, f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run").returncode == 0
            finally:
                cleaned = self._unload_script(bus, script_name)
                if not cleaned:
                    self._pending_cleanup = (bus, script_name)
                    self._cleanup_after = time.monotonic() + self._cleanup_delay
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return ran, cleaned

    def _work(self, phase, work):
        token = self._job[0]
        self._phase = phase

        def run():
            result = None
            try:
                result = work()
            except OSError:
                pass
            finally:
                self._finished.emit(token, result)

        threading.Thread(target=run, daemon=True).start()

    def _start_next(self):
        if self._job is not None:
            return
        if self._actions:
            action, pid, start = self._actions.popleft()
        elif self._refresh_pending:
            self._refresh_pending = False
            action, pid, start = "list", None, None
        else:
            return
        self._job = (uuid.uuid4().hex, self._epoch, action, pid, start)
        if action == "kill":
            self._work("kill", lambda: kill_tree(pid, expected_start=start))
        else:
            token = self._job[0]
            self._work("script", lambda: self._execute_script(token, action, pid, start))

    def _execute_script(self, token, action, pid, start):
        bus = shell.session_bus()
        if not bus:
            self._disconnect()
            return False, False
        if not self._connect(bus):
            shell.invalidate_bus(bus)
            return False, False
        if action == "list":
            source = LIST_JS.replace("TOKEN", json.dumps(token + ":"))
        else:
            if not same_process(pid, start):
                return False, True
            source = ACT_JS % (pid, json.dumps(action))
        ran, cleaned = self._run_script(source, action)
        if not (ran and cleaned):
            shell.invalidate_bus(bus)
            self._disconnect()
        return ran, cleaned

    def _end_job(self):
        self._report_timeout.stop()
        self._job, self._report_text, self._phase = None, None, ""
        self._start_next()

    def _list_failed(self):
        if self._job is None:
            return
        if self._job[1] == self._epoch and self._ok:
            self._ok = False
            self.changed.emit()
        self._end_job()

    @Slot(str, object)
    def _complete(self, token, result):
        if self._job is None or self._job[0] != token:
            return
        _, epoch, action, _, _ = self._job
        if action == "list" and epoch != self._epoch:
            self._end_job()
            return

        if self._phase == "script":
            ran, cleaned = result or (False, False)
            if action == "list":
                if not (ran and cleaned):
                    self._list_failed()
                elif self._report_text is not None:
                    self._collect_report()
                else:
                    self._phase = "report"
                    self._report_timeout.start()
            else:
                if not cleaned and self._ok:
                    self._ok = False
                    self.changed.emit()
                if ran and action == "activate":
                    self.switched.emit()
                if ran and action == "close" and self._active:
                    self._close_refresh.start()
                self._end_job()
        elif self._phase == "collect":
            if result is None:
                self._list_failed()
                return
            items, self._starts = result
            if items != self._items or not self._ok:
                self._items, self._ok = items, True
                self.changed.emit()
            self._end_job()
        elif self._phase == "kill":
            self._refresh_pending |= self._active
            self._end_job()

    @Slot()
    def refresh(self):
        self._refresh_pending = True
        self._start_next()

    @Slot(str)
    def _report(self, text):
        token, _, payload = text.partition(":")
        if self._job is None or self._job[:3] != (token, self._epoch, "list"):
            return
        if self._phase in ("script", "report"):
            self._report_text = payload
            if self._phase == "report":
                self._collect_report()

    def _collect_report(self):
        self._report_timeout.stop()
        text = self._report_text
        self._work("collect", lambda: _collect(text))

    def _enqueue(self, action, wid):
        if wid not in self._starts or len(self._actions) >= 32:
            return
        request = (action, int(wid), self._starts[wid])
        if request not in self._actions and (self._job is None or request != self._job[2:]):
            self._actions.append(request)
            self._start_next()

    @Slot(str)
    def close(self, wid):
        """Ask the window to close, as its own close button does."""
        self._enqueue("close", wid)

    @Slot(str)
    def activate(self, wid):
        self._enqueue("activate", wid)

    @Slot(str)
    def kill(self, wid):
        """End an unresponsive program and everything it started."""
        self._enqueue("kill", wid)
