"""Execute emulator-specific hotkey actions."""
import os, re, struct, fcntl
from PySide6.QtCore import QObject, Slot, Signal

# from trackpad.py: uinput event codes
EV_KEY = 1
EV_SYN = 0
BTN_LEFT = 0x110
KEY_F2 = 60
KEY_F4 = 62
KEY_C = 46
KEY_SPACE = 57
KEY_F1 = 59

EVENT = struct.Struct("@llHHi")

class EmulatorControl(QObject):
    """Execute hotkey actions for different emulators."""
    notice = Signal(str, str)  # message, type

    def __init__(self):
        super().__init__()
        self._current_system = None
        self._keyboard = None
        self._init_keyboard()

    def _init_keyboard(self):
        """Initialize virtual keyboard device."""
        try:
            self._keyboard = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            # setup keyboard device
            fcntl.ioctl(self._keyboard, 0x40045564, EV_KEY)  # UI_SET_EVBIT
            for key in (KEY_F2, KEY_F4, KEY_C, KEY_SPACE):
                fcntl.ioctl(self._keyboard, 0x40045565, key)  # UI_SET_KEYBIT
        except Exception:
            self._keyboard = None

    @Slot(str, str, str)
    def execute(self, system, action_id, game_path=""):
        """Execute a hotkey action."""
        if system in ("snes", "nes", "genesis", "n64", "ps1"):
            self._retroarch_action(action_id)
        elif system in ("gamecube", "wii"):
            self._dolphin_action(action_id, game_path)
        elif system == "ps2":
            self._armsx2_action(action_id, game_path)

    def _send_key(self, keycode):
        """Send keyboard key via uinput."""
        if not self._keyboard:
            return False
        try:
            os.write(self._keyboard, EVENT.pack(0, 0, EV_KEY, keycode, 1))  # press
            os.write(self._keyboard, EVENT.pack(0, 0, EV_SYN, 0, 0))        # sync
            os.write(self._keyboard, EVENT.pack(0, 0, EV_KEY, keycode, 0))  # release
            os.write(self._keyboard, EVENT.pack(0, 0, EV_SYN, 0, 0))        # sync
            return True
        except Exception:
            return False

    def _retroarch_action(self, action_id):
        """RetroArch actions: send hotkeys to RetroArch."""
        # Note: these assume RetroArch hotkeys are configured; adjust keycodes if your hotkeys differ
        actions = {
            "screenshot": (KEY_F1, "📸 Screenshot saved"),
            "save_state": (KEY_F2, "💾 State saved"),
            "load_state": (KEY_F4, "📂 State loaded"),
            "toggle_cheats": (KEY_C, "🎮 Cheats toggled"),
            "fast_forward": (KEY_SPACE, "⏩ Fast forward toggled"),
        }
        if action_id in actions:
            keycode, msg = actions[action_id]
            if self._send_key(keycode):
                self.notice.emit(msg, "info")
            else:
                self.notice.emit(f"⚠️ {msg} (uinput failed)", "warn")

    def _dolphin_action(self, action_id, game_path=""):
        """Dolphin actions: modify GameSettings.ini."""
        if action_id == "screenshot":
            if self._send_key(KEY_F1):
                self.notice.emit("📸 Screenshot saved", "info")
            return

        if not game_path:
            self.notice.emit("⚠️ No game running", "warn")
            return

        # Get Dolphin game ID from game path (e.g. /roms/gamecube/zelda.gcm -> ZELDA)
        game_id = os.path.splitext(os.path.basename(game_path))[0].upper()[:6]
        config_dir = os.path.expanduser("~/.config/dolphin-emu/GameSettings/")
        config_file = os.path.join(config_dir, f"{game_id}.ini")

        try:
            os.makedirs(config_dir, exist_ok=True)
            if not os.path.exists(config_file):
                open(config_file, 'a').close()

            # Read current settings
            settings = {}
            if os.path.exists(config_file):
                for line in open(config_file):
                    if '=' in line:
                        k, v = line.strip().split('=', 1)
                        settings[k.strip()] = v.strip()

            # Modify settings
            if action_id == "toggle_widescreen":
                current = settings.get("Aspect Ratio", "0")
                settings["Aspect Ratio"] = "3" if current != "3" else "0"
                self.notice.emit("📐 Widescreen toggled", "info")
            elif action_id == "increase_resolution":
                # Internal resolution: 1=1x, 2=2x, etc.
                current = int(settings.get("InternalResolution", "1"))
                settings["InternalResolution"] = str(min(current + 1, 5))
                self.notice.emit("⬆️ Resolution increased", "info")
            elif action_id == "decrease_resolution":
                current = int(settings.get("InternalResolution", "1"))
                settings["InternalResolution"] = str(max(current - 1, 1))
                self.notice.emit("⬇️ Resolution decreased", "info")

            # Write back
            with open(config_file, 'w') as f:
                for k, v in settings.items():
                    f.write(f"{k} = {v}\n")
        except Exception as e:
            self.notice.emit(f"⚠️ Config error: {str(e)[:30]}", "warn")

    def _armsx2_action(self, action_id, game_path=""):
        """ARMSX2 actions: modify inis."""
        if action_id == "screenshot":
            if self._send_key(KEY_F1):
                self.notice.emit("📸 Screenshot saved", "info")
            return

        if not game_path:
            self.notice.emit("⚠️ No game running", "warn")
            return

        config_file = os.path.expanduser("~/.config/PCSX2/inis/PCSX2_vm.ini")

        try:
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            if not os.path.exists(config_file):
                open(config_file, 'a').close()

            # Read current settings
            settings = {}
            if os.path.exists(config_file):
                for line in open(config_file):
                    if '=' in line and not line.startswith('['):
                        k, v = line.strip().split('=', 1)
                        settings[k.strip()] = v.strip()

            # Modify settings
            if action_id == "toggle_widescreen":
                current = settings.get("widescreen", "0")
                settings["widescreen"] = "0" if current != "0" else "1"
                self.notice.emit("📐 Widescreen toggled", "info")
            elif action_id == "increase_upscaling":
                current = int(settings.get("upscale_multiplier", "1"))
                settings["upscale_multiplier"] = str(min(current + 1, 5))
                self.notice.emit("⬆️ Upscaling increased", "info")
            elif action_id == "decrease_upscaling":
                current = int(settings.get("upscale_multiplier", "1"))
                settings["upscale_multiplier"] = str(max(current - 1, 1))
                self.notice.emit("⬇️ Upscaling decreased", "info")
            elif action_id == "toggle_interlace":
                current = settings.get("deinterlace", "0")
                settings["deinterlace"] = "0" if current != "0" else "1"
                self.notice.emit("🔄 Interlace toggled", "info")

            # Write back
            with open(config_file, 'w') as f:
                for k, v in settings.items():
                    f.write(f"{k} = {v}\n")
        except Exception as e:
            self.notice.emit(f"⚠️ Config error: {str(e)[:30]}", "warn")
