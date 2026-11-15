import json, os, subprocess, sys, tempfile, threading, time, unittest
from unittest import mock

from tests.common import app  # noqa: F401
from PySide6.QtDBus import QDBusError, QDBusMessage
from armadalive import closer, tasks

WINDOWS = json.dumps([
    dict(id="{a}", title="Mozilla Firefox", app="firefox", pid=500, normal=True, skip=False, min=False),
    dict(id="{b}", title="ArmadaLive", app="armadalive", pid=os.getpid(), normal=True, skip=False, min=False),   # ourselves
    dict(id="{c}", title="", app="plasmashell", pid=77, normal=False, skip=True, min=False),                      # a panel
    dict(id="{f}", title="Another Firefox window", app="firefox", pid=500, normal=True, skip=False, min=True),     # the same program
    dict(id="{d}", title="Dolphin", app="dolphin", pid=600, normal=True, skip=False, min=True),
    dict(id="{e}", title="Odd", app="x", pid=0, normal=True, skip=False, min=False),
])


class Parse(unittest.TestCase):
    def test_only_real_application_windows_other_than_this_app_are_listed(self):
        got = tasks.parse(WINDOWS, os.getpid())
        self.assertEqual([(w["title"], w["windows"]) for w in got], [("Mozilla Firefox", 2), ("Dolphin", 1)])
        self.assertFalse(got[0]["minimized"])      # one of its windows is up
        self.assertTrue(got[1]["minimized"])

    def test_garbage_gives_an_empty_list(self):
        self.assertEqual(tasks.parse("not json", 1), [])
        self.assertEqual(tasks.parse("{}", 1), [])


class Kill(unittest.TestCase):
    def test_a_program_that_ignores_sigterm_is_killed_after_the_grace_time_with_its_children(self):
        code = "import signal, subprocess, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); subprocess.Popen([sys.executable, '-c', 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']); time.sleep(60)"
        p = subprocess.Popen([sys.executable, "-c", code])
        time.sleep(0.8)
        table = tasks.parents()
        kids = [c for c, parent in table.items() if parent == p.pid]
        self.assertTrue(kids)
        tasks.kill_tree(p.pid, grace=0.6, table=table)
        p.wait(timeout=5)
        time.sleep(0.3)
        self.assertFalse(any(os.path.exists(f"/proc/{k}") and open(f"/proc/{k}/stat").read().rpartition(")")[2].split()[0] != "Z" for k in kids))

    def test_memory_is_the_sum_over_the_whole_tree(self):
        self.assertGreater(tasks.memory_mb(os.getpid(), tasks.parents()), 5)


