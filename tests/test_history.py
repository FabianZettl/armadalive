import json, os, tempfile, threading, time, unittest
from unittest import mock

from tests.common import app, dispose_qt, touch, wait_for
from PySide6.QtCore import QObject, Signal

from armadalive import history, nowplaying


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
        self.dir = tempfile.mkdtemp(prefix="armadalive-hist-")
        self.path = f"{self.dir}/history.json"
        self.now = FakeNow()
        with mock.patch.object(history, "STEAM", self.dir + "/none"):
            self.h = history.History(self.now, self.path, gamelists=self.dir + "/gamelists")
            self.addCleanup(dispose_qt, self.h)

    def play_for(self, seconds, **kw):
        self.now.play(**kw)
        self.h._open[3] -= seconds     # the session has been running for that long
        self.now.stop()

    def test_a_session_is_counted_saved_and_listed(self):
        self.play_for(120)
        rec = self.h.games["snes/Chrono Trigger"]
        self.assertEqual((rec["total"], rec["plays"]), (120, 1))
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
        again = history.History(FakeNow(), self.path, gamelists=self.dir + "/gamelists")
        self.addCleanup(dispose_qt, again)
        self.assertEqual(again.info("snes/Chrono Trigger")["total"], 45)

    def test_es_de_and_steam_dates_fill_the_lists_on_the_first_day(self):
        touch(f"{self.dir}/gamelists/snes/gamelist.xml", "<gameList><game><path>./Old Game.sfc</path><lastplayed>20261105T192400</lastplayed><playcount>3</playcount></game></gameList>")
        touch(f"{self.dir}/steam/userdata/1/config/localconfig.vdf", '"apps"\n{\n\t"1145360"\n\t{\n\t\t"LastPlayed"\t\t"1793000000"\n\t\t"Playtime"\t\t"90"\n\t}\n\t"999"\n\t{\n\t\t"Playtime"\t\t"5"\n\t}\n}\n')
        with mock.patch.object(history, "STEAM", self.dir + "/steam"):
            h = history.History(FakeNow(), self.dir + "/h2.json", steam_titles=lambda: {"steam:1145360": "Hades"}, gamelists=self.dir + "/gamelists")
            self.addCleanup(dispose_qt, h)
        keys = dict(h.recent())
        self.assertEqual(keys["steam/1145360"]["total"], 5400)
        self.assertEqual(keys["esde:snes/Old Game.sfc"]["plays"], 3)
        self.assertNotIn("steam/999", keys)


    def test_legacy_history_migrates_unique_games_without_attributing_ambiguous_records(self):
        folder = self.dir + "/collection"
        for rom in ("a/Shared.sfc", "b/Shared.sfc", "b/Unique.sfc"):
            touch(f"{folder}/{rom}")
        touch(f"{self.dir}/custom_systems/es_systems.xml", f"""<systemList>
            <system><name>snes</name><path>{folder}</path><extension>.sfc</extension></system>
            </systemList>""")
        path = self.dir + "/legacy.json"
        start = int(time.time())
        touch(path, json.dumps(dict(imported=True, games={
            "snes/Shared": dict(title="Last sibling", system="snes", path=f"{folder}/a/Shared.sfc", total=20, plays=1, favorite=True, last=start),
            "snes/Unique": dict(title="Only game", system="snes", path="", total=34, plays=2, favorite=True, last=start),
        }, sessions=[["snes/Shared", start, 20], ["snes/Unique", start, 34]])))
        with mock.patch.object(nowplaying, "ES", self.dir):
            backend = history.History(FakeNow(), path, gamelists=f"{self.dir}/gamelists")
            self.addCleanup(dispose_qt, backend)
            wait_for(lambda: backend.info("esde:snes/b/Unique.sfc")["favorite"])
        self.assertEqual(backend.info("esde:snes/b/Unique.sfc")["total"], 34)
        self.assertEqual(dict(backend.favorites())["esde:snes/b/Unique.sfc"]["path"], f"{folder}/b/Unique.sfc")
        self.assertFalse(backend.info("esde:snes/a/Shared.sfc")["favorite"])
        self.assertFalse(backend.info("esde:snes/b/Shared.sfc")["favorite"])
        self.assertEqual(dict(backend.favorites())["snes/Shared"]["path"], "")
        with open(path) as saved:
            state = json.load(saved)
        self.assertEqual(state["games"]["snes/Shared"]["total"], 20)
        self.assertNotIn("snes/Unique", state["games"])
        self.assertEqual([session[0] for session in state["sessions"]], ["snes/Shared", "esde:snes/b/Unique.sfc"])

    def test_legacy_history_requires_real_equivalence_between_absolute_rom_locations(self):
        folder = f"{self.dir}/cardA/roms/snes"
        other = f"{self.dir}/cardB/roms/snes/Separate.sfc"
        touch(f"{folder}/Separate.sfc")
        touch(f"{folder}/Same.sfc")
        touch(other)
        alias = f"{self.dir}/linked"
        os.symlink(folder, alias)
        touch(f"{self.dir}/custom_systems/es_systems.xml", f"""<systemList>
            <system><name>snes</name><path>{folder}</path><extension>.sfc</extension></system>
            </systemList>""")
        path = f"{self.dir}/recorded-paths.json"
        start = int(time.time())
        touch(path, json.dumps(dict(imported=True, games={
            "snes/Separate": dict(system="snes", path=other, total=99, plays=3, favorite=True),
            "snes/Same": dict(system="snes", path=f"{alias}/Same.sfc", total=12, plays=1, favorite=True),
        }, sessions=[["snes/Separate", start, 99], ["snes/Same", start, 12]])))
        with mock.patch.object(nowplaying, "ES", self.dir):
            backend = history.History(FakeNow(), path, gamelists=f"{self.dir}/gamelists")
            self.addCleanup(dispose_qt, backend)
            wait_for(lambda: backend._legacy_scan is None)
        self.assertEqual(backend.info("snes/Separate")["total"], 99)
        self.assertFalse(backend.info("esde:snes/Separate.sfc")["favorite"])
        self.assertEqual(backend.info("esde:snes/Same.sfc")["total"], 12)
        with open(path) as saved:
            state = json.load(saved)
        self.assertEqual(state["games"]["snes/Separate"]["path"], other)
        self.assertEqual([row[0] for row in state["sessions"]], ["snes/Separate", "esde:snes/Same.sfc"])

    def test_pending_legacy_migration_does_not_overwrite_replaced_history(self):
        entered, release = threading.Event(), threading.Event()
        old_key, key = "snes/Unique", "esde:snes/Unique.sfc"
        initial = dict(imported=True, games={old_key: dict(path="", favorite=True)}, sessions=[])
        replacement = dict(imported=True, games={"steam/42": dict(total=55)}, sessions=[])
        touch(self.path, json.dumps(initial))

        def delayed(keys, gamelists):
            entered.set()
            release.wait(2)
            return {old_key: (key, f"{self.dir}/Unique.sfc")}

        with mock.patch.object(nowplaying, "resolve_legacy_keys", side_effect=delayed):
            backend = history.History(FakeNow(), self.path)
            self.addCleanup(dispose_qt, backend)
            try:
                wait_for(entered.is_set)
                touch(self.path, json.dumps(replacement))
            finally:
                release.set()
            wait_for(lambda: backend._legacy_scan is None)
        with open(self.path) as saved:
            self.assertEqual(json.load(saved), replacement)

    def test_pending_presentation_does_not_overwrite_replaced_history(self):
        self.now.state = dict(kind="game", key="esde:snes/Unique.sfc", system="snes", playing=True,
                              title="Event name", metadataPending=True)
        self.now.changed.emit()
        replacement = dict(imported=True, games={"steam/42": dict(total=55)}, sessions=[])
        touch(self.path, json.dumps(replacement))
        self.now.state.update(title="Scraped name", metadataPending=False)
        self.now.changed.emit()
        with open(self.path) as saved:
            self.assertEqual(json.load(saved), replacement)


if __name__ == "__main__":
    unittest.main()
