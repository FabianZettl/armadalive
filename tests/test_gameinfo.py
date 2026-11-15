import os, tempfile, threading, time, unittest
from unittest import mock
from PySide6.QtCore import QTimer

from tests.common import app, runtime_object, touch, wait_for
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
            request = "snes", "New.sfc", "esde:snes/New.sfc", "New"

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
                request = "snes", "./A.sfc", "esde:snes/A.sfc", "A"
                wait_for(lambda: gi.of(*request)["desc"] == "Before")
                touch(file, xml.format("New details"))
                wait_for(lambda: gi.of(*request)["desc"] == "New details")

    def test_configured_rom_root_keeps_nested_roms_system_directory_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = f"{directory}/collection"
            touch(f"{directory}/settings/es_settings.xml", f'<string name="ROMDirectory" value="{root}" />')
            touch(f"{directory}/gamelists/snes/gamelist.xml", """<gameList>
                <game><path>./roms/snes/Unique.sfc</path><desc>Nested game metadata</desc></game>
                </gameList>""")
            with (mock.patch.object(nowplaying, "ES", directory),
                  mock.patch.object(nowplaying, "GAMELISTS", directory + "/gamelists"),
                  mock.patch.object(nowplaying, "MEDIA", directory + "/media")):
                info = gameinfo.read("snes", f"{root}/snes/roms/snes/Unique.sfc")
            self.assertEqual(info["desc"], "Nested game metadata")

    def test_custom_system_root_matches_nested_absolute_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = f"{directory}/snes/collection"
            touch(f"{directory}/settings/es_settings.xml", f'<string name="ROMDirectory" value="{root}" />')
            touch(f"{directory}/custom_systems/es_systems.xml", """<systemList>
                <system><name>snes</name><path>%ROMPATH%/custom</path><extension>.sfc</extension></system>
                </systemList>""")
            touch(f"{directory}/gamelists/snes/gamelist.xml", f"""<gameList>
                <game><path>./Region/snes/Game.sfc</path><name>One</name><desc>Relative</desc></game>
                <game><path>{root}/custom/Another/Game.sfc</path><name>Two</name><desc>Absolute</desc></game>
                <game><path>./Another/Unique.sfc</path><name>Three</name><desc>Unique</desc></game>
                </gameList>""")
            with (mock.patch.object(nowplaying, "ES", directory),
                  mock.patch.object(nowplaying, "GAMELISTS", directory + "/gamelists")):
                self.assertEqual(gameinfo.read("snes", f"{root}/custom/Region/snes/Game.sfc")["desc"], "Relative")
                self.assertEqual(gameinfo.read("snes", "./Another/Game.sfc")["desc"], "Absolute")
                self.assertEqual(gameinfo.read("snes", f"{directory}/unknown/Game.sfc")["desc"], "")
                self.assertEqual(gameinfo.read("snes", f"{directory}/unknown/Unique.sfc")["desc"], "Unique")
                self.assertEqual(gameinfo.read("snes", "./Region/Unique.sfc")["desc"], "")
                self.assertEqual(nowplaying._game_title("snes", f"{root}/custom/Region/snes/Game.sfc"), "One")
                self.assertEqual(nowplaying._game_title("snes", "./Another/Game.sfc"), "Two")

    def test_absolute_gamelist_entries_require_constant_rom_settings_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = f"{directory}/roms"
            touch(f"{directory}/gamelists/snes/gamelist.xml", "<gameList>" + "".join(
                f"<game><path>{root}/snes/Game{n}.sfc</path><name>Game {n}</name></game>" for n in range(10000)
            ) + "</gameList>")
            with (mock.patch.object(nowplaying, "GAMELISTS", directory + "/gamelists"),
                  mock.patch.object(nowplaying, "_rom_dir", return_value=root) as settings):
                self.assertEqual(gameinfo.read("snes", "Game9999.sfc")["name"], "Game 9999")
                self.assertLessEqual(settings.call_count, 2)
                settings.reset_mock()
                nowplaying._gamelists.clear()
                self.assertEqual(nowplaying._game_title("snes", "Game9999.sfc"), "Game 9999")
                self.assertLessEqual(settings.call_count, 2)

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

    def test_expired_store_entry_remains_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/42.json"
            touch(path, '{"short_description": "Cached description"}')
            old = time.time() - 31 * 86400
            os.utime(path, (old, old))
            with mock.patch.object(gameinfo, "STEAM_INFO", directory):
                self.assertEqual(gameinfo.steam_read("42")["desc"], "Cached description")

    def test_fetch_failure_can_retry_and_completion_reaches_owner_thread(self):
        with (tempfile.TemporaryDirectory() as directory,
              mock.patch.object(gameinfo, "STEAM_INFO", directory),
              mock.patch.object(gameinfo, "STEAM_RETRY", 0),
              mock.patch.object(gameinfo, "_steam_fetch", side_effect=[None, {"short_description": "Fetched"}]) as fetch):
            gi = gameinfo.GameInfo(mock.Mock(info=lambda key: {}))
            updated = []
            gi.updated.connect(lambda: updated.append(threading.get_ident()))
            until = time.monotonic() + 0.5
            while time.monotonic() < until and not updated:
                app.processEvents()
                gi.of("steam", "", "steam/42")
                time.sleep(0.001)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(updated, [threading.get_ident()])
            self.assertEqual(gi.of("steam", "", "steam/42")["desc"], "Fetched")

    def test_no_system_or_path_gives_empty_fields(self):
        self.assertEqual(gameinfo.read("", "")["desc"], "")


if __name__ == "__main__":
    unittest.main()
