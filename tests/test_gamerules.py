import os, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

from tests.common import app
from tests.test_runtime import runtime_object, wait_for
from PySide6.QtCore import QObject, QTimer, Signal
from armadalive import gamerules, gamescope, system

GAME = dict(kind="game", key="snes/Super Game (EU)", system="snes", playing=True)


class FakeNow(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.state = dict(GAME)


class FakeGs(QObject):
    fpsLimitFinished = Signal(object, bool)
    fpsLimitRequested = Signal(object)
    def __init__(self):
        super().__init__()
        self.state, self.set = {"limit": 60}, []

    def setFpsLimit(self, fps):
        self.set.append(fps)
        request = len(self.set)
        self.fpsLimitRequested.emit(request)
        QTimer.singleShot(0, self, lambda: self.fpsLimitFinished.emit(request, True))
        return request

    def cancelFpsLimit(self, request):
        pass  # the test double dispatches every request immediately


class FakeSys(QObject):
    profileFinished = Signal(object, bool)
    profileRequested = Signal(object)
    stats = {"profile": "Eco"}

    def __init__(self):
        super().__init__()
        self.requests = []

    def setProfile(self, profile):
        self.requests.append(profile)
        request = len(self.requests)
        self.profileRequested.emit(request)
        QTimer.singleShot(0, self, lambda: self.profileFinished.emit(request, True))
        return request

    def cancelProfile(self, request):
        pass  # the test double dispatches every request immediately


class Rules(unittest.TestCase):
    def setUp(self):
        gamerules.CONFIG = os.path.join(tempfile.mkdtemp(), "rules.json")
        self.now, self.gs = FakeNow(), FakeGs()
        self.sys = FakeSys()
        self.rules = gamerules.GameRules(self.now, self.gs, self.sys)

    def test_a_rule_shows_the_name_of_its_game(self):
        class H:
            def title_of(self, key):
                return "Hades" if key == "steam/1145360" else ""
        self.rules.history = H()
        self.rules._rules = {"game:steam/1145360": dict(profile="Eco", fps=30), "game:snes/X": dict(profile="Eco", fps=0, title="Kept Title"), "system:snes": dict(profile="Eco", fps=0)}
        names = {r["key"]: (r["kind"], r["name"]) for r in self.rules.state["rules"]}
        self.assertEqual(names, {"game:steam/1145360": ("game", "Hades"), "game:snes/X": ("game", "Kept Title"), "system:snes": ("system", "snes")})

    def test_save_apply_and_forget(self):
        self.rules.toggle("game")
        self.assertEqual(self.rules.state["rules"], [dict(key="game:snes/Super Game (EU)", profile="Eco", fps=60, kind="game", name="snes/Super Game (EU)")])
        self.now.state = dict(GAME, playing=False); self.now.changed.emit()   # a game exits...
        self.now.state = dict(GAME); self.now.changed.emit()                  # ...and starts again
        self.assertEqual(self.sys.requests, ["Eco"])
        self.assertEqual(self.gs.set, [60])
        self.rules.toggle("game")
        self.assertEqual(self.rules.state["rules"], [])

    def test_a_system_rule_applies_to_every_game_of_that_system(self):
        self.rules.toggle("system")
        self.now.state = dict(GAME, key="snes/Another Game"); self.now.changed.emit()
        self.assertEqual(self.sys.requests, ["Eco"])

    def test_nothing_is_applied_while_browsing_or_when_switched_off(self):
        self.rules.toggle("system")
        self.now.state = dict(GAME, playing=False); self.now.changed.emit()
        self.rules.setEnabled(False)
        self.now.state = dict(GAME, key="snes/Other"); self.now.changed.emit()
        self.assertEqual(self.sys.requests, [])

    def test_rules_survive_a_restart(self):
        self.rules.toggle("game")
        again = gamerules.GameRules(self.now, self.gs, FakeSys())
        self.assertEqual(len(again.state["rules"]), 1)

    def test_base_rule_covers_games_without_a_rule_and_own_rules_win(self):
        FakeSys.stats = {"profile": "Eco"}
        self.rules.toggle("base")
        self.now.state = dict(GAME, key="snes/Unknown"); self.now.changed.emit()
        self.assertEqual(self.sys.requests, ["Eco"])
        FakeSys.stats = {"profile": "Performance"}
        self.now.state = dict(GAME, key="snes/Mine"); self.rules.toggle("game")   # own rule: Performance
        FakeSys.stats = {"profile": "Eco"}
        self.now.state = dict(GAME, key="snes/Other"); self.now.changed.emit()
        self.now.state = dict(GAME, key="snes/Mine"); self.now.changed.emit()
        self.assertEqual(self.sys.requests, ["Eco", "Eco", "Performance"])

    def test_idle_rule_applies_when_the_last_game_is_gone_not_while_steams_ui_is_in_front(self):
        FakeSys.stats = {"profile": "Eco"}
        self.rules.toggle("idle")
        self.now.state = dict(GAME); self.now.changed.emit()                       # a game runs (no rule for it)
        self.now.running = True
        self.now.state = dict(GAME, playing=False); self.now.changed.emit()       # Steam's UI in front, the game still runs
        self.assertEqual(self.sys.requests, [])
        self.now.running = False
        self.now.changed.emit()                                                   # now it is gone
        self.assertEqual(self.sys.requests, ["Eco"])
        app.processEvents()
        self.assertTrue(self.rules.state["loaded"].startswith("idle"))

    def test_saving_removing_and_loading_are_announced(self):
        seen = []
        self.rules.notice.connect(lambda code, detail: seen.append((code, detail)))
        self.rules.toggle("idle")
        self.rules.toggle("idle")
        self.rules.toggle("base")
        self.now.state = dict(GAME, key="snes/New"); self.now.changed.emit()
        app.processEvents()
        self.assertEqual([c for c, _ in seen], ["saved", "removed", "saved", "loaded"])
        self.assertIn("Eco", seen[2][1])


class ProfileRules(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(gamerules, "CONFIG", Path(directory, "rules.json")))
        self.enterContext(mock.patch.object(system, "Poller"))
        self.blocked = ""
        self.failed = ""
        self.entered, self.release = threading.Event(), threading.Event()
        self.completed, self.notices = [], []
        self.enterContext(mock.patch.object(system, "run", side_effect=self.run_command, create=True))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=lambda args, **_: self.completed.append(args[-1])))
        self.now = FakeNow()
        self.monitor = system.SystemMonitor()
        self.gs = FakeGs()
        self.rules = gamerules.GameRules(self.now, self.gs, self.monitor)
        self.rules.notice.connect(lambda code, detail: self.notices.append((code, detail)))
        self.rules._rules = {
            "game:snes/First": {"profile": "Performance"},
            "game:snes/Next": {"profile": "Balanced"},
            gamerules.IDLE: {"profile": "Eco"},
        }

    def tearDown(self):
        self.release.set()
        self.assertTrue(wait_for(lambda: not self.monitor._commands._running))

    def run_command(self, *args):
        name = args[-1]
        if name == self.blocked:
            self.entered.set()
            if not self.release.wait(3):
                raise TimeoutError("test did not release the profile command")
        if name == self.failed:
            raise OSError("profile unavailable")
        self.completed.append(name)

    def play(self, name):
        self.now.state = dict(GAME, key=f"snes/{name}", title=name)
        self.now.changed.emit()

    def test_older_blocked_manual_request_finishes_before_newer_rule(self):
        self.blocked = "Performance"
        self.monitor.setProfile("Performance")
        self.assertTrue(self.entered.wait(1))
        self.play("Next")
        self.assertEqual(self.completed, [])
        self.assertEqual(self.rules.state["loaded"], "")
        self.release.set()
        self.assertTrue(wait_for(lambda: not self.monitor._commands._running))
        self.assertEqual(self.completed, ["Performance", "Balanced"])
        self.assertEqual(self.notices, [("loaded", "Next · Balanced")])

    def test_idle_supersedes_a_running_rule_and_replaces_pending_rule(self):
        self.blocked = "Performance"
        self.play("First")
        self.assertTrue(self.entered.wait(1))
        self.play("Next")
        self.now.state = {"kind": "idle", "playing": False}
        self.now.changed.emit()
        self.release.set()
        self.assertTrue(wait_for(lambda: not self.monitor._commands._running))
        self.assertEqual(self.completed, ["Performance", "Eco"])
        self.assertEqual(self.notices, [("loaded", "idle · Eco")])
        self.assertEqual(self.rules.state["loaded"], "idle · Eco")

    def test_newer_manual_request_suppresses_stale_rule_notice(self):
        self.blocked = "Performance"
        self.play("First")
        self.assertTrue(self.entered.wait(1))
        self.monitor.setProfile("Eco")
        self.release.set()
        self.assertTrue(wait_for(lambda: not self.monitor._commands._running))
        self.assertEqual(self.completed, ["Performance", "Eco"])
        self.assertEqual(self.notices, [])
        self.assertEqual(self.rules.state["loaded"], "")

    def test_failed_current_rule_does_not_publish_a_loaded_profile(self):
        self.play("First")
        self.assertTrue(wait_for(lambda: not self.monitor._commands._running))
        self.assertEqual(self.rules.state["loaded"], "First · Performance")
        self.failed = "Balanced"
        self.play("Next")
        self.assertTrue(wait_for(lambda: not self.monitor._commands._running))
        self.assertEqual(self.completed, ["Performance"])
        self.assertEqual(self.notices[-1], ("failed", "Next · Balanced"))
        self.assertEqual(self.rules.state["loaded"], "")


