"""Manual pages as pictures, for systems whose Qt has no PDF module (Qt's own viewer is used where it exists).
PyMuPDF renders the pages in a background thread, one picture at a time, so the first page shows at once."""
import hashlib, os, threading
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

CACHE = os.path.expanduser("~/.cache/armadalive/manuals")
ZOOM = 1.6   # pages are drawn a bit larger than the screen: sharp when read, and still small files


def render(path, out, on_page):
    """Draw every page of a PDF to out/pNNN.png (pages already there are kept); on_page(file) after each one."""
    import pymupdf
    os.makedirs(out, exist_ok=True)
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            f = os.path.join(out, f"p{i:03d}.png")
            if not os.path.exists(f):
                page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM)).save(f + ".part", output="png")
                os.replace(f + ".part", f)    # a half-written file is never shown
            on_page(f)


class Manuals(QObject):
    changed = Signal()
    _page = Signal(str, str)    # from the worker thread: the manual it belongs to, and the picture

    def __init__(self):
        super().__init__()
        self._pages, self._source, self._error = [], "", ""
        self._page.connect(self._add)

    @Property("QVariant", notify=changed)
    def pages(self):
        return self._pages

    @Property(str, notify=changed)
    def error(self):
        return self._error

    def _add(self, source, f):
        if source == self._source:     # an older manual that is still being drawn must not leak into the new one
            self._pages = self._pages + [QUrl.fromLocalFile(f).toString()]
            self.changed.emit()

    @Slot(str)
    def load(self, url):
        path = QUrl(url).toLocalFile()
        if url == self._source:
            return
        self._source, self._pages, self._error = url, [], ""
        self.changed.emit()
        if not path:
            return
        out = os.path.join(CACHE, hashlib.sha1(f"{path}:{os.path.getmtime(path) if os.path.exists(path) else 0}".encode()).hexdigest())

        def work():
            try:
                render(path, out, lambda f: self._page.emit(url, f))
            except ImportError:
                self._error = "nopdf"
            except Exception:     # a damaged PDF: show what there is
                self._error = "badpdf"
            self.changed.emit()
        threading.Thread(target=work, daemon=True).start()
