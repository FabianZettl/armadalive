import builtins, os, tempfile, threading, time, unittest
from unittest import mock
from PySide6.QtCore import QTimer

from tests.common import ESDE, GAME, ROMS, Fake, dispose_qt, touch, wait_for
from armadalive import history, nowplaying as n


class Describe(unittest.TestCase):
    def test_game_has_art_and_key(self):
        d = n.describe(GAME)
        self.assertEqual((d["kind"], d["title"], d["key"], d["system"]), ("game", "Super Game", "esde:snes/Super Game (EU).zip", "snes"))
        self.assertTrue(d["logo"].endswith("Super%20Game%20%28EU%29.png") or d["logo"].endswith("Super Game (EU).png"))
        self.assertTrue(d["fanart"] and d["manual"])
        self.assertFalse(d["playing"])
        self.assertTrue(n.describe(dict(GAME, event="game-start"))["playing"])

    def test_nested_rom_title_and_media_follow_the_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            touch(f"{directory}/snes/gamelist.xml", """<gameList>
                <game><path>./a/Same.sfc</path><name>First</name></game>
                <game><path>./b/Same.sfc</path><name>Second</name></game>
                </gameList>""")
            touch(f"{directory}/snes/fanart/a/Same.jpg")
            with mock.patch.object(n, "GAMELISTS", directory), mock.patch.object(n, "MEDIA", directory):
                game = n.describe(dict(GAME, path=f"{ROMS}/snes/a/Same.sfc"))
            self.assertEqual(game["title"], "First")
            self.assertTrue(game["fanart"].endswith("/a/Same.jpg"))

    def test_history_and_rule_keys_consider_unlisted_and_hidden_siblings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = f"{directory}/collection"
            touch(f"{directory}/settings/es_settings.xml", f'<string name="ROMDirectory" value="{root}" />')
            touch(f"{directory}/custom_systems/es_systems.xml", """<systemList>
                <system><name>snes</name><path>%ROMPATH%/custom</path><extension>.sfc .zip</extension></system>
                </systemList>""")
            touch(f"{directory}/gamelists/snes/gamelist.xml", """<gameList>
                <game><path>./a/Same.sfc</path><hidden>true</hidden></game>
                <game><path>./a/Unique.sfc</path><name>Unique</name></game>
                </gameList>""")
            for rom in ("a/Same.sfc", "b/Same.zip", "a/Unique.sfc"):
                touch(f"{root}/custom/{rom}")
            with (mock.patch.object(n, "ES", directory), mock.patch.object(n, "GAMELISTS", directory + "/gamelists")):
                one = n.describe(dict(GAME, path=f"{root}/custom/a/Same.sfc"))
                two = n.describe(dict(GAME, path="b/Same.zip"))
                unique = n.describe(dict(GAME, path="a/Unique.sfc"))
            self.assertEqual((one["key"], two["key"], unique["key"]),
                             ("esde:snes/a/Same.sfc", "esde:snes/b/Same.zip", "esde:snes/a/Unique.sfc"))
            self.assertEqual((one.get("legacyKey"), two.get("legacyKey"), unique.get("legacyKey")),
                             ("", "", "snes/Unique"))

    def test_unresolved_gamelist_path_cannot_make_a_legacy_rule_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = f"{directory}/current/roms/snes"
            other = f"{directory}/different/roms/snes/A.sfc"
            touch(f"{folder}/A.sfc")
            touch(other)
            touch(f"{directory}/custom_systems/es_systems.xml", f"""<systemList>
                <system><name>snes</name><path>{folder}</path><extension>.sfc</extension></system>
                </systemList>""")
            touch(f"{directory}/gamelists/snes/gamelist.xml", f"<gameList><game><path>{other}</path></game></gameList>")
            with (mock.patch.object(n, "ES", directory), mock.patch.object(n, "GAMELISTS", f"{directory}/gamelists")):
                self.assertEqual(n.describe(dict(GAME, path=f"{folder}/A.sfc"))["legacyKey"], "")
                self.assertEqual(n.describe(dict(GAME, path=other))["key"], "")

    def test_retargeted_system_root_invalidates_cached_path_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            original, current = f"{directory}/original", f"{directory}/current"
            linked = f"{directory}/linked"
            for folder in (original, current):
                touch(f"{folder}/Unique.sfc")
            os.symlink(original, linked)
            touch(f"{directory}/custom_systems/es_systems.xml", f"""<systemList>
                <system><name>snes</name><path>{linked}</path><extension>.sfc</extension></system>
                </systemList>""")
            gamelists = f"{directory}/gamelists"
            touch(f"{gamelists}/snes/gamelist.xml", f"<gameList><game><path>{original}/Unique.sfc</path></game></gameList>")
            with mock.patch.object(n, "ES", directory):
                self.assertIn("snes/Unique", n.resolve_legacy_keys({"snes/Unique"}, gamelists))
                os.unlink(linked)
                os.symlink(current, linked)
                self.assertNotIn("snes/Unique", n.resolve_legacy_keys({"snes/Unique"}, gamelists))

    def test_configured_rom_root_takes_precedence_over_system_named_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = f"{directory}/snes/collection"
            touch(f"{directory}/settings/es_settings.xml", f'<string name="ROMDirectory" value="{root}" />')
            touch(f"{directory}/gamelists/snes/gamelist.xml", """<gameList>
                <game><path>./Region/Unique.sfc</path><name>Correct title</name></game>
                </gameList>""")
            touch(f"{directory}/media/snes/fanart/Region/Unique.jpg")
            with (mock.patch.object(n, "ES", directory),
                  mock.patch.object(n, "GAMELISTS", directory + "/gamelists"),
                  mock.patch.object(n, "MEDIA", directory + "/media")):
                game = n.describe(dict(GAME, path=f"{root}/snes/Region/Unique.sfc"))
            self.assertEqual(game["title"], "Correct title")
            self.assertTrue(game["fanart"].endswith("/Region/Unique.jpg"))

    def test_symlink_system_root_gives_physical_and_configured_paths_one_playing_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            physical, linked = f"{directory}/physical", f"{directory}/linked"
            relative = "nested/Unique.sfc"
            touch(f"{physical}/{relative}")
            touch(f"{physical}-other/{relative}")
            os.symlink(physical, linked)
            touch(f"{directory}/custom_systems/es_systems.xml", f"""<systemList>
                <system><name>snes</name><path>{linked}</path><extension>.sfc</extension></system>
                </systemList>""")
            with mock.patch.object(n, "ES", directory):
                for form in (relative, f"{linked}/{relative}", f"{physical}/{relative}"):
                    with self.subTest(form=form):
                        state = n.describe(dict(GAME, event="game-start", path=form))
                        self.assertEqual((state["key"], state["romPath"], state["playing"]),
                                         (f"esde:snes/{relative}", f"{linked}/{relative}", True))
                unrelated = n.describe(dict(GAME, event="game-start", path=f"{physical}-other/{relative}"))
                self.assertEqual(unrelated["key"], "")

    def test_steam_title_uses_configured_library(self):
        with tempfile.TemporaryDirectory() as directory:
            touch(f"{directory}/steamapps/appmanifest_42.acf", '"name" "Custom library game"')
            with mock.patch.object(n.steamlib, "_libraries", return_value={directory}):
                game = n.describe_steam("42")
        self.assertEqual((game or {}).get("title"), "Custom library game")

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
        with mock.patch.object(n.NowPlaying, "_scan"):
            self.np = n.NowPlaying(Fake(), Fake())
        self.addCleanup(self.close_backend, self.np)
        self.np._pinned = False
        self.psx = dict(event="game-start", system="psx", name="Digimon", path=f"{ROMS}/psx/Digimon.chd")

    def close_backend(self, backend):
        for timer in backend.findChildren(QTimer):
            timer.stop()
        pollers = backend.findChildren(n.Poller)
        wait_for(lambda: not any(poller._busy for poller in pollers))
        dispose_qt(backend)

    def close_tracker(self, tracker, backend):
        backend.history = None
        self.close_backend(tracker)

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

            def delayed(system, path, folder=None, index=None):
                if path == "A.sfc":
                    threads.append(threading.get_ident())
                    entered.set()
                    release.wait(2)
                    returned.set()
                return read_title(system, path, folder, index)

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
                self.addCleanup(self.close_backend, backend)
                self.addCleanup(self.close_tracker, tracker, backend)
                backend.history = tracker
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
                    self.assertEqual(backend.state["key"], "esde:snes/A.sfc")
                    tracker._open[3] -= 12
                    backend._event = dict(GAME, path="B.sfc", name="Event B")
                    backend._update()
                    self.assertFalse(backend.state["playing"])
                finally:
                    release.set()
                wait_for(lambda: backend.state["title"] == "Scraped B")
                self.assertNotIn("Scraped A", [state["title"] for state in published])
                self.assertIn(("esde:snes/A.sfc", True), [(state["key"], state["playing"]) for state in published])
                self.assertGreaterEqual(tracker.info("esde:snes/A.sfc")["total"], 12)
                self.assertEqual(tracker.info("esde:snes/A.sfc")["plays"], 1)

    def test_a_legacy_rule_is_proved_eagerly_and_ready_while_presentation_remains_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = f"{directory}/roms"
            path = f"{root}/psp/Region/Unique.iso"
            touch(path)
            entered, release = threading.Event(), threading.Event()
            read_metadata = n._esde_game_metadata
            changes = []
            self.np.legacyRulesChanged.connect(lambda: changes.append(self.np.legacy_rule_identity("psp/Unique")))

            def delayed(*args):
                entered.set()
                release.wait(2)
                return read_metadata(*args)

            with (mock.patch.object(n, "_rom_dir", return_value=root),
                  mock.patch.object(n, "GAMELISTS", f"{directory}/gamelists"),
                  mock.patch.object(n, "_esde_game_metadata", side_effect=delayed)):
                try:
                    self.np.watch_legacy_rules({"psp/Unique"})
                    wait_for(lambda: self.np.legacy_rule_identity("psp/Unique") == "esde:psp/Region/Unique.iso")
                    self.assertEqual(changes, [None, "esde:psp/Region/Unique.iso"])
                    self.assertEqual(self.np.state["kind"], "idle")
                    self.np._esde, self.np._event = True, dict(event="game-select", system="psp", path=path)
                    self.np._update()
                    wait_for(entered.is_set)
                    self.assertTrue(self.np.state["metadataPending"])
                    self.assertFalse(self.np.state["legacyPending"])
                    self.assertEqual(self.np.state["legacyKey"], "psp/Unique")
                    self.assertEqual(self.np.esde_launch_state("psp", path, "Unique")["legacyKey"], "psp/Unique")
                finally:
                    release.set()

    def test_unproven_legacy_rule_reports_pending_without_losing_external_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = f"{directory}/roms"
            path = f"{root}/psp/Unique.iso"
            touch(path)
            entered, release = threading.Event(), threading.Event()
            prove = n.resolve_legacy_keys
            ready_states = []

            def on_ready():
                if self.np.legacy_rule_identity("psp/Unique"):
                    ready_states.append(self.np.state["legacyPending"])

            self.np.legacyRulesChanged.connect(on_ready)

            def delayed(*args):
                entered.set()
                release.wait(2)
                return prove(*args)

            with (mock.patch.object(n, "_rom_dir", return_value=root),
                  mock.patch.object(n, "GAMELISTS", f"{directory}/gamelists"),
                  mock.patch.object(n, "resolve_legacy_keys", side_effect=delayed)):
                try:
                    self.np.watch_legacy_rules({"psp/Unique"})
                    wait_for(entered.is_set)
                    state = self.np.esde_launch_state("psp", path, "Unique")
                    self.assertTrue(state["legacyPending"])
                    self.assertEqual(state["legacyKey"], "")
                    self.assertIsNone(self.np.legacy_rule_identity("psp/Unique"))
                    self.np._esde, self.np._event = True, dict(event="game-start", system="psp", path=path)
                    self.np._update()
                    self.assertTrue(self.np.state["playing"])
                    self.assertTrue(self.np.state["legacyPending"])
                    self.assertEqual(self.np.state["legacyKey"], "")
                finally:
                    release.set()
                wait_for(lambda: self.np.state["legacyKey"] == "psp/Unique")
                self.assertTrue(self.np.state["playing"])
                self.assertFalse(self.np.state["legacyPending"])
                self.assertEqual(ready_states, [False])


