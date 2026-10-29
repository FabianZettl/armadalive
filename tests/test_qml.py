import glob, os, re, unittest

from tests.common import app  # noqa: F401
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

QML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "armadalive", "qml")


class Qml(unittest.TestCase):
    def test_every_file_loads(self):
        gui = QGuiApplication.instance() or QGuiApplication([])
        engine = QQmlApplicationEngine()
        bad = {}
        for f in sorted(glob.glob(QML + "/*.qml")):
            c = QQmlComponent(engine, QUrl.fromLocalFile(f))
            if c.status() != QQmlComponent.Status.Ready:
                bad[os.path.basename(f)] = [e.toString().split("qml/")[-1] for e in c.errors()]
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
