import builtins, tempfile, threading, time, unittest
from unittest import mock

from PySide6.QtCore import QTimer

from tests.common import GAME, ROMS, Fake, dispose_qt, touch, wait_for
from armadalive import gamerules, history, nowplaying as n


class Describe(unittest.TestCase):
    def test_game_has_art_and_key(self):
        d = n.describe(GAME)
        self.assertEqual((d["kind"], d["title"], d["key"], d["system"]), ("game", "Super Game", "snes/Super Game (EU)", "snes"))
        self.assertTrue(d["logo"].endswith("Super%20Game%20%28EU%29.png") or d["logo"].endswith("Super Game (EU).png"))
        self.assertTrue(d["fanart"] and d["manual"])
        self.assertFalse(d["playing"])
        self.assertTrue(n.describe(dict(GAME, event="game-start"))["playing"])

    def test_idle_and_system(self):
        self.assertEqual(n.describe({})["kind"], "idle")
        self.assertEqual(n.describe({"event": "quit"})["kind"], "idle")
        s = n.describe({"event": "system-select", "system": "snes", "systemName": "Super Nintendo", "t": 1})
        self.assertEqual((s["kind"], s["title"], s["system"]), ("system", "Super Nintendo", "snes"))

    def test_system_name_cannot_escape_the_media_folder(self):
        for system in (".", "..", "../../etc", "/tmp", "snes/other", "snes\0extra"):
            with self.subTest(system=system):
                self.assertEqual(n.describe(dict(event="system-select", system=system, t=1))["kind"], "idle")


