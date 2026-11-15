import threading
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from tests.test_runtime import runtime_object, wait_for
from armadalive import gamescope, media


@contextmanager
def display_backend(read, write=lambda _: None):
    with mock.patch.object(gamescope, "_read_fps"), \
            mock.patch.object(gamescope, "_xprop", return_value=None), \
            mock.patch.object(gamescope, "_read_display", side_effect=read), \
            mock.patch.object(gamescope, "_set_limit", side_effect=write), \
            runtime_object(gamescope.Gamescope()) as obj:
        yield obj


class GamescopeReview(unittest.TestCase):
    def test_completed_toggle_survives_delayed_readback(self):
        entered, release = threading.Event(), threading.Event()
        targets, reads = [], []

        def read():
            reads.append(True)
            if len(reads) > 1:
                entered.set()
                release.wait(2)
                return None
            return 60, 60, 60

        with display_backend(read, targets.append) as obj:
            try:
                self.assertTrue(wait_for(lambda: obj.state["hz"] == 60))
                cached = [obj.state]
                obj.changed.connect(lambda: cached.__setitem__(0, obj.state))
                obj.setFpsLimit(120)
                self.assertTrue(wait_for(lambda: entered.is_set() and not obj._commands._running))
                obj._apply_focus(123)  # the regular focus publication while display readback waits
                self.assertEqual(cached[0]["hz"], 120)
                obj.setFpsLimit(60 if cached[0]["hz"] == 120 else 120)
                self.assertTrue(wait_for(lambda: len(targets) == 2 and not obj._commands._running))
                self.assertEqual(targets, [120, 60])
            finally:
                release.set()
                self.assertTrue(wait_for(lambda: not obj._display_poller._busy))

    def test_failed_display_command_publishes_previous_value(self):
        reads = iter([(60, 60, 60)])

        def fail(_):
            raise OSError("display unavailable")

        with display_backend(lambda: next(reads, None), fail) as obj:
            self.assertTrue(wait_for(lambda: obj.state["hz"] == 60))
            cached, completed = [obj.state], []
            obj.changed.connect(lambda: cached.__setitem__(0, obj.state))
            obj._commands.settled.connect(completed.append)
            obj.setFpsLimit(120)
            self.assertTrue(wait_for(lambda: bool(completed)))
            self.assertEqual(cached[0]["hz"], 60)
            self.assertEqual(obj.state["limit"], 60)
            self.assertTrue(wait_for(lambda: not obj._display_poller._busy))

    def test_precommand_read_cannot_replace_acknowledged_target(self):
        entered, release = threading.Event(), threading.Event()
        reads, observed = [], [None]

        def read():
            reads.append(True)
            if len(reads) == 1:
                return 60, 60, 60
            if len(reads) == 2:
                entered.set()
                release.wait(2)
                return 60, 60, 60
            return observed[0]

        with display_backend(read) as obj:
            try:
                self.assertTrue(wait_for(lambda: obj.state["hz"] == 60))
                obj._display_poller.refresh()
                self.assertTrue(entered.wait(1))
                obj.setFpsLimit(120)
                self.assertTrue(wait_for(lambda: not obj._commands._running))
            finally:
                release.set()
                self.assertTrue(wait_for(lambda: not obj._display_poller._busy))
            self.assertEqual(obj.state["hz"], 120)
            observed[0] = (90, 120, 90)  # a later external change is authoritative
            obj._display_poller.refresh()
            self.assertTrue(wait_for(lambda: obj.state["hz"] == 90))

    def test_samples_and_expiry_notify_when_x_properties_fail(self):
        with display_backend(lambda: None) as obj:
            published, focus = [], []
            obj.changed.connect(lambda: published.append((obj.state["fps"], threading.get_ident())))
            obj.focusChanged.connect(focus.append)
            obj._samples.append((40.0, time.monotonic()))
            self.assertTrue(wait_for(lambda: any(fps == 40 for fps, _ in published)))
            obj._samples.append((40.0, time.monotonic() - 13))
            self.assertTrue(wait_for(lambda: published[-1][0] == 0))
            self.assertEqual({thread for _, thread in published}, {threading.get_ident()})
            self.assertEqual(focus, [])
            self.assertTrue(wait_for(lambda: not obj._display_poller._busy and not obj._focus_poller._busy))

    def test_unchanged_frame_rate_does_not_repeat_notifications(self):
        with display_backend(lambda: None) as obj:
            published = []
            obj.changed.connect(lambda: published.append(obj.state["fps"]))
            obj._samples.append((40.1, time.monotonic()))
            self.assertTrue(wait_for(lambda: published == [40]))
            obj._samples.append((40.2, time.monotonic()))
            self.assertFalse(wait_for(lambda: len(published) > 1))
            self.assertTrue(wait_for(lambda: not obj._display_poller._busy and not obj._focus_poller._busy))

    def test_pipe_closure_notifies_after_focus_publishes_a_sample(self):
        with display_backend(lambda: None) as obj:
            published = []
            obj.changed.connect(lambda: published.append(obj.state["fps"]))
            obj._samples.append((40.0, time.monotonic()))
            obj._apply_focus(123)
            self.assertEqual(published, [40])
            obj._samples.append((0.0, 0.0))  # writer closes before the frame-rate timer fires
            self.assertTrue(wait_for(lambda: published[-1] == 0))
            self.assertTrue(wait_for(lambda: not obj._display_poller._busy and not obj._focus_poller._busy))


