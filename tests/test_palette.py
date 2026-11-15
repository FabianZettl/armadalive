import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QThread, QUrl
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from armadalive.palette import Palette
from tests.common import app


class PaletteRequests(unittest.TestCase):
    def test_latest_request_replaces_pending_work_and_discards_stale_result(self):
        palette = Palette()
        self.assertTrue(callable(getattr(palette, "request", None)))
        owner = QThread.currentThread()
        started = threading.Event()
        release = threading.Event()
        reads = []
        published = []
        palette.changed.connect(lambda: published.append((palette.color, QThread.currentThread())))

        def read(url):
            reads.append((url, QThread.currentThread()))
            if url == "first":
                started.set()
                release.wait(2)
            return url

        with patch("armadalive.palette._read_accent", side_effect=read):
            try:
                palette.request("first", True)
                self.assertTrue(started.wait(1))
                self.assertEqual(palette.color, "")
                palette.request("skipped", True)
                palette.request("latest", True)
                self.assertEqual([url for url, _ in reads], ["first"])
            finally:
                release.set()
            self.wait_until(lambda: palette.color == "latest")

        self.assertEqual([url for url, _ in reads], ["first", "latest"])
        self.assertTrue(all(thread != owner for _, thread in reads))
        self.assertEqual(published, [("latest", owner)])

    def test_hidden_request_waits_until_resume_and_previous_color_is_retained(self):
        palette = Palette()
        self.assertTrue(callable(getattr(palette, "request", None)))
        with tempfile.TemporaryDirectory() as directory:
            red = self.make_image(directory, "red", 0xffff0000)
            green = self.make_image(directory, "green", 0xff00ff00)
            palette.request(red, True)
            self.wait_until(lambda: palette.color == "ff0000")
            palette.request(green, False)
            QTest.qWait(40)
            self.assertEqual(palette.color, "ff0000")
            palette.request(green, True)
            self.wait_until(lambda: palette.color == "00ff00")
            palette.request("file:///missing-artwork", True)
            self.wait_until(lambda: palette.color == "")

    @staticmethod
    def make_image(directory, name, color):
        path = Path(directory) / (name + ".png")
        image = QImage(64, 32, QImage.Format.Format_RGB32)
        image.fill(color)
        assert image.save(str(path))
        return QUrl.fromLocalFile(str(path)).toString()

    def wait_until(self, predicate):
        for _ in range(100):
            if predicate():
                return
            QTest.qWait(10)
        self.assertTrue(predicate())
