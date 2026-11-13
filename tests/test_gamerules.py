import os, tempfile, unittest
from unittest import mock

from tests.common import app, Fake  # noqa: F401
from PySide6.QtCore import QObject, Signal
from armadalive import gamerules

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


class FakeSys:
    stats = {"profile": "Eco"}


class Rules(unittest.TestCase):
    def setUp(self):
        gamerules.CONFIG = os.path.join(tempfile.mkdtemp(), "rules.json")
        self.now, self.gs = FakeNow(), FakeGs()
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


if __name__ == "__main__":
    unittest.main()
