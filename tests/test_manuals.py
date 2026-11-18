import os, tempfile, threading, time, unittest
from unittest import mock

from PySide6.QtCore import QUrl

from tests.common import app, wait_for
from armadalive import manuals

try:
    import pymupdf  # noqa: F401
except ImportError:
    pymupdf = None


class ManualRequests(unittest.TestCase):
    def test_pause_keeps_pages_and_resume_deduplicates_cached_pages(self):
        started, release, first_finished = threading.Event(), threading.Event(), threading.Event()
        attempts = []

        def render(path, out, on_page, cancelled):
            attempts.append(cancelled)
            on_page("/one.png")
            if len(attempts) == 1:
                started.set()
                release.wait(1)
                on_page("/stale.png")
                first_finished.set()
                raise ValueError("cancelled render")
            on_page("/two.png")

        def wait_until(condition):
            deadline = time.monotonic() + 1
            while not condition() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            self.assertTrue(condition())

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(manuals, "render", render):
            path = os.path.join(directory, "manual.pdf")
            open(path, "wb").close()
            viewer = manuals.Manuals()
            viewer.load(QUrl.fromLocalFile(path).toString())
            self.assertTrue(started.wait(1))
            wait_until(lambda: bool(viewer.pages))
            try:
                viewer.setActive(False)
                self.assertTrue(attempts[0].is_set())
            finally:
                release.set()
            self.assertTrue(first_finished.wait(1))
            app.processEvents()
            self.assertEqual(viewer.pages, ["file:///one.png"])
            self.assertEqual(viewer.error, "")
            self.assertEqual(len(attempts), 1)
            viewer.setActive(True)
            wait_until(lambda: len(viewer.pages) >= 2)
            self.assertEqual(viewer.pages, ["file:///one.png", "file:///two.png"])
            self.assertEqual(viewer.model.stringList(), viewer.pages)

    def test_resuming_a_replaced_file_replaces_cached_page_versions(self):
        release = threading.Event()
        renders = []

        def render(path, out, on_page, cancelled):
            renders.append(QUrl.fromLocalFile(os.path.join(out, "p000.png")).toString())
            on_page(os.path.join(out, "p000.png"))
            if len(renders) == 1:
                release.wait(1)

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(manuals, "render", render):
            path = os.path.join(directory, "manual.pdf")
            open(path, "wb").close()
            viewer = manuals.Manuals()
            viewer.load(QUrl.fromLocalFile(path).toString())
            try:
                wait_for(lambda: bool(viewer.pages))
                viewer.setActive(False)
                with open(path, "wb") as file:
                    file.write(b"replaced file")
                viewer.setActive(True)
            finally:
                release.set()
            wait_for(lambda: len(renders) == 2 and renders[1] in viewer.pages)
            self.assertNotEqual(renders[0], renders[1])
            self.assertEqual(viewer.pages, [renders[1]])

    def test_duplicate_and_superseded_requests_do_not_queue_render_jobs(self):
        started, release = threading.Event(), threading.Event()
        rendered = []

        def render(path, out, on_page, cancelled=None):
            rendered.append(os.path.basename(path))
            if path.endswith("old.pdf"):
                started.set()
                release.wait(1)
                if cancelled is not None and cancelled.is_set():
                    return
            on_page("/page.png")

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(manuals, "render", render):
            urls = []
            for name in ("old.pdf", "abandoned.pdf", "new.pdf"):
                path = os.path.join(directory, name)
                open(path, "wb").close()
                urls.append(QUrl.fromLocalFile(path).toString())
            viewer = manuals.Manuals()
            viewer.load(urls[0])
            self.assertTrue(started.wait(1))
            try:
                viewer.load(urls[1])
                viewer.load(urls[2])
                viewer.load(urls[2])
            finally:
                release.set()
            until = time.monotonic() + 0.5
            while time.monotonic() < until and not viewer.pages:
                app.processEvents()
                time.sleep(0.001)
            self.assertEqual(rendered, ["old.pdf", "new.pdf"])
            self.assertEqual(viewer.pages, ["file:///page.png"])

    def test_cancelled_source_cannot_publish_error_after_switch(self):
        started, release = threading.Event(), threading.Event()

        def render(path, out, on_page, *args):
            if path.endswith("old.pdf"):
                started.set()
                release.wait(1)
                raise ValueError("old manual is damaged")
            on_page("/new.png")

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(manuals, "render", render):
            for name in ("old.pdf", "new.pdf"):
                open(os.path.join(directory, name), "wb").close()
            viewer = manuals.Manuals()
            viewer.load(QUrl.fromLocalFile(os.path.join(directory, "old.pdf")).toString())
            self.assertTrue(started.wait(1))
            viewer.load(QUrl.fromLocalFile(os.path.join(directory, "new.pdf")).toString())
            release.set()
            until = time.monotonic() + 0.5
            while time.monotonic() < until and not viewer.pages:
                app.processEvents()
                time.sleep(0.001)
            self.assertEqual(viewer.pages, ["file:///new.png"])
            self.assertEqual(viewer.error, "")


    def test_live_error_and_page_reach_the_owner_thread(self):
        def render(path, out, on_page, *args):
            on_page("/good.png")
            raise ValueError("later page is damaged")

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(manuals, "render", render):
            path = os.path.join(directory, "damaged.pdf")
            open(path, "wb").close()
            viewer = manuals.Manuals()
            observations = []
            viewer.changed.connect(lambda: observations.append((threading.get_ident(), viewer.pages, viewer.error)))
            viewer.load(QUrl.fromLocalFile(path).toString())
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not viewer.error:
                app.processEvents()
                time.sleep(0.001)
            self.assertEqual(observations, [
                (threading.get_ident(), [], ""),
                (threading.get_ident(), ["file:///good.png"], ""),
                (threading.get_ident(), ["file:///good.png"], "badpdf"),
            ])


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
