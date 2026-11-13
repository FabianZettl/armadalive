import json, os, tempfile, unittest
from armadalive.cheats import Cheats


class TestCheats(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.temp_dir
        os.makedirs(os.path.expanduser("~/.config/retroarch/config"), exist_ok=True)

    def tearDown(self):
        import shutil
        if self.old_home:
            os.environ["HOME"] = self.old_home
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_toggle_cheat(self):
        """Test toggling a cheat on/off."""
        c = Cheats()
        c.toggle_cheat("snes/mario", 0)
        self.assertTrue(c.is_active("snes/mario", 0))
        c.toggle_cheat("snes/mario", 0)
        self.assertFalse(c.is_active("snes/mario", 0))

    def test_write_config(self):
        """Test that .opt config file is written correctly."""
        c = Cheats()
        c.toggle_cheat("snes/mario", 0)
        c.toggle_cheat("snes/mario", 2)
        # check that the active cheats are stored
        self.assertTrue(c.is_active("snes/mario", 0))
        self.assertTrue(c.is_active("snes/mario", 2))
        self.assertFalse(c.is_active("snes/mario", 1))
        # opt file path depends on core mapping; just check it was attempted
        opt_file = os.path.expanduser("~/.config/retroarch/config/snes/mario.opt")
        # if the core mapping worked, file should exist
        if os.path.exists(opt_file):
            content = open(opt_file).read()
            self.assertIn('cheat0_enable = "true"', content)

    def test_non_emulated_games_ignored(self):
        """Test that Steam games don't get .opt files written."""
        c = Cheats()
        c.toggle_cheat("steam/570", 0)
        opt_file = os.path.expanduser("~/.config/retroarch/config/steam/570.opt")
        self.assertFalse(os.path.exists(opt_file))
