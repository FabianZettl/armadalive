import json, os, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

from tests.common import app, delete_qobject, wait_for
from PySide6.QtCore import QEvent, QObject, QTimer, Signal

from armadalive import backup, history


def write_fixture(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeNow(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.state = dict(kind="idle", key="", playing=False)

    def play(self, key="snes/Chrono Trigger", title="Chrono Trigger", system="snes"):
        self.state = dict(kind="game", key=key, title=title, system=system, path="/roms/x", playing=True, fanart="", logo="")
        self.changed.emit()

    def stop(self):
        self.state = dict(kind="idle", key="", playing=False)
        self.changed.emit()


class Sessions(unittest.TestCase):
    def setUp(self):
        self.dir = self.enterContext(tempfile.TemporaryDirectory(prefix="armadalive-hist-"))
        self.path = f"{self.dir}/history.json"
        self.now = FakeNow()
        write_fixture(self.path, json.dumps(dict(imported=True, games={}, sessions=[])))
        self.h = history.History(self.now, self.path, gamelists=self.dir + "/gamelists")
        self.addCleanup(self.close_history, self.h)

    def close_history(self, backend):
        try:
            backend.flush()
        except OSError:
            pass
        backend.deleteLater()
        app.sendPostedEvents(backend, QEvent.Type.DeferredDelete)

    def play_for(self, seconds, **kw):
        self.now.play(**kw)
        self.h._open[3] -= seconds     # the session has been running for that long
        self.now.stop()

    def test_a_session_is_counted_saved_and_listed(self):
        self.play_for(120)
        rec = self.h.games["snes/Chrono Trigger"]
        self.assertEqual((rec["total"], rec["plays"]), (120, 1))
        self.h.flush()
        with open(self.path) as saved:
            self.assertEqual(json.load(saved)["sessions"][0][2], 120)
        self.assertEqual(self.h.recent()[0][0], "snes/Chrono Trigger")

    def test_favorites_names_and_the_running_total(self):
        self.h.toggleFavorite("steam/42", "", "steam", "")
        self.h.toggleFavorite("snes/Chrono Trigger", "Chrono Trigger", "snes", "/roms/x")
        self.assertEqual([k for k, _ in self.h.favorites()], ["steam/42", "snes/Chrono Trigger"])
        self.assertEqual(self.h.title_of("snes/Chrono Trigger"), "Chrono Trigger")
        self.assertEqual(self.h.title_of("snes/Other Game"), "Other Game")
        self.h.toggleFavorite("steam/42", "", "steam", "")
        self.assertFalse(self.h.info("steam/42")["favorite"])
        self.now.play()
        self.h._open[3] -= 90
        self.assertGreaterEqual(self.h.total_for("snes/Chrono Trigger"), 90)
        self.now.stop()

    def test_a_game_closed_at_once_is_not_a_play(self):
        self.play_for(3)
        self.assertEqual(self.h.games["snes/Chrono Trigger"]["plays"], 0)
        self.h.flush()
        with open(self.path) as saved:
            self.assertEqual(json.load(saved)["sessions"], [])

    def test_the_last_played_game_comes_first_and_totals_add_up(self):
        self.play_for(60, key="snes/A", title="A")
        time.sleep(1.1)
        self.play_for(60, key="snes/B", title="B")
        self.play_for(30, key="snes/A", title="A")
        self.assertEqual([k for k, _ in self.h.recent()], ["snes/A", "snes/B"])
        self.assertEqual(self.h.info("snes/A")["total"], 90)

    def test_week_and_top_use_the_sessions(self):
        self.play_for(600, key="snes/A", title="A")
        self.play_for(300, key="snes/B", title="B")
        week = self.h.week(7)
        self.assertEqual(len(week), 7)
        self.assertEqual(week[-1]["seconds"], 900)
        self.assertEqual([t["title"] for t in self.h.top(7, 5)], ["A", "B"])
        self.assertEqual(self.h.totalSeconds(7), 900)

    def test_it_survives_a_restart_and_a_game_that_is_running_is_written_as_it_goes(self):
        self.now.play()
        self.h._open[3] -= 45
        self.assertEqual(self.h.total_for("snes/Chrono Trigger"), 45)
        self.h._tick()
        self.h.flush()
        again = history.History(FakeNow(), self.path, gamelists=self.dir + "/gamelists")
        self.addCleanup(self.close_history, again)
        self.assertEqual(again.info("snes/Chrono Trigger")["total"], 45)

    def test_startup_loads_previous_history_when_primary_is_malformed(self):
        old = dict(imported=True, games={"steam/42": dict(total=120, plays=1)}, sessions=[])
        write_fixture(self.path + ".bak", json.dumps(old))
        write_fixture(self.path, '{"games": [], "sessions": null}')
        with mock.patch.object(history, "_read_steam", return_value={}):
            again = history.History(FakeNow(), self.path, gamelists=self.dir)
        try:
            self.assertEqual(again.info("steam/42")["total"], 120)
        finally:
            again.deleteLater()
            app.sendPostedEvents(again, QEvent.Type.DeferredDelete)

    def test_corrupt_primary_loads_last_good_backup(self):
        self.play_for(120)
        self.h.flush()
        self.h.toggleFavorite("steam/42", "Favorites", "steam", "")
        self.h.flush()
        write_fixture(self.path, '{"games": [], "sessions": null}')
        again = history.History(FakeNow(), self.path, gamelists=self.dir + "/gamelists")
        self.addCleanup(self.close_history, again)
        self.assertEqual(again.info("snes/Chrono Trigger")["total"], 120)

    def test_export_uses_recovered_history_with_no_new_edits(self):
        saved = dict(imported=True, games={"steam/42": dict(total=120, plays=1)}, sessions=[])
        write_fixture(self.path + ".bak", json.dumps(saved))
        write_fixture(self.path, "incomplete history")
        recovered = history.History(FakeNow(), self.path)
        self.addCleanup(self.close_history, recovered)
        archive = self.dir + "/backup.json"
        with mock.patch.object(backup, "CONFIG_DIR", self.dir), mock.patch.object(backup, "FILE", archive):
            coordinator = backup.Backup((recovered,))
            coordinator.save()
            wait_for(lambda: not coordinator.state["busy"])
        self.assertEqual(coordinator.state["message"], "saved")
        self.assertEqual(json.loads(Path(archive).read_text())["files"]["history.json"], saved)

    def test_interrupted_replacement_keeps_existing_history(self):
        self.play_for(120)
        self.h.flush()
        with mock.patch("os.replace", side_effect=OSError("interrupted save")):
            with self.assertLogs(history.LOG, "WARNING"):
                self.h.toggleFavorite("steam/42", "Favorites", "steam", "")
                with self.assertRaisesRegex(OSError, "interrupted save"):
                    self.h.flush()
        with open(self.path) as saved:
            self.assertNotIn("steam/42", json.load(saved)["games"])
        self.assertEqual(sorted(os.listdir(self.dir)), ["history.json", "history.json.bak"])

    def test_read_only_history_preserves_the_file_and_can_retry(self):
        path = Path(self.path)
        before = path.read_bytes()
        path.chmod(0o444)
        try:
            if os.access(path, os.W_OK):
                self.skipTest("The test process can write read-only files")
            self.h.toggleFavorite("steam/42", "Game", "steam", "")
            with self.assertLogs(history.LOG, "WARNING"), self.assertRaises(OSError):
                self.h.flush()
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(Path(self.path + ".bak").exists())
        finally:
            path.chmod(0o644)
        self.h.flush()
        self.assertTrue(json.loads(path.read_text())["games"]["steam/42"]["favorite"])

    def test_invalid_snapshot_does_not_replace_last_good_history(self):
        path = Path(self.dir) / "overflow.json"
        saved = dict(imported=True, games={"steam/42": dict(plays=2**63 - 1, favorite=True)}, sessions=[])
        before = json.dumps(saved)
        write_fixture(path, before)
        write_fixture(str(path) + ".bak", before)
        now = FakeNow()
        h = history.History(now, str(path))
        self.addCleanup(delete_qobject, h)
        now.play(key="steam/42", title="Game", system="steam")
        with self.assertLogs(history.LOG, "WARNING"), self.assertRaisesRegex(OSError, "invalid play history snapshot"):
            h.flush()
        self.assertEqual(path.read_text(), before)
        self.assertEqual(Path(str(path) + ".bak").read_text(), before)

    def test_periodic_retry_persists_latest_state_after_a_failed_write(self):
        with mock.patch.object(history.persistence, "write_json", side_effect=OSError("disk unavailable")):
            with self.assertLogs(history.LOG, "WARNING"):
                self.h.toggleFavorite("steam/42", "Favorites", "steam", "")
                with self.assertRaisesRegex(OSError, "disk unavailable"):
                    self.h.flush()
        self.h._tick()
        self.h.flush()
        with open(self.path) as saved:
            self.assertTrue(json.load(saved)["games"]["steam/42"]["favorite"])

    def test_blocked_save_does_not_block_qt_and_coalesces_latest_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        writes = []
        owner = threading.get_ident()
        write_json = history.persistence.write_json

        def write(path, data, **kwargs):
            if threading.get_ident() == owner:
                raise AssertionError("History write ran on the Qt owner thread")
            if not writes:
                entered.set()
                release.wait(2)
            writes.append({key: game["favorite"] for key, game in data["games"].items()})
            write_json(path, data, **kwargs)

        with mock.patch.object(history.persistence, "write_json", side_effect=write):
            try:
                self.h.toggleFavorite("steam/42", "First", "steam", "")
                self.assertTrue(entered.wait(1))
                fired = []
                QTimer.singleShot(0, lambda: fired.append(True))
                self.h.toggleFavorite("steam/42", "First", "steam", "")
                self.h.toggleFavorite("steam/43", "Latest", "steam", "")
                app.processEvents()
                self.assertTrue(fired)
                self.assertEqual(writes, [])
            finally:
                release.set()
            self.h.flush()
        self.assertEqual(writes, [{"steam/42": True}, {"steam/42": False, "steam/43": True}])
        with open(self.path) as saved:
            self.assertTrue(json.load(saved)["games"]["steam/43"]["favorite"])

    def test_delayed_import_preserves_live_history_and_favorites(self):
        release = threading.Event()
        entered = threading.Event()
        path = self.dir + "/delayed.json"

        def titles():
            entered.set()
            release.wait(2)
            return {"steam:42": "Steam Title"}

        steam_snapshot = {"42": (time.time() - 100, 300)}
        with mock.patch.object(history, "_read_steam", side_effect=lambda: dict(steam_snapshot)):
            try:
                h = history.History(self.now, path, steam_titles=titles, gamelists=self.dir + "/gamelists")
                self.addCleanup(self.close_history, h)
                self.assertTrue(entered.wait(1))
                self.assertFalse(release.is_set())
                self.now.play(key="steam/42", title="Current title", system="steam")
                h._open[3] -= 45
                self.now.stop()
                steam_snapshot["42"] = (time.time(), 345)
                h.toggleFavorite("steam/42", "Current title", "steam", "")
                h.flush()
                with open(path) as saved:
                    self.assertFalse(json.load(saved)["imported"])
            finally:
                release.set()
            self.wait_for_import(h)
        self.assertEqual(h.games["steam/42"]["title"], "Current title")
        self.assertEqual(h.info("steam/42")["total"], 345)
        with open(path) as saved:
            self.assertEqual(json.load(saved)["games"]["steam/42"]["total"], 345)
        self.assertTrue(h.info("steam/42")["favorite"])

    def test_saved_history_resolves_late_steam_titles_and_notifies_views(self):
        entered, release = threading.Event(), threading.Event()

        def titles():
            entered.set()
            release.wait(2)
            return {"steam:42": "Late title"}

        write_fixture(self.path, json.dumps(dict(imported=True,
                      games={"steam/42": dict(title="steam/42", favorite=True)}, sessions=[])))
        h = history.History(FakeNow(), self.path, steam_titles=titles)
        self.addCleanup(self.close_history, h)
        observed = []
        h.changed.connect(lambda: observed.append(h.title_of("steam/42")))
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(h.title_of("steam/42"), "")
            self.assertTrue(h.info("steam/42")["favorite"])
        finally:
            release.set()
        wait_for(lambda: observed == ["Late title"])

    def test_restart_during_import_reuses_baseline_without_counting_live_time_twice(self):
        entered, release = threading.Event(), threading.Event()
        path = self.dir + "/interrupted.json"

        def titles():
            entered.set()
            release.wait(5)
            return {"steam:42": "Game"}

        with mock.patch.object(history, "_read_steam", return_value={"42": (100, 300)}):
            h = history.History(self.now, path, steam_titles=titles, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            try:
                self.assertTrue(entered.wait(1))
                self.now.play(key="steam/42", title="Game", system="steam")
                h._open[3] -= 60
                self.now.stop()
                h.flush()
                with open(path) as source:
                    snapshot = source.read()
                h._import_timer.stop()  # Simulate a process disappearing before consuming its import.
                restarted_path = self.dir + "/restarted.json"
                write_fixture(restarted_path, snapshot)
                with mock.patch.object(history, "_read_steam", return_value={"42": (200, 360)}):
                    again = history.History(FakeNow(), restarted_path, steam_titles=lambda: {"steam:42": "Game"}, gamelists=self.dir)
                    self.addCleanup(self.close_history, again)
                    self.wait_for_import(again)
                self.assertEqual(again.info("steam/42")["total"], 360)
                self.assertEqual(again.totalSeconds(), 60)
            finally:
                release.set()
                h._import_job.result()

    def test_blocked_baseline_defers_saves_without_blocking_events(self):
        entered, release = threading.Event(), threading.Event()
        path = self.dir + "/blocked-source.json"

        def steam():
            entered.set()
            release.wait(5)
            return {"42": (100, 300)}

        with mock.patch.object(history, "_read_steam", side_effect=steam):
            h = history.History(self.now, path, steam_titles=lambda: {"steam:42": "Game"}, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            try:
                self.assertTrue(entered.wait(1))
                h.toggleFavorite("steam/42", "Game", "steam", "")
                fired = []
                QTimer.singleShot(0, lambda: fired.append(True))
                app.processEvents()
                self.assertTrue(fired)
                self.assertTrue(h.writesPending())
                self.assertFalse(os.path.exists(path))
            finally:
                release.set()
            self.wait_for_import(h)
        self.assertEqual(h.info("steam/42")["total"], 300)
        self.assertTrue(h.info("steam/42")["favorite"])

    def test_emulator_session_keeps_its_local_time_during_delayed_steam_read(self):
        entered, release = threading.Event(), threading.Event()
        path = self.dir + "/emulator-session.json"

        def steam():
            entered.set()
            release.wait(5)
            return {}

        now = FakeNow()
        with mock.patch.object(history, "_read_steam", side_effect=steam):
            h = history.History(now, path, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            try:
                self.assertTrue(entered.wait(1))
                now.play()
                h._open[3] -= 60
                now.stop()
                self.assertEqual(h.totalSeconds(), 60)
                self.assertFalse(os.path.exists(path))
            finally:
                release.set()
            self.wait_for_import(h)
        self.assertEqual(json.loads(Path(path).read_text())["sessions"][0][2], 60)

    def test_game_finished_before_delayed_source_is_not_added_to_newer_steam_total(self):
        entered, release = threading.Event(), threading.Event()
        steam_dir = self.dir + "/steam"
        source = steam_dir + "/userdata/1/config/localconfig.vdf"
        write_fixture(source, '"42" { "LastPlayed" "100" "Playtime" "5" }')

        def delayed_open(path, *args, **kwargs):
            if path == source:
                entered.set()
                release.wait(5)
            return open(path, *args, **kwargs)

        now = FakeNow()
        with mock.patch.object(history, "STEAM", steam_dir), \
                mock.patch.object(history, "open", side_effect=delayed_open, create=True):
            h = history.History(now, self.dir + "/slow-source.json", steam_titles=lambda: {"steam:42": "Game"}, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            try:
                self.assertTrue(entered.wait(1))
                clock = [100.0]
                with mock.patch.object(history.time, "monotonic", side_effect=lambda: clock[0]):
                    now.play(key="steam/42", title="Game", system="steam")
                    clock[0] += 60
                    now.stop()
                write_fixture(source, '"42" { "LastPlayed" "200" "Playtime" "6" }')
            finally:
                release.set()
            self.wait_for_import(h)
        self.assertEqual(h.info("steam/42")["total"], 360)
        self.assertEqual(h.totalSeconds(), 0)

    def test_latest_running_game_starts_when_source_finishes_before_titles(self):
        source_entered, source_release = threading.Event(), threading.Event()
        titles_entered, titles_release = threading.Event(), threading.Event()

        def steam():
            source_entered.set()
            source_release.wait(5)
            return {"42": (100, 300)}

        def titles():
            titles_entered.set()
            titles_release.wait(5)
            return {"steam:42": "First", "steam:43": "Latest"}

        now = FakeNow()
        with mock.patch.object(history, "_read_steam", side_effect=steam):
            h = history.History(now, self.dir + "/source-then-titles.json", steam_titles=titles, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            try:
                self.assertTrue(source_entered.wait(1))
                now.play(key="steam/42", title="First", system="steam")
                now.play(key="steam/43", title="Latest", system="steam")
                self.assertIsNone(h._open)
                source_release.set()
                self.assertTrue(titles_entered.wait(1))
                wait_for(lambda: h._open is not None)
                self.assertEqual(h._open[0], "steam/43")
                h._open[3] -= 30
                now.stop()
                h.flush()
                self.assertEqual(h.info("steam/43")["total"], 30)
                self.assertFalse(h._imported)
            finally:
                source_release.set()
                titles_release.set()
            self.wait_for_import(h)
        self.assertEqual(h.info("steam/42")["total"], 300)
        self.assertEqual(h.info("steam/43")["total"], 30)

    def test_legacy_unfinished_import_keeps_larger_known_total(self):
        for cumulative, expected in ((360, 360), (30, 60)):
            with self.subTest(cumulative=cumulative):
                path = self.dir + f"/legacy-{cumulative}.json"
                write_fixture(path, json.dumps(dict(imported=False, games={"steam/42": dict(total=60, plays=1, favorite=True)}, sessions=[])))
                with mock.patch.object(history, "_read_steam", return_value={"42": (100, cumulative)}):
                    h = history.History(FakeNow(), path, steam_titles=lambda: {"steam:42": "Game"}, gamelists=self.dir)
                    self.addCleanup(self.close_history, h)
                    self.wait_for_import(h)
                self.assertEqual(h.info("steam/42")["total"], expected)
                self.assertTrue(h.info("steam/42")["favorite"])

    def test_missing_steam_source_does_not_prevent_new_history_saves(self):
        path = self.dir + "/no-steam.json"
        with mock.patch.object(history, "STEAM", self.dir + "/no-steam"):
            h = history.History(FakeNow(), path, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            self.wait_for_import(h)
        h.toggleFavorite("steam/42", "Game", "steam", "")
        h.flush()
        with open(path) as saved:
            self.assertTrue(json.load(saved)["games"]["steam/42"]["favorite"])

    def test_bad_steam_times_do_not_block_import_or_local_saves(self):
        steam_dir = self.dir + "/steam"
        source = steam_dir + "/userdata/1/config/localconfig.vdf"
        write_fixture(source, f'''"apps" {{
            "42" {{ "LastPlayed" "100" "Playtime" "{'9' * 350}" }}
            "43" {{ "LastPlayed" "100" "Playtime" "5" }}
            "44" {{ "LastPlayed" "{'9' * 4500}" "Playtime" "5" }}
            "45" {{ "LastPlayed" "100" "Playtime" "-1" }}
            "46" {{ "LastPlayed" "100" }}
        }}''')
        write_fixture(steam_dir + "/userdata/2/config/localconfig.vdf", '''"apps" {
            "47" { "LastPlayed" "100" "Playtime" "2" }
        }''')
        path = self.dir + "/bad-steam-records.json"

        def titles():
            return {f"steam:{appid}": f"Game {appid}" for appid in range(42, 48)}

        now = FakeNow()
        with mock.patch.object(history, "STEAM", steam_dir):
            h = history.History(now, path, steam_titles=titles, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            self.wait_for_import(h)
            self.assertEqual({key: game["total"] for key, game in h.games.items()},
                             {"steam/43": 300, "steam/46": 0, "steam/47": 120})
            now.play()
            h._open[3] -= 30
            now.stop()
            now.play(key="steam/42", title="Game 42", system="steam")
            h._open[3] -= 60
            now.stop()
            h.toggleFavorite("steam/42", "Game 42", "steam", "")
            h.flush()

            write_fixture(source, '''"apps" {
                "42" { "LastPlayed" "200" "Playtime" "6" }
                "43" { "LastPlayed" "100" "Playtime" "5" }
            }''')
            restarted_now = FakeNow()
            restarted = history.History(restarted_now, path, steam_titles=titles, gamelists=self.dir)
            self.addCleanup(self.close_history, restarted)
            wait_for(lambda: not restarted._import_timer.isActive())
            self.assertEqual(restarted.info("steam/42")["total"], 60)
            self.assertEqual(restarted.info("steam/43")["total"], 300)
            self.assertEqual(restarted.info("snes/Chrono Trigger")["total"], 30)
            self.assertTrue(restarted.info("steam/42")["favorite"])
            restarted_now.play(key="steam/42", title="Game 42", system="steam")
            restarted._open[3] -= 15
            restarted_now.stop()
            restarted.flush()
        record = json.loads(Path(path).read_text())["games"]["steam/42"]
        self.assertEqual((record["total"], record["plays"], record["favorite"]), (75, 2, True))

    def test_malformed_baseline_loads_valid_backup(self):
        for i, malformed in enumerate(({"42": "bad"}, {"42": [100, -10]}, {"42": [100, float("nan")]}, None)):
            with self.subTest(baseline=malformed):
                path = self.dir + f"/bad-baseline-{i}.json"
                saved = dict(imported=False, games={"steam/42": dict(total=60, plays=1)}, sessions=[],
                             steam_baseline={"42": [100, 300]})
                write_fixture(path + ".bak", json.dumps(saved))
                saved["steam_baseline"] = malformed
                write_fixture(path, json.dumps(saved))
                with mock.patch.object(history, "_read_steam", return_value={"42": (200, 999)}):
                    h = history.History(FakeNow(), path, steam_titles=lambda: {"steam:42": "Game"}, gamelists=self.dir)
                    self.addCleanup(self.close_history, h)
                    self.wait_for_import(h)
                self.assertEqual(h.info("steam/42")["total"], 360)

    def test_backup_exports_only_accepted_history_while_initial_baseline_is_pending(self):
        started, release_baseline, release_titles = (threading.Event() for _ in range(3))
        backup_dir = self.enterContext(tempfile.TemporaryDirectory(dir=self.dir))
        path, archive = backup_dir + "/history.json", self.dir + "/backup.json"

        def load_baseline():
            started.set()
            release_baseline.wait(5)
            return {}

        def load_titles():
            release_titles.wait(5)
            return {}

        with mock.patch.object(history, "_read_steam", side_effect=load_baseline), \
                mock.patch.object(backup, "CONFIG_DIR", backup_dir), \
                mock.patch.object(backup, "FILE", archive):
            h = history.History(FakeNow(), path, steam_titles=load_titles, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            try:
                self.assertTrue(started.wait(1))
                h.toggleFavorite("steam/42", "Accepted", "steam", "")
                coordinator = backup.Backup((h,))
                coordinator.save()
                h.toggleFavorite("steam/43", "Deferred", "steam", "")
                release_baseline.set()
                wait_for(lambda: coordinator.state["message"] == "saved")
                h.flush()
                with open(archive) as stream:
                    exported = json.load(stream)["files"]["history.json"]["games"]
                self.assertEqual(set(exported), {"steam/42"})
                with open(path) as stream:
                    self.assertEqual(set(json.load(stream)["games"]), {"steam/42", "steam/43"})
            finally:
                release_baseline.set()
                release_titles.set()

    def test_unreadable_steam_account_keeps_other_imports_and_local_steam_saves(self):
        steam_dir = self.dir + "/steam"
        unreadable = steam_dir + "/userdata/1/config/localconfig.vdf"
        readable = steam_dir + "/userdata/2/config/localconfig.vdf"
        write_fixture(unreadable, '"43" { "LastPlayed" "100" "Playtime" "7" }')
        write_fixture(readable, '"42" { "LastPlayed" "100" "Playtime" "5" }')
        path = self.dir + "/partially-readable-steam.json"

        def open_account(path, *args, **kwargs):
            if path == unreadable:
                raise PermissionError("Steam account is unreadable")
            return open(path, *args, **kwargs)

        now = FakeNow()
        with mock.patch.object(history, "STEAM", steam_dir), \
                mock.patch.object(history, "open", side_effect=open_account, create=True), \
                self.assertLogs(history.LOG, "WARNING") as warnings:
            h = history.History(now, path, steam_titles=lambda: {"steam:42": "Game"}, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            self.wait_for_import(h)
        self.assertIn(unreadable, "\n".join(warnings.output))
        now.play(key="steam/42", title="Game", system="steam")
        h._open[3] -= 60
        now.stop()
        h.flush()

        restarted = history.History(FakeNow(), path, gamelists=self.dir)
        self.addCleanup(self.close_history, restarted)
        self.assertEqual(restarted.info("steam/42")["total"], 360)
        self.assertEqual(restarted.totalSeconds(), 60)

    def test_failed_steam_scan_preserves_local_saves_and_retries_on_restart(self):
        source = self.dir + "/steam/userdata/1/config/localconfig.vdf"
        write_fixture(source, '"42" { "LastPlayed" "100" "Playtime" "5" }')
        backup_dir = self.enterContext(tempfile.TemporaryDirectory(dir=self.dir))
        path, archive = backup_dir + "/history.json", self.dir + "/backup.json"
        write_fixture(path, json.dumps(dict(imported=False, games={"steam/42": dict(total=1.5)}, sessions=[])))
        started, release = threading.Event(), threading.Event()

        def gated_read():
            started.set()
            release.wait(5)
            raise RuntimeError("Steam history scan failed unexpectedly")

        now = FakeNow()
        with mock.patch.object(history, "STEAM", self.dir + "/steam"), \
                mock.patch.object(history, "_read_steam", side_effect=gated_read), \
                mock.patch.object(backup, "CONFIG_DIR", backup_dir), \
                mock.patch.object(backup, "FILE", archive):
            h = history.History(now, path, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            coordinator = backup.Backup((h,))
            try:
                self.assertTrue(started.wait(1))
                now.play()
                h._open[3] -= 30
                now.stop()
                h.toggleFavorite("steam/43", "Accepted", "steam", "")
                coordinator.save()
                h.toggleFavorite("steam/44", "Deferred", "steam", "")
                with self.assertLogs(history.LOG, "WARNING") as warnings:
                    release.set()
                    wait_for(lambda: not coordinator.state["busy"] and not h._import_timer.isActive())
                    self.assertEqual(coordinator.state["message"], "saved")
                self.assertIn("Steam history scan failed unexpectedly", "\n".join(warnings.output))
                now.play(key="steam/42", title="Game", system="steam")
                now.stop()
                h.flush()
                exported = json.loads(Path(archive).read_text())["files"]["history.json"]
                saved = json.loads(Path(path).read_text())
                self.assertFalse(saved["imported"])
                self.assertNotIn("steam_baseline", saved)
                self.assertEqual(saved["games"]["steam/42"]["total"], 1.5)
                self.assertEqual(saved["sessions"][0][2], 30)
                self.assertTrue(saved["games"]["steam/44"]["favorite"])
                self.assertTrue(exported["games"]["steam/43"]["favorite"])
                self.assertNotIn("steam/44", exported["games"])
            finally:
                release.set()
                h._import_timer.stop()
                coordinator._drain.stop()
        write_fixture(source, '"42" { "LastPlayed" "200" "Playtime" "6" }')
        with mock.patch.object(history, "STEAM", self.dir + "/steam"):
            restarted = history.History(FakeNow(), path, steam_titles=lambda: {"steam:42": "Game"}, gamelists=self.dir)
            self.addCleanup(self.close_history, restarted)
            self.wait_for_import(restarted)
        self.assertEqual(restarted.info("steam/42")["total"], 360)
        self.assertEqual(restarted.info("snes/Chrono Trigger")["total"], 30)
        self.assertTrue(restarted.info("steam/44")["favorite"])

    def test_flush_drains_accepted_history_when_export_pauses_a_pending_baseline(self):
        started, release_baseline = threading.Event(), threading.Event()
        path = self.dir + "/shutdown.json"

        def load_baseline():
            started.set()
            release_baseline.wait(5)
            return {}

        with mock.patch.object(history, "_read_steam", side_effect=load_baseline):
            h = history.History(FakeNow(), path, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            try:
                self.assertTrue(started.wait(1))
                h.toggleFavorite("steam/42", "Accepted", "steam", "")
                h.pauseWrites()
                h.toggleFavorite("steam/43", "Deferred", "steam", "")
                release_baseline.set()
                h.flush()
                self.assertTrue(os.path.exists(path), "Accepted history did not reach disk")
                with open(path) as stream:
                    self.assertEqual(set(json.load(stream)["games"]), {"steam/42"})
            finally:
                release_baseline.set()

    def test_backup_export_drains_latest_history_without_blocking_events(self):
        entered, release = threading.Event(), threading.Event()
        write_json = history.persistence.write_json
        archive = self.dir + "/backup.json"

        def write(*args, **kwargs):
            entered.set()
            release.wait(5)
            write_json(*args, **kwargs)

        with mock.patch.object(history.persistence, "write_json", side_effect=write), \
                mock.patch.object(backup, "CONFIG_DIR", self.dir), mock.patch.object(backup, "FILE", archive):
            try:
                self.h.toggleFavorite("steam/42", "First", "steam", "")
                self.assertTrue(entered.wait(1))
                self.h.toggleFavorite("steam/43", "Latest", "steam", "")
                b = backup.Backup((self.h,))
                b.save()
                fired = []
                QTimer.singleShot(0, lambda: fired.append(True))
                app.processEvents()
                self.assertTrue(fired)
                self.assertTrue(b.state["busy"])
                self.assertFalse(os.path.exists(archive))
                self.h.toggleFavorite("steam/44", "After export started", "steam", "")
            finally:
                release.set()
            wait_for(lambda: b.state["message"] == "saved")
            self.h.flush()
        with open(archive) as saved:
            self.assertEqual(set(json.load(saved)["files"]["history.json"]["games"]), {"steam/42", "steam/43"})
        with open(self.path) as saved:
            self.assertIn("steam/44", json.load(saved)["games"])

    def test_backup_restore_keeps_history_paused_until_restart(self):
        entered, release = threading.Event(), threading.Event()
        write_json = history.persistence.write_json
        archive = self.dir + "/restore.json"
        restored = dict(imported=True, games={"steam/99": dict(total=900, plays=2)}, sessions=[])
        write_fixture(archive, json.dumps(dict(files={"history.json": restored})))

        def write(*args, **kwargs):
            entered.set()
            release.wait(5)
            write_json(*args, **kwargs)

        with mock.patch.object(history.persistence, "write_json", side_effect=write), \
                mock.patch.object(backup, "CONFIG_DIR", self.dir), mock.patch.object(backup, "FILE", archive), \
                mock.patch.object(backup.QTimer, "singleShot"):
            try:
                self.h.toggleFavorite("steam/42", "Old", "steam", "")
                self.assertTrue(entered.wait(1))
                b = backup.Backup((self.h,))
                b.restore()
                self.assertTrue(b.state["busy"])
            finally:
                release.set()
            wait_for(lambda: b.state["message"] == "restored")
            self.h.toggleFavorite("steam/44", "While restarting", "steam", "")
            self.h.flush()
        with open(self.path) as saved:
            self.assertEqual(json.load(saved), restored)
        # A restart constructs a new History from the restored configuration.
        again = history.History(FakeNow(), self.path)
        self.addCleanup(self.close_history, again)
        self.assertEqual(again.info("steam/99")["total"], 900)
        self.assertNotIn("steam/44", again.games)

    def test_restore_drains_pending_baseline_but_recovers_imported_history_after_restart(self):
        baseline_started, release_baseline, release_titles = (threading.Event() for _ in range(3))
        directory = self.enterContext(tempfile.TemporaryDirectory(dir=self.dir))
        path, archive = Path(directory, "history.json"), Path(self.dir, "restore.json")
        restored = dict(imported=False, games={"steam/99": {"total": 30}}, sessions=[],
                        steam_baseline={"99": [200, 600]})
        write_fixture(archive, json.dumps({"files": {"history.json": restored}}))

        def read_steam():
            baseline_started.set()
            release_baseline.wait(5)
            return {"42": (100, 300)}

        def load_titles():
            release_titles.wait(5)
            return {"steam:42": "Old game"}

        with mock.patch.object(backup, "CONFIG_DIR", directory), mock.patch.object(backup, "FILE", archive), \
                mock.patch.object(history, "_read_steam", side_effect=read_steam), \
                mock.patch.object(backup.QTimer, "singleShot") as later:
            h = history.History(FakeNow(), path, steam_titles=load_titles, gamelists=self.dir)
            self.addCleanup(self.close_history, h)
            coordinator = backup.Backup((h,))
            self.addCleanup(coordinator._drain.stop)
            try:
                self.assertTrue(baseline_started.wait(1))
                h.toggleFavorite("steam/42", "Old favorite", "steam", "")
                coordinator.restore()
                self.assertTrue(coordinator.state["busy"])
                self.assertFalse(path.exists())
                release_baseline.set()
                wait_for(lambda: coordinator.state["message"] == "restored")
                release_titles.set()
                wait_for(lambda: h._imported)
                coordinator.flushWriters()
                self.assertEqual(json.loads(path.read_bytes()), restored)
                with mock.patch.dict(os.environ), mock.patch.object(
                        backup.os, "execv", side_effect=lambda *_: backup.recover_restore(startup=True)):
                    later.call_args.args[1]()
            finally:
                release_baseline.set()
                release_titles.set()

        path.write_text("{damaged primary")
        with mock.patch.object(history, "_read_steam", side_effect=AssertionError("baseline must be reused")) as steam:
            again = history.History(FakeNow(), path, steam_titles=lambda: {"steam:99": "New game"}, gamelists=self.dir)
            self.addCleanup(self.close_history, again)
            self.wait_for_import(again)
        steam.assert_not_called()
        self.assertEqual(again.info("steam/99")["total"], 630)
        self.assertNotIn("steam/42", again.games)

    def test_backup_write_failure_is_reported_and_history_can_retry(self):
        archive = self.dir + "/failed-backup.json"
        with mock.patch.object(history.persistence, "write_json", side_effect=OSError("disk unavailable")), \
                mock.patch.object(backup, "CONFIG_DIR", self.dir), mock.patch.object(backup, "FILE", archive):
            with self.assertLogs(history.LOG, "WARNING"):
                self.h.toggleFavorite("steam/42", "Unsaved", "steam", "")
                b = backup.Backup((self.h,))
                b.save()
                wait_for(lambda: not b.state["busy"])
            self.assertNotEqual(b.state["message"], "saved")
            self.assertFalse(os.path.exists(archive))
        self.h._tick()
        self.h.flush()
        with open(self.path) as saved:
            self.assertTrue(json.load(saved)["games"]["steam/42"]["favorite"])

    def wait_for_import(self, h):
        wait_for(lambda: h._imported)
        h.flush()

    def test_es_de_and_steam_dates_fill_the_lists_on_the_first_day(self):
        write_fixture(f"{self.dir}/gamelists/snes/gamelist.xml", "<gameList><game><path>./Old Game.sfc</path><lastplayed>20261105T192400</lastplayed><playcount>3</playcount></game></gameList>")
        write_fixture(f"{self.dir}/steam/userdata/1/config/localconfig.vdf", '"apps"\n{\n\t"1145360"\n\t{\n\t\t"LastPlayed"\t\t"1793000000"\n\t\t"Playtime"\t\t"90"\n\t}\n\t"999"\n\t{\n\t\t"Playtime"\t\t"5"\n\t}\n}\n')
        with mock.patch.object(history, "STEAM", self.dir + "/steam"):
            h = history.History(FakeNow(), self.dir + "/h2.json", steam_titles=lambda: {"steam:1145360": "Hades"}, gamelists=self.dir + "/gamelists")
            self.addCleanup(self.close_history, h)
            self.wait_for_import(h)
        keys = dict(h.recent())
        self.assertEqual(keys["steam/1145360"]["total"], 5400)
        self.assertEqual(keys["snes/Old Game"]["plays"], 3)
        self.assertNotIn("steam/999", keys)

    def test_bad_es_de_rows_do_not_poison_saved_history(self):
        path = self.dir + "/bad-esde-records.json"
        write_fixture(f"{self.dir}/gamelists/snes/gamelist.xml", f'''<gameList>
            <game><path>./Oversized.sfc</path><lastplayed>20261105T192400</lastplayed><playcount>{'9' * 350}</playcount></game>
            <game><path>./Invalid count.sfc</path><lastplayed>20261105T192400</lastplayed><playcount>invalid</playcount></game>
            <game><path>./Invalid date.sfc</path><lastplayed>invalid</lastplayed><playcount>1</playcount></game>
            <game><path>./Good.sfc</path><lastplayed>20261105T192400</lastplayed><playcount>3</playcount></game>
        </gameList>''')
        with mock.patch.object(history, "STEAM", self.dir + "/no-steam"):
            h = history.History(FakeNow(), path, gamelists=self.dir + "/gamelists")
            self.addCleanup(self.close_history, h)
            self.wait_for_import(h)
        h.toggleFavorite("snes/Good", "Good", "snes", "")
        h.flush()
        restarted = history.History(FakeNow(), path, gamelists=self.dir + "/gamelists")
        self.addCleanup(self.close_history, restarted)
        self.assertEqual(set(restarted.games), {"snes/Good"})
        self.assertEqual(restarted.info("snes/Good")["plays"], 3)
        self.assertTrue(restarted.info("snes/Good")["favorite"])


if __name__ == "__main__":
    unittest.main()
