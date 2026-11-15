"""Exercise the missing-renderer result through the actual manual viewer."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

from PySide6.QtCore import QUrl
from tests.common import app
from armadalive import manuals


class ManualAvailability(unittest.TestCase):
    def test_missing_pymupdf_reports_unavailable_without_pages(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules, {"pymupdf": None}):
            path = os.path.join(directory, "manual.pdf")
            with open(path, "wb"):
                pass
            viewer = manuals.Manuals()
            viewer.load(QUrl.fromLocalFile(path).toString())
            deadline = time.monotonic() + 3
            while not viewer.error and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            self.assertEqual(viewer.error, "nopdf")
            self.assertEqual(viewer.pages, [])


if __name__ == "__main__":
    unittest.main()
