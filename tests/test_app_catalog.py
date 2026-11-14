import json
import stat
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.common import wait_for
from armadalive import apps, backup


class Catalog(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = Path(tmp.name) / "apps.json"
        for module, name, value in (
            (apps, "CONFIG", str(self.config)),
            (apps, "_catalog", lambda: {}),
            (apps.esdelib, "games", lambda **_: {}),
            (apps.esdelib, "systems", lambda: {}),
        ):
            patch = mock.patch.object(module, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_startup_and_picker_reads_do_not_wait_for_the_scan(self):
        owner = threading.get_ident()
        started, release = threading.Event(), threading.Event()

        def scan(**_):
            self.assertNotEqual(threading.get_ident(), owner)
            started.set()
            release.wait(3)
            return [dict(id="steam:10", name="A game", icon="")]

        with mock.patch.object(apps.steamlib, "games", scan):
            backend = apps.Apps()
            self.assertTrue(started.wait(1))
            try:
                self.assertEqual(backend.catalog(), [])
                self.assertEqual(backend.slots, [{}])
                self.assertIn("apps", [g["id"] for g in backend.groups()])
            finally:
                release.set()
            wait_for(lambda: bool(backend.catalog()))
            self.assertEqual(backend.catalog()[0]["name"], "A game")

    def test_unavailable_pins_survive_an_edit_and_recognize_the_next_mount(self):
        self.config.write_text(json.dumps({"slots": ["steam:10", "folder:1"], "folders": {
            "1": {"name": "Games", "items": ["steam:10"]}}, "next": 2}))
        games = []
        with mock.patch.object(apps.steamlib, "games", lambda **_: games[:]):
            backend = apps.Apps()
            wait_for(lambda: not backend.catalogLoading)
            backend.renameFolder("folder:1", "Favorites")
            backend.flush()
            self.assertEqual(json.loads(self.config.read_text())["slots"], ["steam:10", "folder:1"])
            self.assertEqual(backend.slots[0]["id"], "steam:10")
            self.assertEqual(backend.folderItems("folder:1")[0]["id"], "steam:10")
            games.append(dict(id="steam:10", name="A game", icon=""))
            backend.refreshCatalog()
            wait_for(lambda: backend.slots[0]["name"] == "A game")
            self.assertEqual(backend.folderItems("folder:1")[0]["name"], "A game")

    def test_scan_errors_keep_last_catalog_and_next_refresh_recovers(self):
        steam = mock.Mock(side_effect=[
            [dict(id="steam:10", name="Original", icon="")],
            OSError("device unavailable"),
            [dict(id="steam:10", name="Renamed", icon="")],
        ])
        with mock.patch.object(apps.steamlib, "games", steam), self.assertLogs(apps.log, level="ERROR"):
            backend = apps.Apps()
            wait_for(lambda: not backend.catalogLoading)
            backend.refreshCatalog()
            wait_for(lambda: not backend.catalogLoading)
            self.assertEqual(backend.catalog()[0]["name"], "Original")
            backend.refreshCatalog()
            wait_for(lambda: not backend.catalogLoading)
            self.assertEqual(backend.catalog()[0]["name"], "Renamed")

    def test_overlapping_refreshes_discard_the_stale_scan_and_coalesce(self):
        first_started, release_first = threading.Event(), threading.Event()
        second_started, release_second = threading.Event(), threading.Event()
        calls = []

        def scan():
            calls.append(1)
            if len(calls) == 1:
                first_started.set()
                release_first.wait(3)
                return [dict(id="steam:10", name="Old", icon="")]
            second_started.set()
            release_second.wait(3)
            return [dict(id="steam:11", name="Latest", icon="")]

        with mock.patch.object(apps.steamlib, "games", scan):
            backend = apps.Apps()
            try:
                self.assertTrue(first_started.wait(1))
                for _ in range(10):
                    backend.refreshCatalog()
                self.assertEqual(len(calls), 1)
                release_first.set()
                wait_for(second_started.is_set)
                self.assertEqual(backend.catalog(), [])
            finally:
                release_first.set()
                release_second.set()
            wait_for(lambda: not backend.catalogLoading)
            self.assertEqual(len(calls), 2)
            self.assertEqual([row["name"] for row in backend.catalog()], ["Latest"])

    def test_rom_cover_rendering_runs_off_thread_only_for_pinned_tiles(self):
        cover = str(self.config.with_name("A.png"))
        games = {"snes": [dict(id="esde:snes/A.sfc", name="A", cover=cover, rom="/roms/A.sfc")]}
        owner = threading.get_ident()
        calls = []

        def render(path):
            calls.append((threading.get_ident(), path))
            return "file:///rounded.png"

        with mock.patch.object(apps.esdelib, "games", lambda **_: games), \
                mock.patch.object(apps.esdelib, "systems", lambda: {"snes": {"fullname": "Super Nintendo"}}), \
                mock.patch.object(apps.steamlib, "games", lambda: []), \
                mock.patch.object(apps.steamlib, "_url", render):
            backend = apps.Apps()
            wait_for(lambda: not backend.catalogLoading)
            self.assertEqual(calls, [])
            self.assertTrue(backend.catalog()[0]["icon"].endswith("A.png"))
            backend.assign(0, "esde:snes/A.sfc")
            wait_for(lambda: backend.slots[0]["icon"] == "file:///rounded.png")
            backend.flush()
            self.assertEqual(len(calls), 1)
            self.assertNotEqual(calls[0][0], owner)
            self.assertEqual(calls[0][1], cover)

    def test_refresh_retains_pin_and_preview_while_replacement_art_is_pending(self):
        rom = dict(id="esde:snes/A.sfc", name="A", cover="/covers/A.png", rom="/roms/A.sfc")
        self.config.write_text(json.dumps({"slots": [rom["id"], "folder:1"], "folders": {
            "1": {"name": "Games", "items": [rom["id"]]}}}))
        started, release = threading.Event(), threading.Event()
        rounds = []

        def render(path):
            rounds.append(path)
            if len(rounds) == 1:
                return "file:///initial.png"
            started.set()
            release.wait(3)
            return "file:///replacement.png"

        with mock.patch.object(apps.esdelib, "games", lambda **_: {"snes": [rom]}), \
                mock.patch.object(apps.esdelib, "systems", lambda: {"snes": {"fullname": "SNES"}}), \
                mock.patch.object(apps.steamlib, "games", return_value=[]), \
                mock.patch.object(apps.steamlib, "_url", render):
            backend = apps.Apps()
            wait_for(lambda: backend.slots[0]["icon"] == "file:///initial.png")
            backend.refreshCatalog()
            try:
                wait_for(started.is_set)
                self.assertEqual(backend.slots[0]["icon"], "file:///initial.png")
                self.assertEqual(backend.slots[1]["preview"], ["file:///initial.png"])
            finally:
                release.set()
            wait_for(lambda: backend.slots[0]["icon"] == "file:///replacement.png")

    def test_delayed_durable_save_does_not_block_edits_and_flushes_latest(self):
        started, release = threading.Event(), threading.Event()
        real_fsync = apps.os.fsync
        writes = []
        owner = threading.get_ident()

        def delayed_sync(fd):
            if stat.S_ISREG(apps.os.fstat(fd).st_mode):
                writes.append(threading.get_ident())
                if len(writes) == 1:
                    started.set()
                    release.wait(3)
            return real_fsync(fd)

        with mock.patch.object(apps.steamlib, "games", return_value=[]), \
                mock.patch.object(apps.os, "fsync", delayed_sync):
            backend = apps.Apps()
            wait_for(lambda: not backend.catalogLoading)
            backend.assign(0, "folder:new")
            try:
                self.assertTrue(started.wait(1))
                self.assertNotEqual(writes[0], owner)
                for name in ("First", "Second", "Final"):
                    backend.renameFolder("folder:1", name)
                self.assertEqual(backend.slots[0]["name"], "Final")
                self.assertEqual(len(writes), 1)
            finally:
                release.set()
            backend.flush()
            self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Final")
            self.assertEqual(len(writes), 2)

    def test_failed_save_logs_the_error_and_next_edit_can_recover(self):
        with mock.patch.object(apps.steamlib, "games", return_value=[]):
            backend = apps.Apps()
            wait_for(lambda: not backend.catalogLoading)
            backend.assign(0, "folder:new")
            backend.flush()
            with mock.patch.object(apps.os, "replace", side_effect=OSError("device unavailable")), \
                    self.assertLogs(apps.log, level="ERROR") as failure:
                backend.renameFolder("folder:1", "Unsaved name")
                backend.flush()
            self.assertIn(str(self.config), failure.output[0])
            self.assertEqual(backend.slots[0]["name"], "Unsaved name")
            self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "")
            backend.renameFolder("folder:1", "Saved name")
            backend.flush()
            self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Saved name")

    def backup_backend(self):
        self.config.write_text(json.dumps({"slots": ["folder:1"], "folders": {
            "1": {"name": "Current", "items": []}}, "next": 2}))
        patch = mock.patch.object(apps.steamlib, "games", return_value=[])
        patch.start()
        self.addCleanup(patch.stop)
        backend = apps.Apps()
        wait_for(lambda: not backend.catalogLoading)
        self.addCleanup(backend.flush)
        for name, value in (("CONFIG_DIR", str(self.config.parent)),
                            ("FILE", str(self.config.with_name("backup.json")))):
            patch = mock.patch.object(backup, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        coordinator = backup.Backup((backend,))
        return backend, coordinator

    def block_layout_write(self):
        started, release = threading.Event(), threading.Event()
        original = apps._write_layout

        def delayed(path, snapshot):
            started.set()
            if not release.wait(3):
                raise OSError("test write was not released")
            original(path, snapshot)

        patch = mock.patch.object(apps, "_write_layout", delayed)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(release.set)
        return started, release

    def test_backup_export_waits_for_accepted_layout_without_blocking_edits(self):
        backend, coordinator = self.backup_backend()
        started, release = self.block_layout_write()
        backend.renameFolder("folder:1", "Accepted edit")
        self.assertTrue(started.wait(1))
        try:
            coordinator.save()
            self.assertNotEqual(coordinator.state["message"], "saved")
            coordinator.restore()  # A second operation cannot interrupt the export.
            backend.renameFolder("folder:1", "Edit during backup")
        finally:
            release.set()
        wait_for(lambda: coordinator.state["message"] == "saved")
        exported = json.loads(Path(backup.FILE).read_text())
        self.assertEqual(exported["files"]["apps.json"]["folders"]["1"]["name"], "Accepted edit")
        backend.flush()
        self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Edit during backup")

    def test_backup_restore_drains_layout_then_holds_new_writes_until_restart(self):
        backend, coordinator = self.backup_backend()
        restored = {"slots": ["folder:9"], "folders": {
            "9": {"name": "Restored", "items": []}}, "next": 10}
        Path(backup.FILE).write_text(json.dumps({"files": {"apps.json": restored}}))
        started, release = self.block_layout_write()
        backend.renameFolder("folder:1", "Pending edit")
        self.assertTrue(started.wait(1))
        with mock.patch.object(backup.QTimer, "singleShot"):
            try:
                coordinator.restore()
                self.assertNotEqual(coordinator.state["message"], "restored")
                self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Current")
                backend.renameFolder("folder:1", "Edit during restore")
            finally:
                release.set()
            wait_for(lambda: coordinator.state["message"] == "restored")
        backend.renameFolder("folder:1", "Edit before restart")
        backend.flush()
        self.assertEqual(json.loads(self.config.read_text()), restored)

    def test_failed_restore_resumes_deferred_layout_edits(self):
        backend, coordinator = self.backup_backend()
        Path(backup.FILE).write_text(json.dumps({"not": "a backup"}))
        started, release = self.block_layout_write()
        backend.renameFolder("folder:1", "Pending edit")
        self.assertTrue(started.wait(1))
        try:
            coordinator.restore()
            self.assertEqual(coordinator.state["message"], "")
            backend.renameFolder("folder:1", "Kept after failure")
        finally:
            release.set()
        wait_for(lambda: "not an ArmadaLive backup" in coordinator.state["message"])
        backend.flush()
        self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Kept after failure")

    def test_failed_layout_write_refuses_stale_export_and_next_edit_recovers(self):
        backend, coordinator = self.backup_backend()
        with mock.patch.object(apps, "_write_layout", side_effect=OSError("layout device unavailable")), \
                self.assertLogs(apps.log, level="ERROR"):
            backend.renameFolder("folder:1", "Unsaved")
            backend.flush()
        coordinator.save()
        self.assertIn("layout device unavailable", coordinator.state["message"])
        self.assertFalse(Path(backup.FILE).exists())
        backend.renameFolder("folder:1", "Recovered")
        backend.flush()
        coordinator.save()
        self.assertEqual(coordinator.state["message"], "saved")
        self.assertEqual(json.loads(Path(backup.FILE).read_text())["files"]["apps.json"]["folders"]["1"]["name"], "Recovered")

    def test_failed_restart_resumes_deferred_layout_edits(self):
        backend, coordinator = self.backup_backend()
        Path(backup.FILE).write_text(json.dumps({"files": {"apps.json": {
            "slots": [], "folders": {}, "next": 1}}}))
        with mock.patch.object(backup.QTimer, "singleShot") as restart:
            coordinator.restore()
        self.assertEqual(coordinator.state["message"], "restored")
        backend.renameFolder("folder:1", "Kept after restart failure")
        with mock.patch.object(backup.os, "execv", side_effect=OSError("restart unavailable")):
            restart.call_args.args[1]()
        self.assertEqual(coordinator.state["message"], "restart unavailable")
        backend.flush()
        self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Kept after restart failure")

    def test_new_layout_directory_survives_failed_first_write_and_retry(self):
        nested = self.config.parent / "new" / "nested" / "apps.json"
        with mock.patch.object(apps, "CONFIG", str(nested)), \
                mock.patch.object(apps.steamlib, "games", return_value=[]):
            backend = apps.Apps()
            wait_for(lambda: not backend.catalogLoading)
            with mock.patch.object(apps.os, "replace", side_effect=OSError("first replacement failed")), \
                    self.assertLogs(apps.log, level="ERROR"):
                backend.assign(0, "folder:new")
                backend.flush()
            self.assertFalse(nested.exists())
            backend.renameFolder("folder:1", "Recovered new layout")
            backend.flush()
        self.assertEqual(json.loads(nested.read_text())["folders"]["1"]["name"], "Recovered new layout")
