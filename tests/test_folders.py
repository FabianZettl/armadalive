import json, os, tempfile, unittest
from unittest import mock

from tests.common import app  # noqa: F401
from armadalive import apps


class FakeHistory:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, limit=12):
        return self.rows[:limit]

    def favorites(self):
        return self.rows


class Folders(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="armadalive-folders-")
        self.games = {"snes": [dict(id="esde:snes/A.sfc", name="A", cover="", rom="/roms/snes/A.sfc"), dict(id="esde:snes/B.sfc", name="B", cover="", rom="/roms/snes/B.sfc")]}
        self.steam = [dict(id="steam:10", name="Counter-Strike", icon="")]
        self.patches = [mock.patch.object(apps, "CONFIG", f"{self.dir}/apps.json"), mock.patch.object(apps, "_catalog", lambda: {"firefox": dict(id="firefox", name="Firefox", iconName="")}),
                        mock.patch.object(apps.esdelib, "games", lambda: self.games), mock.patch.object(apps.esdelib, "systems", lambda: {"snes": dict(fullname="Super Nintendo")}),
                        mock.patch.object(apps.steamlib, "games", lambda: self.steam)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def make(self, rows=()):
        return apps.Apps(FakeHistory(list(rows)))

    def test_a_manual_folder_is_made_filled_renamed_and_forgotten_with_its_tile(self):
        a = self.make()
        a.assign(0, "folder:new")
        fid = a.slots[0]["id"]
        self.assertTrue(a.slots[0]["folder"] and a.slots[0]["manual"])
        a.addToFolder(fid, "firefox")
        a.addToFolder(fid, "steam:10")
        a.addToFolder(fid, "nonsense")
        a.renameFolder(fid, "  Tools  ")
        self.assertEqual([i["name"] for i in a.folderItems(fid)], ["Firefox", "Counter-Strike"])
        self.assertEqual(a.slots[0]["name"], "Tools")
        again = self.make()                                  # it survives a restart
        self.assertEqual(again.slots[0]["count"], 2)
        a.removeFromFolder(fid, "firefox")
        self.assertEqual(a.slots[0]["count"], 1)
        a.assign(0, "")
        self.assertEqual(json.load(open(f"{self.dir}/apps.json"))["folders"], {})

    def test_the_favorites_folder_and_a_random_start_inside_a_folder(self):
        a = self.make([("snes/B", dict(path="/roms/snes/B.sfc", title="B", last=1)), ("snes/A", dict(path="/roms/snes/A.sfc", title="A", last=2))])
        a.assign(0, "smart:favorites")
        self.assertEqual([i["name"] for i in a.folderItems("smart:favorites")], ["A", "B"])
        with mock.patch.object(apps.Apps, "launchId") as launch, mock.patch.object(apps.random, "choice", lambda items: items[1]):
            a.randomIn("smart:favorites")
        launch.assert_called_once_with("esde:snes/B.sfc")

    def test_a_system_smart_folder_lists_its_games_by_name_and_only_for_systems_that_have_games(self):
        a = self.make()
        a.assign(0, "smart:esde:snes")
        a.assign(1, "smart:esde:nes")                        # no such system here: refused
        self.assertEqual(len(a.slots), 2)                    # the folder and the empty tile
        self.assertEqual(a.slots[0]["name"], "Super Nintendo")
        self.assertEqual([i["name"] for i in a.folderItems("smart:esde:snes")], ["A", "B"])

    def test_recently_played_resolves_history_entries_to_what_can_be_started(self):
        rows = [("snes/B", dict(path="/roms/snes/B.sfc", last=3)), ("steam/10", dict(path="", last=2)), ("snes/Gone", dict(path="/roms/snes/Gone.sfc", last=1))]
        a = self.make(rows)
        a.assign(0, "smart:recent")
        self.assertEqual([i["name"] for i in a.folderItems("smart:recent")], ["B", "Counter-Strike"])

    def test_the_random_tile_starts_one_of_the_games(self):
        a = self.make()
        a.assign(0, apps.RANDOM)
        started = []
        with mock.patch.object(apps.steamshortcuts, "run_rom") as run, mock.patch.object(apps.esdelib, "command", lambda s, r: ["emu", r]), mock.patch.object(apps.steamui, "eval_js") as js:
            for _ in range(20):
                a.launch(0)
        self.assertTrue(run.called or js.called)

    def test_choices_for_the_picker_offer_new_smart_and_random(self):
        a = self.make()
        ids = [c["id"] for c in a.folderChoices()]
        self.assertEqual(ids[0], "folder:new")
        self.assertIn("smart:recent", ids)
        self.assertIn("smart:esde:snes", ids)
        self.assertEqual(ids[-1], apps.RANDOM)


if __name__ == "__main__":
    unittest.main()


class SystemArtTest(unittest.TestCase):
    def test_art_comes_from_the_theme_in_use(self):
        import tempfile
        from armadalive.apps import system_art
        with tempfile.TemporaryDirectory() as es:
            os.makedirs(es + "/settings"); os.makedirs(es + "/themes/t1/_inc/systems/artwork")
            open(es + "/settings/es_settings.xml", "w").write('<string name="Theme" value="t1" />')
            self.assertEqual(system_art("snes", es), "")
            open(es + "/themes/t1/_inc/systems/artwork/snes.webp", "w").close()
            self.assertTrue(system_art("snes", es).endswith("/t1/_inc/systems/artwork/snes.webp"))
