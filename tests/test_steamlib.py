import os, struct, tempfile, unittest
from unittest import mock

from tests.common import touch, wait_for
from PySide6.QtGui import QColor, QImage

from armadalive import apps, steamlib


def vdf_shortcut(appid, name):
    return b"\0" + b"0\0" + b"\2appid\0" + struct.pack("<I", appid) + b"\1AppName\0" + name.encode() + b"\0" + b"\x08"


class Library(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="armadalive-steam-")
        r = self.root
        touch(f"{r}/steamapps/appmanifest_10.acf", '"AppState"\n{\n\t"appid"\t\t"10"\n\t"name"\t\t"Counter-Strike"\n}\n')
        touch(f"{r}/steamapps/appmanifest_1493710.acf", '"AppState"\n{\n\t"appid"\t\t"1493710"\n\t"name"\t\t"Proton Experimental"\n}\n')
        side = QImage(60, 90, QImage.Format_RGB32)
        side.fill(QColor("red"))
        os.makedirs(f"{r}/appcache/librarycache/10", exist_ok=True)
        side.save(f"{r}/appcache/librarycache/10/library_600x900.jpg")
        os.makedirs(f"{r}/userdata/1/config", exist_ok=True)
        with open(f"{r}/userdata/1/config/shortcuts.vdf", "wb") as f:
            f.write(b"\0shortcuts\0" + vdf_shortcut(3422048380, "Eglantine") + b"\x08\x08")
        p = mock.patch.multiple(steamlib, STEAM=r, CACHE=f"{r}/covers")
        p.start()
        self.addCleanup(p.stop)

    def test_installed_games_and_shortcuts_are_listed_and_tools_are_not(self):
        g = {x["id"]: x for x in steamlib.games()}
        self.assertEqual(set(g), {"steam:10", f"steam:{(3422048380 << 32) | 0x02000000}"})
        self.assertEqual(g["steam:10"]["name"], "Counter-Strike")

    def test_a_shortcut_is_found_by_its_app_id(self):
        self.assertEqual(steamlib.shortcut(3422048380), ("Eglantine", ""))
        self.assertIsNone(steamlib.shortcut(1))

    def test_cover_is_a_cached_rounded_square(self):
        url = {x["id"]: x for x in steamlib.games()}["steam:10"]["icon"]
        img = QImage(url.replace("file://", ""))
        self.assertEqual((img.width(), img.height()), (steamlib.SIZE, steamlib.SIZE))
        self.assertEqual(img.pixelColor(0, 0).alpha(), 0)          # corner is cut away
        self.assertGreater(img.pixelColor(180, 180).red(), 240)     # middle is the cover

    def test_title_only_scan_skips_artwork(self):
        with mock.patch.object(steamlib, "_installed_art") as installed, \
                mock.patch.object(steamlib, "_shortcut_art") as shortcuts:
            games = steamlib.games(art=False)
        installed.assert_not_called()
        shortcuts.assert_not_called()
        self.assertEqual({game["name"] for game in games}, {"Counter-Strike", "Eglantine"})
        self.assertTrue(all(not game["icon"] for game in games))

    def test_linked_game_artwork_is_indexed_for_each_game(self):
        cache = f"{self.root}/appcache/librarycache"
        target = f"{self.root}/shared-artwork"
        touch(f"{target}/library_600x900.jpg")
        for appid in ("11", "12"):
            os.symlink(target, f"{cache}/{appid}")
        covers = steamlib._installed_art(cache)
        self.assertEqual(covers.get("11"), f"{cache}/11/library_600x900.jpg")
        self.assertEqual(covers.get("12"), f"{cache}/12/library_600x900.jpg")

    def test_artwork_directory_cycle_is_pruned_before_relisting(self):
        cache = f"{self.root}/appcache/librarycache"
        touch(f"{cache}/10/nested/header.jpg")
        os.symlink(f"{cache}/10", f"{cache}/10/nested/ancestor")
        real_scandir = os.scandir
        visited = []

        def bounded_scandir(path):
            visited.append(path)
            if len(visited) > 4:
                raise AssertionError("artwork traversal followed a directory cycle")
            return real_scandir(path)

        with mock.patch.object(os, "scandir", bounded_scandir):
            covers = steamlib._installed_art(cache)
        self.assertEqual(covers["10"], f"{cache}/10/library_600x900.jpg")
        self.assertEqual(len(visited), 3)

    def test_grid_adds_replaces_and_removes_and_only_knows_catalog_ids(self):
        with mock.patch.object(apps, "CONFIG", f"{self.root}/apps.json"), mock.patch.object(apps, "_catalog", lambda: {}):
            a = apps.Apps()
            wait_for(lambda: not a.catalogLoading)
            self.assertEqual(a.slots, [{}])
            a.assign(0, "steam:10")
            a.assign(5, "steam:10")
            a.assign(0, "nonsense")
            self.assertEqual([s.get("id") for s in a.slots], ["steam:10", None])
            a.assign(0, "")
            a.flush()
            self.assertEqual(a.slots, [{}])


if __name__ == "__main__":
    unittest.main()
