import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from tests.common import app  # noqa: F401
from PySide6.QtCore import QObject, Signal
from armadalive import backup, emusettings, gamerules

GAME = dict(kind="game", key="snes/Super Game (EU)", system="snes", playing=True)


class FakeNow(QObject):
    changed = Signal()
    legacyRulesChanged = Signal()

    def __init__(self):
        super().__init__()
        self.state = dict(GAME)
        self.watched = set()
        self.proofs = {}

    def watch_legacy_rules(self, keys):
        self.watched = set(keys)

    def legacy_rule_identity(self, key):
        return self.proofs.get(key, "")

    def esde_launch_state(self, system, path, title):
        relative = os.path.relpath(path, f"/roms/{system}")
        key = f"esde:{system}/{relative}"
        legacy = f"{system}/{Path(path).stem}"
        proven = self.legacy_rule_identity(legacy)
        return dict(kind="game", playing=False, system=system, path=path, title=title, key=key,
                    legacyKey=legacy if proven == key else "", legacyPending=proven is None)


class FakeGs:
    def __init__(self):
        self.state, self.set = {"limit": 60}, []

    def setFpsLimit(self, fps):
        self.set.append(fps)


class FakeSys:
    stats = {"profile": "Eco"}


class Rules(unittest.TestCase):
    def setUp(self):
        gamerules.CONFIG = os.path.join(tempfile.mkdtemp(), "rules.json")
        self.now, self.gs = FakeNow(), FakeGs()
        self.esde_requests = []
        self.rules = gamerules.GameRules(self.now, self.gs, FakeSys())

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
        with mock.patch("subprocess.Popen") as popen:
            self.now.state = dict(GAME, playing=False); self.now.changed.emit()   # a game exits...
            self.now.state = dict(GAME); self.now.changed.emit()                  # ...and starts again
        self.assertEqual(popen.call_args[0][0], ["armada-power", "profile", "Eco"])
        self.assertEqual(self.gs.set, [60])
        self.rules.toggle("game")
        self.assertEqual(self.rules.state["rules"], [])

    def test_a_system_rule_applies_to_every_game_of_that_system(self):
        self.rules.toggle("system")
        with mock.patch("subprocess.Popen") as popen:
            self.now.state = dict(GAME, key="snes/Another Game"); self.now.changed.emit()
        self.assertEqual(popen.call_args[0][0], ["armada-power", "profile", "Eco"])

    def test_nothing_is_applied_while_browsing_or_when_switched_off(self):
        self.rules.toggle("system")
        with mock.patch("subprocess.Popen") as popen:
            self.now.state = dict(GAME, playing=False); self.now.changed.emit()
            self.rules.setEnabled(False)
            self.now.state = dict(GAME, key="snes/Other"); self.now.changed.emit()
        popen.assert_not_called()

    def test_rules_survive_a_restart(self):
        self.rules.toggle("game")
        again = gamerules.GameRules(self.now, self.gs, FakeSys())
        self.assertEqual(len(again.state["rules"]), 1)

    def test_base_rule_covers_games_without_a_rule_and_own_rules_win(self):
        FakeSys.stats = {"profile": "Eco"}
        self.rules.toggle("base")
        with mock.patch("subprocess.Popen") as popen:
            self.now.state = dict(GAME, key="snes/Unknown"); self.now.changed.emit()
        self.assertEqual(popen.call_args[0][0], ["armada-power", "profile", "Eco"])
        FakeSys.stats = {"profile": "Performance"}
        self.now.state = dict(GAME, key="snes/Mine"); self.rules.toggle("game")   # own rule: Performance
        FakeSys.stats = {"profile": "Eco"}
        with mock.patch("subprocess.Popen") as popen:
            self.now.state = dict(GAME, key="snes/Other"); self.now.changed.emit()
            self.now.state = dict(GAME, key="snes/Mine"); self.now.changed.emit()
        self.assertEqual([c[0][0][2] for c in popen.call_args_list], ["Eco", "Performance"])

    def test_idle_rule_applies_when_the_last_game_is_gone_not_while_steams_ui_is_in_front(self):
        FakeSys.stats = {"profile": "Eco"}
        self.rules.toggle("idle")
        with mock.patch("subprocess.Popen") as popen:
            self.now.state = dict(GAME); self.now.changed.emit()                       # a game runs (no rule for it)
            self.now.running = True
            self.now.state = dict(GAME, playing=False); self.now.changed.emit()       # Steam's UI in front, the game still runs
            popen.assert_not_called()
            self.now.running = False
            self.now.changed.emit()                                                   # now it is gone
        self.assertEqual(popen.call_args[0][0], ["armada-power", "profile", "Eco"])
        self.assertTrue(self.rules.state["loaded"].startswith("idle"))

    def test_saving_removing_and_loading_are_announced(self):
        seen = []
        self.rules.notice.connect(lambda code, detail: seen.append((code, detail)))
        self.rules.toggle("idle")
        self.rules.toggle("idle")
        self.rules.toggle("base")
        with mock.patch("subprocess.Popen"):
            self.now.state = dict(GAME, key="snes/New"); self.now.changed.emit()
        self.assertEqual([c for c, _ in seen], ["saved", "removed", "saved", "loaded"])
        self.assertIn("Eco", seen[2][1])

    def set_esde(self, relative, **details):
        path = f"/roms/snes/{relative}"
        self.now.state = dict(GAME, key=f"esde:snes/{relative}", path=path, **details)
        with mock.patch("subprocess.Popen", side_effect=lambda args, **_: self.esde_requests.append(args[-1])):
            self.now.changed.emit()

    def test_unique_legacy_rule_loads_after_metadata_and_moves_to_canonical_key(self):
        legacy = "game:snes/Original"
        canonical = "game:esde:snes/sub/Original.zip"
        self.rules._rules = {legacy: {"profile": "Performance"}, gamerules.BASE: {"profile": "Eco"}}
        self.rules._save()
        self.set_esde("sub/Original.zip", metadataPending=True)
        self.assertEqual(self.esde_requests, [])
        self.set_esde("sub/Original.zip", legacyKey="snes/Original")
        self.set_esde("sub/Original.zip", legacyKey="snes/Original", title="Enriched title")
        self.assertEqual(self.esde_requests, ["Performance"])
        self.assertEqual(self.rules.state["gameKey"], canonical)
        with open(gamerules.CONFIG) as stream:
            saved = json.load(stream)["rules"]
        self.assertNotIn(legacy, saved)
        self.assertEqual(saved[canonical], {"profile": "Performance"})

    def test_same_basename_in_another_directory_does_not_claim_ambiguous_rule(self):
        legacy = "game:snes/Original"
        self.rules._rules = {legacy: {"profile": "Performance"}, gamerules.BASE: {"profile": "Eco"}}
        self.set_esde("one/Original.zip", metadataPending=True)
        self.assertEqual(self.esde_requests, [])
        self.set_esde("one/Original.zip")
        self.set_esde("two/Original.zip", metadataPending=True)
        self.set_esde("two/Original.zip")
        self.assertEqual(self.esde_requests, ["Eco", "Eco"])
        self.assertIn(legacy, self.rules._rules)

    def test_canonical_rule_wins_and_is_not_repeated_when_alias_arrives(self):
        legacy = "game:snes/Original"
        canonical = "game:esde:snes/sub/Original.zip"
        self.rules._rules = {legacy: {"profile": "Performance"}, canonical: {"profile": "Balanced"}}
        self.set_esde("sub/Original.zip", metadataPending=True)
        self.assertEqual(self.esde_requests, ["Balanced"])
        self.set_esde("sub/Original.zip", legacyKey="snes/Original")
        self.assertEqual(self.esde_requests, ["Balanced"])
        self.assertIn(legacy, self.rules._rules)
        self.rules.toggle("game")
        self.assertEqual(self.rules.state["rules"], [])

    def test_migration_write_failure_keeps_legacy_rule_usable(self):
        legacy = "game:snes/Original"
        self.rules._rules = {legacy: {"profile": "Performance"}}
        self.rules._save()
        with mock.patch("os.replace", side_effect=OSError("rules could not be saved")), \
                self.assertLogs("armadalive.gamerules", level="WARNING"):
            self.set_esde("sub/Original.zip", legacyKey="snes/Original")
        self.assertEqual(self.rules.state["gameKey"], legacy)
        self.assertEqual(self.esde_requests, ["Performance"])
        with open(gamerules.CONFIG) as stream:
            self.assertEqual(list(json.load(stream)["rules"]), [legacy])

    def test_browsing_notifies_game_scope_when_identity_changes(self):
        seen = []
        self.rules.changed.connect(lambda: seen.append(self.rules.state["gameKey"]))
        self.now.state = dict(GAME, playing=False, key="esde:snes/sub/Next.zip")
        self.now.changed.emit()
        self.assertEqual(seen, ["game:esde:snes/sub/Next.zip"])


