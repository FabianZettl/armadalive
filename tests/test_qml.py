import glob, os, re, subprocess, sys, textwrap, unittest

from tests.common import app  # noqa: F401
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

QML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "armadalive", "qml")


class Qml(unittest.TestCase):
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
