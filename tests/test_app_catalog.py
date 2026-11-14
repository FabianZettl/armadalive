import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.common import wait_for
from armadalive import apps


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
