import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/armada-check.sh"


class Diagnostics(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.checkout = self.home / "armadalive-src/armadalive"
        (self.checkout / "tests").mkdir(parents=True)
        self.python = self.home / ".local/share/armadalive/venv/bin/python"
        self.python.parent.mkdir(parents=True)

    @staticmethod
    def shim(path, code):
        path.write_text("#!/bin/sh\n" + code + "\n")
        path.chmod(0o755)

    def run_section(self, heading, next_heading, **env):
        source = SCRIPT.read_text()
        setup = source.split('echo "== System"', 1)[0]
        section = source.split(f'echo "== {heading}"', 1)[1].split(f'echo "== {next_heading}', 1)[0]
        outcome = source.splitlines()[-1]
        return subprocess.run(
            ["bash", "-c", setup + section + outcome], capture_output=True, text=True, timeout=5,
            env=dict(os.environ, HOME=str(self.home), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
            | {"ARMADALIVE_PYTHON": str(self.python)} | env,
        )

    def test_failed_unittest_is_reported_as_failed(self):
        self.shim(self.python, """
case "$1" in
    -c) exit 0 ;;
    -m) echo "$HOME/test-packages"; exit 0 ;;
esac
echo 'FAILED (failures=1)'
exit 1
""")
        result = self.run_section("ArmadaLive code", "errors in this boot")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL  unit tests from source checkout", result.stdout)
        self.assertIn("FAILED (failures=1)", result.stdout)

    def test_test_checkout_is_explicit_and_reuses_selected_python(self):
        checkout = self.home / "named checkout"
        (checkout / "tests").mkdir(parents=True)
        log = self.home / "python.log"
        selected = self.bin / "selected python"
        self.shim(selected, """
case "$1" in
    -c) exit 0 ;;
    -m) echo "$HOME/test-packages"; exit 0 ;;
esac
printf '%s\\n%s\\n' "$PWD" "$HOME" > "$TRACE"
echo OK
""")
        result = self.run_section("ArmadaLive code", "errors in this boot",
                                  ARMADALIVE_TEST_CHECKOUT=str(checkout),
                                  ARMADALIVE_PYTHON=str(selected), TRACE=str(log))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS  unit tests from source checkout", result.stdout)
        cwd, home = log.read_text().splitlines()
        self.assertEqual(cwd, str(checkout))
        self.assertNotEqual(home, str(self.home))

    def test_missing_test_checkout_is_reported(self):
        result = self.run_section("ArmadaLive code", "errors in this boot",
                                  ARMADALIVE_TEST_CHECKOUT=str(self.home / "missing checkout"))
        self.assertIn("FAIL  unit tests from source checkout", result.stdout)
        self.assertIn("No test checkout", result.stdout)

    def test_power_failures_are_reported_and_threshold_is_only_read(self):
        self.shim(self.bin / "armada-power", "echo 'power command failed'; exit 7")
        self.shim(self.bin / "nmcli", "echo 'radio command failed'; exit 8")
        self.shim(self.bin / "bluetoothctl", "echo 'Powered: yes'; exit 9")
        self.shim(self.bin / "wpctl", "echo 'Volume: 50%'")
        self.shim(self.bin / "sudo", 'echo "$*" >> "$HOME/sudo.log"')
        self.shim(self.bin / "cat", "echo 80")
        result = self.run_section("Power, helper, radios, audio", "Steam / gamescope")
        self.assertIn("FAIL  armada-power status", result.stdout)
        self.assertIn("FAIL  Wi-Fi radio state", result.stdout)
        self.assertIn("FAIL  Bluetooth controller", result.stdout)
        self.assertIn("PASS  charge limit readable  (80)", result.stdout)
        self.assertEqual((self.home / "sudo.log").read_text().splitlines(),
                         ["-n -l /etc/armadalive/armadalive-helper"])

    def run_keyboard_probe(self, initially_visible, fail_restore=False):
        package = self.home / "armadalive"
        package.mkdir(exist_ok=True)
        (package / "__init__.py").touch()
        (package / "shell.py").write_text(
            '''import os
from pathlib import Path
KB = []
state = Path("visibility")
def _find_bus():
    return "test"
def activate_window():
    return True
def keyboard_visible():
    return state.read_text() == "true"
def _kb(*args):
    return "b " + state.read_text()
def keyboard_show():
    state.write_text("true")
def keyboard_hide():
    if os.environ["FAIL_RESTORE"] == "0":
        state.write_text("false")
'''
        )
        visibility = self.home / "visibility"
        visibility.write_text("true" if initially_visible else "false")
        script = SCRIPT.read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        result = subprocess.run(
            [sys.executable, "-c", "import time\ntime.sleep = lambda _: None\n" + script],
            cwd=self.home, capture_output=True, text=True, timeout=5,
            env=dict(os.environ, FAIL_RESTORE="1" if fail_restore else "0"),
        )
        return result, visibility.read_text()

    def test_keyboard_probe_leaves_both_initial_visibility_states_intact(self):
        for initially_visible, expected in ((True, "true"), (False, "false")):
            with self.subTest(initially_visible=initially_visible):
                result, visible = self.run_keyboard_probe(initially_visible)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(visible, expected)

    def test_keyboard_probe_reports_failed_restoration(self):
        result, visible = self.run_keyboard_probe(initially_visible=False, fail_restore=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("restore", result.stdout + result.stderr)
        self.assertEqual(visible, "true")

    def run_brightness_probe(self, fail_restore=""):
        backlight = self.home / "backlight"
        display = backlight / "ae94000.dsi.0"
        display.mkdir(parents=True, exist_ok=True)
        brightness = display / "brightness"
        brightness.write_text("42")
        (display / "max_brightness").write_text("100")
        self.shim(self.bin / "sleep", ":")
        self.shim(self.bin / "busctl", """
for value do :; done
if [ "$value" = 42 ]; then
    case "$FAIL_RESTORE" in
        command) exit 7 ;;
        readback) exit 0 ;;
    esac
fi
printf '%s' "$value" > "$BRIGHTNESS"
""")
        script = SCRIPT.read_text().split("cat > /tmp/ac_br.sh <<SH\n", 1)[1].split("\nSH\n", 1)[0]
        source = 'B=$PROBE_BACKLIGHT\nSESS=5\ncat > "$HOME/brightness.sh" <<SH\n' + script
        result = subprocess.run(
            ["bash", "-c", source + '\nSH\nbash "$HOME/brightness.sh"'], capture_output=True, text=True, timeout=5,
            env=dict(os.environ, HOME=str(self.home), FAIL_RESTORE=fail_restore, BRIGHTNESS=str(brightness),
                     PROBE_BACKLIGHT=str(backlight), PATH=str(self.bin) + os.pathsep + os.environ["PATH"]),
        )
        return result, brightness.read_text()

    def test_brightness_probe_confirms_restored_readback(self):
        result, brightness = self.run_brightness_probe()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(brightness, "42")
        self.assertIn("restored 42", result.stdout)

    def test_brightness_probe_reports_failed_restore_command_or_readback(self):
        for mode in ("command", "readback"):
            with self.subTest(mode=mode):
                result, brightness = self.run_brightness_probe(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("restore", result.stdout + result.stderr)
                self.assertEqual(brightness, "60")
