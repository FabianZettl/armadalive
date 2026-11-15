import glob, os, re, subprocess, sys, unittest

from tests.common import app  # noqa: F401
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

QML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "armadalive", "qml")


class Qml(unittest.TestCase):
    def test_gameinfo_refreshes_only_while_presented(self):
        # A real page needs a graphical application; tests.common owns a core-only one.
        probe = r'''
import sys
from PySide6.QtCore import QEvent, QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow

class Selection(QObject):
    changed = Signal()
    current = dict(system="steam", path="", key="steam/10", title="First")

    @Property("QVariant", notify=changed)
    def state(self):
        return self.current

class Metadata(QObject):
    updated = Signal()
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.reads = []
        self.suspensions = 0

    @Slot(str, str, str, str, result="QVariant")
    def of(self, system, path, key, title):
        self.reads.append((key, title))
        return dict(name=title)

    @Slot()
    def suspend(self):
        self.suspensions += 1

app = QGuiApplication([])
engine = QQmlEngine()
selection, metadata = Selection(), Metadata()
engine.rootContext().setContextProperty("nowPlaying", selection)
engine.rootContext().setContextProperty("gameinfo", metadata)
engine.rootContext().setContextProperty("history", metadata)
component = QQmlComponent(engine, QUrl.fromLocalFile(sys.argv[1]))
assert component.isReady(), [e.toString() for e in component.errors()]
page = component.createWithInitialProperties({"presentationActive": False})
assert page is not None, [e.toString() for e in component.errors()]
window = QQuickWindow()
page.setParentItem(window.contentItem())
window.show()
app.processEvents()
assert metadata.reads == [], metadata.reads

page.setProperty("presentationActive", True)
assert metadata.reads[-1] == ("steam/10", "First"), metadata.reads
previous = page.property("d")
suspensions = metadata.suspensions
page.setProperty("presentationActive", False)
assert metadata.suspensions == suspensions + 1
metadata.reads.clear()
selection.current = dict(system="steam", path="", key="steam/20", title="Second")
selection.changed.emit()
metadata.changed.emit()
metadata.updated.emit()
assert metadata.reads == [], metadata.reads
assert page.property("d") == previous

page.setProperty("presentationActive", True)
assert metadata.reads == [("steam/20", "Second")], metadata.reads
assert page.property("d")["name"] == "Second"
page.setProperty("visible", False)
assert metadata.suspensions == suspensions + 2
metadata.reads.clear()
metadata.changed.emit()
metadata.updated.emit()
assert metadata.reads == [], metadata.reads
page.setProperty("visible", True)
assert metadata.reads == [("steam/20", "Second")], metadata.reads
metadata.reads.clear()
metadata.changed.emit()
metadata.updated.emit()
assert metadata.reads == [("steam/20", "Second")] * 2, metadata.reads
page.deleteLater()
app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
'''
        result = subprocess.run([sys.executable, "-c", probe, os.path.join(QML, "GameInfo.qml")],
                                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_file_loads(self):
        gui = QGuiApplication.instance() or QGuiApplication([])
        engine = QQmlApplicationEngine()
        bad = {}
        for f in sorted(glob.glob(QML + "/*.qml")):
            c = QQmlComponent(engine, QUrl.fromLocalFile(f))
            if c.status() != QQmlComponent.Status.Ready:
                errors = [e.toString().split("qml/")[-1] for e in c.errors()]
                # Qt's PDF module is optional (a pip-installed PySide6 has none): Manual.qml falls back to ManualImages.qml
                if os.path.basename(f) == "ManualPdf.qml" and all("Pdf" in e for e in errors):
                    continue
                bad[os.path.basename(f)] = errors
        self.assertEqual(bad, {})

    def test_no_property_group_followed_by_a_semicolon(self):  # a recurring QML syntax trap in this project
        for f in glob.glob(QML + "/*.qml"):
            with open(f) as fh:
                text = fh.read()
            self.assertIsNone(re.search(r"font \{|\}; ", text), f)


class Translations(unittest.TestCase):
    def test_every_text_has_a_german_version(self):
        with open(QML + "/Tr.qml") as fh:
            tr = fh.read()
        german = set(re.findall(r'"((?:[^"\\]|\\.)+)":\s*"', tr))
        used = set()
        for f in glob.glob(QML + "/*.qml"):
            if not f.endswith("Tr.qml"):
                with open(f) as fh:
                    used |= set(re.findall(r'Tr\.t\("((?:[^"\\]|\\.)+)"\)', fh.read()))
        # a few texts are identical in both languages and need no entry
        same = {"Cheats", "Apps", "System", "Tuning", "Auto", "Bluetooth", "Screenshot", "TEMP", "Updates", "Version", "Underclock", "Update", "FPS"}
        self.assertEqual(sorted(t for t in used - german if t not in same), [])


if __name__ == "__main__":
    unittest.main()
