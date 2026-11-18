import fcntl
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
EVENTS = ("startup", "quit", "system-select", "game-select", "game-start", "game-end")


class Installer(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.share = self.home / ".local/share/armadalive"
        self.unit = self.home / ".config/systemd/user/armadalive.service"
        self.desktop = self.home / ".local/share/applications/armadalive.desktop"
        self.hooks = [self.home / "ES-DE/scripts" / event / "armadalive" for event in EVENTS]
        self.venv = self.share / "venv"
        self.previous = {
            self.share / "armadalive/previous.py": "previous app\n",
            self.share / "scripts/run.sh": "previous scripts\n",
            self.share / "esde-event.py": "previous event script\n",
            self.unit: "previous unit\n",
            self.desktop: "previous desktop entry\n",
        }
        for path, content in self.previous.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        for hook in self.hooks:
            hook.parent.mkdir(parents=True)
            hook.symlink_to("previous hook")
        self.private_python = self.venv / "bin/python"
        self.private_python.parent.mkdir(parents=True)
        self.private_python.write_text('#!/bin/sh\nTEST_IN_PRIVATE=1 exec "$TEST_PYTHON" "$@"\n')
        self.private_python.chmod(0o755)
        self.old_venv = self.venv / "previous"
        self.old_venv.write_text("previous environment\n")

        # Allow both interpreter probes without accessing device packages or the network.
        self.modules = self.home / "modules"
        pyside = self.modules / "PySide6"
        pyside.mkdir(parents=True)
        for name in ("__init__", "QtQuick", "QtWebSockets", "QtDBus", "QtTest"):
            (pyside / f"{name}.py").touch()
        (self.modules / "sitecustomize.py").write_text(
            'import os, sys\n'
            'if os.getenv("TEST_USE_PRIVATE") == "1" and not os.getenv("TEST_IN_PRIVATE"):\n'
            '    sys.modules["PySide6"] = None\n'
        )
        (self.modules / "venv.py").write_text(
            'import os, pathlib, sys\n'
            'if not os.getenv("TEST_PROVISION_PRIVATE"):\n'
            '    raise SystemExit("Unexpected private environment provisioning")\n'
            'bin_dir = pathlib.Path(sys.argv[1]) / "bin"\n'
            'bin_dir.mkdir(parents=True)\n'
            'python = bin_dir / "python"\n'
            'python.write_text(\'#!/bin/sh\\nTEST_IN_PRIVATE=1 exec "$TEST_PYTHON" "$@"\\n\')\n'
            'pip = bin_dir / "pip"\n'
            'pip.write_text(\'#!/bin/sh\\nprintf "%s\\\\n" "$@" > "$HOME/pip-arguments"\\n'
            '[ "$FAIL_STAGE" != pip ]\\n\')\n'
            'python.chmod(0o755)\n'
            'pip.chmod(0o755)\n'
        )

        self.commands = self.home / "commands"
        self.enabled = self.home / "enabled"
        self.active = self.home / "active"
        self.failure = self.home / "failure-injected"
        self.shim("systemctl", """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$HOME/commands"
[ "$1" = --user ] || exit 2
case "$2" in
    is-enabled)
        state=$(cat "$HOME/enabled")
        [ "$state" != missing ] || exit 4
        printf '%s\n' "$state"
        [ "$state" = enabled ] || [ "$state" = enabled-runtime ]
        ;;
    is-active)
        state=$(cat "$HOME/active")
        [ "$state" != missing ] || exit 4
        [ "$state" = active ] || exit 3
        ;;
    daemon-reload)
        if [ "$FAIL_STAGE" = reload ] && [ ! -e "$HOME/failure-injected" ]; then
            touch "$HOME/failure-injected"
            exit 1
        fi
        ;;
    enable)
        state=enabled
        if [ "$3" = --runtime ]; then state=enabled-runtime; fi
        printf '%s\n' "$state" > "$HOME/enabled"
        if [ "$FAIL_STAGE" = enable ] && [ ! -e "$HOME/failure-injected" ]; then
            touch "$HOME/failure-injected"
            exit 1
        fi
        ;;
    disable) printf 'disabled\n' > "$HOME/enabled" ;;
    stop) printf 'inactive\n' > "$HOME/active" ;;
    restart)
        if [ -f "$HOME/.local/share/armadalive/armadalive/previous.py" ]; then
            printf 'old\n' >> "$HOME/restarts"
            if [ "$FAIL_STAGE" = recovery ]; then
                touch "$HOME/restore-injected"
                exit 1
            fi
        else
            printf 'new\n' >> "$HOME/restarts"
            case "$FAIL_STAGE" in
            restart|inactive|recovery)
                printf 'inactive\n' > "$HOME/active"
                touch "$HOME/failure-injected"
                [ "$FAIL_STAGE" = inactive ]
                exit $?
                ;;
            esac
        fi
        printf 'active\n' > "$HOME/active"
        ;;
    *) exit 2 ;;
esac
""")
        self.shim("cp", """#!/bin/sh
if [ "$1" = -r ] && [ "${2%/armadalive}" != "$2" ]; then
    case "$FAIL_STAGE" in
        copy) touch "$HOME/failure-injected"; exit 1 ;;
        validation|missing_app|invalid_type|syntax)
            /bin/cp "$@" || exit $?
            app="$3"
            if [ ! -f "$app/app.py" ]; then app="$app/armadalive"; fi
            case "$FAIL_STAGE" in
                validation) rm "$app/__main__.py" ;;
                missing_app) rm "$app/app.py" ;;
                invalid_type) rm "$app/app.py" && mkdir "$app/app.py" ;;
                syntax) printf 'def invalid(' > "$app/app.py" ;;
            esac || exit $?
            touch "$HOME/failure-injected"
            exit 0
            ;;
    esac
fi
exec /bin/cp "$@"
""")
        self.shim("mv", """#!/bin/sh
if [ "$1" = -T ] && [ "$2" = -- ]; then
    case "$FAIL_STAGE:$3:$4" in
        switch:*/new:*/armadalive/scripts|switch_cleanup:*/new:*/armadalive/scripts|rollback:*/new:*/armadalive/scripts)
            touch "$HOME/failure-injected" "${3%/new}/blocked-cleanup"
            exit 1
            ;;
        rollback:*/old:*/armadalive/scripts)
            touch "$HOME/restore-injected"
            exit 1
            ;;
        signal:*/new:*/armadalive/scripts)
            /bin/mv "$@" || exit $?
            touch "$HOME/failure-injected"
            kill -TERM "$PPID"
            exit 0
            ;;
    esac
fi
exec /bin/mv "$@"
""")
        self.shim("rm", """#!/bin/sh
for path do
    case "$FAIL_STAGE" in
        switch_cleanup) [ ! -f "$path/blocked-cleanup" ] || exit 1 ;;
        success_cleanup)
            if [ -f "$path/old/previous.py" ]; then
                touch "$HOME/failure-injected"
                exit 1
            fi
            ;;
    esac
done
exec /bin/rm "$@"
""")

    def shim(self, name, code):
        path = self.home / "bin" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(code)
        path.chmod(0o755)

    def run_installer(self, fail="", *, private=True, enabled="enabled", active="active",
                      provision=False, args=()):
        self.enabled.write_text(enabled + "\n")
        self.active.write_text(active + "\n")
        return subprocess.run(
            ["sh", str(INSTALLER), *args], capture_output=True, text=True, timeout=20,
            env=dict(
                os.environ, HOME=str(self.home), FAIL_STAGE=fail, TEST_PYTHON=sys.executable,
                TEST_USE_PRIVATE="1" if private else "0",
                TEST_PROVISION_PRIVATE="1" if provision else "", PYTHONPATH=str(self.modules),
                PATH=str(self.home / "bin") + os.pathsep + os.environ["PATH"],
            ),
        )

    def assert_previous_installation(self):
        for path, content in self.previous.items():
            self.assertTrue(path.is_file(), path)
            self.assertEqual(path.read_text(), content)
        for hook in self.hooks:
            self.assertEqual(os.readlink(hook), "previous hook")
        self.assertFalse((self.share / "armadalive/__main__.py").exists())

    def assert_injected_failure(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.failure.exists(), result.stdout + result.stderr)

    def test_failed_copy_leaves_previous_installation(self):
        result = self.run_installer("copy")
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertFalse(self.commands.exists())

    def assert_rejects_staged_package(self, fault):
        result = self.run_installer(fault)
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertFalse(self.commands.exists())

    def test_missing_entry_point_is_rejected_before_switch(self):
        self.assert_rejects_staged_package("validation")

    def test_missing_app_module_is_rejected_before_switch(self):
        self.assert_rejects_staged_package("missing_app")

    def test_app_module_directory_is_rejected_before_switch(self):
        self.assert_rejects_staged_package("invalid_type")

    def test_app_syntax_error_is_rejected_before_switch(self):
        self.assert_rejects_staged_package("syntax")

    def test_failed_switch_restores_previous_installation(self):
        result = self.run_installer("switch")
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertFalse((self.home / "restarts").exists())

    def test_cleanup_failure_does_not_interrupt_rollback(self):
        result = self.run_installer("switch_cleanup")
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertIn("Could not remove staging", result.stderr)

    def test_failed_restore_preserves_backup_and_continues_rollback(self):
        result = self.run_installer("rollback")
        self.assert_injected_failure(result)
        self.assertTrue((self.home / "restore-injected").exists())
        self.assertEqual(self.unit.read_text(), "previous unit\n")
        self.assertEqual((self.share / "armadalive/previous.py").read_text(), "previous app\n")
        for hook in self.hooks:
            self.assertEqual(os.readlink(hook), "previous hook")
        [backup] = list(self.share.glob(".armadalive-install.*/old/run.sh"))
        self.assertEqual(backup.read_text(), "previous scripts\n")
        self.assertIn(str(backup.parent), result.stderr)

    def test_cleanup_failure_keeps_successful_install_and_reports_backup(self):
        result = self.run_installer("success_cleanup")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.failure.exists())
        self.assertTrue((self.share / "armadalive/app.py").is_file())
        [backup] = list(self.share.glob(".armadalive-install.*/old/previous.py"))
        self.assertIn(str(backup.parent.parent), result.stderr)

    def test_term_after_switch_restores_previous_installation(self):
        result = self.run_installer("signal")
        self.assert_injected_failure(result)
        self.assertEqual(result.returncode, 143)
        self.assert_previous_installation()

    def test_failed_restart_restores_and_restarts_previous_active_installation(self):
        result = self.run_installer("restart")
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertEqual((self.home / "restarts").read_text(), "new\nold\n")
        self.assertEqual(self.active.read_text(), "active\n")
        self.assertEqual(self.enabled.read_text(), "enabled\n")

    def test_failed_recovery_restart_reports_retained_staging(self):
        result = self.run_installer("recovery")
        self.assert_injected_failure(result)
        self.assertTrue((self.home / "restore-injected").exists())
        self.assert_previous_installation()
        self.assertEqual((self.home / "restarts").read_text(), "new\nold\n")
        [manifest] = list(self.share.glob(".install.*"))
        self.assertIn(str(manifest), result.stderr)
        self.assertTrue((Path((manifest / "app").read_text().strip()) / "failed/app.py").is_file())

    def test_inactive_new_service_rolls_back_to_previously_inactive_installation(self):
        result = self.run_installer("inactive", enabled="disabled", active="inactive")
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertEqual((self.home / "restarts").read_text(), "new\n")
        self.assertEqual(self.active.read_text(), "inactive\n")
        self.assertEqual(self.enabled.read_text(), "disabled\n")

    def test_failed_enable_restores_previous_disabled_active_state(self):
        result = self.run_installer("enable", enabled="disabled")
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertEqual(self.enabled.read_text(), "disabled\n")
        self.assertEqual((self.home / "restarts").read_text(), "new\nold\n")

    def test_failed_enable_removes_partial_first_install_and_disables_service(self):
        for path in self.previous:
            path.unlink()
        for hook in self.hooks:
            hook.unlink()
        (self.share / "armadalive").rmdir()
        (self.share / "scripts").rmdir()

        result = self.run_installer("enable", enabled="missing", active="missing")
        self.assert_injected_failure(result)
        self.assertFalse((self.share / "armadalive").exists())
        self.assertFalse((self.share / "scripts").exists())
        self.assertFalse((self.share / "esde-event.py").exists())
        self.assertFalse(self.unit.exists())
        self.assertFalse(self.desktop.exists())
        for hook in self.hooks:
            self.assertFalse(hook.is_symlink())
        self.assertEqual(self.enabled.read_text(), "disabled\n")
        self.assertEqual(self.active.read_text(), "inactive\n")
        self.assertEqual((self.home / "restarts").read_text(), "new\n")

    def test_failed_enable_restores_previous_runtime_enablement(self):
        result = self.run_installer("enable", enabled="enabled-runtime")
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertEqual(self.enabled.read_text(), "enabled-runtime\n")
        self.assertEqual((self.home / "restarts").read_text(), "new\nold\n")

    def test_failed_reload_restores_service_definition_without_restarting(self):
        result = self.run_installer("reload")
        self.assert_injected_failure(result)
        self.assert_previous_installation()
        self.assertFalse((self.home / "restarts").exists())
        self.assertEqual(self.commands.read_text().splitlines().count("--user daemon-reload"), 2)

    def test_success_replaces_app_scripts_and_hooks_without_moving_private_environment(self):
        original_python = self.private_python.stat()
        result = self.run_installer(enabled="disabled")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.share / "armadalive/previous.py").exists())
        self.assertTrue((self.share / "armadalive/qml/Main.qml").is_file())
        self.assertTrue(os.access(self.share / "scripts/run.sh", os.X_OK))
        self.assertTrue(os.access(self.share / "esde-event.py", os.X_OK))
        for hook in self.hooks:
            self.assertTrue(hook.samefile(self.share / "esde-event.py"))
        self.assertTrue(os.path.samestat(self.private_python.stat(), original_python))
        self.assertEqual(self.old_venv.read_text(), "previous environment\n")
        self.assertEqual(self.unit.read_bytes(), (INSTALLER.parent / "data/armadalive.service").read_bytes())
        self.assertEqual(self.desktop.read_bytes(), (INSTALLER.parent / "data/armadalive.desktop").read_bytes())
        self.assertEqual(self.enabled.read_text(), "enabled\n")
        self.assertEqual((self.home / "restarts").read_text(), "new\n")
        self.assertFalse(list(self.home.rglob(".armadalive-install.*")))

    def test_system_python_install_does_not_create_private_environment(self):
        self.private_python.unlink()
        self.private_python.parent.rmdir()
        self.old_venv.unlink()
        self.venv.rmdir()
        result = self.run_installer(private=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.venv.exists())
        self.assertTrue((self.share / "armadalive/qml/Main.qml").is_file())

    def test_failed_private_environment_provisioning_restores_previous_environment(self):
        self.private_python.unlink()
        result = self.run_installer("pip", provision=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PySide6-Addons", (self.home / "pip-arguments").read_text())
        self.assert_previous_installation()
        self.assertTrue(self.old_venv.is_file(), result.stdout + result.stderr)
        self.assertEqual(self.old_venv.read_text(), "previous environment\n")
        self.assertFalse(self.private_python.exists())
        self.assertFalse((self.home / "restarts").exists())

    def test_failed_restart_restores_previous_private_environment_after_reprovisioning(self):
        self.private_python.unlink()
        result = self.run_installer("restart", provision=True, active="inactive")
        self.assert_injected_failure(result)
        self.assertIn("PySide6-Addons", (self.home / "pip-arguments").read_text())
        self.assert_previous_installation()
        self.assertTrue(self.old_venv.is_file(), result.stdout + result.stderr)
        self.assertEqual(self.old_venv.read_text(), "previous environment\n")
        self.assertFalse(self.private_python.exists())

    def test_success_rebuilds_broken_private_environment_at_its_final_path(self):
        self.private_python.unlink()
        result = self.run_installer(provision=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.home / "pip-arguments").read_text().splitlines(),
                         ["install", "--quiet", "PySide6-Essentials", "PySide6-Addons", "pymupdf"])
        self.assertTrue(os.access(self.private_python, os.X_OK))
        self.assertFalse(self.old_venv.exists())

    def test_running_install_excludes_install_and_uninstall(self):
        lock = self.home / ".cache/armadalive/install.lock"
        lock.parent.mkdir(parents=True)
        with lock.open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            for args in ((), ("--uninstall",)):
                with self.subTest(args=args):
                    result = self.run_installer(args=args)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("installation is in progress", result.stderr)
                    self.assert_previous_installation()
                    self.assertFalse(self.commands.exists())
