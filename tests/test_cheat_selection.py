"""Exercise selection feedback on a populated Qt Quick Cheats page."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class CheatSelection(unittest.TestCase):
    def test_tapping_a_cheat_updates_the_existing_card_both_ways(self):
        result = subprocess.run(
            [sys.executable, "-m", "tests.test_cheat_selection"],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True,
            text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def exercise():
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    from PySide6.QtCore import Property, QEvent, QObject, QPoint, QUrl, Signal, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    from armadalive import cheats

    class CurrentGame(QObject):
        changed = Signal()
        key = "snes/Game.V1"

        @Property("QVariant", notify=changed)
        def state(self):
            return {"key": self.key}

        @Slot(result="QVariant")
        def cheats(self):
            return [{"desc": "Infinite health", "code": "1234"}]

    def visual_children(item):
        for child in item.childItems():
            yield child
            yield from visual_children(child)

    app = QGuiApplication([])
    current = CurrentGame()
    backend = cheats.Cheats()
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("nowPlaying", current)
    engine.rootContext().setContextProperty("cheats", backend)
    component = QQmlComponent(engine)
    qml = Path(__file__).resolve().parents[1] / "armadalive" / "qml"
    component.setData(b"""
        import QtQuick
        Window {
            width: 400; height: 240; visible: true
            Cheats { objectName: "page"; anchors.fill: parent }
        }
    """, QUrl.fromLocalFile(str(qml / "CheatSelectionTest.qml")))
    assert component.isReady(), component.errorString()
    window = component.create()
    assert QTest.qWaitForWindowActive(window)
    page = window.findChild(QQuickItem, "page")
    card = next(item for item in visual_children(page) if item.inherits("QQuickRectangle"))
    border = QQmlExpression(engine.rootContext(), card, "border.width")
    assert border.evaluate()[0] == 1
    assert not backend.is_active(current.key, 0)
    with TemporaryDirectory() as directory, patch.object(cheats, "CONFIG", directory):
        target = Path(directory) / "config" / "Snes9x" / "Game.V1.opt"
        touch = QTest.touchEvent(window, QTest.createTouchDevice(), False)
        point = QPoint(100, 45)
        for width, active in [(2, True), (1, False)]:
            touch.press(0, point).commit()
            QTest.qWait(20)
            touch.release(0, point).commit()
            assert backend.is_active(current.key, 0) == active
            assert border.evaluate()[0] == width, border.evaluate()[0]
            assert f'cheat0_enable = "{str(active).lower()}"' in target.read_text()
        backend.toggle_cheat(current.key, 0)
        assert border.evaluate()[0] == 2
        current.key = "snes/Other Game"
        current.changed.emit()
        assert border.evaluate()[0] == 1
    assert backend.metaObject().indexOfSlot("is_active(QString,int)") >= 0
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    exercise()
