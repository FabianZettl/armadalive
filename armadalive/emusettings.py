"""Internal render resolution for the emulators that keep it in a plain config file, changed just before a game starts."""
import os, re

HOME = os.path.expanduser("~")
PPSSPP = (HOME + "/.var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM/ppsspp.ini", "Graphics", "InternalResolution", "{}")
DOLPHIN = (HOME + "/.var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu/GFX.ini", "Settings", "InternalResolution", "{}")
PCSX2 = (HOME + "/.config/ARMSX2/inis/PCSX2.ini", "EmuCore/GS", "upscale_multiplier", "{}.0")
# ES-DE system -> (file, section, key, value format); Azahar is left out, its qt-config repeats every key with a "\default" flag
SPECS = dict(psp=PPSSPP, gc=DOLPHIN, wii=DOLPHIN, ps2=PCSX2)
MAX = 5


def _find(lines, section, key):
    """(index of the key line or None, index of the section header or None)"""
    head = None
    for i, line in enumerate(lines):
        if line.strip().startswith("["):
            if head is not None:
                return None, head
            head = i if line.strip() == f"[{section}]" else None
        elif head is not None and re.match(rf"\s*{re.escape(key)}\s*=", line):
            return i, head
    return None, head


def read(system):
    spec = SPECS.get(system)
    try:
        lines = open(spec[0]).read().splitlines()
    except (OSError, TypeError):
        return None
    i, _ = _find(lines, spec[1], spec[2])
    return None if i is None else lines[i].split("=", 1)[1].strip()


def write(system, value):
    """Sets the key if the file and its section exist; never creates either. True when the file now holds the value."""
    spec = SPECS.get(system)
    if not spec:
        return False
    path, section, key, fmt = spec
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return False
    i, head = _find(lines, section, key)
    new = f"{key} = {fmt.format(value) if str(value).isdigit() else value}"
    if i is not None:
        lines[i] = new
    elif head is not None:
        lines.insert(head + 1, new)
    else:
        return False
    with open(path, "w") as f:   # in place: the file may be a symlink into a synced folder
        f.write("\n".join(lines) + "\n")
    return True
