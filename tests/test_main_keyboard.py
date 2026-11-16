"""Exercise navigation, modal input and presentation in the complete Main window."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class MainKeyboard(unittest.TestCase):
    def test_reveals_navigation_and_contains_and_restores_password_focus(self):
        self.exercise_cases("chrome", "password", "covered")

    def test_touch_navigation_and_blanking(self):
        self.exercise_cases("touch")

    def test_presentation_follows_visibility_and_blanking(self):
        self.exercise_cases("presentation")

    def exercise_cases(self, *cases):
        for case in cases:
            with self.subTest(case=case):
                result = subprocess.run(
                    [sys.executable, "-m", "tests.test_main_keyboard", case],
                    env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True,
                    text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def exercise(case):
    import time

    from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Property, Qt, QUrl, Signal, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest

    class Backend(QObject):
        changed = Signal()
        selection = Signal()
        seen = Signal()
        begun = Signal()
        switched = Signal()
        pressed = Signal()
        released = Signal()
        longPressed = Signal()
        notice = Signal(str, str)
        alert = Signal(int, str)
        catalogChanged = Signal()

        def __init__(self, value):
            super().__init__()
            self.value = value
            self.commands = []
            self.requests = []
            self.watched = False

        @Property("QVariantMap", notify=changed)
        def state(self):
            return self.value

        @Property("QVariantMap", constant=True)
        def pending(self):
            return {}

        @Property("QVariantMap", constant=True)
        def data(self):
            return {}

        @Property("QVariantList", constant=True)
        def checks(self):
            return []

        @Property("QVariantList", constant=True)
        def slots(self):
            return []

        @Property("QVariantMap", constant=True)
        def stats(self):
            return {"battery": 50, "charging": False, "eta": 0}

        @Property(str, constant=True)
        def error(self):
            return ""

        @Property(bool, constant=True)
        def trackball(self):
            return True

        @Property(str, constant=True)
        def color(self):
            return ""

        @Slot(str)
        def applyFont(self, _):
            pass

        @Slot(str, bool)
        def request(self, source, active):
            self.requests.append((source, active))

        @Slot(QObject)
        def watch(self, _):
            self.watched = True

        @Slot(str, str)
        def run(self, action, password):
            self.commands.append((action, password))

    app = QGuiApplication(["armadalive", "--windowed"])
    engine = QQmlEngine()
    backends = {
        "ui": Backend({"onboarded": True, "lang": "en", "apps": False, "dim": False, "theme": "follow"}),
        "nowPlaying": Backend({"kind": "game", "title": "Test", "manual": "", "logo": "", "fanart": ""}),
        "closer": Backend({"phase": ""}),
        "admin": Backend({"message": ""}),
        "ludo": Backend({"phase": "", "title": ""}),
    }
    for name in ("activity", "apps", "artwork", "ayn", "battery", "controls", "emulatorControl", "health",
                 "media", "onboarding", "rules", "settings", "steamShortcuts", "system", "tasks",
                 "thermal", "trackpad", "updater"):
        backends[name] = Backend({})
    for name, backend in backends.items():
        engine.rootContext().setContextProperty(name, backend)
    from armadalive.controls_layout import ControlsLayout

    layout = ControlsLayout()
    engine.rootContext().setContextProperty("layout", layout)
    file = Path(__file__).resolve().parents[1] / "armadalive" / "qml" / "Main.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(file)))
    assert component.isReady(), component.errorString()
    window = component.create()
    assert QTest.qWaitForWindowActive(window)

    def wait_for(predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        assert predicate(), (case, window.property("page"), focus_label())

    def focus_label():
        item = window.activeFocusItem()
        return item.property("label") if item is not None else None

    def navigate_to(label):
        for _ in range(12):
            if focus_label() == label:
                return window.activeFocusItem()
            QTest.keyClick(window, Qt.Key.Key_Tab)
        raise AssertionError(f"Tab could not reach {label}")

    def items(parent):
        for child in parent.childItems():
            yield child
            yield from items(child)

    def on_screen(item):
        y = item.mapToScene(QPointF()).y()
        return -0.01 <= y and y + item.height() <= window.height() + 0.01

    def center(item):
        return item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()

    def tap(finger, point):
        touch = QTest.touchEvent(window, finger, False)
        touch.press(0, point).commit()
        QTest.qWait(20)
        touch.release(0, point).commit()
        QTest.qWait(20)

    def swipe(finger, start, end):
        touch = QTest.touchEvent(window, finger, False)
        touch.press(0, start).commit()
        for step in range(1, 5):
            touch.move(0, start + (end - start) * step / 4).commit()
            QTest.qWait(20)
        touch.release(0, end).commit()

    controls = next(item for item in items(window.contentItem()) if item.property("label") == "Controls")
    if case == "presentation":
        loaded = next(item for item in items(window.contentItem()) if item.property("presentationActive") is True)
        artwork = backends["artwork"]
        assert backends["activity"].watched
        assert artwork.requests[-1] == ("", True)
        window.setProperty("blanked", True)
        assert not loaded.property("presentationActive")
        assert artwork.requests[-1] == ("", False)
        window.setProperty("blanked", False)
        assert loaded.property("presentationActive")
        assert artwork.requests[-1] == ("", True)
        window.showMinimized()
        assert not loaded.property("presentationActive")
        assert artwork.requests[-1] == ("", False)
        window.showNormal()
        assert loaded.property("presentationActive")
        assert artwork.requests[-1] == ("", True)
    elif case == "touch":
        finger = QTest.createTouchDevice()
        window.setProperty("peek", False)
        wait_for(lambda: not on_screen(controls))
        swipe(finger, QPoint(300, 320), QPoint(300, 190))
        wait_for(lambda: window.property("chrome") and on_screen(controls))
        assert focus_label() != "Controls"
        swipe(finger, QPoint(300, 190), QPoint(300, 320))
        wait_for(lambda: not window.property("chrome") and not on_screen(controls))
        swipe(finger, QPoint(300, 320), QPoint(300, 190))
        wait_for(lambda: window.property("chrome") and on_screen(controls))
        point = center(controls)
        tap(finger, point)
        assert window.property("page") == "controls"

        window.setProperty("blanked", True)
        QTest.qWait(50)
        touch = QTest.touchEvent(window, finger, False)
        touch.press(0, point).commit()
        QTest.qWait(app.styleHints().mousePressAndHoldInterval() + 50)
        touch.release(0, point).commit()
        assert not window.property("blanked") and window.property("page") == "controls"
    elif case == "chrome":
        window.setProperty("peek", False)
        wait_for(lambda: not on_screen(controls))
        assert not window.property("chrome")
        assert not controls.isEnabled(), "Offscreen navigation remained enabled"
        QTest.keyClick(window, Qt.Key.Key_Tab)
        wait_for(lambda: window.property("chrome") and focus_label() == "Game"
                 and on_screen(window.activeFocusItem()))
        QTest.qWait(3100)
        assert window.property("chrome") and focus_label() == "Game"
        window.setProperty("peek", False)
        wait_for(lambda: not on_screen(controls))
        QTest.keyClick(window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        wait_for(lambda: window.property("chrome") and focus_label() == "Game"
                 and on_screen(window.activeFocusItem()))
        assert on_screen(navigate_to("Controls"))
        QTest.keyClick(window, Qt.Key.Key_Return)
        assert window.property("page") == "controls"
    else:
        window.setProperty("peek", True)
        wait_for(lambda: controls.isEnabled() and on_screen(controls))
        assert navigate_to("Controls") == controls
        if case == "password":
            window.setProperty("askDemo", "helper")
            assert focus_label() == "Cancel", focus_label()
            assert not controls.isEnabled()
            for key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Tab):
                QTest.keyClick(window, key)
                assert focus_label() == "Cancel", focus_label()
            QTest.keyClick(window, Qt.Key.Key_Return)
            assert window.property("page") == "now"
            assert window.activeFocusItem() == controls
            assert backends["admin"].commands == []

            window.setProperty("askDemo", "")
            window.setProperty("askDemo", "helper")
            assert focus_label() == "Cancel"
            finger = QTest.createTouchDevice()
            swipe(finger, QPoint(390, 230), QPoint(240, 230))
            assert window.property("page") == "now", "Swipe escaped the password overlay"
            tap(finger, QPoint(31, 300))
            QTest.keyClick(window, Qt.Key.Key_Tab)
            assert focus_label() == "Confirm", focus_label()
            QTest.keyClick(window, Qt.Key.Key_Backtab)
            assert focus_label() == "Cancel", focus_label()
            QTest.keyClick(window, Qt.Key.Key_Tab)
            QTest.keyClick(window, Qt.Key.Key_Return)
            assert backends["admin"].commands == [("helper", "1")]
            assert window.activeFocusItem() == controls
        else:
            window.setProperty("blanked", True)
            assert not controls.isEnabled()
            QTest.keyClick(window, Qt.Key.Key_Tab)
            QTest.keyClick(window, Qt.Key.Key_Return)
            assert window.property("blanked") and window.property("page") == "now"

            window.setProperty("askDemo", "helper")
            QTest.keyClick(window, Qt.Key.Key_Tab)
            QTest.keyClick(window, Qt.Key.Key_Return)
            assert window.property("passwordOpen") and focus_label() not in ("Cancel", "Confirm")
            assert backends["admin"].commands == []
            window.setProperty("blanked", False)
            assert focus_label() == "Cancel"
            QTest.keyClick(window, Qt.Key.Key_Return)

            backends["ui"].value["onboarded"] = False
            backends["ui"].changed.emit()
            assert not controls.isEnabled()
            onboarding = window.findChild(QQuickItem, "onboarding")
            assert onboarding.isVisible() and onboarding.isEnabled()
            QTest.keyClick(window, Qt.Key.Key_Tab)
            assert focus_label() != "Controls"
            assert window.property("page") == "now"
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    exercise(sys.argv[1])
