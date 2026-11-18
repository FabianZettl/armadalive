"""Exercise a history write during shutdown of this test's own process."""
import json
import signal
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PySide6.QtCore import QObject, Signal

from armadalive import history, persistence
from armadalive.backup import Backup
from tests.shutdown_process import child_app, exec_child, gate_write, run_child


class FakeNow(QObject):
    changed = Signal()
    state = {"kind": "idle"}


def child(directory, mode):
    entered, release = threading.Event(), threading.Event()
    app = child_app(directory, mode, release)
    config = directory / "history.json"
    config.write_text(json.dumps({"imported": True, "games": {}, "sessions": []}))
    now = FakeNow()

    with mock.patch.object(persistence, "write_json",
                           gate_write(persistence.write_json, entered, release)):
        play_history = history.History(now, str(config))
        coordinator = Backup((play_history,))
        app.aboutToQuit.connect(coordinator.flushWriters)
        play_history.toggleFavorite("steam/42", "Game", "steam", "")
        if mode == "export":
            coordinator.save()
            play_history.toggleFavorite("steam/43", "During export", "steam", "")
        return exec_child(app, mode, entered)


class Shutdown(unittest.TestCase):
    def run_history(self, mode, signum=None):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stderr = run_child(self, "tests.test_history_shutdown", root, mode, signum)
            saved = json.loads((root / "history.json").read_text())
            if mode == "blocked":
                self.assertIn("Timed out saving play history", stderr)
                self.assertNotIn("steam/42", saved["games"])
            else:
                self.assertTrue(saved["games"]["steam/42"]["favorite"])
                if mode == "export":
                    self.assertTrue(saved["games"]["steam/43"]["favorite"])

    def test_quit_during_export_drains_edits_accepted_after_the_cutoff(self):
        self.run_history("export")

    def test_termination_signal_drains_accepted_history(self):
        self.run_history("terminate", signal.SIGTERM)

    def test_termination_is_bounded_with_stalled_history_storage(self):
        self.run_history("blocked", signal.SIGTERM)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(child(Path(sys.argv[2]), sys.argv[3]))
    unittest.main()
