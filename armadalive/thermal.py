"""A popup when the device gets hot (Settings: 80, 85 or 90 °C, or off), at most once every five minutes."""
import time
from PySide6.QtCore import QObject, Signal

REARM = 5       # degrees below the limit before the next warning is possible
COOLDOWN = 300  # seconds


class Thermal(QObject):
    alert = Signal(int, str)   # temperature and the power profile that is running

    def __init__(self, system, ui):
        super().__init__()
        self._ui, self._armed, self._last = ui, True, -COOLDOWN
        system.changed.connect(lambda: self.check(system.stats.get("temp", 0), system.stats.get("profile", ""), time.monotonic()))

    def check(self, temp, profile, now):
        limit = self._ui.state.get("heat", 85)
        if not limit:
            return
        if temp <= limit - REARM:
            self._armed = True
        elif temp >= limit and self._armed and now - self._last >= COOLDOWN:
            self._armed, self._last = False, now
            self.alert.emit(round(temp), profile)
