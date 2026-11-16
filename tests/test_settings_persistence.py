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
