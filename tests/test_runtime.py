import subprocess
import threading
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from PySide6.QtCore import QEvent, QThreadPool

from tests.common import app, QObject

from armadalive import admin, controls, privileged, system
from armadalive.poller import Poller


def wait_for(predicate):
    until = time.monotonic() + 2
    while time.monotonic() < until:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    return False


@contextmanager
def runtime_object(obj):
    try:
        yield obj
    finally:
        # Keep the parent alive through queued signal emission and delete its timers on their owner.
        if not QThreadPool.globalInstance().waitForDone(5000):
            raise AssertionError("Runtime workers did not finish before fixture teardown")
        obj.deleteLater()
        app.sendPostedEvents(obj, QEvent.Type.DeferredDelete)


class Runtime(unittest.TestCase):
    def test_controls_initial_snapshot_is_read_off_owner_thread(self):
        owner = threading.get_ident()
        with mock.patch.object(controls.Controls, "_read", staticmethod(lambda: {"thread": threading.get_ident()})), \
                mock.patch.object(controls.Controls, "_read_vpn", return_value=None), \
                runtime_object(controls.Controls()) as obj:
            self.assertTrue(wait_for(lambda: "thread" in obj.state))
            self.assertNotEqual(obj.state["thread"], owner)

    def test_admin_initial_snapshot_is_read_off_owner_thread(self):
        owner = threading.get_ident()
        with mock.patch.object(admin, "helper_state", threading.get_ident), runtime_object(admin.Admin()) as obj:
            self.assertTrue(wait_for(lambda: obj.state.get("helper") not in (None, "missing")))
            self.assertNotEqual(obj.state["helper"], owner)

    def test_helper_probe_timeout_returns_unavailable(self):
        timeout = subprocess.TimeoutExpired("sudo", 2)
        with mock.patch.object(privileged.os.path, "exists", return_value=True), \
                mock.patch.object(privileged.subprocess, "run", side_effect=timeout):
            self.assertFalse(privileged.available(refresh=True))

    def test_system_collects_off_thread_and_applies_history_on_owner(self):
        owner = threading.get_ident()
        reads = []
        fps = []
        def cpu():
            reads.append(threading.get_ident())
            return 123, 456

        with mock.patch.object(system, "_cpu_times", cpu), \
                mock.patch.object(system, "_power_state", return_value=None), \
                mock.patch.object(system.SystemMonitor, "_read_detail", return_value={}), \
                runtime_object(system.SystemMonitor(fps=lambda: fps.append(threading.get_ident()) or 60)) as monitor:
            self.assertTrue(wait_for(lambda: monitor.history["fps"] == [60]))
        self.assertTrue(reads)
        self.assertNotIn(owner, reads)
        self.assertEqual(fps, [owner])

    def test_a_queued_result_keeps_the_worker_busy_until_delivery(self):
        reads = []
        applied = []

        def read():
            reads.append(threading.get_ident())
            return len(reads)

        with runtime_object(QObject()) as owner:
            poller = Poller(owner, read, lambda value: applied.append((value, threading.get_ident())), 60_000)
            self.assertTrue(QThreadPool.globalInstance().waitForDone(2000))
            for _ in range(5):
                poller.kick()
            self.assertTrue(wait_for(lambda: bool(applied)))
        self.assertEqual(reads, [reads[0]])
        self.assertEqual(applied, [(1, threading.get_ident())])
        self.assertNotEqual(reads[0], threading.get_ident())

    def test_resume_discards_old_snapshot_and_coalesces_requests(self):
        entered, release = threading.Event(), threading.Event()
        reads = []
        applied = []

        def read():
            reads.append(len(reads) + 1)
            if reads[-1] == 1:
                entered.set()
                release.wait(1)
            return reads[-1]

        with runtime_object(QObject()) as owner:
            poller = Poller(owner, read, applied.append, 60_000, idle_ms=120_000)
            self.assertTrue(entered.wait(1))
            try:
                poller.set_active(False)
                poller.set_active(True)
                poller.refresh()
                poller.refresh()
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: applied == [2]))
        self.assertEqual(reads, [1, 2])

    def test_polling_recovers_after_a_failed_read(self):
        errors, applied = [], []
        failure = ValueError("bad sample")
        read = mock.Mock(side_effect=[failure, 42])
        with runtime_object(QObject()) as owner:
            poller = Poller(owner, read, applied.append, 60_000)
            poller.failed.connect(lambda err: errors.append((err, threading.get_ident())))
            self.assertTrue(wait_for(lambda: bool(errors)))
            self.assertEqual(errors, [(failure, threading.get_ident())])
            self.assertFalse(applied)
            poller.kick()
            self.assertTrue(wait_for(lambda: applied == [42]))

    def test_power_properties_are_collected_in_one_bounded_call(self):
        response = mock.Mock(returncode=0, stdout='{"type":"a{sv}","data":[{"Temperature":{"type":"d","data":52.1},"AvailableProfiles":{"type":"as","data":["Balanced","Performance"]}}]}')
        with mock.patch.object(system.subprocess, "run", return_value=response) as run:
            power = system._power_state()
        self.assertEqual(power["Temperature"], 52.1)
        self.assertEqual(power["AvailableProfiles"], ["Balanced", "Performance"])
        self.assertEqual(run.call_count, 1)
        self.assertGreater(run.call_args.kwargs["timeout"], 0)

    def test_a_worker_can_request_a_poll(self):
        applied = []
        with runtime_object(QObject()) as owner:
            poller = Poller(owner, lambda: True, lambda _: applied.append(threading.get_ident()), 60_000, now=False)
            requests = threading.Thread(target=poller.kick)
            requests.start()
            requests.join()
            self.assertTrue(wait_for(lambda: bool(applied)))
        self.assertEqual(applied, [threading.get_ident()])

    def test_media_only_requests_metadata_for_the_chosen_player(self):
        from armadalive import media

        players = [{"name": media.PREFIX + name} for name in ("paused", "playing", "other")]
        queries = []

        def query(*args, timeout):
            queries.append(args)
            if args[0] == "list":
                return players
            if args[-1] == "Metadata":
                return {"data": {"xesam:title": {"data": "Chosen"}}}
            return {"data": "Playing" if args[1].endswith(".playing") else "Paused"}

        with mock.patch.object(media, "_bus", side_effect=query):
            state = media.Media._read()
        self.assertEqual(state["title"], "Chosen")
        self.assertEqual([args[1] for args in queries if args[-1] == "Metadata"], [players[1]["name"]])


    def test_hidden_gamescope_still_tracks_focus(self):
        from armadalive import gamescope

        focus = [123]
        with mock.patch.object(gamescope, "_read_fps"), \
                mock.patch.object(gamescope, "_xprops", side_effect=lambda *names: {
                    name: focus[0] if name == "GAMESCOPE_FOCUSED_APP" else 60 for name in names}), \
                runtime_object(gamescope.Gamescope()) as obj:
            self.assertTrue(wait_for(lambda: obj.state["focus"] == "123"))
            obj.set_active(False)
            focus[0] = 456
            self.assertTrue(wait_for(lambda: obj.state["focus"] == "456"))
            obj.set_active(True)
            self.assertTrue(wait_for(lambda: obj.state["limit"] == 60))

    def test_media_transport_error_preserves_snapshot_but_empty_list_clears_it(self):
        from armadalive import media

        with mock.patch.object(media, "_bus", return_value=None):
            self.assertIsNone(media.Media._read())
        with mock.patch.object(media, "_bus", return_value=[]):
            self.assertEqual(media.Media._read(), {"active": False})

    def test_gamescope_transport_error_preserves_focus(self):
        from armadalive import gamescope

        initial = mock.Mock(returncode=0, stdout="GAMESCOPE_FOCUSED_APP(CARDINAL) = 123")
        with mock.patch.object(gamescope, "_read_fps"), \
                mock.patch.object(gamescope, "_read_display", return_value=None), \
                mock.patch.object(gamescope.subprocess, "run", side_effect=[
                    initial, subprocess.TimeoutExpired("xprop", 3)]), \
                runtime_object(gamescope.Gamescope()) as obj:
            focus = []
            obj.focusChanged.connect(focus.append)
            self.assertTrue(wait_for(lambda: focus == ["123"]))
            obj._focus_poller.refresh()
            self.assertTrue(wait_for(lambda: not obj._focus_poller._busy))
        self.assertEqual(focus, ["123"])

    def test_failed_radio_and_volume_reads_preserve_known_values(self):
        online = mock.Mock(returncode=0, stdout="enabled")
        blocked = mock.Mock(returncode=0, stdout="Soft blocked: no")
        volume = mock.Mock(returncode=0, stdout="Volume: 0.50")
        saver = mock.Mock(returncode=0, stdout="Power save: on")
        failure = subprocess.TimeoutExpired("control", 3)
        with mock.patch.object(controls.Controls, "_read_vpn", return_value=None), \
                mock.patch.object(controls.Controls, "_wlan", return_value="wlan0"), \
                mock.patch.object(controls, "_rfkill", return_value=None), \
                mock.patch.object(controls.subprocess, "run", side_effect=[online, blocked, saver, volume, failure, failure, failure]), \
                runtime_object(controls.Controls()) as obj:
            self.assertTrue(wait_for(lambda: obj.state.get("volume") == 0.50))
            obj._poller.refresh()
            self.assertTrue(wait_for(lambda: not obj._poller._busy))
            self.assertTrue(obj.state["wifi"])
            self.assertTrue(obj.state["bluetooth"])
            self.assertTrue(obj.state["wifips"])
            self.assertEqual(obj.state["volume"], 0.50)

    def test_failed_metadata_request_retains_media_snapshot(self):
        from armadalive import media

        name = media.PREFIX + "player"
        with mock.patch.object(media, "_bus", side_effect=[
                [{"name": name}], {"data": "Playing"}, None]):
            self.assertIsNone(media.Media._read())


    def test_hidden_system_keeps_power_and_battery_samples_live(self):
        sample = [(100, 200), 100000, 4000000, 1000000, 2000000, False, 60]
        power = {"Temperature": 40}
        with mock.patch.object(system, "_essential", side_effect=lambda: tuple(sample)), \
                mock.patch.object(system, "_power_state", side_effect=lambda: dict(power)), \
                mock.patch.object(system.SystemMonitor, "_read_detail", return_value={}), \
                runtime_object(system.SystemMonitor()) as monitor:
            self.assertTrue(wait_for(lambda: monitor.stats["battery"] == 60 and monitor.stats["temp"] == 40))
            monitor.set_active(False)
            sample[-1], power["Temperature"] = 15, 85
            self.assertTrue(wait_for(lambda: monitor.stats["battery"] == 15 and monitor.stats["temp"] == 85))
            self.assertIn(15, monitor.history["battery"])
            self.assertEqual(monitor._detail_poller._timer.interval(), 15000)
            monitor.set_active(True)
            self.assertEqual(monitor._detail_poller._timer.interval(), 1000)

    def test_power_transport_failure_preserves_previous_snapshot(self):
        reply = mock.Mock(returncode=0, stdout='{"data":[{"Temperature":{"data":85}}]}')
        with mock.patch.object(system.subprocess, "run", side_effect=[reply, subprocess.TimeoutExpired("busctl", 1)]), \
                mock.patch.object(system, "_essential", return_value=None), \
                mock.patch.object(system.SystemMonitor, "_read_detail", return_value=None), \
                runtime_object(system.SystemMonitor()) as monitor:
            self.assertTrue(wait_for(lambda: monitor.stats["temp"] == 85))
            monitor._power_poller.refresh()
            self.assertTrue(wait_for(lambda: not monitor._power_poller._busy))
            self.assertEqual(monitor.stats["temp"], 85)
            monitor._apply_power({"Profile": "Balanced"})
            self.assertEqual(monitor.stats["temp"], 85)

    def test_invalid_power_replies_do_not_publish_defaults(self):
        for response in (mock.Mock(returncode=1, stdout=""), mock.Mock(returncode=0, stdout="bad json"),
                         mock.Mock(returncode=0, stdout='{"data":[[]]}')):
            with self.subTest(response=response), mock.patch.object(system.subprocess, "run", return_value=response):
                self.assertIsNone(system._power_state())

    def test_health_reads_files_on_worker_and_connection_on_owner(self):
        from armadalive import health

        reads, owners = [], []
        class Steam:
            @property
            def connected(self):
                owners.append(threading.get_ident())
                return True

        def checks():
            reads.append(threading.get_ident())
            return True, True, True, False

        with mock.patch.object(health, "_checks", side_effect=checks), runtime_object(health.Health(Steam())) as obj:
            self.assertTrue(wait_for(lambda: bool(obj.checks)))
            self.assertTrue(next(check for check in obj.checks if check["id"] == "steam")["ok"])
        self.assertNotIn(threading.get_ident(), reads)
        self.assertEqual(owners, [threading.get_ident()])

    def test_worker_refresh_invalidates_inflight_result(self):
        entered, release = threading.Event(), threading.Event()
        applied, reads = [], []

        def read():
            reads.append(len(reads) + 1)
            if len(reads) == 1:
                entered.set()
                release.wait(1)
            return reads[-1]

        with runtime_object(QObject()) as owner:
            poller = Poller(owner, read, applied.append, 60000)
            try:
                self.assertTrue(entered.wait(1))
                request = threading.Thread(target=poller.refresh)
                request.start()
                request.join()
                app.processEvents()  # dispatch the request on the owner before the read finishes
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: applied == [2]))
        self.assertEqual(reads, [1, 2])