class QueuedRules(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(gamerules, "CONFIG", Path(directory, "rules.json")))
        self.enterContext(mock.patch.object(system, "Poller"))
        self.enterContext(mock.patch.object(gamescope, "Poller"))
        self.enterContext(mock.patch.object(gamescope, "_read_fps"))
        self.enterContext(mock.patch.object(system, "run", side_effect=lambda *args: self.write("profile", args[-1], "Balanced")))
        self.enterContext(mock.patch.object(gamescope, "_set_limit", side_effect=lambda fps: self.write("display", fps, 120)))
        self.entered = {channel: threading.Event() for channel in ("profile", "display")}
        self.release = threading.Event()
        self.writes = {channel: [] for channel in self.entered}
        self.now = FakeNow()
        self.monitor = self.enterContext(runtime_object(system.SystemMonitor()))
        self.gs = self.enterContext(runtime_object(gamescope.Gamescope()))
        self.rules = self.enterContext(runtime_object(gamerules.GameRules(self.now, self.gs, self.monitor)))
        self.rules._rules = {f"game:{GAME['key']}": {"profile": "Eco", "fps": 60}}
        self.notices = []
        self.rules.notice.connect(lambda *notice: self.notices.append(notice))

    def write(self, channel, target, blocked):
        if target == blocked:
            self.entered[channel].set()
            self.release.wait(3)
        self.writes[channel].append(target)

    def queue_rule(self):
        self.monitor.setProfile("Balanced")
        self.gs.setFpsLimit(120)
        for event in self.entered.values():
            self.assertTrue(event.wait(1))
        self.now.changed.emit()

    def drain(self):
        self.release.set()
        self.assertTrue(wait_for(lambda: not self.monitor._commands._running and not self.gs._commands._running))

    def tearDown(self):
        self.drain()

    def test_disabling_rules_cancels_both_queued_rule_writes(self):
        profile_results, display_results = [], []
        self.monitor.profileFinished.connect(lambda *result: profile_results.append(result))
        self.gs.fpsLimitFinished.connect(lambda *result: display_results.append(result))
        self.queue_rule()
        self.rules.setEnabled(False)
        self.drain()
        self.assertEqual(self.writes, {"profile": ["Balanced"], "display": [120]})
        self.assertEqual(profile_results, [(1, True)])
        self.assertEqual(display_results, [(1, True)])
        self.assertEqual(self.notices, [])

    def test_new_rule_cancels_a_queued_setting_it_leaves_unspecified(self):
        self.rules._rules["game:snes/Next"] = {"profile": "Performance"}
        self.queue_rule()
        self.now.state = dict(GAME, key="snes/Next", title="Next")
        self.now.changed.emit()
        self.drain()
        self.assertEqual(self.writes, {"profile": ["Balanced", "Performance"], "display": [120]})
        self.assertEqual(self.notices, [("loaded", "Next · Performance")])

    def test_exit_cancels_queued_rule_write_and_keeps_newer_manual_request(self):
        self.queue_rule()
        self.monitor.setProfile("Performance")
        self.now.state = {"playing": False}
        self.now.changed.emit()
        self.drain()
        self.assertEqual(self.writes, {"profile": ["Balanced", "Performance"], "display": [120]})
        self.assertEqual(self.notices, [])

    def test_removing_current_rule_cancels_both_waiting_writes(self):
        self.queue_rule()
        self.rules.remove(f"game:{GAME['key']}")
        self.drain()
        self.assertEqual(self.writes, {"profile": ["Balanced"], "display": [120]})
        self.assertEqual([code for code, _ in self.notices], ["removed"])
        self.assertEqual(self.rules.state["loaded"], "")

    def test_toggling_off_current_system_rule_keeps_newer_manual_display_write(self):
        self.rules._rules = {"system:snes": {"profile": "Eco", "fps": 60}}
        self.queue_rule()
        self.gs.setFpsLimit(90)
        self.rules.toggle("system")
        self.drain()
        self.assertEqual(self.writes, {"profile": ["Balanced"], "display": [120, 90]})
        self.assertEqual(self.notices, [("removed", "snes")])
        self.assertEqual(self.rules.state["loaded"], "")

    def test_removing_unrelated_rule_leaves_current_waiting_writes(self):
        self.rules._rules["system:snes"] = {"profile": "Performance", "fps": 90}
        self.queue_rule()
        self.rules.remove("system:snes")
        self.drain()
        self.assertEqual(self.writes, {"profile": ["Balanced", "Eco"], "display": [120, 60]})
        self.assertEqual([code for code, _ in self.notices], ["removed", "loaded"])


