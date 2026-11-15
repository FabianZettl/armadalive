import copy, json, os, tempfile, threading, time, unittest
from types import SimpleNamespace
from unittest import mock

from tests.common import app
from armadalive import device, settings

PROFILES = [dict(id="balanced", label="Balanced", governor="conservative", underclock="medium", fanCurve="moderate", gpuMax=680, gpuMin=220)]
CURVES = [dict(id="moderate", label="Moderate", points=[[0, 51], [55, 51], [96, 255]]), dict(id="aggressive", label="Aggressive", points=[[0, 51], [90, 255]])]


class Guard(unittest.TestCase):
    def make(self, *parts):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.pending = os.path.join(self.directory, *parts, "pending.json")
        self.calls = []
        self.run_helper = lambda *args: ""

        def run(*args):
            self.calls.append(args)
            return self.run_helper(*args)
        patches = [mock.patch.object(settings, "PENDING", self.pending), mock.patch.object(settings.privileged, "run", side_effect=run),
                   mock.patch.object(settings.privileged, "available", return_value=True),
                   mock.patch.object(settings, "read_power", side_effect=lambda: copy.deepcopy(dict(profiles=PROFILES, curves=CURVES, governors=["conservative", "performance"], gpuSteps=[220, 475, 680])))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        s = settings.Settings()
        self.wait_for(lambda: s.data.get("helper"))
        self.calls.clear()
        return s

    def wait_for(self, predicate):
        until = time.monotonic() + 2
        while not predicate() and time.monotonic() < until:
            app.processEvents()
            time.sleep(0.001)
        self.assertTrue(predicate())

    def test_journal_exists_before_helper_mutation(self):
        s = self.make()
        snapshots = []

        def read_journal(*args):
            with open(self.pending) as saved:
                snapshots.append(json.load(saved))
            return ""

        self.run_helper = read_journal
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: not s.pending.get("busy"))
        self.assertEqual(snapshots, [[["profile", "balanced", "gpu_max_mhz", 680]]])

    def test_first_journal_syncs_new_directory_entries_before_helper_mutation(self):
        s = self.make("config", "armadalive")
        synced = set()

        def record_sync(path):
            sync_directory(path)
            synced.add(path)

        def run_helper(*args):
            sync_at_mutation.update(synced)
            return ""

        sync_at_mutation = set()
        sync_directory = settings.persistence._sync_directory
        self.run_helper = run_helper
        with mock.patch.object(settings.persistence, "_sync_directory", side_effect=record_sync):
            s.setProfileOption("balanced", "gpu_max_mhz", "475")
            self.wait_for(lambda: not s.pending.get("busy"))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue({self.directory, os.path.dirname(self.pending),
                         os.path.join(self.directory, "config")} <= sync_at_mutation)

    def test_retry_requires_the_previously_failed_ancestor_sync(self):
        s = self.make("config", "armadalive")
        sync_directory = settings.persistence._sync_directory

        def fail_parent(path):
            if path == self.directory:
                raise OSError("parent sync failed")
            sync_directory(path)

        with mock.patch.object(settings.persistence, "_sync_directory", side_effect=fail_parent):
            for _ in range(2):
                s.setProfileOption("balanced", "gpu_max_mhz", "475")
                self.wait_for(lambda: not s.pending["busy"])
                self.assertFalse(self.calls)
                self.assertTrue(os.path.isdir(os.path.join(self.directory, "config")))

        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: not s.pending["busy"])
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475")])

    def test_failed_apply_attempts_revert_and_retains_failed_recovery(self):
        s = self.make()
        self.run_helper = lambda *args: "helper timed out"
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: not s.pending.get("busy"))
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475"),
                                      ("profile", "balanced", "gpu_max_mhz=680")])
        self.assertTrue(s.pending.get("recovery"))
        self.assertTrue(os.path.exists(self.pending))
        s.confirm()
        self.assertTrue(os.path.exists(self.pending))
        self.run_helper = lambda *args: ""
        s.revert()
        self.wait_for(lambda: not s.pending.get("busy"))
        self.assertFalse(os.path.exists(self.pending))

    def test_failed_multi_operation_revert_retains_journal_across_restart(self):
        s = self.make()
        s.saveFanCurve("moderate", "96:255,55:200,0:51")
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: not s.pending.get("busy"))
        self.calls.clear()
        self.run_helper = lambda *args: "profile failed" if args[0] == "profile" else ""
        s.revert()
        self.wait_for(lambda: not s.pending.get("busy"))
        self.assertEqual([args[0] for args in self.calls], ["fan-curve", "profile"])
        self.assertTrue(os.path.exists(self.pending))
        self.run_helper = lambda *args: ""
        again = settings.Settings()
        self.wait_for(lambda: not os.path.exists(self.pending) and not again.pending.get("busy"))
        self.assertFalse(again.pending["active"])

    def test_waiting_for_helper_does_not_block_and_edits_stay_serial(self):
        s = self.make()
        entered = threading.Event()
        release = threading.Event()

        def block_once(*args):
            if len(self.calls) == 1:
                entered.set()
                release.wait(2)
            return ""

        self.run_helper = block_once
        try:
            s.setProfileOption("balanced", "gpu_max_mhz", "475")
            s.setProfileOption("balanced", "gpu_min_mhz", "475")
            self.wait_for(entered.is_set)
            self.assertTrue(s.pending.get("busy"))
            self.assertEqual(len(self.calls), 1)
        finally:
            release.set()
        self.wait_for(lambda: not s.pending.get("busy"))
        self.assertEqual([args[2] for args in self.calls], ["gpu_max_mhz=475", "gpu_min_mhz=475"])

    def test_expiry_drops_queued_tuning_before_another_helper_call(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: not s.pending["busy"])
        deadline = s._deadline
        entered, release = threading.Event(), threading.Event()

        def block_direct(*args):
            if args[0] == "drop-caches":
                entered.set()
                release.wait(2)
            return ""

        self.run_helper = block_direct
        try:
            s.dropCaches()
            s.setProfileOption("balanced", "gpu_min_mhz", "475")
            self.wait_for(entered.is_set)
            with mock.patch.object(s, "_tick"), mock.patch.object(settings.time, "monotonic", return_value=deadline + 1):
                release.set()
                until = time.perf_counter() + 2
                while s.pending["busy"] and time.perf_counter() < until:
                    app.processEvents()
                    time.sleep(0.001)
        finally:
            release.set()
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475"), ("drop-caches",),
                                      ("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(s.pending["active"])

    def test_a_change_starts_the_countdown_and_confirming_keeps_it(self):
        s = self.make()
        s.setProfileOption("balanced", "cpu_governor", "performance")
        self.wait_for(lambda: not s.pending["busy"])
        self.assertEqual(s.pending["seconds"], settings.CONFIRM_S)
        self.assertTrue(s.pending["active"])
        s.confirm()
        self.wait_for(lambda: not s.pending["busy"])
        self.assertFalse(s.pending["active"])
        self.assertFalse(os.path.exists(self.pending))
        self.assertEqual(self.calls, [("profile", "balanced", "cpu_governor=performance")])

    def _check_keep_while_refreshing(self, *, tick):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: s._future is None)
        deadline = s._deadline
        now = deadline - 1
        entered, release = threading.Event(), threading.Event()

        def blocked_helper_probe():
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Refresh did not release")
            return True

        with (mock.patch.object(settings, "time", SimpleNamespace(monotonic=lambda: now)),
              mock.patch.object(settings.privileged, "available", side_effect=blocked_helper_probe),
              mock.patch.object(settings.persistence, "remove", wraps=settings.persistence.remove) as remove):
            try:
                s.refresh()
                self.assertTrue(entered.wait(2))
                self.assertFalse(s.pending["busy"])
                self.assertEqual(s.pending["seconds"], 1)
                s.confirm()
                s.confirm()
                self.assertTrue(s.pending["busy"])
                self.assertTrue(os.path.exists(self.pending))
                now = deadline + 1
                if tick:
                    s._tick()
                    self.assertFalse(s.pending["recovery"])
                release.set()
                s._future.result(timeout=2)
                # Process refresh completion directly so the dispatch case has no timer tick.
                s._poll_result()
                self.wait_for(lambda: s._future is None)
            finally:
                release.set()
        self.assertFalse(s.pending["active"])
        self.assertFalse(os.path.exists(self.pending))
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475")])
        remove.assert_called_once_with(self.pending)

    def test_dispatch_keeps_confirmation_accepted_before_refresh_crosses_deadline(self):
        self._check_keep_while_refreshing(tick=False)

    def test_timer_keeps_confirmation_accepted_before_refresh_crosses_deadline(self):
        self._check_keep_while_refreshing(tick=True)

    def test_confirm_at_the_deadline_restores_the_previous_value(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: s._future is None)
        deadline = s._deadline
        with mock.patch.object(settings, "time", SimpleNamespace(monotonic=lambda: deadline)):
            s.confirm()
            self.wait_for(lambda: s._future is None)
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475"),
                                     ("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(s.pending["active"])
        self.assertFalse(os.path.exists(self.pending))

    def test_failed_confirmation_keeps_the_journal_for_restore(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: s._future is None)
        messages = []
        s.message.connect(messages.append)
        with mock.patch.object(settings.persistence, "remove", side_effect=OSError("journal removal failed")):
            s.confirm()
            self.wait_for(lambda: s._future is None)
        self.assertTrue(s.pending["recovery"])
        self.assertTrue(os.path.exists(self.pending))
        self.assertIn("journal removal failed", messages)
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475")])

        s.revert()
        self.wait_for(lambda: s._future is None)
        self.assertEqual(self.calls[-1], ("profile", "balanced", "gpu_max_mhz=680"))
        self.assertFalse(s.pending["active"])
        self.assertFalse(os.path.exists(self.pending))

    def test_confirmation_sync_failure_preserves_undo_across_restart(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: s._future is None)
        messages = []
        s.message.connect(messages.append)
        sync_directory = settings.persistence._sync_directory
        failed = False

        def fail_once_after_unlink(path):
            nonlocal failed
            if path == self.directory and not failed:
                failed = True
                self.assertFalse(os.path.exists(self.pending))
                raise OSError("one-time directory sync failure")
            sync_directory(path)

        with mock.patch.object(settings.persistence, "_sync_directory", side_effect=fail_once_after_unlink):
            s.confirm()
            self.wait_for(lambda: s._future is None)
        self.assertIn("one-time directory sync failure", messages)
        self.assertTrue(s.pending["recovery"])

        again = settings.Settings()
        self.wait_for(lambda: again._future is None)
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475"),
                                     ("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(again.pending["active"])
        self.assertFalse(os.path.exists(self.pending))

    def test_confirmation_reports_journal_rewrite_failure_and_preserves_in_memory_undo(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: s._future is None)
        messages = []
        s.message.connect(messages.append)
        with (mock.patch.object(settings.persistence, "_sync_directory", side_effect=OSError("removal sync failed")),
              mock.patch.object(settings.persistence, "write_json", side_effect=OSError("disk full"))):
            s.confirm()
            self.wait_for(lambda: s._future is None)
        self.assertTrue(s.pending["active"])
        self.assertTrue(s.pending["recovery"])
        self.assertIn("removal sync failed", messages[-1])
        self.assertIn("disk full", messages[-1])
        self.assertIn("Retry restore before closing", messages[-1])

        s.revert()
        self.wait_for(lambda: s._future is None)
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475"),
                                     ("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(s.pending["active"])

    def test_delayed_timer_restores_as_soon_as_monotonic_deadline_passes(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: not s.pending["busy"])
        self.calls.clear()
        for _ in range(settings.CONFIRM_S):
            s._tick()
        self.assertEqual(self.calls, [])
        with mock.patch.object(settings.time, "monotonic", return_value=s._deadline + 1):
            s._tick()
        self.wait_for(lambda: not s.pending["busy"])
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(s.pending["active"])

    def test_several_changes_go_back_to_the_value_before_the_first_one(self):
        s = self.make()
        s.setProfileOption("balanced", "cpu_governor", "performance")
        s.setProfileOption("balanced", "cpu_governor", "ondemand")
        s.setProfileOption("balanced", "fan_curve", "aggressive")
        self.wait_for(lambda: not s.pending["busy"])
        self.calls.clear()
        s.revert()
        self.wait_for(lambda: not s.pending["busy"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sorted(self.calls[0][2:]), ["cpu_governor=conservative", "fan_curve=moderate"])

    def test_a_fan_curve_edit_is_taken_back_too(self):
        s = self.make()
        s.saveFanCurve("moderate", "96:255,55:200,0:51")
        self.wait_for(lambda: not s.pending["busy"])
        self.calls.clear()
        s.revert()
        self.wait_for(lambda: not s.pending["busy"])
        self.assertEqual(self.calls, [("fan-curve", "moderate", "96:255,55:51,0:51")])

    def test_an_unchanged_value_does_not_start_a_countdown(self):
        s = self.make()
        s.setProfileOption("balanced", "cpu_governor", "conservative")
        self.wait_for(lambda: not s.pending["busy"])
        self.assertFalse(s.pending["active"])
        self.assertFalse(os.path.exists(self.pending))

    def test_an_unconfirmed_change_is_undone_when_the_app_starts_again(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_for(lambda: not s.pending["busy"])
        self.calls.clear()
        again = settings.Settings()
        self.wait_for(lambda: not again.pending["active"])
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(os.path.exists(self.pending))

    def test_no_tuning_mutation_when_the_journal_cannot_be_written(self):
        s = self.make()
        with mock.patch.object(settings.persistence, "write_json", side_effect=OSError("disk full")):
            s.setProfileOption("balanced", "gpu_max_mhz", "475")
            self.wait_for(lambda: not s.pending["busy"])
        self.assertFalse(self.calls)
        self.assertFalse(s.pending["active"])

    def test_the_whole_chain_is_capped(self):
        s = self.make()
        s.setProfileOption("balanced", "cpu_governor", "performance")
        self.wait_for(lambda: not s.pending["busy"])
        s._since -= settings.MAX_S - 3
        s.setProfileOption("balanced", "fan_curve", "aggressive")
        self.wait_for(lambda: not s.pending["busy"])
        self.assertLessEqual(s.pending["seconds"], 3)


class Presets(unittest.TestCase):
    SPEC = json.load(open(settings.PRESETS))

    def test_they_use_only_what_the_device_has(self):
        out = settings.resolve_presets(self.SPEC, dict(id="x"), [220, 475, 550, 680], ["conservative"], CURVES)
        by = {p["id"]: p["items"] for p in out}
        self.assertIn("gpu_max_mhz=475", by["cool"])               # 80 % of 680 is 544: snaps down to the real step 475
        self.assertNotIn("cpu_governor=performance", sum(by.values(), []))
        self.assertNotIn("fan_curve=relaxed", sum(by.values(), []))   # that curve does not exist here
        self.assertIn("fan_curve=aggressive", by["fast"])

    def test_a_model_entry_overrides_a_preset_for_that_model_only(self):
        spec = dict(self.SPEC, models={"ayn,thor:pro": {"cool": {"gpu_max": 0.9}}})
        steps = [220, 401, 550, 680]
        pro = settings.resolve_presets(spec, dict(id="ayn,thor", tier="pro"), steps, [], CURVES)
        other = settings.resolve_presets(spec, dict(id="ayn,thor", tier="max"), steps, [], CURVES)
        self.assertIn("gpu_max_mhz=550", next(p for p in pro if p["id"] == "cool")["items"])     # 90 % of 680
        self.assertIn("gpu_max_mhz=401", next(p for p in other if p["id"] == "cool")["items"])   # the default 80 %

    def test_the_memory_decides_the_variant(self):
        self.assertEqual([device.tier(g) for g in (0, 7.4, 11.2, 15.0)], ["unknown", "base", "pro", "max"])


if __name__ == "__main__":
    unittest.main()
