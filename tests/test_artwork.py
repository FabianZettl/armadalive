import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QSize, QUrl

from armadalive.artwork import VectorArtwork
from tests.common import app  # noqa: F401


class VectorImages(unittest.TestCase):
    def test_original_dimensions_and_bounded_raster_are_reported_separately(self):
        provider = VectorArtwork()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "art.svg"
            for width, height in [(64, 32), (8000, 100), (100, 8000)]:
                with self.subTest(width=width, height=height):
                    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
                                    f'<rect width="{width}" height="{height}" fill="green"/></svg>')
                    original_size = QSize()
                    image = provider.requestImage(quote(QUrl.fromLocalFile(str(path)).toString(), safe=""),
                                                  original_size, QSize(1024, 768))
                    self.assertFalse(image.isNull())
                    self.assertEqual(original_size, QSize(width, height))
                    self.assertLessEqual(image.width(), 1024)
                    self.assertLessEqual(image.height(), 768)