class RuleAcknowledgments(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(gamerules, "CONFIG", Path(directory, "rules.json")))
        self.enterContext(mock.patch.object(QTimer, "singleShot"))
        self.enterContext(mock.patch("subprocess.Popen"))  # also safe against the old direct writer
        self.now, self.gs, self.sys = FakeNow(), FakeGs(), FakeSys()
        self.rules = gamerules.GameRules(self.now, self.gs, self.sys)
        self.notices = []
        self.rules.notice.connect(lambda *r: self.notices.append(r))

    def apply_rule(self, rule):
        key = f"game:{GAME['key']}"
        self.rules._rules[key] = rule
        self.rules._apply(key, "game")

    def test_frame_rate_only_rule_waits_for_its_own_real_command_acknowledgment(self):
        self.apply_rule({"fps": 60})
        self.assertEqual(self.notices, [])
        self.assertEqual(self.rules.state["loaded"], "")
        self.gs.fpsLimitFinished.emit(99, True)
        self.assertEqual(self.notices, [])
        self.gs.fpsLimitFinished.emit(1, True)
        self.assertEqual(self.notices, [("loaded", "game · –, 60 FPS")])

    def test_frame_rate_failure_cannot_be_hidden_by_profile_success(self):
        self.apply_rule({"profile": "Eco", "fps": 60})
        self.sys.profileFinished.emit(1, True)
        self.assertEqual(self.notices, [])
        self.gs.fpsLimitFinished.emit(1, False)
        self.assertEqual(self.notices, [("failed", "game · Eco, 60 FPS")])
        self.assertEqual(self.rules.state["loaded"], "")

    def test_both_commands_must_finish_even_when_display_finishes_first(self):
        self.apply_rule({"profile": "Eco", "fps": 60})
        self.gs.fpsLimitFinished.emit(1, True)
        self.assertEqual(self.notices, [])
        self.sys.profileFinished.emit(1, True)
        self.assertEqual(self.notices, [("loaded", "game · Eco, 60 FPS")])

    def test_new_manual_profile_invalidates_rule_after_its_profile_part_completed(self):
        self.apply_rule({"profile": "Eco", "fps": 60})
        self.sys.profileFinished.emit(1, True)
        self.sys.setProfile("Performance")
        self.gs.fpsLimitFinished.emit(1, True)
        self.assertEqual(self.notices, [])
        self.assertEqual(self.rules.state["loaded"], "")

    def test_new_manual_display_invalidates_rule_after_its_display_part_completed(self):
        self.apply_rule({"profile": "Eco", "fps": 60})
        self.gs.fpsLimitFinished.emit(1, True)
        self.gs.setFpsLimit(120)
        self.sys.profileFinished.emit(1, True)
        self.assertEqual(self.notices, [])

    def test_disabling_rules_or_game_exit_suppresses_pending_success(self):
        self.rules._applied = GAME["key"]
        self.apply_rule({"fps": 60})
        self.now.state = {"playing": False}
        self.now.changed.emit()
        self.gs.fpsLimitFinished.emit(1, True)
        self.assertEqual(self.notices, [])
        self.apply_rule({"fps": 60})
        self.rules.setEnabled(False)
        self.gs.fpsLimitFinished.emit(2, True)
        self.assertEqual(self.notices, [])


