import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.common import app  # noqa: F401
from armadalive import battery, persistence, tiles, ui


class SettingsPersistence(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.ui = self.root / "ui.json"
        self.tiles = self.root / "tiles.json"
        self.battery = self.root / "battery.json"
        self.enterContext(mock.patch.object(ui, "CONFIG", self.ui))
        self.enterContext(mock.patch.object(tiles, "CONFIG", self.tiles))
        self.enterContext(mock.patch.object(battery, "CONFIG", self.battery))
        self.enterContext(mock.patch.object(battery, "LIMIT_FILE", self.root / "no-charge-limit"))
        self.enterContext(mock.patch.object(battery.privileged, "available", side_effect=AssertionError("unexpected helper probe")))
        self.enterContext(mock.patch.object(battery.privileged, "run", side_effect=AssertionError("unexpected helper call")))

    def test_interrupted_replace_leaves_the_prior_file_and_does_not_emit_changed(self):
        cases = (
            (self.ui, {"theme": "snes", "accent": "68E1FB"}, ui.UiSettings,
             lambda store: store.setTheme("ps2"), lambda store: (store.state["theme"], store.state["accent"]), ("ps2", "")),
            (self.tiles, {"order": ["a", "b"]}, tiles.Tiles,
             lambda store: store.setOrder(["b", "a"]), lambda store: store.order, ["b", "a"]),
            (self.battery, {"warn": 20}, battery.Battery,
             lambda store: store.setWarn(30), lambda store: store.state["warn"], 30),
        )
        for path, saved, make_store, edit, current_value, expected in cases:
            with self.subTest(file=path.name):
                original = json.dumps(saved).encode()
                path.write_bytes(original)
                store = make_store()
                observed = []
                store.changed.connect(lambda: observed.append(json.loads(path.read_bytes())))

                with mock.patch("os.replace", side_effect=OSError("interrupted save")):
                    with self.assertRaisesRegex(OSError, "interrupted save"):
                        edit(store)

                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(current_value(store), expected)
                self.assertEqual(observed, [])
                self.assertEqual(list(self.root.glob(".armadalive-*")), [])

                # Save the same in-memory choice after the filesystem recovers.
                edit(store)
                self.assertEqual(current_value(make_store()), expected)
                self.assertEqual(observed, [json.loads(path.read_bytes())])

    def test_missing_or_unreadable_files_fall_back_to_defaults(self):
        for data in (None, b"{broken", b"\xff", b"[" * 1500 + b"0" + b"]" * 1500):
            with self.subTest(data=str(data)[:12]):
                for path in (self.ui, self.tiles, self.battery):
                    if data is not None:
                        path.write_bytes(data)
                self.assertFalse(ui.UiSettings().state["onboarded"])
                self.assertEqual(tiles.Tiles().order, [])
                self.assertEqual(battery.Battery().state["warn"], 20)

    def test_legacy_settings_keep_supported_values(self):
        self.ui.write_text('{"theme":"ps2","heat":82.5,"lang":"fr","unused":5}')
        self.tiles.write_text('{"order":["b",12,"a",null,"b"],"unused":5}')
        self.battery.write_text('{"warn":55.5,"limit":49,"refused":1,"unused":5}')

        look = ui.UiSettings()
        self.assertEqual(look.state["heat"], 82.5)
        self.assertEqual(look.state["lang"], "fr")
        self.assertTrue(look.state["onboarded"])
        self.assertNotIn("unused", look.state)
        self.assertEqual(tiles.Tiles().order, ["b", "a", "b"])
        stored_battery = battery.Battery()
        self.assertEqual(stored_battery.state["warn"], 55.5)
        self.assertEqual(stored_battery.state["limit"], 49)
        self.assertIs(type(stored_battery.state["refused"]), int)
        self.assertNotIn("unused", stored_battery.state)

        look.setDim(False)
        stored_battery.setWarn(25)
        self.assertEqual(ui.UiSettings().state["heat"], 82.5)
        self.assertEqual(battery.Battery().state["limit"], 49)

    def test_unusable_heat_falls_back_without_discarding_other_choices(self):
        self.ui.write_text('{"theme":"ps2","heat":"hot"}')

        look = ui.UiSettings()
        self.assertEqual(look.state["heat"], 85)
        self.assertEqual(look.state["theme"], "ps2")
        self.assertTrue(look.state["onboarded"])

    def test_unusable_battery_thresholds_fall_back_individually(self):
        self.battery.write_text('{"warn":"high","limit":null,"refused":true}')
        Path(battery.LIMIT_FILE).touch()

        stored_battery = battery.Battery()
        self.assertEqual(stored_battery.state["warn"], 20)
        self.assertEqual(stored_battery.state["limit"], 100)
        self.assertTrue(stored_battery.state["refused"])

    def test_save_follows_an_existing_symlink_and_preserves_target_mode(self):
        target = self.root / "custom-ui.json"
        target.write_text('{"theme":"snes"}')
        target.chmod(0o640)
        self.ui.symlink_to(target.name)

        ui.UiSettings().setTheme("ps2")

        self.assertTrue(self.ui.is_symlink())
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(json.loads(target.read_bytes())["theme"], "ps2")

    def test_overflowed_heat_survives_an_unrelated_appearance_edit(self):
        self.ui.write_text('{"heat":1e309}')
        look = ui.UiSettings()

        look.setDim(False)

        reopened = ui.UiSettings()
        self.assertIs(reopened.state["dim"], False)
        self.assertEqual(reopened.state["heat"], float("inf"))

    def test_overflowed_charge_limit_survives_an_unrelated_warning_edit(self):
        self.battery.write_text('{"limit":1e309}')
        stored_battery = battery.Battery()

        stored_battery.setWarn(25)

        reopened = battery.Battery()
        self.assertEqual(reopened.state["warn"], 25)
        self.assertEqual(reopened.state["limit"], float("inf"))

    def test_shared_json_writer_still_rejects_nonfinite_numbers_by_default(self):
        path = self.root / "strict.json"
        path.write_bytes(b"{}")

        with self.assertRaises(ValueError):
            persistence.write_json(path, {"heat": float("inf")})

        self.assertEqual(path.read_bytes(), b"{}")

    def test_saves_respect_existing_read_only_files_and_symlink_targets(self):
        cases = (
            (self.ui, ui.UiSettings, lambda store: store.setDim(False)),
            (self.tiles, tiles.Tiles, lambda store: store.setOrder(["b", "a"])),
            (self.battery, battery.Battery, lambda store: store.setWarn(25)),
        )
        probe = self.root / "permission-probe"
        probe.touch()
        probe.chmod(0o444)
        if os.access(probe, os.W_OK, effective_ids=True):
            self.skipTest("test process can write files with mode 0444")

        for path, make_store, edit in cases:
            for symlink in (False, True):
                with self.subTest(file=path.name, symlink=symlink):
                    target = path
                    if symlink:
                        path.unlink()
                        target = path.with_suffix(".target.json")
                        path.symlink_to(target.name)
                    target.write_bytes(b"{}")
                    target.chmod(0o444)
                    store = make_store()
                    notifications = []
                    store.changed.connect(lambda: notifications.append(True))

                    with self.assertRaises(PermissionError):
                        edit(store)

                    self.assertEqual(target.read_bytes(), b"{}")
                    self.assertEqual(notifications, [])
                    self.assertEqual(path.is_symlink(), symlink)
                    self.assertEqual(target.stat().st_mode & 0o777, 0o444)

                    target.chmod(0o640)
                    edit(store)
                    self.assertNotEqual(target.read_bytes(), b"{}")
                    self.assertEqual(notifications, [True])


class RestoreWriters(unittest.TestCase):
    def setUp(self):
        from armadalive import backup, gamerules
        from tests.test_gamerules import FakeGs, FakeNow, FakeSys
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(backup, "CONFIG_DIR", str(self.root)))
        self.archive = self.root / "backup.json"
        self.enterContext(mock.patch.object(backup, "FILE", str(self.archive)))
        for module, filename in ((ui, "ui.json"), (tiles, "tiles.json"), (battery, "battery.json"), (gamerules, "game_rules.json")):
            self.enterContext(mock.patch.object(module, "CONFIG", self.root / filename))
        self.enterContext(mock.patch.object(battery, "LIMIT_FILE", self.root / "no-limit"))
        self.look, self.tiles, self.battery = ui.UiSettings(), tiles.Tiles(), battery.Battery()
        self.now, self.gs, self.system = FakeNow(), FakeGs(), FakeSys()
        self.rules = gamerules.GameRules(self.now, self.gs, self.system)
        self.coordinator = backup.Backup((self.look, self.tiles, self.battery, self.rules))
        self.look.setTheme("stock")
        self.tiles.setOrder(["a", "b"])
        self.battery.setWarn(20)
        self.rules.toggle("game")
        self.archive.write_text(json.dumps({"files": {
            "ui.json": {"theme": "neon"}, "tiles.json": {"order": ["b", "a"]},
            "battery.json": {"warn": 30, "limit": 100}, "game_rules.json": {"rules": {}}
        }}))

    def test_restore_drains_actual_battery_commands_and_freezes_every_synchronous_writer(self):
        import threading
        from armadalive import backup
        from tests.test_runtime import wait_for
        started, release = threading.Event(), threading.Event()
        calls = []

        def command(_, percent):
            calls.append(percent)
            if len(calls) == 1:
                started.set()
                if not release.wait(3):
                    raise RuntimeError("test command was not released")
            return ""

        with mock.patch.object(battery.privileged, "available", return_value=True), \
                mock.patch.object(battery.privileged, "run", side_effect=command), \
                mock.patch.object(battery, "_read", return_value=""), \
                mock.patch.object(backup.QTimer, "singleShot") as later:
            try:
                self.battery.setLimit(80)
                self.assertTrue(started.wait(1))
                self.battery.setLimit(75)
                self.coordinator.restore()
                self.assertTrue(self.coordinator.state["busy"])
                self.assertTrue(self.battery.writesPending())
                self.battery.setLimit(60)
                self.battery.setWarn(45)
                self.look.setTheme("forbidden")
                self.tiles.reset()
                self.rules.setEnabled(False)
                self.rules.remove(self.rules.state["gameKey"])
                self.assertTrue(self.rules.state["writesPaused"])
                self.assertTrue(self.rules.state["enabled"])
                self.assertEqual(self.battery.state["warn"], 20)
                self.assertEqual(self.look.state["theme"], "stock")
                self.assertEqual(self.tiles.order, ["a", "b"])
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: self.coordinator.state["message"] == "restored"))
            self.assertEqual(calls, [80, 75])
            self.assertFalse(self.battery.writesPending())
            restored_bytes = {name: (self.root / name).read_bytes() for name in backup.VALIDATORS if (self.root / name).exists()}
            self.battery.setWarn(40)
            self.look.setDim(False)
            self.tiles.setOrder(["bad"])
            self.rules.toggle("idle")
            self.now.state = dict(self.now.state, key="other", playing=True)
            with mock.patch.object(self.rules, "_emulator") as emulator:
                self.now.changed.emit()
                emulator.assert_not_called()
            self.coordinator.flushWriters()
            self.assertEqual(restored_bytes, {name: (self.root / name).read_bytes() for name in restored_bytes})
            with mock.patch.object(backup.os, "execv", side_effect=OSError("exec failed")):
                later.call_args.args[1]()
        self.assertFalse(self.rules.state["writesPaused"])
        self.assertEqual(json.loads((self.root / "battery.json").read_text())["limit"], 75)
        self.battery.setWarn(25)
        self.assertEqual(json.loads((self.root / "battery.json").read_text())["warn"], 25)

    def test_export_waits_for_battery_save_and_failed_completion_aborts_restore(self):
        import threading
        from armadalive import backup
        from tests.test_runtime import wait_for
        for operation, fail in (("save", False), ("restore", True)):
            with self.subTest(operation=operation):
                started, release = threading.Event(), threading.Event()
                previous = (self.root / "ui.json").read_bytes()
                write = persistence.write_json

                def command(*_):
                    started.set()
                    if not release.wait(3):
                        raise RuntimeError("test command was not released")
                    return ""

                def save(path, *args, **kwargs):
                    if fail and Path(path).name == "battery.json":
                        raise OSError("battery persistence failed")
                    return write(path, *args, **kwargs)

                with mock.patch.object(battery.privileged, "available", return_value=True), \
                        mock.patch.object(battery.privileged, "run", side_effect=command), \
                        mock.patch.object(battery, "_read", return_value=""), \
                        mock.patch.object(persistence, "write_json", side_effect=save):
                    try:
                        self.battery.setLimit(80)
                        self.assertTrue(started.wait(1))
                        getattr(self.coordinator, operation)()
                        self.assertTrue(self.coordinator.state["busy"])
                    finally:
                        release.set()
                    self.assertTrue(wait_for(lambda: not self.coordinator.state["busy"]))
                self.assertFalse(self.battery._writes_paused)
                self.assertEqual((self.root / "ui.json").read_bytes(), previous)
                if fail:
                    self.assertIn("battery persistence failed", self.coordinator.state["message"])
                    self.assertFalse(Path(backup._journal_path()).exists())
                    self.battery.setWarn(20)  # A later successful save clears the error.
                else:
                    self.assertEqual(json.loads(self.archive.read_text())["files"]["battery.json"]["limit"], 80)

    def test_battery_timeout_releases_freeze_without_touching_restore_targets(self):
        import threading
        from armadalive import backup
        from tests.test_runtime import wait_for
        started, release = threading.Event(), threading.Event()
        previous = (self.root / "ui.json").read_bytes()

        def command(*_):
            started.set()
            if not release.wait(3):
                raise RuntimeError("test command was not released")
            return ""

        with mock.patch.object(battery.privileged, "available", return_value=True), \
                mock.patch.object(battery.privileged, "run", side_effect=command), \
                mock.patch.object(battery, "_read", return_value=""), \
                mock.patch.object(backup, "WRITE_TIMEOUT", 0):
            try:
                self.battery.setLimit(80)
                self.assertTrue(started.wait(1))
                self.coordinator.restore()
                self.assertIn("Timed out", self.coordinator.state["message"])
                self.assertFalse(self.battery._writes_paused)
                self.assertEqual((self.root / "ui.json").read_bytes(), previous)
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: not self.battery.writesPending()))
        self.assertEqual(json.loads((self.root / "battery.json").read_text())["limit"], 80)
