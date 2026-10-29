import json, os, struct, tempfile, unittest
from unittest import mock

from tests.common import app  # noqa: F401
from PySide6.QtGui import QColor, QImage

from armadalive import backup, battery, closer, controls, emusettings, gamepad, media, palette, thermal


class Palette(unittest.TestCase):
    def test_a_red_picture_gives_red_and_a_grey_one_nothing(self):
        img = QImage(10, 10, QImage.Format.Format_RGB32)
        img.fill(QColor("#c02020"))
        self.assertEqual(palette.accent_of(img)[:2].lower() in ("c0", "d0", "cc", "ff", "e0", "d9", "db", "e6", "f0", "f5"), True, palette.accent_of(img))
        img.fill(QColor("#808080"))
        self.assertEqual(palette.accent_of(img), "")


class Media(unittest.TestCase):
    def test_playing_beats_paused_and_nothing_is_none(self):
        a, b = dict(status="Paused", name="a"), dict(status="Playing", name="b")
        self.assertEqual(media.pick([a, b])["name"], "b")
        self.assertEqual(media.pick([a])["name"], "a")
        self.assertIsNone(media.pick([dict(status="Stopped", name="c")]))

    def test_metadata_is_read_from_the_dbus_json(self):
        meta = {"xesam:title": {"type": "s", "data": "Song"}, "xesam:artist": {"type": "as", "data": ["A", "B"]}}
        self.assertEqual(media.describe("n", "Playing", meta), dict(name="n", status="Playing", title="Song", artist="A, B"))
        self.assertEqual(media.describe("n", "Playing", None)["title"], "")


class Battery(unittest.TestCase):
    def make(self):
        with mock.patch.object(battery, "CONFIG", "/nonexistent/battery.json"):
            b = battery.Battery()
        b.alerts = []
        b.alert.connect(b.alerts.append)
        return b

    def test_each_level_is_told_once_and_rearms_when_charging(self):
        b = self.make()
        b.check(25, "Discharging")
        b.check(19, "Discharging")
        b.check(18, "Discharging")
        self.assertEqual(b.alerts, ["19"])
        b.check(9, "Discharging")
        self.assertEqual(b.alerts, ["19", "9"])
        b.check(40, "Charging")
        b.check(19, "Discharging")
        self.assertEqual(len(b.alerts), 3)

    def test_warning_off_stays_quiet(self):
        b = self.make()
        b._s["warn"] = 0
        b.check(3, "Discharging")
        self.assertEqual(b.alerts, [])


class Backup(unittest.TestCase):
    def test_only_known_files_are_written_and_a_foreign_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(backup, "CONFIG_DIR", d):
            n = backup.apply({"files": {"ui.json": {"theme": "neon"}, "evil.json": {"x": 1}, "tiles.json": "nope"}})
            self.assertEqual(n, 1)
            self.assertEqual(sorted(os.listdir(d)), ["ui.json"])
            self.assertEqual(backup.collect()["files"], {"ui.json": {"theme": "neon"}})
            with self.assertRaises(ValueError):
                backup.apply(["not", "a", "backup"])


class EmuSettings(unittest.TestCase):
    def ini(self, text):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "x.ini")
        open(path, "w").write(text)
        return path, mock.patch.dict(emusettings.SPECS, {"psp": (path, "Graphics", "InternalResolution", "{}")})

    def test_replaces_inserts_and_never_creates(self):
        path, patch = self.ini("[General]\nInternalResolution = 9\n[Graphics]\nInternalResolution = 2\nOther = 1\n")
        with patch:
            self.assertEqual(emusettings.read("psp"), "2")
            self.assertTrue(emusettings.write("psp", 4))
            self.assertEqual(open(path).read(), "[General]\nInternalResolution = 9\n[Graphics]\nInternalResolution = 4\nOther = 1\n")
        path, patch = self.ini("[Graphics]\nOther = 1\n")
        with patch:
            self.assertTrue(emusettings.write("psp", 3))
            self.assertIn("[Graphics]\nInternalResolution = 3\n", open(path).read())
        path, patch = self.ini("[Other]\na = 1\n")
        with patch:
            self.assertFalse(emusettings.write("psp", 3))
            self.assertFalse(emusettings.write("nes", 3))
        with mock.patch.dict(emusettings.SPECS, {"psp": ("/nonexistent/x.ini", "Graphics", "K", "{}")}):
            self.assertFalse(emusettings.write("psp", 3))


