import os, tempfile, unittest

from tests.common import app  # noqa: F401
from armadalive import manuals

try:
    import pymupdf  # noqa: F401
except ImportError:
    pymupdf = None


@unittest.skipIf(pymupdf is None, "PyMuPDF is not installed")
class Render(unittest.TestCase):
    def pdf(self, path, pages):
        doc = pymupdf.open()
        for i in range(pages):
            doc.new_page(width=280, height=400).insert_text((40, 60), f"page {i}")
        doc.save(path)

    def test_every_page_becomes_a_picture_and_is_reused_the_second_time(self):
        with tempfile.TemporaryDirectory() as d:
            src, out, seen = os.path.join(d, "m.pdf"), os.path.join(d, "out"), []
            self.pdf(src, 3)
            manuals.render(src, out, seen.append)
            self.assertEqual([os.path.basename(f) for f in seen], ["p000.png", "p001.png", "p002.png"])
            self.assertTrue(all(os.path.getsize(f) > 0 for f in seen))
            stamp = os.path.getmtime(seen[0])
            manuals.render(src, out, lambda f: None)
            self.assertEqual(os.path.getmtime(seen[0]), stamp)     # not drawn again
            self.assertFalse([f for f in os.listdir(out) if f.endswith(".part")])

    def test_a_broken_pdf_raises_instead_of_hanging(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "bad.pdf")
            open(src, "wb").write(b"not a pdf")
            with self.assertRaises(Exception):
                manuals.render(src, os.path.join(d, "out"), lambda f: None)


if __name__ == "__main__":
    unittest.main()