class Precedence(unittest.TestCase):
    """What is in front decides: Steam UI, a Steam game, then ES-DE's world."""

    def setUp(self):
        with mock.patch.object(n.NowPlaying, "_scan"):
            self.np = n.NowPlaying(Fake(), Fake())
        self.addCleanup(dispose_qt, self.np)
        self.psx = dict(event="game-start", system="psx", name="Digimon", path=f"{ROMS}/psx/Digimon.chd")

    def title(self):
        self.np._update()
        wait_for(lambda: not self.np.state.get("metadataPending"))
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
        self.assertTrue(all(self.np.state[field] for field in ("logo", "fanart", "manual")))
        self.np._ui_focus, self.np._esde = True, False
        self.np._update()
        self.assertEqual(self.np._state["title"], "Super Game")

    def test_busy_metadata_does_not_block_or_drop_an_intervening_game_start(self):
        with tempfile.TemporaryDirectory() as directory:
            touch(f"{directory}/snes/gamelist.xml", """<gameList>
                <game><path>./A.sfc</path><name>Scraped A</name></game>
                <game><path>./B.sfc</path><name>Scraped B</name></game>
                </gameList>""")
            entered, release, returned = threading.Event(), threading.Event(), threading.Event()
            threads, published, ticks = [], [], []
            read_title = n._game_title

            def delayed(system, path):
                if path == "A.sfc":
                    threads.append(threading.get_ident())
                    entered.set()
                    release.wait(2)
                    returned.set()
                return read_title(system, path)

            with (mock.patch.object(n, "GAMELISTS", directory),
                  mock.patch.object(n, "STATE", directory + "/no-state.json"),
                  mock.patch.object(n, "running_game", return_value=None),
                  mock.patch.object(n, "esde_running", return_value=True),
                  mock.patch.object(n, "steam_running", return_value=False),
                  mock.patch.object(n, "_game_title", side_effect=delayed)):
                backend = n.NowPlaying(Fake(), Fake())
                path = f"{directory}/history.json"
                touch(path, '{"imported": true}')
                tracker = history.History(backend, path)
                self.addCleanup(dispose_qt, backend)
                self.addCleanup(dispose_qt, tracker)
                backend.history = tracker
                rules_path = f"{directory}/rules.json"
                touch(rules_path, '{"rules": {"game:snes/A": {"fps": 30}}}')
                display = mock.Mock()
                with mock.patch.object(gamerules, "CONFIG", rules_path):
                    rules = gamerules.GameRules(backend, display, mock.Mock())
                self.addCleanup(dispose_qt, rules)
                backend.changed.connect(lambda: published.append(dict(backend.state)))
                backend._esde = True
                backend._event = dict(GAME, path="A.sfc", name="Event A")
                try:
                    backend._update()
                    QTimer.singleShot(0, lambda: ticks.append(True))
                    wait_for(lambda: entered.is_set() and ticks)
                    self.assertNotEqual(threads, [threading.get_ident()])
                    self.assertFalse(returned.is_set())
                    self.assertEqual(backend.state["title"], "Event A")
                    backend._event = dict(backend._event, event="game-start")
                    backend._update()
                    self.assertTrue(backend.state["playing"])
                    self.assertEqual(backend.state["key"], "snes/A")
                    display.setFpsLimit.assert_called_once_with(30)
                    tracker._open[3] -= 12
                    backend._event = dict(GAME, path="B.sfc", name="Event B")
                    backend._update()
                    self.assertFalse(backend.state["playing"])
                finally:
                    release.set()
                wait_for(lambda: backend.state["title"] == "Scraped B")
                self.assertNotIn("Scraped A", [state["title"] for state in published])
                self.assertIn(("snes/A", True), [(state["key"], state["playing"]) for state in published])
                self.assertGreaterEqual(tracker.info("snes/A")["total"], 12)
                self.assertEqual(tracker.info("snes/A")["plays"], 1)

    def test_matching_metadata_enriches_the_open_history_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/history.json"
            touch(path, '{"imported": true}')
            tracker = history.History(self.np, path)
            self.addCleanup(dispose_qt, tracker)
            self.np.history = tracker
            self.np._event, self.np._esde = dict(GAME, event="game-start"), True
            self.np._update()
            key = "snes/Super Game (EU)"
            self.assertEqual(tracker.games[key]["plays"], 1)
            self.assertEqual(tracker.games[key]["title"], "x")
            wait_for(lambda: bool(tracker.games[key].get("art")))
            self.assertEqual((tracker.games[key]["title"], tracker.games[key]["plays"]), ("Super Game", 1))

    def test_blocked_steam_manifest_does_not_block_focus_changes_or_publish_late(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = f"{directory}/steamapps/appmanifest_42.acf"
            touch(manifest, '"name" "Old Steam game"')
            touch(f"{directory}/steamapps/appmanifest_43.acf", '"name" "Superseded Steam game"')
            entered, release = threading.Event(), threading.Event()
            reads, published = [], []
            read = builtins.open

            def blocked(path, *args, **kwargs):
                if path == manifest:
                    reads.append(threading.get_ident())
                    entered.set()
                    release.wait(1)
                return read(path, *args, **kwargs)

            self.np.changed.connect(lambda: published.append(self.np.state["key"]))
            with (mock.patch.object(n, "STEAM_LIBRARIES", [directory]),
                  mock.patch("builtins.open", side_effect=blocked)):
                try:
                    self.np._focus("42")
                    wait_for(entered.is_set)
                    self.np._focus("43")
                    self.np._ui_selected(10, "Current selection")
                    self.np._focus("769")
                    self.assertNotEqual(reads, [threading.get_ident()])
                    self.assertEqual((self.np.state["key"], self.np.state["playing"]), ("steam/10", False))
                finally:
                    release.set()
                wait_for(lambda: not self.np._focus_lookup._busy)
                self.assertNotIn("steam/42", published)
                self.assertNotIn("steam/43", published)

    def test_process_scan_preserves_foreground_during_steam_focus_lookup(self):
        background = dict(GAME, event="game-start")
        background_key = "snes/Super Game (EU)"
        for outcome, expected in (
            ("known", "steam/42"),
            ("missing", background_key),
            ("failed", background_key),
            ("unfocused", background_key),
        ):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                manifest = f"{directory}/steamapps/appmanifest_42.acf"
                touch(f"{directory}/steamapps/appmanifest_41.acf", '"name" "Previous Steam game"')
                if outcome != "missing":
                    touch(manifest, '"name" "Next Steam game"')
                entered, release = threading.Event(), threading.Event()
                read = builtins.open

                def blocked(path, *args, **kwargs):
                    if path == manifest:
                        entered.set()
                        release.wait(3)
                        if outcome == "failed":
                            raise RuntimeError("Steam manifest reader failed")
                    return read(path, *args, **kwargs)

                self.np._focus("")
                self.np._scan((None, False, False))
                with (mock.patch.object(n, "STEAM_LIBRARIES", [directory]),
                      mock.patch("builtins.open", side_effect=blocked)):
                    self.np._focus("41")
                    wait_for(lambda: self.np.state["key"] == "steam/41")
                    try:
                        self.np._focus("42")
                        wait_for(entered.is_set)
                        self.np._scan((background, True, True))
                        self.assertTrue(self.np.running)
                        self.assertEqual((self.np.state["key"], self.np.state["playing"]), ("steam/41", True))
                        if outcome == "unfocused":
                            self.np._focus("")
                            self.assertEqual(self.np.state["key"], background_key)
                    finally:
                        release.set()
                        wait_for(lambda: not self.np._focus_lookup._busy)
                    self.assertEqual((self.np.state["key"], self.np.state["playing"]), (expected, True))

    def test_known_steam_start_precedes_its_blocked_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            touch(f"{directory}/steamapps/appmanifest_42.acf", '"name" "Steam game"')
            entered, release = threading.Event(), threading.Event()
            first = n._first

            def blocked(pattern):
                if "/42/" in pattern:
                    entered.set()
                    release.wait(1)
                return first(pattern)

            with (mock.patch.object(n, "STEAM_LIBRARIES", [directory]),
                  mock.patch.object(n, "_first", side_effect=blocked)):
                try:
                    self.np._focus("42")
                    wait_for(entered.is_set)
                    self.assertEqual((self.np.state["key"], self.np.state["title"], self.np.state["playing"]),
                                     ("steam/42", "Steam game", True))
                    self.assertTrue(self.np.state.get("metadataPending"))
                finally:
                    release.set()
                wait_for(lambda: not self.np.state.get("metadataPending"))


class RunningGame(unittest.TestCase):
    def cmdline(self, rom):
        args = b"\0".join(a.encode() for a in ("retroarch", "-L", "/cores/x.so", rom, "--appendconfig", "/c.cfg")) + b"\0"
        return mock.patch("builtins.open", mock.mock_open(read_data=args)), mock.patch("os.listdir", return_value=["42"]), mock.patch.object(n, "_rom_dir", return_value=ROMS)

    def test_a_rom_under_another_mount_of_the_same_card_is_found(self):   # what Ludo starts: /run/media/EXT instead of /run/media/armada/EXT
        for rom in ("/run/media/EXT/Emulation/roms/gbc/Pokemon - Silver.gbc", ROMS + "/gbc/Pokemon - Silver.gbc"):
            a, b, c = self.cmdline(rom)
            with a, b, c:
                game = n.running_game()
            self.assertEqual((game["system"], game["name"]), ("gbc", "Pokemon - Silver"))


if __name__ == "__main__":
    unittest.main()
