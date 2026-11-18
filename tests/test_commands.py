import json
import math
import subprocess
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from armadalive import battery, commands, controls, gamescope, system
from tests.common import app, QObject
from tests.test_runtime import runtime_object, wait_for


@contextmanager
def display_backend(read=lambda: None, write=lambda _: None):
    with mock.patch.object(gamescope, "_read_fps"), \
            mock.patch.object(gamescope, "_xprop", return_value=None), \
            mock.patch.object(gamescope, "_read_display", side_effect=read), \
            mock.patch.object(gamescope, "_set_limit", side_effect=write), \
            runtime_object(gamescope.Gamescope()) as obj:
        yield obj


class Queue(unittest.TestCase):
    def test_latest_pending_is_bounded_and_owner_delivers_results(self):
        entered, release = threading.Event(), threading.Event()
        calls, results = [], []
        owner_thread = threading.get_ident()

        def first():
            calls.append((0, threading.get_ident()))
            entered.set()
            release.wait(2)

        with runtime_object(QObject()) as owner:
            queue = commands.Commands(owner, ("volume",))
            queue.completed.connect(lambda *r: results.append((*r, threading.get_ident())))
            queue.submit("volume", first, 0)
            try:
                self.assertTrue(entered.wait(1))
                for value in range(1, 101):
                    queue.submit("volume", lambda value=value: calls.append((value, threading.get_ident())), value)
                self.assertEqual(len(queue._running), 1)
                self.assertEqual(len(queue._pending), 1)
                self.assertEqual(queue.target("volume", -1), 100)
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: len(results) == 2))
            self.assertEqual([v for v, _ in calls], [0, 100])
            self.assertEqual([r[2].current for r in results], [False, True])
            self.assertEqual({r[-1] for r in results}, {owner_thread})
            self.assertNotIn(owner_thread, [t for _, t in calls])
            self.assertEqual(queue.target("volume", -1), 100)
            queue.observed("volume")
            self.assertEqual(queue.target("volume", -1), -1)
            with self.assertRaises(ValueError):
                queue.submit("unknown", lambda: None)

    def test_queued_delivery_counts_as_running_and_deleted_owner_is_safe(self):
        from PySide6.QtCore import QEvent, QThreadPool
        owner = QObject()
        queue = commands.Commands(owner, ("profile",))
        results = []
        queue.completed.connect(lambda *r: results.append(r))
        queue.submit("profile", lambda: None)
        self.assertTrue(QThreadPool.globalInstance().waitForDone(2000))
        self.assertIn("profile", queue._running)
        owner.deleteLater()
        app.sendPostedEvents(owner, QEvent.Type.DeferredDelete)
        app.processEvents()
        self.assertEqual(results, [])

    def test_run_is_bounded_and_checks_return_code(self):
        with mock.patch.object(commands.subprocess, "run") as run:
            commands.run("device", "value")
        self.assertEqual(run.call_args.args, (("device", "value"),))
        self.assertEqual(run.call_args.kwargs["timeout"], 5)
        self.assertTrue(run.call_args.kwargs["check"])


