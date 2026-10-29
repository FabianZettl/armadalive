"""The AYN button, delivered by InputPlumber over D-Bus once scripts/ayn-button.sh has been run (needs root, once)."""
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtDBus import QDBusConnection


HOLD_MS = 800


class AynButton(QObject):
    pressed = Signal()
    longPressed = Signal()      # held for HOLD_MS

    def __init__(self):
        super().__init__()
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(HOLD_MS)
        self._hold.timeout.connect(self.longPressed)
        self.connected = QDBusConnection.systemBus().connect(
            "org.shadowblip.InputPlumber", "", "org.shadowblip.Input.DBusDevice", "InputEvent",
            self, "1inputEvent(QString,double)")  # "1" is what Qt's SLOT() macro prepends

    @Slot(str, float)
    def inputEvent(self, action, value):
        if action != "ui_quick2":
            return
        if value > 0.5:  # on press: act at once, and see whether it turns into a hold
            self.pressed.emit()
            self._hold.start()
        else:
            self._hold.stop()