class MediaReview(unittest.TestCase):
    def test_failed_status_does_not_hide_healthy_player(self):
        self._check_failed_candidate("PlaybackStatus")

    def test_failed_metadata_does_not_hide_healthy_player(self):
        self._check_failed_candidate("Metadata")

    def _check_failed_candidate(self, failed_property):
        names = [media.PREFIX + name for name in ("broken", "healthy")]

        def query(*args, timeout):
            if args[0] == "list":
                return [{"name": name} for name in names]
            if args[1] == names[0] and args[-1] == failed_property:
                return None
            if args[-1] == "PlaybackStatus":
                return {"data": "Playing"}
            return {"data": {"xesam:title": {"data": "Healthy music"}}}

        with mock.patch.object(media, "_bus", side_effect=query):
            result = media.Media._read()
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], names[1])
        self.assertEqual(result["title"], "Healthy music")

    def test_failed_players_share_one_deadline(self):
        names = [media.PREFIX + str(i) for i in range(5)]
        clock, attempted = [0.0], []

        def query(*args, timeout):
            if args[0] == "list":
                return [{"name": name} for name in names]
            attempted.append(args[1])
            clock[0] += timeout
            return None

        with mock.patch.object(media.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(media, "_bus", side_effect=query):
            self.assertIsNone(media.Media._read())
        self.assertEqual(attempted, names[:2])
        self.assertEqual(clock[0], 4)

    def test_failed_status_does_not_discard_usable_paused_player(self):
        names = [media.PREFIX + name for name in ("paused", "broken")]

        def query(*args, timeout):
            if args[0] == "list":
                return [{"name": name} for name in names]
            if args[1] == names[1]:
                return None
            if args[-1] == "PlaybackStatus":
                return {"data": "Paused"}
            return {"data": {"xesam:title": {"data": "Paused music"}}}

        with mock.patch.object(media, "_bus", side_effect=query):
            result = media.Media._read()
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], names[0])
        self.assertEqual(result["status"], "Paused")

    def test_inactive_requires_a_complete_successful_scan(self):
        names = [media.PREFIX + name for name in ("first", "second")]
        for first, expected in ((None, None), ({"data": "Stopped"}, {"active": False})):
            with self.subTest(first=first), mock.patch.object(media, "_bus", side_effect=[
                    [{"name": name} for name in names], first, {"data": "Stopped"}]):
                self.assertEqual(media.Media._read(), expected)

    def test_metadata_uses_only_the_remaining_deadline(self):
        name, clock, timeouts = media.PREFIX + "player", [0.0], []

        def query(*args, timeout):
            if args[0] == "list":
                return [{"name": name}]
            if args[-1] == "PlaybackStatus":
                clock[0] = 3.5
                return {"data": "Playing"}
            timeouts.append(timeout)
            clock[0] += timeout
            return None

        with mock.patch.object(media.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(media, "_bus", side_effect=query):
            self.assertIsNone(media.Media._read())
        self.assertEqual(timeouts, [0.5])
