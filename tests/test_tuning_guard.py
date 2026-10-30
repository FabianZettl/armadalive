import copy, json, os, tempfile, unittest
from unittest import mock

from tests.common import app  # noqa: F401
from armadalive import device, settings

PROFILES = [dict(id="balanced", label="Balanced", governor="conservative", underclock="medium", fanCurve="moderate", gpuMax=680, gpuMin=220)]
CURVES = [dict(id="moderate", label="Moderate", points=[[0, 51], [55, 51], [96, 255]]), dict(id="aggressive", label="Aggressive", points=[[0, 51], [90, 255]])]


class Guard(unittest.TestCase):
    def make(self):
        self.pending = os.path.join(tempfile.mkdtemp(), "pending.json")
        self.calls = []

        def run(*args):
            self.calls.append(args)
            return ""
        patches = [mock.patch.object(settings, "PENDING", self.pending), mock.patch.object(settings.privileged, "run", side_effect=run),
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
        with mock.patch.object(settings.privileged, "run", return_value="no"):
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
