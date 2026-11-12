import os, unittest
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


if __name__ == "__main__":
    unittest.main()
