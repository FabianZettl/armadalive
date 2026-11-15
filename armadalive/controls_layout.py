"""Emulator-specific actions for the Controls page."""
from PySide6.QtCore import QObject, Slot


def canonical_system(system):
    """Use the ES-DE identifiers for GameCube and PlayStation."""
    return {"gamecube": "gc", "ps1": "psx"}.get(system, system)


def emulator_family(system):
    system = canonical_system(system)
    if system in ("snes", "nes", "genesis", "n64", "psx"):
        return "retroarch"
    if system in ("gc", "wii"):
        return "dolphin"
    if system == "ps2":
        return "armsx2"
    return ""


_ACTIONS = {
    "retroarch": (
        ("screenshot", "📸 Shot"),
        ("toggle_cheats", "🎮 Cheats"),
        ("fast_forward", "⏩ Fast"),
        ("save_state", "💾 Save"),
        ("load_state", "📂 Load"),
    ),
    "dolphin": (
        ("screenshot", "📸 Shot"),
        ("toggle_widescreen", "📐 Wide"),
        ("increase_resolution", "⬆️ Res"),
        ("decrease_resolution", "⬇️ Res"),
        ("toggle_aspect", "🔄 Ratio"),
    ),
    "armsx2": (
        ("toggle_widescreen", "📐 Wide"),
        ("increase_upscaling", "⬆️ Scale"),
        ("decrease_upscaling", "⬇️ Scale"),
        ("toggle_interlace", "🔄 Interlace"),
    ),
}


class ControlsLayout(QObject):
    """Provides hotkey buttons based on the emulator system."""

    @Slot(str, result="QVariantMap")
    def layout_for(self, system):
        family = emulator_family(system)
        return {
            "trackpad": family != "retroarch",
            "hotkeys": [{"id": action, "label": label, "icon": ""} for action, label in _ACTIONS.get(family, ())],
        }
