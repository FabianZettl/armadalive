import os, socket, subprocess, tempfile, unittest

RUN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "run.sh")


class RunSh(unittest.TestCase):
    """Which display scripts/run.sh picks: the bottom session, its X11 side, or the desktop's own session."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.socks = []

    def tearDown(self):
        for s in self.socks:
            s.close()

    def sock(self, name):
        s = socket.socket(socket.AF_UNIX)
        s.bind(os.path.join(self.dir, name))
        self.socks.append(s)

    def run_sh(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM")}
        env.update(XDG_RUNTIME_DIR=self.dir, ARMADALIVE_DRY_RUN="1", **extra)
        return subprocess.run(["sh", RUN], env=env, capture_output=True, text=True)

    def test_the_bottom_session_is_used_as_it_is(self):
        self.sock("armada-plasma-bottom")
        self.sock("wayland-0")
        r = self.run_sh(WAYLAND_DISPLAY="armada-plasma-bottom", QT_QPA_PLATFORM="wayland")
        self.assertIn("windowed=\n", r.stdout + "\n")
        self.assertIn("wayland=armada-plasma-bottom", r.stdout)

    def test_a_dead_bottom_session_falls_back_to_its_x11_side(self):
        with open(os.path.join(self.dir, "armada-bottom-env"), "w") as f:
            f.write("DISPLAY=:2\n")
        r = self.run_sh(ARMADALIVE_X11_AFTER="0")
        self.assertIn("platform=xcb", r.stdout)
        self.assertIn("display=:2", r.stdout)
        self.assertNotIn("--windowed", r.stdout)

    def test_at_boot_the_plasma_session_is_waited_for_before_the_x11_side_is_used(self):
        import threading, time
        with open(os.path.join(self.dir, "armada-bottom-env"), "w") as f:     # the bottom gamescope is up, its Plasma session is not yet
            f.write("DISPLAY=:2\n")
        threading.Thread(target=lambda: (time.sleep(1.5), self.sock("armada-plasma-bottom")), daemon=True).start()
        r = self.run_sh(ARMADALIVE_X11_AFTER="10", ARMADALIVE_WAIT="20", WAYLAND_DISPLAY="armada-plasma-bottom", QT_QPA_PLATFORM="wayland")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("wayland=armada-plasma-bottom", r.stdout)
        self.assertNotIn("platform=xcb", r.stdout)

    def test_on_the_x11_side_the_app_is_ended_when_the_plasma_session_shows_up_so_the_unit_restarts_it(self):
        import stat, threading, time
        with open(os.path.join(self.dir, "armada-bottom-env"), "w") as f:
            f.write("DISPLAY=:2\n")
        fake = os.path.join(self.dir, "fakepython")        # -c "import ..." succeeds, -m armadalive runs for a long time
        with open(fake, "w") as f:
            f.write('#!/bin/sh\n[ "$1" = "-c" ] && exit 0\nexec sleep 30\n')
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        threading.Thread(target=lambda: (time.sleep(1.5), self.sock("armada-plasma-bottom")), daemon=True).start()
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM", "ARMADALIVE_DRY_RUN")}
        env.update(XDG_RUNTIME_DIR=self.dir, ARMADALIVE_PYTHON=fake, ARMADALIVE_X11_AFTER="0", ARMADALIVE_WATCH="0.5", ARMADALIVE_WAIT="5")
        started = time.monotonic()
        r = subprocess.run(["sh", RUN], env=env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)
        self.assertLess(time.monotonic() - started, 10)

    def test_desktop_mode_shows_a_window_in_the_desktops_session(self):
        self.sock("wayland-0")
        r = self.run_sh(WAYLAND_DISPLAY="armada-plasma-bottom", QT_QPA_PLATFORM="wayland")   # what the unit sets
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("platform=wayland wayland=wayland-0", r.stdout)
        self.assertIn("windowed=--windowed", r.stdout)

    def test_game_mode_still_starting_fails_so_the_unit_retries_instead_of_ending_quietly(self):
        open(os.path.join(self.dir, "armada-bottom-screen-active"), "w").close()   # the bottom session unit has started, no socket yet
        self.sock("wayland-0")                                                      # must not be taken for desktop mode
        r = self.run_sh(ARMADALIVE_WAIT="0")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("platform=", r.stdout)

    def test_nothing_to_show_it_on_fails_so_the_unit_retries_instead_of_ending_quietly(self):
        r = self.run_sh(ARMADALIVE_WAIT="0")   # boot: neither session is there yet; exit 0 would count as success and never be retried
        self.assertEqual(r.returncode, 1)
        self.assertIn("tries again", r.stderr)

    def test_a_session_that_appears_while_waiting_is_taken(self):
        import threading, time
        threading.Thread(target=lambda: (time.sleep(1.5), self.sock("armada-plasma-bottom")), daemon=True).start()
        r = self.run_sh(ARMADALIVE_WAIT="10", WAYLAND_DISPLAY="armada-plasma-bottom", QT_QPA_PLATFORM="wayland")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("wayland=armada-plasma-bottom", r.stdout)


if __name__ == "__main__":
    unittest.main()
