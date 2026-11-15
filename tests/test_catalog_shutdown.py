"""Exercise a layout write during shutdown of this test's own process."""
import json
import signal
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from armadalive import apps
from tests.shutdown_process import child_app, exec_child, gate_write, run_child


def child(directory, mode):
    entered, release = threading.Event(), threading.Event()
    app = child_app(directory, mode, release)
    config = directory / "apps.json"
    config.write_text(json.dumps({"slots": ["folder:1"], "folders": {"1": {"name": "Old", "items": []}}, "next": 2}))

    with mock.patch.object(apps, "CONFIG", str(config)), \
            mock.patch.object(apps.Apps, "refreshCatalog"), \
            mock.patch.object(apps, "_write_layout", gate_write(apps._write_layout, entered, release)):
        catalog = apps.Apps()
        catalog.renameFolder("folder:1", "Accepted rename")
        return exec_child(app, mode, entered)


class Shutdown(unittest.TestCase):
    def run_layout(self, mode, signum=None, *, button_signals=False):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stderr = run_child(self, "tests.test_catalog_shutdown", root, mode, signum, button_signals=button_signals)
            saved = json.loads((root / "apps.json").read_text())
            name = saved["folders"]["1"]["name"]
            if mode == "blocked":
                self.assertIn("Timed out saving app layout", stderr)
                self.assertEqual(name, "Old")
            else:
                self.assertEqual(name, "Accepted rename")

    def test_normal_qt_quit_drains_accepted_layout(self):
        self.run_layout("quit")

    def test_termination_signal_drains_accepted_layout(self):
        self.run_layout("terminate", signal.SIGTERM)

    def test_interrupt_signal_drains_accepted_layout(self):
        self.run_layout("terminate", signal.SIGINT)

    def test_user_signals_still_press_and_release_the_button(self):
        self.run_layout("terminate", signal.SIGTERM, button_signals=True)

    def test_termination_is_bounded_with_stalled_layout_storage(self):
        self.run_layout("blocked", signal.SIGTERM)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(child(Path(sys.argv[2]), sys.argv[3]))
    unittest.main()