class SessionReliability(unittest.TestCase):
    def test_script_run_timeout_unloads_script_and_deletes_file(self):
        calls = []

        def call(cmd, **kwargs):
            calls.append(cmd)
            if "run" in cmd:
                raise subprocess.TimeoutExpired(cmd, 5)
            reply = "b true" if "unloadScript" in cmd else "i 42"
            return subprocess.CompletedProcess(cmd, 0, reply, "")

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(tasks, "SCRIPT_DIR", directory), mock.patch.object(tasks.subprocess, "run", call):
                backend = tasks.Tasks()
                backend._bus = "test"
                backend._run_script("source", "act")
            self.assertIn("unloadScript", calls[-1])
            self.assertEqual(calls[-1][-1], calls[0][-1])
            self.assertEqual(os.listdir(directory), [])

    def test_failed_unload_blocks_new_scripts_until_cleanup_recovers(self):
        for mode in ("exit", "false", "timeout"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                backend = tasks.Tasks()
                backend._bus = "test"
                calls = []
                recovered = False

                def call(cmd, **kwargs):
                    calls.append(cmd)
                    if "loadScript" in cmd:
                        return subprocess.CompletedProcess(cmd, 0, "i 42", "")
                    if "unloadScript" in cmd:
                        if recovered:
                            return subprocess.CompletedProcess(cmd, 0, "b true", "")
                        if mode == "timeout":
                            raise subprocess.TimeoutExpired(cmd, 5)
                        return subprocess.CompletedProcess(cmd, int(mode == "exit"), "b false", "")
                    if "isScriptLoaded" in cmd:
                        return subprocess.CompletedProcess(cmd, 0, "b true", "")
                    return subprocess.CompletedProcess(cmd, 0, "", "")

                with mock.patch.object(tasks, "SCRIPT_DIR", directory), mock.patch.object(tasks.subprocess, "run", call), \
                        mock.patch.object(tasks.time, "monotonic", return_value=100) as clock:
                    result = backend._run_script("source", "act")
                    self.assertEqual(result, (True, False))
                    script_name = next(cmd[-1] for cmd in calls if "loadScript" in cmd)
                    count = len(calls)
                    self.assertEqual(backend._run_script("another source", "act"), (False, False))
                    self.assertEqual(len(calls), count)

                    clock.return_value += 60
                    recovered = True
                    self.assertEqual(backend._run_script("another source", "act"), (True, True))
                    self.assertIn("unloadScript", calls[count])
                    self.assertEqual(calls[count][-1], script_name)
                    self.assertEqual(sum("run" in cmd for cmd in calls), 2)
                    self.assertEqual(sum("loadScript" in cmd for cmd in calls), 2)
                    self.assertEqual(os.listdir(directory), [])

    def test_activation_effect_is_preserved_but_cleanup_failure_marks_tasks_unhealthy(self):
        backend = tasks.Tasks()
        backend._ok = True
        backend._starts = {"100": 42}
        switched = []
        backend.switched.connect(lambda: switched.append(True))
        with mock.patch.object(tasks.shell, "session_bus", return_value="test"), \
                mock.patch.object(tasks.shell, "invalidate_bus") as invalidate, \
                mock.patch.object(tasks, "same_process", return_value=True), \
                mock.patch.object(backend, "_connect", return_value=True), \
                mock.patch.object(backend, "_run_script", return_value=(True, False)) as run:
            backend.activate("100")
            self.wait_for(lambda: backend._job is None)
        self.assertEqual(switched, [True])
        self.assertFalse(backend.state["ok"])
        run.assert_called_once()
        invalidate.assert_called_once_with("test")

    def test_replaced_dead_bus_with_stale_path_does_not_block_new_scripts(self):
        for error in ("NoServer", "FileNotFound"):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, "dbus-old")
                with open(path, "w"):
                    pass  # The old daemon left a filesystem entry behind.
                old_bus = "unix:path=" + path
                backend = tasks.Tasks()
                backend._bus = "unix:path=" + os.path.join(directory, "dbus-new")
                backend._pending_cleanup = (old_bus, "old-script")
                probe = mock.Mock()
                probe.isConnected.return_value = False
                probe.lastError.return_value = QDBusError(QDBusMessage.createError(
                    "org.freedesktop.DBus.Error." + error, "old endpoint is gone"))
                calls = []

                def call(cmd, **kwargs):
                    calls.append(cmd)
                    if f"--address={old_bus}" in cmd:
                        return subprocess.CompletedProcess(cmd, 1, "", "connection failed")
                    reply = "i 42" if "loadScript" in cmd else "b true"
                    return subprocess.CompletedProcess(cmd, 0, reply, "")

                with mock.patch.object(tasks, "SCRIPT_DIR", directory), \
                        mock.patch.object(tasks.subprocess, "run", side_effect=call), \
                        mock.patch.object(tasks.QDBusConnection, "connectToBus", return_value=probe) as connect, \
                        mock.patch.object(tasks.QDBusConnection, "disconnectFromBus") as disconnect:
                    self.assertEqual(backend._run_script("new source", "list"), (True, True))
                self.assertIsNone(backend._pending_cleanup)
                self.assertEqual(sum("loadScript" in cmd for cmd in calls), 1)
                self.assertEqual(connect.call_args.args[0], old_bus)
                disconnect.assert_called_once_with(connect.call_args.args[1])
                self.assertEqual(os.listdir(directory), ["dbus-old"])

    def test_unconfirmed_old_bus_failure_preserves_cleanup_and_backoff(self):
        for connected, error in ((True, "NoServer"), (False, "NoReply"), (False, "Timeout"),
                                 (False, "TimedOut"), (False, "AuthFailed"), (False, "AccessDenied"),
                                 (False, "UnknownMethod"), (False, "Disconnected"), (False, "Failed")):
            with self.subTest(connected=connected, error=error), tempfile.TemporaryDirectory() as directory:
                backend = tasks.Tasks()
                backend._bus = "unix:path=" + os.path.join(directory, "dbus-new")
                old_bus = "unix:path=" + os.path.join(directory, "dbus-old")
                backend._pending_cleanup = (old_bus, "old-script")
                probe = mock.Mock()
                probe.isConnected.return_value = connected
                probe.lastError.return_value = QDBusError(QDBusMessage.createError(
                    "org.freedesktop.DBus.Error." + error, "old endpoint status is uncertain"))
                with mock.patch.object(tasks, "SCRIPT_DIR", directory), \
                        mock.patch.object(tasks.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "failed")) as run, \
                        mock.patch.object(tasks.QDBusConnection, "connectToBus", return_value=probe) as connect, \
                        mock.patch.object(tasks.QDBusConnection, "disconnectFromBus") as disconnect, \
                        mock.patch.object(tasks.time, "monotonic", return_value=100) as clock:
                    self.assertEqual(backend._run_script("new source", "list"), (False, False))
                    self.assertEqual(backend._pending_cleanup, (old_bus, "old-script"))
                    self.assertEqual(backend._cleanup_after, 102)
                    clock.return_value = 101
                    self.assertEqual(backend._run_script("new source", "list"), (False, False))
                self.assertEqual(len(run.call_args_list), 1)
                self.assertIn("unloadScript", run.call_args.args[0])
                self.assertEqual(connect.call_count, 1)
                disconnect.assert_called_once_with(connect.call_args.args[1])

    def test_successful_old_cleanup_does_not_probe_the_connection(self):
        backend = tasks.Tasks()
        backend._bus = "new-bus"
        backend._pending_cleanup = ("old-bus", "old-script")
        with mock.patch.object(backend, "_unload_script", return_value=True), \
                mock.patch.object(tasks.QDBusConnection, "connectToBus") as connect:
            self.assertTrue(backend._retry_cleanup(backend._bus))
        self.assertIsNone(backend._pending_cleanup)
        connect.assert_not_called()

    def test_false_unload_reply_is_clean_if_the_script_is_absent(self):
        backend = tasks.Tasks()
        backend._bus = "test"
        replies = [(0, "i 42"), (0, ""), (0, "b false"), (0, "b false")]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(tasks, "SCRIPT_DIR", directory), \
                mock.patch.object(tasks.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], code, out, "") for code, out in replies
                ]) as run:
            self.assertEqual(backend._run_script("source", "act"), (True, True))
        self.assertIn("isScriptLoaded", run.call_args.args[0])

    def test_delayed_force_does_not_signal_reused_process_id(self):
        def read(path, *args, **kwargs):
            return mock.mock_open(read_data=f"100 (test process) S 1 {' '.join(['0'] * 17)} {start}").return_value

        start = 1234
        with mock.patch("builtins.open", side_effect=read), mock.patch.object(closer.os, "kill") as kill, \
                mock.patch.object(closer.QTimer, "singleShot") as timer:
            closer.terminate([100])
            start = 5678
            timer.call_args.args[1]()
        self.assertEqual(kill.call_args_list, [mock.call(100, tasks.signal.SIGTERM)])


    def test_disconnected_receiver_is_recreated(self):
        backend = tasks.Tasks()
        old = mock.Mock()
        old.isConnected.return_value = False
        backend._conn, backend._bus, backend._conn_name = old, "same-address", "old-connection"
        new = mock.Mock()
        with mock.patch.object(tasks.QDBusConnection, "connectToBus", return_value=new) as connect, \
                mock.patch.object(tasks.QDBusConnection, "disconnectFromBus") as disconnect:
            self.assertTrue(backend._connect("same-address"))
        self.assertIs(backend._conn, new)
        disconnect.assert_called_once_with("old-connection")
        self.assertNotEqual(connect.call_args.args[1], "old-connection")

    def test_reports_from_old_refresh_are_ignored_after_page_reopens(self):
        backend = tasks.Tasks()
        reports = []

        def run(source, action):
            reports.append(source.split(' "report", "', 1)[1].split(':', 1)[0])
            return True, True

        with mock.patch.object(tasks.shell, "session_bus", return_value="test"), \
                mock.patch.object(backend, "_connect", return_value=True), \
                mock.patch.object(backend, "_run_script", side_effect=run):
            backend.setActive(True)
            try:
                self.wait_for(lambda: len(reports) == 1 and backend._phase == "report")
                backend.setActive(False)
                backend.setActive(True)
                self.wait_for(lambda: len(reports) == 2 and backend._phase == "report")

                backend._rx.report(reports[0] + ":" + WINDOWS)
                self.assertFalse(backend.state["ok"])
                self.assertEqual(backend._phase, "report")

                owner = threading.get_ident()
                worker_ids = []
                collect = tasks._collect

                def collect_off_thread(payload):
                    worker_ids.append(threading.get_ident())
                    return collect(payload)

                with mock.patch.object(tasks, "_collect", side_effect=collect_off_thread):
                    backend._rx.report(reports[1] + ":" + WINDOWS)
                    self.wait_for(lambda: backend.state["ok"])
                self.assertEqual(len(worker_ids), 1)
                self.assertNotEqual(worker_ids[0], owner)
                self.assertEqual([i["title"] for i in backend.state["items"]], ["Dolphin", "Mozilla Firefox"])
            finally:
                backend.setActive(False)

    def wait_for(self, predicate):
        timeout = time.monotonic() + 2
        while not predicate() and time.monotonic() < timeout:
            app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate())

    def test_refresh_requests_coalesce_while_the_script_runs(self):
        entered, release = threading.Event(), threading.Event()
        threads = []

        def run(*args):
            threads.append(threading.get_ident())
            entered.set()
            release.wait(2)
            return False, True

        backend = tasks.Tasks()
        with mock.patch.object(backend, "_connect", return_value=True), mock.patch.object(backend, "_run_script", side_effect=run), \
                mock.patch.object(tasks.shell, "session_bus", return_value="test"):
            backend.refresh()
            try:
                self.wait_for(entered.is_set)
                for _ in range(10):
                    backend.refresh()
                self.assertEqual(len(threads), 1)
            finally:
                release.set()

    def test_process_tree_handles_a_cycle_and_visits_each_process_once(self):
        self.assertEqual(sorted(closer.tree(10, {10: 11, 11: 10, 12: 10})), [10, 11, 12])


if __name__ == "__main__":
    unittest.main()
