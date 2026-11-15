import os, tempfile, unittest
from unittest import mock

from tests.common import app, touch  # noqa: F401

from armadalive import esdelib


class Command(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="armadalive-emu-")
        for f in ("bin/retroarch", "cores/snes9x_libretro.so"):
            touch(f"{self.d}/{f}")
        self.defs = {"snes": dict(fullname="SNES", extensions={".sfc"}, commands=[
            ("Snes9x", "%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/snes9x_libretro.so %ROM%"), ("Other", "%EMULATOR_OTHER% %ROM%")])}
        self.rules = {("emulator", "RETROARCH"): [("systempath", ["no-such-emulator"]), ("staticpath", [f"{self.d}/bin/retroarch"])],
                      ("core", "RETROARCH"): [("corepath", [f"{self.d}/nope", f"{self.d}/cores"])]}
        self.rom = "/roms/snes/Chrono Trigger (USA).sfc"

    def test_command_is_rebuilt_like_es_de_logs_it(self):
        words = esdelib.command("snes", self.rom, self.defs, self.rules)
        self.assertEqual(words, [f"{self.d}/bin/retroarch", "-L", f"{self.d}/cores/snes9x_libretro.so", self.rom])

    def test_alternative_emulator_label_picks_the_command_and_missing_emulator_gives_none(self):
        self.assertIsNone(esdelib.command("snes", self.rom, self.defs, self.rules, label="Other"))   # no OTHER rule: not installed
        self.assertIsNone(esdelib.command("nes", self.rom, self.defs, self.rules))                  # unknown system

    def test_flags_for_es_de_itself_are_dropped_and_unknown_placeholders_refuse(self):
        self.defs["snes"]["commands"] = [("a", "%ENABLESHORTCUTS% %EMULATOR_RETROARCH% %ROM%"), ("b", "%EMULATOR_RETROARCH% %STARTDIR%")]
        self.assertEqual(esdelib.command("snes", self.rom, self.defs, self.rules, label="a"), [f"{self.d}/bin/retroarch", self.rom])
        self.assertIsNone(esdelib.command("snes", self.rom, self.defs, self.rules, label="b"))


class Games(unittest.TestCase):
    def test_nested_games_keep_their_own_names_visibility_and_launch_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = f"{directory}/collection"
            one, two = f"{folder}/a/Shared.sfc", f"{folder}/b/Shared.sfc"
            touch(one)
            touch(two)
            gamelists = f"{directory}/gamelists"
            gamelist = f"{gamelists}/snes/gamelist.xml"
            games = """<gameList>
                <game><path>./a/Shared.sfc</path><name>Game A</name><altemulator>A</altemulator></game>
                <game><path>{}</path><name>Game B</name><altemulator>B</altemulator></game>
                </gameList>""".format(two)
            touch(gamelist, games)
            definitions = {"snes": dict(path=folder, extensions={".sfc"}, commands=[("A", "emu_a %ROM%"), ("B", "emu_b %ROM%")])}
            with (mock.patch.object(esdelib, "GAMELISTS", gamelists),
                  mock.patch.object(esdelib, "_rom_dir", return_value=f"{directory}/roms"),
                  mock.patch.object(esdelib, "_rules", return_value={})):
                rows = esdelib.games(definitions)["snes"]
                self.assertEqual([(row["id"], row["name"]) for row in rows],
                                 [("esde:snes/a/Shared.sfc", "Game A"), ("esde:snes/b/Shared.sfc", "Game B")])
                self.assertEqual(esdelib.command("snes", one, definitions), ["emu_a", one])
                self.assertEqual(esdelib.command("snes", two, definitions), ["emu_b", two])
                touch(gamelist, games.replace("<name>Game A</name>", "<name>Game A</name><hidden>true</hidden>"))
                self.assertEqual([row["name"] for row in esdelib.games(definitions)["snes"]], ["Game B"])

    def test_games_are_found_by_extension_with_gamelist_names_and_hidden_ones_left_out(self):
        root, es = tempfile.mkdtemp(prefix="armadalive-roms-"), tempfile.mkdtemp(prefix="armadalive-es-")
        for f in ("snes/Chrono.sfc", "snes/Hidden.sfc", "snes/notes.txt", "snes/sub/Deep.SFC", "gba/x.gba"):
            touch(f"{root}/{f}")
        touch(f"{es}/gamelists/snes/gamelist.xml",
              "<gameList><game><path>./Chrono.sfc</path><name>Chrono Trigger</name></game>"
              "<game><path>./Hidden.sfc</path><hidden>true</hidden></game></gameList>")
        defs = {"snes": dict(fullname="SNES", extensions={".sfc"}, commands=[("a", "x")])}
        with mock.patch.object(esdelib, "systems", lambda: defs), mock.patch.object(esdelib, "_rom_dir", lambda: root), \
                mock.patch.object(esdelib, "GAMELISTS", es + "/gamelists"):
            found = esdelib.games()
        self.assertEqual(list(found), ["snes"])
        self.assertEqual([(g["id"], g["name"]) for g in found["snes"]],
                         [("esde:snes/Chrono.sfc", "Chrono Trigger"), ("esde:snes/sub/Deep.SFC", "Deep")])

    def test_a_system_with_its_own_path_is_read_from_there(self):
        root, other = tempfile.mkdtemp(prefix="armadalive-roms-"), tempfile.mkdtemp(prefix="armadalive-internal-")
        touch(f"{other}/Game.nup")
        defs = {"switch2": dict(fullname="Switch 2", path=other, extensions={".nup"}, commands=[("a", "x")])}
        with mock.patch.object(esdelib, "systems", lambda: defs), mock.patch.object(esdelib, "_rom_dir", lambda: root):
            found = esdelib.games()
        self.assertEqual([g["rom"] for g in found["switch2"]], [f"{other}/Game.nup"])


if __name__ == "__main__":
    unittest.main()
