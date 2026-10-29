import os, shlex, tempfile, unittest
from unittest import mock

from tests.common import app  # noqa: F401
from PySide6.QtGui import QColor, QImage

from armadalive import steamshortcuts as ss

ROM = "/run/media/armada/EXT/Emulation/roms/nes/Super Mario Bros. 3 (Europe).zip"
LOG = f"""Oct 29 16:07:09 Info:   Launching game "Super Mario Bros. 3" from system "nes"...
Oct 29 16:07:09 Info:   Expanded emulator launch command:
Oct 29 16:07:09 Info:   /var/lib/flatpak/exports/bin/org.libretro.RetroArch -L /cores/mesen_libretro.so {shlex.quote(ROM)}
Oct 29 16:15:57 Info:   Expanded emulator launch command:
Oct 29 16:15:57 Info:   /home/armada/.local/bin/eden-turnip -f -g /roms/switch/Ys\\ Origin.nsp
"""


class Launch(unittest.TestCase):
    def test_the_command_that_started_this_rom_is_found(self):
        words = ss.launch_command(LOG, ROM)
        self.assertEqual(words[0], "/var/lib/flatpak/exports/bin/org.libretro.RetroArch")
        self.assertEqual(words[-1], ROM)

    def test_unknown_rom_and_empty_log_give_nothing(self):
        self.assertIsNone(ss.launch_command(LOG, "/roms/never-started.zip"))
        self.assertIsNone(ss.launch_command("", ROM))

    def test_newest_command_wins(self):
        log = LOG + f"Oct 29 17:00:00 Info:   Expanded emulator launch command:\nOct 29 17:00:00 Info:   /usr/bin/other {shlex.quote(ROM)}\n"
        self.assertEqual(ss.launch_command(log, ROM)[0], "/usr/bin/other")

    def test_options_keep_the_arguments_intact_through_a_shell(self):
        words = ss.launch_command(LOG, ROM)
        options = ss.options_for(words)
        self.assertTrue(options.startswith(f"{ss.WRAP} %command% -L /cores/mesen_libretro.so "))
        self.assertEqual(shlex.split(options)[2:], words[1:])


class Existing(unittest.TestCase):
    def test_launch_options_are_read_from_the_binary_shortcuts_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "shortcuts.vdf")
            open(f, "wb").write(b"\x00shortcuts\x00\x000\x00\x01AppName\x00A\x00\x01LaunchOptions\x00wrap %command% -g x\x00\x08\x08")
            with mock.patch.object(ss, "SHORTCUTS", f):
                self.assertEqual(ss.shortcut_launches(), ["wrap %command% -g x"])


class Artwork(unittest.TestCase):
    def test_cover_hero_and_logo_are_found_by_the_rom_name(self):
        with tempfile.TemporaryDirectory() as d:
            for kind, ext in (("covers", "jpg"), ("fanart", "jpg"), ("marquees", "png")):
                os.makedirs(f"{d}/nes/{kind}")
                img = QImage(40, 20, QImage.Format.Format_RGB32)
                img.fill(QColor("#336699"))
                img.save(f"{d}/nes/{kind}/Super Mario Bros. 3 (Europe).{ext}")
            with mock.patch.object(ss, "MEDIA", d):
                art = ss.artwork("nes", ROM)
            self.assertEqual(sorted(a[0] for a in art), [0, 1, 2, 3])
            self.assertTrue(all(a[1] for a in art))
            with mock.patch.object(ss, "MEDIA", "/nonexistent"):
                self.assertEqual(ss.artwork("nes", ROM), [])


class Add(unittest.TestCase):
    def make(self, state):
        np = mock.Mock()
        np.state = state
        with mock.patch.object(ss, "launch_command", return_value=None):
            c = ss.SteamShortcuts(np)
        c.notices = []
        c.notice.connect(lambda code, title: c.notices.append(code))
        return c

    GAME = dict(kind="game", title="Mario 3", path=ROM, system="nes")

    def test_without_a_logged_command_the_user_is_told_to_start_the_game_first(self):
        c = self.make(self.GAME)
        with mock.patch.object(ss, "launch_command", return_value=None):
            c.add()
        self.assertEqual(c.notices, ["unknown"])

    def test_an_existing_shortcut_is_not_added_twice(self):
        c = self.make(self.GAME)
        words = ["/usr/bin/emu", ROM]
        with mock.patch.object(ss, "launch_command", return_value=words), \
                mock.patch.object(ss, "shortcut_launches", return_value=[ss.options_for(words)]), \
                mock.patch.object(ss, "eval_js") as run:
            c.add()
        self.assertEqual(c.notices, ["exists"])
        run.assert_not_called()

    def test_a_new_shortcut_is_sent_to_steam_and_reported(self):
        c = self.make(self.GAME)
        words = ["/usr/bin/emu", ROM]
        sent = {}
        with mock.patch.object(ss, "launch_command", return_value=words), mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", return_value=[]), mock.patch.object(ss, "eval_js", side_effect=lambda js, done: sent.update(js=js, done=done)):
            c.add()
            c.add()   # a second tap while Steam is busy does nothing
        self.assertIn("Mario 3", sent["js"])
        self.assertIn(shlex.quote(ROM).strip("'"), sent["js"].replace("\\\\", "\\"))
        sent["done"](123)
        self.assertEqual(c.notices, ["created"])

    def test_steam_not_reachable_is_reported(self):
        c = self.make(self.GAME)
        with mock.patch.object(ss, "launch_command", return_value=["/usr/bin/emu", ROM]), mock.patch.object(ss, "shortcut_launches", return_value=[]), \
                mock.patch.object(ss, "artwork", return_value=[]), mock.patch.object(ss, "eval_js", side_effect=lambda js, done: done(None)):
            c.add()
        self.assertEqual(c.notices, ["unreachable"])


if __name__ == "__main__":
    unittest.main()