class Pad(unittest.TestCase):
    def events(self, *pairs):
        return b"".join(gamepad.EVENT.pack(0, 0, 1, code, value) for code, value in pairs)

    def test_combo_needs_both_buttons_on_one_controller(self):
        with mock.patch.object(gamepad, "devices", return_value=[]):
            pad = gamepad.Pad()
        seen = []
        pad.combo.connect(seen.append)
        pad.feed("a", self.events((gamepad.BTN_START, 1)))
        self.assertEqual(seen, [])
        pad.feed("b", self.events((gamepad.BTN_SELECT, 1)))
        self.assertEqual(seen, [])
        pad.feed("a", self.events((gamepad.BTN_SELECT, 1)))
        self.assertEqual(seen, [True])
        pad.feed("a", self.events((gamepad.BTN_START, 2), (gamepad.BTN_START, 0)))
        self.assertEqual(seen, [True, False])


class Closer(unittest.TestCase):
    def test_tree_collects_descendants_only(self):
        table = {10: 1, 11: 10, 12: 11, 13: 10, 20: 1}
        self.assertEqual(sorted(closer.tree(10, table)), [10, 11, 12, 13])

    def test_target_covers_emulators_es_de_and_steam_games_but_not_steam_itself(self):
        c = closer.Closer(mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock())
        c._np.state = {"title": "Some Game"}
        with mock.patch.object(closer, "running_game", return_value=None), mock.patch.object(closer, "steam_pids", return_value=[9]), \
                mock.patch.object(closer, "esde_running", return_value=True):
            for focus, want in (("3202277837", ([9], "ES-DE")), ("12345", ([9], "Some Game")), ("769", None), ("", None)):
                c._gs.state = {"focus": focus}
                self.assertEqual(c.target(), want, focus)
        with mock.patch.object(closer, "running_game", return_value=dict(pid=4, name="x")):
            self.assertEqual(c.target(), ([4], "Some Game"))

    def make(self, target):
        pad = mock.Mock()
        c = closer.Closer(pad, mock.Mock(), mock.Mock(), mock.Mock(state={"close": True}))
        c.target = lambda: target
        return c

    def test_releasing_early_cancels_and_nothing_to_close_does_nothing(self):
        with mock.patch.object(closer, "terminate") as kill:
            c = self.make(([5], "Game"))
            c._combo(True)
            self.assertEqual(c.state["phase"], "holding")
            c._combo(False)
            self.assertEqual(c.state["phase"], "")
            kill.assert_not_called()
            c._combo(True)
            c._since -= 3
            c._step()
            kill.assert_called_once_with([5])
            self.assertEqual(c.state["phase"], "closed")
            idle = self.make(None)
            idle._combo(True)
            self.assertEqual(idle.state["phase"], "")


class Thermal(unittest.TestCase):
    def make(self, heat=85):
        ui = mock.Mock(state={"heat": heat})
        t = thermal.Thermal(mock.Mock(), ui)
        t.alerts = []
        t.alert.connect(lambda temp, profile: t.alerts.append((temp, profile)))
        return t

    def test_warns_once_then_waits_for_cooling_and_the_cooldown(self):
        t = self.make()
        t.check(80, "Balanced", 1000)
        t.check(86.4, "Performance", 1001)
        t.check(90, "Performance", 1002)          # still hot: no second popup
        self.assertEqual(t.alerts, [(86, "Performance")])
        t.check(79, "Performance", 1003)          # cooled by 5 degrees: armed again
        t.check(88, "Performance", 1004)          # but inside the five minutes
        self.assertEqual(len(t.alerts), 1)
        t.check(79, "Performance", 1400)
        t.check(88, "Performance", 1401)
        self.assertEqual(len(t.alerts), 2)

    def test_off_and_other_limits(self):
        t = self.make(0)
        t.check(99, "x", 1000)
        self.assertEqual(t.alerts, [])
        t = self.make(90)
        t.check(89, "x", 1000)
        self.assertEqual(t.alerts, [])


class Tailscale(unittest.TestCase):
    def test_status_json_becomes_a_state(self):
        on = '{"BackendState": "Running", "Self": {"TailscaleIPs": ["100.1.2.3", "fd7a::1"]}}'
        self.assertEqual(controls.tailscale_state(on), dict(state="on", ip="100.1.2.3"))
        self.assertEqual(controls.tailscale_state('{"BackendState": "Stopped", "Self": null}')["state"], "off")
        self.assertEqual(controls.tailscale_state('{"BackendState": "NeedsLogin"}')["state"], "login")
        self.assertEqual(controls.tailscale_state("")["state"], "missing")
        self.assertEqual(controls.tailscale_state("not json")["state"], "missing")

    def test_the_retry_flags_come_from_tailscales_own_hint_and_must_look_like_flags(self):
        err = "Error: changing settings via 'tailscale up' requires mentioning all\nnon-default flags. To proceed, specify --reset or:\n\n\ttailscale up --operator=deck\n"
        self.assertEqual(controls.tailscale_retry(err), ["--operator=deck"])
        self.assertIsNone(controls.tailscale_retry("tailscale up --operator=deck; rm -rf /"))
        self.assertIsNone(controls.tailscale_retry("nothing useful here"))


if __name__ == "__main__":
    unittest.main()
