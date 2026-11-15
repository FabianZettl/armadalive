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

from armadalive import history
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

    with mock.patch.object(history.persistence, "write_json",
                           gate_write(history.persistence.write_json, entered, release)):
        play_history = history.History(now, str(config))
        play_history.toggleFavorite("steam/42", "Game", "steam", "")
        return exec_child(app, mode, entered)


class Shutdown(unittest.TestCase):
    def run_history(self, mode):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stderr = run_child(self, "tests.test_history_shutdown", root, mode, signal.SIGTERM)
            saved = json.loads((root / "history.json").read_text())
            if mode == "blocked":
                self.assertIn("Timed out saving play history", stderr)
                self.assertNotIn("steam/42", saved["games"])
            else:
                self.assertTrue(saved["games"]["steam/42"]["favorite"])

    def test_termination_signal_drains_accepted_history(self):
        self.run_history("terminate")

    def test_termination_is_bounded_with_stalled_history_storage(self):
        self.run_history("blocked")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(child(Path(sys.argv[2]), sys.argv[3]))
    unittest.main()
