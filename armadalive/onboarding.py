"""Helpers for the first-run setup: opening ES-DE for the user."""
import os, subprocess
from PySide6.QtCore import Property, QObject, Slot

from . import esdelib


class Onboarding(QObject):
    @Property(bool, constant=True)
    def esdeFound(self):
        return os.path.exists(esdelib.APPIMAGE)

    @Slot()
    def openEsde(self):
        """Starts ES-DE here (the bottom screen) so its settings can be changed with touch; our own Qt settings must not leak into it."""
        if os.path.exists(esdelib.APPIMAGE):
            env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "QT_QUICK_CONTROLS_STYLE")}
            subprocess.Popen([esdelib.APPIMAGE], env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