if __name__ == "__main__":
    unittest.main()


class RulePersistence(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "game_rules.json"
        self.enterContext(mock.patch.object(gamerules, "CONFIG", self.path))

    def make(self):
        return gamerules.GameRules(FakeNow(), FakeGs(), FakeSys())

    def test_malformed_rules_recover_valid_backup_and_optional_local_values(self):
        import json
        saved = {"rules": {"game:legacy/name": {"profile": "Eco", "fps": 45.5, "res": 7, "extra": True}},
                 "base": {"psp": "2", "gc": None}, "future": {"value": 4}}
        self.path.write_text('{"rules":{"game:bad":null}}')
        self.path.with_suffix(".json.bak").write_text(json.dumps(saved))
        rules = self.make()
        self.assertEqual(rules.state["rules"][0]["key"], "game:legacy/name")
        rules.setEnabled(False)
        persisted = json.loads(self.path.read_text())
        self.assertEqual(persisted["rules"], saved["rules"])
        self.assertEqual(persisted["base"], saved["base"])
        self.assertEqual(persisted["future"], saved["future"])

    def test_invalid_nested_rules_default_safely_without_a_backup(self):
        for content in ('{"rules":null}', '{"rules":{"game:a":[]}}', '{"rules":{"game:a":{"fps":"oops"}}}', '{"base":[]}'):
            with self.subTest(content=content):
                self.path.write_text(content)
                self.assertEqual(self.make().state["rules"], [])

    def test_atomic_save_preserves_symlink_mode_and_last_valid_configuration(self):
        import json
        from armadalive import persistence
        target = self.root / "actual"
        original = b'{ "rules":{}, "base":{"psp":"2"} }'
        target.write_bytes(original)
        target.chmod(0o640)
        self.path.symlink_to(target.name)
        rules = self.make()
        notifications = []
        rules.changed.connect(lambda: notifications.append(True))
        replace = os.replace

        def fail_primary(source, dest):
            if Path(dest) == target:
                raise OSError("primary replace failed")
            return replace(source, dest)

        with mock.patch.object(persistence.os, "replace", side_effect=fail_primary):
            with self.assertRaisesRegex(OSError, "primary replace failed"):
                rules.toggle("game")
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(notifications, [])
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        rules.setEnabled(False)
        self.assertFalse(json.loads(target.read_text())["enabled"])
        self.assertEqual(json.loads(target.read_text())["base"], {"psp": "2"})
        self.assertEqual(Path(str(target) + ".bak").read_bytes(), original)
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_freeze_blocks_all_edits_and_defers_rule_checks_until_resume(self):
        rules = self.make()
        rules.toggle("game")
        previous = self.path.read_bytes()
        rules.pauseWrites(restoring=True)
        rules.toggle("idle")
        rules.cycleRes()
        rules.remove(rules.state["gameKey"])
        rules.setEnabled(False)
        with mock.patch.object(rules, "_emulator") as emulator:
            rules._check()
            self.assertEqual(self.path.read_bytes(), previous)
            self.assertTrue(rules.state["writesPaused"])
            self.assertTrue(rules.state["enabled"])
            self.assertFalse(rules.writesPending())
            emulator.assert_not_called()
            rules.resumeWrites()
            emulator.assert_called_once()
        self.assertFalse(rules.state["writesPaused"])
        rules.setEnabled(False)
        self.assertNotEqual(self.path.read_bytes(), previous)

    def test_pause_persists_live_device_originals_before_backup_cutoff(self):
        import json
        rules = self.make()
        rules._base = {"psp": "device original"}
        rules.pauseWrites(restoring=True)
        self.assertEqual(json.loads(self.path.read_text())["base"], rules._base)
        rules.resumeWrites()
        # A second export can read an unchanged configuration without rewriting it.
        with mock.patch.object(gamerules.persistence, "write_json", side_effect=AssertionError("unexpected rewrite")):
            rules.pauseWrites()
        rules.resumeWrites()

    def test_export_uses_valid_recovered_rules(self):
        import json
        from armadalive import backup
        self.path.write_text('{broken')
        self.path.with_suffix(".json.bak").write_text('{"rules":{},"enabled":false,"base":{"psp":"2"}}')
        rules = self.make()
        archive = self.root / "archive.json"
        with mock.patch.object(backup, "CONFIG_DIR", str(self.root)), mock.patch.object(backup, "FILE", str(archive)):
            coordinator = backup.Backup((rules,))
            coordinator.save()
            self.assertEqual(coordinator.state["message"], "saved")
        saved = json.loads(archive.read_text())["files"]["game_rules.json"]
        self.assertEqual(saved, {"rules": {}, "enabled": False})
        self.assertEqual(json.loads(self.path.read_text())["base"], {"psp": "2"})

    def test_slow_export_keeps_prelaunch_emulator_rules_active(self):
        from armadalive import backup, emusettings
        self.path.write_text('{"rules":{"game:psp/Game":{"res":4}}}')
        ini = self.root / "ppsspp.ini"
        ini.write_text("[Graphics]\nInternalResolution = 2\n")
        now = FakeNow()
        rules = gamerules.GameRules(now, FakeGs(), FakeSys())
        stalled = mock.Mock(writesPending=mock.Mock(return_value=True))
        with mock.patch.object(backup, "CONFIG_DIR", str(self.root)), \
                mock.patch.object(backup, "FILE", str(self.root / "archive.json")), \
                mock.patch.dict(emusettings.SPECS, {"psp": (ini, "Graphics", "InternalResolution", "{}")}):
            coordinator = backup.Backup((rules, stalled))
            self.addCleanup(lambda: coordinator._drain.stop())
            coordinator.save()
            self.assertTrue(coordinator.state["busy"])
            now.state = dict(kind="game", key="psp/Game", system="psp", playing=False)
            now.changed.emit()
            self.assertEqual(emusettings.read("psp"), "4")
            now.state["playing"] = True
            now.changed.emit()
            stalled.writesPending.return_value = False
            coordinator._check_writers()
        self.assertEqual(coordinator.state["message"], "saved")

    def test_invalid_rules_keep_independently_valid_primary_originals_on_ordinary_save(self):
        import json
        self.path.write_text('{"rules":null,"base":{"psp":"device-original"}}')
        self.path.with_suffix(".json.bak").write_text('{"rules":{},"base":{"psp":"older-original"}}')
        rules = self.make()
        self.assertEqual(rules.state["rules"], [])
        rules.setEnabled(False)
        self.assertEqual(json.loads(self.path.read_text())["base"], {"psp": "device-original"})

    def test_unusable_originals_block_save_and_backup_without_erasing_evidence(self):
        from armadalive import backup
        original = b'{"rules":null,"base":{"psp":["damaged-original"]}}'
        self.path.write_bytes(original)
        rules = self.make()
        with self.assertRaisesRegex(ValueError, "original"):
            rules.setEnabled(False)
        self.assertEqual(self.path.read_bytes(), original)
        archive = self.root / "archive.json"
        archive.write_text('{"files":{"game_rules.json":{"rules":{}}}}')
        with mock.patch.object(backup, "CONFIG_DIR", str(self.root)), mock.patch.object(backup, "FILE", str(archive)):
            coordinator = backup.Backup((rules,))
            coordinator.restore()
            self.assertIn("original", coordinator.state["message"])
            self.assertFalse(coordinator.state["busy"])
        self.assertEqual(self.path.read_bytes(), original)
