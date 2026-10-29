"""The AYN button, delivered by InputPlumber over D-Bus once scripts/ayn-button.sh has been run (needs root, once)."""
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtDBus import QDBusConnection


class AynButton(QObject):
    pressed = Signal()

    def __init__(self):
        super().__init__()
        self.connected = QDBusConnection.systemBus().connect(
            "org.shadowblip.InputPlumber", "", "org.shadowblip.Input.DBusDevice", "InputEvent",
            self, "1inputEvent(QString,double)")  # "1" is what Qt's SLOT() macro prepends

    @Slot(str, float)
    def inputEvent(self, action, value):
        if action == "ui_quick2" and value > 0.5:  # on press, not release
            self.pressed.emit()
