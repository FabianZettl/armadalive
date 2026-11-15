import subprocess
import threading
import unittest
from unittest import mock

from armadalive import commands, controls
from tests.common import QObject
from tests.test_runtime import runtime_object, wait_for


class CommandFailures(unittest.TestCase):
    def test_failed_toggle_notifies_on_owner_and_can_retry(self):
        owner = threading.get_ident()
        attempts, completed, notices = [], [], []
        snapshots = iter([{"muted": False}])

        def run(args, **kwargs):
            attempts.append((args[-1], threading.get_ident()))
            if len(attempts) == 1:
                raise subprocess.CalledProcessError(7, args)
            return subprocess.CompletedProcess(args, 0)

        with mock.patch.object(controls.Controls, "_read", staticmethod(lambda: next(snapshots, None))), \
                mock.patch.object(controls.Controls, "_read_vpn", staticmethod(lambda: None)), \
                mock.patch.object(commands.subprocess, "run", run), \
                runtime_object(controls.Controls()) as obj:
            obj.notice.connect(lambda code, detail: notices.append((code, detail, threading.get_ident())))
            obj._commands.completed.connect(lambda *result: completed.append((*result, threading.get_ident())))
            self.assertTrue(wait_for(lambda: obj.state.get("muted") is False))

            obj.toggleMute()
            self.assertTrue(wait_for(lambda: len(completed) == 1))
            self.assertEqual(completed, [("mute", True, False, owner)])
            self.assertEqual(notices, [("commandfail", "", owner)])
            self.assertFalse(obj.state["muted"])

            obj.toggleMute()
            self.assertTrue(wait_for(lambda: len(completed) == 2))
            self.assertEqual(completed[-1], ("mute", True, True, owner))
            self.assertEqual(notices, [("commandfail", "", owner)])
            self.assertTrue(obj.state["muted"])

        self.assertEqual([target for target, _ in attempts], ["1", "1"])
        self.assertNotIn(owner, [worker for _, worker in attempts])

    def test_worker_warnings_include_operation_and_bounded_reason(self):
        errors = (
            (subprocess.CalledProcessError(7, ("device-tool", "private-argument")), "exit status 7"),
            (subprocess.TimeoutExpired(("device-tool", "private-argument"), 5), "timed out"),
            (RuntimeError("permission denied\n" + "failure detail " * 128 + "private-tail"), "permission denied"),
        )

        with runtime_object(QObject()) as owner:
            queue = commands.Commands(owner)
            completed = []
            queue.completed.connect(lambda *result: completed.append(result))

            for i, (error, reason) in enumerate(errors, 1):
                with self.subTest(reason=reason):
                    def fail():
                        raise error

                    with self.assertLogs(commands.log, "WARNING") as logs:
                        queue.submit("wifi-saver", fail)
                        self.assertTrue(wait_for(lambda: len(completed) == i))

                    self.assertEqual(completed[-1], ("wifi-saver", None, False))
                    self.assertEqual(len(logs.records), 1)
                    message = logs.records[0].getMessage()
                    self.assertIn("wifi-saver", message)
                    self.assertIn(reason, message)
                    self.assertNotIn("private-argument", message)
                    self.assertNotIn("private-tail", message)
                    self.assertNotIn("\n", message)
                    self.assertLess(len(message), 220)
