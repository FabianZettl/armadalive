import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HELPER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "armadalive-helper")


class HelperFixture(unittest.TestCase):
    """Run the helper against a temporary configuration directory."""

    def setUp(self):
        self.etc = self.enterContext(tempfile.TemporaryDirectory())
        self.env = dict(os.environ, ARMADALIVE_ETC=self.etc, ARMADALIVE_NO_RELOAD="1")

    def run_helper(self, *args):
        return subprocess.run([sys.executable, HELPER, *args], env=self.env, capture_output=True, text=True, timeout=12)

    def conf(self):
        with open(os.path.join(self.etc, "power-profiles.conf")) as f:
            return f.read()


class Helper(HelperFixture):
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

    def test_a_battery_that_refuses_the_limit_is_reported_plainly(self):
        self.env["ARMADALIVE_CHARGE_LIMIT_FILE"] = os.path.join(self.etc, "no", "such", "dir", "threshold")
        self.assertEqual(self.run_helper("charge-limit", "80").returncode, 2)   # missing file: "no charge limit"
        path = os.path.join(self.etc, "threshold")
        os.mkdir(path)   # opening a directory for writing fails with an OSError, like the Thor's timeout
        self.env["ARMADALIVE_CHARGE_LIMIT_FILE"] = path
        r = self.run_helper("charge-limit", "80")
        self.assertEqual(r.returncode, 2)
        self.assertIn("did not accept the limit", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_charge_limit_and_wifi_saver_values_are_checked(self):
        for args in (("charge-limit", "49"), ("charge-limit", "101"), ("charge-limit", "x"), ("wifi-powersave", "maybe"), ("wifi-powersave",)):
            self.assertEqual(self.run_helper(*args).returncode, 2, args)

    def test_rgb_values_are_checked(self):
        for args in (("true", "FF00FF;rm", "20", "100", "false", "50"), ("true", "00FF88", "150", "100", "false", "50"), ("maybe", "00FF88", "20", "100", "false", "50")):
            self.assertEqual(self.run_helper("rgb", *args).returncode, 2, args)

    def test_unknown_action(self):
        self.assertEqual(self.run_helper("rm").returncode, 2)


class Reload(HelperFixture):
    def setUp(self):
        super().setUp()
        self.commands = Path(self.etc, "bin")
        self.commands.mkdir()
        self.env["PATH"] = str(self.commands)
        self.env.pop("ARMADALIVE_NO_RELOAD")

    def executable(self, name, script):
        path = self.commands / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)

    def test_save_reports_failed_reload_after_writing_configuration(self):
        self.executable("armada-power", "#!/bin/sh\n[ \"$1\" = reload ] || exit 3\n"
                        "echo 'fixture rejected reload' >&2\nexit 7\n")
        result = self.run_helper("fan", "min_pwm=21")
        self.assertIn("min_pwm = 21", self.conf())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reload failed", result.stderr)
        self.assertIn("7", result.stderr)
        self.assertIn("fixture rejected reload", result.stderr)
        self.assertIn("on disk may have changed", result.stderr)

    def test_reset_reports_failed_reload_after_moving_configuration(self):
        self.executable("armada-power", "#!/bin/sh\nexit 7\n")
        config = Path(self.etc, "power-profiles.conf")
        config.write_text("[fan]\nmin_pwm = 21\n", encoding="utf-8")
        result = self.run_helper("reset")
        self.assertFalse(config.exists())
        self.assertEqual(config.with_suffix(".conf.armadalive-bak").read_text(encoding="utf-8"),
                         "[fan]\nmin_pwm = 21\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reload failed", result.stderr)
        self.assertIn("on disk may have changed", result.stderr)

    def test_hanging_reload_reports_a_timeout_within_the_helper_budget(self):
        self.executable("armada-power", f"#!{sys.executable}\n"
                        "import os, time\n"
                        "parent = os.getppid()\n"
                        "while parent != 1 and os.getppid() == parent:\n"
                        "    time.sleep(0.05)\n")
        try:
            result = self.run_helper("fan", "min_pwm=21")
        except subprocess.TimeoutExpired:
            self.fail("The helper failed to bound its reload command")
        self.assertIn("min_pwm = 21", self.conf())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reload timed out", result.stderr)
        self.assertIn("on disk may have changed", result.stderr)

    def test_missing_reload_command_is_reported_after_writing_configuration(self):
        result = self.run_helper("fan", "min_pwm=21")
        self.assertIn("min_pwm = 21", self.conf())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reload could not run", result.stderr)
        self.assertIn("on disk may have changed", result.stderr)

    def test_restore_retains_journal_until_helper_acknowledges_reload(self):
        from armadalive import settings

        self.env["ARMADALIVE_TEST_HELPER"] = HELPER
        self.executable("sudo", "#!/bin/sh\n"
                        "[ \"$1\" = -n ] && [ \"$2\" = \"$ARMADALIVE_TEST_HELPER\" ] && [ \"$3\" = fan-curve ] || exit 2\n"
                        "shift\nexec \"$@\"\n")
        self.executable("armada-power", "#!/bin/sh\nexit 7\n")
        journal = Path(self.etc, "tuning_pending.json")
        journal.write_text('[["curve", "moderate", "", "96:255,55:51,0:51"]]', encoding="utf-8")
        original_journal = journal.read_bytes()
        with (mock.patch.dict(os.environ, self.env, clear=True),
              mock.patch.object(settings.privileged, "HELPER", HELPER)):
            undo = settings._journal(journal)
            result = settings._restore(journal, undo)
            self.assertIn("curve = 96:255,55:51,0:51", self.conf())
            self.assertIn("reload failed", result)
            self.assertEqual(journal.read_bytes(), original_journal)

            self.executable("armada-power", "#!/bin/sh\n[ \"$1\" = reload ]\n")
            self.assertEqual(settings._restore(journal, settings._journal(journal)), "")
            self.assertFalse(journal.exists())


if __name__ == "__main__":
    unittest.main()