class ControlChannels(unittest.TestCase):
    @contextmanager
    def backend(self):
        with mock.patch.object(controls, "Poller"), runtime_object(controls.Controls()) as obj:
            obj._apply(dict(wifi=True, bluetooth=True, muted=False, wifips=False))
            obj._apply_vpn(dict(state="off", ip=""))
            yield obj

    def test_each_control_failure_refreshes_and_notifies_on_owner(self):
        actions = (
            ("wifi", lambda o: o.toggleWifi()),
            ("bluetooth", lambda o: o.toggleBluetooth()),
            ("mute", lambda o: o.toggleMute()),
            ("volume", lambda o: o.setVolume(.3)),
            ("brightness-top", lambda o: o.setBrightness("top", 40)),
            ("brightness-bottom", lambda o: o.setBrightness("bottom", 40)),
            ("screenshot", lambda o: o.screenshot()),
            ("wifi-saver", lambda o: o.toggleWifiSaver()),
        )
        for channel, action in actions:
            with self.subTest(channel=channel), self.backend() as obj, \
                    mock.patch.object(controls, "run", side_effect=OSError("unavailable")), \
                    mock.patch.object(controls, "_read", return_value=100), \
                    mock.patch.object(controls, "_screenshot", side_effect=OSError("unavailable")), \
                    mock.patch.object(controls.privileged, "available", return_value=False):
                completed, notices = [], []
                obj._commands.completed.connect(lambda *r: completed.append(r))
                obj.notice.connect(lambda *r: notices.append((*r, threading.get_ident())))
                action(obj)
                self.assertTrue(wait_for(lambda: bool(completed)))
                self.assertEqual(completed[0][0], channel)
                self.assertFalse(completed[0][2].succeeded)
                self.assertEqual(notices, [("commandfail", "", threading.get_ident())])
                obj._poller.refresh.assert_called_once()
                self.assertTrue(obj.state["wifi"])
                self.assertFalse(obj.state["muted"])

    def test_airplane_and_individual_toggles_share_radio_channels(self):
        entered, release = threading.Event(), threading.Event()
        writes = []

        def write(*args):
            if args[0] == "nmcli" and not writes:
                entered.set()
                release.wait(2)
            writes.append(args)

        with self.backend() as obj, mock.patch.object(controls, "run", side_effect=write):
            obj.toggleWifi()
            try:
                self.assertTrue(entered.wait(1))
                obj.toggleAirplane()  # both latest intents become off
                obj.toggleWifi()      # replaces only Wi-Fi with on
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertEqual([v[-1] for v in writes if v[0] == "nmcli"], ["off", "on"])
            self.assertEqual([v for v in writes if v[0] == "rfkill"], [("rfkill", "block", "bluetooth")])
            self.assertTrue(obj.state["wifi"])  # only a readback changes the observed state

    def test_acknowledged_toggle_survives_failed_readback_then_external_change_wins(self):
        snapshots = iter([dict(muted=False)])
        writes = []
        with mock.patch.object(controls.Controls, "_read", side_effect=lambda: next(snapshots, None)), \
                mock.patch.object(controls.Controls, "_read_vpn", return_value=None), \
                mock.patch.object(controls, "run", side_effect=lambda *a: writes.append(a)), \
                runtime_object(controls.Controls()) as obj:
            self.assertTrue(wait_for(lambda: obj.state.get("muted") is False))
            obj.toggleMute()
            self.assertTrue(wait_for(lambda: not obj._commands._running and not obj._poller._busy))
            obj.toggleMute()
            self.assertTrue(wait_for(lambda: len(writes) == 2 and not obj._commands._running))
            self.assertEqual([a[-1] for a in writes], ["1", "0"])
            obj._apply(dict(muted=True))  # successful fresh external observation
            obj.toggleMute()
            self.assertTrue(wait_for(lambda: len(writes) == 3 and not obj._commands._running))
            self.assertEqual(writes[-1][-1], "0")

    def test_mute_before_first_observation_preserves_tap_parity(self):
        for taps, expected_muted, expected_writes in ((1, False, 1), (2, True, 2), (3, False, 1), (4, True, 2)):
            with self.subTest(taps=taps):
                entered, release = threading.Event(), threading.Event()
                writes = []
                muted = True

                def write(*args):
                    nonlocal muted
                    target = args[-1]
                    writes.append(target)
                    if len(writes) == 1:
                        entered.set()
                        release.wait(3)
                    muted = not muted if target == "toggle" else target == "1"

                with mock.patch.object(controls, "Poller"), mock.patch.object(controls, "run", side_effect=write), \
                        runtime_object(controls.Controls()) as obj:
                    try:
                        obj.toggleMute()
                        self.assertTrue(entered.wait(1))
                        for _ in range(taps - 1):
                            obj.toggleMute()
                    finally:
                        release.set()
                    self.assertTrue(wait_for(lambda: not obj._commands._running))
                    self.assertEqual(muted, expected_muted)
                    self.assertEqual(len(writes), expected_writes)
                    self.assertNotIn("muted", obj.state)

    def test_tailscale_retry_and_notices_are_delivered_on_owner(self):
        attempts = []
        def run(args, **kwargs):
            attempts.append((args, kwargs["timeout"], threading.get_ident()))
            return subprocess.CompletedProcess(args, 1 if len(attempts) == 1 else 0, "", "tailscale up --operator=armada")
        with self.backend() as obj, mock.patch.object(controls.subprocess, "run", side_effect=run):
            notices = []
            obj.notice.connect(lambda *r: notices.append((*r, threading.get_ident())))
            obj.toggleTailscale()
            self.assertTrue(wait_for(lambda: bool(notices)))
            self.assertEqual(notices, [("tson", "", threading.get_ident())])
            self.assertEqual(attempts[-1][0], ["tailscale", "up", "--operator=armada"])
            self.assertEqual({timeout for _, timeout, _ in attempts}, {25})
            self.assertNotIn(threading.get_ident(), [t for _, _, t in attempts])
            self.assertEqual(obj.state["tailscale"]["state"], "off")
            obj._vpn_poller.refresh.assert_called_once()

    def test_tailscale_denied_timeout_and_stale_success(self):
        for failure, expected in ((subprocess.CompletedProcess([], 1, "", "permission denied"), "tsdenied"),
                                  (subprocess.TimeoutExpired("tailscale", 25), "tsfail")):
            with self.subTest(expected=expected), self.backend() as obj, \
                    mock.patch.object(controls.subprocess, "run", side_effect=[failure]):
                notices = []
                obj.notice.connect(lambda *r: notices.append((*r, threading.get_ident())))
                obj.toggleTailscale()
                self.assertTrue(wait_for(lambda: bool(notices)))
                self.assertEqual(notices, [(expected, "", threading.get_ident())])
        entered, release = threading.Event(), threading.Event()
        calls = []
        def run(args, **kwargs):
            calls.append(args[-1])
            if len(calls) == 1:
                entered.set()
                release.wait(2)
            return subprocess.CompletedProcess(args, 0, "", "")
        with self.backend() as obj, mock.patch.object(controls.subprocess, "run", side_effect=run):
            notices = []
            obj.notice.connect(lambda *r: notices.append(r))
            obj.toggleTailscale()
            try:
                self.assertTrue(entered.wait(1))
                obj.toggleTailscale()
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertEqual(calls, ["up", "down"])
            self.assertEqual(notices, [("tsoff", "")])

    def test_brightness_and_volume_clamp_and_screenshot_run_off_owner(self):
        calls = []
        with self.backend() as obj, tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(controls, "_read", return_value=1000), \
                mock.patch.object(controls.os.path, "expanduser", return_value=directory), \
                mock.patch.object(controls, "run", side_effect=lambda *a: calls.append((a, threading.get_ident()))):
            obj.setBrightness("bottom", 0)
            obj.setVolume(2)
            obj.screenshot()
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            by_name = {a[0]: a for a, _ in calls}
            self.assertEqual(by_name["busctl"][-1], "30")
            self.assertEqual(by_name["wpctl"][-1], "1.00")
            self.assertTrue(by_name["spectacle"][-1].startswith(directory + "/armadalive-"))
            self.assertNotIn(threading.get_ident(), [t for _, t in calls])


