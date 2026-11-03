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
        r = self.run_sh()
        self.assertIn("platform=xcb", r.stdout)
        self.assertIn("display=:2", r.stdout)
        self.assertNotIn("--windowed", r.stdout)

    def test_desktop_mode_shows_a_window_in_the_desktops_session(self):
        self.sock("wayland-0")
        r = self.run_sh(WAYLAND_DISPLAY="armada-plasma-bottom", QT_QPA_PLATFORM="wayland")   # what the unit sets
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("platform=wayland wayland=wayland-0", r.stdout)
        self.assertIn("windowed=--windowed", r.stdout)

    def test_nothing_to_show_it_on_ends_quietly_instead_of_aborting(self):
        r = self.run_sh()
        self.assertEqual(r.returncode, 0)
        self.assertIn("nothing to show it on", r.stderr)


if __name__ == "__main__":
    unittest.main()
