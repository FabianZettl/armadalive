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


if __name__ == "__main__":
    unittest.main()
