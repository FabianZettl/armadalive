import glob, os, re, subprocess, sys, textwrap, unittest

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

    def test_every_file_compiles(self):
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

    def test_open_picker_populates_from_a_pending_scan_without_resetting_search(self):
        script = textwrap.dedent(r"""
            import sys, threading, time
            from tempfile import TemporaryDirectory
            from unittest import mock
            from PySide6.QtCore import QObject, QUrl, Slot
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtQml import QQmlComponent, QQmlEngine
            from PySide6.QtQuick import QQuickItem
            from armadalive import apps

            class Shell(QObject):
                @Slot(bool)
                def textFocus(self, active):
                    pass

            owner = threading.get_ident()
            started, release = threading.Event(), threading.Event()

            def desktop():
                assert threading.get_ident() != owner, "picker scan ran on the window thread"
                started.set()
                assert release.wait(3), "test never released the scan"
                return {"new-app": {"name": "New App", "iconName": ""}}

            def wait_for(predicate):
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    app.processEvents()
                    if predicate():
                        return
                    time.sleep(0.005)
                raise AssertionError("Picker did not display the catalog")

            app = QGuiApplication([])
            engine = QQmlEngine()
            shell = Shell()
            window_component = QQmlComponent(engine)
            window_component.setData(b"import QtQuick\nWindow { width: 620; height: 540; visible: true }", QUrl())
            window = window_component.create()
            with TemporaryDirectory() as directory, mock.patch.multiple(
                apps, CONFIG=directory + "/apps.json", _catalog=desktop, ICON_ROOTS=[]
            ), mock.patch.object(apps.esdelib, "systems", return_value={}), mock.patch.object(
                apps.steamlib, "games", return_value=[]
            ):
                backend = apps.Apps()
                engine.rootContext().setContextProperty("apps", backend)
                engine.rootContext().setContextProperty("shell", shell)
                component = QQmlComponent(engine, QUrl.fromLocalFile(sys.argv[1]))
                picker = component.createWithInitialProperties({"visible": False, "width": 620, "height": 540})
                assert isinstance(picker, QQuickItem), component.errors()
                picker.setParentItem(window.contentItem())
                try:
                    assert started.wait(1)
                    picker.setVisible(True)
                    app.processEvents()
                    assert backend.catalogLoading
                    assert picker.isVisible()
                    assert not any(item["id"] == "new-app" for item in picker.property("items").toVariant())
                    picker.setProperty("query", "new")
                finally:
                    release.set()
                wait_for(lambda: not backend.catalogLoading)
                assert picker.property("query") == "new"
                assert any(item["id"] == "new-app" for item in picker.property("items").toVariant())
                picker.deleteLater()
                window.deleteLater()
                app.processEvents()
        """)
        result = subprocess.run([sys.executable, "-c", script, QML + "/AppPicker.qml"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_now_playing_motion_and_marquee_rendering(self):
        # This suite uses QCoreApplication. The component needs a real offscreen window.
        script = textwrap.dedent(r"""
            import sys, tempfile
            from pathlib import Path
            from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
            from PySide6.QtGui import QGuiApplication, QImage
            from PySide6.QtQml import QQmlEngine, QQmlComponent
            from PySide6.QtQuick import QQuickItem
            from PySide6.QtTest import QTest
            from armadalive.artwork import VectorArtwork

            class Backend(QObject):
                changed = Signal()
                state = Property("QVariantMap", lambda self: self.value, notify=changed)
                slots = Property("QVariantList", lambda self: [], notify=changed)

                def __init__(self, value):
                    super().__init__()
                    self.value = value

                @Slot(str, result="QVariantList")
                def folderItems(self, folder):
                    return self.value.get("items", [])

            app = QGuiApplication([])
            engine = QQmlEngine()
            engine.addImageProvider("vectors", VectorArtwork())
            backends = {
                "ui": Backend({"animate": True}),
                "nowPlaying": Backend({"kind": "game", "title": "Test", "logo": "",
                                       "fanart": "", "manual": "", "hasCheats": False}),
                "apps": Backend({}),
            }
            for name, backend in backends.items():
                engine.rootContext().setContextProperty(name, backend)
            window = QQmlComponent(engine)
            window.setData(b"import QtQuick\nWindow { width: 620; height: 540; visible: true }", QUrl())
            root = window.create()
            component = QQmlComponent(engine, QUrl.fromLocalFile(sys.argv[1]))
            page = component.create()
            page.setParentItem(root.contentItem())
            page.setWidth(620)
            page.setHeight(540)
            QTest.qWait(200)
            before = page.property("breathe")
            assert before > 0, before
            assert page.setProperty("presentationActive", False)
            paused = page.property("breathe")
            QTest.qWait(200)
            assert page.property("breathe") == paused, page.property("breathe")
            assert page.setProperty("presentationActive", True)
            QTest.qWait(200)
            assert page.property("breathe") > 0, page.property("breathe")

            with tempfile.TemporaryDirectory() as directory:
                path = directory + "/logo.png"
                image = QImage(64, 32, QImage.Format.Format_RGB32)
                image.fill(0xffff0000)
                assert image.save(path)
                backends["nowPlaying"].value.update(logo=QUrl.fromLocalFile(path).toString())
                backends["nowPlaying"].changed.emit()
                for _ in range(50):
                    QTest.qWait(20)
                    images = [item for item in page.findChildren(QQuickItem)
                              if item.inherits("QQuickImage")
                              and item.property("source") == QUrl.fromLocalFile(path)]
                    if any(item.isVisible() and abs(item.width() - 96) < 0.01 for item in images):
                        break
                else:
                    raise AssertionError([(item.width(), item.height(), item.implicitWidth(), item.implicitHeight()) for item in images])
                assert all(item.property("asynchronous") for item in images)
                assert all(item.property("sourceSize").width() >= 96 for item in images)

                fanart_path = directory + "/fanart.png"
                fanart = QImage(8000, 100, QImage.Format.Format_RGB32)
                fanart.fill(0xff00ff00)
                assert fanart.save(fanart_path)
                fanart_url = QUrl.fromLocalFile(fanart_path)
                page.setProperty("presentationActive", False)
                backends["nowPlaying"].value.update(fanart=fanart_url.toString())
                backends["nowPlaying"].changed.emit()
                QTest.qWait(50)
                assert not any(item.inherits("QQuickImage") and item.property("source") == fanart_url
                               for item in page.findChildren(QQuickItem))
                page.setProperty("presentationActive", True)
                for _ in range(50):
                    QTest.qWait(20)
                    images = [item for item in page.findChildren(QQuickItem)
                              if item.inherits("QQuickImage") and item.property("source") == fanart_url]
                    if any(item.implicitWidth() > 0 for item in images):
                        break
                else:
                    raise AssertionError("Updated fanart was not loaded on resume")
                assert all(0 < item.implicitWidth() <= 1280 for item in images)

                def vector(name, width, height):
                    file = Path(directory) / name
                    file.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
                                    f'<rect width="{width}" height="{height}" fill="green"/></svg>')
                    return QUrl.fromLocalFile(str(file)).toString()

                for original_width, kind, width, height in [(64, "game", 96, 48), (64, "system", 372, 186),
                                                            (2000, "game", 446.4, 223.2), (2000, "system", 372, 186)]:
                    name = f"logo-{original_width}.svg"
                    backends["nowPlaying"].value.update(kind=kind, logo=vector(name, original_width, original_width // 2), fanart="")
                    backends["nowPlaying"].changed.emit()
                    for _ in range(50):
                        QTest.qWait(20)
                        logos = [item for item in page.findChildren(QQuickItem)
                                 if item.inherits("QQuickImage") and item.isVisible()
                                 and item.property("source").toString().endswith(name)]
                        if any(abs(item.width() - width) < 0.01 and abs(item.height() - height) < 0.01
                               and (kind != "system" or item.implicitWidth() >= width)
                               for item in logos):
                            break
                    else:
                        raise AssertionError((kind, [(item.width(), item.height()) for item in logos]))

                backends["nowPlaying"].value.update(kind="game", logo=vector("tall #ログ % logo.svg", 100, 8000),
                                                    fanart=vector("wide.svg", 8000, 100))
                backends["nowPlaying"].changed.emit()
                for _ in range(50):
                    QTest.qWait(20)
                    images = [item for item in page.findChildren(QQuickItem)
                              if item.inherits("QQuickImage") and item.isVisible()
                              and item.implicitHeight() > 0 and item.height() > 0]
                    logo = next((item for item in images
                                 if abs(item.width() / item.height() - 0.0125) < 0.001), None)
                    fanart = next((item for item in images
                                   if item.property("source").toString().endswith("wide.svg")), None)
                    if logo is not None and fanart is not None:
                        break
                else:
                    raise AssertionError(("Tall logo or wide fanart did not render",
                                          [(item.width(), item.height()) for item in images]))
                assert 0 < logo.implicitHeight() <= 768
                assert abs(logo.height() - 345.6) < 1
                assert abs(fanart.width() - 43200) < 1 and abs(fanart.height() - 540) < 1, (
                    fanart.width(), fanart.height())

                backends["apps"].value["items"] = [{
                    "id": "app", "name": "App", "icon": vector("portrait.svg", 100, 8000),
                    "cover": False,
                }]
                folder_component = QQmlComponent(engine, QUrl.fromLocalFile(
                    str(Path(sys.argv[1]).with_name("FolderView.qml"))))
                folder = folder_component.createWithInitialProperties({"folder": "test", "width": 620, "height": 540})
                folder.setParentItem(root.contentItem())
                grid = next(item for item in folder.findChildren(QQuickItem) if item.inherits("QQuickGridView"))
                for _ in range(50):
                    QTest.qWait(20)
                    content = grid.property("contentItem")
                    icons = [image for delegate in content.childItems() for box in delegate.childItems()
                             for container in box.childItems() for image in container.childItems()
                             if image.inherits("QQuickImage") and image.height() > 0]
                    if icons:
                        break
                else:
                    raise AssertionError("Tall folder icon was not rendered")
                icon = icons[0]
                assert 0 < icon.implicitHeight() <= 512
                assert abs(icon.width() / icon.height() - 0.0125) < 0.002
                folder.deleteLater()
            page.deleteLater()
            root.deleteLater()
            QTest.qWait(0)
        """)
        for scale in ("1", "2"):
            with self.subTest(screen_scale=scale):
                result = subprocess.run([sys.executable, "-c", script, QML + "/NowPlaying.qml"],
                                        env=dict(os.environ, QT_SCALE_FACTOR=scale),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_property_group_followed_by_a_semicolon(self):  # a recurring QML syntax trap in this project
        for f in glob.glob(QML + "/*.qml"):
            with open(f) as fh:
                text = fh.read()
            self.assertIsNone(re.search(r"font \{|\}; ", text), f)

    def test_now_playing_resumes_vector_marquee_without_a_source_binding_loop(self):
        # The offscreen window follows Main's page loader and selection routing.
        script = textwrap.dedent(r"""
            import sys, tempfile
            from pathlib import Path
            from PySide6.QtCore import QEventLoop, QTimer, QUrl
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtQml import QQmlEngine, QQmlComponent
            from PySide6.QtQuick import QQuickItem
            from armadalive.artwork import VectorArtwork

            def wait(milliseconds):
                loop = QEventLoop()
                QTimer.singleShot(milliseconds, loop.quit)
                loop.exec()

            def visible_artwork(page):
                return [item for item in page.findChildren(QQuickItem)
                        if item.inherits("QQuickImage") and item.isVisible()
                        and not item.property("source").isEmpty()]

            app = QGuiApplication([])
            engine = QQmlEngine()
            engine.addImageProvider("vectors", VectorArtwork())
            component = QQmlComponent(engine)
            component.setData(b'''
                import QtQuick
                Window {
                    id: win
                    width: 620
                    height: 540
                    visible: true
                    property bool blanked: false
                    readonly property bool presentationActive: visible && !blanked
                    property string page: "now"
                    property alias nowPage: loader.item
                    property var selectedGame: ({kind: "game", title: "", logo: "", fanart: "", manual: "", hasCheats: false})
                    onSelectedGameChanged: nowPlaying.selection()
                    QtObject {
                        id: nowPlaying
                        readonly property var state: win.selectedGame
                        signal selection()
                    }
                    QtObject { id: ui; readonly property var state: ({animate: true}) }
                    QtObject { id: apps; readonly property var slots: []; signal changed() }
                    Connections {
                        target: nowPlaying
                        function onSelection() { win.page = "now" }
                    }
                    Loader {
                        id: loader
                        anchors.fill: parent
                        source: win.page === "now" ? "NowPlaying.qml" : ""
                        onLoaded: item.presentationActive = Qt.binding(() => win.presentationActive)
                    }
                }
            ''', QUrl.fromLocalFile(sys.argv[1]))
            window = component.create()
            assert window is not None, component.errors()

            with tempfile.TemporaryDirectory() as directory:
                logos = [Path(directory) / name for name in ("first.svg", "last.svg")]
                for logo in logos:
                    logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200">'
                                    '<rect width="800" height="200" fill="green"/></svg>')

                # Resume once to populate the image cache, then repeat with the same artwork.
                for _ in range(3):
                    assert window.setProperty("page", "system")
                    assert window.property("nowPage") is None
                    assert window.setProperty("blanked", True)
                    for logo in logos:
                        assert window.setProperty("selectedGame", dict(
                            kind="game", title=logo.stem, logo=QUrl.fromLocalFile(str(logo)).toString(),
                            fanart="", manual="", hasCheats=False))
                    assert window.property("page") == "now"
                    page = window.property("nowPage")
                    assert page is not None and not page.property("presentationActive")
                    assert not visible_artwork(page)

                    assert window.setProperty("blanked", False)
                    for _ in range(100):
                        if any(item.property("source").toString().endswith("last.svg")
                               and item.implicitWidth() == 800 and item.implicitHeight() == 200
                               for item in visible_artwork(page)):
                            break
                        wait(20)
                    else:
                        raise AssertionError("The last selected marquee did not render at its natural size")
                window.deleteLater()
                wait(0)
        """)
        for scale in ("1", "2"):
            with self.subTest(screen_scale=scale):
                result = subprocess.run([sys.executable, "-c", script, QML + "/MarqueeTestWindow.qml"],
                                        env=dict(os.environ, QT_SCALE_FACTOR=scale),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotRegex(result.stderr, r'NowPlaying\.qml[^\n]*Binding loop detected for property "source"')


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