class DisplayCommands(unittest.TestCase):
    def test_paired_atoms_stay_ordered_and_partial_failure_is_not_success(self):
        calls = []
        def run(*args, **kwargs):
            calls.append((args[-2], args[-1]))
            if args[-2] == "GAMESCOPE_FPS_LIMIT":
                raise OSError("second property failed")
        # Keep the actual pair writer; mock only its external operation.
        with mock.patch.object(gamescope, "_read_fps"), mock.patch.object(gamescope, "Poller"), \
                mock.patch.object(gamescope, "run", side_effect=run), runtime_object(gamescope.Gamescope()) as obj:
            done = []
            obj.fpsLimitFinished.connect(lambda *r: done.append((*r, threading.get_ident())))
            request = obj.setFpsLimit(120)
            self.assertTrue(wait_for(lambda: bool(done)))
            self.assertEqual(calls, [("GAMESCOPE_DYNAMIC_REFRESH", "120"), ("GAMESCOPE_FPS_LIMIT", "120")])
            self.assertEqual(done, [(request, False, threading.get_ident())])
            obj._display_poller.refresh.assert_called_once()

    def test_old_read_is_discarded_and_delayed_readback_keeps_observation_distinct(self):
        entered, release = threading.Event(), threading.Event()
        count, observed, writes = [0], [None], []
        def read():
            count[0] += 1
            if count[0] == 1:
                return 60, 60, 60
            if count[0] == 2:
                entered.set()
                release.wait(2)
                return 60, 60, 60
            return observed[0]
        with display_backend(read, writes.append) as obj:
            self.assertTrue(wait_for(lambda: obj.state["hz"] == 60))
            obj._display_poller.refresh()
            try:
                self.assertTrue(entered.wait(1))
                obj.toggleRefresh()
                self.assertTrue(wait_for(lambda: not obj._commands._running))
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: not obj._display_poller._busy))
            self.assertEqual(obj.state["hz"], 60)
            self.assertEqual(obj.state["requestedLimit"], 120)
            obj.toggleRefresh()
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertEqual(writes, [120, 60])
            observed[0] = (90, 120, 90)
            obj._display_poller.refresh()
            self.assertTrue(wait_for(lambda: obj.state["hz"] == 90))
            self.assertEqual(obj.state["requestedLimit"], 90)

    def test_latest_pair_replaces_pending_pair_and_only_current_ack_is_emitted(self):
        entered, release = threading.Event(), threading.Event()
        writes, done = [], []
        def write(fps):
            writes.append(fps)
            if len(writes) == 1:
                entered.set()
                release.wait(2)
        with display_backend(write=write) as obj:
            obj.fpsLimitFinished.connect(lambda *r: done.append(r))
            obj.setFpsLimit(120)
            try:
                self.assertTrue(entered.wait(1))
                obj.setFpsLimit(90)
                request = obj.setFpsLimit(60)
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertEqual(writes, [120, 60])
            self.assertEqual(done, [(request, True)])


