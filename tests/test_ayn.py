import unittest

from tests.common import app  # noqa: F401
from PySide6.QtTest import QTest
from armadalive import ayn


class Button(unittest.TestCase):
    def setUp(self):
        ayn.HOLD_MS = 120
        self.b = ayn.AynButton()
        self.events = []
        self.b.pressed.connect(lambda: self.events.append("press"))
        self.b.longPressed.connect(lambda: self.events.append("long"))
        self.b.released.connect(lambda: self.events.append("tap"))

    def test_a_short_press_only_presses(self):
        self.b.inputEvent("ui_quick2", 1.0)
        self.b._hold.setInterval(120)
        QTest.qWait(40)
        self.b.inputEvent("ui_quick2", 0.0)
        QTest.qWait(200)
        self.assertEqual(self.events, ["press", "tap"])

    def test_a_hold_also_long_presses(self):
        self.b._hold.setInterval(120)
        self.b.inputEvent("ui_quick2", 1.0)
        QTest.qWait(250)
        self.b.inputEvent("ui_quick2", 0.0)   # letting go after a hold is not a tap
        self.assertEqual(self.events, ["press", "long"])

    def test_other_events_are_ignored(self):
        self.b.inputEvent("ui_quick1", 1.0)
        QTest.qWait(200)
        self.assertEqual(self.events, [])


if __name__ == "__main__":
    unittest.main()
