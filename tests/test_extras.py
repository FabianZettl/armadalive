import json, os, struct, tempfile, unittest
from pathlib import Path
from unittest import mock

from tests.common import app  # noqa: F401
from PySide6.QtGui import QColor, QImage

from armadalive import backup, battery, closer, controls, emusettings, gamepad, gamerules, media, palette, thermal, tiles, ui


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

    def test_a_refused_limit_is_remembered_and_hides_the_setting(self):
        b = self.make()
        b.supported = True
        with mock.patch.object(battery.privileged, "available", return_value=True), mock.patch.object(battery.privileged, "run", return_value="the battery did not accept the limit"), \
                mock.patch.object(battery, "CONFIG", "/tmp/armadalive-test-battery.json"):
            b.setLimit(80)
        self.assertTrue(b.state["refused"])
        self.assertFalse(b.state["supported"])
        self.assertEqual(b.state["limit"], 100)

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
    def test_only_known_files_are_written_and_foreign_backup_is_refused(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(backup, "CONFIG_DIR", d):
            n = backup.apply({"files": {"ui.json": {"theme": "neon"}, "evil.json": {"x": 1}}})
            self.assertEqual(n, 1)
            self.assertEqual(sorted(os.listdir(d)), ["ui.json"])
            self.assertEqual(backup.collect()["files"], {"ui.json": {"theme": "neon"}})
            with self.assertRaises(ValueError):
                backup.apply(["not", "a", "backup"])

    def test_the_app_grid_with_its_folders_and_the_play_history_are_in_the_backup(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(backup, "CONFIG_DIR", d):
            data = {"files": {"apps.json": {"slots": [], "folders": {"1": {"name": "Tools", "items": []}}}, "history.json": {"games": {}, "sessions": [["x", 1, 2]]}}}
            self.assertEqual(backup.apply(data), 2)
            self.assertEqual(backup.collect()["files"], data["files"])

    def test_legacy_emulator_originals_do_not_transfer_between_devices(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(backup, "CONFIG_DIR", directory):
            file = Path(directory, "game_rules.json")
            local = {"enabled": False, "base": {"psp": "2"}}
            file.write_text(json.dumps(local))
            portable = backup.collect()["files"]
            self.assertEqual(portable["game_rules.json"], {"enabled": False})
            portable["game_rules.json"]["base"] = {"psp": "5"}
            backup.apply({"files": portable})
            self.assertEqual(json.loads(file.read_text()), local)
            file.unlink()
            backup.apply({"files": portable})
            self.assertEqual(json.loads(file.read_text()), {"enabled": False})

    def test_invalid_known_file_is_reported_before_any_file_is_written(self):
        invalid = {
            "game_rules.json": {"rules": None},
            "battery.json": {"warn": "20"},
            "tiles.json": {"order": ["battery", 1]},
            "apps.json": {"slots": {}, "folders": []},
            "history.json": {"sessions": [["game", "not a date", 2]]},
            "ui.json": {"heat": "hot"},
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(backup, "CONFIG_DIR", directory):
            existing = Path(directory, "ui.json")
            previous = b'{ "theme": "stock" }\n'
            existing.write_bytes(previous)
            for name, data in invalid.items():
                with self.subTest(name=name):
                    files = {"ui.json": {"theme": "neon"}, name: data}
                    with self.assertRaisesRegex(ValueError, name.replace(".", r"\.")):
                        backup.apply({"files": files})
                    self.assertEqual(existing.read_bytes(), previous)
                    self.assertEqual(sorted(os.listdir(directory)), ["ui.json"])

    def test_interrupted_backup_export_keeps_previous_archive(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(backup, "CONFIG_DIR", directory):
            archive = Path(directory, "backup.json")
            previous = b'{ "files": {"ui.json": {}} }\n'
            archive.write_bytes(previous)
            with mock.patch.object(backup, "FILE", str(archive)), \
                    mock.patch("os.replace", side_effect=OSError("export replace failed")):
                coordinator = backup.Backup()
                coordinator.save()
            self.assertIn("export replace failed", coordinator.state["message"])
            self.assertEqual(archive.read_bytes(), previous)

    def test_second_replace_failure_rolls_back_the_first_file(self):
        self._verify_failed_restore(OSError("second replace failed"), b"prior bytes, even from a damaged file")

    def test_interrupted_restore_rolls_back_on_restart(self):
        self._verify_failed_restore(KeyboardInterrupt())

    def _verify_failed_restore(self, failure, prior_ui=None):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(backup, "CONFIG_DIR", directory):
            ui_file = Path(directory, "ui.json")
            real_rules = Path(directory, "rules-target")
            rules_file = Path(directory, "game_rules.json")
            previous = b'{ "rules": {}, "enabled": true }\n'
            if prior_ui is not None:
                ui_file.write_bytes(prior_ui)
            real_rules.write_bytes(previous)
            rules_file.symlink_to(real_rules.name)
            replace = os.replace

            def fail_second(source, dest):
                if Path(dest) == real_rules:
                    raise failure
                replace(source, dest)

            files = {"ui.json": {"theme": "neon"}, "game_rules.json": {"enabled": False}}
            with mock.patch("os.replace", side_effect=fail_second):
                with self.assertRaises(type(failure)):
                    backup.apply({"files": files})
            if isinstance(failure, KeyboardInterrupt):
                self.assertTrue(ui_file.exists())
                backup.recover_restore()
                backup.recover_restore()
            expected = ["game_rules.json", "rules-target"]
            if prior_ui is None:
                self.assertFalse(ui_file.exists())
            else:
                self.assertEqual(ui_file.read_bytes(), prior_ui)
                expected.append("ui.json")
            self.assertEqual(sorted(os.listdir(directory)), expected)
            self.assertTrue(rules_file.is_symlink())
            self.assertEqual(real_rules.read_bytes(), previous)

    def test_successful_restore_preserves_symlink_and_target_mode(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(backup, "CONFIG_DIR", directory):
            actual = Path(directory, "target")
            actual.write_text('{"theme":"stock"}')
            actual.chmod(0o640)
            link = Path(directory, "ui.json")
            link.symlink_to(actual.name)
            self.assertEqual(backup.apply({"files": {"ui.json": {"theme": "neon"}}}), 1)
            backup.recover_restore()
            self.assertTrue(link.is_symlink())
            self.assertEqual(json.loads(actual.read_text()), {"theme": "neon"})
            self.assertEqual(actual.stat().st_mode & 0o777, 0o640)

    def test_restore_failure_after_replacement_retains_undo_until_retry(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(backup, "CONFIG_DIR", directory):
            ui_file = Path(directory, "ui.json")
            rules_file = Path(directory, "game_rules.json")
            rules_file.write_text('{"enabled":false}')
            write = backup.persistence.write_bytes

            def fail_second(path, data, **options):
                if Path(path) != rules_file:
                    return write(path, data, **options)
                if data != b'{"enabled":false}':
                    write(path, data, **options)
                raise OSError("device stopped responding")

            files = {"ui.json": {"theme": "neon"}, "game_rules.json": {"enabled": True}}
            with mock.patch.object(backup.persistence, "write_bytes", side_effect=fail_second):
                with self.assertRaisesRegex(backup.RestoreRecoveryError, "device stopped responding"):
                    backup.apply({"files": files})
                self.assertFalse(ui_file.exists())
                self.assertEqual(json.loads(rules_file.read_text()), {"enabled": True})
            backup.recover_restore()
            self.assertEqual(rules_file.read_text(), '{"enabled":false}')
            self.assertEqual(sorted(os.listdir(directory)), ["game_rules.json"])

    def test_startup_defaults_for_individual_malformed_configurations(self):
        from tests.test_gamerules import FakeGs, FakeNow, FakeSys

        cases = (
            (gamerules, {"rules": None}, lambda: gamerules.GameRules(FakeNow(), FakeGs(), FakeSys()).state["rules"], []),
            (battery, {"warn": "20"}, lambda: self._battery_warning(), 20),
            (ui, {"heat": "hot"}, lambda: ui.UiSettings().state["heat"], 85),
            (tiles, {"order": ["battery", 1]}, lambda: tiles.Tiles().order, []),
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(battery, "LIMIT_FILE", "/nonexistent"):
            path = Path(directory, "config.json")
            for module, saved, startup, expected in cases:
                with self.subTest(module=module.__name__), mock.patch.object(module, "CONFIG", path):
                    path.write_text(json.dumps(saved))
                    self.assertEqual(startup(), expected)

    @staticmethod
    def _battery_warning():
        backend = battery.Battery()
        backend.check(9, "Discharging")
        return backend.state["warn"]


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


    def test_changes_only_the_value_at_the_symlink_target(self):
        original = b"# header\r\n[Graphics]\r\n  InternalResolution= 2  ; keep this\r\nOther=\xff"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "target.ini")
            target.write_bytes(original)
            target.chmod(0o640)
            link = target.with_name("x.ini")
            link.symlink_to(target.name)
            with mock.patch.dict(emusettings.SPECS, {"psp": (link, "Graphics", "InternalResolution", "{}")}):
                self.assertEqual(emusettings.read("psp"), "2")
                self.assertTrue(emusettings.write("psp", 4))
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), original.replace(b"2  ;", b"4  ;"))
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_interrupted_emu_write_keeps_settings(self):
        original = "[Graphics]\nInternalResolution = 2\nOther = 9\n"
        path, patch = self.ini(original)
        with patch, mock.patch("os.replace", side_effect=OSError("replace failed")):
            self.assertFalse(emusettings.write("psp", 4))
        with open(path) as stream:
            self.assertEqual(stream.read(), original)

    def test_ambiguous_emulator_keys_and_sections_are_left_unchanged(self):
        cases = (
            "[Graphics]\nInternalResolution = 2\nInternalResolution = 3\n",
            "[Graphics]\nInternalResolution = 2\n[Other]\na = 1\n[Graphics]\nInternalResolution = 3\n",
        )
        for original in cases:
            with self.subTest(original=original):
                path, patch = self.ini(original)
                with patch:
                    self.assertIsNone(emusettings.read("psp"))
                    self.assertFalse(emusettings.write("psp", 4))
                self.assertEqual(Path(path).read_text(), original)


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


class FrameGenSwitch(unittest.TestCase):
    def test_the_tile_creates_and_removes_the_off_file(self):
        path = os.path.join(tempfile.mkdtemp(), "mako-thor", "off")
        with mock.patch.object(controls, "FRAMEGEN_OFF", path), mock.patch.object(controls.Controls, "_read", return_value={}):
            c = controls.Controls()
            c._poller = mock.Mock()
            c.toggleFrameGen()
            self.assertTrue(os.path.exists(path))
            c.toggleFrameGen()
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
