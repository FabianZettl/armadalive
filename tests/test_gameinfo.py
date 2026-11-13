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

    def test_no_system_or_path_gives_empty_fields(self):
        self.assertEqual(gameinfo.read("", "")["desc"], "")


if __name__ == "__main__":
    unittest.main()
