import copy, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from tests.common import app  # noqa: F401
from armadalive import device, settings

PROFILES = [dict(id="balanced", label="Balanced", governor="conservative", underclock="medium", fanCurve="moderate", gpuMax=680, gpuMin=220)]
CURVES = [dict(id="moderate", label="Moderate", points=[[0, 51], [55, 51], [96, 255]]), dict(id="aggressive", label="Aggressive", points=[[0, 51], [90, 255]])]


class Guard(unittest.TestCase):
    def make(self):
        self.pending = os.path.join(tempfile.mkdtemp(), "pending.json")
        self.calls = []

        def run(command, **kwargs):
            self.calls.append(tuple(command[3:]))
            return subprocess.CompletedProcess(command, 0, "", "")
        patches = [mock.patch.object(settings, "PENDING", self.pending), mock.patch.object(settings.privileged.subprocess, "run", side_effect=run),
                   mock.patch.object(settings.privileged, "available", return_value=True),
                   mock.patch.object(settings, "read_power", side_effect=lambda: copy.deepcopy(dict(profiles=PROFILES, curves=CURVES, governors=["conservative", "performance"], gpuSteps=[220, 475, 680])))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        s = settings.Settings()
        self.calls.clear()
        return s

    def test_a_change_starts_the_countdown_and_confirming_keeps_it(self):
        s = self.make()
        s.setProfileOption("balanced", "cpu_governor", "performance")
        self.assertEqual(s.pending["seconds"], settings.CONFIRM_S)
        self.assertTrue(s.pending["active"])
        s.confirm()
        self.assertFalse(s.pending["active"])
        self.assertFalse(os.path.exists(self.pending))
        self.assertEqual(self.calls, [("profile", "balanced", "cpu_governor=performance")])

    def test_running_out_of_time_restores_the_old_value(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        self.calls.clear()
        for _ in range(settings.CONFIRM_S):
            s._tick()
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(s.pending["active"])

    def test_several_changes_go_back_to_the_value_before_the_first_one(self):
        s = self.make()
        s.setProfileOption("balanced", "cpu_governor", "performance")
        s._data["profiles"][0]["governor"] = "performance"      # what a refresh would show after the first change
        s.setProfileOption("balanced", "cpu_governor", "ondemand")
        s.setProfileOption("balanced", "fan_curve", "aggressive")
        self.calls.clear()
        s.revert()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sorted(self.calls[0][2:]), ["cpu_governor=conservative", "fan_curve=moderate"])

    def test_a_fan_curve_edit_is_taken_back_too(self):
        s = self.make()
        s.saveFanCurve("moderate", "96:255,55:200,0:51")
        self.calls.clear()
        s.revert()
        self.assertEqual(self.calls, [("fan-curve", "moderate", "96:255,55:51,0:51")])

    def test_a_refused_change_arms_nothing_and_an_unchanged_value_neither(self):
        s = self.make()
        s.setProfileOption("balanced", "cpu_governor", "conservative")      # already that
        self.assertFalse(s.pending["active"])
        refusal = subprocess.CompletedProcess([], 2, "", "no")
        with mock.patch.object(settings.privileged.subprocess, "run", return_value=refusal):
            s.setProfileOption("balanced", "cpu_governor", "performance")
        self.assertFalse(s.pending["active"])

    def test_an_unconfirmed_change_is_undone_when_the_app_starts_again(self):
        s = self.make()
        s.setProfileOption("balanced", "gpu_max_mhz", "475")
        pending = self.pending
        self.calls.clear()
        with mock.patch.object(settings, "PENDING", pending):
            again = settings.Settings()
            again._tick()
        self.assertEqual(self.calls, [("profile", "balanced", "gpu_max_mhz=680")])
        self.assertFalse(os.path.exists(pending))

    def test_the_whole_chain_is_capped(self):
        s = self.make()
        s.setProfileOption("balanced", "cpu_governor", "performance")
        s._since -= settings.MAX_S - 3
        s.setProfileOption("balanced", "fan_curve", "aggressive")
        self.assertLessEqual(s.pending["seconds"], 3)


class ReloadGuard(unittest.TestCase):
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
        self.enterContext(mock.patch.object(settings.privileged.subprocess, "run", side_effect=fake_sudo))
        self.settings = settings.Settings()
        self.messages = []
        self.settings.message.connect(self.messages.append)

    def test_profile_edit_arms_undo_when_reload_is_rejected(self):
        self.settings.setProfileOption("balanced", "cpu_underclock", "small")
        self.assertIn("cpu_underclock = small", self.config.read_text(encoding="utf-8"))
        self.assertIn("fixture rejected reload", self.messages[-1])
        self.assertTrue(self.settings.pending["active"])
        self.assertEqual(json.loads(self.pending.read_text(encoding="utf-8")),
                         [["profile", "balanced", "cpu_underclock", "medium"]])

    def test_fan_curve_edit_arms_undo_when_reload_times_out(self):
        self.reload.write_text("#!/bin/sh\nexec /bin/sleep 11\n", encoding="utf-8")
        self.settings.saveFanCurve("moderate", "96:255,55:200,0:51")
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
                self.assertIn(error, self.messages[-1])
                self.assertEqual(self.config.read_text(encoding="utf-8"), self.original)
                self.assertFalse(self.settings.pending["active"])
                self.assertFalse(self.pending.exists())


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
