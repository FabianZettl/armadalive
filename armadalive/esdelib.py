"""ES-DE's systems and games, read from its own files, and the launch command ES-DE itself would build for a game.

ES-DE cannot start one game from the command line, so the command is rebuilt here from its system definitions (the bundled
ones inside the AppImage, replaced by the user's `custom_systems`) and its find rules."""
import glob, os, re, shlex, shutil, subprocess, tempfile
import xml.etree.ElementTree as ET

from .nowplaying import ES, GAMELISTS, MEDIA, _gamelist, _rom_dir, rom_key, rom_relative

APPIMAGE = os.path.expanduser("~/Applications/ES-DE.AppImage")
CACHE = os.path.expanduser("~/.cache/armadalive/esde")
INSIDE = "usr/share/es-de/resources/systems/linux"
DROP = ("%INJECT%", "%ENABLESHORTCUTS%", "%RUNINBACKGROUND%", "%HIDEWINDOW%")   # flags for ES-DE itself, not part of the command
COVERS = ("covers", "3dboxes", "miximages", "screenshots")

_cached_definitions = {}


def _bundled():
    """The definition files of the installed ES-DE, unpacked once per AppImage version into the cache."""
    try:
        stamp = str(os.stat(APPIMAGE).st_mtime_ns)
    except OSError:
        return CACHE if os.path.exists(CACHE + "/es_systems.xml") else ""
    try:
        fresh = os.path.exists(CACHE + "/es_systems.xml") and open(CACHE + "/stamp").read() == stamp
    except OSError:
        fresh = False
    if not fresh:
        tmp = tempfile.mkdtemp(prefix="armadalive-esde-")
        try:
            subprocess.run([APPIMAGE, "--appimage-extract", INSIDE + "/*"], cwd=tmp, timeout=120, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.makedirs(CACHE, exist_ok=True)
            for f in ("es_systems.xml", "es_find_rules.xml"):
                shutil.copy(f"{tmp}/squashfs-root/{INSIDE}/{f}", f"{CACHE}/{f}")
            open(CACHE + "/stamp", "w").write(stamp)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return CACHE if os.path.exists(CACHE + "/es_systems.xml") else ""


def _parse(path):
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return ET.Element("none")


def systems():
    """{name: {fullname, extensions, commands: [(label, template)]}}; the user's custom_systems replace bundled ones by name."""
    return _system_definitions(ES, _bundled())


def cached_systems(es):
    """Read installed definitions without extracting an AppImage during lookup."""
    def version(path):
        try:
            info = os.stat(path)
            return info.st_ino, info.st_mtime_ns, info.st_size
        except OSError:
            return None

    key = es, CACHE
    stamp = (version(CACHE + "/es_systems.xml"), version(es + "/custom_systems/es_systems.xml"))
    cached = _cached_definitions.get(key)
    if cached is None or cached[0] != stamp:
        cached = _cached_definitions[key] = stamp, _system_definitions(es, CACHE)
    return cached[1]


def _system_definitions(es, bundled):
    out = {}
    paths = [bundled + "/es_systems.xml"] if bundled else []
    for path in paths + [es + "/custom_systems/es_systems.xml"]:
        root = _parse(path)
        for s in root.iter("system"):
            name = s.findtext("name")
            if name:
                out[name] = dict(fullname=s.findtext("fullname") or name, path=(s.findtext("path") or "").strip(), extensions=set((s.findtext("extension") or "").lower().split()),
                                 commands=[(c.get("label") or "", (c.text or "").strip()) for c in s.findall("command")])
    return out


def system_folder(system, rom_dir, definition=None):
    """The system's configured ROM folder, including custom paths outside the default root."""
    path = (definition or {}).get("path") or ""
    return os.path.expanduser(path.replace("%ROMPATH%", rom_dir.rstrip("/"))) or os.path.join(rom_dir, system)


def _rules():
    out = {}
    for root in (_parse(_bundled() + "/es_find_rules.xml"), _parse(ES + "/custom_systems/es_find_rules.xml")):
        for tag in ("emulator", "core"):
            for e in root.iter(tag):
                out[(tag, e.get("name"))] = [(r.get("type"), [(x.text or "").strip() for x in r.findall("entry")]) for r in e.findall("rule")]
    return out


def _find(rules, tag, name, member=""):
    for kind, entries in rules.get((tag, name), []):
        for entry in entries:
            if kind == "systempath" and tag == "emulator":
                hit = shutil.which(entry)
            elif kind in ("staticpath", "corepath"):
                hits = [h for h in sorted(glob.glob(os.path.expanduser(entry))) if not member or os.path.exists(os.path.join(h, member))]
                hit = hits[0] if hits else None
            else:
                hit = None
            if hit:
                return hit
    return None


def command(system, rom, defs=None, rules=None, label=""):
    """The command words for this ROM as ES-DE would run it (the chosen alternative emulator, else the system's first command);
    None if it needs something this cannot place, or an emulator that is not installed."""
    defs = defs or systems()
    rules = rules or _rules()
    s = defs.get(system)
    if not s or not s["commands"]:
        return None
    rom_dir = _rom_dir()
    folder = os.path.abspath(system_folder(system, rom_dir, s))
    label = label or _alternative(system, rom, folder)
    template = next((t for lab, t in s["commands"] if lab == label), s["commands"][0][1])
    base, parent = os.path.basename(rom), os.path.dirname(rom)
    subs = {"%ROM%": rom, "%ROMRAW%": rom, "%FILENAME%": base, "%BASENAME%": os.path.splitext(base)[0], "%GAMEDIR%": parent,
            "%GAMEDIRRAW%": parent, "%ROMPATH%": rom_dir}
    words = []
    try:
        pieces = shlex.split(template)
    except ValueError:
        return None
    for w in pieces:
        if w in DROP:
            continue
        for key, value in subs.items():
            w = w.replace(key, value)
        for core in re.findall(r"%CORE_([A-Z0-9_-]+)%/?([^\s%]*)", w):
            where = _find(rules, "core", core[0], core[1])
            w = w.replace(f"%CORE_{core[0]}%", where or "%MISSING%")
        for emu in re.findall(r"%EMULATOR_([A-Z0-9_-]+)%", w):
            where = _find(rules, "emulator", emu)
            w = w.replace(f"%EMULATOR_{emu}%", where or "%MISSING%")
        words.append(w)
    return None if any("%" in w and re.search(r"%[A-Z_0-9-]+%", w) for w in words) else words


def _alternative(system, rom, folder):
    """The emulator ES-DE was told to use: for this game in its gamelist, else for the whole system."""
    root = _parse(f"{GAMELISTS}/{system}/gamelist.xml")
    relative = rom_relative(system, rom, folder)
    if relative:
        for game in root.iter("game"):
            if rom_relative(system, game.findtext("path") or "", folder) == relative and game.findtext("altemulator"):
                return game.findtext("altemulator")
    return root.findtext("alternativeEmulator/label") or ""


def _cover(system, path):
    base = glob.escape(os.path.splitext(os.path.basename(path))[0])
    for kind in COVERS:
        hit = sorted(glob.glob(f"{glob.escape(MEDIA)}/{glob.escape(system)}/{kind}/{base}.*"))
        if hit:
            return hit[0]
    return ""


def rom_files(folder, extensions, *, onerror=None, stems=None):
    """Paths of the system's ROM files, including entries hidden by ES-DE."""
    for here, dirs, files in os.walk(folder, onerror=onerror):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("media", "images", "videos", "manuals")]
        for filename in files:
            stem, extension = os.path.splitext(filename)
            if (not filename.startswith(".") and (extensions is None or extension.lower() in extensions)
                    and (stems is None or stem in stems)):
                yield os.path.relpath(os.path.join(here, filename), folder)


def games(definitions=None):
    """{system: [{id: "esde:<system>/<path under the system folder>", name, cover (file path), rom}]} for systems that have games."""
    root, out = _rom_dir(), {}
    definitions = systems() if definitions is None else definitions
    for name, s in definitions.items():
        # the folder ES-DE itself uses: its <path> (with %ROMPATH% and ~ expanded), else <ROM directory>/<system>
        folder = os.path.abspath(system_folder(name, root, s))
        if not os.path.isdir(folder):
            continue
        entries, _ = _gamelist(name, folder, GAMELISTS)
        found = []
        for relative in rom_files(folder, s["extensions"]):
            entry = entries.get(relative)
            if entry is not None and (entry.findtext("hidden") or "").lower() == "true":
                continue
            stem = os.path.splitext(os.path.basename(relative))[0]
            title = entry.findtext("name") if entry is not None else ""
            path = os.path.join(folder, relative)
            found.append(dict(id=rom_key(name, relative), name=title or stem,
                              cover=_cover(name, path), rom=path))
        if found:
            out[name] = sorted(found, key=lambda g: g["name"].lower())
    return out
