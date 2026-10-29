import json, os, tempfile, unittest

from tests.common import app  # noqa: F401
from PySide6.QtQml import QJSEngine
from armadalive import tiles

IDS = ["a", "b", "c", "d"]


class Order(unittest.TestCase):
    def setUp(self):
        tiles.CONFIG = os.path.join(tempfile.mkdtemp(), "tiles.json")
        self.t = tiles.Tiles()

    def test_unmoved_tiles_keep_their_order(self):
        self.assertEqual(self.t.arrange(IDS), IDS)

    def test_swap_and_remember(self):
        self.t.swap("a", "c", IDS)
        self.assertEqual(self.t.arrange(IDS), ["c", "b", "a", "d"])
        self.assertEqual(tiles.Tiles().arrange(IDS), ["c", "b", "a", "d"])   # after a restart

    def test_a_tile_added_by_an_update_goes_to_the_end_and_a_removed_one_is_ignored(self):
        self.t.swap("a", "b", IDS)
        self.assertEqual(self.t.arrange(["b", "a", "c", "d", "new"]), ["b", "a", "c", "d", "new"])
        self.assertEqual(self.t.arrange(["b", "c", "d"]), ["b", "c", "d"])

    def test_a_list_made_in_qml_is_understood(self):  # QML hands over a QJSValue, not a Python list
        engine = QJSEngine()   # the value is only valid while its engine lives
        js = engine.evaluate('["a", "b", "c"]')
        self.assertEqual(self.t.arrange(js), ["a", "b", "c"])
        self.t.swap("a", "c", js)
        self.assertEqual(self.t.arrange(js), ["c", "b", "a"])

    def test_nonsense_swaps_change_nothing(self):
        self.t.swap("a", "a", IDS); self.t.swap("a", "zzz", IDS)
        self.assertEqual(self.t.arrange(IDS), IDS)

    def test_reset_and_a_broken_file(self):
        self.t.swap("a", "d", IDS); self.t.reset()
        self.assertEqual(self.t.arrange(IDS), IDS)
        with open(tiles.CONFIG, "w") as f:
            f.write("{broken")
        self.assertEqual(tiles.Tiles().arrange(IDS), IDS)
        with open(tiles.CONFIG, "w") as f:
            json.dump({"order": "not a list"}, f)
        self.assertEqual(tiles.Tiles().arrange(IDS), IDS)


if __name__ == "__main__":
    unittest.main()