class EmulatorRules(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = root / "game_rules.json"
        self.undo = root / "emulator_undo.json"
        self.actual = root / "graphics.ini"
        self.actual.write_bytes(b"[Graphics]\r\nResolution=2\r\nOther=unchanged\r\n")
        symlink = root / "symlink.ini"
        symlink.symlink_to(self.actual.name)
        self.enterContext(mock.patch.object(gamerules, "CONFIG", self.config))
        rules = {"game:gc/Fixture": {"res": 4}, "game:wii/Fixture": {"res": 5}}
        self.config.write_text(json.dumps({"rules": rules}))
        self.enterContext(mock.patch.dict(emusettings.SPECS, {
            "gc": (symlink, "Graphics", "Resolution", "{}.0"),
            "wii": (self.actual, "Graphics", "Resolution", "{}.0"),
        }))
        self.now = FakeNow()
        self.rules = gamerules.GameRules(self.now, FakeGs(), FakeSys())

    def select(self, game="Fixture", system="gc", playing=False):
        self.now.state = dict(kind="game", key=f"{system}/{game}", system=system, playing=playing)
        self.now.changed.emit()

    def test_restart_recovers_aliased_emulator_with_exact_original_value(self):
        before = self.actual.read_bytes()
        self.select()
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.select(system="wii")
        self.assertEqual(emusettings.read("gc"), "5.0")
        self.assertTrue(self.undo.exists())
        gamerules.GameRules(FakeNow(), FakeGs(), FakeSys())
        self.assertEqual(self.actual.read_bytes(), before)
        self.assertFalse(self.undo.exists())

    def test_no_external_write_when_undo_cannot_be_saved(self):
        before = self.actual.read_bytes()
        real_replace = os.replace

        def fail_journal(source, target):
            if Path(target) == self.undo:
                raise OSError("cannot save original")
            real_replace(source, target)

        with mock.patch("os.replace", side_effect=fail_journal), \
                self.assertLogs("armadalive.gamerules", level="WARNING"):
            self.select()
        self.assertEqual(self.actual.read_bytes(), before)
        self.assertFalse(self.undo.exists())

    def test_restoration_failure_keeps_original_for_retry(self):
        before = self.actual.read_bytes()
        self.select()
        real_replace = os.replace

        def fail_restore(source, target):
            if Path(target) == self.actual:
                raise OSError("config unavailable")
            real_replace(source, target)

        with mock.patch("os.replace", side_effect=fail_restore), \
                self.assertLogs("armadalive.gamerules", level="WARNING"):
            self.select(game="Unruled")
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.assertTrue(self.undo.exists())
        self.select(game="Unruled")
        self.assertEqual(self.actual.read_bytes(), before)
        self.assertFalse(self.undo.exists())

    def lose_undo_during_clear(self):
        self.select()
        remove = gamerules.persistence.remove

        def fail_after_unlink(path):
            remove(path)
            raise OSError("undo directory sync failed")

        with mock.patch.object(gamerules.persistence, "remove", side_effect=fail_after_unlink), \
                self.assertLogs("armadalive.gamerules", level="WARNING"):
            self.select(game="Unruled")
        self.assertFalse(self.undo.exists())
        self.assertEqual(emusettings.read("gc"), "2")

    def test_failed_undo_clear_recommits_original_before_next_override(self):
        self.lose_undo_during_clear()
        self.select()
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.assertTrue(self.undo.exists())
        gamerules.GameRules(FakeNow(), FakeGs(), FakeSys())
        self.assertEqual(emusettings.read("gc"), "2")

    def test_uncertain_undo_suppresses_override_when_repair_fails(self):
        self.lose_undo_during_clear()
        with mock.patch.object(gamerules.persistence, "write_json", side_effect=OSError("undo unavailable")), \
                self.assertLogs("armadalive.gamerules", level="WARNING"):
            self.select()
        self.assertEqual(emusettings.read("gc"), "2")

    def test_failed_undo_shrink_repairs_all_retained_targets_before_override(self):
        alternate = self.actual.with_name("other.ini")
        alternate.write_text("[Graphics]\nResolution=3\n")
        self.rules._rules["game:psp/Fixture"] = {"res": 5}
        write_json = gamerules.persistence.write_json
        replace = os.replace

        def block_gc_restore(source, target):
            if Path(target) == self.actual:
                raise OSError("emulator config unavailable")
            replace(source, target)

        def fail_after_shrink(path, data, **kwargs):
            write_json(path, data, **kwargs)
            if Path(path) == self.undo and len(data) == 1:
                raise OSError("undo directory sync failed")

        with mock.patch.dict(emusettings.SPECS, {"psp": (alternate, "Graphics", "Resolution", "{}")}):
            self.select()
            with mock.patch("os.replace", side_effect=block_gc_restore), \
                    self.assertLogs("armadalive.gamerules", level="WARNING"):
                self.select(system="psp")
            with mock.patch.object(gamerules.persistence, "write_json", side_effect=fail_after_shrink), \
                    self.assertLogs("armadalive.gamerules", level="WARNING"):
                self.select()
            self.assertEqual(len(json.loads(self.undo.read_text())), 1)
            with mock.patch("os.replace", side_effect=block_gc_restore), \
                    self.assertLogs("armadalive.gamerules", level="WARNING"):
                self.select(system="psp")
            self.assertEqual(emusettings.read("psp"), "5")
            gamerules.GameRules(FakeNow(), FakeGs(), FakeSys())
            self.assertEqual(emusettings.read("psp"), "3")

    def test_disable_and_switch_away_restore_resolution(self):
        self.select()
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.rules.setEnabled(False)
        self.assertEqual(emusettings.read("gc"), "2")
        self.rules.setEnabled(True)
        self.select()
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.select(system="snes")
        self.assertEqual(emusettings.read("gc"), "2")

    def test_legacy_local_original_is_recovered_once(self):
        self.actual.write_text("[Graphics]\nResolution=4.0\n")
        self.config.write_text(json.dumps({"base": {"gc": "2"}}))
        gamerules.GameRules(FakeNow(), FakeGs(), FakeSys())
        self.assertEqual(emusettings.read("gc"), "2")
        self.assertNotIn("base", json.loads(self.config.read_text()))
        self.assertFalse(self.undo.exists())
        emusettings.write("gc", 3)
        gamerules.GameRules(FakeNow(), FakeGs(), FakeSys())
        self.assertEqual(emusettings.read("gc"), "3.0")

    def test_legacy_resolution_ready_before_first_owned_launch_without_metadata(self):
        path = "/roms/gc/sub/Fixture.iso"
        self.assertIn("gc/Fixture", self.now.watched)
        self.now.proofs["gc/Fixture"] = None
        self.assertIsNone(self.rules.prepare_esde_launch("gc", path, "Fixture"))
        self.assertEqual(emusettings.read("gc"), "2")
        self.now.proofs["gc/Fixture"] = "esde:gc/sub/Fixture.iso"
        self.now.legacyRulesChanged.emit()
        self.assertNotIn("game:gc/Fixture", json.loads(self.config.read_text())["rules"])
        self.assertEqual(self.rules.prepare_esde_launch("gc", path, "Fixture"), "")
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.assertTrue(self.undo.exists())
        self.assertEqual(self.rules.prepare_esde_launch("gc", path, "Fixture"), "")

    def test_prelaunch_reports_failure_without_applying_unjournaled_resolution(self):
        path = "/roms/gc/sub/Fixture.iso"
        self.now.proofs["gc/Fixture"] = "esde:gc/sub/Fixture.iso"
        with mock.patch.object(gamerules.persistence, "write_json", side_effect=OSError("disk unavailable")), \
                self.assertLogs("armadalive.gamerules", level="WARNING"):
            self.assertEqual(self.rules.prepare_esde_launch("gc", path, "Fixture"), "Could not apply emulator resolution")
        self.assertEqual(emusettings.read("gc"), "2")

    def test_prelaunch_does_not_edit_emulator_while_backup_pauses_writes(self):
        self.rules.pauseWrites()
        self.assertEqual(self.rules.prepare_esde_launch("gc", "/roms/gc/Fixture.iso", "Fixture"),
                         "Game rules are paused during backup")
        self.assertEqual(emusettings.read("gc"), "2")

    def test_pending_profile_only_rule_does_not_hold_emulator_launch(self):
        self.rules._rules["game:gc/Fixture"] = {"profile": "Eco"}
        self.now.proofs["gc/Fixture"] = None
        self.assertEqual(self.rules.prepare_esde_launch("gc", "/roms/gc/Fixture.iso", "Fixture"), "")

    def test_foreground_metadata_cannot_undo_prepared_resolution_before_start(self):
        self.select(game="Unruled")
        path = "/roms/gc/sub/Fixture.iso"
        self.now.proofs["gc/Fixture"] = "esde:gc/sub/Fixture.iso"
        self.assertEqual(self.rules.prepare_esde_launch("gc", path, "Fixture"), "")
        self.now.state = dict(self.now.state, title="Unrelated metadata completed")
        self.now.changed.emit()
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.now.state = dict(self.now.esde_launch_state("gc", path, "Fixture"), playing=True)
        self.now.changed.emit()
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.select(game="Unruled")
        self.assertEqual(emusettings.read("gc"), "2")

    def test_unobserved_launch_releases_override_when_startup_window_expires(self):
        self.select(game="Unruled")
        self.now.proofs["gc/Fixture"] = "esde:gc/Fixture.iso"
        self.assertEqual(self.rules.prepare_esde_launch("gc", "/roms/gc/Fixture.iso", "Fixture"), "")
        self.assertEqual(emusettings.read("gc"), "4.0")
        self.rules._launch_hold.timeout.emit()
        self.assertEqual(emusettings.read("gc"), "2")

    def test_late_resolution_proof_notifies_once_without_editing_running_game(self):
        seen = []
        self.rules.notice.connect(lambda code, detail: seen.append((code, detail)))
        path = "/roms/gc/sub/Fixture.iso"
        self.now.proofs["gc/Fixture"] = None
        self.now.state = dict(self.now.esde_launch_state("gc", path, "Fixture"), playing=True)
        self.now.changed.emit()
        self.now.proofs["gc/Fixture"] = "esde:gc/sub/Fixture.iso"
        self.now.legacyRulesChanged.emit()
        self.now.state = dict(self.now.esde_launch_state("gc", path, "Fixture"), playing=True)
        self.now.changed.emit()
        self.assertEqual(seen.count(("resolutionNextLaunch", "Fixture")), 1)
        self.assertEqual(emusettings.read("gc"), "2")
        self.assertFalse(self.undo.exists())


class BackupRules(unittest.TestCase):
    legacy = "game:snes/Original"
    canonical = "game:esde:snes/sub/Original.zip"

    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = directory / "game_rules.json"
        self.tiles = directory / "tiles.json"
        self.archive = directory / "backup.json"
        self.journal = directory / backup.JOURNAL
        self.enterContext(mock.patch.object(gamerules, "CONFIG", self.config))
        self.enterContext(mock.patch.object(backup, "CONFIG_DIR", directory))
        self.enterContext(mock.patch.object(backup, "FILE", self.archive))
        self.config.write_text(json.dumps({"rules": {self.legacy: {"profile": "Eco"}}}))
        self.tiles.write_text('{ "order": ["before"] }\n')
        self.now = FakeNow()
        self.rules = gamerules.GameRules(self.now, FakeGs(), FakeSys())
        self.now.state = dict(GAME, playing=False, key=self.canonical[5:], metadataPending=True)
        self.now.changed.emit()
        self.restored = {"rules": {gamerules.BASE: {"profile": "Balanced"}}}
        self.archive.write_text(json.dumps({"files": {"game_rules.json": self.restored, "tiles.json": {"order": ["after"]}}}))

    def complete_identity(self):
        self.now.proofs[self.legacy[5:]] = self.canonical[5:]
        self.now.legacyRulesChanged.emit()
        self.now.state = dict(self.now.state, metadataPending=False, legacyKey="snes/Original")
        self.now.changed.emit()

    def restore(self):
        coordinator = backup.Backup((self.rules,))
        with mock.patch.object(backup.QTimer, "singleShot") as restart:
            coordinator.restore()
        self.assertEqual(coordinator.state["message"], "restored")
        return coordinator, restart.call_args.args[1]

    def test_restored_rules_are_frozen_through_restart(self):
        coordinator, restart = self.restore()
        self.complete_identity()
        self.assertEqual(json.loads(self.config.read_text()), self.restored)
        self.assertTrue(self.rules.state["writesPaused"])
        self.rules.toggle("game")
        self.rules.remove(self.legacy)
        self.rules.setEnabled(False)
        self.assertEqual(json.loads(self.config.read_text()), self.restored)
        self.assertTrue(self.journal.exists())
        with mock.patch.object(backup.os, "execv") as execv:
            restart()
        execv.assert_called_once()
        self.assertFalse(self.journal.exists())
        self.assertTrue(coordinator.state["busy"])

    def test_failed_restart_undoes_all_replacements_before_replaying_identity(self):
        coordinator, restart = self.restore()
        self.complete_identity()
        with mock.patch.object(backup.os, "execv", side_effect=OSError("cannot restart")):
            restart()
        self.assertEqual(coordinator.state["message"], "cannot restart")
        self.assertEqual(self.tiles.read_text(), '{ "order": ["before"] }\n')
        self.assertEqual(json.loads(self.config.read_text())["rules"], {self.canonical: {"profile": "Eco"}})
        self.assertFalse(self.rules.state["writesPaused"])
        self.assertFalse(self.journal.exists())

    def test_failed_restart_rollback_can_retry_before_writers_resume(self):
        coordinator, restart = self.restore()
        replace = os.replace

        def fail_rules_rollback(source, target):
            if Path(target) == self.config:
                raise OSError("cannot restore rules")
            replace(source, target)

        with mock.patch.object(backup.os, "execv", side_effect=OSError("cannot restart")), \
                mock.patch("os.replace", side_effect=fail_rules_rollback):
            restart()
        self.assertIn("cannot restore rules", coordinator.state["message"])
        self.complete_identity()
        self.assertEqual(json.loads(self.config.read_text()), self.restored)
        self.assertTrue(self.journal.exists())
        coordinator.save()
        self.assertEqual(coordinator.state["message"], "saved")
        exported = json.loads(self.archive.read_text())["files"]
        self.assertEqual(exported["game_rules.json"]["rules"], {self.legacy: {"profile": "Eco"}})
        self.assertEqual(json.loads(self.config.read_text())["rules"], {self.canonical: {"profile": "Eco"}})
        self.assertFalse(self.rules.state["writesPaused"])
        self.assertFalse(self.journal.exists())

    def test_failed_restore_resumes_pending_identity_callback(self):
        self.archive.write_text('{"not": "a backup"}')
        waiting = mock.Mock()
        waiting.writesPending.return_value = True
        coordinator = backup.Backup((self.rules, waiting))
        coordinator.restore()
        self.complete_identity()
        self.assertEqual(json.loads(self.config.read_text())["rules"], {self.legacy: {"profile": "Eco"}})
        waiting.writesPending.return_value = False
        coordinator._check_writers()
        self.assertEqual(coordinator.state["message"], "not an ArmadaLive backup")
        self.assertEqual(json.loads(self.config.read_text())["rules"], {self.canonical: {"profile": "Eco"}})


if __name__ == "__main__":
    unittest.main()
