import hashlib, io, json, os, re, subprocess, tarfile, tempfile, threading, time, unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest import mock

from tests.common import app
from armadalive import updater


def wait_for(condition):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("Asynchronous update did not arrive")


class Readiness(unittest.TestCase):
    def test_ready_uses_the_service_manager_address(self):
        for address, expected in (("/run/notify", "/run/notify"), ("@notify", "\0notify")):
            with self.subTest(address=address), mock.patch.dict(os.environ, {"NOTIFY_SOCKET": address}), \
                 mock.patch.object(updater.socket, "socket") as create_socket:
                updater.notify_ready()
                create_socket.assert_called_once_with(updater.socket.AF_UNIX, updater.socket.SOCK_DGRAM)
                create_socket.return_value.__enter__.return_value.sendto.assert_called_once_with(b"READY=1", expected)

    def test_standalone_app_has_no_service_manager_notification(self):
        with mock.patch.dict(os.environ, {"NOTIFY_SOCKET": ""}), mock.patch.object(updater.socket, "socket") as sock:
            updater.notify_ready()
        sock.assert_not_called()


class Version(unittest.TestCase):
    def test_comparison(self):
        self.assertGreater(updater._version("v0.10.0"), updater._version("0.9.9"))
        self.assertEqual(updater._version("v1.2.3"), updater._version("1.2.3"))

    def test_sha256(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x"
            path.write_bytes(b"abc")
            self.assertEqual(updater.sha256(path), hashlib.sha256(b"abc").hexdigest())


class Check(unittest.TestCase):
    def check(self, release):
        with tempfile.TemporaryDirectory() as cache, mock.patch.multiple(
            updater, REPO_ID="o/r", CACHE=cache,
            _get=lambda url, timeout=15: io.BytesIO(json.dumps(release).encode()),
        ):
            u = updater.Updater()
            u.check()
            wait_for(lambda: u.state["status"] != "checking")
            return u.state

    def test_a_newer_release_with_a_checksum_is_offered(self):
        s = self.check({"tag_name": "v99.0.0", "assets": [
            {"name": updater.ASSET, "browser_download_url": "https://x/a"}, {"name": updater.CHECKSUM, "browser_download_url": "https://x/s"}]})
        self.assertEqual((s["status"], s["latest"]), ("available", "v99.0.0"))

    def test_a_newer_release_without_a_checksum_is_refused(self):
        s = self.check({"tag_name": "v99.0.0", "assets": [{"name": updater.ASSET, "browser_download_url": "https://x/a"}]})
        self.assertEqual(s["status"], "error")
        self.assertIn("checksum", s["message"])

    def test_malformed_release_metadata_is_terminal(self):
        for release in (None, [], {"tag_name": 99}, {"tag_name": "latest"},
                        {"tag_name": "v99.0.0", "assets": None}, {"tag_name": "v99.0.0", "assets": [{}]}):
            with self.subTest(release=release):
                self.assertEqual(self.check(release)["status"], "error")

    def test_the_same_version_is_up_to_date(self):
        self.assertEqual(self.check({"tag_name": "v0.0.1", "assets": []})["status"], "uptodate")


class Install(unittest.TestCase):
    def setUp(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        patch = mock.patch.multiple(updater, CACHE=cache.name, REPO_ID="o/r")
        patch.start()
        self.addCleanup(patch.stop)

    def available(self, tag):
        obj = updater.Updater()
        obj._set(status="available", latest=tag, tarball="asset", sha="checksum")
        return obj

    def run_install(self, checksum=None, installer_exit=0, service_error=None, tag="v99.0.0", obj=None,
                    installer_script=None):
        archive = io.BytesIO()
        script = installer_script or f"#!/bin/sh\nexit {installer_exit}\n".encode()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            member = tarfile.TarInfo("release/install.sh")
            member.size = len(script)
            member.mode = 0o755
            tar.addfile(member, io.BytesIO(script))
        release = archive.getvalue()
        if checksum is None:
            checksum = (hashlib.sha256(release).hexdigest() + "  armadalive.tar.gz\n").encode()
        obj = obj or self.available(tag)

        def fetch(url, *args):
            if url == "asset":
                return io.BytesIO(release)
            return io.BytesIO(checksum) if isinstance(checksum, bytes) else checksum

        with mock.patch.object(updater, "_get", side_effect=fetch), mock.patch.object(
            updater.subprocess, "run", side_effect=service_error
        ) as start:
            obj.install()
            wait_for(lambda: obj.state["status"] != "installing")
        return obj, start.call_args.args[0] if start.called else None

    def test_missing_or_malformed_checksum_fails_without_starting_service(self):
        for checksum in (b"", b" \n\t", b"no", b"a" * 63, b"z" * 64, b"\xff", b"a" * 64 + b" " * 5000):
            with self.subTest(checksum=checksum[:70]):
                updater_object, command = self.run_install(checksum=checksum)
                self.assertEqual(updater_object.state["status"], "error")
                self.assertIn("checksum", updater_object.state["message"])
                self.assertIsNone(command)

    def test_mismatching_checksum_fails_without_starting_service(self):
        updater_object, command = self.run_install(checksum=b"0" * 64)
        self.assertEqual(updater_object.state["status"], "error")
        self.assertIn("checksum mismatch", updater_object.state["message"])
        self.assertIsNone(command)

    def test_service_launch_failure_is_terminal_after_application_restarts(self):
        old_app, _ = self.run_install(service_error=OSError("service manager unavailable"))
        self.assertEqual(old_app.state["status"], "error")
        new_app = updater.Updater()
        self.assertEqual(new_app.state["status"], "error")
        self.assertIn("service manager unavailable", new_app.state["message"])

    def test_success_is_visible_only_after_installer_finishes(self):
        old_app, command = self.run_install()
        self.assertEqual(old_app.state["status"], "started")
        restarted_app = updater.Updater()
        self.assertEqual(restarted_app.state["status"], "started")
        subprocess.run(command[command.index("sh"):], check=True, timeout=2)
        wait_for(lambda: restarted_app.state["status"] == "installed")
        self.assertEqual(updater.Updater().state["status"], "installed")
        self.assertEqual(updater.Updater().state["latest"], "v99.0.0")

    def test_transient_command_preserves_shell_and_uses_downloader_lock(self):
        installer = b'#!/bin/sh\n[ "$EXPECTED_LOCK" -ef /proc/self/fd/9 ]\n'
        _, command = self.run_install(installer_script=installer)
        launcher = command[command.index("sh"):]

        # The manager substitutes braced environment expressions in each argument.
        # These arguments should reach the shell unchanged with no matching variables.
        def expand(arg):
            return re.sub(r"\$\$|\$\{[^}]*\}", lambda m: "$" if m[0] == "$$" else "", arg)

        expanded = [expand(arg) for arg in launcher]
        self.assertEqual(expanded, launcher)
        expected_lock = Path(updater.CACHE) / "attempt.lock"
        result = subprocess.run(expanded, env=dict(os.environ, EXPECTED_LOCK=str(expected_lock)),
                                capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(updater.Updater().state["status"], "installed")

    def test_missing_completion_record_eventually_fails_after_restart(self):
        old_app, _ = self.run_install()
        self.assertEqual(old_app.state["status"], "started")
        with mock.patch.object(updater.time, "time", return_value=updater.time.time() + updater.INSTALL_TIMEOUT + 61):
            restarted_app = updater.Updater()
        self.assertEqual(restarted_app.state["status"], "error")
        self.assertIn("did not report", restarted_app.state["message"])

    def test_failed_new_checksum_supersedes_previous_installed_result(self):
        _, command = self.run_install()
        subprocess.run(command[command.index("sh"):], check=True, timeout=2)
        self.assertEqual(updater.Updater().state["status"], "installed")
        failed_update, command = self.run_install(checksum=b" \n", tag="v100.0.0")
        self.assertIsNone(command)
        self.assertEqual(failed_update.state["status"], "error")
        restarted_app = updater.Updater()
        self.assertEqual((restarted_app.state["status"], restarted_app.state["latest"]), ("error", "v100.0.0"))
        self.assertFalse(list(Path(updater.CACHE).glob("install-*.result")))

    def test_interrupted_checksum_is_terminal_and_removes_staging(self):
        class InterruptedChecksum(io.BytesIO):
            def read(self, *args):
                raise IncompleteRead(b"checksum fragment")

        update, command = self.run_install(checksum=InterruptedChecksum())
        self.assertIsNone(command)
        self.assertEqual(update.state["status"], "error")
        self.assertEqual(updater.Updater().state["status"], "error")
        self.assertFalse(list(Path(updater.CACHE).glob("install-*/")))

    def test_stale_available_instance_cannot_replace_launched_update(self):
        stale = self.available("v100.0.0")
        _, command = self.run_install()
        duplicate, second_command = self.run_install(obj=stale)
        self.assertIsNone(second_command)
        self.assertEqual((duplicate.state["status"], duplicate.state["latest"]), ("started", "v99.0.0"))
        subprocess.run(command[command.index("sh"):], check=True, timeout=2)
        self.assertEqual(updater.Updater().state["latest"], "v99.0.0")

    def test_concurrent_instances_do_not_download_over_each_other(self):
        first, second = self.available("v99.0.0"), self.available("v100.0.0")
        downloading, release = threading.Event(), threading.Event()
        calls = []

        def fetch(*args):
            calls.append(args)
            downloading.set()
            release.wait(2)
            raise OSError("download interrupted")

        with mock.patch.object(updater, "_get", side_effect=fetch):
            first.install()
            try:
                self.assertTrue(downloading.wait(1))
                observer = updater.Updater()
                self.assertEqual((observer.state["status"], observer.state["latest"]), ("installing", "v99.0.0"))
                # Exercise both instances while the same download still owns the attempt.
                second._set(status="installing")
                second._install()
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
                wait_for(lambda: first.state["status"] == "error")
        wait_for(lambda: observer.state["status"] == "error")
        self.assertEqual(updater.Updater().state["latest"], "v99.0.0")

    def test_nonzero_installer_exit_is_visible_after_restarting(self):
        old_app, command = self.run_install(installer_exit=23)
        result = subprocess.run(command[command.index("sh"):], timeout=2)
        self.assertEqual(result.returncode, 23)
        old_app._poll_completion()
        self.assertEqual(old_app.state["status"], "error")
        new_app = updater.Updater()
        self.assertEqual(new_app.state["status"], "error")
        self.assertIn("23", new_app.state["message"])


if __name__ == "__main__":
    unittest.main()
