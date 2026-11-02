import os, tempfile, unittest
from unittest import mock

from tests.common import app  # noqa: F401

import json

from tests.common import GAME
from armadalive import ludo, nowplaying

START = [
    "[x][DEBUG]: [AUTO-SYNC] ⏱️ inventory: save-file walk 0.58s",
    "[x][INFO]: [AUTO-SYNC] ⏱️ pre-launch conflict check 4.32s (waiting on a sync 0.00s, sync 4.32s)",
    "[x][INFO]: [AUTO-SYNC] 🔄 Pre-launch sync for Pokemon - Silver (USA).gbc...".replace(".gbc", ""),
    "[x][INFO]: [AUTO-SYNC] ✅ Pre-launch sync complete for Pokemon - Silver (USA)",
    "[x][INFO]: [AUTO-SYNC] 🎮 RetroArch launched",
]


class Banner(unittest.TestCase):
    def setUp(self):
        self.l = ludo.LudoSync()
        self.addCleanup(self.l._gone.stop)

    def phases(self, lines):
        out = []
        for line in lines:
            self.l.feed(line)
            out.append(self.l.state["phase"])
        return out

    def test_a_start_goes_check_sync_start_gone(self):
        self.assertEqual(self.phases(START), ["check", "check", "sync", "start", ""])
        self.l.feed(START[2])
        self.assertEqual(self.l.state["title"], "Pokemon - Silver (USA)")

    def test_a_walk_inside_a_session_is_no_start(self):
        self.assertEqual(self.phases(["[x]: Save-sync session (connect)", START[0]]), ["", ""])

    def test_after_a_game_closed_saves_go_up_until_the_session_ends(self):
        self.assertEqual(self.phases(["[x]: Save-sync session (RetroArch closed)", START[0], "[x]: session sync 9.54s (dirs 0.01s, states 1.33s)"]),
                         ["upload", "upload", ""])

    def test_background_syncs_show_nothing(self):
        self.assertEqual(self.phases(["[x]: Save-sync session (save changed)", "[x]: session sync 5.70s (dirs 0.02s, states 0.89s)"]), ["", ""])


class Tail(unittest.TestCase):
    def test_only_lines_written_after_it_looked_are_read(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ludo, "LOGS", d):
            path = os.path.join(d, "a.log")
            open(path, "w").write(START[2] + "\n")   # old line: must not show
            l = ludo.LudoSync()
            self.addCleanup(l._gone.stop)
            l.poll()
            self.assertEqual(l.state["phase"], "")
            open(path, "a").write(START[3] + "\n")
            l.poll()
            self.assertEqual(l.state["phase"], "start")


class Highlighted(unittest.TestCase):
    """A tile highlighted in Ludo shows the art of the game like ES-DE does, or the server's screenshot."""
    def describe(self, rom_id, shot=""):
        with tempfile.TemporaryDirectory() as d:
            snapshot = os.path.join(d, "library_snapshot.json")
            json.dump(dict(server_url="https://romm.example/", games=[dict(rom_id=1, local_path=GAME["path"]), dict(rom_id=2)]), open(snapshot, "w"))
            with mock.patch.object(nowplaying, "LUDO", snapshot):
                return nowplaying.describe_ludo(f"ludo:{rom_id}", "Name in Ludo", shot)

    def test_a_downloaded_game_has_its_es_de_logo_and_background(self):
        out = self.describe(1, "/assets/x/0.jpg")
        self.assertTrue(out["logo"].endswith("/marquees/Super%20Game%20(EU).png") or "/marquees/Super" in out["logo"])
        self.assertTrue(out["fanart"].endswith("/fanart/Super%20Game%20(EU).jpg") or "/fanart/Super" in out["fanart"])
        self.assertEqual((out["title"], out["key"]), ("Name in Ludo", "ludo/1"))

    def test_any_other_game_gets_the_screenshot_of_the_server(self):
        out = self.describe(2, "/assets/x/0.jpg")
        self.assertEqual((out["logo"], out["fanart"]), ("", "https://romm.example/assets/x/0.jpg"))

    def test_without_a_snapshot_there_is_still_a_title(self):
        with mock.patch.object(nowplaying, "LUDO", "/nonexistent"):
            out = nowplaying.describe_ludo("ludo:3", "Only a name", "/assets/x/0.jpg")
        self.assertEqual((out["title"], out["fanart"]), ("Only a name", ""))


if __name__ == "__main__":
    unittest.main()
