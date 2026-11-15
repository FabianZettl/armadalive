import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


class Installer(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.share = self.home / ".local/share/armadalive"
        self.unit = self.home / ".config/systemd/user/armadalive.service"
        self.desktop = self.home / ".local/share/applications/armadalive.desktop"
        self.hook = self.home / "ES-DE/scripts/game-start/armadalive"
        self.previous = {
            self.share / "armadalive/previous.py": "previous app\n",
            self.share / "scripts/run.sh": "previous scripts\n",
            self.share / "esde-event.py": "previous hook\n",
            self.unit: "previous unit\n",
            self.desktop: "previous desktop file\n",
        }
        for path, content in self.previous.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.hook.parent.mkdir(parents=True)
        self.hook.symlink_to("previous hook")
        python = self.share / "venv/bin/python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        # Only the installer's interpreter capability probe needs these imports.
        self.modules = self.home / "modules"
        pyside = self.modules / "PySide6"
        pyside.mkdir(parents=True)
        for name in ("__init__", "QtQuick", "QtWebSockets", "QtDBus", "QtTest"):
            (pyside / f"{name}.py").touch()
        (self.modules / "sitecustomize.py").write_text(
            'import os, sys\n'
            'if os.environ["TEST_USE_PRIVATE"] == "1" and sys.executable == "/usr/bin/python3":\n'
            '    sys.modules["PySide6"] = None\n'
        )
        (self.modules / "venv.py").write_text('raise SystemExit("Installer test attempted to provision a real venv")\n')
        self.commands = self.home / "commands"
        self.shim("systemctl", """#!/bin/sh
printf '%s\n' "$*" >> "$HOME/commands"
if [ "$2" = restart ] && [ ! -f "$HOME/.local/share/armadalive/armadalive/previous.py" ]; then
    case "${FAIL_STAGE:-}" in
        restart) exit 1 ;;
        startup)
            # Type=simple returns success before application startup.
            if grep -qx 'Type=notify' "$HOME/.config/systemd/user/armadalive.service"; then
                find "$HOME/.local/share/armadalive" -name previous.py > "$HOME/startup-backups"
                exit 1
            fi
            ;;
    esac
fi
""")
        self.shim("cp", """#!/bin/sh
if [ "$1" = -r ] && [ "${2%/armadalive}" != "$2" ]; then
    case "${FAIL_STAGE:-}" in
        copy) exit 1 ;;
        validation) /bin/cp "$@" && rm "$3/__main__.py"; exit $? ;;
        missing_app) /bin/cp "$@" && rm "$3/app.py"; exit $? ;;
    esac
fi
exec /bin/cp "$@"
""")
        self.shim("mv", """#!/bin/sh
case "${FAIL_STAGE:-}" in
    switch|switch_cleanup|rollback)
        for arg do
            case "$previous:$arg" in
                */new:*/armadalive/scripts)
                    touch "${previous%/new}/blocked-cleanup"
                    exit 1
                    ;;
                */old:*/armadalive/scripts)
                    [ "$FAIL_STAGE" != rollback ] || exit 1
                    ;;
            esac
            previous=$arg
        done
        ;;
esac
exec /bin/mv "$@"
""")
        self.shim("rm", """#!/bin/sh
for path do
    case "${FAIL_STAGE:-}" in
        switch_cleanup) [ ! -f "$path/blocked-cleanup" ] || exit 1 ;;
        success_cleanup) [ ! -f "$path/old/previous.py" ] || exit 1 ;;
    esac
done
exec /bin/rm "$@"
""")

    def shim(self, name, code):
        path = self.home / "bin" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(code)
        path.chmod(0o755)

    def run_installer(self, fail="", private=True):
        return subprocess.run(
            ["sh", str(INSTALLER)], capture_output=True, text=True, timeout=20,
            env=dict(os.environ, HOME=str(self.home), FAIL_STAGE=fail,
                     TEST_USE_PRIVATE="1" if private else "0", PYTHONPATH=str(self.modules),
                     PATH=str(self.home / "bin") + os.pathsep + os.environ["PATH"]),
        )

    def assert_previous_installation(self):
        for path, content in self.previous.items():
            self.assertTrue(path.is_file(), path)
            self.assertEqual(path.read_text(), content)
        self.assertEqual(os.readlink(self.hook), "previous hook")
        self.assertFalse((self.share / "armadalive/__main__.py").exists())

    def test_failed_copy_leaves_previous_installation(self):
        result = self.run_installer("copy")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_previous_installation()
        self.assertFalse(self.commands.exists())

    def test_incomplete_stage_is_rejected_before_switch(self):
        result = self.run_installer("validation")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_previous_installation()
        self.assertFalse(self.commands.exists())

    def test_missing_app_module_is_rejected_before_switch(self):
        result = self.run_installer("missing_app")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_previous_installation()
        self.assertFalse(self.commands.exists())

    def test_cleanup_failure_does_not_interrupt_rollback(self):
        result = self.run_installer("switch_cleanup")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_previous_installation()
        self.assertIn("Could not remove staging", result.stderr)

    def test_failed_restore_preserves_backup_and_continues_rollback(self):
        result = self.run_installer("rollback")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.share / "armadalive/previous.py").is_file())
        self.assertFalse((self.share / "armadalive/__main__.py").exists())
        self.assertEqual(os.readlink(self.hook), "previous hook")
        [scripts_backup] = list(self.share.glob(".armadalive-install.*/old/run.sh"))
        self.assertEqual(scripts_backup.read_text(), "previous scripts\n")
        self.assertIn(str(scripts_backup.parent), result.stderr)

    def test_cleanup_failure_keeps_successful_install_and_reports_backup(self):
        result = self.run_installer("success_cleanup")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.share / "armadalive/app.py").is_file())
        [backup] = list(self.share.glob(".armadalive-install.*/old/previous.py"))
        self.assertIn(str(backup.parent.parent), result.stderr)

    def test_failed_startup_after_launch_keeps_backup_until_rollback(self):
        result = self.run_installer("startup")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.home / "startup-backups").read_text().strip())
        self.assert_previous_installation()
        self.assertEqual(self.commands.read_text().count("--user restart armadalive\n"), 2)

    def test_failed_switch_restores_previous_installation(self):
        result = self.run_installer("switch")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_previous_installation()

    def test_failed_restart_restores_and_restarts_previous_installation(self):
        result = self.run_installer("restart")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_previous_installation()
        self.assertEqual(self.commands.read_text().count("--user restart armadalive\n"), 2)

    def test_success_replaces_app_scripts_and_hooks_without_moving_venv(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.share / "armadalive/previous.py").exists())
        self.assertTrue((self.share / "armadalive/qml/Main.qml").is_file())
        self.assertTrue(os.access(self.share / "scripts/run.sh", os.X_OK))
        self.assertTrue(os.access(self.share / "esde-event.py", os.X_OK))
        self.assertTrue(self.hook.samefile(self.share / "esde-event.py"))
        self.assertTrue((self.share / "venv/bin/python").samefile(sys.executable))
        self.assertTrue(self.unit.is_file())
        self.assertTrue(self.desktop.is_file())

    def test_system_python_install_does_not_create_private_venv(self):
        python = self.share / "venv/bin/python"
        python.unlink()
        python.parent.rmdir()
        python.parent.parent.rmdir()
        result = self.run_installer(private=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.share / "venv").exists())
        self.assertTrue((self.share / "armadalive/qml/Main.qml").is_file())
