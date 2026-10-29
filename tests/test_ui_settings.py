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
        self.assertEqual(ui.UiSettings().state, dict(theme="famicom", accent="68E1FB", lang="de", animate=False, dim=False, close=True))

    def test_a_file_with_every_key_is_read(self):  # this used to raise and silently fall back to the defaults
        write(dict(theme="ps2", accent="", lang="de", animate=False, dim=False, close=True))
        self.assertEqual(ui.UiSettings().state["theme"], "ps2")

    def test_partial_broken_and_missing_files(self):
        write({"theme": "snes", "stale": 1})
        self.assertEqual(ui.UiSettings().state, dict(ui.DEFAULTS, theme="snes"))
        write("not json", raw=True)
        self.assertEqual(ui.UiSettings().state, ui.DEFAULTS)
        os.remove(ui.CONFIG)
        self.assertEqual(ui.UiSettings().state, ui.DEFAULTS)

    def test_an_unknown_language_is_refused(self):
        s = ui.UiSettings(); s.setLang("xx")
        self.assertEqual(s.state["lang"], "en")


if __name__ == "__main__":
    unittest.main()
