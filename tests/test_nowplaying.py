import time, unittest

from tests.common import ESDE, GAME, ROMS, Fake
from armadalive import nowplaying as n


class Describe(unittest.TestCase):
    def test_game_has_art_info_and_key(self):
        d = n.describe(GAME)
        self.assertEqual((d["kind"], d["title"], d["key"], d["system"]), ("game", "Super Game", "snes/Super Game (EU)", "snes"))
        self.assertTrue(d["logo"].endswith("Super%20Game%20%28EU%29.png") or d["logo"].endswith("Super Game (EU).png"))
        self.assertTrue(d["fanart"] and d["manual"])
        self.assertEqual((d["info"]["developer"], d["info"]["gametime"], d["hasInfo"]), ("Dev", "7260", True))
        self.assertFalse(d["playing"])
        self.assertTrue(n.describe(dict(GAME, event="game-start"))["playing"])

    def test_idle_and_system(self):
        self.assertEqual(n.describe({})["kind"], "idle")
        self.assertEqual(n.describe({"event": "quit"})["kind"], "idle")
        s = n.describe({"event": "system-select", "system": "snes", "systemName": "Super Nintendo", "t": 1})
        self.assertEqual((s["kind"], s["title"], s["system"]), ("system", "Super Nintendo", "snes"))

    def test_system_name_cannot_escape_the_media_folder(self):
        self.assertEqual(n.describe({"event": "system-select", "system": "../../etc", "t": 1})["kind"], "idle")


class Precedence(unittest.TestCase):
    """What is in front decides: Steam UI, a Steam game, then ES-DE's world."""

    def setUp(self):
        self.np = n.NowPlaying(Fake(), Fake())
        self.np._pinned = False
        self.psx = dict(event="game-start", system="psx", name="Digimon", path=f"{ROMS}/psx/Digimon.chd")

    def title(self):
        self.np._update()
        return self.np._state["title"]

    def test_browsing_beats_a_lingering_emulator(self):
        self.np._esde, self.np._event, self.np._proc, self.np._shortcut = True, GAME, self.psx, True
        self.assertEqual(self.title(), "Super Game")

    def test_a_started_game_shows_the_running_emulator(self):
        self.np._esde, self.np._event, self.np._proc = True, dict(GAME, event="game-start"), self.psx
        self.assertEqual(self.title(), "Digimon")

    def test_steam_ui_selection_beats_everything_behind_it(self):
        self.np._ui_app, self.np._ui_focus, self.np._esde, self.np._event, self.np._proc = (1190170, "OlliOlli"), True, True, GAME, self.psx
        self.assertEqual(self.title(), "OlliOlli")

    def test_a_launching_steam_game_is_held_but_a_shortcut_in_front_ends_the_hold(self):
        self.np._ui_app, self.np._hold = (1190170, "OlliOlli"), time.monotonic() + 25
        self.assertEqual(self.title(), "OlliOlli")
        self.np._esde, self.np._event, self.np._shortcut = True, GAME, True
        self.assertEqual(self.title(), "Super Game")

    def test_a_stale_event_is_ignored_when_es_de_is_closed(self):
        self.np._event, self.np._esde = GAME, False
        self.assertEqual(self.np._state["kind"] if self.np._update() is None else "", "idle")

    def test_snapshot_pin_holds_still(self):
        self.np.pin(GAME)
        self.np._ui_focus, self.np._esde = True, False
        self.np._update()
        self.assertEqual(self.np._state["title"], "Super Game")


class Notes(unittest.TestCase):
    def test_notes_roundtrip_and_clear(self):
        import tempfile
        n.NOTES = tempfile.mkdtemp()
        np = n.NowPlaying(Fake(), Fake())
        np.pin(GAME)
        self.assertEqual(np.notes(), "")
        np.setNotes("hidden warp in level 3")
        self.assertEqual(np.notes(), "hidden warp in level 3")
        np.setNotes("  ")
        self.assertEqual(np.notes(), "")


if __name__ == "__main__":
    unittest.main()
