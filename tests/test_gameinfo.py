import os, tempfile, threading, time, unittest
from unittest import mock

from tests.common import runtime_object, touch, wait_for
from PySide6.QtCore import QTimer
from armadalive import gameinfo, nowplaying


class Read(unittest.TestCase):
    def test_a_gamelist_entry_and_the_pictures_are_read(self):
        es = tempfile.mkdtemp(prefix="armadalive-gi-")
        touch(f"{es}/gamelists/snes/gamelist.xml", "<gameList><game><path>./Chrono Trigger (USA).sfc</path><name>Chrono Trigger</name><desc>A boy meets a girl.</desc>"
              "<genre>RPG</genre><developer>Square</developer><releasedate>19950311T000000</releasedate><rating>0.8</rating><players>1</players></game></gameList>")
        touch(f"{es}/downloaded_media/snes/covers/Chrono Trigger (USA).png", "x")
        touch(f"{es}/downloaded_media/snes/screenshots/Chrono Trigger (USA).png", "x")
        with mock.patch.object(nowplaying, "GAMELISTS", es + "/gamelists"), mock.patch.object(nowplaying, "MEDIA", es + "/downloaded_media"):
            info = gameinfo.read("snes", "/roms/snes/Chrono Trigger (USA).sfc")
            nothing = gameinfo.read("snes", "/roms/snes/Unknown.sfc")
        self.assertEqual((info["name"], info["genre"], info["developer"], info["year"], info["rating"]), ("Chrono Trigger", "RPG", "Square", "1995", 4.0))
        self.assertTrue(info["cover"].endswith("Chrono%20Trigger%20%28USA%29.png") or info["cover"].endswith(".png"))
        self.assertEqual(len(info["shots"]), 1)
        self.assertEqual((nothing["name"], nothing["desc"], nothing["shots"]), ("", "", []))

    def test_custom_system_name_preserves_game_key_and_metadata(self):
        system, path = "msx+custom", "/roms/msx+custom/Space Manbow.rom"
        with tempfile.TemporaryDirectory() as directory:
            touch(f"{directory}/{system}/gamelist.xml", """<gameList><game>
                <path>./Space Manbow.rom</path><name>Space Manbow</name><desc>Custom system details.</desc>
                </game></gameList>""")
            with mock.patch.object(nowplaying, "GAMELISTS", directory):
                state = nowplaying.describe(dict(event="game-start", system=system, path=path))
                info = gameinfo.read(system, path)
        with self.subTest("foreground game"):
            self.assertEqual((state["key"], state["playing"], state["title"]),
                             ("msx+custom/Space Manbow", True, "Space Manbow"))
        with self.subTest("game details"):
            self.assertEqual((info["name"], info["desc"]), ("Space Manbow", "Custom system details."))

    def test_a_steam_shortcut_game_is_found_in_es_de_by_its_name(self):
        es = tempfile.mkdtemp(prefix="armadalive-gi-")
        touch(f"{es}/gamelists/switch/gamelist.xml", "<gameList><game><path>./Super Mario 3D World.nsp</path><name>Super Mario 3D World + Bowser\u2019s Fury</name><desc>Cats.</desc></game></gameList>")
        history = mock.Mock(info=lambda key: dict(total=5, plays=1, last=2, favorite=False))
        with (mock.patch.object(nowplaying, "GAMELISTS", es + "/gamelists"),
              mock.patch.object(nowplaying, "MEDIA", es + "/downloaded_media"),
              runtime_object(gameinfo.GameInfo(history)) as gi):
            args = "steam", "", "steam/2214475957", "Super Mario 3D World + Bowser's Fury"
            wait_for(lambda: not gi.of(*args).get("loading"))
            info = gi.of(*args)
        self.assertEqual((info["desc"], info["total"]), ("Cats.", 5))

    def test_unmatched_shortcut_search_yields_to_qt_and_does_not_publish_over_a_new_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            touch(f"{directory}/snes/gamelist.xml", """<gameList>
                <game><path>./New.sfc</path><name>New</name><desc>New details</desc></game>
                </gameList>""")
            entered, release, returned = threading.Event(), threading.Event(), threading.Event()
            threads, results, ticks = [], [], []
            request = "snes", "New.sfc", "snes/New", "New"

            def blocked_search(title):
                threads.append(threading.get_ident())
                entered.set()
                release.wait(2)
                returned.set()
                return "snes", "Old.sfc"

            with (mock.patch.object(nowplaying, "GAMELISTS", directory),
                  mock.patch.object(gameinfo, "find", side_effect=blocked_search),
                  runtime_object(gameinfo.GameInfo(mock.Mock(info=lambda key: {}))) as gi):
                gi.updated.connect(lambda: results.append((threading.get_ident(), gi.of(*request)["desc"])))
                try:
                    first = gi.of("steam", "", "steam/2214475957", "Unmatched")
                    QTimer.singleShot(0, lambda: ticks.append(True))
                    wait_for(lambda: entered.is_set() and ticks)
                    self.assertNotEqual(threads, [threading.get_ident()])
                    self.assertFalse(returned.is_set())
                    self.assertTrue(first.get("loading"))
                    self.assertTrue(gi.of(*request).get("loading"))
                finally:
                    release.set()
                wait_for(lambda: bool(results))
                self.assertEqual(results, [(threading.get_ident(), "New details")])

    def test_visible_local_metadata_refreshes_when_the_gamelist_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            file = f"{directory}/snes/gamelist.xml"
            xml = "<gameList><game><path>./A.sfc</path><desc>{}</desc></game></gameList>"
            touch(file, xml.format("Before"))
            with (mock.patch.object(nowplaying, "GAMELISTS", directory),
                  runtime_object(gameinfo.GameInfo(mock.Mock(info=lambda key: {}))) as gi):
                request = "snes", "./A.sfc", "snes/A", "A"
                wait_for(lambda: gi.of(*request)["desc"] == "Before")
                touch(file, xml.format("New details"))
                wait_for(lambda: gi.of(*request)["desc"] == "New details")

    def test_a_steam_game_takes_its_data_from_the_cached_store_entry(self):
        d = tempfile.mkdtemp(prefix="armadalive-steam-")
        touch(f"{d}/730.json", '{"name": "Counter-Strike 2", "short_description": "Shoot.", "genres": [{"description": "Action"}, {"description": "FPS"}, {"description": "x"}], '
              '"developers": ["Valve"], "release_date": {"date": "21 Aug, 2012"}, "metacritic": {"score": 80}, "screenshots": [{"path_thumbnail": "https://x/1.jpg"}]}')
        with mock.patch.object(gameinfo, "STEAM_INFO", d):
            info = gameinfo.steam_read("730")
            with runtime_object(gameinfo.GameInfo(mock.Mock(info=lambda key: dict(total=9, plays=1, last=2, favorite=False)))) as gi:
                args = "steam", "", "steam/730", "Counter-Strike 2"
                wait_for(lambda: gi.of(*args)["desc"] == "Shoot.")
                via_of = gi.of(*args)
        self.assertEqual((info["name"], info["genre"], info["developer"], info["year"], info["rating"], info["shots"]),
                         ("Counter-Strike 2", "Action, FPS", "Valve", "2012", 4.0, ["https://x/1.jpg"]))
        self.assertEqual((via_of["desc"], via_of["total"]), ("Shoot.", 9))

    def test_expired_store_entry_remains_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/42.json"
            touch(path, '{"short_description": "Cached description"}')
            old = time.time() - 31 * 86400
            os.utime(path, (old, old))
            with mock.patch.object(gameinfo, "STEAM_INFO", directory):
                self.assertEqual(gameinfo.steam_read("42")["desc"], "Cached description")

    def test_store_failure_retries_and_refreshes_stale_fields_on_owner_thread(self):
        calls, published = [], []
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/42.json"
            touch(path, '{"short_description": "Cached description"}')
            old = time.time() - 31 * 86400
            os.utime(path, (old, old))

            def fetch(appid, lang):
                calls.append(threading.get_ident())
                return {"short_description": "Fetched"} if len(calls) == 2 else None

            with (mock.patch.object(gameinfo, "STEAM_INFO", directory),
                  mock.patch.object(gameinfo, "STEAM_RETRY", 0.1, create=True),
                  mock.patch.object(gameinfo, "_steam_fetch", side_effect=fetch),
                  runtime_object(gameinfo.GameInfo(mock.Mock(info=lambda key: {}))) as gi):
                args = "steam", "", "steam/42", "Selected"
                gi.updated.connect(lambda: published.append((threading.get_ident(), gi.of(*args)["desc"])))
                gi.of(*args)
                wait_for(lambda: bool(calls))
                self.assertEqual(gi.of(*args)["desc"], "Cached description")
                wait_for(lambda: gi.of(*args)["desc"] == "Fetched")
                self.assertEqual(published, [(threading.get_ident(), "Cached description"), (threading.get_ident(), "Fetched")])
                self.assertEqual(len(calls), 2)
                self.assertTrue(all(thread != threading.get_ident() for thread in calls))

    def test_blocked_steam_cache_read_leaves_event_loop_free_and_cannot_overwrite_local_game(self):
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        threads, ticks, published = [], [], []

        def blocked_cache(*args):
            threads.append(threading.get_ident())
            entered.set()
            release.wait(1)
            returned.set()
            return {"desc": "Old Steam details"}, True

        with (mock.patch.object(gameinfo, "_steam_entry", side_effect=blocked_cache, create=True),
              mock.patch.object(gameinfo, "_steam_fetch", return_value=None),
              runtime_object(gameinfo.GameInfo(mock.Mock(info=lambda key: {}))) as gi):
            args = "snes", "Super Game (EU).zip", "snes/Super Game (EU)", "Super Game"
            gi.updated.connect(lambda: published.append(gi.of(*args)["desc"]))
            try:
                first = gi.of("steam", "", "steam/42", "Old Steam game")
                QTimer.singleShot(0, lambda: ticks.append(True))
                wait_for(lambda: entered.is_set() and ticks)
                self.assertNotEqual(threads, [threading.get_ident()])
                self.assertFalse(returned.is_set())
                self.assertEqual(first["desc"], "")
                self.assertTrue(gi.of(*args).get("loading"))
            finally:
                release.set()
            wait_for(lambda: bool(published))
            self.assertEqual(published, ["A test game."])

    def test_no_system_or_path_gives_empty_fields(self):
        self.assertEqual(gameinfo.read("", "")["desc"], "")


if __name__ == "__main__":
    unittest.main()
