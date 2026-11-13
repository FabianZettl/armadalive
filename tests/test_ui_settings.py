import json, os, tempfile, unittest

from tests.common import app  # noqa: F401
from armadalive import ui


def write(value, raw=False):
    with open(ui.CONFIG, "w") as f:
        f.write(value) if raw else json.dump(value, f)


class Persistence(unittest.TestCase):
    def setUp(self):
        ui.CONFIG = os.path.join(tempfile.mkdtemp(), "ui.json")

    def test_choices_survive_a_restart(self):
        a = ui.UiSettings()
        a.setTheme("famicom"); a.setAccent("68E1FB"); a.setLang("de"); a.setAnimate(False); a.setDim(False)
        self.assertEqual(ui.UiSettings().state, dict(theme="famicom", accent="68E1FB", lang="de", animate=False, dim=False, close=True, heat=85, apps=True, ledFollow=True, onboarded=False))

    def test_a_file_with_every_key_is_read(self):  # this used to raise and silently fall back to the defaults
        write(dict(theme="ps2", accent="", lang="de", animate=False, dim=False, close=True, heat=85, apps=True))
        self.assertEqual(ui.UiSettings().state["theme"], "ps2")

    def test_partial_broken_and_missing_files(self):
        write({"theme": "snes", "stale": 1})
        self.assertEqual(ui.UiSettings().state, dict(ui.DEFAULTS, theme="snes"))
        write("not json", raw=True)
        self.assertEqual(ui.UiSettings().state, dict(ui.DEFAULTS, onboarded=False))
        os.remove(ui.CONFIG)
        self.assertEqual(ui.UiSettings().state, dict(ui.DEFAULTS, onboarded=False))

    def test_only_a_fresh_install_gets_the_first_run_setup(self):
        self.assertFalse(ui.UiSettings().state["onboarded"])      # no settings yet
        write({"theme": "snes"})
        s = ui.UiSettings()
        self.assertTrue(s.state["onboarded"])                      # an install that already has settings keeps its way
        s.setOnboarded(False)
        self.assertFalse(ui.UiSettings().state["onboarded"])       # "Run setup again"

    def test_an_unknown_language_is_refused(self):
        s = ui.UiSettings(); s.setLang("xx")
        self.assertEqual(s.state["lang"], "en")


if __name__ == "__main__":
    unittest.main()
