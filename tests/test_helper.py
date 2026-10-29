import os, subprocess, sys, tempfile, unittest

HELPER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "armadalive-helper")


class Helper(unittest.TestCase):
    """The root helper validates every value. Runs against a temp folder, never touches /etc."""

    def setUp(self):
        self.etc = tempfile.mkdtemp()
        self.env = dict(os.environ, ARMADALIVE_ETC=self.etc, ARMADALIVE_NO_RELOAD="1")

    def run_helper(self, *args):
        return subprocess.run([sys.executable, HELPER, *args], env=self.env, capture_output=True, text=True)

    def conf(self):
        with open(os.path.join(self.etc, "power-profiles.conf")) as f:
            return f.read()

    def test_a_valid_fan_curve_is_written_sorted(self):
        r = self.run_helper("fan-curve", "silent", "60:60,90:255,70:90", "Silent")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("curve = 90:255,70:90,60:60", self.conf())

    def test_bad_fan_curves_are_refused(self):
        for args in (("../x", "90:255"), ("ok", "300:255"), ("ok", "90:999"), ("ok", "90"), ("Bad Name", "90:255")):
            self.assertEqual(self.run_helper("fan-curve", *args).returncode, 2, args)
        self.assertFalse(os.path.exists(os.path.join(self.etc, "power-profiles.conf")))

    def test_fan_settings_are_range_checked(self):
        self.assertEqual(self.run_helper("fan", "ramp_up=40", "smoothing=0.6").returncode, 0)
        for bad in ("ramp_up=999", "smoothing=1.5", "min_pwm=-1", "evil=1"):
            self.assertEqual(self.run_helper("fan", bad).returncode, 2, bad)

    def test_profile_names_and_keys_are_checked(self):
        self.assertEqual(self.run_helper("profile", "root", "cpu_governor=performance").returncode, 2)
        self.assertEqual(self.run_helper("profile", "eco", "cpu_max=0.1").returncode, 2)
        self.assertEqual(self.run_helper("profile", "eco", "cpu_governor=evil").returncode, 2)

    def test_charge_limit_and_wifi_saver_values_are_checked(self):
        for args in (("charge-limit", "49"), ("charge-limit", "101"), ("charge-limit", "x"), ("wifi-powersave", "maybe"), ("wifi-powersave",)):
            self.assertEqual(self.run_helper(*args).returncode, 2, args)

    def test_rgb_values_are_checked(self):
        for args in (("true", "FF00FF;rm", "20", "100", "false", "50"), ("true", "00FF88", "150", "100", "false", "50"), ("maybe", "00FF88", "20", "100", "false", "50")):
            self.assertEqual(self.run_helper("rgb", *args).returncode, 2, args)

    def test_unknown_action(self):
        self.assertEqual(self.run_helper("rm").returncode, 2)


if __name__ == "__main__":
    unittest.main()