class RunningGame(unittest.TestCase):
    def cmdline(self, rom, root=ROMS):
        args = b"\0".join(a.encode() for a in ("retroarch", "-L", "/cores/x.so", rom, "--appendconfig", "/c.cfg")) + b"\0"
        read_file = builtins.open
        read_proc = mock.mock_open(read_data=args)
        return (mock.patch("builtins.open", side_effect=lambda path, *a, **kw:
                           read_proc(path, *a, **kw) if str(path).startswith("/proc/") else read_file(path, *a, **kw)),
                mock.patch("os.listdir", return_value=["42"]), mock.patch.object(n, "_rom_dir", return_value=root))

    def test_a_nested_rom_keeps_every_path_component(self):
        rom = f"{ROMS}/gbc/Region/Nested/My Game.gbc"
        a, b, c = self.cmdline(rom)
        with a, b, c:
            game = n.running_game()
        self.assertEqual(game["path"], f"{ROMS}/gbc/Region/Nested/My Game.gbc")
        self.assertEqual(game["name"], "My Game")

    def test_a_rom_under_another_mount_of_the_same_card_is_found(self):
        with tempfile.TemporaryDirectory() as directory:
            root = f"{directory}/card/roms"
            relative = "gbc/Pokemon - Silver.gbc"
            canonical = f"{root}/{relative}"
            alternate = f"{directory}/alternate/roms/{relative}"
            different = f"{directory}/different/roms/{relative}"
            touch(canonical)
            touch(different)
            os.makedirs(os.path.dirname(alternate))
            os.link(canonical, alternate)  # same inode as through a bind mount
            for rom in (alternate, canonical):
                a, b, c = self.cmdline(rom, root=root)
                with a, b, c:
                    game = n.running_game()
                self.assertEqual((game["system"], game["name"], game["path"]), ("gbc", "Pokemon - Silver", canonical))
            a, b, c = self.cmdline(different, root=root)
            with a, b, c:
                self.assertIsNone(n.running_game())

    def test_detects_running_rom_under_a_custom_system_root(self):
        with tempfile.TemporaryDirectory() as directory:
            rom = f"{directory}/outside-roms/Region/Unique.sfc"
            touch(f"{directory}/custom_systems/es_systems.xml", f"""<systemList>
                <system><name>snes</name><path>{directory}/outside-roms</path><extension>.sfc</extension></system>
                </systemList>""")
            read_file = builtins.open
            read_proc = mock.mock_open(read_data=f"retroarch\0-L\0/cores/core.so\0{rom}\0".encode())
            with (mock.patch.object(n, "ES", directory),
                  mock.patch("os.listdir", return_value=["42"]),
                  mock.patch("builtins.open", side_effect=lambda path, *a, **kw:
                             read_proc(path, *a, **kw) if str(path).startswith("/proc/") else read_file(path, *a, **kw))):
                game = n.running_game()
                self.assertEqual((game["system"], game["path"], n.describe(game)["key"]),
                                 ("snes", rom, "esde:snes/Region/Unique.sfc"))

    def test_detects_physical_path_for_a_symlink_configured_system(self):
        with tempfile.TemporaryDirectory() as directory:
            physical, linked = f"{directory}/physical", f"{directory}/linked"
            rom = f"{physical}/Region/Unique.sfc"
            touch(rom)
            os.symlink(physical, linked)
            touch(f"{directory}/custom_systems/es_systems.xml", f"""<systemList>
                <system><name>snes</name><path>{linked}</path><extension>.sfc</extension></system>
                </systemList>""")
            read_file = builtins.open
            read_proc = mock.mock_open(read_data=f"retroarch\0{rom}\0".encode())
            with (mock.patch.object(n, "ES", directory), mock.patch("os.listdir", return_value=["42"]),
                  mock.patch("builtins.open", side_effect=lambda path, *a, **kw:
                             read_proc(path, *a, **kw) if str(path).startswith("/proc/") else read_file(path, *a, **kw))):
                game = n.running_game()
                self.assertIsNotNone(game)
                self.assertEqual((game["path"], n.describe(game)["key"]),
                                 (f"{linked}/Region/Unique.sfc", "esde:snes/Region/Unique.sfc"))


if __name__ == "__main__":
    unittest.main()
