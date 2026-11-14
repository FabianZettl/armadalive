import json, os, tempfile, threading, time, unittest
from unittest import mock

from tests.common import app, touch  # noqa: F401
from PySide6.QtCore import QEvent, QObject, QTimer, Signal

from armadalive import history


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
        with mock.patch.object(history, "STEAM", self.dir + "/none"):
            self.h = history.History(self.now, self.path, gamelists=self.dir + "/gamelists")
            self.wait_for_import(self.h)
        self.addCleanup(self.close_history, self.h)

    def close_history(self, backend):
        backend._shutdown()
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
        self.assertEqual(json.load(open(self.path))["sessions"][0][2], 120)
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
        self.assertEqual(json.load(open(self.path))["sessions"], [])

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
        self.h._tick()
        self.h.flush()
        again = history.History(FakeNow(), self.path, gamelists=self.dir + "/gamelists")
        self.addCleanup(self.close_history, again)
        self.assertEqual(again.info("snes/Chrono Trigger")["total"], 45)

    def test_corrupt_primary_loads_last_good_backup(self):
        self.play_for(120)
        self.h.flush()
        self.h.toggleFavorite("steam/42", "Favorites", "steam", "")
        self.h.flush()
        touch(self.path, '{"games": [], "sessions": null}')
        again = history.History(FakeNow(), self.path, gamelists=self.dir + "/gamelists")
        self.addCleanup(self.close_history, again)
        self.assertEqual(again.info("snes/Chrono Trigger")["total"], 120)

    def test_interrupted_replacement_keeps_existing_history(self):
        self.play_for(120)
        self.h.flush()
        with mock.patch("os.replace", side_effect=OSError("interrupted save")):
            with self.assertLogs(history.LOG, "WARNING"):
                self.h.toggleFavorite("steam/42", "Favorites", "steam", "")
                self.h.flush()
        with open(self.path) as saved:
            self.assertNotIn("steam/42", json.load(saved)["games"])
        self.assertEqual(sorted(os.listdir(self.dir)), ["history.json", "history.json.bak"])

    def test_periodic_retry_persists_latest_state_after_a_failed_write(self):
        with mock.patch.object(history.persistence, "write_json", side_effect=OSError("disk unavailable")):
            with self.assertLogs(history.LOG, "WARNING"):
                self.h.toggleFavorite("steam/42", "Favorites", "steam", "")
                self.h._drain_saves()
        self.assertTrue(self.h._dirty)
        self.h._tick()
        self.wait_for(lambda: not self.h._dirty)
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

    def wait_for(self, predicate):
        until = time.monotonic() + 2
        while not predicate() and time.monotonic() < until:
            app.processEvents()
            time.sleep(0.001)
        self.assertTrue(predicate())

    def wait_for_import(self, h):
        self.wait_for(lambda: h._imported)
        h.flush()

    def test_es_de_and_steam_dates_fill_the_lists_on_the_first_day(self):
        touch(f"{self.dir}/gamelists/snes/gamelist.xml", "<gameList><game><path>./Old Game.sfc</path><lastplayed>20261105T192400</lastplayed><playcount>3</playcount></game></gameList>")
        touch(f"{self.dir}/steam/userdata/1/config/localconfig.vdf", '"apps"\n{\n\t"1145360"\n\t{\n\t\t"LastPlayed"\t\t"1793000000"\n\t\t"Playtime"\t\t"90"\n\t}\n\t"999"\n\t{\n\t\t"Playtime"\t\t"5"\n\t}\n}\n')
        with mock.patch.object(history, "STEAM", self.dir + "/steam"):
            h = history.History(FakeNow(), self.dir + "/h2.json", steam_titles=lambda: {"steam:1145360": "Hades"}, gamelists=self.dir + "/gamelists")
            self.addCleanup(self.close_history, h)
            self.wait_for_import(h)
        keys = dict(h.recent())
        self.assertEqual(keys["steam/1145360"]["total"], 5400)
        self.assertEqual(keys["snes/Old Game"]["plays"], 3)
        self.assertNotIn("steam/999", keys)


if __name__ == "__main__":
    unittest.main()
