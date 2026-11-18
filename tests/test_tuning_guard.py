import copy, json, os, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from shiboken6 import delete

from tests.common import app
from armadalive import device, settings

PROFILES = [dict(id="balanced", label="Balanced", governor="conservative", underclock="medium", fanCurve="moderate", gpuMax=680, gpuMin=220)]
CURVES = [dict(id="moderate", label="Moderate", points=[[0, 51], [55, 51], [96, 255]]), dict(id="aggressive", label="Aggressive", points=[[0, 51], [90, 255]])]


class SettingsTestCase(unittest.TestCase):
    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.001)
        self.assertTrue(predicate(), "Settings did not settle")

    def wait_idle(self, backend, timeout=3):
        self.wait_for(lambda: backend._future is None, timeout)

    def start_backend(self, **kwargs):
        backend = settings.Settings(**kwargs)
        self.addCleanup(self.dispose_backend, backend)
        self.wait_idle(backend)
        return backend

    def dispose_backend(self, backend):
        self.wait_idle(backend)
        backend._executor.shutdown()
        delete(backend)


class Guard(SettingsTestCase):
    def make(self, *parts):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.pending = self.directory.joinpath(*parts, "pending.json")
        self.calls = []
        self.now = 100
        self.available = lambda: True
        self.run_helper = lambda *args: (0, "")
        self.power = copy.deepcopy(dict(profiles=PROFILES, curves=CURVES,
                                        governors=["conservative", "performance"], gpuSteps=[220, 475, 680]))
        self.read_power = lambda: copy.deepcopy(self.power)

        def run(*args):
            self.calls.append(args)
            return self.run_helper(*args)

        self.enterContext(mock.patch.multiple(settings, PENDING=self.pending,
                                              read_power=lambda: self.read_power(),
                                              read_rgb=lambda: dict(saturation=70, linkBrightness=True, maxBrightness=60)))
        self.enterContext(mock.patch.object(settings.privileged, "available", side_effect=lambda: self.available()))
        self.enterContext(mock.patch.object(settings.privileged, "run_with_status", side_effect=run))
        return self.start()

    def start(self):
        return self.start_backend(now=lambda: self.now)

    def journal(self):
        return json.loads(self.pending.read_text(encoding="utf-8"))

    def test_journal_exists_before_helper_mutation(self):
        backend = self.make()
        snapshots = []

        def record_journal(*args):
            snapshots.append(self.journal())
            return 0, ""

        self.run_helper = record_journal
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        self.assertEqual(snapshots, [[["profile", "balanced", "gpu_max_mhz", 680]]])

    def test_new_journal_directories_are_synced_before_the_helper_call(self):
        backend = self.make("config", "armadalive")
        synced, synced_at_mutation = set(), set()
        sync_directory = settings.persistence._sync_directory

        def record_sync(path):
            sync_directory(path)
            synced.add(Path(path))

        def run(*args):
            synced_at_mutation.update(synced)
            return 0, ""

        self.run_helper = run
        with mock.patch.object(settings.persistence, "_sync_directory", side_effect=record_sync):
            backend.setProfileOption("balanced", "gpu_max_mhz", "475")
            self.wait_idle(backend)
        self.assertTrue({self.directory, self.pending.parent, self.pending.parent.parent} <= synced_at_mutation)

    def test_repeated_ancestor_sync_failure_never_calls_the_helper(self):
        backend = self.make("config", "armadalive")
        sync_directory = settings.persistence._sync_directory

        def fail_parent(path):
            if Path(path) == self.directory:
                raise OSError("parent sync failed")
            sync_directory(path)

        with mock.patch.object(settings.persistence, "_sync_directory", side_effect=fail_parent):
            for _ in range(2):
                backend.setProfileOption("balanced", "gpu_max_mhz", "475")
                self.wait_idle(backend)
                self.assertEqual(self.calls, [])
                self.assertFalse(backend.pending["active"])
                self.assertTrue(self.pending.parent.is_dir())

        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475")])

    def test_failed_journal_write_prevents_mutation(self):
        backend = self.make()
        with mock.patch.object(settings.persistence, "write_json", side_effect=OSError("disk full")):
            backend.setProfileOption("balanced", "gpu_max_mhz", "475")
            self.wait_idle(backend)
        self.assertEqual(self.calls, [])
        self.assertFalse(backend.pending["active"])

    def test_unavailable_previous_profile_value_prevents_mutation(self):
        backend = self.make()
        self.power["profiles"][0].update(gpuMax=600, governor="old-governor")
        messages = []
        backend.message.connect(messages.append)

        for key, replacement, previous in (
            ("gpu_max_mhz", "475", "graphics clock limit"),
            ("cpu_governor", "performance", "processor governor"),
        ):
            with self.subTest(key=key):
                backend.setProfileOption("balanced", key, replacement)
                self.wait_idle(backend)
                self.assertEqual(self.calls, [])
                self.assertFalse(self.pending.exists())
                self.assertIn(previous, messages[-1])

    def test_ambiguous_apply_failure_retries_recovery_without_losing_originals(self):
        backend = self.make()
        self.run_helper = lambda *args: (None, "helper timed out")
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475"),
                                      ("profile", "balanced", "gpu_max_mhz=680")])
        self.assertTrue(backend.pending["recovery"])
        backend.confirm()
        self.assertEqual(self.journal(), [["profile", "balanced", "gpu_max_mhz", 680]])

        self.run_helper = lambda *args: (0, "")
        backend.revert()
        self.wait_idle(backend)
        self.assertFalse(backend.pending["active"])
        self.assertFalse(self.pending.exists())

    def test_a_validation_rejection_preserves_only_the_earlier_pending_edit(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        self.now += 2
        self.run_helper = lambda *args: (2, "no")
        backend.setProfileOption("balanced", "gpu_min_mhz", "bad")
        self.wait_idle(backend)
        self.assertEqual(self.journal(), [["profile", "balanced", "gpu_max_mhz", 680]])
        self.assertEqual(backend.pending["seconds"], settings.CONFIRM_S - 2)
        self.assertFalse(backend.pending["recovery"])
        self.assertEqual(self.calls[-1], ("profile", "balanced", "gpu_min_mhz=bad"))

    def test_failed_multi_operation_restore_retains_every_entry_across_restart(self):
        backend = self.make()
        backend.saveFanCurve("moderate", "96:255,55:200,0:51")
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        originals = self.journal()
        self.calls.clear()
        self.run_helper = lambda *args: (3, "daemon reload failed") if args[0] == "profile" else (0, "")
        backend.revert()
        self.wait_idle(backend)
        self.assertEqual([args[0] for args in self.calls], ["fan-curve", "profile"])
        self.assertTrue(backend.pending["recovery"])
        self.assertEqual(self.journal(), originals)

        self.run_helper = lambda *args: (0, "")
        restarted = self.start()
        self.assertEqual([args[0] for args in self.calls], ["fan-curve", "profile", "fan-curve", "profile"])
        self.assertFalse(restarted.pending["active"])
        self.assertFalse(self.pending.exists())

    def test_edits_wait_for_one_another_and_keep_the_first_original(self):
        backend = self.make()
        entered, release = threading.Event(), threading.Event()

        def run(*args):
            if args[-1] == "gpu_max_mhz=475":
                entered.set()
                release.wait(3)
                self.power["profiles"][0]["gpuMax"] = 475
            return 0, ""

        self.run_helper = run
        try:
            backend.setProfileOption("balanced", "gpu_max_mhz", "475")
            backend.setProfileOption("balanced", "gpu_max_mhz", "220")
            self.wait_for(entered.is_set)
            self.assertTrue(backend.pending["busy"])
            self.assertEqual(len(self.calls), 1)
        finally:
            release.set()
        self.wait_idle(backend)
        self.assertEqual([args[-1] for args in self.calls], ["gpu_max_mhz=475", "gpu_max_mhz=220"])
        self.assertEqual(self.journal(), [["profile", "balanced", "gpu_max_mhz", 680]])

    def test_expiry_discards_queued_tuning_but_keeps_direct_commands(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        entered, release = threading.Event(), threading.Event()

        def run(*args):
            if args[0] == "drop-caches":
                entered.set()
                release.wait(3)
            return 0, ""

        self.run_helper = run
        try:
            backend.dropCaches()
            backend.setProfileOption("balanced", "gpu_min_mhz", "475")
            backend.setRgb(True, "FF0000", 25)
            self.wait_for(entered.is_set)
            self.now += settings.CONFIRM_S
        finally:
            release.set()
        self.wait_idle(backend)
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475"), ("drop-caches",),
                                      ("profile", "balanced", "gpu_max_mhz=680"),
                                      ("rgb", "true", "FF0000", 25, 70, "true", 60)])
        self.assertFalse(backend.pending["active"])

    def test_a_change_starts_the_countdown_and_confirming_keeps_it(self):
        backend = self.make()
        backend.setProfileOption("balanced", "cpu_governor", "performance")
        self.wait_idle(backend)
        self.assertEqual(backend.pending["seconds"], settings.CONFIRM_S)
        self.assertTrue(backend.pending["active"])
        backend.confirm()
        self.wait_idle(backend)
        self.assertFalse(backend.pending["active"])
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.calls, [("profile", "balanced", "cpu_governor=performance")])

    def test_keep_accepted_during_a_slow_refresh_survives_the_deadline(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        entered, release = threading.Event(), threading.Event()

        def probe():
            entered.set()
            release.wait(3)
            return True

        self.available = probe
        try:
            backend.refresh()
            self.wait_for(entered.is_set)
            self.now += settings.CONFIRM_S - 1
            self.assertFalse(backend.pending["busy"])
            self.assertEqual(backend.pending["seconds"], 1)
            backend.confirm()
            backend.confirm()
            self.assertTrue(backend.pending["busy"])
            self.assertTrue(self.pending.exists())
            self.now += 2
            backend._tick()
            self.assertFalse(backend.pending["recovery"])
        finally:
            release.set()
        self.wait_idle(backend)
        self.assertFalse(backend.pending["active"])
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475")])

    def test_confirm_at_the_deadline_restores_the_original(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        self.now += settings.CONFIRM_S
        backend.confirm()
        self.wait_idle(backend)
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=475"),
                                      ("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(backend.pending["active"])

    def test_failed_confirmation_leaves_the_original_available_for_retry(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        with mock.patch.object(settings.persistence, "remove", side_effect=OSError("journal removal failed")):
            backend.confirm()
            self.wait_idle(backend)
        self.assertTrue(backend.pending["recovery"])
        self.assertEqual(self.journal(), [["profile", "balanced", "gpu_max_mhz", 680]])
        self.assertEqual(len(self.calls), 1)
        backend.revert()
        self.wait_idle(backend)
        self.assertEqual(self.calls[-1], ("profile", "balanced", "gpu_max_mhz=680"))
        self.assertFalse(self.pending.exists())

    def test_failed_confirmation_sync_recovers_on_restart_even_after_unlink(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        sync_directory = settings.persistence._sync_directory
        failed = False

        def fail_once_after_unlink(path):
            nonlocal failed
            if Path(path) == self.directory and not failed:
                failed = True
                self.assertFalse(self.pending.exists())
                raise OSError("directory sync failed")
            sync_directory(path)

        with mock.patch.object(settings.persistence, "_sync_directory", side_effect=fail_once_after_unlink):
            backend.confirm()
            self.wait_idle(backend)
        self.assertTrue(backend.pending["recovery"])
        self.assertEqual(self.journal(), [["profile", "balanced", "gpu_max_mhz", 680]])

        restarted = self.start()
        self.assertEqual(self.calls[-1], ("profile", "balanced", "gpu_max_mhz=680"))
        self.assertFalse(restarted.pending["active"])
        self.assertFalse(self.pending.exists())

    def test_failed_confirmation_rewrite_reports_that_only_memory_keeps_the_original(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        messages = []
        backend.message.connect(messages.append)
        with (mock.patch.object(settings.persistence, "_sync_directory", side_effect=OSError("removal sync failed")),
              mock.patch.object(settings.persistence, "write_json", side_effect=OSError("disk full"))):
            backend.confirm()
            self.wait_idle(backend)
        self.assertTrue(backend.pending["recovery"])
        self.assertIn("removal sync failed", messages[-1])
        self.assertIn("disk full", messages[-1])
        self.assertIn("Retry restore before closing", messages[-1])
        backend.revert()
        self.wait_idle(backend)
        self.assertEqual(self.calls[-1], ("profile", "balanced", "gpu_max_mhz=680"))
        self.assertFalse(backend.pending["active"])

    def test_delayed_timer_restores_when_monotonic_deadline_passes(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        for _ in range(settings.CONFIRM_S):
            backend._tick()
        self.assertEqual(len(self.calls), 1)
        self.now += settings.CONFIRM_S + 1
        backend._tick()
        self.wait_idle(backend)
        self.assertEqual(self.calls[-1], ("profile", "balanced", "gpu_max_mhz=680"))
        self.assertFalse(backend.pending["active"])

    def test_an_unchanged_value_does_not_create_a_pending_change(self):
        backend = self.make()
        backend.setProfileOption("balanced", "cpu_governor", "conservative")
        self.wait_idle(backend)
        self.assertFalse(backend.pending["active"])
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.calls, [])

    def test_restart_restores_an_unconfirmed_change_when_the_helper_becomes_available(self):
        backend = self.make()
        backend.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.wait_idle(backend)
        self.available = lambda: False
        restarted = self.start()
        self.assertTrue(restarted.pending["recovery"])
        self.assertFalse(restarted.pending["busy"])
        self.assertEqual(len(self.calls), 1)
        self.available = lambda: True
        restarted.revert()
        self.wait_idle(restarted)
        self.assertEqual(self.calls[-1], ("profile", "balanced", "gpu_max_mhz=680"))
        self.assertFalse(restarted.pending["active"])

    def test_the_whole_chain_is_capped_at_the_first_changes_deadline(self):
        backend = self.make()
        backend.setProfileOption("balanced", "cpu_governor", "performance")
        self.wait_idle(backend)
        for _ in range(settings.MAX_S // 10 - 1):
            self.now += 10
            backend.setProfileOption("balanced", "fan_curve", "aggressive")
            self.wait_idle(backend)
        self.assertEqual(backend.pending["seconds"], 10)


class ReloadGuard(SettingsTestCase):
    custom_caps = "cpu_max_policy0 = 1234567\ncpu_max_policy4 = 2345678\n"

    def setUp(self):
        etc = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.config = etc / "power-profiles.conf"
        self.original = (
            "[profile.balanced]\ncpu_governor = conservative\ncpu_underclock = medium\nfan_curve = moderate\n"
            "[fan_curve.moderate]\ncurve = 96:255,55:51,0:51\n"
        )
        self.config.write_text(self.original, encoding="utf-8")
        self.pending = etc / "pending.json"
        self.reload = etc / "armada-power"
        self.reload.write_text("#!/bin/sh\necho 'fixture rejected reload' >&2\nexit 7\n", encoding="utf-8")
        self.reload.chmod(0o755)
        helper = str(Path(__file__).resolve().parents[1] / "scripts" / "armadalive-helper")
        env = dict(os.environ, ARMADALIVE_ETC=str(etc), PATH=str(etc))
        env.pop("ARMADALIVE_NO_RELOAD", None)
        run = subprocess.run

        def fake_sudo(command, **kwargs):
            self.assertEqual(command[:3], ["sudo", "-n", helper])
            return run([sys.executable, *command[2:]], env=env, **kwargs)

        self.enterContext(mock.patch.multiple(settings, OVERRIDE=str(self.config), PENDING=str(self.pending),
                                              FACTORY=etc / "factory", GPU_FREQS=etc / "freqs", GOVERNORS=etc / "governors"))
        self.enterContext(mock.patch.object(settings.privileged, "HELPER", helper))
        self.enterContext(mock.patch.object(settings.privileged, "available", return_value=True))
        helper_process = SimpleNamespace(run=fake_sudo, TimeoutExpired=subprocess.TimeoutExpired)
        self.enterContext(mock.patch.object(settings.privileged, "subprocess", helper_process))
        self.settings = self.start_backend()
        self.messages = []
        self.settings.message.connect(self.messages.append)

    def test_profile_edit_arms_undo_when_reload_is_rejected(self):
        self.settings.setProfileOption("balanced", "cpu_underclock", "small")
        self.wait_idle(self.settings)
        self.assertIn("cpu_underclock = small", self.config.read_text(encoding="utf-8"))
        self.assertIn("fixture rejected reload", self.messages[-1])
        self.assertTrue(self.settings.pending["active"])
        self.assertEqual(json.loads(self.pending.read_text(encoding="utf-8")),
                         [["profile", "balanced", "cpu_underclock", "medium"]])
        self.reload.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.settings.revert()
        self.wait_idle(self.settings)
        self.assertIn("cpu_underclock = medium", self.config.read_text(encoding="utf-8"))
        self.assertFalse(self.pending.exists())

    def test_underclock_edit_preserves_custom_caps_by_rejecting_the_change(self):
        custom = self.original.replace("[fan_curve.moderate]", self.custom_caps + "[fan_curve.moderate]")
        self.config.write_text(custom, encoding="utf-8")
        self.settings.setProfileOption("balanced", "cpu_underclock", "small")
        self.wait_idle(self.settings)
        self.assertEqual(self.config.read_text(encoding="utf-8"), custom)
        self.assertIn("custom processor caps", self.messages[-1])
        self.assertFalse(self.settings.pending["active"])
        self.assertFalse(self.pending.exists())

    def test_preset_with_unchanged_underclock_preserves_custom_caps(self):
        custom = self.original.replace("[fan_curve.moderate]", self.custom_caps + "[fan_curve.moderate]")
        self.config.write_text(custom + "\n[fan_curve.relaxed]\ncurve = 96:255,55:80,0:40\n", encoding="utf-8")
        self.reload.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.settings.refresh()
        self.wait_idle(self.settings)

        self.settings.applyPreset("balanced", "quiet")
        self.wait_idle(self.settings)
        applied = self.config.read_text(encoding="utf-8")
        self.assertIn("fan_curve = relaxed", applied)
        self.assertIn(self.custom_caps, applied)
        self.assertEqual(json.loads(self.pending.read_text(encoding="utf-8")),
                         [["profile", "balanced", "fan_curve", "moderate"]])

        self.settings.revert()
        self.wait_idle(self.settings)
        restored = self.config.read_text(encoding="utf-8")
        self.assertIn("fan_curve = moderate", restored)
        self.assertIn(self.custom_caps, restored)
        self.assertFalse(self.pending.exists())

    def test_fan_curve_edit_arms_undo_when_reload_times_out(self):
        self.reload.write_text("#!/bin/sh\nexec /bin/sleep 11\n", encoding="utf-8")
        self.settings.saveFanCurve("moderate", "96:255,55:200,0:51")
        self.wait_idle(self.settings, timeout=12)
        self.assertIn("curve = 96:255,55:200,0:51", self.config.read_text(encoding="utf-8"))
        self.assertIn("reload timed out", self.messages[-1])
        self.assertTrue(self.settings.pending["active"])
        self.assertEqual(json.loads(self.pending.read_text(encoding="utf-8")),
                         [["curve", "moderate", "", "96:255,55:51,0:51"]])

    def test_validation_rejections_leave_the_configuration_and_undo_alone(self):
        for edit, args, error in (
            (self.settings.setProfileOption, ("balanced", "cpu_underclock", "invalid"), "cpu_underclock must be"),
            (self.settings.saveFanCurve, ("moderate", "96:999"), "outside 0..255"),
        ):
            with self.subTest(args=args):
                edit(*args)
                self.wait_idle(self.settings)
                self.assertIn(error, self.messages[-1])
                self.assertEqual(self.config.read_text(encoding="utf-8"), self.original)
                self.assertFalse(self.settings.pending["active"])
                self.assertFalse(self.pending.exists())


class Presets(unittest.TestCase):
    SPEC = json.loads(Path(settings.PRESETS).read_text(encoding="utf-8"))

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