class PowerCommands(unittest.TestCase):
    def test_gpu_auto_manual_share_channel_and_refresh_after_failure(self):
        entered, release = threading.Event(), threading.Event()
        writes = []
        def run(*args):
            writes.append(args)
            if len(writes) == 1:
                entered.set()
                release.wait(2)
            else:
                raise OSError("gpu unavailable")
        with mock.patch.object(system, "Poller"), mock.patch.object(system, "run", side_effect=run), \
                runtime_object(system.SystemMonitor()) as obj:
            done = []
            obj._commands.completed.connect(lambda *r: done.append((*r, threading.get_ident())))
            obj.setGpuManual(800)
            try:
                self.assertTrue(entered.wait(1))
                obj.setGpuManual(900)
                obj.setGpuAuto()
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertEqual(writes, [("armada-power", "gpu-manual", "800"), ("armada-power", "gpu-auto")])
            self.assertFalse(done[-1][2].succeeded)
            self.assertEqual({r[-1] for r in done}, {threading.get_ident()})
            self.assertEqual(obj._power_poller.refresh.call_count, 2)

    def test_profile_keeps_confirmed_readback_until_new_observation(self):
        reads, entered, release = [0], threading.Event(), threading.Event()
        def read():
            reads[0] += 1
            if reads[0] == 1:
                return {"Profile": "Eco"}
            if reads[0] == 2:
                entered.set()
                release.wait(2)
                return {"Profile": "Old"}
            return {"Profile": "Balanced"}
        with mock.patch.object(system, "_power_state", side_effect=read), \
                mock.patch.object(system, "_essential", return_value=None), \
                mock.patch.object(system.SystemMonitor, "_read_detail", return_value=None), \
                mock.patch.object(system, "run"), runtime_object(system.SystemMonitor()) as obj:
            self.assertTrue(wait_for(lambda: obj.stats["profile"] == "Eco"))
            obj._power_poller.refresh()
            try:
                self.assertTrue(entered.wait(1))
                obj.setProfile("Performance")
                self.assertTrue(wait_for(lambda: not obj._commands._running))
                self.assertEqual(obj.stats["profile"], "Eco")
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: obj.stats["profile"] == "Balanced"))


