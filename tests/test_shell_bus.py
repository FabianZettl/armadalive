import os, threading, unittest
from unittest import mock

from tests.common import app  # noqa: F401
from armadalive import shell


def fake(lists):
    """busctl --address=<x> list: what each bus answers."""
    def run(cmd, **kw):
        addr = cmd[1].split("=", 1)[1]
        return mock.Mock(stdout=lists.get(addr, ""))
    return run


class FindBus(unittest.TestCase):
    def find(self, private, lists):
        with mock.patch.object(shell.glob, "glob", lambda p: private), mock.patch.object(shell.os, "stat", lambda p: mock.Mock(st_mode=0o140700, st_uid=os.getuid())), \
                mock.patch.object(shell.subprocess, "run", fake(lists)), mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}):
            return shell._find_bus()

    def test_the_bottom_sessions_private_bus_is_preferred(self):
        self.assertEqual(self.find(["/tmp/dbus-x"], {"unix:path=/tmp/dbus-x": " kwin_wayland ", "unix:path=/run/user/1000/bus": "org.kde.KWin"}), "unix:path=/tmp/dbus-x")

    def test_in_desktop_mode_the_kwin_of_the_session_bus_is_used(self):
        self.assertEqual(self.find([], {"unix:path=/run/user/1000/bus": "org.kde.KWin  1234 kwin_wayland"}), "unix:path=/run/user/1000/bus")

    def test_no_kwin_anywhere_gives_none(self):
        self.assertIsNone(self.find([], {"unix:path=/run/user/1000/bus": "org.freedesktop.Notifications"}))


class Keyboard(unittest.TestCase):
    def test_failed_visibility_query_does_not_toggle_keyboard(self):
        with mock.patch.object(shell, "_kb", return_value="") as dbus:
            shell.keyboard_show()
        self.assertEqual([c.args[0] for c in dbus.call_args_list], ["get-property"])

    def test_has_kwin_uses_cached_state_without_discovering_on_call(self):
        with mock.patch.object(shell, "_find_bus", return_value=None) as discover:
            backend = shell.Shell()
            discover.reset_mock()
            backend.hasKwin()
            self.assertEqual(discover.call_count, 0)

    def test_unpin_during_visibility_query_discards_stale_show(self):
        checking, release, hidden = threading.Event(), threading.Event(), threading.Event()
        operations, started = [], []
        start = threading.Thread.start

        def capture(worker):
            started.append(worker)
            start(worker)

        def dbus(*args):
            operations.append(args[0])
            if args[0] == "get-property":
                checking.set()
                release.wait(2)
                return "b false"
            if args[0] == "set-property":
                hidden.set()
            return ""

        with mock.patch.object(shell, "_kb", side_effect=dbus), mock.patch.object(shell, "_find_bus", return_value=None), \
                mock.patch.object(threading.Thread, "start", capture):
            backend = shell.Shell()
            backend.keyboard()
            try:
                self.assertTrue(checking.wait(1))
                backend.keyboard()
            finally:
                release.set()
            self.assertTrue(hidden.wait(1))
            # The first worker must finish before asserting the absence of a toggle.
            for worker in started:
                worker.join(1)
        self.assertEqual(operations, ["get-property", "set-property"])


if __name__ == "__main__":
    unittest.main()
