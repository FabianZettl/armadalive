"""Send emulator hotkeys and update supported emulator configuration options."""
import math

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Qt, Signal, Slot

from . import emusettings
from .controls_layout import canonical_system, emulator_family
from .trackpad import EV_KEY, KEYS, Virtual

# Defaults from RetroArch's retroarch.cfg and Dolphin's HotkeyManager.cpp.
_HOTKEYS = {
    "retroarch": {
        "screenshot": 66,       # F8
        "save_state": 60,       # F2
        "load_state": 62,       # F4
        "toggle_cheats": 22,    # U
        "fast_forward": KEYS["space"],
    },
    "dolphin": {"screenshot": 67},  # F9
}
_KEYS = tuple(sorted({key for actions in _HOTKEYS.values() for key in actions.values()}))
# Userspace discovers a newly created uinput device asynchronously. Then hold
# the key over several polls so keyboard-state readers can observe it.
_KEYBOARD_DISCOVERY_MS = 1000
_KEY_HOLD_MS = 80


def _dolphin_widescreen(current):
    if current is None or current.lower() in ("false", "0"):
        return "True"
    if current.lower() in ("true", "1"):
        return "False"
    raise ValueError("Unrecognized Dolphin widescreen value.")


def _dolphin_aspect(current):
    # Dolphin's Rotate Aspect Ratio hotkey cycles Auto, Force Wide, Force Standard, Stretch.
    value = 0 if current is None else int(current)
    if not 0 <= value <= 6:
        raise ValueError("Unrecognized Dolphin aspect ratio.")
    return str((value + 1) % 4)


def _armsx2_aspect(current):
    return "Auto 4:3/3:2" if current == "16:9" else "16:9"


def _armsx2_interlace(current):
    # The ARMSX2 GSInterlaceMode enum starts with Automatic (0) and Off (1).
    if current in (None, "0"):
        return "1"
    if current == "1":
        return "0"
    raise ValueError("Choose Automatic or Off in ARMSX2 before using this toggle.")


_CONFIG_ACTIONS = {
    "dolphin": {
        "toggle_widescreen": ("wideScreenHack", _dolphin_widescreen),
        "toggle_aspect": ("AspectRatio", _dolphin_aspect),
    },
    "armsx2": {
        "toggle_widescreen": ("AspectRatio", _armsx2_aspect),
        "toggle_interlace": ("deinterlace_mode", _armsx2_interlace),
    },
}
_RESOLUTION_ACTIONS = {
    "dolphin": {"increase_resolution": 1, "decrease_resolution": -1},
    "armsx2": {"increase_upscaling": 1, "decrease_upscaling": -1},
}


def _resolution_step(current, direction, fmt, fractional):
    try:
        value = 1 if current is None else (float(current) if fractional else int(current))
        next_value = math.floor(value) + 1 if direction > 0 else math.ceil(value) - 1
    except (ValueError, OverflowError):
        raise ValueError("Unrecognized emulator resolution.") from None
    if value < 0 or not 1 <= next_value <= emusettings.MAX:
        raise ValueError(f"Controls can set resolutions from 1× to {emusettings.MAX}×.")
    return fmt.format(next_value)


class EmulatorControl(QObject):
    """Execute the shortcuts available on the Controls page."""
    notice = Signal(str, str)  # message, type

    def __init__(self):
        super().__init__()
        self._keyboard = None
        self._ready = False
        self._key = None
        self._key_timer = QTimer(self)
        self._key_timer.setSingleShot(True)
        self._key_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._key_timer.timeout.connect(self._advance_keyboard)
        self._open_keyboard()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._close_keyboard)

    def _open_keyboard(self):
        try:
            self._keyboard = Virtual("ArmadaLive Emulator Keys", keys=_KEYS)
        except OSError:
            return False
        self._key_timer.start(_KEYBOARD_DISCOVERY_MS)
        return True

    def _close_keyboard(self):
        self._key_timer.stop()
        if self._keyboard is not None:
            if self._ready and self._key is not None:
                try:
                    self._write_key(0)
                except OSError:
                    pass
            self._keyboard.close()
        self._keyboard = None
        self._ready = False
        self._key = None

    def _write_key(self, value):
        self._keyboard.emit(EV_KEY, self._key, value)
        self._keyboard.sync()

    def _input_failed(self):
        self._close_keyboard()
        self.notice.emit("Could not send the emulator shortcut through /dev/uinput.", "warn")

    def _press_key(self):
        try:
            self._write_key(1)
        except OSError:
            self._input_failed()
        else:
            self._key_timer.start(_KEY_HOLD_MS)

    def _advance_keyboard(self):
        if not self._ready:
            self._ready = True
            if self._key is not None:
                self._press_key()
            return

        try:
            self._write_key(0)
        except OSError:
            self._input_failed()
        else:
            self._key = None
            self.notice.emit("Emulator shortcut sent to the virtual keyboard.", "info")

    def _send_key(self, key):
        if self._key is not None:
            self.notice.emit("An emulator shortcut is already in progress.", "warn")
            return
        if self._keyboard is None and not self._open_keyboard():
            self._input_failed()
            return

        self._key = key
        if self._ready:
            self._press_key()

    @Slot(str, str, str)
    def execute(self, system, action_id, game_path=""):
        family = emulator_family(system)
        key = _HOTKEYS.get(family, {}).get(action_id)
        if key is not None:
            self._send_key(key)
            return

        change = _CONFIG_ACTIONS.get(family, {}).get(action_id)
        direction = _RESOLUTION_ACTIONS.get(family, {}).get(action_id)
        if change is None and direction is None:
            if family == "armsx2" and action_id == "screenshot":
                self.notice.emit("ARMSX2 does not provide a supported screenshot shortcut.", "warn")
            else:
                self.notice.emit("Unsupported emulator action.", "warn")
            return
        if not game_path:
            self.notice.emit("No game selected.", "warn")
            return

        path, section, option, fmt = emusettings.SPECS[canonical_system(system)]
        if change is None:
            def transform(current):
                return _resolution_step(current, direction, fmt, family == "armsx2")
        else:
            option, transform = change
        try:
            updated = emusettings.update_setting((path, section, option, fmt), transform)
        except ValueError as error:
            self.notice.emit(str(error), "warn")
            return
        if updated:
            self.notice.emit("Global emulator setting saved on disk. A running game may not reload it.", "info")
        else:
            self.notice.emit("Could not update the emulator configuration file.", "warn")
