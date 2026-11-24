"""Device-specific configuration for AYN Thor and Retroid Pocket Duo.
https://github.com/FabianZettl/armadalive
"""
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
        dsi_bottom="/sys/class/backlight/ae94000.dsi.0/brightness",  # bottom screen
        dsi_top="/sys/class/backlight/ae96000.dsi.0/brightness",  # top screen
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
    """Detect device: 'thor' | 'duo'. Falls back to 'thor' if device cannot be detected."""
    # Priority 1: Check for Thor's Plasma bottom session (most reliable)
    run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if os.path.isdir(run):
        if os.path.exists(f"{run}/armada-plasma-bottom") or os.path.exists(f"{run}/armada-bottom-env"):
            return "thor"

    # Priority 2: Check device-tree for device markers (most reliable across boots)
    try:
        with open("/sys/firmware/devicetree/base/compatible", "r") as f:
            compat = f.read().lower()
            if "retroid" in compat or "duo" in compat:
                return "duo"
            if "ayn" in compat or "thor" in compat:
                return "thor"
    except (OSError, FileNotFoundError):
        pass

    # Priority 3: Check for Wayland without Plasma (Duo pattern)
    try:
        for sock in os.listdir(run) if os.path.isdir(run) else []:
            if sock.startswith("wayland-") and "armada-plasma" not in sock:
                return "duo"
    except (OSError, FileNotFoundError):
        pass

    # Fallback: assume Thor (conservative, Thor is the original target device)
    return "thor"


def get_profile() -> DeviceProfile:
    """Get the current device's profile. Raises ValueError if device cannot be detected."""
    device = detect_device()
    return PROFILES[device]
