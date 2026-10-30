"""Which device this is: the device tree names it, memory tells the variants apart (Pro 12 GB, Max 16 GB; a guess, not a label on the box)."""
import os

DT = "/proc/device-tree"
MEMINFO = "/proc/meminfo"


def _dt(name):
    try:
        return open(f"{DT}/{name}", "rb").read().decode(errors="replace").strip("\0 \n")
    except OSError:
        return ""


def _ram_gb():
    try:
        for line in open(MEMINFO):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1048576
    except (OSError, ValueError):
        pass
    return 0.0


def tier(ram_gb):
    """Usable memory is a bit under the fitted size."""
    return "unknown" if ram_gb <= 0 else "base" if ram_gb <= 9 else "pro" if ram_gb <= 13.5 else "max"


def info():
    compat = _dt("compatible").split("\0")
    ram = _ram_gb()
    soc = next((c.split(",")[1].upper() for c in compat if c.startswith("qcom,")), "")
    model = compat[0] if compat and compat[0] else ""
    t = tier(ram) if model.startswith("ayn,thor") and not model.endswith("lite") else "unknown"
    label = _dt("model") or "Unknown device"
    return dict(id=model, name=label + (f" {t.title()}" if t != "unknown" else ""), soc=soc, ram=round(ram, 1), tier=t)
