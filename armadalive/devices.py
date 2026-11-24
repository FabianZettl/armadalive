"""Device-specific configuration for AYN Thor and Retroid Pocket Duo."""
import os
from dataclasses import dataclass


@dataclass
class DeviceProfile:
    """Hardware-specific paths and properties."""
    name: str
    wayland_display: str | None  # None for Duo (no Plasma session)
    dsi_bottom: str  # Path to bottom screen DSI backlight
    dsi_top: str | None  # Path to top screen DSI backlight (None for single-screen devices)
    max_brightness_bottom: int
    max_brightness_top: int | None
    width_bottom: int
    height_bottom: int
    service_name: str  # systemd service name for the app


PROFILES = {
    "thor": DeviceProfile(
        name="AYN Thor",
        wayland_display="armada-plasma-bottom",
        dsi_bottom="/sys/class/backlight/ae96000.dsi.0/brightness",  # DSI-1
        dsi_top="/sys/class/backlight/ae94000.dsi.0/brightness",  # DSI-2
        max_brightness_bottom=4095,
        max_brightness_top=4095,
        width_bottom=1240,
        height_bottom=720,
        service_name="armadalive",
    ),
    "duo": DeviceProfile(
        name="Retroid Pocket Duo",
        wayland_display=None,  # Duo doesn't have Plasma sessions
        dsi_bottom="/sys/class/backlight/ae96000.dsi.0/brightness",  # Needs verification on real device
        dsi_top=None,
        max_brightness_bottom=3445,
        max_brightness_top=None,
        width_bottom=720,
        height_bottom=720,
        service_name="armadalive-duo",
    ),
}


def detect_device() -> str:
    """Detect which device we're running on. Returns profile key: 'thor' or 'duo'."""
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")

    # If we have the Thor's Plasma bottom session, it's definitely a Thor
    if "armada-plasma-bottom" in wayland_display:
        return "thor"

    # Check for Duo-specific files (heuristic: different backlight layout)
    # For now, default to duo if not Thor
    return "duo"


def get_profile() -> DeviceProfile:
    """Get the current device's profile."""
    device = detect_device()
    return PROFILES[device]
