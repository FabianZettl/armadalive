"""Internal render resolution for the emulators that keep it in a plain config file, changed just before a game starts."""
import os, re, stat

from . import persistence

HOME = os.path.expanduser("~")
PPSSPP = (HOME + "/.var/app/org.ppsspp.PPSSPP/config/ppsspp/PSP/SYSTEM/ppsspp.ini", "Graphics", "InternalResolution", "{}")
DOLPHIN = (HOME + "/.var/app/org.DolphinEmu.dolphin-emu/config/dolphin-emu/GFX.ini", "Settings", "InternalResolution", "{}")
PCSX2 = (HOME + "/.config/ARMSX2/inis/PCSX2.ini", "EmuCore/GS", "upscale_multiplier", "{}.0")
# ES-DE system -> (file, section, key, value format); Azahar is left out, its qt-config repeats every key with a "\default" flag
SPECS = dict(psp=PPSSPP, gc=DOLPHIN, wii=DOLPHIN, ps2=PCSX2)
MAX = 5


def _is_dolphin_setting(section, key):
    # Match the supported GFX.ini options after the caller resolves a symlink
    # or derives another path for the same settings.
    return section == DOLPHIN[1] and key in (DOLPHIN[2], "wideScreenHack", "AspectRatio")


def _find(lines, section, key, dolphin):
    """Find an unambiguous section and option in the selected dialect."""
    head, option = None, None
    active = False
    header = f"[{section.lower() if dolphin else section}]"
    flags = re.IGNORECASE | re.ASCII if dolphin else 0
    assignment = re.compile(rf"[ \t]*{re.escape(key)}[ \t]*=", flags)
    for i, line in enumerate(lines):
        text = line.strip()
        if dolphin:
            content = line.removeprefix("\ufeff") if i == 0 else line
            text = content.lstrip(" \t")
            if text.startswith("["):
                end = text.find("]")
                if text != content or end == -1:
                    return None, None
                text = text[:end + 1].lower()
        if text.startswith("["):
            active = text == header
            if active:
                if head is not None:
                    return None, None
                head = i
        elif active and assignment.match(line):
            if option is not None:
                return None, None
            option = i
    return option, head


def _read_lines(path):
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as stream:
        return stream.read().splitlines(keepends=True), stat.S_IMODE(os.fstat(stream.fileno()).st_mode)


def _option(line, dolphin):
    prefix, value, newline = re.fullmatch(r"(.*?=[ \t]*)(.*?)(\r\n|\r|\n)?", line).groups()
    newline = newline or ""
    if dolphin:
        # Dolphin stores the whole right-hand side and strips enclosing double
        # quotes. A comment marker here makes these numeric/bool options invalid.
        unpadded = value.rstrip(" \t")
        if any(marker in unpadded for marker in "#;"):
            return None
        suffix = value[len(unpadded):] + newline
        if len(unpadded) >= 2 and unpadded[0] == unpadded[-1] == '"':
            return prefix + '"', unpadded[1:-1], '"' + suffix
        return prefix, unpadded, suffix
    tokens = re.finditer(r'''"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|(?:^|[ \t])[#;]''', value)
    comment = next((match.start() for match in tokens if match[0][-1] in "#;"), len(value))
    end = len(value[:comment].rstrip(" \t"))
    return prefix, value[:end], value[end:] + newline


def read_setting(spec):
    """Read an emulator option's value, or None if it is unavailable."""
    path, section, key, _ = spec
    try:
        lines, _ = _read_lines(path)
    except OSError:
        return None
    dolphin = _is_dolphin_setting(section, key)
    i, _ = _find(lines, section, key, dolphin)
    option = _option(lines[i], dolphin) if i is not None else None
    return option[1] if option is not None else None


def update_setting(spec, transform):
    """Update an existing file and section, replacing or removing one option.

    The transform receives its current text (None if absent), and returns the
    new text (None to remove it). Its errors propagate to the caller.
    """
    path, section, key, _ = spec
    try:
        path = os.path.realpath(path, strict=True)
        lines, mode = _read_lines(path)
    except OSError:
        return False
    dolphin = _is_dolphin_setting(section, key)
    i, head = _find(lines, section, key, dolphin)
    option = _option(lines[i], dolphin) if i is not None else ("", None, "")
    if head is None or option is None:
        return False
    prefix, old, suffix = option
    new = transform(old)
    if new == old:
        return True
    if new is not None and any(char in new for char in "\r\n"):
        raise ValueError("An emulator option must fit on one line")
    if dolphin and new is not None and any(marker in new for marker in "#;"):
        return False
    if i is None:
        newline = next((match[0] for line in lines if (match := re.search(r"(?:\r\n|\r|\n)$", line))), "\n")
        if not lines[head].endswith(("\r", "\n")):
            lines[head] += newline
            newline = ""
        lines.insert(head + 1, f"{key} = {new}{newline}")
    elif new is None:
        del lines[i]
    else:
        if suffix.startswith(("#", ";")):
            suffix = " " + suffix
        lines[i] = prefix + new + suffix
    try:
        persistence.write_bytes(path, "".join(lines).encode("utf-8", "surrogateescape"), mode=mode)
    except OSError:
        return False
    return True


def read(system):
    spec = SPECS.get(system)
    return read_setting(spec) if spec else None


def write(system, value):
    """Set the render resolution when the emulator file and section exist."""
    spec = SPECS.get(system)
    if spec is None:
        return False
    return update_setting(spec, lambda _: spec[3].format(value) if str(value).isdigit() else str(value))
