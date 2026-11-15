"""Verify emulator control targets and the virtual keyboard with isolated fixtures."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from armadalive import emusettings, trackpad
from armadalive.emulator_control import EmulatorControl


@contextmanager
def input_protocol(create_error=False, fail_event=None):
    calls = []
    event_count = 0

    def open_device(path, flags):
        calls.append(("open", path))
        return 0  # descriptor zero is valid

    def ioctl(fd, code, value=None):
        calls.append(("ioctl", fd, code, value))
        if create_error and code == trackpad.UI_DEV_CREATE:
            raise OSError("cannot create keyboard")

    def write(fd, data):
        nonlocal event_count
        if len(data) == trackpad.EVENT.size:
            event_count += 1
            if event_count == fail_event:
                calls.append(("short_write", fd, data))
                return len(data) - 1
        calls.append(("write", fd, data))
        return len(data)

    with patch.object(trackpad.os, "open", open_device), patch.object(trackpad.fcntl, "ioctl", ioctl), \
         patch.object(trackpad.os, "write", write), patch.object(trackpad.os, "close", lambda fd: calls.append(("close", fd))):
        yield calls


def input_events(calls):
    return [trackpad.EVENT.unpack(call[2])[2:] for call in calls
            if call[0] == "write" and len(call[2]) == trackpad.EVENT.size]


def wait_for(predicate):
    from tests.common import app

    deadline = monotonic() + 3
    while monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        sleep(0.005)
    raise AssertionError("The emulator event did not arrive")


class PollingKeyboard:
    """Read one batch of pending events and sample the resulting key state."""
    def __init__(self, calls):
        self.calls = calls
        self.next_event = 0
        self.pressed = set()

    def poll(self):
        events = input_events(self.calls)
        for kind, key, value in events[self.next_event:]:
            if kind == trackpad.EV_KEY:
                if value:
                    self.pressed.add(key)
                else:
                    self.pressed.discard(key)
        self.next_event = len(events)
        return self.pressed.copy()


class EmulatorControlTests(unittest.TestCase):
    def test_polling_clients_observe_down_then_up_and_only_one_shortcut_is_admitted(self):
        with input_protocol() as calls:
            control = EmulatorControl()
            try:
                notices = []
                control.notice.connect(lambda message, level: notices.append((message, level)))
                keyboard = PollingKeyboard(calls)
                control.execute("psx", "screenshot", "/roms/Example.chd")
                self.assertEqual(input_events(calls), [], "Events preceded keyboard discovery")
                self.assertEqual(notices, [])

                control.execute("psx", "load_state", "/roms/Example.chd")
                self.assertEqual([level for _, level in notices], ["warn"])
                wait_for(lambda: bool(input_events(calls)))
                self.assertEqual(keyboard.poll(), {66})
                self.assertEqual([level for _, level in notices], ["warn"])

                wait_for(lambda: len(notices) == 2)
                self.assertEqual(keyboard.poll(), set())
                self.assertEqual([level for _, level in notices], ["warn", "info"])
                self.assertEqual(input_events(calls), [(1, 66, 1), (0, 0, 0), (1, 66, 0), (0, 0, 0)])
            finally:
                control._close_keyboard()

    def test_write_failure_releases_before_destroy_and_recovery_waits_for_discovery(self):
        with input_protocol(fail_event=2) as calls:
            control = EmulatorControl()
            try:
                notices = []
                control.notice.connect(lambda message, level: notices.append((message, level)))
                control.execute("psx", "screenshot", "/roms/Example.chd")
                wait_for(lambda: bool(notices))
                self.assertEqual([level for _, level in notices], ["warn"])
                self.assertEqual(input_events(calls), [(1, 66, 1), (1, 66, 0), (0, 0, 0)])
                self.assertEqual(calls[-2:], [("ioctl", 0, trackpad.UI_DEV_DESTROY, None), ("close", 0)])

                keyboard = PollingKeyboard(calls)
                self.assertEqual(keyboard.poll(), set())
                before = input_events(calls)
                control.execute("gc", "screenshot", "/roms/Example.rvz")
                self.assertEqual(input_events(calls), before, "Events preceded rediscovery")
                self.assertEqual([level for _, level in notices], ["warn"])
                wait_for(lambda: len(input_events(calls)) > len(before))
                self.assertEqual(keyboard.poll(), {67})
                wait_for(lambda: len(notices) == 2)
                self.assertEqual(keyboard.poll(), set())
                self.assertEqual([level for _, level in notices], ["warn", "info"])
            finally:
                control._close_keyboard()

    def test_default_hotkeys_use_a_created_keyboard_and_release_it(self):
        with input_protocol() as calls:
            control = EmulatorControl()
            try:
                notices = []
                control.notice.connect(lambda message, level: notices.append((message, level)))
                for system, action in [
                    ("psx", "screenshot"), ("ps1", "save_state"), ("snes", "load_state"),
                    ("nes", "toggle_cheats"), ("n64", "fast_forward"),
                    ("gc", "screenshot"), ("gamecube", "screenshot"), ("wii", "screenshot"),
                ]:
                    expected_notices = len(notices) + 1
                    control.execute(system, action, "/roms/Example.rom")
                    wait_for(lambda: len(notices) == expected_notices)

                keys = [66, 60, 62, 22, 57, 67, 67, 67]  # F8, F2, F4, U, Space, F9
                self.assertEqual(calls[0], ("open", "/dev/uinput"))
                self.assertEqual(calls[1], ("ioctl", 0, trackpad.UI_SET_EVBIT, trackpad.EV_KEY))
                self.assertEqual(
                    {call[3] for call in calls if call[:3] == ("ioctl", 0, trackpad.UI_SET_KEYBIT)},
                    set(keys),
                )
                creation = calls.index(("ioctl", 0, trackpad.UI_DEV_CREATE, None))
                self.assertEqual(calls[creation - 1][:2], ("write", 0))
                self.assertTrue(calls[creation - 1][2].startswith(b"ArmadaLive Emulator Keys\0"))
                events = [trackpad.EVENT.unpack(call[2])[2:] for call in calls[creation + 1:]]
                expected = []
                for key in keys:
                    expected.extend([(1, key, 1), (0, 0, 0), (1, key, 0), (0, 0, 0)])
                self.assertEqual(events, expected)
                self.assertEqual([level for _, level in notices], ["info"] * len(keys))
                self.assertTrue(all("shortcut sent" in message.lower() for message, _ in notices))

                control._close_keyboard()
                control._close_keyboard()
                self.assertEqual(calls[-2:], [("ioctl", 0, trackpad.UI_DEV_DESTROY, None), ("close", 0)])
                self.assertEqual(calls.count(("close", 0)), 1)
            finally:
                control._close_keyboard()

    def test_keyboard_setup_failure_closes_and_warns_without_sending_keys(self):
        from tests.common import app  # noqa: F401

        with input_protocol(create_error=True) as calls:
            control = EmulatorControl()
            notices = []
            control.notice.connect(lambda message, level: notices.append((message, level)))
            control.execute("psx", "screenshot", "/roms/Example.chd")
            self.assertEqual(calls[-1], ("close", 0))
            self.assertTrue(all(len(call[2]) > trackpad.EVENT.size for call in calls if call[0] == "write"))
            self.assertEqual(calls.count(("close", 0)), calls.count(("open", "/dev/uinput")))
            self.assertEqual(len(notices), 1)
            self.assertEqual(notices[0][1], "warn")

    @contextmanager
    def config_fixture(self, system, original):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "synced.ini"
            target.write_bytes(original)
            link = home / "config.ini"
            link.symlink_to(target)
            _, section, option, fmt = emusettings.SPECS[system]
            with patch.object(trackpad.os, "open", side_effect=PermissionError):
                control = EmulatorControl()
            notices = []
            control.notice.connect(lambda message, level: notices.append((message, level)))
            with patch.dict(os.environ, HOME=directory), patch.dict(
                emusettings.SPECS, {system: (str(link), section, option, fmt)},
            ):
                yield control, notices, home, target, link

    def test_dolphin_updates_only_supported_options_in_existing_config(self):
        original = (b"# Graphics settings\r\n[Settings]\r\n"
                    b"InternalResolution  = 2\r\nwideScreenHack = False\r\nAspectRatio = 1\r\n"
                    b"[Other]\r\nAspectRatio = keep\r\nInternalResolution = keep")
        with self.config_fixture("gc", original) as (control, notices, home, target, link):
            guessed = home / ".config/dolphin-emu/GameSettings/FRIEND.ini"
            guessed.parent.mkdir(parents=True)
            guessed.write_bytes(original)
            for system, action in [
                ("gc", "increase_resolution"), ("gamecube", "toggle_widescreen"), ("gc", "toggle_aspect"),
            ]:
                control.execute(system, action, "/roms/gc/Friendly Name.rvz")
            self.assertEqual(target.read_bytes(), original.replace(b"  = 2", b"  = 3")
                             .replace(b"= False", b"= True").replace(b"AspectRatio = 1", b"AspectRatio = 2"))
            self.assertEqual(guessed.read_bytes(), original)
            self.assertTrue(link.is_symlink())
            self.assertEqual([level for _, level in notices], ["info"] * 3)
            self.assertTrue(all("saved on disk" in message for message, _ in notices))

    def test_dolphin_uses_effective_case_insensitive_names_and_preserves_their_spelling(self):
        original = (b"\xef\xbb\xbf[sEtTiNgS] # manually named\r\n"
                    b"  internalresolution  = \"4\"\r\n"
                    b"[Other]\r\nInternalResolution = keep\r\n")
        with self.config_fixture("gc", original) as (control, notices, _, target, link):
            target.chmod(0o640)
            self.assertEqual(emusettings.read("gc"), "4")
            control.execute("gc", "increase_resolution", "/roms/gc/Example.rvz")
            self.assertEqual(target.read_bytes(), original.replace(b'"4"', b'"5"'))
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)
            self.assertEqual([level for _, level in notices], ["info"])

    def test_dolphin_refuses_ambiguous_or_ineffective_assignments_without_writes(self):
        cases = [
            b"[Settings]\nInternalResolution = 2\ninternalRESOLUTION = 4\n",
            b"[Settings]\nInternalResolution = 2\n[SETTINGS] # duplicate\n",
            b"  [Settings]\nInternalResolution = 2\n",
            b"[Settings]\nInternalResolution = 2 # suffix is part of the value\n",
            b"[Settings]\nInternalResolution = 2 ; suffix is part of the value\n",
        ]
        for original in cases:
            with self.subTest(original=original), self.config_fixture("gc", original) as fixture:
                control, notices, _, target, link = fixture
                control.execute("gc", "increase_resolution", "/roms/gc/Example.rvz")
                self.assertEqual(target.read_bytes(), original)
                self.assertTrue(link.is_symlink())
                self.assertEqual([level for _, level in notices], ["warn"])
                self.assertFalse(emusettings.write("gc", 4))
                self.assertEqual(target.read_bytes(), original)

    def test_armsx2_updates_real_section_and_preserves_repeat_keys(self):
        original = (b"; Graphics settings\n[EmuCore/GS]\n"
                    b"upscale_multiplier = 2.0\nAspectRatio = Auto 4:3/3:2\ndeinterlace_mode = 0\n"
                    b"[Other]\nAspectRatio = keep\ndeinterlace_mode = 7\nupscale_multiplier = 12.0\n")
        with self.config_fixture("ps2", original) as (control, notices, home, target, link):
            for action in ("increase_upscaling", "toggle_widescreen", "toggle_interlace"):
                control.execute("ps2", action, "/roms/ps2/Example.iso")
            self.assertEqual(target.read_bytes(), original.replace(b"= 2.0", b"= 3.0")
                             .replace(b"= Auto 4:3/3:2", b"= 16:9").replace(b"deinterlace_mode = 0", b"deinterlace_mode = 1"))
            self.assertTrue(link.is_symlink())
            self.assertFalse((home / ".config/PCSX2").exists())
            self.assertEqual([level for _, level in notices], ["info"] * 3)

    def test_missing_sections_unknown_actions_and_invalid_values_warn_without_writes(self):
        original = b"# Keep the file as-is\n[Settings]\nInternalResolution = custom\n"
        with self.config_fixture("gc", original) as (control, notices, home, target, link):
            control.execute("gamecube", "increase_resolution", "/roms/gc/Example.rvz")
            control.execute("gc", "toggle_fullscreen", "/roms/gc/Example.rvz")
            control.execute("ps2", "screenshot", "/roms/ps2/Example.iso")
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual([level for _, level in notices], ["warn"] * 3)
            self.assertFalse((home / ".config").exists())
            target.write_text("[Other]\nInternalResolution = 2\n")
            control.execute("gc", "increase_resolution", "/roms/gc/Example.rvz")
            self.assertEqual(target.read_text(), "[Other]\nInternalResolution = 2\n")
            target.unlink()
            control.execute("gc", "increase_resolution", "/roms/gc/Example.rvz")
            self.assertFalse(target.exists())
            self.assertTrue(link.is_symlink())
            self.assertEqual([level for _, level in notices], ["warn"] * 5)

    def test_trackpad_uses_the_same_actions_for_canonical_systems_and_aliases(self):
        result = subprocess.run(
            [sys.executable, "-m", "tests.test_emulator_control"],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True,
            text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def exercise_layout():
    from PySide6.QtCore import Property, QObject, QPoint, QTimer, Qt, QUrl, Signal
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtTest import QSignalSpy, QTest

    from armadalive.controls_layout import ControlsLayout

    class CurrentGame(QObject):
        changed = Signal()
        system = ""

        @Property("QVariant", notify=changed)
        def state(self):
            return {"system": self.system, "path": "/roms/Example.rom"}

    app = QGuiApplication([])
    engine = QQmlEngine()
    current, layout, pad = CurrentGame(), ControlsLayout(), trackpad.Trackpad()
    with patch.object(trackpad.os, "open", side_effect=PermissionError):
        control = EmulatorControl()
    for name, value in (("nowPlaying", current), ("layout", layout), ("trackpad", pad), ("emulatorControl", control)):
        engine.rootContext().setContextProperty(name, value)
    path = Path(__file__).resolve().parents[1] / "armadalive" / "qml" / "Trackpad.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    assert component.isReady(), component.errorString()
    page = component.createWithInitialProperties({"width": 620, "height": 540})
    dolphin = ["screenshot", "toggle_widescreen", "increase_resolution", "decrease_resolution", "toggle_aspect"]
    retroarch = ["screenshot", "toggle_cheats", "fast_forward", "save_state", "load_state"]
    armsx2 = ["toggle_widescreen", "increase_upscaling", "decrease_upscaling", "toggle_interlace"]
    for systems, actions in [(("gc", "gamecube", "wii"), dolphin), (("psx", "ps1", "snes"), retroarch),
                             (("ps2",), armsx2), (("steam", ""), [])]:
        for system in systems:
            current.system = system
            current.changed.emit()
            actual = [button["id"] for button in page.property("emulatorButtons").toVariant()]
            assert actual == actions + ["glide"], (system, actual)

    window = QQuickWindow()
    window.resize(620, 540)
    page.setParentItem(window.contentItem())
    window.show()
    assert QTest.qWaitForWindowActive(window)
    current.system = "psx"
    current.changed.emit()
    frame = QSignalSpy(window.afterAnimating)
    window.requestUpdate()
    assert frame.wait(3000), "The Controls page did not render"
    with input_protocol() as calls:
        try:
            notice = QSignalSpy(control.notice)
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(140, 105))
            assert notice.wait(3000), "Shortcut did not complete"
            assert page.property("actionStatus") == "Emulator shortcut sent to the virtual keyboard."
            assert not page.property("actionWarning")
            assert input_events(calls) == [(1, 66, 1), (0, 0, 0), (1, 66, 0), (0, 0, 0)]
            control.execute("psx", "load_state", "/roms/Example.rom")
            assert input_events(calls)[-2:] == [(1, 62, 1), (0, 0, 0)]
            QTimer.singleShot(0, app.quit)
            assert app.exec() == 0
            assert input_events(calls)[-2:] == [(1, 62, 0), (0, 0, 0)]
            assert calls[-2:] == [("ioctl", 0, trackpad.UI_DEV_DESTROY, None), ("close", 0)]
        finally:
            control._close_keyboard()
    window.close()
    del page


if __name__ == "__main__":
    exercise_layout()
