import base64
import json
import stat
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage

from tests.common import delete_qobject, wait_for
from armadalive import apps, backup, steamshortcuts


@contextmanager
def catalog_fixture(*args):
    backend = apps.Apps(*args)
    try:
        yield backend
    finally:
        try:
            backend.flush()
        finally:
            wait_for(lambda: (not backend.catalogLoading and not backend._art_running
                              and backend._writer is None and backend._shortcuts._preparing is None))
            delete_qobject(backend)


class DesktopOverrides(unittest.TestCase):
    def test_hidden_and_no_display_overrides_mask_the_system_entry(self):
        with TemporaryDirectory() as tmp:
            user, system = (Path(tmp) / name for name in ("user", "system"))
            for directory in (user, system):
                directory.mkdir()
            for name, key in (("hidden", "Hidden"), ("no-display", "NoDisplay")):
                (user / f"{name}.desktop").write_text(f"[Desktop Entry]\nType=Application\nName=User\n{key}=true\n")
                (system / f"{name}.desktop").write_text("[Desktop Entry]\nType=Application\nName=System\n")
            (system / "visible.desktop").write_text("[Desktop Entry]\nType=Application\nName=Visible\n")
            with mock.patch.object(apps, "APP_DIRS", [user, system]):
                self.assertEqual(set(apps._catalog()), {"visible"})


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

        with mock.patch.object(apps.steamlib, "games", scan), catalog_fixture() as backend:
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
        with mock.patch.object(apps.steamlib, "games", lambda **_: games[:]), catalog_fixture() as backend:
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
        with mock.patch.object(apps.steamlib, "games", steam), self.assertLogs(apps.log, level="ERROR"), \
                catalog_fixture() as backend:
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

        with mock.patch.object(apps.steamlib, "games", scan), catalog_fixture() as backend:
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
                mock.patch.object(apps.steamlib, "_url", render), \
                catalog_fixture() as backend:
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
                mock.patch.object(apps.steamlib, "_url", render), \
                catalog_fixture() as backend:
            wait_for(lambda: backend.slots[0]["icon"] == "file:///initial.png")
            backend.refreshCatalog()
            try:
                wait_for(started.is_set)
                self.assertEqual(backend.slots[0]["icon"], "file:///initial.png")
                self.assertEqual(backend.slots[1]["preview"], ["file:///initial.png"])
            finally:
                release.set()
            wait_for(lambda: backend.slots[0]["icon"] == "file:///replacement.png")

    def test_first_rom_launch_prepares_real_art_off_thread_and_drops_duplicate_taps(self):
        name = "Big game"
        rom = dict(id="esde:snes/Big game.sfc", name=name, cover="", rom="/roms/Big game.sfc")
        media = self.config.parent / "snes" / "fanart"
        media.mkdir(parents=True)
        fanart = QImage(2560, 1440, QImage.Format.Format_RGB32)
        fanart.fill(0xFF336699)
        self.assertTrue(fanart.save(str(media / "Big game.jpg")))

        owner = threading.get_ident()
        started, release = threading.Event(), threading.Event()
        artwork = steamshortcuts.artwork
        prepared_on, steam_calls, heartbeats, notices = [], [], [], []

        def gated_artwork(system, path):
            prepared_on.append(threading.get_ident())
            started.set()
            release.wait(1.5)
            return artwork(system, path)

        def dispatch(expression, done, **_):
            steam_calls.append((threading.get_ident(), expression, done))

        with mock.patch.object(apps.esdelib, "games", return_value={"snes": [rom]}), \
                mock.patch.object(apps.esdelib, "systems", return_value={"snes": {"fullname": "SNES"}}), \
                mock.patch.object(apps.esdelib, "command", return_value=["/usr/bin/emu", rom["rom"]]), \
                mock.patch.object(apps.steamlib, "games", return_value=[]), \
                mock.patch.object(steamshortcuts, "SHORTCUTS", str(self.config.parent / "missing.vdf")), \
                mock.patch.object(steamshortcuts, "MEDIA", str(self.config.parent)), \
                mock.patch.object(steamshortcuts, "artwork", gated_artwork), \
                mock.patch.object(steamshortcuts, "eval_js", dispatch), \
                catalog_fixture() as backend:
            shortcuts = backend._shortcuts
            shortcuts.notice.connect(lambda code, title: notices.append((code, title)))
            wait_for(lambda: not backend.catalogLoading)
            QTimer.singleShot(0, lambda: heartbeats.append(True))
            try:
                backend.launchId(rom["id"])
                wait_for(started.is_set)
                self.assertTrue(heartbeats)
                self.assertFalse(steam_calls)
                backend.launchId(rom["id"])
            finally:
                release.set()
            wait_for(lambda: len(steam_calls) == 1)
            thread, expression, added = steam_calls[0]
            self.assertEqual(thread, owner)
            self.assertEqual(len(prepared_on), 1)
            self.assertNotEqual(prepared_on[0], owner)
            payload = json.loads(expression[expression.rfind(")({") + 2:-1])
            images = {kind: QImage.fromData(base64.b64decode(data)) for kind, data, _ in payload["art"]}
            self.assertEqual(set(images), {1, 3})
            self.assertEqual((images[1].width(), images[1].height()), (1920, 1080))
            self.assertEqual((images[3].width(), images[3].height()), (764, 430))
            added(123)
            wait_for(lambda: len(steam_calls) == 2)
            self.assertEqual(steam_calls[1][0], owner)
            self.assertIn("SteamClient.Apps.RunGame", steam_calls[1][1])
            steam_calls[1][2](True)
            self.assertFalse(shortcuts.state["busy"])
            self.assertEqual(notices, [("launchRequested", name)])

    def test_duplicate_random_tap_cannot_dispatch_both_steam_and_emulated_games(self):
        rom = dict(id="esde:snes/Book.sfc", name="Book", cover="", rom="/roms/Book.sfc")
        native = dict(id="steam:10", name="Native", icon="")
        for first in (rom, native):
            with self.subTest(first=first["id"]):
                dispatches = []
                remaining = native if first is rom else rom
                with mock.patch.object(apps.esdelib, "games", return_value={"snes": [rom]}), \
                        mock.patch.object(apps.esdelib, "systems", return_value={"snes": {"fullname": "SNES"}}), \
                        mock.patch.object(apps.esdelib, "command", return_value=["/usr/bin/emu", rom["rom"]]), \
                        mock.patch.object(apps.steamlib, "games", return_value=[native]), \
                        mock.patch.object(apps.random, "choice", side_effect=[first["id"], remaining["id"]]) as choose, \
                        mock.patch.object(steamshortcuts, "known_appid", return_value=123), \
                        mock.patch.object(steamshortcuts, "eval_js", side_effect=lambda js, done, **_: dispatches.append((js, done))), \
                        mock.patch("armadalive.steamui.eval_js", side_effect=lambda js, done, **_: dispatches.append((js, done))), \
                        catalog_fixture() as backend:
                    wait_for(lambda: not backend.catalogLoading)
                    backend.launchId(apps.RANDOM)
                    backend.launchId(apps.RANDOM)
                    expected_gameid = (123 << 32) | 0x02000000 if first is rom else 10
                    wait_for(lambda: any(f'"{expected_gameid}"' in js for js, _ in dispatches))
                    self.assertEqual(len(dispatches), 1)
                    self.assertEqual(choose.call_count, 1)
                    dispatches[0][1](True)

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
                mock.patch.object(apps.os, "fsync", delayed_sync), \
                catalog_fixture() as backend:
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

    def test_transient_write_failure_retries_the_latest_accepted_rename(self):
        backend, _ = self.backup_backend()
        started, release = threading.Event(), threading.Event()
        original = apps._write_layout
        attempts = []

        def fail_first(path, snapshot):
            attempts.append(snapshot["folders"]["1"]["name"])
            if len(attempts) == 1:
                started.set()
                if not release.wait(3):
                    raise OSError("test write was not released")
                raise OSError("transient failure")
            original(path, snapshot)

        with mock.patch.object(apps, "_write_layout", fail_first), self.assertLogs(apps.log, level="ERROR"):
            backend.renameFolder("folder:1", "First accepted name")
            try:
                self.assertTrue(started.wait(1))
                backend.renameFolder("folder:1", "Latest accepted name")
                self.assertEqual(backend.slots[0]["name"], "Latest accepted name")
            finally:
                release.set()
            backend.flush()
        self.assertEqual(attempts, ["First accepted name", "Latest accepted name"])
        self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Latest accepted name")

    def test_transient_write_failure_recovers_without_a_new_edit_or_flush(self):
        backend, _ = self.backup_backend()
        original = apps._write_layout
        attempts = []

        def fail_first(path, snapshot):
            attempts.append(path)
            if len(attempts) == 1:
                raise OSError("transient failure")
            original(path, snapshot)

        with mock.patch.object(apps, "_write_layout", fail_first), self.assertLogs(apps.log, level="ERROR"):
            backend.renameFolder("folder:1", "Accepted name")
            wait_for(lambda: json.loads(self.config.read_text())["folders"]["1"]["name"] == "Accepted name")
        self.assertEqual(len(attempts), 2)

    def test_permanent_failure_stays_pending_without_spinning_and_flush_reports_it(self):
        backend, _ = self.backup_backend()

        def flush_failure():
            with self.assertRaisesRegex(OSError, "device unavailable"):
                backend.flush()

        with mock.patch.object(apps.os, "replace", side_effect=OSError("device unavailable")) as replace, \
                self.assertLogs(apps.log, level="ERROR") as failure:
            backend.renameFolder("folder:1", "Unsaved name")
            flush_failure()
            calls = replace.call_count
            self.assertGreaterEqual(calls, 1)
            self.assertLessEqual(calls, 3)
            time.sleep(0.2)
            self.assertEqual(replace.call_count, calls)
        self.assertIn(str(self.config), failure.output[0])
        self.assertEqual(backend.slots[0]["name"], "Unsaved name")
        self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Current")
        backend.flush()
        self.assertEqual(json.loads(self.config.read_text())["folders"]["1"]["name"], "Unsaved name")

    def backup_backend(self):
        self.config.write_text(json.dumps({"slots": ["folder:1"], "folders": {
            "1": {"name": "Current", "items": []}}, "next": 2}))
        patch = mock.patch.object(apps.steamlib, "games", return_value=[])
        patch.start()
        self.addCleanup(patch.stop)
        backend = self.enterContext(catalog_fixture())
        wait_for(lambda: not backend.catalogLoading)
        for name, value in (("CONFIG_DIR", str(self.config.parent)),
                            ("FILE", str(self.config.with_name("backup.json")))):
            patch = mock.patch.object(backup, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        coordinator = backup.Backup((backend,))
        self.addCleanup(delete_qobject, coordinator)
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
            with self.assertRaisesRegex(OSError, "layout device unavailable"):
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
                mock.patch.object(apps.steamlib, "games", return_value=[]), \
                catalog_fixture() as backend:
            wait_for(lambda: not backend.catalogLoading)
            with mock.patch.object(apps.os, "replace", side_effect=OSError("first replacement failed")), \
                    self.assertLogs(apps.log, level="ERROR"):
                backend.assign(0, "folder:new")
                with self.assertRaisesRegex(OSError, "first replacement failed"):
                    backend.flush()
            self.assertFalse(nested.exists())
            backend.renameFolder("folder:1", "Recovered new layout")
            backend.flush()
        self.assertEqual(json.loads(nested.read_text())["folders"]["1"]["name"], "Recovered new layout")
