"""Render manual pages as pictures on systems without Qt's PDF viewer."""
import hashlib, os, tempfile, threading, weakref
from PySide6.QtCore import Property, QObject, QStringListModel, Qt, QUrl, Signal, Slot

CACHE = os.path.expanduser("~/.cache/armadalive/manuals")
ZOOM = 1.6   # pages are drawn a bit larger than the screen: sharp when read, and still small files


def render(path, out, on_page, cancelled=None):
    """Render missing pages, stopping between pages when the viewer changes manuals."""
    if cancelled is not None and cancelled.is_set():
        return
    import pymupdf

    os.makedirs(out, exist_ok=True)
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            if cancelled is not None and cancelled.is_set():
                return
            f = os.path.join(out, f"p{i:03d}.png")
            if not os.path.exists(f):
                with tempfile.NamedTemporaryFile(dir=out, suffix=".part", delete=False) as tmp:
                    part = tmp.name
                try:
                    page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM)).save(part, output="png")
                    os.replace(part, f)   # a half-written file is never shown
                finally:
                    if os.path.exists(part):
                        os.unlink(part)
            if cancelled is None or not cancelled.is_set():
                on_page(f)


class Manuals(QObject):
    changed = Signal()
    _page = Signal(int, str)
    _finished = Signal(int, str)

    def __init__(self):
        super().__init__()
        self._source, self._error = "", ""
        self._generation = 0
        self._presenting = True
        self._done = False
        self._active = None
        self._seen = set()
        self._rendered_folder = None
        self._model = QStringListModel(self)
        self._page.connect(self._add, Qt.ConnectionType.QueuedConnection)
        self._finished.connect(self._complete, Qt.ConnectionType.QueuedConnection)

    @Property("QVariant", notify=changed)
    def pages(self):
        return self._model.stringList()

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Slot(int, str)
    def _add(self, generation, f):
        if generation != self._generation:
            return
        folder = os.path.dirname(f)
        if self._rendered_folder is not None and folder != self._rendered_folder:
            self._seen.clear()
            self._model.setStringList([])
        self._rendered_folder = folder
        if f in self._seen:
            return
        self._seen.add(f)
        url = QUrl.fromLocalFile(f).toString()
        row = self._model.rowCount()
        self._model.insertRow(row)
        self._model.setData(self._model.index(row, 0), url)
        self.changed.emit()

    @Slot(int, str)
    def _complete(self, generation, error):
        self._active = None
        if generation != self._generation:
            self._start()
        else:
            self._done = True
            if error:
                self._error = error
                self.changed.emit()

    def _start(self):
        if not self._presenting or self._done or self._active is not None:
            return
        path = QUrl(self._source).toLocalFile()
        if not path:
            return

        generation = self._generation
        cancelled = self._active = threading.Event()
        owner = weakref.ref(self)

        def emit(signal, *args):
            if (viewer := owner()) is not None:
                try:
                    getattr(viewer, signal).emit(generation, *args)
                    return
                except RuntimeError:
                    pass  # The viewer was deleted before delivery.
            cancelled.set()

        def work():
            error = ""
            try:
                stat = os.stat(path)
                stamp = f"{path}:{stat.st_mtime_ns}:{stat.st_size}:{stat.st_dev}:{stat.st_ino}"
                out = os.path.join(CACHE, hashlib.sha1(stamp.encode()).hexdigest())
                render(path, out, lambda f: emit("_page", f), cancelled)
            except ImportError:
                error = "nopdf"
            except Exception:   # a damaged PDF: show the pages we got
                error = "badpdf"
            emit("_finished", error)
        threading.Thread(target=work, daemon=True).start()

    @Slot(bool)
    def setActive(self, active):
        if self._presenting == active:
            return
        self._presenting = active
        if active:
            self._start()
        elif self._active is not None:
            self._generation += 1
            self._active.set()

    @Slot(str)
    def load(self, url):
        if url == self._source:
            return
        self._generation += 1
        self._source, self._error = url, ""
        self._done = False
        self._rendered_folder = None
        self._seen.clear()
        self._model.setStringList([])
        if self._active is not None:
            self._active.set()
        self._start()
        self.changed.emit()
