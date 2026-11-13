import tempfile, unittest
from unittest import mock

from tests.common import app, touch  # noqa: F401
from armadalive import gameinfo, nowplaying


class Read(unittest.TestCase):
    def test_a_gamelist_entry_and_the_pictures_are_read(self):
        es = tempfile.mkdtemp(prefix="armadalive-gi-")
        touch(f"{es}/gamelists/snes/gamelist.xml", "<gameList><game><path>./Chrono Trigger (USA).sfc</path><name>Chrono Trigger</name><desc>A boy meets a girl.</desc>"
              "<genre>RPG</genre><developer>Square</developer><releasedate>19950311T000000</releasedate><rating>0.8</rating><players>1</players></game></gameList>")
        touch(f"{es}/downloaded_media/snes/covers/Chrono Trigger (USA).png", "x")
        touch(f"{es}/downloaded_media/snes/screenshots/Chrono Trigger (USA).png", "x")
        with mock.patch.object(nowplaying, "GAMELISTS", es + "/gamelists"), mock.patch.object(nowplaying, "MEDIA", es + "/downloaded_media"):
            gameinfo._cache.clear()
            info = gameinfo.read("snes", "/roms/snes/Chrono Trigger (USA).sfc")
            nothing = gameinfo.read("snes", "/roms/snes/Unknown.sfc")
        self.assertEqual((info["name"], info["genre"], info["developer"], info["year"], info["rating"]), ("Chrono Trigger", "RPG", "Square", "1995", 4.0))
        self.assertTrue(info["cover"].endswith("Chrono%20Trigger%20%28USA%29.png") or info["cover"].endswith(".png"))
        self.assertEqual(len(info["shots"]), 1)
        self.assertEqual((nothing["name"], nothing["desc"], nothing["shots"]), ("", "", []))

    def test_a_steam_shortcut_game_is_found_in_es_de_by_its_name(self):
        es = tempfile.mkdtemp(prefix="armadalive-gi-")
        touch(f"{es}/gamelists/switch/gamelist.xml", "<gameList><game><path>./Super Mario 3D World.nsp</path><name>Super Mario 3D World + Bowser\u2019s Fury</name><desc>Cats.</desc></game></gameList>")
        with mock.patch.object(nowplaying, "GAMELISTS", es + "/gamelists"), mock.patch.object(nowplaying, "MEDIA", es + "/downloaded_media"):
            gameinfo._cache.clear()
            info = gameinfo.GameInfo(mock.Mock(info=lambda key: dict(total=5, plays=1, last=2, favorite=False))).of("steam", "", "steam/2214475957", "Super Mario 3D World + Bowser's Fury")
        self.assertEqual((info["desc"], info["total"]), ("Cats.", 5))

    def test_a_steam_game_takes_its_data_from_the_cached_store_entry(self):
        d = tempfile.mkdtemp(prefix="armadalive-steam-")
        touch(f"{d}/730.json", '{"name": "Counter-Strike 2", "short_description": "Shoot.", "genres": [{"description": "Action"}, {"description": "FPS"}, {"description": "x"}], '
              '"developers": ["Valve"], "release_date": {"date": "21 Aug, 2012"}, "metacritic": {"score": 80}, "screenshots": [{"path_thumbnail": "https://x/1.jpg"}]}')
        with mock.patch.object(gameinfo, "STEAM_INFO", d):
            info = gameinfo.steam_read("730")
            gi = gameinfo.GameInfo(mock.Mock(info=lambda key: dict(total=9, plays=1, last=2, favorite=False)))
            via_of = gi.of("steam", "", "steam/730", "Counter-Strike 2")
            with mock.patch.object(gameinfo.GameInfo, "_fetch") as fetch, mock.patch.object(gameinfo.threading, "Thread") as thread:
                gi.of("steam", "", "steam/999", "Other")          # not cached: asked for in the background, once
                gi.of("steam", "", "steam/999", "Other")
            self.assertEqual(thread.call_count, 1)
        self.assertEqual((info["name"], info["genre"], info["developer"], info["year"], info["rating"], info["shots"]),
                         ("Counter-Strike 2", "Action, FPS", "Valve", "2012", 4.0, ["https://x/1.jpg"]))
        self.assertEqual((via_of["desc"], via_of["total"]), ("Shoot.", 9))

    def test_no_system_or_path_gives_empty_fields(self):
        self.assertEqual(gameinfo.read("", "")["desc"], "")


if __name__ == "__main__":
    unittest.main()
