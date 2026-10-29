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

    def test_save_apply_and_forget(self):
        self.rules.toggle("game")
        self.assertEqual(self.rules.state["rules"], [dict(key="game:snes/Super Game (EU)", profile="Eco", fps=60)])
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


if __name__ == "__main__":
    unittest.main()
