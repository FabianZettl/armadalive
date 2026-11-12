import unittest

from tests.common import app  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer

from armadalive import activity


class Seen(unittest.TestCase):
    def setUp(self):
        self.target, self.act, self.count = QObject(), activity.Activity(), []
        self.act.seen.connect(lambda: self.count.append(1))
        self.act.watch(self.target)

    def send(self, kind):
        QCoreApplication.sendEvent(self.target, QEvent(kind))

    def test_a_touch_or_click_going_down_or_up_and_a_key_always_count(self):
        for kind in (QEvent.Type.TouchBegin, QEvent.Type.TouchEnd, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.KeyPress):
            self.send(kind)
        self.assertEqual(len(self.count), 5)

    def test_moves_are_reported_but_not_more_often_than_a_few_times_a_second(self):
        for _ in range(20):
            self.send(QEvent.Type.TouchUpdate)
        self.assertEqual(len(self.count), 1)

    def test_events_that_are_no_activity_do_not_count_and_nothing_is_swallowed(self):
        self.send(QEvent.Type.Timer)
        self.send(QEvent.Type.Paint)
        self.assertEqual(self.count, [])
        self.assertFalse(self.act.eventFilter(self.target, QEvent(QEvent.Type.TouchBegin)))    # the event goes on to the item


if __name__ == "__main__":
    unittest.main()
