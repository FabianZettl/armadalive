"""Emulator-specific control layouts and hotkeys."""
from PySide6.QtCore import QObject, Slot, Signal


class ControlsLayout(QObject):
    """Provides hotkey buttons based on the running emulator/system."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._current_system = None

    def layout_for(self, system):
        """Get hotkeys for a given system."""
        if not system:
            return {"trackpad": True, "hotkeys": []}

        layouts = {
            "snes": {"trackpad": False, "hotkeys": self._retroarch_hotkeys()},
            "genesis": {"trackpad": False, "hotkeys": self._retroarch_hotkeys()},
            "n64": {"trackpad": False, "hotkeys": self._retroarch_hotkeys()},
            "nes": {"trackpad": False, "hotkeys": self._retroarch_hotkeys()},
            "ps1": {"trackpad": False, "hotkeys": self._retroarch_hotkeys()},
            "ps2": {"trackpad": True, "hotkeys": self._armsx2_hotkeys()},
            "gamecube": {"trackpad": True, "hotkeys": self._dolphin_hotkeys()},
            "wii": {"trackpad": True, "hotkeys": self._dolphin_hotkeys()},
            "steam": {"trackpad": True, "hotkeys": []},
        }
        return layouts.get(system, {"trackpad": True, "hotkeys": []})

    def _retroarch_hotkeys(self):
        """RetroArch hotkeys: save/load state, etc."""
        return [
            {"id": "save_state", "label": "🔒 Save", "icon": ""},
            {"id": "load_state", "label": "🔓 Load", "icon": ""},
            {"id": "toggle_cheats", "label": "🎮 Cheats", "icon": ""},
            {"id": "fast_forward", "label": "⏩ Fast", "icon": ""},
        ]

    def _dolphin_hotkeys(self):
        """Dolphin hotkeys: widescreen, resolution, etc."""
        return [
            {"id": "toggle_widescreen", "label": "📐 Wide", "icon": ""},
            {"id": "increase_resolution", "label": "⬆️ Res", "icon": ""},
            {"id": "decrease_resolution", "label": "⬇️ Res", "icon": ""},
            {"id": "toggle_fullscreen", "label": "🖥️ Full", "icon": ""},
        ]

    def _armsx2_hotkeys(self):
        """ARMSX2 hotkeys: upscaling, widescreen, etc."""
        return [
            {"id": "toggle_widescreen", "label": "📐 Wide", "icon": ""},
            {"id": "increase_upscaling", "label": "⬆️ Scale", "icon": ""},
            {"id": "decrease_upscaling", "label": "⬇️ Scale", "icon": ""},
            {"id": "toggle_interlace", "label": "🔄 Interlace", "icon": ""},
        ]
