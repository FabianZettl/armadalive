import os, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

from tests.common import app, wait_for
from PySide6.QtCore import QObject, QTimer, Signal
from armadalive import gamerules, system

GAME = dict(kind="game", key="snes/Super Game (EU)", system="snes", playing=True)


class FakeNow(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.state = dict(GAME)


class FakeGs:
    def __init__(self):
        self.state, self.set = {"limit": 60}, []

    def setFpsLimit(self, fps):
        self.set.append(fps)


class FakeSys(QObject):
    profileFinished = Signal(object, bool)
    stats = {"profile": "Eco"}

    def __init__(self):
        super().__init__()
        self.requests = []

    def setProfile(self, profile):
        self.requests.append(profile)
        request = len(self.requests)
        QTimer.singleShot(0, self, lambda: self.profileFinished.emit(request, True))
        return request


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
        self.enterContext(mock.patch.object(system, "run", side_effect=self.run_command))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=lambda args, **_: self.completed.append(args[-1])))
        self.now = FakeNow()
        self.monitor = system.SystemMonitor()
        self.rules = gamerules.GameRules(self.now, FakeGs(), self.monitor)
        self.rules.notice.connect(lambda code, detail: self.notices.append((code, detail)))
        self.rules._rules = {
            "game:snes/First": {"profile": "Performance"},
            "game:snes/Next": {"profile": "Balanced"},
            gamerules.IDLE: {"profile": "Eco"},
        }

    def tearDown(self):
        self.release.set()
        wait_for(lambda: not self.monitor._commands._running)

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
        wait_for(lambda: not self.monitor._commands._running)
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
        wait_for(lambda: not self.monitor._commands._running)
        self.assertEqual(self.completed, ["Performance", "Eco"])
        self.assertEqual(self.notices, [("loaded", "idle · Eco")])
        self.assertEqual(self.rules.state["loaded"], "idle · Eco")

    def test_newer_manual_request_suppresses_stale_rule_notice(self):
        self.blocked = "Performance"
        self.play("First")
        self.assertTrue(self.entered.wait(1))
        self.monitor.setProfile("Eco")
        self.release.set()
        wait_for(lambda: not self.monitor._commands._running)
        self.assertEqual(self.completed, ["Performance", "Eco"])
        self.assertEqual(self.notices, [])
        self.assertEqual(self.rules.state["loaded"], "")

    def test_failed_current_rule_does_not_publish_a_loaded_profile(self):
        self.play("First")
        wait_for(lambda: not self.monitor._commands._running)
        self.assertEqual(self.rules.state["loaded"], "First · Performance")
        self.failed = "Balanced"
        self.play("Next")
        wait_for(lambda: not self.monitor._commands._running)
        self.assertEqual(self.completed, ["Performance"])
        self.assertEqual(self.notices[-1], ("failed", "Next · Balanced"))
        self.assertEqual(self.rules.state["loaded"], "")


if __name__ == "__main__":
    unittest.main()