class BatteryCommands(unittest.TestCase):
    @contextmanager
    def backend(self, saved=None, write=lambda *a: "", read=lambda *a: ""):
        with tempfile.TemporaryDirectory() as directory:
            config, limit = Path(directory, "battery.json"), Path(directory, "limit")
            limit.write_text("100")
            config.write_text(json.dumps(saved or battery.DEFAULTS))
            with mock.patch.object(battery, "CONFIG", config), mock.patch.object(battery, "LIMIT_FILE", limit), \
                    mock.patch.object(battery.privileged, "available", return_value=True), \
                    mock.patch.object(battery.privileged, "run", side_effect=write), \
                    mock.patch.object(battery, "_read", side_effect=read), runtime_object(battery.Battery()) as obj:
                yield obj, config

    def test_startup_and_latest_manual_limit_share_queue_and_save_on_owner(self):
        entered, release = threading.Event(), threading.Event()
        writes, changed = [], []
        def write(_, value):
            writes.append((value, threading.get_ident()))
            if len(writes) == 1:
                entered.set()
                release.wait(2)
                return "startup refusal"
            return ""
        with self.backend(dict(warn=20, limit=80, refused=False), write) as (obj, config):
            obj.changed.connect(lambda: changed.append(threading.get_ident()))
            try:
                self.assertTrue(entered.wait(1))
                obj.setLimit(90)
                obj.setLimit(100)
                self.assertEqual(obj.state["limit"], 80)
            finally:
                release.set()
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertEqual([v for v, _ in writes], [80, 100])
            self.assertNotIn(threading.get_ident(), [t for _, t in writes])
            self.assertEqual(changed, [threading.get_ident()])
            self.assertFalse(obj.state["refused"])
            self.assertEqual(json.loads(config.read_text())["limit"], 100)

    def test_mismatch_marks_refused_and_missing_helper_can_retry(self):
        with self.backend(read=lambda *a: "100") as (obj, config):
            obj.setLimit(80)
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertTrue(obj.state["refused"])
            self.assertEqual(json.loads(config.read_text())["limit"], 100)
        with self.backend() as (obj, config):
            with mock.patch.object(battery.privileged, "available", return_value=False):
                obj.setLimit(80)
                self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertFalse(obj.state["refused"])
            self.assertEqual(obj.state["error"], "root helper missing")
            obj.setLimit(80)
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertEqual(json.loads(config.read_text())["limit"], 80)

    def test_confirmed_limit_is_saved_before_a_newer_refused_limit_finishes(self):
        entered, release = threading.Event(), threading.Event()
        latest_entered, latest_release = threading.Event(), threading.Event()
        writes, applied = [], [100]

        def write(_, percent):
            writes.append(percent)
            if percent == 90:
                latest_entered.set()
                latest_release.wait(3)
                return "the battery rejected 90"
            entered.set()
            release.wait(3)
            applied.append(percent)
            return ""

        with self.backend(write=write, read=lambda *_: str(applied[-1])) as (obj, config):
            try:
                obj.setLimit(80)
                self.assertTrue(entered.wait(1))
                obj.setLimit(90)
                release.set()
                self.assertTrue(wait_for(latest_entered.is_set))
                self.assertEqual(applied[-1], 80)
                self.assertEqual(obj.state["limit"], 80)
                self.assertEqual(json.loads(config.read_text())["limit"], 80)
            finally:
                release.set()
                latest_release.set()
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertTrue(obj.state["supported"])
            self.assertEqual(obj.state["error"], "the battery rejected 90")
            self.assertEqual(obj.state["limit"], 80)
            with runtime_object(battery.Battery()) as restarted:
                self.assertTrue(wait_for(lambda: not restarted._commands._running))
                self.assertEqual(writes, [80, 90, 80])
                self.assertEqual(restarted.state["limit"], 80)

    def test_warning_and_charge_limit_saves_follow_existing_configuration_symlink(self):
        with self.backend() as (obj, config):
            target = config.with_name("managed-battery.json")
            config.rename(target)
            config.symlink_to(target.name)
            obj.setWarn(30)
            self.assertTrue(config.is_symlink())
            self.assertEqual(json.loads(target.read_text())["warn"], 30)
            obj.setLimit(80)
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertTrue(config.is_symlink())
            self.assertEqual(json.loads(target.read_text())["limit"], 80)

    def test_charge_limit_completion_preserves_accepted_nonfinite_warning_values(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.backend(dict(warn=value, limit=100, refused=False)) as (obj, config):
                changed = []
                obj.changed.connect(lambda: changed.append(threading.get_ident()))
                obj.setLimit(80)
                self.assertTrue(wait_for(lambda: not obj._commands._running))
                saved = json.loads(config.read_text())
                self.assertEqual(saved["limit"], 80)
                if math.isnan(value):
                    self.assertTrue(math.isnan(saved["warn"]))
                else:
                    self.assertEqual(saved["warn"], value)
                self.assertEqual(changed, [threading.get_ident()])
                self.assertEqual(obj.state["error"], "")

    def test_warning_save_preserves_accepted_nonfinite_limit(self):
        with self.backend(dict(warn=20, limit=float("nan"), refused=False)) as (obj, config):
            obj.setWarn(30)
            saved = json.loads(config.read_text())
            self.assertEqual(saved["warn"], 30)
            self.assertTrue(math.isnan(saved["limit"]))

    def test_save_failure_does_not_block_next_command(self):
        with self.backend() as (obj, config):
            with mock.patch.object(obj, "_save", side_effect=OSError("disk full")):
                obj.setLimit(80)
                self.assertTrue(wait_for(lambda: not obj._commands._running))
                self.assertIn("Could not save", obj.state["error"])
            obj.setLimit(90)
            self.assertTrue(wait_for(lambda: not obj._commands._running))
            self.assertEqual(json.loads(config.read_text())["limit"], 90)
            self.assertEqual(obj.state["error"], "")
